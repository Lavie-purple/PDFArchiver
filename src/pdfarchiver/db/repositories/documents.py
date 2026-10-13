"""文档主记录读写。唯一口径：**一个规范化路径 = 一条主记录**（D-005，p7 实测）。

重叠监测根重复扫到同一文件时，靠 `ux_documents_path_key` 拒绝插入，
所以这里一律用 `INSERT ... ON CONFLICT(path_key) DO UPDATE`，不许先查后插（有竞态）。
"""
from __future__ import annotations

from pdfarchiver.db.engine import Engine
from pdfarchiver.db.models import Document, now_ts

_COLS = """
  id, path, path_key, name, ext, size_bytes, mtime_ns, ctime_ns, file_id, sha256,
  page_count, is_pdf, needs_pass, is_repaired, parse_status, text_status, ocr_status,
  fts_status, vector_status, category_confirmed, last_scanned_at, last_error,
  missing_since, created_at, updated_at
"""


def _to_doc(row) -> Document:
    return Document(**{k: row[k] for k in row.keys()})


class DocumentRepository:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def upsert(self, doc: Document) -> Document:
        """按 path_key 幂等写入。已存在就只刷新文件层面的事实，**不动索引状态与分类确认位**。"""
        conn = self.engine.thread_connection()
        ts = now_ts()
        if not doc.created_at:
            doc.created_at = ts
        doc.updated_at = ts
        with self.engine.transaction(conn, on_error=f"写入文档主记录失败 {doc.path}"):
            conn.execute(
                """
                INSERT INTO documents (path, path_key, name, ext, size_bytes, mtime_ns, ctime_ns,
                  file_id, sha256, page_count, is_pdf, needs_pass, is_repaired, parse_status,
                  text_status, ocr_status, fts_status, vector_status, category_confirmed,
                  last_scanned_at, last_error, missing_since, created_at, updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(path_key) DO UPDATE SET
                  size_bytes=excluded.size_bytes, mtime_ns=excluded.mtime_ns,
                  ctime_ns=excluded.ctime_ns, file_id=excluded.file_id,
                  sha256=excluded.sha256, name=excluded.name, ext=excluded.ext,
                  missing_since=NULL, updated_at=excluded.updated_at
                """,
                (doc.path, doc.path_key, doc.name, doc.ext, doc.size_bytes, doc.mtime_ns,
                 doc.ctime_ns, doc.file_id, doc.sha256, doc.page_count, doc.is_pdf, doc.needs_pass,
                 doc.is_repaired, doc.parse_status, doc.text_status, doc.ocr_status, doc.fts_status,
                 doc.vector_status, doc.category_confirmed, doc.last_scanned_at, doc.last_error,
                 doc.missing_since, doc.created_at, doc.updated_at))
        row = conn.execute(f"SELECT {_COLS} FROM documents WHERE path_key=?",
                           (doc.path_key,)).fetchone()
        return _to_doc(row)

    def get_by_path_key(self, path_key: str) -> Document | None:
        row = self.engine.thread_connection().execute(
            f"SELECT {_COLS} FROM documents WHERE path_key=?", (path_key,)).fetchone()
        return _to_doc(row) if row else None

    def get(self, doc_id: int) -> Document | None:
        row = self.engine.thread_connection().execute(
            f"SELECT {_COLS} FROM documents WHERE id=?", (doc_id,)).fetchone()
        return _to_doc(row) if row else None

    def list(self, limit: int = 500, offset: int = 0) -> list[Document]:
        rows = self.engine.thread_connection().execute(
            f"SELECT {_COLS} FROM documents ORDER BY name COLLATE NOCASE LIMIT ? OFFSET ?",
            (limit, offset)).fetchall()
        return [_to_doc(r) for r in rows]

    def count(self) -> int:
        return self.engine.thread_connection().execute("SELECT count(*) FROM documents").fetchone()[0]

    def count_missing(self) -> int:
        return self.engine.thread_connection().execute(
            "SELECT count(*) FROM documents WHERE missing_since IS NOT NULL").fetchone()[0]

    def mark_missing(self, path_key: str) -> bool:
        """文件不见了要**保留记录**（SPEC 3.2：路径不是永久身份），只打时间戳。
        时间戳只认 `now_ts()` 一个口径（UTC unix 秒），不引入本地 naive 时间。"""
        conn = self.engine.thread_connection()
        ts = now_ts()
        with self.engine.transaction(conn, on_error=f"标记缺失失败 {path_key}"):
            cur = conn.execute(
                "UPDATE documents SET missing_since=?, updated_at=? WHERE path_key=? AND missing_since IS NULL",
                (ts, ts, path_key))
        return cur.rowcount > 0

    def set_error(self, doc_id: int, message: str) -> None:
        conn = self.engine.thread_connection()
        with self.engine.transaction(conn, on_error=f"写入文档错误状态失败 doc_id={doc_id}"):
            conn.execute("UPDATE documents SET last_error=?, parse_status='failed', updated_at=? WHERE id=?",
                         (message, now_ts(), doc_id))
