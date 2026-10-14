"""PDF 元数据（1:1 挂在 documents 上）读写。

SPEC 3.2 的硬口径：**缺失的元数据保留为空，不得凭空编造作者、标题或日期**。
落到代码上是两条可断言的规则：
1. 只写解析层真正读出来的字段，读不到就传 `None`，这里不做任何"看起来合理"的兜底；
2. 空字符串按"没有"处理（存 NULL）。PDF 里 `Title=""` 与"没有 Title"对用户是同一件事，
   存成空串会让界面显示一个空白字段却看不出是没有还是有，等于第二个口径。
"""
from __future__ import annotations

from dataclasses import dataclass

from pdfarchiver.db.engine import Engine
from pdfarchiver.db.repositories.documents import DocFilter, where_for_filter
from pdfarchiver.db.sqltext import like_contains

FIELDS = ("title", "author", "subject", "creator_tool", "producer",
          "pdf_created_at", "pdf_modified_at", "keywords", "language")


@dataclass(frozen=True)
class MetaHit:
    """一次元数据命中：哪份文档、哪个字段、字段原文（片段在检索层按同一函数算）。"""

    doc_id: int
    field: str
    value: str


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


class MetadataRepository:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def replace(self, doc_id: int, values: dict[str, str | None], *, source: str = "pdf_info") -> None:
        """整体替换一份文档的元数据。解析失败时传空 dict，也要落一行 `source`，
        这样状态页能区分"没解析过"和"解析了但 PDF 里什么都没有"。"""
        conn = self.engine.thread_connection()
        cleaned = {k: _clean(values.get(k)) for k in FIELDS}
        with self.engine.transaction(conn, on_error=f"写入元数据失败 doc_id={doc_id}"):
            conn.execute(
                "INSERT INTO document_metadata(doc_id, title, author, subject, creator_tool, producer,"
                " pdf_created_at, pdf_modified_at, keywords, language, source)"
                " VALUES(?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(doc_id) DO UPDATE SET"
                " title=excluded.title, author=excluded.author, subject=excluded.subject,"
                " creator_tool=excluded.creator_tool, producer=excluded.producer,"
                " pdf_created_at=excluded.pdf_created_at, pdf_modified_at=excluded.pdf_modified_at,"
                " keywords=excluded.keywords, language=excluded.language, source=excluded.source",
                (doc_id, cleaned["title"], cleaned["author"], cleaned["subject"],
                 cleaned["creator_tool"], cleaned["producer"], cleaned["pdf_created_at"],
                 cleaned["pdf_modified_at"], cleaned["keywords"], cleaned["language"], source))

    def get(self, doc_id: int) -> dict[str, str | None]:
        row = self.engine.thread_connection().execute(
            f"SELECT doc_id, {', '.join(FIELDS)}, source FROM document_metadata WHERE doc_id=?",
            (doc_id,)).fetchone()
        if row is None:
            return {}
        return {k: row[k] for k in (*FIELDS, "source")}

    def count_with(self, field: str) -> int:
        """某个元数据字段非空的文档数（状态页要知道"作者到底有多少份读得出来"）。"""
        if field not in FIELDS:
            raise ValueError(f"不是元数据字段：{field}；合法值 {list(FIELDS)}")
        conn = self.engine.thread_connection()
        return conn.execute(
            f"SELECT count(*) FROM document_metadata WHERE {field} IS NOT NULL").fetchone()[0]

    def field_hits(self, needle: str, *, filters: DocFilter, limit: int = 200) -> list[MetaHit]:
        """九个元数据字段逐个"包含"匹配，**返回命中的是哪个字段**。

        只回 doc_id 等于把口径丢了：用户看到一份文档被搜出来，却不知道是标题里
        有这个词还是 producer 里有，就没法判断这是不是一次真命中。

        筛选条件用 `documents.where_for_filter`，与文件名 / 路径 / 正文三条通道**同一份** ——
        在这里另写一遍 `missing_since IS NULL`，迟早和那边分家（AGENTS.md 禁止同类问题逐个打补丁）。
        字段名来自 `FIELDS` 白名单（拼进 SQL 的是列名，不是用户输入），值一律走参数。
        """
        inner = " UNION ALL ".join(
            f"SELECT m.doc_id, '{f}' AS field, m.{f} AS value FROM document_metadata m"
            f" WHERE m.{f} LIKE ? ESCAPE '\\'" for f in FIELDS)
        w = where_for_filter(filters)
        conn = self.engine.thread_connection()
        rows = conn.execute(
            f"SELECT x.doc_id, x.field, x.value FROM ({inner}) x"
            f" JOIN documents d ON d.id = x.doc_id{w.sql_with()} LIMIT ?",
            (like_contains(needle),) * len(FIELDS) + (*w.params, limit)).fetchall()
        return [MetaHit(doc_id=r["doc_id"], field=r["field"], value=r["value"]) for r in rows]
