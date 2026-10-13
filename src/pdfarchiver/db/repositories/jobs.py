"""任务队列的持久化部分。

阶段 1 只要**任务能落库、能被读出来、重启后看得见**；真正的调度线程属于阶段 2 的 `jobs/`。
这里没有线程、没有假进度，只有表读写 —— 进度字段一律 0.0，因为还没有任何东西在跑。
"""
from __future__ import annotations

from pdfarchiver.db.engine import Engine
from pdfarchiver.db.models import Job, now_ts

_JOB_COLS = "id,kind,doc_id,state,priority,attempts,progress,last_error,created_at"


class JobRepository:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def enqueue(self, kind: str, doc_id: int | None = None, *, priority: int = 5) -> Job:
        conn = self.engine.thread_connection()
        ts = now_ts()
        with self.engine.transaction(conn, on_error=f"任务入队失败 kind={kind}"):
            cur = conn.execute(
                "INSERT INTO processing_jobs(kind, doc_id, state, priority, created_at)"
                " VALUES(?,?,?,?,?)", (kind, doc_id, "queued", priority, ts))
        return Job(id=cur.lastrowid, kind=kind, doc_id=doc_id, state="queued",
                   priority=priority, created_at=ts)

    def list(self, states: tuple[str, ...] = ("queued", "running", "paused")) -> list[Job]:
        if not states:
            raise ValueError("states 为空时应当显式查全部，不许靠默认值返回 0 行")
        conn = self.engine.thread_connection()
        marks = ",".join("?" * len(states))
        rows = conn.execute(
            f"SELECT {_JOB_COLS} FROM processing_jobs WHERE state IN ({marks})"
            " ORDER BY priority, id", states).fetchall()
        return [Job(**dict(r)) for r in rows]

    def count(self, state: str | None = None) -> int:
        conn = self.engine.thread_connection()
        if state is None:
            return conn.execute("SELECT count(*) FROM processing_jobs").fetchone()[0]
        return conn.execute("SELECT count(*) FROM processing_jobs WHERE state=?", (state,)).fetchone()[0]

    def counts_by_state(self) -> dict[str, int]:
        conn = self.engine.thread_connection()
        rows = conn.execute("SELECT state, count(*) AS n FROM processing_jobs GROUP BY state").fetchall()
        return {r["state"]: r["n"] for r in rows}
