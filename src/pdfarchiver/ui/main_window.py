"""主窗口外壳：左导航 + 右页面 + 状态栏。

这不是任何一屏的布局方案：右侧页面由 `ui/nav.py` 注册表决定，阶段 1 只有一页有内容。
不设最小窗口宽度（那个数值是 Q7 里由你定的，我不替你猜），不做主题、不做图标。

关窗必须真的把数据库连接关掉并留下对账行，否则"能启动能关闭"只是看起来成立。
"""
from __future__ import annotations

import logging

from PySide6 import QtCore, QtGui, QtWidgets

from pdfarchiver import __version__
from pdfarchiver.services.bootstrap import AppContext
from pdfarchiver.ui.nav import NAV_ITEMS, NavItem
from pdfarchiver.ui.pages.pending_page import PendingPage
from pdfarchiver.ui.pages.status_page import StatusPage

log = logging.getLogger("pdfarchiver.ui")


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self, ctx: AppContext, cold_start_seconds: float | None = None) -> None:
        super().__init__()
        self.ctx = ctx
        self._cold_start = cold_start_seconds
        self._pages: dict[str, QtWidgets.QWidget] = {}
        self.setWindowTitle(f"PDF 归档工具 v{__version__}")
        self.resize(1000, 680)

        split = QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal)
        self.nav = QtWidgets.QListWidget()
        self.nav.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.SingleSelection)
        for item in NAV_ITEMS:
            self.nav.addItem(f"{item.title}（SPEC {item.spec}）"
                             + ("" if item.implemented else " · 未实现"))
        self.stack = QtWidgets.QStackedWidget()
        split.addWidget(self.nav)
        split.addWidget(self.stack)
        split.setStretchFactor(1, 1)
        self.setCentralWidget(split)
        self.nav.currentRowChanged.connect(self._on_nav_changed)

        self._build_menus()
        self.statusBar().showMessage(self._status_text())

        self._select_by_page_id(ctx.session.last_nav_page() or NAV_ITEMS[0].page_id)

    # ---- 构建 ----

    def _build_menus(self) -> None:
        file_menu = self.menuBar().addMenu("文件")
        quit_action = QtGui.QAction("退出", self)
        quit_action.setShortcut(QtGui.QKeySequence.StandardKey.Quit)
        quit_action.triggered.connect(self.close)
        file_menu.addAction(quit_action)

        view_menu = self.menuBar().addMenu("视图")
        refresh = QtGui.QAction("刷新状态", self)
        refresh.setShortcut(QtGui.QKeySequence.StandardKey.Refresh)
        refresh.triggered.connect(self._refresh_current)
        view_menu.addAction(refresh)

    def _make_page(self, item: NavItem) -> QtWidgets.QWidget:
        if item.page_id == "status":
            return StatusPage(self.ctx, cold_start_seconds=self._cold_start)
        return PendingPage(item)

    # ---- 导航 ----

    def _select_by_page_id(self, page_id: str) -> None:
        index = next((i for i, item in enumerate(NAV_ITEMS) if item.page_id == page_id), 0)
        self.nav.setCurrentRow(index)

    def _on_nav_changed(self, row: int) -> None:
        if row < 0 or row >= len(NAV_ITEMS):
            return
        item = NAV_ITEMS[row]
        page = self._pages.get(item.page_id)
        if page is None:
            page = self._make_page(item)
            self._pages[item.page_id] = page
            self.stack.addWidget(page)
        self.stack.setCurrentWidget(page)
        self.ctx.session.remember_nav_page(item.page_id)  # 立刻落库：重启后要能回到这一项
        self.statusBar().showMessage(self._status_text())

    def _refresh_current(self) -> None:
        page = self.stack.currentWidget()
        if isinstance(page, StatusPage):
            page.reload()
        else:
            self.statusBar().showMessage("当前页没有可刷新的内容")

    def _status_text(self) -> str:
        return f"{self.ctx.paths.describe()}｜结构版本 {self.ctx.schema_version}"

    # ---- 后台巡检 ----

    def start_patrol(self) -> None:
        """把巡检器接到界面线程的定时器上（SPEC 阶段 2 第 5 条的其中一条腿）。

        间隔取 `patrol.poll_seconds`，不另读一遍设置：那是 `bootstrap` 已经按设置算好的同一个数，
        这里再乘一次 1000 之外的任何解释都会变成第二个口径。
        定时器每 tick 只做"取事件 + 排任务"，目录走查和正文抽取都在 worker 线程里，
        界面线程一次都不能等（`services/patrol.py` 分工）。
        """
        timer = QtCore.QTimer(self)
        timer.timeout.connect(self.patrol_tick)
        timer.start(int(self.ctx.patrol.poll_seconds * 1000))
        self._patrol_timer = timer

    def patrol_tick(self) -> None:
        """一次轮询。异常在这里挡住：定时器一旦因为一轮失败而停摆，此后所有文件事件都没人管了。"""
        try:
            report = self.ctx.patrol.poll()
        except Exception as exc:  # noqa: BLE001 - 边界：巡检要碰磁盘和库，任何异常都得留下原文并让定时器活着
            log.exception("巡检轮询失败，定时器继续跑，下一轮还会试")
            self.statusBar().showMessage(f"巡检出错：{type(exc).__name__}: {exc}")
            return
        page = self._pages.get("status")
        if isinstance(page, StatusPage) and page.isVisible():
            page.reload()  # 没有事件时也要重查：worker 线程一直在推进度
        if report.did_anything:
            self.statusBar().showMessage("巡检：" + report.summarize())

    # ---- 生命周期 ----

    def set_cold_start_seconds(self, seconds: float) -> None:
        """由组合根在窗口就绪后回填，再刷进状态页。放在构造参数里会漏掉窗口自身的构建耗时。"""
        self._cold_start = seconds
        page = self._pages.get("status")
        if isinstance(page, StatusPage):
            page.cold_start_seconds = seconds
            page.reload()

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:  # noqa: N802 - Qt 命名
        try:
            row = self.nav.currentRow()
            if 0 <= row < len(NAV_ITEMS):
                self.ctx.session.remember_nav_page(NAV_ITEMS[row].page_id)
        except Exception:  # noqa: BLE001 - 关闭路径上任何异常都不能拦住退出；现场已由 excepthook 记录
            log.exception("关闭时写入导航记忆失败，不影响退出")
        self.ctx.shutdown()
        super().closeEvent(event)

    def current_item(self) -> NavItem | None:
        """当前选中的导航项。测试和状态栏都靠它，不另设第二套口径。"""
        row = self.nav.currentRow()
        return NAV_ITEMS[row] if 0 <= row < len(NAV_ITEMS) else None
