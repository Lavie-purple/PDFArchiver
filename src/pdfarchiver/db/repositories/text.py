"""正文页与全文索引读写 —— SQL 只许出现在这一层（docs/ARCHITECTURE 一）。

三条来自实测的规矩，改动前先看：

1. **外部内容表的正文只有一份**（在 `text_pages`），`content_fts` 里只有倒排。
   所以写入必须走 `text_pages`，由三条触发器同步索引；直接写 `content_fts` 会把两边写歪。
2. **删一份文档的正文 = 删 `text_pages` 的行**，触发器负责从索引里摘干净。
   `delete` 命令漏带 `old.body` 时 SQLite 不报错，只留幽灵行（p1 `delete_trigger_trap`）——
   所以这里配了 `ghost_row_count()`，G10 每次门禁都数一遍。
3. **短查询走 LIKE**。trigram 需要 ≥3 个字符才能构成一个 gram（p1：2 字词 trigram 命中 0），
   1–2 字查询由 `search` 层显式选 LIKE 通道，并在结果里标明用的是哪种口径，不许静默返回 0 条。
"""
from __future__ import annotations

from dataclasses import dataclass

from pdfarchiver.db.engine import Engine
from pdfarchiver.db.models import TextPage, now_ts
from pdfarchiver.db.repositories.documents import DocFilter, where_for_filter
from pdfarchiver.db.sqltext import like_contains


@dataclass(frozen=True)
class PageHit:
    """一条正文命中。`body` 是整页文本，片段由 `indexing/snippets.py` 在 Python 侧算
    （FTS5 没有 `offsets()`，D-015）。"""

    doc_id: int
    page_no: int
    body: str
    source_kind: str
    score: float


class TextRepository:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def replace_pages(self, doc_id: int, pages: list[TextPage]) -> int:
        """整体替换某文档的正文页。删旧 + 插新在**一个事务**里：
        中途失败要么全不做，要么全做完，不许留下"半本正文 + fts_status=done"。"""
        conn = self.engine.thread_connection()
        ts = now_ts()
        with self.engine.transaction(conn, on_error=f"写入正文失败 doc_id={doc_id}"):
            conn.execute("DELETE FROM text_pages WHERE doc_id=?", (doc_id,))
            conn.executemany(
                "INSERT INTO text_pages(doc_id, page_no, source_kind, char_count, body, indexed_at)"
                " VALUES(?,?,?,?,?,?)",
                [(doc_id, p.page_no, p.source_kind, p.char_count, p.body, ts) for p in pages])
        return len(pages)

    def delete_for_doc(self, doc_id: int) -> int:
        conn = self.engine.thread_connection()
        with self.engine.transaction(conn, on_error=f"清除正文失败 doc_id={doc_id}"):
            cur = conn.execute("DELETE FROM text_pages WHERE doc_id=?", (doc_id,))
        return cur.rowcount

    def count_pages(self, doc_id: int) -> int:
        """这份文档在库里有几页正文。走 `ux_text_pages_doc_page` 的覆盖扫描，不碰 `body` 列 ——
        短路判据用它而不是 `pages_of`：后者为了数个数把整本文本拷进内存，
        946 页的文档就是白读一遍（p2 最大单文件实测）。"""
        return self.engine.thread_connection().execute(
            "SELECT count(*) FROM text_pages WHERE doc_id=?", (doc_id,)).fetchone()[0]

    def pages_of(self, doc_id: int) -> list[TextPage]:
        rows = self.engine.thread_connection().execute(
            "SELECT doc_id, page_no, source_kind, char_count, body FROM text_pages"
            " WHERE doc_id=? ORDER BY page_no", (doc_id,)).fetchall()
        return [TextPage(**dict(r)) for r in rows]

    def search_fts(self, match: str, filters: DocFilter, *, limit: int = 200) -> list[PageHit]:
        """trigram 短语检索。`match` 必须是 `indexing.fts.match_expression()` 产出的**已转义**串，
        不能是用户原始输入 —— FTS5 查询语法里的 `"`、`(`、`AND` 会被当成运算符。

        筛选条件走 `documents.where_for_filter`，与文件名 / 路径 / 元数据三条通道**同一份**：
        同一次检索里"按分类筛完搜正文"和"按分类筛完看文件名"必须得到同一批候选文档。
        JOIN documents 还兜住了安全要求「文件删除后不许继续显示虚假的有效结果」——
        默认口径就带 `missing_since IS NULL`，被删掉的文件的正文根本进不了结果集。
        """
        w = where_for_filter(filters)
        rows = self.engine.thread_connection().execute(
            "SELECT tp.doc_id, tp.page_no, tp.body, tp.source_kind, bm25(content_fts) AS score"
            " FROM content_fts JOIN text_pages tp ON tp.rowid = content_fts.rowid"
            f" JOIN documents d ON d.id = tp.doc_id{w.sql_with('content_fts MATCH ?')}"
            " ORDER BY score LIMIT ?",
            (*w.params, match, limit)).fetchall()
        return [PageHit(**dict(r)) for r in rows]

    def search_like(self, needle: str, filters: DocFilter, *, limit: int = 200) -> list[PageHit]:
        """1–2 字查询的 LIKE 通道：`score` 恒为 0（LIKE 没有相关性得分），
        排序退回"文档序 + 页序"。界面必须显示"慢速匹配"，因为这条是全文扫描（p1：30 万行 499ms）。"""
        w = where_for_filter(filters)
        rows = self.engine.thread_connection().execute(
            "SELECT tp.doc_id, tp.page_no, tp.body, tp.source_kind, 0.0 AS score"
            " FROM text_pages tp JOIN documents d ON d.id = tp.doc_id"
            + w.sql_with(r"tp.body LIKE ? ESCAPE '\'")
            + " ORDER BY tp.doc_id, tp.page_no LIMIT ?",
            (*w.params, like_contains(needle), limit)).fetchall()
        return [PageHit(**dict(r)) for r in rows]

    def ghost_row_count(self) -> int:
        """G10：索引里指向已不存在的正文行的条目数。正确实现下必须是 0。"""
        conn = self.engine.thread_connection()
        return conn.execute(
            "SELECT count(*) FROM content_fts WHERE rowid NOT IN (SELECT rowid FROM text_pages)").fetchone()[0]

    def rebuild_all(self) -> None:
        """让外部内容表与内容表重新对齐（`text_pages` 是真身，索引只是投影）。"""
        conn = self.engine.thread_connection()
        with self.engine.transaction(conn, on_error="全文索引重建失败"):
            conn.execute("INSERT INTO content_fts(content_fts) VALUES('rebuild')")

    def stats(self) -> dict[str, int]:
        conn = self.engine.thread_connection()
        pages = conn.execute("SELECT count(*) FROM text_pages").fetchone()[0]
        docs = conn.execute("SELECT count(DISTINCT doc_id) FROM text_pages").fetchone()[0]
        chars = conn.execute("SELECT coalesce(sum(char_count), 0) FROM text_pages").fetchone()[0]
        return {"pages": pages, "docs": docs, "chars": chars}
