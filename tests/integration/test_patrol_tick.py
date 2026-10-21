"""巡检定时器 `patrol_tick` 干的三件事：把脏根排成扫描任务、状态栏回显、逐屏刷新进度。

从 `test_app_shell.py` 拆出（**ISSUES I58** 丙，2026-10-17；线管所有 `.py`，见 **R-010**）。
判据全部落在"定时器真的把活接下去了"这一件事上：接线断掉时界面**不会报错**，只会停在一个
看起来像还在跑的读数上 —— 这正是 SPEC 4.3「故障要能被知道」禁止的那种静默。
下面两组共用同一条链：S5 判重进度也是 `patrol_tick` 刷出来的（线框 §S5「进度」那一行）。
"""
from __future__ import annotations

from tests.conftest import settle as _settle


def test_巡检一轮就把脏根排成一条扫描任务(window, ctx, root) -> None:
    """`patrol_tick` 必须真的调 `patrol.poll()`：定时器空转的话，事件永远没人处理，
    而界面上的"上次扫描"会停在启动那一刻，看起来像还在跑。"""
    r = root("巡检")
    ctx.events.push_directory(r.root_key)
    assert ctx.jobs.count("queued") == 0

    window.patrol_tick()
    live = ctx.jobs.list()
    assert [j.kind for j in live] == ["scan"], live
    assert "巡检：" in window.statusBar().currentMessage()

    window.patrol_tick()
    assert ctx.jobs.count("queued") == 1, "脏根已经取走，第二轮不该再排一场重复的重扫"


def test_巡检定时器与巡检器同一个间隔口径(window, ctx) -> None:
    """间隔只许有一个出处。测试先把巡检器的间隔改成 7.5 秒再起定时器：
    界面里写死 5000（`scan_poll_seconds` 的默认值）当场露馅 —— 用默认值当默认值的断言等于没断言。"""
    ctx.patrol.poll_seconds = 7.5
    window.start_patrol()
    timer = window._patrol_timer
    assert timer is not None and timer.isActive()
    assert timer.interval() == 7500, f"定时器间隔没跟巡检器取同一个数：{timer.interval()}ms"
    timer.stop()


def test_巡检抛异常时定时器不许停并且状态栏留下原文(window, ctx, monkeypatch) -> None:
    """一轮失败如果把定时器打死，此后所有文件事件都没人管，而界面看起来一切正常 ——
    这正是 SPEC 4.3「故障要能被知道」禁止的那种静默。"""
    def boom():
        raise OSError("移动盘被拔掉了")

    window.start_patrol()
    monkeypatch.setattr(ctx.patrol, "poll", boom)
    window.patrol_tick()
    message = window.statusBar().currentMessage()
    assert "巡检出错：OSError: 移动盘被拔掉了" in message, message
    assert window._patrol_timer.isActive(), "异常之后定时器必须还活着"


# —— S5 判重进度（线框 §S5「进度」那一行）———————————————————————————


def _show_dedup(window, qapp):
    """切到重复检测屏并让它真的可见。

    不切的话 `QStackedWidget` 里它是隐藏页，`isVisible()` 恒为 False，
    `patrol_tick` 那一支分支根本不会走 —— 上一轮就是被这个假绿骗过一次。
    """
    from pdfarchiver.ui.pages.dedup_page import DedupPage

    window._select_by_page_id("duplicates")
    _settle(qapp)
    page = window._pages["duplicates"]
    assert isinstance(page, DedupPage) and page.isVisible(), "这一组断言全部依赖这一屏真的可见"
    return page


def test_判重进度块显示的是那一行的真份数不是假数(window, ctx, qapp) -> None:
    """这两个控件原来是**建完就 setVisible(False)、全站零引用**的死控件。

    线框 §S5「进度」的硬条件：读数只认 `JobRepository.set_progress` 写进去的 `done`/`total`，
    而且**不许**出现"整库判重总进度百分比"这种合并假数 —— 所以这里量份数，不量百分号。
    """
    page = _show_dedup(window, qapp)
    assert not page.progress_bar.isVisible() and not page.lbl_progress.isVisible(), \
        "库里一条判重任务都没有，进度块就该整个收起，不许显示一个 0% 的空条"

    job = ctx.jobs.enqueue("dedup", doc_id=None, priority=5)
    ctx.jobs.claim(("dedup",))
    ctx.jobs.set_progress(job.id, 120, 4000)
    page.reload_progress()

    assert page.progress_bar.isVisible() and page.lbl_progress.isVisible()
    assert (page.progress_bar.minimum(), page.progress_bar.maximum(),
            page.progress_bar.value()) == (0, 4000, 120)
    text = page.lbl_progress.text()
    assert "判重进行中" in text and "第 120/4,000 份" in text, text
    assert "%" not in text, f"§S5 明令禁止合并百分比读数，界面上却印出来了：{text}"
    # 进度条自带的那行百分比是横着压在进度块（accent 填充）上的：浅色 4.19:1、暗色 2.98:1，
    # 两套主题都不过 AA。关掉文字、读数交给旁边的标签，是唯一两边都过线的形状。
    assert not page.progress_bar.isTextVisible(), "百分比文字压在 accent 进度块上，两主题都不过 AA"


def test_判重已完成却一份都没算时不许留忙碌条与还没数出来的文案(window, ctx, qapp) -> None:
    """**ISSUES I105**：轮十九真机截图 S5 逮到 `state=done, total=0` 的任务仍显示忙碌条 +
    「判重完成：待算份数还没数出来」。任务已经结束，这句话与状态栏的"完成"互相矛盾；
    全库都已算过哈希时这是常态，不是理论分支。"""
    page = _show_dedup(window, qapp)
    job = ctx.jobs.enqueue("dedup", doc_id=None, priority=5)
    ctx.jobs.claim(("dedup",))
    ctx.jobs.succeed(job.id)          # 没调过 set_progress，total 仍是 NULL
    page.reload_progress()

    assert not page.progress_bar.isVisible(), "任务已经 done，还挂着忙碌条就是在说它还在算"
    text = page.lbl_progress.text()
    assert "判重完成" in text and "没有要算的份数" in text, text
    assert "还没数出来" not in text, f"任务已终结却说份数还没数出来：{text}"


def test_判重没数出份数就失败时显示故障原文而不是数数文案(window, ctx, qapp) -> None:
    page = _show_dedup(window, qapp)
    job = ctx.jobs.enqueue("dedup", doc_id=None, priority=5)
    ctx.jobs.claim(("dedup",))
    ctx.jobs.finish_as(job.id, "failed", error="磁盘被拔掉了")
    page.reload_progress()

    assert not page.progress_bar.isVisible(), "终结态的任务不该再显示忙碌条"
    text = page.lbl_progress.text()
    assert "判重失败" in text and "磁盘被拔掉了" in text, text
    assert "还没数出来" not in text, f"任务已失败却不报原文：{text}"


def test_判重任务行没了以后进度块必须整个收起(window, ctx, qapp) -> None:
    """进度块只认 `latest_of_kind` 那一行，所以**那一行没了它就得跟着没**。

    这条不是理论上的洁癖：`JobRepository.clear_finished` 会删掉全部终结行（门禁 stage5 就在用）。
    删完之后如果界面还挂着"判重完成：第 X/Y 份"，那句话指的是一个库里已经不存在的任务 ——
    和 **ISSUES I31** 同族：读数说不清自己指的是什么，用户就当成还在跑。
    """
    page = _show_dedup(window, qapp)
    job = ctx.jobs.enqueue("dedup", doc_id=None, priority=5)
    ctx.jobs.claim(("dedup",))
    ctx.jobs.set_progress(job.id, 3, 3)
    ctx.jobs.succeed(job.id)
    page.reload_progress()
    assert page.progress_bar.isVisible() and page.lbl_progress.isVisible()

    assert ctx.jobs.clear_finished() == 1, "用例前提：终结行确实被清掉了"
    page.reload_progress()
    assert not page.progress_bar.isVisible() and not page.lbl_progress.isVisible(), \
        "任务行已经不在了，界面上还留着一条指向它的读数"


def test_判重跑着的时候进度跟着定时器走且发起按钮不许再亮(window, ctx, qapp, root, make_pdf) -> None:
    """接线断在中间有两种坏法，这一条同时抓住：定时器压根不刷这一屏（进度永远停在发起那一刻），
    以及刷了但「发起」又被①段那个计数重新点亮（按下去只弹一句「判重已在进行」）。"""
    r = root("判重进度")
    make_pdf("判重进度/寅.pdf", page_lines=["寅文档的正文内容字符"])
    ctx.scan.scan_root(r)

    page = _show_dedup(window, qapp)
    page.reload()
    assert page.btn_start.isEnabled(), "有 1 份还没算过哈希、又没在跑，按钮就该是亮的"

    job = ctx.jobs.enqueue("dedup", doc_id=None, priority=5)
    ctx.jobs.claim(("dedup",))
    window.patrol_tick()
    assert page.progress_bar.isVisible(), "patrol_tick 没把这一屏的进度刷进去，接线断了"
    assert "判重进行中" in page.lbl_progress.text(), page.lbl_progress.text()
    # 这一会儿 `set_total` 还没跑过（`total` 是 NULL）：区间必须是 0..0（Qt 的忙碌条 = "在干，
    # 总量还不知道"）。写成 0..100 + value 0 会画出一根空满量程条，看着像卡死在 0%。
    assert (page.progress_bar.minimum(), page.progress_bar.maximum()) == (0, 0), \
        f"还没数出待算份数却给了满量程空条：min={page.progress_bar.minimum()} max={page.progress_bar.maximum()}"
    assert "待算份数还没数出来" in page.lbl_progress.text(), page.lbl_progress.text()
    assert not page.btn_start.isEnabled(), "任务活着的时候按钮还亮着，点下去只会弹一句「已在进行」"

    ctx.jobs.set_progress(job.id, 1, 1)
    ctx.jobs.succeed(job.id)
    window.patrol_tick()
    assert "判重完成" in page.lbl_progress.text(), page.lbl_progress.text()
    assert (page.progress_bar.minimum(), page.progress_bar.value()) == (0, 1), \
        "`succeed` 会把 done 补齐成 total：跑完的那一次要显示成满格，不是停在 0"


def test_判重进度的状态词表对齐仓储的状态口径() -> None:
    """六个合法状态漏一个，那一行就显示成空串（ KeyError 之前先炸的是界面），
    而 `latest_of_kind` 会如实把那条捞回来 —— 所以只有拿仓储的 `STATES` 来对才能发现。"""
    from pdfarchiver.db.repositories.jobs import LIVE_STATES, STATES
    from pdfarchiver.ui.pages.dedup_page import _LIVE_STATES, _STATE_READING

    assert frozenset(_STATE_READING) == frozenset(STATES), (
        f"词表缺 {set(STATES) - set(_STATE_READING)}，多出 {set(_STATE_READING) - set(STATES)}")
    assert _LIVE_STATES == LIVE_STATES, "「已经排过了」的判定与仓储的未终结集合不是同一组状态"
