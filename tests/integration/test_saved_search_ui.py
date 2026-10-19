"""S1 把筛选条件存成智能集合 → S8 点开回放 —— **ISSUES I78** 乙（2026-10-19）。

**ISSUES I78** 那一格记的第三件事是：`CollectionRepository` 会存 `query_json`，可产品里**没有任何
一处能产生一份条件** —— S8 那颗「新建」存的是 `query={}`（一条集合等于"全库"），而 S1 的筛选只存在于
一个屏幕上看不见的 `_selected_category_id`。SPEC 阶段 3「智能集合可根据保存的查询条件返回真实结果」
因此一直不成立。线框 §I78-yi（`docs/wireframes/2026-10-19-round14-i67-i78.html`，2026-10-19 勾「乙」）
落地的是：S1 搜索框底下一排 chips（筛选条件的唯一现场）+「存为智能集合 / 覆盖此集合」，S8 右栏每行
带现数的命中、双击回放。

这一组断言逐条对着线框那五条**硬断言**写：
(a) 存 → 关 → 开，筛选条件与结果仍是同一份；
(b) `Criteria → query_json → Criteria` 往返 `==`；
(c) 删除集合不许动文档（SPEC 3.3.5）；
(d) 集合那一行的命中数 = 回放后表格的行数；
(e) `update_query` 在产品里从「零调用点」变成有调用点，且调用方写死。

另有七条接线：chips 那张表与 `search.QUERY_FIELDS` 同一批字段、「索引状态」那几种说法与
`SEARCHABLE_STATUSES` 同一批（界面无从 import，所以只能钉住读数）、去掉一枚 chip 是去掉那个键
而不是置成默认值、「标签要全部命中」在没有标签时既不上屏也不入库、关键词检索**就在当前这排条件里搜**
（修前那句 `search_text` 会配着「分类 = 合同」的文案返回别的分类的文档 —— **ISSUES I11** 的最新一例）、
S8 那排按钮读的是行上那条 `CollectionEntry` 而不是第几行，以及两行拆分的分档算术。

**每条各配一条坏法，全部真注入过**：`tests/probes/p21_saved_search_injection.py`（24 条）。

夹具三条规矩照常（offscreen、独立数据根、真 sqlite3 —— **D-012**）。
文档全是现造的假名字，真实语料一条不进测试（**ISSUES I64**）；直接 SELECT 只出现在本文件的读数
辅助函数里（测试直连真库数行，产品代码一条 SQL都不写）。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from PySide6 import QtCore, QtWidgets

from pdfarchiver.db.models import Document
from pdfarchiver.db.repositories.documents import SEARCHABLE_STATUSES
from pdfarchiver.fs.identity import identity_key
from pdfarchiver.search.service import QUERY_FIELDS, Criteria
from pdfarchiver.services.bootstrap import bootstrap
from pdfarchiver.ui.collection_bar import CONDITIONS, FTS_LABELS
from pdfarchiver.ui.main_window import MainWindow
from tests.conftest import settle as _settle

_SRC = Path(__file__).resolve().parents[2] / "src" / "pdfarchiver"


# ---------------------------------------------------------------------------
# 夹具与读数辅助
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def dialogs(monkeypatch) -> list[tuple[str, str, str]]:
    """截住模态提示，返回 `(kind, title, text)` 清单。

    必需性与 `test_catalog_writes_ui.py` 同一条：offscreen 下真 `QMessageBox` 的 `exec()`
    会把主线程堵死，而这一屏的「删除集合」「候选清单是空的」各要弹一句。
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
def answers(monkeypatch):
    """把 `QInputDialog.getText` 换成"依次吐出这几句"（集合名、备注、页数、大小都走它）。

    队列吐完就返回 `(="", False)` = 人按了取消，所以"多问了一次"不会被静默喂一个默认值。
    """
    ctl: dict[str, object] = {"queue": [], "asked": []}

    def _getText(parent, title, prompt, *a, **k):
        ctl["asked"].append((str(title), str(prompt)))
        if not ctl["queue"]:
            return "", False
        return str(ctl["queue"].pop(0)), True

    monkeypatch.setattr(QtWidgets.QInputDialog, "getText", staticmethod(_getText))
    return ctl


@pytest.fixture
def choose(monkeypatch):
    """把 `QInputDialog.getItem`（分类 / 标签 / 监测根 / 索引状态 挑一个）换成"按下指定那一项"。

    与 `test_catalog_writes_ui.py` 的 `pick` 同一形状：`choose["label"]` 是要选的**显示文案**，
    `choose["items"]` 记下界面实际摆出来的清单 —— 「候选里到底有什么」由此可断言，不靠读代码。
    """
    ctl: dict[str, object] = {"label": "", "items": []}

    def _getItem(parent, title, prompt, items, *a, **k):
        ctl["items"] = list(items)
        wanted = str(ctl["label"])
        return wanted, wanted in items

    monkeypatch.setattr(QtWidgets.QInputDialog, "getItem", staticmethod(_getItem))
    return ctl


def _seed(ctx, count: int, *, prefix: str, fts: str = "done") -> list[int]:
    """灌 count 份**只有名字**的文档（不碰磁盘），返回 id 列表。

    `prefix` 必填且每次要不同：`path_key` 是 upsert 的幂等键，两次用同名会**改写同一行**，
    于是"两组文档"变成"一组"，断言就永远抓不到第二组。
    """
    ids: list[int] = []
    for n in range(count):
        name = f"{prefix}{n}号.pdf"
        path = f"D:\\用户资料\\{name}"
        row = ctx.documents.upsert(Document(
            path=path, path_key=identity_key(path), name=name,
            size_bytes=4096, page_count=2, mtime_ns=1_760_000_000_000_000_000,
            sha256=f"{abs(hash(prefix)) * 1000 + n:064x}",
            text_status=fts, fts_status=fts))
        ids.append(row.id)
    return ids


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


def _chips(bar) -> list[QtWidgets.QFrame]:
    """chip 控件本身（不是内部状态）：断言"上屏了几枚"必须数真的控件。"""
    lay = bar.chip_row.layout()
    return [lay.itemAt(i).widget() for i in range(lay.count())
            if isinstance(lay.itemAt(i).widget(), QtWidgets.QFrame)
            and lay.itemAt(i).widget().objectName() == "filterChip"]


def _chip_texts(bar) -> list[str]:
    return [c.findChild(QtWidgets.QLabel).text() for c in _chips(bar)]


def _placeholder_text(bar) -> str:
    """没有条件时那一行的说法（它是 chip 位上的一个 QLabel，不是内部字段）。"""
    label = bar.chip_row.findChild(QtWidgets.QLabel)
    return label.text() if label is not None else ""


def _click_cross(bar, index: int, qapp) -> None:
    """点掉第 `index` 枚 chip 上的 ×。走 `QToolButton.click()`（发真 `clicked` 信号），不调私有槽。"""
    _chips(bar)[index].findChild(QtWidgets.QToolButton).click()
    _settle(qapp)


def _pick_menu_field(btn, field: str) -> None:
    """展开「添加条件」菜单并按下载荷为 `field` 的那一项。

    走 `aboutToShow` → `trigger()` 这条真信号链：菜单"每次展开重取条件表"就接在那个信号上，
    绕过它等于把那条约定测成摆设（与 `test_catalog_writes_ui._click` 同一条理由）。
    """
    menu = btn.menu()
    menu.aboutToShow.emit()
    target = next((a for a in menu.actions() if a.data() == field), None)
    assert target is not None, f"菜单里没有 {field} 这一项：{[a.data() for a in menu.actions()]}"
    target.trigger()


def _doc_ids(page) -> list[int]:
    return [page.doc_table.item(row, 0).data(QtCore.Qt.ItemDataRole.UserRole)
            for row in range(page.doc_table.rowCount())]


def _cat(ctx, name: str) -> int:
    return ctx.catalog.add_category(name).id


def _stored_json(ctx, collection_id: int) -> dict:
    """库里那一行 `query_json` 反序列化回来的东西 —— 断言"存进去的到底是什么"只能直连真库看。"""
    conn = ctx.engine.thread_connection()
    row = conn.execute("SELECT query_json FROM collections WHERE id=?", (collection_id,)).fetchone()
    return json.loads(row[0])


def _save_current(page, qapp, answers, name: str) -> int:
    """点真按钮存一条集合，返回它的 id。"""
    answers["queue"] = [name, ""]              # 名字 + 备注（备注留空）
    page.filter_bar.save_btn.click()
    _settle(qapp)
    return next(e.id for e in page.ctx.collection.entries() if e.name == name)


# ---------------------------------------------------------------------------
# (b) 一份条件的往返：Criteria ⇄ query_json
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("criteria", [
    Criteria(),                                                # 一条都不设
    Criteria(category_ids=(3,), min_pages=10),                  # tuple → list 那一跳
    Criteria(tag_ids=(1, 2), tag_match_all=True, root_key="D:\\docs",
             modified_from=1_760_000_000, fts_status="pending", missing_only=True),
], ids=["空条件", "分类+页数", "六条一起"])
def test_条件经过query_json往返还是同一条(criteria: Criteria) -> None:
    """**硬断言 (b)**：`Criteria → query_json → Criteria` 两端 `==`，而且再存一次不变形。

    过的是真 JSON 文本而不是 dict：库里躺着的是 `query_json` 那一列，tuple 会在这里变成 list、
    `None` 会在这里变成 null —— 只比 dict 的话这两处都测不到。
    第二跳（`back.to_query()` 与存进去那份逐字相同）钉的是"存一次和存两次是同一个字节串"，
    否则「覆盖此集合」会把同一份条件越写越歪。
    """
    dumped = json.dumps(criteria.to_query(), ensure_ascii=False, sort_keys=True)
    back = Criteria.from_query(json.loads(dumped))
    assert back == criteria, f"往返回来不是同一条：{back} ≠ {criteria}"
    assert json.dumps(back.to_query(), ensure_ascii=False, sort_keys=True) == dumped


def test_集合只存筛选条件不存这次怎么看() -> None:
    """`text / in_fields / sort / limit / offset` 一律不进 `query_json`。

    那是"这一次怎么看"，存进集合等于把一次查询的偶然状态固化成永久条件（回放时用户会看到
    自己上次滚到第几页）。这一条同时是 (b) 的边界：正因为不存这些，往返才可能 `==`。
    """
    query = Criteria(text="合同", sort="size", limit=200, offset=50).to_query()
    assert not ({"text", "in_fields", "sort", "limit", "offset"} & set(query))
    assert set(query) == set(QUERY_FIELDS)


def test_认不出的键当场拒() -> None:
    """`from_query` 不许咽下不认识的键：咽下去 = 屏幕上写着筛过、库里一条 WHERE 都没加。

    三种最可能的来源：手写过集合（`category` 少个 `_ids`）、存了不该存的那一格（`text`）、
    把数字写成了中文。
    """
    for bad in ({"category": [3]}, {"text": "合同"}, {"min_pages": "十"}):
        with pytest.raises(ValueError):
            Criteria.from_query(bad)


# ---------------------------------------------------------------------------
# chips 那张表与后端口径不许漂（界面无从 import，只能钉住读数）
# ---------------------------------------------------------------------------

def test_筛选条这张表与集合能存的字段同一批() -> None:
    """读写同源靠的是**同一批键名**：两处各自增减就变成两套条件。

    界面多一条 chips（`CONDITIONS` 多出一个键）→ 存进去后 `from_query` 当场拒（上一条），
    集合根本存不下；
    `QUERY_FIELDS` 多一个字段而界面没有 → 那份条件**永远存不进集合**，屏幕上不说为什么。
    两种漂法本条都红。只比集合不比顺序：菜单顺序是界面自己的排法，不是契约。
    """
    assert {c.field for c in CONDITIONS} == set(QUERY_FIELDS)
    assert len(CONDITIONS) == len(QUERY_FIELDS), "条件表里有重复字段"


def test_索引状态那几句说法与库里可搜的状态同一批() -> None:
    """`fts_status` 的取值由 `db...SEARCHABLE_STATUSES` 定，界面 import 不到它（架构守卫）。

    漂了的后果不是报错而是**筛不出东西**：chip 上写 `已完成`，那一列的值是 `done`，
    于是这条条件永远命中 0 份，而屏幕上那句话看着完全合理。
    """
    assert set(FTS_LABELS) == set(SEARCHABLE_STATUSES)


def test_条件表每一枚都上得了屏也问得出值() -> None:
    """每枚 chips 必须有菜单句（`menu`）、chip 句（`prefix`），且 `ask` 认得。

    `ask` 写错一个字的后果不是崩，是 `_ask` 走到最后一支（当成"大小"问）：于是「页数」那枚
    弹出一个 `50 MB` 的输入框，值能存进去、SQL 不报错，只有人是错的。
    `multi` 必须与值的形状一致：`*_ids` 是一串 id（每枚 chip 只删自己那一个），其余是单值。
    """
    assert {c.ask for c in CONDITIONS} <= {"category", "tag", "root", "fts",
                                           "day_from", "day_to", "pages", "size", "flag"}
    for cond in CONDITIONS:
        assert cond.menu and cond.prefix, f"{cond.field} 没有可上屏的说法"
        assert cond.multi == (cond.field.endswith("_ids")), f"{cond.field} 的值形状标错了"


# ---------------------------------------------------------------------------
# (a) 存 → 关 → 开，条件与结果还是同一份
# ---------------------------------------------------------------------------

def test_存一条集合_关开一次_条件与结果仍是同一份(window, qapp, answers, choose) -> None:
    """**硬断言 (a)**：条件不是内存里的临时状态，重启后回放它必须一模一样。

    走的是真人那条路：菜单加「分类」→ 挑一个 → 再加「索引状态」→ 挑一个 → 存名字 → 关窗重开 →
    S8 双击。中间没有一处直接写 dict，所以这条同时是"添加条件的菜单接线"的验收。
    """
    ctx = window.ctx
    cat_id = _cat(ctx, "合同卷")
    _seed(ctx, 3, prefix="已索引卷")
    pending = _seed(ctx, 2, prefix="待索引卷", fts="pending")
    ctx.catalog.link_categories(pending, cat_id)
    page = _library(window, qapp)

    choose["label"] = "合同卷"
    _pick_menu_field(page.filter_bar.add_btn, "category_ids")
    choose["label"] = "待索引"
    _pick_menu_field(page.filter_bar.add_btn, "fts_status")
    _settle(qapp)
    assert page.filter_bar.query() == {"category_ids": [cat_id], "fts_status": "pending"}

    before_texts = _chip_texts(page.filter_bar)
    assert before_texts == ["分类 = 合同卷", "索引状态 = 待索引"], before_texts
    coll_id = _save_current(page, qapp, answers, "待办的合同")
    assert "已存为集合「待办的合同」· 命中 2 份" in page.status_label.text()
    # 写进库里的那一份必须是**回放得起来**的那一份：真人这条路上递出去的是屏幕上的 dict，
    # 落盘的却是 `Criteria` 规范化后的 —— 后面那一截不是屏幕状态，只能从库里查。
    assert Criteria.from_query(_stored_json(ctx, coll_id)).to_query() == \
        Criteria(category_ids=(cat_id,), fts_status="pending").to_query()

    root = ctx.paths.root
    window.close()
    second = bootstrap(root)
    try:
        w2 = MainWindow(second)
        w2.show()
        s8 = _categories(w2, qapp)
        assert [e.name for e in second.collection.entries()] == ["待办的合同"]
        s8.collection_list.itemDoubleClicked.emit(s8.collection_list.item(0))
        _settle(qapp)
        page2 = w2._pages["library"]
        assert page2.filter_bar.query() == {"category_ids": [cat_id], "fts_status": "pending"}
        assert _chip_texts(page2.filter_bar) == before_texts, "重启后 chip 上屏的说法变了"
        assert set(_doc_ids(page2)) == set(pending), "重启后回放出的是另一批文档"
        w2.close()
    finally:
        second.shutdown()


def test_存集合存的是规范化那一份而不是屏幕上的写法(window, qapp, answers) -> None:
    """屏幕上递的是 list，`Criteria` 里是 tuple，库里必须落成**规范化后**的那份。

    不规范化就会出现同一个条件两种写法（`[3]` 与 `(3,)`），`==` 回不来，而"集合存的条件"与
    "界面显示的条件"从此是两个东西 —— 那正是 (a) 要拦的事，只是它在写的一侧。
    """
    ctx = window.ctx
    cat_id = _cat(ctx, "写法卷")
    page = _library(window, qapp)
    page.filter_bar.set_field("category_ids", [cat_id])         # 故意用 list 递进去
    coll_id = _save_current(page, qapp, answers, "写法")

    assert _stored_json(ctx, coll_id) == Criteria(category_ids=(cat_id,)).to_query()


# ---------------------------------------------------------------------------
# (d) 命中数 = 回放后的行数
# ---------------------------------------------------------------------------

def test_集合那一行的命中数等于回放后表格的行数(window, qapp, answers) -> None:
    """**硬断言 (d)**：S8 那个数与 S1 那张表必须是同一个 WHERE 数出来的。

    两侧都不是界面自己数的：数由 `documents.count_matching` 出（`CollectionService.entries`），
    回放由 `browse_documents(query=…)` 取 —— 两者共用 `Criteria.browse_page().doc_filter()`。
    所以这一条红的典型原因是有人在某一侧另拼了一份过滤条件。

    行数只在此刻**不大于一批**时等于总数（`DEFAULT_PAGE_SIZE=50`，§I51 的虚拟化）；
    这里整条条件筛出 3 份，所以全部在表上。
    """
    ctx = window.ctx
    cat_id = _cat(ctx, "对账卷")
    ids = _seed(ctx, 4, prefix="对账")
    ctx.catalog.link_categories(ids[:3], cat_id)
    page = _library(window, qapp)
    page.filter_bar.set_field("category_ids", [cat_id])
    coll_id = _save_current(page, qapp, answers, "三份的那条")

    entry = next(e for e in ctx.collection.entries() if e.id == coll_id)
    assert entry.hits == 3, f"存的时候数出来就不是 3：{entry.hits}"

    page.filter_bar.apply_query({})                    # 先退回全库
    _settle(qapp)
    assert page.doc_table.rowCount() == 4
    s8 = _categories(window, qapp)
    s8.collection_list.itemDoubleClicked.emit(s8.collection_list.item(0))
    _settle(qapp)
    assert page.doc_table.rowCount() == entry.hits, (
        f"集合说 {entry.hits} 份，回放表上 {page.doc_table.rowCount()} 行")


# ---------------------------------------------------------------------------
# (c) 删除集合不许动文档
# ---------------------------------------------------------------------------

def test_删除集合只删那一行查询不动文档(window, qapp, answers) -> None:
    """**硬断言 (c)**（SPEC 3.3.5）：集合是"保存的查询"，不是一份文件分组。

    从 S8 那排按钮点出去（不是直接调服务），所以这条同时钉住"按钮读的是行上那条 `CollectionEntry`"。
    """
    ctx = window.ctx
    cat_id = _cat(ctx, "删集合卷")
    ids = _seed(ctx, 3, prefix="删集合")
    ctx.catalog.link_categories(ids, cat_id)
    page = _library(window, qapp)
    page.filter_bar.set_field("category_ids", [cat_id])
    _save_current(page, qapp, answers, "要被删掉的")

    docs_before = ctx.documents.count()
    links_before = ctx.engine.thread_connection().execute(
        "SELECT count(*) FROM document_categories").fetchone()[0]

    s8 = _categories(window, qapp)
    s8.collection_list.setCurrentRow(0)
    s8.delete_coll_btn.click()
    _settle(qapp)

    assert ctx.collections.count() == 0, "集合行没删掉"
    assert s8.collection_list.count() == 0, "界面上那一行还留着"
    assert ctx.documents.count() == docs_before, "删集合把文档删了"
    assert ctx.engine.thread_connection().execute(
        "SELECT count(*) FROM document_categories").fetchone()[0] == links_before, "删集合动了分类关联"


# ---------------------------------------------------------------------------
# (e) update_query 的调用点
# ---------------------------------------------------------------------------

def test_update_query在产品里有调用点且调用方写死() -> None:
    """**硬断言 (e)**：`update_query` 此前是"仓储层定义了、全项目零调用"的死方法。

    这条把反过来的事实钉住，并写死**谁调**：只有服务层的 `overwrite` 该碰它（界面不许直取仓储 ——
    规范化与空条件检查都只在服务层）。哪天有人让 `ui` 直接调 `ctx.collections.update_query`，
    就绕过了 `_require_usable`，"存了一条不生效的条件"那条路重新打开。
    第二条读数管的是"服务层那一处真被界面点得到"：`CollectionService.overwrite` 的调用方
    只许是 S1 那颗「覆盖此集合」。
    """
    files = {p.relative_to(_SRC).as_posix(): p.read_text(encoding="utf-8")
             for p in _SRC.rglob("*.py")}
    found = sorted(pos for pos, text in files.items() if ".update_query" in text)
    assert found == ["services/collection_service.py"], f"`update_query` 的调用方现在是：{found}"
    callers = sorted(pos for pos, text in files.items()
                     if ".overwrite(" in text and not pos.endswith("collection_service.py"))
    assert callers == ["ui/collection_bar.py"], f"`overwrite` 的调用方现在是：{callers}"


def test_覆盖此集合改写存着的那份而不新增一行(window, qapp, answers) -> None:
    """「覆盖」的语义：同一条集合、同一个名字、条件换成屏幕上这一排。

    如果它变成"再存一条"，库里会长出两条同名条件，而 (e) 那条 `update_query` 又回到零调用点。
    """
    ctx = window.ctx
    cat_a, cat_b = _cat(ctx, "甲卷"), _cat(ctx, "乙卷")
    page = _library(window, qapp)
    page.filter_bar.set_field("category_ids", [cat_a])
    coll_id = _save_current(page, qapp, answers, "覆盖测试")

    page.filter_bar.set_field("category_ids", [cat_b])       # 就地改条件：覆盖按钮该亮起来
    assert page.filter_bar.overwrite_btn.isEnabled(), \
        "就地改一枚 chip 把集合的身份弄丢了 —— 「覆盖此集合」从此只能在条件没变时点亮，那次是空动作"
    assert page.filter_bar.source_label.text() == "来自集合「覆盖测试」· 已改动，覆盖才写回", \
        "屏幕与存着的那份不一致时必须说出来，不许静顶着「来自集合」这个名字"
    page.filter_bar.overwrite_btn.click()
    _settle(qapp)

    assert ctx.collections.count() == 1, "覆盖变成了新增"
    assert ctx.collections.get(coll_id).name == "覆盖测试"
    assert Criteria.from_query(_stored_json(ctx, coll_id)) == Criteria(category_ids=(cat_b,))
    assert "已覆盖集合「覆盖测试」" in page.status_label.text()
    assert page.filter_bar.source_label.text() == "来自集合「覆盖测试」", "写回后出处该退回"


# ---------------------------------------------------------------------------
# chips 的接线：加 / 删 / 空条件
# ---------------------------------------------------------------------------

def test_去掉一枚chip是去掉那个键而不是置成默认值(window, qapp) -> None:
    """两条条件时删掉一枚，另一条纹丝不动（`_without` 只 pop 指定那一个键）。

    写成"置成默认值"的话 `query_json` 里会留着 `fts_status: null` 这种键，而
    `Criteria.from_query` 对缺键与 null 一律落回默认 —— 两种写法都能过，于是同一条件在库里
    出现两种形状，「覆盖此集合」的判等开始不稳。
    """
    cat_id = _cat(window.ctx, "删章卷")
    _seed(window.ctx, 2, prefix="删章")
    page = _library(window, qapp)
    page.filter_bar.set_field("category_ids", [cat_id])
    page.filter_bar.set_field("fts_status", "pending")
    assert len(_chips(page.filter_bar)) == 2

    _click_cross(page.filter_bar, 1, qapp)          # 第二枚 = 索引状态
    assert page.filter_bar.query() == {"category_ids": [cat_id]}
    assert len(_chips(page.filter_bar)) == 1


def test_标签没了全部命中那条也跟着走(window, qapp) -> None:
    """`tag_match_all` 只能挂在标签上：留着它就等于存一条屏幕上看不见、却会被带进回放的条件。

    另一半在 `_chips()`：没有标签时它**连上屏都不许**（**ISSUES I11**「界面宣称它会做它不做的事」）。
    """
    tag = window.ctx.catalog.add_tag("临时标")
    page = _library(window, qapp)
    page.filter_bar.set_field("tag_ids", [tag.id])
    page.filter_bar.set_field("tag_match_all", True)
    assert _chip_texts(page.filter_bar) == ["标签 = 临时标", "标签要全部命中"]

    _click_cross(page.filter_bar, 0, qapp)          # 第一枚 = 那枚标签
    assert page.filter_bar.query() == {}
    assert _chips(page.filter_bar) == [], "标签清空后「全部命中」还挂在屏幕上"

    # 单独一条「全部命中」（标签为空）既不上屏，也就存不进集合 —— 与空条件同一扇门。
    page.filter_bar.apply_query({"tag_match_all": True})
    assert _chips(page.filter_bar) == []
    assert not page.filter_bar.save_btn.isEnabled()


def test_没有条件时存不动界面也说为什么(window, qapp, answers) -> None:
    """空条件的两扇门：按钮是死的（并写明为什么），服务层也拒（谁绕过按钮都拒得了）。

    `save_btn` 的判据必须是**翻转过来的**：它在 `_render()` 里按"此刻有没有 chips"设，
    所以先加一条（亮）、再点「清除全部」（灭），两侧都量到才算断言 —— 只写
    `not isEnabled()` 的话，构造函数里默认禁用的控件也能骗过它（p9 注入 I58 那一例）。
    """
    cat_id = _cat(window.ctx, "门卷")
    page = _library(window, qapp)
    page.filter_bar.set_field("category_ids", [cat_id])
    assert page.filter_bar.save_btn.isEnabled()

    page.filter_bar.clear_btn.click()               # 「清除全部」是真按钮，不是内部方法
    _settle(qapp)
    assert not page.filter_bar.save_btn.isEnabled()
    assert "先加至少一条条件" in page.filter_bar.save_btn.toolTip()
    assert "没有筛选条件" in _placeholder_text(page.filter_bar)

    with pytest.raises(ValueError, match="没有任何筛选条件"):
        window.ctx.collection.save("空条件", {})


def test_旧版那种空条件集合上屏写着它筛过什么(window, qapp) -> None:
    """库里可能留着旧版「新建」存下的 `query={}` 行 —— 屏幕上不许替它假装它筛过什么。

    这条不改数据（迁移与回退不许自行删，AGENTS.md），只把读数改成如实的那一句。
    """
    window.ctx.collections.add("旧版留下的", {})      # 绕过服务层，直取仓储造出历史行
    entry = window.ctx.collection.entries()[0]
    assert entry.usable is False
    assert "无筛选条件" in entry.label()

    s8 = _categories(window, qapp)
    assert "无筛选条件" in s8.collection_list.item(0).text()


# ---------------------------------------------------------------------------
# 关键词检索就在当前条件里
# ---------------------------------------------------------------------------

def test_关键词搜索就在当前那排chips里搜(window, qapp) -> None:
    """修前这里是 `search_text(query)`：chips 写着「分类 = 命中卷」，返回的却是别的分类的文档。

    现在走 `search_in(self._query, …)`。判据取"另一个分类里同名文档**不出现**"，
    不取"出现的条数" —— 条数会被"两边都搜到了"和"根本没搜"两种坏法同时满足。
    """
    ctx = window.ctx
    cat_in, cat_out = _cat(ctx, "命中卷"), _cat(ctx, "别卷")
    inside = _seed(ctx, 2, prefix="合同甲")
    outside = _seed(ctx, 2, prefix="合同乙")
    ctx.catalog.link_categories(inside, cat_in)
    ctx.catalog.link_categories(outside, cat_out)

    page = _library(window, qapp)
    page.filter_bar.set_field("category_ids", [cat_in])
    page.search_input.setText("合同")
    page.search_btn.click()
    _settle(qapp)
    assert set(_doc_ids(page)) == set(inside), f"带着「分类 = 命中卷」搜出了别的分类的文档"
    assert "分类 = 命中卷" in _chip_texts(page.filter_bar), "搜完了，屏幕上那排条件却不在了"


def test_语义搜索明说自己不看这排条件(window, qapp, monkeypatch) -> None:
    """语义通道按向量近邻取 top_k，`DocFilter` 插不进去 —— 那就必须**说出来**。

    不说出来的后果与 `search_text` 那一例同一类：**ISSUES I11**「界面不许伪装」。
    引擎在这里被换成一个固定回表（测试机不装模型，与 `test_semantic_search_ui` 同一处置），
    断言只认状态栏那一句有没有把"不看条件"写上去。
    """
    cat_id = _cat(window.ctx, "语义卷")
    ids = _seed(window.ctx, 2, prefix="语义")
    monkeypatch.setattr(window.ctx.semantic_search, "search",
                        lambda text, top_k=50: [(i, 1, 0.9) for i in ids], raising=False)
    page = _library(window, qapp)
    page.filter_bar.set_field("category_ids", [cat_id])
    page.semantic_toggle.setChecked(True)
    page.search_input.setText("随便")
    page.search_btn.click()
    _settle(qapp)
    assert "语义通道不看上面那排筛选条件" in page.status_label.text()


# ---------------------------------------------------------------------------
# S8 那一栏的接线
# ---------------------------------------------------------------------------

def test_双击一行S8把外壳切到S1并灌回条件(window, qapp, answers) -> None:
    """外壳这条路由 `play_requested` 信号承载，S8 不认识 S1，S1 也不认识 S8。

    （与 `open_in_reader` 同一做法。）断言落在三格读数上：当前屏、chips 里那份 dict、
    和「来自集合「X」」那句出处 —— 少任何一格，回放就是"看着像过去了其实没过去"。
    """
    cat_id = _cat(window.ctx, "路由卷")
    _seed(window.ctx, 2, prefix="路由")
    page = _library(window, qapp)
    page.filter_bar.set_field("category_ids", [cat_id])
    _save_current(page, qapp, answers, "路由")

    s8 = _categories(window, qapp)
    assert s8.collection_list.count() == 1
    s8.collection_list.itemDoubleClicked.emit(s8.collection_list.item(0))
    _settle(qapp)

    assert window.current_item().page_id == "library"
    assert window.stack.currentWidget() is window._pages["library"]
    assert page.filter_bar.query() == {"category_ids": [cat_id]}
    assert page.filter_bar.source_label.text() == "来自集合「路由」"


def test_S8那一行读的是行上那条集合而不是第几行(window, qapp, answers) -> None:
    """上屏那句是「名字 · 命中 N」，名字与数都来自后端（`CollectionEntry.label()`，**ISSUES I60**）。

    句柄必须是行上的 `CollectionEntry`：三颗按钮都读"当前那一行"，而行号在"列表刚重查过"
    那一刻会错位 —— 拿 `UserRole` 里那条的话，改名与删除动的就是被点名的那条。
    """
    cat_id = _cat(window.ctx, "读数卷")
    ids = _seed(window.ctx, 3, prefix="读数")
    window.ctx.catalog.link_categories(ids[:2], cat_id)
    page = _library(window, qapp)
    page.filter_bar.set_field("category_ids", [cat_id])
    _save_current(page, qapp, answers, "读数")

    s8 = _categories(window, qapp)
    assert s8.collection_list.item(0).text() == "读数 · 命中 2"
    entry = s8.collection_list.item(0).data(QtCore.Qt.ItemDataRole.UserRole)
    assert entry.query.get("category_ids") == [cat_id]

    s8.collection_list.setCurrentRow(0)
    assert s8._current_collection("改名").id == entry.id


def test_改名与复制为新走的是服务层(window, qapp, answers) -> None:
    """「改名」不许顺手改条件，「复制为新」不许只复制名字不复制条件。

    复制那条特别要紧：`copy_as_new` 是走 `save` 的，所以旧版那种 `query={}` 的行复制出来
    照样被拒 —— 这里用一条**有条件**的集合验它真的把条件带上了。
    """
    cat_id = _cat(window.ctx, "复制卷")
    _seed(window.ctx, 2, prefix="复制")
    page = _library(window, qapp)
    page.filter_bar.set_field("category_ids", [cat_id])
    _save_current(page, qapp, answers, "原名")

    s8 = _categories(window, qapp)
    s8.collection_list.setCurrentRow(0)
    answers["queue"] = ["新名字"]
    s8.rename_coll_btn.click()
    _settle(qapp)
    assert [e.name for e in window.ctx.collection.entries()] == ["新名字"]

    s8.collection_list.setCurrentRow(0)
    answers["queue"] = ["副本"]
    s8.copy_coll_btn.click()
    _settle(qapp)
    entries = window.ctx.collection.entries()
    assert [e.name for e in entries] == ["副本", "新名字"]        # 仓储层按名字序，这里逐字对上
    assert all(e.query.get("category_ids") == [cat_id] for e in entries), "复制丢了条件"


def test_添加条件菜单每展开一次才重取条件表(window, qapp, choose) -> None:
    """菜单接在 `aboutToShow` 上，而不是构造时填一次。

    填一次的话 `_fill` 里那句"这张表此刻有哪些条"就固化了。这条同时钉住 `_on_menu_pick`
    认的是 `setData` 里的字段名而不是标题（与 `ui/catalog_links.py` 同一条约定）：
    菜单句改成别的字，选择照样有效。
    """
    cat_id = _cat(window.ctx, "菜单卷")
    page = _library(window, qapp)
    menu = page.filter_bar.add_btn.menu()
    assert menu.actions() == [], "菜单在构造时就填满了 —— `aboutToShow` 那一条没接上"
    menu.aboutToShow.emit()
    assert [a.data() for a in menu.actions()] == [c.field for c in CONDITIONS]

    choose["label"] = "菜单卷"
    _pick_menu_field(page.filter_bar.add_btn, "category_ids")
    _settle(qapp)
    assert page.filter_bar.query().get("category_ids") == [cat_id]
    assert _chip_texts(page.filter_bar) == ["分类 = 菜单卷"]


# ---------------------------------------------------------------------------
# 分档算术（为什么 chips 与那四颗按钮是两行而不是一行）
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("width", [1280, 1024], ids=["默认档", "地板档"])
def test_筛选条拆两行的算术在两个宽度档都成立(window, qapp, width) -> None:
    """线框 §I78-yi 原本把 chips 与按钮画在**同一行**；这一条把"拆成两行"的理由变成可判定的。

    判据不写魔法数：**chips 那条拉伸项的宽度不许小于同一行那颗固定按钮** ——
    一旦有人把它并回一行，中栏 463px 里四颗按钮的 `minimumSizeHint` 吃掉约 390px，
    chips 只剩 49px（= 一枚都放不下，正是线框那格算术的失败形状），本条当场红。
    地板档（1024）按 D-040 收起左右两栏、中栏变宽，所以两档都过才算"降级没吃掉筛选条"。
    """
    window.resize(width, 800)
    _settle(qapp)
    page = _library(window, qapp)
    page.filter_bar.set_field("category_ids", [_cat(window.ctx, f"算术{width}")])
    _settle(qapp)
    bar = page.filter_bar

    for btn in (bar.add_btn, bar.clear_btn, bar.save_btn, bar.overwrite_btn):
        assert btn.width() >= btn.minimumSizeHint().width(), (
            f"{width} 档按钮被裁切：{btn.text()} 只有 {btn.width()}px")
    assert bar.chip_scroll.width() >= bar.add_btn.width(), (
        f"{width} 档 chips 被挤得比一颗按钮还窄："
        f"{bar.chip_scroll.width()}px vs {bar.add_btn.width()}px")
