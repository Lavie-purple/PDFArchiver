"""S1 主窗口 · 库视图与搜索结果面板 —— 甲·甲·甲（2026-10-15 定案）。

三栏布局（**宽档**，页面可用宽度 ≥ 1076）：
- 左栏：分类树（用于筛选）
- 中栏：文档表格（支持四通道检索）
- 右栏：文档详情面板

**窄档的形状是 D-040 定下来的，不是这里的偏好**：线框 §S1 的算术
`236 + 480 + 360 = 1076 > 1024` ⇒ 三栏放不下，**必须且只牺牲右栏** ——
搜索是"要结果时才看结果"，分类树是"随时知道我在库的哪个位置"。于是：

- 右栏变成 **420px 浮层**（可关；默认关，不记忆成"每次都开"）；
- 左栏收成 **48px 的条**，整棵树改由那一条唤出（树没有被删，只是不常驻）；
- 中栏吃掉剩余宽度。

两档的切换机械不在本文件里，在 `ui/tier.py` —— **D-039** 要求 S8 的树侧栏在 1024 档
收起同一把尺子，AGENTS.md「禁止同类问题逐个打补丁」，所以一条规则两处用。

行高必须统一（D-040 表里第一行的形状）：虚拟化要按 O(1) 做行号↔坐标换算，
一旦变成"命中展开把行撑高"就得整表测高 —— 8 万行档就是 O(n²)，AGENTS.md 明令禁止。

数据来自 `AppContext.search`、`AppContext.documents`、`AppContext.catalog`。
"""
from __future__ import annotations

from PySide6 import QtCore, QtGui, QtWidgets

from pdfarchiver.services.bootstrap import AppContext
from pdfarchiver.services.status_service import format_ts
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


def _format_size(size_bytes: int) -> str:
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    else:
        return f"{size_bytes / (1024 * 1024 * 1024):.1f} GB"


def _mtime_text(doc) -> str:
    """修改时间的显示。没有 mtime 时留空，**不进 `format_ts`** —— 它把 `None` 显示成"从未"，
    而对一份文件的修改时刻来说"从未"是错的读法（那是"不知道"，不是"从来没有"）。
    """
    return format_ts(doc.mtime_ns // 1_000_000_000) if doc.mtime_ns else ""


class LibraryPage(QtWidgets.QWidget):
    """S1：宽档三栏常驻（分类树 | 文档表格 | 详情面板），窄档走 `ui/tier.py` 的降级。"""

    def __init__(self, ctx: AppContext, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.ctx = ctx

        self.splitter = QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal)

        # 左栏：分类树。宽档占 splitter 一槽，窄档整块变成浮层、原位留下 48px 的条（D-040）。
        # 条上给的是"2 字按钮 + 真树浮层"而不是每类一枚图标：`Category` 里没有图标字段
        # （`db/models.py:54`），线框那句"图标条"要的产品数据还不存在，记在 **ISSUES I53** ①。
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
        # 快捷键那半句线框没给具体键位，不替用户猜，记在 **ISSUES I53** ③。
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
        # 五列合计 780px，而**中栏视口不是一个数**：宽档（页面 1079px）空库实测 463px、灌进行
        # 之后 425px，窄档（窗口 1024px / 页面 823px）同一组是 756px / 718px —— 随数据少掉的那
        # 38px 是 Qt 自己长出来的行号列（见 **ISSUES I54**）。装不装得下随分档与行数两个因素变，
        # 所以"超出就必须滚得过去"由 `test_表格定宽列放不下时必须还能滚到` 在宽档钉住。
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
        center_lay.addWidget(self.doc_table, 1)

        # 状态栏
        self.status_label = QtWidgets.QLabel("共 0 份文档")
        self.status_label.setObjectName("muted")
        center_lay.addWidget(self.status_label)

        self.splitter.addWidget(center)

        # 右栏：详情面板。宽档时它是 splitter 的第三槽；窄档时被 `FloatablePanel`
        # 摘出来挂到本页面自己身上当浮层 —— **同一个控件，不复制内容**。
        self.detail_panel = FloatablePanel(self, "文档详情", column_width=RIGHT_COLUMN_WIDTH)
        self.detail_view = QtWidgets.QPlainTextEdit()
        self.detail_view.setReadOnly(True)
        self.detail_panel.body.addWidget(self.detail_view, 1)

        self.ai_classify_btn = QtWidgets.QPushButton("🤖 AI 推荐分类")
        self.ai_classify_btn.setObjectName("searchBtn")
        self.ai_classify_btn.setEnabled(False)
        self.ai_classify_btn.setToolTip("基于文档内容与分类语义中心的相似度推荐分类")
        self.ai_classify_btn.clicked.connect(self._on_ai_classify_clicked)
        self.detail_panel.body.addWidget(self.ai_classify_btn)

        self.ai_result_label = QtWidgets.QLabel("")
        self.ai_result_label.setWordWrap(True)
        self.ai_result_label.setObjectName("muted")
        self.detail_panel.body.addWidget(self.ai_result_label)

        self.detail_panel.attach(self.splitter)

        self._panels = [self.tree_panel, self.detail_panel]
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
        self._reload_categories()
        self._load_all_documents()

    # ---- 分档（D-040：1024 档牺牲右栏，不牺牲分类树）----

    def resizeEvent(self, event: QtGui.QResizeEvent) -> None:  # noqa: N802 - Qt 命名
        super().resizeEvent(event)
        sync_tier(self.splitter, self._panels, self.width())

    def eventFilter(self, obj: QtCore.QObject, event: QtCore.QEvent) -> bool:
        """「点搜索框 → 浮层出现」（D-040 §S1 降级那一段的触发点）。"""
        if obj is self.search_input and event.type() == QtCore.QEvent.Type.FocusIn:
            self.detail_panel.open_overlay()
        return super().eventFilter(obj, event)

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
        self._selected_category_id = category_id
        self._load_documents_by_category(category_id)

    def _load_all_documents(self) -> None:
        self._selected_category_id = None
        docs = self.ctx.documents.list(limit=1000)
        self._current_docs = docs
        self._populate_table(docs)

    def _load_documents_by_category(self, category_id: int) -> None:
        doc_ids = self.ctx.catalog.docs_in_category(category_id)
        by_id = self.ctx.documents.by_ids(doc_ids)
        docs = [by_id[did] for did in doc_ids if did in by_id]
        docs.sort(key=lambda d: d.name.casefold())
        self._current_docs = docs
        self._populate_table(docs)

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
        self.status_label.setText(f"关键词搜索命中 {len(docs)} 份文档（耗时 {result.took_ms:.0f}ms）")

    def _do_semantic_search(self, query: str) -> None:
        """语义搜索：基于向量相似度。"""
        results = self.ctx.semantic_search.search(query, top_k=50)

        if not results:
            self._current_docs = []
            self._populate_table([])
            self.status_label.setText("语义搜索无结果（向量库为空或模型不可用）")
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
        self.status_label.setText(f"语义搜索命中 {len(docs)} 份文档（最高相似度 {results[0][2]:.3f}）")

    def _clear_search(self) -> None:
        self.search_input.clear()
        if self._selected_category_id is not None:
            self._load_documents_by_category(self._selected_category_id)
        else:
            self._load_all_documents()

    def _populate_table(self, docs: list[Document]) -> None:
        self.doc_table.setRowCount(len(docs))
        for row, doc in enumerate(docs):
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
            cats = self._get_categories_for_doc(doc.id)
            cat_str = ", ".join(c.name for c in cats[:3])
            cat_item = QtWidgets.QTableWidgetItem(cat_str)
            cat_item.setToolTip(cat_str)
            self.doc_table.setItem(row, 4, cat_item)

        if not self.search_input.text().strip():
            self.status_label.setText(f"共 {len(docs)} 份文档")

    def _get_categories_for_doc(self, doc_id: int) -> list:
        return self.ctx.catalog.categories_of(doc_id)

    def _on_doc_selected(self) -> None:
        row = self.doc_table.currentRow()
        if row < 0:
            self.detail_view.clear()
            self.ai_classify_btn.setEnabled(False)
            self.ai_result_label.setText("")
            self._selected_doc_id = None
            return
        item = self.doc_table.item(row, 0)
        if not item:
            return
        doc_id = item.data(QtCore.Qt.ItemDataRole.UserRole)
        self._selected_doc_id = doc_id
        self.ai_classify_btn.setEnabled(True)
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
        # 详情是"选中这一行之后才有的内容"，窄档它藏在浮层里，所以选中即唤出。
        # 线框只写了"点搜索框或按快捷键"—— 这一档的右栏装的是详情而不是命中列表
        # （差量记在 **ISSUES I53** ②），触发点跟着内容走比照着线框少一个入口更诚实。
        self.detail_panel.open_overlay()

    def _get_tags_for_doc(self, doc_id: int) -> list:
        return self.ctx.catalog.tags_of(doc_id)

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
            self.ai_result_label.setText("无匹配分类（向量库为空或相似度不足）")
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
