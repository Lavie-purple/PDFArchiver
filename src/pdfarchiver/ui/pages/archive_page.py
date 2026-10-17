"""S3 归档预览与确认 —— 丙·丙·甲（2026-10-15 定案）。

布局：
- 顶部：目标根目录选择 + 模板预览
- 中部：待归档文档列表（可勾选）
- 底部：预览表格（源路径 → 目标路径）+ [执行归档] 按钮

数据来自 `AppContext.documents`、`AppContext.settings`。
"""
from __future__ import annotations

from pathlib import Path

from PySide6 import QtCore, QtWidgets

from pdfarchiver.services.bootstrap import AppContext
from pdfarchiver.ui.pages.status_page import unwired_lines
from pdfarchiver.ui.table_layout import set_table_columns


class ArchivePage(QtWidgets.QWidget):
    """S3：归档预览与确认。"""

    def __init__(self, ctx: AppContext, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.ctx = ctx

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        # 顶部：目标根目录 + 模板
        top_lay = QtWidgets.QFormLayout()
        self.target_root_input = QtWidgets.QLineEdit()
        self.target_root_input.setPlaceholderText("选择目标根目录...")
        self.target_root_input.setText(self.ctx.settings.values.get("archive_target_root", ""))
        top_lay.addRow("目标根目录:", self.target_root_input)

        self.template_input = QtWidgets.QLineEdit()
        self.template_input.setText(self.ctx.settings.values.get("archive_default_template", "{category}/{year}/{name}.pdf"))
        top_lay.addRow("命名模板:", self.template_input)

        # **ISSUES I55** ③ 的如实呈现（勾乙，2026-10-17）。这一栏现在是**断的三处**：值不落回
        # `settings`、`_generate_preview()` 读进局部变量后一次都没用、执行器也忽略入参 ——
        # 三种形状里最阴的不是"按钮按下去没反应"，是"控件看着能用、预览看着对，改了却什么都不变"，
        # 用户会以为自己已经分好了目录。所以把"没生效"写在它正下方，而不是等人去状态页翻。
        # 文案取 `status_page.unwired_lines("S3")` —— **界面不另编一句**（全站只有那一份口径）。
        self.unwired_label = QtWidgets.QLabel()
        self.unwired_label.setObjectName("muted")
        self.unwired_label.setWordWrap(True)
        self.unwired_label.setText("本轮未接线：" + "；".join(unwired_lines("S3")))
        top_lay.addRow(self.unwired_label)

        layout.addLayout(top_lay)

        # 中部：待归档文档列表
        doc_title = QtWidgets.QLabel("待归档文档（从文档库勾选）")
        doc_title.setObjectName("sectionTitle")
        layout.addWidget(doc_title)
        self.doc_table = QtWidgets.QTableWidget()
        self.doc_table.setColumnCount(4)
        self.doc_table.setHorizontalHeaderLabels(["选择", "文件名", "路径", "分类"])
        # 让「分类」当吸收列而不是「文件名」：定宽那三列合计 576px，地板档（窗口 1024px）下这张
        # 表的视口实测 805px（空库读数），富余全落在吸收列上（实测「分类」229px）—— 文件名/路径
        # 保住定宽，被吃掉的是信息量最低、且左栏分类树里本来就有的那一列。地板档已经压不出更窄的
        # 视口了（**D-039** 的 1024px 地板，见 **ISSUES I52**），所以"吸收列落错地方"这一类
        # 由 `test_压到地板宽度时归档表仍保住文件名与路径` 钉住，而不是靠窗口还能更小来暴露。
        # 805px 现在是个**与行数无关**的读数（**ISSUES I54** 已销：行号列不再长出来，行多了只
        # 多一条 8px 的纵向滚动条）。同一档改这行之前读到的是 805 / 767 / 746（空库 / 2 行 / 40 行），
        # 「分类」那条吸收列跟着从 229 漂到 191 再漂到 170 —— 反算的分母根本不稳定。
        set_table_columns(self.doc_table, {0: 56, 1: 280, 2: 240}, stretch_col=3)
        self.doc_table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.doc_table.setAlternatingRowColors(True)
        layout.addWidget(self.doc_table, 1)

        # 底部：预览 + 按钮
        preview_title = QtWidgets.QLabel("预览（源 → 目标）")
        preview_title.setObjectName("sectionTitle")
        layout.addWidget(preview_title)
        self.preview_table = QtWidgets.QTableWidget()
        self.preview_table.setColumnCount(2)
        self.preview_table.setHorizontalHeaderLabels(["源路径", "目标路径"])
        set_table_columns(self.preview_table, {0: 300}, stretch_col=1)
        self.preview_table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.preview_table.setAlternatingRowColors(True)
        layout.addWidget(self.preview_table, 1)

        btn_lay = QtWidgets.QHBoxLayout()
        self.load_btn = QtWidgets.QPushButton("加载文档库")
        self.load_btn.clicked.connect(self._load_documents)
        btn_lay.addWidget(self.load_btn)

        self.preview_btn = QtWidgets.QPushButton("生成预览")
        self.preview_btn.clicked.connect(self._generate_preview)
        btn_lay.addWidget(self.preview_btn)

        self.execute_btn = QtWidgets.QPushButton("执行归档")
        self.execute_btn.setObjectName("searchBtn")
        self.execute_btn.clicked.connect(self._execute_archive)
        btn_lay.addWidget(self.execute_btn)

        btn_lay.addStretch()
        layout.addLayout(btn_lay)

    def _load_documents(self) -> None:
        """从文档库加载文档列表。"""
        docs = self.ctx.documents.list(limit=500)
        self.doc_table.setRowCount(len(docs))
        for row, doc in enumerate(docs):
            checkbox = QtWidgets.QTableWidgetItem()
            checkbox.setCheckState(QtCore.Qt.CheckState.Unchecked)
            self.doc_table.setItem(row, 0, checkbox)
            name_item = QtWidgets.QTableWidgetItem(doc.name)
            # 「文件名」「分类」是定宽装不下的可截断列（名字长度没有上限、分类是最多
            # 三个用户自定义名），口径与「路径」一致：截断了必须能悬停读回全文。
            name_item.setToolTip(doc.name)
            self.doc_table.setItem(row, 1, name_item)
            path_item = QtWidgets.QTableWidgetItem(doc.path)
            path_item.setToolTip(doc.path)
            self.doc_table.setItem(row, 2, path_item)
            cats = self.ctx.catalog.categories_of(doc.id)
            cat_str = ", ".join(c.name for c in cats[:2])
            cat_item = QtWidgets.QTableWidgetItem(cat_str)
            cat_item.setToolTip(cat_str)
            self.doc_table.setItem(row, 3, cat_item)
            # 存储 doc_id
            self.doc_table.item(row, 0).setData(QtCore.Qt.ItemDataRole.UserRole, doc.id)

    def _generate_preview(self) -> None:
        """根据勾选的文档生成预览。"""
        target_root = self.target_root_input.text().strip()
        if not target_root:
            QtWidgets.QMessageBox.warning(self, "预览失败", "请先设置目标根目录")
            return

        template = self.template_input.text().strip()
        target_root_path = Path(target_root)

        selected_docs = []
        for row in range(self.doc_table.rowCount()):
            checkbox = self.doc_table.item(row, 0)
            if checkbox and checkbox.checkState() == QtCore.Qt.CheckState.Checked:
                doc_id = checkbox.data(QtCore.Qt.ItemDataRole.UserRole)
                doc = self.ctx.documents.get(doc_id)
                if doc:
                    selected_docs.append(doc)

        self.preview_table.setRowCount(len(selected_docs))
        for row, doc in enumerate(selected_docs):
            src_item = QtWidgets.QTableWidgetItem(doc.path)
            src_item.setToolTip(doc.path)
            self.preview_table.setItem(row, 0, src_item)
            # 目标路径**不看 `template`**（上面那行 `unwired_label` 就是这件事的屏上说明）：
            # 渲染接线与「执行归档」「整批撤销」在同一张账上（**ISSUES I55** 甲/乙/丙 勾乙）。
            dst = target_root_path / doc.name
            dst_item = QtWidgets.QTableWidgetItem(str(dst))
            dst_item.setToolTip(str(dst))
            self.preview_table.setItem(row, 1, dst_item)

    def _execute_archive(self) -> None:
        """「执行归档」**还没接到后台队列** —— 只报"没动盘"，不许报"已提交"。

        后端链路本身是通的：`WorkQueue` 注册了 `"archive": archive.handle`
        （`services/bootstrap.py`），`ArchiveService.handle` 会建批次、写 journal、
        逐条校验后真的搬文件。缺的只有界面这一步：把勾选项落成一条 job。
        接线连着 **G17 / G18 / G19** 三条磁盘安全门禁一起欠着，挂账见 **ISSUES I55**；
        接上时还要按 **D-042** 换成分级确认控件（全可逆 → 复选框 + 影响条数；
        含不可逆项 → 输入确认词），现在的 Yes/No 弹窗不够格。

        原来这里在收集完 `doc_ids` 之后什么都没做，却弹「已将 N 份文档提交到归档队列，
        请在操作日志页查看进度」—— 台账里不会多出任何一条，因为压根没提交。
        AGENTS.md 把这条写死了：禁止能力不足时伪装成功。
        """
        target_root = self.target_root_input.text().strip()
        if not target_root:
            QtWidgets.QMessageBox.warning(self, "执行归档", "请先设置目标根目录")
            return

        doc_ids = []
        for row in range(self.doc_table.rowCount()):
            checkbox = self.doc_table.item(row, 0)
            if checkbox and checkbox.checkState() == QtCore.Qt.CheckState.Checked:
                doc_ids.append(checkbox.data(QtCore.Qt.ItemDataRole.UserRole))
        if not doc_ids:
            QtWidgets.QMessageBox.warning(
                self, "执行归档", "请先在「待归档文档」里勾选要归档的文档")
            return

        QtWidgets.QMessageBox.information(
            self, "执行归档还没接上",
            f"选中的 {len(doc_ids)} 份文档一份都没有被移动，磁盘上什么都没变。\n\n"
            "预览能算出目标路径，但「执行」这一步还没接到后台队列：现在点它"
            "不会创建操作批次，也不会开始搬运。接线与撤销执行器在同一张账上。")
