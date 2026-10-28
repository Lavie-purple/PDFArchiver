"""S1 **轮三十六 甲**：「按当前筛选送识别」（顶栏按钮）+ 搜不到时的情境提示条。

这一轮解决的是"待识别 2,457 份，但界面上只有'在表格里勾几份'这一条入口"：
两份读数（按钮上的份数、提示条那句为什么搜不到）都来自 `ctx.ocr.pending_in` 一个出口，
再往下只有 `documents.ids_pending_ocr / pending_ocr_totals` 两条 SQL —— 界面既不解析条件、
也不数份数。**不碰 `text_pages`**（197.6 万行，**ISSUES I109** 上主线程是 200 秒量级）。

断言分三组：
① 读数只认 `ocr_status='pending'`，且**跟着筛选走**（换个条件份数就变，不是"全库待识别"）；
② 名单被 `PENDING_ID_LIMIT` 截断时，总数与"这次最多送多少"要一起说清（**ISSUES I11**）；
③ 界面：按钮按的是**筛选**不是表格选中、没有待识别就置灰、提示条只在"真有待识别 + 一条没命中"
   时出现，且它那颗按钮排的是同一批。

每条断言的坏法登记在 `tests/probes/p25_ocr_on_demand_injection.py`。
"""
from __future__ import annotations

from pdfarchiver.ui.library_hits import OCR_HINT_BTN_TEXT
from pdfarchiver.ui.pages.library_page import FILTER_OCR_BTN_TEXT
from tests.integration.ocr_doubles import _scanned, _textual
from tests.conftest import settle as _settle

#: 一个**任何正文里都不会有**的词：提示条只在"一条没命中"时说话，命中数必须是 0 而不是"很少"。
NO_SUCH_WORD = "量子纠缠式装订线"


def _library(window, qapp):
    window._select_by_page_id("library")
    _settle(qapp)
    page = window._pages["library"]
    page.reload()
    _settle(qapp)
    return page


def _queued(ctx) -> int:
    return ctx.jobs.counts_by_kind_state().get(("ocr", "queued"), 0)


# ---------------------------------------------------------------------------
# ① 读数：只认 pending，且跟着筛选走
# ---------------------------------------------------------------------------

def test_待识别只数没识别过的扫描件(ctx, root, make_scanned_pdf, make_pdf) -> None:
    """`pending_in` 的分子里只有 `ocr_status='pending'`：原生文字版是 `na`、识别完的是 `done`。

    坏法（"凡扫描件都算待识别"）：把仓储那条 WHERE 去掉 —— 那么已经识别完的那份会重新
    出现在名单里，用户每按一次都在重排同一批，而按钮上的份数永远掉不下来。
    """
    pending = [_scanned(ctx, root, make_scanned_pdf, name=f"扫描件{i}.pdf") for i in (1, 2)]
    _textual(ctx, root, make_pdf, name="文字版.pdf")

    readout = ctx.ocr.pending_in({})

    assert sorted(readout.ids) == sorted(pending), (
        f"待识别名单应当只有那两份扫描件，实际 {readout.ids}")
    assert readout.documents == 2, readout.documents
    assert readout.pages == 4, f"页数是主记录页数合计（两份各 2 页），实际 {readout.pages}"


def test_读数跟着筛选走而不是全库待识别(ctx, root, make_scanned_pdf) -> None:
    """同一批文档，换一条筛选条件份数就变 —— 这条是「按**当前筛选**送识别」的字面意思。

    坏法（"按钮总是报全库待识别"）：让 `_refresh_pending_ocr` 传 `{}` 而不是 `self._query` ——
    界面上写着"当前筛选"却报全库的数，等于把筛选条那排 chips 当成装饰（**ISSUES I11**）。
    """
    for i in (1, 2):
        _scanned(ctx, root, make_scanned_pdf, name=f"扫描件{i}.pdf", pages=2)

    everything = ctx.ocr.pending_in({})
    # 两份都是 2 页：按"页数 ≥ 3"筛，一份都不该剩
    filtered = ctx.ocr.pending_in({"min_pages": 3})

    assert everything.documents == 2, everything.describe()
    assert filtered.documents == 0 and filtered.ids == (), (
        f"按页数 ≥3 筛过之后不该还有待识别，实际 {filtered.describe()}")


def test_名单截断时总数与这次最多送多少一起说清(ctx, root, make_scanned_pdf) -> None:
    """**ISSUES I11**：名单被截断时只报名单长度，等于把"库里 2 份"说成"只有 1 份"。

    坏法（"只说名单长度"）：`describe() / strip_line()` 去掉 `capped` 那一句 ——
    界面上就是个自相矛盾的数字（总数 2、名单 1），而屏幕上没有半个字解释。
    """
    for i in (1, 2):
        _scanned(ctx, root, make_scanned_pdf, name=f"扫描件{i}.pdf")

    readout = ctx.ocr.pending_in({}, limit=1)

    assert readout.documents == 2 and len(readout.ids) == 1, readout.describe()
    assert readout.capped, "名单比总数短却说自己没截断"
    assert "本次最多排 1 份" in readout.describe(), readout.describe()
    assert "本次最多送 1 份" in readout.strip_line(), readout.strip_line()


# ---------------------------------------------------------------------------
# ② 按钮：按的是筛选，不是表格选中
# ---------------------------------------------------------------------------

def test_按钮按的是筛选而不是表格里勾了哪几份(window, ctx, root, make_scanned_pdf,
                                          qapp) -> None:
    """一行都不选，按钮就该亮着并且报这一批的份数 —— 那正是这个入口存在的理由。

    按下去**不写队列**，先展开同一块批次面板算账（`.=plan_ocr`）：账与回执同源的形状
    沿用 **ISSUES I67** 乙 那块已验证的面板，不是第二个实现。
    """
    ids = [_scanned(ctx, root, make_scanned_pdf, name=f"扫描件{i}.pdf") for i in (1, 2)]
    page = _library(window, qapp)
    before = _queued(ctx)

    assert page.doc_table.selectionModel().selectedRows() == [], "夹具自己就没选中任何行"
    assert page.filter_ocr_btn.isEnabled(), "有待识别却把按钮置灰了"
    assert page.filter_ocr_btn.text() == f"{FILTER_OCR_BTN_TEXT}（2 份）", page.filter_ocr_btn.text()

    page.filter_ocr_btn.click()
    _settle(qapp)

    assert page.ocr_panel.isVisible(), "按了「按当前筛选送识别」却没展开账"
    assert f"点名 {len(ids)} 份" in page.ocr_panel.summary_label.text(), (
        page.ocr_panel.summary_label.text())
    assert _queued(ctx) == before, "还没按「排队」就写进队列了 —— 「先给账再排队」被绕过"


def test_筛选里没有待识别时按钮置灰(window, ctx, root, make_pdf, qapp) -> None:
    """原生文字版不需要 OCR：按钮禁用，且 tooltip 说清"这里没有待识别的"，
    而不是亮着一颗按下去什么都不发生的按钮。"""
    _textual(ctx, root, make_pdf, name="文字版.pdf")
    page = _library(window, qapp)

    assert not page.filter_ocr_btn.isEnabled(), page.filter_ocr_btn.toolTip()
    assert page.filter_ocr_btn.text() == FILTER_OCR_BTN_TEXT, page.filter_ocr_btn.text()
    assert "没有待识别" in page.filter_ocr_btn.toolTip(), page.filter_ocr_btn.toolTip()


# ---------------------------------------------------------------------------
# ③ 情境提示条：搜不到时才说话
# ---------------------------------------------------------------------------

def test_一条都没命中时提示条说清为什么搜不到(window, ctx, root, make_scanned_pdf, qapp) -> None:
    """正文通道搜不到扫描件是**因为还没识别**，不是"库里没有"。这条横幅就是那句话。

    坏法（"提示条常驻"）：`_update_ocr_hint` 不看 `empty` —— 那么用户每次搜索都会看到
    一条和当前查询无关的横幅，第二次起就被当成装饰忽略掉。
    """
    [_scanned(ctx, root, make_scanned_pdf, name=f"扫描件{i}.pdf") for i in (1, 2)]
    page = _library(window, qapp)

    page.search_input.setText(NO_SUCH_WORD)
    page.search_btn.click()
    _settle(qapp)

    assert page.ocr_hint_band.isVisible(), "一条没命中却没说为什么"
    line = page.ocr_hint_label.text()
    assert "2 份扫描件还没识别" in line, line
    assert "正文通道搜不到" in line, line
    assert page.ocr_hint_btn.text() == OCR_HINT_BTN_TEXT, page.ocr_hint_btn.text()


def test_有命中时提示条收起(window, ctx, root, make_scanned_pdf, qapp) -> None:
    """搜得到就不是"搜不到"那个情境：横幅必须收回去，否则它在替一次成功的检索道歉。"""
    _scanned(ctx, root, make_scanned_pdf, name="扫描件甲.pdf")
    page = _library(window, qapp)

    page.search_input.setText("扫描件甲")
    page.search_btn.click()
    _settle(qapp)

    assert page.status_label.text(), "夹具没跑出结果行"
    assert not page.ocr_hint_band.isVisible(), page.ocr_hint_label.text()


def test_提示条收起时不留空名单(window, ctx, root, make_pdf, qapp) -> None:
    """一条待识别都没有时，"为什么搜不到"这句话不成立（没有可送的那一批）——
    横幅不许出现，更不许出现一颗点不到任何一份的按钮。"""
    _textual(ctx, root, make_pdf, name="文字版.pdf")
    page = _library(window, qapp)

    page.search_input.setText(NO_SUCH_WORD)
    page.search_btn.click()
    _settle(qapp)

    assert not page.ocr_hint_band.isVisible(), page.ocr_hint_label.text()
    assert page.ocr_hint_label.text() == "", page.ocr_hint_label.text()


def test_提示条那颗按钮排的是这一批(window, ctx, root, make_scanned_pdf, qapp) -> None:
    """横幅上那颗「送去识别这批」与顶栏那颗走同一条路（同一批名单、同一块面板）——
    两处各排一批就等于同一屏上有两个"这批"（AGENTS.md 禁止核心概念多口径）。"""
    ids = [_scanned(ctx, root, make_scanned_pdf, name=f"扫描件{i}.pdf") for i in (1, 2)]
    page = _library(window, qapp)
    before = _queued(ctx)

    page.search_input.setText(NO_SUCH_WORD)
    page.search_btn.click()
    _settle(qapp)
    assert page.ocr_hint_band.isVisible()

    page.ocr_hint_btn.click()
    _settle(qapp)

    assert page.ocr_panel.isVisible(), "提示条那颗按钮没展开账"
    assert f"点名 {len(ids)} 份" in page.ocr_panel.summary_label.text(), (
        page.ocr_panel.summary_label.text())
    assert _queued(ctx) == before, "还没按「排队」就写进队列了"
