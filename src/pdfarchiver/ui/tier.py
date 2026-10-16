"""**D-040 / D-039** 的降级机械 —— 一条规则，不是每屏各写一遍。

定案的形状来自两处文档，用的是同一把尺子：

- `docs/UI-WIREFRAMES.md` §S1「1024×720 的降级」+ **D-040**：
  `左树 236 + 中列表 ≥480 + 命中面板 ≥360 = 1076 > 1024` ⇒ 三栏放不下，
  **必须且只牺牲右栏** —— 命中/详情面板变浮层（420px，可关），左树收成 48px 的条，
  中列表吃掉剩下的宽度。
- `docs/DECISIONS.md` **D-039** 尺寸段（同一句在 `docs/UI-SCREENS.md` 第 113 行）：
  「**1024 档必须收起 S8 的树侧栏**，这一条写成界面断言」。

所以命中这一类的现有屏是 **S1**（左分类树 + 右详情）与 **S8**（左分类树），
它们共用下面这一个 `FloatablePanel`，而不是各屏再抄一遍 `resizeEvent`。
AGENTS.md「禁止同类问题逐个打补丁 —— 发现一类先问还有哪些地方是同类」是这里的直接理由：
两份手抄的切档代码一旦阈值漂了，差别只在某个用户把窗口拖窄的那一刻才看得见。

形状约定（都可在测试里断言）：
- 判档只有一个比较：`host_width < THREE_COLUMN_MIN_WIDTH`；
- 收起 = 面板**从 splitter 里摘出来、挂到页面上当浮层**。浮层不参与布局 ⇒ 永远不会
  把 `minimumSizeHint` 顶宽，窗口拖不到 D-039 地板以下；
- 浮层**默认关**、**可关**（D-040 代价段：「开/关状态可断言，不记忆成每次都开」）；
- 一块 host 上**同时只开一个浮层** —— 线框只给了一个浮层的位置（列表右侧 420px），
  两个叠在一起会让下面那个变成"关不掉的透明层"。
"""
from __future__ import annotations

from PySide6 import QtWidgets

# 线框 §S1 的算术原式。比较的是**页面自己的宽度**（外壳已经扣掉导航），不是窗口宽度 ——
# 窗口口径在 `main_window.MIN_WINDOW_WIDTH`，这里再减一次 200 就变成第二个口径。
LEFT_COLUMN_WIDTH = 236
CENTER_MIN_WIDTH = 480
RIGHT_COLUMN_WIDTH = 360
THREE_COLUMN_MIN_WIDTH = LEFT_COLUMN_WIDTH + CENTER_MIN_WIDTH + RIGHT_COLUMN_WIDTH  # 1076

TREE_STRIP_WIDTH = 48      # D-040 的"图标条 48px"
OVERLAY_WIDTH = 420        # D-040 的"覆盖在列表右侧 420px，可关"


class FloatablePanel(QtWidgets.QWidget):
    """一块面板：宽档待在 splitter 里占一槽，窄档变成页面上的浮层。

    `strip_label` 非空时另带一条 48px 的替身条，它**一直挂在 splitter 里**、宽档隐藏
    （QSplitter 给隐藏项 0 宽），所以切换只改父对象和可见性，不在两个控件之间搬东西。
    条上那颗按钮是浮层的入口，面板顶栏那颗「✕ 关闭」是出口。

    面板内容只有一份：复制一份控件就等于把同一份读数写进两个地方 ——
    **D-040** 第三条后果在 S7 上刚犯过一次（状态读数被抄了两遍），这里不重犯。
    """

    def __init__(self, host: QtWidgets.QWidget, title: str, *,
                 column_width: int, strip_label: str = "",
                 overlay_width: int = OVERLAY_WIDTH) -> None:
        super().__init__()
        self.host = host
        self.column_width = column_width
        self.overlay_width = overlay_width
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
        self.body.setContentsMargins(8, 8, 8, 8)
        head = QtWidgets.QHBoxLayout()
        label = QtWidgets.QLabel(title)
        label.setObjectName("sectionTitle")
        head.addWidget(label)
        head.addStretch(1)
        self.close_button = QtWidgets.QToolButton()
        self.close_button.setText("✕ 关闭")
        self.close_button.setToolTip(f"收起「{title}」浮层（窄档这一栏不常驻）")
        self.close_button.clicked.connect(self.close_overlay)
        # 宽档它是常驻栏，没有"关掉整栏"这回事 —— 「可关」是 D-040 给浮层写的形状。
        self.close_button.setVisible(False)
        self.body.addLayout(head)

        self.strip: QtWidgets.QWidget | None = None
        if strip_label:
            self.strip = QtWidgets.QWidget()
            strip_lay = QtWidgets.QVBoxLayout(self.strip)
            strip_lay.setContentsMargins(2, 8, 2, 8)
            button = QtWidgets.QToolButton()
            button.setText(strip_label)
            button.setToolTip(f"展开「{title}」（窄档把这一栏收成这一条）")
            button.clicked.connect(self.open_overlay)
            strip_lay.addWidget(button)
            strip_lay.addStretch(1)
            self.strip.setFixedWidth(TREE_STRIP_WIDTH)
            self.strip.setVisible(False)

    def attach(self, splitter: QtWidgets.QSplitter) -> None:
        """宽档形状：条（若有）排在面板前面，两者都进 splitter。"""
        self._splitter = splitter
        if self.strip is not None:
            splitter.addWidget(self.strip)
        splitter.addWidget(self)
        self._index = splitter.indexOf(self)

    def set_narrow(self, narrow: bool) -> bool:
        """切档。返回是否真的变了档（没变就不该重推 splitter 尺寸）。"""
        if narrow == self.narrow:
            return False
        self.narrow = narrow
        if narrow:
            # PySide6 6.8 的 QSplitter 没有 removeWidget；`setParent(host)` 本身就会经
            # ChildRemoved 把它从 splitter 里摘掉（实测 count 3→2）。
            self.setParent(self.host)
            self.setFixedWidth(self.overlay_width)
            if self.strip is not None:
                self.strip.setVisible(True)
            self.close_button.setVisible(True)
            self.setVisible(False)     # 默认关：不记忆成"每次都开"
        else:
            self.setMinimumWidth(0)
            self.setMaximumWidth(self._default_max_width)
            if self.strip is not None:
                self.strip.setVisible(False)
            self.close_button.setVisible(False)
            # 第一次切到宽档时它本来就在 splitter 里（`attach` 放进去的），别重复插。
            if self.parent() is not self._splitter:
                self._splitter.insertWidget(self._index, self)
            self.setVisible(True)
        return True

    def place(self) -> None:
        """贴在页面右沿；不参与布局，所以位置只能自己算。"""
        if not self.narrow or not self.isVisible():
            return
        height = self._splitter.height() if self._splitter else self.host.height()
        self.setGeometry(max(0, self.host.width() - self.overlay_width),
                         0, self.overlay_width, height)
        self.raise_()

    def open_overlay(self) -> None:
        if not self.narrow:
            return
        # findChildren 只找得到已经挂到 host 上的浮层（宽档时它们是 splitter 的子），
        # 收口成一个调用点，省掉"每屏记得互相登记"这条容易漏的约定。
        for other in self.host.findChildren(FloatablePanel):
            if other is not self:
                other.setVisible(False)
        self.setVisible(True)
        self.place()

    def close_overlay(self) -> None:
        self.setVisible(False)


def sync_tier(splitter: QtWidgets.QSplitter, panels: list[FloatablePanel],
              host_width: int) -> None:
    """按页面宽度切档，并把 splitter 的尺寸推到当前档该有的形状。

    `host_width == 0` 直接返回：构造时 `width()` 还是 0，拿它判档会凭一个假宽度把
    常驻栏凭空摘走（实测过：窗口没 resize 前页面就布局了一轮 0 宽）。
    """
    if host_width <= 0:
        return
    narrow = host_width < THREE_COLUMN_MIN_WIDTH
    switched = [panel.set_narrow(narrow) for panel in panels]
    if any(switched):
        splitter.setSizes(_tier_sizes(splitter, panels, host_width, narrow))
    for panel in panels:
        panel.place()


def _tier_sizes(splitter: QtWidgets.QSplitter, panels: list[FloatablePanel],
                host_width: int, narrow: bool) -> list[int]:
    """每一槽该多宽：收起的栏换成 48px 的条，常驻列平分剩下的宽度。

    窄档只剩一条常驻列时（S1 的中列表），"平分"就正好是 D-040 那句「中列表吃掉剩余」。
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
            widths.append(TREE_STRIP_WIDTH if narrow else 0)
        else:
            widths.append(0 if narrow else panel.column_width)
    if flex:
        share = max(0, host_width - sum(widths)) // len(flex)
        for i in flex:
            widths[i] = share
    return widths
