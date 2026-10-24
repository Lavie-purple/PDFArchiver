"""库体检取数 —— S7 的「库体检」面板与离线探针 p12 共用同一批口径。

这里只放**读数所需的 SQL 与 PRAGMA**，判定文案在 `services/db_check.py`，界面只负责显示。
四条纪律（与 p12 同源，别在这里另立一套）：

1. **只读**：不写库、不动文件；快照只以 `mode=ro` 打开。唯一会写库的是服务层最后记下的
   「上次体检时间与计数」，那是 `app_settings` 里的一行应用状态。
2. **合法取值 import 自写这个字段的那一处**：`text_status` 的 `pending` 由扫描层写、
   `parse_status` 的 `ok/degraded/failed` 由索引层写、`fts_status` 取
   `documents.SEARCHABLE_STATUSES`、队列两列取 `jobs.STATES/KINDS` —— 这里不另列名单。
3. **耗时与库同量级的项只给 full 档**：`PRAGMA integrity_check` 在 11GB 真库实测约 18 分钟、
   `foreign_key_check` 与正文扫描同量级，`quick` 档一条都不发。
4. **快照目录由调用方传入**（`AppPaths.backups_dir`）：仓储层不猜路径。
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from pdfarchiver.db.engine import Engine
from pdfarchiver.db.models import ITEM_STATES, OP_STATUSES, VECTOR_STATUSES
from pdfarchiver.db.repositories.documents import SEARCHABLE_STATUSES
from pdfarchiver.db.repositories.jobs import KINDS, STATES
from pdfarchiver.parsing.classify import OCR_STATUSES, TEXT_STATUSES

# 允许值一律取自"写这个字段的那一处"：
#   text_status ← parsing/classify.TEXT_STATUSES（"还没解析过"由扫描层写 pending）
#   parse_status ← services/index_service._parse_status（ok/degraded/failed）+ 扫描层 pending
#   fts_status   ← documents.SEARCHABLE_STATUSES
#   vector_status ← db/models.VECTOR_STATUSES
TEXT_LEGAL = frozenset(TEXT_STATUSES) | {"pending"}
PARSE_LEGAL = frozenset({"pending", "ok", "degraded", "failed"})
OCR_LEGAL = frozenset(OCR_STATUSES)
VECTOR_LEGAL = frozenset(VECTOR_STATUSES)

STATUS_DOMAINS: tuple[tuple[str, str, frozenset[str]], ...] = (
    ("documents", "text_status", TEXT_LEGAL),
    ("documents", "parse_status", PARSE_LEGAL),
    ("documents", "ocr_status", OCR_LEGAL),
    ("documents", "fts_status", frozenset(SEARCHABLE_STATUSES)),
    ("processing_jobs", "state", frozenset(STATES)),
    ("processing_jobs", "kind", frozenset(KINDS)),
)


def _scalar(conn: sqlite3.Connection, sql: str, *args) -> object:
    return conn.execute(sql, args).fetchone()[0]


class HealthRepository:
    """一个库文件 = 一个 Engine；这里不缓存任何读数（缓存只会让"读到旧数"变成 bug）。"""

    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    # ---- 结构 ----

    def schema_version(self) -> int:
        conn = self.engine.thread_connection()
        has_table = conn.execute(
            "SELECT count(*) FROM sqlite_master WHERE name='schema_version' AND type='table'"
        ).fetchone()[0]
        if not has_table:
            return 0
        return int(_scalar(conn, "SELECT coalesce(max(version), 0) FROM schema_version"))

    # ---- 主记录 ----

    def document_count(self) -> int:
        return int(_scalar(self.engine.thread_connection(), "SELECT count(*) FROM documents"))

    def document_path_keys(self) -> list[tuple[str, str]]:
        """`(path, path_key)` 全量 —— 真库 10,991 行，主记录这一档不需要分批。"""
        rows = self.engine.thread_connection().execute(
            "SELECT path, path_key FROM documents").fetchall()
        return [(r["path"], r["path_key"]) for r in rows]

    # ---- 正文与索引花名册 ----

    def text_page_count(self) -> int:
        return int(_scalar(self.engine.thread_connection(), "SELECT count(*) FROM text_pages"))

    def fts_roster_count(self) -> int:
        return int(_scalar(self.engine.thread_connection(),
                           "SELECT count(*) FROM content_fts_docsize"))

    def fts_gaps(self) -> tuple[int, int]:
        """(漏索引, 花名册残留)。两条 `NOT IN` 在真库各扫描约 200 万行，只给 full 档。"""
        conn = self.engine.thread_connection()
        unindexed = int(_scalar(conn, "SELECT count(*) FROM text_pages tp"
                                      " WHERE tp.rowid NOT IN (SELECT id FROM content_fts_docsize)"))
        stale = int(_scalar(conn, "SELECT count(*) FROM content_fts_docsize"
                                  " WHERE id NOT IN (SELECT rowid FROM text_pages)"))
        return unindexed, stale

    def text_page_totals(self) -> tuple[int, int]:
        conn = self.engine.thread_connection()
        return (int(_scalar(conn, "SELECT count(*) FROM text_pages")),
                int(_scalar(conn, "SELECT count(*) FROM text_pages WHERE source_kind='ocr'")))

    def text_page_structure(self) -> dict[str, int]:
        """C5 里不读正文的四项；`char_count` 与 NUL 由 `text_page_char_candidates` 定生死。"""
        conn = self.engine.thread_connection()
        return {
            "kind_bad": int(_scalar(conn, "SELECT count(*) FROM text_pages"
                                          " WHERE source_kind NOT IN ('native','ocr')")),
            "ocr_no_version": int(_scalar(conn, "SELECT count(*) FROM text_pages"
                                                " WHERE source_kind='ocr' AND ocr_version IS NULL")),
            "native_with_version": int(_scalar(
                conn, "SELECT count(*) FROM text_pages"
                      " WHERE source_kind='native' AND ocr_version IS NOT NULL")),
            "empty_body": int(_scalar(conn, "SELECT count(*) FROM text_pages WHERE body=''")),
        }

    def text_page_char_candidates(self) -> list[sqlite3.Row]:
        """`char_count <> length(body)` 的安全超集（**ISSUES I90** 甲）。

        产品写的 `char_count` 恒等于 Python `len(body)`，两者只在正文夹 U+0000 时与 SQL
        `length(body)` 分家 —— 所以真正字数写错的行必然进候选，不会漏报。
        """
        return self.engine.thread_connection().execute(
            "SELECT doc_id, page_no, char_count, body FROM text_pages"
            " WHERE char_count <> length(body)").fetchall()

    def page_range_counts(self) -> tuple[int, int, int]:
        """(超页, 页码<1, 同页重复)。"""
        conn = self.engine.thread_connection()
        over = int(_scalar(conn, "SELECT count(*) FROM text_pages tp"
                                 " JOIN documents d ON d.id = tp.doc_id"
                                 " WHERE d.page_count IS NOT NULL AND tp.page_no > d.page_count"))
        below = int(_scalar(conn, "SELECT count(*) FROM text_pages WHERE page_no < 1"))
        dup = int(_scalar(conn, "SELECT count(*) FROM (SELECT doc_id, page_no FROM text_pages"
                                " GROUP BY doc_id, page_no HAVING count(*) > 1)"))
        return over, below, dup

    # ---- 状态取值域 ----

    def status_domain_violations(self) -> list[tuple[str, str, int, list[str]]]:
        """六列里越界的行数与出现值。全为空列表 = 六列全部合法。"""
        conn = self.engine.thread_connection()
        out: list[tuple[str, str, int, list[str]]] = []
        for table, column, legal in STATUS_DOMAINS:
            marks = ",".join("?" * len(legal))
            args = sorted(legal)
            n = int(_scalar(conn, f"SELECT count(*) FROM {table} WHERE {column} NOT IN ({marks})", *args))
            if not n:
                continue
            values = [r[0] for r in conn.execute(
                f"SELECT DISTINCT {column} FROM {table} WHERE {column} NOT IN ({marks})", args)]
            out.append((table, column, n, values))
        return out

    def vector_status_distribution(self) -> dict[str, int]:
        return {r[0]: int(r[1]) for r in self.engine.thread_connection().execute(
            "SELECT vector_status, count(*) FROM documents GROUP BY vector_status")}

    def vector_domain_violations(self) -> tuple[int, list[str]]:
        conn = self.engine.thread_connection()
        legal = sorted(VECTOR_LEGAL)
        marks = ",".join("?" * len(legal))
        n = int(_scalar(conn, f"SELECT count(*) FROM documents"
                              f" WHERE vector_status NOT IN ({marks})", *legal))
        values = [r[0] for r in conn.execute(
            f"SELECT DISTINCT vector_status FROM documents WHERE vector_status NOT IN ({marks})",
            legal)] if n else []
        return n, values

    def operation_distributions(self) -> tuple[dict[str, int], dict[str, int]]:
        conn = self.engine.thread_connection()
        ops = {r[0]: int(r[1]) for r in conn.execute(
            "SELECT status, count(*) FROM file_operations GROUP BY status")}
        items = {r[0]: int(r[1]) for r in conn.execute(
            "SELECT state, count(*) FROM operation_items GROUP BY state")}
        return ops, items

    # ---- 队列 ----

    def job_state_distribution(self) -> dict[str, int]:
        return {r[0]: int(r[1]) for r in self.engine.thread_connection().execute(
            "SELECT state, count(*) FROM processing_jobs GROUP BY state")}

    # ---- 分类树 ----

    def category_rows(self) -> list[dict]:
        return [dict(r) for r in self.engine.thread_connection().execute(
            "SELECT id, name, parent_id, name_path FROM categories")]

    def dangling_document_categories(self) -> int:
        return int(_scalar(self.engine.thread_connection(),
                           "SELECT count(*) FROM document_categories dc"
                           " WHERE NOT EXISTS (SELECT 1 FROM documents d WHERE d.id = dc.doc_id)"))

    # ---- 监测根 ----

    def root_rows(self) -> list[dict]:
        return [dict(r) for r in self.engine.thread_connection().execute(
            "SELECT root_path, root_key FROM monitored_roots")]

    # ---- 健康（PRAGMA；只给 full 档） ----

    def integrity(self) -> tuple[bool, str]:
        """主库的 `integrity_check` + `foreign_key_check`。绝不抛 —— 损坏要能被读出来上报。"""
        try:
            conn = self.engine.connect()
        except Exception as exc:  # noqa: BLE001 - 打不开也是体检结论，原文必须回到界面上
            return False, f"打不开：{type(exc).__name__}: {exc}"
        try:
            integrity = [r[0] for r in conn.execute("PRAGMA integrity_check").fetchall()]
            fks = [tuple(r) for r in conn.execute("PRAGMA foreign_key_check").fetchall()]
        except sqlite3.DatabaseError as exc:
            return False, f"读不动：{type(exc).__name__}: {exc}"
        finally:
            conn.close()
        if integrity == ["ok"] and not fks:
            return True, "integrity_check=ok｜foreign_key_check 0 条"
        return False, f"integrity_check={integrity[:3]}｜外键违规 {len(fks)} 条 {fks[:3]}"

    def snapshot_version(self, path: Path) -> int:
        """迁移前的第一份快照来自空库：那时连 `schema_version` 都没有，v0 是正当取值。"""
        conn = _ro(path)
        try:
            has_table = conn.execute(
                "SELECT count(*) FROM sqlite_master WHERE name='schema_version' AND type='table'"
            ).fetchone()[0]
            if not has_table:
                return 0
            return int(_scalar(conn, "SELECT coalesce(max(version), 0) FROM schema_version"))
        finally:
            conn.close()

    def snapshot_health(self, path: Path) -> tuple[bool, str]:
        conn = _ro(path)
        try:
            integrity = [r[0] for r in conn.execute("PRAGMA integrity_check").fetchall()]
            fks = [tuple(r) for r in conn.execute("PRAGMA foreign_key_check").fetchall()]
        except sqlite3.DatabaseError as exc:
            return False, f"读不动：{type(exc).__name__}: {exc}"
        finally:
            conn.close()
        if integrity == ["ok"] and not fks:
            return True, "integrity_check=ok｜foreign_key_check 0 条"
        return False, f"integrity_check={integrity[:3]}｜外键违规 {len(fks)} 条 {fks[:3]}"


def _ro(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{Path(path).as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


# 状态取值域两列给 C8 用：合法值仍取 `db/models`，不在这里另写一份
OPERATION_DOMAINS = (("file_operations", "status", frozenset(OP_STATUSES)),
                     ("operation_items", "state", frozenset(ITEM_STATES)))
