"""分类清单导出的落盘纪律、回执与三种格式 —— 从 791 行原文件拆出的第二份。

2026-10-20 拆分，测试名一条没改。这里管：同名产物不覆盖、写盘失败不留半截、
回执逐字来自 `ExportReceipt.describe()`（**ISSUES I60**）、CSV/JSON/Markdown 三种后缀与
空值/竖线口径。弹层与列同源、份数、门与接线在 `test_ui.py`；「已归档」在 `test_archive.py`。
"""
from __future__ import annotations

import json

from pdfarchiver.services.export_service import DEFAULT_COLUMNS, EXPORT_COLUMNS, ExportReceipt

from _helpers import (
    MD_CELL,
    _box,
    _by_suffix,
    _csv_rows,
    _set_dir,
    _written,
)


# ---------------------------------------------------------------------------
# 落盘纪律：不覆盖、不留半截
# ---------------------------------------------------------------------------

def test_同名产物第二次导出被拒而第一份原样还在(ctx, branch, tmp_path, dialogs) -> None:
    """同一天同一枝 = 同一个文件名；静默盖掉就是把"上午那份清单"变没了，而屏幕上只写"已导出"。"""
    dest = tmp_path / "out"
    dest.mkdir()
    box = _box(ctx, branch["fin_ht"].id)
    _set_dir(box, dest)
    box.run_export()
    first = _written(dest)[0].read_bytes()

    again = _box(ctx, branch["fin_ht"].id)
    _set_dir(again, dest)
    again.run_export()
    assert dialogs[-1][0] == "warning" and "不覆盖" in dialogs[-1][2], dialogs[-1]
    assert _written(dest)[0].read_bytes() == first, "被拒的那一次仍然动了已有产物"


def test_写盘中途失败时不留半截产物(ctx, branch, tmp_path, monkeypatch) -> None:
    """落盘走 `.part` 再改名：中途失败留下的是半截的 `.part`，不是一份看起来完整的坏文件。

    这里把改名那一步换成"抛异常"，验 `finally` 真的把 `.part` 清掉了 —— 目录里既没有产物
    也没有临时件。不清的话，用户下次在同一目录里会看见一个后缀奇怪、内容截断的文件。
    """
    from pdfarchiver.services import export_service

    dest = tmp_path / "out"
    dest.mkdir()

    class _NoReplace:
        @staticmethod
        def replace(_src, _dst):
            raise OSError("注入：改名这一步失败")

    monkeypatch.setattr(export_service, "os", _NoReplace)
    box = _box(ctx, branch["fin"].id)
    _set_dir(box, dest)
    box.run_export()
    assert _written(dest) == [], [f.name for f in _written(dest)]


# ---------------------------------------------------------------------------
# 回执：屏幕上那句只有一个出处（ISSUES I60）
# ---------------------------------------------------------------------------

def test_屏幕上那句逐字就是后端回执(ctx, branch, tmp_path, dialogs) -> None:
    """把 `ExportReceipt` 自己拼一遍再逐字比 —— 界面写第二套格式化就会在这里红。"""
    dest = tmp_path / "out"
    dest.mkdir()
    box = _box(ctx, branch["fin"].id)
    _set_dir(box, dest)
    box.run_export()
    path = _written(dest)[0]
    expected = ExportReceipt(
        category_name_path="导出测试财务", include_children=True, fmt="csv", rows=6,
        labels=tuple(c.label for c in EXPORT_COLUMNS if c.key in DEFAULT_COLUMNS),
        path=path, local_path_included=False).describe()
    assert dialogs[-1][0] == "information", dialogs[-1]
    assert dialogs[-1][2] == expected
    assert "已导出 6 行" in expected and path.name in expected, expected


# ---------------------------------------------------------------------------
# 三种格式与空值口径
# ---------------------------------------------------------------------------

def test_三种格式各写出对应后缀与内容(ctx, branch, tmp_path) -> None:
    dest = tmp_path / "out"
    dest.mkdir()
    for key in ("csv", "json", "markdown"):
        box = _box(ctx, branch["fin"].id)
        box.format_buttons[key].setChecked(True)
        _set_dir(box, dest)
        box.run_export()
    files = _by_suffix(dest)
    assert set(files) == {".csv", ".json", ".md"}, [f.name for f in _written(dest)]
    assert len(json.loads(files[".json"].read_text(encoding="utf-8"))) == 6
    md = files[".md"].read_text(encoding="utf-8").splitlines()
    assert md[0].startswith("| 文件名 |")
    assert {cell.strip() for cell in MD_CELL.split(md[1])} == {"", "---"}, md[1]


def test_csv带bom而md与json不带(ctx, branch, tmp_path) -> None:
    """BOM 是给 Excel 的（无 BOM 时中文整列成乱码，实测），JSON/MD 的读者不需要它。"""
    dest = tmp_path / "out"
    dest.mkdir()
    for key in ("csv", "json", "markdown"):
        box = _box(ctx, branch["fin"].id)
        box.format_buttons[key].setChecked(True)
        _set_dir(box, dest)
        box.run_export()
    for f in _written(dest):
        assert (f.read_bytes()[:3] == b"\xef\xbb\xbf") == (f.suffix == ".csv"), f.name


def test_md转义竖线而列数不变(ctx, branch, tmp_path) -> None:
    """Windows 文件名不许有 `|`，但库里的 `name` 来自任何监测根，那一侧它是合法字符；
    漏转义的那一行会被切成更多列，整张表跟着错位。"""
    from pdfarchiver.db.models import Document
    from pdfarchiver.fs.identity import identity_key

    weird = ctx.documents.upsert(Document(
        path="D:\\导出测试\\竖线\\竖线|号.pdf",
        path_key=identity_key("D:\\导出测试\\竖线\\竖线|号.pdf"),
        name="竖线|号.pdf", size_bytes=1, mtime_ns=1_760_000_000_000_000_000,
        sha256="f" * 64, page_count=1, text_status="done", fts_status="done"))
    cat = ctx.catalog.add_category("导出测试转义")
    ctx.catalog.link_categories([weird.id], cat.id)
    dest = tmp_path / "out"
    dest.mkdir()
    box = _box(ctx, cat.id)
    box.format_buttons["markdown"].setChecked(True)
    _set_dir(box, dest)
    box.run_export()
    lines = _written(dest)[0].read_text(encoding="utf-8").splitlines()
    assert "竖线\\|号.pdf" in lines[2], lines[2]
    assert len(MD_CELL.split(lines[2])) == len(MD_CELL.split(lines[0])), lines[2]


def test_没有页数的文档写成空单元格而不是none字面量(ctx, branch, tmp_path) -> None:
    """SPEC 3.2「缺失的元数据不得凭空编造」在产物侧的版本：空就是空，不是字符串 `"None"`。"""
    dest = tmp_path / "out"
    dest.mkdir()
    box = _box(ctx, branch["fin"].id)
    box.column_checks["tags"].setChecked(True)
    _set_dir(box, dest)
    box.run_export()
    path = _written(dest)[0]
    rows = _csv_rows(path)
    bare = next(r for r in rows[1:] if r[0].startswith("报销卷"))
    body = path.read_text(encoding="utf-8-sig")
    assert "None" not in body, body
    assert bare[rows[0].index("页数")] == ""
    assert bare[rows[0].index("标签")] == "", "没有标签的写成 None 了"


def test_勾上标签列之后每行是那几个标签(ctx, branch, tmp_path) -> None:
    """标签列是十二列里要**跨表**取值的那两列之一（另一列是「已归档」）：一批一条查询
    （**ISSUES I51** 那条纪律）。

    这条数结果（6 份里 2 份带标签、4 份空）；"逐行查"那种坏法不改结果，所以由 p22 注入里
    数 SQL 条数那一 case 负责。
    """
    dest = tmp_path / "out"
    dest.mkdir()
    box = _box(ctx, branch["fin"].id)
    box.column_checks["tags"].setChecked(True)
    _set_dir(box, dest)
    box.run_export()
    rows = _csv_rows(_written(dest)[0])
    cells = [r[rows[0].index("标签")] for r in rows[1:]]
    assert cells.count("导出测试标签") == 2, cells
    assert cells.count("") == 4, cells
