"""S1 中栏那一列是**一批一批取**的（销账 **ISSUES I51**）。

修前的形状（2026-10-18 实测，`.probe_work/i51_1018/before_8000.json`）：
`documents.list(limit=1000)` 一次灌满表格，8,000 份的库里**看不见 7,000 份**，
状态栏那句 `f"共 {len(docs)} 份文档"` 把"没显示"报成了"不存在"（写着「共 1000 份文档」），
而每一行的分类各调一次 `categories_of` ⇒ 1,000 行 = **1,000 条 SQL**。×10 档 8 万份时
看不见的是 79,000 份。

这一组断言因此全部钉**数字与可达性**，不钉文案也不钉标志位：
① 首屏的行数是一批而不是全库；② 那一行同时给出「全库 N」与「已有 M」两个数；
③ 真的把滚动条推到底能补上下一批，一路推到库尾时**不重不漏**（顺序与仓储的
   `SORTS["name"]` 逐行相同）；④ 一次浏览会话只把全库数**一遍**（每批重数 = O(行数²)）；
⑤ 分类浏览吃同一套分页且只出这一类；
⑥ 一批行的分类是**一条**查询；⑦ 查询命中那张表滚到底不许长出与本次查询无关的库里的行；
⑧ 视口比一批还高时第一批就补到能滚（否则滚动条没有量程，永远滚不动也永远不补）。

夹具三条规矩照常（offscreen、独立数据根、真 sqlite3 —— **D-012**）。
库里的文档全是现造的假名字，真实语料一条不进测试（**ISSUES I64**）。
"""
from __future__ import annotations

import pytest
from PySide6 import QtCore

from pdfarchiver.db.models import Document
from pdfarchiver.db.repositories.documents import DocFilter
from pdfarchiver.fs.identity import identity_key
from pdfarchiver.search.service import DEFAULT_PAGE_SIZE
from pdfarchiver.services.bootstrap import AppContext
from tests.conftest import settle as _settle

_TOTAL = DEFAULT_PAGE_SIZE * 2 + 30   # 130：跨过两批，又不至于让单测跑几十秒
_FILL_TOTAL = 200                     # 视口那一档要用：库尾必须比"填满视口"更远，才测得出补批停在哪儿
_ROW_HEIGHT = 30                      # 实测行高（`test_ui_tier` 量过：统一行高，D-040）


def _name(n: int) -> str:
    """名字序与插入序**故意不同**（乘一个与 10^6 互质的数再取模）。

    如果分页其实没排序（按插入序取批），③ 那条"逐行等于仓储名字序"就会红 ——
    两者同序时任何错位都看不出来。取模的底数比任何夹具的份数都大，`n` 与名字因此一对一
    （`documents.path_key` 上有唯一索引，重名会叫后一份把前一份覆盖掉）。
    """
    return f"合同{(n * 7919) % 1_000_000:06d}号.pdf"


def _seed(ctx: AppContext, count: int = _TOTAL) -> list[int]:
    """灌 count 份文档，返回它们的 id。"""
    ids: list[int] = []
    for n in range(count):
        name = _name(n)
        path = f"D:\\用户资料\\2026 年度合同与结算凭证归档\\{name}"
        row = ctx.documents.upsert(Document(
            path=path, path_key=identity_key(path), name=name,
            size_bytes=1024 * 1024 + n, mtime_ns=1_760_000_000_000_000_000,
            sha256=f"{n:064x}", text_status="done", fts_status="done"))
        ids.append(row.id)
    return ids


def _library(window, qapp):
    """切到 S1、重查一遍，返回页面对象（已经在当前页时 `reload()` 必须显式调）。"""
    window._select_by_page_id("library")
    _settle(qapp)
    page = window._pages["library"]
    page.reload()
    _settle(qapp)
    return page


def _table_ids(page) -> list[int]:
    return [page.doc_table.item(r, 0).data(QtCore.Qt.ItemDataRole.UserRole)
            for r in range(page.doc_table.rowCount())]


def _push_to_bottom(page, qapp) -> None:
    """真的动滚动条，不调私有方法 —— 要验的就是那条接线在不在。"""
    bar = page.doc_table.verticalScrollBar()
    bar.setValue(bar.maximum())
    _settle(qapp)


def _repo_ids(ctx: AppContext, category_id: int | None = None) -> list[int]:
    """仓储按唯一排序口径（`SORTS["name"]`）给出的那串 id —— 表格里那列的对照物。"""
    flt = DocFilter(include_missing=True,
                    category_ids=() if category_id is None else (category_id,))
    return [d.id for d in ctx.documents.list_sorted(
        flt, sort="name", limit=ctx.documents.count(), offset=0)]


# ---------------------------------------------------------------------------
# ① 首屏：一批而不是一整库，两个数都得在
# ---------------------------------------------------------------------------

def test_首屏只取一批而不是整库(window, ctx, qapp) -> None:
    """坏法注入实测：把 `_start_browse()` 改成 `while not self._browse_exhausted` 一次取到
    库尾 ⇒ 本条红在读数 130。"""
    _seed(ctx)
    page = _library(window, qapp)

    assert page.doc_table.rowCount() == DEFAULT_PAGE_SIZE, (
        f"首屏灌了 {page.doc_table.rowCount()} 行，一批应是 {DEFAULT_PAGE_SIZE} 行 —— "
        "库里那些行不该一次全进表格（ISSUES I51）")


def test_库比一批大时不许把已载入说成全部(window, ctx, qapp) -> None:
    """修前那行写的就是「共 1000 份文档」，而库里有 8,000 份 —— 这一条钉的就是那个谎。

    两个数都必须来自后端字段（`matching_documents` 与 `offset + 本页行数`），
    界面不许自己 `len(...)` 拼句子（**ISSUES I60** 同一条纪律）。
    """
    _seed(ctx)
    page = _library(window, qapp)
    line = page.status_label.text()

    assert f"共 {_TOTAL} 份文档" in line, f"那一行没报出全库的数：{line}"
    assert f"已有 {DEFAULT_PAGE_SIZE} 行" in line, f"那一行没说清表格里只有一批：{line}"


def test_库里不足一批时那一行不多报一行(window, ctx, qapp) -> None:
    """小库（3 份）不该出现「滚动到底继续取下一批」—— 根本没有下一批。"""
    _seed(ctx, 3)
    page = _library(window, qapp)

    assert page.status_label.text() == "共 3 份文档｜表格里 3 行"


# ---------------------------------------------------------------------------
# ② 滚动 → 补批 → 一路到库尾，不重不漏
# ---------------------------------------------------------------------------

def test_把滚动条推到底真的会补一批(window, ctx, qapp) -> None:
    """这条钉**接线**：槽没连上时推滚动条不会有任何反应（控件在场 ≠ 行为在场）。"""
    _seed(ctx)
    page = _library(window, qapp)
    before = page.doc_table.rowCount()

    _push_to_bottom(page, qapp)

    assert page.doc_table.rowCount() == before + DEFAULT_PAGE_SIZE, (
        f"滚到底之后从 {before} 行变成 {page.doc_table.rowCount()} 行 —— "
        "补批没接在滚动条上，或者一次补了不止一批")


def test_一路滚到底能把整库取完而且不重不漏(window, ctx, qapp) -> None:
    """§S1 硬条件「翻页不重不漏」在分页方案下的机器版本。

    三种坏法各红一头：① `offset` 传成定值（永远同一批）⇒ 行数不再增长，红在取不完；
    ② `offset` 少算一行 ⇒ 出现重复 id，红在"重"；
    ③ 取数不排序而对照按名字序 ⇒ 红在"逐行不同"。
    """
    _seed(ctx)
    page = _library(window, qapp)

    pushes = 0
    while not page._browse_exhausted:
        _push_to_bottom(page, qapp)
        pushes += 1
        assert pushes <= _TOTAL + 5, "补批没有推进 —— 滚一次取不完就是死循环"

    assert page.doc_table.rowCount() == _TOTAL, (
        f"滚到库尾只有 {page.doc_table.rowCount()} 行，库里 {_TOTAL} 份 —— 有些文档永远看不见")
    ids = _table_ids(page)
    assert len(ids) == len(set(ids)), "表格里出现了重复的文档行"
    assert ids == _repo_ids(ctx), "表格那列与仓储的名字序逐行不同 —— 批与批之间错位或漏行"
    assert page.status_label.text() == f"共 {_TOTAL} 份文档｜表格里 {_TOTAL} 行"


# ---------------------------------------------------------------------------
# ③ 一次浏览会话只数一遍全库
# ---------------------------------------------------------------------------

def test_补批时不许每批重数一遍全库(window, ctx, qapp) -> None:
    """`count_matching` 是 `SELECT count(*) … WHERE missing_since IS NULL`，而
    `ix_documents_missing` 是**部分索引**（只收非 NULL 的行），数 NULL 用不上它 ⇒ 一句扫全表。
    一批扫一遍、滚完整库扫 库行数/50 遍 = O(行数²)（AGENTS.md「禁止 O(n²)」）。

    坏法注入实测：把 `_load_more()` 里那个 `total=self._browse_total or None` 去掉 ⇒
    本条红在 `数了 3 遍`（130 份 = 3 批）。
    """
    _seed(ctx)
    page = _library(window, qapp)

    counts = {"n": 0}
    original = ctx.documents.count_matching

    def counted(f):  # noqa: ANN001 - 只是转发计数，签名跟着被包的那条走
        counts["n"] += 1
        return original(f)

    ctx.documents.count_matching = counted            # type: ignore[method-assign]
    try:
        page._load_all_documents()                    # 重新起一次浏览会话：第一批在这里数
        pushes = 0
        while not page._browse_exhausted:
            _push_to_bottom(page, qapp)
            pushes += 1
            assert pushes <= _TOTAL + 5, "补批没有推进"
    finally:
        ctx.documents.count_matching = original        # type: ignore[method-assign]

    assert page.doc_table.rowCount() == _TOTAL, "前提：整库都取完了"
    assert counts["n"] == 1, (
        f"这一次浏览会话把全库数了 {counts['n']} 遍 —— 每一遍都是一次全表扫描")


# ---------------------------------------------------------------------------
# ⑤ 分类浏览吃同一套分页
# ---------------------------------------------------------------------------
def test_点分类之后只出这一类而且同样是一批(window, ctx, qapp) -> None:
    """分类模式与全库模式必须同一条取数口径（同一个 `browse_documents`）——
    否则「点分类看到的」与「搜索时筛同一分类看到的」又会各说各话。"""
    ids = _seed(ctx)
    picked = ids[:DEFAULT_PAGE_SIZE + 10]      # 60 份：超过一批，分类里也得分批
    category = ctx.catalog.add_category("报销")
    for doc_id in picked:
        ctx.catalog.link_category(doc_id, category.id)

    page = _library(window, qapp)
    page._load_documents_by_category(category.id)
    _settle(qapp)

    assert page.doc_table.rowCount() == DEFAULT_PAGE_SIZE, (
        f"分类下 {len(picked)} 份，首屏却有 {page.doc_table.rowCount()} 行 —— 分类模式没走分页")
    assert set(_table_ids(page)) <= set(picked), "分类浏览里混进了不属于这一类的文档"
    assert f"共 {len(picked)} 份文档" in page.status_label.text()

    pushes = 0
    while not page._browse_exhausted:
        _push_to_bottom(page, qapp)
        pushes += 1
        assert pushes <= len(picked) + 5, "分类模式的补批没有推进"
    assert sorted(_table_ids(page)) == sorted(picked)
    assert _table_ids(page) == _repo_ids(ctx, category_id=category.id)


# ---------------------------------------------------------------------------
# ⑥ 一批行的分类是一条查询，显示的名字与逐行取时一字不差
# ---------------------------------------------------------------------------

def test_一批行的分类只走一条查询(window, ctx, qapp) -> None:
    """修前逐行 `categories_of`：1,000 行 = 1,000 条 SQL（实测读数）。

    坏法注入实测：把 `_write_rows()` 里那次 `categories_by_doc_ids` 换回逐行取 ⇒
    本条红在 `per_row=50 / batched=0`。
    """
    _seed(ctx, DEFAULT_PAGE_SIZE)
    page = _library(window, qapp)

    counted = {"per_row": 0, "batched": 0}
    original_of = ctx.catalog.categories_of
    original_batch = ctx.catalog.categories_by_doc_ids

    def counted_of(doc_id: int):
        counted["per_row"] += 1
        return original_of(doc_id)

    def counted_batch(doc_ids):
        counted["batched"] += 1
        return original_batch(doc_ids)

    ctx.catalog.categories_of = counted_of               # type: ignore[method-assign]
    ctx.catalog.categories_by_doc_ids = counted_batch    # type: ignore[method-assign]
    try:
        page._load_all_documents()
        _settle(qapp)
    finally:
        ctx.catalog.categories_of = original_of          # type: ignore[method-assign]
        ctx.catalog.categories_by_doc_ids = original_batch  # type: ignore[method-assign]

    assert page.doc_table.rowCount() == DEFAULT_PAGE_SIZE
    assert counted["per_row"] == 0, f"填一批却逐行取了 {counted['per_row']} 次分类"
    assert counted["batched"] == 1, f"一批分类取了 {counted['batched']} 次，应该是一条查询"


def test_分类那一列显示的仍是这几个名字(window, ctx, qapp) -> None:
    """改成整批取之后，「一行里有哪些分类名、按什么顺序」不许与逐行取时不同
    （两条 SQL 共用同一个 `ORDER BY c.name_path`）。"""
    ids = _seed(ctx, 3)
    category = ctx.catalog.add_category("合同")
    child = ctx.catalog.add_category("运输合同", parent_id=category.id)
    ctx.catalog.link_category(ids[0], child.id)
    ctx.catalog.link_category(ids[0], category.id)

    page = _library(window, qapp)
    row = next(r for r in range(page.doc_table.rowCount())
               if page.doc_table.item(r, 0).data(QtCore.Qt.ItemDataRole.UserRole) == ids[0])

    expected = ", ".join(c.name for c in ctx.catalog.categories_of(ids[0])[:3])
    assert page.doc_table.item(row, 4).text() == expected
    assert page.doc_table.item(row, 4).toolTip() == expected   # 截断了也要悬停读得回全文


# ---------------------------------------------------------------------------
# ⑦ 命中表不是浏览列表：滚到底不许补库里的行
# ---------------------------------------------------------------------------

def test_查询命中表滚到底不许长出库里的行(window, ctx, qapp) -> None:
    """命中表只有几行时没有滚动条，所以这条直接把滚动事件的载荷递给槽 ——
    要钉的是浏览态关掉时 `_on_scrolled` 确实不动，而不是"滚不动所以没测到"。
    """
    ids = _seed(ctx)
    page = _library(window, qapp)
    needle = _name(23)[: -len(".pdf")]
    page.search_input.setText(needle)
    page._do_search()
    _settle(qapp)
    hits = page.doc_table.rowCount()
    assert 0 < hits < DEFAULT_PAGE_SIZE, f"用例前提：命中该是几条，实测 {hits} 行"
    # 命中那一行必须真是这份文档（`setRowCount` 与 `setItem` 对不上时行数是涨了、内容却丢了）
    assert _table_ids(page) == [ids[23]], f"命中表里那几行不是刚才查的那份文档：{needle}"
    status_after_search = page.status_label.text()

    page._on_scrolled(0)
    _settle(qapp)

    assert page.doc_table.rowCount() == hits, (
        f"命中表从 {hits} 行变成 {page.doc_table.rowCount()} 行 —— 浏览态没关掉，"
        "库里的行被补到了命中底下（看着像命中，其实一条都没验过）")
    assert page.status_label.text() == status_after_search, "命中表的状态行被浏览态读数顶掉了"


# ---------------------------------------------------------------------------
# ⑧ 视口比一批还高时，第一批就得补到能滚
# ---------------------------------------------------------------------------

def test_视口装得下一批以上时自动补到能滚(window, ctx, qapp, monkeypatch) -> None:
    """没有这一步，用户看到的是"50 行 + 一根没有量程的滚动条"：滚不动 ⇒ 永远不再补。

    本机视口实测 606px（≈20 行），比一批还矮，所以这里把**视口高**这一个读数换成一块能显示
    80 行的屏 —— 走的是同一个 `_fill_viewport()`，接线（`_start_browse` 里那一次调用）也在这条
    的覆盖范围里：删掉那一次调用 ⇒ 本条红在 50 行。
    库取 200 份：比"填满这块屏"更远，才看得出补批是停在够滚那一处、而不是把整库灌进来。
    """
    _seed(ctx, _FILL_TOTAL)
    window._select_by_page_id("library")
    _settle(qapp)
    page = window._pages["library"]
    viewport_rows = 80
    monkeypatch.setattr(page.doc_table.viewport(), "height", lambda: _ROW_HEIGHT * viewport_rows)

    page._start_browse()
    _settle(qapp)

    assert page.doc_table.rowCount() > DEFAULT_PAGE_SIZE, (
        f"视口能显示 {viewport_rows} 行却只取了 {page.doc_table.rowCount()} 行（一批都没补）—— "
        "滚动条没有量程，用户滚不动也就永远补不上")
    assert page.doc_table.rowCount() >= viewport_rows, (
        f"只取了 {page.doc_table.rowCount()} 行，屏幕上的空位没被填到")
    assert page.doc_table.rowCount() < _FILL_TOTAL, "把整库灌进来了 —— 那不是补到能滚，那是回到修前"
    assert not page._browse_exhausted, "用例前提：这一档还没到库尾，补批是被视口顶出来的"


@pytest.mark.parametrize("count", [0, 1, DEFAULT_PAGE_SIZE, DEFAULT_PAGE_SIZE + 1])
def test_行数边界上表格不许多出库里没有的行(window, ctx, qapp, count) -> None:
    """四档（空库 / 一份 / 正好一批 / 刚过一批）读到的都该是 `min(已取, 全库)`。"""
    if count:
        _seed(ctx, count)
    page = _library(window, qapp)

    assert page.doc_table.rowCount() == min(count, DEFAULT_PAGE_SIZE)
    assert f"共 {count} 份文档" in page.status_label.text()
