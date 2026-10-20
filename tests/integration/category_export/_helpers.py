"""分类清单导出那 31 条断言的共用夹具件（2026-10-20 从 `test_category_export_ui.py` 拆出）。

拆成 `test_ui` / `test_output` / `test_archive` 三份的直接原因：原文件 791 行，距 `.py`
红线 800 只剩 9 行（轮十五 收尾记的欠账）。这里只放"让断言读得下去"的准备函数，
一条判据都不放 —— 判据全在三个测试文件里，坏法注入仍由 `p22_category_export_injection.py`
一张网覆盖全部 31 条（探针按新路径逐条点名）。
"""
from __future__ import annotations

import csv
import io
import re
from pathlib import Path

from pdfarchiver.db.models import Document
from pdfarchiver.fs.identity import identity_key
from pdfarchiver.ui.export_dialog import ExportDialog

#: 带盘符的内容才叫"泄露本机路径"（线框 §I78-bing 硬断言 c 给的就是这条正则）。
DRIVE_LETTER = re.compile(r"[A-Za-z]:[\\/]")
#: Markdown 按**未被反斜杠挡住**的竖线分列。
MD_CELL = re.compile(r"(?<!\\)\|")


def _docs(ctx, count: int, prefix: str, *, bare: bool = False) -> list[int]:
    """灌 count 份**只有名字**的文档（不碰磁盘）；`bare` 那份故意没有页数、哈希与正文覆盖率。"""
    ids: list[int] = []
    for n in range(count):
        name = f"{prefix}{n}号.pdf"
        path = f"D:\\导出测试\\{prefix}\\{name}"
        row = ctx.documents.upsert(Document(
            path=path, path_key=identity_key(path), name=name,
            size_bytes=2048 + n, mtime_ns=1_760_000_000_000_000_000 + n,
            sha256=None if bare else f"{n:064x}", page_count=None if bare else 7 + n,
            text_bearing_rate=None if bare else 0.5,
            text_status="done", fts_status="done", ocr_status="na"))
        ids.append(row.id)
    return ids


def _box(ctx, category_id: int) -> ExportDialog:
    """直接构造弹层而不 `exec()`：`exec()` 在 offscreen 下堵死主线程，而这一屏所有判据
    （按钮的禁用态、勾一下弹不弹确认）都只能在不开模态的情况下读。"""
    return ExportDialog(ctx, category_id)


def _set_dir(box: ExportDialog, dest: Path) -> None:
    box.dest_input.setText(str(dest))


def _written(dest: Path) -> list[Path]:
    return sorted(dest.glob("*"))


def _by_suffix(dest: Path) -> dict[str, Path]:
    return {f.suffix: f for f in _written(dest)}


def _fingerprint(ctx, tables: tuple[str, ...]) -> dict[str, str]:
    """几张表的**逐行指纹**：内容一样 → 字符串一样。导出前后各算一次就是 (d) 那条。"""
    conn = ctx.engine.thread_connection()
    out: dict[str, str] = {}
    for table in tables:
        rows = conn.execute(f"SELECT * FROM {table}").fetchall()
        out[table] = repr(sorted(str(tuple(r)) for r in rows))
    return out


def _csv_rows(path: Path) -> list[list[str]]:
    return list(csv.reader(io.StringIO(path.read_text(encoding="utf-8-sig"))))


def _ledger(ctx, doc_id: int, dst: str, *, batch: str = "archive",
            state: str = "done", kind: str = "move") -> None:
    """在真台账里写一条搬动：先 `pending` 落库再写终态，与执行器同一形状（**D-048**）。"""
    op = ctx.operations.create_operation(batch)
    item = ctx.operations.add_item(op.id, doc_id, kind, f"E:\\导出测试源\\{doc_id}.pdf", dst)
    if state != "pending":
        ctx.operations.update_item_state(item.id, state)


def _relocate(ctx, doc_id: int, path: str) -> None:
    """搬完之后的收尾：`adopt_path` 换 path/path_key，**id 不变**（归档执行真做完的样子）。"""
    ctx.documents.adopt_path(
        doc_id, path=path, path_key=identity_key(path), name=Path(path).name,
        ext=".pdf", size_bytes=2048, mtime_ns=1_760_000_000_000_000_000, ctime_ns=None)


def _archived_cells(ctx, category_id: int, dest: Path) -> dict[str, str]:
    """按「文件名 → 已归档单元格」导一遍，读的是产品自己那条链路（勾列 → 导出 → 解析）。"""
    dest.mkdir(parents=True, exist_ok=True)
    box = _box(ctx, category_id)
    box.column_checks["archived"].setChecked(True)
    _set_dir(box, dest)
    box.run_export()
    rows = _csv_rows(_written(dest)[0])
    col = rows[0].index("已归档（按最后一笔归档落点）")
    return {r[0]: r[col] for r in rows[1:]}


def _tree_item(page, name: str):
    """按名字找树上那一行（含子层）。`findItems` 只搜顶层，所以自己走一遍。"""
    stack = [page.category_tree.topLevelItem(i)
             for i in range(page.category_tree.topLevelItemCount())]
    while stack:
        item = stack.pop()
        if item.text(0) == name:
            return item
        stack.extend(item.child(i) for i in range(item.childCount()))
    return None
