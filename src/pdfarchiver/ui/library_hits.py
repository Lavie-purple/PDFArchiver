"""S1 右栏那一栏的全部现场：命中面板 + 文档详情 + AI 推荐分类。

**ISSUES I96** 甲（2026-10-20）从 `ui/pages/library_page.py` 整段搬来 —— 搬的是同一批代码，
不是第二份实现：那一屏在轮十四一天里从 686 行写到 795 行（五处接线全落在同一屏），
AGENTS.md 那条「单文件超 800 行就拆」已经变成"下一次写入就会违约"的形状。

**为什么是 mixin 而不是一个独立控件**：这一栏不是贴在页面上的部件，它是 S1 身体的一部分 ——
`FloatablePanel` 要挂进页面 splitter 的第三槽、`ui/tier.py` 的 `sync_tier` 要在拖窄时把它摘成
420px 浮层、每条命中要点回中栏那张表（`_select_doc_row`）、跳转要发页面自己的 `open_in_reader`
信号。做成控件就得把这几样反向递进去，而 `tests/integration/test_ui_tier.py` 那三十来条几何断言
认的是 `page.right_panel` / `page.hit_list` —— 换访问路径等于让断言跟着实现改。混入让控件仍然挂在
页面对象上，归属只挪了文件。

混入方（`ui/pages/library_page.py` 的 `LibraryPage`）须提供三样：
`self.ctx`（AppContext）、`self.doc_table`（中栏那张表，点命中回来选行）、
`self.open_in_reader`（`(doc_id, page_no)` 信号，跳到 S2 的出口）。

搜索编排（`_do_search` / `_do_keyword_search` / `_do_semantic_search`）**留在页面里**：
一次查询要同时写中栏表、状态栏与这一栏三处状态，拆开就是两边各拿一半。
每一格写什么、详情那一段的排版在 `ui/library_rows.py`；两档切换的尺子在 `ui/tier.py`。
"""
from __future__ import annotations

from PySide6 import QtCore, QtWidgets

from pdfarchiver.ui.library_rows import DOC_ID_COLUMN, detail_lines
from pdfarchiver.ui.tier import RIGHT_COLUMN_WIDTH, FloatablePanel


def set_text_role(label: QtWidgets.QLabel, role: str) -> None:
    """把标签的文字角色挂到 objectName 上，由 `ui/theme.py` 的令牌决定颜色。

    改 objectName 后必须 unpolish/polish，否则 Qt 沿用已经算好的旧样式。
    """
    label.setObjectName(role)
    label.style().unpolish(label)
    label.style().polish(label)


# 命中面板每一行挂的两样数据：跳转要用的 doc_id 与页码（`None` = 这一条没有页码）。
_HIT_DOC_ROLE = QtCore.Qt.ItemDataRole.UserRole
_HIT_PAGE_ROLE = QtCore.Qt.ItemDataRole.UserRole + 1


class LibraryHitsMixin:
    """右栏的构造与回调。宽档常驻 / 窄档浮层两档形状由 `ui/tier.py` 决定，不在这里。"""

    def _build_right_panel(self) -> None:
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

    # ---- 键盘入口（**D-052** / **ISSUES I53** ③甲）----

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

    # ---- 命中面板（**ISSUES I53** ②甲 / **D-052**）-----------------------------

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
            item = self.doc_table.item(row, DOC_ID_COLUMN)
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

    # ---- 文档详情 + AI 推荐分类（这一栏的下半部）------------------------------

    def _render_detail(self, doc_id: int) -> bool:
        """把一份文档的详情画进右栏下半部；库里已经没有这一份时返回 False（什么都不画）。"""
        doc = self.ctx.documents.get(doc_id)
        if not doc:
            return False

        cats = self._get_categories_for_doc(doc_id)
        tags = self._get_tags_for_doc(doc_id)
        self.detail_view.setPlainText("\n".join(detail_lines(doc, cats, tags)))
        return True

    def _get_categories_for_doc(self, doc_id: int) -> list:
        return self.ctx.catalog.categories_of(doc_id)

    def _get_tags_for_doc(self, doc_id: int) -> list:
        return self.ctx.catalog.tags_of(doc_id)

    def _on_ai_classify_clicked(self) -> None:
        if self._selected_doc_id is None:
            return
        self.ai_classify_btn.setEnabled(False)
        set_text_role(self.ai_result_label, "muted")
        self.ai_result_label.setText("正在分析...")
        QtWidgets.QApplication.processEvents()
        try:
            suggestions = self.ctx.ai_classify.suggest_for_doc(self._selected_doc_id)
        except Exception as exc:
            set_text_role(self.ai_result_label, "danger")
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
