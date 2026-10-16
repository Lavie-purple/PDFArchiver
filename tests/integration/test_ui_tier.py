"""**D-039 / D-040** 的降级几何 —— 1024 档收起侧栏，两屏共用 `ui/tier.py` 那一条规则。

为什么单独成一个文件而不是塞进 `test_app_shell.py`（那个文件已经 780 行）：这一组量的是
**同一个控件在两个宽度档下的形状**，判据全部来自 `ui/tier.py` 的常量，跟外壳/读数/列宽守卫
不是一条链。

所有断言都在 offscreen 量**真实几何**（不是截图）：离屏截图只有形状没有 CJK 字形，
而 Qt 在这里的坑全是"数字看着对、其实没重排"，只有量 `width()/sizes()/rowHeight()` 能判。
`narrow is None` 那条尤其重要 —— Qt 虚函数里抛的 Python 异常会被吞掉，切档悄悄不跑时
界面只是"停在默认布局"，别的断言照样绿（本轮实测抓到一次）。
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest
from PySide6 import QtWidgets

from pdfarchiver.db.models import Document
from pdfarchiver.fs.identity import identity_key
from pdfarchiver.services.bootstrap import AppContext
from pdfarchiver.ui import tier
from pdfarchiver.ui.main_window import (
    DEFAULT_WINDOW_HEIGHT,
    DEFAULT_WINDOW_WIDTH,
    MIN_WINDOW_HEIGHT,
    MIN_WINDOW_WIDTH,
    NAV_WIDTH,
    MainWindow,
)
from pdfarchiver.ui.pages import categories_page, library_page
from pdfarchiver.ui.tier import (
    CENTER_MIN_WIDTH,
    LEFT_COLUMN_WIDTH,
    RIGHT_COLUMN_WIDTH,
    THREE_COLUMN_MIN_WIDTH,
    TREE_STRIP_WIDTH,
    FloatablePanel,
)
from tests.conftest import settle as _settle

# 页面可用宽 = 窗口宽 − 导航 − 1px 边框（实测 1024→823、1280→1079；这条 −1 的口径
# 与 `test_app_shell.AVAILABLE_WIDTH` 同一个来源，两处都不写死像素）。
PAGE_WIDTH_AT_FLOOR = MIN_WINDOW_WIDTH - NAV_WIDTH - 1     # 823
PAGE_WIDTH_AT_DEFAULT = DEFAULT_WINDOW_WIDTH - NAV_WIDTH - 1   # 1079


@pytest.fixture
def window(qapp, ctx):
    w = MainWindow(ctx, cold_start_seconds=0.42)
    w.show()
    yield w
    w.close()
    ctx.shutdown()


def _page_at(window, qapp, page_id: str, width: int, height: int):
    """切到某一屏、重查一遍、压到指定窗口宽，返回页面对象。

    必须**真的切过去**再 resize：`QStackedWidget` 里隐藏的页不重排，没看过的页面量出来
    是一串 0（离屏 Qt 的既有陷阱）。
    还要显式 `reload()`：已经在当前页时 `setCurrentRow` 不发信号，外壳的刷新链一次都不走，
    测试中途灌进库的行就读不到（实测文档表停在 0 行）。
    """
    window._select_by_page_id(page_id)
    _settle(qapp)
    page = window._pages[page_id]
    page.reload()
    window.resize(width, height)
    _settle(qapp)
    assert page.isVisible(), f"用例前提：{page_id} 这一屏得是当前可见页，否则量到的都是 0"
    return page


def _seed_docs(ctx: AppContext, count: int = 3) -> None:
    """灌几行进文档表 —— 空表量不到行高，长文件名才量得到"变行高展开"会不会发生。"""
    for n in range(count):
        name = f"归档范围与保留期限的请示（复函稿）第{n}版附件全部版本.pdf"
        path = f"D:\\用户资料\\2026 年度合同与结算凭证归档\\{name}"
        ctx.documents.upsert(Document(
            path=path, path_key=identity_key(path), name=name,
            size_bytes=1024 * 1024, mtime_ns=1_760_000_000_000_000_000,
            sha256=f"{n:064x}", text_status="done", fts_status="done"))


def test_宽档左栏与右栏按定宽常驻(window, qapp) -> None:
    """`236 + 480 + 360 = 1076` 在设计档 1280 下三栏都常驻，定宽就是这两个数。

    上一轮这里量到的是 [236, 481, 360]，看着对 —— 其实那三个数来自 `__init__` 里手写的
    `setSizes`，切档代码在 Qt 虚函数里抛异常被吞了、从没跑过。所以 `narrow is False`
    （而不是 None）这一条要先钉住：**切档真的跑过**，后面的宽度读数才算数。
    """
    page = _page_at(window, qapp, "library", DEFAULT_WINDOW_WIDTH, DEFAULT_WINDOW_HEIGHT)
    assert page.width() == PAGE_WIDTH_AT_DEFAULT, f"页面可用宽不是 {PAGE_WIDTH_AT_DEFAULT}：{page.width()}"
    assert page.width() >= THREE_COLUMN_MIN_WIDTH, "用例前提：这一档应当放得下三栏"
    for panel in (page.tree_panel, page.detail_panel):
        assert panel.narrow is False, "切档没跑（还是 None）—— 异常被 Qt 的虚函数调用吞掉了"
        assert panel.parent() is page.splitter, "宽档这两栏得还在 splitter 里占槽"
    assert page.tree_panel.width() == LEFT_COLUMN_WIDTH, f"左栏不是 D-040 的 {LEFT_COLUMN_WIDTH}px：{page.tree_panel.width()}"
    assert page.detail_panel.width() == RIGHT_COLUMN_WIDTH, f"右栏不是 D-040 的 {RIGHT_COLUMN_WIDTH}px：{page.detail_panel.width()}"
    assert page.tree_panel.strip is not None and not page.tree_panel.strip.isVisible(), \
        "宽档那条 48px 的条必须隐藏，否则左栏前面多出一条空栏"


def test_窄档只牺牲右栏且左栏收成_48px_的条(window, qapp) -> None:
    """**D-040** 的取舍：地板档放不下三栏，牺牲的是命中/详情栏，**不是分类树**。

    分类树在窄档换成一条 48px 的条，中栏吃掉剩余宽度（实测 823 档：[48, 774]）。
    """
    page = _page_at(window, qapp, "library", MIN_WINDOW_WIDTH, MIN_WINDOW_HEIGHT)
    assert page.width() == PAGE_WIDTH_AT_FLOOR
    assert page.width() < THREE_COLUMN_MIN_WIDTH, "用例前提：这一档放不下三栏"
    assert page.tree_panel.narrow is True and page.detail_panel.narrow is True
    assert page.tree_panel.parent() is page and page.detail_panel.parent() is page, \
        "窄档两块面板都该从 splitter 里摘出来挂到页面上（不参与布局 ⇒ 顶不宽窗口）"
    assert page.splitter.count() == 2, f"窄档 splitter 该只剩「条 + 中栏」两槽：{page.splitter.sizes()}"
    strip = page.tree_panel.strip
    assert strip.isVisible() and strip.width() == TREE_STRIP_WIDTH, \
        f"左栏没收成 {TREE_STRIP_WIDTH}px 的条：{strip.width()}"
    center = page.splitter.widget(1)
    assert center.width() >= page.width() - TREE_STRIP_WIDTH - 2, \
        f"中栏没吃掉剩余宽度：只占 {center.width()}px，可用 {page.width() - TREE_STRIP_WIDTH}px"
    assert center.width() >= CENTER_MIN_WIDTH, f"中栏低于 D-040 的 {CENTER_MIN_WIDTH}px 下限"


def test_浮层默认关可关且不把窗口顶宽(window, qapp) -> None:
    """D-040 代价段那句"开/关状态可断言，不记忆成每次都开"落成三条读数。

    入口走的是条上那颗按钮（不是直接调 API）—— 只测 `open_overlay()` 的话，按钮没接线
    这一屏在窄档就等于没有分类树。
    """
    page = _page_at(window, qapp, "library", MIN_WINDOW_WIDTH, MIN_WINDOW_HEIGHT)
    for panel in (page.tree_panel, page.detail_panel):
        assert not panel.isVisible(), "窄档浮层默认必须是关的（'每次都开'就是这条被违背）"

    hint_page, hint_window = page.minimumSizeHint().width(), window.minimumSizeHint().width()

    strip_button = page.tree_panel.strip.findChild(QtWidgets.QToolButton)
    assert strip_button is not None, "48px 的条上得真有一颗按钮"
    strip_button.click()
    _settle(qapp)
    assert page.tree_panel.isVisible(), "点条上的按钮没唤出树"
    geo = page.tree_panel.geometry()
    assert geo.x() + geo.width() == page.width(), f"浮层没贴在页面右沿：{geo.getRect()}"
    assert geo.width() == tier.OVERLAY_WIDTH, f"浮层不是 D-040 的 {tier.OVERLAY_WIDTH}px：{geo.width()}"

    # 一块 host 上同时只开一个浮层：线框只给了一个位置，两个叠着会让下面那个变成关不掉的透明层。
    page.detail_panel.open_overlay()
    _settle(qapp)
    assert page.detail_panel.isVisible() and not page.tree_panel.isVisible(), \
        "开第二个浮层时第一个没收起"

    page.detail_panel.close_button.click()
    _settle(qapp)
    assert not page.detail_panel.isVisible(), "顶栏那颗「✕ 关闭」没把浮层关掉（D-040 的「可关」）"

    assert (page.minimumSizeHint().width(), window.minimumSizeHint().width()) == (hint_page, hint_window), \
        "浮层开了就把窗口的最低宽度顶宽 —— 它不该参与布局"


def test_地板档下_S8_的树侧栏收起(window, qapp) -> None:
    """**D-039** 尺寸段点名要写成界面断言的那一条：1024 档收起 S8 的树侧栏。

    顺带钉住"收起的是一整块、不是只收树"：树下面的新建/改名/删除三颗按钮跟着面板一起进
    浮层，否则 1024 档这一屏变成"能改看不见"。
    """
    wide = _page_at(window, qapp, "categories", DEFAULT_WINDOW_WIDTH, DEFAULT_WINDOW_HEIGHT)
    assert wide.tree_panel.narrow is False and wide.tree_panel.width() == LEFT_COLUMN_WIDTH

    page = _page_at(window, qapp, "categories", MIN_WINDOW_WIDTH, MIN_WINDOW_HEIGHT)
    assert page.tree_panel.narrow is True, "D-039：1024 档 S8 的树侧栏必须收起"
    assert page.tree_panel.strip.isVisible() and page.tree_panel.strip.width() == TREE_STRIP_WIDTH
    assert page.splitter.count() == 3, f"收起后该剩「条 + 标签 + 集合」三槽：{page.splitter.sizes()}"
    assert not page.tree_panel.isVisible()
    page.tree_panel.open_overlay()
    _settle(qapp)
    assert page.category_tree.isVisible() and page.add_cat_btn.isVisible(), \
        "浮层里只有树没有编辑按钮 —— 1024 档这一屏改不动分类"


@pytest.mark.parametrize("page_id", ["library", "categories"])
def test_两屏的面板都来自同一条规则(page_id: str, window, qapp) -> None:
    """AGENTS.md「禁止同类问题逐个打补丁」的机器版本：命中这一类的面板必须是同一个类。

    S1 两块、S8 一块。哪天有人在自己屏里再抄一份 `resizeEvent` 切档，这条先红。
    """
    page = _page_at(window, qapp, page_id, DEFAULT_WINDOW_WIDTH, DEFAULT_WINDOW_HEIGHT)
    assert page.findChildren(FloatablePanel), f"{page_id} 没有用 ui/tier.py 的可收起面板"
    for panel in page.findChildren(FloatablePanel):
        assert panel in page._panels, f"{page_id} 有一块面板没登记进 `_panels`，切档不会带上它"


def test_降级算术钉住线框里那三个数() -> None:
    """**D-040** 明写"算术进测试"：`236 + 480 + 360 = 1076 > 1024`。

    这条看着像废话，但下面那些几何断言全部是**拿常量比的** —— 把 48 改成 40，
    「条是 48px」那条照样绿（分子分母一起变）。只有把数钉死在字面量上，
    阈值自己漂掉时才会红。
    """
    assert (LEFT_COLUMN_WIDTH, CENTER_MIN_WIDTH, RIGHT_COLUMN_WIDTH) == (236, 480, 360)
    assert THREE_COLUMN_MIN_WIDTH == LEFT_COLUMN_WIDTH + CENTER_MIN_WIDTH + RIGHT_COLUMN_WIDTH
    assert THREE_COLUMN_MIN_WIDTH == 1076
    assert TREE_STRIP_WIDTH == 48 and tier.OVERLAY_WIDTH == 420
    assert THREE_COLUMN_MIN_WIDTH > MIN_WINDOW_WIDTH, "放不下这一档的前提，改了宽度就得重看降级"
    assert PAGE_WIDTH_AT_FLOOR < THREE_COLUMN_MIN_WIDTH <= PAGE_WIDTH_AT_DEFAULT, \
        "两档测试用的宽度必须真的分处阈值两侧，否则上面几条几何断言测的是同一档"


def test_尺寸阈值只有_tier_里那一份() -> None:
    """第二份口径的具体形态：页面模块里**自己定义**一个 `*WIDTH` 常量。

    查的是模块顶层的赋值（`ast`），不是 `dir(module)` —— 后者会把从 `ui/tier.py`
    和 `ui/table_layout.py` 正常导入的常量一起报成"自己的一份"（实测假红过一次）。
    阈值漂掉的后果不在 CI 里，在用户把窗口拖到 1024 的那一刻 —— 正是不该靠人记的那类。
    """
    for module in (library_page, categories_page):
        tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
        own = [target.id
               for node in tree.body if isinstance(node, ast.Assign)
               for target in node.targets
               if isinstance(target, ast.Name) and "WIDTH" in target.id]
        assert own == [], f"{module.__name__} 里自己定义了尺寸 {own} —— 用 ui/tier.py 的常量"


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
