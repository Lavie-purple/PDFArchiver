"""S9 · 库内问答（轮三十七 丁，线框 §D 甲 · §E 第 6 问 甲 第 7 问 甲）。

两栏布局：顶栏「提问」输入 + 「提问」按钮 + 「范围：全库（N 份）」提示；
左栏「历史提问」（**内存态**，线框不变量 ①：不加新表 —— 会话里够用，重启清空是诚实的行为，
不是缺陷）；右栏「答案」句 + 证据卡列表。每张证据卡双击 → S2 打开该页
（复用 S1 已有的 `open_in_reader` 通路，页面只发信号、不认识外壳）。

三个"不许"，各有对应的守卫断言（`tests/integration/test_ask_page.py`）：

1. **界面不拼句子**：答案句、证据卡头、范围提示全部来自 `QaService`（**ISSUES I60** 族：
   文案只有后端一个 owner）。界面只做"把字段摆到控件上"。
2. **抽取式的诚实标记**：「这里是原文摘录，不是生成的话」常驻 —— 甲案没有生成，
   这一句就是它的身份证；换成乙案时这句要跟着改。
3. **失败必须可见**：模型不在场时 `EmbeddingService` 抛 `FileNotFoundError`，
   穿出 Qt 槽等于屏幕上什么都不发生（**ISSUES I84** ③ 的教训）—— 这里接住，红字 + 原文。

检索与统计都在界面线程同步跑（与 S1 语义通道同一条纪律）：真库一次提问 2–4s，
页面**惰性构建**，`stats()` 的 25ms（温）/1.1s（冷，**ISSUES I111** ⑥ 实测）只在
进这一屏与每次提问后发生，不挂在巡检与建窗路径上 —— 那是 **ISSUES I109** 的禁区。

D-040 降级：页宽 < 两栏下限时左栏「历史提问」收起（答案区吃掉全部宽度）。
这里的收起是 `setVisible(False)`，不是 S1 那种浮层 —— 历史提问是辅助列表，
不是任何读数的唯一载体，收走不丢信息（重问一遍它就回来了）。
"""
from __future__ import annotations

from PySide6 import QtCore, QtWidgets

from pdfarchiver.services.bootstrap import AppContext
from pdfarchiver.ui.empty_state import make_hint, sync_hint
from pdfarchiver.ui.library_hits import set_text_role

# 证据对象是 `semantic.qa_service.Evidence`，但 **ui 不 import semantic**（docs/ARCHITECTURE
# 二 的自上而下纪律，架构守卫在钉）：跟 S1 用语义命中一样的鸭子类型 —— 只读它带过来的字段。

# 两栏下限的算术（同 `ui/tier.py` 的写法）：左栏 240 + 答案区保底 720。
# 页宽低于它（1024 地板档页宽 824）时左栏收起 —— 线框 §D 甲「1024 档左栏收起」。
HISTORY_WIDTH = 240
ANSWER_MIN_WIDTH = 720
TWO_COLUMN_MIN_WIDTH = HISTORY_WIDTH + ANSWER_MIN_WIDTH  # 960

HISTORY_MAX_ITEMS = 20  # 内存态列表的容量上限：够一場会话用，防 O(n²) 不存在但防无限长

EXCERPT_NOTE = "这里是原文摘录，不是生成的话"


class _EvidenceCard(QtWidgets.QFrame):
    """一张证据卡：卡头（文件名｜页码｜相似度）+ 摘录原文。双击 → 发跳转信号。"""

    activated = QtCore.Signal(object)  # (doc_id, page_no) —— 与 S1 的 `open_in_reader` 同一份载荷口径

    def __init__(self, evidence) -> None:
        super().__init__()
        self.setObjectName("evidenceCard")
        self._payload = (int(evidence.doc_id), int(evidence.page_no))
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(8, 6, 8, 6)
        lay.setSpacing(2)
        head = QtWidgets.QLabel(f"<b>{evidence.header()}</b>")
        head.setTextInteractionFlags(QtCore.Qt.TextInteractionFlag.TextSelectableByMouse)
        lay.addWidget(head)
        excerpt = QtWidgets.QLabel(evidence.excerpt)
        excerpt.setWordWrap(True)
        excerpt.setToolTip("双击打开这份文档的这一页（S2）")
        lay.addWidget(excerpt)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802 - Qt 命名
        self.activated.emit(self._payload)


class AskPage(QtWidgets.QWidget):
    """S9 库内问答。取数只走 `ctx.qa`；跨屏动作只发 `open_in_reader`。"""

    open_in_reader = QtCore.Signal(object)

    def __init__(self, ctx: AppContext, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.ctx = ctx
        self._cards: list[_EvidenceCard] = []

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 8)
        root.setSpacing(8)

        # —— 顶栏：提问 + 范围 ——
        top = QtWidgets.QHBoxLayout()
        top.addWidget(QtWidgets.QLabel("提问"))
        self.ask_input = QtWidgets.QLineEdit()
        self.ask_input.setPlaceholderText("就用这一批文档，……？")
        self.ask_input.returnPressed.connect(self._ask)
        top.addWidget(self.ask_input, 1)
        self.ask_btn = QtWidgets.QPushButton("提问")
        self.ask_btn.clicked.connect(self._ask)
        top.addWidget(self.ask_btn)
        self.scope_hint = QtWidgets.QLabel()
        self.scope_hint.setObjectName("muted")
        top.addWidget(self.scope_hint)
        root.addLayout(top)

        # —— 两栏 ——
        split = QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal)
        history_pane = QtWidgets.QWidget()
        history_lay = QtWidgets.QVBoxLayout(history_pane)
        history_lay.setContentsMargins(0, 0, 0, 0)
        history_lay.setSpacing(4)
        history_lay.addWidget(QtWidgets.QLabel("历史提问"))
        # ⑱ 空态（**D-066**）：这一栏是**内存态**，每次启动都从空开始 —— 空框在这里不是
        # "坏了"，而是"还没问过"，所以必须说一句它会有什么东西、以及怎么让它有东西。
        self.history_hint = make_hint(
            "还没有问过问题：在右边输入一句、点「提问」，问过的一条条列在这里，"
            "点一条回到那次的答案。", history_pane)
        history_lay.addWidget(self.history_hint)
        self.history_list = QtWidgets.QListWidget()
        self.history_list.itemClicked.connect(self._replay_history)
        history_lay.addWidget(self.history_list, 1)
        self._history_pane = history_pane

        self.answer_scroll = QtWidgets.QScrollArea()
        self.answer_scroll.setWidgetResizable(True)
        self.answer_scroll.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        host = QtWidgets.QWidget()
        answer_lay = QtWidgets.QVBoxLayout(host)
        answer_lay.setContentsMargins(0, 0, 8, 0)
        answer_lay.setSpacing(6)
        title = QtWidgets.QLabel("答案")
        title.setObjectName("sectionTitle")
        answer_lay.addWidget(title)
        # ⑨ 空态引导（轮四十二）：没提问之前答案区一片空白，这句话告诉人这一屏怎么用、
        # 以及「向量 未建」时为什么提问不会有结果。第一次提问后整条隐藏。
        # 文案随向量读数变（`_update_empty_hint`），所以这里只造壳、内容由那一处填；
        # 样式仍走 ⑱ 的唯一出口（**D-066**），不再手抄 `setObjectName` + `setWordWrap`。
        self.empty_hint = make_hint("", host)
        answer_lay.addWidget(self.empty_hint)
        self.answer_label = QtWidgets.QLabel()
        self.answer_label.setWordWrap(True)
        answer_lay.addWidget(self.answer_label)
        self.note_label = QtWidgets.QLabel(EXCERPT_NOTE)
        self.note_label.setObjectName("muted")
        self.note_label.setWordWrap(True)
        answer_lay.addWidget(self.note_label)
        evidence_title = QtWidgets.QLabel("证据（按相似度）")
        evidence_title.setObjectName("sectionTitle")
        answer_lay.addWidget(evidence_title)
        self._cards_lay = QtWidgets.QVBoxLayout()
        self._cards_lay.setSpacing(6)
        answer_lay.addLayout(self._cards_lay)
        answer_lay.addStretch(1)
        self.answer_scroll.setWidget(host)

        split.addWidget(history_pane)
        split.addWidget(self.answer_scroll)
        split.setStretchFactor(1, 1)
        split.setSizes([HISTORY_WIDTH, ANSWER_MIN_WIDTH])
        root.addWidget(split, 1)

        # —— 底栏：耗时 + 向量读数（线框 §D 甲）——
        bottom = QtWidgets.QHBoxLayout()
        self.time_label = QtWidgets.QLabel()
        self.time_label.setObjectName("muted")
        bottom.addWidget(self.time_label)
        bottom.addStretch(1)
        self.vector_label = QtWidgets.QLabel()
        self.vector_label.setObjectName("muted")
        bottom.addWidget(self.vector_label)
        root.addLayout(bottom)

        self.refresh_scope()

    # —— 读数 ——

    def refresh_scope(self) -> None:
        """顶栏范围提示与底栏向量读数，两个数都来自 `qa.stats()` 的同一次扫描。"""
        vectors, docs = self.ctx.qa.stats()
        self.scope_hint.setText(f"范围：全库（{docs:,} 份）")
        self.vector_label.setText("向量 已建" if vectors else "向量 未建")
        self._update_empty_hint(vectors)

    def _update_empty_hint(self, vectors: int) -> None:
        """⑨ 空态引导的两档文案：向量在场讲用法，缺席讲为什么提问不会有结果。

        向量由索引链路自动建立（job 队列的 `vector` 处理器），不设第二个入口 ——
        所以「未建」指路只能指「等索引完成」，指别处就是假出路。
        """
        base = ("在上方输入关于这批文档的问题，点「提问」：答案从库里的正文原文中摘录，"
                "并附证据卡，双击证据卡直接打开那一页。")
        if vectors:
            self.empty_hint.setText(base)
        else:
            self.empty_hint.setText(base + "当前「向量 未建」：索引完成后会自动建立，"
                                     "建好之前提问检索不到内容。")

    def reload(self) -> None:
        """「视图 → 刷新状态」入口：重读范围与向量读数。"""
        self.refresh_scope()

    # —— 提问 ——

    def _ask(self) -> None:
        query = self.ask_input.text().strip()
        if not query:
            return
        self.empty_hint.setVisible(False)
        try:
            answer = self.ctx.qa.ask(query)
        except Exception as exc:  # noqa: BLE001 - 边界：模型/向量库抛什么都得让用户看见原文
            self._clear_cards()
            set_text_role(self.answer_label, "danger")
            self.answer_label.setText(f"检索失败：{exc}")
            return
        if answer.evidences:
            set_text_role(self.answer_label, "")   # 常态字色：答案有内容时不是提示语
        else:
            set_text_role(self.answer_label, "muted")
        self.answer_label.setText(answer.summary)
        self.note_label.setText(answer.note or EXCERPT_NOTE)
        self._show_evidences(answer.evidences)
        self.time_label.setText(f"检索耗时 {answer.elapsed_ms:,} ms")
        self._remember_history(query)
        self.refresh_scope()

    def _show_evidences(self, evidences: tuple[Evidence, ...]) -> None:
        self._clear_cards()
        for evidence in evidences:
            card = _EvidenceCard(evidence)
            card.activated.connect(self.open_in_reader)
            self._cards_lay.addWidget(card)
            self._cards.append(card)

    def _clear_cards(self) -> None:
        for card in self._cards:
            self._cards_lay.removeWidget(card)
            card.deleteLater()
        self._cards = []

    # —— 历史提问（内存态）——

    def _remember_history(self, query: str) -> None:
        """去重置顶：刚问过的在最上面，再问同一个不重复记（同名旧条从中间摘掉再插顶）。"""
        for i in range(self.history_list.count()):
            if self.history_list.item(i).text() == query:
                self.history_list.takeItem(i)
                break
        self.history_list.insertItem(0, QtWidgets.QListWidgetItem(query))
        while self.history_list.count() > HISTORY_MAX_ITEMS:
            self.history_list.takeItem(self.history_list.count() - 1)
        sync_hint(self.history_list)

    def _replay_history(self, item: QtWidgets.QListWidgetItem) -> None:
        self.ask_input.setText(item.text())
        self._ask()

    # —— D-040 降级 ——

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt 命名
        super().resizeEvent(event)
        self._history_pane.setVisible(self.width() >= TWO_COLUMN_MIN_WIDTH)
