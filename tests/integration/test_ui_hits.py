"""**ISSUES I53** ②甲/③甲（2026-10-17 定案，记在 **D-052**）：S1 的右栏是真命中面板。

这一组量的是**数据到文字的链路**，不是控件在两个宽度档下的形状（后者留在
`test_ui_tier.py`）。2026-10-30（轮四十五）按 **D-054** 那句"超线按主题拆"从那份文件搬出来：
它涨到 825 行顶到 800 红线，而这一节是最后长上去的、跟切档规则本来就不是一条链。
`window` 夹具与 `_page_at` 一起搬进 `tests/conftest.py` —— 同一句守卫的话写着"**抄一份不算拆**"。

五条判据覆盖：面板每行的文字与它挂着的 doc_id/页码（①②）、浏览态不许留过期读数、
Ctrl+F 的键盘入口（③甲）、跳到 S2 并落在那一页的整条链、越界页码要拒绝并说明原因。
判据数字来自 `.probe_work/i53_geometry_probe.py`（log 同目录），每条的坏法注入记录写在
各自的 docstring 里（`.probe_work/i53_guard_injection.py`）。

断言全部在 offscreen 跑真控件（`click()` / `keyClick()` / `mouseDClick()`）而不是直接调槽：
Qt 虚函数与槽里抛出的 Python 异常会被吞掉，"点下去什么都不做"本身不会让测试变红。
"""
from __future__ import annotations

import re

from PySide6 import QtCore, QtWidgets, QtTest

from pdfarchiver.db.models import Document, TextPage
from pdfarchiver.fs.identity import identity_key
from pdfarchiver.services.bootstrap import AppContext
from pdfarchiver.ui import library_hits
from pdfarchiver.ui.main_window import (
    DEFAULT_WINDOW_HEIGHT,
    DEFAULT_WINDOW_WIDTH,
    MIN_WINDOW_HEIGHT,
    MIN_WINDOW_WIDTH,
)
from pdfarchiver.ui.pages.reader_page import ReaderPage
from tests.conftest import page_at as _page_at, settle as _settle


# ---------------------------------------------------------------------------
# **ISSUES I53** ②甲/③甲（2026-10-17 定案，记在 **D-052**）：右栏是真命中面板
# ---------------------------------------------------------------------------
# 这一节管的是"控件在场、链路也得在场"：面板里每行的文字、每行挂的 doc_id/页码、
# 键盘入口、跳到 S2 的那条链、以及越界页码的读法。判据数字来自本轮探针
# `.probe_work/i53_geometry_probe.py`（log 同目录）。

_DOC_ROLE = library_hits._HIT_DOC_ROLE
_PAGE_ROLE = library_hits._HIT_PAGE_ROLE
_PAGE_IN_TEXT = re.compile(r"第 \d+ 页")


def _seed_hit_corpus(ctx: AppContext, make_pdf) -> int:
    """一份三页**真** PDF（查询词只在第 2 页）+ 一份只有文件名/路径能命中的文档。

    为什么非得是真 PDF：这一节要量到跳转的终点 `ReaderPage.open_document`，它对路径做
    `pymupdf.open()` —— 假路径会走进 except 弹**模态框**，测试是卡住而不是变红（那比红更糟）。
    """
    path = make_pdf("归档范围与保留期限的请示.pdf",
                    page_lines=[["本件为内部流转稿"],
                                ["归档范围与保留期限的请示正文第三段"],
                                ["附件清单另列"]]).replace("\\", "/")
    ctx.documents.upsert(Document(
        path=path, path_key=identity_key(path), name="归档范围与保留期限的请示.pdf",
        size_bytes=20480, mtime_ns=1_760_000_000_000_000_000, page_count=3,
        text_status="done", fts_status="done"))
    doc_id = int(ctx.documents.list(limit=1)[0].id)
    ctx.texts.replace_pages(doc_id, [
        TextPage(doc_id=doc_id, page_no=1, body="本件为内部流转稿", char_count=9),
        TextPage(doc_id=doc_id, page_no=2, body="归档范围与保留期限的请示正文第三段", char_count=17),
        TextPage(doc_id=doc_id, page_no=3, body="附件清单另列", char_count=6)])
    other = "D:/用户资料/请示（复函稿）.pdf"
    ctx.documents.upsert(Document(
        path=other, path_key=identity_key(other), name="请示（复函稿）.pdf",
        size_bytes=1024, mtime_ns=1_760_000_000_000_000_000,
        text_status="done", fts_status="done"))
    return doc_id


def _rows(page) -> list[tuple[str, object, object]]:
    return [(page.hit_list.item(i).text(),
             page.hit_list.item(i).data(_DOC_ROLE),
             page.hit_list.item(i).data(_PAGE_ROLE))
            for i in range(page.hit_list.count())]


def _headers(page) -> list[str]:
    return [item.text() for item in (page.hit_list.item(i) for i in range(page.hit_list.count()))
            if not (item.flags() & QtCore.Qt.ItemFlag.ItemIsSelectable)]


def _activate(window, qapp) -> None:
    """把窗口标成"活动"并跑几轮事件循环。

    offscreen 下 `QShortcut`（WindowShortcut）只在活动窗口里派发 —— 本轮实测：不激活时
    按键完全没反应（`.probe_work/i53_geometry_probe.log`）。真用户在活动窗口里按键，
    所以这一步是**还原前提**，不是给断言铺路。
    """
    window.activateWindow()
    for _ in range(4):
        qapp.processEvents()


def test_命中面板按通道分组带页码与片段且无页码的通道不编页码(window, ctx, qapp, make_pdf) -> None:
    """§S1 甲那一栏点名的三样：**分组、页码、片段**，一条不许界面自己编。

    两向都钉：正文行必须写「第 2 页」并带出片段原文；文件名/路径行**必须没有**页码
    （`Hit.page_no is None`，编一个「第 1 页」就是让用户翻到错的那一页去找东西）。
    文字取自后端 `SearchResult.rows()`，界面不重拼（**ISSUES I60** 那条"格式化只有一个
    owner"在这里同样成立）。空组不占一行 —— 这批文档没写元数据，所以「元数据」整组不在场。
    坏法注入实测（2026-10-17，`.probe_work/i53_guard_injection.py`，四条各自红在不同的断言上）：
    ① 把 `_show_hits` 的行文案换成 `hit.doc.name` ⇒ 红在「页码 + 片段」那条；
    ② 把后端 `rows()` 的 `where` 换成 `f"第 {hit.page_no or 1} 页" if True` ⇒ 红在「无页码通道」那条；
    ③ 把 `rows()` 的 `source` 恒置空 ⇒ 只红在「出处」那条（页码与片段仍绿，说明三样各钉得住）；
    ④ 把组头的 flags 加上 `ItemIsSelectable` ⇒ 红在分组标题那条（读数变成 `[]`）。
    """
    _seed_hit_corpus(ctx, make_pdf)
    page = _page_at(window, qapp, "library", DEFAULT_WINDOW_WIDTH, DEFAULT_WINDOW_HEIGHT)
    page.search_input.setText("保留期限")   # 4 字 ⇒ trigram 正文通道，命中在第 2 页
    page._do_search()
    _settle(qapp)

    assert _headers(page) == ["文件名", "路径", "正文"], \
        f"分组标题不对（顺序按 `criteria.in_fields`，空组不占行）：{_headers(page)}"
    rows = _rows(page)
    body = [row for row in rows if row[2] is not None]
    assert len(body) == 1, f"正文命中该恰好一条，读到 {len(body)} 条：{rows}"
    text, doc_id, page_no = body[0]
    assert page_no == 2, f"查询词只在第 2 页，面板写的是第 {page_no} 页"
    assert "第 2 页" in text and "正文第三段" in text, f"这一行既要有页码也要有片段原文：{text}"
    assert "原生正文" in text, f"正文命中必须带出处（原生 vs OCR 是两个可信度）：{text}"

    no_page = [row for row in rows if row[1] is not None and row[2] is None]
    assert no_page, "用例前提：文件名/路径通道的命中得在场，否则这条只测了正文那一半"
    for text, _, _ in no_page:
        assert not _PAGE_IN_TEXT.search(text), f"没有页码的通道被编了页码：{text}"


def test_浏览态不许留着上一次查询的命中(window, ctx, qapp, make_pdf) -> None:
    """右栏的标题是「命中面板（**当前查询**）」—— 没有当前查询时它就该是空的。

    走的是用户那颗「清除」按钮而不是直接调 `_clear_hits()`：入口没接线时这一屏在
    浏览态会一直挂着上次检索的命中，那是**过期读数**（与 **ISSUES I55** 同一类）。
    坏法注入实测（2026-10-17，`.probe_work/i53_guard_injection.py`）：删掉
    `_load_all_documents()` 末尾那句 `_clear_hits()` ⇒ 红在「还留着 6 行过期读数」那条
    （查完有命中那条前提仍绿，所以红的是清空链路而不是用例数据）。
    """
    _seed_hit_corpus(ctx, make_pdf)
    page = _page_at(window, qapp, "library", DEFAULT_WINDOW_WIDTH, DEFAULT_WINDOW_HEIGHT)
    page.search_input.setText("保留期限")
    page._do_search()
    _settle(qapp)
    assert page.hit_list.count() > 0, "用例前提：查完要有命中在场"
    page.hit_list.setCurrentRow(0)
    _settle(qapp)

    page.clear_btn.click()
    _settle(qapp)
    assert page.hit_list.count() == 0, f"清除查询后右栏还留着 {page.hit_list.count()} 行过期读数"
    assert not page.jump_btn.isEnabled(), "面板空了跳转按钮还亮着 = 按下去什么都不知道"


def test_Ctrl_F_把光标交给搜索框而右栏等搜索结果(window, qapp) -> None:
    """③甲 定的键位（轮四十二 ⑭ 改约：Ctrl+F 只交焦点，右栏等搜索出结果再开）。

    1. **焦点在导航列表上按 Ctrl+F** —— 焦点最终落在搜索框。这一条同时验两件事：短路挂在
       **窗口**（`WindowShortcut`，所以焦点不在 S1 的控件里也有效）与槽真的会 `setFocus()`。
    2. 键面就是 **Ctrl+F**（改成 Ctrl+G 也算"有快捷键"，但那是线框之外的第二个口径）。
    3. 右栏**不**因为 Ctrl+F 打开 —— 那一刻它还是空的，空白浮层盖在表格上是又一种堆积。

    坏法注入实测（2026-10-17，`.probe_work/i53_guard_injection.py`）：
    ① 键位改成 Ctrl+G ⇒ 红在判据 2；
    ③ 把 `QShortcut` 的 parent 从窗口改成 `self.stack` 并降成 `WidgetWithChildrenShortcut`
       ⇒ 红在判据 1（焦点在导航列表上按键没反应）。
    """
    for width in (MIN_WINDOW_WIDTH, DEFAULT_WINDOW_WIDTH):
        page = _page_at(window, qapp, "library", width, MIN_WINDOW_HEIGHT)
        assert str(window.search_shortcut.key().toString()) == "Ctrl+F"
        assert not page.right_panel.isVisible(), "用例前提：右栏默认是关的"
        window.nav.setFocus()
        _activate(window, qapp)
        assert QtWidgets.QApplication.focusWidget() is not page.search_input, "用例前提：焦点先在别处"
        QtTest.QTest.keyClick(window, QtCore.Qt.Key.Key_F, QtCore.Qt.KeyboardModifier.ControlModifier)
        _settle(qapp)
        assert QtWidgets.QApplication.focusWidget() is page.search_input, "Ctrl+F 没把焦点交给搜索框"
        assert not page.right_panel.isVisible(), "Ctrl+F 只交焦点；右栏等搜索出结果再开（轮四十二 ⑭）"


def test_跳转按钮与双击真的走到_S2_并落在那一页(window, ctx, qapp, make_pdf) -> None:
    """②甲 的落点：面板不是用来看的，是"看到 → 翻到那一页"。

    走真控件（`setCurrentRow` + `click()`），不走直接调槽：本轮实测过 ——
    `Signal(object)` 挂两个参数 emit 时抛 TypeError，而异常发生在 Qt 槽里被吞掉，
    按钮点下去**什么都不做**（`.probe_work/_sig_probe.py`）。只有真点一次才量得到。
    顺带把 §S1「必须承接的六件事」第 6 条（双击行打开文件）接上：此前
    `ReaderPage.open_document` 在全项目**零调用**，阅读器是一屏进不去的界面。

    坏法注入实测（2026-10-17，`.probe_work/i53_guard_injection.py`，四条红在四个不同环节）：
    ① emit 改回两个参数 ⇒ 红在取阅读器页那一步（当场 `KeyError: 'reader'`，
       这一页压根没被创建 —— 死按钮的证据是"那屏根本不存在"，比红一行文案更硬）；
    ② emit 的页码改成恒 `None` ⇒ 红在「阅读器停在第 1 页」；
    ③ 撤掉 `itemDoubleClicked` 那根线 ⇒ 只红在最后那条双击判据；
    ④ `_on_hit_current` 里把 `_select_doc_row()` 换成 `pass` ⇒ 红在中栏联动那条。
    """
    doc_id = _seed_hit_corpus(ctx, make_pdf)
    page = _page_at(window, qapp, "library", DEFAULT_WINDOW_WIDTH, DEFAULT_WINDOW_HEIGHT)
    page.search_input.setText("保留期限")
    page._do_search()
    _settle(qapp)

    body_row = next(i for i in range(page.hit_list.count())
                    if page.hit_list.item(i).data(_PAGE_ROLE) == 2)
    page.hit_list.setCurrentRow(body_row)
    _settle(qapp)
    assert page.jump_btn.isEnabled() and page.jump_btn.text() == "跳到该页 → S2"
    assert page.doc_table.currentRow() == 0, "选中一条命中没把中栏那行一起选上（§S1 的联动）"

    page.jump_btn.click()
    _settle(qapp)
    reader = window._pages["reader"]
    assert isinstance(window.stack.currentWidget(), ReaderPage), "点了跳转没切到 S2"
    assert reader._current_doc_id == doc_id, f"打开的不是那份文档：{reader._current_doc_id}"
    assert reader._current_page == 1, f"命中在第 2 页，阅读器停在第 {reader._current_page + 1} 页"
    assert reader.page_label.text().startswith("2 / 3"), reader.page_label.text()

    # 没有页码的那条：措辞换成「打开文档」，且不许编一个页码
    window._select_by_page_id("library")
    _settle(qapp)
    name_row = next(i for i in range(page.hit_list.count())
                    if page.hit_list.item(i).data(_DOC_ROLE) is not None
                    and page.hit_list.item(i).data(_PAGE_ROLE) is None)
    page.hit_list.setCurrentRow(name_row)
    _settle(qapp)
    assert page.jump_btn.text() == "打开文档 → S2", page.jump_btn.text()
    page.jump_btn.click()
    _settle(qapp)
    assert isinstance(window.stack.currentWidget(), ReaderPage)

    # 双击中栏的行（真鼠标事件，不是直接发信号）
    window._select_by_page_id("library")
    _settle(qapp)
    page.search_input.setText("保留期限")
    page._do_search()
    _settle(qapp)
    _activate(window, qapp)
    viewport = page.doc_table.viewport()
    center = page.doc_table.visualRect(page.doc_table.model().index(0, 0)).center()
    # 先单击再双击 = 用户真实的手序。只发 DblClick 时 Qt 的
    # `QAbstractItemView::mouseDoubleClickEvent` 因为 `pressedIndex` 无效会直接 return，
    # offscreen 下实测第一发会被吞（本轮探针「真双击矩阵」）。
    QtTest.QTest.mouseClick(viewport, QtCore.Qt.MouseButton.LeftButton,
                           QtCore.Qt.KeyboardModifier.NoModifier, center)
    QtTest.QTest.mouseDClick(viewport, QtCore.Qt.MouseButton.LeftButton,
                            QtCore.Qt.KeyboardModifier.NoModifier, center)
    _settle(qapp)
    assert isinstance(window.stack.currentWidget(), ReaderPage), "双击文档行没打开阅读器（§S1 第 6 条）"


def test_越界页码拒绝并说明原因而不是就近取整(window, ctx, qapp, make_pdf) -> None:
    """§S2 甲的断言点：库里记的页码与文件真实页数可以不一致，静默落到第 1 页最坏。

    两向都钉：在范围内的跳转不许出现「不存在」；越界的那次要**说清共几页、停在哪一页**，
    并且真的停在原来那一页（既不折回第 1 页也不夹到最后一步）。
    坏法注入实测（2026-10-17，`.probe_work/i53_guard_injection.py`）：在 `if page_no is not None:`
    之后插一句 `page_no = min(page_no, len(self._doc))` ⇒ 红在「越界没说明原因」那条，
    而前半条（范围内不许出现「不存在」）**仍然绿** —— 就近取整不会让在范围内的跳转出错，
    它只在用户翻到库里记错了的那一页时才骗人，所以两向都得钉。
    """
    doc_id = _seed_hit_corpus(ctx, make_pdf)
    window._open_in_reader((doc_id, 2))
    _settle(qapp)
    reader = window._pages["reader"]
    assert "不存在" not in reader.status_label.text(), reader.status_label.text()

    window._open_in_reader((doc_id, 99))
    _settle(qapp)
    text = reader.status_label.text()
    assert "第 99 页不存在" in text and "共 3 页" in text, f"越界没说明原因：{text}"
    assert "已停在第 2 页" in text, f"要能说清现在到底停在哪：{text}"
    assert reader._current_page == 1, f"越界被就近取整了：现在在第 {reader._current_page + 1} 页"
