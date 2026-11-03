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

from PySide6 import QtCore, QtWidgets, QtTest

from pdfarchiver.db.models import Document, TextPage
from pdfarchiver.fs.identity import identity_key
from pdfarchiver.services.bootstrap import AppContext
from pdfarchiver.ui import library_hits
from pdfarchiver.ui.library_rows import DOC_ID_COLUMN
from pdfarchiver.ui.main_window import (
    DEFAULT_WINDOW_HEIGHT,
    DEFAULT_WINDOW_WIDTH,
    MIN_WINDOW_HEIGHT,
    MIN_WINDOW_WIDTH,
)
from pdfarchiver.ui.pages.reader_page import ReaderPage
from tests.conftest import (
    WINDOW_WIDTH_RIGHT_DOCKED,
    page_at as _page_at, run_search as _run_search, settle as _settle,
)


# ---------------------------------------------------------------------------
# **ISSUES I53** ②甲/③甲（2026-10-17 定案，记在 **D-052**）：右栏是真命中面板
# ---------------------------------------------------------------------------
# 这一节管的是"控件在场、链路也得在场"：面板里每行的文字、每行挂的 doc_id/页码、
# 键盘入口、跳到 S2 的那条链、以及越界页码的读法。判据数字来自本轮探针
# `.probe_work/i53_geometry_probe.py`（log 同目录）。
# **轮五十九 ①甲** 给这一节加了一句前置判据：只有带页码与片段的命中才许逐行出现在这一栏
# （`Hit.carries_evidence`），其余通道收成后端的一行小结 —— 于是"没有页码的通道不许编页码"
# 那半条改成了"没有页码的通道不逐行在场"，`_PAGE_IN_TEXT` 那把尺子跟着删（`test_hit_explain.py`
# 里还有一份，它量的是后端 `rows()`/`suffix()` 的措辞，那里仍在用）。

_DOC_ROLE = library_hits._HIT_DOC_ROLE
_PAGE_ROLE = library_hits._HIT_PAGE_ROLE


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


def test_右栏只列带页码与片段的命中_其余通道收成一行小结(window, ctx, qapp, make_pdf) -> None:
    """**轮五十九 ①甲**：这一栏是**证据栏**，不是第二个结果列表 —— 一句判据钉住它。

    判据「**表格里看不到的东西才许进这一栏**」在后端只有一个出口 `Hit.carries_evidence`
    （页码 + 正文片段 + 相关度是中栏五列没有的三样；文件名 / 路径那两路的 `snippet` 就是
    被匹配的那一列自己，列进来等于把表格里那一格再抄一遍 —— 用户 2026-11-03 红框 #2 的
    "右侧和左侧一致"正是这里）。界面不复述这条判据，只按它过滤。

    两向都钉：① 正文命中必须在场，且带「第 2 页」+ 片段原文 + 出处（§S1 甲点名的三样，
    一条不许界面自己编）；② 只按文件名 / 路径命中的那几路**不许逐行出现**，整路收成一行人话
    小结，数字取后端 `counts_by_field`（与状态栏同源，界面一个新数都不算）。
    文字取自后端 `SearchResult.rows()`，界面不重拼（**ISSUES I60** 那条"格式化只有一个
    owner"在这里同样成立）。空组不占一行 —— 这批文档没写元数据，所以「元数据」不在小结里。
    坏法注入实测（2026-11-03，`.probe_work/r59_inject*.py`，日志同目录；五条红在五条例外上）：
    ① 把 `_show_hits` 的过滤摘掉（`evidence` 换成 `list(zip(result.hits, lines))`）⇒ 红在
       「没有页码的通道不许逐行在场」，读数 `3 行 vs 带证据的 1 行` 并把多出的文件名 / 路径
       两行逐字列出（那正是用户红框 #2 指的"右侧和左侧一致"）；
    ② 删掉 `self._add_info_row(summary)` ⇒ 红在「组头 + 一行小结」，读数只剩 `['正文']`；
    ③ 把后端 `carries_evidence` 恒置 `True` ⇒ 红在①那一条；恒置 `False` ⇒ 红在「正文命中该
       恰好一条，读到 0 条」，读数是一行小结 `文件名 1 行、路径 1 行、正文 1 行 —— 就在上面表格里`
       （正文那一路也被收走，正是这条判据反向时的真实形状）；
    ④ 把说明行的 flags 加上 `ItemIsSelectable` ⇒ 红在 `_headers` 那条，读数变成 `[]`
       （组头与小结都"可选中"了，说明这一栏再没有"不是命中"的行）；
    ⑤ 把后端小结里那句「—— 就在上面表格里」删掉 ⇒ 红在最后那条指路判据。
    """
    _seed_hit_corpus(ctx, make_pdf)
    page = _page_at(window, qapp, "library", DEFAULT_WINDOW_WIDTH, DEFAULT_WINDOW_HEIGHT)
    page.search_input.setText("保留期限")   # 4 字 ⇒ trigram 正文通道，命中在第 2 页
    _run_search(page, qapp)
    _settle(qapp)

    rows = _rows(page)
    body = [row for row in rows if row[2] is not None]
    assert len(body) == 1, f"正文命中该恰好一条，读到 {len(body)} 条：{rows}"
    text, doc_id, page_no = body[0]
    assert page_no == 2, f"查询词只在第 2 页，面板写的是第 {page_no} 页"
    assert "第 2 页" in text and "正文第三段" in text, f"这一行既要有页码也要有片段原文：{text}"
    assert "原生正文" in text, f"正文命中必须带出处（原生 vs OCR 是两个可信度）：{text}"

    # ②甲 的另一半：带 doc_id 的行必须**全都**带页码 —— 非正文通道不再逐行在场。
    listed = [row for row in rows if row[1] is not None]
    assert len(listed) == len(body), \
        f"没有页码的通道又逐行抄进右栏了（{len(listed)} 行 vs 带证据的 {len(body)} 行）：{listed}"

    # 那几路归成后端的一行小结（措辞与数字都不许界面自己拼）。
    result = page.ctx.search.search_in(page._query, "保留期限", limit=100)
    summary = result.collapsed_counts_line()
    assert summary, "用例前提：这批数据里得有不带证据的通道，否则下面验的是空串"
    assert _headers(page) == ["正文", summary], \
        f"右栏该是「组头 + 一行小结」，读到 {_headers(page)}（小结应为「{summary}」）"
    assert "文件名" in summary and "路径" in summary and "就在上面表格里" in summary, \
        f"小结没说清是哪几路、也没指回表格：{summary}"


def test_右栏常驻时空着也有一句引导_有命中之后要让位(window, ctx, qapp, make_pdf) -> None:
    """**②甲 的 ⑱ 后果**（2026-11-03 全量回归当场红出来的那一条）。

    这一栏原先两档都是浮层、默认关着 —— 按 `test_empty_state.py` 的定义「隐藏的列表不在场」，
    空态规则管不到它（那份文件的 docstring 当时写的正是「与 **D-064** ⑭ 同一形状」）。
    ②甲 把它改成宽档贴边常驻之后，它**开局就在屏幕上且是空的**，⑱（**D-066**）当场生效：
    红字逐字 `这些列表面板空着却没有一句引导：文档库（library）的 hit_list`。
    修的是产品（`make_hint` + `sync_hint`，全站唯一出口），不是把那条守卫改成放过这一栏。

    三向都量，因为"恒亮"和"恒灭"都能骗过单向断言：
    ① 没搜过 ⇒ 引导在场（这一栏不是空框）；
    ② 搜出正文命中 ⇒ 引导让位（灯不能恒亮）；
    ③ 点「清除」回到浏览态 ⇒ 引导**回来**（跟着这一栏的条数走，不是一次性消掉）。
    ② 走的是真按钮那条路（`clear_btn.click()`），不是直接调 `_clear_hits()`。

    坏法注入实测（2026-11-03，`.probe_work/r59_inject6.py`，日志 `.tmp_r59_inj6.txt` 已随本轮清零）：
    ① 摘掉 `_show_hits` 末尾那句 `sync_hint` ⇒ 红在②（`这一栏有内容了，「还没有命中」那句还占着屏`，
       读数把三行逐字列出：组头 + 正文命中 + 通道小结，引导与它们同时在场）；
    ② 把 `make_hint` 那一块删掉 ⇒ 红在本条①，但红形是 `AttributeError: 'LibraryPage' object has no
       attribute 'hit_hint'`（那一栏连那句引导都不存在，走不到断言）；同一场全站守卫一起红，逐字
       `这些列表面板空着却没有一句引导：文档库（library）的 hit_list` —— 这正是本轮修之前的那条红；
    ③ 把 `sync_hint` 写成恒 `setVisible(False)` ⇒ 本条只红在①（测试在第一条断言就停，恒灭看不见
       后面），另两处在同一份日志里红：全站那条点名守卫（这次四栏一起报）与
       `test_引导跟着条数走_有内容之后要让位` 的 `隔壁那句空着的引导不该被一起灭掉`。

    追注（2026-11-04 · **轮六十 乙**）：入场档从"宽档"收窄成**右栏真的贴边常驻那一档**，所以
    本页从 `DEFAULT_WINDOW_WIDTH`（1,280）搬到 `WINDOW_WIDTH_RIGHT_DOCKED`（1,440）。乙 之后
    1,280 那一档这一栏是**让位、且默认关着的浮层** —— 按 `test_empty_state.py`「隐藏的列表不在场」，
    ⑱ 在那一档根本不该生效，本条的三条断言在 1,280 会红在第一条前提。不变的是这条守卫管的东西：
    **只要这一栏是常驻的，空着就必须有那句引导**。
    """
    doc_id = _seed_hit_corpus(ctx, make_pdf)
    page = _page_at(window, qapp, "library", WINDOW_WIDTH_RIGHT_DOCKED, DEFAULT_WINDOW_HEIGHT)
    assert page.right_panel.isVisible(), \
        f"用例前提：常驻档（{WINDOW_WIDTH_RIGHT_DOCKED}）这一栏该是贴边常驻且在场"
    assert page.hit_list.count() == 0, f"用例前提：还没搜过，这一栏该是空的：{_rows(page)}"
    assert page.hit_hint.isVisible(), "常驻的一栏空着却没有 ⑱ 那句引导"

    page.search_input.setText("保留期限")
    _run_search(page, qapp)
    _settle(qapp)
    assert page.hit_list.count() > 0, "用例前提：正文命中已经上屏"
    assert not page.hit_hint.isVisible(), \
        f"这一栏有内容了，「还没有命中」那句还占着屏：{_rows(page)}"

    page.clear_btn.click()
    _settle(qapp)
    assert page.hit_list.count() == 0, f"清除没把命中行退掉（{doc_id}）：{_rows(page)}"
    assert page.hit_hint.isVisible(), "回到浏览态之后那句引导该跟着回来（跟着条数走，不是一次性）"


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
    _run_search(page, qapp)
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
    3. 右栏**不**因为 Ctrl+F 变化 —— 判据从轮五十九 ②甲 起换了量法。原先那句"右栏保持不可见"
       在宽档不成立也不该成立：宽档右栏现在是**贴边常驻列**（`docked=True`、一直在场），
       "没打开"不再是"不可见"。所以这里钉的是**这一键没有改变右栏的形状与在场**
       （`isVisible` 与「在不在 splitter 里」这一对），窄档那一档另加一条前提：浮层默认关着。

    坏法注入实测（2026-10-17 三条 + 2026-11-03 一条）：
    ① 键位改成 Ctrl+G ⇒ 红在判据 2；
    ② 把 `QShortcut` 的 parent 从窗口改成 `self.stack` 并降成 `WidgetWithChildrenShortcut`
       ⇒ 红在判据 1（焦点在导航列表上按键没反应）；
    ③ 在 Ctrl+F 的槽里加一句 `right_panel.open_overlay()` ⇒ 红在判据 3（窄档那一档
       `(False, False)` 变 `(True, False)`，浮层凭空盖在表格上）。

    追注（2026-11-04 · **轮六十 乙**）：宽档那一档从 1,280 搬到 1,440 —— 乙 之后 1,280 右栏是
    **让位的浮层**，那句"常驻列一直场"的分支在 1,280 不再在场，两档会量到同一种形状（判据 3 只剩
    一条分支被覆盖）。搬到常驻档之后 `(True, True)` 那一支重新被采样。副作用要说清：注入 ③ 现在
    只在窄档那一档红 —— 常驻档上 `open_overlay()` 对已贴边的面板是空转（早退），改不了形状与在场。
    """
    for width in (MIN_WINDOW_WIDTH, WINDOW_WIDTH_RIGHT_DOCKED):
        page = _page_at(window, qapp, "library", width, MIN_WINDOW_HEIGHT)
        assert str(window.search_shortcut.key().toString()) == "Ctrl+F"
        panel = page.right_panel
        before = (panel.isVisible(), panel.parent() is page.splitter)
        if panel._is_overlay():
            assert not before[0], "用例前提：浮层那一档右栏默认是关的"
        else:
            assert before == (True, True), "用例前提：宽档右栏是贴边常驻列，默认在场"
        window.nav.setFocus()
        _activate(window, qapp)
        assert QtWidgets.QApplication.focusWidget() is not page.search_input, "用例前提：焦点先在别处"
        QtTest.QTest.keyClick(window, QtCore.Qt.Key.Key_F, QtCore.Qt.KeyboardModifier.ControlModifier)
        _settle(qapp)
        assert QtWidgets.QApplication.focusWidget() is page.search_input, "Ctrl+F 没把焦点交给搜索框"
        after = (panel.isVisible(), panel.parent() is page.splitter)
        assert after == before, \
            f"Ctrl+F 只该交焦点，右栏却从 {before} 变成了 {after}（窄档浮层默认关、宽档常驻在场）"


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

    **轮五十九 ①甲** 新加的那条（右栏只剩带证据的那一行）本轮也真注入过（`.probe_work/
    r59_inject*.py`，日志同目录）：⑤ 把 `_show_hits` 的过滤摘掉 ⇒ 红在「不该再有『没有页码的
    行』」，读数逐字列出多出的文件名 / 路径两行；⑥ 把后端 `carries_evidence` 恒置 `False`
    ⇒ 红在「用例前提：右栏得有一条写着第 2 页的正文命中」。原先这里写的是裸 `next(...)`，
    ⑥ 那种坏法抛的是 `StopIteration`（不点名、看着像用例自己坏了），已改成会报读数的断言。
    """
    doc_id = _seed_hit_corpus(ctx, make_pdf)
    page = _page_at(window, qapp, "library", DEFAULT_WINDOW_WIDTH, DEFAULT_WINDOW_HEIGHT)
    page.search_input.setText("保留期限")
    _run_search(page, qapp)
    _settle(qapp)

    body_rows = [i for i in range(page.hit_list.count())
                 if page.hit_list.item(i).data(_PAGE_ROLE) == 2]
    assert body_rows, f"用例前提：右栏得有一条写着第 2 页的正文命中：{_rows(page)}"
    page.hit_list.setCurrentRow(body_rows[0])
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

    # ①甲 之后这一栏里**没有"没有页码的那一行"了**：只按文件名 / 路径命中的那路收成后端的一行
    # 小结，不再逐行在场。原先这一段验的「打开文档 → S2」措辞因此改由**中栏选中**驱动，那条
    # 守卫在 `test_round42_ux.py::test_没搜过时跳转按钮退到打开选中的文档`。这里钉这一条链上
    # ①甲 的后果：面板里可选中的行只剩带证据的那一条，它带的页码就是跳转要去的那一页。
    window._select_by_page_id("library")
    _settle(qapp)
    selectable = [i for i in range(page.hit_list.count())
                  if page.hit_list.item(i).data(_DOC_ROLE) is not None]
    assert len(selectable) == 1, \
        f'右栏不该再有「没有页码的行」，读到 {len(selectable)} 条带 doc_id 的行：{_rows(page)}'
    assert page.hit_list.item(selectable[0]).data(_PAGE_ROLE) == 2

    # 双击中栏的行（真鼠标事件，不是直接发信号）
    window._select_by_page_id("library")
    _settle(qapp)
    page.search_input.setText("保留期限")
    _run_search(page, qapp)
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


# ---------------------------------------------------------------------------
# 轮五十八 ②：命中表重排之后，右栏那份详情不许停在上一批的第 N 行
# ---------------------------------------------------------------------------


def test_命中表重排之后详情写的是这一行的那一份(window, ctx, qapp, make_pdf) -> None:
    """用户红框点名的第二处：表里第一行已经换了，「文档详情」还写着上一批那一行。

    根因不在详情那段代码，在 Qt 的选中保持：`QTableWidget` 按**行号**保选中，
    `setRowCount` + `setItem` 不改变 `currentRow` ⇒ `itemSelectionChanged` 一次都不发，
    只挂在那根信号上的详情就停在上一批的第 N 行（真机读数：表首行已是 `文档07.pdf`，
    详情仍写 `文件名：文档29.pdf`）。修法因此是**再走一次那唯一的渲染入口**
    （`_populate_table` 末尾调 `_on_doc_selected()`），而不是给详情另开第二个取数口径。

    判据只有一条用户看得见的：详情首行的文件名 == 表格首行那一格。三条前提读数缺一条这条就
    在验别的东西：重排前后 `currentRow` 都得是 0（不然"详情没跟着换"可能只是选中被清了，
    修没修一个样）、首行那份文档必须真的换了（不然量的是没变过的表）、详情起初确实写着首行。
    坏法注入实测（2026-11-03）：删掉 `_populate_table` 末尾那句 `self._on_doc_selected()`
    ⇒ 红在「详情首行 == 表首行」那条，读数逐字写着两边各是哪一份。
    """
    _seed_hit_corpus(ctx, make_pdf)
    page = _page_at(window, qapp, "library", DEFAULT_WINDOW_WIDTH, DEFAULT_WINDOW_HEIGHT)
    assert page.doc_table.rowCount() == 2, "用例前提：浏览态两份都在表里"
    page.doc_table.selectRow(0)
    _settle(qapp)
    first_before = page.doc_table.item(0, DOC_ID_COLUMN).text()
    assert page.detail_view.toPlainText().startswith(f"文件名：{first_before}"), \
        f"用例前提：详情写的就是当前行那一份（当前是「{first_before}」）"

    _run_search(page, qapp, "复函稿")      # 只有另一份的文件名命中 ⇒ 首行换人
    _settle(qapp)
    assert page.doc_table.rowCount() == 1 and page.doc_table.currentRow() == 0, (
        f"用例前提没了：重排后 {page.doc_table.rowCount()} 行 / 当前行 "
        f"{page.doc_table.currentRow()} —— 选中被清了，这条就量不到「详情过没过期」")
    name_now = page.doc_table.item(0, DOC_ID_COLUMN).text()
    assert name_now != first_before, "用例前提：这批命中得真的换了一份，否则验的是没变过的表"
    detail = page.detail_view.toPlainText()
    assert detail.startswith(f"文件名：{name_now}"), (
        f"详情停在上一批那一行了：表首行是「{name_now}」，详情首行是「{detail.splitlines()[0]}」")
