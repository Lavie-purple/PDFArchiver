"""S7 设置 · 监测与索引 —— 上下分区（甲 · 2026-10-15 定案）。

上半区 = StatusPage 现有内容（运行时 / 设置 / 数据库 / 任务读数），一字不改搬过来。
下半区 = 设置 UI：监测目录管理、索引设置、OCR 三读数、模型状态；**同一块区域里还有第二页
「库体检」**（#198 · 1甲，2026-10-24）—— 翻页而不是另开窗口，上半区那张状态页始终在场。

**上半区是真的把 `StatusPage` 那个控件嵌进来，不是再抄一份渲染代码**（**D-040** 第三条后果）。
先前这里自己拼了一遍 `== 运行时 == / == 数据库 == / …`，两份代码已经漂掉了：状态页结尾那句
"OCR 后端已交付……语义搜索……还没实现"在这里就没有。**同一份读数在两个地方各拼一遍，
就是"核心概念多个口径"** —— 所以这一屏嵌控件，不嵌副本。

数据全部来自 `AppContext` 的真查询，页面里没有写死的数字。
"""
from __future__ import annotations

from PySide6 import QtCore, QtGui, QtWidgets

from pdfarchiver.services.bootstrap import AppContext
from pdfarchiver.services.db_check import LAST_KEY, MODE_LABELS, format_duration
from pdfarchiver.services.status_service import format_ts
from pdfarchiver.ui.empty_state import make_hint, sync_hint
from pdfarchiver.ui.pages.health_panel import HealthPanel
from pdfarchiver.ui.pages.status_page import StatusPage


class SettingsPage(QtWidgets.QWidget):
    """S7：上半区状态 + 下半区设置。"""

    #: 重开首启引导 —— 页面只发信号，不认识外壳（与 S1 `open_in_reader`、S8 `play_requested` 同形状）
    replay_onboarding = QtCore.Signal()

    def __init__(self, ctx: AppContext, cold_start_seconds: float | None = None,
                 parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.ctx = ctx

        splitter = QtWidgets.QSplitter(QtCore.Qt.Orientation.Vertical)

        # 上半区：那张状态页本身（D-040 —— 嵌控件，不重画一份读数）
        self.status_page = StatusPage(self.ctx, cold_start_seconds=cold_start_seconds)

        # 下半区：设置 UI + 库体检（#198 1甲 —— 同一块区域翻页，不另开窗口）
        lower = QtWidgets.QWidget()
        lower_lay = QtWidgets.QVBoxLayout(lower)
        lower_lay.setContentsMargins(8, 8, 8, 8)

        header = QtWidgets.QHBoxLayout()
        self.lower_title = QtWidgets.QLabel("监测与索引")
        self.lower_title.setObjectName("sectionTitle")
        header.addWidget(self.lower_title)
        header.addStretch()
        self.health_toggle_btn = QtWidgets.QPushButton("库体检…")
        self.health_toggle_btn.setToolTip("就地打开库体检（不另开窗口）；上半区的状态读数一直还在")
        self.health_toggle_btn.clicked.connect(self._toggle_lower)
        header.addWidget(self.health_toggle_btn)
        # 重开首启引导（轮四十三 甲：向导里「以后不再显示」勾了之后，这是唯一能把三屏再调出来的入口）
        self.replay_onboarding_btn = QtWidgets.QPushButton("首次引导…")
        self.replay_onboarding_btn.setToolTip("重开首次使用引导的三个步骤")
        self.replay_onboarding_btn.clicked.connect(self.replay_onboarding)
        header.addWidget(self.replay_onboarding_btn)
        lower_lay.addLayout(header)

        self.settings_view = QtWidgets.QWidget()
        settings_lay = QtWidgets.QVBoxLayout(self.settings_view)
        settings_lay.setContentsMargins(0, 0, 0, 0)

        # 监测目录
        roots_group = QtWidgets.QGroupBox("监测目录")
        roots_lay = QtWidgets.QVBoxLayout(roots_group)
        # ⑱ 空态（**D-066**）：这一栏开局就是空的，而「空」在这里的含义最重 —— 一条都没登记
        # 就等于整个程序没有任何东西可索引。出路只指界面上真存在的那颗按钮。
        self.roots_hint = make_hint(
            "还没有登记监测目录：点下面「添加目录」告诉程序要整理哪个文件夹 —— "
            "一条都没登记，文档表就永远不会出现任何文档。", roots_group)
        roots_lay.addWidget(self.roots_hint)
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
        settings_lay.addWidget(roots_group)

        # OCR 三读数
        ocr_group = QtWidgets.QGroupBox("OCR 读数（O1 / O2 / O3）")
        ocr_lay = QtWidgets.QFormLayout(ocr_group)
        self.ocr_o1 = QtWidgets.QLabel("—")
        self.ocr_o2 = QtWidgets.QLabel("—")
        self.ocr_o3 = QtWidgets.QLabel("—")
        ocr_lay.addRow("O1 · 今日已识别页数:", self.ocr_o1)
        ocr_lay.addRow("O2 · 预算剩余:", self.ocr_o2)
        ocr_lay.addRow("O3 · 累计识别页数:", self.ocr_o3)
        settings_lay.addWidget(ocr_group)

        # 模型状态
        model_group = QtWidgets.QGroupBox("模型状态")
        model_lay = QtWidgets.QFormLayout(model_group)
        self.model_status = QtWidgets.QLabel("—")
        self.model_path = QtWidgets.QLabel("—")
        # 版本戳/路径这类整串不换行会把下半区的最低宽度顶起来（实测 455px）
        self.model_path.setWordWrap(True)
        model_lay.addRow("状态:", self.model_status)
        model_lay.addRow("路径:", self.model_path)
        settings_lay.addWidget(model_group)

        settings_lay.addStretch()

        self.health_panel = HealthPanel(self.ctx)
        self.health_panel.finished.connect(lambda _report: self.reload_last_check())

        # 两页一起放进 stack：切页不改下半区的高度（QStackedWidget 的 sizeHint 取两页最大值），
        # 否则用户点一次「库体检」上半区那张状态页就会跟着跳一下。
        self.lower_stack = QtWidgets.QStackedWidget()
        self.lower_stack.addWidget(self.settings_view)
        self.lower_stack.addWidget(self.health_panel)
        lower_lay.addWidget(self.lower_stack, 1)

        splitter.addWidget(self.status_page)
        splitter.addWidget(lower)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1)
        # **ISSUES I75**：这两行只管"窗口变高时多出来的高度怎么分"，**不管初始分配** ——
        # 实测 720 / 800 / 1409 三个窗高下上半区恒拿 36%，正是两栏 sizeHint 258/447 的比例。
        # 初始分配由下面的 `_balance_split_by_content()` 在每次尺寸变化时按内容重算。
        self._splitter = splitter
        self._lower = lower
        #: 用户亲手拖过分隔条之后不再自动改分配（否则他每次缩放窗口都被抢回去）
        self._split_locked = False
        #: 自己调 `setSizes` 也会触发 `splitterMoved`，用它把那次自转标出来
        self._rebalancing = False
        splitter.splitterMoved.connect(self._on_splitter_moved)

        main_lay = QtWidgets.QVBoxLayout(self)
        main_lay.setContentsMargins(0, 0, 0, 0)
        main_lay.addWidget(splitter)

        self.reload_status()
        self.reload_settings()

    def _on_splitter_moved(self, *_args) -> None:
        if not self._rebalancing:
            self._split_locked = True

    def _toggle_lower(self) -> None:
        if self.lower_stack.currentWidget() is self.health_panel:
            self.show_settings()
        else:
            self.show_health()

    def show_health(self) -> None:
        """就地翻到「库体检」页（#198 1甲）。上半区不动。"""
        self.lower_stack.setCurrentWidget(self.health_panel)
        self.lower_title.setText("库体检")
        self.health_toggle_btn.setText("← 返回设置")
        self._balance_split_by_content()

    def show_settings(self) -> None:
        self.lower_stack.setCurrentWidget(self.settings_view)
        self.lower_title.setText("监测与索引")
        self.health_toggle_btn.setText("库体检…")
        self._balance_split_by_content()

    def reload_last_check(self) -> None:
        """4甲 的界面半边：只显示上次体检的时间与三个计数，明细不在库里。

        `format_ts` 是全站唯一的时间出口（UTC + `Z`）；`format_duration` 是时长不是时刻，
        两者别混用。没有记录时明说「还没有跑过」，不拿 `—` 冒充一个数。
        """
        try:
            payload = self.ctx.app_settings.get(LAST_KEY)
        except Exception:
            payload = None
        if not isinstance(payload, dict) or "ts" not in payload:
            self.health_panel.set_last_check("上次体检：还没有跑过（本页不会自动体检）")
            return
        mode = MODE_LABELS.get(str(payload.get("mode")), str(payload.get("mode", "—")))
        self.health_panel.set_last_check(
            f"上次体检：{format_ts(int(payload['ts']))}｜{mode}｜"
            f"共 {int(payload.get('total', 0))} 项｜未通过 {int(payload.get('red', 0))}｜"
            f"读数 {int(payload.get('readings', 0))}｜"
            f"用时 {format_duration(float(payload.get('elapsed_s', 0)))}")

    def resizeEvent(self, event: QtGui.QResizeEvent) -> None:
        super().resizeEvent(event)
        self._balance_split_by_content()

    def _balance_split_by_content(self) -> None:
        """上半区按**内容**要高，下半区按**能不能滚**让路（**ISSUES I75**）。

        规则只有一条：下半区（三个分组、没有滚动条）先拿它想要的高；不够分时它朝自己的
        `minimumSizeHint` 退，退出来的每一像素都给上半区（那张状态页带滚动条，看不完可以滚，
        但被压到看不见的任务/故障读数等于没有 —— 正是这一屏存在的理由）。
        所以**永远不出现"两栏比例固定、一边全是空白另一边是窄缝"**。
        """
        if self._split_locked:
            return
        avail = self._splitter.height() - self._splitter.handleWidth()
        if avail <= 0:
            return
        view = self.status_page.view
        line_h = view.fontMetrics().height()
        if line_h <= 0:
            return
        # 上半区"一屏看全"要多高 = 行数 × 行高 + 这条链上的固定开销（标题/标签/边距/边框）
        chrome = max(self.status_page.height() - view.viewport().height(), 0)
        need_upper = view.document().blockCount() * line_h + chrome
        need_lower = self._lower.sizeHint().height()
        min_lower = self._lower.minimumSizeHint().height()
        deficit = need_upper + need_lower - avail
        lower_get = need_lower if deficit <= 0 else max(need_lower - deficit, min_lower)
        upper_get = max(avail - lower_get, 0)
        if self._splitter.sizes()[:2] == [upper_get, avail - upper_get]:
            return
        self._rebalancing = True
        try:
            self._splitter.setSizes([upper_get, avail - upper_get])
        finally:
            self._rebalancing = False

    def reload_status(self) -> None:
        """重渲染上半区 —— 就是让那张状态页自己重查一遍库，这里不留第二份查询。

        走的是**轻版本**（`reload_progress()`）：这条被 5 秒巡检节拍和建窗路径调用，
        不能在里面放那条全库正文扫描（**ISSUES I109** 丙）。要那个数请按上半区那颗按钮。
        """
        self.status_page.reload_progress()

    def reload_settings(self) -> None:
        """重查下半区的设置读数。"""
        # 监测目录：`root_key` 存在 item 的 UserRole 里，不靠回解显示串
        self.roots_list.clear()
        enabled = {r.root_key for r in self.ctx.roots.list_enabled()}
        for root in self.ctx.roots.list():
            status = "" if root.root_key in enabled else " [已禁用]"
            item = QtWidgets.QListWidgetItem(f"{root.root_path}{status}")
            item.setData(QtCore.Qt.ItemDataRole.UserRole, root.root_key)
            item.setToolTip(f"登记键：{root.root_key}")
            self.roots_list.addItem(item)
        sync_hint(self.roots_list)

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

        self.reload_last_check()

    def add_root(self) -> None:
        """登记一个监测根。真写库：走 `ctx.register_root`，它同时负责挂上文件监听。

        这里不许直接 `ctx.roots.add(...)`：漏掉 `watch()` 的话新登记的根只有周期校验在管、
        实时事件一条收不到，而界面上完全看不出来（**ISSUES I5** 那一族"看着对、其实没接"）。
        """
        raw = QtWidgets.QFileDialog.getExistingDirectory(self, "选择要监测的目录")
        if not raw:
            return
        try:
            self.ctx.register_root(raw)
        except Exception as exc:  # 用户挑的目录可能正好读不动（断网盘、权限）—— 回显原文，不吞
            QtWidgets.QMessageBox.critical(self, "添加监测目录失败", str(exc))
            return
        self.reload_settings()

    def remove_root(self) -> None:
        """移除选中的监测根：只撤监测配置，磁盘文件不动，库里的文档记录与分类标注也不删。"""
        item = self.roots_list.currentItem()
        if item is None:
            QtWidgets.QMessageBox.information(self, "移除监测目录", "先在列表里选中一个目录。")
            return
        answer = QtWidgets.QMessageBox.question(
            self, "移除监测目录",
            "移除只是不再监测这个目录：\n"
            "磁盘上的文件不动，库里已登记的文档记录与分类标注也不删。\n"
            "要重新监测，再点「添加目录...」选它一次就行。\n\n确定移除？")
        if answer != QtWidgets.QMessageBox.StandardButton.Yes:
            return
        self.ctx.unregister_root(item.data(QtCore.Qt.ItemDataRole.UserRole))
        self.reload_settings()
