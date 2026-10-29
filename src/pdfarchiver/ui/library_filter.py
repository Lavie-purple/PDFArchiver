"""S1 筛选区的全部现场（轮四十二 ⑬）：筛选条、「按当前筛选送识别」与收放它们的容器。

**ISSUES I96** 甲（2026-10-30）从 `ui/pages/library_page.py` 整段搬来，理由与
`ui/library_hits.py` 同一条：那一屏的接线只增不减，700 行自线是"下一次写入就会违约"的
形状。**为什么是 mixin 而不是一个独立控件**也同一条 —— `FilterBar` 与 `filter_area` 挂在
页面中栏的布局里，`tests/integration/test_ocr_on_demand.py` 等断言认的是
`page.filter_bar` / `page.filter_ocr_btn` / `page.filter_toggle` 这些页面属性，
换访问路径等于让断言跟着实现改。混入让控件仍然挂在页面对象上，归属只挪了文件。

混入方（`ui/pages/library_page.py` 的 `LibraryPage`）须提供：
`self.ctx`（AppContext）、`self._set_status`（状态栏出口）、`self._apply_query`
（筛选条递条件的落点）、`self._query`（"有无条件"是收放的自动档）、
`self._update_ocr_hint`（右栏那条情境提示，`LibraryHitsMixin` 提供）。

搜索编排、浏览分页与 `_apply_query` 本体**留在页面里**：一次条件变化要同时写
中栏表、状态栏、右栏与这一区四处状态，拆开就是两边各拿一半。
"""
from __future__ import annotations

from PySide6 import QtCore, QtWidgets

from pdfarchiver.services.bootstrap import AppContext  # noqa: F401 - 文档化混入契约
from pdfarchiver.ui.collection_bar import FilterBar

#: 轮三十六 甲：「按当前筛选」那颗按钮的基础文案（与「送去识别」认的东西不同 ——
#: 它认 `filter_bar` 那份筛选，不认表格里的选中）。份数由 `PendingOcr` 递上来，不在界面里数。
FILTER_OCR_BTN_TEXT = "按当前筛选送识别"


class LibraryFilterMixin:
    """筛选区的构造与收放逻辑；控件仍归页面（`page.xxx` 访问路径不变）。"""

    def _build_filter_area(self, center_lay: QtWidgets.QVBoxLayout) -> None:
        """筛选区（轮四十二 ⑬）：筛选条 + 「按当前筛选送识别」收进一块**默认收起**的容器，
        入口是那颗常驻的「筛选与集合」—— 条件多的时候它们是三排控件，一条条件都没加
        时挂在屏幕上是堆积。规则：有条件（chips 非空）自动展开，没条件自动收起；
        用户点开关手动收放的意愿在"有无条件"变化前一直生效（`_filter_manual`）。"""
        self.filter_toggle = QtWidgets.QToolButton()
        self.filter_toggle.setObjectName("filterToggle")
        self.filter_toggle.setAutoRaise(True)
        self.filter_toggle.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        self.filter_toggle.clicked.connect(self._toggle_filter_area)
        self._update_filter_toggle(False)
        center_lay.addWidget(self.filter_toggle)

        self.filter_area = QtWidgets.QWidget()
        filter_lay = QtWidgets.QVBoxLayout(self.filter_area)
        filter_lay.setContentsMargins(0, 0, 0, 0)
        filter_lay.setSpacing(4)

        # 筛选条（**ISSUES I78** 乙）：chips 就是这一页的筛选状态，取数只认它递下来的那份 dict。
        self.filter_bar = FilterBar(self.ctx, on_query_changed=self._apply_query,
                                    set_status=self._set_status)
        filter_lay.addWidget(self.filter_bar)

        # —— 轮三十六 甲：「按当前筛选送识别」—— 解决"待识别 2,457 份，但入口只有'在表格里
        # 勾几份'"。它排的是上面那份筛选下的**全部**待识别份（`ocr_status='pending'`），
        # 名单与份数都来自 `ctx.ocr.pending_in` 一个出口；按下去先展开同一块批次面板算账
        # （该跑/不跑/代价/预算），确认后才排队 —— 与「送去识别」同一条老路，不是第二个实现。
        # 位置紧贴筛选条、**不跟**「送去识别」同一排：那一颗认"表格里勾了哪几份"，这一颗认
        # "筛选命中的那一批"，两句并排在同一行会让人以为它们是同一件事的两种说法。
        # 同理也不进 `ocr_row`：面板展开时「送去识别（选中 2 份）」会变宽，那一排实测已到
        # 823 地板档的边上（`test_面板展开时页面与窗口都不许顶过地板宽度`）。
        filter_ocr_row = QtWidgets.QHBoxLayout()
        self.filter_ocr_btn = QtWidgets.QPushButton(FILTER_OCR_BTN_TEXT)
        self.filter_ocr_btn.setObjectName("clearBtn")
        self.filter_ocr_btn.setEnabled(False)
        self.filter_ocr_btn.clicked.connect(self._on_filter_ocr_requested)
        filter_ocr_row.addWidget(self.filter_ocr_btn)
        filter_ocr_row.addStretch(1)
        filter_lay.addLayout(filter_ocr_row)
        # 默认收起（`_filter_manual=None` 时按"有无条件"自动收放）。
        self._filter_manual: bool | None = None
        self.filter_area.setVisible(False)
        center_lay.addWidget(self.filter_area)
        # 「按当前筛选送识别」的读数（轮三十六 甲）：`PendingOcr` 或 None（还没读过）。
        # 由 `_refresh_pending_ocr` 写，按钮与提示条都只认这一份，不各自再查一次库。
        self._pending_ocr = None

    def _toggle_filter_area(self) -> None:
        """手动开关：记住用户这次收放的意愿，直到"有无条件"变化才交还给自动规则。"""
        self._filter_manual = not self.filter_area.isVisible()
        self._update_filter_area()

    def _update_filter_area(self) -> None:
        """可见 = 手动意愿，没有意愿就按"有无条件"自动收放。"""
        visible = bool(self._filter_manual) if self._filter_manual is not None \
            else bool(self._query)
        self.filter_area.setVisible(visible)
        self._update_filter_toggle(visible)

    def _update_filter_toggle(self, expanded: bool) -> None:
        self.filter_toggle.setText(("▾ 筛选与集合" if expanded else "▸ 筛选与集合")
                                   + ("" if expanded else "（未加条件）"))
        self.filter_toggle.setToolTip("展开筛选条与「按当前筛选送识别」"
                                      if not expanded else "收起这一区（条件还在，不因收起而失效）")

    def _refresh_pending_ocr(self) -> None:
        """按当前筛选重读"待识别"读数（轮三十六 甲）：按钮上的份数与提示条都用这一份。

        数字与句子都不在这里算：份数/页数来自 `ctx.ocr.pending_in`（它再往下只有
        `documents.pending_ocr_totals / ids_pending_ocr` 一条 SQL），界面只负责贴上去。
        名单为空就把按钮置灰并收起提示条 —— 一颗点下去点不到任何一份的按钮不该亮着。
        """
        pending = self.ctx.ocr.pending_in(self._query)
        self._pending_ocr = pending
        self.filter_ocr_btn.setText(
            f"{FILTER_OCR_BTN_TEXT}（{pending.documents:,} 份）" if pending.documents
            else FILTER_OCR_BTN_TEXT)
        self.filter_ocr_btn.setEnabled(bool(pending.ids))
        self.filter_ocr_btn.setToolTip(
            f"{pending.describe()}；按下去先展开这批的账（该跑/不跑/代价/今日预算），确认后才排队"
            if pending.ids else "当前筛选里没有待识别的扫描件（已识别的与原生文字版都不在这一批）")
        if not pending.ids:
            self._update_ocr_hint(empty=False)

    def _on_filter_ocr_requested(self) -> None:
        """「按当前筛选送识别」/ 提示条那颗「送去识别这批」→ 同一块批次面板（轮三十六 甲）。

        复用的是 I67 乙 那块面板：它拿到 id 之后自己去 `plan_ocr` 算账，界面不重算，
        也不在按下按钮这一刻就写队列 —— 「先给账再排队」是那一块已验证的形状。
        """
        pending = self._pending_ocr
        if pending is None or not pending.ids:
            return
        self.ocr_panel.open_for(list(pending.ids))
