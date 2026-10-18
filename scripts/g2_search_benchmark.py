"""G2 搜索 P95 实测 —— 真库、真 SearchService 入口、20 条查询。

判据（docs/TESTING.md G2）：端到端（含 bm25 排序 + snippet，200 候选）P95 ≤ 500ms [反算]。
p1 的线性外推提示 202 万行时基线可能顶不住，这一轮就是"先做 L4 实测定分片策略"的那一步：
量当前真实行数下的 P95，并留行数读数供外推。

方法：
- 20 条查询 ×（1 次预热 + 5 次计时）= 100 个计时样本
- 每次走 SearchService.search(Criteria(limit=200))，取 SearchResult.took_ms（服务自己量的端到端）
- P50/P95/P99/max 全列，末行 VERDICT

用法：
    python scripts/g2_search_benchmark.py
    python scripts/g2_search_benchmark.py --reps 8
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import statistics
import sys
import time
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent / "src"))

from pdfarchiver.app import bootstrap  # noqa: E402
from pdfarchiver.config.paths import AppPaths  # noqa: E402
from pdfarchiver.search.service import Criteria  # noqa: E402

# 阶段 1 验收第 6 条：脚本也不许依赖开发机上的固定绝对路径 —— 与 bootstrap() 同一个来源。
_PATHS = AppPaths.resolve()
DB = _PATHS.catalog_db
OUT = _PATHS.logs_dir / "g2_benchmark.json"

# 20 条查询：≥3 字走 FTS trigram；1–2 字走 LIKE 回退（已知最慢通道，必须进样本）；
# 覆盖正文/文件名/路径/元数据四通道与中英混合。
QUERIES = [
    "机器学习",          # 1 四字正文
    "深度学习",          # 2
    "人工智能",          # 3
    "调查报告",          # 4
    "合同条款",          # 5
    "数据分析",          # 6
    "北京",              # 7 两字（LIKE 回退）
    "发票",              # 8 两字（LIKE 回退）
    "PDF",              # 9 英文三字母
    "engineering",      # 10 英文长词
    "可持续发展",        # 11 五字
    "城市规划",          # 12
    "环境影响评价",      # 13 六字
    "财务审计",          # 14
    "技术规范",          # 15
    "施工组织设计",      # 16 六字
    "教育",              # 17 两字（LIKE 回退）
    "法律",              # 18 两字（LIKE 回退）
    "说明书",            # 19
    "quarterly report", # 20 英文短语
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reps", type=int, default=5, help="每条查询的计时次数（另加 1 次预热）")
    args = ap.parse_args()

    # `str(DB)` 在 Windows 上是反斜杠路径，而 URI 形式里反斜杠会被 sqlite3 当转义符吃掉 ——
    # 这条脚本第一次真跑就栽在这里（`sqlite3.OperationalError: unable to open database file`）。
    conn = sqlite3.connect(f"file:{DB.as_posix()}?mode=ro", uri=True)
    rows_pages = conn.execute("SELECT COUNT(*) FROM text_pages").fetchone()[0]
    docs_done = conn.execute("SELECT COUNT(*) FROM documents WHERE fts_status='done'").fetchone()[0]
    docs_total = conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
    conn.close()
    print(f"库读数：documents done={docs_done}/{docs_total}  text_pages={rows_pages:,} 行")
    print(f"判据：P95 ≤ 500ms（G2 基线）｜样本 = {len(QUERIES)} 查询 × {args.reps} 次 + 预热")
    print()

    ctx = bootstrap()
    try:
        results = []
        all_ms: list[float] = []
        for q in QUERIES:
            # 预热 1 次（页缓存冷，不计入）
            warm = ctx.search.search(Criteria(text=q, limit=200))
            samples = []
            for _ in range(args.reps):
                r = ctx.search.search(Criteria(text=q, limit=200))
                samples.append(r.took_ms)
            all_ms.extend(samples)
            hit = len(warm.hits)
            qmax = max(samples)
            qmed = statistics.median(samples)
            results.append({"query": q, "samples_ms": samples, "median_ms": qmed,
                            "max_ms": qmax, "hits": hit})
            print(f"  {q!r:24s} med={qmed:7.1f}ms  max={qmax:7.1f}ms  hits={hit}")

        all_ms.sort()
        n = len(all_ms)
        p50 = all_ms[int(n * 0.50)]
        p95 = all_ms[min(int(n * 0.95), n - 1)]
        p99 = all_ms[min(int(n * 0.99), n - 1)]
        worst = max(results, key=lambda r: r["max_ms"])

        print()
        print(f"样本数: {n}")
        print(f"P50 = {p50:.1f}ms")
        print(f"P95 = {p95:.1f}ms")
        print(f"P99 = {p99:.1f}ms")
        print(f"max = {all_ms[-1]:.1f}ms  （最差查询：{worst['query']!r}）")
        print()

        # 外推：p1 的口径是 bm25_top50=134ms@30万行，线性到当前行数
        scale = rows_pages / 300_000 if rows_pages else 0
        # 末行必须是门禁链认的那句口径（`gates/final.py::_gate`：退出码 0 且含
        # "VERDICT: ALL GREEN"）。这里原来写的是 "GREEN"，实测让 g2 段自己判 GREEN、
        # 外层判 RED —— 同一个判定两个拼法就是两个口径，统一成链里那一个。
        green = p95 <= 500.0
        verdict = "ALL GREEN" if green else f"RED（P95={p95:.1f}ms 超 500ms）"
        print(f"行数口径：text_pages={rows_pages:,}（p1 的 30 万行 × {scale:.1f}）")
        print(f"G2 判定：P95={p95:.1f}ms vs 500ms → {verdict}")

        OUT.write_text(json.dumps({
            "benchmark": "G2",
            "measured_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "text_pages_rows": rows_pages,
            "documents_done": docs_done,
            "documents_total": docs_total,
            "queries": len(QUERIES),
            "reps_per_query": args.reps,
            "samples": n,
            "p50_ms": p50, "p95_ms": p95, "p99_ms": p99, "max_ms": all_ms[-1],
            "worst_query": worst["query"],
            "verdict": verdict,
            "per_query": results,
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"报告：{OUT}")
        print(f"VERDICT: {verdict}")
        return 0 if green else 1
    finally:
        ctx.shutdown()


if __name__ == "__main__":
    sys.exit(main())
