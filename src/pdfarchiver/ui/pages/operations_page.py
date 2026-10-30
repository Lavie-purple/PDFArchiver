"""S4 操作日志与撤销 —— 甲·甲·甲·甲（2026-10-15 定案）。

布局：
- 顶部：操作批次列表（可展开查看每项详情）
- 底部：选中批次的详细日志（每项的状态、错误、journal 读数）

数据来自 `AppContext.operations`。
"""
from __future__ import annotations

from PySide6 import QtCore, QtWidgets

from pdfarchiver.services.bootstrap import AppContext
from pdfarchiver.ui.action_row import ActionRow
from pdfarchiver.ui.confirm import DangerSummary, confirm_dangerous
from pdfarchiver.ui.table_layout import CELL_PADDING_WIDTH, loaded_line, set_table_columns


class OperationsPage(QtWidgets.QWidget):
    """S4：操作日志与撤销。"""

    def __init__(self, ctx: AppContext, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.ctx = ctx

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        # 操作批次列表
        op_title = QtWidgets.QLabel("操作批次")
        op_title.setObjectName("sectionTitle")
        layout.addWidget(op_title)
        self.loaded_note = QtWidgets.QLabel("")
        self.loaded_note.setObjectName("muted")
        self.loaded_note.setWordWrap(True)
        layout.addWidget(self.loaded_note)
        self.op_table = QtWidgets.QTableWidget()
        self.op_table.setColumnCount(6)
        self.op_table.setHorizontalHeaderLabels(["ID", "类型", "状态", "总数", "完成", "失败"])
        # 「状态」90px 装不下词表里最长的 `partially_done`（14 字符 ×7px + 23px 内边距
        # = 121px），实测显示成 `parti…` —— §S4 那条「七个态必须都能显示」当场落空。
        set_table_columns(self.op_table,
                          {0: 56, 2: 98 + CELL_PADDING_WIDTH,
                           3: 64, 4: 64, 5: 64}, stretch_col=1)
        self.op_table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.op_table.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.SingleSelection)
        self.op_table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.op_table.setAlternatingRowColors(True)
        self.op_table.itemSelectionChanged.connect(self._on_op_selected)
        layout.addWidget(self.op_table, 1)

        # 操作项详情
        item_title = QtWidgets.QLabel("操作项详情")
        item_title.setObjectName("sectionTitle")
        layout.addWidget(item_title)
        # 未选批次时详情表只有表头 —— 不说一句就是让人对着空表猜（**ISSUES I108** 甲；
        # 乙「reload() 默认选中最新一条」被否掉，因为那会让「撤销选中批次」一进页面就可点）。
        self.item_hint = QtWidgets.QLabel("先点上面一条批次，详情才会列出它搬了哪些文件")
        self.item_hint.setObjectName("muted")
        self.item_hint.setWordWrap(True)
        layout.addWidget(self.item_hint)
        self.item_table = QtWidgets.QTableWidget()
        self.item_table.setColumnCount(6)
        self.item_table.setHorizontalHeaderLabels(["ID", "类型", "源路径", "目标路径", "状态", "错误"])
        # 「错误」当吸收列（**ISSUES I121 ①甲**）：它是这一屏唯一内容天生没上限的一列
        # （第三方报错原文，在 `ELIDABLE_COLUMNS` 里、有 tooltip 回读），六列定宽合计 966px，
        # 地板档视口装不下时由运行时判据退回全定宽 + 横向滚动。
        set_table_columns(self.item_table,
                          {0: 56, 1: 110, 2: 240, 3: 240, 4: 80, 5: 240}, stretch_col=5)
        self.item_table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.item_table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.item_table.setAlternatingRowColors(True)
        layout.addWidget(self.item_table, 1)

        # 按钮
        self.action_row = ActionRow()
        self.refresh_btn = QtWidgets.QPushButton("刷新")
        self.refresh_btn.setObjectName("searchBtn")
        self.refresh_btn.clicked.connect(self.reload)
        self.action_row.add_button(self.refresh_btn)

        self.undo_btn = QtWidgets.QPushButton("撤销选中批次")
        self.undo_btn.clicked.connect(self._undo_operation)
        self.action_row.add_button(self.undo_btn)

        # 「共 N 条｜表格里 M 条」那句本来贴在批次表上方，行末那根弹簧空着（**ISSUES I121** ④）。
        self.action_row.absorb(layout, self.loaded_note)
        layout.addWidget(self.action_row)

        self.reload()

    def reload(self) -> None:
        """刷新操作批次列表。批次大小取仓储层默认值，界面不定数（**ISSUES I76**）。"""
        ops = self.ctx.operations.list_operations()
        self.op_table.setRowCount(len(ops))
        for row, op in enumerate(ops):
            self.op_table.setItem(row, 0, QtWidgets.QTableWidgetItem(str(op.id)))
            self.op_table.setItem(row, 1, QtWidgets.QTableWidgetItem(op.kind))
            self.op_table.setItem(row, 2, QtWidgets.QTableWidgetItem(op.status))
            self.op_table.setItem(row, 3, QtWidgets.QTableWidgetItem(str(op.items_total)))
            self.op_table.setItem(row, 4, QtWidgets.QTableWidgetItem(str(op.items_done)))
            self.op_table.setItem(row, 5, QtWidgets.QTableWidgetItem(str(op.items_failed)))
            # 存储 op_id
            self.op_table.item(row, 0).setData(QtCore.Qt.ItemDataRole.UserRole, op.id)
        # 「共 N 条」必须数自库，不能是 `len(ops)` —— 后者是被 limit 截过的取回数（**ISSUES I76**）
        self.loaded_note.setText(loaded_line(self.ctx.operations.count_operations(),
                                             len(ops), "条操作批次"))
        # 同一屏改写完那句要重判一次搬不搬（QLabel 没有 textChanged，见 `ui/action_row.py`）。
        self.action_row.sync()
        self._sync_item_hint()

    def _sync_item_hint(self) -> None:
        """详情表只有表头时给一句话（I108 甲）；选中批次之后就撤掉，别盖住真详情。"""
        self.item_hint.setVisible(self.op_table.currentRow() < 0)

    def _on_op_selected(self) -> None:
        row = self.op_table.currentRow()
        if row < 0:
            self.item_table.setRowCount(0)
            self._sync_item_hint()
            return
        item = self.op_table.item(row, 0)
        if not item:
            return
        op_id = item.data(QtCore.Qt.ItemDataRole.UserRole)
        items = self.ctx.operations.list_items(op_id)
        self.item_table.setRowCount(len(items))
        for r, it in enumerate(items):
            self.item_table.setItem(r, 0, QtWidgets.QTableWidgetItem(str(it.id)))
            self.item_table.setItem(r, 1, QtWidgets.QTableWidgetItem(it.kind))
            src_item = QtWidgets.QTableWidgetItem(it.src_path)
            src_item.setToolTip(it.src_path)
            self.item_table.setItem(r, 2, src_item)
            dst_item = QtWidgets.QTableWidgetItem(it.dst_path or "")
            dst_item.setToolTip(it.dst_path or "")
            self.item_table.setItem(r, 3, dst_item)
            self.item_table.setItem(r, 4, QtWidgets.QTableWidgetItem(it.state))
            err_item = QtWidgets.QTableWidgetItem(it.error or "")
            err_item.setToolTip(it.error or "")
            self.item_table.setItem(r, 5, err_item)
        self._sync_item_hint()

    def _selected_op_id(self) -> int | None:
        row = self.op_table.currentRow()
        if row < 0:
            return None
        item = self.op_table.item(row, 0)
        return None if item is None else item.data(QtCore.Qt.ItemDataRole.UserRole)

    def _undo_operation(self) -> None:
        """整批撤销：另开一条 `kind='undo'`、`undo_of=本批` 的反向批次（**D-043** 甲）。

        确认之前先把 `ArchiveService.plan_undo()` 的账摆出来 —— 能撤几条、排除几条、
        每条为什么。§S4 那条硬约束是"排除的**条数与原因必须显示**，不许只显示撤销成功"，
        所以原因原文进确认框，不汇总成一句。含"被标记为不可逆"的那几条时，
        **D-042** 丙 的分级控件自动切到输入确认词那一档（与 S3 同一个控件、同一条形状）。

        批次如何搬、journal 怎么写、撤销跑完之后原批次转 `undone` —— 全在后台执行器里，
        本屏只负责"算账给人看"和"提交"。
        """
        op_id = self._selected_op_id()
        if op_id is None:
            QtWidgets.QMessageBox.information(self, "撤销", "请先选择一个操作批次")
            return
        try:
            plan = self.ctx.archive.plan_undo(op_id)
        except ValueError as exc:          # 批次不存在 / 它本身就是撤销批次：原文回显
            QtWidgets.QMessageBox.warning(self, "撤销", str(exc))
            return
        if not plan.moves:
            detail = "\n".join(f"· {reason}" for reason in plan.excluded)
            QtWidgets.QMessageBox.information(
                self, "撤销",
                f"批次 #{op_id} 没有可撤销的项。\n{detail}" if detail else
                f"批次 #{op_id} 没有可撤销的项：这一批一项都没搬成。")
            return

        lines = tuple(plan.excluded)
        if lines:
            lines = (f"排除 {len(lines)} 项，原因逐条：",) + lines
        if not confirm_dangerous(
                self, title=f"确认撤销批次 #{op_id}", verb="撤销",
                summary=DangerSummary(
                    will_run=len(plan.moves),
                    same_disk=sum(1 for m in plan.moves if m.kind == "move"),
                    cross_disk=sum(1 for m in plan.moves if m.kind == "copy"),
                    irreversible=plan.irreversible,
                    lines=tuple(x for x in lines if x))):
            return

        op, excluded, _reasons = self.ctx.archive.submit_undo(op_id)
        self.reload()
        QtWidgets.QMessageBox.information(
            self, "已提交撤销",
            f"已提交撤销批次 #{op.id}（撤销 #{op_id}）｜共 {op.items_total} 项｜排除 {excluded} 项\n"
            "反向批次排在后台队列里跑；进度、journal 态与失败原因在本屏刷新后逐项可见。")
