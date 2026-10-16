"""续跑索引 —— 首扫脚本退出后把队列里剩下的任务排空。

用法：
    python scripts/resume_indexing.py                 # 一直跑到排空
    python scripts/resume_indexing.py --max-hours 3   # 最多跑 3 小时
    python scripts/resume_indexing.py --check-only    # 只报当前队列状态不跑

bootstrap + start_background() 自带两件关键的：
- queue.recover()：把上次进程退出留在 running 的残尸收回 queued
- scan.resume_pending()：把 fts_status in (pending, stale) 且磁盘还在的补排进队
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
import time
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent / "src"))

from pdfarchiver.app import bootstrap  # noqa: E402
from pdfarchiver.config.paths import AppPaths  # noqa: E402

# 阶段 1 验收第 6 条：与 bootstrap() 取同一个库路径，不在脚本里钉死开发机路径。
DB = AppPaths.resolve().catalog_db


def queue_snapshot() -> dict[str, int]:
    conn = sqlite3.connect(DB)
    try:
        jobs = dict(conn.execute("SELECT state, COUNT(*) FROM processing_jobs GROUP BY state").fetchall())
        fts = {f"fts_{r[0]}": r[1] for r in conn.execute(
            "SELECT fts_status, COUNT(*) FROM documents GROUP BY fts_status").fetchall()}
        jobs.update(fts)
        return jobs
    finally:
        conn.close()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-hours", type=float, default=8.0)
    ap.add_argument("--check-only", action="store_true")
    args = ap.parse_args()

    snap = queue_snapshot()
    print("当前队列状态：")
    for k, v in sorted(snap.items()):
        print(f"  {k:20s} {v}")

    if args.check_only:
        return 0

    remaining = snap.get("queued", 0) + snap.get("running", 0)
    if remaining == 0 and snap.get("fts_pending", 0) + snap.get("fts_stale", 0) == 0:
        print("队列已空，无需续跑。")
        return 0

    ctx = bootstrap()
    queue = ctx.start_background()
    print(f"\n后台已启动：worker {queue.thread_count}，待排空 {remaining} 条")

    t0 = time.time()
    max_s = args.max_hours * 3600
    last_done = -1
    try:
        while time.time() - t0 < max_s:
            time.sleep(30)
            snap = queue_snapshot()
            pending = snap.get("queued", 0) + snap.get("running", 0)
            done = snap.get("done", 0)
            elapsed = time.time() - t0
            rate = (done - last_done) / 60 if last_done >= 0 and elapsed > 0 else 0
            print(f"[{elapsed/60:5.1f} min] 剩余 {pending:5d}  done={done}  (+{rate:.1f}/min)")
            last_done = done
            if pending == 0:
                print(f"\n队列已排空，本次续跑 {elapsed/60:.1f} 分钟")
                fts_done = snap.get("fts_done", 0)
                fts_failed = snap.get("fts_failed", 0)
                print(f"文档索引：done={fts_done}  failed={fts_failed}")
                break
    finally:
        ctx.shutdown()

    snap = queue_snapshot()
    pending = snap.get("queued", 0) + snap.get("running", 0)
    return 0 if pending == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
