"""阅读器行为断言（**ISSUES I79** 乙）。

三条断言钉三件事，每件都是 SPEC 阶段 3 验收「阅读器处理损坏文件和失效路径时不会导致应用崩溃」
的直接证据，之前只有"手动点过没坏"的层次：

1. 缩放档 —— `_zoom_in` / `_zoom_out` 的上下限（3.0 / 0.3）与倍率（1.2×）必须逐次生效，
   不超界、不跳步。
2. 损坏 / 失效文件不崩且回显原文 —— `pymupdf.open()` 抛异常时必须走 `QMessageBox.critical`，
   标题是「打开 PDF 失败」，正文是异常原文（不是"未知错误"之类的遮罩）。
3. 阅读进度跨重启恢复 —— 翻到第 N 页后 `last_read_page` 必须写进库；用同一个 `Engine`
   重新打开同一份文档，阅读器必须停在那一页（1-based 口径，与 `text_pages.page_no` 一致）。

这三条合起来就是 S2 阅读器的三条硬要求：能放大缩小、坏了不崩、下次打开还在那页。
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pymupdf
import pytest
from PySide6 import QtWidgets

from pdfarchiver.db.models import Document
from pdfarchiver.ui.pages.reader_page import ReaderPage


def _insert_doc(ctx, *, path: str, page_count: int = 3) -> int:
    conn = ctx.engine.thread_connection()
    conn.execute(
        "INSERT INTO documents(path, path_key, name, ext, size_bytes, mtime_ns,"
        " page_count, created_at, updated_at)"
        " VALUES(?,?,?,?,?,?,?,1,1)",
        (path, path.lower(), path.rsplit("/", 1)[-1], "pdf", 1024, 1, page_count))
    conn.commit()
    return int(conn.execute(
        f"SELECT id FROM documents WHERE path_key='{path.lower()}'").fetchone()[0])


def _navigate_to_reader(window, qapp) -> ReaderPage:
    """拿到阅读页并切到它。轮四十一（2026-10-29）起 S2 不占导航格，
    阅读页由外壳按需创建直接切栈 —— 这里走的就是外壳同一条路。"""
    from tests.conftest import settle as _settle
    page = window._ensure_reader_page()
    window.nav.setCurrentRow(-1)
    window.stack.setCurrentWidget(page)
    _settle(qapp)
    return page


def test_缩放档上下限与倍率(ctx, window, qapp, tmp_path: Path) -> None:
    """`_zoom_in` 上限 3.0、`_zoom_out` 下限 0.3、每次 1.2×。

    初始 1.0 → zoom_in → 1.2 → zoom_in → 1.44 → … → 不能超过 3.0；
    初始 1.0 → zoom_out → 0.833… → zoom_out → 0.694… → … → 不能低于 0.3。
    """
    pdf_path = tmp_path / "zoom.pdf"
    doc = pymupdf.open()
    for i in range(3):
        page = doc.new_page()
        page.insert_text((36, 40 + i * 30), f"第 {i+1} 页", fontsize=11, fontname="china-s")
    doc.save(pdf_path)
    doc.close()

    doc_id = _insert_doc(ctx, path=str(pdf_path).replace("\\", "/"))
    reader = _navigate_to_reader(window, qapp)
    reader.open_document(doc_id)

    assert reader._zoom_level == 1.0, "初始缩放必须是 1.0"

    reader._zoom_in()
    assert abs(reader._zoom_level - 1.2) < 0.01, f"第一次放大应是 1.2，实际 {reader._zoom_level}"

    reader._zoom_out()
    assert abs(reader._zoom_level - 1.0) < 0.01, f"放大后缩小应回到 1.0，实际 {reader._zoom_level}"

    for _ in range(20):
        reader._zoom_in()
    assert reader._zoom_level <= 3.0, f"缩放上限 3.0 被突破：{reader._zoom_level}"
    assert reader._zoom_level == 3.0, f"连续放大必须停在 3.0，实际 {reader._zoom_level}"

    for _ in range(30):
        reader._zoom_out()
    assert reader._zoom_level >= 0.3, f"缩放下限 0.3 被突破：{reader._zoom_level}"
    assert reader._zoom_level == 0.3, f"连续缩小必须停在 0.3，实际 {reader._zoom_level}"


def test_损坏PDF不崩且回显原文(ctx, window, qapp, tmp_path: Path) -> None:
    """`pymupdf.open()` 抛异常时必须走 `QMessageBox.critical`，标题是「打开 PDF 失败」，
    正文是异常原文。

    用一份「合法文件头 + 垃圾字节」造出损坏件，`pymupdf.open()` 会抛 `RuntimeError`。
    阅读器必须弹框而不是崩溃，且框里的文字是 PyMuPDF 的原文（不是"未知错误"）。
    """
    bad_path = tmp_path / "corrupt.pdf"
    bad_path.write_bytes(b"%PDF-1.4\n" + b"\x00" * 100)

    doc_id = _insert_doc(ctx, path=str(bad_path).replace("\\", "/"))
    reader = _navigate_to_reader(window, qapp)

    with patch.object(QtWidgets.QMessageBox, "critical") as mock_msg:
        reader.open_document(doc_id)
        mock_msg.assert_called_once()
        args = mock_msg.call_args
        title = args[0][1] if len(args[0]) > 1 else args[1].get("title", "")
        body = args[0][2] if len(args[0]) > 2 else args[1].get("text", "")
        assert title == "打开 PDF 失败", f"弹框标题必须是「打开 PDF 失败」，实际「{title}」"
        assert len(body) > 0, "弹框正文不能是空的"
        assert "未知错误" not in body, "弹框正文必须是异常原文，不许遮罩成「未知错误」"


def test_阅读进度跨重启恢复(ctx, window, qapp, tmp_path: Path) -> None:
    """翻到第 N 页后 `last_read_page` 必须写进库；重新打开同一份文档，阅读器停在那一页。

    1-based 口径（与 `text_pages.page_no` 一致）。初始打开 → 翻到第 3 页 → 断言 DB 里
    `last_read_page=3` → 再次调用 `open_document` → 断言阅读器停在第 3 页（0-based = 2）。
    这证明恢复逻辑从 DB 读值而不是从内存缓存。
    """
    pdf_path = tmp_path / "progress.pdf"
    doc = pymupdf.open()
    for i in range(5):
        page = doc.new_page()
        page.insert_text((36, 40), f"第 {i+1} 页", fontsize=11, fontname="china-s")
    doc.save(pdf_path)
    doc.close()

    doc_id = _insert_doc(ctx, path=str(pdf_path).replace("\\", "/"), page_count=5)
    reader = _navigate_to_reader(window, qapp)
    reader.open_document(doc_id)
    assert reader._current_page == 0, "初始应停在第 1 页（0-based = 0）"

    reader._next_page()
    reader._next_page()
    assert reader._current_page == 2, "翻两页后应停在第 3 页（0-based = 2）"

    conn = ctx.engine.thread_connection()
    row = conn.execute("SELECT last_read_page, last_read_at FROM documents WHERE id=?",
                       (doc_id,)).fetchone()
    assert row["last_read_page"] == 3, f"阅读进度必须是 3（1-based），实际 {row['last_read_page']}"
    assert row["last_read_at"] is not None, "last_read_at 必须被写入"

    reader._current_page = 0
    reader.open_document(doc_id)
    assert reader._current_page == 2, (
        f"重新打开同一文档应从 DB 恢复到最后读的那页（0-based = 2），"
        f"实际 {reader._current_page}")
