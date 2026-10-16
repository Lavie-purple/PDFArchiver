"""S2 PDF 阅读器 —— 甲·乙·甲（2026-10-15 定案）。

布局：
- 顶部工具栏：页码导航、缩放、搜索
- 主区域：PDF 渲染（使用 PyMuPDF）
- 底部状态栏：当前页/总页数、文档信息

阅读器需要记住"上次读到哪一页"，关闭时自动保存进度。
"""
from __future__ import annotations

from PySide6 import QtCore, QtGui, QtWidgets

from pdfarchiver.services.bootstrap import AppContext

try:
    import fitz  # PyMuPDF
    FITZ_AVAILABLE = True
except ImportError:
    FITZ_AVAILABLE = False


class ReaderPage(QtWidgets.QWidget):
    """S2：PDF 阅读器。"""

    def __init__(self, ctx: AppContext, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.ctx = ctx
        self._current_doc_id: int | None = None
        self._doc: fitz.Document | None = None if FITZ_AVAILABLE else None
        self._current_page = 0

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        if not FITZ_AVAILABLE:
            layout.addWidget(QtWidgets.QLabel("PyMuPDF 未安装，无法显示 PDF"))
            return

        # 顶部工具栏
        toolbar = QtWidgets.QHBoxLayout()
        self.prev_btn = QtWidgets.QPushButton("上一页")
        self.prev_btn.clicked.connect(self._prev_page)
        toolbar.addWidget(self.prev_btn)

        self.page_label = QtWidgets.QLabel("0 / 0")
        toolbar.addWidget(self.page_label)

        self.next_btn = QtWidgets.QPushButton("下一页")
        self.next_btn.clicked.connect(self._next_page)
        toolbar.addWidget(self.next_btn)

        toolbar.addStretch()

        self.zoom_in_btn = QtWidgets.QPushButton("放大")
        self.zoom_in_btn.clicked.connect(self._zoom_in)
        toolbar.addWidget(self.zoom_in_btn)

        self.zoom_out_btn = QtWidgets.QPushButton("缩小")
        self.zoom_out_btn.clicked.connect(self._zoom_out)
        toolbar.addWidget(self.zoom_out_btn)

        layout.addLayout(toolbar)

        # PDF 显示区域
        self.pdf_view = QtWidgets.QScrollArea()
        self.pdf_label = QtWidgets.QLabel()
        self.pdf_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.pdf_view.setWidget(self.pdf_label)
        self.pdf_view.setWidgetResizable(True)
        layout.addWidget(self.pdf_view, 1)

        # 底部状态栏
        self.status_label = QtWidgets.QLabel("")
        self.status_label.setObjectName("muted")
        layout.addWidget(self.status_label)

        self._zoom_level = 1.0

    def open_document(self, doc_id: int) -> None:
        """打开指定文档。"""
        if not FITZ_AVAILABLE:
            return

        doc = self.ctx.documents.get(doc_id)
        if not doc or not doc.path:
            return

        try:
            self._doc = fitz.open(doc.path)
            self._current_doc_id = doc_id
            self._current_page = 0

            # 恢复上次阅读进度
            if doc.last_read_page and 1 <= doc.last_read_page <= len(self._doc):
                self._current_page = doc.last_read_page - 1

            self._render_page()
            self.status_label.setText(f"{doc.name} | {doc.page_count or len(self._doc)} 页")
        except Exception as exc:
            QtWidgets.QMessageBox.critical(self, "打开 PDF 失败", str(exc))

    def _render_page(self) -> None:
        if not self._doc or self._current_page < 0 or self._current_page >= len(self._doc):
            return

        page = self._doc[self._current_page]
        mat = fitz.Matrix(self._zoom_level, self._zoom_level)
        pix = page.get_pixmap(matrix=mat)
        img = QtGui.QImage(pix.samples, pix.width, pix.height, pix.stride, QtGui.QImage.Format.Format_RGB888)
        pixmap = QtGui.QPixmap.fromImage(img)
        self.pdf_label.setPixmap(pixmap)

        self.page_label.setText(f"{self._current_page + 1} / {len(self._doc)}")

        # 保存阅读进度
        if self._current_doc_id is not None:
            self.ctx.documents.update_reading_progressress(self._current_doc_id, self._current_page + 1)

    def _prev_page(self) -> None:
        if self._current_page > 0:
            self._current_page -= 1
            self._render_page()

    def _next_page(self) -> None:
        if self._doc and self._current_page < len(self._doc) - 1:
            self._current_page += 1
            self._render_page()

    def _zoom_in(self) -> None:
        self._zoom_level = min(3.0, self._zoom_level * 1.2)
        self._render_page()

    def _zoom_out(self) -> None:
        self._zoom_level = max(0.3, self._zoom_level / 1.2)
        self._render_page()

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:
        """关闭时保存阅读进度。"""
        if self._doc:
            self._doc.close()
        super().closeEvent(event)
