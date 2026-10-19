"""S1 主窗口 · 库视图与搜索结果面板 —— 甲·甲·甲（2026-10-15 定案）。

三栏布局（**宽档**，页面可用宽度 ≥ 1076）：
- 左栏：分类树（用于筛选）
- 中栏：文档表格（支持四通道检索）
- 右栏：**命中面板（当前查询）** —— 按通道分组、每条带页码与片段（**ISSUES I53** ②甲，2026-10-17）；
  同一栏的下半部是选中那一行的文档详情 + AI 推荐分类。

**窄档的形状是 D-040 定下来的，不是这里的偏好**：线框 §S1 的算术
`236 + 480 + 360 = 1076 > 1024` ⇒ 三栏放不下，**必须且只牺牲右栏** ——
搜索是"要结果时才看结果"，分类树是"随时知道我在库的哪个位置"。于是：

- 右栏变成 **420px 浮层**（可关；默认关，不记忆成"每次都开"）；
- 左栏收成 **48px 的条**（条上一颗「分类」按钮，点开是真树浮层），整棵树改由那一条唤出；
- 中栏吃掉剩余宽度。

键盘入口 = **Ctrl+F**（聚焦搜索框并唤出右栏；定案见 **D-052**，短路挂在外壳上，
判据是"当前屏是不是 S1"，不做跨屏跳转）。

两档的切换机械不在本文件里，在 `ui/tier.py` —— **D-039** 要求 S8 的树侧栏在 1024 档
收起同一把尺子，AGENTS.md「禁止同类问题逐个打补丁」，所以一条规则两处用。

行高必须统一（D-040 表里第一行的形状）：虚拟化要按 O(1) 做行号↔坐标换算，
一旦变成"命中展开把行撑高"就得整表测高 —— 8 万行档就是 O(n²)，AGENTS.md 明令禁止。

中栏那一列是**一批一批取**的（**ISSUES I51**）：每批 `DEFAULT_PAGE_SIZE` 行，滚到底补下一批，
线框 §S1 甲 那一句「只渲染视口内 ~25 行；滚到底再取下一批 50 条」就是这一段的规格。
批次大小不在本文件里定数 —— 它是检索层 `Criteria.limit` 的默认值，写两处就有第二个口径。

表格底下那一颗「送去识别」（**ISSUES I67** 甲，2026-10-19）是产品里 `request_ocr` 的
**第一个调用点**：此前 OCR 只能由 `gates/stage5.py` 与测试点名，S7 只有三个读数。

数据来自 `AppContext.search`、`AppContext.documents`、`AppContext.catalog`、`AppContext.ocr`。
"""
from __future__ import annotations

from PySide6 import QtCore, QtGui, QtWidgets

from pdfarchiver.services.bootstrap import AppContext
from pdfarchiver.services.status_service import format_ts
from pdfarchiver.ui.format import format_bytes as _format_size
from pdfarchiver.ui.table_layout import CELL_PADDING_WIDTH, set_table_columns
from pdfarchiver.ui.tier import (LEFT_COLUMN_WIDTH, RIGHT_COLUMN_WIDTH,
                                 FloatablePanel, sync_tier)


def _tint(label: QtWidgets.QLabel, role: str) -> None:
    """把标签的文字角色挂到 objectName 上，由 `ui/theme.py` 的令牌决定颜色。

    改 objectName 后必须 unpolish/polish，否则 Qt 沿用已经算好的旧样式。
    """
    label.setObjectName(role)
    label.style().unpolish(label)
    label.style().polish(label)


# 命中面板每一行挂的两样数据：跳转要用的 doc_id 与页码（`None` = 这一条没有页码）。
_HIT_DOC_ROLE = QtCore.Qt.ItemDataRole.UserRole
_HIT_PAGE_ROLE = QtCore.Qt.ItemDataRole.UserRole + 1


def _mtime_text(doc) -> str:
    """修改时间的显示。没有 mtime 时留空，**不进 `format_ts`** —— 它把 `None` 显示成"从未"，
    而对一份文件的修改时刻来说"从未"是错的读法（那是"不知道"，不是"从来没有"）。
    """
    return format_ts(doc.mtime_ns // 1_000_000_000) if doc.mtime_ns else ""


class LibraryPage(QtWidgets.QWidget):
    """S1：宽档三栏常驻（分类树 | 文档表格 | 命中面板），窄档走 `ui/tier.py` 的降级。"""

    # (doc_id, page_no)；page_no 为 None 表示这一条命中没有页码（文件名/路径/元数据三通道）。
    # 用 tuple 而不是给 page_no 编一个 0 当"没有"，是为了让越界判定只存在于阅读器一处。
    open_in_reader = QtCore.Signal(object)

    def __init__(self, ctx: AppContext, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.ctx = ctx

        self.splitter = QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal)

        # 左栏：分类树。宽档占 splitter 一槽，窄档整块变成浮层、原位留下 48px 的条（D-040）。
        # 条上给的是"2 字按钮 + 真树浮层"而不是每类一枚图标：`Category` 里没有图标字段
        # （`db/models.py:54`）—— 线框那句"图标条"要的产品数据不存在，2026-10-17 按
        # **ISSUES I53** ①甲 定案**把线框改成现在这个形状**（见 `docs/UI-WIREFRAMES.md` §S1 定案记录）。
        self.tree_panel = FloatablePanel(self, "分类筛选",
                                         column_width=LEFT_COLUMN_WIDTH, strip_label="分类")
        self.category_tree = QtWidgets.QTreeWidget()
        self.category_tree.setHeaderHidden(True)
        self.category_tree.itemClicked.connect(self._on_category_clicked)
        self.tree_panel.body.addWidget(self.category_tree, 1)
        # 窄档原先靠弹层菜单里的「显示全部文档」退回全库视图；树现在整块在浮层里，
        # 所以这个入口跟着树走，两档同一处、同一个回调。
        self.show_all_btn = QtWidgets.QPushButton("显示全部")
        self.show_all_btn.setToolTip("清除分类筛选，回到全库视图")
        self.show_all_btn.clicked.connect(self._load_all_documents)
        self.tree_panel.body.addWidget(self.show_all_btn)
        self.tree_panel.attach(self.splitter)

        # 中栏：搜索 + 文档表格
        center = QtWidgets.QWidget()
        center_lay = QtWidgets.QVBoxLayout(center)
        center_lay.setContentsMargins(8, 8, 8, 8)

        # 搜索栏
        search_lay = QtWidgets.QHBoxLayout()
        self.search_input = QtWidgets.QLineEdit()
        self.search_input.setPlaceholderText("输入检索内容...")
        self.search_input.returnPressed.connect(self._do_search)
        # D-040 的浮层触发点："点搜索框 …覆盖在列表右侧 420px，可关"。
        # 键位那半句 2026-10-17 定为 **Ctrl+F**（**ISSUES I53** ③甲 / **D-052**）：短路挂在
        # `ui/main_window.py`（窗口级 accelerator 的归属就该是窗口），落点是下面的
        # `focus_search()` —— 它**显式**唤浮层，不只靠 `FocusIn` 副作用：窗口未激活时
        # `FocusIn` 不保证派发，键盘入口不能"有时候按了没反应"。
        self.search_input.installEventFilter(self)
        search_lay.addWidget(self.search_input, 1)

        # 语义搜索切换
        self.semantic_toggle = QtWidgets.QCheckBox("语义搜索")
        self.semantic_toggle.setToolTip("使用 AI 向量匹配，而非关键词匹配")
        search_lay.addWidget(self.semantic_toggle)

        self.search_btn = QtWidgets.QPushButton("搜索")
        self.search_btn.setObjectName("searchBtn")
        self.search_btn.clicked.connect(self._do_search)
        search_lay.addWidget(self.search_btn)
        self.clear_btn = QtWidgets.QPushButton("清除")
        self.clear_btn.setObjectName("clearBtn")
        self.clear_btn.clicked.connect(self._clear_search)
        search_lay.addWidget(self.clear_btn)
        center_lay.addLayout(search_lay)

        # 文档表格
        self.doc_table = QtWidgets.QTableWidget()
        self.doc_table.setColumnCount(5)
        self.doc_table.setHorizontalHeaderLabels(["文件名", "路径", "大小", "修改时间", "分类"])
        # 定宽按实测内容反算（13px 字体）再**加上单元格内边距**：
        # 大小最宽读数 `1023.9 MB`（9 字符，MB/GB 档在 1024 进位，到不了 10 字符）、
        # 修改时间 `2026-10-16 16:11:00Z`（定宽 20 字符，走 `status_service.format_ts`，
        #   界面唯一出口，整改计划第 7 条勾甲 —— 带 `Z` 之后比原来的 16 字符宽 4×7=28px）、
        # 分类名一段按 5 字算。
        # 上一轮这三列反算的是**文本宽**、给的是 +8，于是显示成 `2026-1…` / `1…` ——
        # 少算了 Qt 单元格实测的 23px 内边距（见 table_layout.CELL_PADDING_WIDTH）。
        # 五列合计 780px（220+200+86+163+111），而视口比它小得多：宽档（页面 1079px）实测
        # 空库 463px、2 行 463px、40 行 455px；地板档（窗口 1024px / 页面 823px）40 行 748px。
        # **行号列已经不在了**（**ISSUES I54**，`set_table_columns` 里 hide），所以读数不随
        # 行号的位数漂；40 行比空库少的那 8px 是**纵向滚动条**（现测 `verticalScrollBar().width()`=8），
        # 那是真占地方。装不装得下还随分档变，所以"超出就必须滚得过去"由
        # `test_ui_layout.test_表格定宽列放不下时必须还能滚到` 在宽档钉住，
        # "视口不随行数漂"由 `test_ui_tier.test_视口宽度只随滚动条变不随行的位数变` 钉住。
        # 不给任何列设 Stretch：定宽列已经把视口吃满时，Stretch 那一列会被压到接近
        # minimumSectionSize（实测「分类」掉到 38px），而且**永远是这一条缝** ——
        # 滚动条能滚（范围按档不按像素），滚过去的还是那个窄条。
        set_table_columns(self.doc_table,
                          {0: 220, 1: 200,
                           2: 63 + CELL_PADDING_WIDTH,
                           3: 140 + CELL_PADDING_WIDTH,
                           4: 88 + CELL_PADDING_WIDTH})
        self.doc_table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.doc_table.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.SingleSelection)
        self.doc_table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.doc_table.setAlternatingRowColors(True)
        self.doc_table.itemSelectionChanged.connect(self._on_doc_selected)
        # §S1「必须承接的六件事」第 6 条：双击行 → 打开这份文件（此前 `ReaderPage.open_document`
        # 在全项目**零调用**，阅读器是一屏进不去的界面 —— 与 **ISSUES I55** 同一类"控件在场、
        # 链路不在场"，随本条一起接上）。
        self.doc_table.itemDoubleClicked.connect(self._on_doc_activated)
        # 「滚到底再取下一批」（§S1 甲 线框里那一句）。挂滚动条的值上而不是别的：
        # Qt 没有"滚到底"信号，而 `maximum - value ≤ 视口高` 是一次 O(1) 比较。
        self.doc_table.verticalScrollBar().valueChanged.connect(self._on_scrolled)
        center_lay.addWidget(self.doc_table, 1)

        # —— 「送去识别」（**ISSUES I67** 甲 · 2026-10-19 定案，线框 `docs/wireframes/
        # 2026-10-19-round14-i67-i78.html` §I67-jia）——
        # 产品里 `request_ocr` 的**第一个调用点**：此前 OCR 只能由 `gates/stage5.py` 与测试
        # 点名，S7 只有 O1/O2/O3 三个读数，界面上没有任何一处能把一份扫描件排进队列。
        # 建来是禁用的：没有当前行就没有点名的对象（与 `ai_classify_btn` 同一形状）。
        ocr_row = QtWidgets.QHBoxLayout()
        self.ocr_btn = QtWidgets.QPushButton("送去识别")
        self.ocr_btn.setObjectName("searchBtn")
        self.ocr_btn.setEnabled(False)
        self.ocr_btn.setToolTip("把当前这一份排进识别队列（按页幂等，版本没变的页不再推理）")
        self.ocr_btn.clicked.connect(self._on_ocr_requested)
        ocr_row.addWidget(self.ocr_btn)
        ocr_row.addStretch(1)
        center_lay.addLayout(ocr_row)

        # 状态栏
        self.status_label = QtWidgets.QLabel("共 0 份文档")
        self.status_label.setObjectName("muted")
        # 折行是**必须**的，不是美化：不折行的 QLabel 其 `minimumSizeHint()` 就等于整句宽，
        # 而 §S1 定案要这一栏把检索口径与各通道行数都上屏（**ISSUES I60**）。实测把
        # `SearchResult.lines()` 整句（1056px）直接 setText 进去，页面最小宽被顶到 1121px、
        # 窗口最小宽 1178px —— 越过 D-039 的 1024 地板，`test_ui_layout` 那两条断言当场红。
        # 这里按 `ui/pages/backup_page.py` 的同一口径处理（中文可断行，路径不可，见其 `_elided`）。
        self.status_label.setWordWrap(True)
        center_lay.addWidget(self.status_label)

        self.splitter.addWidget(center)

        # 右栏：**命中面板（当前查询）**（**ISSUES I53** ②甲，2026-10-17）。宽档时它是 splitter
        # 的第三槽；窄档时被 `FloatablePanel` 摘出来挂到本页面自己身上当浮层 —— **同一个控件，
        # 不复制内容**。原先独占这一栏的文档详情留在**同一栏的下半部**：它是全站唯一显示
        # 单文档四种状态（解析/正文/OCR/索引）的地方，而 §S2 甲的顶栏与底栏没有元数据区，
        # 没有一个"已确认的位置"可搬 —— 这条差量与理由记在 **D-052**。
        self.right_panel = FloatablePanel(self, "命中面板（当前查询）",
                                          column_width=RIGHT_COLUMN_WIDTH)
        self.hit_list = QtWidgets.QListWidget()
        # 命中行是"整句片段"，必须折行；折行就意味着行高不齐 —— 这**不打犯** D-040 的
        # 行高统一：那条管的是中栏那张要虚拟化的文档表（行号↔坐标必须 O(1)），而这一栏
        # 的行数有上限：`_do_keyword_search` 传的 `limit=100`（后端页上限 `MAX_PAGE_SIZE=200`）
        # 加至多 4 条组头 ⇒ ≤104 行，所以这一栏不虚拟化。实测（2026-10-17，宽档 344px 列内）
        # 组头 25px、单行命中 38px、被折成三行的路径命中 77px。
        self.hit_list.setWordWrap(True)
        self.hit_list.currentItemChanged.connect(self._on_hit_current)
        self.right_panel.body.addWidget(self.hit_list, 3)

        self.jump_btn = QtWidgets.QPushButton("跳到该页 → S2")
        self.jump_btn.setObjectName("searchBtn")
        self.jump_btn.setToolTip("在阅读器里打开这一条命中所在的页")
        self.jump_btn.setEnabled(False)
        self.jump_btn.clicked.connect(self._on_jump_clicked)
        self.right_panel.body.addWidget(self.jump_btn)

        detail_title = QtWidgets.QLabel("文档详情")
        detail_title.setObjectName("sectionTitle")
        self.right_panel.body.addWidget(detail_title)

        self.detail_view = QtWidgets.QPlainTextEdit()
        self.detail_view.setReadOnly(True)
        self.right_panel.body.addWidget(self.detail_view, 2)

        self.ai_classify_btn = QtWidgets.QPushButton("🤖 AI 推荐分类")
        self.ai_classify_btn.setObjectName("searchBtn")
        self.ai_classify_btn.setEnabled(False)
        self.ai_classify_btn.setToolTip("按文件名与所在目录名推荐分类（不读文档正文）")
        self.ai_classify_btn.clicked.connect(self._on_ai_classify_clicked)
        self.right_panel.body.addWidget(self.ai_classify_btn)

        self.ai_result_label = QtWidgets.QLabel("")
        self.ai_result_label.setWordWrap(True)
        self.ai_result_label.setObjectName("muted")
        self.right_panel.body.addWidget(self.ai_result_label)

        self.right_panel.attach(self.splitter)

        self._panels = [self.tree_panel, self.right_panel]
        # 拖宽时只有中列表该吃掉增量（条是 fixedWidth，两块浮栏按 D-040 定宽，其余项
        # 默认 stretch 就是 0）。索引会随切档变（条一直在 splitter 里、面板会被摘走），
        # 所以这里按控件取索引，不写死数字。
        self.splitter.setStretchFactor(self.splitter.indexOf(center), 1)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.splitter)

        self._selected_category_id: int | None = None
        self._current_docs: list = []
        self._selected_doc_id: int | None = None
        # —— 浏览分页（**ISSUES I51**）——
        # `_browse_active`：表里这一列是不是"浏览库"来的。是 → 滚动到底补一批；
        #   否 → 表里是查询命中（有上限），滚动到底什么都不该再加。
        # `_browse_exhausted`：已经取到库尾。没有它就得靠"已取行数 ≥ 总数"判尾，
        #   而第一批还没取时总数是 0，那条判据会把第一批直接拦掉。
        self._browse_active = False
        self._browse_exhausted = False
        self._browse_total = 0
        self._reload_categories()
        self._load_all_documents()

    # ---- 分档（D-040：1024 档牺牲右栏，不牺牲分类树）----

    def resizeEvent(self, event: QtGui.QResizeEvent) -> None:  # noqa: N802 - Qt 命名
        super().resizeEvent(event)
        sync_tier(self.splitter, self._panels, self.width())

    def eventFilter(self, obj: QtCore.QObject, event: QtCore.QEvent) -> bool:
        """「点搜索框 → 浮层出现」（D-040 §S1 降级那一段的触发点）。"""
        if obj is self.search_input and event.type() == QtCore.QEvent.Type.FocusIn:
            self.right_panel.open_overlay()
        return super().eventFilter(obj, event)

    def focus_search(self) -> None:
        """Ctrl+F 的落点（**ISSUES I53** ③甲 / **D-052**）：唤出右栏并把光标交给搜索框。
        显式调 `open_overlay()` 而不是只靠上面的 `FocusIn` —— 窗口未激活时 Qt 不保证派发
        `FocusIn`，那样的话"按了没反应"只在用户身上发生、测试里量不到。
        """
        self.right_panel.open_overlay()
        self.search_input.setFocus()
        self.search_input.selectAll()

    def _reload_categories(self) -> None:
        self.category_tree.clear()
        tree = self.ctx.catalog.category_tree()
        items_by_path: dict[str, QtWidgets.QTreeWidgetItem] = {}
        for cat, depth in tree:
            item = QtWidgets.QTreeWidgetItem([cat.name])
            item.setData(0, QtCore.Qt.ItemDataRole.UserRole, cat.id)
            if depth == 0:
                self.category_tree.addTopLevelItem(item)
            else:
                parent_path = cat.name_path.rsplit("/", 1)[0]
                parent_item = items_by_path.get(parent_path)
                if parent_item:
                    parent_item.addChild(item)
            items_by_path[cat.name_path] = item
        self.category_tree.expandAll()

    def _on_category_clicked(self, item: QtWidgets.QTreeWidgetItem, column: int) -> None:
        self._filter_by_category(item.data(0, QtCore.Qt.ItemDataRole.UserRole))

    def _filter_by_category(self, category_id: int) -> None:
        """宽档点树、窄档点浮层里的树，都收敛到这一个入口 —— 两档共用同一筛选口径。"""
        self._load_documents_by_category(category_id)

    def _load_all_documents(self) -> None:
        self._selected_category_id = None
        # 浏览模式没有"当前查询"，右栏就不该留着上一次查询的命中（挂着是过期读数）。
        self._start_browse()
        self._clear_hits()

    def _load_documents_by_category(self, category_id: int) -> None:
        self._selected_category_id = category_id
        self._start_browse()
        self._clear_hits()   # 列表换成这一类的文档了，右栏留着上一次查询的命中就是过期读数

    # ---- 浏览：一批一批取（**ISSUES I51**）------------------------------------

    def _start_browse(self) -> None:
        """把中栏切成"浏览库里这一列"：只先取第一批，剩下的等滚动。

        修前这里是 `documents.list(limit=1000)` 一次灌满再逐行取分类：8,000 份的库实测
        `table_rows=1000 / 看不见 7,000 份 / 逐行 SQL 1,000 条`，而状态栏那句
        「共 1000 份文档」把"没显示"说成了"不存在"（×10 档 8 万份时看不见 79,000 份）。
        """
        self._browse_active = True
        self._browse_exhausted = False
        self._browse_total = 0
        self._current_docs = []
        self.doc_table.setRowCount(0)
        self._load_more()
        self._fill_viewport()

    def _load_more(self) -> None:
        """取下一批追加到表尾。取完了就是空操作 —— 不许到库尾再绕回头。"""
        if not self._browse_active or self._browse_exhausted:
            return
        # `or None`：第一批还没数过（`_browse_total` 是 0），把 0 当"已知的数"递下去就等于
        # 叫后端跳过 `count_matching`、然后状态栏说「共 0 份文档」。第二批起才带上第一批
        # 那个读数 —— 每批重数一遍全表是 O(行数²)，见 `SearchService.search` 的 `known_total`。
        result = self.ctx.search.browse_documents(
            category_id=self._selected_category_id, offset=len(self._current_docs),
            total=self._browse_total or None)
        self._browse_total = result.matching_documents
        docs = [hit.doc for hit in result.hits]
        if not docs:
            self._browse_exhausted = True
        elif len(self._current_docs) + len(docs) >= self._browse_total:
            self._browse_exhausted = True
        self._append_rows(docs)
        self._set_status(result.status_line())

    def _append_rows(self, docs: list) -> None:
        if not docs:
            return
        start = len(self._current_docs)
        self.doc_table.setRowCount(start + len(docs))
        self._write_rows(start, docs)
        self._current_docs += docs

    def _fill_viewport(self) -> None:
        """第一批顶不出滚动条时（视口比一批还高）永远不会有人滚 ⇒ 也就永远不会补，
        所以这里主动补到"能滚"为止。行高统一（**D-040**）⇒ 一次乘法就够，不测每行。"""
        while self._browse_active and not self._browse_exhausted \
                and self._loaded_height() <= self.doc_table.viewport().height():
            self._load_more()

    def _loaded_height(self) -> int:
        if not self._current_docs:
            return 0
        return self.doc_table.rowHeight(0) * len(self._current_docs)

    def _on_scrolled(self, value: int) -> None:
        bar = self.doc_table.verticalScrollBar()
        if bar.maximum() - value <= self.doc_table.viewport().height():
            self._load_more()

    def _do_search(self) -> None:
        query = self.search_input.text().strip()
        if not query:
            self._load_all_documents()
            return

        if self.semantic_toggle.isChecked():
            # 语义搜索
            self._do_semantic_search(query)
        else:
            # 关键词搜索（四通道）
            self._do_keyword_search(query)

    def _do_keyword_search(self, query: str) -> None:
        """关键词检索：四通道（文件名/路径/元数据/正文）。"""
        result = self.ctx.search.search_text(query, limit=100)

        seen_ids: set[int] = set()
        docs: list[Document] = []
        for hit in result.hits:
            if hit.doc.id not in seen_ids:
                seen_ids.add(hit.doc.id)
                docs.append(hit.doc)

        self._current_docs = docs
        self._populate_table(docs)
        self._show_hits(result)
        # **ISSUES I60**（§S1 的两条已定案契约）：显示的数只许来自 `matching_documents` /
        # `counts_by_field` / `truncated_fields`，口径（trigram / 慢速 LIKE）与截断必须上屏。
        # 这里**不在界面里拼句子** —— 格式化只有后端一个出口（`SearchResult.status_line()`，
        # 原先那句 `f"关键词搜索命中 {len(docs)} 份…"` 正是线框点名的自算数）。
        # 中栏表里那些行仍是按 `hit.doc.id` 去重的结果，但那是**列表本身**，不是"显示的数"。
        self._set_status(result.status_line())

    def _set_status(self, text: str, *, danger: bool = False) -> None:
        """状态栏那一行的唯一出口：红字与常态由同一处切。

        为什么要有这个出口：`_tint` 此前只被 `ai_result_label` 用过，状态栏从没被染红过，
        四处 `setText` 各写各的 ⇒ 一旦某条失败把字染红，下一次成功的读数会**带着上一次的红色**
        上屏（**ISSUES I84** ③ 要求失败可见，但没说不许把可见变成常驻）。
        """
        _tint(self.status_label, "danger" if danger else "muted")
        self.status_label.setText(text)

    def _do_semantic_search(self, query: str) -> None:
        """语义搜索：基于向量相似度。"""
        try:
            results = self.ctx.semantic_search.search(query, top_k=50)
        except Exception as exc:
            # **ISSUES I84** ③：模型不在场时服务层抛 `FileNotFoundError`（原文逐字在那条台账里），
            # 而这里原先没有 `except` ⇒ 异常穿出 Qt 槽，屏幕上**什么都不发生**（表格停在上一状态），
            # 原文只进 `crash.log`。落点与 AI 分类那条同一口径：染红 + 后端原文，界面不重述原因。
            # 表也要清空：状态栏那一行是「表里这些行是什么」的唯一口径（**ISSUES I60**），
            # 留着上一批行配一句失败 = 两个答案。
            self._current_docs = []
            self._populate_table([])
            self._clear_hits()
            self._set_status(f"语义搜索失败：{exc}", danger=True)
            return

        if not results:
            self._current_docs = []
            self._populate_table([])
            self._clear_hits()
            # ③ 落地之后「模型不可用」不再是"无结果"的一种原因（它现在带原文走红字那条路），
            # 这句因此去掉那半截 —— 同一条规则：文案只报后端此刻真的知道的事。
            self._set_status("语义搜索无结果（向量库里还没有向量）")
            return

        # 收集文档 ID（去重）
        seen_ids: set[int] = set()
        docs: list[Document] = []
        for doc_id, page_no, score in results:
            if doc_id not in seen_ids:
                seen_ids.add(doc_id)
                doc = self.ctx.documents.get(doc_id)
                if doc:
                    docs.append(doc)

        self._current_docs = docs
        self._populate_table(docs)
        self._show_semantic_hits(results)
        self._set_status(f"语义搜索命中 {len(docs)} 份文档（最高相似度 {results[0][2]:.3f}）")

    # ---- 右栏：命中面板（**ISSUES I53** ②甲 / **D-052**）-----------------------

    def _clear_hits(self) -> None:
        self.hit_list.clear()
        self.jump_btn.setEnabled(False)
        self.jump_btn.setText("跳到该页 → S2")

    def _show_hits(self, result) -> None:
        """§S1 甲 那一栏：把**当前查询**的命中按通道分组列出来，每条带页码与片段。

        每行的文案取后端出口 `SearchResult.rows()`，界面不重拼一遍 —— **ISSUES I60**
        那条"格式化只有后端一个 owner"在这里同样成立（`rows()` 里已经写好了
        「第 N 页」/ 无页码时改显通道名 / 正文命中带出处，正是线框点名的三样）。
        分组顺序按 `criteria.in_fields`（用户勾的那几条），空组不占一行 ——
        未装模型时语义那一组因此整组不在场，符合线框「不是灰掉、不是空表」。
        组头不写数字：计数是状态栏那一行的口径（`counts_by_field`），这里再写一份
        就是同一个数的第二个出处。
        """
        lines = result.rows()
        self._clear_hits()
        for name in result.criteria.in_fields:
            group = [(hit, line) for hit, line in zip(result.hits, lines) if hit.field == name]
            if not group:
                continue
            self._add_group(group[0][0].field_label, name in result.truncated_fields)
            for hit, line in group:
                self._add_hit_row(line, int(hit.doc.id or 0), hit.page_no, hit.doc.path)

    def _show_semantic_hits(self, results: list[tuple[int, int, float]]) -> None:
        """语义命中进同一栏、同一套跳转。

        **这一组的文本是界面拼的**，因为语义命中没有后端 formatter —— 线框 §S1 的
        「语义命中的标注」那一行自己写着「阶段 6 的 `SearchResult` 扩展（**尚未存在**）」，
        后端把语义并进 `SearchResult` 的那天，这段就该删掉、改走 `rows()`。
        措辞照线框那一格：「语义命中（相近，非原文）」+ 相似度，不许看起来像原文。
        """
        self._clear_hits()
        self._add_group("语义", False)
        for doc_id, page_no, score in results:
            doc = self.ctx.documents.get(doc_id)
            if not doc:
                continue
            where = f"第 {page_no} 页" if page_no else "整份文档"
            self._add_hit_row(f"[{where}]｜语义命中（相近，非原文）｜相似度 {score:.3f}｜{doc.name}",
                              int(doc_id), page_no or None, doc.path)

    def _add_group(self, label: str, truncated: bool) -> None:
        header = QtWidgets.QListWidgetItem(label + ("（已截断）" if truncated else ""))
        # 只留 Enabled、去掉 Selectable：分组标题不是命中，点它不该让跳转按钮亮起来。
        header.setFlags(QtCore.Qt.ItemFlag.ItemIsEnabled)
        self.hit_list.addItem(header)

    def _add_hit_row(self, text: str, doc_id: int, page_no: int | None, path: str) -> None:
        item = QtWidgets.QListWidgetItem(text)
        item.setData(_HIT_DOC_ROLE, doc_id)
        item.setData(_HIT_PAGE_ROLE, page_no)
        item.setToolTip(path)   # 片段里放不下整条路径，悬停回读（与中栏「路径」列同一口径）
        self.hit_list.addItem(item)

    def _on_hit_current(self, current, previous) -> None:
        """选中一条命中 → 中栏跳到那份文档（详情跟着走）+ 决定跳转按钮的形状。"""
        doc_id = current.data(_HIT_DOC_ROLE) if current is not None else None
        page_no = current.data(_HIT_PAGE_ROLE) if current is not None else None
        self.jump_btn.setEnabled(doc_id is not None)
        # 一条按钮两个措辞而不是两条按钮：动作只有一个（在阅读器里打开），差别只在**落到哪一页**。
        # 文件名/路径/元数据三通道没有页码（`Hit.page_no is None`），编一个"第 1 页"就是假装有。
        self.jump_btn.setText("跳到该页 → S2" if page_no else "打开文档 → S2")
        if doc_id is not None:
            self._select_doc_row(int(doc_id))

    def _select_doc_row(self, doc_id: int) -> None:
        for row in range(self.doc_table.rowCount()):
            item = self.doc_table.item(row, 0)
            if item is not None and item.data(QtCore.Qt.ItemDataRole.UserRole) == doc_id:
                self.doc_table.selectRow(row)
                return

    def _on_jump_clicked(self) -> None:
        item = self.hit_list.currentItem()
        if item is None:
            return
        doc_id = item.data(_HIT_DOC_ROLE)
        if doc_id is None:
            return
        # 载荷是一个 tuple 而不是两个参数：`Signal(object)` 只接一arg，emit 两个当场 TypeError，
        # 而它发生在 Qt 槽里 —— 按钮点下去什么都不做（本轮探针 .probe_work/_sig_probe.py 实测）。
        self.open_in_reader.emit((int(doc_id), item.data(_HIT_PAGE_ROLE)))

    def _on_doc_activated(self, item: QtWidgets.QTableWidgetItem) -> None:
        doc_id = item.data(QtCore.Qt.ItemDataRole.UserRole)
        if doc_id is not None:
            self.open_in_reader.emit((int(doc_id), None))

    def _clear_search(self) -> None:
        self.search_input.clear()
        if self._selected_category_id is not None:
            self._load_documents_by_category(self._selected_category_id)
        else:
            self._load_all_documents()

    def _populate_table(self, docs: list[Document]) -> None:
        """一次性灌一张**有上限**的命中表（关键词 ≤100 行 / 语义 ≤50 行，上限都在调用方那里）。

        浏览库里那一列不走这里 —— 那条要一批一批取，见 `_start_browse`（**ISSUES I51**）。
        命中表必须把浏览态关掉：不然用户在几十条命中上滚到底，表尾就会开始长出"与这次查询无关
        的库里的行"，看着像命中，其实一条都没验过。
        """
        self._browse_active = False
        self._browse_exhausted = True
        self._current_docs = list(docs)
        self.doc_table.setRowCount(len(docs))
        self._write_rows(0, docs)

    def _write_rows(self, start: int, docs: list[Document]) -> None:
        """把一批文档写进表格的连续几行。

        分类那一列是**一条查询取回整批**（`categories_by_doc_ids`），不是逐行取 ——
        修前每行调一次 `categories_of`，1,000 行就是 1,000 条 SQL（**ISSUES I51** 实测）。
        """
        cats_by_doc = self.ctx.catalog.categories_by_doc_ids([doc.id for doc in docs])
        for row, doc in enumerate(docs, start=start):
            # 文件名
            name_item = QtWidgets.QTableWidgetItem(doc.name)
            name_item.setData(QtCore.Qt.ItemDataRole.UserRole, doc.id)
            name_item.setToolTip(doc.name)
            self.doc_table.setItem(row, 0, name_item)

            # 路径：定宽装不下整条绝对路径，靠悬停回读（与 S5 判重表同一口径）
            path_item = QtWidgets.QTableWidgetItem(doc.path)
            path_item.setToolTip(doc.path)
            self.doc_table.setItem(row, 1, path_item)

            # 大小
            self.doc_table.setItem(row, 2, QtWidgets.QTableWidgetItem(_format_size(doc.size_bytes)))

            # 修改时间
            self.doc_table.setItem(row, 3, QtWidgets.QTableWidgetItem(_mtime_text(doc)))

            # 分类（查询关联）：至多三个用户自定义名，长度没有上限（DDL 只对
            # (parent_id, name) 建唯一索引，不约束长度），所以按可截断列处理，
            # 与「路径」同一口径 —— 截断了必须能悬停读回全文。
            cat_str = ", ".join(c.name for c in cats_by_doc.get(doc.id, [])[:3])
            cat_item = QtWidgets.QTableWidgetItem(cat_str)
            cat_item.setToolTip(cat_str)
            self.doc_table.setItem(row, 4, cat_item)

    def _get_categories_for_doc(self, doc_id: int) -> list:
        return self.ctx.catalog.categories_of(doc_id)

    def _on_doc_selected(self) -> None:
        row = self.doc_table.currentRow()
        if row < 0:
            self.detail_view.clear()
            self.ai_classify_btn.setEnabled(False)
            self.ocr_btn.setEnabled(False)
            self.ai_result_label.setText("")
            self._selected_doc_id = None
            return
        item = self.doc_table.item(row, 0)
        if not item:
            return
        doc_id = item.data(QtCore.Qt.ItemDataRole.UserRole)
        self._selected_doc_id = doc_id
        self.ai_classify_btn.setEnabled(True)
        self.ocr_btn.setEnabled(True)
        self.ai_result_label.setText("")
        doc = self.ctx.documents.get(doc_id)
        if not doc:
            return

        cats = self._get_categories_for_doc(doc_id)
        tags = self._get_tags_for_doc(doc_id)

        lines = [
            f"文件名：{doc.name}",
            f"扩展名：{doc.ext}",
            f"路径：{doc.path or '(未知)'}",
            f"大小：{_format_size(doc.size_bytes)}",
            f"修改时间：{_mtime_text(doc)}",
            f"SHA256: {doc.sha256 or '(未计算)'}",
            "",
            f"页数：{doc.page_count or '(未知)'}",
            f"正文覆盖率：{doc.text_bearing_rate:.1%}" if doc.text_bearing_rate else "正文覆盖率：(未知)",
            "",
            f"分类：{', '.join(c.name for c in cats) or '(无)'}",
            f"标签：{', '.join(t.name for t in tags) or '(无)'}",
            "",
            f"解析状态：{doc.parse_status}",
            f"正文状态：{doc.text_status}",
            f"OCR 状态：{doc.ocr_status}",
            f"索引状态：{doc.fts_status}",
        ]
        if doc.last_error:
            lines.append(f"最后错误：{doc.last_error}")

        self.detail_view.setPlainText("\n".join(lines))
        # 详情是"选中这一行之后才有的内容"，窄档它藏在浮层里（这一栏的下半部），所以选中即唤出。
        self.right_panel.open_overlay()

    def _get_tags_for_doc(self, doc_id: int) -> list:
        return self.ctx.catalog.tags_of(doc_id)

    def _on_ocr_requested(self) -> None:
        """「送去识别」（**ISSUES I67** 甲）：把当前行排进队列，回执**原样**上屏。

        份数与跳过理由只有后端一个出口（`OcrRequest.describe()` 与 `SKIP_LABELS`），
        界面不许自己数第六类理由（**ISSUES I67** 销账判定②／**ISSUES I60** 同一条纪律）。
        新增 0 条时染红：「按了但没进队列」必须在屏幕上看得见（销账判定①③）。
        排队失败的落点与语义搜索那条同一口径（**ISSUES I84** ③）：染红 + 后端原文，界面不重述原因。
        """
        if self._selected_doc_id is None:
            return
        try:
            request = self.ctx.ocr.request_ocr([self._selected_doc_id])
        except Exception as exc:
            self._set_status(f"识别排队失败：{exc}", danger=True)
            return
        self._set_status(f"{request.describe()}｜{self.ctx.ocr.budget.describe()}",
                         danger=request.enqueued == 0)

    def _on_ai_classify_clicked(self) -> None:
        if self._selected_doc_id is None:
            return
        self.ai_classify_btn.setEnabled(False)
        _tint(self.ai_result_label, "muted")
        self.ai_result_label.setText("正在分析...")
        QtWidgets.QApplication.processEvents()
        try:
            suggestions = self.ctx.ai_classify.suggest_for_doc(self._selected_doc_id)
        except Exception as exc:
            _tint(self.ai_result_label, "danger")
            self.ai_result_label.setText(f"AI 分类不可用：{exc}")
            self.ai_classify_btn.setEnabled(True)
            return
        if not suggestions:
            # **ISSUES I84** ②：原先这句写「请先执行语义索引」，而产品里**没有**这个动作
            # （`VectorStore.add*` 零产品调用方、`vector` 从不入队 —— **ISSUES I63** 丙/丁），
            # 把人引向一个不存在的按钮比说错更费时间。只报后端此刻真的知道的那两件事。
            self.ai_result_label.setText("暂无向量数据：向量库里还没有向量，或相似度低于阈值")
        else:
            lines = ["AI 推荐分类："]
            for s in suggestions:
                lines.append(f"  · {s.category_name}（相似度 {s.score:.2f}）")
            self.ai_result_label.setText("\n".join(lines))
        self.ai_classify_btn.setEnabled(True)

    def reload(self) -> None:
        """刷新数据。"""
        self._reload_categories()
        if self._selected_category_id is not None:
            self._load_documents_by_category(self._selected_category_id)
        else:
            self._load_all_documents()
