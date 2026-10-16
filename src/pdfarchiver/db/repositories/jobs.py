"""任务队列的持久化部分 —— SQL 只许出现在这一层。

阶段 1 只有"入队 + 按状态读"；阶段 2 补上真正的状态流转原语：
原子领取、进度回写、失败重试、取消、重启恢复。

**调度与线程在 `jobs/queue.py`，这里只有表操作**。分开的理由不是好看：
状态机必须能被单测在没有线程的情况下跑完（同一套 SQL 用两个连接对敲），
一旦把线程混进来，"两个 worker 抢到同一个任务"这种竞态就只能靠运气复现。

两条不可违反的规矩：
1. **领取必须原子**。`UPDATE ... WHERE id=(SELECT ...) AND state='queued'` 一句做完，
   靠 rowcount==1 判断抢到；先 SELECT 再 UPDATE 有两个 worker 同时拿到同一个任务的竞态。
2. **重启后不许有 `running` 残尸**。进程被杀时正在跑的任务，状态停在 running，
   但它已经不在任何线程里了 —— 恢复时一律收回 queued，否则队列会永远卡着 N 个假任务。
"""
from __future__ import annotations

from typing import Iterable

from pdfarchiver.db.engine import Engine
from pdfarchiver.db.models import Job, now_ts

# 合法状态与种类在这里定义一处；`jobs/queue.py` 的流转规则 import 它们。
# 仓储只保证"写进去的是一个合法状态字符串"，不解释业务含义。
STATES = ("queued", "running", "paused", "done", "failed", "cancelled")
KINDS = ("scan", "index", "ocr", "vector", "archive", "dedup")

_JOB_COLS = ("id, kind, doc_id, state, priority, attempts, progress, total, done,"
             " last_error, created_at, started_at, finished_at")

# 队列里的两组状态，各自回答不同的问题，而且都是**唯一口径**：
# 未终结 —— "同一件事已经排过了吗""这个任务还能取消吗"（入队去重、取消闸门）；
# 已终结 —— "哪些行算历史""哪些行可以删掉"（历史查询、清理）。
LIVE_STATES = ("queued", "running", "paused")
TERMINAL_STATES = ("done", "failed", "cancelled")
_LIVE_MARKS = ",".join("?" * len(LIVE_STATES))
_TERMINAL_MARKS = ",".join("?" * len(TERMINAL_STATES))

# 批量入队的分块。一行去重 INSERT 带 10 个变量，90 行 = 900 个，
# 压在 SQLite 老默认上限 999 之下（AGENTS.md：写死的阈值按最大量级反算，不靠"应该够大"）。
ENQUEUE_CHUNK = 90


class JobRepository:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    @staticmethod
    def _insert_sql(dedupe: bool) -> str:
        """入队语句的唯一写法。`enqueue` 与 `enqueue_many` 共用一份，
        否则"批量入队忘了去重"这种事一定会在某次改动里悄悄发生。"""
        head = "INSERT INTO processing_jobs(kind, doc_id, state, priority, total, created_at)"
        if dedupe:
            return (head + " SELECT ?,?,'queued',?,?,? WHERE NOT EXISTS ("
                    " SELECT 1 FROM processing_jobs WHERE kind=? AND IFNULL(doc_id,-1)=IFNULL(?,-1)"
                    " AND state IN (" + _LIVE_MARKS + "))")
        return head + " VALUES(?,?,?,?,?,?)"

    def enqueue(self, kind: str, doc_id: int | None = None, *, priority: int = 5,
                total: int | None = None, dedupe: bool = True) -> Job | None:
        """入队。`dedupe=True` 时，同一 (kind, doc_id) 已有未终结任务就不再排第二个 ——
        重复点两次"重新扫描"不该让队列膨胀一倍，也不该让同一文件被索引两遍。
        返回 None 表示"已经排过了"，不是失败。

        `doc_id=None` 也要去重（`IFNULL(...,-1)` 把 NULL 变成一个可比的中立值）：全量扫描任务
        就是这种"不针对某份文档"的任务。只按 `doc_id IS NOT NULL` 去重的话，watcher 每动一下
        就多排一条扫描，队列会被同一个待办刷满。"""
        if kind not in KINDS:
            raise ValueError(f"未知任务类型 {kind}；合法值 {'/'.join(KINDS)}")
        conn = self.engine.thread_connection()
        ts = now_ts()
        sql = self._insert_sql(dedupe)
        if dedupe:
            params: tuple[object, ...] = (kind, doc_id, priority, total, ts, kind, doc_id, *LIVE_STATES)
        else:
            params = (kind, doc_id, "queued", priority, total, ts)
        with self.engine.transaction(conn, on_error=f"任务入队失败 kind={kind}"):
            cur = conn.execute(sql, params)
        if cur.rowcount == 0:
            return None
        row = conn.execute(f"SELECT {_JOB_COLS} FROM processing_jobs WHERE id=?",
                           (cur.lastrowid,)).fetchone()
        return Job(**dict(row))

    def enqueue_many(self, kind: str, doc_ids: Iterable[int], *, priority: int = 5) -> int:
        """批量入队（全量扫描首轮要排 8,000 条索引任务，×10 档 8 万条）。
        逐条 `enqueue` 等于把同一件事提交 8,000 次事务；这里一个事务一批。
        返回**真正新增**的条数（去重命中的不计），调用方因此能分清"已经排过了"和"排进去了"。"""
        ids = sorted({int(i) for i in doc_ids})
        if not ids:
            return 0
        if kind not in KINDS:
            raise ValueError(f"未知任务类型 {kind}；合法值 {'/'.join(KINDS)}")
        conn = self.engine.thread_connection()
        sql = self._insert_sql(True)
        inserted = 0
        for start in range(0, len(ids), ENQUEUE_CHUNK):
            batch = ids[start:start + ENQUEUE_CHUNK]
            ts = now_ts()
            rows = [(kind, d, priority, None, ts, kind, d, *LIVE_STATES) for d in batch]
            with self.engine.transaction(conn, on_error=f"批量入队失败 kind={kind}（{len(batch)} 条）"):
                cur = conn.executemany(sql, rows)
            inserted += cur.rowcount
        return inserted

    def claim(self, kinds: tuple[str, ...]) -> Job | None:
        """原子领取一个 queued 任务并标记 running，`attempts` 在这里 +1。
        两个 worker 同时抢时，输的那个拿不到 RETURNING 行，返回 None（调用方应短暂退避后再试）。
        用 `RETURNING` 而不是"改完再按 started_at 查回来"：时间戳是秒级整数，
        同一秒内两个 worker 各领一条时按时间查会**领错任务**。"""
        if not kinds:
            raise ValueError("kinds 为空等于领取全部任务，这不是调用方想要的意思")
        conn = self.engine.thread_connection()
        marks = ",".join("?" * len(kinds))
        ts = now_ts()
        with self.engine.transaction(conn, on_error="领取任务失败"):
            row = conn.execute(
                f"UPDATE processing_jobs SET state='running', started_at=?, attempts=attempts+1"
                f" WHERE id = (SELECT id FROM processing_jobs WHERE state='queued' AND kind IN ({marks})"
                "  ORDER BY priority, id LIMIT 1) AND state='queued'"
                f" RETURNING {_JOB_COLS}", (ts, *kinds)).fetchone()
        return Job(**dict(row)) if row else None

    def set_progress(self, job_id: int, done: int, total: int | None = None) -> None:
        """进度回写。`progress` 由 done/total 算出来，**不是调用方传进来的百分比** ——
        谁都能报一个 100%，但只有这里的除法能算出 100%（AGENTS.md：不许模拟进度）。"""
        conn = self.engine.thread_connection()
        with self.engine.transaction(conn, on_error=f"回写进度失败 job_id={job_id}"):
            if total is None:
                row = conn.execute("SELECT total FROM processing_jobs WHERE id=?", (job_id,)).fetchone()
                total = row["total"] if row else None
            ratio = (done / total) if total else 0.0
            conn.execute("UPDATE processing_jobs SET done=?, total=?, progress=? WHERE id=?",
                         (done, total, min(1.0, max(0.0, ratio)), job_id))

    def succeed(self, job_id: int) -> None:
        """收尾必须清掉 `last_error`：第 1 次尝试的故障原文留在"成功"的行上，
        界面就成了"一条失败的成功任务"，而 attempts 已经说明了它重试过。

        `done` 在这里补齐成 `total`，不靠处理函数记得先 `flush()`：「任务已完成」的定义就是
        工作量全部处理完。留着一个没人保证的约定，进度就会停在 92% 而状态是 done，
        而 `sum_progress()` 把所有 done 行加起来的"已处理页数"会长期少算一截。"""
        conn = self.engine.thread_connection()
        ts = now_ts()
        with self.engine.transaction(conn, on_error=f"任务收尾失败 job_id={job_id}"):
            conn.execute("UPDATE processing_jobs SET state='done', finished_at=?, progress=1.0,"
                         " done=coalesce(total, done), last_error=NULL WHERE id=?", (ts, job_id))

    def retry_later(self, job_id: int, error: str, *, max_attempts: int) -> str:
        """失败后的分流：还能试就回 queued（下次再领），试满就 failed（留下原文）。
        返回落到的状态，调用方要用它写日志 —— 不许"记个日志说自己重试了"。"""
        conn = self.engine.thread_connection()
        ts = now_ts()
        with self.engine.transaction(conn, on_error=f"任务失败分流失败 job_id={job_id}"):
            row = conn.execute("SELECT attempts FROM processing_jobs WHERE id=?", (job_id,)).fetchone()
            attempts = row["attempts"] if row else max_attempts
            if attempts < max_attempts:
                conn.execute("UPDATE processing_jobs SET state='queued', last_error=?, started_at=NULL"
                             " WHERE id=?", (error, job_id))
                return "queued"
            conn.execute("UPDATE processing_jobs SET state='failed', last_error=?, finished_at=?"
                         " WHERE id=?", (error, ts, job_id))
            return "failed"

    def finish_as(self, job_id: int, state: str, *, error: str | None = None) -> None:
        if state not in ("cancelled", "failed"):
            raise ValueError(f"finish_as 只用于终结性状态，收到 {state}")
        conn = self.engine.thread_connection()
        ts = now_ts()
        with self.engine.transaction(conn, on_error=f"任务终止失败 job_id={job_id}"):
            conn.execute("UPDATE processing_jobs SET state=?, last_error=?, finished_at=? WHERE id=?",
                         (state, error, ts, job_id))

    def request_cancel(self, job_id: int) -> bool:
        """取消是**协作式**的：这里只打标记，worker 每处理一页检查一次。
        直接把状态改成 cancelled 会让"我已经改了半本正文"这件事没人知道。
        暂停中的任务也算能取消 —— 它还没开始跑，用户没有理由必须先把闸门打开。"""
        conn = self.engine.thread_connection()
        with self.engine.transaction(conn, on_error=f"请求取消失败 job_id={job_id}"):
            cur = conn.execute(
                "UPDATE processing_jobs SET state='cancelled', finished_at=?"
                " WHERE id=? AND state IN (" + _LIVE_MARKS + ")", (now_ts(), job_id, *LIVE_STATES))
        return cur.rowcount > 0

    def is_cancelled(self, job_id: int) -> bool:
        row = self.engine.thread_connection().execute(
            "SELECT state FROM processing_jobs WHERE id=?", (job_id,)).fetchone()
        return row is not None and row["state"] == "cancelled"

    def set_state(self, job_id: int, state: str) -> bool:
        """暂停/恢复用。只接受 queued↔paused，running 的任务不许被暂停打断
        —— 让它跑完当前这一页，由 worker 在下一次领取前看门闸。"""
        if state not in ("queued", "paused"):
            raise ValueError(f"set_state 只用于 queued↔paused，收到 {state}")
        conn = self.engine.thread_connection()
        with self.engine.transaction(conn, on_error=f"切换任务状态失败 job_id={job_id}"):
            cur = conn.execute("UPDATE processing_jobs SET state=? WHERE id=? AND state IN ('queued','paused')",
                               (state, job_id))
        return cur.rowcount > 0

    def recover_interrupted(self, *, max_attempts: int) -> dict[str, int]:
        """启动时处理上次进程被杀时留下的 running 残尸，返回 {"requeued": n, "failed": m}。

        不处理的话，重启后队列里永远挂着 N 个"正在跑"的假任务（验收：重启后能继续扫描）。
        已经试满 `max_attempts` 的任务**不再回收**，直接判 failed —— 否则一个每次启动都把它
        跑崩的文件，会让用户每次开机都重新等一遍同一件事。
        """
        conn = self.engine.thread_connection()
        ts = now_ts()
        with self.engine.transaction(conn, on_error="恢复中断任务失败"):
            cur = conn.execute(
                "UPDATE processing_jobs SET state='queued', started_at=NULL, progress=0.0, done=0"
                " WHERE state='running' AND attempts<?", (max_attempts,))
            requeued = cur.rowcount
            cur2 = conn.execute(
                "UPDATE processing_jobs SET state='failed', finished_at=?,"
                " last_error='进程中断，已达最大尝试次数 ' || attempts WHERE state='running'",
                (ts,))
            return {"requeued": requeued, "failed": cur2.rowcount}

    def get(self, job_id: int) -> Job | None:
        row = self.engine.thread_connection().execute(
            f"SELECT {_JOB_COLS} FROM processing_jobs WHERE id=?", (job_id,)).fetchone()
        return Job(**dict(row)) if row else None

    def list(self, states: tuple[str, ...] = LIVE_STATES) -> list[Job]:
        if not states:
            raise ValueError("states 为空时应当显式查全部，不许靠默认值返回 0 行")
        conn = self.engine.thread_connection()
        marks = ",".join("?" * len(states))
        rows = conn.execute(
            f"SELECT {_JOB_COLS} FROM processing_jobs WHERE state IN ({marks})"
            " ORDER BY priority, id", states).fetchall()
        return [Job(**dict(r)) for r in rows]

    def latest_of_kind(self, kind: str) -> Job | None:
        """这一类任务「此刻最该当进度看」的那一条：running → paused → queued → 最近结束的。

        不在界面里用 `list()` 挑：未终结表在全量首轮挂着 8,000 条索引任务（×10 档 8 万条），
        定时器每 5 秒刷一次进度就每 5 秒做一次全量加载。
        `state IN (六态)` 看着像没过滤，它是**索引入口**：`ix_jobs_state_kind` 的前导列是
        `state`，只写 `WHERE kind=?` 会退化成整表扫描。（六态 = LIVE + TERMINAL，
        两者相加等于全部合法状态由 `test_job_queue.py` 钉着。）
        """
        conn = self.engine.thread_connection()
        states = LIVE_STATES + TERMINAL_STATES
        marks = ",".join("?" * len(states))
        row = conn.execute(
            f"SELECT {_JOB_COLS} FROM processing_jobs"
            f" WHERE state IN ({marks}) AND kind=?"
            " ORDER BY CASE state WHEN 'running' THEN 0 WHEN 'paused' THEN 1"
            " WHEN 'queued' THEN 2 ELSE 3 END, id DESC LIMIT 1",
            (*states, kind)).fetchone()
        return Job(**dict(row)) if row else None

    def recent_finished(self, limit: int = 10) -> list[Job]:
        conn = self.engine.thread_connection()
        rows = conn.execute(
            f"SELECT {_JOB_COLS} FROM processing_jobs"
            " WHERE state IN (" + _TERMINAL_MARKS + ") ORDER BY id DESC LIMIT ?",
            (*TERMINAL_STATES, limit)).fetchall()
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

    def counts_by_kind_state(self) -> dict[tuple[str, str], int]:
        conn = self.engine.thread_connection()
        rows = conn.execute(
            "SELECT kind, state, count(*) AS n FROM processing_jobs GROUP BY kind, state").fetchall()
        return {(r["kind"], r["state"]): r["n"] for r in rows}

    def sum_progress(self, kind: str) -> tuple[int, int]:
        """某类任务已完成/总计的**工作量**（不是任务条数）：索引类任务按页数累计，
        所以进度条显示"已索引 12,340 / 45,678 页"，比"3 / 10 个任务"诚实。"""
        conn = self.engine.thread_connection()
        row = conn.execute(
            "SELECT coalesce(sum(done),0) AS d, coalesce(sum(total),0) AS t"
            " FROM processing_jobs WHERE kind=?", (kind,)).fetchone()
        return int(row["d"]), int(row["t"])

    def counts_retried_by_kind(self) -> dict[str, int]:
        """还没终结、但已经试过至少一次的任务条数（"重试中"的唯一口径：`attempts>1` 且未终结）。

        用 SQL 聚合而不是 `list()` 回来在 Python 里数：全量首轮会排 8,000 条索引任务，
        界面每 5 秒把它们全捞成对象只为数出几个数，等于每刷新一次做一次全量加载。
        """
        conn = self.engine.thread_connection()
        rows = conn.execute(
            "SELECT kind, count(*) AS n FROM processing_jobs"
            " WHERE attempts>1 AND state IN (" + _LIVE_MARKS + ") GROUP BY kind", LIVE_STATES).fetchall()
        return {r["kind"]: r["n"] for r in rows}

    def recent_errors(self, limit: int = 10) -> list[Job]:
        """最近带故障原文的任务行，**含正在重试的 queued 行**。

        不复用 `recent_finished`：重试中的任务把原文留在 `last_error` 上、状态却是 queued，
        只查终结状态等于"错误要等它死了才可见"，而用户恰恰要在它还活着时知道为什么慢。
        按 id 倒序而不是按 finished_at：后者的 NULL 在 ASC 排序里会排到最前面。
        """
        conn = self.engine.thread_connection()
        rows = conn.execute(
            f"SELECT {_JOB_COLS} FROM processing_jobs WHERE last_error IS NOT NULL"
            " ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [Job(**dict(r)) for r in rows]

    def clear_finished(self) -> int:
        """清空已终结的任务行（重建队列时用）。绝不删 queued/running/paused —— 那是还在排队的活。"""
        conn = self.engine.thread_connection()
        with self.engine.transaction(conn, on_error="清理已结束任务失败"):
            cur = conn.execute("DELETE FROM processing_jobs WHERE state IN (" + _TERMINAL_MARKS + ")",
                               TERMINAL_STATES)
        return cur.rowcount
