"""阶段 2 第 10 项：扫描与索引任务的**进度 / 错误 / 重试**读数（`StatusService.read_tasks`）。

这一组断言里没有任何一个数字是测试自己拼出来的字符串：任务行由真 `WorkQueue` 的 worker 线程写，
故障与重试行由仓储的状态流转写，读数再从库里查回来。
界面（`ui/pages/status_page.py`）拿的就是这同一条 `lines()`，所以它显示什么由这里说了算。
"""
from __future__ import annotations

import threading

import pytest

from pdfarchiver.jobs.queue import DEFAULT_MAX_ATTEMPTS, ProgressMonitor, WorkQueue
from pdfarchiver.services.bootstrap import BackgroundState
from pdfarchiver.services.status_service import MAX_ERROR_LINES, format_ts


@pytest.fixture
def queue(ctx):
    """真 worker 线程的队列 —— 进度行只有它写得出来。用完一定停掉，别让线程活到下一个测试。"""
    built: list[WorkQueue] = []

    def _make(**kw) -> WorkQueue:
        q = WorkQueue(ctx.jobs, {"scan": ctx.scan.handle, "index": ctx.indexer.handle},
                      engine=ctx.engine, threads=1, poll_seconds=0.02, **kw)
        built.append(q)
        return q

    yield _make
    for q in built:
        q.stop(timeout=5.0)


# —— 空库也要有读数 ————————————————————————————————————————————

def test_空队列也要给出一行读数而不是空白(ctx) -> None:
    """"还没跑过"和"程序坏了所以没输出"在界面上必须分得开 —— 前者要有字面写着它的那一行。"""
    st = ctx.status.read_tasks(max_attempts=DEFAULT_MAX_ATTEMPTS)
    lines = "\n".join(st.lines())
    assert st.jobs_by_kind_state == {} and st.errors == []
    assert "队列里没有任何行" in lines
    assert "一个都没添加" in lines
    assert "最近故障：无" in lines
    assert "还欠一次索引 0" in lines


def test_时刻口径是UTC且从未不等于1970() -> None:
    assert format_ts(None) == "从未"
    assert format_ts(0) == "1970-01-01 00:00:00Z"


# —— 进度 ————————————————————————————————————————————

def test_索引进度按页累计而不是按任务条数(ctx, root, make_pdf, queue) -> None:
    """两页的文档索引完 = 2/2 页，不是 1/1 个任务：SPEC 要的是"还剩多少活"，
    条数在 8,000 份的量级里既不动也不告诉人还剩多久。"""
    r = root("读数")
    make_pdf("读数/两页的文档.pdf", page_lines=[["第一页的正文内容字符啊"], ["第二页的正文内容字符啊"]])
    ctx.scan.scan_root(r)
    q = queue()
    q.start()
    assert q.wait_until_idle(timeout=60.0), "worker 没在 60 秒内跑完，读数无从谈起"

    st = ctx.status.read_tasks(max_attempts=DEFAULT_MAX_ATTEMPTS)
    assert st.work_by_kind["index"] == (2, 2), st.work_by_kind
    assert st.count("index", "done") == 1
    assert "进度（按页）index：2 / 2 页 = 100.0%" in "\n".join(st.lines())


def test_排队中的任务算条数不算进度(ctx, root, make_pdf) -> None:
    """扫描排完队、worker 还没领：条数必须是 1，工作量必须还是 0/0 ——
    在任务被领取之前显示任何百分比都是模拟进度。"""
    r = root("排队")
    make_pdf("排队/等着的文档.pdf", page_lines=["等着被索引的正文内容字符"])
    ctx.scan.scan_root(r)
    st = ctx.status.read_tasks(max_attempts=DEFAULT_MAX_ATTEMPTS)
    assert st.count("index", "queued") == 1
    assert st.work_by_kind["index"] == (0, 0), st.work_by_kind
    assert "进度（按页）" not in "\n".join(st.lines()), "total=0 时不许出现百分比"


# —— 索引欠账的唯一口径 ————————————————————————————————————————————

def test_还欠一次索引只认pending与stale不认failed(ctx, root, make_pdf) -> None:
    """`failed` 是"试过且知道为什么不行"。把它算进欠账等于每扫一遍就重排一次同一个坏文件；
    口径来自 `documents.NEEDS_INDEX_STATUSES`，界面不许自己再列一遍状态名。"""
    r = root("欠账")
    make_pdf("欠账/甲.pdf", page_lines=["甲文档的正文内容字符"])
    make_pdf("欠账/乙.pdf", page_lines=["乙文档的正文内容字符"])
    ctx.scan.scan_root(r)
    ids = sorted(int(j.doc_id) for j in ctx.jobs.list() if j.kind == "index" and j.doc_id)
    ctx.indexer.index_document(ids[0])
    ctx.documents.set_fts_status(ids[1], "failed", error="整本读不出内容")
    ctx.documents.invalidate_index(ids[0])

    st = ctx.status.read_tasks(max_attempts=DEFAULT_MAX_ATTEMPTS)
    assert st.fts_by_status == {"failed": 1, "stale": 1}
    assert st.index_backlog == 1, "欠账 = stale 那一份；failed 那份不算"
    assert "还欠一次索引 1（口径 pending+stale）" in "\n".join(st.lines())


# —— 错误与重试 ————————————————————————————————————————————

def test_重试中的任务既算重试也带着原文出现在读数里(ctx, root, make_pdf) -> None:
    """走真实流转：领→失败回队→再领→再失败回队。此后它是 `queued` 且 `attempts=2`，
    既要被数进"重试中"，也要在故障列表里带着文档名和原文 —— 只查终结状态的话，
    用户看不到"这份文件已经在第二次尝试了"，只会看到它一直不动。"""
    r = root("重试")
    make_pdf("重试/丙.pdf", page_lines=["丙文档的正文内容字符"])
    ctx.scan.scan_root(r)
    first = ctx.jobs.claim(("index",))
    assert first is not None
    ctx.jobs.retry_later(int(first.id), "第 1 次：库被占用", max_attempts=3)
    second = ctx.jobs.claim(("index",))
    assert second is not None and second.attempts == 2
    ctx.jobs.retry_later(int(second.id), "第 2 次：读取超时", max_attempts=3)

    st = ctx.status.read_tasks(max_attempts=3)
    assert st.retried_by_kind == {"index": 1}, st.retried_by_kind
    err = st.errors[0]
    assert (err.kind, err.state, err.attempts) == ("index", "queued", 2)
    assert err.doc_name == "丙.pdf" and err.error == "第 2 次：读取超时"
    text = "\n".join(st.lines())
    assert "重试中：index=1（每条最多 3 次尝试）" in text
    assert "· index[queued] 第 2 次尝试｜丙.pdf｜第 2 次：读取超时" in text
    assert all(j.id != int(second.id) for j in ctx.jobs.recent_finished()), "故障行还活着，不该出现在终结列表里"


def test_试满上限后不再算重试而是留下失败终态(ctx, root, make_pdf) -> None:
    """两行都要造出来才证得了事：一条 `attempts=2` 但已经终结的行**不能**出现在"重试中"里，
    否则"重试中"就退化成"试过不止一次的行数"，一个早就放弃的文件会永远挂在上面。"""
    r = root("放弃")
    make_pdf("放弃/丁.pdf", page_lines=["丁文档的正文内容字符"])
    ctx.scan.scan_root(r)
    first = ctx.jobs.claim(("index",))
    ctx.jobs.retry_later(int(first.id), "第 1 次：读取超时", max_attempts=2)
    second = ctx.jobs.claim(("index",))
    assert second is not None and second.attempts == 2
    assert ctx.jobs.retry_later(int(second.id), "第 2 次：还是读不出来", max_attempts=2) == "failed"

    st = ctx.status.read_tasks(max_attempts=2)
    assert st.retried_by_kind == {}, f"已终结的行不该算重试中：{st.retried_by_kind}"
    assert st.count("index", "failed") == 1
    assert (st.errors[0].state, st.errors[0].attempts) == ("failed", 2)
    assert "每条最多 2 次尝试" in "\n".join(st.lines())


def test_故障读数最多列十条并按最新优先(ctx) -> None:
    """量级预埋：全量首轮 8,000 份一起失败时，把 8,000 行原文灌进文本框就是全量渲染。
    封顶是这里的规矩，所以断言必须写封顶后的条数而不是"库里有多少就显示多少"。"""
    total = MAX_ERROR_LINES + 5
    for i in range(total):
        job = ctx.jobs.enqueue("index", doc_id=None, dedupe=False)
        ctx.jobs.retry_later(int(job.id), f"第 {i} 次故障原文", max_attempts=9)

    st = ctx.status.read_tasks(max_attempts=9)
    assert len(st.errors) == MAX_ERROR_LINES
    assert st.errors[0].error == f"第 {total - 1} 次故障原文", "最新的那条要排在最前"
    assert "\n".join(st.lines()).count("· index[") == MAX_ERROR_LINES


# —— 监测根 ————————————————————————————————————————————

def test_监测根上次扫描错误显示出来且成功一次就清空(ctx, root) -> None:
    """留着上一次的失败信息会让人以为现在还是坏的（同一个概念两个口径），
    所以"清空"这件事也要在读数里当场可见 —— 它靠的是 `mark_full_scan` 的 error=None 分支。"""
    r = root("根读数")
    st0 = ctx.status.read_tasks(max_attempts=DEFAULT_MAX_ATTEMPTS)
    text0 = "\n".join(st0.lines())
    assert "启用" in text0 and "上次 从未" in text0 and "⚠" not in text0

    ctx.roots.mark_full_scan(r.root_key, error="OSError: 移动盘没插上")
    text1 = "\n".join(ctx.status.read_tasks(max_attempts=DEFAULT_MAX_ATTEMPTS).lines())
    assert "⚠ 上次扫描错误：OSError: 移动盘没插上" in text1

    ctx.roots.mark_full_scan(r.root_key)
    text2 = "\n".join(ctx.status.read_tasks(max_attempts=DEFAULT_MAX_ATTEMPTS).lines())
    assert "⚠" not in text2, "扫描已经成功了，界面上不许还挂着上一次的错误"


def test_暂停的根在读数里标出来(ctx, root) -> None:
    r = root("暂停的根")
    ctx.roots.set_enabled(r.root_key, False)
    text = "\n".join(ctx.status.read_tasks(max_attempts=DEFAULT_MAX_ATTEMPTS).lines())
    assert "[已暂停]" in text and "[启用]" not in text


# —— 重试上限的口径 ————————————————————————————————————————————

def test_重试上限显示的是队列真正在用的那个数(ctx, queue) -> None:
    """`WorkQueue.max_attempts` 是"到第几次就放弃"的唯一持有者。展示侧自己写一个 3，
    就有了"界面说最多 3 次、队列按别的数判 failed"的两个口径，所以这条把两边钉在同一个数上。"""
    q = queue(max_attempts=7)
    assert q.max_attempts == 7
    text = "\n".join(ctx.status.read_tasks(max_attempts=q.max_attempts).lines())
    assert "每条最多 7 次尝试" in text
    assert ctx.background_state().max_attempts == DEFAULT_MAX_ATTEMPTS, "后台还没起，按默认口径说"


def test_后台没起时读数说未启动而不是说一切正常(ctx) -> None:
    bg = ctx.background_state()
    assert bg.running is False and bg.worker_threads == 0 and bg.watched_roots == 0
    assert bg.watcher_alive is False, "没 start 过的监听线程不许报成活着"
    assert "后台未启动" in "\n".join(bg.lines())
    assert bg.max_attempts == DEFAULT_MAX_ATTEMPTS


def test_后台起来后读数给出线程数与监听根数(ctx, root) -> None:
    r = root("在跑的根")
    q = ctx.start_background()
    bg = ctx.background_state()
    try:
        assert bg.running is True
        assert bg.worker_threads == q.thread_count == int(ctx.settings["worker_threads"])
        assert bg.max_attempts == q.max_attempts
        assert bg.watched_roots == 1, f"注册了 1 个根就该在听 1 个：{bg}"
        assert bg.watcher_alive is True, "observer 线程死了读数还在说一切正常，等于把事故藏起来"
        lines = "\n".join(bg.lines())
        assert "监听根 1" in lines and "⚠" not in lines
    finally:
        ctx.shutdown()


def test_监听线程半路死了读数当场跟着翻脸(ctx, root) -> None:
    """`watcher_alive` 必须每次去问 observer 线程本人，不许把"启动那一刻活着"抄进快照。
    只有真让它半路死一次，才测得出快照是现读的还是缓存的 —— 而阶段 2 的事故（处理器缺
    `dispatch`，observer 在第一条事件上就死掉，`watched_roots` 照旧是 1）偏偏就是半路死。"""
    root("会断的根")
    ctx.start_background()
    assert ctx.background_state().watcher_alive is True, "刚起来就该是活的，否则下面那步没有意义"

    ctx.watch.stop()
    bg = ctx.background_state()
    try:
        assert bg.running is True and bg.watched_roots == 1, "根还在名单上，只是没人听了"
        assert bg.watcher_alive is False, "监听线程已经退出，读数还在说活着"
        assert "⚠ 文件监听线程已不在" in "\n".join(bg.lines())
    finally:
        ctx.shutdown()


def test_监听线程死了读数必须把它说出来() -> None:
    """`fs/watcher.py` 的处理器缺 `dispatch` 时，observer 线程在第一条事件上就崩了，
    而 `watched_roots` 照样是 1、worker 照样在跑、界面上没有任何一行字说"事件不再进来"
    （阶段 2 实测踩过）。这类死亡唯一的可见出口就是这一行 ⚠。"""
    dead = BackgroundState(running=True, worker_threads=2, max_attempts=3, watched_roots=1,
                           watcher_alive=False, pending_events=0)
    text = "\n".join(dead.lines())
    assert "⚠ 文件监听线程已不在" in text, f"监听断了却没在读数里出现：{text}"

    # 一个根都没配时不是"断了"，是"没东西可听"，不许吓唬人
    nothing = BackgroundState(running=True, worker_threads=2, max_attempts=3, watched_roots=0,
                              watcher_alive=False, pending_events=0)
    assert "⚠" not in "\n".join(nothing.lines())


def test_真索引一份文档后读数各栏都对(ctx, root, make_pdf) -> None:
    """`read_tasks` 依赖的每一栏（条数、工作量、索引状态、根）都用真数据填一遍：
    进度由 `ProgressMonitor` 写、终态由 `succeed` 写，跟 worker 走的不是两条路。"""
    r = root("齐活")
    make_pdf("齐活/戊.pdf", page_lines=["戊文档的正文内容字符"])
    ctx.scan.scan_root(r)
    job = ctx.jobs.claim(("index",))
    assert job is not None and job.doc_id is not None
    ctx.indexer.handle(job, ProgressMonitor(ctx.jobs, int(job.id), threading.Event()))
    ctx.jobs.succeed(int(job.id))

    st = ctx.status.read_tasks(max_attempts=DEFAULT_MAX_ATTEMPTS)
    assert st.documents == 1
    assert st.jobs_by_kind_state == {("index", "done"): 1}
    assert st.work_by_kind["index"] == (1, 1)
    assert st.fts_by_status == {"done": 1} and st.index_backlog == 0
    assert "· index" not in "\n".join(st.lines()), "成功收尾必须清掉 last_error，不许留一条失败的成功任务"
