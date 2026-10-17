"""字节数的显示口径 —— 全站一处。

这里原先没有唯一出口，`ui` 里躺着三份各写各的：`library_page._format_size` 的 GB 档是
`.1f`、`dedup_page._format_bytes` 是 `.2f`，而判重页的"浪费量"那一行又就地抄了第三遍。
同一个 500MB 在两个屏上分别写成 `0.49 GB` 与 `0.5 GB` —— AGENTS.md「禁止核心概念有多个口径」
管的正是这种数，只是之前没人把"字节怎么显示"当成一个口径。

档位按 **1024 进位**（磁盘容量口径，不是十进制营销口径），小数位固定：
GB 两位、MB/KB 一位、B 不带小数。列宽反算用得上这个形状：GB 档最宽读数 `999.99 GB`
（8 字符）、MB 档最宽 `1023.9 MB`（9 字符），两者都在 `tests/integration/test_ui_layout.py`
的"定宽列必须装得下最宽读数"里被量过。
"""
from __future__ import annotations

_KB = 1024
_MB = 1024 * 1024
_GB = 1024 * 1024 * 1024


def format_bytes(n: int) -> str:
    """把字节数写成给人看的容量串。负数原样带上符号，不假装它是 0。"""
    if n < 0:
        return f"-{format_bytes(-n)}"
    if n >= _GB:
        return f"{n / _GB:.2f} GB"
    if n >= _MB:
        return f"{n / _MB:.1f} MB"
    if n >= _KB:
        return f"{n / _KB:.1f} KB"
    return f"{n} B"
