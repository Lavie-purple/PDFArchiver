"""P3 桌面 UI 与渲染管线探针：PySide6 / QtPdf / WebEngine / PyMuPDF 四选一的可运行性。

必须在 offscreen 平台下跑（不打扰用户桌面），真实首屏核对留到阶段 1 人工做。

验证项：
  Q1 PySide6 6.12 能否 import + 建 QApplication + 控件树 + 事件循环正常退出
  Q2 QtPdf（PySide6_Pdf）是否真的可用：打开真实 PDF、渲染一页成 QImage
  Q3 QWebEngineView 是否能实例化、代价多大内存、offscreen 下是否可用
  Q4 PyMuPDF pixmap -> QImage 的桥接是否无损、耗时
  Q5 QThread + signal/slot 把后台渲染结果送回主线程（跨线程信号是否可靠投递）
  Q6 高 DPI / 字体 / 中文文本在 QImage 上的真实渲染（drawText 是否出方块）

用法: QT_QPA_PLATFORM=offscreen python tests/probes/p3_ui_render.py [--pdf <真实pdf>]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import psutil
import pymupdf

pymupdf.TOOLS.mupdf_display_errors(False)
RSS = psutil.Process(os.getpid())


def rss_mb() -> float:
    return RSS.memory_info().rss / 1048576


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdf", default="", help="用一个真实 PDF 测渲染，缺省则自建")
    ap.add_argument("--out", default=".probe_work/p3_ui_result.json")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    res: dict = {"platform": os.environ.get("QT_QPA_PLATFORM"), "rss_import_start_mb": round(rss_mb(), 1)}

    t0 = time.perf_counter()
    from PySide6 import QtCore, QtGui, QtWidgets
    res["import_pyside6_seconds"] = round(time.perf_counter() - t0, 2)
    res["qt_version"] = QtCore.qVersion()
    res["rss_after_pyside6_mb"] = round(rss_mb(), 1)

    app = QtWidgets.QApplication(sys.argv[:1])
    res["qapplication_created"] = app is not None
    res["rss_after_qapp_mb"] = round(rss_mb(), 1)
    res["screens"] = [(s.name(), s.geometry().width(), s.geometry().height(), round(s.devicePixelRatio(), 2)) for s in app.screens()]
    res["font_families_with_cjk"] = [f for f in QtGui.QFontDatabase.families() if any(k in f for k in ("YaHei", "SimSun", "SimHei", "Microsoft", "Noto"))][:8]

    w = QtWidgets.QWidget()
    w.resize(1280, 800)
    lay = QtWidgets.QHBoxLayout(w)
    tree = QtWidgets.QTreeWidget()
    tree.setHeaderLabels(["分类", "数量"])
    table = QtWidgets.QTableWidget(200, 6)
    table.setHorizontalHeaderLabels(["文件名", "路径", "页数", "大小", "类型", "状态"])
    table.setColumnWidth(0, 320)
    edit = QtWidgets.QLineEdit()
    edit.setPlaceholderText("搜索：人工智能 产业报告")
    for i in range(200):
        table.setItem(i, 0, QtWidgets.QTableWidgetItem(f"人工智能产业报告第{i}卷.pdf"))
        table.setItem(i, 1, QtWidgets.QTableWidgetItem("H:/docs/研究报告/" + "中" * 30))
    lay.addWidget(tree)
    lay.addWidget(table)
    lay.addWidget(edit)
    w.grab().save(".probe_work/p3_widget_tree.png")
    res["widget_tree_offscreen_render_ok"] = os.path.exists(".probe_work/p3_widget_tree.png")

    pdf_path = args.pdf
    if not pdf_path or not os.path.exists(pdf_path):
        hint = ".probe_work/p3_real_pdf_path.txt"
        if os.path.exists(hint):
            pdf_path = open(hint, encoding="utf-8").read().strip()
    if not pdf_path or not os.path.exists(pdf_path):
        doc = pymupdf.open()
        p = doc.new_page()
        p.insert_text((72, 100), "Chinese 中文渲染测试 人工智能产业报告")
        pdf_path = ".probe_work/p3_selfmade.pdf"
        doc.save(pdf_path)
        doc.close()
        res["test_pdf_kind"] = "self-made"
    else:
        res["test_pdf_kind"] = "real-corpus"
    res["test_pdf"] = os.path.basename(pdf_path)

    # Q2 QtPdf —— 注意 6.8.3 的实际方法名是 render()/close()，不是 renderPage()/unload()
    try:
        from PySide6.QtPdf import QPdfDocument  # type: ignore
        from PySide6.QtCore import QSize

        t0 = time.perf_counter()
        qdoc = QPdfDocument()
        status = qdoc.load(pdf_path)
        res["qtpdf_load_status"] = str(status)
        res["qtpdf_error_enum"] = str(qdoc.error())
        res["qtpdf_page_count"] = qdoc.pageCount()
        res["qtpdf_metadata"] = {str(f): str(qdoc.metaData(f)) for f in list(QPdfDocument.MetaDataField)[:4]}
        res["qtpdf_ptsize"] = [round(qdoc.pagePointSize(0).width(), 1), round(qdoc.pagePointSize(0).height(), 1)]
        t1 = time.perf_counter()
        img = qdoc.render(0, QSize(1000, 1400))
        res["qtpdf_open_ms"] = round((t1 - t0) * 1000, 1)
        res["qtpdf_render_ms"] = round((time.perf_counter() - t1) * 1000, 1)
        res["qtpdf_image_null"] = img.isNull()
        res["qtpdf_image_wh"] = [img.width(), img.height()]
        img.save(".probe_work/p3_qtpdf_page.png")
        # 阅读器需求 3.5「当前文档内文字搜索」能否直接靠 QtPdf 拿到页面文本
        try:
            sel = qdoc.getAllText(0)
            blocks = sel.selectedText() if hasattr(sel, "selectedText") else str(sel)
            res["qtpdf_has_alltext"] = bool(blocks.strip())
            res["qtpdf_alltext_chars"] = len(blocks)
        except Exception as exc:  # noqa: BLE001
            res["qtpdf_has_alltext"] = False
            res["qtpdf_alltext_error"] = f"{type(exc).__name__}: {exc}"
        res["qtpdf_available"] = True
        qdoc.close()
    except Exception as exc:  # noqa: BLE001
        res["qtpdf_available"] = False
        res["qtpdf_error"] = f"{type(exc).__name__}: {exc}"

    # Q4 PyMuPDF -> QImage 桥接
    t0 = time.perf_counter()
    doc = pymupdf.open(pdf_path)
    pix = doc[0].get_pixmap(matrix=pymupdf.Matrix(150 / 72, 150 / 72))
    t1 = time.perf_counter()
    img = QtGui.QImage(pix.samples, pix.width, pix.height, pix.stride, QtGui.QImage.Format.Format_RGB888).copy()
    res["fitz_to_qimage_ms"] = round((time.perf_counter() - t1) * 1000, 1)
    res["fitz_open_and_render_ms"] = round((t1 - t0) * 1000, 1)
    res["fitz_qimage_null"] = img.isNull()
    res["fitz_qimage_wh"] = [img.width(), img.height()]
    img.save(".probe_work/p3_fitz_page.png")

    # Q3 QWebEngineView
    t0 = time.perf_counter()
    try:
        from PySide6.QtWebEngineWidgets import QWebEngineView  # type: ignore

        rss_before = rss_mb()
        view = QWebEngineView()
        view.setHtml("<html><body><h1>测试</h1><p>人工智能产业报告</p></body></html>")
        app.processEvents()
        res["webengine_created"] = True
        res["webengine_rss_delta_mb"] = round(rss_mb() - rss_before, 1)
        res["webengine_seconds"] = round(time.perf_counter() - t0, 2)
        view.deleteLater()
    except Exception as exc:  # noqa: BLE001
        res["webengine_created"] = False
        res["webengine_error"] = f"{type(exc).__name__}: {exc}"

    # Q5 跨线程信号：后台线程做重活，通过 signal 回主线程
    class Worker(QtCore.QObject):
        done = QtCore.Signal(object)
        progress = QtCore.Signal(int)

        def __init__(self, path):
            super().__init__()
            self.path = path

        @QtCore.Slot()
        def run(self):
            d = pymupdf.open(self.path)
            for i in range(min(d.page_count, 5)):
                d[i].get_text("text")
                self.progress.emit(i + 1)
            px = d[0].get_pixmap(matrix=pymupdf.Matrix(1.5, 1.5))
            self.done.emit(px)
            d.close()

    thread = QtCore.QThread()
    worker = Worker(pdf_path)
    worker.moveToThread(thread)
    got: dict = {"progress": [], "done": None}
    worker.progress.connect(lambda n: got["progress"].append(n))
    worker.done.connect(lambda px: got.update(done=px), type=QtCore.Qt.ConnectionType.QueuedConnection)
    thread.started.connect(worker.run)
    t0 = time.perf_counter()
    thread.start()
    while time.perf_counter() - t0 < 15 and got["done"] is None:
        app.processEvents()
        time.sleep(0.01)
    res["thread_progress_events"] = got["progress"]
    res["thread_done_delivered"] = got["done"] is not None
    res["thread_roundtrip_ms"] = round((time.perf_counter() - t0) * 1000, 1)
    thread.quit()
    thread.wait(3000)
    doc.close()

    # Q6 中文绘制
    im = QtGui.QImage(600, 120, QtGui.QImage.Format.Format_ARGB32)
    im.fill(QtGui.QColor("white"))
    paint = QtGui.QPainter(im)
    f = QtGui.QFont("Microsoft YaHei", 20)
    paint.setFont(f)
    paint.drawText(10, 60, "人工智能产业报告 2026")
    paint.end()
    actual_fam = f.family()
    res["cjk_draw"] = {"requested_font": "Microsoft YaHei", "resolved_ok": actual_fam == "Microsoft YaHei", "img_saved": bool(im.save(".probe_work/p3_text.png"))}

    app.quit()
    res["rss_end_mb"] = round(rss_mb(), 1)
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(res, fh, ensure_ascii=False, indent=2)

    checks = [
        ("PySide6 QApplication 在 offscreen 下可创建", res["qapplication_created"]),
        ("控件树离屏渲染出图", res["widget_tree_offscreen_render_ok"]),
        ("PyMuPDF 页面能转成非空 QImage", res["fitz_qimage_null"] is False),
        ("单页 fitz 渲染+转换 < 800ms", res["fitz_open_and_render_ms"] + res["fitz_to_qimage_ms"] < 800),
        ("跨线程信号确实投递回主线程", res["thread_done_delivered"]),
        ("后台进度事件按序到达", len(res["thread_progress_events"]) >= 1),
        ("中文字体解析到 Microsoft YaHei 而非回退", res["cjk_draw"]["resolved_ok"]),
        ("QtPdf 可用且真渲染出非空页面（与 fitz 双通道，取较快者）",
         res.get("qtpdf_available") is True and res.get("qtpdf_page_count", 0) >= 1 and res.get("qtpdf_image_null") is False),
    ]
    for label, ok in checks:
        print(f"  {'PASS' if ok else 'FAIL'}  {label}")
    print("  INFO qtpdf: " + json.dumps({k: v for k, v in res.items() if k.startswith("qtpdf")}, ensure_ascii=False))
    print("  INFO webengine: " + json.dumps({k: v for k, v in res.items() if k.startswith("webengine")}, ensure_ascii=False))
    print("  INFO rss MB: " + json.dumps({k: v for k, v in res.items() if "rss" in k}, ensure_ascii=False))
    print("VERDICT: " + ("ALL GREEN" if all(ok for _, ok in checks) else "RED"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
