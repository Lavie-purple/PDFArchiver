"""按监测根增量重扫 —— 把「盘上有、库里没有」补进库（**ISSUES I118** 甲）。

产品只在**扫描 / 文件监听**那一刻把文件写进库；门禁是 headless 跑的、应用没开着，
所以用户在两场链之间落进监测根的新文件一直不在库里，p12 的 C3 每场都能数出来。
这个脚本把「以前每轮临时写一次探针」的动作固定成一个入口。

用法：
    python scripts/rescan_roots.py                          # 只读预演：列出启用的监测根
    python scripts/rescan_roots.py --apply                  # 逐根 scan_root + 排空 index 队列
    python scripts/rescan_roots.py --apply --only D:        # 只扫路径里含 "D:" 的根（可重复给）
    python scripts/rescan_roots.py --apply --paths "C:/x/a.pdf"
    python scripts/rescan_roots.py --apply --no-drain       # 只扫描排队，索引留给应用跑
    python scripts/rescan_roots.py --apply --paths ... --vectors   # 顺手把向量也建了

边界（与门禁同一条纪律）：
- 只走产品入口：`ScanService.scan_root` / `reconcile_path`、`IndexService.index_document`、
  向量走 `VectorService.request_vectors`；**不写一条 SQL**、不动磁盘上的用户文件。
- **写的是用户库**，所以不带 `--apply` 一律只读；判据与阈值一处不动。
- 索引不够就停：排空超时如实打 `RESCAN: RED`，不延长窗口、不假装跑完。
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent / "src"))

from pdfarchiver.services.bootstrap import AppContext, bootstrap  # noqa: E402

DEFAULT_TIMEOUT_MIN = 30.0
POLL_SECONDS = 2.0


def harden_stdio() -> None:
    """GBK 控制台里打印中文别把整条命令崩掉（与门禁入口同一条兜底）。"""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def select_roots(ctx: AppContext, only: list[str]) -> list:
    """启用的监测根；给了 `--only` 就按路径子串筛（不区分大小写）。"""
    roots = ctx.roots.list_enabled()
    if not only:
        return roots
    keys = [k.lower() for k in only]
    return [r for r in roots if any(k in r.root_path.lower() for k in keys)]


def rescan_paths(ctx: AppContext, paths: list[str]) -> dict:
    """点名文件：`reconcile_path` 建主记录，需要索引就当场索引（不经过队列）。"""
    steps: list[dict] = []
    indexed: list[int] = []
    for raw in paths:
        outcome = ctx.scan.reconcile_path(raw)
        step = {"path": raw, "action": outcome.action, "doc_id": outcome.doc_id,
                "needs_index": bool(outcome.needs_index)}
        line = f"[file] {outcome.action}｜doc {outcome.doc_id}｜{raw}"
        if outcome.needs_index and outcome.doc_id is not None:
            result = ctx.indexer.index_document(int(outcome.doc_id))
            step["index"] = {"page_count": result.page_count, "stored_pages": result.stored_pages,
                             "text_status": result.text_status, "fts_status": result.fts_status,
                             "skipped_unchanged": result.skipped_unchanged,
                             "took_ms": result.took_ms}
            indexed.append(int(outcome.doc_id))
            line += (f"｜索引 {result.stored_pages}/{result.page_count} 页"
                     f" text={result.text_status} fts={result.fts_status} {result.took_ms}ms")
        steps.append(step)
        print(line, flush=True)
    return {"steps": steps, "indexed": indexed,
            "doc_ids": [int(s["doc_id"]) for s in steps if s["doc_id"] is not None]}


def rescan_roots(ctx: AppContext, roots: list) -> dict:
    """逐根 `scan_root`：只把新出现 / 改动过的文件排上索引，未变的只刷「又看见了」。"""
    reports: list[dict] = []
    for root in roots:
        print(f"[scan] {root.root_path} …", flush=True)
        report = ctx.scan.scan_root(root)
        reports.append({"root_path": report.root_path, "pdfs": report.pdfs,
                        "added": report.added, "changed": report.changed,
                        "adopted": report.adopted, "missing": report.missing,
                        "unchanged": report.unchanged, "index_enqueued": report.index_enqueued,
                        "error_count": report.error_count, "errors": report.errors[:5],
                        "cancelled": report.cancelled, "took_ms": report.took_ms})
        print(f"[scan] {report.summarize()}", flush=True)
    totals = {k: sum(r[k] for r in reports)
              for k in ("pdfs", "added", "changed", "adopted", "missing", "unchanged",
                        "index_enqueued", "error_count")}
    return {"reports": reports, "totals": totals}


def drain(ctx: AppContext, kinds: tuple[str, ...], timeout_min: float) -> dict:
    """起产品自己的 worker，等这些任务被执行体做完（状态由队列写，不在这里改）。"""
    ctx.start_background()
    started = time.monotonic()
    deadline = started + timeout_min * 60.0
    last_line = 0.0
    while True:
        counts = ctx.jobs.counts_by_kind_state()
        waiting = sum(counts.get((kind, state), 0) for kind in kinds
                      for state in ("queued", "running"))
        if waiting == 0:
            return {"drained": True, "waited_s": round(time.monotonic() - started, 1),
                    "left": 0}
        if time.monotonic() >= deadline:
            return {"drained": False, "waited_s": round(time.monotonic() - started, 1),
                    "left": waiting}
        if time.monotonic() - last_line >= 10.0:
            last_line = time.monotonic()
            print(f"[drain] 还剩 {waiting} 条（{time.monotonic() - started:.0f}s）", flush=True)
        time.sleep(POLL_SECONDS)


def pending_count(ctx: AppContext, kinds: tuple[str, ...]) -> int:
    counts = ctx.jobs.counts_by_kind_state()
    return sum(counts.get((kind, state), 0) for kind in kinds for state in ("queued", "running"))


def main(argv: list[str] | None = None) -> int:
    harden_stdio()
    ap = argparse.ArgumentParser(description="按监测根增量重扫（ISSUES I118 甲）")
    ap.add_argument("--data-root", default=None, help="数据根目录（默认与 bootstrap 同源）")
    ap.add_argument("--apply", action="store_true", help="真的写库；不给就是只读预演")
    ap.add_argument("--only", action="append", default=[], help="按根路径子串筛选，可重复")
    ap.add_argument("--paths", nargs="+", default=[], help="点名文件（走 reconcile_path）")
    ap.add_argument("--vectors", action="store_true", help="索引完成后同时排向量任务")
    ap.add_argument("--no-drain", action="store_true", help="只排队，不在这里跑 worker")
    ap.add_argument("--timeout-min", type=float, default=DEFAULT_TIMEOUT_MIN)
    args = ap.parse_args(argv)

    ctx = bootstrap(args.data_root)
    try:
        roots = select_roots(ctx, args.only)
        print(f"数据根：{ctx.paths.root}｜匹配监测根 {len(roots)} 个", flush=True)
        for root in roots:
            stamp = root.last_full_scan_at or "从未"
            print(f"  - {root.root_path}｜上次全扫 {stamp}", flush=True)

        if not args.apply:
            for raw in args.paths:
                known = ctx.documents.facts_by_key(_key(raw))
                state = f"doc {known.doc_id}" if known is not None else "库里没有"
                print(f"[preview] {raw}｜{state}", flush=True)
            print("RESCAN: DRY-RUN（只读预演，加 --apply 才写库）", flush=True)
            return 0

        if args.paths:
            result = rescan_paths(ctx, args.paths)
            summary = (f"点名 {len(result['steps'])} 份｜当场索引 {len(result['indexed'])} 份")
            doc_ids = result["doc_ids"]
        else:
            if not roots:
                print("RESCAN: RED（没有匹配的监测根，什么都没扫）", flush=True)
                return 2
            result = rescan_roots(ctx, roots)
            totals = result["totals"]
            summary = (f"PDF {totals['pdfs']}｜新增 {totals['added']}｜改动 {totals['changed']}"
                       f"｜改名 {totals['adopted']}｜未见 {totals['missing']}"
                       f"｜排队索引 {totals['index_enqueued']}｜读不出 {totals['error_count']}")
            doc_ids = []

        if args.vectors and doc_ids:
            request = ctx.vector.request_vectors(doc_ids)
            print(f"[vector] {request.describe()}", flush=True)
            if request.skipped:
                print(f"[vector] 跳过 {request.skipped}", flush=True)

        kinds = ("index", "vector") if args.vectors else ("index",)
        if not args.no_drain and pending_count(ctx, kinds) > 0:
            outcome = drain(ctx, kinds, args.timeout_min)
            if not outcome["drained"]:
                print(f"RESCAN: RED（排空超时：{outcome['left']} 条仍在排队，"
                      f"等了 {outcome['waited_s']}s）", flush=True)
                return 3
            summary += f"｜排空 {outcome['waited_s']}s"

        errors = sum(s["error_count"] for s in result.get("reports", []))
        verdict = "OK" if errors == 0 else "RED"
        print(f"RESCAN: {verdict}（{summary}）", flush=True)
        return 0 if errors == 0 else 1
    finally:
        ctx.shutdown()


def _key(path: str) -> str:
    from pdfarchiver.fs.identity import identity_key
    return identity_key(Path(path))


if __name__ == "__main__":
    raise SystemExit(main())
