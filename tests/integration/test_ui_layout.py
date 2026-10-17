"""地板档布局守卫：任何一屏都不许把侧栏榨瘪，定宽列必须装得下它那一列能产出的最宽读数。

从 `test_app_shell.py` 拆出（**ISSUES I58** 丙，2026-10-17；线管所有 `.py`，见 **R-010**）。
与 `test_ui_tier.py` 的分工：那一档量的是**同一个控件在两个宽度档下的形状**（判据取自
`ui/tier.py`），这一档量的是**压到地板时不越界**（判据取自 `main_window.py` 的 MIN_*
与 `ui/table_layout.py` 的常量，两处都不写死像素）。

所有量都在 offscreen 下读真实几何。判据里每条实测数字都注了出处，改之前先复跑
`tests/probes/`，别照抄注释。
"""
from __future__ import annotations

from pathlib import Path

import pytest
from PySide6 import QtWidgets

from pdfarchiver.ui.main_window import (
    DEFAULT_WINDOW_WIDTH,
    MIN_WINDOW_HEIGHT,
    MIN_WINDOW_WIDTH,
    NAV_WIDTH,
)
from pdfarchiver.ui.nav import NAV_ITEMS
from pdfarchiver.ui.table_layout import CELL_PADDING_WIDTH, ELIDABLE_COLUMNS
from tests.conftest import settle as _settle


# —— 布局守卫：任何一屏都不许把侧栏榨瘪 ——————————————————————————————
# 出处是界面审核发现 1（单行不折行的长文字）。可用宽度按 **D-039 的地板档 1024** 算，
# 不按 1280 的设计档算：地板是用户能压到的最窄处，在设计档上量等于把守卫放松 256px。
# 两个数都取自外壳本身（MIN_WINDOW_WIDTH / NAV_WIDTH），不在这里另立口径。

AVAILABLE_WIDTH = MIN_WINDOW_WIDTH - NAV_WIDTH - 1

# 环境里的临时路径太短，顶不出这个坏法；自己钉一条 247 字符的（现测 len(str(...)) = 247）。
# 尾段是一整串无空格 ASCII（Qt 把 CJK 逐字当可断点，全中文的长路径自己就能折断），
# 结尾留一个独特文件名，用来区分"中段省略"和"尾段截断"。
# 用户名位写成 local 而不是真用户名：这条只是形状夹具，规则见 docs/REPO-JOURNAL.md R-003
# （commit 前 `git grep` 本机用户名与私人目录名，命中即改；同类事故已出过一次，提交 0e808d0）。
LONG_DB_PATH = (Path("C:/Users/local/AppData/Local/PdfArchiver/profiles")
                / ("log" * 60) / "catalog-final.db")


@pytest.mark.parametrize("page_id", [i.page_id for i in NAV_ITEMS if i.implemented])
def test_每屏在地板宽度下都装得下且不吃侧栏(window, ctx, page_id, qapp, monkeypatch) -> None:
    """一条不可折行的长文字（典型是 Windows 绝对路径）会把该页 minimumSizeHint 顶到
    比窗口还宽，QSplitter 于是把侧栏压到它的 minimumSizeHint —— 实测 backup 页一条
    103 字符的路径让侧栏从 200px 掉到 **56px**，而且 splitter 尺寸是被撑大的那一份，
    切回别的屏也不恢复。D-040 只授权在宽度不足时牺牲命中面板，侧栏不在授权范围内。

    先把库路径钉成一条 243 字符的长 ASCII 路径再逐屏量：环境里的临时路径太短，
    不钉的话这个坏法能骗过断言（实测同一段代码，短路径下本页最低宽度 510px、
    长路径下 2935px，只有后者会红）。

    三条断言对应三种坏法，缺一漏一半：
    - 页面最低宽度 > 地板档侧栏之外的可用宽度 → 侧栏被榨瘪；
    - 窗口自身布局算出的最低宽度 > D-039 的地板 → `setMinimumSize` 是假的，
      用户连"把窗口缩到 1024"都做不到（Qt 实际用的最低宽是两者的较大值）；
    - 真把窗口压到地板再量侧栏 → 抓的是"声明了地板但页面仍然顶宽"这一类，
      前两条都只比 hint，不量 splitter 实际分到的宽度。
    """
    monkeypatch.setattr(ctx.engine, "path", LONG_DB_PATH)
    window._select_by_page_id(page_id)
    window._refresh_current()
    qapp.processEvents()

    page = window._pages[page_id]
    budget = AVAILABLE_WIDTH
    # QTabWidget 只把**当前**标签页的尺寸算进 minimumSizeHint；隐藏标签页里的长文字
    # 要到切过去的那一刻才顶宽（实测把恢复标签页的一条裸路径留在里面，这条断言照样绿）。
    # 所以逐屏量之前要把每屏的每个标签页都轮一遍。
    for tabs in page.findChildren(QtWidgets.QTabWidget):
        for i in range(tabs.count()):
            tabs.setCurrentIndex(i)
            qapp.processEvents()
            assert tabs.minimumSizeHint().width() <= budget, (
                f"{page_id} 第 {i + 1} 个标签页（{tabs.tabText(i)}）最低宽度 "
                f"{tabs.minimumSizeHint().width()}px，超过侧栏之外的可用 {budget}px")

    assert page.minimumSizeHint().width() <= budget, (
        f"{page_id} 的最低宽度 {page.minimumSizeHint().width()}px 超过地板档下侧栏之外"
        f"的可用 {budget}px —— 侧栏会被榨瘪（实测掉到 56px 且切屏不恢复）")
    assert window.minimumSizeHint().width() <= MIN_WINDOW_WIDTH, (
        f"{page_id} 让窗口自身布局的最低宽度到了 {window.minimumSizeHint().width()}px，"
        f"超过 D-039 的地板 {MIN_WINDOW_WIDTH}px —— setMinimumSize 挡不住它，"
        f"Qt 取两者较大值，用户压不到 1024")

    window.resize(MIN_WINDOW_WIDTH, MIN_WINDOW_HEIGHT)
    _settle(qapp)
    assert window.nav.width() >= NAV_WIDTH, (
        f"{page_id} 在地板档 {MIN_WINDOW_WIDTH}px 下把侧栏压到了 {window.nav.width()}px"
        f"（应当还是 {NAV_WIDTH}px）—— I52 的坏法重现")


def test_选中备份文件之后恢复标签页也不许顶宽(window, ctx, qapp, monkeypatch) -> None:
    """上一条逐标签页量的是**静态**内容；`QTabWidget` 只把当前标签页算进
    minimumSizeHint，所以"点了按钮之后才填进去的长路径"它看不见（实测把
    `lbl_selected` 换成裸路径，上一条照样绿）。这条走真的那条路：选一个深路径的备份。
    """
    from PySide6.QtWidgets import QFileDialog, QMessageBox

    # 成功/失败都会弹模态框，测试里不拦下来就直接卡住
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a, **k: None))
    monkeypatch.setattr(QMessageBox, "critical", staticmethod(lambda *a, **k: None))

    deep = str(LONG_DB_PATH)
    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: (deep, "")))
    window._select_by_page_id("backup")
    page = window._pages["backup"]
    tabs = page.findChildren(QtWidgets.QTabWidget)[0]
    tabs.setCurrentIndex(1)
    qapp.processEvents()

    page._select_backup()
    qapp.processEvents()

    budget = AVAILABLE_WIDTH
    assert tabs.minimumSizeHint().width() <= budget, (
        f"填进真实路径后，恢复标签页最低宽度 {tabs.minimumSizeHint().width()}px，"
        f"超过侧栏之外的可用 {budget}px")
    assert "…" in page.lbl_selected.text(), f"路径没中段省略：{page.lbl_selected.text()!r}"
    assert page.lbl_selected.toolTip() == deep, "完整路径要能在悬停里回读"

    # 同一标签页上还有第三条会填路径的标签（恢复结果），坏法一模一样，顺手一起钉住
    monkeypatch.setattr(QFileDialog, "getExistingDirectory",
                        staticmethod(lambda *a, **k: deep))
    monkeypatch.setattr(ctx.backup, "restore_to_new_dir", lambda *a, **k: Path(deep))
    page._restore_to_new_dir()
    qapp.processEvents()
    assert tabs.minimumSizeHint().width() <= budget, (
        f"填进恢复结果路径后，恢复标签页最低宽度 {tabs.minimumSizeHint().width()}px，"
        f"超过侧栏之外的可用 {budget}px")
    assert "…" in page.lbl_restore_result.text(), "恢复结果里的新库路径同样要中段省略"


def test_截掉的路径必须能在悬停里回读(window, ctx, qapp, monkeypatch) -> None:
    """上一条管"不许顶宽"，这一条管"顶不宽了也不能把信息弄丢"。

    中段省略是 S5 判重表已经定下的口径（表头直接写着"路径（悬停看全长）"）：
    盘符和文件名两端都要看得见，完整值靠 tooltip 回读。
    """
    monkeypatch.setattr(ctx.engine, "path", LONG_DB_PATH)
    window._select_by_page_id("backup")
    page = window._pages["backup"]
    page._reload_current_info()
    qapp.processEvents()

    assert "…" in page.lbl_current.text(), "够长却没省略 = 截断没生效（或干脆没截）"
    assert str(LONG_DB_PATH) in page.lbl_current.toolTip(), "截掉的完整路径必须能在 tooltip 里回读"
    assert page.lbl_current.text().startswith("当前库：C:"), "开头（盘符）要留着才能认出是哪台盘"
    assert "catalog-final.db" in page.lbl_current.text(), \
        "结尾（文件名）也要留着 —— 变成尾段截断就看不出是哪个库了"


# 用户真正要读、且**长度不固定**的那几列，在各页的表头文案。
# 判重表的「SHA256（前8位）」不在这里：它是定长 8 个十六进制字符（约 55px），
# 100px 的默认宽都截不断它，给它设 200px 底线只是把阈值调到一个坏法根本骗不过它的数字上。
# 与 `table_layout.ELIDABLE_COLUMNS` 的分工：本集合是"可以截断、但必须还能看出目录层次"
# 的那几条路径列；后者是它的超集（多「分类」「错误」），装得下/回读得上的守卫用后者 ——
# 两套列名不许各说各话，末尾单独一条断言钉住子集关系。
CONTENT_COLUMNS = {"文件名", "路径", "源路径", "目标路径", "路径（悬停看全长）"}
# 200px：13px 字体下约 15 个汉字，是一条绝对路径能不能看出目录层次的底线。
# 40px：证明没有任何一列被 Stretch 压成缝（实测压瘪后是 38px／25px，见下面两条测试）。
MIN_CONTENT_WIDTH = 200
MIN_ANY_WIDTH = 40


@pytest.mark.parametrize("page_id", [i.page_id for i in NAV_ITEMS if i.implemented])
def test_表格不许把内容列压成一条缝(window, ctx, page_id, qapp) -> None:
    """钉住两种坏法。

    ① 八张表原先都只写一句 `setStretchLastSection(True)`：除最后一列以外全留在 Qt 默认的
    100px，剩余宽度一律给最后一列 —— 实测文档库「文件名」100px 而「分类」225px，
    操作日志把 688px 给了「失败」这一列**计数**。
    ② 改成显式定宽后又踩到第二个坑：定宽列已经把视口吃掉时，Stretch 那一列被压成几十像素的
    缝（文档库「分类」实测 38px、归档「文件名」压到窗口最低时实测 25px），而且**永远是这一条缝** ——
    横向滚动条本身是好的（Qt 的滚动范围按"档"不按像素，maximum()==2 也能滚完整段超出量），
    滚过去看见的仍是个窄条。
    """
    window._select_by_page_id(page_id)
    _settle(qapp)
    for table in window._pages[page_id].findChildren(QtWidgets.QTableWidget):
        header = table.horizontalHeader()
        widths = [header.sectionSize(c) for c in range(table.columnCount())]
        for col, name in enumerate(
                [table.horizontalHeaderItem(c).text() if table.horizontalHeaderItem(c) else "?"
                 for c in range(table.columnCount())]):
            floor = MIN_CONTENT_WIDTH if name in CONTENT_COLUMNS else MIN_ANY_WIDTH
            assert widths[col] >= floor, (
                f"{page_id} 的「{name}」列只有 {widths[col]}px，低于底线 {floor}px"
                f"（该表列宽 {widths}，视口 {table.viewport().width()}px）")


def test_表格定宽列放不下时必须还能滚到(window, ctx, qapp) -> None:
    """全定宽这条修法的前提是"滚得过去"，所以把前提本身钉住，而不是只钉列宽。

    文档库中栏视口实测 463px（**ISSUES I54 已销**：行号列不再长出来，读数不随行的位数漂；
    40 行时 455px，少的 8px 是纵向滚动条），五列定宽合计 780px（220+200+86+163+111）
    —— 装不下是设计内的（D-040：1024px 下
    宁可牺牲命中面板也不动侧栏）。装不下时剩下的列**必须仍然可达**：横向滚动条可用，
    且把滚动值拧到底之后最后一列会进视口。
    """
    window._select_by_page_id("library")
    _settle(qapp)
    table = window._pages["library"].doc_table
    last = table.columnCount() - 1
    bar = table.horizontalScrollBar()
    assert table.viewport().width() < sum(
        table.horizontalHeader().sectionSize(c) for c in range(table.columnCount())), (
        "前提没了：五列已经能全部装进视口，那这条测试该改成量别的")
    assert bar.maximum() >= 1 and bar.isVisible(), (
        f"列宽超出视口却没有可用的横向滚动条（maximum={bar.maximum()}，"
        f"可见={bar.isVisible()}）—— 超出部分等于被裁掉")
    bar.setValue(bar.maximum())
    _settle(qapp)
    assert table.columnViewportPosition(last) < table.viewport().width(), (
        "滚到底也到不了最后一列 —— 定宽列超出视口时被裁掉了，等于那列永远看不见")


def test_压到地板宽度时归档表仍保住文件名与路径(window, ctx, qapp) -> None:
    """吸收列放在哪一列，决定窗口压窄时**谁**被牺牲，所以这条单独钉住那一列。

    归档页的定宽三列（选择 56 + 文件名 280 + 路径 240）合计 576px。**D-039 立了 1024px 地板
    之后**，侧栏之外的可用宽度只剩 823px，这一档实测视口 805px（**ISSUES I54 已销** ⇒ 与行数无关；
    40 行时 797px，差的 8px 是纵向滚动条）—— 576px 装得下，剩余宽度由「分类」这条吸收列吃掉
    （实测 229px，40 行时 221px）。
    **地板之前**窗口能压到 356px、视口 281px，那时必然装不下，而被压瘪的正是内容列
    （那是 **ISSUES I52** 的坏法，现在压不到了）—— 所以这条守卫今天钉的是"地板真的挡住了它"。
    原先把吸收列放在「文件名」上，压窄时牺牲的恰好是用户唯一要读的那一列；现在放在「分类」上
    （左栏分类树里本来就有），文件名/路径按定宽保住。
    """
    window._select_by_page_id("archive")
    _settle(qapp)
    # 一级一级压到底，不能一次跳过去：实测从 1000 直接 resize 到 356 时 QHeaderView
    # **不重排 Stretch 列**，读数还留着 1000px 时的 375px —— 守卫会因此假绿
    # （注入坏法验证时被抓到一次）。步进才等效于用户拖窗口。
    for width in range(DEFAULT_WINDOW_WIDTH, MIN_WINDOW_WIDTH - 1, -50):
        window.resize(width, MIN_WINDOW_HEIGHT)
        _settle(qapp, rounds=4)
    window.resize(MIN_WINDOW_WIDTH, MIN_WINDOW_HEIGHT)
    _settle(qapp)
    assert window.width() == MIN_WINDOW_WIDTH, (
        f"窗口压不到 D-039 的地板：停在 {window.width()}px —— 地板被页面顶宽了")

    header = window._pages["archive"].doc_table.horizontalHeader()
    widths = {
        window._pages["archive"].doc_table.horizontalHeaderItem(c).text(): header.sectionSize(c)
        for c in range(window._pages["archive"].doc_table.columnCount())}
    assert widths["文件名"] >= MIN_CONTENT_WIDTH, (
        f"窗口压到地板 {MIN_WINDOW_WIDTH}px 时「文件名」只剩 {widths['文件名']}px，"
        f"说明吸收列又落回了内容列上：{widths}")
    assert widths["路径"] >= MIN_CONTENT_WIDTH, f"「路径」同样被压瘪：{widths}"


# ---------------------------------------------------------------------------
# 定宽列必须装得下它那一列**格式能产出的最宽读数**
# ---------------------------------------------------------------------------
# 上面三条量的是"底线"（内容列 ≥200px / 任何列 ≥40px），它们管的是列被压成缝，
# 管不到"列看着挺宽、值却带省略号"。实测漏网的就是这一类：I48 那轮反算的是**文本宽**
# （修改时间 110px、大小 41px）然后给了 +8，而 Qt 单元格的内边距实测 23px
# （`sizeHintForColumn − 最长文本 advance`，五张表五个列都得 23）——
# 于是「大小」显示成 `1…`、「修改时间」显示成 `2026-1…`、批次「状态」显示成 `parti…`，
# 三屏四列全都恰好差那一截。
#
# 宽度模型用字符类别而不是运行时字体：离屏平台上这里**一个 UI 字体都没有**
# （Microsoft YaHei UI / Microsoft YaHei / Segoe UI 全部缺席），`horizontalAdvance`
# 把数字位量成 13px，比真机宽近一倍 —— 直接拿它当"需要宽"会把阈值抬到一个
# 好版本也过不了、只有把列宽翻倍才能过的数字上。13px UI 字体的现实量级：
# ASCII ≈7px（`2026-10-15 12:34` 16 字符 = 112px，与 I48 实测的 110px 对得上），
# 汉字与全角标点 ≈13px（1 em，这条离屏也量得准）。
ASCII_CHAR_WIDTH = 7
WIDE_CHAR_WIDTH = 13


def _estimated_text_width(text: str) -> int:
    return sum(WIDE_CHAR_WIDTH if ord(ch) > 127 else ASCII_CHAR_WIDTH for ch in text)


def _need_for(column_name: str, cells: list[str]) -> int:
    """该列必须容下的宽度：列头与最坏读数取最宽，再加单元格内边距。"""
    return max([_estimated_text_width(column_name)]
               + [_estimated_text_width(t) for t in cells]) + CELL_PADDING_WIDTH


def _seed_worst_readings(window, ctx, page_id: str) -> None:
    """把每列**格式能产出的最宽读数**灌进去，别让守卫只看列头。

    空表量不到值 —— 上一轮就是这么假绿的：文档库和备份页在测试库里都是 0 行，
    「大小」「修改时间」窄到只显示一个 `1` 也没人报警。
    """
    from datetime import datetime, timezone

    from pdfarchiver.db.models import Document

    if page_id == "library":
        # 大小档位在 1024 进位，最宽读数因此是 `1023.9 MB`（9 字符）
        widest_mb = int(1023.9 * 1024 * 1024)
        stamp = datetime(2026, 10, 16, 16, 8, 30, tzinfo=timezone.utc).timestamp()
        for name in ("归档范围与保留期限的请示（复函稿）.pdf", "Introduction-to-Statistical-Learning.pdf"):
            path = f"D:\\用户资料\\2026 年度合同与结算凭证归档\\{name}"
            ctx.documents.upsert(Document(
                path=path, path_key=path.casefold(), name=name,
                size_bytes=widest_mb, mtime_ns=int(stamp * 1_000_000_000),
                sha256=f"{hash(name):064x}", text_status="done", fts_status="done"))
    elif page_id == "operations":
        op = ctx.operations.create_operation("archive")
        ctx.operations.add_item(op.id, None, "move", "D:\\a.pdf", "D:\\b.pdf")
        ctx.operations.finish_operation(op.id, status="partially_done")
    elif page_id == "backup":
        ctx.backup.create_backup()
    elif page_id == "duplicates":
        # 判重页最宽读数：浪费量 "999.99 GB"、SHA 固定 8 字符、份数 3 位、状态 "缺+硬链接"。
        # 灌一条重复组（2 份同哈希），让表格有数据可量。
        from pdfarchiver.db.models import Document
        sha = "a" * 64
        for i, name in enumerate(("report_1.pdf", "report_1_copy.pdf")):
            ctx.documents.upsert(Document(
                path=f"D:\\docs\\{name}", path_key=f"d:\\docs\\{name}".casefold(),
                name=name, size_bytes=500 * 1024 * 1024,  # 500 MB × 2 = 浪费 500 MB
                sha256=sha, text_status="done", fts_status="done"))


@pytest.mark.parametrize("page_id", [i.page_id for i in NAV_ITEMS if i.implemented])
def test_定宽列必须装得下最宽读数(window, ctx, page_id, qapp) -> None:
    """两条承诺按列分工：**不许截断的列**必须装得下，**允许截断的列**必须能悬停回读。

    判重表已并进 `set_table_columns` 定宽口径（ISSUES I61 选甲），与其他 7 张表统一。
    """
    _seed_worst_readings(window, ctx, page_id)
    window._select_by_page_id(page_id)
    _settle(qapp)

    for table in window._pages[page_id].findChildren(QtWidgets.QTableWidget):
        header = table.horizontalHeader()
        for col in range(table.columnCount()):
            head_item = table.horizontalHeaderItem(col)
            name = head_item.text() if head_item else "?"
            if header.sectionResizeMode(col) != QtWidgets.QHeaderView.ResizeMode.Interactive:
                continue                      # Stretch / ResizeToContents 由另两条守卫管
            cells = [table.item(r, col).text() for r in range(table.rowCount())
                     if table.item(r, col) is not None and table.item(r, col).text()]
            actual = header.sectionSize(col)
            if name in ELIDABLE_COLUMNS:
                # 内容天生无上限（绝对路径 / 用户自定义分类名 / 第三方报错原文），
                # 所以不承诺装得下，改承诺"每一格都能悬停读回全文"。
                for r, text in enumerate(cells):
                    assert table.item(r, col).toolTip() == text, (
                        f"{page_id} 的「{name}」列第 {r} 行截断了却没有 tooltip 回读全文："
                        f"{text[:40]!r}")
                continue
            need = _need_for(name, cells)
            assert actual >= need, (
                f"{page_id} 的「{name}」列给 {actual}px，最宽读数要 {need}px"
                f"（最长值 {max(cells, key=_estimated_text_width)[:24]!r} + 内边距 "
                f"{CELL_PADDING_WIDTH}px）—— 该列会显示成省略号")


def test_内容列集合必须还是可截断列集合的子集() -> None:
    """两套列名各说各话，早晚会有一列"既没人承诺装得下、也没人承诺能回读"。"""
    assert CONTENT_COLUMNS <= ELIDABLE_COLUMNS, (
        f"只在 CONTENT_COLUMNS 里的列：{sorted(CONTENT_COLUMNS - ELIDABLE_COLUMNS)}")
