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

混入方（`ui/pages/library_page.py` 的 `LibraryPage`）须提供四样：
`self.ctx`（AppContext）、`self.doc_table`（中栏那张表，点命中回来选行）、
`self.open_in_reader`（`(doc_id, page_no)` 信号，跳到 S2 的出口）、
`self._set_status`（状态栏那一行的唯一出口，「为当前文档建向量」的回回执到这里）。

搜索编排（`_do_search` 起线程 → `_on_search_ready` 落回主线程 → `_render_keyword` /
`_render_semantic` 上屏）**留在页面里**：一次查询要同时写中栏表、状态栏与这一栏三处状态，
拆开就是两边各拿一半。
每一格写什么、详情那一段的排版在 `ui/library_rows.py`；两档切换的尺子在 `ui/tier.py`。
"""
from __future__ import annotations

from PySide6 import QtCore, QtWidgets

from pdfarchiver.ui.empty_state import make_hint, sync_hint
from pdfarchiver.ui.library_rows import DOC_ID_COLUMN, detail_lines
from pdfarchiver.ui.semantic_state import absent_or_original, apply_state
from pdfarchiver.ui.tier import RIGHT_COLUMN_WIDTH, FloatablePanel


def set_text_role(label: QtWidgets.QLabel, role: str) -> None:
    """把标签的文字角色挂到 objectName 上，由 `ui/theme.py` 的令牌决定颜色。

    改 objectName 后必须 unpolish/polish，否则 Qt 沿用已经算好的旧样式。
    """
    label.setObjectName(role)
    label.style().unpolish(label)
    label.style().polish(label)


# 命中面板每一行挂的两样数据：跳转要用的 doc_id、页码（`None` = 这一条没有页码）。
# 「为什么被找到」不再单独挂角色（轮三十七 甲）：后缀已由 `_show_hits` 直接接进行尾文案，
# 逐字等于 `SearchResult.suffix(hit)`，界面上不存在第二份解释。
_HIT_DOC_ROLE = QtCore.Qt.ItemDataRole.UserRole
_HIT_PAGE_ROLE = QtCore.Qt.ItemDataRole.UserRole + 1

#: 情境提示条上那颗按钮（轮三十六 甲 · 乙）。与表下那颗「送去识别」是两回事：
#: 那颗认"表格里选中了哪几份"，这颗认"当前筛选下的那一批待识别"，所以文案里必须带"这批/筛选"。
OCR_HINT_BTN_TEXT = "送去识别这批"


class LibraryHitsMixin:
    """右栏的构造与回调。宽档常驻 / 窄档浮层两档形状由 `ui/tier.py` 决定，不在这里。"""

    def _build_right_panel(self) -> None:
        # 右栏：**命中面板（当前查询）**（**ISSUES I53** ②甲，2026-10-17）。宽档时它是 splitter
        # 的第三槽；窄档时被 `FloatablePanel` 摘出来挂到本页面自己身上当浮层 —— **同一个控件，
        # 不复制内容**。原先独占这一栏的文档详情留在**同一栏的下半部**：它是全站唯一显示
        # 单文档四种状态（解析/正文/OCR/索引）的地方，而 §S2 甲的顶栏与底栏没有元数据区，
        # 没有一个"已确认的位置"可搬 —— 这条差量与理由记在 **D-052**。
        # 轮四十二 ⑭ 把它改成两档都是浮层；轮五十九 ②甲 改回**宽档贴边**：浮层盖住的正好
        # 是它自己抄的那一列（用户红框 #2 那处"右侧和左侧一致"）。`sacrificial=True` 认领
        # **D-040**「必须且只牺牲右栏」—— 页宽不够"轨 + 展开的树 + 中栏下限 + 右栏"同时在场
        # 时（默认窗口 1,099 < 1,124），是这一栏变浮层，不是把三条下限一起放宽。
        # 内容上它也不再是第二个结果列表：只有带页码与片段的命中（正文 / 语义）才列在这里，
        # 其余通道归成后端的一行小结（`SearchResult.collapsed_counts_line()`，轮五十九 ①甲）。
        self.right_panel = FloatablePanel(self, "命中面板（当前查询）",
                                          column_width=RIGHT_COLUMN_WIDTH, sacrificial=True)
        self._right_dismissed = False
        self.right_panel.closed.connect(self._on_right_closed)

        # 情境提示条（轮三十六 甲 · 乙）：只在「查询一条都没命中、而这个筛选下确实有没识别过的
        # 扫描件」时出现 —— 它回答的是"我明明有这类文件，为什么搜不到"，而不是一块常驻横幅。
        # 句子取后端出口 `PendingOcr.strip_line()`；颗数/页数由 `ctx.ocr.pending_in` 一条口径数出来。
        self.ocr_hint_band = QtWidgets.QFrame()
        self.ocr_hint_band.setObjectName("ocrHintBand")
        hint_lay = QtWidgets.QVBoxLayout(self.ocr_hint_band)
        hint_lay.setContentsMargins(8, 4, 8, 4)
        self.ocr_hint_label = QtWidgets.QLabel("")
        self.ocr_hint_label.setObjectName("muted")
        self.ocr_hint_label.setWordWrap(True)
        hint_lay.addWidget(self.ocr_hint_label)
        self.ocr_hint_btn = QtWidgets.QPushButton(OCR_HINT_BTN_TEXT)
        self.ocr_hint_btn.setObjectName("searchBtn")
        self.ocr_hint_btn.setToolTip("先展开这一批的账（该跑几份/不跑几份/代价/今日预算），确认后才排队")
        self.ocr_hint_btn.clicked.connect(self._on_filter_ocr_requested)
        hint_lay.addWidget(self.ocr_hint_btn)
        # 默认不占位：建来是隐藏的，`_update_ocr_hint` 决定它出不出现。
        self.ocr_hint_band.setVisible(False)
        self.right_panel.body.addWidget(self.ocr_hint_band)

        # 栏目标题（轮五十九 ①甲）：把这一栏的**内容契约**写在屏幕上 ——
        # 「表格里看不到的东西才进这一栏」。用户问的正是"这块区域显示什么内容"。
        hit_title = QtWidgets.QLabel("命中证据")
        hit_title.setObjectName("sectionTitle")
        hit_title.setToolTip(
            "只列带页码与正文片段的命中（正文 / 语义）—— 中栏表格里看不到的那三样。\n"
            "只按文件名 / 路径 / 元数据命中的那几路收成下面一行小结，不逐行重抄表格。")
        self.right_panel.body.addWidget(hit_title)

        # ⑱ 全站空态规则（**D-066**）的唯一出口。这一栏以前不归它管 —— 两档都是浮层、默认关着，
        # 「隐藏的列表」按定义不在场；轮五十九 ②甲 把它改成宽档常驻之后它**开局就在屏幕上且是空的**，
        # 于是当场归管（全量回归 2026-11-03 逐字红在「文档库（library）的 hit_list」）。
        self.hit_hint = make_hint(
            "还没有命中：在上方输入关键词后点「搜索」，这里列的是带页码与正文片段的那些"
            "（只按文件名 / 路径命中的那几路收成一行小结，不重抄表格）。", self.right_panel)
        self.right_panel.body.addWidget(self.hit_hint)

        self.hit_list = QtWidgets.QListWidget()
        # 命中行是"整句片段"，必须折行；折行就意味着行高不齐 —— 这**不打犯** D-040 的
        # 行高统一：那条管的是中栏那张要虚拟化的文档表（行号↔坐标必须 O(1)），而这一栏
        # 的行数有上限：`_do_search` 给关键词那一路传的 `limit=100`（后端页上限 `MAX_PAGE_SIZE=200`）
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
        # 轮四十二 ②：右栏浮层被唤出而详情还是空的那块白底，与"坏了"长得一样。
        # 占位文字说清"这里会出什么、去哪选中"。
        self.detail_view.setPlaceholderText(
            "选中左边表格里的一行，这里显示这份文档的路径、分类与标签。")
        self.right_panel.body.addWidget(self.detail_view, 2)

        self.ai_classify_btn = QtWidgets.QPushButton("🤖 AI 推荐分类")
        self.ai_classify_btn.setObjectName("searchBtn")
        self.ai_classify_btn.setEnabled(False)
        self.ai_classify_btn.setToolTip("按文件名与所在目录名推荐分类（不读文档正文）")
        self.ai_classify_btn.clicked.connect(self._on_ai_classify_clicked)
        self.right_panel.body.addWidget(self.ai_classify_btn)

        # 「为当前文档建向量」（轮五十一 Q2 甲·丁-2）：就地点名**这一份**，走
        # `ctx.vector.request_vectors` 那条唯一入口 —— 它只排队、不碰模型，真活由 worker 领；
        # 但它是语义入口之一，所以模型不在本机时跟着谓词一起灰（Q1 乙）。不设自动触发。
        self.vector_btn = QtWidgets.QPushButton("为当前文档建向量")
        self.vector_btn.setObjectName("searchBtn")
        self.vector_btn.setEnabled(False)
        self.vector_btn.setToolTip("把这一份的正文排进向量队列，等索引 worker 建向量（不会自动开工）")
        self.vector_btn.clicked.connect(self._on_vector_requested)
        self.right_panel.body.addWidget(self.vector_btn)

        apply_state(self.ai_classify_btn, ready=self.ctx.semantic_ready)
        apply_state(self.vector_btn, ready=self.ctx.semantic_ready)

        self.ai_result_label = QtWidgets.QLabel("")
        self.ai_result_label.setWordWrap(True)
        self.ai_result_label.setObjectName("muted")
        self.right_panel.body.addWidget(self.ai_result_label)

        self.right_panel.attach(self.splitter)

    # ---- 键盘入口（**D-052** / **ISSUES I53** ③甲）----

    def _on_right_closed(self) -> None:
        """用户亲手按 ✕ 关掉右栏：此后选中文档不再自动唤出（轮四十二 ⑭），
        直到下一次搜索出新内容（`_show_hits` 会把这个记号清掉）。
        """
        self._right_dismissed = True

    def _open_right_panel(self) -> None:
        """搜索出了新结果 → 右栏带着新内容唤出（旧内容还在时尊重用户关掉的选择）。"""
        self._right_dismissed = False
        self.right_panel.open_overlay()

    def focus_search(self) -> None:
        """Ctrl+F 的落点（**ISSUES I53** ③甲 / **D-052**）：把光标交给搜索框。

        轮四十二 ⑭ 起不再顺带唤右栏 —— 那一刻它还是空的，先把一块空白浮层盖在表格上
        是又一种堆积；等搜索出了结果，`_show_hits` 自己会开。
        """
        self.search_input.setFocus()
        self.search_input.selectAll()

    # ---- 命中面板（**ISSUES I53** ②甲 / **D-052**）-----------------------------

    def _clear_hits(self) -> None:
        self.hit_list.clear()
        self.jump_btn.setEnabled(False)
        self.jump_btn.setText("跳到该页 → S2")
        sync_hint(self.hit_list)

    # ---- 情境提示条（轮三十六 甲 · 乙）---------------------------------------

    def _update_ocr_hint(self, *, empty: bool) -> None:
        """查询一条都没命中时，若这个筛选下真有还没识别的扫描件，就把「为什么搜不到」摆上屏。

        `empty` 由页面（搜索编排那一侧）判定 —— 这一栏不知道刚才查了什么，也不该自己再数一遍。
        名单为空时同样收起：一条按下去点不到任何一份的横幅比没有横幅更糟。

        最后那一句 `if show: self._open_right_panel()` 是 **轮六十 乙** 的直接后果（2026-11-04
        全量回归当场红在 `test_ocr_on_demand.py` 两条上）：这条带子挂在右栏里，而 乙 之后
        **默认档（窗口 1,280）右栏是让位、按 ⑭ 默认关着的浮层** ⇒ 只把带子 `setVisible(True)`
        等于把那句话写进一块不在屏幕上的面板。规则与 `_show_hits` 那句"有正文命中才开"是同一条
        （**有增量内容才唤出**），只是此刻这一栏唯一的增量内容就是这句话；出口也只有一处
        （`_open_right_panel`，顺带把 `_invoked` 记上，让位↔常驻来回切档时不会把它关没）。
        """
        pending = getattr(self, "_pending_ocr", None)
        show = bool(empty and pending is not None and pending.ids)
        self.ocr_hint_label.setText(pending.strip_line() if show else "")
        self.ocr_hint_band.setVisible(show)
        if show:
            self._open_right_panel()

    def _show_hits(self, result) -> None:
        """右栏只列**带增量的命中**：有页码、有正文片段的那几路（正文 / 语义）。

        判据是后端的一个属性 `Hit.carries_evidence`，界面不复述它（**轮五十九 ①甲**）：
        文件名 / 路径 / 元数据三路的行文案就是中栏那一格自己（`rows()` 对非正文通道
        退回 `hit.doc.path`），逐行列进右栏等于把同一份数据画两遍 —— 用户 2026-11-03
        红框 #2 点名的"右侧和左侧一致"正是这里。这三路收成
        `SearchResult.collapsed_counts_line()` 的**一行**小结，计数与状态栏同源。

        每行文案取后端出口 `SearchResult.rows()`，界面不重拼一遍 —— **ISSUES I60**
        那条"格式化只有后端一个 owner"在这里同样成立（`rows()` 里已经写好了
        「第 N 页」/ 正文命中带出处，正是线框点名的三样）。
        分组顺序按 `criteria.in_fields`（用户勾的那几条），空组不占一行 ——
        未装模型时语义那一组因此整组不在场，符合线框「不是灰掉、不是空表」。
        组头不写数字：计数是状态栏那一行的口径（`counts_by_field`），这里再写一份
        就是同一个数的第二个出处。

        「为什么被找到」的**行内后缀**同样取后端出口 `SearchResult.suffix(hit)`（轮三十七 甲）：
        接在 `rows()` 那句的行尾、一个「 · 」分隔 —— 界面只做拼接，不自己拼一句"为什么"。
        页码与出处 `rows()` 行首已带，后缀不重复，所以这条拼接就是全部。

        唤出条件从"有结果就开"收紧成「**有正文命中才开**」：只命中文件名时这一栏没有证据
        可列，把一块空面板盖在表格上没有道理；选中文档行照样出详情（`_on_doc_selected`），
        用户按过 ✕ 就不再自动唤出（`_right_dismissed`）。"开"只管浮层那一档 —— 宽档这一栏
        是常驻的（②甲），空着的时候由 ⑱ 那句引导在场，不留一块空框。
        """
        lines = result.rows()
        self._clear_hits()
        evidence = [(hit, line) for hit, line in zip(result.hits, lines)
                    if hit.carries_evidence]
        for name in result.criteria.in_fields:
            group = [(hit, line) for hit, line in evidence if hit.field == name]
            if not group:
                continue
            self._add_group(group[0][0].field_label, name in result.truncated_fields)
            for hit, line in group:
                self._add_hit_row(f"{line} · {result.suffix(hit)}",
                                  int(hit.doc.id or 0), hit.page_no, hit.doc.path)
        summary = result.collapsed_counts_line()
        if summary:
            self._add_info_row(summary)
        sync_hint(self.hit_list)
        if evidence:
            self._open_right_panel()

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
        self._open_right_panel()

    def _add_group(self, label: str, truncated: bool) -> None:
        self._add_info_row(label + ("（已截断）" if truncated else ""))

    def _add_info_row(self, text: str) -> None:
        """一行"不是命中"的说明（组头、通道小结共用）：不可选中，点它不该让跳转按钮亮。"""
        item = QtWidgets.QListWidgetItem(text)
        # 只留 Enabled、去掉 Selectable：说明行不是命中，点它不该让跳转按钮亮起来。
        item.setFlags(QtCore.Qt.ItemFlag.ItemIsEnabled)
        self.hit_list.addItem(item)

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
        # 轮四十二 ①：跳转按钮的兜底。命中列表里有一条**可选中的**当前行 → 按命中跳；
        # 没有（没搜过 / 刚清空 / 当前停在分组标题上）→ 按中栏选中的那份文档开整份。
        # 按钮的形状（文字/可用性）由 `_on_hit_current` 与 `_set_jump_fallback` 两处
        # 各自管，动作落点只有这一处判断，两处不会说两样话。
        item = self.hit_list.currentItem()
        if item is not None and (item.flags() & QtCore.Qt.ItemFlag.ItemIsSelectable):
            doc_id = item.data(_HIT_DOC_ROLE)
            if doc_id is not None:
                # 载荷是一个 tuple 而不是两个参数：`Signal(object)` 只接一arg，emit 两个当场
                # TypeError，而它发生在 Qt 槽里 —— 按钮点下去什么都不做（探针实测）。
                self.open_in_reader.emit((int(doc_id), item.data(_HIT_PAGE_ROLE)))
                return
        if self._selected_doc_id is not None:
            self.open_in_reader.emit((int(self._selected_doc_id), None))

    def _set_jump_fallback(self) -> None:
        """中栏选中变化 → 命中列表没有可用选中时，让跳转按钮退到"打开选中的文档"。

        命中列表的当前行**可选中**（一条真命中）时什么都不动 —— `_on_hit_current` 已经按
        那一行定了按钮的形状；分组标题没有 `_HIT_DOC_ROLE`（不可选中，构造时就摘了
        Selectable），落到兜底。可用性跟**点名**走（与动作行 ⑯ 同口径）：Qt 的
        `clearSelection` 不重置 currentRow，表格已无高亮行时亮着一颗按钮等于指着一个
        看不见的"选中"。点名非空才退到"打开文档"，空了就灰。
        """
        current = self.hit_list.currentItem()
        if current is not None and (current.flags() & QtCore.Qt.ItemFlag.ItemIsSelectable):
            return
        self.jump_btn.setEnabled(bool(self._selected_doc_ids()))
        self.jump_btn.setText("打开文档 → S2")

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
            # 轮五十一 Q3 乙：模型缺席只上一句人话，后端原文逐字进日志；其余失败照旧回原文。
            self.ai_result_label.setText(absent_or_original(exc, prefix="AI 分类不可用："))
            # 收回去时不能写 `True`：那等于界面自己判定"模型在了"，把 Q1 乙那一个谓词顶掉。
            self.ai_classify_btn.setEnabled(self.ctx.semantic_ready)
            return
        if not suggestions:
            # **ISSUES I84** ②：原先这句写「请先执行语义索引」，指向的是当时产品里**不存在**的动作。
            # 那个动作自轮五十一 丁-2 起真的有了（就是下面那颗「为当前文档建向量」），
            # 但这里仍只报后端此刻真的知道的那两件事 —— 按钮就在同一栏里，不在这儿二次指路。
            self.ai_result_label.setText("暂无向量数据：向量库里还没有向量，或相似度低于阈值")
        else:
            lines = ["AI 推荐分类："]
            for s in suggestions:
                lines.append(f"  · {s.category_name}（相似度 {s.score:.2f}）")
            self.ai_result_label.setText("\n".join(lines))
        self.ai_classify_btn.setEnabled(self.ctx.semantic_ready)

    def _on_vector_requested(self) -> None:
        """「为当前文档建向量」（轮五十一 Q2 甲·丁-2）：只点名**当前这一份**，只排队。

        回执一律取后端 `VectorRequest.describe()`，界面不重拼（**ISSUES I60** 同一条纪律）；
        新增 0 条时染红 —— 「按了但没进队列」必须在屏幕上看得见，与 OCR 那颗同一口径。
        排队失败不走 `absent_or_original`：`request_vectors` 只碰队列、不碰模型，
        它抛什么都该照原文上屏。
        """
        if self._selected_doc_id is None:
            return
        try:
            request = self.ctx.vector.request_vectors([self._selected_doc_id])
        except Exception as exc:  # noqa: BLE001 - 边界：排队失败必须看得见
            self._set_status(f"向量排队失败：{exc}", danger=True)
            return
        self._set_status(request.describe(), danger=request.enqueued == 0)
