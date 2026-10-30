"""S1「上次读到」提示行与应用图标（轮四十一 甲 + 轮四十 ③）。

S2 自轮四十一起不再是导航项，「继续阅读」降级成 S1 搜索栏下的一行轻提示。
三条断言钉三个状态（互斥，数据只来自 `DocumentRepository.last_read()` 一个出口）：

1. 无阅读记录 → 提示行整行隐藏（空屏不放常驻的"什么都没有"）；
2. 有阅读记录 → 行可见可点，点一下经 `open_in_reader`（与命中面板同一载荷口径
   `(doc_id, None)`）打开最近读的那份、落在 `last_read_page` 那页
   （1 基口径，复用 reader_page 既有恢复逻辑）；
3. 文件已不在原位置 → 行可见但**禁用**、写明原因 —— 不放一颗点不动的按钮装没这回事。

另有一条应用身份：`assets/app.ico` 必须存在、多尺寸、`_apply_app_identity` 之后
QApplication 的图标非空（冻结产物由 spec datas 收进包，漏收 = 用户机窗口图标退回系统默认）。
"""
from __future__ import annotations

import re
from pathlib import Path

import pymupdf
from PySide6 import QtGui

from pdfarchiver.ui.nav import NAV_ITEMS

HINT_MISSING_FILE = "已不在原位置"
HINT_CONTINUE = "点此继续"


def _make_pdf(path: Path, *, pages: int = 5) -> str:
    doc = pymupdf.open()
    for i in range(pages):
        page = doc.new_page()
        page.insert_text((36, 40), f"第 {i + 1} 页", fontsize=11, fontname="china-s")
    doc.save(path)
    doc.close()
    return str(path).replace("\\", "/")


def _insert_doc(ctx, *, path: str, name: str, page_count: int = 5,
                last_read_page: int | None = None, last_read_at: float | None = None) -> int:
    conn = ctx.engine.thread_connection()
    conn.execute(
        "INSERT INTO documents(path, path_key, name, ext, size_bytes, mtime_ns,"
        " page_count, last_read_page, last_read_at, created_at, updated_at)"
        " VALUES(?,?,?,?,?,?,?,?,?,1,1)",
        (path, path.lower(), name, "pdf", 1024, 1, page_count, last_read_page, last_read_at))
    conn.commit()
    row = conn.execute("SELECT id FROM documents WHERE path_key=?", (path.lower(),)).fetchone()
    return int(row[0])


def _hint(window):
    return window._pages["library"].last_read_hint


def test_无阅读记录时提示行整行隐藏(ctx, window) -> None:
    assert ctx.documents.last_read() is None, "用例前提：干净库没有任何阅读记录"
    hint = _hint(window)
    assert not hint.isVisible(), "没有阅读记录就不许放一行'什么都没有'的常驻提示"


def test_有阅读记录提示行可见可点且落到上次那页(ctx, window, tmp_path: Path) -> None:
    real = _make_pdf(tmp_path / "resume.pdf")
    doc_id = _insert_doc(ctx, path=real, name="resume.pdf", page_count=5,
                         last_read_page=3, last_read_at=1000.0)
    page = window._pages["library"]
    page.update_last_read_hint()
    hint = page.last_read_hint
    assert hint.isVisible() and hint.isEnabled(), "有记录且文件在，提示行必须可见可点"
    assert "resume.pdf" in hint.text() and "第 3 页" in hint.text(), \
        f"提示要写清读到哪份哪页，实际：{hint.text()!r}"
    hint.click()
    reader = window._pages["reader"]
    assert reader._current_doc_id == doc_id, \
        f"点提示应打开 doc {doc_id}，实际 _current_doc_id={reader._current_doc_id}"
    assert reader._current_page == 2, "必须停在 last_read_page=3 那页（0 基内部 = 2）"


def test_文件已挪走提示行可见但禁用(ctx, window, tmp_path: Path) -> None:
    gone = str(tmp_path / "moved_away.pdf").replace("\\", "/")
    _insert_doc(ctx, path=gone, name="moved_away.pdf", page_count=5,
                last_read_page=2, last_read_at=1000.0)
    page = window._pages["library"]
    page.update_last_read_hint()
    hint = page.last_read_hint
    assert hint.isVisible(), "文件挪走了也要说，不许悄悄藏起来"
    assert not hint.isEnabled(), "文件不在了就不许是一颗点得动的按钮"
    assert HINT_MISSING_FILE in hint.text(), f"要写明原因，实际：{hint.text()!r}"


def test_提示行不带框且不挂复读tooltip(ctx, window, tmp_path: Path) -> None:
    """轮四十六：这一行是"一句可以直接点的话"，不是一颗按钮。

    两半各钉一处，缺一半就退回用户红框点出的样子：
    - QSS 里 `QToolButton#lastReadHint` 必须同时声明 `border: none` 与透明底
      —— 框是 windowsvista 样式给 QToolButton 画的，`setAutoRaise(True)` 在原生样式下不管事；
    - 控件的 tooltip 必须是空串 —— 行里写的就是全部内容，悬停复读一遍只是噪声。
    """
    real = _make_pdf(tmp_path / "flat.pdf")
    _insert_doc(ctx, path=real, name="flat.pdf", page_count=5,
                last_read_page=4, last_read_at=2000.0)
    page = window._pages["library"]
    page.update_last_read_hint()
    hint = page.last_read_hint
    assert hint.text(), "用例前提：提示行得写上字"
    assert hint.toolTip() == "", f"不许用 tooltip 复读自己这一行：{hint.toolTip()!r}"

    qss = re.sub(r"/\*.*?\*/", "", window.theme.generate_qss(), flags=re.S)
    block = re.search(r"QToolButton#lastReadHint\s*\{([^}]*)\}", qss)
    assert block, "抹平规则不在了 —— 原生样式的框会直接回到屏上"
    body = block.group(1)
    assert "border: none" in body and "transparent" in body, f"缺一半都压不住框：{body}"


def test_导航注册表8项且阅读器不再占一格() -> None:
    ids = [i.page_id for i in NAV_ITEMS]
    assert "reader" not in ids, "阅读器已在轮四十一退出导航，入口全在 S1：{ids}"
    assert len(ids) == 8 and len(set(ids)) == 8, f"注册表应当是 8 项且 id 唯一：{ids}"
    pending = [i for i in NAV_ITEMS if not i.implemented]
    assert not pending, f"不许再留任何未实现导航项：{[i.title for i in pending]}"


def test_应用身份_图标非空且多尺寸(qapp) -> None:
    from pdfarchiver.app import _apply_app_identity

    ico_path = Path(__file__).resolve().parents[2] / "src" / "pdfarchiver" / "assets" / "app.ico"
    assert ico_path.is_file(), "assets/app.ico 不存在：窗口/任务栏会退回系统默认裸图标"
    icon = QtGui.QIcon(str(ico_path))
    sizes = {s.height() for s in icon.availableSizes()}
    assert {16, 32, 256} <= sizes, f"多尺寸 .ico 至少要有 16/32/256，实际 {sorted(sizes)}"
    _apply_app_identity(qapp)
    assert not qapp.windowIcon().isNull(), "_apply_app_identity 之后应用图标仍为空"
