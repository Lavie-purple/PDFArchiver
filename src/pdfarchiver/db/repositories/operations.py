"""操作批次与逐文件条目的仓储。

file_operations 是一次操作批次（如"归档 128 份文件"），operation_items 是批次里的每一项。
状态流转：
- file_operations.status: planned → running → done/failed
- operation_items.state: pending → copying → done/failed

journal_path 指向 JSONL 文件，每步操作前写一行，用于崩溃恢复。
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from pdfarchiver.db.engine import Engine, DatabaseError
from pdfarchiver.db.models import now_ts


@dataclass
class FileOperation:
    id: int
    kind: str
    status: str
    plan_json: str | None
    journal_path: str | None
    items_total: int
    items_done: int
    items_failed: int
    undo_of: int | None
    created_at: int
    started_at: int | None
    finished_at: int | None


@dataclass
class OperationItem:
    id: int
    op_id: int
    doc_id: int | None
    kind: str
    src_path: str
    dst_path: str | None
    state: str
    reversible: int
    error: str | None
    src_sha256: str | None
    dst_sha256: str | None
    updated_at: int


class OperationRepository:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def create_operation(self, kind: str, plan: dict | None = None,
                         journal_path: str | None = None, undo_of: int | None = None) -> FileOperation:
        """新建操作批次。"""
        conn = self.engine.thread_connection()
        ts = now_ts()
        plan_json = json.dumps(plan, ensure_ascii=False) if plan else None
        with self.engine.transaction(conn, on_error="新建操作批次失败"):
            cur = conn.execute(
                "INSERT INTO file_operations(kind, status, plan_json, journal_path, "
                "items_total, items_done, items_failed, undo_of, created_at) "
                "VALUES(?, 'planned', ?, ?, 0, 0, 0, ?, ?)",
                (kind, plan_json, journal_path, undo_of, ts))
        return FileOperation(
            id=cur.lastrowid, kind=kind, status="planned",
            plan_json=plan_json, journal_path=journal_path,
            items_total=0, items_done=0, items_failed=0,
            undo_of=undo_of, created_at=ts, started_at=None, finished_at=None)

    def add_item(self, op_id: int, doc_id: int | None, kind: str,
                 src_path: str, dst_path: str | None = None,
                 reversible: int = 1) -> OperationItem:
        """给批次添加一项。"""
        conn = self.engine.thread_connection()
        ts = now_ts()
        with self.engine.transaction(conn, on_error="添加操作项失败"):
            cur = conn.execute(
                "INSERT INTO operation_items(op_id, doc_id, kind, src_path, dst_path, "
                "state, reversible, updated_at) VALUES(?, ?, ?, ?, ?, 'pending', ?, ?)",
                (op_id, doc_id, kind, src_path, dst_path, reversible, ts))
            conn.execute("UPDATE file_operations SET items_total = items_total + 1 WHERE id=?",
                         (op_id,))
        return OperationItem(
            id=cur.lastrowid, op_id=op_id, doc_id=doc_id, kind=kind,
            src_path=src_path, dst_path=dst_path, state="pending",
            reversible=reversible, error=None, src_sha256=None, dst_sha256=None,
            updated_at=ts)

    def get_operation(self, op_id: int) -> FileOperation | None:
        row = self.engine.thread_connection().execute(
            "SELECT id, kind, status, plan_json, journal_path, items_total, items_done, "
            "items_failed, undo_of, created_at, started_at, finished_at "
            "FROM file_operations WHERE id=?", (op_id,)).fetchone()
        if not row:
            return None
        return FileOperation(**dict(row))

    def list_operations(self, limit: int = 100) -> list[FileOperation]:
        rows = self.engine.thread_connection().execute(
            "SELECT id, kind, status, plan_json, journal_path, items_total, items_done, "
            "items_failed, undo_of, created_at, started_at, finished_at "
            "FROM file_operations ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
        return [FileOperation(**dict(r)) for r in rows]

    def list_items(self, op_id: int) -> list[OperationItem]:
        rows = self.engine.thread_connection().execute(
            "SELECT id, op_id, doc_id, kind, src_path, dst_path, state, reversible, "
            "error, src_sha256, dst_sha256, updated_at "
            "FROM operation_items WHERE op_id=? ORDER BY id", (op_id,)).fetchall()
        return [OperationItem(**dict(r)) for r in rows]

    def start_operation(self, op_id: int) -> None:
        conn = self.engine.thread_connection()
        ts = now_ts()
        with self.engine.transaction(conn, on_error="启动操作批次失败"):
            conn.execute("UPDATE file_operations SET status='running', started_at=? WHERE id=?",
                         (ts, op_id))

    def finish_operation(self, op_id: int, status: str = "done") -> None:
        conn = self.engine.thread_connection()
        ts = now_ts()
        with self.engine.transaction(conn, on_error="完成操作批次失败"):
            conn.execute("UPDATE file_operations SET status=?, finished_at=? WHERE id=?",
                         (status, ts, op_id))

    def update_item_state(self, item_id: int, state: str, error: str | None = None,
                          dst_sha256: str | None = None) -> None:
        conn = self.engine.thread_connection()
        ts = now_ts()
        with self.engine.transaction(conn, on_error="更新操作项状态失败"):
            conn.execute(
                "UPDATE operation_items SET state=?, error=?, dst_sha256=?, updated_at=? WHERE id=?",
                (state, error, dst_sha256, ts, item_id))
            # 更新批次的计数
            if state == "done":
                conn.execute("UPDATE file_operations SET items_done = items_done + 1 "
                             "WHERE id IN (SELECT op_id FROM operation_items WHERE id=?)",
                             (item_id,))
            elif state == "failed":
                conn.execute("UPDATE file_operations SET items_failed = items_failed + 1 "
                             "WHERE id IN (SELECT op_id FROM operation_items WHERE id=?)",
                             (item_id,))

    def write_journal(self, journal_path: str, entry: dict) -> None:
        """写一行 journal（JSONL 格式），用于崩溃恢复。"""
        path = Path(journal_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            f.flush()
