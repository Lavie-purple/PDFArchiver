"""S8 右键「导出此分类清单…」的弹层 —— **ISSUES I78** 丙（2026-10-19）。

形状取线框 `docs/wireframes/2026-10-19-round14-i67-i78.html` §I78-bing（2026-10-19 勾「丙」）：
右键某枝 → 弹层里四件事（含子分类 · 格式 · 列 · 保存路径）→「导出」。

四条不是偏好而是后果的约定：
- **复选框的清单与表头只有一个出处**：`services/export_service.py` 的 `EXPORT_COLUMNS` 与
  `FORMATS`。界面在这里读它们，而不是抄一份标签 —— 抄的那一份会在服务层加列之后继续按旧列集
  上屏，于是「界面上有这一列、产物里没有」正好是 **ISSUES I80** 那一类"界面宣称它会做它不做的事"。
- **屏幕上那个份数就是产物里的行数**：`ctx.export.count()` 与导出走的是同一条 WHERE
  （同一个 `DocFilter`），所以勾「含子分类」时那一行数字当场跟着变。线框的硬断言 (a)
  「导出行数 == 那条 COUNT(*)」靠这一条才成立，而不是靠导出之后再数一遍。
- **「本机绝对路径」勾选时先确认一次**（线框 (c)）。确认之后才把 `acknowledge_local_path=True`
  传下去：这一列的显式确认位归服务层判，界面不许"以为自己问过了"。拒了就当场回落到未勾，
  不许留着勾但实际不写 —— 那是屏幕上说"勾了"、产物里没有。
- **保存路径为空时「导出」是死的**（**ISSUES I74** 三件套同一条纪律）：不预设一个"看起来对"的
  目录，因为产物落哪儿只有人知道；默认写到应用数据目录属于替人做决定。
  目录存在与否**不在这里判** —— 服务层那句「目标目录不存在或不是一个目录」是同一件事的唯一说法。
"""
from __future__ import annotations

from pathlib import Path

from PySide6 import QtWidgets

from pdfarchiver.services.bootstrap import AppContext
from pdfarchiver.services.export_service import (
    DEFAULT_COLUMNS,
    EXPORT_COLUMNS,
    FORMATS,
    LOCAL_PATH_WARNING,
)


class ExportDialog(QtWidgets.QDialog):
    """S8 那一枝的导出弹层；控件全部挂成具名属性，好让测试不开模态也能驱动。"""

    def __init__(self, ctx: AppContext, category_id: int,
                 parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.ctx = ctx
        self.category_id = category_id
        self.category_name_path = ctx.catalog.get_category(category_id).name_path
        self.setWindowTitle(f"导出清单 · {self.category_name_path}")
        self.setMinimumWidth(460)

        lay = QtWidgets.QVBoxLayout(self)
        scope = QtWidgets.QLabel(f"目标「{self.category_name_path}」")
        lay.addWidget(scope)

        self.child_toggle = QtWidgets.QCheckBox("含子分类（把这一整枝都算进来）")
        self.child_toggle.setChecked(True)
        self.child_toggle.toggled.connect(self._refresh_count)
        lay.addWidget(self.child_toggle)

        self.count_note = QtWidgets.QLabel()
        self.count_note.setObjectName("muted")
        lay.addWidget(self.count_note)

        # ---- 输出格式：三颗单选钮，标签来自 FORMATS ----
        fmt_box = QtWidgets.QGroupBox("输出格式")
        fmt_lay = QtWidgets.QHBoxLayout(fmt_box)
        self.format_buttons: dict[str, QtWidgets.QRadioButton] = {}
        for key, label, _ext in FORMATS:
            radio = QtWidgets.QRadioButton(label)
            radio.setObjectName(f"fmt_{key}")
            radio.setChecked(key == "csv")     # 线框推荐档：CSV 主、JSON 次、MD 可选
            fmt_lay.addWidget(radio)
            self.format_buttons[key] = radio
        lay.addWidget(fmt_box)

        # ---- 导出列：默认勾五项，未勾的列不出现在产物里 ----
        col_box = QtWidgets.QGroupBox("导出列")
        col_lay = QtWidgets.QGridLayout(col_box)
        self.column_checks: dict[str, QtWidgets.QCheckBox] = {}
        for index, column in enumerate(EXPORT_COLUMNS):
            box = QtWidgets.QCheckBox(column.label)
            box.setChecked(column.key in DEFAULT_COLUMNS)
            if column.privacy:
                box.setText(f"{column.label} ⚠ 隐私")
                box.setToolTip(f"{LOCAL_PATH_WARNING}；默认不勾，勾了要多确认一次")
                box.toggled.connect(self._on_local_path_toggled)
            box.toggled.connect(self._refresh_export_enabled)
            col_lay.addWidget(box, index // 2, index % 2)
            self.column_checks[column.key] = box
        lay.addWidget(col_box)

        # ---- 保存路径 ----
        dest_row = QtWidgets.QHBoxLayout()
        dest_row.addWidget(QtWidgets.QLabel("保存到"))
        self.dest_input = QtWidgets.QLineEdit()
        self.dest_input.setPlaceholderText("先选一个目录，产物写进这里")
        self.dest_input.textChanged.connect(self._refresh_export_enabled)
        dest_row.addWidget(self.dest_input, 1)
        self.choose_btn = QtWidgets.QPushButton("选择…")
        self.choose_btn.setObjectName("searchBtn")
        self.choose_btn.clicked.connect(self.choose_destination)
        dest_row.addWidget(self.choose_btn)
        lay.addLayout(dest_row)

        note = QtWidgets.QLabel("未勾的列不出现在产物里 · 同名产物不覆盖 · 全程只读，不写库不改文档")
        note.setObjectName("muted")
        note.setWordWrap(True)
        lay.addWidget(note)

        buttons = QtWidgets.QHBoxLayout()
        buttons.addStretch(1)
        self.cancel_btn = QtWidgets.QPushButton("取消")
        self.cancel_btn.clicked.connect(self.reject)
        self.export_btn = QtWidgets.QPushButton("导出")
        self.export_btn.setObjectName("searchBtn")
        # 回车不许等于导出：与 `ui/confirm.py` 同一条理由，模态框一打开焦点就在第一个控件上。
        self.export_btn.setAutoDefault(False)
        self.export_btn.setDefault(False)
        self.export_btn.clicked.connect(self.run_export)
        buttons.addWidget(self.cancel_btn)
        buttons.addWidget(self.export_btn)
        lay.addLayout(buttons)

        self._refresh_count()
        self._refresh_export_enabled()   # 建控件时的 setChecked 不发信号，禁用态必须自己算一次

    # ---- 读数 ----

    def include_children(self) -> bool:
        return self.child_toggle.isChecked()

    def selected_format(self) -> str:
        for key, radio in self.format_buttons.items():
            if radio.isChecked():
                return key
        # 三颗钮在同一互斥组里，理论上不可能全不选中；真到了那一步也不许猜一个格式写产物。
        raise ValueError("没有任何一个格式被选中")

    def selected_columns(self) -> tuple[str, ...]:
        """按 `EXPORT_COLUMNS` 的顺序回勾选项 —— 产物里的列顺序由那张表定，不由点击顺序定。"""
        return tuple(c.key for c in EXPORT_COLUMNS if self.column_checks[c.key].isChecked())

    def destination(self) -> Path:
        return Path(self.dest_input.text().strip())

    def _refresh_count(self) -> None:
        """屏幕上那句份数由服务层数，界面不自己拼 SQL、不数表格行数（**ISSUES I60**）。"""
        try:
            rows = self.ctx.export.count(self.category_id, include_children=self.include_children())
        except Exception as exc:
            self.count_note.setText(f"份数取不到：{exc}")
            return
        scope = "含子分类" if self.include_children() else "只这一枝"
        self.count_note.setText(f"{scope} · 此刻 {rows} 行 = 导出的行数")

    def _refresh_export_enabled(self) -> None:
        self.export_btn.setEnabled(bool(self.dest_input.text().strip())
                                   and bool(self.selected_columns()))

    # ---- 隐私列的确认（线框 §I78-bing 硬断言 c）----

    def _on_local_path_toggled(self, checked: bool) -> None:
        box = self.column_checks["local_path"]
        if not checked:
            # 摘掉之后再勾要重新问一次：确认下来的是"这一次要写"，不是"以后都别问我"。
            box.setProperty("confirmed", False)
            return
        if box.property("confirmed"):
            return
        reply = QtWidgets.QMessageBox.question(
            self, "导出本机绝对路径？",
            f"{LOCAL_PATH_WARNING}。\n\n清单一旦被发到群里，目录结构与用户名就一起交出去了。\n"
            "确定要写这一列吗？",
            QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No)
        if reply == QtWidgets.QMessageBox.StandardButton.Yes:
            box.setProperty("confirmed", True)
            return
        box.blockSignals(True)           # 程序化取消不能再次触发这条确认，否则点"否"会弹第二次
        box.setChecked(False)
        box.blockSignals(False)

    def choose_destination(self) -> None:
        chosen = QtWidgets.QFileDialog.getExistingDirectory(self, "选择导出目录",
                                                            self.dest_input.text().strip())
        if chosen:
            self.dest_input.setText(chosen)

    # ---- 动作 ----

    def run_export(self) -> None:
        try:
            receipt = self.ctx.export.export(
                self.category_id, dest_dir=self.destination(), fmt=self.selected_format(),
                columns=self.selected_columns(), include_children=self.include_children(),
                acknowledge_local_path=self.column_checks["local_path"].isChecked())
        except Exception as exc:
            # 后端原文直接上屏（**ISSUES I84** ③）：这一句里带着"为什么不写"，界面不重述一遍。
            QtWidgets.QMessageBox.warning(self, "导出未完成", str(exc))
            return
        self.accept()
        QtWidgets.QMessageBox.information(self, "导出完成", receipt.describe())
