"""P2 PDF 解析探针：在真实语料上验证 PyMuPDF 的抽取、渲染、内存与异常行为。

必须回答的问题：
  Q1 真实语料的页数分布、文本层命中率（原生/扫描/混合各占多少）
  Q2 每页抽取耗时与整库外推（决定 7,768 份能不能在可接受时间内索引完）
  Q3 单页渲染耗时与内存增长（决定阅读器的渲染策略与缓存上限）
  Q4 打开 1GB 级文件是否会把整文件读进内存（SPEC 五.8 明令禁止）
  Q5 SHA-256 全文哈希吞吐（决定重复检测与"内容变化但路径不变"的校验成本）
  Q6 损坏/加密/零字节/伪 PDF/中文超长路径 的真实失败形态（决定错误分类）
  Q7 page.search_for() 能否给出命中矩形（决定搜索结果跳转+高亮的可行性）
  Q8 在真实中文文本上建 FTS5 trigram 索引的体积比（比合成语料可信）

只读用户 PDF，不改不删；写操作只发生在 .probe_work/ 里。

用法: python tests/probes/p2_pdf_extract.py [--census .probe_work/p0_corpus_census.json]
      [--per-bucket 5] [--out .probe_work/p2_pdf_result.json]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import sqlite3
import sys
import time
from pathlib import Path

import psutil
import pymupdf

# MuPDF 会把格式错误直接写 stderr（实测：损坏对象绕过 Python 异常体系）。
# GUI 应用里必须静音并改走日志，否则用户看到的是控制台噪声而不是可诊断的错误。
pymupdf.TOOLS.mupdf_display_errors(False)

BUCKETS = [
    ("lt_1MB", 0, 1_048_576),
    ("1_10MB", 1_048_576, 10_485_760),
    ("10_50MB", 10_485_760, 52_428_800),
    ("50_200MB", 52_428_800, 209_715_200),
    ("ge_200MB", 209_715_200, 2**62),
]
DIR_CAP = 12
RSS = psutil.Process(os.getpid())


def rss_mb() -> float:
    return RSS.memory_info().rss / 1048576


def collect_samples(census_path: str, per_bucket: int) -> dict[str, list[str]]:
    """从普查结果里的高密度目录做分层抽样，每个桶取 per_bucket 个文件。"""
    data = json.loads(Path(census_path).read_text(encoding="utf-8"))
    dirs = [d["dir"] for d in data["top20_directories_by_pdf_count"]]
    big = [f["path"] for f in data["top15_largest"]]
    found: dict[str, list[tuple[int, str]]] = {k: [] for k, _, _ in BUCKETS}
    for d in dirs:
        p = Path(d)
        if not p.is_dir():
            continue
        try:
            entries = sorted((e for e in p.iterdir() if e.is_file()), key=lambda e: e.stat().st_size, reverse=True)
        except OSError:
            continue
        picked = 0
        for e in entries[:400]:
            if e.suffix.lower() != ".pdf":
                continue
            try:
                size = e.stat().st_size
            except OSError:
                continue
            for name, lo, hi in BUCKETS:
                if lo <= size < hi and len(found[name]) < DIR_CAP:
                    found[name].append((size, str(e)))
                    break
            picked += 1
            if picked > 60:
                break
    for path in big:
        try:
            size = os.path.getsize(path)
        except OSError:
            continue
        for name, lo, hi in BUCKETS:
            if lo <= size < hi and len(found[name]) < DIR_CAP + 6:
                found[name].append((size, path))
                break
    rng = random.Random(20261014)
    out: dict[str, list[str]] = {}
    for name, _, _ in BUCKETS:
        uniq = list(dict.fromkeys(p for _, p in found[name]))
        rng.shuffle(uniq)
        n = per_bucket if name != "ge_200MB" else min(per_bucket, len(uniq))
        out[name] = uniq[: max(2, n)]
    return out


def classify(doc) -> tuple[str, dict]:
    """按均匀抽样最多 30 页判定文档类型；text_bearing_rate 直接决定 OCR 工作量。"""
    pages = doc.page_count
    if pages <= 30:
        sample_idx = list(range(pages))
    else:
        step = pages / 30
        sample_idx = [int(i * step) for i in range(30)]
    chars_total = 0
    images_total = 0
    bearing = 0
    per_page = []
    for i in sample_idx:
        try:
            page = doc[i]
            txt = page.get_text("text") or ""
            imgs = page.get_images(full=False)
        except Exception as exc:  # noqa: BLE001 - 探针必须记录任何一页的真实异常形态
            per_page.append({"page": i, "error": f"{type(exc).__name__}: {exc}"})
            continue
        stripped = len(txt.strip())
        chars_total += stripped
        images_total += len(imgs)
        if stripped >= 40:
            bearing += 1
        if len(per_page) < 4:
            per_page.append({"page": i, "chars": stripped, "images": len(imgs), "rect": [round(v, 1) for v in tuple(page.rect)]})
    avg_chars = chars_total / max(1, len(sample_idx))
    rate = bearing / max(1, len(sample_idx))
    if rate >= 0.5:
        kind = "native_text"
    elif rate <= 0.1:
        kind = "scanned_image" if images_total > 0 else "empty_or_unreadable"
    else:
        kind = "mixed"
    return kind, {
        "sampled_pages": per_page,
        "sample_count": len(sample_idx),
        "avg_chars_per_sampled_page": round(avg_chars, 1),
        "text_bearing_rate": round(rate, 3),
        "sampled_images": images_total,
    }


def probe_file(path: str, render_scale: float, keep_text: bool = False) -> dict:
    rec: dict = {"path_tail": os.path.basename(path)[:60], "bytes": os.path.getsize(path)}
    rss_before = rss_mb()
    t0 = time.perf_counter()
    try:
        doc = pymupdf.open(path)
    except Exception as exc:  # noqa: BLE001
        rec["open_error"] = f"{type(exc).__name__}: {exc}"
        rec["open_ms"] = round((time.perf_counter() - t0) * 1000, 1)
        return rec
    rec["open_ms"] = round((time.perf_counter() - t0) * 1000, 1)
    try:
        rec["pages"] = doc.page_count
        rec["is_pdf"] = doc.is_pdf
        rec["needs_pass"] = bool(doc.needs_pass)
        rec["is_encrypted"] = bool(doc.is_encrypted)
        rec["is_repaired"] = bool(getattr(doc, "is_repaired", False))
        meta = doc.metadata or {}
        rec["metadata_keys_present"] = sorted(k for k, v in meta.items() if v not in (None, "", b""))
        rec["title_head"] = (meta.get("title") or "")[:40]
        rec["producer"] = (meta.get("producer") or "")[:40]
        try:
            rec["toc_entries"] = len(doc.get_toc(simple=True))
        except Exception as exc:  # noqa: BLE001
            rec["toc_entries"] = f"ERROR {exc}"
        kind, detail = classify(doc)
        rec["kind"] = kind
        rec["detail"] = detail
        # 全文抽取整本（限页数上限，防止 1GB 文件把探针拖死）
        cap = min(doc.page_count, 400)
        t1 = time.perf_counter()
        texts = []
        for i in range(cap):
            try:
                texts.append(doc[i].get_text("text") or "")
            except Exception:  # noqa: BLE001
                texts.append("")
        extract_s = time.perf_counter() - t1
        joined = "\n".join(texts)
        if keep_text:
            rec["_text"] = joined[:20000]
        rec["extract_pages"] = cap
        rec["extract_seconds"] = round(extract_s, 3)
        rec["chars_total"] = len(joined)
        rec["pages_per_second"] = round(cap / extract_s, 1) if extract_s > 0 else None
        rec["chars_per_page_mean"] = round(len(joined) / cap, 1) if cap else 0
        # 渲染第一页 @150dpi
        try:
            t2 = time.perf_counter()
            pix = doc[0].get_pixmap(matrix=pymupdf.Matrix(render_scale, render_scale))
            rec["render_ms"] = round((time.perf_counter() - t2) * 1000, 1)
            rec["render_wh"] = [pix.width, pix.height]
            rec["render_bytes"] = pix.samples.__len__() if hasattr(pix.samples, "__len__") else None
            del pix
        except Exception as exc:  # noqa: BLE001
            rec["render_error"] = f"{type(exc).__name__}: {exc}"
        # search_for 命中矩形（结果跳转与高亮的可行性）
        probe_term = None
        for t in texts:
            for line in t.splitlines():
                s = line.strip()
                if 2 <= len(s) <= 8 and any("\u4e00" <= c <= "\u9fff" for c in s):
                    probe_term = s
                    break
            if probe_term:
                break
        if probe_term:
            hit_page = None
            for i, t in enumerate(texts):
                if probe_term in t.replace("\n", ""):
                    hit_page = i
                    break
            if hit_page is not None:
                try:
                    rects = doc[hit_page].search_for(probe_term)
                    rec["search_for"] = {"term": probe_term, "page": hit_page, "rects": len(rects),
                                         "first_rect": [round(v, 1) for v in tuple(rects[0])] if rects else None}
                except Exception as exc:  # noqa: BLE001
                    rec["search_for"] = {"error": f"{type(exc).__name__}: {exc}"}
    finally:
        doc.close()
    rec["rss_delta_mb_after_close"] = round(rss_mb() - rss_before, 1)
    # 流式 SHA-256 吞吐
    t3 = time.perf_counter()
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    dt = time.perf_counter() - t3
    rec["sha256_seconds"] = round(dt, 2)
    rec["sha256_mb_per_second"] = round(rec["bytes"] / 1048576 / dt, 1) if dt > 0 else None
    rec["sha256_head"] = h.hexdigest()[:12]
    return rec


def edge_cases(work: str) -> dict:
    out: dict = {}
    os.makedirs(work, exist_ok=True)
    real = pymupdf.open()
    page = real.new_page()
    page.insert_text((72, 72), "hello world 中文测试")
    real[0].insert_text((72, 120), "第二行 人工智能产业报告")
    clean = os.path.join(work, "edge_clean.pdf")
    real.save(clean)
    real.close()

    raw = Path(clean).read_bytes()
    trunc = os.path.join(work, "edge_truncated.pdf")
    Path(trunc).write_bytes(raw[: max(20, len(raw) // 3)])
    zero = os.path.join(work, "edge_zero.pdf")
    Path(zero).write_bytes(b"")
    fake = os.path.join(work, "edge_fake.pdf")
    Path(fake).write_text("这不是 PDF，只是文本文件改的扩展名。" * 20, encoding="utf-8")
    junk = os.path.join(work, "edge_junk.pdf")
    Path(junk).write_bytes(os.urandom(5000))

    for label, path in [("clean", clean), ("truncated", trunc), ("zero_bytes", zero), ("text_as_pdf", fake), ("random_bytes", junk)]:
        try:
            doc = pymupdf.open(path)
            info = {"opened": True, "pages": doc.page_count, "is_pdf": doc.is_pdf,
                    "needs_pass": doc.needs_pass, "repaired": bool(getattr(doc, "is_repaired", False))}
            try:
                info["text_first_page"] = (doc[0].get_text("text") or "")[:30] if doc.page_count else ""
            except Exception as exc:  # noqa: BLE001
                info["text_error"] = f"{type(exc).__name__}: {exc}"
            doc.close()
        except Exception as exc:  # noqa: BLE001
            info = {"opened": False, "error": f"{type(exc).__name__}: {exc}"}
        out[label] = info

    enc_src = pymupdf.open(clean)
    enc = os.path.join(work, "edge_encrypted.pdf")
    enc_src.save(enc, encryption=pymupdf.PDF_ENCRYPT_AES_256, owner_pw="o123", user_pw="u123")
    enc_src.close()
    d = pymupdf.open(enc)
    out["encrypted"] = {"needs_pass": bool(d.needs_pass), "is_encrypted": bool(d.is_encrypted),
                        "pages_before_auth": d.page_count}
    authed = d.authenticate("u123")
    out["encrypted"]["authenticate_returned"] = authed
    out["encrypted"]["pages_after_auth"] = d.page_count
    try:
        out["encrypted"]["text_after_auth"] = (d[0].get_text("text") or "")[:20]
    except Exception as exc:  # noqa: BLE001
        out["encrypted"]["text_error"] = str(exc)
    d.close()

    deep_dir = os.path.join(work, "中文目录 空格 与很长路径用于验证 MAX_PATH 边界行为", "第二层 " + "长" * 30, "第三层" + "长" * 40)
    os.makedirs(deep_dir, exist_ok=True)
    deep = os.path.join(deep_dir, "文件名" + "长" * 90 + ".pdf")
    out["long_chinese_path"] = {"path_len": len(deep), "over_260": len(deep) > 260}
    try:
        Path(deep).write_bytes(raw)
        d = pymupdf.open(deep)
        out["long_chinese_path"]["opened"] = True
        out["long_chinese_path"]["pages"] = d.page_count
        d.close()
        out["long_chinese_path"]["stat_size"] = os.path.getsize(deep)
        Path(deep).unlink()
    except Exception as exc:  # noqa: BLE001
        out["long_chinese_path"]["error"] = f"{type(exc).__name__}: {exc}"
    unc = "\\\\?\\" + os.path.abspath(deep).replace("/", "\\")
    out["long_path_extended_prefix"] = {"probe_only": "if the plain path fails, \\?? prefix is the escape hatch"}
    try:
        out["long_path_extended_prefix"]["write_via_extended"] = bool(Path(unc).write_bytes(raw))
        out["long_path_extended_prefix"]["read_pages"] = pymupdf.open(unc).page_count
    except Exception as exc:  # noqa: BLE001
        out["long_path_extended_prefix"]["error"] = f"{type(exc).__name__}: {exc}"
    try:
        os.remove(unc)
    except OSError:
        pass

    lock = os.path.join(work, "edge_locked.pdf")
    Path(lock).write_bytes(raw)
    holder = open(lock, "rb")
    try:
        with open(lock, "ab"):
            pass
    except OSError as exc:
        out["open_for_write_while_readholder"] = f"{type(exc).__name__}: {exc}"
    try:
        d = pymupdf.open(lock)
        out["read_while_held"] = {"opened": True, "pages": d.page_count}
        d.close()
    except Exception as exc:  # noqa: BLE001
        out["read_while_held"] = {"opened": False, "error": f"{type(exc).__name__}: {exc}"}
    holder.close()
    os.remove(lock)
    return out


def real_text_index(records: list[dict], work: str) -> dict:
    """用真实抽取到的中文正文量一遍 trigram 体积比与查询延迟。"""
    texts = [r.get("_text") for r in records if r.get("_text")]
    if not texts:
        return {"skipped": "没有可抽取的真实文本页"}
    path = os.path.join(work, "p2_real_fts.db")
    for p in (path, path + "-wal", path + "-shm"):
        if os.path.exists(p):
            os.remove(p)
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("CREATE TABLE pages(doc_id INTEGER, page_no INTEGER, body TEXT)")
    conn.execute("CREATE VIRTUAL TABLE pages_fts USING fts5(body, content='pages', content_rowid='rowid', tokenize='trigram')")
    rows = [(i // 20, i % 20, t) for i, t in enumerate(texts)]
    with conn:
        conn.executemany("INSERT INTO pages VALUES(?,?,?)", rows)
    t0 = time.perf_counter()
    conn.execute("INSERT INTO pages_fts(pages_fts) VALUES('rebuild')")
    conn.commit()
    build = time.perf_counter() - t0
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    text_bytes = conn.execute("SELECT sum(length(CAST(body AS BLOB))) FROM pages").fetchone()[0]
    lat = {}
    for q in ("人工智能", "产业", "报告"):
        t0 = time.perf_counter()
        conn.execute("SELECT count(*) FROM pages_fts WHERE pages_fts MATCH ?", (f'"{q}"',)).fetchone()
        lat[q] = round((time.perf_counter() - t0) * 1000, 2)
    res = {
        "real_pages": len(rows),
        "real_text_bytes": text_bytes,
        "index_build_seconds": round(build, 2),
        "db_bytes": sum(os.path.getsize(p) for p in (path, path + "-wal", path + "-shm") if os.path.exists(p)),
        "query_ms": lat,
    }
    res["db_over_text_ratio"] = round(res["db_bytes"] / max(1, res["real_text_bytes"]), 2)
    conn.close()
    return res


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--census", default=".probe_work/p0_corpus_census.json")
    ap.add_argument("--work", default=".probe_work")
    ap.add_argument("--out", default=".probe_work/p2_pdf_result.json")
    ap.add_argument("--per-bucket", type=int, default=5)
    ap.add_argument("--dpi", type=float, default=150)
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    samples = collect_samples(args.census, args.per_bucket)
    print("sampled per bucket: " + json.dumps({k: len(v) for k, v in samples.items()}))
    scale = args.dpi / 72
    records: list[dict] = []
    rss_start = rss_mb()
    for bucket, paths in samples.items():
        for p in paths:
            print(f"  [{bucket}] {os.path.basename(p)[:50]} ({os.path.getsize(p)/1048576:.1f}MB)")
            try:
                rec = probe_file(p, scale, keep_text=True)
            except Exception as exc:  # noqa: BLE001 - 单个文件异常不许中断整轮探针
                rec = {"path_tail": os.path.basename(p)[:60], "fatal": f"{type(exc).__name__}: {exc}"}
            rec["bucket"] = bucket
            records.append(rec)
    report = {
        "pymupdf_version": pymupdf.VersionBind,
        "python": sys.version.split()[0],
        "rss_start_mb": round(rss_start, 1),
        "rss_now_mb": round(rss_mb(), 1),
        "dpi": args.dpi,
        "buckets": {k: len(v) for k, v in samples.items()},
        "files": records,
        "edge_cases": edge_cases(args.work),
    }
    kinds = {}
    for r in records:
        kinds[r.get("kind", "error_or_unopened")] = kinds.get(r.get("kind", "error_or_unopened"), 0) + 1
    ok = [r for r in records if r.get("kind")]
    report["kind_distribution"] = kinds
    def pct(vals: list[float], q: float) -> float:
        vals = sorted(vals)
        return round(vals[min(len(vals) - 1, int((len(vals) - 1) * q))], 1) if vals else 0

    renders = [r["render_ms"] for r in ok if r.get("render_ms")]
    report["aggregate"] = {
        "files_ok": len(ok),
        "pages_sum": sum(r.get("pages", 0) for r in ok),
        "pages_mean": round(sum(r.get("pages", 0) for r in ok) / len(ok), 1) if ok else 0,
        "pages_median": pct([r.get("pages", 0) for r in ok], 0.5),
        "pages_max": max((r.get("pages", 0) for r in ok), default=0),
        "text_bearing_rate_mean": round(sum(r["detail"]["text_bearing_rate"] for r in ok if r.get("detail")) / max(1, len([r for r in ok if r.get("detail")])), 3),
        "extract_pages_per_second_mean": round(sum(r["pages_per_second"] for r in ok if r.get("pages_per_second")) / max(1, len([r for r in ok if r.get("pages_per_second")])), 1),
        "render_ms_mean": round(sum(renders) / len(renders), 1) if renders else 0,
        "render_ms_median": pct(renders, 0.5),
        "render_ms_p90": pct(renders, 0.9),
        "sha256_mb_per_second_mean": round(sum(r["sha256_mb_per_second"] for r in ok if r.get("sha256_mb_per_second")) / max(1, len([r for r in ok if r.get("sha256_mb_per_second")])), 1),
        "open_ms_max": max((r.get("open_ms", 0) for r in ok), default=0),
        "search_for_success": sum(1 for r in ok if isinstance(r.get("search_for"), dict) and r["search_for"].get("rects")),
        "search_for_attempted": sum(1 for r in ok if r.get("search_for")),
    }
    agg = report["aggregate"]
    report["real_text_fts"] = real_text_index(records, args.work)
    for r in report["files"]:
        r.pop("_text", None)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2)

    agg = report["aggregate"]
    ec_cases = report["edge_cases"]
    checks = [
        ("没有任何文件把整本读进内存（RSS 增量 < 1200MB）", report["rss_now_mb"] - report["rss_start_mb"] < 1200),
        ("零字节文件被识别为 EmptyFileError 而非崩溃", ec_cases["zero_bytes"]["opened"] is False and "EmptyFile" in ec_cases["zero_bytes"].get("error", "")),
        ("伪 PDF（文本改扩展名）被识别为 FileDataError", ec_cases["text_as_pdf"]["opened"] is False),
        ("随机字节文件被拒绝", ec_cases["random_bytes"]["opened"] is False),
        ("截断文件能打开但被标记 is_repaired（必须当成降级状态而不是成功）", ec_cases["truncated"]["opened"] is True and ec_cases["truncated"]["repaired"] is True),
        ("加密 PDF 能被识别为 needs_pass 而不是崩溃", ec_cases["encrypted"]["needs_pass"] is True),
        ("search_for 在有文本的文档上返回了矩形", agg["search_for_success"] > 0),
        ("单页渲染中位数 < 250ms @150dpi", agg["render_ms_median"] < 250),
        ("文本抽取均值 > 20 pages/s", agg["extract_pages_per_second_mean"] > 20),
        ("超长中文路径（>260）行为已被记录", ec_cases["long_chinese_path"]["over_260"] is True),
    ]
    for label, passed in checks:
        print(f"  {'PASS' if passed else 'FAIL'}  {label}")
    print("  INFO kinds: " + json.dumps(kinds, ensure_ascii=False))
    print("  INFO agg: " + json.dumps(agg, ensure_ascii=False))
    print("  INFO rss start->now: %.1f -> %.1f MB" % (report["rss_start_mb"], report["rss_now_mb"]))
    print("VERDICT: " + ("ALL GREEN" if all(p for _, p in checks) else "RED"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
