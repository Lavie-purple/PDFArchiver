"""操作批次与逐文件条目的仓储。

file_operations 是一次操作批次（如"归档 128 份文件"），operation_items 是批次里的每一项。
状态流转：
- file_operations.status: planned → previewed → running → done/partially_done/failed/undone
- operation_items.state: pending → done/failed/skipped（`copying` 那些中间态只活在 journal 里，
  不在表里 —— 见迁移 `0005_stage4_vocab` 的 CHECK 与 **D-048**）

journal_path 指向 JSONL 文件，每步操作前写一行，用于崩溃恢复。
job_id 是「队列任务 ⇄ 操作批次」的反查口径（**D-043** 第 2 条后果 / **ISSUES I43**）：
由 `claim_previewed()` 在领批次的那一刻写下，所以它指的是"真的跑掉这一批的那条任务"，
而不是提交时猜的那一条。
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from pdfarchiver.db.engine import Engine, DatabaseError
from pdfarchiver.db.models import ITEM_KINDS, ITEM_STATES, OP_STATUSES, now_ts


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
    job_id: int | None = None


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


_OP_COLS = ("id, kind, status, plan_json, journal_path, items_total, items_done, items_failed,"
            " undo_of, created_at, started_at, finished_at, job_id")


class OperationRepository:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def create_operation(self, kind: str, plan: dict | None = None,
                         journal_path: str | None = None, undo_of: int | None = None,
                         status: str = "planned") -> FileOperation:
        """新建操作批次。批次一出生停在哪个态由调用方说 —— 归档执行走 `previewed`，
        因为"用户已经在确认框上勾过"这件事发生在建批次之前。"""
        if status not in OP_STATUSES:
            raise ValueError(f"未知批次状态 {status!r}；合法值 {list(OP_STATUSES)}")
        conn = self.engine.thread_connection()
        ts = now_ts()
        plan_json = json.dumps(plan, ensure_ascii=False) if plan else None
        with self.engine.transaction(conn, on_error="新建操作批次失败"):
            cur = conn.execute(
                "INSERT INTO file_operations(kind, status, plan_json, journal_path, "
                "items_total, items_done, items_failed, undo_of, created_at) "
                "VALUES(?, ?, ?, ?, 0, 0, 0, ?, ?)",
                (kind, status, plan_json, journal_path, undo_of, ts))
        return FileOperation(
            id=cur.lastrowid, kind=kind, status=status,
            plan_json=plan_json, journal_path=journal_path,
            items_total=0, items_done=0, items_failed=0,
            undo_of=undo_of, created_at=ts, started_at=None, finished_at=None)

    def attach_journal(self, op_id: int, journal_path: str) -> None:
        """把 journal 文件路径写回批次。

        单独一句的存在理由：journal 按批次 id 命名（`op_<id>.jsonl`），而 id 要 INSERT 之后
        才知道 —— 不能在 INSERT 那句里猜一个。
        """
        conn = self.engine.thread_connection()
        with self.engine.transaction(conn, on_error=f"写 journal 路径失败 op_id={op_id}"):
            conn.execute("UPDATE file_operations SET journal_path=? WHERE id=?",
                         (journal_path, op_id))

    def claim_previewed(self, job_id: int, kinds: tuple[str, ...]) -> FileOperation | None:
        """原子领一条 `previewed` 批次：`previewed → running`，同时把领它的那条任务写进 `job_id`。

        两句在同一事务里，且 UPDATE 带着 `status='previewed'` 的条件去数 rowcount ——
        两个 worker 同时 SELECT 到同一条时只有一个能真的领走（与 `repositories/jobs.py`
        的 `claim()` 同一个形状）。领不到就返回 None，**不报错**：队列为空是正常状态。
        """
        conn = self.engine.thread_connection()
        marks = ",".join("?" * len(kinds))
        claimed: int | None = None
        with self.engine.transaction(conn, on_error="领取操作批次失败"):
            row = conn.execute(
                f"SELECT id FROM file_operations WHERE status='previewed' "
                f"AND kind IN ({marks}) ORDER BY id LIMIT 1", kinds).fetchone()
            if row:
                op_id = int(row[0])
                cur = conn.execute(
                    "UPDATE file_operations SET status='running', job_id=?, started_at=? "
                    "WHERE id=? AND status='previewed'", (job_id, now_ts(), op_id))
                if cur.rowcount == 1:
                    claimed = op_id
        return self.get_operation(claimed) if claimed is not None else None

    def add_item(self, op_id: int, doc_id: int | None, kind: str,
                 src_path: str, dst_path: str | None = None,
                 reversible: int = 1, state: str = "pending",
                 error: str | None = None) -> OperationItem:
        """给批次添加一项。计划阶段就能判定不做的项直接以 `skipped` 落库并带上原因，
        它不进 journal（**D-048**：journal 只记真动过的）。"""
        if state not in ITEM_STATES:
            raise ValueError(f"未知操作项状态 {state!r}；合法值 {list(ITEM_STATES)}")
        if kind not in ITEM_KINDS:
            raise ValueError(f"未知操作项类型 {kind!r}；合法值 {list(ITEM_KINDS)}（改名不是第三种"
                             "类型：模板换名后 src≠dst，它仍然是一次 move）")
        conn = self.engine.thread_connection()
        ts = now_ts()
        with self.engine.transaction(conn, on_error="添加操作项失败"):
            cur = conn.execute(
                "INSERT INTO operation_items(op_id, doc_id, kind, src_path, dst_path, "
                "state, reversible, error, updated_at) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (op_id, doc_id, kind, src_path, dst_path, state, reversible, error, ts))
            conn.execute("UPDATE file_operations SET items_total = items_total + 1 WHERE id=?",
                         (op_id,))
        return OperationItem(
            id=cur.lastrowid, op_id=op_id, doc_id=doc_id, kind=kind,
            src_path=src_path, dst_path=dst_path, state=state,
            reversible=reversible, error=error, src_sha256=None, dst_sha256=None,
            updated_at=ts)

    def get_operation(self, op_id: int) -> FileOperation | None:
        row = self.engine.thread_connection().execute(
            f"SELECT {_OP_COLS} FROM file_operations WHERE id=?", (op_id,)).fetchone()
        if not row:
            return None
        return FileOperation(**dict(row))

    def list_operations(self, limit: int = 100) -> list[FileOperation]:
        rows = self.engine.thread_connection().execute(
            f"SELECT {_OP_COLS} FROM file_operations ORDER BY created_at DESC, id DESC "
            "LIMIT ?", (limit,)).fetchall()
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
        """终态只认 `models.OP_STATUSES`。

        这里是故意拦而不是"看起来对不对"：执行器曾经写过 `"partial"`，而那个值既不在代码口径
        里、也不在 `docs/DATABASE.md` §二 的词表里，台账上就会留下一条没人认识的状态。
        """
        if status not in OP_STATUSES:
            raise ValueError(f"未知批次状态 {status!r}；合法值 {list(OP_STATUSES)}")
        conn = self.engine.thread_connection()
        ts = now_ts()
        with self.engine.transaction(conn, on_error="完成操作批次失败"):
            conn.execute("UPDATE file_operations SET status=?, finished_at=? WHERE id=?",
                         (status, ts, op_id))

    def update_item_state(self, item_id: int, state: str, error: str | None = None,
                          dst_sha256: str | None = None,
                          src_sha256: str | None = None) -> None:
        if state not in ITEM_STATES:
            raise ValueError(f"未知操作项状态 {state!r}；合法值 {list(ITEM_STATES)}")
        conn = self.engine.thread_connection()
        ts = now_ts()
        with self.engine.transaction(conn, on_error="更新操作项状态失败"):
            conn.execute(
                "UPDATE operation_items SET state=?, error=?, dst_sha256=?, src_sha256=?,"
                " updated_at=? WHERE id=?",
                (state, error, dst_sha256, src_sha256, ts, item_id))
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
