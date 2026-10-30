"""S2 PDF 阅读器 —— 甲·乙·甲（2026-10-15 定案）。

布局：
- 顶部工具栏：页码导航、缩放（「适应宽度」+ 手动两颗）、搜索
- 主区域：PDF 渲染（使用 PyMuPDF）
- 底部状态栏：当前页/总页数、文档信息

阅读器需要记住"上次读到哪一页"，关闭时自动保存进度。
"""
from __future__ import annotations

import math

from PySide6 import QtCore, QtGui, QtWidgets

from pdfarchiver.services import pdf_view
from pdfarchiver.services.bootstrap import AppContext
from pdfarchiver.ui.viewport_fit import HostResizeWatcher

# 手动轴（**Q2 乙**，轮四十七 实测）。上限从 3.0 抬到 4.0：2560 档要看清一处局部需要 3.92，
# 3.0 正好卡在那一步够不着的地方；抬到 4.0 时单页渲染 2382×3368 = 8.02M 像素，仍在下面的预算内。
_ZOOM_MIN = 0.3
_ZOOM_MAX = 4.0
_ZOOM_STEP = 1.2

# 「适应宽度」那一态**不受手动轴卡**（**Q2 甲**：卡了就永远占不满 2560 档，那正是②的病），
# 它卡的是单次渲染的像素预算：A4 在 2560 档铺满 = 2333×3299 = 7.70M，留 1.5 倍余量 ⇒ 12M。
# 超预算时按预算夹，此时横向留一点空是**设计内**的（断言放过这一种）。
_FIT_PIXEL_BUDGET = 12_000_000

# 拖着窗边改宽时，每变 1px 就重铺一整页（最贵 8M 像素）会把手感拖成幻灯片。这一段只是
# **拖窗那一路**的防抖；点按钮与翻页仍然同步重铺，不然"按下要立刻铺满"就变成"等一下才动"。
_REFIT_DEBOUNCE_MS = 120

# 重铺之后竖滚条要不要占位会改变可视宽（本机量到的是 807 ⇄ 799，那条 `sizeHint()` 只有 8px），
# 于是又进来一次 Resize。两次倍率没变化就不重铺 —— 铺一遍是几百万像素，同一个数字再画一遍纯属白干。
# 这一档必须**远小于一条滚条的宽度占比**（8/807 ≈ 1%）：卡到 1% 以上，那条缝就被判成"已经收敛"，
# 横向永远留一条谁也没要的空白。实测横版页那一跳是 0.9489 → 0.9584（1.0%），照常铺第二次，
# 铺完差=0、第三次进来时倍率已不再动 ⇒ 停。
_REFIT_CONVERGENCE = 0.005


class ReaderPage(QtWidgets.QWidget):
    """S2：PDF 阅读器。"""

    def __init__(self, ctx: AppContext, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.ctx = ctx
        self._current_doc_id: int | None = None
        self._doc: pdf_view.Document | None = None
        self._current_page = 0
        self._zoom_level = 1.0

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        if not pdf_view.AVAILABLE:
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

        # 「适应宽度」是这一态的**可见出口**（**Q1 甲-1**）：可按下，开着 = 按下，点放大/缩小即弹起。
        # 放在手动两颗**之前**、且不改动那两颗的次序 —— 它们原样留着，新加的那颗只是接管宽档。
        # 默认开（2026-10-31 用户点名；甲-1 原判默认关，甲-3 才默认开）：宽屏首帧就铺满，
        # 不用每启动一次按一次 —— `_render_page` 在开着时按现视口现算，首开即生效。
        self.fit_btn = QtWidgets.QPushButton("适应宽度")
        self.fit_btn.setObjectName("fitWidthBtn")
        self.fit_btn.setCheckable(True)
        self.fit_btn.setChecked(True)
        self.fit_btn.clicked.connect(self._on_fit_clicked)
        toolbar.addWidget(self.fit_btn)

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

        # 这一态跟着画布宽走：观察者与动作行末格用的是同一份形状（`ui/viewport_fit.py`）——
        # 只跟 Resize、只比 Python 包装对象、重入挡一层，那三条实测坑一条不少。
        self._refit_timer = QtCore.QTimer(self)
        self._refit_timer.setSingleShot(True)
        self._refit_timer.setInterval(_REFIT_DEBOUNCE_MS)
        self._refit_timer.timeout.connect(self._refit_now)
        HostResizeWatcher(self.pdf_view.viewport(), self._on_viewport_width).attach()

        # 底部状态栏
        self.status_label = QtWidgets.QLabel("")
        self.status_label.setObjectName("muted")
        layout.addWidget(self.status_label)

    def open_document(self, doc_id: int, page_no: int | None = None) -> None:
        """打开指定文档。`page_no` 是 S1 命中面板给的那一页（1 基，与 `text_pages.page_no` 同源）。

        **越界不许"就近取整"**（§S2 的断言点写死了：「`page_no` 越界必须拒绝并显示原因」）：
        库里记的页码与文件真实页数可以不一致（解析后被换过、OCR 只跑了一半），
        静悄悄落到第 1 页就是让用户对着错的那一页确认自己找的东西。
        """
        if not pdf_view.AVAILABLE:
            return

        doc = self.ctx.documents.get(doc_id)
        if not doc or not doc.path:
            return

        try:
            self._doc = pdf_view.open_document(doc.path)
            self._current_doc_id = doc_id
            self._current_page = 0

            # 恢复上次阅读进度
            if doc.last_read_page and 1 <= doc.last_read_page <= len(self._doc):
                self._current_page = doc.last_read_page - 1

            refused = ""
            if page_no is not None:
                if 1 <= page_no <= len(self._doc):
                    self._current_page = page_no - 1
                else:
                    refused = (f"｜第 {page_no} 页不存在（这份共 {len(self._doc)} 页），"
                               f"已停在第 {self._current_page + 1} 页")
            self._render_page()
            self.status_label.setText(
                f"{doc.name} | {doc.page_count or len(self._doc)} 页{refused}")
        except Exception as exc:
            QtWidgets.QMessageBox.critical(self, "打开 PDF 失败", str(exc))

    def _render_page(self) -> None:
        if not self._doc or self._current_page < 0 or self._current_page >= len(self._doc):
            return

        if self.fit_btn.isChecked():
            # 「适应宽度」开着 ⇒ 倍率在**渲染这一刻**按现视口重算，不沿用上一次的存值：
            # 翻页可能换到一页不同宽窄的纸（横版、票据条），拖窗宽更要重算 —— 两条路共用这一句，
            # 于是"这一态听谁的"全站只有一处口径。
            self._zoom_level = self._fit_zoom()

        page = self._doc[self._current_page]
        mat = pdf_view.Matrix(self._zoom_level, self._zoom_level)
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
        self.fit_btn.setChecked(False)   # 手动一动就退出这一态：不弹起就没法表达"现在到底听谁的"
        self._zoom_level = min(_ZOOM_MAX, self._zoom_level * _ZOOM_STEP)
        self._render_page()

    def _zoom_out(self) -> None:
        self.fit_btn.setChecked(False)
        self._zoom_level = max(_ZOOM_MIN, self._zoom_level / _ZOOM_STEP)
        self._render_page()

    # —— 「适应宽度」那一态（**Q1 甲-1 / Q2 甲**）————————————————

    def _on_fit_clicked(self) -> None:
        """按下这颗 = 立刻按现视口重铺一次；弹起 = 什么都不动，当前倍率就地变成手动轴的现值。

        走 `clicked` 不走 `toggled`：后者在**程序**改状态时同样派发（`_zoom_in` / `_zoom_out`
        里那句 `setChecked(False)`），这一态的可见出口就此变成重铺的触发器 —— 谁也没按按钮，
        整页却已经画了两遍（最贵的一档 8M 像素）。钉它的是 `test_手动缩放弹起…` 里那句
        「点一次「放大」只铺一遍」。
        """
        if self.fit_btn.isChecked() and self._doc is not None:
            self._render_page()

    def _on_viewport_width(self, _width: int) -> None:
        """画布每变一次宽：只给停手之后的那一次重铺排队（`_REFIT_DEBOUNCE_MS` 的注释）。"""
        if self.fit_btn.isChecked():
            self._refit_timer.start()

    def _refit_now(self) -> None:
        if not self.fit_btn.isChecked() or self._doc is None:
            return
        zoom = self._fit_zoom()
        if abs(zoom - self._zoom_level) <= self._zoom_level * _REFIT_CONVERGENCE:
            return          # 已在收敛带内：重铺一遍只会画出同一张图
        self._render_page()

    def _fit_zoom(self) -> float:
        """倍率 = 画布可视宽 ÷ 这一页 1.0 倍时的渲染宽（**Q1 甲-1 的算式，全站只这一处**）。

        竖滚条那一条**只在它还没占位时**才扣：`viewport().width()` 报的是"滚条排完版之后"的宽，
        它已经挂着的时候这个数就少了一条（实测 807 ⇄ 799），再扣一次就是双扣 ——
        2560 档量出来是渲染 2327 / 视口 2335，右边留一条谁也没要的 8px 缝。
        它此刻没挂上而这一页铺满之后又要超可视高时，必须先把它那条让出来再说，
        否则"按 2335 算、画出来只有 2327"之外还会多出一根永远消不掉的横向滚条 —— ② 的病根。
        """
        page = self._doc[self._current_page]
        width, height = page.rect.width, page.rect.height
        viewport = self.pdf_view.viewport()
        avail = viewport.width()
        if avail < 1 or width < 1 or height < 1:
            # 还没进过布局（从没显示过的窗口）：此刻的读数不是可视宽，不拿它算倍率。
            return self._zoom_level
        zoom = avail / width
        bar = self.pdf_view.verticalScrollBar()
        if not bar.isVisible() and height * zoom > viewport.height():
            zoom = (avail - bar.sizeHint().width()) / width
        return min(zoom, math.sqrt(_FIT_PIXEL_BUDGET / (width * height)))

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:
        """关闭时保存阅读进度。"""
        if self._doc:
            self._doc.close()
        super().closeEvent(event)
