"""S8 右键「导出此分类清单…」+ 那枚弹层 —— **ISSUES I78** 丙 的界面与本份数口径。

2026-10-20 从 791 行的 `test_category_export_ui.py` 拆出（轮十五 收尾欠的 ④），测试名一条没改，
p22 注入探针按新路径逐条点名。本文件管：弹层与列**同源**、份数只有一个数、未勾的列不出现、
本机绝对路径的确认、只读指纹、同名两枝、门与接线。

另外三组各自成文件：`test_output.py`（落盘纪律 / 回执 / 格式与空值）与
`test_archive.py`（「已归档」唯一口径）。三份共用 `conftest.py` 那棵树。

夹具三条规矩照常（offscreen、独立数据根、真 sqlite3 —— **D-012**）；库里的文档全是现造的假名字，
真实语料一条不进测试（**ISSUES I64**）。测试直连真库只为**数行与算指纹**——(d) 那条要的就是
库里的事实；产品代码一条 SQL 都不写（那是 `tests/guards/test_architecture.py` 钉的方向）。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from PySide6 import QtWidgets

from pdfarchiver.services.export_service import (
    DEFAULT_COLUMNS,
    EXPORT_COLUMNS,
    FORMATS,
    LOCAL_PATH_WARNING,
)

from _helpers import (
    DRIVE_LETTER,
    _box,
    _csv_rows,
    _fingerprint,
    _ledger,
    _relocate,
    _set_dir,
    _tree_item,
    _written,
)


# ---------------------------------------------------------------------------
# 口径来源：弹层不许抄一份列清单
# ---------------------------------------------------------------------------

def test_弹层上的列与格式逐字来自服务层那张表(ctx, branch) -> None:
    """**ISSUES I80** 那一类：界面写着有、产物写不出。

    十二行复选框与三颗单选钮的**文本**必须逐个等于 `EXPORT_COLUMNS` / `FORMATS` 里的标签 ——
    界面抄一份，服务层加一列时界面就会先上屏一个"勾了也没用"的选项。
    """
    box = _box(ctx, branch["fin"].id)
    assert [c.text() for c in box.column_checks.values()] == [
        (f"{c.label} ⚠ 隐私" if c.privacy else c.label) for c in EXPORT_COLUMNS]
    assert [box.format_buttons[k].text() for k, _, _ in FORMATS] == [label for _, label, _ in FORMATS]
    assert LOCAL_PATH_WARNING in box.column_checks["local_path"].toolTip(), \
        "隐私列的悬浮说明里没有那句确认原文"


def test_默认勾的就是服务层那五列(ctx, branch) -> None:
    """默认档是线框勾过的那五项（文件名 / 页数 / 大小 / SHA256 前 12 / 修改时间）。

    这里钉成"**与 `DEFAULT_COLUMNS` 同源**"而不是写死五个名字：界面与服务层各留一份默认值
    就会有一天不一样，而"默认导出不带本机路径"是一件要人负责的策略，不是偏好。
    """
    box = _box(ctx, branch["fin"].id)
    assert {k for k, c in box.column_checks.items() if c.isChecked()} == set(DEFAULT_COLUMNS)
    assert not box.column_checks["local_path"].isChecked(), "本机绝对路径默认就该是关的"


def test_产物列顺序由表定而不是由点击顺序定(ctx, branch, tmp_path) -> None:
    """先勾「修改时间」再勾「文件名」，产物里第一列仍是文件名。

    列顺序是产物的一部分（人拿去与上一份对拍），让**鼠标轨迹**决定它就是让顺序随机。
    """
    dest = tmp_path / "out"
    dest.mkdir()
    box = _box(ctx, branch["fin"].id)
    for c in box.column_checks.values():
        c.setChecked(False)
    box.column_checks["mtime"].setChecked(True)
    box.column_checks["name"].setChecked(True)
    assert box.selected_columns() == ("name", "mtime"), "勾选顺序漏进了列顺序"
    _set_dir(box, dest)
    box.run_export()
    assert _csv_rows(_written(dest)[0])[0] == ["文件名", "修改时间"]


# ---------------------------------------------------------------------------
# 线框硬断言 (a)：只有一个数
# ---------------------------------------------------------------------------

def test_屏幕上那个份数就是产物里的行数(ctx, branch, tmp_path) -> None:
    """(a) 的原话是「导出行数 == 那条 `SELECT COUNT(*)`」，这里比的是三个读数：
    屏幕上那句里的数、`ctx.export.count()`、产物实际行数。

    服务层在写出之前还比过一次 `len(docs) != total`（取行与数行用了两条口径就当场拒），
    那一半的坏法在 p22 注入里。
    """
    dest = tmp_path / "out"
    dest.mkdir()
    box = _box(ctx, branch["fin"].id)
    shown = int(re.search(r"(\d+) 行", box.count_note.text()).group(1))
    assert shown == ctx.export.count(branch["fin"].id, include_children=True) == 6, \
        box.count_note.text()
    _set_dir(box, dest)
    box.run_export()
    assert len(_csv_rows(_written(dest)[0])) - 1 == shown


def test_含子分类切下去屏幕上那句与产物一起跟着变(ctx, branch, tmp_path) -> None:
    """同一枝的"含子"与"只这一枝"是两个行集，两个读数必须**同时**跟着切换。

    只验屏幕上那句会放过一种很像样的坏法：标签换了、`DocFilter` 没换 —— 于是界面写着
    "只这一枝"，产物里还是整枝。所以这里数产物。
    """
    dest = tmp_path / "out"
    dest.mkdir()
    box = _box(ctx, branch["fin"].id)
    box.child_toggle.setChecked(False)
    assert "只这一枝" in box.count_note.text(), box.count_note.text()
    assert re.search(r"(\d+) 行", box.count_note.text()).group(1) == "2"
    _set_dir(box, dest)
    box.run_export()
    rows = _csv_rows(_written(dest)[0])[1:]
    assert len(rows) == 2 and all(r[0].startswith("财务卷") for r in rows), rows


def test_导出被拒时弹的是失败框而目录里什么都没落(ctx, branch, tmp_path, dialogs) -> None:
    """同一个入口的两条收尾不许混：`information` 是"产物已经在那儿了"，`warning` 是"没有产物"。

    把拒因塞进 `information` 是会骗人的 —— 用户看见一个"完成"字样的弹窗就走了。
    空枝那一条拒因同时在**打开文件之前**，所以目录里必须还是空的（不留 0 字节的"空清单"）。
    """
    dest = tmp_path / "out"
    dest.mkdir()
    box = _box(ctx, branch["empty"].id)
    _set_dir(box, dest)
    box.run_export()
    assert _written(dest) == [], [f.name for f in _written(dest)]
    assert [k for k, _, _ in dialogs] == ["warning"], dialogs
    assert "名下没有文档" in dialogs[0][2], dialogs[0][2]


# ---------------------------------------------------------------------------
# 线框硬断言 (b)：未勾的列不出现
# ---------------------------------------------------------------------------

def test_未勾的列不出现在表头与json键里(ctx, branch, tmp_path) -> None:
    """(b) 要的是"**不出现**"，不是出现且留空。

    CSV 与 JSON 各数一次：这两条渲染路径是分开写的，只验一种会放掉另一种里的漏网。
    """
    csv_dir = tmp_path / "csv"
    csv_dir.mkdir()
    box = _box(ctx, branch["fin"].id)
    box.column_checks["size_bytes"].setChecked(False)
    box.column_checks["mtime"].setChecked(False)
    _set_dir(box, csv_dir)
    box.run_export()
    assert _csv_rows(_written(csv_dir)[0])[0] == ["文件名", "页数", "SHA256（前 12 位）"]

    json_dir = tmp_path / "json"
    json_dir.mkdir()
    box2 = _box(ctx, branch["fin"].id)
    box2.format_buttons["json"].setChecked(True)
    box2.column_checks["size_bytes"].setChecked(False)
    box2.column_checks["mtime"].setChecked(False)
    _set_dir(box2, json_dir)
    box2.run_export()
    payload = json.loads(_written(json_dir)[0].read_text(encoding="utf-8"))
    assert sorted(payload[0]) == ["SHA256（前 12 位）", "文件名", "页数"], sorted(payload[0])


# ---------------------------------------------------------------------------
# 线框硬断言 (c)：本机绝对路径
# ---------------------------------------------------------------------------

def test_默认产物里搜不到盘符(ctx, branch, tmp_path) -> None:
    """(c) 的前半：把十二列**全勾满但不勾隐私列**，产物正文里仍然不许出现 `[A-Z]:\\`。

    勾满再 grep 而不是按默认五列 grep，是因为"默认档里没有路径"可以靠漏列蒙对；
    而「本机绝对路径」是唯一带盘符的来源，其余十一列的值来自文件或库里的元数据。
    """
    dest = tmp_path / "out"
    dest.mkdir()
    box = _box(ctx, branch["fin"].id)
    for key, c in box.column_checks.items():
        c.setChecked(key != "local_path")
    _set_dir(box, dest)
    box.run_export()
    body = _written(dest)[0].read_text(encoding="utf-8-sig")
    assert not DRIVE_LETTER.search(body), f"产物里出现了盘符：{DRIVE_LETTER.findall(body)}"


def test_勾本机绝对路径要先确认一次而确认后产物里才有路径(ctx, branch, tmp_path, dialogs) -> None:
    """(c) 的后半：确认那句的**原文**必须就是服务层的 `LOCAL_PATH_WARNING` —— 两处一份。"""
    dest = tmp_path / "out"
    dest.mkdir()
    box = _box(ctx, branch["fin"].id)
    box.column_checks["mtime"].setChecked(False)
    box.column_checks["local_path"].setChecked(True)
    asked = [t for k, _, t in dialogs if k == "question"]
    assert len(asked) == 1, f"勾一次弹了 {len(asked)} 次确认"
    assert LOCAL_PATH_WARNING in asked[0], asked[0]
    _set_dir(box, dest)
    box.run_export()
    body = _written(dest)[0].read_text(encoding="utf-8-sig")
    assert DRIVE_LETTER.search(body), "勾了并确认了，产物里却没有本机路径"
    assert dialogs[-1][0] == "information", dialogs[-1]


def test_确认时答否就回落到未勾而产物里没有那一列(ctx, branch, tmp_path, dialogs, answers) -> None:
    """答"否"之后复选框**自己回到未勾**：留着勾而产物里没有，屏幕就在说谎。"""
    dest = tmp_path / "out"
    dest.mkdir()
    answers["question"] = QtWidgets.QMessageBox.StandardButton.No
    box = _box(ctx, branch["fin"].id)
    box.column_checks["local_path"].setChecked(True)
    assert not box.column_checks["local_path"].isChecked(), "答了否，复选框还留着勾"
    assert len([k for k, _, _ in dialogs if k == "question"]) == 1, "答否之后又弹了第二次确认"
    _set_dir(box, dest)
    box.run_export()
    assert "本机绝对路径" not in _csv_rows(_written(dest)[0])[0]


# ---------------------------------------------------------------------------
# 线框硬断言 (d)：只读
# ---------------------------------------------------------------------------

def test_只读导出前后五张表逐行不变(ctx, branch, tmp_path) -> None:
    """(d)：`documents` / `document_categories` / `document_tags` + 台账两张表**逐行**相同。

    这条要拦的是"顺手写一笔"的诱惑：导出时给分类记一个"上次导出时间"看起来无害，
    但它让一屏只读操作变成写操作，而界面上没有任何地方说它写了。轮十五 丙 起「已归档」
    要读台账，所以那两张表也进指纹 —— 读归读，写一笔就不行。
    """
    doc = branch["own"][0]
    _ledger(ctx, doc, "E:\\导出测试归档\\只读.pdf")
    _relocate(ctx, doc, "E:\\导出测试归档\\只读.pdf")
    tables = ("documents", "document_categories", "document_tags",
              "file_operations", "operation_items")
    before = _fingerprint(ctx, tables)
    dest = tmp_path / "out"
    dest.mkdir()
    box = _box(ctx, branch["fin"].id)
    box.column_checks["tags"].setChecked(True)
    box.column_checks["archived"].setChecked(True)
    _set_dir(box, dest)
    box.run_export()
    assert _written(dest), "这一条没真的导出东西，指纹相同只是因为什么都没发生"
    assert _fingerprint(ctx, tables) == before, "导出动了库"


# ---------------------------------------------------------------------------
# 线框硬断言 (e)：同名两枝不并
# ---------------------------------------------------------------------------

def test_同名两枝各导各的而产物文件名不撞(ctx, branch, tmp_path) -> None:
    """(e)：「导出测试财务/合同」与「导出测试技术/合同」同名不同层。

    两次导出落到**同一个目录**，产物是两个文件而不是"第二次撞名被拒"：文件名带整条
    `name_path`，所以这两枝天然不撞；行集按 **id** 取子树，所以内容也不串。
    """
    dest = tmp_path / "out"
    dest.mkdir()
    for cat in (branch["fin_ht"], branch["tech_ht"]):
        box = _box(ctx, cat.id)
        _set_dir(box, dest)
        box.run_export()
    files = _written(dest)
    assert len(files) == 2, [f.name for f in files]
    finance = next(f for f in files if "财务" in f.name)
    tech = next(f for f in files if "技术" in f.name)
    assert len(_csv_rows(finance)) - 1 == 3, finance.read_text(encoding="utf-8-sig")
    assert len(_csv_rows(tech)) - 1 == 2, tech.read_text(encoding="utf-8-sig")


# ---------------------------------------------------------------------------
# 门：没有目标就不许点得动（ISSUES I74 那一族）
# ---------------------------------------------------------------------------

def test_没选目录时导出是死的而选了才亮起来(ctx, branch) -> None:
    """不预设一个"看起来对"的目录：产物落哪儿只有人知道。"""
    box = _box(ctx, branch["fin"].id)
    assert not box.export_btn.isEnabled(), "没给目录也能点导出"
    box.dest_input.setText("Z:\\随便什么")
    assert box.export_btn.isEnabled()


def test_一列都不勾时导出也是死的(ctx, branch) -> None:
    """没有列的清单不是清单 —— 与 `ExportService` 那句拒因同一个方向，界面前一道门先拦住。"""
    box = _box(ctx, branch["fin"].id)
    box.dest_input.setText("Z:\\随便什么")
    assert box.export_btn.isEnabled()
    for c in box.column_checks.values():
        c.setChecked(False)
    assert not box.export_btn.isEnabled(), "一列没勾还能点导出"


def test_选择按钮把目录填回输入框(ctx, branch, chooser, tmp_path) -> None:
    """那颗「选择…」的唯一动作就是填回输入框；填回之后导出才亮。"""
    dest = tmp_path / "out"
    dest.mkdir()
    chooser["dir"] = str(dest)
    box = _box(ctx, branch["fin"].id)
    box.choose_btn.click()
    assert box.dest_input.text() == str(dest)
    assert box.export_btn.isEnabled()


# ---------------------------------------------------------------------------
# 接线：菜单上那一项不是空动作
# ---------------------------------------------------------------------------

def test_菜单上那一项按下去真的把弹层开起来(window, ctx, qapp, monkeypatch, branch) -> None:
    """形状对了但没接线，就是 **ISSUES I79** 那一类。这里只验一件事：触发 → 弹层被构造且 `exec`。

    替身接在 `categories_page` 的模块名上（不是 `export_dialog`），所以这条同时也是那句
    "页面用的是什么"的口径：换成直接 import 别处构造对话框，本条红。
    """
    from pdfarchiver.ui.pages import categories_page

    seen: list[list[object]] = []

    class _Recorder:
        def __init__(self, _ctx, category_id, _parent=None) -> None:
            self.seen = seen
            seen.append([category_id])

        def exec(self):
            self.seen[0].append("exec")
            return 0

    monkeypatch.setattr(categories_page, "ExportDialog", _Recorder)
    window._select_by_page_id("categories")
    qapp.processEvents()
    page = window._pages["categories"]
    page.reload()
    qapp.processEvents()

    item = _tree_item(page, "导出测试财务")
    assert item is not None, "分类树没把这枝上屏，右键那一条测不了"
    # `category_menu(it)` 只造菜单，不动选中；真实流程里"把选中挪到被点那一枝"是
    # `_show_category_menu` 干的（由 test_catalog_writes_ui 钉住），这里替它做这一步。
    page.category_tree.setCurrentItem(item)
    action = next(a for a in page.category_menu(item).actions() if a.text() == "导出此分类清单…")
    action.trigger()
    assert seen == [[branch["fin"].id, "exec"]], seen


def test_导出链路每一环在产品侧各有调用点了() -> None:
    """**ISSUES I78** 丙 记的就是「`src/` 里没有任何导出路径」。这条把每一环的调用方逐字写死。"""
    src = Path(__file__).resolve().parents[3] / "src"
    files = {p.relative_to(src).as_posix(): p.read_text(encoding="utf-8") for p in src.rglob("*.py")}
    expected = {
        "ExportService(documents, catalog, operations)": "pdfarchiver/services/bootstrap.py",
        "self.catalog.subtree_ids(category_id)": "pdfarchiver/services/export_service.py",
        "self.ops.last_archive_destinations(": "pdfarchiver/services/export_service.py",
        "is_archived(d.path_key": "pdfarchiver/services/export_service.py",
        "self.ctx.export.count(": "pdfarchiver/ui/export_dialog.py",
        "self.ctx.export.export(": "pdfarchiver/ui/export_dialog.py",
        "ExportDialog(self.ctx, cat_id, self)": "pdfarchiver/ui/pages/categories_page.py",
    }
    for needle, caller in expected.items():
        found = sorted(pos for pos, text in files.items() if needle in text)
        assert found == [caller], f"`{needle}` 的调用方现在是：{found}（应当只有 {caller}）"
