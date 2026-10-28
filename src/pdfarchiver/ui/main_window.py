"""主窗口外壳：左导航 + 右页面 + 状态栏。

这不是任何一屏的布局方案：右侧页面由 `ui/nav.py` 注册表决定，阶段 1 只有一页有内容。
最小窗口 **1024×720** 是 **D-039** 定的（`[约定]`），默认开在 **1280×800** ——
那是 p3 唯一有实测证据的布局档，也正是 S1 三栏刚好放得下的那一档（算术见
`ui/pages/library_page.py`，降级形状是 **D-040**）。这条地板同时销掉 **ISSUES I52**
（原来"不设最小窗宽"，窗口压到 900 以下时侧栏被一路榨瘪到 56px）。

关窗必须真的把数据库连接关掉并留下对账行，否则"能启动能关闭"只是看起来成立。
"""
from __future__ import annotations

import logging

from PySide6 import QtCore, QtGui, QtWidgets

from pdfarchiver import __version__
from pdfarchiver.services.bootstrap import AppContext
from pdfarchiver.ui.nav import NAV_ITEMS, NavItem
from pdfarchiver.ui.pages.archive_page import ArchivePage
from pdfarchiver.ui.pages.ask_page import AskPage
from pdfarchiver.ui.pages.backup_page import BackupPage
from pdfarchiver.ui.pages.categories_page import CategoriesPage
from pdfarchiver.ui.pages.dedup_page import DedupPage
from pdfarchiver.ui.pages.library_page import LibraryPage
from pdfarchiver.ui.pages.operations_page import OperationsPage
from pdfarchiver.ui.pages.pending_page import PendingPage
from pdfarchiver.ui.pages.reader_page import ReaderPage
from pdfarchiver.ui.pages.settings_page import SettingsPage
from pdfarchiver.ui.theme import ThemeManager

log = logging.getLogger("pdfarchiver.ui")

# D-039 [约定]：最小窗口 1024×720。默认开在 1280×800 —— 线框就是按这一档画的，
# 且 S1 的三栏（236 + 480 + 360 = 1076）加上 200px 导航刚好在这档放得下。
MIN_WINDOW_WIDTH = 1024
MIN_WINDOW_HEIGHT = 720
DEFAULT_WINDOW_WIDTH = 1280
DEFAULT_WINDOW_HEIGHT = 800

# 导航栏宽度。布局守卫（`tests/integration/test_ui_layout.py`）拿它算"一屏还能用多宽"，
# 所以它是外壳的口径，不是测试里写死的第二个数。侧栏不参与 D-040 的降级授权 ——
# 宽度不足时牺牲的是 S1 的右栏，不是这里。
NAV_WIDTH = 200

# 导航项对应的 Unicode 图标
_NAV_ICONS: dict[str, str] = {
    "library": "\U0001f4c1",      # 📁 文档库
    "search": "\U0001f50d",       #  检索
    "ask": "\U0001f4ac",          # 💬 库内问答
    "reader": "\U0001f4d6",       #  PDF 阅读
    "archive": "\U0001f4e6",      # 📦 归档预览
    "operations": "\U0001f4dd",   # 📝 操作日志
    "duplicates": "\U0001f504",   # 🔄 重复检测
    "monitor": "\U00002699\ufe0f", # ️ 监测设置
    "categories": "\U0001f3f7\ufe0f", # 🏷️ 分类标签
    "backup": "\U0001f4be",       # 💾 备份恢复
}


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self, ctx: AppContext, cold_start_seconds: float | None = None) -> None:
        super().__init__()
        self.ctx = ctx
        self._cold_start = cold_start_seconds
        self._pages: dict[str, QtWidgets.QWidget] = {}
        self.setWindowTitle(f"PDF 归档工具 v{__version__}")
        self.setMinimumSize(MIN_WINDOW_WIDTH, MIN_WINDOW_HEIGHT)  # D-039；同时是 I52 的甲案
        self.resize(DEFAULT_WINDOW_WIDTH, DEFAULT_WINDOW_HEIGHT)

        # 主题管理
        self.theme = ThemeManager()
        saved_theme = ctx.app_settings.get("ui.theme", ThemeManager.LIGHT)
        self.theme.set_theme(saved_theme)

        split = QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal)
        self.nav = QtWidgets.QListWidget()
        self.nav.setObjectName("navList")
        self.nav.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.SingleSelection)
        self.nav.setIconSize(QtCore.QSize(18, 18))
        for item in NAV_ITEMS:
            icon = _NAV_ICONS.get(item.page_id, "")
            self.nav.addItem(f"  {icon}  {item.title}")
        self.stack = QtWidgets.QStackedWidget()
        split.addWidget(self.nav)
        split.addWidget(self.stack)
        split.setStretchFactor(1, 1)
        split.setSizes([NAV_WIDTH, DEFAULT_WINDOW_WIDTH - NAV_WIDTH])
        self.setCentralWidget(split)
        self.nav.currentRowChanged.connect(self._on_nav_changed)

        self._build_menus()
        self._apply_theme()
        self.statusBar().showMessage(self._status_text())
        # 状态栏右侧常驻一格「全库同步到哪个时刻」（轮三十六 乙，线框 §C 甲）。
        # 挂在 permanent 区而不是走 `showMessage`：临时区是巡检每 5 秒要覆盖的地方
        # （`patrol_tick` 那句「巡检：…」），写进去的同步读数只活几秒就被冲掉 ——
        # 而它是"我改的文件进库了没有"的唯一常驻读数。
        self.sync_label = QtWidgets.QLabel()
        self.sync_label.setObjectName("muted")
        self.statusBar().addPermanentWidget(self.sync_label)
        self.refresh_sync_cell()

        # Ctrl+F = S1 搜索框的键盘入口（**ISSUES I53** ③甲，2026-10-17 定案，见 **D-052**）。
        # 挂在外壳而不是页面里：焦点停在导航列表时按 Ctrl+F 也该有用，而
        # `WidgetWithChildrenShortcut` 那种情况下根本不触发。判据只有一条「当前屏是 S1」——
        # 不做跨屏跳转，那等于新增一条线框里没有、屏幕上也看不见的导航。
        self.search_shortcut = QtGui.QShortcut(QtGui.QKeySequence("Ctrl+F"), self)
        self.search_shortcut.activated.connect(self._focus_library_search)

        self._select_by_page_id(ctx.session.last_nav_page() or NAV_ITEMS[0].page_id)

    # ---- 跨页动作 ----

    def _focus_library_search(self) -> None:
        if isinstance(self.stack.currentWidget(), LibraryPage):
            self.stack.currentWidget().focus_search()

    def _open_in_reader(self, payload: tuple[int, int | None]) -> None:
        """S1 的「跳到该页 → S2」与双击文档行都走这里（`page_no` 为 None = 从当前页开）。"""
        doc_id, page_no = payload
        self._select_by_page_id("reader")
        self._pages["reader"].open_document(doc_id, page_no=page_no)

    def _play_collection(self, entry) -> None:
        """S8 双击一条智能集合 → 切到 S1 并回放它存的那份条件（**ISSUES I78** 乙）。

        条件本身由 `FilterBar.apply_query` 灌进顶栏的 chips，所以这一屏显示的排就是那条集合
        存的排 —— 不在这里另拼一份 WHERE，也不在这儿数命中（那个数在 S8 那一行上，同一份
        `CollectionEntry` 带过来的）。
        """
        self._select_by_page_id("library")
        self._pages["library"].apply_saved(entry)

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

        view_menu.addSeparator()
        self._theme_action = QtGui.QAction("切换到暗色模式", self)
        self._theme_action.triggered.connect(self._toggle_theme)
        view_menu.addAction(self._theme_action)

    def _apply_theme(self) -> None:
        """将当前主题的 QSS 应用到整个应用。"""
        qss = self.theme.generate_qss()
        self.setStyleSheet(qss)
        # 占位色不走 QSS，必须单独设进调色板（`ThemeManager.apply_palette`，ISSUES I50 乙）
        self.theme.apply_palette(self)
        # 更新菜单文字
        label = "切换到浅色模式" if self.theme.theme == ThemeManager.DARK else "切换到暗色模式"
        self._theme_action.setText(label)
        # 持久化
        try:
            self.ctx.app_settings.set("ui.theme", self.theme.theme)
        except Exception:
            log.exception("保存主题偏好失败")

    def _toggle_theme(self) -> None:
        self.theme.toggle()
        self._apply_theme()

    def _make_page(self, item: NavItem) -> QtWidgets.QWidget:
        if item.page_id == "monitor":
            return SettingsPage(self.ctx, cold_start_seconds=self._cold_start)
        if item.page_id == "categories":
            page = CategoriesPage(self.ctx)
            # S8 右栏双击一条集合 → 由外壳切到 S1 回放（同一个做法：页面只发信号，不认识外壳）。
            page.play_requested.connect(self._play_collection)
            return page
        if item.page_id == "library":
            page = LibraryPage(self.ctx)
            # 命中面板的「跳到该页」与表格双击都发这个信号；接收方在这里，页面不必知道外壳的存在。
            page.open_in_reader.connect(self._open_in_reader)
            return page
        if item.page_id == "ask":
            page = AskPage(self.ctx)
            # S9 证据卡双击 → S2：与 S1 同一份 `_open_in_reader` 载荷口径（doc_id, page_no）。
            page.open_in_reader.connect(self._open_in_reader)
            return page
        if item.page_id == "reader":
            return ReaderPage(self.ctx)
        if item.page_id == "archive":
            return ArchivePage(self.ctx)
        if item.page_id == "operations":
            return OperationsPage(self.ctx)
        if item.page_id == "duplicates":
            return DedupPage(self.ctx)
        if item.page_id == "backup":
            return BackupPage(self.ctx)
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
            # 页面惰性创建，晚于启动时那次 `_apply_theme` —— 占位色只有设在控件自身才
            # 上屏（父控件 / 应用级实测被 QSS 覆盖），所以每建一页补设一次。**ISSUES I50**
            self.theme.apply_palette(page)
            self._pages[item.page_id] = page
            self.stack.addWidget(page)
        self.stack.setCurrentWidget(page)
        self.ctx.session.remember_nav_page(item.page_id)  # 立刻落库：重启后要能回到这一项
        self.statusBar().showMessage(self._status_text())

    def _refresh_current(self) -> None:
        page = self.stack.currentWidget()
        if isinstance(page, SettingsPage):
            page.reload_status()
            page.reload_settings()
        elif isinstance(page, CategoriesPage):
            page.reload()
        elif isinstance(page, LibraryPage):
            page.reload()
        elif isinstance(page, AskPage):
            page.reload()
        elif isinstance(page, DedupPage):
            page.reload()
        elif isinstance(page, BackupPage):
            page.reload()
        else:
            self.statusBar().showMessage("当前页没有可刷新的内容")

    def _status_text(self) -> str:
        return f"{self.ctx.paths.describe()}｜结构版本 {self.ctx.schema_version}"

    def refresh_sync_cell(self) -> None:
        """重算状态栏右侧那一格。每次都是新查询、不缓存 —— 与巡检节拍同一个纪律。

        读数口径全在 `StatusService.sync_status()`：取各启用根里**最早**的那一刻，
        所以"还有根没对过账"不会被子虚乌有地说成"同步到了今天"。
        """
        self.sync_label.setText(self.ctx.status.sync_status().summary())

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
        # 起定时器当场先跑一轮（轮三十六 乙）。`QTimer.start` 的第一次触发要等一个完整间隔
        # （默认 5 秒），而"上次关掉到现在磁盘上变了什么"是最该立刻知道的那件事 ——
        # `Patrol.poll()` 的第一轮必定排一场全量对账，晚 5 秒起步就白等 5 秒；
        # 这一轮顺带把状态栏那一格与 S7 的读数铺成当前值。
        self.patrol_tick()

    def patrol_tick(self) -> None:
        """一次轮询。异常在这里挡住：定时器一旦因为一轮失败而停摆，此后所有文件事件都没人管了。"""
        try:
            report = self.ctx.patrol.poll()
        except Exception as exc:  # noqa: BLE001 - 边界：巡检要碰磁盘和库，任何异常都得留下原文并让定时器活着
            log.exception("巡检轮询失败，定时器继续跑，下一轮还会试")
            self.statusBar().showMessage(f"巡检出错：{type(exc).__name__}: {exc}")
            return
        # 状态栏那一格跟着同一个节拍重算（轮三十六 乙）：排完队/跑完一轮之后，
        # 「同步到哪个时刻」与「同步中/空闲」当场跟着变，不停在上一个时刻。
        self.refresh_sync_cell()
        settings_page = self._pages.get("monitor")
        if isinstance(settings_page, SettingsPage) and settings_page.isVisible():
            # 这一条同时管住了状态读数：状态页现在是 S7 的上半区（D-040），
            # `reload_status()` 就是让那块控件重查一遍 —— 少这一行，界面上的进度会停在
            # 一个已经过去的时刻，而 worker 线程一直在推进度。
            # 它走的是状态页的**轻版本**：下面判重页那条理由在这里同样成立，而且更严重 ——
            # 「库里已存 OCR 正文」那一格要扫正文全表（真库实测 ~200s），挂在这个 5 秒节拍上
            # 等于每 tick 把界面线程按住几分钟，所以它只由状态块上那颗按钮现数（**ISSUES I109** 丙）。
            settings_page.reload_status()
            settings_page.reload_settings()
        duplicates_page = self._pages.get("duplicates")
        if isinstance(duplicates_page, DedupPage) and duplicates_page.isVisible():
            # 只刷进度那一行，不调整页 `reload()`：那一页的组表要查 500 组、每组再查一次成员，
            # 挂在一个 5 秒一次的定时器上等于每 tick 做一次接近全量的重查。
            duplicates_page.reload_progress()
        if report.did_anything:
            self.statusBar().showMessage("巡检：" + report.summarize())

    # ---- 生命周期 ----

    def set_cold_start_seconds(self, seconds: float) -> None:
        """由组合根在窗口就绪后回填，再刷进 S7 上半区那张状态页。

        放在构造参数里会漏掉窗口自身的构建耗时。状态页现在不是独立的一屏了（**D-040**），
        但它仍是同一个控件嵌在 `monitor` 里，所以这一条只换了去找它的路线，读数口径没变。
        """
        self._cold_start = seconds
        page = self._pages.get("monitor")
        if isinstance(page, SettingsPage):
            page.status_page.cold_start_seconds = seconds
            page.reload_status()

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
