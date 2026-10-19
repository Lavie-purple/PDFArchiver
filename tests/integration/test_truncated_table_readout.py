"""三张靠 `limit=` 封顶的表都要报 **I51 那两个数**（**ISSUES I76**）。

规则一条、不分屏打补丁（AGENTS.md「禁止同类问题逐个打补丁 —— 发现一类先问还有哪些地方是同类」）：
凡取数带 `limit=` 的表格，屏上必须**同时**出现「总数」与「已取回数」，且两个数都取自后端字段。
理由与 **ISSUES I51** 完全同形：那时无界 `documents.list()` 被改成 `list(limit=1000)`，8,000 份
的库里界面上说「共 1000 份文档」，把"还有 7,000 份没在表格里"报成了"库只有 1000 份"。
这一族在 S3 / S5 / S4 上各复发了一次（`archive_page:246`、`dedup_page:249`、
`operations_page:79`），真语料 10,977 份时用户没有任何途径知道第 501 份之后的文档不存在于界面。

另一半规则同样可断言：**批次大小只在仓储层定义一处，界面不许再写 `limit=` 这种数**
（`test_界面不再自己定批次大小`）。

三张表的"取回少数"分支都用 monkeypatch 造 —— 造 501 份真 PDF 只为跑一次截断分支，
测的是 Qt 那一行文字，不是磁盘。
"""
from __future__ import annotations

from pathlib import Path

import pytest
from PySide6 import QtWidgets

from pdfarchiver.db.models import Document
from pdfarchiver.fs.identity import read_identity
from tests.conftest import settle as _settle

BODY = b"%PDF-1.7\ntruncated-table-fixture\n" * 8


def _seed_doc(ctx, path: Path, *, sha256: str | None = None) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(BODY)
    identity = read_identity(path)
    doc = ctx.documents.upsert(Document(
        path=identity.path, path_key=identity.path_key, name=identity.name, ext=identity.ext,
        size_bytes=identity.size_bytes, mtime_ns=identity.mtime_ns, ctime_ns=identity.ctime_ns,
        file_id=identity.file_id, device_id=identity.device,
        parse_status="ok", text_status="native", fts_status="done"))
    if sha256:
        ctx.documents.update_sha256(int(doc.id), sha256)
    return int(doc.id)


def _page(window, qapp, page_id: str):
    window._select_by_page_id(page_id)
    _settle(qapp)
    return window._pages[page_id]


def _expect(note: QtWidgets.QLabel, page, text: str) -> None:
    """两个数都要在，而且必须**看得见** —— 设在不可见的标签上等于没有（**ISSUES I17** 同款假绿）。"""
    assert isinstance(note, QtWidgets.QLabel), "这一屏没有那条「两个数」的说明标签"
    assert note.isVisibleTo(page), f"两个数设在不可见的标签上：{note.text()!r}"
    assert note.text() == text, f"口径不对：{note.text()!r} ≠ 期望 {text!r}"


def test_S3归档候选表报两个数(window, ctx, qapp, tmp_path) -> None:
    for i in range(3):
        _seed_doc(ctx, tmp_path / "候选" / f"甲{i}.pdf")
    page = _page(window, qapp, "archive")
    total = ctx.documents.count()
    assert total == 3
    page.load_btn.click()                 # S3 的候选表由「载入文档库」这个按钮触发
    _settle(qapp)
    assert page.doc_table.rowCount() == total
    _expect(page.loaded_note, page, f"共 {total} 份文档｜表格里 {total} 份文档")

    # 截断分支：仓储只回 1 份（等价于 `limit=1`），屏上必须换成"还有 N 条没在这里"
    real_list = ctx.documents.list
    ctx.documents.list = lambda *a, **kw: real_list(limit=1)  # type: ignore[assignment]
    try:
        page._load_documents()
        _settle(qapp)
        _expect(page.loaded_note, page,
                f"共 {total} 份文档｜表格里已有 1 份文档，还有 2 份文档没在这里")
    finally:
        ctx.documents.list = real_list  # type: ignore[method-assign]


def test_S5重复组表报两个数(window, ctx, qapp, tmp_path) -> None:
    for i in range(2):
        _seed_doc(ctx, tmp_path / "重复" / f"乙{i}.pdf", sha256="aa" * 32)
    _seed_doc(ctx, tmp_path / "重复" / "独立.pdf", sha256="bb" * 32)
    page = _page(window, qapp, "duplicates")
    total = ctx.documents.dedup_summary()["group_count"]
    assert total == 1, "两份同哈希 = 一组重复，第三份独份不成组"
    assert page.table.rowCount() == total
    _expect(page.loaded_note, page, f"共 {total} 组重复｜表格里 {total} 组重复")

    real = ctx.documents.duplicate_groups
    ctx.documents.duplicate_groups = lambda *a, **kw: []  # type: ignore[assignment]
    try:
        page._reload_groups()
        _settle(qapp)
        _expect(page.loaded_note, page,
                f"共 {total} 组重复｜表格里已有 0 组重复，还有 1 组重复没在这里")
    finally:
        ctx.documents.duplicate_groups = real  # type: ignore[method-assign]


def test_S4操作批次表报两个数(window, ctx, qapp) -> None:
    for _ in range(2):
        ctx.operations.create_operation("archive")
    page = _page(window, qapp, "operations")
    total = ctx.operations.count_operations()
    assert total == 2
    assert page.op_table.rowCount() == total
    _expect(page.loaded_note, page, f"共 {total} 条操作批次｜表格里 {total} 条操作批次")

    real = ctx.operations.list_operations
    ctx.operations.list_operations = lambda *a, **kw: []  # type: ignore[assignment]
    try:
        page.reload()
        _settle(qapp)
        _expect(page.loaded_note, page,
                f"共 {total} 条操作批次｜表格里已有 0 条操作批次，还有 2 条操作批次没在这里")
    finally:
        ctx.operations.list_operations = real  # type: ignore[method-assign]


def test_界面不再自己定批次大小() -> None:
    """`limit=` 只许出现在仓储层 —— 界面写死一个数就是第二个口径（**ISSUES I76**）。"""
    from pdfarchiver.ui.pages import archive_page, dedup_page, operations_page

    offenders = []
    for mod in (archive_page, dedup_page, operations_page):
        path = Path(mod.__file__)
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if "limit=" in line and not line.lstrip().startswith("#"):
                offenders.append(f"{path.name}:{lineno}: {line.strip()}")
    assert offenders == [], "这三张屏又在界面里自己定批次：\n" + "\n".join(offenders)
