"""任务队列的状态流转 —— 真 sqlite 文件 + 真线程，不 mock（D-012）。

这里的断言只认两种证据：**库里的行**和**处理函数被调了几次**。
不看日志、不看返回值里的自述 —— 队列说"我重试了"不算，`attempts` 涨了才算。

`processing_jobs.doc_id` 有外键指向 `documents`，所以每条任务都挂一份真实建过档的文档，
不靠关外键绕过（`PRAGMA foreign_keys` 关掉就等于把"任务指向不存在的文件"这类 bug 藏起来）。
"""
from __future__ import annotations

import threading
import time
from typing import Iterator

import pytest

from pdfarchiver.db.models import Document
from pdfarchiver.db.repositories.jobs import LIVE_STATES, STATES, TERMINAL_STATES
from pdfarchiver.fs.identity import identity_key, normalize_path
from pdfarchiver.jobs.queue import (DEFAULT_MAX_ATTEMPTS, IllegalTransition, JobCancelled,
                                    LEGAL_TRANSITIONS, PermanentFailure, PROGRESS_STEP_PAGES,
                                    WorkQueue, assert_transition, states)
from pdfarchiver.jobs.queue import TERMINAL_STATES as QUEUE_TERMINAL_STATES


@pytest.fixture
def doc_ids(ctx, tmp_path) -> list[int]:
    """8 份真实文档主记录（只写表，不碰磁盘），给任务当外键目标。"""
    ids = []
    for i in range(1, 9):
        p = tmp_path / f"doc{i}.pdf"
        ids.append(int(ctx.documents.upsert(
            Document(path=normalize_path(p), path_key=identity_key(p), name=p.name,
                     ext="pdf", size_bytes=1024, mtime_ns=1)).id))
    return ids


@pytest.fixture
def make_queue(ctx) -> Iterator[callable]:
    """建队列并保证测试结束时线程真的退干净 —— 漏掉 stop() 会把线程和连接带进下一个测试。"""
    built: list[WorkQueue] = []

    def _make(handlers: dict[str, object], **kw) -> WorkQueue:
        q = WorkQueue(ctx.jobs, handlers, engine=ctx.engine, poll_seconds=0.02, **kw)  # type: ignore[arg-type]
        built.append(q)
        return q

    yield _make
    for q in built:
        q.stop(timeout=5.0)


def _start_and_wait(queue: WorkQueue, *, timeout: float = 10.0) -> bool:
    """只在没启动过时用 —— `start()` 重复调用会当场报错，不静默开出双倍 worker。"""
    queue.start()
    return queue.wait_until_idle(timeout=timeout)


# —— 口径：状态集合必须只有一个说法 ————————————————————————————————

def test_状态口径只有一套():
    assert states() == tuple(sorted(STATES))
    assert set(LEGAL_TRANSITIONS) == set(STATES)
    assert frozenset(LIVE_STATES) | frozenset(TERMINAL_STATES) == frozenset(STATES)
    assert not set(LIVE_STATES) & set(TERMINAL_STATES)
    for src, targets in LEGAL_TRANSITIONS.items():
        assert targets <= set(STATES), f"{src} 的流转目标里有没定义过的状态"
        if src in TERMINAL_STATES:
            assert not targets, f"终态 {src} 不该还有出路"


def test_队列与仓储的终态是同一个定义():
    assert QUEUE_TERMINAL_STATES == frozenset(TERMINAL_STATES)


def test_非法流转报错时带上从哪到哪():
    with pytest.raises(IllegalTransition) as bad_from:
        assert_transition("running_", "done")
    assert "running_" in str(bad_from.value)
    with pytest.raises(IllegalTransition) as bad_to:
        assert_transition("done", "queued")
    assert "done" in str(bad_to.value) and "queued" in str(bad_to.value)


# —— 入队 ——————————————————————————————————————————————————

def test_同一文档的同类任务只排一条(ctx, doc_ids):
    assert ctx.jobs.enqueue("index", doc_ids[0]) is not None
    assert ctx.jobs.enqueue("index", doc_ids[0]) is None
    assert ctx.jobs.enqueue("index", doc_ids[1]) is not None   # 换文档就该排
    assert ctx.jobs.enqueue("scan", doc_ids[0]) is not None    # 换种类就该排
    assert ctx.jobs.count() == 3


def test_任务指向不存在的文档时数据库拦住(ctx):
    """外键不是摆设：任务挂着幽灵 doc_id，索引就会去索引一份不存在的文件还不报错。"""
    with pytest.raises(Exception, match="FOREIGN KEY"):
        ctx.jobs.enqueue("index", 9999)


def test_不针对具体文档的全量任务也去重(ctx):
    """watcher 每动一下都会排一条全量扫描；不去重就把队列刷满同一件待办。"""
    assert ctx.jobs.enqueue("scan") is not None
    assert ctx.jobs.enqueue("scan") is None
    assert ctx.jobs.count("queued") == 1
    assert ctx.jobs.enqueue("scan", dedupe=False) is not None   # 显式绕开仍然能排


def test_未知任务类型当场拒绝(ctx):
    with pytest.raises(ValueError, match="未知任务类型"):
        ctx.jobs.enqueue("recycle")


def test_没有处理函数的队列拒绝启动(ctx):
    with pytest.raises(ValueError, match="空转"):
        WorkQueue(ctx.jobs, {}, engine=ctx.engine)
    with pytest.raises(ValueError, match="不在"):
        WorkQueue(ctx.jobs, {"recycle": lambda *_: None}, engine=ctx.engine)
    with pytest.raises(ValueError, match="线程数"):
        WorkQueue(ctx.jobs, {"scan": lambda *_: None}, engine=ctx.engine, threads=0)


# —— 领取：原子性 ————————————————————————————————————————————

def test_四个线程同时领取不会重复(ctx, doc_ids):
    """这一条直接对敲仓储，不经过 WorkQueue —— 竞态发生在 SQL 那一层。"""
    ids = [ctx.jobs.enqueue("index", d) for d in doc_ids]
    expected = sorted(int(job.id) for job in ids)
    claimed: list[int] = []
    lock = threading.Lock()

    def grab() -> None:
        while True:
            job = ctx.jobs.claim(("index",))
            if job is None:
                break
            with lock:
                claimed.append(int(job.id))
        ctx.engine.close_thread_connection()

    threads = [threading.Thread(target=grab) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)
    assert sorted(claimed) == expected, "要么漏了任务，要么同一个任务被领走了两次"
    assert all(ctx.jobs.get(i).attempts == 1 for i in expected)  # type: ignore[union-attr]


def test_领取只认队列里排着的任务(ctx, doc_ids):
    job = ctx.jobs.enqueue("index", doc_ids[0])
    ctx.jobs.enqueue("index", doc_ids[1])
    assert ctx.jobs.claim(("scan",)) is None          # 种类不对，不许越界领
    with pytest.raises(ValueError, match="kinds 为空"):
        ctx.jobs.claim(())
    got = ctx.jobs.claim(("index",))
    assert got is not None
    assert int(got.id) == int(job.id)                 # priority 相同 → 按 id 先来
    assert got.state == "running" and got.attempts == 1


def test_优先级高的先走(ctx, doc_ids):
    low = ctx.jobs.enqueue("index", doc_ids[0], priority=9)
    high = ctx.jobs.enqueue("index", doc_ids[1], priority=1)
    got = ctx.jobs.claim(("index",))
    assert got is not None and int(got.id) == int(high.id)  # type: ignore[arg-type]
    assert ctx.jobs.get(int(low.id)).state == "queued"      # type: ignore[union-attr]


# —— 跑完整条链路 ————————————————————————————————————————————

def test_处理函数跑完任务落done(ctx, make_queue, doc_ids):
    ran: list[int] = []

    def handler(job, monitor):
        ran.append(int(job.id))
        monitor.set_total(3)
        for _ in range(3):
            monitor.advance()

    q = make_queue({"index": handler}, threads=1)
    job = ctx.jobs.enqueue("index", doc_ids[0])
    assert _start_and_wait(q)
    assert ran == [int(job.id)]  # type: ignore[arg-type]
    done = ctx.jobs.get(int(job.id))
    assert done.state == "done" and done.done == 3 and done.total == 3
    assert done.progress == 1.0 and done.finished_at


def test_进度按步长攒着写最后补齐(ctx, make_queue, doc_ids):
    """每次 `advance` 都写库 = 把磁盘带宽花在没人看的数字上（200 万页语料）。
    但任务结束时必须是真值，否则界面停在 92% 而库里已经 done。"""
    seen: list[int] = []

    def handler(job, monitor):
        monitor.set_total(1000)
        for _ in range(PROGRESS_STEP_PAGES - 1):
            monitor.advance()
        seen.append(int(ctx.jobs.get(int(job.id)).done))  # type: ignore[union-attr]
        monitor.advance()
        seen.append(int(ctx.jobs.get(int(job.id)).done))  # type: ignore[union-attr]

    q = make_queue({"index": handler}, threads=1)
    job = ctx.jobs.enqueue("index", doc_ids[0])
    assert _start_and_wait(q)
    assert seen == [0, PROGRESS_STEP_PAGES], "攒批的门槛没生效"
    final = ctx.jobs.get(int(job.id))
    # 正常返回就是"做完了"，所以收尾必须把 done 补齐到 total：状态 done 而进度停在 64/1000
    # 是两个口径（`progress` 已经是 1.0），而 `sum_progress()` 会把这一行的缺口算进"还剩多少活"。
    assert final.state == "done" and (final.done, final.total, final.progress) == (1000, 1000, 1.0)  # type: ignore[union-attr]


def test_一个坏文件不许把worker拖死(ctx, make_queue, doc_ids):
    order: list[str] = []

    def boom(job, monitor):
        order.append("boom")
        raise RuntimeError("正文提取炸了")

    def fine(job, monitor):
        order.append("fine")

    q = make_queue({"index": boom, "scan": fine}, threads=1)
    bad = ctx.jobs.enqueue("index", doc_ids[0])
    q.start()
    good = ctx.jobs.enqueue("scan", doc_ids[1])
    assert q.wait_until_idle(timeout=10.0)
    assert q.thread_count == 1, "worker 线程被处理函数的异常带走了"
    assert "boom" in order and "fine" in order
    row = ctx.jobs.get(int(bad.id))
    assert row.state in ("queued", "failed") and row.attempts >= 1      # type: ignore[union-attr]
    assert "RuntimeError" in row.last_error and "正文提取炸了" in row.last_error  # type: ignore[union-attr]
    assert ctx.jobs.get(int(good.id)).state == "done"                   # type: ignore[union-attr]


def test_重试到上限才判失败且留下原文(ctx, make_queue, doc_ids):
    calls: list[int] = []

    def always_fail(job, monitor):
        calls.append(len(calls) + 1)
        raise OSError(2, "No such file or directory: 'x.pdf'")

    q = make_queue({"index": always_fail}, threads=1, max_attempts=DEFAULT_MAX_ATTEMPTS)
    job = ctx.jobs.enqueue("index", doc_ids[0])
    assert _start_and_wait(q)
    row = ctx.jobs.get(int(job.id))
    assert row.state == "failed", "试满之后还留在队列里，等于每次开机重跑同一个必崩文件"
    assert row.attempts == DEFAULT_MAX_ATTEMPTS == len(calls)  # type: ignore[union-attr]
    assert "No such file" in row.last_error                    # type: ignore[union-attr]
    assert row.finished_at is not None                         # type: ignore[union-attr]


def test_第二次就成功的任务不会被记成失败(ctx, make_queue, doc_ids):
    attempts: list[int] = []

    def flaky(job, monitor):
        attempts.append(int(job.attempts))
        if len(attempts) == 1:
            raise TimeoutError("文件正被别的程序占用")

    q = make_queue({"index": flaky}, threads=1)
    job = ctx.jobs.enqueue("index", doc_ids[0])
    assert _start_and_wait(q)
    assert attempts == [1, 2]
    row = ctx.jobs.get(int(job.id))
    assert row.state == "done" and row.attempts == 2   # type: ignore[union-attr]
    assert row.last_error is None, "成功了还挂着上一次的错误原文，界面就成了\"失败的成功任务\""  # type: ignore[union-attr]


def test_永久失败直接判死不退队重试(ctx, make_queue, doc_ids):
    """`PermanentFailure` = "再试也不会不一样"（文件坏了、加密没密码）。
    让它烧掉 3 次尝试预算，等于把语料里 37.5% 的必崩件重跑三遍（p2 实测比例）。"""
    calls: list[int] = []

    def broken(job, monitor):
        calls.append(1)
        raise PermanentFailure("PDF 结构损坏，无法打开")

    q = make_queue({"index": broken}, threads=1)
    job = ctx.jobs.enqueue("index", doc_ids[0])
    assert _start_and_wait(q)
    row = ctx.jobs.get(int(job.id))
    assert calls == [1] and row.attempts == 1                   # type: ignore[union-attr]
    assert row.state == "failed" and "无法打开" in row.last_error  # type: ignore[union-attr]
    assert q.live_count() == 0, "永久失败的任务不许留在队列里等下次回收"


# —— 取消与打断：两种"停"不许混 ————————————————————————————————

def test_用户取消正在跑的任务后状态保持cancelled(ctx, make_queue, doc_ids):
    entered = threading.Event()

    def long_job(job, monitor):
        entered.set()
        while not monitor.cancelled():
            time.sleep(0.01)
        raise JobCancelled

    q = make_queue({"index": long_job}, threads=1)
    job = ctx.jobs.enqueue("index", doc_ids[0])
    q.start()
    assert entered.wait(5.0)
    assert q.cancel(int(job.id)) is True                       # type: ignore[arg-type]
    assert q.wait_until_idle(timeout=5.0)
    assert ctx.jobs.get(int(job.id)).state == "cancelled"      # type: ignore[union-attr]
    assert q.cancel(int(job.id)) is False, "取消一个已终结的任务不是失败，是没有意义"


def test_处理期间被取消的任务不许改回done(ctx, make_queue, doc_ids):
    """处理函数没看闸门、跑完直接返回 —— 收尾必须按**库里的当前状态**判，不能自证。"""

    def ignores_cancel(job, monitor):
        ctx.jobs.request_cancel(int(job.id))

    q = make_queue({"index": ignores_cancel}, threads=1)
    job = ctx.jobs.enqueue("index", doc_ids[0])
    assert _start_and_wait(q)
    assert ctx.jobs.get(int(job.id)).state == "cancelled"      # type: ignore[union-attr]


def test_退出打断留下的残尸下次启动收回queued(ctx, make_queue, doc_ids):
    entered = threading.Event()

    def blocked(job, monitor):
        entered.set()
        while not monitor.cancelled():   # 停于关闸门：这是退出，不是用户取消
            time.sleep(0.01)

    q = make_queue({"index": blocked}, threads=1)
    job = ctx.jobs.enqueue("index", doc_ids[0])
    q.start()
    assert entered.wait(5.0)
    assert q.stop(timeout=5.0) is True
    assert ctx.jobs.get(int(job.id)).state == "running", "退出打断被写成了 cancelled"  # type: ignore[union-attr]

    assert q.recover() == {"requeued": 1, "failed": 0}
    assert ctx.jobs.get(int(job.id)).state == "queued"           # type: ignore[union-attr]
    assert ctx.jobs.get(int(job.id)).started_at is None          # type: ignore[union-attr]


def test_中断且已试满的任务直接判failed(ctx, doc_ids):
    job = ctx.jobs.enqueue("index", doc_ids[0])
    for _ in range(DEFAULT_MAX_ATTEMPTS - 1):   # 领取 → 记一次瞬时故障回队 → 再领取，走的是真原语
        assert ctx.jobs.claim(("index",)) is not None
        ctx.jobs.retry_later(int(job.id), "第若干次尝试失败", max_attempts=DEFAULT_MAX_ATTEMPTS + 1)
    assert ctx.jobs.claim(("index",)) is not None   # 最后一次领取后就再没回来过
    row = ctx.jobs.get(int(job.id))
    assert row.state == "running" and row.attempts == DEFAULT_MAX_ATTEMPTS  # type: ignore[union-attr]
    assert ctx.jobs.recover_interrupted(max_attempts=DEFAULT_MAX_ATTEMPTS) == {"requeued": 0, "failed": 1}
    assert ctx.jobs.get(int(job.id)).state == "failed"                       # type: ignore[union-attr]


def test_暂停闸门只挡住新的领取(ctx, make_queue, doc_ids):
    ran: list[int] = []
    q = make_queue({"index": lambda job, monitor: ran.append(int(job.id))}, threads=1)
    q.pause()
    job = ctx.jobs.enqueue("index", doc_ids[0])
    q.start()
    time.sleep(0.2)
    assert ran == [] and q.live_count() == 1
    assert ctx.jobs.get(int(job.id)).state == "queued"            # type: ignore[union-attr]
    q.resume()
    assert q.wait_until_idle(timeout=5.0)
    assert ran == [int(job.id)]                                   # type: ignore[arg-type]


def test_取消暂停中的任务(ctx, make_queue, doc_ids):
    q = make_queue({"index": lambda job, monitor: None}, threads=1)
    job = ctx.jobs.enqueue("index", doc_ids[0])
    assert ctx.jobs.set_state(int(job.id), "paused")
    assert q.cancel(int(job.id)) is True
    assert ctx.jobs.get(int(job.id)).state == "cancelled"         # type: ignore[union-attr]


# —— 收尾环节自己出错，也不许带走线程 ———————————————————————————

def test_任务行被人删掉时worker继续跑下一条(ctx, make_queue, doc_ids):
    ran: list[str] = []

    def vanishing(job, monitor):
        ran.append("first")
        conn = ctx.engine.thread_connection()
        conn.execute("DELETE FROM processing_jobs WHERE id=?", (int(job.id),))
        conn.commit()

    q = make_queue({"index": vanishing, "scan": lambda job, monitor: ran.append("second")}, threads=1)
    ctx.jobs.enqueue("index", doc_ids[0])
    q.start()
    second = ctx.jobs.enqueue("scan", doc_ids[1])
    assert q.wait_until_idle(timeout=10.0)
    assert ran == ["first", "second"]
    assert ctx.jobs.get(int(second.id)).state == "done"          # type: ignore[union-attr]
    assert q.thread_count == 1


def test_live_count只数未终结的(ctx, make_queue, doc_ids):
    q = make_queue({"index": lambda job, monitor: None}, threads=1)
    ctx.jobs.enqueue("index", doc_ids[0])
    ctx.jobs.enqueue("index", doc_ids[1])
    assert q.live_count() == 2
    assert _start_and_wait(q)
    assert q.live_count() == 0
    assert ctx.jobs.count("done") == 2
    assert [job.kind for job in ctx.jobs.recent_finished()] == ["index", "index"]
    assert ctx.jobs.list() == []                    # 默认口径=未终结，历史要靠 recent_finished
    assert set(ctx.jobs.counts_by_state()) == {"done"}
    assert ctx.jobs.counts_by_kind_state() == {("index", "done"): 2}


def test_clear_finished只删终结的(ctx, make_queue, doc_ids):
    q = make_queue({"index": lambda job, monitor: None}, threads=1)
    finished = ctx.jobs.enqueue("index", doc_ids[0])
    assert _start_and_wait(q)
    pending = ctx.jobs.enqueue("index", doc_ids[1])
    assert ctx.jobs.clear_finished() == 1
    assert ctx.jobs.get(int(finished.id)) is None
    assert ctx.jobs.get(int(pending.id)).state == "queued"       # type: ignore[union-attr]


def test_sum_progress按工作量算而不是任务条数(ctx, make_queue, doc_ids):
    def handler(job, monitor):
        monitor.set_total(10)
        for _ in range(10):
            monitor.advance()

    q = make_queue({"index": handler}, threads=2)
    for d in doc_ids[:3]:
        ctx.jobs.enqueue("index", d, total=10)
    assert _start_and_wait(q)
    assert ctx.jobs.sum_progress("index") == (30, 30)
