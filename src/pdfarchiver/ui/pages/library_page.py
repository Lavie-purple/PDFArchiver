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

表格底下那一颗「送去识别」（**ISSUES I67** 甲先乙后）是产品里 `request_ocr` 的**第一个调用点**；
此前 OCR 只能由 `gates/stage5.py` 与测试点名，选中多份时先由 `ui/ocr_batch_panel.py` 把账摆上屏。

同一排那三颗「归入分类 / 加标签 / 移除标签」（**ISSUES I78** 甲，2026-10-19）是产品里
`link_categories / link_tags / unlink_tags` 的调用点：建控件的整段理由与它的四条约定在
`ui/catalog_links.py`，本文件只负责递给它两样东西 —— 表格里点名了哪几份、状态栏那一句怎么写。

搜索框底下那一排 chips（**ISSUES I78** 乙，2026-10-19，`ui/collection_bar.py`）是这一页
**筛选条件的唯一现场**：原先这里只有一个 `_selected_category_id`，屏幕上看不见"现在到底筛了
什么"，也没有任何地方能留下一组条件。现在点分类树改的是同一份 dict，取数走
`ctx.search.browse_documents(query=…)` 一条路，S8 点开一条集合也只是把那份 dict 换上来
（`apply_saved`）—— 分类浏览、条件筛选、集合回放三件事共用同一条 WHERE，不存在第二套入口。

每一格里写什么、详情那一段怎么排版，在 `ui/library_rows.py`（同一份文档的"可截断列"与
"整段文本"两种显示由那一处出，两档不会各说各话）。
右栏那一栏（命中面板 + 文档详情 + AI 推荐分类）的控件与回调在 `ui/library_hits.py`，由本类混入
（**ISSUES I96** 甲，2026-10-20）—— 控件仍然挂在页面对象上（`page.right_panel` / `page.hit_list`），
挪走的只有归属。搜索编排留在本文件：一次查询同时写中栏表、状态栏与右栏三处，拆开就是两边各拿一半。
筛选区（筛选条 + 「按当前筛选送识别」+ 收放开关）同理在 `ui/library_filter.py`
（2026-10-30 第二次按主题拆）。

数据来自 `AppContext.search`、`AppContext.documents`、`AppContext.catalog`、`AppContext.ocr`、
`AppContext.collection`（存/覆盖集合与数命中都走它，这一页不碰 `collections` 仓储）。
"""
from __future__ import annotations

from pathlib import Path

from PySide6 import QtCore, QtGui, QtWidgets

from pdfarchiver.services.bootstrap import AppContext
from pdfarchiver.services.collection_service import CollectionEntry
from pdfarchiver.ui.catalog_links import CatalogLinkBar
from pdfarchiver.ui.library_filter import FILTER_OCR_BTN_TEXT, LibraryFilterMixin
from pdfarchiver.ui.library_hits import LibraryHitsMixin, set_text_role
from pdfarchiver.ui.library_rows import (HEADERS, CATEGORY_COLUMN, DOC_ID_COLUMN, category_cell,
                                         write_document_rows)
from pdfarchiver.ui.ocr_batch_panel import OcrBatchPanel
from pdfarchiver.ui.table_layout import CELL_PADDING_WIDTH, set_table_columns
from pdfarchiver.ui.tier import LEFT_COLUMN_WIDTH, FloatablePanel, sync_tier


#: 那颗 OCR 按钮的基础文案。选中两份以上时后面跟「（选中 N 份）」（**ISSUES I67** 乙），
#: 所以写它的时候只有一处，读它的时候也只有一处 —— 两处各写一份就会有一天对不上。
OCR_BTN_TEXT = "送去识别"


class LibraryPage(LibraryFilterMixin, LibraryHitsMixin, QtWidgets.QWidget):
    """S1：宽档三栏常驻（分类树 | 文档表格 | 命中面板），窄档走 `ui/tier.py` 的降级。"""

    # (doc_id, page_no)；page_no 为 None 表示这一条命中没有页码（文件名/路径/元数据三通道）。
    # 用 tuple 而不是给 page_no 编一个 0 当"没有"，是为了让越界判定只存在于阅读器一处。
    open_in_reader = QtCore.Signal(object)

    def __init__(self, ctx: AppContext, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.ctx = ctx

        self.splitter = QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal)

        # 左栏：分类树。**D-066**（走查 ⑮）之后宽档也默认收成 48px 的条，点条才展开成
        # D-040 那 236px 常驻列；窄档不变（条 + 420px 浮层）。条上那颗按钮自己管收/放。
        # 条上给的是"2 字按钮 + 真树浮层"而不是每类一枚图标：`Category` 里没有图标字段
        # （`db/models.py:54`）—— 线框那句"图标条"要的产品数据不存在，2026-10-17 按
        # **ISSUES I53** ①甲 定案**把线框改成现在这个形状**（见 `docs/UI-WIREFRAMES.md` §S1 定案记录）。
        self.tree_panel = FloatablePanel(self, "分类筛选", column_width=LEFT_COLUMN_WIDTH,
                                         strip_label="分类", collapsible=True)
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
        # D-040 的浮层触发点原是"点搜索框"：轮四十二 ⑭ 起右栏不常驻、默认关，
        # 点框就唤出一块空白浮层是又一种堆积 —— 触发点收进 `_show_hits`（有结果才开）。
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

        # 轮四十一 甲「上次读到」提示行：S2 不再是导航项，「继续阅读」降级成 S1 搜索栏
        # 下的一行 —— 有记录才出现，点击经 `open_in_reader` 打开最近那份、落上次那页
        # （page_no=None，与命中面板同一载荷）；文件不在了可见但禁用并写明原因。
        self.last_read_hint = QtWidgets.QToolButton()
        self.last_read_hint.setObjectName("lastReadHint")
        self.last_read_hint.setAutoRaise(True)
        self.last_read_hint.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        self.last_read_hint.hide()
        self.last_read_hint.clicked.connect(self._open_last_read)
        center_lay.addWidget(self.last_read_hint)
        self.update_last_read_hint()

        # 筛选区（轮四十二 ⑬）：筛选条 + 「按当前筛选送识别」+ 收放开关，构造与收放逻辑
        # 在 `ui/library_filter.py`（**ISSUES I96** 甲，同 `library_hits.py` 的混入先例）。
        self._build_filter_area(center_lay)

        # 文档表格
        self.doc_table = QtWidgets.QTableWidget()
        # 五列的列名与顺序在 `ui/library_rows.py` 的 `HEADERS`（那一模块负责往这几格里写什么），
        # 列数由它算，不写两个 5。
        self.doc_table.setColumnCount(len(HEADERS))
        self.doc_table.setHorizontalHeaderLabels(list(HEADERS))
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
        # **ISSUES I78** 甲（2026-10-19）改多选：「批量打标签」在 SPEC 阶段 3 里写的是"一批文档"，
        # 单选的话一次只能归一份，那条验收仍然做不到。Ctrl/Shift 与 `SelectRows` 同一形状，
        # 而"当前行"（`currentRow`）的语义不变 —— 「送去识别」与详情面板照旧认当前那一行。
        self.doc_table.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.ExtendedSelection)
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
        # 动作行（轮四十二 ⑯）：「送去识别」+ 三颗写入按钮整排**默认隐藏**，表格里点名
        # ≥1 份才出现 —— 没选任何东西时它们全是灰按钮挂着，是纯堆积。
        self.action_row = QtWidgets.QWidget()
        action_lay = QtWidgets.QHBoxLayout(self.action_row)
        action_lay.setContentsMargins(0, 0, 0, 0)
        self.ocr_btn = QtWidgets.QPushButton(OCR_BTN_TEXT)
        self.ocr_btn.setObjectName("searchBtn")
        self.ocr_btn.setEnabled(False)
        self.ocr_btn.setToolTip("把选中的份排进识别队列（按页幂等，版本没变的页不再推理）"
                                "；选中多份时先展开面板算账，确认后才排队")
        self.ocr_btn.clicked.connect(self._on_ocr_requested)
        action_lay.addWidget(self.ocr_btn)
        # 同一排右边是三颗写入按钮（**ISSUES I78** 甲）：它只认"表格里点名了哪几份"和
        # "状态栏那一句怎么写"，两者都由这一页递进去 —— 按钮自己从不查库、不数条数。
        self.link_bar = CatalogLinkBar(self.ctx,
                                       selected_ids=self._selected_doc_ids,
                                       set_status=self._set_status,
                                       on_written=self._after_link_written)
        action_lay.addWidget(self.link_bar)
        action_lay.addStretch(1)
        self.action_row.setVisible(False)
        center_lay.addWidget(self.action_row)

        # 同一颗按钮在**选中多份**时展开的批次面板（**ISSUES I67** 乙 · 2026-10-19 勾「甲先乙后」，
        # 线框 §I67-yi）：多份点名要先看清"该跑几份、哪几份不跑、为什么不跑、今日预算够不够"，
        # 而单份不必看这份账 —— 按下去直接排队就是甲案那条老路。建来是隐藏的，不看时不占屏幕。
        self.ocr_panel = OcrBatchPanel(self.ctx, set_status=self._set_status)
        center_lay.addWidget(self.ocr_panel)
        # 排完队之后重读一次待识别读数：新排的份此刻仍是 pending（要等 worker 跑完才变），
        # 所以这个数不会立刻掉 —— 但它是**从库里读的**，不是界面自己减的（**ISSUES I60**）。
        self.ocr_panel.enqueue_btn.clicked.connect(self._refresh_pending_ocr)

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

        # 右栏：**命中面板（当前查询）** + 文档详情 + AI 推荐分类 —— 整栏的构造与回调在
        # `ui/library_hits.py`（**ISSUES I96** 甲）。它混进本类，控件仍挂在 `self` 上，
        # 所以这里只需要一句调用：建出来的 `self.right_panel` 落进 splitter 第三槽。
        self._build_right_panel()

        self._panels = [self.tree_panel, self.right_panel]
        # 拖宽时只有中列表该吃掉增量（条是 fixedWidth，两块浮栏按 D-040 定宽，其余项
        # 默认 stretch 就是 0）。索引会随切档变（条一直在 splitter 里、面板会被摘走），
        # 所以这里按控件取索引，不写死数字。
        self.splitter.setStretchFactor(self.splitter.indexOf(center), 1)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.splitter)

        self._query: dict = {}
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
        # 轨上那句计数（**轮四十五 乙**）拿上面那次查询的现成结果，不再查第二遍。
        self.tree_panel.set_strip_count(len(tree))
        # 宽档也收成条之后（**D-066** / ⑮），那颗小圆点是"已经有文档归过类"的信号。
        # 判据用"有没有文档归过类"，不用"树有没有节点"：默认分类一开局就种 14 个，
        # 后一条恒为真，等于装一颗永远亮着的灯。
        self.tree_panel.set_strip_dot(self.ctx.catalog.has_categorized_documents())

    def _load_all_documents(self) -> None:
        """分类树那颗「显示全部」：只去掉「分类」这一条，其余 chips 留着（tooltip 写的就是它）。"""
        self.filter_bar.drop_field("category_ids")

    def _load_documents_by_category(self, category_id: int) -> None:
        """宽档点树、窄档点浮层里的树，都收敛到这一个入口 —— 两档共用同一筛选口径。

        它换掉的只有「分类」这一条：其余条件（比如「索引状态 = 待索引」）是用户自己加的，
        点一下树就把它们清空等于替用户做了他没做的决定。
        """
        self.filter_bar.set_field("category_ids", [category_id])

    # ---- 筛选条（**ISSUES I78** 乙）：条件只有一份 dict ----

    def _apply_query(self, query: dict) -> None:
        """筛选条递下来的新条件：存下来，然后重新起一次浏览会话。

        右栏那些命中是**上一次查询**的，换了筛选口径还挂着就是过期读数（与 **ISSUES I53** ②甲
        那条"命中面板只对当前查询负责"同一条纪律）。
        """
        if bool(query) != bool(self._query):
            self._filter_manual = None  # 自动状态变了，手动收放意愿交还给自动规则
        self._query = query
        self._update_filter_area()
        self._start_browse()
        self._clear_hits()
        # 换了筛选口径，提示条上那句"本次筛选里 N 份还没识别"与按钮上的份数都过期了：
        # 先收起，再按新条件重读（读数只从 `ctx.ocr.pending_in` 出）。
        self._update_ocr_hint(empty=False)
        self._refresh_pending_ocr()

    def apply_saved(self, entry: CollectionEntry) -> None:
        """S8 双击一条集合 → 外壳把这条递到这里（**ISSUES I78** 乙 硬断言 (a)(d)）。

        载荷是整个 `CollectionEntry` 而不是 `query` dict：那条集合叫什么、此刻命中几份，
        与"它筛的是什么"是同一条读数的三格，分成三个参数传就会在某一格上开始各说各话。
        """
        self.filter_bar.apply_query(entry.query, saved=entry)

    def _on_category_clicked(self, item: QtWidgets.QTreeWidgetItem, column: int) -> None:
        self._load_documents_by_category(item.data(0, QtCore.Qt.ItemDataRole.UserRole))

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
        # 轮四十二 ⑤：浏览态的口径是 `_browse_line()`，关键词那条 tooltip 是过期口径，清掉。
        self.status_label.setToolTip("")
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
            query=self._query, offset=len(self._current_docs),
            total=self._browse_total or None)
        self._browse_total = result.matching_documents
        docs = [hit.doc for hit in result.hits]
        if not docs:
            self._browse_exhausted = True
        elif len(self._current_docs) + len(docs) >= self._browse_total:
            self._browse_exhausted = True
        self._append_rows(docs)
        # 轮四十二 ⑦：筛选是"分类 = X"、一页都没取到、且表格本来就空 ⇒ 十有八九是这个分类
        # 底下还没有任何文档**归入**（真库实测 `document_categories` 0 行、14 个裸分类）。
        # 只报「共 0 份文档」会让人以为程序坏了；出路指真实的写入口（catalog_links 那排按钮）。
        if not docs and not self._current_docs and self._query.get("category_ids"):
            self._set_status(f"{result.status_line()}｜这个分类还没有文档归入："
                             "在表格里选中文件后，用那排写入按钮里的「归入分类…」建立关联。")
        else:
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
            self._apply_query(self._query)
            return

        # 轮四十二 ⑥：真库一次检索 2–4s（G2 之外的最坏分支），没有任何反馈会被当成"点了没反应"
        # 而连点几轮。等待光标比禁用按钮好：语义与关键词各自的成功路径都要改表格，
        # 漏一处 enable 就是永久锁死；try/finally 保证异常路径也归还光标。
        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.CursorShape.WaitCursor)
        try:
            if self.semantic_toggle.isChecked():
                # 语义搜索
                self._do_semantic_search(query)
            else:
                # 关键词搜索（四通道）
                self._do_keyword_search(query)
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()

    def _do_keyword_search(self, query: str) -> None:
        """关键词检索：四通道（文件名/路径/元数据/正文），**并且就在当前那排 chips 的条件里搜**。"""
        result = self.ctx.search.search_in(self._query, query, limit=100)

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
        # 轮三十六 乙：一条都没命中时，如果这个筛选下真有没识别过的扫描件，就把原因摆到右栏。
        # 有命中/有查询词但不为空时一律收起 —— 它不是常驻横幅，只在"搜不到"这个情境里说话。
        self._update_ocr_hint(empty=not result.hits)
        # 轮四十二 ⑤：栏里是短通道名，技术全称（trigram / LIKE 为何退回）挪进悬停。
        # tooltip 也要后端出 —— 界面不存第二份口径。
        self.status_label.setToolTip(result.status_detail())

    def _set_status(self, text: str, *, danger: bool = False) -> None:
        """状态栏那一行的唯一出口：红字与常态由同一处切。

        为什么要有这个出口：`set_text_role` 此前只被 `ai_result_label` 用过，状态栏从没被染红过，
        四处 `setText` 各写各的 ⇒ 一旦某条失败把字染红，下一次成功的读数会**带着上一次的红色**
        上屏（**ISSUES I84** ③ 要求失败可见，但没说不许把可见变成常驻）。
        """
        set_text_role(self.status_label, "danger" if danger else "muted")
        self.status_label.setText(text)

    def _do_semantic_search(self, query: str) -> None:
        """语义搜索：基于向量相似度。"""
        # 语义通道"没命中"的原因是向量库，不是"扫描件没识别过"（向量入场券 I116 甲已改成
        # 有可搜正文才入场）—— 那条提示条讲的是关键词正文通道的事，这里一律收起。
        self._update_ocr_hint(empty=False)
        self.status_label.setToolTip("")  # 轮四十二 ⑤：语义那行没有 keyword 口径可悬停
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
        # 语义那条通道读的是向量库，它**不看**上面那排 chips（向量检索没有带筛选的路径，
        # 阶段 6 的实现里 `SemanticSearchService.search` 只有一个 top_k）。屏幕上明明挂着
        # 「分类 = 合同」却给出全库的相近文档，就是 **ISSUES I11** 那一类"界面宣称它会做它不做的事"，
        # 所以这里把它不说清楚不行：条件还在，只是这一条通道不认。
        note = ("｜⚠ 语义通道不看上面那排筛选条件" if self._query else "")
        self._set_status(f"语义搜索命中 {len(docs)} 份文档（最高相似度 {results[0][2]:.3f}）{note}")

    def _clear_search(self) -> None:
        """搜索行那颗「清除」只管**查询词**：清掉之后中栏回到当前条件下那一列。

        它不动 chips —— 清掉查询词与撤掉筛选条件是两件事，后者是 chips 上那枚 × 和「清除全部」，
        一处按钮干两件事的话，用户下一次不敢按。
        """
        self.search_input.clear()
        self._apply_query(self._query)

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
        """把一批文档写进表格的连续几行 —— 每格写什么在 `ui/library_rows.py`。

        `catalog` 在**调用时**从 `self.ctx` 取而不是构造时存好：`test_一批行的分类只走一条查询`
        就是靠在这里换掉 `categories_by_doc_ids` 来数 SQL 条数的（**ISSUES I51** 的坏法对照）。
        """
        write_document_rows(self.doc_table, docs, start, self.ctx.catalog)

    def _on_doc_selected(self) -> None:
        # 「送去识别」与三颗写入按钮认的都是"点名了几份"（多选），详情面板仍认"当前行"（单选语义不变）。
        self.link_bar.refresh_enabled()
        # 换选中就收起批次面板：那份账算的是**刚才那一批**，留着它等于让人对着过期名单按「排队」。
        self.ocr_panel.close_panel()
        named = len(self._selected_doc_ids())
        self.ocr_btn.setText(OCR_BTN_TEXT if named < 2 else f"{OCR_BTN_TEXT}（选中 {named} 份）")
        # 动作行（轮四十二 ⑯）：点名 ≥1 份才出现，清空选中就整排收起。
        self.action_row.setVisible(named > 0)
        row = self.doc_table.currentRow()
        if row < 0:
            self.detail_view.clear()
            self.ai_classify_btn.setEnabled(False)
            self.ocr_btn.setEnabled(False)
            self.ai_result_label.setText("")
            self._selected_doc_id = None
            self._set_jump_fallback()
            return
        item = self.doc_table.item(row, DOC_ID_COLUMN)
        if not item:
            return
        doc_id = item.data(QtCore.Qt.ItemDataRole.UserRole)
        self._selected_doc_id = doc_id
        self.ai_classify_btn.setEnabled(True)
        self.ocr_btn.setEnabled(True)
        self.ai_result_label.setText("")
        # 轮四十二 ①：命中列表没有可用选中时，跳转按钮退到"打开这份文档"。
        self._set_jump_fallback()
        if self._render_detail(doc_id) and not self._right_dismissed:
            # 详情是"选中这一行之后才有的内容"，右栏默认关（轮四十二 ⑭）：选中即唤出，
            # 但用户亲手按 ✕ 关掉后就不再追着开 —— 下一次搜索出新内容才重开。
            self.right_panel.open_overlay()

    def _selected_doc_ids(self) -> list[int]:
        """表格里现在点名了哪几份 —— 三颗写入按钮的点名对象（**ISSUES I78** 甲）。

        id 取第一列的 `UserRole`（`_write_rows` 挂上去的那份）。`SelectRows` + `ExtendedSelection`
        下同一行有五个 item 被选中，所以按**行号**取、按 doc_id 去重；用 set 而不是 `not in list`，
        免得选中上千行时变成 O(n²)（AGENTS.md 明令禁止）。
        """
        rows = {index.row() for index in self.doc_table.selectionModel().selectedIndexes()}
        seen: set[int] = set()
        ids: list[int] = []
        for row in sorted(rows):
            item = self.doc_table.item(row, DOC_ID_COLUMN)
            if item is None:
                continue
            doc_id = item.data(QtCore.Qt.ItemDataRole.UserRole)
            if doc_id is not None and int(doc_id) not in seen:
                seen.add(int(doc_id))
                ids.append(int(doc_id))
        return ids

    def _after_link_written(self, doc_ids: list[int]) -> None:
        """归入 / 打标 / 摘标之后：只重画被点名的那几行的「分类」列，再重画当前那份的详情。

        不整表重取，也不走 `reload()`：浏览态下 `_current_docs` 可以有上千行，把它们全部塞进
        一次 `categories_by_doc_ids` 会撞 `MAX_BULK_IDS`（**ISSUES I51** 那一条纪律在这儿同样成立），
        而 `reload()` 更是把用户筛的那一列整片换掉、选中态也没了 —— 一次写入不该有这种副作用。
        """
        held = self.ctx.catalog.categories_by_doc_ids(doc_ids)
        targets = set(doc_ids)
        for row in range(self.doc_table.rowCount()):
            item = self.doc_table.item(row, DOC_ID_COLUMN)
            if item is None:
                continue
            doc_id = item.data(QtCore.Qt.ItemDataRole.UserRole)
            if doc_id in targets:
                self.doc_table.setItem(row, CATEGORY_COLUMN, category_cell(held.get(doc_id, [])))
        if self._selected_doc_id is not None:
            self._render_detail(self._selected_doc_id)

    def _on_ocr_requested(self) -> None:
        """「送去识别」：一份直接排队（**I67** 甲），两份以上先展开批次面板（**I67** 乙）。

        份数与跳过理由只有后端一个出口（`OcrRequest.describe()` / `OcrPlan.describe()` 与 `SKIP_LABELS`），
        界面不许自己数第六类理由（**ISSUES I67** 销账判定②／**ISSUES I60** 同一条纪律）。
        新增 0 条时染红：「按了但没进队列」必须在屏幕上看得见（销账判定①③）。
        排队失败的落点与语义搜索那条同一口径（**ISSUES I84** ③）：染红 + 后端原文，界面不重述原因。
        """
        named = self._selected_doc_ids()
        if len(named) > 1:
            self.ocr_panel.open_for(named)
            return
        if self._selected_doc_id is None:
            return
        try:
            request = self.ctx.ocr.request_ocr([self._selected_doc_id])
        except Exception as exc:
            self._set_status(f"识别排队失败：{exc}", danger=True)
            return
        self._set_status(f"{request.describe()}｜{self.ctx.ocr.budget.describe()}",
                         danger=request.enqueued == 0)

    def reload(self) -> None:
        """刷新数据：分类字典重取（S8 可能改过名、新建过），chips 的文案跟着重画。

        条件本身一条不动 —— 「刷新」不该把用户筛好的那排 chips 抹掉，那样中栏会突然变成全库，
        而屏幕上没有一个字解释为什么。
        """
        self._reload_categories()
        self.filter_bar.refresh()
        self._apply_query(self._query)
        self.update_last_read_hint()

    def update_last_read_hint(self) -> None:
        """按 `ctx.documents.last_read()` 刷新提示行（轮四十一 甲）。三态互斥：
        没记录 → 整行隐藏；有记录且文件在 → 可点；文件不在 → 可见但禁用、写明原因。"""
        doc = self.ctx.documents.last_read()
        if doc is None:
            self.last_read_hint.hide()
            return
        exists = Path(doc.path).exists()
        # 轮四十二 ③：`last_read_page == 1` 时「读到第 1 页」是"刚翻开"，不是"读到了哪"
        # —— 两个分支要说出不同的动作（翻到第 1 页 = 从头看）。
        if doc.last_read_page and doc.last_read_page > 1 and exists:
            self.last_read_hint.setText(
                f"上次读到 《{doc.name}》 · 第 {doc.last_read_page} 页 —— 点此继续")
        elif exists:
            self.last_read_hint.setText(f"上次打开过 《{doc.name}》 —— 点此继续")
        else:
            self.last_read_hint.setText(f"上次在读《{doc.name}》，但文件已不在原位置")
        self.last_read_hint.setToolTip(self.last_read_hint.text())
        self.last_read_hint.setEnabled(exists)
        self.last_read_hint.setVisible(True)

    def _open_last_read(self) -> None:
        doc = self.ctx.documents.last_read()
        if doc is not None and self.last_read_hint.isEnabled():
            self.open_in_reader.emit((int(doc.id), None))
