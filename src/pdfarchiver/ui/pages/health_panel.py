"""S7 下半区的「库体检」面板（#198 · 1甲 2甲 3甲 4甲，2026-10-24）。

四件已定的事在这里各落一处，别在别处再写一份：

- **1甲 就地折叠**：它是 S7 下半区的第二页（`QStackedWidget`），不另开独立窗口 ——
  上半区那张状态页始终还在，体检读数与运行状态可以对照着看。
- **2甲 两档**：快速 / 全库。两档的成本说明照抄 `services/db_check.FULL_COST`，不在这里改写。
- **3甲 只报证据**：本面板没有"重跑索引""修复"按钮；红行的原文就是结论。
- **4甲 只存上次时间与计数**：写 `app_settings` 的是服务层，界面这里只显示。

**为什么全库体检在后台线程跑**：真库同口径两次实测约 57 分钟与约 67 分钟（C1 约 17–20 分、
C5 约 21–26 分、C11 约 16–17 分），
放在 GUI 线程里等于整个应用冻住一小时。用 `threading.Thread` + `Signal(object)` 回主线程，
不用 `QThread`：窗口关闭时 QThread 还在跑会打 "Destroyed while thread is still running"，
而 daemon 线程随进程退出、服务层在 `finally` 里把那条线程的连接还掉。

**本面板不自己算任何读数**：表格三列逐行来自 `DbCheckReport.rows`，红/通过/读数三个计数
来自报告自己的属性；界面只负责铺上去。
"""
from __future__ import annotations

import threading
import time

from PySide6 import QtCore, QtWidgets

from pdfarchiver.services.bootstrap import AppContext
from pdfarchiver.services.db_check import (
    FULL,
    FULL_COST,
    QUICK,
    QUICK_COST,
    DbCheckReport,
    format_duration,
)
from pdfarchiver.ui.library_hits import set_text_role
from pdfarchiver.ui.table_layout import set_table_columns


class HealthPanel(QtWidgets.QWidget):
    """两档体检按钮 + 一句成本说明 + 一张逐项读数表。"""

    #: 后台线程把报告递回主线程用的内部通道（跨线程的 emit 走队列连接）。
    _report_ready = QtCore.Signal(object)
    #: 报告已经铺上屏之后对外发一次，参数是 `DbCheckReport`。
    finished = QtCore.Signal(object)

    def __init__(self, ctx: AppContext, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.ctx = ctx
        self._running = False
        self._mode: str | None = None
        self._t0 = 0.0
        self._thread: threading.Thread | None = None

        self._timer = QtCore.QTimer(self)
        self._timer.setInterval(500)
        self._timer.timeout.connect(self._tick)
        self._report_ready.connect(self._on_report)

        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)

        self.intro_label = QtWidgets.QLabel(
            "只读体检：不修库、不重跑索引、不动文件。明细只显示在本页，库里只留上次的时间与计数。")
        self.intro_label.setWordWrap(True)
        self.intro_label.setObjectName("muted")
        lay.addWidget(self.intro_label)

        # 4甲 的界面半边：只显示上次的时间与三个计数，明细不在库里。放在本页而不是设置页标题栏，
        # 是因为设置页标题栏多这一行会把下半区的最低高度顶高 36px —— 720 窗高下上半区状态页
        # 会被挤到只看见 13 行（`test_status_readout.test_S7上半区按内容给高…` 实测）。
        self.last_check_label = QtWidgets.QLabel("上次体检：—")
        self.last_check_label.setObjectName("muted")
        self.last_check_label.setWordWrap(True)
        lay.addWidget(self.last_check_label)

        self.cost_label = QtWidgets.QLabel(QUICK_COST + "\n" + FULL_COST)
        self.cost_label.setWordWrap(True)
        self.cost_label.setObjectName("muted")
        lay.addWidget(self.cost_label)

        buttons = QtWidgets.QHBoxLayout()
        self.quick_btn = QtWidgets.QPushButton("快速体检")
        self.quick_btn.setToolTip(QUICK_COST)
        self.quick_btn.clicked.connect(lambda: self.start(QUICK))
        buttons.addWidget(self.quick_btn)

        self.full_btn = QtWidgets.QPushButton("全库体检…")
        self.full_btn.setToolTip(FULL_COST)
        self.full_btn.clicked.connect(self._confirm_full)
        buttons.addWidget(self.full_btn)
        buttons.addStretch()
        lay.addLayout(buttons)

        self.status_label = QtWidgets.QLabel("还没有跑过。快速体检是十几秒量级的，可先跑它。")
        self.status_label.setWordWrap(True)
        self.status_label.setObjectName("muted")
        lay.addWidget(self.status_label)

        self.table = QtWidgets.QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["检查项", "结果", "读数"])
        # 检查项那一列按最长标签反算（"C4 正文与索引花名册双向对账" 13 个 CJK + 3 个 ASCII
        # ≈ 190px，加 CELL_PADDING_WIDTH 23 = 213 → 给 220）；结果列只需容下「未通过」。
        # 读数那列内容天生没有上限（真库会报十几条例子），作 stretch 列并挂 tooltip 回读全文。
        set_table_columns(self.table, {0: 220, 1: 90}, stretch_col=2)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.setMinimumHeight(180)
        self.table.verticalHeader().setDefaultSectionSize(30)
        lay.addWidget(self.table, 1)

    # ---- 对外状态 ----

    @property
    def running(self) -> bool:
        return self._running

    def current_mode(self) -> str | None:
        return self._mode

    def set_last_check(self, text: str) -> None:
        self.last_check_label.setText(text)

    # ---- 起跑 ----

    def start(self, mode: str) -> None:
        """立即在后台线程里跑一档。已在跑时忽略重复点击（按钮也会禁用）。"""
        if self._running:
            return
        self._running = True
        self._mode = mode
        self._t0 = time.perf_counter()
        self._set_busy(True)
        self.table.setRowCount(0)
        self._status_text(f"{self._label(mode)}进行中… 已用 0 秒（界面可以继续用）", "muted")
        self._timer.start()

        def work() -> None:
            try:
                report = self.ctx.db_check.run(mode)
            except BaseException as exc:  # noqa: BLE001 - 没跑起来也要把原文交给界面
                report = self.ctx.db_check.failure_report(mode, exc)
            self._report_ready.emit(report)

        self._thread = threading.Thread(target=work, name=f"db-check-{mode}", daemon=True)
        self._thread.start()

    def _confirm_full(self) -> None:
        answer = QtWidgets.QMessageBox.question(
            self, "全库体检",
            FULL_COST + "\n\n运行期间不可中断；要中止只能退出应用（不会改库）。\n\n确定开始？")
        if answer == QtWidgets.QMessageBox.StandardButton.Yes:
            self.start(FULL)

    # ---- 收尾 ----

    @QtCore.Slot(object)
    def _on_report(self, report: DbCheckReport) -> None:
        self._timer.stop()
        self._running = False
        self._set_busy(False)
        self._fill(report)
        self._status_text(report.summary(), "danger" if report.red else "muted")
        self.finished.emit(report)

    # ---- 内部 ----

    @staticmethod
    def _label(mode: str) -> str:
        return "全库体检" if mode == FULL else "快速体检"

    def _set_busy(self, busy: bool) -> None:
        self.quick_btn.setEnabled(not busy)
        self.full_btn.setEnabled(not busy)

    def _tick(self) -> None:
        if not self._running:
            self._timer.stop()
            return
        self._status_text(f"{self._label(self._mode or '')}进行中… "
                          f"已用 {format_duration(time.perf_counter() - self._t0)}"
                          "（界面可以继续用；关掉应用会中止本次体检，不改库）", "muted")

    def _status_text(self, text: str, role: str) -> None:
        self.status_label.setText(text)
        set_text_role(self.status_label, role)

    def _fill(self, report: DbCheckReport) -> None:
        self.table.setRowCount(len(report.rows))
        for index, row in enumerate(report.rows):
            name = QtWidgets.QTableWidgetItem(f"{row.code} {row.label}")
            name.setToolTip(f"{row.code} {row.label}｜本条用时 {format_duration(row.seconds)}")
            self.table.setItem(index, 0, name)

            verdict = QtWidgets.QTableWidgetItem(row.verdict)
            verdict.setTextAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(index, 1, verdict)

            measured = QtWidgets.QTableWidgetItem(row.measured)
            measured.setToolTip(row.measured)
            self.table.setItem(index, 2, measured)
