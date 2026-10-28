"""S1「送去识别」选中多份时那块批次面板 —— **ISSUES I67** 乙（2026-10-19 勾「甲先乙后」）。

线框 `docs/wireframes/2026-10-19-round14-i67-i78.html` §I67-yi（2026-10-19 勾「甲先乙后」，
本轮落乙）画的是：表格里 Ctrl/Shift 选若干 → 那颗按钮变成「送去识别（选中 N 份）」→
按下去在表格底下**就地展开**一块面板，写清「该跑几份 / 不跑几份 / 每一类不跑的是哪几份 /
今日预算 / 代价」，再给「排队」「取消」。

这一组断言逐条对着 **ISSUES I67** 的三条销账判定与 §I67-yi 的硬条件写：
① 按下「排队」之后 `jobs` 里 `kind='ocr'` 的行数 **+N**，而 N 就是面板上那句「该跑 N 份」
   —— **预览与执行同源**（同一判据的两次读法，与归档预览那条 `plan()/submit()` 同形，**D-043**）；
② 每一类跳过理由都能在屏幕上**展开指到具体是哪几份**；
③ 预算不够 / 跑满时**在屏幕上看得见**，按「排队」原样回后端那句，不许静默。
另外四条是这块面板自己的形状：一份不弹面板（甲案那条老路不变）、换选中必须收起（不许对着
过期名单按排队）、算不出账与排队失败都要把后端原文上屏（**ISSUES I84** ③）、
面板展开时不许把页面顶过 D-039 的 1024 地板（**长文字的折行纪律**）。

夹具三条规矩照常（offscreen、独立数据根、真 sqlite3 —— **D-012**）。每条断言的坏法登记在
`tests/probes/p23_ocr_batch_injection.py`。
"""
from __future__ import annotations

import re
from pathlib import Path

from PySide6 import QtCore

from pdfarchiver.services.ocr_service import (PARTIAL_TAIL_TEXT, SKIP_BUDGET, SKIP_BUDGET_SHORT,
                                              SKIP_LABELS, SKIP_NO_VERDICT, SKIP_NOT_NEEDED)
from pdfarchiver.ui.main_window import MIN_WINDOW_HEIGHT, MIN_WINDOW_WIDTH, NAV_WIDTH
from pdfarchiver.ui.ocr_batch_panel import COLLAPSE_TEXT, EXPAND_TEXT
from pdfarchiver.ui.pages.library_page import OCR_BTN_TEXT
from tests.integration.ocr_doubles import _doc_id, _scanned, _textual
from tests.conftest import settle as _settle

#: 与 `test_ui_layout.AVAILABLE_WIDTH` 同一个算式（两个数都取自外壳本身，不在这里写死像素）。
AVAILABLE_WIDTH = MIN_WINDOW_WIDTH - NAV_WIDTH - 1


def _library(window, qapp):
    """切到 S1 并重查一遍，返回页面对象（与 `test_ocr_entry_ui.py` 同一取法）。"""
    window._select_by_page_id("library")
    _settle(qapp)
    page = window._pages["library"]
    page.reload()
    _settle(qapp)
    return page


def _queued(ctx) -> int:
    return ctx.jobs.counts_by_kind_state().get(("ocr", "queued"), 0)


def _row_of(page, doc_id) -> int:
    for row in range(page.doc_table.rowCount()):
        item = page.doc_table.item(row, 0)
        if item and item.data(QtCore.Qt.ItemDataRole.UserRole) == doc_id:
            return row
    raise AssertionError(f"表格里没有 id={doc_id} 这一行（共 {page.doc_table.rowCount()} 行）")


def _select(page, qapp, *doc_ids) -> None:
    """Ctrl 点几行的等效：先 `selectRow`（顺带把"当前行"摆好），再逐行 `Select|Rows` 加进去。

    最后一行自己证伪夹具 —— 选中态没真的落进表格时，下面所有断言都在数别的份数。
    """
    rows = [_row_of(page, d) for d in doc_ids]
    page.doc_table.selectRow(rows[0])
    model = page.doc_table.model()
    flags = (QtCore.QItemSelectionModel.SelectionFlag.Select
             | QtCore.QItemSelectionModel.SelectionFlag.Rows)
    for row in rows[1:]:
        page.doc_table.selectionModel().select(model.index(row, 0), flags)
    _settle(qapp)
    assert sorted(page._selected_doc_ids()) == sorted(doc_ids), (
        f"夹具没把这几行都选中：点名的是 {page._selected_doc_ids()}，要的是 {list(doc_ids)}")


def _unindexed(ctx, root, make_pdf, name: str = "没索引.pdf") -> int:
    """扫进库但**没索引**的一份 —— `SKIP_NO_VERDICT` 那一类的现场条件（没有可用的正文判定）。"""
    r = root("未索引")
    path = Path(make_pdf(f"未索引/{name}", pages=1, lines=["一句话正文内容测试用"]))
    ctx.scan.scan_root(r)
    return _doc_id(ctx, path)


def _count(text: str, pattern: str) -> int:
    hit = re.search(pattern, text)
    assert hit, f"屏幕上那句里没有「{pattern}」：{text}"
    return int(hit.group(1))


# ---------------------------------------------------------------------------
# 接线：几份才弹面板、按钮文案上写的就是点名的份数
# ---------------------------------------------------------------------------

def test_选中两份按下去展开面板而一条也不排(window, ctx, root, make_scanned_pdf, qapp) -> None:
    """乙案的第一条：**看账那一下不许有副作用**。面板是预览，排队是执行，两步分开。

    「不跑 0 份」与"面板上一行理由都不摆"是同一件事的两面：两例都是"没跳过的份"，
    多摆一行空的说明就是界面在替后端编一句话。
    """
    first = _scanned(ctx, root, make_scanned_pdf, name="合同一.pdf")
    second = _scanned(ctx, root, make_scanned_pdf, name="合同二.pdf")
    page = _library(window, qapp)
    _select(page, qapp, first, second)
    before = _queued(ctx)

    page.ocr_btn.click()
    _settle(qapp)

    assert page.ocr_panel.isVisible(), "选中两份按下去没展开面板（乙案的入口没接上）"
    assert _queued(ctx) == before, "只是看这份账，队列里却多了任务"
    summary = page.ocr_panel.summary_label.text()
    assert _count(summary, "点名 (\\d+) 份") == 2
    assert _count(summary, "该跑 (\\d+) 份") == 2
    assert _count(summary, "不跑 (\\d+) 份") == 0
    assert page.ocr_panel.reason_rows == [], f"没有跳过的份却摆了理由行：{summary}"


def test_只点名一份时不弹面板而是直接排队(window, ctx, root, make_scanned_pdf, qapp) -> None:
    """一份不需要看这份账 —— 甲案那条老路必须原样保留（分档判据是 `> 1`，不是 `>= 1`）。

    这条同时钉住"两套回执格式"：单份那一句仍然逐字是 `request.describe()｜budget.describe()`。
    """
    doc_id = _scanned(ctx, root, make_scanned_pdf)
    page = _library(window, qapp)
    _select(page, qapp, doc_id)
    before = _queued(ctx)

    page.ocr_btn.click()
    _settle(qapp)

    assert not page.ocr_panel.isVisible(), "一份也弹面板：多一次点击才能干活，是倒退"
    assert _queued(ctx) == before + 1, f"单份那条路被乙案改断了（队列 {before} → {_queued(ctx)}）"
    line = page.status_label.text()
    assert "点名 1 份｜该跑 1 份｜新增任务 1 条" in line, line
    assert ctx.ocr.budget.describe() in line, line


def test_按钮文案上写的就是点名的份数(window, ctx, root, make_scanned_pdf, qapp) -> None:
    """§I67-yi 那一句「按下去之前就知道自己点了几份」的落点：份数在按钮上，不用点开才看见。"""
    ids = [_scanned(ctx, root, make_scanned_pdf, name=f"批次{i}.pdf") for i in (1, 2, 3)]
    page = _library(window, qapp)

    _select(page, qapp, ids[0])
    assert page.ocr_btn.text() == OCR_BTN_TEXT, f"一份时按钮该只有基础文案：{page.ocr_btn.text()}"

    _select(page, qapp, *ids)
    assert page.ocr_btn.text() == f"{OCR_BTN_TEXT}（选中 3 份）", page.ocr_btn.text()

    _select(page, qapp, ids[1])
    assert page.ocr_btn.text() == OCR_BTN_TEXT, f"退回一份还写着 3 份：{page.ocr_btn.text()}"


# ---------------------------------------------------------------------------
# 三句读数：屏幕上那三行逐字来自服务层，界面不重算
# ---------------------------------------------------------------------------

def test_面板那三句逐字是服务层算出来的账(window, ctx, root, make_scanned_pdf, qapp,
                                          monkeypatch) -> None:
    """**ISSUES I60** 在面板上的版本：份数、代价、预算三行的格式化只有后端一个出口。

    顺带钉住"递下去的就是表格里点名的那几份"（不是当前行、也不是上一批）。
    """
    ids = [_scanned(ctx, root, make_scanned_pdf, name=f"扫描件{i}.pdf") for i in (1, 2)]
    page = _library(window, qapp)
    _select(page, qapp, *ids)

    seen: dict = {}
    original = ctx.ocr.plan_ocr

    def spy(doc_ids, **kw):
        plan = original(doc_ids, **kw)
        seen["ids"], seen["plan"] = list(doc_ids), plan
        return plan

    monkeypatch.setattr(ctx.ocr, "plan_ocr", spy)
    page.ocr_btn.click()
    _settle(qapp)

    panel = page.ocr_panel
    assert seen["ids"] == sorted(ids), f"展开面板时递下去的不是点名那几份：{seen.get('ids')}"
    assert panel.summary_label.text() == seen["plan"].describe(), (
        f"那句不是 `plan.describe()` 原样：{panel.summary_label.text()!r}")
    assert panel.cost_label.text() == seen["plan"].cost_line(), panel.cost_label.text()
    assert panel.budget_label.text() == (
        f"{ctx.ocr.budget.describe()}｜{seen['plan'].budget_note()}"), panel.budget_label.text()


def test_代价那句上屏的是这一批的主记录页数(window, ctx, root, make_scanned_pdf, qapp) -> None:
    """§I67-yi 的「按页算的代价」：两份各 2 页 = 4 页。界面不数页，只把后端那句摆上去。"""
    ids = [_scanned(ctx, root, make_scanned_pdf, name=f"扫描件{i}.pdf") for i in (1, 2)]
    page = _library(window, qapp)
    _select(page, qapp, *ids)

    page.ocr_btn.click()
    _settle(qapp)

    assert "共 4 页" in page.ocr_panel.cost_label.text(), page.ocr_panel.cost_label.text()


# ---------------------------------------------------------------------------
# ① 预览与执行同源：面板说的「该跑 N 份」就是按下排队之后的那个 N
# ---------------------------------------------------------------------------

def test_面板说的该跑份数与按下排队后的新增条数是同一个数(window, ctx, root,
                                              make_scanned_pdf, make_pdf, qapp) -> None:
    """**I67 销账判定①** + §I67-yi 第三条硬条件。

    样本刻意选**三种不同的下场**（一份该跑、一份判过不需要、一份还没索引），所以
    「该跑 1 份」与「点名 3 份」必然不同数：面板要是自己数 `len(ids)` 当"该跑"，
    或者执行那一路偷偷换了判据（例如 `force=True`），屏幕上就会出现两个数 —— 本条当场红。
    """
    scanned = _scanned(ctx, root, make_scanned_pdf, name="合同一.pdf")
    textual = _textual(ctx, root, make_pdf, name="文字版.pdf")
    unindexed = _unindexed(ctx, root, make_pdf)
    page = _library(window, qapp)
    _select(page, qapp, scanned, textual, unindexed)
    before = _queued(ctx)

    page.ocr_btn.click()
    _settle(qapp)
    planned = _count(page.ocr_panel.summary_label.text(), "该跑 (\\d+) 份")
    assert planned == 1, page.ocr_panel.summary_label.text()

    page.ocr_panel.enqueue_btn.click()
    _settle(qapp)

    assert _queued(ctx) == before + planned, (
        f"面板说该跑 {planned} 份，队列里却从 {before} 条变成 {_queued(ctx)} 条")
    line = page.status_label.text()
    assert _count(line, "该跑 (\\d+) 份") == planned, f"预览与执行报了两个数：{line}"
    assert not page.ocr_panel.isVisible(), "排队之后面板还挂着"


def test_重复排队同一批时新增0条而屏幕上看得见0条(window, ctx, root, make_scanned_pdf, qapp) -> None:
    """去重在服务层（`enqueue_many`），面板不许绕过它 —— 更要紧的是屏幕上看得见那个 0，
    否则用户只会以为"第二次按了没反应"。与甲案同一条形状，这里是它的批量版本。"""
    ids = [_scanned(ctx, root, make_scanned_pdf, name=f"扫描件{i}.pdf") for i in (1, 2)]
    page = _library(window, qapp)
    _select(page, qapp, *ids)

    page.ocr_btn.click()
    _settle(qapp)
    page.ocr_panel.enqueue_btn.click()
    _settle(qapp)
    queued = _queued(ctx)

    page.ocr_btn.click()
    _settle(qapp)
    page.ocr_panel.enqueue_btn.click()
    _settle(qapp)

    assert _queued(ctx) == queued, "同一批被排了两次 —— 去重被面板绕过了"
    line = page.status_label.text()
    assert "点名 2 份｜该跑 2 份｜新增任务 0 条" in line, line
    assert page.status_label.objectName() == "danger", f"一条没进队列却是常态色：{line}"


# ---------------------------------------------------------------------------
# ② 每一类跳过理由都指得到是哪几份
# ---------------------------------------------------------------------------

def test_两类跳过理由各占一行而展开指得到具体份名(window, ctx, root, make_scanned_pdf,
                                                 make_pdf, qapp) -> None:
    """**I67 销账判定②**（乙案要补的就是这半）：理由不能只是一句"跳过了 2 份"。

    一行的标题逐字是 `SKIP_LABELS` 里那句 + 这一类的份数；点「展开」之后屏幕上必须出现
    那一份的**文件名**，再点一次收回（那一行不许常驻，与 **ISSUES I84** 那条「可见但不许常驻」同理）。
    """
    scanned = _scanned(ctx, root, make_scanned_pdf, name="合同一.pdf")
    textual = _textual(ctx, root, make_pdf, name="文字版.pdf")
    unindexed = _unindexed(ctx, root, make_pdf)
    page = _library(window, qapp)
    _select(page, qapp, scanned, textual, unindexed)

    page.ocr_btn.click()
    _settle(qapp)

    rows = page.ocr_panel.reason_rows
    by_title = {row.title_label.text(): row for row in rows}
    assert set(by_title) == {f"{SKIP_LABELS[SKIP_NOT_NEEDED]}（1 份）",
                             f"{SKIP_LABELS[SKIP_NO_VERDICT]}（1 份）"}, f"理由行不对：{list(by_title)}"
    assert all(row.toggle_btn.text() == EXPAND_TEXT for row in rows), "展开钮默认文案不对"
    assert all(not row.expanded for row in rows), "没点就先占着屏幕"

    need = {SKIP_NOT_NEEDED: "文字版.pdf", SKIP_NO_VERDICT: "没索引.pdf"}
    for reason, name in need.items():
        row = by_title[f"{SKIP_LABELS[reason]}（1 份）"]
        row.toggle_btn.click()
        _settle(qapp)
        assert row.expanded, f"{SKIP_LABELS[reason]} 点了展开而清单没出来"
        assert row.toggle_btn.text() == COLLAPSE_TEXT
        assert name in row.detail_label.text(), (
            f"这一类理由指不到是哪一份：{row.detail_label.text()!r}")

    rows[0].toggle_btn.click()
    _settle(qapp)
    assert not rows[0].expanded, "再点一次没收起"
    assert rows[0].toggle_btn.text() == EXPAND_TEXT


def test_预算跑满时这一类理由也指得到是哪几份(window, ctx, root, make_scanned_pdf, qapp) -> None:
    """判定②对 `SKIP_BUDGET` 同样成立：闸门落下时要知道**被闸门挡住的是哪几份**，
    不然明天该补跑谁只能靠记忆。"""
    ids = [_scanned(ctx, root, make_scanned_pdf, name=f"扫描件{i}.pdf") for i in (1, 2)]
    ctx.ocr.budget.consume(ctx.ocr.budget.pages_per_day)
    page = _library(window, qapp)
    _select(page, qapp, *ids)

    page.ocr_btn.click()
    _settle(qapp)

    row = page.ocr_panel.reason_rows[0]
    assert row.title_label.text() == f"{SKIP_LABELS[SKIP_BUDGET]}（2 份）", row.title_label.text()
    row.toggle_btn.click()
    _settle(qapp)
    assert "扫描件1.pdf" in row.detail_label.text() and "扫描件2.pdf" in row.detail_label.text(), (
        row.detail_label.text())


# ---------------------------------------------------------------------------
# ③ 预算：不够与跑满都必须先在屏幕上说清
# ---------------------------------------------------------------------------

def test_预算跑满时面板先说明天恢复而按下排队原样回预算那句(window, ctx, root,
                                                        make_scanned_pdf, qapp) -> None:
    """**I67 销账判定③**：预算是资源闸门，`force` 也不绕它。

    两处都要看得见：展开面板时那一句先说明白（不用按下去才知道），按下「排队」之后屏幕上
    仍是后端那句 `SKIP_LABELS[SKIP_BUDGET]`，且**一条也没进队列**、染红。
    """
    ids = [_scanned(ctx, root, make_scanned_pdf, name=f"扫描件{i}.pdf") for i in (1, 2)]
    ctx.ocr.budget.consume(ctx.ocr.budget.pages_per_day)
    page = _library(window, qapp)
    _select(page, qapp, *ids)
    before = _queued(ctx)

    page.ocr_btn.click()
    _settle(qapp)
    assert "已经用满" in page.ocr_panel.budget_label.text(), page.ocr_panel.budget_label.text()
    assert page.ocr_panel.cost_label.text() == "这一批没有该跑的份，不烧页"

    page.ocr_panel.enqueue_btn.click()
    _settle(qapp)

    assert _queued(ctx) == before, "预算跑满还排进了队列 —— 闸门被界面绕过了"
    line = page.status_label.text()
    assert SKIP_LABELS[SKIP_BUDGET] in line, f"预算跑满却没上屏：{line}"
    assert "新增任务 0 条" in line, line
    assert page.status_label.objectName() == "danger", line
    assert "剩 0 页" in line, line


def test_预算不够跑完这一批时那句在面板上看得见(window, ctx, root, make_scanned_pdf,
                                              qapp, monkeypatch) -> None:
    """闸门还没落下、但**今天跑不完**这一档（轮三十六 甲改口径之后的两句话都要在屏上）。

    这一档分两种，措辞不同、动作也不同，合成一句就等于抹掉一种：
    ① 一份装不下余量 —— 它照样排进去，跑到余量用完停下记 `partial`（**ISSUES I19**），
       面板必须说"跑不到底 + 剩余页明日回到待办"，否则用户以为按完今天就能全变 done；
    ② 排在它后面的那些**整份**留到明天 —— 归进 `SKIP_BUDGET_SHORT` 并逐份列出来
       （`SKIP_BUDGET` 是"一页都不剩"，那句是"别按了"，两者不是一个动作）。
    """
    ids = [_scanned(ctx, root, make_scanned_pdf, name=f"扫描件{i}.pdf") for i in (1, 2)]
    monkeypatch.setattr(ctx.ocr.budget, "pages_per_day", 3)   # 这批要 4 页，今天只剩 3
    page = _library(window, qapp)
    _select(page, qapp, *ids)
    before = _queued(ctx)

    page.ocr_btn.click()
    _settle(qapp)
    note = page.ocr_panel.budget_label.text()
    assert "今天跑不到底" in note, note
    assert PARTIAL_TAIL_TEXT in note, note

    page.ocr_panel.enqueue_btn.click()
    _settle(qapp)

    assert _queued(ctx) == before + 2, "预算还够排就该排进去，「跑不完」不是「不排」"
    assert "新增任务 2 条" in page.status_label.text(), page.status_label.text()
    assert page.status_label.objectName() != "danger"


def test_预算只够一部分时排得下的照排其余逐份列出来(window, ctx, root, make_scanned_pdf,
                                                      qapp, monkeypatch) -> None:
    """**轮三十六 甲**：预算只剩 3 页、这一批 3 份各 2 页 —— 只排预算内的，排不下的
    **逐份列出来**（分类名 + 点开指到具体哪几份），而不是像旧行为那样整批照排让 worker 空跑。

    这条钉的是「只排预算内的」这半边：第一份 2 页、第二份装 1 页（跑到余量用完）、
    第三份一页都不剩 ⇒ 进 `SKIP_BUDGET_SHORT`。
    """
    ids = [_scanned(ctx, root, make_scanned_pdf, name=f"扫描件{i}.pdf") for i in (1, 2, 3)]
    monkeypatch.setattr(ctx.ocr.budget, "pages_per_day", 3)
    page = _library(window, qapp)
    _select(page, qapp, *ids)
    before = _queued(ctx)

    page.ocr_btn.click()
    _settle(qapp)
    rows = {r.item.reason: r for r in page.ocr_panel.reason_rows}
    assert SKIP_BUDGET_SHORT in rows, f"排不下的份没单列一类：{list(rows)}"
    row = rows[SKIP_BUDGET_SHORT]
    assert row.title_label.text() == f"{SKIP_LABELS[SKIP_BUDGET_SHORT]}（1 份）", row.title_label.text()
    row.toggle_btn.click()
    _settle(qapp)
    assert "扫描件3.pdf" in row.detail_label.text(), row.detail_label.text()

    page.ocr_panel.enqueue_btn.click()
    _settle(qapp)

    assert _queued(ctx) == before + 2, (
        f"预算内的两份该排进去（第 2 份跑到余量用完），实际新增 {_queued(ctx) - before} 条")
    assert SKIP_LABELS[SKIP_BUDGET_SHORT] in page.status_label.text(), page.status_label.text()
    assert "新增任务 2 条" in page.status_label.text(), page.status_label.text()


# ---------------------------------------------------------------------------
# 面板的生命周期：换选中收起、取消收起、算不出账不许展开空面板
# ---------------------------------------------------------------------------

def test_换选中时面板收起不留过期名单(window, ctx, root, make_scanned_pdf, qapp) -> None:
    """那份账算的是**刚才那一批**。选中态一变而面板还挂着，用户按下「排队」排的就是
    一份他再也没在屏幕上确认过的名单 —— 与 §I78-jia 那条"每次展开重取清单"同一条纪律。"""
    batch = [_scanned(ctx, root, make_scanned_pdf, name=f"扫描件{i}.pdf") for i in (1, 2)]
    other = _scanned(ctx, root, make_scanned_pdf, name="另一份.pdf")
    page = _library(window, qapp)

    _select(page, qapp, *batch)
    page.ocr_btn.click()
    _settle(qapp)
    assert page.ocr_panel.isVisible() and page.ocr_panel.plan is not None

    _select(page, qapp, other)
    assert not page.ocr_panel.isVisible(), "换了选中批次，面板还对着上一批"
    assert page.ocr_panel.plan is None, "面板收了却没放手那份账"


def test_取消之后面板收起而一条也没排(window, ctx, root, make_scanned_pdf, qapp) -> None:
    """「取消」必须是一颗真的取消：收起 + 放手那份账 + 零副作用。"""
    ids = [_scanned(ctx, root, make_scanned_pdf, name=f"扫描件{i}.pdf") for i in (1, 2)]
    page = _library(window, qapp)
    _select(page, qapp, *ids)
    before = _queued(ctx)

    page.ocr_btn.click()
    _settle(qapp)
    page.ocr_panel.cancel_btn.click()
    _settle(qapp)

    assert not page.ocr_panel.isVisible()
    assert page.ocr_panel.plan is None
    assert _queued(ctx) == before, "按的是「取消」，队列却动了"


def test_账算不出来时不展开假面板而屏上给的是后端原文(window, ctx, root, make_scanned_pdf,
                                                  qapp, monkeypatch) -> None:
    """**ISSUES I84** ③ + 「界面不许伪装」：算不出这份账就摆一块空面板写着"点名 0 份"，
    比不出现更费时间。这里要的是后端原文 + 面板**不**出现。"""
    ids = [_scanned(ctx, root, make_scanned_pdf, name=f"扫描件{i}.pdf") for i in (1, 2)]
    page = _library(window, qapp)
    _select(page, qapp, *ids)

    def boom(doc_ids, **kw):
        raise RuntimeError("模拟一次点名超出批量上限")

    monkeypatch.setattr(ctx.ocr, "plan_ocr", boom)
    page.ocr_btn.click()
    _settle(qapp)

    line = page.status_label.text()
    assert "模拟一次点名超出批量上限" in line, f"后端原文没上屏：{line}"
    assert page.status_label.objectName() == "danger", line
    assert not page.ocr_panel.isVisible(), "账算不出来却展开了一块面板"


def test_排队那一下抛异常时屏上留原文而面板不收起(window, ctx, root, make_scanned_pdf,
                                              qapp, monkeypatch) -> None:
    """执行那一步失败：原文上屏 + 那份账**还看得见**（用户可以照着它重试），
    而不是收起面板让人从头再点一遍名单。"""
    ids = [_scanned(ctx, root, make_scanned_pdf, name=f"扫描件{i}.pdf") for i in (1, 2)]
    page = _library(window, qapp)
    _select(page, qapp, *ids)

    page.ocr_btn.click()
    _settle(qapp)

    def boom(doc_ids, **kw):
        raise RuntimeError("模拟排队时库被锁住")

    monkeypatch.setattr(ctx.ocr, "request_ocr", boom)
    page.ocr_panel.enqueue_btn.click()
    _settle(qapp)

    line = page.status_label.text()
    assert "模拟排队时库被锁住" in line, f"失败原文没上屏：{line}"
    assert page.status_label.objectName() == "danger", line
    assert page.ocr_panel.isVisible(), "排队失败却把那份账收了"


# ---------------------------------------------------------------------------
# 几何：面板展开时不许把页面顶过 D-039 的地板
# ---------------------------------------------------------------------------

def test_面板展开时页面与窗口都不许顶过地板宽度(window, ctx, root, make_scanned_pdf,
                                            qapp) -> None:
    """那三行都是**整句中文**，最宽的预算行接近 70 字。不折行的 QLabel 其
    `minimumSizeHint()` 等于整句宽，会把这一栏乃至窗口顶过 1024 —— 侧栏被榨瘪那笔账
    在 `test_ui_layout.py` 里已经记过实测（103 字符的路径让侧栏从 200px 掉到 56px）。

    这条量的是**面板展开之后**的形状：静态那一屏的守卫看不见运行时才填进去的长文字
    （同一坑见 `test_选中备份文件之后恢复标签页也不许顶宽`）。
    """
    ids = [_scanned(ctx, root, make_scanned_pdf, name=f"扫描件{i}.pdf") for i in (1, 2)]
    ctx.ocr.budget.consume(ctx.ocr.budget.pages_per_day)
    page = _library(window, qapp)
    _select(page, qapp, *ids)
    page.ocr_btn.click()
    _settle(qapp)
    assert page.ocr_panel.isVisible() and len(page.ocr_panel.budget_label.text()) > 60

    assert page.minimumSizeHint().width() <= AVAILABLE_WIDTH, (
        f"面板展开后页面最低宽度 {page.minimumSizeHint().width()}px，超过地板档侧栏之外的"
        f"可用 {AVAILABLE_WIDTH}px —— 侧栏会被榨瘪")
    assert window.minimumSizeHint().width() <= MIN_WINDOW_WIDTH, (
        f"面板展开后窗口最低宽度 {window.minimumSizeHint().width()}px，超过 D-039 的地板 "
        f"{MIN_WINDOW_WIDTH}px —— 用户压不到 1024")

    window.resize(MIN_WINDOW_WIDTH, MIN_WINDOW_HEIGHT)
    _settle(qapp)
    assert window.width() == MIN_WINDOW_WIDTH, (
        f"窗口压不到 D-039 的地板：停在 {window.width()}px —— 地板被展开的面板顶宽了")
    assert window.nav.width() >= NAV_WIDTH, (
        f"地板档下面板把侧栏压到了 {window.nav.width()}px")
