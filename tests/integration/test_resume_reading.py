"""「继续阅读」导航项与应用图标（轮四十用户勾选 ②乙 + ③）。

四条断言钉四件事：

1. 无阅读记录 → 停在阅读页并给指引文案（不弹窗、不空屏）；
2. 有阅读记录 → 导航进阅读页就自动接上**最近读过**的那份、落在 `last_read_page` 那页
   （1-based 口径与 `text_pages.page_no` 一致，复用 reader_page 既有恢复逻辑）；
3. S1 命中面板跳转（`_open_in_reader`）压着抑制位时**不许**被 resume 覆盖 ——
   用户点的是命中那一页，不是"最近读的那份"；
4. 文件已不在原位置 → 降级为状态栏提示，不弹模态框
   （`open_document` 的失败路径是模态 `QMessageBox`，自动导航若不设防会把用户困在框里）。

另有一条应用身份：`assets/app.ico` 必须存在、多尺寸、`_apply_app_identity` 之后
QApplication 的图标非空（冻结产物由 spec datas 收进包，漏收 = 用户机窗口图标退回系统默认）。
"""
from __future__ import annotations

from pathlib import Path

import fitz
from PySide6 import QtGui, QtWidgets

from pdfarchiver.ui.nav import NAV_ITEMS
from tests.conftest import settle as _settle

HINT_NO_HISTORY = "还没有阅读记录"
HINT_MISSING_FILE = "已不在原位置"


def _make_pdf(path: Path, *, pages: int = 5) -> str:
    doc = fitz.open()
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


def _go_reader(window, qapp):
    window._select_by_page_id("reader")
    _settle(qapp)
    return window._pages["reader"]


def test_无阅读记录给指引不弹窗(ctx, window, qapp) -> None:
    assert ctx.documents.last_read() is None, "用例前提：干净库没有任何阅读记录"
    reader = _go_reader(window, qapp)
    assert reader._current_doc_id is None, "没有记录就不许悄悄打开任何一份"
    assert HINT_NO_HISTORY in reader.status_label.text()


def test_有阅读记录自动接上那份并落在上次那页(ctx, window, qapp, tmp_path: Path) -> None:
    real = _make_pdf(tmp_path / "resume.pdf")
    doc_id = _insert_doc(ctx, path=real, name="resume.pdf", page_count=5,
                         last_read_page=3, last_read_at=1000.0)
    reader = _go_reader(window, qapp)
    assert reader._current_doc_id == doc_id, \
        f"导航进阅读页就应接上最近读的那份 doc {doc_id}，实际 _current_doc_id={reader._current_doc_id}"
    assert reader._current_page == 2, "必须停在 last_read_page=3 那页（0 基内部 = 2）"


def test_文件已挪走降级为提示不弹模态(ctx, window, qapp, tmp_path: Path) -> None:
    gone = str(tmp_path / "moved_away.pdf").replace("\\", "/")
    _insert_doc(ctx, path=gone, name="moved_away.pdf", page_count=5,
                last_read_page=2, last_read_at=1000.0)
    reader = _go_reader(window, qapp)
    assert reader._current_doc_id is None, "文件都不在了就不许把阅读页标成已打开"
    assert HINT_MISSING_FILE in reader.status_label.text()


def test_S1跳转时不叠加继续阅读(ctx, window, qapp, tmp_path: Path) -> None:
    """终态断言分不出好坏（载荷在 resume 之后打开，覆盖终态）—— 所以钉的是
    **调用本身**：S1 带压跳转期间 `_resume_last_read` 一次都不许跑，
    不许先把"最近读的那份"真开一遍再换目标（多余的 fitz.open + 状态栏闪一下）。"""
    from unittest.mock import patch

    _insert_doc(ctx, path=str(tmp_path / "never_opened.pdf").replace("\\", "/"),
                name="never_opened.pdf",
                last_read_page=4, last_read_at=1000.0)
    target = _make_pdf(tmp_path / "hit.pdf")
    target_id = _insert_doc(ctx, path=target, name="hit.pdf")
    with patch.object(window, "_resume_last_read") as mock_resume:
        window._open_in_reader((target_id, 4))
        _settle(qapp)
    mock_resume.assert_not_called(), "S1 跳转压着抑制位，resume 一次都不该跑"
    reader = window._pages["reader"]
    assert reader._current_doc_id == target_id, \
        f"S1 跳的是 doc {target_id}，实际打开的是 {reader._current_doc_id}"
    assert reader._current_page == 3, "S1 给的第 4 页必须生效"


def test_导航注册表不再有占位项() -> None:
    pending = [i for i in NAV_ITEMS if not i.implemented]
    assert not pending, f"检索占位项删除后不许再留任何未实现导航项：{[i.title for i in pending]}"


def test_应用身份_图标非空且多尺寸(qapp) -> None:
    from pdfarchiver.app import _apply_app_identity

    ico_path = Path(__file__).resolve().parents[2] / "src" / "pdfarchiver" / "assets" / "app.ico"
    assert ico_path.is_file(), "assets/app.ico 不存在：窗口/任务栏会退回系统默认裸图标"
    icon = QtGui.QIcon(str(ico_path))
    sizes = {s.height() for s in icon.availableSizes()}
    assert {16, 32, 256} <= sizes, f"多尺寸 .ico 至少要有 16/32/256，实际 {sorted(sizes)}"
    _apply_app_identity(qapp)
    assert not qapp.windowIcon().isNull(), "_apply_app_identity 之后应用图标仍为空"
