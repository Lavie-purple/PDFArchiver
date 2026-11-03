"""**D-039 / D-040** 的降级几何 —— 1024 档收起侧栏，两屏共用 `ui/tier.py` 那一条规则；
外加 `FloatablePanel` 自己的两条形状账（宽档两栏都是常驻列、「✕」不许漏成桌面顶层窗）。
（**追注 2026-11-04 · 轮六十**：**ISSUES I54** 的表格几何、**ISSUES I60** 的状态栏几何与
**D-051** 的状态栏接线三组按 800 行线拆进 `test_ui_table_geom.py`，刀口在"量的对象"——
这一文件管面板在宽度档下收成什么形状，那一文件管表里的行与状态栏那句口径话占掉多少像素。）
轮四十二 ⑭ 之后右栏曾两档都是浮层、默认关、搜索出结果才开；轮五十九 ②甲 把它改回**宽档贴边常驻**
（浮层盖住的正好是它自己抄的那一列），代价是「轨 + 展开的树 + 中栏下限 + 右栏」= 1,124 > 默认档
可用的 1,099 —— 三条地板下限一条没放宽，放不下时由 `sacrificial` 那一栏让位（**D-040**
「必须且只牺牲右栏」从此按当下需求算，不再只看宽窄）。轮六十 **ISSUES I133** 乙 把这条算式里
中栏那一格从 480 的地板换成**它自己的真实需求**（S1 = 定宽表 780 + 中栏左右边距 16 = **796**，
由页面从 `set_table_columns` 的返回值算出来，`ui/tier.py` 里不出现第二个数），再把 splitter
那 1~3 根 1px 把手一起算进去 —— 于是"贴边常驻"有了入场券：**条态从窗口 1,387 起、展开左树
从 1,624 起**，默认档 1,280 退回浮层（并且按 ⑭ 那条"默认关"，空栏不再盖着表格），换回的是
中栏整张定宽表一屏放完、横向滚动条不再常驻。轮四十四 ⑮（**D-066**）
又把左树在宽档也收成 48px 的条、轮四十五 乙 把那根条做成**标题轨**（整根可点 + 带分类计数）、
丙 把 S8 从可收起里摘出去 —— `test_宽档左树默认收成条而右栏贴边常驻`、
`test_右栏常驻的入场券是中栏装得下全表`（乙 新加的那一条：两档交叉 + 换来的是什么）、
`test_宽档展开左树时让位的是右栏_三条下限一条不放宽`、
`test_轨整根可点且带分类计数`、`test_地板档下_S8_的树侧栏收起而宽档常驻` 五条钉的是这几轮
叠在一起之后的契约。

为什么单独成一个文件（`test_app_shell.py` 那一摊 2026-10-17 已按 **ISSUES I58** 丙 拆成四份，
见 **REPO-JOURNAL R-010**）：这一组量的是**同一个控件在两个宽度档下的形状**，判据全部来自
`ui/tier.py` 的常量，跟外壳/读数/列宽底线守卫不是一条链。
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
from PySide6 import QtCore, QtGui, QtWidgets

from pdfarchiver.ui import library_hits, tier
from pdfarchiver.ui.main_window import (
    DEFAULT_WINDOW_HEIGHT,
    DEFAULT_WINDOW_WIDTH,
    MIN_WINDOW_HEIGHT,
    MIN_WINDOW_WIDTH,
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
from tests.conftest import (
    PAGE_WIDTH_AT_DEFAULT,
    PAGE_WIDTH_AT_DOCKED,
    PAGE_WIDTH_AT_FLOOR,
    WINDOW_WIDTH_RIGHT_DOCKED,
    page_at as _page_at,
    resize_stepped as _stepped,
    seed_docs as _seed_docs,
    settle as _settle,
)

# 三个量档（843 / 1,099 / 1,259）与 `_seed_docs` 都在 `tests/conftest.py`：判形状的这一组与
# 判表格几何的那一组（`test_ui_table_geom.py`，轮六十 按 800 行线拆出）都要它们，抄两份就是
# 第二个口径。**ISSUES I58** 丙 拆 `test_app_shell.py` 时同一条理由。


def _center(splitter: QtWidgets.QSplitter, page) -> QtWidgets.QWidget:
    """中栏 = splitter 里唯一不是面板、也不是轨的那一槽。

    不写死下标：槽序跟着形状变（收起时「条 + 中栏 + 右栏」，展开让位时「条 + 树 + 中栏」），
    写死 `widget(1)` 的用例在形状变了那天就开始量错东西 —— 而量错的中栏照样是个正数，不会红。
    """
    skip = {id(widget) for panel in page._panels
            for widget in (panel, panel.strip) if widget is not None}
    for i in range(splitter.count()):
        widget = splitter.widget(i)
        if id(widget) not in skip:
            return widget
    raise AssertionError(f"用例前提：splitter 里没有中栏：{splitter.sizes()}")


def test_宽档左树默认收成条而右栏贴边常驻(window, qapp) -> None:
    """**D-066**（走查 ⑮）+ **轮五十九 ②甲** 之后的宽档：左树起始是 48px 的条，右栏贴边常驻。

    这条改名自 `test_宽档左树默认收成条而右栏默认关`（轮四十二 ⑭ 那份"两档都是浮层"的契约由
    ②甲 接替：浮层盖住的正好是它自己抄的那一列 —— 用户 2026-11-03 红框 #2 的"右侧和左侧一致"）。
    没动的读数：`narrow is False`（切档**真的跑过** —— 上一轮这里量到 [236, 481, 360] 看着对，
    其实那三个数来自 `__init__` 里手写的 `setSizes`，切档代码在 Qt 虚函数里抛异常被吞了、从没跑过）。
    跟着形状一起改的只有右栏那几条：它现在**吃档位判定**，所以 `narrow` 不再是 None。

    【2026-11-04 **ISSUES I133** 乙】"贴边常驻"从这一轮起有入场券（要装得下中栏那张定宽表），
    默认档 1,280 不再常驻 ⇒ 这一条的量档换到 `WINDOW_WIDTH_RIGHT_DOCKED`（1,440，页面 1,259
    ≥ 轨 48 + 中栏 796 + 右栏 360 + 两根 1px 把手 = 1,206）。**默认档为什么让位、让位之后
    中栏拿到多少**由 `test_右栏常驻的入场券是中栏装得下全表` 那条量，两条不重叠。
    """
    page = _page_at(window, qapp, "library", WINDOW_WIDTH_RIGHT_DOCKED, DEFAULT_WINDOW_HEIGHT)
    assert page.width() == PAGE_WIDTH_AT_DOCKED, f"页面可用宽不是 {PAGE_WIDTH_AT_DOCKED}：{page.width()}"
    assert page.width() >= THREE_COLUMN_MIN_WIDTH, "用例前提：这一档应当放得下左树 + 中栏 + 右栏"
    tp = page.tree_panel
    assert tp.narrow is False, "切档没跑（还是 None）—— 异常被 Qt 的虚函数调用吞掉了"
    assert tp.collapsible and tp.collapsed, "⑮：带条的左树宽档起始就该收成条"
    assert tp.parent() is page and not tp.isVisible(), \
        "收成条时面板还留在 splitter 里占槽 —— 那一栏没真的让出来"
    assert tp.strip.isVisible() and tp.strip.width() == TREE_STRIP_WIDTH, \
        f"宽档没留出 {TREE_STRIP_WIDTH}px 的条：{tp.strip.width()}"

    # 右栏（②甲 改的就是这几条）：左树收成条时「轨 48 + 中栏真实需求 796 + 右栏 360」+ 两根
    # 1px 把手 = 1,206 ≤ 1,259，放得下，它就该在第三槽里贴边常驻。
    rp = page.right_panel
    assert rp.docked and rp.narrow is False, \
        f"右栏现在吃档位判定了，narrow 必须是现成的读数而不是 None：{rp.narrow}"
    assert rp.sacrificial, "右栏必须认领 D-040「必须且只牺牲右栏」—— 谁可以让位只许有这一个声明处"
    assert rp.parent() is page.splitter and rp.isVisible() and rp.width() == RIGHT_COLUMN_WIDTH, \
        f"宽档右栏没作为 {RIGHT_COLUMN_WIDTH}px 常驻列贴在右边：parent={rp.parent()} w={rp.width()}"
    assert not rp.close_button.isVisible(), \
        "常驻列不该有「✕」—— 关不掉的栏摆一颗按下去没反应的按钮，是假出口"
    assert page.splitter.count() == 3, f"宽档该是「条 + 中栏 + 右栏」三槽：{page.splitter.sizes()}"
    center = _center(page.splitter, page)
    # 减掉的是两根 1px 把手（实测 849 = 1,259 − 48 − 360 − 2），不是"中栏自己缩了"。
    assert center.width() >= page.width() - TREE_STRIP_WIDTH - RIGHT_COLUMN_WIDTH - 2, \
        f"收起的左树没把宽度还给中栏：中栏 {center.width()}px"
    assert center.width() >= page.center_minimum_width, \
        f"乙 的承诺兑现不了：右栏常驻时中栏只有 {center.width()}px，装不下它自己声明的 {page.center_minimum_width}px"

    # 收起态与展开态的常驻需求不同（48+360 vs 48+236+360），最低宽度因此**本来就会变**，
    # 所以这里在起始形状取基准、走完一个来回再比 —— 比的仍是同一个形状。
    hint = window.minimumSizeHint().width()
    assert hint <= MIN_WINDOW_WIDTH, f"宽档常驻形状已经吃掉 D-039 的 {MIN_WINDOW_WIDTH}px 地板余量：{hint}"

    # 点条展开 = 236px 常驻列（这一档展开之后右栏放不下、让位成浮层，那一形状单独两条用例量）。
    tp.strip_button.click()
    _settle(qapp)
    assert tp.isVisible() and tp.parent() is page.splitter, "点条没把这一栏放回 splitter"
    assert tp.width() == LEFT_COLUMN_WIDTH, f"展开的左栏不是 D-040 的 {LEFT_COLUMN_WIDTH}px：{tp.width()}"
    assert tp.strip.isVisible(), "展开态条没了 ⇒ 这一栏收不回去（把手只有这一颗）"
    assert not tp.close_button.isVisible(), "常驻列不该有「✕」—— 浮层才用角标出口"
    assert page.splitter.count() == 3 and _center(page.splitter, page).width() >= CENTER_MIN_WIDTH, \
        f"展开后中栏低于 D-040 的 {CENTER_MIN_WIDTH}px 下限：{_center(page.splitter, page).width()}"

    # 再点收回：两态可逆。收回时漏清 `setFixedWidth(420)` 就是最后这一条先红。
    tp.strip_button.click()
    _settle(qapp)
    assert not tp.isVisible() and tp.parent() is page, "再点条没收回成条"
    assert window.minimumSizeHint().width() <= hint, \
        f"收回成条反而把窗口最低宽度顶宽了：{hint} → {window.minimumSizeHint().width()}"


def test_右栏常驻的入场券是中栏装得下全表(window, ctx, qapp) -> None:
    """**ISSUES I133** 乙：常驻不再只看 D-040 那条 480 地板，看的是"让出右栏之后中栏装不装得下**整张定宽表**"。

    三段判据（读数 2026-11-04 现量 `.probe_work/r60_truth2.log`）：
    ① **需求产地唯一** —— 中栏要多少由页面自己声明（`set_table_columns` 返回的定宽合计
       780 + 中栏布局左右边距 16 = **796**），`ui/tier.py` 里不出现这个数；
    ② **入场券按这条算式生效，两档各量两侧** —— 条态 1,360／1,386 让位、1,387 常驻；
       展开左树 1,623 让位、1,624 常驻。只量一侧挡不住"把手归零"那类改法（台账那句
       "约 1,385／约 1,621"与实测之差正好是 splitter 的 1px 把手），所以两侧都是判据；
    ③ **换来的是什么** —— 常驻的每一档中栏 ≥ 页面声明的需求，且文档表
       `horizontalScrollBar().maximum() == 0`（整张表一屏放完，用户不必横向滚文件名与路径 ——
       那正是 ②甲 之后滚动条常驻在 S1 的东西）；让位的档里右栏按 ⑭ 那条「默认关」**不唤出空栏**。

    为什么 ③ 用 `maximum()==0` 而不是"视口 ≥ 780"：780 是那张表的形状，已经在 ① 那个数里
    由列宽声明处产出一次；再在断言里抄一遍字面量就是第二个口径（**D-040** 那条纪律）。
    `maximum()==0` 是 Qt 自己对"装得下"的读数，它把 796 这个数**覆盖不到**的变数一起算进来
    —— 注入 ⑧ 就是这一句的唯一牙齿（见下）。

    坏法注入实测（2026-11-04 跑 `.probe_work/r60_inject.py`，九条各跑一遍、每条按字节还原并
    校验 md5；逐字红字带行号见 RUNLOGS §4.71 与 `.probe_work/r60_inject.log`。下面按"哪一句先红"
    记，行号会随本文件增删漂移，所以不写行号）：
    ① 把 `_center_requirement` 换成 `return CENTER_MIN_WIDTH`（＝乙 之前的算式，只看 480 地板）
       ⇒ 红在让位那一支的 `state == (True, False)`：「1280px（条态）该让位成浮层，实际
       tight=False parent 在 splitter=True」；
    ② 把 `_handle_cost` 直接 `return 0` ⇒ 同一句，但红在 1,386 那一侧（1,387 常驻、1,386 也常驻）
       —— 这就是"两侧都量"的理由：只量常驻那一侧，把手归零照样绿；
    ③ 把 `sync_tier` 的 `tight = ...` 硬改成 `False` ⇒ 同一句，红在 1,280；
    ④ 把 `set_tight` 里 `invoked = self._invoked` 换回 `invoked = self.isVisible()` ⇒ 红在让位那一支
       最后的 `not rp.isVisible()`：「1386px 这一档右栏是浮层，新建窗口就把它开着」；同一场里 ⑭
       那条老守卫（`test_宽档展开左树时让位的是右栏_三条下限一条不放宽`）**照旧绿**
       （1 failed, 1 passed）⇒ 「默认关」这一半只有本用例接得住；
    ⑦ 把 `library_page` 那句声明改成 `self.center_minimum_width = 480`（页面不再交出真实需求）
       ⇒ 红在开头 `center_minimum_width == 796`：「中栏的需求不是从列宽声明处算出来的：480」；
    ⑧ 把 `set_table_columns` 落屏的列宽整体 +100（交出的那个数与真实所需分家）⇒ 红在
       `bar.maximum() == 0`：「1440px 常驻时文档表还要横向滚 2px…视口 833px、中栏 849px、
       纵向滚动条在场=False」，而它上一句"中栏 ≥ 它自己声明的需求"**照旧绿** —— 849 ≥ 796 是真的，
       格子够了而表放不下，只有 Qt 自己的滚动读数看得见。（先试过 +40：超出量被吸收列的 Stretch
       吃掉，全表仍 `max=0` ⇒ 这一句的入场券是"定宽列本身超出视口"，不是"表比声明宽一点"。）
    """
    _seed_docs(ctx)
    page = _page_at(window, qapp, "library", DEFAULT_WINDOW_WIDTH, DEFAULT_WINDOW_HEIGHT)
    rp, table = page.right_panel, page.doc_table
    bar, vsb = table.horizontalScrollBar(), table.verticalScrollBar()
    assert page.center_minimum_width == 796, \
        f"中栏的需求不是从列宽声明处算出来的：{page.center_minimum_width}（该是定宽表 780 + 边距 16）"
    assert page.center_minimum_width > CENTER_MIN_WIDTH, \
        "用例前提：这一屏的真实需求要高于 D-040 的地板，否则乙 的核算与 ②甲 等价、白测"

    # (窗口宽, 展开左树?) ⇒ 该不该常驻。两侧都取自现量交叉档。
    cases = [(DEFAULT_WINDOW_WIDTH, False, False), (1360, False, False), (1386, False, False),
             (WINDOW_WIDTH_RIGHT_DOCKED, False, True), (1386, True, False), (1624, True, True)]
    for width, expand, docks in cases:
        if expand:
            page.tree_panel.expand()
        else:
            page.tree_panel.collapse()
        _stepped(window, qapp, width, DEFAULT_WINDOW_HEIGHT)
        state = (rp.tight, rp.parent() is page.splitter)
        center = _center(page.splitter, page)
        shape = "展开" if expand else "条态"
        if docks:
            assert state == (False, True), \
                f"{width}px（{shape}）该贴边常驻，实际 tight={rp.tight} parent 在 splitter={state[1]}"
            assert center.width() >= page.center_minimum_width, \
                f"{width}px 常驻时中栏 {center.width()}px < 它自己声明的 {page.center_minimum_width}px —— 常驻的代价又回来了"
            assert bar.maximum() == 0, (
                f"{width}px 常驻时文档表还要横向滚 {bar.maximum()}px（整张定宽表没放完，**ISSUES I133**）；"
                f"视口 {table.viewport().width()}px、中栏 {center.width()}px、"
                f"纵向滚动条在场={vsb.isVisible()} 宽 {vsb.width()}px")
        else:
            assert state == (True, False), \
                f"{width}px（{shape}）该让位成浮层，实际 tight={rp.tight} parent 在 splitter={state[1]}"
            assert center.width() >= page.center_minimum_width, \
                f"{width}px 让位之后中栏 {center.width()}px 仍装不下整张表：让位没换来东西"
            assert not rp.isVisible(), \
                f"{width}px 这一档右栏是浮层，新建窗口就把它开着 ⇒ 一条空栏盖住表格右端（⑭「默认关」）"

    # 「默认关」不等于「唤出来也关不掉」：让位的档里页面真要它时必须在场（这条钉 `_invoked` 的另一半）。
    page.tree_panel.collapse()
    _stepped(window, qapp, DEFAULT_WINDOW_WIDTH, DEFAULT_WINDOW_HEIGHT)
    assert rp.tight and not rp.isVisible(), "回到让位那一档后它该是关着的浮层（上面那支已量过，这里是用例前提）"
    rp.open_overlay()
    _settle(qapp)
    assert rp.isVisible() and rp.width() == tier.OVERLAY_WIDTH, "open_overlay() 没把让位中的浮层开出来"
    rp.close_overlay()
    _settle(qapp)
    assert not rp.isVisible(), "✕ 关不掉 ⇒ 这条浮层成了关不掉的遮罩"


def test_宽档展开左树时让位的是右栏_三条下限一条不放宽(window, qapp) -> None:
    """**D-040**「必须且只牺牲右栏」从"整档只看宽窄"精确成"按当下常驻需求算"（轮五十九 ②甲）。

    算术（②甲 那份现量 `.probe_work/r59_readings.log`，乙 之后那份 `.probe_work/r60_truth2.log`）：
    展开左树要同时放下「轨 48 + 树 236 + 中栏 + 右栏 360」，**中栏那一格从 480 的地板换成
    它自己的真实需求 796**（**ISSUES I133** 乙）⇒ 门槛 1,124 → **1,440**。三条地板
    （480 / 360 / 236）与 D-039 的 1,024 一个像素都没动，动的只有"这一栏常驻的入场券"。
    ②甲 之后这个门槛真的会撞上车：左树收起时 1,440 那一档放得下（乙 的量档，见
    `test_右栏常驻的入场券是中栏装得下全表`），展开时放不下 —— **修法不是**把下限一起放宽，
    而是让声明了 `sacrificial` 的那一栏在算不下时变回浮层；窄档的牺牲逻辑本来就是这一味药，
    现在它按需求算，而不是按"宽窄"这一个布尔值算。

    这一条的"常驻"前提因此从默认档 1,280 挪到 `WINDOW_WIDTH_RIGHT_DOCKED`（1,440），
    "宽一档又回来了"那半挪到 1,660（页面 1,479 ≥ 1,440 + 三根 1px 把手）。

    坏法注入实测（2026-11-03 三条 + 2026-11-04 一条）：
    ① 把 `library_hits` 构造里的 `sacrificial=True` 摘掉 ⇒ 红在「右栏没让位」那条
       （它硬占 360px，中栏被压到 1,259−48−236−360−3=612 < 796，
       `test_右栏常驻的入场券是中栏装得下全表` 同时红）；
    ② 把 `sync_tier` 那句 `tight = …` 硬改成 `False` ⇒ 同一条红，读数一样 —— 这两条注入
       分不开，所以 ① 之外另钉 `rp.sacrificial`（声明处）与 ② 之外钉下面那档 1,660；
    ③ 把 `set_tight` 里 `_invoked` 那一步删掉（让位时不再重开）⇒ 红在「让位把用户正在看的
       那一栏变没了」；
       （2026-11-03 补做实测：第一次锚点出现 0 次没打上，那句话当时是空头账。按 CRLF 重锚后真跑
       `2 failed, 18 passed` —— 逐字「让位不许把用户正在看的那一栏变没（set_tight 里 was_open 那一步）」
       @ :193，另 :634 那条跟着红（它的前提就是"让位成了开着的浮层"）；还原后逐字节相同。）
    ④ 【乙】把 `set_tight` 的判据从 `self._invoked` 换回 `self.isVisible()` ⇒ 这一条**不红**
       （常驻列本来就 visible，两种写法在这里同值）；红的是
       `test_右栏常驻的入场券是中栏装得下全表` 的「默认关」那一支 —— 注入记录留在这里是为了
       说明这两条的分工，别把 ③ 与 ④ 当成同一条。
    """
    page = _page_at(window, qapp, "library", WINDOW_WIDTH_RIGHT_DOCKED, DEFAULT_WINDOW_HEIGHT)
    tp, rp = page.tree_panel, page.right_panel
    assert rp.parent() is page.splitter, \
        f"用例前提：条态、{WINDOW_WIDTH_RIGHT_DOCKED}px 这一档右栏是常驻列"
    demand = TREE_STRIP_WIDTH + LEFT_COLUMN_WIDTH + RIGHT_COLUMN_WIDTH + page.center_minimum_width
    assert demand == 1440 and page.width() < demand, \
        f"用例前提：这一档正好放不下四件常驻件（{page.width()} < {demand}）"

    rp.open_overlay()      # 「用户正在看这一栏」这笔账由页面记；乙 之后让位认的是它，不是 isVisible()
    _settle(qapp)
    tp.expand()
    _settle(qapp)
    assert rp.tight is True and rp.parent() is page, \
        f"放不下时右栏没让位（还在第三槽）：tight={rp.tight} parent={rp.parent()}"
    assert rp.width() == tier.OVERLAY_WIDTH, \
        f"让位后的右栏不是窄档那块浮层的 {tier.OVERLAY_WIDTH}px：{rp.width()}"
    assert rp.isVisible(), "让位不许把用户正在看的那一栏变没（`set_tight` 里 `_invoked` 那一步）"
    assert rp.close_button.isVisible(), "让位后它是浮层形状，✕ 就必须在场（常驻列上没有）"
    assert tp.width() == LEFT_COLUMN_WIDTH, "展开的左树被一起挤掉了 —— 让位只许发生在 sacrificial 那一栏"
    assert _center(page.splitter, page).width() >= CENTER_MIN_WIDTH, \
        f"让位之后中栏仍低于 D-040 的 {CENTER_MIN_WIDTH}px：{_center(page.splitter, page).width()}"

    # 再宽一档（1,660 → 页面 1,479）四件常驻件连同 splitter 的把手同时放得下，右栏就该自己回第三槽。
    # 这一半挡住"把 tight 恒置 True"那类假修法：让位必须由需求算出来，不是形状写死。
    _stepped(window, qapp, 1660, DEFAULT_WINDOW_HEIGHT)
    assert page.width() >= demand, f"用例前提：这一档该放得下四件常驻件：{page.width()} < {demand}"
    assert rp.tight is False and rp.parent() is page.splitter and rp.width() == RIGHT_COLUMN_WIDTH, \
        f"放得下却没回到常驻列：tight={rp.tight} w={rp.width()}"
    assert not rp.close_button.isVisible(), "常驻列上的 ✕ 没跟着形状收回去"
    assert _center(page.splitter, page).width() >= page.center_minimum_width


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

    分类树在窄档换成一条 48px 的条，中栏吃掉剩余宽度（实测 843 档：[48, 794]，2026-11-03；
    导航仍是 200 时那一读是 823 档 [48, 774]）。
    轮五十九 ②甲 之后右栏是**常驻列**，窄档把它摘成那块默认关的 420px 浮层 —— 与左树同一味药，
    所以它现在也吃档位判定（`narrow` 是真读数，不再是 None）。两栏一起让位，中栏才吃得到剩余宽度。
    """
    page = _page_at(window, qapp, "library", MIN_WINDOW_WIDTH, MIN_WINDOW_HEIGHT)
    assert page.width() == PAGE_WIDTH_AT_FLOOR
    assert page.width() < THREE_COLUMN_MIN_WIDTH, "用例前提：这一档放不下三栏"
    assert page.tree_panel.narrow is True and page.right_panel.narrow is True, \
        "两栏都该被判成窄档（右栏从 docked=False 改成常驻列之后，narrow 不再是 None）"
    assert page.tree_panel.parent() is page and page.right_panel.parent() is page, \
        "窄档两块面板都该从 splitter 里摘出来挂到页面上（不参与布局 ⇒ 顶不宽窗口）"
    assert page.splitter.count() == 2, f"窄档 splitter 该只剩「条 + 中栏」两槽：{page.splitter.sizes()}"
    strip = page.tree_panel.strip
    assert strip.isVisible() and strip.width() == TREE_STRIP_WIDTH, \
        f"左栏没收成 {TREE_STRIP_WIDTH}px 的条：{strip.width()}"
    center = _center(page.splitter, page)
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


# ---------------------------------------------------------------------------
# `FloatablePanel` 自己的两条形状账
# ---------------------------------------------------------------------------
# 上面那些用例管的是"什么时候收成什么形状"，这两条管的是"收成的那种形状有没有真做成"：
# 常驻列不许被 `close_overlay()` 收走（收走就再也回不来），浮层的「✕」不许漏成顶层孤儿窗。
# **ISSUES I53** ②甲/③甲 那一节（命中面板的行文案、浏览态清空、Ctrl+F、跳 S2 的链、
# 越界页码）在 `test_ui_hits.py`。


def test_常驻列关不掉_让位成浮层的那一栏才有出口(window, qapp) -> None:
    """`close_overlay()` 的早退跟着**形状**走，不跟着"这一栏叫什么"走（轮五十九 ②甲 改的就是这里）。

    原契约（轮四十二 ⑭ 那条同名用例）里右栏两档都是浮层、可关，只有左树是常驻列。现在右栏宽档
    也是常驻列，两栏在同一档**共用同一条早退**：常驻列被误 `setVisible(False)` 之后
    `set_narrow()` 只在真的换档时才 `setVisible(True)`，宽档一旦收起就**再也回不来**
    （2026-10-17 探针实测到了这个形状）。右栏的浮层形状改由「让位」产生 —— 展开左树把它挤出
    第三槽的那一刻，✕ 必须真的在、且真的关得掉。判据收在 `_is_overlay()` 一个出口上
    （**D-040** 第三条后果那条纪律：`narrow or tight` 的合并写法散开就是第二个口径）。

    【2026-11-04 **I133** 乙】"宽档右栏是常驻列"这一前提从默认档 1,280 挪到
    `WINDOW_WIDTH_RIGHT_DOCKED`（1,440）：乙 之后 1,280 那一档它本来就让位成浮层了，
    前提会在第一行就红。下面那半（展开 ⇒ 让位 ⇒ ✕ 在场且关得掉）跟着 `_invoked` 那笔账走 ——
    上半那次 `open_overlay()` 就是"用户正在看这一栏"，让位时它不会凭空变没。
    """
    page = _page_at(window, qapp, "library", WINDOW_WIDTH_RIGHT_DOCKED, DEFAULT_WINDOW_HEIGHT)
    rp = page.right_panel
    assert rp.parent() is page.splitter and rp.isVisible(), \
        f"用例前提：{WINDOW_WIDTH_RIGHT_DOCKED}px 这一档右栏是常驻列"
    rp.open_overlay()
    _settle(qapp)
    assert rp.parent() is page.splitter and rp.width() == RIGHT_COLUMN_WIDTH, \
        "在常驻列上调 open_overlay() 却把它摘成了浮层 —— 开/关的出口必须只认 `_is_overlay()`"
    rp.close_overlay()
    _settle(qapp)
    assert rp.isVisible() and rp.parent() is page.splitter, \
        "宽档的常驻右栏被 close_overlay() 收走了 —— 这一档没有'关掉整栏'这回事，且再也回不来"

    # 展开左树 ⇒ 右栏放不下 ⇒ 它是浮层形状了：✕ 在场、真的关得掉。
    page.tree_panel.expand()
    _settle(qapp)
    assert rp.tight and rp.isVisible(), "用例前提：展开左树之后右栏让位成了开着浮层"
    assert rp.close_button.isVisible(), "浮层形状却没有 ✕ = 开了关不掉"
    rp.close_button.click()
    _settle(qapp)
    assert not rp.isVisible(), "让位成浮层之后 ✕ 没把它关掉"

    tp = page.tree_panel
    assert tp.isVisible() and not tp.close_button.isVisible(), "宽档常驻列不该有「✕」"
    tp.close_overlay()
    _settle(qapp)
    assert tp.isVisible() and tp.parent() is page.splitter and tp.width() == LEFT_COLUMN_WIDTH, \
        "宽档的常驻树列被 close_overlay() 收走了 —— 与右栏同一条早退，两栏都得守住"


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


# ---------------------------------------------------------------------------
# 轮五十八 ①：浮层必须自己画底（本文件唯一量像素的一条）
# ---------------------------------------------------------------------------


def _logical_rect(page, widget) -> QtCore.QRect:
    """把子控件的矩形换算到页面坐标系（取样要跨两个坐标系就必须只留一个口径）。"""
    top_left = page.mapFromGlobal(widget.mapToGlobal(QtCore.QPoint(0, 0)))
    return QtCore.QRect(top_left, widget.size())


def test_浮层覆盖区自己画底_不许透出底下的表格(window, ctx, qapp) -> None:
    """用户红框点名的第一处"显示 bug"：表格内容从面板**底下**透上来，与面板内容叠在一起。

    为什么这条量像素而其它条量几何：透明面板的 `geometry()` / `width()` / `isVisible()`
    **全都对** —— 毛病正好是"这一块画了什么"，只有取样颜色能判（真机 A/B：摘掉浮层后覆盖区
    **48.7%**（9,914 / 20,370）取样点颜色一模一样 ⇒ 那一片一个字也没画）。
    判据取浮层覆盖区里**不属于任何子控件**的取样点（面板自己的边距环与控件间隙），
    逐点必须等于面板底色令牌 `card_bg`；只要有一个点不是，那就是底下的东西透上来了。

    【2026-11-03 追记（**轮五十九 ②甲**）】宽档右栏改回常驻列之后，"浮层"这一形状只剩两处入口：
    窄档、以及宽档展开左树时的**让位**。让位是本轮新长出来的那条路径（`set_tight` → `_apply_shape`
    的浮层支），它要是透明，透出来的正好是用户红框 #1 那一片，所以两种形状各取一遍样。
    坏法注入实测（2026-11-03）：去掉 `ui/tier.py` 那行 `WA_StyledBackground` ⇒ 本条两档都红，
    红字报的是"不等于底色的点数"，而不是"面板不见了"（面板仍在场、几何仍对）。
    """
    _seed_docs(ctx, 12)
    page = _page_at(window, qapp, "library", MIN_WINDOW_WIDTH, MIN_WINDOW_HEIGHT)
    panel = page.right_panel
    expected = QtGui.QColor(window.theme.colors.card_bg)

    for shape in ("窄档浮层", "宽档让位"):
        if shape == "窄档浮层":
            window.resize(MIN_WINDOW_WIDTH, MIN_WINDOW_HEIGHT)
        else:
            window.resize(DEFAULT_WINDOW_WIDTH, DEFAULT_WINDOW_HEIGHT)
            page.tree_panel.expand()      # 展开左树 ⇒ 四件常驻件放不下 ⇒ 右栏让位成浮层
        _settle(qapp)
        assert panel._is_overlay(), f"用例前提：{shape} 这一档右栏得是浮层形状，否则量的是页面自己的底"
        panel.open_overlay()
        _settle(qapp)
        assert panel.isVisible() and panel.width() == tier.OVERLAY_WIDTH, \
            f"用例前提：{shape} 下右栏真的开着：w={panel.width()}"

        image = page.grab().toImage()
        ratio = image.width() / page.width()      # 高 DPI 下 grab 给的是设备像素
        covered = [_logical_rect(page, child) for child in panel.findChildren(QtWidgets.QWidget)
                   if child.isVisible()]
        rect = _logical_rect(page, panel)
        samples = 0
        mismatched: list[tuple[int, int, str]] = []
        for y in range(rect.top() + 2, rect.bottom(), 7):
            for x in range(rect.left() + 2, rect.right(), 7):
                if any(box.contains(QtCore.QPoint(x, y)) for box in covered):
                    continue
                samples += 1
                color = image.pixelColor(int(x * ratio), int(y * ratio))
                if color != expected:
                    mismatched.append((x, y, color.name()))
        assert samples >= 200, \
            f"{shape}：取样点只有 {samples} 个 —— 这条已经空转，判据落不到面板自己的底上"
        assert not mismatched, (
            f"{shape}：浮层覆盖区有 {len(mismatched)} / {samples} 个取样点不是面板底色 "
            f"{expected.name()}，露出来的是底下表格的东西（前 3 个点：{mismatched[:3]}）")
        panel.close_overlay()
        _settle(qapp)

