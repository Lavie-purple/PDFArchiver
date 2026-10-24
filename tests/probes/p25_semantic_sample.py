"""P25 真库小样本语义索引：吞吐、内存、向量体积，以及「语义 vs 全文」在真实语料上的对比。

**为什么要有这一条**（2026-10-24 轮二十三，用户勾选「真库小样本语义索引」）：
带 `--data-root` 的 p12 已经证明真库 **10,991 份**主记录、`vector_status` **全 `na`** ——
语义链路写完了、演示库跑通过，但**真语料上一条向量都没建过**。p6 量的是模型本身能不能跑，
用的却是几十段手挑文本；全量到底要多久、占多少盘、真语料上比全文多召回多少，仍是空白。
这一条不建正式索引（不写 `vectors.npy`、不改 `vector_status`），只在内存里对
**300 份 / ≤1,500 页**真页做一次可复现的抽样，回答四个数：

1. **吞吐**：模型加载几秒、每页几毫秒（含分词），折算全量 1,975,611 页要几小时；
2. **内存**：RSS 增量（模型 + 1500×512 的 float32 矩阵）；
3. **体积**：int8 每页 512 B，折算全量正文页要多少 GiB（与 D-036 的 1.93GB/4M chunks 对账）；
4. **检索**：20 条自然语言查询 + 20 条关键词式查询，各跑一遍语义与产品现有的全文通道
   （`indexing.fts.match_expression()` 造 trigram 短语），看语义补回了哪几条全文召不回的。

**口径边界（写进 JSON，别让读数被当成质量验收）**：
- 抽样规则固定：`text_status in (native,mixed)`、`page_count 1–60`、按 id 排序后
  `random.Random(20261024).sample(300)`；每份只取前 7 页 —— 这是吞吐样本，不是全量质量样本。
- 20 条查询都由这 300 份里**首页真实内容**出题，期望命中就是那一页；因此 Recall 只证明
  「语义能把换过说法的句子对回去」，不证明「20 条真实需求已经覆盖」（那是 **ISSUES I11** 的活）。
- 真库以 **只读 URI + `pragma query_only=1`** 打开；探针不写库、不写向量文件。
- 出现任何模型/库异常都如实记 `RED` 并打印原文，不拿"没跑成"当"没问题"。

跑法：
    .venv/Scripts/python.exe tests/probes/p25_semantic_sample.py
    .venv/Scripts/python.exe tests/probes/p25_semantic_sample.py --docs 120 --max-pages 600
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sqlite3
import sys
import time
from pathlib import Path

import psutil

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

SEED = 20261024
SAMPLE_DOCS = 300
PER_DOC_PAGES = 7
MAX_PAGES = SAMPLE_DOCS * PER_DOC_PAGES   # = 2100：上限必须盖住 20 条查询期望的那几份，否则是样本自己漏题
BODY_CHARS = 600          # 模型 max_length=256 token，中文 600 字已足够；再长只是白读库
TOP_K = 10

RSS = psutil.Process(os.getpid())


def rss_mb() -> float:
    return RSS.memory_info().rss / 1048576


# 20 条：`自然语言` 是用户真实会打的句子；`关键词` 是他退化成搜词时的输入。`doc` / `page` 是
# 2026-10-24 从这 300 份样本的首页正文里读出来出题的，不是照着文档名编的。
# 关键词刻意分两组：17 条是**单个词串**（产品 FTS 是短语匹配），3 条带空格（`服饰 时尚` / `国庆 出游` /
# `元宇宙 电商`）—— 后者就是拿来照出「整串当一个短语、不拆词」这条产品口径的，读数里它们是 0 命中。
QUERIES = [
    ("女性服装款式的变化和生育策略有什么关系", "服饰 时尚", 12, 1),
    ("互联网十年发展的本质是什么", "互联网10年", 50, 1),
    ("怎么把一个人的认知方式提取出来给别人用", "认知操作系统", 61, 1),
    ("国庆假期出游人数和人均消费的变化", "国庆 出游", 89, 1),
    ("85后到00后几代人的消费特点", "人群洞察", 186, 1),
    ("2022年科技与IT行业的主要趋势", "科技与IT", 209, 1),
    ("泛娱乐用户的消费和营销有什么特点", "泛娱乐", 223, 1),
    ("读完《数据的本质》这本书的感想", "数据的本质", 245, 1),
    ("做竞品分析通常用哪些方法和模型", "竞品分析", 255, 1),
    ("顺丰如何建设企业数据治理体系", "数据治理", 273, 1),
    ("国有企业数字化转型有哪些案例", "数字化转型", 277, 1),
    ("大模型人才认证市场的情况", "人才认证", 286, 1),
    ("提示词工程在金融和法律领域怎么应用", "提示词工程", 309, 1),
    ("智能体Agent里的提示词应该如何优化", "Agent", 313, 1),
    ("元宇宙时代有哪些投资机会", "元宇宙", 332, 1),
    ("元宇宙会怎样改变电商交易", "元宇宙 电商", 335, 1),
    ("元宇宙与下一代互联网的关系", "下一代互联网", 346, 1),
    ("塔罗牌占卜感情时怎么摆牌阵", "塔罗", 380, 1),
    ("塔罗圣杯的水元素代表什么", "圣杯", 385, 1),
    ("怎么停止自我PUA和自我保护", "自我PUA", 421, 1),
]


def open_ro(data_root: Path) -> sqlite3.Connection:
    db = data_root / "data" / "catalog.db"
    if not db.is_file():
        raise SystemExit(f"真库不存在：{db}（data-root 传基目录，不是 data/ 那一层）")
    conn = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True, timeout=30)
    conn.execute("pragma query_only=1")
    return conn


def sample_docs(conn: sqlite3.Connection, want: int) -> list[int]:
    ids = [r[0] for r in conn.execute(
        "select id from documents where text_status in ('native','mixed')"
        " and page_count between 1 and 60 order by id")]
    rng = random.Random(SEED)
    return sorted(rng.sample(ids, min(want, len(ids))))


def load_pages(conn: sqlite3.Connection, docs: list[int], max_pages: int) -> list[dict]:
    pages: list[dict] = []
    for doc_id in docs:
        if len(pages) >= max_pages:
            break
        rows = conn.execute(
            "select page_no, substr(body,1,?) from text_pages where doc_id=?"
            " order by page_no limit ?", (BODY_CHARS, doc_id, PER_DOC_PAGES)).fetchall()
        for page_no, body in rows:
            if not (body or "").strip():
                continue
            pages.append({"doc_id": doc_id, "page_no": page_no, "body": body})
            if len(pages) >= max_pages:
                break
    return pages


def fts_hits(conn: sqlite3.Connection, match: str, doc_ids: set[int]) -> list[tuple[int, int]]:
    """产品全文通道：≥3 字走 trigram 短语，1–2 字按 `channel_for()` 退 LIKE（与产品同口径）。
    **SQL 里就限在这 300 份** —— 语义只见过这 300 份，全文若对全库跑，同一条查询会被
    10,991 份里的命中挤掉 top-200，那是拿范围差冒充召回差。"""
    from pdfarchiver.indexing.fts import MIN_FTS_CHARS, match_expression
    ids = sorted(doc_ids)
    marks = ",".join("?" * len(ids))
    if len(match.strip()) < MIN_FTS_CHARS:
        rows = conn.execute(
            "select doc_id, page_no from text_pages"
            f" where doc_id in ({marks}) and body like ? escape '\\'"
            " order by doc_id, page_no limit 200",
            (*ids, "%" + match.strip() + "%")).fetchall()
        return [(int(d), int(p)) for d, p in rows]
    try:
        expr = match_expression(match)
    except ValueError:
        return []
    rows = conn.execute(
        "select tp.doc_id, tp.page_no from content_fts"
        " join text_pages tp on tp.rowid = content_fts.rowid"
        f" where content_fts match ? and tp.doc_id in ({marks})"
        " order by bm25(content_fts) limit 200",
        (expr, *ids)).fetchall()
    return [(int(d), int(p)) for d, p in rows]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-root", default=None, help="真库数据根（默认跟随产品解析）")
    ap.add_argument("--docs", type=int, default=SAMPLE_DOCS)
    ap.add_argument("--max-pages", type=int, default=MAX_PAGES)
    ap.add_argument("--out", default=".probe_work/p25_semantic_sample.json")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    os.makedirs(os.path.dirname(args.out), exist_ok=True)

    from pdfarchiver.config.paths import resolve_data_root
    data_root = resolve_data_root(args.data_root)
    model_root = REPO / ".probe_work"          # models_dir = <root>/models，权重只在这里
    if not (model_root / "models" / "bge-small-zh-v1.5").is_dir():
        raise SystemExit(f"样本模型不在 {model_root / 'models'}，先确认 .probe_work/models 还在")

    report: dict = {"probe": "p25_semantic_sample", "data_root": str(data_root),
                    "sample_seed": SEED,
                    "caveats": [
                        f"抽样 {SAMPLE_DOCS} 份 / 每份前 {PER_DOC_PAGES} 页，不是全库 {1_975_611:,} 页",
                        f"每页正文截断到 {BODY_CHARS} 字（模型 max_length=256 token 之外读不到）",
                        "20 条查询是探针模拟的，不是用户手里那 20 条真查询 ⇒ 不能用来销账 ISSUES I11",
                        "期望页固定是第 1 页；按页严格口径低于按文档口径（同一份的其它页也算错）",
                    ]}
    checks: list[tuple[str, bool]] = []
    try:
        conn = open_ro(Path(data_root))
    except Exception as exc:  # noqa: BLE001
        print(f"  FAIL  打开真库失败：{type(exc).__name__}: {exc}")
        print("VERDICT: RED")
        return 1

    try:
        vec_rows = conn.execute("select count(*) from documents where vector_status='done'").fetchone()[0]
        report["real_library"] = {
            "vector_status_done": int(vec_rows),
            "documents_with_text": int(conn.execute(
                "select count(*) from documents where text_status in ('native','mixed')").fetchone()[0]),
        }
        docs = sample_docs(conn, args.docs)
        pages = load_pages(conn, docs, args.max_pages)
        doc_ids = {p["doc_id"] for p in pages}
        names = {r[0]: r[1] for r in conn.execute(
            "select id,name from documents where id in (%s)" % ",".join("?" * len(doc_ids)),
            tuple(doc_ids))}
        report["sample"] = {"docs_with_pages": len(doc_ids), "pages": len(pages),
                            "chars": sum(len(p["body"]) for p in pages),
                            "docs_requested": args.docs, "max_pages": args.max_pages,
                            "per_doc_pages_cap": PER_DOC_PAGES}
        print(f"  样本：{len(doc_ids)} 份 / {len(pages)} 页 / "
              f"{report['sample']['chars']:,} 字（种子 {SEED}，每份前 {PER_DOC_PAGES} 页）")
        checks.append(("真库以只读方式打开并抽到 ≥100 份文档", len(doc_ids) >= 100))
        checks.append(("抽到的正文页 ≥300（否则吞吐与召回都不算样本）", len(pages) >= 300))

        # ── 嵌入 ─────────────────────────────────────────────────────────────
        from pdfarchiver.semantic.embedding import EmbeddingService
        svc = EmbeddingService(model_root)
        t_load0 = time.perf_counter()
        svc._ensure_session()                     # 探针要看真实 provider，读私有会话属证据采集
        load_s = time.perf_counter() - t_load0
        providers = list(svc._session.get_providers()) if svc._session else []
        rss0 = rss_mb()
        t0 = time.perf_counter()
        vecs = []
        for i in range(0, len(pages), EmbeddingService.BATCH_SIZE):
            batch = [p["body"] for p in pages[i:i + EmbeddingService.BATCH_SIZE]]
            vecs.append(svc.embed(batch))
        elapsed = time.perf_counter() - t0
        rss1 = rss_mb()
        import numpy as np
        V = np.vstack(vecs)
        per_page_ms = elapsed * 1000 / max(len(pages), 1)
        full_pages = 1_975_611                    # p12 真根实测的正文行数（2026-10-24）
        report["embed"] = {
            "providers": providers, "dim": int(V.shape[1]), "vectors": int(V.shape[0]),
            "model_load_seconds": round(load_s, 2),
            "embed_seconds": round(elapsed, 2),
            "pages_per_second": round(len(pages) / max(elapsed, 1e-9), 2),
            "ms_per_page": round(per_page_ms, 1),
            "rss_before_mb": round(rss0, 1), "rss_after_mb": round(rss1, 1),
            "rss_delta_mb": round(rss1 - rss0, 1),
            "float32_matrix_mb": round(V.nbytes / 1048576, 1),
            "int8_bytes_per_page": int(V.shape[1]),
            "full_corpus_pages": full_pages,
            "full_corpus_int8_gib": round(full_pages * V.shape[1] / 1024 ** 3, 2),
            "full_corpus_fp32_gib": round(full_pages * V.shape[1] * 4 / 1024 ** 3, 2),
            "full_corpus_hours_at_measured_rate": round(full_pages / (len(pages) / max(elapsed, 1e-9)) / 3600, 2),
        }
        print(f"  嵌入：{len(pages)} 页 / {elapsed:.1f}s = {per_page_ms:.1f} ms/页｜"
              f"加载 {load_s:.1f}s｜RSS {rss0:.0f}→{rss1:.0f} MiB｜provider {providers}")
        print(f"  全量折算：{full_pages:,} 页 ÷ {report['embed']['pages_per_second']} 页/秒 = "
              f"{report['embed']['full_corpus_hours_at_measured_rate']} 小时；"
              f"int8 {report['embed']['full_corpus_int8_gib']} GiB / fp32 {report['embed']['full_corpus_fp32_gib']} GiB")
        checks.append(("模型真跑出 512 维向量（不是空矩阵）", V.shape[1] == 512 and V.shape[0] == len(pages)))
        checks.append(("吞吐与全量耗时已折算（不许只报'能跑'）",
                       report["embed"]["pages_per_second"] > 0))

        # ── 检索对比 ─────────────────────────────────────────────────────────
        results = []
        for text, kw, doc, page in QUERIES:
            qv = svc.embed([text])[0]
            semantic_hits = [(pages[i]["doc_id"], pages[i]["page_no"], float(V[i] @ qv))
                             for i in np.argsort(-(V @ qv))[:TOP_K]]
            expected = (doc, page)                       # 元组：列表 `[d, p] in [(d, p)]` 恒为假
            fts_nat = set(fts_hits(conn, text, doc_ids)[:TOP_K])
            fts_kw = set(fts_hits(conn, kw, doc_ids)[:TOP_K])
            results.append({
                "query": text, "keyword": kw, "expected": [doc, page],
                "semantic_top": [{"doc": d, "page": p, "score": round(s, 4),
                                  "name": names.get(d, "?"),
                                  "snippet": next((x["body"][:80] for x in pages
                                                   if x["doc_id"] == d and x["page_no"] == p), "")}
                                 for d, p, s in semantic_hits[:5]],
                "semantic_hit": any(d == doc and p == page for d, p, _ in semantic_hits),
                "fts_natural_hit": expected in fts_nat,
                "fts_keyword_hit": expected in fts_kw,
                "fts_keyword_total": len(fts_hits(conn, kw, doc_ids)),
                "fts_keyword_top": sorted(fts_kw)[:3],
            })
        n = len(results)
        sem = sum(r["semantic_hit"] for r in results)
        fts_nat = sum(r["fts_natural_hit"] for r in results)
        fts_kw = sum(r["fts_keyword_hit"] for r in results)
        complement = sum(r["semantic_hit"] and not r["fts_natural_hit"] for r in results)
        report["retrieval"] = {
            "queries": n, "semantic_recall_at_10": f"{sem}/{n}",
            "fts_natural_phrase_recall_at_10": f"{fts_nat}/{n}",
            "fts_keyword_recall_at_10": f"{fts_kw}/{n}",
            "semantic_only": f"{complement}/{n}",
            "per_query": results,
        }
        for r in results:
            mark = "语义✓" if r["semantic_hit"] else "语义✗"
            print(f"  {mark} 全文句={int(r['fts_natural_hit'])} 全文词={int(r['fts_keyword_hit'])}"
                  f"  [{r['expected'][0]}:{r['expected'][1]}] {r['query']}")
            if r["semantic_top"]:
                t = r["semantic_top"][0]
                print(f"        top1 {t['doc']}:{t['page']} {t['score']:.3f} {t['name'][:30]}")
        print(f"  召回：语义 {sem}/{n}｜全文自然句 {fts_nat}/{n}｜全文关键词 {fts_kw}/{n}｜"
              f"语义独有 {complement}/{n}")
        checks.append((f"20 条查询全部跑完（{n}）", n == len(QUERIES)))
        checks.append(("检索表带 doc_id + page_no + 片段（可定位）",
                       all(r["semantic_top"] and r["semantic_top"][0]["snippet"] for r in results)))
    finally:
        conn.close()

    report["real_library"]["vector_status_still_na"] = report["real_library"]["vector_status_done"] == 0
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2)
    print(f"  读数落盘：{args.out}")
    print("  口径：抽样吞吐 + 首页出题，不是全量质量验收；不写库、不写 vectors.npy")
    for label, ok in checks:
        print(f"  {'PASS' if ok else 'FAIL'}  {label}")
    print("VERDICT: " + ("ALL GREEN" if all(ok for _, ok in checks) else "RED"))
    return 0 if all(ok for _, ok in checks) else 1


if __name__ == "__main__":
    sys.exit(main())
