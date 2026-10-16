"""S4 操作日志与撤销 —— 甲·甲·甲·甲（2026-10-15 定案）。

布局：
- 顶部：操作批次列表（可展开查看每项详情）
- 底部：选中批次的详细日志（每项的状态、错误、journal 读数）

数据来自 `AppContext.operations`。
"""
from __future__ import annotations

from PySide6 import QtCore, QtWidgets

from pdfarchiver.services.bootstrap import AppContext
from pdfarchiver.ui.table_layout import CELL_PADDING_WIDTH, set_table_columns


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
        self.item_table = QtWidgets.QTableWidget()
        self.item_table.setColumnCount(6)
        self.item_table.setHorizontalHeaderLabels(["ID", "类型", "源路径", "目标路径", "状态", "错误"])
        set_table_columns(self.item_table,
                          {0: 56, 1: 110, 2: 240, 3: 240, 4: 80, 5: 240})
        self.item_table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.item_table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.item_table.setAlternatingRowColors(True)
        layout.addWidget(self.item_table, 1)

        # 按钮
        btn_lay = QtWidgets.QHBoxLayout()
        self.refresh_btn = QtWidgets.QPushButton("刷新")
        self.refresh_btn.setObjectName("searchBtn")
        self.refresh_btn.clicked.connect(self.reload)
        btn_lay.addWidget(self.refresh_btn)

        self.undo_btn = QtWidgets.QPushButton("撤销选中批次")
        self.undo_btn.clicked.connect(self._undo_operation)
        btn_lay.addWidget(self.undo_btn)

        btn_lay.addStretch()
        layout.addLayout(btn_lay)

        self.reload()

    def reload(self) -> None:
        """刷新操作批次列表。"""
        ops = self.ctx.operations.list_operations(limit=100)
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

    def _on_op_selected(self) -> None:
        row = self.op_table.currentRow()
        if row < 0:
            self.item_table.setRowCount(0)
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

    def _undo_operation(self) -> None:
        """整批撤销**还没实现**，这里只报"没动盘"，不演一遍成功。

        按 **D-043** 定案，撤销落成一条**新批次**（`kind='undo'`、`undo_of=原批次`）：
        只收 `reversible=1` 的项，被排除的条数与原因必须显示，完成后给出 **G18** 的
        四件读数（源存在 / 字节数一致 / sha256 一致 / 目标已消失）。这套执行器与读数都
        还没有，实现挂账见 **ISSUES I55**。

        文案为什么不能留成原来那句「这将创建一个反向操作批次」：它承诺的是磁盘动作，
        而点完「是」之后什么也没发生 —— 用户会以为已经搬回去了。这一类"文案说了、
        代码没做"由 `test_撤销入口的文案不许承诺磁盘动作` 钉住。
        """
        row = self.op_table.currentRow()
        if row < 0:
            QtWidgets.QMessageBox.information(self, "撤销", "请先选择一个操作批次")
            return
        item = self.op_table.item(row, 0)
        if not item:
            return
        op_id = item.data(QtCore.Qt.ItemDataRole.UserRole)
        op = self.ctx.operations.get_operation(op_id)
        if not op:
            return
        QtWidgets.QMessageBox.information(
            self, "撤销还没实现",
            f"操作批次 #{op_id} 没有被改动，磁盘上的文件一个都没动。\n\n"
            "整批撤销还没做好。做好之后它会另开一条反向批次：只撤销可逆的项，"
            "不可逆的项会列出条数和原因，完成后逐项给出四项对账读数"
            "（源文件存在、字节数一致、内容哈希一致、原目标已消失）。")
