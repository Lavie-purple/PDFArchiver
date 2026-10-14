"""任务队列的**调度**部分 —— 线程、领取、进度回写、取消、重试、退出收尾。

和 `db/repositories/jobs.py` 的分工只有一条：那边只有表操作，这边只有流转。
分开的理由写在仓库文件里：状态机必须能在没有线程的情况下被单测跑完，
否则"两个 worker 抢到同一个任务"这种竞态只能靠运气复现。

四条写死在这里的规矩：
1. **一个 worker 线程一条连接**。仓储一律走 `engine.thread_connection()`（线程本地），
   所以线程退出前必须 `close_thread_connection()`，否则连接跟着死掉的线程留在那儿。
2. **状态只能按 `LEGAL_TRANSITIONS` 走**。每次写状态前先从库里读回**当前**状态再查表 ——
   拿调用方内存里记着的那个状态去查等于自证：任务可能在处理期间被用户取消，这时
   `running → done` 就不合法，而这张表只有在这种时候才真的挡得住东西。
3. **退出打断 ≠ 用户取消**。进程收尾时正在跑的任务，行留在 `running`，
   下次启动由 `recover_interrupted()` 收回 `queued`；用户显式取消才落 `cancelled`。
   两者混成一个的话，每次正常关应用都会留下一堆"已取消"的任务，没人知道那些文件到底做完了没有。
4. **进度按工作量回写，且必须节流**。全量索引要跑 200 万页（docs/VERIFICATION 语料实测），
   每页一次 UPDATE 就是把磁盘带宽花在没人看的数字上；按 `PROGRESS_STEP_PAGES` 攒着写，
   结束时补一次真值。百分比由仓储里的 `done/total` 算，不由这里传（AGENTS.md：不许模拟进度）。
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from typing import Callable

from pdfarchiver.db.engine import Engine
from pdfarchiver.db.models import Job
from pdfarchiver.db.repositories.jobs import KINDS, TERMINAL_STATES, JobRepository

log = logging.getLogger("pdfarchiver.jobs")

# [约定] 一个任务最多被尝试几次。3 次足够吃掉"文件正被别的程序占用"这类瞬时故障，
# 又不至于让每次开机都把同一个必崩文件重跑一遍（见 recover_interrupted）。
DEFAULT_MAX_ATTEMPTS = 3
PROGRESS_STEP_PAGES = 64   # p2 实测正文提取 ≈147.9 页/秒 → 约 0.43s 回写一次；界面 0.5s 刷新，再密也没人看
IDLE_POLL_SECONDS = 0.05   # wait_until_idle 的轮询步长；只影响等待精度，不参与任务状态判定
TERMINAL_STATES = frozenset(TERMINAL_STATES)  # 定义在仓储层，与 SQL 里的"终结"同源

LEGAL_TRANSITIONS: dict[str, frozenset[str]] = {
    "queued": frozenset({"running", "paused", "cancelled"}),
    "running": frozenset({"queued", "done", "failed", "cancelled"}),
    "paused": frozenset({"queued", "cancelled"}),
    "done": frozenset(),
    "failed": frozenset(),
    "cancelled": frozenset(),
}


class IllegalTransition(RuntimeError):
    """想做的状态跳转不在表里。消息要带上 from/to，只说"不合法"没法查。"""


class JobCancelled(Exception):
    """处理函数主动抛出，表示"这一页之后别再干了"。"""


class PermanentFailure(Exception):
    """处理函数判定"再试也不会不一样"时抛这个：文件本身坏了、加密且没有密码。
    它和瞬时故障分开走，是因为 `max_attempts` 的意义是"吃掉暂时性的占用/锁库"，
    让一个必崩的文件把三次机会烧完，等于把队列里 37.5% 的扫描件都重试三遍（p2 实测比例）。
    任务照样落 `failed` 并留下原文 —— 只是不再排第二次。"""


def assert_transition(from_state: str, to_state: str) -> None:
    allowed = LEGAL_TRANSITIONS.get(from_state)
    if allowed is None:
        raise IllegalTransition(f"未知任务状态 {from_state!r}；合法值 {sorted(LEGAL_TRANSITIONS)}")
    if to_state not in allowed:
        raise IllegalTransition(
            f"任务状态流转 {from_state} → {to_state} 不合法；{from_state} 之后只能是 "
            f"{sorted(allowed) or '（终态，不许再动）'}")


def states() -> tuple[str, ...]:
    """状态口径的唯一写法，和仓储 `STATES` 由单测对齐断言钉在一起。"""
    return tuple(sorted(LEGAL_TRANSITIONS))


@dataclass
class ProgressMonitor:
    """交给处理函数的两支笔：写进度、问该不该停。

    处理函数拿不到 `JobRepository` —— 它一旦能直接写状态，就能写出表里没有的流转。
    """

    jobs: JobRepository
    job_id: int
    _stop: threading.Event
    _done: int = 0
    _total: int | None = None
    _written: int = 0

    def set_total(self, total: int) -> None:
        """工作量总数（页数、文件数）。要在第一次 `advance` 之前调用，
        否则 `progress` 长期停在 0/0，界面看起来像卡死而不是刚开始。"""
        self._total = total
        self.jobs.set_progress(self.job_id, self._done, total)
        self._written = self._done

    def advance(self, n: int = 1) -> None:
        self._done += n
        if self._done - self._written >= PROGRESS_STEP_PAGES:
            self.jobs.set_progress(self.job_id, self._done, self._total)
            self._written = self._done

    def flush(self) -> None:
        """把攒着的最后一批写出去：不写的话任务已经 done 而进度停在 92%。"""
        self.jobs.set_progress(self.job_id, self._done, self._total)
        self._written = self._done

    def cancelled(self) -> bool:
        """退出打断和用户取消都算"停"。区分发生在队列那边，不在这里 ——
        处理函数只需要尽早停下，少做无用功。"""
        return self._stop.is_set() or self.jobs.is_cancelled(self.job_id)


Handler = Callable[[Job, ProgressMonitor], None]


class WorkQueue:
    """N 个 worker 线程围着 `processing_jobs` 表转。没有内存队列：
    队列状态就是数据库状态，进程被杀后重启才知道上次到底排了什么（验收：重启后能继续扫描）。"""

    def __init__(self, jobs: JobRepository, handlers: dict[str, Handler], *,
                 engine: Engine, threads: int = 2,
                 max_attempts: int = DEFAULT_MAX_ATTEMPTS,
                 poll_seconds: float = 0.2) -> None:
        if not handlers:
            raise ValueError("没有任何处理函数的队列只会空转")
        unknown = sorted(set(handlers) - set(KINDS))
        if unknown:
            raise ValueError(f"任务类型 {unknown} 不在 {KINDS} 里；处理函数拼错了就该当场说")
        if threads < 1:
            raise ValueError(f"worker 线程数至少 1，收到 {threads}")
        self._jobs = jobs
        self._handlers = dict(handlers)
        self._kinds = tuple(sorted(self._handlers))
        self._engine = engine
        self._want_threads = threads
        self._max_attempts = max_attempts
        self._poll = poll_seconds
        self._stop = threading.Event()
        self._paused = threading.Event()
        self._threads: list[threading.Thread] = []

    # —— 生命周期 ————————————————————————————————————————————

    def recover(self) -> dict[str, int]:
        """启动时收上次进程被杀留下的 `running` 残尸。必须在 `start()` 之前调用。"""
        result = self._jobs.recover_interrupted(max_attempts=self._max_attempts)
        if result["requeued"] or result["failed"]:
            log.warning("回收中断任务：%s", result)
        return result

    def start(self) -> None:
        if self._threads:
            raise RuntimeError("队列已经启动，重复 start 会开出两倍的 worker")
        self._stop.clear()
        for i in range(self._want_threads):
            t = threading.Thread(target=self._worker_loop, name=f"pdfarchiver-worker-{i}", daemon=True)
            self._threads.append(t)
            t.start()
        log.info("任务队列启动：%d 个 worker，种类 %s", len(self._threads), ",".join(self._kinds))

    def stop(self, *, timeout: float = 5.0) -> bool:
        """停止领取新任务，并在 `timeout` 内等在跑的线程退出。返回是否全都真的退了。

        超时的线程**不再陪它等**：任务行留在 running，下次启动由 `recover()` 收回。
        主线程跟着一起卡死，比留一行待回收的记录糟糕得多。
        """
        self._stop.set()
        for t in self._threads:
            t.join(timeout)
        alive = [t for t in self._threads if t.is_alive()]
        if alive:
            log.warning("worker 未在 %.1fs 内退出，任务留在 running 等下次回收：%s",
                        timeout, [t.name for t in alive])
        self._threads = alive
        return not alive

    def pause(self) -> None:
        """全局闸门：正在跑的那一条会跑完当前任务，之后不再领新的。"""
        self._paused.set()

    def resume(self) -> None:
        self._paused.clear()

    @property
    def paused(self) -> bool:
        return self._paused.is_set()

    @property
    def thread_count(self) -> int:
        return len([t for t in self._threads if t.is_alive()])

    @property
    def max_attempts(self) -> int:
        """这条队列实际会用到第几次尝试才放弃。界面要显示"第 N/M 次"，M 只能从这里取 ——
        在展示侧再写一个 3，就有了"界面说最多 3 次、队列按别的数判 failed"的两个口径。"""
        return self._max_attempts

    # —— 对外动作 ————————————————————————————————————————————

    def cancel(self, job_id: int) -> bool:
        """只打标记；真正停下由处理函数在下一次 `monitor.cancelled()` 时完成。
        已经终结的任务返回 False —— 取消一个 done 的任务不是"失败"，是没有意义。"""
        job = self._jobs.get(job_id)
        if job is None or job.state in TERMINAL_STATES:
            return False
        assert_transition(str(job.state), "cancelled")
        return self._jobs.request_cancel(job_id)

    def live_count(self) -> int:
        """还在排队/在跑/暂停的任务条数。界面用它决定"扫描中"还是"空闲"。"""
        return (self._jobs.count("queued") + self._jobs.count("running")
                + self._jobs.count("paused"))

    def wait_until_idle(self, *, timeout: float = 60.0) -> bool:
        """等到没有 queued/running 的任务（paused 不算：那是人按下闸门的，不是我们在等的事）。
        给测试和"扫完再算"的调用方用 —— 不许用 `sleep(2)` 猜时间：
        慢机器上假失败，快机器上白等。"""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self._jobs.count("queued") == 0 and self._jobs.count("running") == 0:
                return True
            time.sleep(IDLE_POLL_SECONDS)
        return self._jobs.count("queued") == 0 and self._jobs.count("running") == 0

    # —— worker 循环 —————————————————————————————————————————

    def _worker_loop(self) -> None:
        try:
            while not self._stop.is_set():
                if self._paused.is_set():
                    time.sleep(self._poll)
                    continue
                try:
                    job = self._jobs.claim(self._kinds)
                except Exception:  # 领取失败（锁库、表被外部改动）不许弄死线程：留原文，退避后再试
                    log.exception("领取任务失败，%.1fs 后重试", self._poll)
                    time.sleep(self._poll)
                    continue
                if job is None:
                    time.sleep(self._poll)
                    continue
                try:
                    self._run_one(job)
                except Exception:  # 收尾环节自己出错（非法流转、库锁）也不许带走线程
                    log.exception("任务 %s(%s) 收尾流程出错，worker 继续处理下一条", job.id, job.kind)
        finally:
            self._engine.close_thread_connection()

    def _run_one(self, job: Job) -> None:
        job_id = int(job.id or 0)
        handler = self._handlers[str(job.kind)]
        monitor = ProgressMonitor(self._jobs, job_id, self._stop)
        outcome = "done"
        try:
            handler(job, monitor)
        except JobCancelled:
            outcome = "cancelled"
        except PermanentFailure as exc:
            outcome = f"permanent:{exc}"
        except Exception as exc:  # 一个坏文件不许把 worker 拖死，但原文必须留下（AGENTS.md 排障条）
            outcome = f"error:{type(exc).__name__}: {exc}"
        finally:
            monitor.flush()

        if outcome == "done" and self._stop.is_set():
            # 处理函数没抛 JobCancelled 就正常返回，但退出闸门已经拉下 —— 不能信"它做完了"：
            # 它很可能只是看见 `monitor.cancelled()` 就提前 return。判成 done 等于把这个文件
            # 永远标成"已处理"，而它只跑了一半。宁可下次启动重跑一遍（索引是可重入的）。
            outcome = "cancelled"

        if outcome == "done":
            self._finish_success(job)
        elif outcome == "cancelled":
            self._finish_cancelled(job)
        elif outcome.startswith("permanent:"):
            self._finish_permanent(job, outcome[len("permanent:"):])
        else:
            self._record_failure(job, outcome[len("error:"):])

    def _finish_permanent(self, job: Job, error: str) -> None:
        """直接落 failed，不进 `retry_later` —— 重试次数是留给瞬时故障的预算。"""
        job_id = int(job.id or 0)
        current = self._jobs.get(job_id)
        if current is None:
            log.warning("任务 %s 已经不在表里，跳过永久失败收尾", job_id)
            return
        if current.state == "cancelled":
            log.info("任务 %s(%s) 已被取消，永久失败原文只记日志：%s", job.id, job.kind, error)
            return
        assert_transition(str(current.state), "failed")
        self._jobs.finish_as(job_id, "failed", error=error)
        log.error("任务 %s(%s) 判定为不可重试失败（不再排第二次）：%s", job.id, job.kind, error)

    def _record_failure(self, job: Job, error: str) -> None:
        job_id = int(job.id or 0)
        current = self._jobs.get(job_id)
        if current is None:
            log.warning("任务 %s 已经不在表里，跳过失败收尾", job_id)
            return
        if current.state == "cancelled":
            log.info("任务 %s(%s) 已被取消，失败原文只记日志不再改状态：%s", job.id, job.kind, error)
            return
        assert_transition(str(current.state), "queued")  # 还要再试就得回 queued；试满由仓储落 failed
        state = self._jobs.retry_later(job_id, error, max_attempts=self._max_attempts)
        if state == "failed":
            log.error("任务 %s(%s) 试满 %d 次仍失败：%s", job.id, job.kind,
                      self._max_attempts, error, exc_info=True)
        else:
            log.warning("任务 %s(%s) 第 %s 次尝试失败，已回队：%s", job.id, job.kind,
                        job.attempts, error)

    def _finish_success(self, job: Job) -> None:
        """按**库里的当前状态**判流转，不按内存里记着的那个 ——
        处理期间任务可能已被用户取消，这时 `running → done` 不合法，必须停手。"""
        job_id = int(job.id or 0)
        current = self._jobs.get(job_id)
        if current is None:
            log.warning("任务 %s 已经不在表里，跳过 done 收尾", job_id)
            return
        if current.state == "cancelled":
            log.info("任务 %s(%s) 在收尾前已被取消，状态保持 cancelled 不改写", job.id, job.kind)
            return
        assert_transition(str(current.state), "done")
        self._jobs.succeed(job_id)

    def _finish_cancelled(self, job: Job) -> None:
        """`request_cancel` 已经把行写成 cancelled 了，这里只分辨是哪一种停。"""
        job_id = int(job.id or 0)
        if self._jobs.is_cancelled(job_id):
            log.info("任务 %s(%s) 已按请求取消", job.id, job.kind)
            return
        # 退出打断：不改状态。留在 running 的那一行是 recover() 的输入，不是 bug。
        log.info("任务 %s(%s) 被退出打断，留在 running 等下次回收", job.id, job.kind)
