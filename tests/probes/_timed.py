"""p12 逐条计时的共用件：红/绿之外，还得回答「时间花在哪一条」。

欠账出处（**轮十八 ⑥**）：`consistency` 段的真根核查与 `injection` 段加起来吃掉链里大半时间，
内部分布一直没读过数。p12 自己贴着 800 行红线（**ISSUES I58**），计时器与 `ms` 字段塞不进
它，所以 `timed()` 把耗时挂成 Row 的**动态属性**、`breakdown()` 把它们拼成一行读数 ——
读法在 p12 末尾的「逐条计时」汇总行与 `--out` JSON 的 `ms` 键里，不另立第二份口径。
"""
from __future__ import annotations

import time


def timed(fn, *args, **kwargs):
    """跑一个返回 Row 或 list[Row] 的检查函数，给每条 Row 挂上 `ms`（毫秒）。"""
    t0 = time.perf_counter()
    out = fn(*args, **kwargs)
    ms = round((time.perf_counter() - t0) * 1000, 1)
    for row in out if isinstance(out, list) else [out]:
        row.ms = ms
    return out


def breakdown(rows) -> str:
    return "｜".join(f"{r.code} {r.ms:.0f}ms" for r in rows
                     if getattr(r, "ms", None) is not None)