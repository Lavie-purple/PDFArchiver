"""S8 右键「导出此分类清单…」+ 那枚弹层 —— **ISSUES I78** 丙（2026-10-19）。

线框 §I78-bing（`docs/wireframes/2026-10-19-round14-i67-i78.html`，2026-10-19 勾「丙」，
并当场勾了三件口径：默认五列 / CSV 主 / 本机绝对路径默认关）给了五条**硬断言**，
本文件逐条对上，一条不合并：

(a) 导出行数 == 屏幕上那个份数 == `ctx.export.count()`，三个数同源，
    见 `test_屏幕上那个份数就是产物里的行数`；
(b) 未勾的列**不出现在** CSV 表头 / JSON key 里（`test_未勾的列不出现在表头与json键里`）；
(c) 默认产物里 grep 不到盘符，勾了「本机绝对路径」才出现，且勾时弹一次确认
    （`test_默认产物里搜不到盘符` + 确认的两条路径各一条）；
(d) 只读：导出前后 `documents` / `document_categories` / `document_tags` 逐行不变；
(e) 与 **ISSUES I77** 甲 的 `name_ci` 口径一致：同名的两枝各导各的、产物文件名不撞。

另有六条线框没写但实现期冒出来的口径断言：弹层上的列与格式**逐字来自服务层那张表**
（抄一份就会漂，**ISSUES I80** 那一类）、产物列顺序由 `EXPORT_COLUMNS` 定而不是由鼠标轨迹定、
`None` 写成空单元格而不是 `None` 字面量（SPEC 3.2「不得凭空编造」）、CSV 带 BOM 而 JSON/MD 不带、
Markdown 里的竖线要转义、被拒时不留半截产物。屏幕上那句回执逐字来自
`ExportReceipt.describe()`（**ISSUES I60**），「没有目录就不许点得动」沿用 **ISSUES I74** 那一族。

**25 条各配一条坏法，全部真注入过**：`tests/probes/p22_category_export_injection.py`
（2026-10-19 实跑：基线 25 条绿，25 条坏法全部红且各自点名自己那一条，单跑 73s）。

夹具三条规矩照常（offscreen、独立数据根、真 sqlite3 —— **D-012**）；库里的文档全是现造的假名字，
真实语料一条不进测试（**ISSUES I64**）。测试直连真库只为**数行与算指纹**——(d) 那条要的就是
库里的事实；产品代码一条 SQL 都不写（那是 `tests/guards/test_architecture.py` 钉的方向）。
"""
from __future__ import annotations

import csv
import io
import json
import re
from pathlib import Path

import pytest
from PySide6 import QtWidgets

from pdfarchiver.db.models import Document
from pdfarchiver.fs.identity import identity_key
from pdfarchiver.services.export_service import (
    DEFAULT_COLUMNS,
    EXPORT_COLUMNS,
    FORMATS,
    LOCAL_PATH_WARNING,
    ExportReceipt,
)
from pdfarchiver.ui.export_dialog import ExportDialog

#: 带盘符的内容才叫"泄露本机路径"（线框 §I78-bing 硬断言 c 给的就是这条正则）。
DRIVE_LETTER = re.compile(r"[A-Za-z]:[\\/]")
#: Markdown 按**未被反斜杠挡住**的竖线分列。
MD_CELL = re.compile(r"(?<!\\)\|")


@pytest.fixture(autouse=True)
def need_qapp(qapp):
    """本文件每一条都要构造 `QDialog`：没有 QApplication 就构造 QWidget 是直接 abort 进程。"""
    return qapp


@pytest.fixture
def answers() -> dict:
    """模态回答的旋钮，默认一律"Yes"。

    autouse 的 `dialogs` 是在**每次调用时**读这个 dict 的，所以测试里先把它改成 `No`
    再驱动控件是有效的（而不是把夹具顺序赌上去）。
    """
    return {"question": QtWidgets.QMessageBox.StandardButton.Yes}


@pytest.fixture(autouse=True)
def dialogs(monkeypatch, answers) -> list[tuple[str, str, str]]:
    """截住模态提示，返回 `(kind, title, text)` 清单 —— 这批测试的读数大半在文案里。

    autouse 的必需性与 `test_catalog_writes_ui.py` 同一条：offscreen 下真 `QMessageBox`
    的 `exec()` 会把主线程堵死。
    """
    shown: list[tuple[str, str, str]] = []

    def _capture(kind: str, reply=None):
        def _fn(parent, title, text, *a, **k):
            shown.append((kind, title, str(text)))
            return answers["question"] if reply is None else reply
        return staticmethod(_fn)

    monkeypatch.setattr(QtWidgets.QMessageBox, "information", _capture("information"))
    monkeypatch.setattr(QtWidgets.QMessageBox, "warning", _capture("warning"))
    monkeypatch.setattr(QtWidgets.QMessageBox, "critical", _capture("critical"))
    monkeypatch.setattr(QtWidgets.QMessageBox, "question", _capture("question"))
    return shown


@pytest.fixture
def chooser(monkeypatch) -> dict:
    """把"选目录"那个系统对话框换成"返回这里指定的目录"。"""
    ctl: dict[str, object] = {"dir": ""}

    def _get_existing(parent, title, start="", *a, **k):
        return str(ctl["dir"])

    monkeypatch.setattr(QtWidgets.QFileDialog, "getExistingDirectory", staticmethod(_get_existing))
    return ctl


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


@pytest.fixture
def branch(ctx):
    """一棵**故意带同名两枝**的分类树，外加"父亲自己也挂文档"这一档。

    - 「导出测试财务/合同」与「导出测试技术/合同」同名不同层：**ISSUES I77** 甲 的 0008 迁移
      只锁同层重名，所以按**名字**取子树会把两枝并成一坨 —— 这棵树就是为了让那种并法露出来（(e)）。
    - 「导出测试财务」自己名下有 2 份，子枝另有 3 + 1 份：这样"含子分类"切下去是
      **6 → 2** 而不是 **6 → 0**。关掉之后一个都导不出来那种数，分不清"谓词换了"和"当场拒了"。
    """
    fin = ctx.catalog.add_category("导出测试财务")
    fin_ht = ctx.catalog.add_category("合同", parent_id=fin.id)
    sub = ctx.catalog.add_category("报销", parent_id=fin.id)
    tech = ctx.catalog.add_category("导出测试技术")
    tech_ht = ctx.catalog.add_category("合同", parent_id=tech.id)
    empty = ctx.catalog.add_category("导出测试空枝")

    own = _docs(ctx, 2, "财务卷")
    kids = _docs(ctx, 3, "合同卷")
    bare = _docs(ctx, 1, "报销卷", bare=True)
    tech_ids = _docs(ctx, 2, "技术卷")
    ctx.catalog.link_categories(own, fin.id)
    ctx.catalog.link_categories(kids, fin_ht.id)
    ctx.catalog.link_categories(bare, sub.id)
    ctx.catalog.link_categories(tech_ids, tech_ht.id)
    tag = ctx.catalog.add_tag("导出测试标签")
    ctx.catalog.link_tags(own, tag.id)
    return {"fin": fin, "fin_ht": fin_ht, "sub": sub, "tech": tech, "tech_ht": tech_ht,
            "empty": empty, "own": own, "kids": kids, "bare": bare, "tech_ids": tech_ids}


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
    """三张表的**逐行指纹**：内容一样 → 字符串一样。导出前后各算一次就是 (d) 那条。"""
    conn = ctx.engine.thread_connection()
    out: dict[str, str] = {}
    for table in tables:
        rows = conn.execute(f"SELECT * FROM {table}").fetchall()
        out[table] = repr(sorted(str(tuple(r)) for r in rows))
    return out


def _csv_rows(path: Path) -> list[list[str]]:
    return list(csv.reader(io.StringIO(path.read_text(encoding="utf-8-sig"))))


# ---------------------------------------------------------------------------
# 口径来源：弹层不许抄一份列清单
# ---------------------------------------------------------------------------

def test_弹层上的列与格式逐字来自服务层那张表(ctx, branch) -> None:
    """**ISSUES I80** 那一类：界面写着有、产物写不出。

    十一行复选框与三颗单选钮的**文本**必须逐个等于 `EXPORT_COLUMNS` / `FORMATS` 里的标签 ——
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
    """(c) 的前半：把十一列**全勾满但不勾隐私列**，产物正文里仍然不许出现 `[A-Z]:\\`。

    勾满再 grep 而不是按默认五列 grep，是因为"默认档里没有路径"可以靠漏列蒙对；
    而「本机绝对路径」是唯一带盘符的来源，其余十列的值都来自文件本身。
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

def test_只读导出前后三张表逐行不变(ctx, branch, tmp_path) -> None:
    """(d)：`documents` / `document_categories` / `document_tags` 三张表**逐行**相同。

    这条要拦的是"顺手写一笔"的诱惑：导出时给分类记一个"上次导出时间"看起来无害，
    但它让一屏只读操作变成写操作，而界面上没有任何地方说它写了。
    """
    tables = ("documents", "document_categories", "document_tags")
    before = _fingerprint(ctx, tables)
    dest = tmp_path / "out"
    dest.mkdir()
    box = _box(ctx, branch["fin"].id)
    box.column_checks["tags"].setChecked(True)
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
    """标签列是十一列里唯一要**跨表**取值的：一批一条查询取回（**ISSUES I51** 那条纪律）。

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
    src = Path(__file__).resolve().parents[2] / "src"
    files = {p.relative_to(src).as_posix(): p.read_text(encoding="utf-8") for p in src.rglob("*.py")}
    expected = {
        "ExportService(documents, catalog)": "pdfarchiver/services/bootstrap.py",
        "self.catalog.subtree_ids(category_id)": "pdfarchiver/services/export_service.py",
        "self.ctx.export.count(": "pdfarchiver/ui/export_dialog.py",
        "self.ctx.export.export(": "pdfarchiver/ui/export_dialog.py",
        "ExportDialog(self.ctx, cat_id, self)": "pdfarchiver/ui/pages/categories_page.py",
    }
    for needle, caller in expected.items():
        found = sorted(pos for pos, text in files.items() if needle in text)
        assert found == [caller], f"`{needle}` 的调用方现在是：{found}（应当只有 {caller}）"
