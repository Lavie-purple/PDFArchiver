"""命中片段与偏移：FTS5 里**没有** `offsets()`（D-015；p1 实测 `pragma_function_list` 只有
`rank/snippet/bm25/highlight`；ISSUES I7），所以"命中在第几个字"只能在 Python 侧算。

这一层是纯字符串：不认识数据库，不认识 PDF，不认识界面。输入是"一段文本 + 一个查询词"，
输出是"带绝对偏移的片段"。正文（`text_pages.body`）、文件名、路径、元数据值四类字段
都走同一个函数 —— 它们的片段计算没有区别，写四份只会造成四个口径。

偏移的用途很具体：界面拿到 `query_start/query_end` 才能在原文里高亮，拿到
`truncated_before/truncated_after` 才能把片段两端显示成"……"，不让用户以为句子从这里开始。

一个必须承认的边界：SQLite 的 trigram 折叠与 `str.lower()` 的折叠**不是同一张表**
（前者是 Unicode 简单折叠）。绝大多数情况一致；一旦不一致，会出现"SQLite 说这页命中了、
Python 在原文里找不到那串字"。这时**不硬凑一个偏移**，而是给一段没有高亮的页首窗口
（`matched=False`）—— 这页在结果里照样出现，只是不高亮。骗用户说命中在某个位置，
比不高亮糟糕得多。
"""
from __future__ import annotations

from dataclasses import dataclass

CONTEXT_CHARS = 90  # 片段左右各取的字符数：一行结果约容 60–80 个汉字，两侧同宽才不会把命中词挤到视野边缘
MAX_SNIPPETS = 3    # 一段文本最多给几片：重复命中时够覆盖，再多就变成整页渲染（G6 禁止）
ELLIPSIS = "…"


@dataclass(frozen=True)
class Snippet:
    """一段可直接展示的原文切片，附带它在整段原文里的坐标。"""

    text: str                 # 从原文切出来的片段，一个字都没改
    start: int                # text 在原文里的起始偏移
    end: int                  # text 在原文里的结束偏移
    query_start: int          # 命中词在原文里的起始偏移；定位不到时 -1
    query_end: int            # 命中词在原文里的结束偏移；定位不到时 -1
    matched: bool             # False = 这只是页首窗口，不代表程序找到了命中位置
    truncated_before: bool    # 前面还有原文，被窗口切掉了
    truncated_after: bool     # 后面还有原文，被窗口切掉了

    def line(self) -> str:
        """界面直接用的那一行：两端按需要加省略号，正文本身不动。"""
        return (ELLIPSIS if self.truncated_before else "") + self.text \
            + (ELLIPSIS if self.truncated_after else "")


def _fold(text: str) -> str:
    return text.lower()


def _locate(text: str, query: str, limit: int) -> list[tuple[int, int]]:
    """取前 `limit` 个互不重叠的命中区间。

    用 `str.find` 逐次后移，不是双重循环 —— 一页正文按语料实测约 1–2KB，×200 条命中行，
    O(n²) 的写法会把首屏 500ms 门禁（G2）整个吃掉。
    """
    folded_text, folded_query = _fold(text), _fold(query)
    # 折叠改变长度（土耳其语 İ、德语 ß）时，折叠串上的偏移映射不回原文，宁可不报位置
    if len(folded_text) != len(text) or len(folded_query) != len(query):
        return []
    span = len(folded_query)
    hits: list[tuple[int, int]] = []
    pos = 0
    while len(hits) < limit:
        found = folded_text.find(folded_query, pos)
        if found < 0:
            break
        hits.append((found, found + span))
        pos = found + span
    return hits


def _fallback(text: str, context: int) -> Snippet:
    left, right = 0, min(len(text), context * 2)
    return Snippet(text=text[left:right], start=left, end=right,
                   query_start=-1, query_end=-1, matched=False,
                   truncated_before=False, truncated_after=right < len(text))


def snippets_for(text: str, query: str, *, limit: int = MAX_SNIPPETS,
                 context: int = CONTEXT_CHARS) -> list[Snippet]:
    """一段文本里取最多 `limit` 片互不重叠的命中窗口；一处都没定位到时返回一片 `matched=False` 的页首窗口。

    查询词为空要当场抛：调用方一定是写错了 —— 空串进 `find` 会在 0 号位"命中"，
    于是每条结果都显示一段高亮了个空气的句子，看起来像界面坏了。
    """
    if not query.strip():
        raise ValueError("空查询没有片段可算")
    if not text:
        return []

    hits = _locate(text, query, limit * 4)  # 多要几组：两把命中靠得近会共用一个窗口，凑不满 limit 片
    out: list[Snippet] = []
    cursor = -1
    for start, end in hits:
        if len(out) >= limit:
            break
        if start <= cursor:      # 落在上一片窗口里：换下一处命中，否则同一段文字被重复展示
            continue
        left = max(0, start - context)
        right = min(len(text), end + context)
        out.append(Snippet(text=text[left:right], start=left, end=right,
                           query_start=start, query_end=end, matched=True,
                           truncated_before=left > 0, truncated_after=right < len(text)))
        cursor = right
    return out or [_fallback(text, context)]


def snippet_for(text: str, query: str, *, context: int = CONTEXT_CHARS) -> Snippet:
    return snippets_for(text, query, limit=1, context=context)[0]
