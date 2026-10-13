"""P0 语料普查：把 PROJECT_SPEC 2.3 里"约 5,000 份 PDF"的估算换成可计数的事实。

只读。不打开 PDF 内容，只统计路径、大小、时间戳与目录分布。

用法:
    python tests/probes/p0_corpus_census.py --roots "C:/Users/<用户名>" "H:/" --out .probe_work/p0.json --limit 600

结果写 UTF-8 JSON 文件（不写 stdout：Windows 控制台是 GBK，重定向会把中文路径写成非 UTF-8 字节）。
含个人路径，产物目录 .probe_work/ 已在 .gitignore 内，只有聚合数字进 docs/VERIFICATION.md。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import Counter
from pathlib import Path

SKIP_DIR_NAMES = {".git", "node_modules", "__pycache__", "$RECYCLE.BIN", "System Volume Information", ".venv", "venv"}


def human(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.1f}{unit}"
        n /= 1024
    return f"{n:.1f}TB"


def census(roots: list[str], limit_seconds: int) -> dict:
    deadline = time.time() + limit_seconds
    ext_counter: Counter[str] = Counter()
    pdf_dirs: Counter[str] = Counter()
    pdf_sizes: list[tuple[int, str]] = []
    per_root: dict[str, dict] = {}
    visited_dirs = 0
    timed_out = False
    unreadable: list[str] = []

    def walk(root: str) -> None:
        nonlocal visited_dirs, timed_out
        stat = {"count": 0, "bytes": 0}
        per_root[root] = stat
        stack = [root]
        while stack:
            if time.time() > deadline:
                timed_out = True
                return
            current = stack.pop()
            visited_dirs += 1
            try:
                with os.scandir(current) as it:
                    entries = list(it)
            except OSError as exc:
                unreadable.append(f"{current} :: {type(exc).__name__}: {exc.strerror or exc}")
                continue
            for e in entries:
                try:
                    if e.is_dir(follow_symlinks=False):
                        if e.name not in SKIP_DIR_NAMES:
                            stack.append(e.path)
                        continue
                    if not e.is_file(follow_symlinks=False):
                        continue
                    name = e.name
                    _, _, ext = name.partition(".")
                    key = ("." + ext.lower()) if ext else "(no ext)"
                    ext_counter[key] += 1
                    if key == ".pdf":
                        size = e.stat(follow_symlinks=False).st_size
                        pdf_sizes.append((size, e.path))
                        pdf_dirs[os.path.dirname(e.path)] += 1
                        stat["count"] += 1
                        stat["bytes"] += size
                except OSError as exc:
                    unreadable.append(f"{e.path} :: {type(exc).__name__}: {exc}")

    for r in roots:
        if Path(r).exists():
            walk(r)
        else:
            unreadable.append(f"{r} :: root missing")

    pdf_sizes.sort()
    sizes = [s for s, _ in pdf_sizes]
    total = sum(sizes)
    quart = lambda q: sizes[int((len(sizes) - 1) * q)] if sizes else 0
    top_files = [
        {"bytes": s, "human": human(s), "path": p.replace("\\", "/")}
        for s, p in pdf_sizes[-15:]
    ]
    buckets = {"<1MB": 0, "1-10MB": 0, "10-50MB": 0, "50-200MB": 0, ">=200MB": 0}
    for s in sizes:
        if s < 1_048_576:
            buckets["<1MB"] += 1
        elif s < 10_485_760:
            buckets["1-10MB"] += 1
        elif s < 52_428_800:
            buckets["10-50MB"] += 1
        elif s < 209_715_200:
            buckets["50-200MB"] += 1
        else:
            buckets[">=200MB"] += 1
    return {
        "roots": roots,
        "scanned_directories": visited_dirs,
        "timed_out": timed_out,
        "per_root": {k: {"pdf_count": v["count"], "pdf_bytes_human": human(v["bytes"])} for k, v in per_root.items()},
        "pdf_count": len(sizes),
        "pdf_total_bytes": total,
        "pdf_total_human": human(total),
        "size_buckets": buckets,
        "pdf_bytes_min": sizes[0] if sizes else 0,
        "pdf_bytes_p50": quart(0.5),
        "pdf_bytes_p90": quart(0.9),
        "pdf_bytes_p99": quart(0.99),
        "pdf_bytes_max": sizes[-1] if sizes else 0,
        "pdf_mean_bytes": int(total / len(sizes)) if sizes else 0,
        "top15_largest": top_files,
        "top20_directories_by_pdf_count": [
            {"count": c, "dir": d.replace("\\", "/")}
            for d, c in pdf_dirs.most_common(20)
        ],
        "all_extensions_top25": ext_counter.most_common(25),
        "unreadable_sample": unreadable[:20],
        "unreadable_count": len(unreadable),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--roots", nargs="+", required=True)
    ap.add_argument("--limit", type=int, default=600, help="秒级时间上限")
    ap.add_argument("--out", required=True, help="UTF-8 JSON 输出路径")
    args = ap.parse_args()
    result = census(args.roots, args.limit)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(result, fh, ensure_ascii=False, indent=2)
    print(f"pdf_count={result['pdf_count']} total={result['pdf_total_human']} "
          f"dirs={result['scanned_directories']} timed_out={result['timed_out']} -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

