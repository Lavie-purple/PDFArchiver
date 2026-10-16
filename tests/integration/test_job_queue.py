"""任务队列的状态流转 —— 真 sqlite 文件 + 真线程，不 mock（D-012）。

这里的断言只认两种证据：**库里的行**和**处理函数被调了几次**。
不看日志、不看返回值里的自述 —— 队列说"我重试了"不算，`attempts` 涨了才算。

`processing_jobs.doc_id` 有外键指向 `documents`，所以每条任务都挂一份真实建过档的文档，
不靠关外键绕过（`PRAGMA foreign_keys` 关掉就等于把"任务指向不存在的文件"这类 bug 藏起来）。
"""
from __future__ import annotations

import inspect
import sqlite3
import threading
import time
from typing import Iterator

import pytest

from pdfarchiver.config.settings import DEFAULTS
from pdfarchiver.db.engine import DEFAULT_BUSY_TIMEOUT_MS
from pdfarchiver.db.models import Document
from pdfarchiver.db.repositories.jobs import LIVE_STATES, STATES, TERMINAL_STATES
from pdfarchiver.fs.identity import identity_key, normalize_path
from pdfarchiver.jobs.queue import (DEFAULT_MAX_ATTEMPTS, FINISH_WRITE_ATTEMPTS,
                                    FINISH_WRITE_BACKOFF_SECONDS, IllegalTransition, JobCancelled,
                                    LEGAL_TRANSITIONS, PermanentFailure, PROGRESS_STEP_PAGES,
                                    ProgressMonitor, WorkQueue, assert_transition, states)
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


def test_某类任务该看的那一条_running压过排队压过历史(ctx) -> None:
    """S5 的进度块只读这一条；选错就等于把「上次跑完的那次」显示成「正在跑的这次」。

    `list()` 回来到 Python 里挑也能挑对，但全量首轮未终结表里挂着 8,000 条索引任务
    （×10 档 8 万条），界面每 5 秒刷一次进度就每 5 秒做一次全量加载 —— 所以这个选择
    必须由一条带回 `LIMIT 1` 的查询来做，且它与 `list()` 给的答案必须一致。
    """
    assert ctx.jobs.latest_of_kind("dedup") is None, "一条都没排过时不许返回别的种类的任务"

    first = ctx.jobs.enqueue("dedup", doc_id=None)
    ctx.jobs.succeed(first.id)
    assert ctx.jobs.latest_of_kind("dedup").id == first.id

    second = ctx.jobs.enqueue("dedup", doc_id=None)
    ctx.jobs.claim(("dedup",))
    third = ctx.jobs.enqueue("dedup", doc_id=None, dedupe=False)
    assert ctx.jobs.latest_of_kind("dedup").id == second.id, "running 的那一条必须压过排队的"

    ctx.jobs.succeed(second.id)
    assert ctx.jobs.latest_of_kind("dedup").id == third.id, "没有在跑的了，就取最近那一条"

    picked = [j.id for j in ctx.jobs.list(STATES) if j.kind == "dedup"]
    assert set(picked) <= {first.id, second.id, third.id}
    assert ctx.jobs.latest_of_kind("dedup").id == max(picked), "与 list() 手挑的结果不一致"


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


# —— 取消与打断：三种"停"不许混 ————————————————————————————————

def test_处理函数自己判停时落cancelled并留下原因(ctx, make_queue, doc_ids):
    """阶段 5 新增的第三种停：OCR 的每日页预算跑满、单页耗时超过上限 —— 与用户和退出都无关。
    留在 `running` 会让界面一直显示"正在跑"而 worker 早已去领下一条，
    `wait_until_idle()` 也永远等不到空闲（这条就是这么发现的）。"""

    def stops_itself(job, monitor):
        monitor.set_total(5)
        monitor.advance()
        raise JobCancelled("跑到第 2 页之前今天的页预算用满")

    q = make_queue({"index": stops_itself}, threads=1)
    job = ctx.jobs.enqueue("index", doc_ids[0])
    assert _start_and_wait(q), "处理函数判停后队列等不到空闲 —— 停被当成了还在跑"

    row = ctx.jobs.get(int(job.id))
    assert row.state == "cancelled", row.state
    assert row.last_error == "跑到第 2 页之前今天的页预算用满", "原因没进库，界面就答不出为什么停"
    assert (row.done, row.total) == (1, 5), "真实跑过的那一页进度不许被抹掉，也不许补齐成 5"
    assert q.recover() == {"requeued": 0, "failed": 0}, \
        "判停是终态：下次启动自动重跑一份被明确停下的文档，就绕过了「只跑显式点名的」"


def test_退出闸门与用户取消同时按下时落cancelled(ctx, make_queue, doc_ids):
    """两种停同时发生时**取消赢**：`request_cancel` 已经把行写成 `cancelled`，
    退出分支不许把它改回 running 去等回收 —— 用户按了取消的文件不该下次开机再跑一遍。

    与下一条的区别是这里**真的按了取消**；只拉闸门不取消的那条见
    `test_退出闸门已拉下时处理函数判停仍按打断处理`。两条同名时前一条永远不会被执行，
    「同时按下」这个分支就只剩注释在守着（见 tests/guards/test_test_hygiene.py）。
    """
    entered = threading.Event()

    def stops_after_shutdown(job, monitor):
        entered.set()
        while not monitor.cancelled():
            time.sleep(0.01)
        raise JobCancelled("今天的页预算用满")

    q = make_queue({"index": stops_after_shutdown}, threads=1)
    job = ctx.jobs.enqueue("index", doc_ids[0])
    q.start()
    assert entered.wait(5.0)
    assert q._stop.set() is None          # type: ignore[union-attr]
    q.cancel(int(job.id))                 # type: ignore[arg-type]
    assert q.wait_until_idle(timeout=5.0)
    assert ctx.jobs.get(int(job.id)).state == "cancelled", \
        "用户已经按了取消，这行就该是 cancelled，退出分支不许把它改回去"      # type: ignore[union-attr]


def test_退出闸门已拉下时处理函数判停仍按打断处理(ctx, make_queue, doc_ids):
    """两种停同时发生时**闸门优先**：退出时没人知道它做到哪儿，那行是 `recover()` 的输入，
    把它写成 cancelled 就等于宣布"这份不用再看了"。"""
    entered = threading.Event()

    def stops_after_shutdown(job, monitor):
        entered.set()
        while not monitor.cancelled():
            time.sleep(0.01)
        raise JobCancelled("今天的页预算用满")

    q = make_queue({"index": stops_after_shutdown}, threads=1)
    job = ctx.jobs.enqueue("index", doc_ids[0])
    q.start()
    assert entered.wait(5.0)
    assert q.stop(timeout=5.0) is True
    assert ctx.jobs.get(int(job.id)).state == "running", "退出打断被写成了 cancelled"  # type: ignore[union-attr]
    assert q.recover() == {"requeued": 1, "failed": 0}


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


# —— 收尾写失败：不许悄悄把任务留在 running（**ISSUES I46** 乙）————————————————

def _flaky_succeed(jobs, *, fail_first: int, calls: list[int], monkeypatch) -> None:
    """把「落 done」那次 UPDATE 的前 `fail_first` 次换成 `database is locked`，之后放通。

    只拦 `succeed` 一个方法：I46 现场卡住的 13 份全是处理函数正常跑完、只差收尾那一行
    UPDATE 的，拦在别处就验不到同一条路径。`fail_first=0` 退化成纯计数（用来断言
    "根本没走到写库那一步"）。断言只数**被调几次 + 库里的行**，与文件开头那条口径一致。
    """
    real = jobs.succeed

    def flaky(job_id: int) -> None:
        calls.append(int(job_id))
        if len(calls) <= fail_first:
            raise sqlite3.OperationalError("database is locked")
        real(job_id)

    monkeypatch.setattr(jobs, "succeed", flaky)


def test_收尾重试预算与退避表和忙等时长自洽():
    """三条都是「改一个常量就会把收尾写变成静默卡死」的口径，不是风格检查。

    ① 预算至少 2：等于 1 就没有「就地重试」了，瞬时锁只能等下一次迭代的重放。
    ② 退避表比预算短会在 `except` 里再抛 `IndexError` —— 那一次失败既不重试也不重放，
       任务行正好停在 `running`，就是这个改动要消灭的那个 bug 本身。
    ③ 每条尝试自己先吃满 `busy_timeout`，最坏耗时是可算出来的：按 [约定] 上限 30s
       （一次收尾拖住 worker 半分钟已经够久，再长就该改小重试次数而不是改大本断言）。
    """
    assert FINISH_WRITE_ATTEMPTS >= 2, (
        f"收尾重试预算={FINISH_WRITE_ATTEMPTS}：等于 1 就是「一次锁就放弃、全靠重放」，"
        "而重放要等 worker 走到下一次迭代 —— 瞬时锁的正解是就地立刻再写一次")
    assert len(FINISH_WRITE_BACKOFF_SECONDS) >= FINISH_WRITE_ATTEMPTS - 1, (
        f"重试 {FINISH_WRITE_ATTEMPTS} 次要睡 {FINISH_WRITE_ATTEMPTS - 1} 个退避间隔，"
        f"表里只有 {len(FINISH_WRITE_BACKOFF_SECONDS)} 个")
    worst = FINISH_WRITE_ATTEMPTS * DEFAULT_BUSY_TIMEOUT_MS / 1000 + sum(FINISH_WRITE_BACKOFF_SECONDS)
    assert worst <= 30.0, f"[约定] 单条收尾最坏 {worst:.0f}s > 30s（3×5s 忙等 + 1+3s 退避）"


def test_worker线程数默认值两处同口径():
    """**I46** 甲：SQLite 只有单一写者，写密集的 index 任务并行 = 撞锁。默认降到 1 之后，
    「默认值」有了两个写法（`WorkQueue` 的 `threads=` 形参默认、`DEFAULTS["worker_threads"]`），
    只改一处就会出现「界面报 1 个 worker、直接构造队列时开 2 个」的第二个口径。

    用户仍可在 settings.json 里覆盖成 2 —— 这条守的是默认值，不是禁掉这个能力。
    """
    default_threads = inspect.signature(WorkQueue.__init__).parameters["threads"].default
    assert default_threads == int(DEFAULTS["worker_threads"]) == 1, (
        f"`WorkQueue(threads=)`={default_threads}、`DEFAULTS`={DEFAULTS['worker_threads']}，"
        "两者必须同为 1（见 ISSUES I46 甲）")


def test_收尾写瞬时失败重试后仍落done(ctx, make_queue, doc_ids, monkeypatch):
    """`database is locked` 在写密集任务里是常态（I46 现场 27 次）：一次瞬时锁
    就把这一行判死留在 `running`，界面显示"正在跑"而 worker 早已去领下一条。"""
    calls: list[int] = []
    _flaky_succeed(ctx.jobs, fail_first=1, calls=calls, monkeypatch=monkeypatch)

    q = make_queue({"index": lambda job, monitor: None}, threads=1)
    job = ctx.jobs.enqueue("index", doc_ids[0])
    assert _start_and_wait(q, timeout=20.0), "收尾写失败一次就把任务永久留在了 running"
    assert calls == [int(job.id)] * 2, "没重试 —— 一次瞬时锁就放弃，或重试了不止一次"
    assert ctx.jobs.get(int(job.id)).state == "done"       # type: ignore[union-attr]
    assert q.thread_count == 1 and q.live_count() == 0, "worker 被收尾写的异常带走了"


def test_收尾写连试失败会在同一进程里重放到终态(ctx, make_queue, doc_ids, monkeypatch):
    """重试预算烧完不等于结束：I46 的 13 份就是这么卡住的 —— 兜底 `except` 把异常吞掉，
    行停在 `running`，而 `recover()` 只在启动时跑一次，本进程再无回收路径，
    排空判定 `queued + running` **永不归零**。"""
    calls: list[int] = []
    _flaky_succeed(ctx.jobs, fail_first=FINISH_WRITE_ATTEMPTS, calls=calls, monkeypatch=monkeypatch)

    q = make_queue({"index": lambda job, monitor: None}, threads=1)
    job = ctx.jobs.enqueue("index", doc_ids[0])
    assert _start_and_wait(q, timeout=25.0), (
        f"收尾写试满 {FINISH_WRITE_ATTEMPTS} 次后这一行永远停在 running —— 就是 I46 的机制")
    assert len(calls) == FINISH_WRITE_ATTEMPTS + 1, f"重放没发生：一共只写了 {len(calls)} 次"
    assert ctx.jobs.get(int(job.id)).state == "done"       # type: ignore[union-attr]
    assert q._pending_finals == [] and q.thread_count == 1, "重放成功后不许还挂在待重放列表里"


def _gate_locked_succeed(jobs, *, calls: list[int], gate: threading.Event, monkeypatch) -> None:
    """收尾写在 `gate` 拉起前一律撞 `database is locked`，拉起后放通。

    放行条件用队列**自己的退出闸门**，而不是测试里再数一次：那样"重放会不会成功"是由
    `_stop` 因果决定的，不靠测试和 worker 抢时间 —— 慢机器上抢时间的写法会假红。
    """
    real = jobs.succeed

    def flaky(job_id: int) -> None:
        calls.append(int(job_id))
        if not gate.is_set():
            raise sqlite3.OperationalError("database is locked")
        real(job_id)

    monkeypatch.setattr(jobs, "succeed", flaky)


def test_线程退出前把等重放的收尾落库(ctx, make_queue, doc_ids, monkeypatch):
    """真语料那 13 份正是「跑完最后一条、正好关窗口」时撞上的：重放若只做在下一次迭代开头，
    进程就没有下一次迭代了。

    排布：A 的收尾写烧光重试预算挂进重放队列 → worker 去领 B 并阻塞在退出闸门上 →
    先放开写库、再拉闸门 → B 返回后 worker 没有下一次迭代了，只有 `finally` 里那次重放
    能把 A 落成 done。同时钉住模块说明第 3 条与第 5 条**没被合并**：B 是退出打断，故意留在
    `running` 等下次启动回收；A 是写失败，必须在本进程内落终态。
    """
    calls: list[int] = []
    gate = threading.Event()
    _gate_locked_succeed(ctx.jobs, calls=calls, gate=gate, monkeypatch=monkeypatch)

    def blocked(job, monitor):
        while not monitor.cancelled():
            time.sleep(0.01)

    q = make_queue({"index": lambda job, monitor: None, "scan": blocked}, threads=1)
    job_a = int(ctx.jobs.enqueue("index", doc_ids[0]).id)      # A 立刻跑完，只差收尾那一行
    job_b = int(ctx.jobs.enqueue("scan", doc_ids[1]).id)       # B 阻塞在闸门上，占住 worker
    q.start()
    # 等到 worker 走进 B 的处理函数：领取发生在重放之后，而 `_run_one(B)` 会一直阻塞到闸门
    # 拉起，所以这一刻 A 必定已烧光预算、稳稳挂在重放队列里（不是抢时间的观测）。
    deadline = time.monotonic() + 20.0
    while ctx.jobs.get(job_b).state != "running":
        assert time.monotonic() < deadline, f"worker 没领走 B（写库一共被调 {len(calls)} 次）"
        time.sleep(0.05)
    assert len(q._pending_finals) == 1, "A 的收尾没挂进重放队列"
    assert ctx.jobs.get(job_a).state == "running", "写失败的任务被顺手改成了别的状态"

    gate.set()        # 必须先放开写库、再拉退出闸门：反过来的话 `finally` 那次重放还会撞锁
    assert q.stop(timeout=25.0) is True, "worker 没退出：收尾重放把自己关在了循环里"
    assert ctx.jobs.get(job_a).state == "done", "退出前的那次重放没落库，A 会卡在 running"
    assert calls.count(job_a) >= FINISH_WRITE_ATTEMPTS + 1, "重放压根没发生"
    assert q._pending_finals == [] and q.thread_count == 0
    assert ctx.jobs.get(job_b).state == "running", "退出打断被重放机制顺手改成了终态"
    assert q.recover() == {"requeued": 1, "failed": 0}, "只有 B 该被回收：A 已经是 done"


def test_收尾流转不合法时不重试也不重放(ctx, make_queue, doc_ids, monkeypatch):
    """那一行已经不在 `running` 了（被人改成 `paused`）：`running → done` 被表挡的是**语义**，
    重放只会一直撞同一面墙。

    判据是**读了几次当前状态**：每一次收尾尝试（含重放）都必须先 `get` 一次，所以
    「只撞一次」= 2 次读（`_finish_success` 一次 + 记下真实状态供日志一次），
    「进了重试预算」≥ 3 次。按尝试次数而不是按 `_pending_finals` 判，是因为重放侧对
    非法流转本来就该停手 —— 注入第 4 条坏法时那一度被清空，看着像没事。

    同步点用「worker 回到循环顶部再次领取」而不是死等：那一刻 `_run_one` 必定已经返回，
    收尾是停手还是进了重试预算都已是既成事实（绿的时候 0.1s，坏法下才付重试睡眠的钱）。
    本条**不能**用 `wait_until_idle` 当同步点：那一行是 `paused`，而排空判定只看
    queued/running —— 拿它当"跑完了"的信号会在收尾还在睡退避时就开始断言（实测被
    注入第 4 条坏法骗过一轮）。
    """
    calls: list[int] = []
    _flaky_succeed(ctx.jobs, fail_first=0, calls=calls, monkeypatch=monkeypatch)
    reads: dict[int, int] = {}
    real_get = ctx.jobs.get

    def counted_get(job_id: int):
        reads[int(job_id)] = reads.get(int(job_id), 0) + 1
        return real_get(job_id)

    claims: list[int] = []
    real_claim = ctx.jobs.claim

    def counted_claim(kinds):
        claims.append(1)
        return real_claim(kinds)

    monkeypatch.setattr(ctx.jobs, "get", counted_get)
    monkeypatch.setattr(ctx.jobs, "claim", counted_claim)

    def hijacked(job, monitor):
        conn = ctx.engine.thread_connection()
        conn.execute("UPDATE processing_jobs SET state='paused' WHERE id=?", (int(job.id),))
        conn.commit()

    q = make_queue({"index": hijacked}, threads=1)
    job = ctx.jobs.enqueue("index", doc_ids[0])
    q.start()
    deadline = time.monotonic() + 20.0
    while len(claims) < 2:
        assert time.monotonic() < deadline, f"worker 没回到循环顶部（只领到 {len(claims)} 次）"
        time.sleep(0.02)

    assert reads.get(int(job.id), 0) <= 2, (
        f"非法流转被当成瞬时故障重试了：当前状态被读了 {reads.get(int(job.id))} 次"
        "（合法路径只读 2 次），撞墙的记录每次迭代还会再撞一遍")
    assert calls == [], "非法流转不该走到写库那一步"
    assert ctx.jobs.get(int(job.id)).state == "paused"     # type: ignore[union-attr]
    assert q._pending_finals == [], "撞墙的记录不许挂进重放队列（挂进去就每次迭代白撞一遍）"
    assert q.thread_count == 1, "worker 被非法流转带走了"


def test_攒着的进度写不进去也不许挡住收尾(ctx, make_queue, doc_ids, monkeypatch):
    """`flush()` 在 `_run_one` 的 `finally` 里：它一抛就把整个 `_run_one` 顶成异常，
    收尾那行**根本没机会执行** —— `_worker_loop` 的兜底 `except` 把这件事变成一条日志，
    行留在 `running`。和 `_write_final` 是同一个坏法的两个入口（进度停在 92% 是观感问题，
    收尾没落库才是「永远留在 running」），所以按 AGENTS.md「同类问题一次声明规则」一起钉。
    """
    calls: list[int] = []
    _flaky_succeed(ctx.jobs, fail_first=0, calls=calls, monkeypatch=monkeypatch)

    def flush_boom(self) -> None:
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(ProgressMonitor, "flush", flush_boom)
    q = make_queue({"index": lambda job, monitor: None}, threads=1)
    job = ctx.jobs.enqueue("index", doc_ids[0])
    assert _start_and_wait(q, timeout=10.0), \
        "flush 抛异常把 `_run_one` 顶了出去，收尾没执行，这一行留在 running"
    assert calls == [int(job.id)], "进度写失败之后收尾根本没跑"
    assert ctx.jobs.get(int(job.id)).state == "done"       # type: ignore[union-attr]
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
