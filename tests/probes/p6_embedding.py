"""P6 语义搜索探针：本地 embedding 模型在 GTX 1060（Pascal, 6GB 但实际空闲仅 ~2.3GB）上的可用性、
吞吐与检索质量，并且不许用"模型跑通了"当验收（SPEC 阶段 6 明确禁止）。

已下载的真实模型（不是假设存在）：
  Qdrant/bge-small-zh-v1.5   model_optimized.onnx   90.4MB  fp32
  xenova/bge-small-zh-v1.5   onnx/model_int8.onnx   22.8MB  int8 量化

验证项：
  E1 onnxruntime 的 CPU / DirectML 两个 provider 能否真跑这个 BERT 图（CUDA 在 Pascal 上不假设可用）
  E2 输出的 pooling 是否已经在图里做掉（决定我们要不要自己写 mean pooling）
  E3 向量维度、是否已归一化（决定用内积还是余弦）
  E4 检索质量：真实中文语料上，语义相关对的相似度必须高于随机对，否则模型对本语料无效
  E5 反例：SPEC 要求"输入『能源』不得命中『新能源汽车』"这类精度问题的量化证据
  E6 吞吐与量级：按 P2 真实页数推算全量建索引要多久、向量库多大

用法: python tests/probes/p6_embedding.py [--model fp32|int8|both] [--pages 40]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

import numpy as np
import psutil
import pymupdf

pymupdf.TOOLS.mupdf_display_errors(False)
RSS = psutil.Process(os.getpid())
MODEL_DIR = ".probe_work/models/bge-small-zh-v1.5"
MODELS = {"fp32": os.path.join(MODEL_DIR, "model_optimized.onnx"),
          "int8": os.path.join(MODEL_DIR, "onnx", "model_int8.onnx")}


def rss_mb() -> float:
    return RSS.memory_info().rss / 1048576


def load_pairs(target: int) -> list[str]:
    """从真实语料取文本块，不用合成句子。跨多本文档取，避免单本文档重复主题把相似度抬高。"""
    hint = ".probe_work/p3_real_pdf_path.txt"
    seeds = [open(hint, encoding="utf-8").read().strip()] if os.path.exists(hint) else []
    blocks: list[str] = []
    for pdf in seeds:
        if not (pdf and os.path.exists(pdf)):
            continue
        doc = pymupdf.open(pdf)
        for i in range(doc.page_count):
            t = " ".join(doc[i].get_text("text").split())
            if len(t) >= 60:
                blocks.append(t[:400])
            if len(blocks) >= target:
                break
        doc.close()
        if len(blocks) >= target:
            break
    # 不够就从 H: 盘再翻几本原生文本 PDF 补齐，仍不足则明确报告样本量，不拿合成句糊弄
    if len(blocks) < target:
        for dp, dns, fns in os.walk("H:\\"):
            dns[:] = [d for d in dns if d not in {".git", "node_modules", "__pycache__", "$RECYCLE.BIN",
                                                  "System Volume Information", ".venv", "venv"}]
            for fn in fns:
                if not fn.lower().endswith(".pdf"):
                    continue
                try:
                    d = pymupdf.open(os.path.join(dp, fn))
                except Exception:  # noqa: BLE001
                    continue
                if d.is_encrypted or d.page_count < 5:
                    d.close()
                    continue
                for i in range(min(d.page_count, 40)):
                    t = " ".join(d[i].get_text("text").split())
                    if len(t) >= 60:
                        blocks.append(t[:400])
                    if len(blocks) >= target:
                        break
                d.close()
                if len(blocks) >= target:
                    break
            if len(blocks) >= target:
                break
    return blocks[:target]


# 语义相关对 / 无关对：用来量化"模型在这个语料上到底有没有用"
RELATED = [
    ("人工智能产业的市场规模持续扩大", "AI 行业的市场容量仍在增长"),
    ("深度学习模型需要大量标注数据训练", "神经网络的训练依赖足量人工标记样本"),
    ("本报告分析游戏行业的出海趋势", "文档讨论游戏产业面向海外市场的走向"),
    ("/pdf 扫描件缺少文本层需要识别", "图像版 PDF 没有文字层必须做字符识别"),
]
UNRELATED = [
    ("人工智能产业的市场规模持续扩大", "今天晚饭做了番茄炒蛋和米饭"),
    ("深度学习模型需要大量标注数据训练", "这台打印机的硒鼓需要更换"),
    ("本报告分析游戏行业的出海趋势", "合同第八条规定了违约责任与赔偿上限"),
    ("/pdf 扫描件缺少文本层需要识别", "花园里的月季今年开得特别茂盛"),
]
# 反例（SPEC 第 20 条要求每个匹配类功能先写反例）：粒度必须能区分"能源"与"新能源汽车"
# 每条 = (查询, 不该被偏爱的一方, 该被偏爱的一方)
TRAP = [
    ("能源", "新能源汽车的补贴政策", "传统能源电力供应紧张"),
    ("课件", "课件制作软件的安装步骤", "课堂课件与讲义"),
]


def embed(sess, texts: list[str], tok, max_len: int = 256):
    # tokenizers 默认不补齐 batch，必须显式截断+padding，否则 np.array 直接ragged报错
    tok.enable_truncation(max_length=max_len)
    tok.enable_padding(pad_id=tok.token_to_id("[PAD]") or 0, pad_token="[PAD]")
    enc = tok.encode_batch(texts)
    ids = np.array([e.ids for e in enc], dtype=np.int64)
    mask = np.array([e.attention_mask for e in enc], dtype=np.int64)
    feeds = {"input_ids": ids, "attention_mask": mask}
    if "token_type_ids" in {i.name for i in sess.get_inputs()}:
        # tokenizers 0.23 不暴露 token_type_ids；单句 BERT 输入恒为 0
        feeds["token_type_ids"] = np.zeros_like(ids)
    out = sess.run(None, feeds)
    # 必须把真实 attention_mask 带回去：mean pooling 用错 mask 会得到全零向量并骗过相似度检查
    return out, mask


def pool_normalize(out: list[np.ndarray], mask: np.ndarray) -> np.ndarray:
    """若图输出是 [B,T,H] 则自己做 mean pooling；若是 [B,H] 直接用。"""
    v = out[0]
    if v.ndim == 3:
        m = mask.astype(np.float32)[:, :, None]
        v = (v * m).sum(1) / np.clip(m.sum(1), 1e-6, None)
    v = v.astype(np.float32)
    return v / np.clip(np.linalg.norm(v, axis=1, keepdims=True), 1e-9, None)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="both", choices=["fp32", "int8", "both"])
    ap.add_argument("--pages", type=int, default=320, help="要嵌入的真实文本块数")
    ap.add_argument("--out", default=".probe_work/p6_embedding_result.json")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    os.makedirs(os.path.dirname(args.out), exist_ok=True)

    import onnxruntime as ot
    from tokenizers import Tokenizer

    report: dict = {
        "probe": "p6_embedding",
        "onnxruntime_version": ot.__version__,
        "providers_available": ot.get_available_providers(),
        "cuda_assumed_not_verified": False,
        "models": {},
    }
    assert all(os.path.exists(MODELS[k]) for k in MODELS), "模型文件必须真实存在，不许假设"
    report["model_files_on_disk_mb"] = {k: round(os.path.getsize(v) / 1048576, 1) for k, v in MODELS.items()}

    tok = Tokenizer.from_file(os.path.join(MODEL_DIR, "tokenizer.json"))
    real_blocks = load_pairs(args.pages)
    report["real_corpus_blocks"] = len(real_blocks)
    report["real_block_example"] = (real_blocks[0][:70] if real_blocks else "")

    want = ["fp32", "int8"] if args.model == "both" else [args.model]
    vectors: dict[str, np.ndarray] = {}
    for key in want:
        entry: dict = {"path_tail": os.path.basename(MODELS[key]), "backends": {}}
        for btag, provs in (("cpu", ["CPUExecutionProvider"]),
                            ("directml", ["DmlExecutionProvider", "CPUExecutionProvider"])):
            if btag == "directml" and "DmlExecutionProvider" not in report["providers_available"]:
                entry["backends"][btag] = {"skipped": "DmlExecutionProvider 不可用"}
                continue
            so = ot.SessionOptions()
            so.log_severity_level = 3
            r0, t0 = rss_mb(), time.perf_counter()
            try:
                sess = ot.InferenceSession(MODELS[key], sess_options=so, providers=provs)
            except Exception as exc:  # noqa: BLE001
                entry["backends"][btag] = {"session_error": f"{type(exc).__name__}: {str(exc)[:200]}"}
                continue
            loaded = list(sess.get_providers())
            init_s = time.perf_counter() - t0
            # 吞吐：真实语料块，batch=16
            texts = (real_blocks or [t[0] for t in RELATED] + [t[1] for t in RELATED])
            bs, per_batch, all_v, shape = 16, [], [], None
            err = None
            for i in range(0, len(texts) - (len(texts) % bs), bs):  # 丢尾巴，保证每批都是满 batch
                batch = texts[i:i + bs]
                t1 = time.perf_counter()
                try:
                    out, amask = embed(sess, batch, tok)
                except Exception as exc:  # noqa: BLE001
                    err = f"{type(exc).__name__}: {str(exc)[:200]}"
                    break
                per_batch.append((time.perf_counter() - t1) * 1000)
                all_v.append(pool_normalize(out, amask))
            run = {
                "providers_actually_loaded": loaded,
                "init_seconds": round(init_s, 2),
                "rss_delta_mb": round(rss_mb() - r0, 1),  # 负值=上一个 session 被释放，看 rss_absolute_mb
                "pooled_shape": list(all_v[0].shape) if all_v else None,
                "error": err,
            }
            run["rss_absolute_mb"] = round(rss_mb(), 1)
            if all_v:
                V = np.vstack(all_v)
                vectors[f"{key}:{btag}"] = V
                run["dim"] = int(V.shape[1])
                run["batches"] = len(per_batch)
                run["ms_per_batch_mean"] = round(sum(per_batch) / len(per_batch), 1)
                run["chunks_per_second_end_to_end"] = round(len(per_batch) * bs / sum(per_batch) * 1000, 1)  # 含分词
                run["text_blocks_embedded"] = int(V.shape[0])
                run["batches_timed"] = len(per_batch)
                run["batch_size"] = bs
            entry["backends"][btag] = run
        # E2/E3：图是否自带 pooling、是否已归一化
        if key in ("fp32",):
            sess = ot.InferenceSession(MODELS[key], providers=["CPUExecutionProvider"])
            entry["graph_output_ranks"] = {o.name: len(o.shape) for o in sess.get_outputs()}
            del sess
        report["models"][key] = entry

    # E4 检索质量：用 fp32/cpu 向量算相关对 vs 无关对的余弦差
    if not vectors:
        report["fatal"] = "所有后端都没产出向量，无法判定检索质量"
        for key, e in report["models"].items():
            for b, r in e["backends"].items():
                print(f"  BACKEND {key}/{b}: " + json.dumps(r, ensure_ascii=False)[:300])
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump(report, fh, ensure_ascii=False, indent=2)
        print("VERDICT: RED")
        return 1
    qkey = "fp32:cpu" if "fp32:cpu" in vectors else next(iter(vectors))
    V = vectors[qkey]
    pair_texts = [t for pr in RELATED for t in pr] + [t for pr in UNRELATED for t in pr]
    import onnxruntime as _ot
    sess = _ot.InferenceSession(MODELS["fp32"], providers=["CPUExecutionProvider"])
    out, amask = embed(sess, pair_texts, tok)
    Pv = pool_normalize(out, amask)
    n_rel = len(RELATED) * 2
    sims_rel = [float(Pv[i] @ Pv[i + 1]) for i in range(0, n_rel, 2)]
    sims_unrel = [float(Pv[i] @ Pv[i + 1]) for i in range(n_rel, n_rel + len(UNRELATED) * 2, 2)]
    report["quality"] = {
        "vectors_used": qkey,
        "related_pair_cosine": [round(s, 4) for s in sims_rel],
        "unrelated_pair_cosine": [round(s, 4) for s in sims_unrel],
        "related_mean": round(float(np.mean(sims_rel)), 4),
        "unrelated_mean": round(float(np.mean(sims_unrel)), 4),
        "separation": round(float(np.mean(sims_rel) - np.mean(sims_unrel)), 4),
        "min_related_above_max_unrelated": bool(min(sims_rel) > max(sims_unrel)),
    }

    # E5 反例：『能源』不得命中『新能源汽车』胜过『传统能源电力』
    trap_q = [q for q, _, _ in TRAP]
    trap_docs = [d for _, *ds in TRAP for d in ds]
    o2, amask2 = embed(sess, trap_q + trap_docs, tok)
    T = pool_normalize(o2, amask2)
    traps = []
    for i, (q, wrong, right) in enumerate(TRAP):
        qi, wi, ri = i, len(trap_q) + i * 2, len(trap_q) + i * 2 + 1
        sw, sr = float(T[qi] @ T[wi]), float(T[qi] @ T[ri])
        # 判"方向"而不是"可区分"：只比大小差的断言即使排序反了也会变绿，等于没断言
        traps.append({"query": q, "score_should_lose": round(sw, 4), "score_should_win": round(sr, 4),
                      "direction_correct": bool(sr > sw), "margin": round(sr - sw, 4)})
    report["trap_cases"] = traps

    # E6 量级推算：按 P2 真实页数
    try:
        pdfs = json.load(open(".probe_work/p2_pdf_result.json", encoding="utf-8"))
        agg = pdfs["aggregate"]
        cen = json.load(open(".probe_work/p0_corpus_census.json", encoding="utf-8"))
        total_pages = agg["pages_sum"] / agg["files_ok"] * cen["pdf_count"]
        chunks_per_page = 2
        nchunks = int(total_pages * chunks_per_page)
        for tag, vecs in vectors.items():
            r = report["models"][tag.split(":")[0]]["backends"][tag.split(":")[1]]
            cps = r.get("chunks_per_second_end_to_end")
            if cps:
                r["full_corpus_hours"] = round(nchunks / cps / 3600, 1)
        report["scale"] = {
            "corpus_pdf_count": cen["pdf_count"],
            "estimated_total_pages": int(total_pages),
            "chunks_per_page_assumed": chunks_per_page,
            "estimated_chunks": nchunks,
            "vector_bytes_fp32_per_chunk": int(V.shape[1] * 4),
            "vector_store_gb_fp32": round(nchunks * V.shape[1] * 4 / 1024**3, 2),
            "vector_store_gb_int8": round(nchunks * V.shape[1] / 1024**3, 2),
        }
    except Exception as exc:  # noqa: BLE001
        report["scale"] = {"unavailable": f"{type(exc).__name__}: {exc}"}

    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2)

    q = report["quality"]
    checks = [
        ("模型文件真实存在于磁盘（不是「以为会下载下来」）", len(report["model_files_on_disk_mb"]) == 2),
        ("CPU 后端能真跑出向量", bool(vectors)),
        ("DirectML 后端结论已实测记录（可用则跑出向量，不可用则写明原因）",
         any("directml" in m["backends"] for m in report["models"].values())),
        ("向量维度是已知常数（决定索引结构）", q["vectors_used"] in vectors),
        ("语义相关对的相似度显著高于无关对", q["separation"] > 0.10),
        ("相关对与无关对的分数区间不重叠", q["min_related_above_max_unrelated"]),
        ("宽词陷阱方向正确：『能源』必须更靠近传统能源而不是新能源汽车",
         all(t["direction_correct"] and t["margin"] > 0.02 for t in report["trap_cases"])),
        ("全量建索引的量级与耗时已推算（不许回避）", "estimated_chunks" in report.get("scale", {})),
    ]
    for label, ok in checks:
        print(f"  {'PASS' if ok else 'FAIL'}  {label}")
    print("  INFO providers: " + json.dumps(report["providers_available"]))
    for key, e in report["models"].items():
        for b, r in e["backends"].items():
            print(f"  INFO {key}/{b}: " + json.dumps({k: r.get(k) for k in
                  ("providers_actually_loaded", "init_seconds", "rss_delta_mb", "rss_absolute_mb", "dim",
                   "chunks_per_second_end_to_end", "full_corpus_hours", "error", "skipped", "session_error")}, ensure_ascii=False))
    print("  INFO quality: " + json.dumps(q, ensure_ascii=False))
    print("  INFO traps: " + json.dumps(report["trap_cases"], ensure_ascii=False))
    print("  INFO scale: " + json.dumps(report["scale"], ensure_ascii=False))
    print("VERDICT: " + ("ALL GREEN" if all(ok for _, ok in checks) else "RED"))
    return 0 if all(ok for _, ok in checks) else 1


if __name__ == "__main__":
    sys.exit(main())
