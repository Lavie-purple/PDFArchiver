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

from PySide6 import QtCore

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

    assert text.count("移动、改名或删除") == 1, (
        "磁盘口径出现了不止一份。SPEC 阶段 4 之后这一句是真会变的（归档一接线就得改），"
        "两处就有了第二个口径（AGENTS.md「禁止核心概念有多个口径」）")


# 这两个按钮的共同点：按下之后**本该动磁盘**。现在执行器没接上，所以它们必须只报
# 「什么都没变」；报「已提交 / 撤销成功」就是把没做的事说成做完了
# （AGENTS.md「禁止能力不足时伪装成功」）。
FAKE_OUTCOME_CLAIMS = ("已提交", "提交到归档队列", "已开始", "已创建", "将创建",
                       "已撤销", "撤销成功", "已移动", "已搬")


def test_没接上执行器的按钮不许伪装成功(window, ctx, qapp, monkeypatch, tmp_path) -> None:
    from PySide6.QtWidgets import QMessageBox

    from pdfarchiver.db.models import Document

    shown: list[str] = []
    monkeypatch.setattr(QMessageBox, "information",
                        staticmethod(lambda parent, title, text, *a, **k: shown.append(text)))
    monkeypatch.setattr(QMessageBox, "warning",
                        staticmethod(lambda parent, title, text, *a, **k: shown.append(text)))

    # 撤销要有批次可选，而这条批次必须在**取基线之前**建好 —— 它是对照的起点，
    # 不是被测动作的产物；建晚了就只能拿"+1"当预期，测的就不是"没动盘"了。
    ctx.operations.create_operation("archive")
    ops_before = len(ctx.operations.list_operations(limit=200))
    jobs_before = ctx.jobs.count()

    # S3 执行归档：灌一份文档、勾上、给目标根，然后真的点按钮
    path = str(tmp_path / "待归档.pdf")
    ctx.documents.upsert(Document(
        path=path, path_key=path.casefold(), name="待归档.pdf", size_bytes=1024,
        mtime_ns=1_760_000_000_000_000_000, sha256=f"{1:064x}",
        text_status="done", fts_status="done"))
    window._select_by_page_id("archive")
    _settle(qapp)
    page = window._pages["archive"]
    page._load_documents()
    page.doc_table.item(0, 0).setCheckState(QtCore.Qt.CheckState.Checked)
    page.target_root_input.setText(str(tmp_path / "归档库"))
    page.execute_btn.click()

    # S4 整批撤销：选中上面那条批次，点撤销
    window._select_by_page_id("operations")
    _settle(qapp)
    ops_page = window._pages["operations"]
    ops_page.reload()
    assert ops_page.op_table.rowCount() >= 1, "撤销那屏列不出批次，测试前提坏了"
    ops_page.op_table.setCurrentCell(0, 0)
    ops_page.undo_btn.click()

    assert len(shown) == 2, f"两个按钮各该报一次，实际报了 {len(shown)} 次：{shown}"
    for text in shown:
        assert not any(w in text for w in FAKE_OUTCOME_CLAIMS), f"文案谎报了后果：{text!r}"
        assert "磁盘" in text, f"没接上执行器的按钮必须明说磁盘上没动过：{text!r}"
    assert len(ctx.operations.list_operations(limit=200)) == ops_before, (
        "点过「执行归档」和「撤销」之后台账里多出了批次 —— 界面在背地里建批次了")
    assert ctx.jobs.count() == jobs_before, (
        "点过之后队列里冒出了任务，可文案说的是「还没接上」 —— 读数与行为对不上")


def test_S3_上未接线的那两条只许来自那一份列表(window, ctx, qapp, monkeypatch) -> None:
    """**ISSUES I55** 乙（2026-10-17，用户「勾选的清单 均听你推荐」）要的形状：**可以挂账，
    但事实必须显示在控件旁边**。

    「命名模板」那一栏改了什么都不变，而屏幕上一点看不出来 —— 用户会以为自己已经分好了目录，
    这比"按钮按下去没反应"更阴（I55 原文就是这么记的）。所以这条钉四件事：
    ① S3 上有一条**在场且可见**的说明，同时点名「执行归档」与「命名模板」；
    ② 那句话是**从 `status_page.UNWIRED_ACTIONS` 拼出来的**，不是界面手抄的一句道歉 ——
       硬证明是把来源里那条撤掉再重开一屏，屏上那句必须跟着消失（手抄的会当场留在原地，
       而留在原地的那句从此没有来源，代码一改就变成假话，与上面那条守卫盯的是同一条规则）；
    ③ 说明里不许出现承诺后果的词（`FAKE_OUTCOME_CLAIMS`）；
    ④ 不许把磁盘口径那句再抄一份到 S3（`DISK_EFFECT_LINE` 全站只许一处）。

    **断言顺序是设计的一部分，别顺手重排**：坏法注入实测（2026-10-17，
    `.probe_work/i55_guard_injection.py`，台账要求「红**且点名**」）里，① ② ③ ④ 各被一条独立
    坏法打到自己的那句消息上；把同源比对挪到最前面之后，「抄了半句磁盘口径」与「承诺后果」两种坏法
    都会先撞在②上、从而**验不到 ③ ④ 自己**。台账里还留着一课：第一轮有一条坏法写成
    `setText(...) + "…"`，`NoneType + str` 当场抛错被 Qt 吞在 `_make_page` 里，测试红在
    `KeyError: 'archive'` —— 红的是坏法自己坏了，不是守卫有效。
    """
    from pdfarchiver.ui.pages import status_page
    from pdfarchiver.ui.pages.archive_page import ArchivePage

    window._select_by_page_id("archive")
    _settle(qapp)
    page = window._pages["archive"]
    text = page.unwired_label.text()

    assert page.unwired_label.isVisibleTo(page), "说明挂在屏上但不可见 = 等于没有"
    assert "命名模板" in text and "不会照着改名" in text, f"断链的那一栏必须自己说清楚：{text!r}"
    assert "执行归档" in text, f"同一个屏上还有第二条断链，不能只说一半：{text!r}"
    assert not any(w in text for w in FAKE_OUTCOME_CLAIMS), f"未接线说明里承诺了后果：{text!r}"
    # 查的是那句话的**语义核心**而不是整条常量：整条比对会放过"抄半句"这种最常见的复写
    assert "移动、改名或删除" not in text, "磁盘口径那句话只许在 DISK_EFFECT_LINE 一份"
    assert text == "本轮未接线：" + "；".join(status_page.unwired_lines("S3")), (
        "S3 那句不是从唯一来源拼出来的")

    monkeypatch.setattr(status_page, "UNWIRED_ACTIONS", tuple(
        a for a in status_page.UNWIRED_ACTIONS if not a.startswith("S3 命名模板")))
    fresh = ArchivePage(ctx)
    assert "命名模板" not in fresh.unwired_label.text(), (
        "撤掉来源里那条，屏上那句还留着 —— 它是手抄的，不是拼出来的")
    assert "执行归档" in fresh.unwired_label.text(), "撤错条目了：撤的必须是模板那一条"
