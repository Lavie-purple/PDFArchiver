"""操作批次与逐文件条目的仓储。

file_operations 是一次操作批次（如"归档 128 份文件"），operation_items 是批次里的每一项。
状态流转：
- file_operations.status: planned → previewed → running → done/partially_done/failed/undone
- operation_items.state: pending → done/failed/skipped（`copying` 那些中间态只活在 journal 里，
  不在表里 —— 见迁移 `0005_stage4_vocab` 的 CHECK 与 **D-048**）

journal_path 指向 JSONL 文件，每步操作前写一行，用于崩溃恢复。
批次的 `kind` 只有 `archive`（正向）与 `undo`（反向，**D-043** 甲：另开一条批次而不是改原行），
「已归档」那一列的口径就靠这个值把撤销写下的那几行排除掉 —— 见 `last_archive_destinations()`
与 **ISSUES I78** 丙。
job_id 是「队列任务 ⇄ 操作批次」的反查口径（**D-043** 第 2 条后果 / **ISSUES I43**）：
由 `claim_previewed()` 在领批次的那一刻写下，所以它指的是"真的跑掉这一批的那条任务"，
而不是提交时猜的那一条。
"""
from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from pdfarchiver.db.engine import Engine, DatabaseError
from pdfarchiver.db.models import ITEM_KINDS, ITEM_STATES, OP_STATUSES, now_ts
from pdfarchiver.db.repositories.documents import MAX_BULK_IDS


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

    def count_operations(self) -> int:
        """库里到底有几条操作批次 —— S4 那句「共 N 条」的唯一出处（**ISSUES I76**）。

        必须与 `list_operations` 的默认 `limit` 分开存在：屏上只报取回的条数会把"没列出来"
        说成"不存在"，口径同 **ISSUES I51**。
        """
        row = self.engine.thread_connection().execute(
            "SELECT count(*) FROM file_operations").fetchone()
        return int(row[0])

    def list_items(self, op_id: int) -> list[OperationItem]:
        rows = self.engine.thread_connection().execute(
            "SELECT id, op_id, doc_id, kind, src_path, dst_path, state, reversible, "
            "error, src_sha256, dst_sha256, updated_at "
            "FROM operation_items WHERE op_id=? ORDER BY id", (op_id,)).fetchall()
        return [OperationItem(**dict(r)) for r in rows]

    def last_archive_destinations(self, doc_ids: Iterable[int]) -> dict[int, str]:
        """每份文档**最后一笔已完成的归档搬动**落到了哪儿（`{doc_id: dst_path}`）。

        「已归档」只有一个口径（**ISSUES I78** 丙 · 轮十五 丙），而它对台账的形状很挑，
        所以四个挑法都写死在这里，界面上与导出里都不许再各挑一次：

        - **「最后一笔」按 `id` 最大取，不按 `updated_at`**：写终态那句取的是 `now_ts()`，
          那是**秒级**的，同一批里前后几条会并列，按它排就等于让 SQLite 的返回顺序决定谁赢。
          `id` 是单调的，一份文件归档两次（换了模板重跑）时第二次天然在后面。
        - **只认正向批次（`file_operations.kind='archive'`）**：撤销是另开一条 `kind='undo'`
          的批次、条目是全新的行且 src/dst 取反（**D-043** 甲）。不加这一道筛选，刚被退回
          原处的文件会因为"正躺在反向搬动把它放去的位置上"而重新读成已归档。
        - **`state='done'` 就够了，不再筛 `kind`**：0005 的 CHECK 只有 `move`/`copy` 两个值，
          两个都把文件落到 `dst_path`（`copy` 是跨盘那一档：验完 sha256 才删源，G19）。
          `pending`/`failed`/`skipped` 都不算 —— 那些文件根本不在 `dst_path` 上。
        - `doc_id` 为 NULL 的历史不参与（原记录被删过，`ON DELETE SET NULL`）：它已经没有
          一条"当前路径"可以跟落点对照。

        一批一条 SQL、最多 `MAX_BULK_IDS` 个 id，与 `CatalogRepository.tags_by_doc_ids` 同形
        （**ISSUES I51**：逐行查就是 n 条 SQL）。返回的字典**只含有归档记录的**那些份，
        缺键就是"这批台账里没动过它"，调用方不要替它补一个落点。
        """
        unique = list(dict.fromkeys(doc_ids))
        if not unique:
            return {}
        if len(unique) > MAX_BULK_IDS:
            raise ValueError(f"一次取 {len(unique)} 条超出 {MAX_BULK_IDS}；"
                             "大批量请按条件分页取文档，不要把 ID 列表塞进参数")
        marks = ",".join("?" * len(unique))
        rows = self.engine.thread_connection().execute(
            "SELECT doc_id, dst_path FROM operation_items WHERE id IN ("
            "  SELECT max(x.id) FROM operation_items AS x"
            "  JOIN file_operations AS y ON y.id = x.op_id"
            "  WHERE x.state='done' AND y.kind='archive' AND x.dst_path IS NOT NULL"
            f"    AND x.doc_id IN ({marks}) GROUP BY x.doc_id)", unique).fetchall()
        return {int(r["doc_id"]): str(r["dst_path"]) for r in rows}

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
