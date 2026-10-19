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

from PySide6 import QtCore, QtWidgets

from pdfarchiver.ui.nav import NAV_ITEMS
from pdfarchiver.ui.pages.settings_page import SettingsPage
from pdfarchiver.ui.pages.status_page import StatusPage, UNWIRED_ACTIONS
from tests.conftest import settle as _settle


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
    assert "queued=1" in page.view.toPlainText()

    make_pdf("刷新读数/丑.pdf", page_lines=["丑文档的正文内容字符"])
    ctx.scan.scan_root(r)
    qtbot.mouseClick(page.refresh, QtCore.Qt.MouseButton.LeftButton)
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

    判据按**最小窗高 720**（D-039 那档地板）反算，不是随手取的分数：
    改前 offscreen 实测（`.probe_work/i75_split_needs.py`）两栏 sizeHint 258 / 447 = 36.6%，
    而窗口 720 / 800 / 1409 三档上半区**恒为 36%**（`sizes=[247,428] / [276,479] / [499,865]`），
    可见行数 12 / 14 / 31（48 行的 25% / 29% / 64%）。按内容分配之后同一档实测 18 / 24 / 48 行
    （37.5% / 50% / 100%），所以这里钉两档：**地板档 ≥ 内容行数的三分之一**、
    **最大化档 1409 一屏看全**（那正是用户会做的动作，也是原报障里"最大化也不解决"那半句）。
    """
    block = _status_block(window, qapp)
    view = block.view
    lh = view.fontMetrics().height()
    blocks = view.document().blockCount()
    assert lh > 0 and blocks > 0, "读数框没内容就量不出比例，这条断言会假绿"

    for win_h, floor in ((720, blocks // 3), (1409, blocks)):
        window.resize(1280, win_h)
        _settle(qapp)
        splitter = window._pages["monitor"].findChild(QtWidgets.QSplitter)
        assert splitter is not None, "S7 取不到那个竖排 QSplitter"
        visible = view.viewport().height() // lh
        assert visible >= floor, (
            f"窗口高 {win_h}：上半区视口只装得下 {visible}/{blocks} 行（要求 ≥ {floor}）"
            f"，sizes={splitter.sizes()}")


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
