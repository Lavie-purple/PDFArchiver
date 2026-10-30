"""首次启动分步引导窗（轮四十三 甲 · 用户 2026-10-30 勾选）。

方案甲 · 独立模态向导窗：首启动弹一个居中 QDialog，一屏一步共 3 屏 ——
① 启动语义（黑窗口别关 + 数据只在本机）→ ② 选择要监测的目录（选完立即登记，
与 S7「添加目录」同一条 `ctx.register_root` 路径）→ ③ 验收说明（回 S1 搜一次）。

跳过 / 完成 / 勾了「以后不再显示」再关窗 → 写 `app_settings["ui.wizard.done"]`；
直接 ✕ 且没勾 → 不写，下次启动还会弹。以后可从 S7 一键重开。

关窗不许被引导窗卡住：外壳 `closeEvent` 会先合上这里（G20 的 `--exit-after`
首启冒烟就是靠这条路退出的）。
"""
from __future__ import annotations

import logging

from PySide6 import QtCore, QtWidgets

from pdfarchiver.services.bootstrap import AppContext

log = logging.getLogger("pdfarchiver.ui.onboarding")

#: 「看过引导」的唯一存放键。放 `app_settings`（应用内部状态），不进 settings.json。
ONBOARDING_KEY = "ui.wizard.done"

WELCOME_TEXT = "欢迎使用"
CONSOLE_NOTE = "启动时会伴随一个黑色命令行窗口，请不要关它——关闭主窗口时它会一起退出。"
LOCAL_NOTE = "你的文件和数据库只存在本机。"
NOT_ASK_CHECK = "以后不再显示"
STEP2_TITLE = "告诉我要整理哪个文件夹："
STEP2_PICK = "选择目录..."
STEP2_NOTE = "选完立即登记，可跳过以后在设置里再设。"
STEP3_TITLE = "验收一下："
STEP3_BODY = ("回到「文档库」，在搜索框输入一个词按回车，\n能出命中就说明一切就绪。")


class OnboardingWizard(QtWidgets.QDialog):
    def __init__(self, ctx: AppContext, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.ctx = ctx
        self._done = False
        self.setWindowTitle("首次使用引导")
        self.setMinimumSize(420, 260)

        self.steps = QtWidgets.QStackedWidget()
        self.steps.addWidget(self._build_step1())
        self.steps.addWidget(self._build_step2())
        self.steps.addWidget(self._build_step3())

        self.prev_btn = QtWidgets.QPushButton("← 上一步")
        self.prev_btn.clicked.connect(self._go_prev)
        self.next_btn = QtWidgets.QPushButton("下一步 →")
        self.next_btn.clicked.connect(self._go_next)
        self.skip_btn = QtWidgets.QPushButton("跳过")
        self.skip_btn.clicked.connect(self._skip)
        btns = QtWidgets.QHBoxLayout()
        btns.addWidget(self.skip_btn)
        btns.addStretch()
        btns.addWidget(self.prev_btn)
        btns.addWidget(self.next_btn)

        lay = QtWidgets.QVBoxLayout(self)
        lay.addWidget(self.steps, 1)
        lay.addLayout(btns)

        self._sync_buttons()

    # ---- 三屏 ----

    def _build_step1(self) -> QtWidgets.QWidget:
        w = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(w)
        lay.addStretch()
        title = QtWidgets.QLabel(WELCOME_TEXT)
        title.setObjectName("sectionTitle")
        title.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(title)
        for note in (CONSOLE_NOTE, LOCAL_NOTE):
            label = QtWidgets.QLabel(note)
            label.setWordWrap(True)
            lay.addWidget(label)
        lay.addSpacing(12)
        self.not_ask_check = QtWidgets.QCheckBox(NOT_ASK_CHECK)
        lay.addWidget(self.not_ask_check)
        lay.addStretch()
        return w

    def _build_step2(self) -> QtWidgets.QWidget:
        w = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(w)
        lay.addStretch()
        title = QtWidgets.QLabel(STEP2_TITLE)
        title.setWordWrap(True)
        lay.addWidget(title)
        self.pick_btn = QtWidgets.QPushButton(STEP2_PICK)
        self.pick_btn.clicked.connect(self._pick_root)
        lay.addWidget(self.pick_btn)
        self.root_note = QtWidgets.QLabel(STEP2_NOTE)
        self.root_note.setObjectName("muted")
        self.root_note.setWordWrap(True)
        lay.addWidget(self.root_note)
        lay.addStretch()
        return w

    def _build_step3(self) -> QtWidgets.QWidget:
        w = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(w)
        lay.addStretch()
        title = QtWidgets.QLabel(STEP3_TITLE)
        lay.addWidget(title)
        body = QtWidgets.QLabel(STEP3_BODY)
        body.setWordWrap(True)
        lay.addWidget(body)
        lay.addStretch()
        return w

    # ---- 导航与收尾 ----

    def _go_prev(self) -> None:
        # 第一屏上「上一步」本来就藏着（`_sync_buttons`），点不到；Qt 自己把越界索引收在 0，不再另夹一层。
        self.steps.setCurrentIndex(self.steps.currentIndex() - 1)
        self._sync_buttons()

    def _go_next(self) -> None:
        if self.steps.currentIndex() >= self.steps.count() - 1:
            self._finish()
            return
        self.steps.setCurrentIndex(self.steps.currentIndex() + 1)
        self._sync_buttons()

    def _sync_buttons(self) -> None:
        first = self.steps.currentIndex() == 0
        last = self.steps.currentIndex() == self.steps.count() - 1
        self.prev_btn.setVisible(not first)
        self.skip_btn.setVisible(first)
        self.next_btn.setText("完成" if last else "下一步 →")

    def _skip(self) -> None:
        self._finish()

    def _finish(self) -> None:
        self._mark_done()
        self.accept()

    def _mark_done(self) -> None:
        if self._done:
            return
        self._done = True
        try:
            self.ctx.app_settings.set(ONBOARDING_KEY, True)
        except Exception:  # noqa: BLE001 - 引导看没看过不该拦住正常使用
            log.exception("写入 %s 失败（下次启动会再弹一次引导）", ONBOARDING_KEY)

    def _pick_root(self) -> None:
        raw = QtWidgets.QFileDialog.getExistingDirectory(self, "选择要监测的目录")
        if not raw:
            return
        try:
            self.ctx.register_root(raw)
        except Exception as exc:  # noqa: BLE001 - 用户挑的目录可能读不动，回显原文
            QtWidgets.QMessageBox.critical(self, "添加监测目录失败", str(exc))
            return
        self.root_note.setText(f"已登记监测目录：{raw}")

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt 命名
        # 直接 ✕：只有明确勾了「以后不再显示」才算看过；没勾的下次还弹。
        if not self._done and self.not_ask_check.isChecked():
            self._mark_done()
        super().closeEvent(event)
