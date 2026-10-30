"""**D-039 / D-040** 的降级几何 —— 1024 档收起侧栏，两屏共用 `ui/tier.py` 那一条规则；
外加 **ISSUES I54** 的表格几何（行号列在不在场、视口随不随数据量漂）、
**ISSUES I60** 的状态栏几何（口径那一行长什么样、折行之后顶不顶宽）、
**D-051** 的状态栏接线（浅扫自报那句话有没有真的上屏），以及 `FloatablePanel`
自己的两条形状账（宽档右栏是浮层而左栏是常驻列、「✕」不许漏成桌面顶层窗）。
轮四十二 ⑭ 之后右栏不再常驻：两档都是浮层、默认关、搜索出结果才开；轮四十四 ⑮（**D-066**）
又把左树在宽档也收成 48px 的条、轮四十五 乙 把那根条做成**标题轨**（整根可点 + 带分类计数）、
丙 把 S8 从可收起里摘出去 —— `test_宽档左树默认收成条而右栏默认关`、
`test_轨整根可点且带分类计数`、`test_地板档下_S8_的树侧栏收起而宽档常驻` 三条钉的是这三轮
叠在一起之后的契约。

为什么单独成一个文件（`test_app_shell.py` 那一摊 2026-10-17 已按 **ISSUES I58** 丙 拆成四份，
见 **REPO-JOURNAL R-010**）：这一组量的是**同一个控件在两个宽度档下的形状**，判据全部来自
`ui/tier.py` 与 `ui/table_layout.py` 的常量，跟外壳/读数/列宽底线守卫不是一条链。
**ISSUES I53** ②甲/③甲 那一节（命中面板的行文案、浏览态清空、Ctrl+F、跳到 S2 的链、
越界页码）2026-10-30 按同一理由拆进 `test_ui_hits.py` —— 它量的是**数据到文字的链路**，
不是控件在两个宽度下的形状。

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

from pdfarchiver.db.models import Document, TextPage
from pdfarchiver.db.repositories.documents import DocFilter
from pdfarchiver.fs.identity import identity_key
from pdfarchiver.services.bootstrap import AppContext
from pdfarchiver.ui import library_hits, tier
from pdfarchiver.ui.main_window import (
    DEFAULT_WINDOW_HEIGHT,
    DEFAULT_WINDOW_WIDTH,
    MIN_WINDOW_HEIGHT,
    MIN_WINDOW_WIDTH,
    NAV_WIDTH,
)
from pdfarchiver.ui.nav import NAV_ITEMS
from pdfarchiver.ui.pages import categories_page, library_page
from pdfarchiver.ui.tier import (
    CENTER_MIN_WIDTH,
    LEFT_COLUMN_WIDTH,
    RIGHT_COLUMN_WIDTH,
    THREE_COLUMN_MIN_WIDTH,
    TREE_STRIP_WIDTH,
    FloatablePanel,
)
from tests.conftest import page_at as _page_at, settle as _settle

# 页面可用宽 = 窗口宽 − 导航 − 1px 边框（实测 1024→823、1280→1079；这条 −1 的口径
# 与 `test_ui_layout.AVAILABLE_WIDTH` 同一个来源，两处都不写死像素）。
PAGE_WIDTH_AT_FLOOR = MIN_WINDOW_WIDTH - NAV_WIDTH - 1     # 823
PAGE_WIDTH_AT_DEFAULT = DEFAULT_WINDOW_WIDTH - NAV_WIDTH - 1   # 1079

# `window` 夹具与 `_page_at` 走 conftest 那一份（**ISSUES I58** 丙，2026-10-17：
# `test_app_shell.py` 拆成四份后四组都要它，本地再留一份一模一样的就是第二个口径）。


def _seed_docs(ctx: AppContext, count: int = 3) -> list[int]:
    """灌几行进文档表 —— 空表量不到行高，长文件名才量得到"变行高展开"会不会发生。

    返回落库后的 id：⑮ 那颗小圆点的用例要真去建一条"文档 ↔ 分类"关联。
    """
    ids: list[int] = []
    for n in range(count):
        name = f"归档范围与保留期限的请示（复函稿）第{n}版附件全部版本.pdf"
        path = f"D:\\用户资料\\2026 年度合同与结算凭证归档\\{name}"
        doc = ctx.documents.upsert(Document(
            path=path, path_key=identity_key(path), name=name,
            size_bytes=1024 * 1024, mtime_ns=1_760_000_000_000_000_000,
            sha256=f"{n:064x}", text_status="done", fts_status="done"))
        ids.append(doc.id)
    return ids


def test_宽档左树默认收成条而右栏默认关(window, qapp) -> None:
    """**D-066**（走查 ⑮）之后的宽档：左树起始是一条 48px 的条，点条才展开成 236px 常驻列。

    这条改名自 `test_宽档左栏常驻而右栏默认关`（轮四十二 ⑭ 的契约，D-066 取消了它留给
    左树的那条"宽档常驻"例外）。没动的两条读数：`narrow is False`（切档**真的跑过** ——
    上一轮这里量到 [236, 481, 360] 看着对，其实那三个数来自 `__init__` 里手写的 `setSizes`，
    切档代码在 Qt 虚函数里抛异常被吞了、从没跑过）；右栏 `docked=False` + 定宽 420 + 默认关。
    """
    page = _page_at(window, qapp, "library", DEFAULT_WINDOW_WIDTH, DEFAULT_WINDOW_HEIGHT)
    assert page.width() == PAGE_WIDTH_AT_DEFAULT, f"页面可用宽不是 {PAGE_WIDTH_AT_DEFAULT}：{page.width()}"
    assert page.width() >= THREE_COLUMN_MIN_WIDTH, "用例前提：这一档应当放得下左树 + 中栏"
    tp = page.tree_panel
    assert tp.narrow is False, "切档没跑（还是 None）—— 异常被 Qt 的虚函数调用吞掉了"
    assert tp.collapsible and tp.collapsed, "⑮：带条的左树宽档起始就该收成条"
    assert tp.parent() is page and not tp.isVisible(), \
        "收成条时面板还留在 splitter 里占槽 —— 那一栏没真的让出来"
    assert tp.strip.isVisible() and tp.strip.width() == TREE_STRIP_WIDTH, \
        f"宽档没留出 {TREE_STRIP_WIDTH}px 的条：{tp.strip.width()}"
    assert page.splitter.count() == 2, f"收起后该只剩「条 + 中栏」两槽：{page.splitter.sizes()}"
    center = page.splitter.widget(1)
    assert center.width() >= page.width() - TREE_STRIP_WIDTH - 2, \
        f"收起的没把宽度还给中栏：中栏 {center.width()}px，可用 {page.width() - TREE_STRIP_WIDTH}px"

    # 点条展开 = D-040 原本的宽档形状（236px 常驻列，不是 420px 浮层）。
    tp.strip_button.click()
    _settle(qapp)
    assert tp.isVisible() and tp.parent() is page.splitter, "点条没把这一栏放回 splitter"
    assert tp.width() == LEFT_COLUMN_WIDTH, f"展开的左栏不是 D-040 的 {LEFT_COLUMN_WIDTH}px：{tp.width()}"
    assert tp.strip.isVisible(), "展开态条没了 ⇒ 这一栏收不回去（把手只有这一颗）"
    assert not tp.close_button.isVisible(), "常驻列不该有「✕」—— 浮层才用角标出口"
    assert page.splitter.count() == 3 and center.width() >= CENTER_MIN_WIDTH, \
        f"展开后中栏低于 D-040 的 {CENTER_MIN_WIDTH}px 下限：{center.width()}"

    # 再点收回：两态可逆。展开态常驻列把窗口的最低宽度抬到 481（实测），收回成条后
    # 必须**不增** —— 收起时漏清 `setFixedWidth(420)` 就是这一条先红。
    hint = window.minimumSizeHint().width()
    assert hint <= MIN_WINDOW_WIDTH, f"展开态已经吃掉 D-039 的 {MIN_WINDOW_WIDTH}px 地板余量：{hint}"
    tp.strip_button.click()
    _settle(qapp)
    assert not tp.isVisible() and tp.parent() is page, "再点条没收回成条"
    assert window.minimumSizeHint().width() <= hint, \
        f"收回成条反而把窗口最低宽度顶宽了：{hint} → {window.minimumSizeHint().width()}"

    rp = page.right_panel
    assert rp.docked is False and rp.narrow is None, "右栏不该吃档位判定（轮四十二 ⑭）"
    assert rp.parent() is page and not rp.isVisible(), "右栏默认关、挂页面上当浮层"
    assert (rp.minimumWidth(), rp.maximumWidth()) == (tier.OVERLAY_WIDTH, tier.OVERLAY_WIDTH), \
        f"右栏定宽不是 {tier.OVERLAY_WIDTH}px"


def test_条上小圆点跟着分类关联走(window, ctx, qapp) -> None:
    """⑮ 那句"树里有内容时条上加个小圆点提醒" —— 判据是**有没有文档归过类**，不是树非空。

    为什么不用节点数：装配时就种下 14 个默认分类（启动读数那句「分类 14 个（种下默认分类
    14 个）」），拿节点数当信号等于装一颗永远亮着的灯 —— 与 **ISSUES I33** 修过的那类
    "永不变的瞎读数"是同一种病，灯一旦恒亮就不再回答任何问题。
    """
    page = _page_at(window, qapp, "library", DEFAULT_WINDOW_WIDTH, DEFAULT_WINDOW_HEIGHT)
    dot = page.tree_panel.strip_dot
    assert dot is not None and not dot.isVisible(), "一份都没归入分类 ⇒ 灯不该亮"

    ctx.catalog.link_categories(_seed_docs(ctx, 1), ctx.catalog.list_categories()[0].id)
    page.reload()
    _settle(qapp)
    assert dot.isVisible(), "归入过分类了，条上的灯还灭着"

    ctx.catalog.delete_category(ctx.catalog.list_categories()[0].id)
    page.reload()
    _settle(qapp)
    assert not dot.isVisible(), "关联都删光了灯还亮着 —— 它没有在跟着库走"


def test_轨整根可点且带分类计数(window, ctx, qapp) -> None:
    """**轮四十五 乙**：那根 48px 的条从此是**标题轨**，不是"顶上 20px 能点的死列"。

    四条读数各对着改前的一次实测：
    - 可点区占比 ≥ 90%（改前那颗按钮 44×20 压 48×875 = **2.1%**，97.9% 的面积点不动）；
    - `objectName="treeRail"` **且**运行时 stylesheet 里真有 `QWidget#treeRail` 那条 ——
      只量 objectName 的话，把 QSS 里那条删掉照样绿，而屏上又变回"另一栏"；
    - 轨上有分类计数：零篇归类时那颗圆点恒灭（⑮ 的实测就是 0 行挂载），"有几类可归"
      是轨上唯一答得上话的东西。**跟着库走**那条才是关键 —— 写死 14 也能过前一条；
    - 箭头跟着形状翻（收起朝右 = 点开它，展开朝左 = 点它收回）。
    """
    page = _page_at(window, qapp, "library", DEFAULT_WINDOW_WIDTH, DEFAULT_WINDOW_HEIGHT)
    tp = page.tree_panel
    strip, button = tp.strip, tp.strip_button
    assert strip is not None and button is not None, "用例前提：带条的面板才谈得上标题轨"

    hit = button.width() * button.height()
    rail = strip.width() * strip.height()
    assert rail > 0 and hit / rail >= 0.9, \
        f"轨上只有 {hit / rail:.1%} 可点（改前 2.1%）—— 其余是一条点不动的死列"

    assert strip.objectName() == "treeRail", f"轨没挂上 QSS 要的钩子：{strip.objectName()!r}"
    # 运行时那份 QSS 是外壳自己 `setStyleSheet` 上去的（`main_window.py:211`），不在 qapp 上 ——
    # 拿 `qapp.styleSheet()` 量会恒读到空串，这条就成了一条永真断言。
    assert "QWidget#treeRail" in window.styleSheet(), \
        "objectName 挂上了但样式表里没有对应选择器 —— 观感照旧是 splitter 边框"

    expected = len(ctx.catalog.category_tree())
    assert str(expected) in button.text(), f"轨上没有分类计数（{expected} 类）：{button.text()!r}"
    assert "\n" in button.text(), f"计数与标签得竖排才塞得进 48px：{button.text()!r}"

    ctx.catalog.delete_category(ctx.catalog.list_categories()[-1].id)
    page.reload()
    _settle(qapp)
    assert str(expected - 1) in button.text() and str(expected) not in button.text(), \
        f"删掉一类之后轨上还是旧数字：{button.text()!r}"

    assert button.text().startswith("▸"), f"收起态的箭头该朝右（点开它）：{button.text()!r}"
    button.click()
    _settle(qapp)
    assert tp.isVisible() and button.text().startswith("◂"), \
        f"展开态的箭头没翻过来（点它收回）：{button.text()!r}"


def test_窄档左栏收成_48px_的条而右栏同样不占槽(window, qapp) -> None:
    """**D-040** 的取舍：地板档放不下三栏，牺牲的是命中/详情栏，**不是分类树**。

    分类树在窄档换成一条 48px 的条，中栏吃掉剩余宽度（实测 823 档：[48, 774]）。
    右栏非常驻，窄档它还是那块默认关的浮层 —— 窄档真正要降级的只有左栏。
    """
    page = _page_at(window, qapp, "library", MIN_WINDOW_WIDTH, MIN_WINDOW_HEIGHT)
    assert page.width() == PAGE_WIDTH_AT_FLOOR
    assert page.width() < THREE_COLUMN_MIN_WIDTH, "用例前提：这一档放不下三栏"
    assert page.tree_panel.narrow is True and page.right_panel.narrow is None
    assert page.tree_panel.parent() is page and page.right_panel.parent() is page, \
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
    for panel in (page.tree_panel, page.right_panel):
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
    page.right_panel.open_overlay()
    _settle(qapp)
    assert page.right_panel.isVisible() and not page.tree_panel.isVisible(), \
        "开第二个浮层时第一个没收起"

    page.right_panel.close_button.click()
    _settle(qapp)
    assert not page.right_panel.isVisible(), "顶栏那颗「✕ 关闭」没把浮层关掉（D-040 的「可关」）"

    assert (page.minimumSizeHint().width(), window.minimumSizeHint().width()) == (hint_page, hint_window), \
        "浮层开了就把窗口的最低宽度顶宽 —— 它不该参与布局"


def test_地板档下_S8_的树侧栏收起而宽档常驻(window, qapp) -> None:
    """**D-039** 尺寸段点名要写成界面断言的那一条：1024 档收起 S8 的树侧栏。

    宽档那半是 **轮四十五 丙** 改的（改名自 `test_地板档下_S8_的树侧栏收起`）：**D-066**
    曾把 S8 也收成条，而 ⑮ 那条实测判据（14 个默认分类零篇挂载）说的是 **S1 的筛选**场景 ——
    S8 是**管理**场景，这棵树正是这一屏要编辑的主对象，默认藏进 48px 是语义错放。
    于是这一条现在读的是「宽档 236px 常驻 + 条不在场，窄档才收成条」。

    顺带钉住"收起的是一整块、不是只收树"：树下面的新建/改名/删除三颗按钮跟着面板一起进
    浮层，否则 1024 档这一屏变成"能改看不见"。
    """
    wide = _page_at(window, qapp, "categories", DEFAULT_WINDOW_WIDTH, DEFAULT_WINDOW_HEIGHT)
    tp = wide.tree_panel
    assert tp.narrow is False and tp.collapsible is False, \
        "丙：S8 的主对象（分类树）不许默认收成条 —— 收起判据来自 S1 的筛选场景"
    assert tp.isVisible() and tp.parent() is wide.splitter, "宽档 S8 的树没常驻在 splitter 里"
    assert tp.width() == LEFT_COLUMN_WIDTH, f"常驻的树不是 D-040 的 {LEFT_COLUMN_WIDTH}px：{tp.width()}"
    assert not tp.strip.isVisible(), "宽档不收起的这一屏还留着那 48px 的条 —— 白占一槽"

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
    for module in (library_page, library_hits, categories_page):
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


# ---------------------------------------------------------------------------
# **ISSUES I54**：Qt 自动长出来的行号列
# ---------------------------------------------------------------------------
# 全项目没有一处主动要过这一列，但只要有行它就在场，而且**按行号的位数变宽**
# （2026-10-17 现测：空表 0 / 2 行 38 / 40 行 51px）。两条断言分管两头：
# 第一条管"在场不在场"（逐屏扫），第二条管"在场会造成什么"（视口随数据量漂）。


def test_每张表都不许带行号列(window, ctx, qapp) -> None:
    """9 张表逐个点名 —— 这条是"第 10 张表冒出来时会不会漏"的牙。

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
    assert seen == 9, f"全站该扫到 9 张表，实际 {seen} 张 —— 有页面新增了表或表被拆掉了，重数一遍再改注释"


def test_每张表都是单行行高_不许开自动换行(window, ctx, qapp) -> None:
    """**ISSUES I107**：`wordWrap` 开着时，Qt 把「反斜杠 + CJK 混排」的长路径画成 `C…`。

    真桌面实测（2026-10-24，S3 计划表）：同一格 260px、文本 98 字符，`ElideRight` 下整行只剩
    一个字符加省略号；同一格换成正斜杠串立刻正常，`setWordWrap(False)` 后也恢复正常
    （对照图 `.probe_work/_plan_repro_full.png` / `_plan_nowrap.png`）。离屏平台不复现这条
    绘制差异（CJK 字形本就缺），所以这里钉的是**开关**：9 张表一律 `wordWrap() is False`。

    坏法注入（2026-10-24 真跑过）：删掉 `table_layout.set_table_columns()` 里那行
    `setWordWrap(False)` → 这里 9 张表逐张红并点名；还原后绿。
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
    assert seen == 9, f"全站该扫到 9 张表，实际 {seen} 张 —— 有页面新增了表或表被拆掉了"


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
    """
    _seed_docs(ctx, 3)
    for width in (MIN_WINDOW_WIDTH, DEFAULT_WINDOW_WIDTH):
        page = _page_at(window, qapp, "library", width, MIN_WINDOW_HEIGHT)
        for query, want_slow in (("请示", True), ("保留期限", False)):
            page.search_input.setText(query)
            page._do_search()
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
    page._do_search()
    _settle(qapp)
    assert "未扫完" in page.status_label.text(), page.status_label.text()

    monkeypatch.setattr("pdfarchiver.search.service.LIKE_SCAN_ROWS", 99)
    page._do_search()
    _settle(qapp)
    assert "未扫完" not in page.status_label.text(), page.status_label.text()


# ---------------------------------------------------------------------------
# `FloatablePanel` 自己的两条形状账
# ---------------------------------------------------------------------------
# 上面那些用例管的是"什么时候收成什么形状"，这两条管的是"收成的那种形状有没有真做成"：
# 常驻列不许被 `close_overlay()` 收走（收走就再也回不来），浮层的「✕」不许漏成顶层孤儿窗。
# **ISSUES I53** ②甲/③甲 那一节（命中面板的行文案、浏览态清空、Ctrl+F、跳 S2 的链、
# 越界页码）在 `test_ui_hits.py`。


def test_右栏两档都是浮层_宽档常驻树列关不掉(window, qapp) -> None:
    """轮四十二 ⑭ 之后的不对称：右栏（docked=False）两档都是可关的浮层；
    左树（docked=True）在宽档是常驻列，`close_overlay()` 必须早退 ——
    常驻列被误收起后 `set_narrow()` 只在真的换档时才 `setVisible(True)`，
    宽档一旦收起就**再也回不来**（2026-10-17 探针实测到了这个形状）。
    """
    page = _page_at(window, qapp, "library", DEFAULT_WINDOW_WIDTH, DEFAULT_WINDOW_HEIGHT)
    rp = page.right_panel
    assert not rp.isVisible()
    rp.open_overlay()
    _settle(qapp)
    assert rp.isVisible(), "宽档右栏也该能开（两档都是浮层）"
    geo = rp.geometry()
    assert geo.width() == tier.OVERLAY_WIDTH and geo.x() + geo.width() == page.width(), \
        f"右栏没贴在页面右沿：{geo.getRect()}"
    rp.close_button.click()
    _settle(qapp)
    assert not rp.isVisible(), "右栏的「✕」没把浮层关掉"

    tp = page.tree_panel
    tp.expand()                        # D-066 之后宽档起始是条，先把它展开成常驻列
    _settle(qapp)
    assert tp.isVisible(), "用例前提：展开后的左栏是常驻列"
    assert not tp.close_button.isVisible(), "宽档常驻列不该有「✕」"
    tp.close_overlay()
    _settle(qapp)
    assert tp.isVisible() and tp.parent() is page.splitter and tp.width() == LEFT_COLUMN_WIDTH, \
        "宽档的常驻树列被 close_overlay() 收走了 —— 这一档没有'关掉整栏'这回事"


def test_浮层的关闭按钮不许成为无父孤儿(window, qapp) -> None:
    """2026-10-29 真实事故：桌面漏出一个 135×59 的「✕ 关闭」顶层小窗。

    根因是构造顺序 —— 控件先 `addWidget` 进未安装的 `head`，`head` 才被 `addLayout` 进
    `body`，PySide6 6.8 不给这种顺序补 reparent（探针实测 parent 从构造起就是 None）；
    窄档 `set_narrow(True)` 里 `close_button.setVisible(True)` 一调，无父控件就被提升成
    独立顶层窗口，`panel.setVisible(False)` 永远盖不住它。判据用 `window()`（控件实际
    所在的顶层窗口）而不是只看 `parent()`：孤儿一旦露头，`window()` 就不再等于主窗。
    坏法注入实测（2026-10-29，本轮真跑）：把构造改回无父的 `QToolButton()` ⇒ 窄档开
    浮层后 `window() is panel.window()` 当场红，且 `topLevelWidgets()` 里扫出孤儿按钮。
    """
    page = _page_at(window, qapp, "library", MIN_WINDOW_WIDTH, MIN_WINDOW_HEIGHT)
    for panel in (page.tree_panel, page.right_panel):
        assert panel.close_button.parent() is panel, \
            "关闭按钮没有显式挂到面板上 —— 窄档 setVisible(True) 会把它漏成桌面顶层窗口"
        panel.open_overlay()
        _settle(qapp)
        assert panel.close_button.window() is panel.window(), \
            "「✕ 关闭」成了一个独立顶层窗口（孤儿按钮漏到桌面的形状）"
        panel.close_overlay()
        _settle(qapp)
    orphans = [w for w in QtWidgets.QApplication.topLevelWidgets()
               if isinstance(w, QtWidgets.QToolButton) and w.text() == "✕"]
    assert not orphans, f"桌面级顶层控件里扫到 {len(orphans)} 颗孤儿「✕」按钮"
