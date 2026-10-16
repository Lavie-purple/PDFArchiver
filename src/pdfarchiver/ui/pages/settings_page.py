"""S7 设置 · 监测与索引 —— 上下分区（甲 · 2026-10-15 定案）。

上半区 = StatusPage 现有内容（运行时 / 设置 / 数据库 / 任务读数），一字不改搬过来。
下半区 = 设置 UI：监测目录管理、索引设置、OCR 三读数、模型状态。

**上半区是真的把 `StatusPage` 那个控件嵌进来，不是再抄一份渲染代码**（**D-040** 第三条后果）。
先前这里自己拼了一遍 `== 运行时 == / == 数据库 == / …`，两份代码已经漂掉了：状态页结尾那句
"OCR 后端已交付……语义搜索……还没实现"在这里就没有。**同一份读数在两个地方各拼一遍，
就是"核心概念多个口径"** —— 所以这一屏嵌控件，不嵌副本。

数据全部来自 `AppContext` 的真查询，页面里没有写死的数字。
"""
from __future__ import annotations

from PySide6 import QtCore, QtWidgets

from pdfarchiver.services.bootstrap import AppContext
from pdfarchiver.ui.pages.status_page import StatusPage


class SettingsPage(QtWidgets.QWidget):
    """S7：上半区状态 + 下半区设置。"""

    def __init__(self, ctx: AppContext, cold_start_seconds: float | None = None,
                 parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.ctx = ctx

        splitter = QtWidgets.QSplitter(QtCore.Qt.Orientation.Vertical)

        # 上半区：那张状态页本身（D-040 —— 嵌控件，不重画一份读数）
        self.status_page = StatusPage(self.ctx, cold_start_seconds=cold_start_seconds)

        # 下半区：设置 UI
        lower = QtWidgets.QWidget()
        lower_lay = QtWidgets.QVBoxLayout(lower)
        lower_lay.setContentsMargins(8, 8, 8, 8)

        # 监测目录
        roots_group = QtWidgets.QGroupBox("监测目录")
        roots_lay = QtWidgets.QVBoxLayout(roots_group)
        self.roots_list = QtWidgets.QListWidget()
        self.roots_list.setMaximumHeight(120)
        roots_lay.addWidget(self.roots_list)
        roots_btns = QtWidgets.QHBoxLayout()
        self.add_root_btn = QtWidgets.QPushButton("添加目录...")
        self.add_root_btn.clicked.connect(self.add_root)
        self.remove_root_btn = QtWidgets.QPushButton("移除选中")
        self.remove_root_btn.clicked.connect(self.remove_root)
        roots_btns.addWidget(self.add_root_btn)
        roots_btns.addWidget(self.remove_root_btn)
        roots_btns.addStretch()
        roots_lay.addLayout(roots_btns)
        lower_lay.addWidget(roots_group)

        # OCR 三读数
        ocr_group = QtWidgets.QGroupBox("OCR 读数（O1 / O2 / O3）")
        ocr_lay = QtWidgets.QFormLayout(ocr_group)
        self.ocr_o1 = QtWidgets.QLabel("—")
        self.ocr_o2 = QtWidgets.QLabel("—")
        self.ocr_o3 = QtWidgets.QLabel("—")
        ocr_lay.addRow("O1 · 今日已识别页数:", self.ocr_o1)
        ocr_lay.addRow("O2 · 预算剩余:", self.ocr_o2)
        ocr_lay.addRow("O3 · 累计识别页数:", self.ocr_o3)
        lower_lay.addWidget(ocr_group)

        # 模型状态
        model_group = QtWidgets.QGroupBox("模型状态")
        model_lay = QtWidgets.QFormLayout(model_group)
        self.model_status = QtWidgets.QLabel("—")
        self.model_path = QtWidgets.QLabel("—")
        # 版本戳/路径这类整串不换行会把下半区的最低宽度顶起来（实测 455px）
        self.model_path.setWordWrap(True)
        model_lay.addRow("状态:", self.model_status)
        model_lay.addRow("路径:", self.model_path)
        lower_lay.addWidget(model_group)

        lower_lay.addStretch()

        splitter.addWidget(self.status_page)
        splitter.addWidget(lower)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1)

        main_lay = QtWidgets.QVBoxLayout(self)
        main_lay.setContentsMargins(0, 0, 0, 0)
        main_lay.addWidget(splitter)

        self.reload_status()
        self.reload_settings()

    def reload_status(self) -> None:
        """重渲染上半区 —— 就是让那张状态页自己重查一遍库，这里不留第二份查询。"""
        self.status_page.reload()

    def reload_settings(self) -> None:
        """重查下半区的设置读数。"""
        # 监测目录
        self.roots_list.clear()
        enabled = {r.root_key for r in self.ctx.roots.list_enabled()}
        for root in self.ctx.roots.list():
            status = "" if root.root_key in enabled else " [已禁用]"
            self.roots_list.addItem(f"{root.root_key}: {root.root_path}{status}")

        # OCR 三读数（从 app_settings 现数，不缓存）
        try:
            ocr_stats = self.ctx.app_settings.get("ocr_stats")
            if isinstance(ocr_stats, dict):
                today = ocr_stats.get("today_pages", 0)
                total = ocr_stats.get("total_pages", 0)
                budget = int(self.ctx.settings["ocr_daily_page_budget"])
                self.ocr_o1.setText(str(today))
                self.ocr_o2.setText(f"{max(0, budget - today)} / {budget}")
                self.ocr_o3.setText(str(total))
            else:
                self.ocr_o1.setText("0")
                self.ocr_o2.setText(f"{int(self.ctx.settings['ocr_daily_page_budget'])}")
                self.ocr_o3.setText("0")
        except Exception:
            self.ocr_o1.setText("—")
            self.ocr_o2.setText("—")
            self.ocr_o3.setText("—")

        # 模型状态
        try:
            stamp = self.ctx.ocr.engine.version_stamp
            self.model_status.setText("可用")
            self.model_path.setText(stamp[:32] + "..." if len(stamp) > 32 else stamp)
        except Exception:
            self.model_status.setText("不可用（未装可选层）")
            self.model_path.setText("—")

    def add_root(self) -> None:
        """添加监测目录（暂不实现，等阶段 4 的归档目标根一起定）。"""
        QtWidgets.QMessageBox.information(
            self, "添加监测目录",
            "此功能将在阶段 4 落地时实现。\n"
            "当前监测目录只能通过配置文件修改。"
        )

    def remove_root(self) -> None:
        """移除监测目录（暂不实现）。"""
        QtWidgets.QMessageBox.information(
            self, "移除监测目录",
            "此功能将在阶段 4 落地时实现。"
        )
