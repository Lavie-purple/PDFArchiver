"""未实现屏的说明页：一句话讲清"为什么这里还是空的"。

故意不放任何占位控件、假表格、假进度条 —— SPEC 附带的硬规矩是「不允许假数据和模拟进度」。
"""
from __future__ import annotations

from PySide6 import QtCore, QtWidgets

from pdfarchiver.ui.nav import NavItem


class PendingPage(QtWidgets.QWidget):
    def __init__(self, item: NavItem, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        label = QtWidgets.QLabel(
            f"<b>{item.title}</b>（SPEC {item.spec}）<br><br>"
            f"本屏尚未实现。阻塞原因：{item.blocked_by}<br><br>"
            "AGENTS.md 规定线框未经逐屏确认前不写界面代码，所以这里不放任何占位控件。")
        label.setWordWrap(True)
        label.setAlignment(QtCore.Qt.AlignmentFlag.AlignTop | QtCore.Qt.AlignmentFlag.AlignLeft)
        label.setTextInteractionFlags(QtCore.Qt.TextInteractionFlag.TextSelectableByMouse)
        lay = QtWidgets.QVBoxLayout(self)
        lay.addWidget(label)
        lay.addStretch(1)
