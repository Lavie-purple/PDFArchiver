"""C5 的两面（**ISSUES I117** 甲）：OCR 页级完成标记的空串行不是垃圾；原生空串仍是。

坏法注入（真做过）：
- 把豁免删掉（`empty_marker` 恒 0，所有空串都算垃圾）→ 第一条红，读数里「OCR 页级标记 0」；
- 把豁免放宽成「任何空串都算标记」（`empty_junk` 恒 0）→ 第二条红。
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "probes"))

import p12_consistency as p12  # noqa: E402


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE text_pages(rowid INTEGER PRIMARY KEY, doc_id INTEGER, page_no INTEGER,"
        " source_kind TEXT NOT NULL DEFAULT 'native', char_count INTEGER NOT NULL,"
        " body TEXT NOT NULL, ocr_version TEXT, indexed_at INTEGER NOT NULL)")
    return conn


def _page(conn, doc_id: int, page_no: int, body: str, *, kind: str = "native",
          version: str | None = None) -> None:
    conn.execute("INSERT INTO text_pages(doc_id, page_no, source_kind, char_count, body,"
                 " ocr_version, indexed_at) VALUES(?,?,?,?,?,?,1)",
                 (doc_id, page_no, kind, len(body), body, version))


def test_OCR页级完成标记的空串行不算零信息行() -> None:
    """识别过但这页没字：那行 0 字正文同时是「vX 版本做过这页」的唯一落点，删了会重跑。"""
    conn = _conn()
    _page(conn, 1, 1, "正常原生正文")
    _page(conn, 2, 1, "", kind="ocr", version="abc")
    _page(conn, 2, 2, "", kind="ocr", version="abc")
    row = p12.c5_pages(conn)
    assert row.ok, row.measured
    assert "OCR 页级标记 2" in row.measured and "真垃圾 0" in row.measured


def test_原生空串仍是零信息行必须判红() -> None:
    conn = _conn()
    _page(conn, 1, 1, "正常原生正文")
    _page(conn, 1, 2, "")
    row = p12.c5_pages(conn)
    assert not row.ok, row.measured
    assert "真垃圾 1" in row.measured
