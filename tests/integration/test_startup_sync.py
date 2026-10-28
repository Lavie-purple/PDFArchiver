"""轮三十六 乙：**启动即增量同步** —— 第一轮巡检必对账 + 「全库同步到哪个时刻」的唯一读数。

问题的实测形状：真库六根 `monitored_roots.last_full_scan_at` 全停在 **2026-10-16**，
而库里文档已经涨到 10,998。根因不是巡检坏了，是它的慢路按**连续运行时间**计时
（`scan_verify_minutes=30` ⇒ 1800s/5s = 360 次轮询），而应用一关一开计数器就从 0 重来 ——
那个"30 分钟"在绝大多数会话里永远走不到点。所以修法落在两处：

1. `Patrol.poll()` 的**第一轮**无条件排一场全量对账（增量的：没变的文件不排索引）；
2. `MainWindow.start_patrol()` 起定时器**当场**跑一轮，不等第一个 5 秒间隔。

读数侧的规矩与 **ISSUES I109** 丙 同源：这一格挂在 5 秒节拍上，所以只许走
`monitored_roots` + `processing_jobs` 的便宜查询，绝不碰 `text_pages`。
"""
from __future__ import annotations

from pdfarchiver.services.status_service import format_ts


# —— 后端：第一轮巡检必对账 ————————————————————————————————

def test_第一轮巡检就排一场全量对账(ctx, root) -> None:
    """不这么做的后果不是"慢"，是"从来不对账"：`verify_every_polls` 量的是连续运行时间。"""
    root("同步根")
    assert [j.kind for j in ctx.jobs.list()] == [], "用例前提：启动前队列是空的"

    report = ctx.patrol.poll()

    assert report.scan_enqueued is True
    assert [j.kind for j in ctx.jobs.list()] == ["scan"]
    assert "排队重扫" in report.summarize(), report.summarize()


def test_第二轮巡检不再排第二场(ctx, root) -> None:
    """第一轮那场还排在队里，第二轮不该再排 —— 排两场等于对同一棵树走两遍。"""
    root("同步根")
    assert ctx.patrol.poll().scan_enqueued is True

    assert ctx.patrol.poll().scan_enqueued is False
    assert ctx.jobs.count("queued") == 1


def test_起巡检定时器就当场对一次账不等第一个间隔(window, ctx, root) -> None:
    """`QTimer.start(5000)` 的第一次触发要等一个完整间隔；那 5 秒里库和磁盘是不一致的，
    而"上次关掉到现在变了什么"正是最该立刻知道的那件事。"""
    root("同步根")
    assert ctx.jobs.count("queued") == 0
    try:
        window.start_patrol()
        assert [j.kind for j in ctx.jobs.list()] == ["scan"], \
            "起了定时器却要等 5 秒才对账，启动那一刻的库和磁盘仍然是两个答案"
    finally:
        window._patrol_timer.stop()


# —— 读数：全库同步到哪个时刻 ————————————————————————————

def test_上次同步取各根最早的那一刻而不是最新的(ctx, root) -> None:
    """取最新那一刻会把"还有根停在半个月前"说成"同步到了今天"，所以量的是 min。
    两个根的时刻必须**不一样**才证得了事 —— 相同时 min 与 max 同值，这条断言就空了。"""
    early = root("早的根")
    late = root("晚的根")
    conn = ctx.engine.thread_connection()
    conn.execute("UPDATE monitored_roots SET last_full_scan_at=? WHERE root_key=?",
                 (1_000_000, early.root_key))
    conn.execute("UPDATE monitored_roots SET last_full_scan_at=? WHERE root_key=?",
                 (2_000_000, late.root_key))
    conn.commit()

    st = ctx.status.sync_status()
    assert st.roots_enabled == 2
    assert st.roots_never_scanned == 0
    assert st.last_full_scan_at == 1_000_000, "两个根的时刻不同，取到的却是另一个"
    assert st.summary() == f"同步到 {format_ts(1_000_000)}｜空闲", st.summary()


def test_从未对账的根要数出来且不许说成同步到今天(ctx, root) -> None:
    """只要还有一个根没对过账，就不存在"全库同步到某刻"这件事 —— 那是空话而不是读数。"""
    scanned = root("对过的根")
    root("没对过的根")
    ctx.roots.mark_full_scan(scanned.root_key)

    st = ctx.status.sync_status()
    assert (st.roots_enabled, st.roots_never_scanned) == (2, 1)
    assert st.last_full_scan_at is None, "另一个根从没对过账，却报出了一个同步时刻"
    assert st.summary() == "同步：1/2 个根从未全量对账｜空闲", st.summary()


def test_一个根都没有时说没有根而不是说同步完了(ctx) -> None:
    st = ctx.status.sync_status()
    assert st.roots_enabled == 0 and st.last_full_scan_at is None
    assert st.summary() == "同步：没有启用的监测根", st.summary()


def test_排队与在跑在读数里分开(ctx, root) -> None:
    """只有一个 worker（**ISSUES I46** 甲）：排着不等于在走，两句话不能合成一句。"""
    root("同步根")
    ctx.patrol.poll()
    queued = ctx.status.sync_status()
    assert (queued.scan_queued, queued.scan_running, queued.busy) == (1, 0, True)
    assert queued.summary().endswith("｜同步中")

    claimed = ctx.jobs.claim(("scan",))
    assert claimed is not None
    running = ctx.status.sync_status()
    assert (running.scan_queued, running.scan_running) == (0, 1)
    assert "scan 任务：排队 0｜在跑 1" in "\n".join(running.lines())


def test_停用的根不算进同步口径(ctx, root) -> None:
    """停用的根本来就不该在读数里撑着"全库"两个字：它不在扫描名单上（`list_enabled`）。"""
    live = root("在用的根")
    off = root("停用的根")
    ctx.roots.mark_full_scan(live.root_key)
    ctx.roots.set_enabled(off.root_key, False)

    st = ctx.status.sync_status()
    assert st.roots_enabled == 1 and st.roots_never_scanned == 0
    assert st.summary().startswith("同步到 "), st.summary()


# —— 两处落点：状态栏常驻格 + S7 状态页 ————————————————————

def test_同步读数挂在状态栏常驻区不被巡检消息冲掉(window, ctx, root) -> None:
    """巡检每 5 秒会拿「巡检：…」覆盖临时区；同步读数若也走 `showMessage`，
    就只活几秒 —— 而它是"我改的文件进库了没有"的唯一常驻读数。"""
    root("同步根")
    window.patrol_tick()
    assert "巡检：" in window.statusBar().currentMessage()

    before = window.sync_label.text()
    assert before.startswith("同步"), before
    window.statusBar().showMessage("巡检：事件 3｜新增 1")
    assert window.sync_label.text() == before, "临时区那句话把同步读数从屏幕上挤掉了"


def test_S7_状态页把同步读数铺上屏(window, ctx, root) -> None:
    """S7 那一块与状态栏那一格读的是同一个 `sync_status()`，所以两个口径不会各说各话。"""
    root("同步根")
    window._select_by_page_id("monitor")
    page = window._pages["monitor"]

    text = page.status_page.view.toPlainText()
    assert "== 全库同步到哪个时刻 ==" in text
    assert "启用监测根 = 1（其中从未全量对账 1）" in text
    assert "全库同步到 = 从未（口径：各启用根里最早的那一刻）" in text
