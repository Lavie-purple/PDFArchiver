"""一行按钮的**行末那格** —— 宽屏时把「这屏已经有的一句读数」搬进来，装不下就留在原位（**ISSUES I121** ④）。

线框 `docs/wireframes/2026-10-31-round47-fit-width-action-rows.html` §2 乙-1、§4 Q3 乙-1 /
Q4 甲 / Q5 甲 / Q6 甲 定案（2026-10-31「都按你推荐来」）。五条行：S3 底部按钮行 / S4 按钮行 /
S5 ① 段工具行 / S6 备份按钮行 / S7 体检行；S6 的 tab 条与 S7 的监测目录行按那张表**明写不做**。

症状与读数都在那份线框里：这五条行末尾都写着一根 `addStretch()`，1280 档那根弹簧吃掉
758–894px、2560 档 2,038–2,174px —— 右侧一片空，而**该屏本来就有一句读数**，只是画在行的
上方或下方。这一格不新增数、不新增入口，只把那句搬进行末。

三条硬口径：

1. **内容一个字不改**：那一格放的必须是这一屏别处已有的那只 QLabel（界面不自算第六个数，
   **ISSUES I60** 已定过的口径）。
2. **只在整句装得下时才搬**（`ui/viewport_fit.py` 的 `fits_absorbing`，与表格吸收列同一份判据）。
   这条比线框乙-1 写的「下限 200px + 超出省略号 + 悬停回读」**更严**，三处理由，都在下面：
   - 截第二刀会把已有的回读弄丢：S6 `lbl_current` 自己就按 `_elided` 做过中段省略，并把完整
     路径挂在 tooltip 上（`ui/pages/backup_page.py:27-46`）。行末再切一刀 = 「截了但回读不到全文」，
     撞 `test_截掉的路径必须能在悬停里回读` 那一族口径。
   - 200px 那条下限在实测数字下**永远成立**（末颗右缘 185–303px，地板档宿主约 800px，
     303 + 200 = 503 ≤ 800）⇒ Q5 甲那句「装不下就退回原位」在产品里根本走不到，
     等于留一段只能靠人工把宿主压窄才能红的死码。整句判据让两个分支都活着。
   - 整句装得下 ⇒ 不需要 `setMaximumWidth` / `ElideRight` / 改 `wordWrap` 这些把戏 ⇒ 不写回
     文本、不裁剪 ⇒ `test_truncated_table_readout._expect` 那两条（`isVisibleTo` 与全文相等）
     一个字都不用改。行末期间给句子的只是 `minimumWidth`（把布局能榨它的那一下挡掉，见
     `_Cell.width_of` 里 S6 那 273×43 的实测），回原位时还原登记那一刻的值。
     另有两处搬动本身的副作用要在 `_move` 里钉回去：跨宿主 `setParent` 会抹掉控件的显式
     显示位，`wordWrap` 标签的 sizeHint 又给的是折行后的窄宽。
3. **搬的是同一个控件**，不是它的副本：同一屏同年份不许出现两遍，所以是"画在哪"在变，
   不是"再说一遍"。装不下时按登记时的位置放回原 layout，形状等于没动。

第 4 条口径是防守型的：行widget 的横向策略设成 `Ignored`。搬进来的那句有自己的最低宽度
（S6 那条路径省略后仍是 ~420px 的**不可折断整词**），行内再叠上按钮的最低宽度就会把整窗的
最低宽度顶上去 —— 那正是 **ISSUES I52** 侧栏被榨瘪那一条的形状。这句话现在量不到（窄档那句
在本位、也在同一个页 layout 里，页最低宽度本来就含它），但它是这一格唯一能让"改窗宽"变成
"改窗宽下限"的路径，所以先堵死。
"""
from __future__ import annotations

from PySide6 import QtWidgets

from pdfarchiver.ui.viewport_fit import HostResizeWatcher, fits_absorbing


class _Cell:
    """一句读数（加上与它同进同出的同伴）在「行末」与「原位」之间的搬动记录。"""

    def __init__(self, home: QtWidgets.QBoxLayout, caption: QtWidgets.QLabel,
                 companions: tuple[QtWidgets.QWidget, ...],
                 row: "ActionRow") -> None:
        self.home = home
        self.caption = caption
        self.widgets = (caption, *companions)
        self.row = row
        self.in_row = False
        # 原位记的是**当下**的格子号：同一格里的同伴按登记顺序放回去，索引正好自洽
        # （先放前面那个，后面那个的原位就回来了）。
        self.homes: dict[QtWidgets.QWidget, int] = {w: home.indexOf(w) for w in self.widgets}
        # 回原位时要还原的最低宽：登记那一刻的值（五处登记点实测全是 0，但那是"当时没设过"，
        # 不是"永远是 0"，所以记下来而不是写死）。
        self.mins: dict[QtWidgets.QWidget, int] = {w: w.minimumWidth() for w in self.widgets}

    def width_of(self, widget: QtWidgets.QWidget) -> int:
        """这一只控件**单行**摆下需要的宽度。

        QLabel 的 `sizeHint()` 在 `wordWrap(True)` 下给的是折行后的偏好宽（**窄**），直接拿去
        排会真的折行 —— 实测 S6 `lbl_current` 整句 `horizontalAdvance` 是 585px，而 `sizeHint`
        只报 273×43，搬进行末之后布局按 273 给它，句子被压成三行、行高只有 36 ⇒ 上下都看不见。
        所以判据按单行整句量，搬进去之后还把`minimumWidth`钉成这个数，布局就榨不动它。
        """
        if isinstance(widget, QtWidgets.QLabel):
            advance = widget.fontMetrics().horizontalAdvance(widget.text())
            return max(advance + 2 * widget.margin(), widget.sizeHint().width())
        return widget.sizeHint().width()

    def width_needed(self) -> int:
        return (sum(self.width_of(w) for w in self.widgets)
                + self.row.spacing_between * (len(self.widgets) - 1))

    def pin_widths(self) -> None:
        """把每只控件的最低宽钉成"单行摆下"的那个值（只在行末期间生效）。"""
        for widget in self.widgets:
            widget.setMinimumWidth(self.width_of(widget))

    def unpin_widths(self) -> None:
        for widget in self.widgets:
            widget.setMinimumWidth(self.mins[widget])

    def can_absorb(self, fixed_total: int, row_width: int) -> bool:
        if self.caption.isHidden() or not self.caption.text():
            return False        # 空句搬进去等于把弹簧换成一条缝；隐藏的句更不该出现在行末
        return fits_absorbing(fixed_total, self.width_needed(), row_width)


class ActionRow(QtWidgets.QWidget):
    """一行按钮 + 行末那格。`add_button` 从左到右排，弹簧常驻在最右，吸收格落在弹簧右边贴右缘。

    用法（各页 `_init_ui` 里）：

        row = ActionRow()
        row.add_button(self.load_btn)
        ...
        row.absorb(layout, self.loaded_note)
        layout.addWidget(row)

    **改写完那句之后必须再调一次 `row.sync()`**：Qt 的 QLabel 根本没有"文字变了"这种信号
    （`textChanged` 是 QLineEdit 的），所以本格不会自己发现内容变了。窗口改宽那一路有
    `HostResizeWatcher` 兜着，而"同一宽度下重写了读数"只有调用点自己知道。五个登记点各自
    在哪一行调 `sync()`，都写在那一行的注释里，并由 `test_action_row_ui.py` 逐屏验一次。
    """

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self._lay = QtWidgets.QHBoxLayout(self)
        self._lay.setContentsMargins(0, 0, 0, 0)
        self._buttons: list[QtWidgets.QWidget] = []
        self._cells: list[_Cell] = []
        # 弹簧常驻：装不下时这一行的形状与"只写 addStretch()"那一天逐像素相同。
        self._spacer = QtWidgets.QSpacerItem(
            0, 0, QtWidgets.QSizePolicy.Policy.MinimumExpanding,
            QtWidgets.QSizePolicy.Policy.Minimum)
        self._lay.addItem(self._spacer)
        # 横向 `Ignored` 挡 **ISSUES I52**（见模块 docstring 第 4 条）；纵向留默认 `Preferred`：
        # 这一行原来是宿主 QVBoxLayout 里的一层 `addLayout()`，换成 widget 之后要不要额外钉
        # `Fixed` 是个可测问题 —— 实测五处宿主（S3/S4/S5/S6/S7）的行高在 1024/1280/1600/2560
        # 四档下全是 36，与改之前的嵌套布局同高，所以不钉。（S7 第一次量到 480 是**隐藏面板
        # 从没排过版**、widget 停在 Qt 默认尺寸 640×480 造成的假读数，不是被撑高。）
        self.setSizePolicy(QtWidgets.QSizePolicy.Policy.Ignored,
                           QtWidgets.QSizePolicy.Policy.Preferred)
        self._watcher = HostResizeWatcher(self, self._fit).attach()

    @property
    def spacing_between(self) -> int:
        """这一行里相邻两格之间的空隙，取布局自己的值；Qt 没给就用样式算出来的那个。"""
        spacing = self._lay.spacing()
        if spacing >= 0:
            return spacing
        return self.style().pixelMetric(
            QtWidgets.QStyle.PixelMetric.PM_LayoutHorizontalSpacing)

    def add_button(self, button: QtWidgets.QWidget) -> None:
        self._buttons.append(button)
        self._lay.insertWidget(self._lay.indexOf(self._spacer), button)

    def absorb(self, home: QtWidgets.QBoxLayout, caption: QtWidgets.QLabel,
               companions: tuple[QtWidgets.QWidget, ...] = ()) -> None:
        """把 `caption` 那句认给这一行；`companions` 与它同进同出（S5 的进度条就是同伴 ——
        把句子搬走而把它的进度条留在页底，等于把一句读数劈成两半）。

        登记时**不判一次**：五处登记点都发生在 `_init_ui` 里，那一刻行宽还是 0（`sync()` 自己
        就会退回去），第一次真判由 Qt 补发的那次 Resize 做。这一句写在 docstring 而不是代码里，
        因为坏法注入量过：在登记处补一次 `self.sync()` 全站 33 条断言一条都不红。"""
        self._cells.append(_Cell(home, caption, companions, self))

    def sync(self) -> None:
        """主动判一次：改过那句的内容或可见性之后（`setVisible` 不发信号）。"""
        width = self.width()
        if width > 0:
            self._fit(width)

    def _fit(self, row_width: int) -> None:
        fixed = self._fixed_total()
        for cell in self._cells:
            fits = cell.can_absorb(fixed, row_width)
            if fits != cell.in_row:
                self._move(cell, fits)
            if fits:
                # 钉最低宽**只这一处**：刚搬进去的那一次，与"同一宽度下句子被改写"的那一次，
                # 走同一条。原来在 `_move` 里还钉了一遍，坏法注入量出那一遍永远删不红
                # （`_fit` 这一遍兜着），所以收成一处所有权。
                cell.pin_widths()

    def _fixed_total(self) -> int:
        if not self._buttons:
            return 0
        return (sum(b.sizeHint().width() for b in self._buttons)
                + self.spacing_between * len(self._buttons))

    def _move(self, cell: _Cell, into_row: bool) -> None:
        # Qt 在 `setParent`（也就是 `insertWidget` 跨宿主）时会把这一只控件的显式显示位清掉：
        # 实测搬进 ① 段行末之后 `progress_bar.isHidden()` 变 True、geometry 还停在页底那个位置。
        # 所以先把**自己那一层的**显隐位记下来，放回布局之后再原样钉回去 —— 钉 `isVisible()`
        # 是错的，那个数连着宿主链，宿主本身没显示时它恒 False，钉回去等于把显示位抹平。
        flags = {w: w.isHidden() for w in cell.widgets}
        if into_row:
            for widget in cell.widgets:
                cell.home.removeWidget(widget)
                if widget is cell.caption:
                    self._lay.addWidget(widget)          # 弹簧之后 ⇒ 贴右缘
                else:
                    self._lay.insertWidget(self._lay.indexOf(self._spacer), widget)
        else:
            for widget in cell.widgets:
                self._lay.removeWidget(widget)
                index = min(cell.homes[widget], cell.home.count())
                cell.home.insertWidget(index, widget)
        for widget, hidden in flags.items():
            widget.setVisible(not hidden)
        if not into_row:
            # 回原位把最低宽还原成登记那一刻的值：本位上宿主 layout 该能折这一句，
            # 留着行末那份 585px 下限就是把页最低宽顶上去的那条路（**ISSUES I52** 那一族）。
            # 搬进去时的钉宽由 `_fit` 统一做，这里不重复。
            cell.unpin_widths()
        cell.in_row = into_row
