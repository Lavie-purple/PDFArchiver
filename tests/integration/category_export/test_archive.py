"""「已归档」唯一口径 —— 从 791 行原文件拆出的第三份（轮十五 丙 · **ISSUES I78** 丙 残留 ②）。

2026-10-20 拆分，测试名一条没改。口径由 `archive_service.is_archived` 一家说，
表头带着口径名，默认列集里故意没有它 —— 库里没有 `is_archived` 这一列，也不该有。
弹层其余口径在 `test_ui.py`，落盘与格式在 `test_output.py`；三份共用 `conftest.py` 那棵树。
"""
from __future__ import annotations

from pdfarchiver.services.export_service import DEFAULT_COLUMNS, EXPORT_COLUMNS

from _helpers import _archived_cells, _ledger, _relocate


# ---------------------------------------------------------------------------
# 「已归档」唯一口径（ISSUES I78 丙 · 轮十五 丙）
# ---------------------------------------------------------------------------

def test_默认列集仍是线框勾的那五列() -> None:
    """默认档是五列**有序**的一项策略：多一列就多一次跨表读，少一列就少一个判据。

    比的是元组而不是集合 —— 集合放得过"顺序被 sort 过一遍"，而列顺序是产物的一部分。
    """
    assert DEFAULT_COLUMNS == ("name", "page_count", "size_bytes", "sha256_12", "mtime")


def test_已归档列的表头带着口径名() -> None:
    """库里没有 `is_archived` 这一列，也不该有：口径不写进表头，拿到清单的人
    会以为它是文件的属性，而不是"按台账最后一笔归档落点"算出来的。
    """
    label = next(c.label for c in EXPORT_COLUMNS if c.key == "archived")
    assert label == "已归档（按最后一笔归档落点）"


def test_已归档列读的是最后一笔归档落点(ctx, branch, tmp_path) -> None:
    """同一份文件归档两次（换了模板重跑）：读**最后一笔**，不是第一笔。

    另一份从没归档过的读「否」而不是空着 —— 空列分不清"没归档"与"这一列没实现"。
    """
    doc = branch["own"][0]
    old = "E:\\导出测试归档\\旧\\财务卷0号.pdf"
    new = "E:\\导出测试归档\\新\\财务卷0号.pdf"
    for dst in (old, new):
        _ledger(ctx, doc, dst)
        _relocate(ctx, doc, dst)
    assert ctx.operations.last_archive_destinations([doc])[doc] == new
    cells = _archived_cells(ctx, branch["fin"].id, tmp_path / "out")
    assert cells["财务卷0号.pdf"] == "是", cells
    assert cells["合同卷0号.pdf"] == "否", f"从没归档过的读成了 {cells['合同卷0号.pdf']!r}"


def test_撤销之后这一列读否而归档落点那行还在台账里(ctx, branch, tmp_path) -> None:
    """撤销另开一条 `kind='undo'` 的批次、src/dst 取反（**D-043** 甲），原来那行不动。

    只看"最后一笔搬动落在哪"的旧口径会把刚退回原处的文件报成已归档 —— 文件确实正躺在
    那笔撤销把它放去的位置上。所以这里先证台账里归档落点还在，再证这一列读「否」：
    「否」来自位置对不上，不是来自历史被抹了。
    """
    doc = branch["own"][1]
    archived_to = "E:\\导出测试归档\\撤销前\\财务卷1号.pdf"
    original = "D:\\导出测试\\财务\\财务卷1号.pdf"
    _ledger(ctx, doc, archived_to)
    _relocate(ctx, doc, archived_to)
    _ledger(ctx, doc, original, batch="undo")
    _relocate(ctx, doc, original)
    assert ctx.operations.last_archive_destinations([doc])[doc] == archived_to, \
        "归档那条记录被撤销批次顶掉了"
    cells = _archived_cells(ctx, branch["fin"].id, tmp_path / "out")
    assert cells["财务卷1号.pdf"] == "否", "退回原处之后仍读已归档"


def test_跨盘归档的copy条目也算已归档(ctx, branch, tmp_path) -> None:
    """跨盘那一档台账写的是 `kind='copy'`（验完 sha256 才删源，G19），文件照样落在 `dst_path`。

    只在 `kind='move'` 里挑，等于把"跨盘归档过"的文档全报成没归档 —— 而它恰恰是搬过的。
    """
    doc = branch["own"][0]
    dst = "E:\\导出测试归档\\跨盘\\财务卷0号.pdf"
    _ledger(ctx, doc, dst, kind="copy")
    _relocate(ctx, doc, dst)
    cells = _archived_cells(ctx, branch["fin"].id, tmp_path / "out")
    assert cells["财务卷0号.pdf"] == "是", cells


def test_没跑完的搬动不算已归档(ctx, branch, tmp_path) -> None:
    """`failed` / `skipped` 的条目文件根本没落到 `dst_path`，不能进这个口径。

    先直接读仓储：导出层那句 `len()` 看不出"把失败项也算进来"这种坏法。
    """
    failed, skipped = branch["kids"][0], branch["kids"][1]
    _ledger(ctx, failed, "E:\\导出测试归档\\失败的.pdf", state="failed")
    _ledger(ctx, skipped, "E:\\导出测试归档\\跳过的.pdf", state="skipped")
    assert ctx.operations.last_archive_destinations([failed, skipped]) == {}
    cells = _archived_cells(ctx, branch["fin"].id, tmp_path / "out")
    assert cells["合同卷0号.pdf"] == "否" and cells["合同卷1号.pdf"] == "否", cells
