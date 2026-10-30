"""主题系统：浅色（Clean Minimal）+ 暗色（Professional Dark）双主题。

通过 QSS（Qt Style Sheet）实现全局样式，颜色令牌集中定义，
切换时重新生成 QSS 应用到 QApplication。主题偏好持久化到 app_settings。

**有一件事 QSS 做不到**：输入框占位文字的颜色。`QLineEdit::placeholder { color: … }`
是死选择器（填纯红 `#ff0000` 渲染回来 0 个红像素，实测见 **ISSUES I49**），Qt 取的是
`QPalette.PlaceholderText` 这个 role —— 所以它走 `ThemeManager.apply_palette()`，
**不在下面那段 QSS 字符串里**（**ISSUES I50**，用户勾乙）。
"""
from __future__ import annotations

from dataclasses import dataclass, field

from PySide6 import QtGui, QtWidgets


@dataclass(frozen=True)
class ThemeColors:
    """一套主题的颜色令牌。"""
    # 侧栏
    sidebar_bg: str
    sidebar_text: str
    sidebar_hover: str
    sidebar_active_bg: str
    sidebar_active_text: str
    sidebar_border: str

    # 内容区
    content_bg: str
    card_bg: str
    card_border: str

    # 文字
    text_primary: str
    text_secondary: str

    # 强调色
    accent: str
    accent_hover: str
    accent_light: str  # 浅色背景用（如选中行）
    # 以下两个与 `accent` 分开，是因为 accent（blue-500 #3b82f6）压白字只有 3.68:1、
    # 当小字颜色压在浅底上只有 3.31:1，都低于 13px 文字要求的 4.5:1。
    # accent 继续负责装饰性用色（选中左边条、复选框填充、标签下划线）。
    accent_text: str         # accent 当文字色时用（blue-600 / blue-300）
    btn_primary_bg: str      # 主按钮填充，上面永远压白字

    # 状态色
    danger: str

    # 表格
    table_header_bg: str
    table_header_text: str
    table_row_hover: str
    table_row_alt: str
    table_border: str
    table_grid: str

    # 输入框
    input_bg: str
    input_border: str
    input_focus_border: str

    # 按钮
    btn_bg: str
    btn_text: str
    btn_hover: str
    btn_border: str
    # 禁用态三件套。**为什么必须显式写出来**：QSS 一旦同时声明 `background-color` + `color`，
    # Qt 就不再拿调色板的 Disabled 组画字，禁用态与可用态在屏幕上长得一模一样
    # （实测两态直方图逐格相同，**ISSUES I74**）。字色这里不能复用 `text_secondary`：
    # 浅色下 `#6c757d` 压在任何灰底上都不过 AA（压 `#f8f9fa` 只有 4.45:1），
    # 所以浅色那档只能保持 `#495057`（压 `#e9ecef` 6.90:1），把"死掉"交给底色与描边承担。
    btn_disabled_bg: str
    btn_disabled_text: str
    btn_disabled_border: str

    # 状态栏
    status_bg: str
    status_text: str

    # 分割线
    splitter_handle: str

    # 树形控件
    tree_bg: str
    tree_hover: str

    # 滚动条
    scrollbar_bg: str
    scrollbar_handle: str
    scrollbar_handle_hover: str


LIGHT_THEME = ThemeColors(
    sidebar_bg="#f8f9fa",
    sidebar_text="#495057",
    sidebar_hover="#e9ecef",
    sidebar_active_bg="#ffffff",
    sidebar_active_text="#2563eb",
    sidebar_border="#e9ecef",
    content_bg="#ffffff",
    card_bg="#ffffff",
    card_border="#e9ecef",
    text_primary="#212529",
    text_secondary="#6c757d",
    accent="#3b82f6",
    accent_hover="#1d4ed8",
    accent_light="#eff6ff",
    accent_text="#2563eb",
    btn_primary_bg="#2563eb",
    danger="#dc3545",
    table_header_bg="#f8f9fa",
    table_header_text="#495057",
    table_row_hover="#f0f7ff",
    table_row_alt="#fafbfc",
    table_border="#e9ecef",
    table_grid="#f1f3f5",
    input_bg="#ffffff",
    input_border="#dee2e6",
    input_focus_border="#3b82f6",
    btn_bg="#ffffff",
    btn_text="#495057",
    btn_hover="#f1f3f5",
    btn_border="#dee2e6",
    btn_disabled_bg="#e9ecef",
    btn_disabled_text="#495057",
    btn_disabled_border="#dee2e6",
    status_bg="#f8f9fa",
    # 状态栏是 12px 小字。原先这里复用 text_secondary 的 #6c757d：压白底 4.69:1 过 AA，
    # 但压在本主题的状态栏底 #f8f9fa 上只有 **4.45:1**（AA 要 4.5）—— 同一个灰在两个底上
    # 结论不一样，所以单独降一档：#6a737b 在 #f8f9fa 上 4.58:1、在白底上 4.83:1。
    status_text="#6a737b",
    splitter_handle="#e9ecef",
    tree_bg="#ffffff",
    tree_hover="#f0f7ff",
    scrollbar_bg="#f1f3f5",
    scrollbar_handle="#ced4da",
    scrollbar_handle_hover="#adb5bd",
)


DARK_THEME = ThemeColors(
    sidebar_bg="#1e293b",
    sidebar_text="#e2e8f0",
    sidebar_hover="#334155",
    sidebar_active_bg="#2563eb",
    sidebar_active_text="#ffffff",
    sidebar_border="#334155",
    content_bg="#0f172a",
    card_bg="#1e293b",
    card_border="#334155",
    text_primary="#e2e8f0",
    text_secondary="#94a3b8",
    accent="#3b82f6",
    accent_hover="#1d4ed8",
    accent_light="#1e3a5f",
    accent_text="#93c5fd",
    btn_primary_bg="#2563eb",
    danger="#f87171",
    table_header_bg="#1e293b",
    table_header_text="#e2e8f0",
    table_row_hover="#334155",
    table_row_alt="#162032",
    table_border="#334155",
    table_grid="#283548",
    input_bg="#1e293b",
    input_border="#475569",
    input_focus_border="#3b82f6",
    btn_bg="#334155",
    btn_text="#e2e8f0",
    btn_hover="#475569",
    btn_border="#475569",
    btn_disabled_bg="#283548",
    btn_disabled_text="#94a3b8",
    btn_disabled_border="#334155",
    status_bg="#0f172a",
    status_text="#94a3b8",
    splitter_handle="#334155",
    tree_bg="#1e293b",
    tree_hover="#334155",
    scrollbar_bg="#1e293b",
    scrollbar_handle="#475569",
    scrollbar_handle_hover="#64748b",
)


class ThemeManager:
    """管理主题切换与 QSS 生成。"""

    LIGHT = "light"
    DARK = "dark"

    def __init__(self) -> None:
        self._theme = self.LIGHT
        self._colors = LIGHT_THEME

    @property
    def theme(self) -> str:
        return self._theme

    @property
    def colors(self) -> ThemeColors:
        return self._colors

    def set_theme(self, theme: str) -> None:
        if theme == self.DARK:
            self._theme = self.DARK
            self._colors = DARK_THEME
        else:
            self._theme = self.LIGHT
            self._colors = LIGHT_THEME

    def toggle(self) -> str:
        self.set_theme(self.DARK if self._theme == self.LIGHT else self.LIGHT)
        return self._theme

    #: 能显示占位文字的控件类型 —— 占位色必须逐控件设，见 `apply_palette`。
    PLACEHOLDER_WIDGETS = (QtWidgets.QLineEdit, QtWidgets.QPlainTextEdit,
                           QtWidgets.QTextEdit)

    def apply_palette(self, scope: QtWidgets.QWidget) -> None:
        """把**占位色**设进调色板 —— 这件事 QSS 做不到（见模块说明与 **ISSUES I50**）。

        **为什么是逐控件而不是主窗 / QApplication**：2026-10-17 数像素实测，role 设在主窗
        （父控件）和设在 `QApplication` 上都**不上屏** —— 祖先带了 QSS，Qt 就给子孙重建一份
        调色板，把外层继承盖掉；只有设在控件自身那一份才落屏（三种落点各填纯红 `#ff0000`，
        只有「控件自身」那例数得出 631 个红像素）。所以这里遍历 scope 的子树逐个设。
        不设的代价是 Qt 兜底：**正文字色 50% alpha 压在输入框底上**，浅色实测 `#909294` =
        **3.12:1**、暗色 `#808895` = **4.09:1**，两主题都不过 AA。

        **为什么 `QAbstractScrollArea` 还要多设一份 viewport**：`QPlainTextEdit` / `QTextEdit`
        设在控件自身的那一份**留不住** —— 实测「设了立刻读」是令牌色，一个 `processEvents()`
        之后就被按样式表重解析回 `#212529`；viewport 那一份才活到落屏（`QLineEdit` 没有
        viewport，所以对它只是多一次空操作）。

        复用 `text_secondary` 而不是再造一枚灰：占位文字与「次要说明文字」是同一个语义
        （弱化、但仍要读得清），再造一个令牌就是第二个口径。实测它压在 `input_bg` 上
        浅色 **4.69:1**、暗色 **5.71:1**（AA 线 4.5），而正文色是 **15.43:1** / **11.87:1**
        —— 差一个量级，所以「这是我填的」与「这是提示」分得开。
        取副本再改 role：直接新建一个 `QPalette()` 会把窗口其余 role 打回 Qt 默认值。
        """
        targets: list[QtWidgets.QWidget] = []
        for kind in self.PLACEHOLDER_WIDGETS:
            if isinstance(scope, kind):
                targets.append(scope)
            targets.extend(scope.findChildren(kind))
        role = QtGui.QPalette.ColorRole.PlaceholderText
        color = QtGui.QColor(self._colors.text_secondary)
        for widget in targets:
            sinks: list[QtWidgets.QWidget] = [widget]
            if isinstance(widget, QtWidgets.QAbstractScrollArea):
                sinks.append(widget.viewport())
            for sink in sinks:
                palette = sink.palette()
                palette.setColor(role, color)
                sink.setPalette(palette)

    def generate_qss(self) -> str:
        """生成全局 QSS 样式表。"""
        c = self._colors
        tooltip_bg = c.sidebar_bg if self._theme == self.LIGHT else "#334155"
        tooltip_text = c.text_primary if self._theme == self.LIGHT else "#e2e8f0"
        return f"""
/* ===== 全局 ===== */
QWidget {{
    background-color: {c.content_bg};
    color: {c.text_primary};
    font-family: "Microsoft YaHei UI", "Segoe UI", "PingFang SC", sans-serif;
    font-size: 13px;
}}

QMainWindow {{
    background-color: {c.content_bg};
}}

QMainWindow::separator {{
    background-color: {c.splitter_handle};
    width: 1px;
}}

/* ===== 容器/面板 ===== */
QFrame {{
    background-color: {c.content_bg};
}}
QScrollArea {{
    background-color: {c.content_bg};
    border: none;
}}

/* ===== 菜单栏 ===== */
QMenuBar {{
    background-color: {c.content_bg};
    color: {c.text_primary};
    border-bottom: 1px solid {c.card_border};
    padding: 2px 8px;
}}
QMenuBar::item:selected {{
    background-color: {c.sidebar_hover};
    border-radius: 4px;
}}
QMenu {{
    background-color: {c.card_bg};
    color: {c.text_primary};
    border: 1px solid {c.card_border};
    border-radius: 6px;
    padding: 4px;
}}
QMenu::item:selected {{
    background-color: {c.accent_light};
    color: {c.accent_text};
    border-radius: 4px;
}}

/* ===== 导航列表（侧栏） ===== */
QListWidget#navList {{
    background-color: {c.sidebar_bg};
    color: {c.sidebar_text};
    border: none;
    border-right: 1px solid {c.sidebar_border};
    outline: none;
    font-size: 13px;
}}
QListWidget#navList::item {{
    padding: 10px 16px 10px 20px;
    border-left: 3px solid transparent;
    border-bottom: none;
}}
QListWidget#navList::item:hover {{
    background-color: {c.sidebar_hover};
}}
QListWidget#navList::item:selected {{
    background-color: {c.sidebar_active_bg};
    color: {c.sidebar_active_text};
    border-left: 3px solid {c.accent};
    font-weight: 600;
}}

/* ===== 表格 =====
   轮四十二 ⑰：外圈描边去掉（表格自己的表头底线 + 网格线已经够分隔，
   再围一圈就是"每个格子都装在盒子里"的分割感）。 */
QTableWidget {{
    background-color: {c.card_bg};
    alternate-background-color: {c.table_row_alt};
    gridline-color: {c.table_grid};
    border: none;
    outline: none;
    selection-background-color: {c.accent_light};
    selection-color: {c.text_primary};
}}
QTableWidget::item {{
    padding: 6px 8px;
    border-bottom: 1px solid {c.table_grid};
    background-color: transparent;
}}
QTableWidget::item:hover {{
    background-color: {c.table_row_hover};
}}
QTableWidget::item:selected {{
    background-color: {c.accent_light};
}}
QHeaderView::section {{
    background-color: {c.table_header_bg};
    color: {c.table_header_text};
    padding: 8px 10px;
    border: none;
    border-bottom: 2px solid {c.table_border};
    border-right: 1px solid {c.table_grid};
    font-weight: 600;
    font-size: 12px;
}}
QHeaderView::section:last {{
    border-right: none;
}}
QTableCornerButton::section {{
    background-color: {c.table_header_bg};
    border: none;
    border-bottom: 2px solid {c.table_border};
    border-right: 1px solid {c.table_grid};
}}

/* ===== 树形控件 =====
   轮四十二 ⑰：同表格 —— 树常驻在 FloatablePanel 里，外面再描一圈就是双重框。 */
QTreeWidget {{
    background-color: {c.tree_bg};
    color: {c.text_primary};
    border: none;
    outline: none;
}}
QTreeWidget::item {{
    padding: 5px 4px;
    background-color: transparent;
}}
QTreeWidget::item:hover {{
    background-color: {c.tree_hover};
    border-radius: 4px;
}}
QTreeWidget::item:selected {{
    background-color: {c.accent_light};
    color: {c.accent_text};
    border-radius: 4px;
}}

/* ===== 分类标题轨（收成条的那 48px，**D-066** / 走查 ⑮ → 轮四十五 乙）=====
   钩子是 `ui/tier.py` 给条挂的 `objectName="treeRail"`；没有它，条只剩继承来的底色和
   splitter 边框，读起来是"另一栏"（实测：可点区只占 2.1%，剩下 97.9% 是死区）。
   底色取表头那一档（比正文底深一点）⇒ 条与它守着的树**同色**，中间只剩 1px 分割线，
   读起来就是"树收起来的样子"。字色用表头字/表头底那一对（浅色 7.76:1、暗色 11.87:1），
   悬停换成 accent 字压树悬停底（4.79:1 / 5.74:1），两主题都过 AA。
   `border-left` 静止时与底同色（不写 `transparent`：Qt 的 QSS 没有这个颜色关键字），
   悬停才亮出一条 accent 左边线 —— 这一栏能收回去，就得看得出按中了谁。 */
QWidget#treeRail {{
    background-color: {c.table_header_bg};
    border: none;
}}
QWidget#treeRail QToolButton {{
    background-color: {c.table_header_bg};
    color: {c.table_header_text};
    border: none;
    border-left: 3px solid {c.table_header_bg};
    font-size: 12px;
    padding: 6px 0;
}}
QWidget#treeRail QToolButton:hover {{
    background-color: {c.tree_hover};
    color: {c.accent_text};
    border-left: 3px solid {c.accent};
}}

/* ===== 列表控件 =====
   轮四十二 ⑰：同表格。命中面板/详情这类整栏列表不再自带描边。 */
QListWidget {{
    background-color: {c.card_bg};
    color: {c.text_primary};
    border: none;
    outline: none;
}}
QListWidget::item {{
    padding: 6px 8px;
    background-color: transparent;
}}
QListWidget::item:hover {{
    background-color: {c.table_row_hover};
    border-radius: 4px;
}}
QListWidget::item:selected {{
    background-color: {c.accent_light};
    border-radius: 4px;
}}

/* ===== 输入框 ===== */
QLineEdit {{
    background-color: {c.input_bg};
    color: {c.text_primary};
    border: 1px solid {c.input_border};
    border-radius: 6px;
    padding: 8px 12px;
    font-size: 13px;
    selection-background-color: {c.accent_light};
}}
QLineEdit:focus {{
    border: 1.5px solid {c.input_focus_border};
}}
/* 这里原来有一条 `QLineEdit::placeholder {{ color: … }}`，是**死选择器**：
   给它填纯红 #ff0000 渲染出来是 0 个红像素。占位文字其实按 Qt 的兜底画 ——
   **正文字色 50% alpha 混在输入框底上**（浅色实测 #909294 = 3.12:1、暗色 #808895 = 4.09:1，
   都不过 AA），等于一条永远不生效的声明。Qt 的占位色不走 QSS，走 `QPalette.PlaceholderText`
   —— 实现落在 `ThemeManager.apply_palette()`（**ISSUES I50** 乙，2026-10-17 已落地），
   所以这段字符串里**故意没有**占位相关的规则；哪天有人往这里加，它一样不会生效。 */

/* ===== 按钮 ===== */
QPushButton {{
    background-color: {c.btn_bg};
    color: {c.btn_text};
    border: 1px solid {c.btn_border};
    border-radius: 6px;
    padding: 7px 16px;
    font-size: 13px;
    min-height: 20px;
}}
QPushButton:hover {{
    background-color: {c.btn_hover};
    border-color: {c.accent};
    /* 悬停时不再把文字染成 accent：blue-500 压在 btn_hover 上只有 3.31:1（暗色 2.06:1）。
       背景与描边已经表达了悬停，文字回到 text_primary 两套主题都过线。 */
    color: {c.text_primary};
}}
QPushButton:pressed {{
    background-color: {c.accent_light};
}}
/* 「适应宽度」那颗是**可按下态**（轮四十七 甲-1）：开着 = 按下。按钮族此前只有 `:hover`／
   `:pressed`／`:disabled` 三档，没有 `:checked` —— 不补这一条，按下与松开在屏幕上逐格相同，
   而这一态存在的全部意义就是"看得出现在听谁的"。三个值全取现成令牌：accent_text 压 accent_light
   两主题实测 4.75／6.38（已在 `test_theme_contrast.live_pairs` 里量过），不新造第三种蓝。 */
QPushButton#fitWidthBtn:checked {{
    background-color: {c.accent_light};
    color: {c.accent_text};
    border: 1px solid {c.accent};
}}
QPushButton#searchBtn {{
    background-color: {c.btn_primary_bg};
    color: #ffffff;
    border: 1px solid {c.btn_primary_bg};
    font-weight: 600;
}}
QPushButton#searchBtn:hover {{
    background-color: {c.accent_hover};
    border-color: {c.accent_hover};
    color: #ffffff;
}}
QPushButton#clearBtn {{
    color: {c.text_secondary};
}}
/* ===== 禁用态（**ISSUES I74**）=====
   全项目 14 处 `setEnabled`，其中四处是**不可逆动作的门**（不输确认词 / 执行归档 /
   恢复备份 / 开始判重）。不补下面这几条，它们在屏幕上与可用态逐格相同 ——
   两态直方图实测相同这件事记在 **ISSUES I74** 的 证据 格里。 */
QPushButton:disabled {{
    background-color: {c.btn_disabled_bg};
    color: {c.btn_disabled_text};
    border: 1px solid {c.btn_disabled_border};
}}
/* 主按钮弱下去不退回普通灰，而是"褪色的蓝"：一眼看得出是那个蓝按钮死了，
   而不是它变成了一个次要按钮。accent_text 压 accent_light 两主题分别 4.75 / 6.38。 */
QPushButton#searchBtn:disabled {{
    background-color: {c.accent_light};
    color: {c.accent_text};
    border: 1px solid {c.input_border};
}}
/* `#fitWidthBtn:checked`（特异度 111）压得过 `QPushButton:disabled`（11）：不补这一条，
   那颗门被禁用时屏幕上仍是亮底 = 看着是开的。当前代码没有任何一处禁用它，这条守的是 Qt
   无条件的那句话 —— **显式写过 bg/color 就不拿调色板的 Disabled 组画**（**ISSUES I74** 机制面），
   由守卫 `test_接过调色板的按钮必须有disabled配对` 逐条点名。 */
QPushButton#fitWidthBtn:disabled {{
    background-color: {c.btn_disabled_bg};
    color: {c.btn_disabled_text};
    border: 1px solid {c.btn_disabled_border};
}}
/* id 选择器的优先级高于状态词（CSS2 特异度 101 > 10）：不写这一条，上面那条
   `QPushButton:disabled` 的 `color` 会被 `#clearBtn` 盖掉，禁用态字色还是压不住灰底的 #6c757d。 */
QPushButton#clearBtn:disabled {{
    color: {c.btn_disabled_text};
}}

/* ===== 筛选 chips（S1 顶栏那一排，**ISSUES I78** 乙）=====
   底取 card_bg 而不是再造一个"chip 专用灰"：chip 上的字是 `QLabel#muted`（= text_secondary），
   (text_secondary × card_bg) 与 (text_primary × card_bg) 两主题都在 `test_theme_contrast` 的
   live_pairs 里量过。再加一档只在某个底上才成立的灰，就是 **ISSUES I74** 那个"同一个色在两个底上
   结论不一样"的重演。 */
QFrame#filterChip {{
    background-color: {c.card_bg};
    border: 1px solid {c.card_border};
    border-radius: 9px;
}}
QToolButton#chipRemove {{
    color: {c.text_secondary};
    background-color: transparent;
    border: none;
    padding: 0 2px;
}}

/* S1 右栏的情境提示条（轮三十六 甲 · 乙）：底/边/角取已有的 `card_bg` / `card_border`
   （这对搭配已在 `live_pairs` 里量过两主题都过 AA），带上的字是 `QLabel#muted`。
   **只有 background-color 与 border、没有 color**，不新增任何字色搭配。 */
QFrame#ocrHintBand {{
    background-color: {c.card_bg};
    border: 1px solid {c.card_border};
    border-radius: 6px;
}}
/* S9 证据卡（轮三十七 丁）：与解释带/提示条同一族"一块说明"—— 同一套
   card_bg / card_border / 圆角，同样不写 color（卡上文字走默认与 muted，
   那两个配色已在 live_pairs 里量过）。 */
QFrame#evidenceCard {{
    background-color: {c.card_bg};
    border: 1px solid {c.card_border};
    border-radius: 6px;
}}
QToolButton#chipRemove:hover {{
    color: {c.text_primary};
}}

/* S1「上次读到」提示行（轮四十六）：它是一行**可以直接点的话**，不是一颗按钮。
   windowsvista 样式给 QToolButton 画了一圈边框（用户在真机截图里红框点出的那个框），
   `setAutoRaise(True)` 在原生样式下不管事 —— 与 `#chipRemove` 同一味药：显式抹平。
   只写 background 与 border，不写 color：字色仍走 QWidget 继承，不新增字色搭配。 */
QToolButton#lastReadHint {{
    background-color: transparent;
    border: none;
    padding: 0;
}}

/* ===== 复选框 ===== */
QCheckBox {{
    color: {c.text_secondary};
    spacing: 6px;
    font-size: 12px;
}}
QCheckBox::indicator {{
    width: 16px;
    height: 16px;
    border: 1.5px solid {c.input_border};
    border-radius: 3px;
    background-color: {c.input_bg};
}}
QCheckBox::indicator:checked {{
    background-color: {c.accent};
    border-color: {c.accent};
}}

/* ===== 单选钮 ===== */
/* 与复选框同一套尺寸与配色，只是指示器是圆的：S8 的「导出此分类清单…」弹层第一次用到
   `QRadioButton`（三种格式互斥），不写这一段就会落回平台默认的浅色圆圈，压在暗色卡片上。 */
QRadioButton {{
    color: {c.text_secondary};
    spacing: 6px;
    font-size: 12px;
}}
QRadioButton::indicator {{
    width: 16px;
    height: 16px;
    border: 1.5px solid {c.input_border};
    border-radius: 8px;
    background-color: {c.input_bg};
}}
QRadioButton::indicator:checked {{
    background-color: {c.accent};
    border-color: {c.accent};
}}

/* ===== 标签 ===== */
QLabel {{
    color: {c.text_primary};
    background-color: transparent;
}}
QLabel#sectionTitle {{
    font-size: 14px;
    font-weight: 700;
    color: {c.text_primary};
    padding: 4px 0 8px 0;
}}
/* 页面里要"弱化"或"报错"的文字挂 objectName，不要写死十六进制 ——
   写死的浅色灰（#6c757d/#666/#888）压在暗色卡片上只有 2.55~4.13:1，暗色主题下等于看不见。 */
QLabel#muted {{
    font-size: 12px;
    color: {c.text_secondary};
    padding: 2px 0;
}}
QLabel#danger {{
    font-size: 12px;
    color: {c.danger};
    padding: 2px 0;
}}

/* ===== 分割线 ===== */
QSplitter::handle {{
    background-color: {c.splitter_handle};
}}
QSplitter::handle:horizontal {{
    width: 1px;
}}
QSplitter::handle:vertical {{
    height: 1px;
}}

/* ===== 状态栏 ===== */
QStatusBar {{
    background-color: {c.status_bg};
    color: {c.status_text};
    border-top: 1px solid {c.card_border};
    font-size: 12px;
    padding: 4px 12px;
}}

/* ===== 标签页 ===== */
QTabWidget::pane {{
    border: 1px solid {c.card_border};
    border-radius: 6px;
    background-color: {c.card_bg};
}}
QTabBar::tab {{
    background-color: {c.content_bg};
    color: {c.text_secondary};
    border: 1px solid {c.card_border};
    border-bottom: none;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
    padding: 8px 16px;
    margin-right: 2px;
}}
QTabBar::tab:selected {{
    background-color: {c.card_bg};
    color: {c.text_primary};
    border-bottom: 2px solid {c.accent};
    font-weight: 600;
}}
QTabBar::tab:hover {{
    background-color: {c.table_row_hover};
    /* 换了底就必须同时换字色：未选中标签的字是 text_secondary，压在悬停底上
       浅色只有 4.34:1、暗色 4.04:1，两套主题都掉出 AA。形状照 `QPushButton:hover`
       ——背景与描边表达悬停，文字回到 text_primary（14.29:1 / 8.40:1）。 */
    color: {c.text_primary};
}}

/* ===== 滚动条 ===== */
QScrollBar:vertical {{
    background-color: {c.scrollbar_bg};
    width: 8px;
    border-radius: 4px;
    margin: 0;
}}
QScrollBar::handle:vertical {{
    background-color: {c.scrollbar_handle};
    border-radius: 4px;
    min-height: 30px;
}}
QScrollBar::handle:vertical:hover {{
    background-color: {c.scrollbar_handle_hover};
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
}}
QScrollBar:horizontal {{
    background-color: {c.scrollbar_bg};
    height: 8px;
    border-radius: 4px;
    margin: 0;
}}
QScrollBar::handle:horizontal {{
    background-color: {c.scrollbar_handle};
    border-radius: 4px;
    min-width: 30px;
}}
QScrollBar::handle:horizontal:hover {{
    background-color: {c.scrollbar_handle_hover};
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    width: 0;
}}

/* ===== 文本编辑区 =====
   轮四十二 ⑰：详情这类只读大块文本去描边（输入型 QTextEdit 一样走这条 ——
   输入框的可编辑线索由 QLineEdit 的描边承担，多行输入产品里还没有）。 */
QPlainTextEdit, QTextEdit {{
    background-color: {c.card_bg};
    color: {c.text_primary};
    border: none;
    padding: 8px;
    selection-background-color: {c.accent_light};
}}

/* ===== 分组框 ===== */
QGroupBox {{
    color: {c.text_secondary};
    border: 1px solid {c.card_border};
    border-radius: 8px;
    margin-top: 12px;
    padding-top: 16px;
    font-weight: 600;
    background-color: {c.card_bg};
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    padding: 0 8px;
    color: {c.text_primary};
}}

/* ===== 进度条 ===== */
QProgressBar {{
    background-color: {c.content_bg};
    border: 1px solid {c.card_border};
    border-radius: 4px;
    text-align: center;
    color: {c.text_primary};
}}
QProgressBar::chunk {{
    background-color: {c.accent};
    border-radius: 3px;
}}

/* ===== 工具提示 ===== */
QToolTip {{
    background-color: {tooltip_bg};
    color: {tooltip_text};
    border: 1px solid {c.card_border};
    border-radius: 4px;
    padding: 6px 10px;
    font-size: 12px;
}}
"""
