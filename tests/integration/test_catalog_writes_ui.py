"""「归入分类 / 加标签 / 移除标签」+ S8 右键「改父类 / 与…合并」—— **ISSUES I78** 甲（2026-10-19）。

**ISSUES I78** 记的原话是：`CatalogRepository.link_category / link_tag / unlink_tag` 在产品里
**零调用点** —— 用户能建分类、能建标签，却没有任何一处能把一份文档归进去，于是 SPEC 阶段 3
的「分类和标签能够持久化」在产品路径上做不到。线框 §I78-jia
（`docs/wireframes/2026-10-19-round14-i67-i78.html`，2026-10-19 勾「甲」）落地的是：
S1 表格底下三颗按钮（批量）+ S8 分类树右键两项（改父类 / 合并）+ 删除前置检查。

这一组断言逐条对着线框那五条**硬断言**写：
(a) 多选 3 份归入 → `document_categories` 正好 +3 行，再点一次还是 3 行（幂等）；
(b) 归入后再移除：其他类关联不动；
(c) 打标签 → 移除 → 再打：同一 (doc, tag) 只 1 行；
(d) 合并两个分类：源整枝的文档指向目标，源类行数归零；
(e) 改父类：子孙树 `name_path` 整片跟随。
另有四条接线：没有点名对象时三颗按钮是死的；屏幕上那句逐字是后端 `LinkReceipt.describe()`
（**ISSUES I60**：格式化只有一个出口）；写完之后表格那一列当场跟着变，而取分类还是一条查询
（**ISSUES I51** 那条纪律在写路径上的版本）；这六条写方法在 `src/` 里各有真调用点。

**19 条各配一条坏法，全部真注入过**：`tests/probes/p9_reverse_injection.py` 的 p9 注入 I50–I69
（其中 I58 第一次跑是 GREEN —— 那条断言当时走不到重复插，改的是断言而不是坏法，见那里）。

夹具三条规矩照常（offscreen、独立数据根、真 sqlite3 —— **D-012**）。
库里的文档全是现造的假名字，真实语料一条不进测试（**ISSUES I64**）；
`document_categories` 的直接 SELECT **只出现在本文件的读数辅助函数里**（测试直连真库数行，
产品代码一条 SQL 都不写 —— 那是 `tests/guards/test_architecture.py` 钉的方向）。
"""
from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from PySide6 import QtCore, QtWidgets

from pdfarchiver.db.models import Document
from pdfarchiver.fs.identity import identity_key
from pdfarchiver.ui.library_rows import CATEGORY_COLUMN, category_cell_text
from tests.conftest import settle as _settle

_SELECT_FLAGS = (QtCore.QItemSelectionModel.SelectionFlag.Select
                 | QtCore.QItemSelectionModel.SelectionFlag.Rows)


# ---------------------------------------------------------------------------
# 夹具与读数辅助
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def dialogs(monkeypatch) -> list[tuple[str, str, str]]:
    """截住模态提示，返回 `(kind, title, text)` 清单 —— 这批测试的读数全在文案里。

    autouse 的必需性与 `test_archive_execute_ui.py` 同一条：offscreen 下真 `QMessageBox`
    的 `exec()` 会把主线程堵死，而「合并成功」与「拒绝删除」收尾各有一句弹窗。
    """
    shown: list[tuple[str, str, str]] = []

    def _capture(kind: str, reply=None):
        def _fn(parent, title, text, *a, **k):
            shown.append((kind, title, str(text)))
            return reply
        return staticmethod(_fn)

    monkeypatch.setattr(QtWidgets.QMessageBox, "information", _capture("information"))
    monkeypatch.setattr(QtWidgets.QMessageBox, "warning", _capture("warning"))
    monkeypatch.setattr(QtWidgets.QMessageBox, "critical", _capture("critical"))
    monkeypatch.setattr(QtWidgets.QMessageBox, "question",
                        _capture("question", QtWidgets.QMessageBox.StandardButton.Yes))
    return shown


@pytest.fixture
def pick(monkeypatch):
    """把 `QInputDialog.getItem`（改父类 / 合并 挑目标那一格）换成"按下指定的那个名字"。

    返回的是一个可写的 dict：`pick["name"]` 是要选的那一项，`pick["items"]` 记下界面**实际**
    摆出来的清单 —— 「自己不出现在候选里」这条就靠后者断言，不靠读代码。
    """
    ctl: dict[str, object] = {"name": "", "items": []}

    def _getItem(parent, title, prompt, items, *a, **k):
        ctl["items"] = list(items)
        wanted = str(ctl["name"])
        return wanted, wanted in items

    monkeypatch.setattr(QtWidgets.QInputDialog, "getItem", staticmethod(_getItem))
    return ctl


def _library(window, qapp):
    window._select_by_page_id("library")
    _settle(qapp)
    page = window._pages["library"]
    page.reload()
    _settle(qapp)
    return page


def _categories(window, qapp):
    window._select_by_page_id("categories")
    _settle(qapp)
    page = window._pages["categories"]
    page.reload()
    _settle(qapp)
    return page


def _seed(ctx, count: int, prefix: str = "归入测试") -> list[int]:
    """灌 count 份**只有名字**的文档（不碰磁盘），返回 id 列表。"""
    ids: list[int] = []
    for n in range(count):
        name = f"{prefix}{n}号.pdf"
        path = f"D:\\用户资料\\{name}"
        row = ctx.documents.upsert(Document(
            path=path, path_key=identity_key(path), name=name,
            size_bytes=1024 + n, mtime_ns=1_760_000_000_000_000_000,
            sha256=f"{n:064x}", text_status="done", fts_status="done"))
        ids.append(row.id)
    return ids


def _select_docs(page, qapp, doc_ids: list[int]) -> None:
    """在表格上点名这几份（`ExtendedSelection` 下逐行叠加，与键盘 Ctrl+点同一条路径）。"""
    model, sel = page.doc_table.model(), page.doc_table.selectionModel()
    sel.clearSelection()
    for wanted in doc_ids:
        for row in range(page.doc_table.rowCount()):
            item = page.doc_table.item(row, 0)
            if item is not None and item.data(QtCore.Qt.ItemDataRole.UserRole) == wanted:
                sel.select(model.index(row, 0), _SELECT_FLAGS)
    _settle(qapp)


def _click(btn, target_id: int, qapp) -> None:
    """展开那排按钮的菜单，点掉载荷为 `target_id` 的那一项。

    走 `aboutToShow` → `trigger()` 这条真信号链而不是直接调私有槽：菜单"每次展开重取清单"
    就接在这个信号上，绕过它等于把那条约定测成了摆设（**ISSUES I80** 那一类）。
    """
    menu = btn.menu()
    menu.aboutToShow.emit()
    target = next((a for a in menu.actions() if a.data() == target_id), None)
    assert target is not None, f"菜单里没有载荷 {target_id} 这一项：{[a.data() for a in menu.actions()]}"
    target.trigger()
    _settle(qapp)


def _link_count(ctx, doc_ids: list[int], category_id: int | None = None,
                tag_id: int | None = None, table: str = "document_categories") -> int:
    """数关联表里这几份文档的行 —— **只有直连真库数得准**，仓储层没有"数关联行"这个口子。"""
    marks = ",".join("?" * len(doc_ids))
    conn = ctx.engine.thread_connection()
    if table == "document_categories":
        sql = f"SELECT count(*) FROM document_categories WHERE doc_id IN ({marks})"
        args: list = list(doc_ids)
        if category_id is not None:
            sql += " AND category_id=?"
            args.append(category_id)
    else:
        sql = f"SELECT count(*) FROM document_tags WHERE doc_id IN ({marks})"
        args = list(doc_ids)
        if tag_id is not None:
            sql += " AND tag_id=?"
            args.append(tag_id)
    return conn.execute(sql, args).fetchone()[0]


def _walk_items(tree) -> Iterator[QtWidgets.QTreeWidgetItem]:
    stack = [tree.topLevelItem(i) for i in range(tree.topLevelItemCount())]
    while stack:
        item = stack.pop()
        yield item
        stack.extend(item.child(j) for j in range(item.childCount()))


def _cat_item(page, cat_id: int) -> QtWidgets.QTreeWidgetItem:
    item = next((i for i in _walk_items(page.category_tree)
                 if i.data(0, QtCore.Qt.ItemDataRole.UserRole) == cat_id), None)
    assert item is not None, f"树上找不到分类 {cat_id}（上一轮写没落库？）"
    return item


def _tree_paths(page) -> set[str]:
    """把树上每一条**完整路径**收集出来（由"它在第几层、父亲叫什么"拼出，不读库）。

    为什么要有它：**硬断言 (e)** 要的"子孙整片跟随"，只查被挪那一枝自己的 `name_path` 是量不出来的
    —— 子孙掉成孤儿时那一枝照样对，而界面上那一整枝直接不见了（`_reload_categories` 按
    `name_path` 的前缀挂父亲，前缀对不上就没人挂它）。这一句钉的是"树上有的 == 库里有"。
    """
    out: list[str] = []

    def walk(item: QtWidgets.QTreeWidgetItem, prefix: str) -> None:
        path = f"{prefix}/{item.text(0)}" if prefix else item.text(0)
        out.append(path)
        for j in range(item.childCount()):
            walk(item.child(j), path)

    for i in range(page.category_tree.topLevelItemCount()):
        walk(page.category_tree.topLevelItem(i), "")
    return set(out)


class _NoPopup:
    """只替掉"把菜单弹起来"这一步，菜单本体还是 `category_menu()` 真的那一个。

    为什么要这一层而不是 `monkeypatch.setattr(QtWidgets.QMenu, "exec", …)`：offscreen 下真
    `exec()` 会把主线程堵死（本轮实测卡了一次），而 PySide6 的 `exec` 是 metaclass 懒生成的
    改名属性，类级 setattr 盖不住它 —— 桩装上了，`exec` 照样弹。
    """

    def __init__(self, sink: list, menu: QtWidgets.QMenu) -> None:
        self.sink, self.menu = sink, menu

    def exec(self, *args) -> int:
        self.sink.append(self.menu)
        return 0


def _select_cat(page, cat_id: int) -> None:
    """让 S8 树上选中 `cat_id` 这一枝（等价于鼠标点它一下）。"""
    item = _cat_item(page, cat_id)
    page.category_tree.setCurrentItem(item)


def _path_of(ctx, cat_id: int) -> str:
    return next(c.name_path for c in ctx.catalog.list_categories() if c.id == cat_id)


# ---------------------------------------------------------------------------
# 接线：没有点名对象就没有写入的目标
# ---------------------------------------------------------------------------

def test_没有选中任何行时三颗按钮都是死的(window, ctx, qapp) -> None:
    """**ISSUES I74** 那条「:disabled 三件套」在写入口上的版本：按不动，而不是按下去没反应。
    坏法注入见 p9 注入 I50（把 `refresh_enabled` 的判据改成恒真）。
    注意另一条看着等价的坏法**注不动本条**：删掉建按钮那行的 `setEnabled(False)` 还是绿的 ——
    `__init__` 末尾那句 `refresh_enabled()` 已经把三颗按钮按住了，承重的只有那个判据。"""
    ids = _seed(ctx, 2)
    cat = ctx.catalog.add_category("甲类禁用")
    page = _library(window, qapp)
    assert page.doc_table.rowCount() == 2, "用例前提：表里有行，但一行都没点名"

    for btn in (page.link_bar.link_category_btn, page.link_bar.link_tag_btn,
                page.link_bar.unlink_tag_btn):
        assert not btn.isEnabled(), f"{btn.text()} 在没有点名对象时按得动"

    page.link_bar.link_category_btn.click()
    _settle(qapp)
    assert _link_count(ctx, ids, category_id=cat.id) == 0, "禁用态的按钮按下去还是写了关联"


def test_选中一行后三颗一起亮起来(window, ctx, qapp) -> None:
    """三颗按钮共用一个可用性判据（`refresh_enabled`），不许各算各的。"""
    ids = _seed(ctx, 2)
    page = _library(window, qapp)

    _select_docs(page, qapp, [ids[0]])
    for btn in (page.link_bar.link_category_btn, page.link_bar.link_tag_btn,
                page.link_bar.unlink_tag_btn):
        assert btn.isEnabled(), f"点名了一份，{btn.text()} 还是死的"

    _select_docs(page, qapp, [])
    assert not page.link_bar.link_category_btn.isEnabled(), "取消点名之后按钮还亮着"


# ---------------------------------------------------------------------------
# (a) 批量归入：+N 行，且幂等
# ---------------------------------------------------------------------------

def test_多选三份归入一个分类表里正好三行而再点一次还是三行(window, ctx, qapp) -> None:
    """**硬断言 (a)**：一次点击 = 一批文档各一行关联（不是 N 个事务），重复点不加长。"""
    ids = _seed(ctx, 3)
    cat = ctx.catalog.add_category("甲类合同")
    page = _library(window, qapp)
    _select_docs(page, qapp, ids)

    _click(page.link_bar.link_category_btn, cat.id, qapp)

    assert _link_count(ctx, ids, category_id=cat.id) == 3, "归入三份之后关联表不是恰好 3 行"
    assert all(c.id == cat.id for c in ctx.catalog.categories_of(ids[0]))
    held = ctx.catalog.categories_of(ids[2])
    assert [c.name for c in held] == ["甲类合同"], f"三份里最后一份的分类不对：{held}"

    _click(page.link_bar.link_category_btn, cat.id, qapp)
    assert _link_count(ctx, ids, category_id=cat.id) == 3, "同批再点一次，关联表变长了（幂等破了）"
    assert "新增 0 条" in page.status_label.text(), page.status_label.text()


def test_状态条那句逐字就是后端回执(window, ctx, qapp, monkeypatch) -> None:
    """**ISSUES I60** 在写入口上的版本：格式化只有 `LinkReceipt.describe()` 一个出口。
    界面若自己拼「已归入 N 份」，那份数与仓储实际写了几个字就会悄悄漂。"""
    ids = _seed(ctx, 2)
    cat = ctx.catalog.add_category("甲类回执")
    page = _library(window, qapp)
    _select_docs(page, qapp, ids)

    seen: dict = {}
    original = ctx.catalog.link_categories

    def spy(doc_ids, category_id, **kw):
        receipt = original(doc_ids, category_id, **kw)
        seen["receipt"], seen["ids"] = receipt, list(doc_ids)
        return receipt

    monkeypatch.setattr(ctx.catalog, "link_categories", spy)
    _click(page.link_bar.link_category_btn, cat.id, qapp)

    assert seen["ids"] == ids, f"点下去递下去的不是屏幕上点名那几份：{seen.get('ids')}"
    assert page.status_label.text() == seen["receipt"].describe(), (
        f"那句不是后端回执原样：{page.status_label.text()!r}")
    assert page.status_label.objectName() != "danger", "归入成功却是红字"


def test_归入失败时屏幕上留的是后端原文(window, ctx, qapp, monkeypatch) -> None:
    """**ISSUES I84** ③：仓储层抛出来的原文要上屏，不许穿出 Qt 槽让屏幕「什么都不发生」。"""
    ids = _seed(ctx, 1)
    cat = ctx.catalog.add_category("甲类报错")
    page = _library(window, qapp)
    _select_docs(page, qapp, ids)

    def boom(doc_ids, category_id, **kw):
        raise RuntimeError("模拟归入时库被锁住")

    monkeypatch.setattr(ctx.catalog, "link_categories", boom)
    _click(page.link_bar.link_category_btn, cat.id, qapp)

    assert "模拟归入时库被锁住" in page.status_label.text(), page.status_label.text()
    assert page.status_label.objectName() == "danger"
    assert _link_count(ctx, ids, category_id=cat.id) == 0


# ---------------------------------------------------------------------------
# (b) 归入是"加"不是"换"：多分类共存，摘标签不碰分类
# ---------------------------------------------------------------------------

def test_归入第二个分类时第一个分类的关联一条不动(window, ctx, qapp) -> None:
    """**硬断言 (b)**。`document_categories` 的主键是 `(doc_id, category_id)`，
    一份文档本就该能同时属于「合同」和「2026 年度」，所以归入只加不减。"""
    ids = _seed(ctx, 1)
    a = ctx.catalog.add_category("甲类共存")
    b = ctx.catalog.add_category("乙类共存")
    page = _library(window, qapp)
    _select_docs(page, qapp, ids)

    _click(page.link_bar.link_category_btn, a.id, qapp)
    _click(page.link_bar.link_category_btn, b.id, qapp)

    assert _link_count(ctx, ids) == 2, "归入第二类把第一类的关联顶掉了（该是共存）"
    assert {c.name for c in ctx.catalog.categories_of(ids[0])} == {"甲类共存", "乙类共存"}


def test_移除标签只摘那一个而别的标签与分类都不动(window, ctx, qapp) -> None:
    """**硬断言 (b)** 的另一半 + **销账判定②**：那一颗按钮的承诺是「别的标签一条不动」。"""
    ids = _seed(ctx, 2)
    cat = ctx.catalog.add_category("甲类共存")
    keep = ctx.catalog.add_tag("留着")
    drop = ctx.catalog.add_tag("摘掉")
    page = _library(window, qapp)
    _select_docs(page, qapp, ids)

    _click(page.link_bar.link_category_btn, cat.id, qapp)
    _click(page.link_bar.link_tag_btn, keep.id, qapp)
    _click(page.link_bar.link_tag_btn, drop.id, qapp)
    assert _link_count(ctx, ids, table="document_tags") == 4

    _click(page.link_bar.unlink_tag_btn, drop.id, qapp)

    assert _link_count(ctx, ids, tag_id=drop.id, table="document_tags") == 0
    assert _link_count(ctx, ids, tag_id=keep.id, table="document_tags") == 2, "摘一个标签把别的标签也带走了"
    assert _link_count(ctx, ids, category_id=cat.id) == 2, "摘标签把分类关联也带走了"


# ---------------------------------------------------------------------------
# (c) 打 → 移除 → 再打：同一 (doc, tag) 永远只有一行
# ---------------------------------------------------------------------------

def test_打标签移除再打同一份标签只有一行(window, ctx, qapp) -> None:
    """**硬断言 (c)**：`document_tags` 主键是 `(doc_id, tag_id)`，走一圈回来还是 1 行。

    第一轮那两次**连着点**（中间不摘）钉的是幂等：`link_tags` 少做一次判重就会撞主键，
    屏幕上那句跟着翻成「加标签失败」（坏法 p9 注入 I58）。
    摘掉那一步由 p9 注入 I69 钉（`unlink_tags` 里的 `if have:` 改成恒假 ⇒ 点了摘不掉）。
    """
    ids = _seed(ctx, 1)
    tag = ctx.catalog.add_tag("甲类循环")
    page = _library(window, qapp)
    _select_docs(page, qapp, ids)

    for step in range(3):
        _click(page.link_bar.link_tag_btn, tag.id, qapp)
        assert _link_count(ctx, ids, tag_id=tag.id, table="document_tags") == 1, (
            f"第 {step + 1} 轮打上标签之后不是 1 行")
        if step == 0:
            _click(page.link_bar.link_tag_btn, tag.id, qapp)
            assert _link_count(ctx, ids, tag_id=tag.id, table="document_tags") == 1, (
                "同一份标签连着点两次，关联表加长了")
            assert "新增 0 条" in page.status_label.text(), page.status_label.text()
        _click(page.link_bar.unlink_tag_btn, tag.id, qapp)
        assert _link_count(ctx, ids, tag_id=tag.id, table="document_tags") == 0

    _click(page.link_bar.unlink_tag_btn, tag.id, qapp)
    assert "原本没有 1 份" in page.status_label.text(), page.status_label.text()


# ---------------------------------------------------------------------------
# 写完之后表格那一列当场跟着变（而取分类还是一条查询）
# ---------------------------------------------------------------------------

def test_归入之后分类列当场改而一批只走一条查询(window, ctx, qapp, monkeypatch) -> None:
    """**ISSUES I51** 那条纪律在写路径上的版本：只重画被点名的行，取分类一条 SQL。

    本条走的是"只点名、不置当前行"的选中（`select()` 不动 `currentIndex`），所以详情那条
    逐行取分类的路径不参与计数 —— 详情认当前行、按钮认点名，是两个口径（**ISSUES I53** ②）。

    坏法注入实测（p9 注入 I59）：把 `_after_link_written` 里那次
    `categories_by_doc_ids` 换成逐行 `categories_of` ⇒ 本条红在第一句 `一次归入取了 0 批分类`
    （批量那条一次都不发了，逐行那条发了 3 次）。
    """
    ids = _seed(ctx, 3)
    cat = ctx.catalog.add_category("甲类刷新")
    page = _library(window, qapp)
    _select_docs(page, qapp, ids)

    counted = {"per_row": 0, "batched": 0}
    original_of = ctx.catalog.categories_of
    original_batch = ctx.catalog.categories_by_doc_ids

    def counted_of(doc_id):
        counted["per_row"] += 1
        return original_of(doc_id)

    def counted_batch(doc_ids):
        counted["batched"] += 1
        return original_batch(list(doc_ids))

    monkeypatch.setattr(ctx.catalog, "categories_of", counted_of)
    monkeypatch.setattr(ctx.catalog, "categories_by_doc_ids", counted_batch)
    _click(page.link_bar.link_category_btn, cat.id, qapp)
    monkeypatch.undo()

    assert counted["batched"] == 1, (
        f"一次归入取了 {counted['batched']} 批分类（应当恰好一次重画被点名那几行）")
    assert counted["per_row"] == 0, f"一次归入却逐行取了 {counted['per_row']} 次分类"
    for doc_id in ids:
        row = next(r for r in range(page.doc_table.rowCount())
                   if page.doc_table.item(r, 0).data(QtCore.Qt.ItemDataRole.UserRole) == doc_id)
        cell = page.doc_table.item(row, CATEGORY_COLUMN).text()
        assert cell == category_cell_text(ctx.catalog.categories_of(doc_id)), (
            f"第 {row} 行那一列没跟着写变：{cell!r}")


# ---------------------------------------------------------------------------
# (e) S8 改父类：子孙整片跟随
# ---------------------------------------------------------------------------

def test_改父类之后子孙的name_path整片跟随(window, ctx, qapp, pick, dialogs) -> None:
    """**硬断言 (e)**：孙那一层不是"半路成孤儿"，`name_path` 三段全跟着换前缀。

    坏法注入实测（p9 注入 I60）：`reparent_category` 里只改自己被挪的那一行、不重排子孙 ⇒
    本条红在第一句 `孙那层没跟着换前缀`（只查 `mid` 那条是量不出来的，它自己照样对）。
    """
    top = ctx.catalog.add_category("甲类改父")
    mid = ctx.catalog.add_category("中间层", parent_id=top.id)
    grand = ctx.catalog.add_category("孙层", parent_id=mid.id)
    new_top = ctx.catalog.add_category("乙类新家")
    page = _categories(window, qapp)

    _select_cat(page, mid.id)
    pick["name"] = "乙类新家"
    page.reparent_category()
    _settle(qapp)

    assert _path_of(ctx, mid.id) == "乙类新家/中间层"
    assert _path_of(ctx, grand.id) == "乙类新家/中间层/孙层", "孙那层没跟着换前缀"
    assert _path_of(ctx, new_top.id) == "乙类新家"
    assert _tree_paths(page) == {c.name_path for c in ctx.catalog.list_categories()}, (
        "树上的分类与库里的对不上（有一枝掉成了孤儿）")
    assert not dialogs, f"改父类成功却弹了东西：{dialogs}"


def test_放到最外层之后前缀不再带父名(window, ctx, qapp, pick) -> None:
    """「（放到最外层）」那一行的载荷必须是"没有父亲"，而不是某个真分类的 id。"""
    top = ctx.catalog.add_category("甲类上浮")
    kid = ctx.catalog.add_category("下沉层", parent_id=top.id)
    page = _categories(window, qapp)

    _select_cat(page, kid.id)
    pick["name"] = "（放到最外层）"
    page.reparent_category()
    _settle(qapp)

    assert _path_of(ctx, kid.id) == "下沉层"
    assert "（放到最外层）" in pick["items"], f"改父类清单里没有最外层：{pick['items']}"
    assert "甲类上浮" in pick["items"]


def test_自己不出现在改父类的候选清单里(window, ctx, qapp, pick) -> None:
    """`_pick_category` 的 `exclude_id`：把自己当新父亲，仓储层会当场拒，但那一拒的原文
    是技术话术 —— 不如一开始就不给这一项。"""
    top = ctx.catalog.add_category("甲类排除")
    page = _categories(window, qapp)

    _select_cat(page, top.id)
    pick["name"] = "甲类排除"
    page.reparent_category()
    _settle(qapp)

    assert "甲类排除" not in pick["items"], f"候选清单里留着自己：{pick['items']}"
    assert _path_of(ctx, top.id) == "甲类排除", "挑了自己还是把树改坏了"


def test_把父亲挪到自己的子下面被拒而树一根不动(window, ctx, qapp, pick, dialogs) -> None:
    """成环由仓储层拒（口径只有一个），UI 不许自己再算一遍树；拒了就得看得见。"""
    parent = ctx.catalog.add_category("甲类成环")
    child = ctx.catalog.add_category("子类", parent_id=parent.id)
    before = [(c.id, c.name_path) for c in ctx.catalog.list_categories()]
    page = _categories(window, qapp)

    _select_cat(page, parent.id)
    pick["name"] = "甲类成环/子类"      # 清单里给的是 name_path，不是名字
    page.reparent_category()
    _settle(qapp)

    assert [(c.id, c.name_path) for c in ctx.catalog.list_categories()] == before, "成环的移动落库了"
    assert any(kind == "critical" for kind, _, _ in dialogs), f"被拒了却什么都没弹：{dialogs}"


# ---------------------------------------------------------------------------
# (d) S8 合并：源整枝指向目标，源行归零
# ---------------------------------------------------------------------------

def test_合并分类后源整枝的文档指向目标而源行归零(window, ctx, qapp, pick, dialogs) -> None:
    """**硬断言 (d)**：源**与它子孙**名下的文档全部改指目标，然后源整枝删掉。

    「源行归零」数的是 `document_categories` 里 category_id = 源 的残留行 —— 那是外键
    `ON DELETE CASCADE` 该保证的，界面上看不见，只有直连库数得出。
    """
    source = ctx.catalog.add_category("甲类源枝")
    ctx.catalog.add_category("源的子", parent_id=source.id)
    target = ctx.catalog.add_category("甲类目标")
    ids = _seed(ctx, 2)
    ctx.catalog.link_categories(ids, source.id)
    page = _categories(window, qapp)

    _select_cat(page, source.id)
    pick["name"] = "甲类目标"
    page.merge_category()
    _settle(qapp)

    assert _link_count(ctx, ids, category_id=source.id) == 0, "源分类的关联行没归零"
    assert _link_count(ctx, ids, category_id=target.id) == 2, "整枝的文档没指向目标"
    assert [c.name for c in ctx.catalog.categories_of(ids[0])] == ["甲类目标"]
    conn = ctx.engine.thread_connection()
    assert conn.execute("SELECT count(*) FROM categories WHERE id=?", (source.id,)).fetchone()[0] == 0
    receipt = next((text for kind, _, text in dialogs if kind == "information"), "")
    assert "移动 2 份" in receipt, f"合并回执没报出份数：{receipt}"


# ---------------------------------------------------------------------------
# 删除前置检查（§S8 定案）+ 整枝谓词不误伤兄弟
# ---------------------------------------------------------------------------

def test_名下还有文件时删除被拒并给出清单(window, ctx, qapp, dialogs) -> None:
    """§S8 定案：「删除必须先检查该类下是否还有文件，有则拒绝并给出文件清单」。

    同时钉住**整枝谓词不误伤兄弟**：同前缀的「删除测试单据」是另一枝，它那一份文档
    既不该出现在清单里，也不该跟着被删 —— 那是 `LIKE '父%'` 那一类错的现行版本。
    """
    top = ctx.catalog.add_category("删除测试")
    kid = ctx.catalog.add_category("子枝", parent_id=top.id)
    sibling = ctx.catalog.add_category("删除测试单据")
    mine = _seed(ctx, 2, prefix="本枝")
    theirs = _seed(ctx, 1, prefix="兄弟枝")
    ctx.catalog.link_categories([mine[0]], top.id)
    ctx.catalog.link_categories([mine[1]], kid.id)
    ctx.catalog.link_categories(theirs, sibling.id)
    page = _categories(window, qapp)

    _select_cat(page, top.id)
    page.delete_category()
    _settle(qapp)

    kinds = [(kind, text) for kind, _, text in dialogs]
    assert any(k == "warning" for k, _ in kinds), f"有文件却删掉了（没弹拒绝）：{kinds}"
    refuse = next(text for k, text in kinds if k == "warning")
    assert "本枝0号.pdf" in refuse and "本枝1号.pdf" in refuse, f"清单没列全本枝的文件：{refuse}"
    assert "兄弟枝0号.pdf" not in refuse, f"兄弟枝的文件混进了清单：{refuse}"
    conn = ctx.engine.thread_connection()
    assert conn.execute("SELECT count(*) FROM categories WHERE id=?", (sibling.id,)).fetchone()[0] == 1
    assert _link_count(ctx, theirs, category_id=sibling.id) == 1, "删这一枝把同前缀的兄弟也带走了"


def test_空枝才删得掉而子枝一起消失(window, ctx, qapp, dialogs) -> None:
    """检查放行之后删的是**整枝**（子分类一起），而库里那份文档本身一条不动。"""
    top = ctx.catalog.add_category("删除测试乙")
    ctx.catalog.add_category("空的子", parent_id=top.id)
    ids = _seed(ctx, 1)
    page = _categories(window, qapp)

    _select_cat(page, top.id)
    page.delete_category()
    _settle(qapp)

    assert any(kind == "question" for kind, _, _ in dialogs), f"空枝没走确认就删了：{dialogs}"
    remaining = {c.name_path for c in ctx.catalog.list_categories()}
    assert "删除测试乙" not in remaining and "删除测试乙/空的子" not in remaining
    assert ctx.documents.get(ids[0]) is not None, "删分类把文档本身也带走了"


# ---------------------------------------------------------------------------
# 右键菜单的形状：那四项，且不多不少
# ---------------------------------------------------------------------------

def test_右键菜单上就那四项而选中跟着右键走(window, ctx, qapp, monkeypatch) -> None:
    """「改父类 / 合并」这两个动作在产品里只有这一个入口（**ISSUES I78** 甲的补法），
    菜单少一项就是功能没入口；多一项就是**未接线的按钮**（**ISSUES I79** 那一类）。
    「导出此分类清单…」属于 **ISSUES I78** 丙，这一轮出现它就是提前挂了个空动作。

    第二条钉的是 `_show_category_menu` 里那句 `setCurrentItem` —— 菜单上的四个动作全读
    `currentItem()`，右键不先挪选中就会"在 A 上右键、改了 B"。
    """
    opened: list[QtWidgets.QMenu] = []
    cat = ctx.catalog.add_category("甲类菜单")
    page = _categories(window, qapp)
    item = _cat_item(page, cat.id)
    rect = page.category_tree.visualItemRect(item)
    assert rect.isValid(), "offscreen 下树没排出版面，这一条测不了"

    real_menu = page.category_menu
    monkeypatch.setattr(page, "category_menu", lambda it: _NoPopup(opened, real_menu(it)))
    page.category_tree.setCurrentItem(None)
    page._show_category_menu(rect.center())
    _settle(qapp)

    assert len(opened) == 1, f"右键没开出菜单（只开了 {len(opened)} 个）"
    assert page.category_tree.currentItem() is item, "右键没把选中挪到被点的那一枝"
    titles = [a.text() for a in opened[0].actions() if not a.isSeparator()]
    assert titles == ["改名…", "改父类…", f"与…合并「{cat.name}」", "删除（先检查类下有无文件）"], titles
    assert [a.isEnabled() for a in opened[0].actions() if not a.isSeparator()] == [True] * 4


def test_右键空白处不开菜单(window, ctx, qapp, monkeypatch) -> None:
    """`itemAt()` 落空时直接返回：在树下方的空白处右键弹出一个"作用于不确定分类"的菜单，
    比什么都不弹更糟。"""
    opened: list[QtWidgets.QMenu] = []
    ctx.catalog.add_category("甲类空白")
    page = _categories(window, qapp)
    monkeypatch.setattr(page, "category_menu", lambda it: _NoPopup(opened, None))

    page._show_category_menu(QtCore.QPoint(1, 4000))
    _settle(qapp)
    assert opened == [], "在空白处右键还是弹了菜单"


# ---------------------------------------------------------------------------
# ISSUES I78 那条账的本体：六条写方法在产品侧有调用点了
# ---------------------------------------------------------------------------

def test_六条写方法在产品侧各有调用点了() -> None:
    """**ISSUES I78** 记的就是「调用方全在 `tests/`，`src/` 里零调用点」。
    这条把反过来的事实钉住，并把**谁调**逐字写死：哪天拆按钮拆到只剩 `gates/` 在用，本条红。
    坏法见 p9 注入 I53（把 S1 那三颗按钮的 `_write` 调用整段删掉）。

    匹配的是 `.{name}` 而不是 `.{name}(`：S1 那排按钮把方法**本身当值**递给 `_write`
    （`self._write(self.ctx.catalog.link_categories, …)`），真正的调用在 `catalog_links.py`
    里那一处通用的 `write(ids, target_id)`。写死调用方文件比数括号更严 —— 引用它的人变了就红。
    """
    src = Path(__file__).resolve().parents[2] / "src"
    files = {p.relative_to(src).as_posix(): p.read_text(encoding="utf-8") for p in src.rglob("*.py")}
    expected = {
        "link_categories": "pdfarchiver/ui/catalog_links.py",
        "link_tags": "pdfarchiver/ui/catalog_links.py",
        "unlink_tags": "pdfarchiver/ui/catalog_links.py",
        "reparent_category": "pdfarchiver/ui/pages/categories_page.py",
        "merge_categories": "pdfarchiver/ui/pages/categories_page.py",
        "docs_in_subtree": "pdfarchiver/ui/pages/categories_page.py",
    }
    for name, caller in expected.items():
        found = sorted(pos for pos, text in files.items()
                       if f".{name}" in text and not pos.endswith("db/repositories/catalog.py"))
        assert found == [caller], f"`{name}` 的调用方现在是：{found}（应当只有 {caller}）"
