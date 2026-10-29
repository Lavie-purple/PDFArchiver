"""S2 阅读器渲染用的 pymupdf 门面 —— ui 层不许直接依赖 PDF 引擎。

docs/ARCHITECTURE 二 规定依赖只能自上而下：pymupdf 只许 parsing 直接 import，
ui 经由 services 这一层拿渲染入口（`tests/guards/test_architecture.py`
FORBIDDEN_IMPORTS 钉着，旧名 `fitz` 同单禁止 —— 1.28 起弃用打警告）。
这里只转发 S2 用到的三样东西：打开文档、文档/矩阵类型、可用性标志；
不复制 pymupdf 的任何行为，渲染逻辑仍在 `ui/pages/reader_page.py`。
"""
from __future__ import annotations

try:
    import pymupdf  # PyMuPDF；`import fitz` 旧名已弃用（1.28 起打警告）
    AVAILABLE = True
except ImportError:  # 冻结产物裁掉引擎时才走这
    AVAILABLE = False

if AVAILABLE:
    Document = pymupdf.Document
    Matrix = pymupdf.Matrix


def open_document(path: str) -> "pymupdf.Document":
    """打开一份 PDF（`pymupdf.open` 的转发；引擎缺席时调用方先看 `AVAILABLE`）。"""
    return pymupdf.open(path)
