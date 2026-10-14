"""LIKE 模式串的唯一写法。

`documents` / `text_pages` / `document_metadata` 三处都要"包含某串字"的匹配，
转义规则（`\\`、`%`、`_`）只要有一处漏了，同一句话在三个字段上就给出三种结果 ——
这正是 AGENTS.md 禁止的"一个概念多个口径"。所以这里放一份，三处 import。

配套的 SQL 一律写 `LIKE ? ESCAPE '\\'`：不声明 ESCAPE 时 SQLite 的 LIKE **没有转义符**，
`报告%` 这种真实存在的目录名会被当成通配符。
"""
from __future__ import annotations


def escape_like(text: str) -> str:
    out = text
    for ch in ("\\", "%", "_"):
        out = out.replace(ch, "\\" + ch)
    return out


def like_contains(needle: str) -> str:
    """“包含 needle”的完整模式串。空串要抛：`"%" + "" + "%"` 会匹配全表，
    调用方传空串一定是漏了前置判断，让它静默返回全部比抛错更难查。"""
    if not needle.strip():
        raise ValueError("空串不能变成 LIKE 模式：它会匹配全部行")
    return "%" + escape_like(needle.strip()) + "%"


def like_prefix(prefix: str) -> str:
    """“以 prefix 开头”的模式串，用于按目录前缀取子树。"""
    if not prefix.strip():
        raise ValueError("空前缀不能变成 LIKE 模式：它会匹配全部行")
    return escape_like(prefix.rstrip("/")) + "/%"
