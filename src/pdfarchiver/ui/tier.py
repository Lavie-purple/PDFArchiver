"""**D-040 / D-039** 的降级机械 —— 一条规则，不是每屏各写一遍。

定案的形状来自两处文档，用的是同一把尺子：

- `docs/UI-WIREFRAMES.md` §S1「1024×720 的降级」+ **D-040**：
  `左树 236 + 中列表 ≥480 + 命中面板 ≥360 = 1076 > 1024` ⇒ 三栏放不下，
  **必须且只牺牲右栏** —— 命中/详情面板变浮层（420px，可关），左树收成 48px 的条，
  中列表吃掉剩下的宽度。
- `docs/DECISIONS.md` **D-039** 尺寸段（同一句在 `docs/UI-SCREENS.md` 第 113 行）：
  「**1024 档必须收起 S8 的树侧栏**，这一条写成界面断言」。

所以命中这一类的现有屏是 **S1**（左分类树）与 **S8**（左分类树），
它们共用下面这一个 `FloatablePanel`，而不是各屏再抄一遍 `resizeEvent`。
AGENTS.md「禁止同类问题逐个打补丁 —— 发现一类先问还有哪些地方是同类」是这里的直接理由：
两份手抄的切档代码一旦阈值漂了，差别只在某个用户把窗口拖窄的那一刻才看得见。

形状约定（都可在测试里断言）：
- 判档只有一个比较：`host_width < THREE_COLUMN_MIN_WIDTH`；
- 收起 = 面板**从 splitter 里摘出来、挂到页面上当浮层**。浮层不参与布局 ⇒ 永远不会
  把 `minimumSizeHint` 顶宽，窗口拖不到 D-039 地板以下；
- 浮层**默认关**、**可关**（D-040 代价段：「开/关状态可断言，不记忆成每次都开」）；
- 一块 host 上**同时只开一个浮层** —— 线框只给了一个浮层的位置（列表右侧 420px），
  两个叠在一起会让下面那个变成"关不掉的透明层"；
- `docked=False` 的面板**两档都是浮层**：不进 splitter、默认关，命中时机到了才开
  （轮四十二 ⑭：S1 右栏不再常驻占一栏）。它不吃档位判定，`set_narrow` 恒 False。

走查清单 **⑮** 又往前一步（**D-066** 取消 **D-064** 留给左树的那条"宽档常驻"例外）：带条的
左树**宽档也默认收成 48px**。判据是 2026-10-30 只读实测真库 —— `documents` 14,190 行、
`document_categories` **0 行**、`categories` 14 行，236px 一栏常年守着一棵没挂过文档的树。
`collapsible=True` 的面板宽档起始就是条，点条展开成 **D-040 原样的 236px 常驻列**，再点收
回去；条在展开态也留在场，它就是那颗收回的把手（宽档展开时没有「✕」，`close_overlay()`
对常驻列仍然早退 —— 轮三十九那条牙不动）。
窄档的形状与开关完全没变：条 → 420px 浮层 → 「✕」关。

轮四十五 乙 给这根条定身份（走查 ⑮ 落地后的实测：条 48×875、可点的只有顶上那颗 44×20 的
按钮 ⇒ 97.9% 是死区；且条没有 objectName，外观全靠 splitter 边框，读起来是"另一栏"）：
条从此是**标题轨** —— 按钮撑满整根（竖排「▸ 分类 14」，可点区 2.1% → ~100%）、挂
`objectName="treeRail"` 由 `theme.py` 给它自己的底色与 hover 左边线、上面带**分类计数**，
于是"一篇都没归类"那颗圆点恒灭时，轨上也有一句答得上话的东西。

轮四十五 丙 把 S8 从 `collapsible` 里摘出去：⑮ 那条实测说的是 **S1 的筛选**场景（14 个默认
分类零篇挂载），S8 是**管理**场景，那棵树正是这一屏要编辑的主对象 —— 默认藏起来是语义错放。
**D-066** 那句"没有布局例外"随之改成按角色判定，定案写在 **D-067**（`docs/DECISIONS.md`）。
"""
from __future__ import annotations

from PySide6 import QtCore, QtWidgets

# 线框 §S1 的算术原式。比较的是**页面自己的宽度**（外壳已经扣掉导航），不是窗口宽度 ——
# 窗口口径在 `main_window.MIN_WINDOW_WIDTH`，这里再减一次 200 就变成第二个口径。
LEFT_COLUMN_WIDTH = 236
CENTER_MIN_WIDTH = 480
RIGHT_COLUMN_WIDTH = 360
THREE_COLUMN_MIN_WIDTH = LEFT_COLUMN_WIDTH + CENTER_MIN_WIDTH + RIGHT_COLUMN_WIDTH  # 1076

TREE_STRIP_WIDTH = 48      # D-040 的"图标条 48px"
OVERLAY_WIDTH = 420        # D-040 的"覆盖在列表右侧 420px，可关"

# 浮层顶部要给右上角那颗「✕」让位，正文上边距比常驻列多留一截。
_OVERLAY_TOP_MARGIN = 32
_DOCKED_TOP_MARGIN = 8


class FloatablePanel(QtWidgets.QWidget):
    """一块面板：宽档待在 splitter 里占一槽，窄档变成页面上的浮层。

    `strip_label` 非空时另带一条 48px 的替身条，它**一直挂在 splitter 里**、宽档隐藏
    （QSplitter 给隐藏项 0 宽），所以切换只改父对象和可见性，不在两个控件之间搬东西。
    条上那颗按钮是浮层的入口，面板右上角那颗「✕」是出口；关掉时发 `closed`，
    调用方用它区分"用户亲手关了"与"从来没开过"。

    带条的面板就是**标题轨**（轮四十五 乙）：`objectName="treeRail"`、按钮撑满整根、
    文字竖排成「箭头 + 标签逐字 + 计数」。它同时是标题和把手，两个身份都由同一颗按钮承担 ——
    分成两个控件就等于把"这一栏叫什么"再抄一遍，而且展开态那条 48px 会重新变成死区。

    面板内容只有一份：复制一份控件就等于把同一份读数写进两个地方 ——
    **D-040** 第三条后果在 S7 上刚犯过一次（状态读数被抄了两遍），这里不重犯。

    轮四十二 乙：标题行整行删掉（原来那行 `QLabel` 从构造起就没 `setText`，
    只在 tooltip 里有字，却一直占着一格高 —— 用户红框 #1 的空带）。

    `collapsible=True`（**D-066** / ⑮，只对"带条的常驻列"生效）把宽档的起始形状改成条：
    形状只有 `(narrow, collapsed)` 两个输入，全走 `_apply_shape()` 这一个出口。
    """

    closed = QtCore.Signal()

    def __init__(self, host: QtWidgets.QWidget, title: str, *,
                 column_width: int, strip_label: str = "",
                 overlay_width: int = OVERLAY_WIDTH,
                 docked: bool = True, collapsible: bool = False) -> None:
        super().__init__()
        self.host = host
        self._title = title
        self.column_width = column_width
        self.overlay_width = overlay_width
        self.docked = docked
        # 收起态只在"带条的常驻列"上说得通：没有条就没有把手，非常驻列本来就是浮层。
        self.collapsible = bool(collapsible and docked and strip_label)
        self.collapsed = self.collapsible
        # `setFixedWidth` 同时改 min 和 max，回宽档要恢复的就是这两个默认值。这里记下构造时
        # 的默认上限，而不是硬写 `QWIDGETSIZE_MAX` —— PySide6 6.8 的 `QtWidgets` 里**没有**
        # 这个常量（实测 AttributeError），而它一旦被写进一个 Qt 虚函数调用链里，异常会被
        # Qt 吞掉、只留下"分档没生效"的症状（上一轮 S1 的宽档定宽就是这么静默没落地的）。
        self._default_max_width = self.maximumWidth()
        # None = 还没切过档。构造时 `width()` 是 0，第一个真实宽度必须**无论宽窄都算一次
        # 切换**，否则 `sync_tier` 不会推尺寸，宽档就停在 Qt 自己按 sizeHint 分的那份上
        # （实测停在 272/533/272，而不是 D-040 要的 236/481/360 —— 定宽没落地）。
        self.narrow: bool | None = None
        self._splitter: QtWidgets.QSplitter | None = None
        self._index = -1

        self.body = QtWidgets.QVBoxLayout(self)
        self.body.setContentsMargins(8, _DOCKED_TOP_MARGIN, 8, 8)

        # 「✕」不进 body：它是面板自己的角标，位置在 resizeEvent 里钉在右上角。
        # 显式挂父（构造时给 self）—— 轮三十九的孤儿顶层窗就是漏挂父爆出来的。
        self.close_button = QtWidgets.QToolButton(self)
        self.close_button.setText("✕")
        self.close_button.setToolTip(f"收起「{title}」浮层（这一栏不常驻）")
        self.close_button.clicked.connect(self.close_overlay)
        # 常驻列没有"关掉整栏"这回事 —— 「可关」是 D-040 给浮层写的形状。
        self.close_button.setVisible(False)

        self.strip: QtWidgets.QWidget | None = None
        self.strip_button: QtWidgets.QToolButton | None = None
        self.strip_dot: QtWidgets.QLabel | None = None
        self._strip_label = strip_label
        self._strip_count: int | None = None
        if docked and strip_label:
            self.strip = QtWidgets.QWidget()
            # 这条 objectName 是给 theme.py 那段 QSS 的钩子（`QWidget#treeRail`）。
            # 裸 QWidget 不吃样式表的背景，得显式开 WA_StyledBackground。
            self.strip.setObjectName("treeRail")
            self.strip.setAttribute(QtCore.Qt.WidgetAttribute.WA_StyledBackground, True)
            strip_lay = QtWidgets.QVBoxLayout(self.strip)
            strip_lay.setContentsMargins(0, 0, 0, 6)
            strip_lay.setSpacing(0)
            self.strip_button = QtWidgets.QToolButton()
            self.strip_button.setText(self._rail_text())
            # 撑满整根条：原先它只占顶上那颗 44×20，条 97.9% 的面积点不动（轮四十五 乙 的实测）。
            self.strip_button.setSizePolicy(
                QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Expanding)
            self.strip_button.clicked.connect(self._on_strip_clicked)
            strip_lay.addWidget(self.strip_button, 1)
            # 收成条之后这一栏只剩一颗按钮，小圆点是"里头有东西可看"的唯一线索（⑮ 原话）。
            # 构造时显式挂父（同一批孤儿按钮的教训），再进布局。
            self.strip_dot = QtWidgets.QLabel("●", self.strip)
            self.strip_dot.setToolTip(f"「{title}」里有内容")
            self.strip_dot.setAlignment(QtCore.Qt.AlignmentFlag.AlignHCenter)
            self.strip_dot.setVisible(False)
            strip_lay.addWidget(self.strip_dot)
            self.strip.setFixedWidth(TREE_STRIP_WIDTH)
            self.strip.setVisible(False)

        if not docked:
            # 两档都是浮层：定宽、开浮层样式、默认关（`attach` 时挂到 host 上）。
            self.setFixedWidth(self.overlay_width)
            self._apply_overlay_style(True)

    # ---- 形状 ----

    def _apply_overlay_style(self, on: bool) -> None:
        self.body.setContentsMargins(
            8, _OVERLAY_TOP_MARGIN if on else _DOCKED_TOP_MARGIN, 8, 8)
        self.close_button.setVisible(on)

    def _is_overlay(self) -> bool:
        """此刻是不是以浮层形状活着（非常驻列恒是；常驻列只在窄档是）。"""
        return not self.docked or bool(self.narrow)

    def _wants_strip(self) -> bool:
        """条在不在场：窄档必须在（它是浮层唯一的入口）；宽档只有可收栏留着当把手。"""
        return self.strip is not None and (bool(self.narrow) or self.collapsible)

    def _strip_hint(self) -> str:
        if self.narrow:
            return f"展开「{self._title}」（窄档把这一栏收成这一条）"
        return f"{'展开' if self.collapsed else '收起'}「{self._title}」"

    def _rail_text(self) -> str:
        """轨上那句竖排字：箭头 + 标签逐字 + 计数（「▸ / 分 / 类 / 14」）。

        48px 的宽放不下横排两字，竖排是这一档唯一的排法；箭头按状态翻，
        收起时朝右（点开它）、展开时朝左（点它收回）。计数让轨在**一篇都没归类**时
        也有话可说 —— 那时那颗小圆点恒灭，光靠它这一栏就等于没标签。
        """
        arrow = "▸" if (self.narrow or self.collapsed) else "◂"
        lines = [arrow, *self._strip_label]
        if self._strip_count is not None:
            lines.append(str(self._strip_count))
        return "\n".join(lines)

    def attach(self, splitter: QtWidgets.QSplitter) -> None:
        """常驻列的宽档形状：条（若有）排在面板前面，两者都进 splitter。

        `docked=False` 的面板不进 splitter —— `setParent(host)` 挂到页面上当纯浮层，
        默认关；它不影响 splitter 的槽数与 `minimumSizeHint`。
        """
        self._splitter = splitter
        if not self.docked:
            self.setParent(self.host)
            self.setVisible(False)
            return
        if self.strip is not None:
            splitter.addWidget(self.strip)
        splitter.addWidget(self)
        self._index = splitter.indexOf(self)
        if self.collapsible:
            # 起始就该是"收成条"：不等第一次 resize，否则 236px 常驻列会闪一下再消失。
            self._apply_shape()

    def _apply_shape(self) -> None:
        """把 `(narrow, collapsed)` 这一对状态落成正好一种形状 —— 唯一出口。

        三个分支互斥，所以"切档"与"收/放"走的是同一段代码：各写一遍就是 **D-040**
        第三条后果（同一份读数抄两处）的老路，而且槽宽算式会跟着漂。
        """
        if self.strip is not None:
            self.strip.setVisible(self._wants_strip())
            self.strip_button.setToolTip(self._strip_hint())
            # 箭头跟着形状翻：收起/窄档朝右（点开它），宽档展开态朝左（点它收回）。
            self.strip_button.setText(self._rail_text())
        if self.narrow:
            # PySide6 6.8 的 QSplitter 没有 removeWidget；`setParent(host)` 本身就会经
            # ChildRemoved 把它从 splitter 里摘掉（实测 count 3→2）。
            if self.parent() is not self.host:
                self.setParent(self.host)
            self.setFixedWidth(self.overlay_width)
            self._apply_overlay_style(True)
            self.setVisible(False)     # 默认关：不记忆成"每次都开"
        elif self.collapsed:
            # 宽档收成条（**D-066** / ⑮）：同样摘出来藏好，条就是唯一入口。
            # 定宽留着不动 —— 这一档它不参与布局，展开时下面那支会清掉。
            if self.parent() is not self.host:
                self.setParent(self.host)
            self.setVisible(False)
        else:
            self.setMinimumWidth(0)
            self.setMaximumWidth(self._default_max_width)
            self._apply_overlay_style(False)
            # 第一次切到宽档时它本来就在 splitter 里（`attach` 放进去的），别重复插。
            if self._splitter is not None and self.parent() is not self._splitter:
                self._splitter.insertWidget(self._index, self)
            self.setVisible(True)

    def set_narrow(self, narrow: bool) -> bool:
        """切档。返回是否真的变了档（没变就不该重推 splitter 尺寸）。"""
        if not self.docked:
            return False
        if narrow == self.narrow:
            return False
        self.narrow = narrow
        self._apply_shape()
        return True

    def expand(self) -> None:
        """宽档把这一栏放回 splitter 当 236px 常驻列（**D-040** 原本的宽档形状）。"""
        if not self.collapsible or self.narrow or not self.collapsed:
            return
        self.collapsed = False
        self._apply_shape()
        self._push_sizes()

    def collapse(self) -> None:
        if not self.collapsible or self.narrow or self.collapsed:
            return
        self.collapsed = True
        self._apply_shape()
        self._push_sizes()

    def _push_sizes(self) -> None:
        """收/放之后把 splitter 各槽推回这一档该有的宽度。

        面板自己推：槽宽算式在 `_tier_sizes` 一处，让每屏再连一个信号去调它 = 第二个口径。
        """
        if self._splitter is None or self.host.width() <= 0:
            return
        panels = [p for p in self.host.findChildren(FloatablePanel) if p.docked]
        self._splitter.setSizes(_tier_sizes(self._splitter, panels, self.host.width()))

    def set_strip_dot(self, has_content: bool) -> None:
        """条上那颗小圆点：收成条时替用户回答"这一栏里现在有没有东西可看"。"""
        if self.strip_dot is not None:
            self.strip_dot.setVisible(bool(has_content))

    def set_strip_count(self, count: int) -> None:
        """轨上那句计数（轮四十五 乙）：分类有几类。

        由页面在**重查树的那一处**传进来（`len(category_tree())` 的现成结果），不在这里
        查第二遍 —— 同一份读数抄两处就是 **D-040** 那条老路。计数与那颗圆点回答的不是
        同一个问题：圆点问"归过类吗"，计数问"有几类可归"，后者在零篇归类时照样有话可说。
        """
        if self.strip_button is not None and count != self._strip_count:
            self._strip_count = int(count)
            self.strip_button.setText(self._rail_text())

    def place(self) -> None:
        """贴在页面右沿；不参与布局，所以位置只能自己算。"""
        if not self.isVisible():
            return
        if not self._is_overlay():
            return
        height = self._splitter.height() if self._splitter else self.host.height()
        self.setGeometry(max(0, self.host.width() - self.overlay_width),
                         0, self.overlay_width, height)
        self.raise_()

    def resizeEvent(self, event: QtCore.QEvent) -> None:  # noqa: N802 - Qt 命名
        super().resizeEvent(event)
        # 「✕」钉在右上角：面板宽随浮层/常驻两档变，手动定位只能跟着 resize 走。
        self.close_button.adjustSize()
        self.close_button.move(self.width() - self.close_button.width() - 8, 6)

    # ---- 开关 ----

    def _on_strip_clicked(self) -> None:
        """条上那颗按钮：窄档仍是浮层入口（D-040 原样，出口是浮层自己的「✕」）；
        宽档的可收栏拿它当"收/放"把手 —— 点一下展开成常驻列，再点收回成条（**D-066**）。
        """
        if self.docked and not self.narrow:
            if self.collapsed:
                self.expand()
            else:
                self.collapse()
            return
        self.open_overlay()

    def open_overlay(self) -> None:
        if self.docked and not self.narrow:
            # 宽档没有"浮层"这一说：可收栏的"开"就是展开成常驻列，不可收的常驻列
            # 本来就开着 —— 与原来的早退等价。
            self.expand()
            return
        # findChildren 只找得到已经挂到 host 上的浮层（常驻宽档时它们是 splitter 的子），
        # 收口成一个调用点，省掉"每屏记得互相登记"这条容易漏的约定。
        # 只摘**此刻是浮层**的同伴：常驻列被误 setVisible(False) 会收起且回不来。
        for other in self.host.findChildren(FloatablePanel):
            if other is not self and other._is_overlay():
                other.setVisible(False)
        self.setVisible(True)
        self.place()

    def close_overlay(self) -> None:
        """常驻列不可关（与 `open_overlay()` 对称地早退）：误调用一次就把常驻列收起且
        **再也回不来** —— `set_narrow()` 只在真的换档时才 `setVisible(True)`。
        宽档要收这一栏走的是条上那颗按钮（`collapse()`），不是这颗「✕」。

        真正关掉浮层时发 `closed`：调用方（S1 右栏）据此记住"用户亲手关了"，
        后续选中文档不再自动把它唤出来。
        """
        if self.docked and not self.narrow:
            return
        self.setVisible(False)
        self.closed.emit()


def sync_tier(splitter: QtWidgets.QSplitter, panels: list[FloatablePanel],
              host_width: int) -> None:
    """按页面宽度切档，并把 splitter 的尺寸推到当前档该有的形状。

    `host_width == 0` 直接返回：构造时 `width()` 还是 0，拿它判档会凭一个假宽度把
    常驻栏凭空摘走（实测过：窗口没 resize 前页面就布局了一轮 0 宽）。
    `docked=False` 的面板不吃档位（`set_narrow` 恒 False），但 `place()` 照走 ——
    它开着的时候窗口变宽变窄都得跟着贴右沿。
    """
    if host_width <= 0:
        return
    narrow = host_width < THREE_COLUMN_MIN_WIDTH
    switched = [panel.set_narrow(narrow) for panel in panels]
    if any(switched):
        splitter.setSizes(_tier_sizes(splitter, panels, host_width))
    for panel in panels:
        panel.place()


def _tier_sizes(splitter: QtWidgets.QSplitter, panels: list[FloatablePanel],
                host_width: int) -> list[int]:
    """每一槽该多宽：在场的条给 48px，常驻列给它的定宽，其余槽平分剩下的宽度。

    档位与"用户此刻收没收起"都从面板自己读，不再传一个全局 `narrow` 进来 —— 那会变成
    第二个口径：宽档收成条时面板压根不在 splitter 里，而条要占 48px。
    只剩一条常驻列时（S1 的中列表），"平分"就正好是 D-040 那句「中列表吃掉剩余」。
    """
    widths: list[int] = []
    flex: list[int] = []
    for i in range(splitter.count()):
        widget = splitter.widget(i)
        panel = next((p for p in panels if widget is p or widget is p.strip), None)
        if panel is None:
            flex.append(i)
            widths.append(0)
        elif widget is panel.strip:
            widths.append(TREE_STRIP_WIDTH if panel._wants_strip() else 0)
        else:
            widths.append(panel.column_width)
    if flex:
        share = max(0, host_width - sum(widths)) // len(flex)
        for i in flex:
            widths[i] = share
    return widths
