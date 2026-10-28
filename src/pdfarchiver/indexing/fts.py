"""全文检索的**口径层**：一条查询该走 FTS 还是走 LIKE，以及怎么把用户输入变成安全的 FTS 表达式。

这里只有纯字符串计算，没有 SQL（SQL 全部在 `db/repositories/text.py`，
因为架构守卫规定只有仓储层能出现 SQL 片段 —— docs/ARCHITECTURE 一）。
分开放不是为了好看：**MATCH 表达式必须由这一层负责转义**，
把用户原话直接塞进 `MATCH` 等于把 `"、AND、NEAR、()` 交给用户当运算符用。

两条实测结论（p1）：
- trigram 需要 **≥3 个字符**才能组出一个 gram。2 字中文查询走 FTS 命中 **0**，
  所以 1–2 字查询必须退回 LIKE（30 万行实测 499ms/424ms —— 慢，但**不是 0 结果**）。
- LIKE 回退必须**在结果里标注口径**。用户搜"人工"看到 0 条时，他会认为搜索坏了；
  看到"慢速匹配 3 条"才知道是自己在用一个太短的查询。
"""
from __future__ import annotations

MIN_FTS_CHARS = 3  # p1：trigram 的 gram 长度
VIA_FTS = "fts"
VIA_LIKE = "like_fallback"

LIKE_SCAN_WARNING = "1–2 字查询无法用 trigram 索引，已退回全文扫描"


def match_expression(query: str) -> str:
    """把任意用户输入变成一个 FTS5 **短语**表达式。

    规则只有一条：外层加双引号，内部的 `"` 翻倍。这样 `"人工智能"` 是一个三字短语，
    而用户输入里的 `AND`、`OR`、`NEAR`、括号、`*` 全部退化为普通字符 ——
    不转义的话，搜 `3 AND 5` 会被当成布尔表达式，搜 `a(` 会直接报语法错。
    """
    text = query.strip()
    if not text:
        raise ValueError("空查询不进 FTS")
    return '"' + text.replace('"', '""') + '"'


def channel_for(query: str) -> str:
    """这条查询该走哪个通道。判据是**字符数**，与中英文无关：
    trigram 按 Unicode 码位组 gram，一个汉字和一个字母都算一个字符。"""
    return VIA_FTS if len(query.strip()) >= MIN_FTS_CHARS else VIA_LIKE


def describe_channel(channel: str, query: str) -> str:
    if channel == VIA_FTS:
        return f"trigram 短语检索（{len(query.strip())} 字）"
    return f"慢速全文扫描 LIKE（{len(query.strip())} 字，<{MIN_FTS_CHARS} 字无法用索引）"


def format_bm25(score: float) -> str:
    """bm25 读数的唯一格式（`SearchResult.explain` 的正文分支用它）。

    小库里这个数的绝对值会落到 1e-3 以下，两位小数直接量化成 `0.00` / `-0.00`——
    那与「这条通道没有得分」长得一模一样，正是**ISSUES I11**「界面不许伪装」要防的那类读数。
    量化到 0.00 的那一档改说「≈0」：有多少说多少，不印一个看着像坏了的小数。
    """
    return f"{score:.2f}" if abs(score) >= 0.005 else "≈0"
