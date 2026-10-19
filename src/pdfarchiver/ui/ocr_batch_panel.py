"""S1「送去识别」选中多份时就地展开的那块批次面板 —— **ISSUES I67** 乙（2026-10-19 勾「甲先乙后」）。

线框 `docs/wireframes/2026-10-19-round14-i67-i78.html` §I67-yi 画的是：表格里 Ctrl/Shift 选若干 →
那颗按钮变成「送去识别（选中 N 份）」→ 按下去在表格底下**就地展开**一块面板（不是模态框），
上面写清「该跑几份 / 不跑几份 / 每一类不跑的是哪几份 / 今日预算 / 代价」，再给「排队」「取消」。

三条不是偏好而是后果的约定：

- **面板上的每个数都由服务层算**（`OcrService.plan_ocr`）。界面判 `ocr_ready`、比引擎版本、
  数"哪几份还没索引"，就是给同一件事造第二个口径 —— 那两个数迟早和真排队之后的回执漂开
  （**ISSUES I60** 同一条纪律；线框 §I67-yi「估算归谁算」那条）。
- **不排队也能看清账**：`plan_ocr` 与 `request_ocr` 共用同一个 `_split`，所以「该跑 7 份」与
  按下「排队」之后那句「该跑 7 份」是同一个判据的两次读法，不是"预览一套、执行另一套"
  （与归档预览那条 `plan()/submit()` 同源同形，**D-043**）。
- **预算不够时不许静默**（**ISSUES I67** 销账判定③）：面板上明写「今日预算不够跑完这一批」，
  「排队」按下去也原样把 `SKIP_BUDGET` 那句上屏，而不是排进一条永远不动的任务让人猜。

单份走的是甲案那条老路（点一下就排队，回执上屏，见 `test_ocr_entry_ui.py`）：一份不需要面板。
"""
from __future__ import annotations

from collections.abc import Callable

from PySide6 import QtWidgets

from pdfarchiver.services.bootstrap import AppContext
from pdfarchiver.services.ocr_service import OcrPlan, SkippedReason

#: 那一行标题右边的展开钮默认写「展开」；按下换「收起」。文案只有一个出处，测试逐字比对用它。
EXPAND_TEXT = "展开"
COLLAPSE_TEXT = "收起"


class ReasonRow(QtWidgets.QWidget):
    """一类跳过理由：一行标题（措辞来自后端 `SKIP_LABELS`）+ 一个能指到具体份名的展开区。"""

    def __init__(self, item: SkippedReason, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.item = item
        head = QtWidgets.QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(6)

        self.title_label = QtWidgets.QLabel(item.label())
        self.title_label.setObjectName("muted")
        self.title_label.setWordWrap(True)
        head.addWidget(self.title_label, 1)

        self.toggle_btn = QtWidgets.QPushButton(EXPAND_TEXT)
        self.toggle_btn.setObjectName("searchBtn")
        self.toggle_btn.setCheckable(True)
        head.addWidget(self.toggle_btn)

        self.detail_label = QtWidgets.QLabel(item.name_preview())
        self.detail_label.setObjectName("muted")
        self.detail_label.setWordWrap(True)
        self.detail_label.setVisible(False)

        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(2)
        outer.addLayout(head)
        outer.addWidget(self.detail_label)
        self.toggle_btn.toggled.connect(self._on_toggled)

    def _on_toggled(self, on: bool) -> None:
        self.detail_label.setVisible(on)
        self.toggle_btn.setText(COLLAPSE_TEXT if on else EXPAND_TEXT)

    @property
    def expanded(self) -> bool:
        return self.detail_label.isVisible()


class OcrBatchPanel(QtWidgets.QWidget):
    """那块面板本体；点名对象与状态栏都由宿主页面（S1）递进来，它自己从不查库。"""

    def __init__(self, ctx: AppContext, *, set_status: Callable[..., None],
                 parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.ctx = ctx
        self._set_status = set_status
        self._ids: list[int] = []
        self._plan: OcrPlan | None = None

        self.outer = QtWidgets.QVBoxLayout(self)
        self.outer.setContentsMargins(0, 0, 0, 0)
        self.outer.setSpacing(2)

        # 每一句都 setWordWrap：不折行的 QLabel 其 minimumSizeHint() 等于整句宽，
        # 会把这一栏乃至窗口的最小宽顶过 D-039 的 1024 地板（library_page 状态栏同一坑）。
        self.summary_label = self._label()
        self.reason_box = QtWidgets.QWidget()
        self.reason_lay = QtWidgets.QVBoxLayout(self.reason_box)
        self.reason_lay.setContentsMargins(0, 0, 0, 0)
        self.reason_lay.setSpacing(2)
        self.cost_label = self._label()
        self.budget_label = self._label()

        btn_row = QtWidgets.QHBoxLayout()
        btn_row.setContentsMargins(0, 0, 0, 0)
        self.enqueue_btn = QtWidgets.QPushButton("排队")
        self.enqueue_btn.setObjectName("searchBtn")
        self.enqueue_btn.setToolTip("按上面这份账把它们排进识别队列（按页幂等，版本没变的页不再推理）")
        self.enqueue_btn.clicked.connect(self._on_enqueue)
        self.cancel_btn = QtWidgets.QPushButton("取消")
        self.cancel_btn.setObjectName("searchBtn")
        self.cancel_btn.clicked.connect(self.close_panel)
        btn_row.addWidget(self.enqueue_btn)
        btn_row.addWidget(self.cancel_btn)
        btn_row.addStretch(1)

        for w in (self.summary_label, self.reason_box, self.cost_label, self.budget_label):
            self.outer.addWidget(w)
        self.outer.addLayout(btn_row)
        self.setVisible(False)

    def _label(self) -> QtWidgets.QLabel:
        label = QtWidgets.QLabel("")
        label.setObjectName("muted")
        label.setWordWrap(True)
        return label

    @property
    def reason_rows(self) -> list[ReasonRow]:
        return [self.reason_lay.itemAt(i).widget() for i in range(self.reason_lay.count())]

    @property
    def plan(self) -> OcrPlan | None:
        return self._plan

    def open_for(self, doc_ids: list[int]) -> bool:
        """按这份账展开；服务层算不出这份账时（一次点名太多）把原文上屏并**不**展开。"""
        self._ids = list(doc_ids)
        try:
            self._plan = self.ctx.ocr.plan_ocr(self._ids)
        except Exception as exc:
            self._set_status(f"识别点名算不了这份账：{exc}", danger=True)
            self.close_panel()
            return False
        self._fill(self._plan)
        self.setVisible(True)
        return True

    def _fill(self, plan: OcrPlan) -> None:
        for i in reversed(range(self.reason_lay.count())):
            row = self.reason_lay.itemAt(i).widget()
            row.setParent(None)
            row.deleteLater()
        self.summary_label.setText(plan.describe())
        for item in plan.skipped:
            self.reason_lay.addWidget(ReasonRow(item))
        self.cost_label.setText(plan.cost_line())
        self.budget_label.setText(f"{self.ctx.ocr.budget.describe()}｜{plan.budget_note()}")

    def close_panel(self) -> None:
        self.setVisible(False)
        self._ids = []
        self._plan = None

    def _on_enqueue(self) -> None:
        """「排队」：把这份账交给 `request_ocr`，屏幕上那句逐字是它的回执（**I67** ①③）。

        `enqueued == 0` 时染红 —— 「按了但一条没进队列」必须在屏幕上看得见，
        与甲案那颗按钮同一条形状（**ISSUES I84** ③：失败要上屏原文，不许静默）。
        """
        ids = list(self._ids)
        try:
            request = self.ctx.ocr.request_ocr(ids)
        except Exception as exc:
            self._set_status(f"识别排队失败：{exc}", danger=True)
            return
        self._set_status(f"{request.describe()}｜{self.ctx.ocr.budget.describe()}",
                         danger=request.enqueued == 0)
        self.close_panel()
