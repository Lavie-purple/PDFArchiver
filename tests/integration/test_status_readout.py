"""界面显示的是**库里的真读数**，以及"缺什么"这句话的唯一来源（**D-040** / **ISSUES I55** 乙）。

从 `test_app_shell.py` 拆出（**ISSUES I58** 丙，2026-10-17；线管所有 `.py`，见 **R-010**）。
这一组盯的全是**文案与代码状态的一致性**，三种坏法各由一条断言钉住：
① 读数缓存住、不重查库 —— 界面停在过去的某个时刻；
② 用散文宣称「某某还没实现」—— 散文没有来源，代码一改它就悄悄变成假话（上一轮真的漂过）；
③ 没接到后端的按钮或未接线的栏目把没做的事说成做完了 —— AGENTS.md
   「禁止能力不足时伪装成功」。

**2026-10-17 起这一组里所有"状态读数"的断言都走 S7 上半区**（**D-040**）：
状态不再是注册表里独立的一项，内容一字未改，只是换了取它的路线 —— `_status_block()`。
"""
from __future__ import annotations

import re
import threading
import time

from PySide6 import QtCore, QtWidgets

from pdfarchiver.ui.nav import NAV_ITEMS
from pdfarchiver.ui.pages.settings_page import SettingsPage
from pdfarchiver.ui.pages.status_page import StatusPage, UNWIRED_ACTIONS
from tests.conftest import settle as _settle


def _wait_reload(page: StatusPage, qapp, timeout: float = 30.0) -> None:
    """等后台重查把正文递回来（**ISSUES I109** ①：按钮路径不再同步渲染）。

    队列信号只有在主线程跑事件循环时才投递，所以这里必须 `processEvents()` 而不是睡等；
    超时就直接红，别让"线程没回信号"变成一条静默的旧读数。
    """
    deadline = time.monotonic() + timeout
    while page.reloading:
        if time.monotonic() > deadline:
            raise AssertionError(f"后台重查 {timeout:.0f}s 未结束（status-reload 线程没回信号？）")
        qapp.processEvents()
        time.sleep(0.01)
    _settle(qapp)


def _status_block(window, qapp) -> StatusPage:
    """切到 S7 并取出它上半区那张状态页（**D-040**：状态不再是独立的一屏）。

    必须真的切过去：`QStackedWidget` 里隐藏页不重排，`isVisible()` 恒为 False，
    下面的 `view.toPlainText()` 就会读到一个从没刷过的控件还照样绿。
    """
    window._select_by_page_id("monitor")
    _settle(qapp)
    page = window._pages["monitor"]
    assert isinstance(page, SettingsPage), "S7 下半区是设置、上半区是状态，两半在同一屏里"
    block = page.status_page
    assert isinstance(block, StatusPage) and block.isVisible(), \
        "这一组断言全部依赖状态那一块真的可见"
    return block


def test_首屏显示的是库里的真数字不是写死的文案(window, ctx, qapp) -> None:
    page = _status_block(window, qapp)
    text = page.view.toPlainText()
    assert f"结构版本 schema_version = {ctx.schema_version}" in text
    assert "分类 = 14" in text, "默认模板 14 个分类要真的读出来"
    assert "文档主记录 = 0" in text, "空库就显示 0，不许显示成看起来有数据的样子"
    assert str(ctx.paths.root) in text
    assert "[默认]" in text and "库文件 =" in text
    # 状态页**不跑任何同步库检查**（2026-10-16 判死：quick_check 在 6.1GB 真库上也要 452s+），
    # 所以这行也不该再出现——出现就说明有人把检查塞回了 UI，那会把大库状态页冻住。
    assert "integrity_check" not in text and "quick_check" not in text


def test_设置项三列口径在界面上打全(window, ctx, qapp) -> None:
    from pdfarchiver.config.settings import DEFAULTS

    text = _status_block(window, qapp).view.toPlainText()
    for key in DEFAULTS:
        assert f"{key}=" in text, f"启动时漏打印了设置项 {key}"


def test_刷新按钮重查数据库(window, ctx, qapp, qtbot) -> None:
    page = _status_block(window, qapp)
    assert "标签 = 0" in page.view.toPlainText()
    ctx.catalog.add_tag("刷新后才出现的标签")
    qtbot.mouseClick(page.refresh, QtCore.Qt.MouseButton.LeftButton)
    _wait_reload(page, qapp)
    assert "标签 = 1" in page.view.toPlainText(), "刷新必须是重新查库，不是重排一遍旧文本"


# —— 阶段 2 第 10 项：进度 / 错误 / 重试真的显示出来 ————————————————————

def test_状态页显示扫描与索引任务的读数(window, ctx, qapp, root, make_pdf) -> None:
    """界面不许只显示"一切正常"：S7 上半区要把队列的真条数打出来。

    `后台未启动` 那半句同样是指令的一部分 —— 阶段 2 的装配刻意不起线程，
    所以界面必须说"没在跑"，不能让人以为任务卡住了。
    """
    r = root("界面读数")
    make_pdf("界面读数/己.pdf", page_lines=["己文档的正文内容字符"])
    ctx.scan.scan_root(r)
    page = _status_block(window, qapp)
    page.reload()
    _wait_reload(page, qapp)
    text = page.view.toPlainText()
    assert "== 扫描与索引任务：进度 / 错误 / 重试 ==" in text
    assert "后台未启动" in text, "没起 worker 就要说没起，不许显示成正在跑"
    assert "任务条数  index：queued=1" in text, text
    assert "还欠一次索引 1" in text
    assert r.root_path in text


def test_刷新按钮同样重查任务读数(window, ctx, qapp, root, make_pdf, qtbot) -> None:
    """进度块缓存一下就等于在界面上展示一个已经过去的时刻 —— 刷新必须连它一起重查。"""
    r = root("刷新读数")
    make_pdf("刷新读数/辛.pdf", page_lines=["辛文档的正文内容字符"])
    ctx.scan.scan_root(r)
    page = _status_block(window, qapp)
    qtbot.mouseClick(page.refresh, QtCore.Qt.MouseButton.LeftButton)
    _wait_reload(page, qapp)
    assert "queued=1" in page.view.toPlainText()

    make_pdf("刷新读数/丑.pdf", page_lines=["丑文档的正文内容字符"])
    ctx.scan.scan_root(r)
    qtbot.mouseClick(page.refresh, QtCore.Qt.MouseButton.LeftButton)
    _wait_reload(page, qapp)
    assert "任务条数  index：queued=2" in page.view.toPlainText()


def test_状态读数只有这一处拼装(window, ctx, qapp) -> None:
    """D-040 的选择是**嵌控件**而不是抄一份渲染代码，所以全站只该有一个 `StatusPage`。

    一旦有人图省事在 `SettingsPage` 里另写一段 `parts += ...`，两份读数就会各自漂：
    上一轮已经真的漂过一次——"OCR 后端已交付但没有界面入口"那句只在原件里，
    副本里没有，而两边都长得像"状态页"，没人看得出哪份是权威的。
    """
    window._select_by_page_id("monitor")
    _settle(qapp)
    page = window._pages["monitor"]
    assert page.findChildren(StatusPage) == [page.status_page], \
        "S7 里出现了第二个状态读数控件，等于回到两份口径"
    text = page.status_page.view.toPlainText()
    assert text.count("== 扫描与索引任务：进度 / 错误 / 重试 ==") == 1, \
        "同一个标题出现两次 = 两处在拼同一份读数"


# 缺什么只许从两个列表里出来：nav 注册表（整屏没做）与 `status_page.UNWIRED_ACTIONS`
# （屏在、动作没接到后端）。散文式的「某某还没实现」会过期 —— 上一轮那句
# 「语义搜索（阶段 6）与文件归档、备份恢复的界面（阶段 4）后端和界面都还没实现」
# 就是三条一起漂（语义搜索早已接进 S1 的复选框，归档与备份两屏都建出来了）。
MISSING_CLAIM_RE = re.compile(r"还没实现|未实现|都没有|没做")
SECTION_RE = re.compile(r"^== .+ ==$")


def test_状态读数里的缺什么只许来自两个列表(window, ctx, qapp) -> None:
    window._select_by_page_id("monitor")
    _settle(qapp)
    text = window._pages["monitor"].status_page.view.toPlainText()

    sanctioned = ({f"  · {a}" for a in UNWIRED_ACTIONS}
                  | {f"  · {i.title} —— 未实现：{i.blocked_by}"
                     for i in NAV_ITEMS if not i.implemented})
    for line in text.splitlines():
        if not MISSING_CLAIM_RE.search(line):
            continue
        assert SECTION_RE.match(line) or line in sanctioned, (
            f"状态读数在用散文宣称「没实现」：{line!r}\n"
            "缺什么只许从 nav 注册表或 status_page.UNWIRED_ACTIONS 里出来 —— "
            "散文没有来源，代码一改它就悄悄变成假话")

    assert text.count("会真的移动你磁盘上的文件") == 1, (
        "磁盘口径出现了不止一份。这一句跟着执行器的接线**一定会变**（2026-10-17 随 A2/A4 "
        "已经改过一遍：从「不会动盘」改成「会真的移动」），两处就有了第二个口径"
        "（AGENTS.md「禁止核心概念有多个口径」）")


# —— 未接线说明的形状（**ISSUES I55** 乙）————————————————————————————
# 「屏在、动作没接到后端」那一档现在只剩 OCR 一条 ——「S3 执行归档」「S3 命名模板」
# 「S4 整批撤销」随 A2/A3/A4 接线销账。所以这里钉的不再是那两句话的**内容**，
# 而是**说明与唯一来源同生同灭**这个机制：来源清空 ⇒ 屏上那句必须跟着消失；
# 来源加一条 ⇒ 屏上那句必须一字不差地长出来。手抄的句子在这个机制下活不过一次改动。
FAKE_OUTCOME_CLAIMS = ("已提交", "提交到归档队列", "已开始", "已创建", "将创建",
                       "已撤销", "撤销成功", "已移动", "已搬")


def test_S3_的未接线说明只许与来源同生同灭(window, ctx, qapp, monkeypatch) -> None:
    """**ISSUES I55** 乙（用户「勾选的清单 均听你推荐」）要的形状：可以挂账，但事实必须显示在控件旁边；
    而**账销了，那句道歉也必须一起消失** —— 留在原地的那句从此没有来源。
    """
    from pdfarchiver.ui.pages import status_page
    from pdfarchiver.ui.pages.archive_page import ArchivePage

    window._select_by_page_id("archive")
    _settle(qapp)
    page = window._pages["archive"]

    assert status_page.unwired_lines("S3") == [], (
        "这条守卫测的是「来源已清空」那一侧；S3 又挂了新账就别套用它")
    assert page.unwired_label.text() == "", "S3 的账已经销完，屏上那句道歉还留着"
    assert not page.unwired_label.isVisibleTo(page), "空说明还占着一行，用户会以为还能展开"

    # 另一侧：来源里挂上两条 S3 的账，重开一屏必须原样拼出来（顺序、分隔符、去掉屏名前缀）
    monkeypatch.setattr(status_page, "UNWIRED_ACTIONS", tuple(
        status_page.UNWIRED_ACTIONS
        + ("S3 假账甲：这一栏改了什么都不变", "S3 假账乙：那个按钮没有后端")))
    fresh = ArchivePage(ctx)
    text = fresh.unwired_label.text()
    assert fresh.unwired_label.isVisibleTo(fresh), "挂在屏上但不可见 = 等于没有"
    assert text == "本轮未接线：假账甲：这一栏改了什么都不变；假账乙：那个按钮没有后端", (
        f"屏上那句不是从唯一来源拼出来的：{text!r}")
    assert not any(w in text for w in FAKE_OUTCOME_CLAIMS), f"未接线说明里承诺了后果：{text!r}"


def test_S7上半区按内容给高不冻在两栏sizeHint的比例(window, ctx, qapp) -> None:
    """**ISSUES I75**：S7 上半区那条窄缝（48 行只看得见 12–14 行）不能是"比例分配"的结果。

    判据只钉**写进 `_balance_split_by_content()` docstring 的那条政策**，不钉窗高的任何分数：
    上半区按内容要高、下半区朝自己的 `minimumSizeHint` 退、**退出来的每一像素都给上半区**。
    所以地板档量"下半区到底了没有"、最大化档量"一屏看全了没有"。

    地板档原先写的是 `blocks // 3` —— 那是**按内容算的分数**，而视口被下半区的物理地板卡死，
    两者量的不是一件事：轮三十六只给上半区加了 5 行读数（47 → 52 blocks），门槛就从 15 抬到 17，
    而实测视口仍是 15 行（`sizes=[280, 395]`，395 正是下半区自己的 `minimumSizeHint` 395），
    于是分配完全正确却被判红。按内容涨的判据会跟着内容漂，按地板量的不会。
    改前 offscreen 实测（`.probe_work/i75_split_needs.py`）两栏 sizeHint 258 / 447 = 36.6%，
    720 / 800 / 1409 三档上半区**恒为 36%**（`sizes=[247,428] / [276,479] / [499,865]`），
    可见行数 12 / 14 / 31；按内容分配之后三档实测 280 / 360 / 905px、可见 15 / 21 / 63 行。
    """
    block = _status_block(window, qapp)
    view = block.view
    page = window._pages["monitor"]
    lh = view.fontMetrics().height()
    blocks = view.document().blockCount()
    assert lh > 0 and blocks > 0, "读数框没内容就量不出比例，这条断言会假绿"

    # 地板档 720（D-039 那档最小窗高）：下半区必须已经退到自己的地板，退不动的才留给它。
    window.resize(1280, 720)
    _settle(qapp)
    splitter = page._splitter
    lower = splitter.sizes()[1]
    min_lower = page._lower.minimumSizeHint().height()
    assert min_lower < page._lower.sizeHint().height(), (
        f"前提不成立：下半区「想要」的 {page._lower.sizeHint().height()}px 与它自己的地板 {min_lower}px "
        "相等 —— 它没有可退的空间，下面那条判据就成了恒真，得换一档窗高或换判据")
    assert abs(lower - min_lower) <= 2, (
        f"窗口高 720：下半区拿了 {lower}px，而它自己的地板是 {min_lower}px —— "
        f"还有 {lower - min_lower}px 能退给上半区，sizes={splitter.sizes()}")

    # 最大化档 1409：一屏看全（原报障里"最大化也不解决"那半句）
    window.resize(1280, 1409)
    _settle(qapp)
    visible = view.viewport().height() // lh
    assert visible >= blocks, (
        f"窗口高 1409：一屏只装得下 {visible}/{blocks} 行，sizes={splitter.sizes()}")


def test_S7用户拖过分隔条之后缩放窗口不许抢回分配(window, ctx, qapp) -> None:
    """按内容分配是**初始**政策，不是"永远赢过用户" —— 拖过的比例必须留住（**ISSUES I75**）。

    这条是上一条的配对：`setSizes` 自己也会发 `splitterMoved`，所以"用户拖过"这一判据
    必须能被程序自己触发（这里用 `moveSplitter`，等价于拖到那个位置），否则锁根本没接上。
    """
    block = _status_block(window, qapp)
    page = window._pages["monitor"]
    splitter = page.findChild(QtWidgets.QSplitter)

    window.resize(1280, 720)
    _settle(qapp)
    before = splitter.sizes()[0]           # 按内容分配给上半区的那一档（实测 322）
    splitter.moveSplitter(120, 1)          # 往 120px 拖 —— Qt 会夹到上半区的最小高 138
    _settle(qapp)
    dragged = splitter.sizes()[0]
    assert dragged < before, f"分隔条没被真的挪动：{before} → {splitter.sizes()}"

    window.resize(1280, 1409)
    _settle(qapp)
    sizes = splitter.sizes()
    assert sizes[0] < sizes[1], (
        f"用户刚把上半区压到 {dragged}px，放大窗口就被抢回 {sizes[0]}px —— 分配政策赢了用户")
    assert page._split_locked is True, "锁没生效：resize 之后还会继续自动重算"


# —— **ISSUES I109** 丁 · 自动路径的计划级守卫 ——————————————
# 丙 的处理是「把那一格读数从 5 秒巡检节拍与建窗路径上摘掉」。只断言屏上写着「未现数」
# 是软的：谁把 `with_ocr_pages` 改回 True，那格照样渲染得出来，只是界面线程被按住几分钟
# —— 而那正是这条问题本身。所以这里问的是**计划**：把这一轮真执行过的每条 SQL 拿去
# `EXPLAIN QUERY PLAN`，出现逐行扫 `text_pages` 全表就红。

def _statements_during(ctx, run) -> list[str]:
    """跑 `run()`，回它这一轮在主线程连接上真执行过的 SQL 原文。

    用 sqlite 的 trace 回调捞，而不是在测试里重打一遍自认为会跑的查询 —— 重打的那份
    产品改了它看不见，就成了"测试自己造证据"（AGENTS.md 排障只认原始证据）。
    """
    conn = ctx.engine.thread_connection()
    seen: list[str] = []
    conn.set_trace_callback(seen.append)
    try:
        run()
    finally:
        conn.set_trace_callback(None)
    return seen


def _full_scans_of_text_pages(conn, statements: list[str]) -> list[str]:
    """把每条 SQL 拿去问计划，回那些逐行扫 `text_pages` 全表的（带 `USING` 的不算）。

    判据与 **ISSUES I109** 甲 的证据同一条：`EXPLAIN QUERY PLAN` 里
    `SCAN text_pages` = 全表逐行；走索引会打成 `SEARCH … USING INDEX` 或
    `SCAN … USING COVERING INDEX`，那两种都不该判红。
    """
    bad: list[str] = []
    for sql in statements:
        if "text_pages" not in sql:
            continue
        head = sql.lstrip().upper()
        if not head.startswith(("SELECT", "DELETE", "UPDATE", "INSERT")):
            continue
        for row in conn.execute("EXPLAIN QUERY PLAN " + sql).fetchall():
            detail = row["detail"]
            if detail.startswith("SCAN text_pages") and "USING" not in detail:
                bad.append(f"{detail}｜{sql.strip()}")
    return bad


def test_自动节拍不现数全库OCR页数(window, ctx, qapp) -> None:
    """建窗与 5 秒巡检节拍走 `reload_progress()`：这一轮一条 SQL 都不许扫正文全表。

    真库实测那条 `count(*) … source_kind='ocr'` 单条 201–212s（1,975,611 行、`source_kind`
    无索引），而这条路径的节拍是 5 秒一次 —— 挂回去等于每 tick 把界面线程按住几分钟。
    """
    block = _status_block(window, qapp)
    seen = _statements_during(ctx, block.reload_progress)
    assert seen, "trace 回调一条 SQL 都没抓到 —— 这条守卫会永真，先修捕获再谈结论"
    bad = _full_scans_of_text_pages(ctx.engine.thread_connection(), seen)
    assert not bad, f"自动路径上出现了逐行扫 text_pages 全表的查询：{bad}"
    text = block.view.toPlainText()
    assert "库里已存 OCR 正文 未现数" in text, f"没数过的那一格要明写未现数，不许显示成 0 页：{text}"


def _statements_during_button_reload(ctx, page: StatusPage, qapp) -> list[str]:
    """按下刷新按钮并等它读完，回**后台线程那条连接**上真执行过的 SQL 原文。

    按钮路径的重查在后台线程跑（**ISSUES I109** ①），用的是那条线程自己
    `engine.connect()` 的产物 —— 主线程那份 trace 一条也抓不到。所以这里把
    `Engine.connect` 临时包一层，给每条新建连接挂同一个 trace 回调。
    """
    seen: list[str] = []
    real_connect = ctx.engine.connect

    def traced_connect():
        conn = real_connect()
        conn.set_trace_callback(seen.append)
        return conn

    ctx.engine.connect = traced_connect
    try:
        page.refresh.click()
        _wait_reload(page, qapp)
    finally:
        ctx.engine.connect = real_connect
    return seen


def test_探测器在按钮路径上真的抓得到那条扫描(window, ctx, qapp) -> None:
    """上面那条的反面配对：只有按钮会现数那一格，所以探测器必须在那里报出来。

    没有这一条，`_full_scans_of_text_pages` 可以写成永远返回空列表而上面照样绿 ——
    不会变红的断言就是摆设（AGENTS.md）。顺带钉住按钮确实把那格数出来了（空夹具库 = 0 页，
    0 要显示成 `0 页` 而不是「未现数」）。
    """
    block = _status_block(window, qapp)
    seen = _statements_during_button_reload(ctx, block, qapp)
    assert seen, "后台线程那条连接一条 SQL 都没抓到 —— 这条守卫会永真，先修捕获再谈结论"
    bad = _full_scans_of_text_pages(ctx.engine.thread_connection(), seen)
    assert len(bad) == 1, f"按钮路径应当恰好出现一条全表扫描，实际 {len(bad)} 条：{bad}"
    assert "库里已存 OCR 正文 0 页" in block.view.toPlainText()


def test_按钮重读在后台跑不占住界面线程(window, ctx, qapp, monkeypatch, qtbot) -> None:
    """**ISSUES I109** ①：完整重查在后台线程跑，点击当场返回。

    判据是**点击耗时**与**点击刚返回时的正文**：把一次读数拖慢 0.6 秒（真库上那格是
    201–212 秒），同步实现会把点击一起拖住、正文当场就变；后台实现必须立刻返回、
    正文还是旧的，并且 `read_tasks` 是在非主线程里被调的。
    """
    block = _status_block(window, qapp)
    real = ctx.status.read_tasks
    names: list[str] = []

    def slow(*args, **kwargs):
        names.append(threading.current_thread().name)
        time.sleep(0.6)
        return real(*args, **kwargs)

    monkeypatch.setattr(ctx.status, "read_tasks", slow)
    before = block.view.toPlainText()

    t0 = time.perf_counter()
    qtbot.mouseClick(block.refresh, QtCore.Qt.MouseButton.LeftButton)
    elapsed = time.perf_counter() - t0

    assert elapsed < 0.2, f"点击耗时 {elapsed:.2f}s —— 重查还在 GUI 线程里同步跑"
    assert block.reloading, "点击之后没有进入'正在读'的状态，按钮无法反映进度"
    assert block.view.toPlainText() == before, "点击刚返回正文就变了 —— 同步跑才会这样"
    assert not block.refresh.isEnabled(), "读取期间按钮该禁用，否则重复点击会叠线程"

    _wait_reload(block, qapp)
    assert names, "桩没被调用：后台线程根本没开始读"
    assert names[0] != "MainThread", f"读数在主线程里跑的（thread={names[0]}）"
    assert block.refresh.isEnabled() and block.refresh.text() == "重新读取数据库状态"


# `I109` ① 三条新断言（2026-10-25 轮二十七，三条坏法各自真注入过再还原，逐字结果）：
#   坏法 A｜`reload()` 改回 `self._render(with_ocr_pages=True)`（同步渲染）⇒ **2 failed, 11 passed**：
#          一条红在 `后台线程那条连接一条 SQL 都没抓到`（主线程连接早缓存过，worker 根本没起），
#          另一条红在 `点击耗时 0.60s —— 重查还在 GUI 线程里同步跑`。
#   坏法 B｜删掉 `self.refresh.setEnabled(False)` ⇒ 只有新测试红，`读取期间按钮该禁用，否则重复点击会叠线程`。
#   坏法 C｜后台线程里改成 `_render_text(with_ocr_pages=False)`（按钮不再现数 OCR 页数）
#          ⇒ **1 failed, 12 passed**，红在 `按钮路径应当恰好出现一条全表扫描，实际 0 条` ——
#          证明探测器仍咬在按钮路径上，没有因为挪线程而跟着空转。
