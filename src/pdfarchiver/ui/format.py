"""字节数的显示口径 —— 全站一处。

这里原先没有唯一出口，`ui` 里躺着三份各写各的：`library_page._format_size` 的 GB 档是
`.1f`、`dedup_page._format_bytes` 是 `.2f`，而判重页的"浪费量"那一行又就地抄了第三遍。
同一个 500MB 在两个屏上分别写成 `0.49 GB` 与 `0.5 GB` —— AGENTS.md「禁止核心概念有多个口径」
管的正是这种数，只是之前没人把"字节怎么显示"当成一个口径。

档位按 **1024 进位**（磁盘容量口径，不是十进制营销口径），小数位固定：
GB 两位、MB/KB 一位、B 不带小数。列宽反算用得上这个形状：GB 档最宽读数 `999.99 GB`
（8 字符）、MB 档最宽 `1023.9 MB`（9 字符），两者都在 `tests/integration/test_ui_layout.py`
的"定宽列必须装得下最宽读数"里被量过。

反方向（人写的容量串 → 字节）也在这一处：`parse_size`。单独放这里而不是放在用它的
筛选条里，是因为**进位制只许有一个** —— 那边写 `× 1000 * 1000`、这边写 `× 1024 * 1024`
的话，「大小 ≥ 50 MB」这条筛选筛出来的文档数与 chip 上回显的读数就会开始对不上，
而对不上的原因藏在两个函数之间的第二个口径里，屏幕上看不出来。
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


#: 单位到字节的换算全部指回上面那三个常量，所以这里不存在第二种进位制。
_UNITS = {"KB": _KB, "MB": _MB, "GB": _GB, "B": 1}
#: 「数字 + 单位」是唯一形状，不给缺省单位：`min_size_bytes` 这个字段名写的就是字节，
#: 而让人只写 `50` 的意思在人的手感和字段的口径之间是两回事，猜错的这一次是筛出 0 份文档、
#: 屏幕上却写着「大小 ≥ 50」。所以裸数字当场拒，报错里把可写的形状列全。
_SIZE_HELP = "要写成 50 MB / 1.5 GB / 500 KB / 800 B 这样（数字 + 单位）"


def parse_size(text: str) -> int:
    """人写的容量串 → 字节。读不出来时 `ValueError` 里带着原话与可写的形状。"""
    cleaned = text.strip().upper().replace(" ", "")
    for unit in ("KB", "MB", "GB", "B"):       # `B` 放最后：`MB`/`KB` 也都以 B 结尾
        if cleaned.endswith(unit):
            number = cleaned[:-len(unit)]
            try:
                value = float(number)
            except ValueError:
                raise ValueError(f"「{text}」里的数字读不出来 —— {_SIZE_HELP}") from None
            if value < 0:
                raise ValueError(f"「{text}」是负数，大小条件没有负数这一档")
            return int(value * _UNITS[unit])
    raise ValueError(f"「{text}」读不出来 —— {_SIZE_HELP}")
