"""**ISSUES I54 / I107 / I60 / D-051 / D-040** 的表格与状态栏几何 —— 十张表与 S1 中栏那一句
口径话在两个宽度档下的真实读数。

这一组从 `test_ui_tier.py` 拆出来（轮六十 2026-11-04，**AGENTS.md** 那条「单文件超 800 行就拆，
每次改动顺手迁一个模块」；**ISSUES I58** 丙 / **D-054** 是同一规矩的前两次落地）。拆的刀口在
**量的对象**：`test_ui_tier.py` 管的是"可收起面板在宽度档下收成什么形状"（判据全来自
`ui/tier.py` 的常量），这一组管的是"表里那一行行、状态栏那一句句占掉多少像素"（判据来自
`ui/table_layout.py` 的列宽声明与 `QTableView` 自己的视口）。两条链只在"同一个窗口宽"上相遇。

所有断言照旧在 offscreen 量**真实几何**，不量截图（离屏平台没有 CJK 字形，而这里全部毛病
都是"数字看着对、其实没重排"）。共享的三样东西走 `tests/conftest.py` 那一份：`_page_at`
（切屏 + reload + resize）、`_seed_docs`（灌进行）、`PAGE_WIDTH_AT_FLOOR`（页面可用宽口径）。
"""
from __future__ import annotations

from PySide6 import QtWidgets

from pdfarchiver.db.models import Document, TextPage
from pdfarchiver.db.repositories.documents import DocFilter
from pdfarchiver.fs.identity import identity_key
from pdfarchiver.services.bootstrap import AppContext
from pdfarchiver.ui.main_window import (
    DEFAULT_WINDOW_HEIGHT,
    DEFAULT_WINDOW_WIDTH,
    MIN_WINDOW_HEIGHT,
    MIN_WINDOW_WIDTH,
)
from pdfarchiver.ui.nav import NAV_ITEMS
from tests.conftest import (
    PAGE_WIDTH_AT_FLOOR,
    page_at as _page_at,
    run_search as _run_search,
    seed_docs as _seed_docs,
    settle as _settle,
)


def test_文档表行高统一不许变行高展开(window, ctx, qapp) -> None:
    """**D-040** 表里第一行的形状：行高统一 ⇒ 行号↔坐标换算保持 O(1)。

    为什么判"各行等高"而不是判"等于 `defaultSectionSize`"：统一的加高行仍然是 O(1)，
    规则禁的是"按行撑高"（实测 `resizeRowsToContents()` 把三行量成 [85, 85, 16]）——
    8 万行档那版一撑就要整表测高，AGENTS.md 明令禁止 O(n²)。
    """
    _seed_docs(ctx)
    page = _page_at(window, qapp, "library", DEFAULT_WINDOW_WIDTH, DEFAULT_WINDOW_HEIGHT)
    heights = [page.doc_table.rowHeight(r) for r in range(page.doc_table.rowCount())]
    assert len(heights) >= 2, f"用例前提：得真的灌进行，空表量不到行高：{heights}"
    assert len(set(heights)) == 1, f"行高不齐 {heights} —— 行号↔坐标不再是 O(1)"


# ---------------------------------------------------------------------------
# **ISSUES I54**：Qt 自动长出来的行号列
# ---------------------------------------------------------------------------
# 全项目没有一处主动要过这一列，但只要有行它就在场，而且**按行号的位数变宽**
# （2026-10-17 现测：空表 0 / 2 行 38 / 40 行 51px）。两条断言分管两头：
# 第一条管"在场不在场"（逐屏扫），第二条管"在场会造成什么"（视口随数据量漂）。


def test_每张表都不许带行号列(window, ctx, qapp) -> None:
    """10 张表逐个点名 —— 这条是"第 11 张表冒出来时会不会漏"的牙。

    坏法注入（本轮真跑）：删掉 `table_layout.set_table_columns()` 里那行
    `verticalHeader().hide()` → 7 张表当场红；判重页那张不经 `set_table_columns`
    （表头按内容自适应），所以它自己一行 `hide()` 也在被扫的范围里 —— 两处任删一处都红。
    """
    _seed_docs(ctx, 40)   # 空表量不出行号列，必须灌进行
    seen = 0
    for item in NAV_ITEMS:
        if not item.implemented:
            continue
        window._select_by_page_id(item.page_id)
        _settle(qapp)
        page = window._pages[item.page_id]
        assert page.isVisible(), f"用例前提：{item.page_id} 得是当前可见页，否则量到的都是 0"
        # 有 reload 的页重查一遍（archive / operations 没有，它们不随库里的行数变）：
        # 只有真的灌进行，`verticalHeader().width()` 才是非 0 的读数，断言才不只是"标志位对不对"。
        reload = getattr(page, "reload", None)
        if callable(reload):
            reload()
            _settle(qapp)
        for table in page.findChildren(QtWidgets.QTableWidget):
            seen += 1
            vh = table.verticalHeader()
            assert vh.isHidden() and vh.width() == 0, (
                f"{item.page_id} 的表（{table.objectName() or '未命名'}，"
                f"{table.rowCount()} 行）带着行号列：宽 {vh.width()}px —— "
                f"它没经 `set_table_columns()` 也没自己 `hide()`（ISSUES I54）")
    assert seen == 10, f"全站该扫到 10 张表，实际 {seen} 张 —— 有页面新增了表或表被拆掉了，重数一遍再改注释"


def test_每张表都是单行行高_不许开自动换行(window, ctx, qapp) -> None:
    """**ISSUES I107**：`wordWrap` 开着时，Qt 把「反斜杠 + CJK 混排」的长路径画成 `C…`。

    真桌面实测（2026-10-24，S3 计划表）：同一格 260px、文本 98 字符，`ElideRight` 下整行只剩
    一个字符加省略号；同一格换成正斜杠串立刻正常，`setWordWrap(False)` 后也恢复正常
    （对照图 `.probe_work/_plan_repro_full.png` / `_plan_nowrap.png`）。离屏平台不复现这条
    绘制差异（CJK 字形本就缺），所以这里钉的是**开关**：10 张表一律 `wordWrap() is False`。

    坏法注入（2026-10-24 真跑过）：删掉 `table_layout.set_table_columns()` 里那行
    `setWordWrap(False)` → 这里 10 张表逐张红并点名；还原后绿。
    """
    seen = 0
    for item in NAV_ITEMS:
        if not item.implemented:
            continue
        window._select_by_page_id(item.page_id)
        _settle(qapp)
        page = window._pages[item.page_id]
        assert page.isVisible(), f"用例前提：{item.page_id} 得是当前可见页，否则扫不到表"
        reload = getattr(page, "reload", None)
        if callable(reload):
            reload()
            _settle(qapp)
        for table in page.findChildren(QtWidgets.QTableWidget):
            seen += 1
            assert not table.wordWrap(), (
                f"{item.page_id} 的表（{table.objectName() or '未命名'}）开着自动换行 —— "
                "单行行高 + ElideRight 会把反斜杠 CJK 路径画成 `C…`（ISSUES I107）；"
                "经 `set_table_columns()` 建的表都该被那一行关掉")
    assert seen == 10, f"全站该扫到 10 张表，实际 {seen} 张 —— 有页面新增了表或表被拆掉了"


def test_视口宽度只随滚动条变不随行的位数变(window, ctx, qapp) -> None:
    """I48 那套列宽反算的分母必须是个**定值**，否则"装不装得下"随数据量漂。

    实测对照（S1 中栏、宽档页面 1079px）：修复前 0 行 463 / 2 行 425 / 40 行 404，
    修复后 0 行 463 / 2 行 463 / 40 行 455。剩下那 8px 是**纵向滚动条**（40 行时
    `verticalScrollBar()` 才出现，实测宽 8px）—— 那是真在占地方，不修，所以判据放它过去。
    坏法注入：删掉 `hide()` 那行 → 40 行档量到 404 < 463 − 8 = 455，红。
    """
    readings = []
    for count in (0, 2, 40):
        if count:
            _seed_docs(ctx, count)
        page = _page_at(window, qapp, "library", DEFAULT_WINDOW_WIDTH, DEFAULT_WINDOW_HEIGHT)
        table = page.doc_table
        assert table.rowCount() == count, f"用例前提：灌了 {count} 行就该读到 {count} 行"
        readings.append((count, table.viewport().width(),
                         table.verticalScrollBar().isVisible(),
                         table.verticalScrollBar().width()))
    baseline = readings[0][1]
    for count, width, vsb_visible, vsb_width in readings[1:]:
        allowance = vsb_width if vsb_width and vsb_visible else 0
        assert width >= baseline - allowance, (
            f"{count} 行时视口只有 {width}px，空库是 {baseline}px，滚动条只占 {allowance}px —— "
            f"多出来的 {baseline - allowance - width}px 是 Qt 自己长出来的行号列（ISSUES I54）")
    assert readings[-1][2], "用例前提：40 行那一档要真的把纵向滚动条顶出来，否则这条只测了个等式"


def test_状态栏那行口径在两档都不裁字不顶宽(window, ctx, qapp) -> None:
    """**ISSUES I60** 的界面半边：§S1 要这一栏把检索口径与各通道行数都上屏，那句话在中栏里
    必须同时做到 ①两向都对 ②看得见尾 ③不把窗口顶过 D-039 地板。

    数字来自本轮探针 `.probe_work/i60_status_line_probe.py`（2026-10-17 实测）：
    把 `SearchResult.lines()` 整句塞进标签，不折行要 1056px ⇒ 页面最小宽 1121px、
    窗口最小宽 1178px，`test_ui_layout` 那两条 minimumSizeHint 守卫当场红；
    换成 `status_line()`（2 字口径不折行 816px、trigram 口径 708px）并折行之后
    ⇒ 地板档标签拿到 758px、宽档拿到 465px（2026-10-17 复测：4 字口径在 758px 下一行就放得下，
    2 字口径要两行），页面最小宽 321px / 546px。
    坏法注入实测（2026-10-17）：删掉 `library_page` 里那句 `setWordWrap(True)` ⇒ 先红在
    `wordWrap()` 那条；把这条也临时让过去，下一条「不顶宽」跟着红，读数是
    **1280px 档搜完「请示」之后页面最小宽 1031px > 823px** —— 两条都不是装饰。

    【2026-11-03 追记（**轮五十八 ④甲**，导航 200→180）】同一处现量：地板档标签 778px、
    默认档 1,034px，页面最小宽 321px 不变（`.probe_work/r58_readings.log`）。比上面那两个读数宽
    截，来源是 轮四十二 ⑭ 之后右栏不再占 splitter 槽 + 本轮侧栏收窄，判档与断言口径一条没变 ——
    「不顶宽」那条比的是 `PAGE_WIDTH_AT_FLOOR`（跟着 `NAV_WIDTH` 算），不是写死的 823。
    """
    _seed_docs(ctx, 3)
    for width in (MIN_WINDOW_WIDTH, DEFAULT_WINDOW_WIDTH):
        page = _page_at(window, qapp, "library", width, MIN_WINDOW_HEIGHT)
        for query, want_slow in (("请示", True), ("保留期限", False)):
            _run_search(page, qapp, query)
            _settle(qapp)
            label = page.status_label
            assert ("慢速" in label.text()) is want_slow, (
                f"{width}px 档「{query}」的口径提示方向错了：{label.text()}")
            assert label.wordWrap(), (
                "不折行的 QLabel 其 `minimumSizeHint()` 等于整句宽，会把窗口顶过 D-039 地板")
            need = label.heightForWidth(label.width())
            assert label.height() >= need, (
                f"{width}px 档那句话被裁了：给高 {label.height()}px，要 {need}px —— {label.text()}")
            assert page.minimumSizeHint().width() <= PAGE_WIDTH_AT_FLOOR, (
                f"{width}px 档搜完「{query}」之后页面最小宽 {page.minimumSizeHint().width()}px，"
                f"超过地板档可用的 {PAGE_WIDTH_AT_FLOOR}px —— 状态栏把中栏顶宽了")


# ---------------------------------------------------------------------------
# **D-051**：浅扫自报的界面半边
# ---------------------------------------------------------------------------


def _seed_bodies(ctx: AppContext, count: int = 3) -> None:
    """给 `_seed_docs` 那几份各补一页正文 —— 浅扫预算管的是 `text_pages` 里的行，
    没有正文行就没有窗口，标签上那句「未扫完」也无从出现（`_seed_docs` 只建主记录）。"""
    _seed_docs(ctx, count)
    for doc in ctx.documents.list_sorted(DocFilter(), sort="name", limit=count):
        ctx.texts.replace_pages(int(doc.id), [TextPage(
            doc_id=int(doc.id), page_no=1, body="归档范围与保留期限的请示正文", char_count=13)])


def test_浅扫自报要出现在状态栏标签上(window, ctx, qapp, monkeypatch) -> None:
    """后端认了"没扫完"，屏幕上就得看得见这句话。**ISSUES I60** 那轮的教训正是"后端三样都算好了、
    只有界面没接"，所以这条不复用 formatter 的断言，它读的是 `status_label.text()`。

    两向都钉：预算 1 行（库里有 3 行）⇒ 必须说「未扫完」；预算 99 行（盖得住全库）⇒ 必须不说。
    坏法注入实测（2026-10-17）：把 `library_page.py` 那句 `setText(result.status_line())`
    换回 I60 之前那句 `f"关键词搜索命中 {len(docs)} 份文档…"` ⇒ 第一条红在「未扫完」。
    """
    _seed_bodies(ctx, 3)
    page = _page_at(window, qapp, "library", DEFAULT_WINDOW_WIDTH, MIN_WINDOW_HEIGHT)
    page.search_input.setText("请示")

    monkeypatch.setattr("pdfarchiver.search.service.LIKE_SCAN_ROWS", 1)
    _run_search(page, qapp)
    _settle(qapp)
    assert "未扫完" in page.status_label.text(), page.status_label.text()

    monkeypatch.setattr("pdfarchiver.search.service.LIKE_SCAN_ROWS", 99)
    _run_search(page, qapp)
    _settle(qapp)
    assert "未扫完" not in page.status_label.text(), page.status_label.text()

