"""解释带（轮三十六 丙 · 乙）：选中一条命中，那一栏写明**它为什么被找到**。

这一组钉三件事，缺一件这条带子就会变成新的「界面自己编的数」：

1. **只报取回来时本来就带着的事实**。页码、通道、出处、bm25 全部来自 `Hit` 与
   `SearchResult` 已有的字段；同名的那条 `score` 只有 trigram 一支是真的，文件名 / 路径 /
   元数据三通道恒 0.0、正文走 LIKE 也恒 0.0 —— 后两类**一个字都不许提 bm25**，
   否则屏幕上会出现一个 0.00 的假相关度（`test_两字查询走慢速_LIKE_时解释不许报_bm25`）。
2. **小库里 bm25 不许印成「-0.00」**。刚建的归档工具只有几十页，FTS5 的 bm25 绝对值落在
   1e-06 级，两位小数会量化成 0.00 —— 那与「没有得分」长得一模一样，正是要防的那类假读数。
3. **带子跟着选中走、没选中就退回写死的那句**。留着上一条的解释会让人以为它在讲现在这条。

服务层的判据全部取 `SearchResult.explain(hit)` 的返回值（后端是唯一 owner）；
界面那三条在 offscreen 里量真几何 —— 离屏截图只有形状没有 CJK 字形，`text()` 与
`height()` 才是能判的东西。
"""
from __future__ import annotations

import re

import pytest
from PySide6 import QtCore

from pdfarchiver.db.models import Document, TextPage
from pdfarchiver.fs.identity import identity_key
from pdfarchiver.indexing.fts import VIA_FTS, VIA_LIKE, format_bm25
from pdfarchiver.search.service import (Criteria, FIELD_BODY, FIELD_BROWSE, FIELD_FILENAME,
                                        FIELD_METADATA, SearchService)
from pdfarchiver.ui import library_hits
from pdfarchiver.ui.main_window import DEFAULT_WINDOW_HEIGHT, DEFAULT_WINDOW_WIDTH
from tests.conftest import settle as _settle

_DOC_ROLE = library_hits._HIT_DOC_ROLE
_PAGE_ROLE = library_hits._HIT_PAGE_ROLE
_EXPLAIN_ROLE = library_hits._HIT_EXPLAIN_ROLE

NAMED = "归档范围与保留期限的请示.pdf"
BODY_PAGE_2 = "归档范围与保留期限的请示正文第三段"
OCR_BODY = "本授权书由归档处盖章生效，保留期限另议"

#: 「解释里印了一个 bm25 **读数**」的判据。只查 `"bm25" in text` 会误红：非正文通道那句
#: 本来就写着「不打 bm25」—— 那是解释为什么没有分数，不是分数本身。
_BM25_READING = re.compile(r"bm25 [-\d≈]")


def _assert_no_bm25_reading(text: str, channel: str) -> None:
    assert not _BM25_READING.search(text), \
        f"{channel} 没有相关性得分，解释里却印了一个读数：{text}"


@pytest.fixture
def corpus(ctx, make_pdf):
    """三份文档，四种出处各就位：

    - `named`：真 PDF 三页，查询词「保留期限」只落在第 2 页（原生正文）；
    - `by_name`：只有文件名/路径能命中它（`复函稿` / `用户资料`）；
    - `scanned`：一页 `source_kind="ocr"` 的正文，同一句里也带着「保留期限」。
    """
    path = make_pdf(f"语料/{NAMED}",
                    page_lines=[["本件为内部流转稿"], [BODY_PAGE_2], ["附件清单另列"]]).replace("\\", "/")
    named = ctx.documents.upsert(Document(
        path=path, path_key=identity_key(path), name=NAMED,
        size_bytes=20480, mtime_ns=1_760_000_000_000_000_000, page_count=3,
        text_status="done", fts_status="done"))
    ctx.texts.replace_pages(int(named.id), [
        TextPage(doc_id=int(named.id), page_no=1, body="本件为内部流转稿"),
        TextPage(doc_id=int(named.id), page_no=2, body=BODY_PAGE_2),
        TextPage(doc_id=int(named.id), page_no=3, body="附件清单另列")])
    ctx.metadata.replace(int(named.id), {"title": "归档工作请示", "author": "政策研究室"})

    other_path = "D:/用户资料/请示（复函稿）.pdf"
    ctx.documents.upsert(Document(
        path=other_path, path_key=identity_key(other_path), name="请示（复函稿）.pdf",
        size_bytes=1024, mtime_ns=1_760_000_000_000_000_000, text_status="done"))

    ocr_path = "D:/用户资料/扫描件/授权书（扫描件）.pdf"
    scanned = ctx.documents.upsert(Document(
        path=ocr_path, path_key=identity_key(ocr_path), name="授权书（扫描件）.pdf",
        size_bytes=4096, mtime_ns=1_760_000_000_000_000_000, page_count=1,
        text_status="done", fts_status="done", ocr_status="done"))
    ctx.texts.replace_pages(int(scanned.id), [
        TextPage(doc_id=int(scanned.id), page_no=1, body=OCR_BODY,
                 source_kind="ocr", ocr_version="probe-1")])

    return {"ctx": ctx, "named": named, "search": SearchService(ctx.documents, ctx.metadata, ctx.texts)}


# —— 服务层：解释里写的必须是真事实 ——————————————————————————

def test_bm25_读数不许量化成_0_00() -> None:
    """小库里 bm25 的绝对值会落到 1e-3 以下，两位小数直接变成 `0.00` —— 与「没有得分」同形。

    这条单独量 `format_bm25` 而不是靠语料：真语料（哪怕只有三页）算出来的分数也在 0.38 量级
    （实测 -0.3849），凑不出落进 1e-3 的库；靠造数据去够那一段只会得到一个与产品无关的用例。
    """
    assert format_bm25(-15.364124) == "-15.36"
    assert format_bm25(-0.3848) == "-0.38"
    for tiny in (-0.0000012, -0.0049, 0.0):
        shown = format_bm25(tiny)
        assert shown == "≈0", f"分数 {tiny} 被印成 {shown} —— 0.00 会和「没有得分」混起来"


def test_正文命中解释写明通道页码与真_bm25(corpus) -> None:
    """trigram 那一支是全项目**唯一**有真相关度的地方，页码与出处也得一起报。"""
    result = corpus["search"].search(Criteria(text="保留期限", in_fields=(FIELD_BODY,)))
    assert result.channel == VIA_FTS, f"四字查询该走 trigram，实际 {result.channel}"
    native = [h for h in result.hits if h.body_source == "native"]
    assert native and native[0].page_no == 2, f"用例前提：原生正文命中在第 2 页：{result.hits}"

    text = result.explain(native[0])
    assert "trigram 短语检索（4 字）" in text, f"通道口径没写对：{text}"
    assert "第 2 页" in text and "原生正文" in text, f"页码与出处必须都在：{text}"
    assert "-0.00" not in text and "bm25 0.00" not in text, \
        f"bm25 被量化成 0.00 —— 那与「没有得分」长得一样：{text}"

    token = re.search(r"bm25 (\S+?)（", text)
    assert token, f"这句话里该有一个 bm25 读数（或 ≈0）：{text}"
    if token.group(1) == "≈0":
        assert abs(native[0].score) < 0.005, \
            f"报了「≈0」但取回来的分数是 {native[0].score} —— 那是把真分数说小了"
    else:
        shown = float(token.group(1))
        assert abs(shown - native[0].score) <= abs(native[0].score) * 0.1, \
            f"屏幕上写 {shown}，后端分数是 {native[0].score} —— 不是同一个数"


def test_两字查询走慢速_LIKE_时解释不许报_bm25(corpus) -> None:
    """`search_like` 的 `score` 恒 0.0（docstring：「LIKE 没有相关性得分」）。
    把它照抄到屏幕上，用户读到的就是「相关度 0.00」，而这条通道压根没算过分。"""
    result = corpus["search"].search(Criteria(text="保留", in_fields=(FIELD_BODY,)))
    assert result.channel == VIA_LIKE and result.hits, "用例前提：两字查询走 LIKE 且有命中"
    for hit in result.hits:
        assert hit.score == 0.0, "用例前提：LIKE 通道的分数恒 0"
        text = result.explain(hit)
        assert "慢速全文扫描 LIKE（2 字" in text, f"通道口径没写对：{text}"
        _assert_no_bm25_reading(text, "正文慢速 LIKE")
        assert f"第 {hit.page_no} 页" in text, f"正文命中必须带页码：{text}"


def test_文件名命中解释不报页码也不报分数(corpus) -> None:
    result = corpus["search"].search(Criteria(text="复函稿", in_fields=(FIELD_FILENAME,)))
    assert [(h.field, h.doc.name) for h in result.hits] == [(FIELD_FILENAME, "请示（复函稿）.pdf")]
    text = result.explain(result.hits[0])
    assert "通道：文件名" in text, f"没写明是从哪类字段找到的：{text}"
    assert not re.search(r"第 \d+ 页", text), f"文件名命中没有页码，编一个是假信息：{text}"
    _assert_no_bm25_reading(text, "文件名通道")


def test_元数据命中点名是哪一列(corpus) -> None:
    """「这份文档被搜出来」还不够 —— 用户得知道是标题里有还是作者里有。"""
    result = corpus["search"].search(Criteria(text="政策研究室", in_fields=(FIELD_METADATA,)))
    assert result.hits and result.hits[0].field_detail == "author", \
        f"用例前提：这条命中的是 author 列：{result.hits}"
    text = result.explain(result.hits[0])
    assert "元数据·author" in text, f"没点名是哪一列：{text}"
    _assert_no_bm25_reading(text, "元数据通道")


def test_浅扫未扫完时解释跟着说清(corpus, monkeypatch) -> None:
    """**D-051**：预算截停之后结果只覆盖库里靠前那一段 —— 解释带不许让它看起来是"全部"。"""
    monkeypatch.setattr("pdfarchiver.search.service.LIKE_SCAN_ROWS", 1)
    result = corpus["search"].search(Criteria(text="保留", in_fields=(FIELD_BODY,)))
    assert result.body_scan_incomplete is True, "用例前提：预算 1 行而库里有 5 页，必须被截停"
    text = result.explain(result.hits[0])
    assert "按 1 页预算浅扫，未扫完" in text, f"浅扫自报没跟着解释走：{text}"


def test_浏览模式的行也有解释(corpus) -> None:
    """没有查询词时右栏也是那排文档 —— 它们不是"命中"，解释带得说清楚来源。"""
    result = corpus["search"].browse_documents()
    assert result.hits and {h.field for h in result.hits} == {FIELD_BROWSE}
    text = result.explain(result.hits[0])
    assert "浏览模式" in text, f"浏览态的行不该被说成命中：{text}"
    _assert_no_bm25_reading(text, "浏览模式")


def test_OCR_命中写明识别出处(corpus) -> None:
    """**SPEC 五**：识别出来的字可能有错字，用户照抄进报告之前有权知道。"""
    result = corpus["search"].search(Criteria(text="保留期限", in_fields=(FIELD_BODY,)))
    ocr = [h for h in result.hits if h.body_source == "ocr"]
    assert ocr, f"用例前提：那页 OCR 正文里也带着查询词：{result.hits}"
    text = result.explain(ocr[0])
    assert "OCR 识别（可能有错字）" in text, f"OCR 出处没写进解释：{text}"
    assert "第 1 页" in text, f"页码不在解释里：{text}"


# —— 界面：那条带子跟着选中走 ——————————————————————————————

def _page_at(window, qapp):
    """切到 S1、重查一遍、压回设计档，返回页面对象。

    与 `test_ui_tier._page_at` 同一个理由：隐藏页不重排（量到一串 0），
    已在当前页时 `setCurrentRow` 不发信号（外壳的刷新链一次都不走）。
    """
    window._select_by_page_id("library")
    _settle(qapp)
    page = window._pages["library"]
    page.reload()
    window.resize(DEFAULT_WINDOW_WIDTH, DEFAULT_WINDOW_HEIGHT)
    _settle(qapp)
    assert page.isVisible(), "用例前提：library 这一屏得是当前可见页，否则量到的都是 0"
    return page


def _body_row(page) -> int:
    """第一条正文命中所在的行号（分组标题也占行，所以不能写死 0）。"""
    for i in range(page.hit_list.count()):
        if page.hit_list.item(i).data(_PAGE_ROLE) is not None:
            return i
    raise AssertionError(f"用例前提：这一栏里得有一条带页码的正文命中："
                         f"{[page.hit_list.item(i).text() for i in range(page.hit_list.count())]}")


def test_选中一条命中右栏就写明它为什么被找到(window, corpus, qapp) -> None:
    page = _page_at(window, qapp)
    page.search_input.setText("保留期限")
    page._do_search()
    _settle(qapp)

    row = _body_row(page)
    expected = page.hit_list.item(row).data(_EXPLAIN_ROLE)
    assert expected, "命中行上没挂解释 —— 选中时那条带子只能空着或留着上一条"
    page.hit_list.setCurrentRow(row)
    _settle(qapp)

    assert page.explain_label.text() == expected, \
        f"选中第 {row} 行后带子上写的不是这一条的解释：{page.explain_label.text()!r}"
    assert "第 2 页" in expected and "trigram" in expected, f"这条解释缺了关键事实：{expected}"


def test_没有选中时解释带退回那句写死的提示(window, corpus, qapp) -> None:
    """选分组标题、以及按「清除」回到浏览态，两处都得退回 `EXPLAIN_IDLE` ——
    留着上一条的解释会让人以为它在讲现在这条。"""
    page = _page_at(window, qapp)
    page.search_input.setText("保留期限")
    page._do_search()
    _settle(qapp)

    page.hit_list.setCurrentRow(_body_row(page))
    _settle(qapp)
    assert page.explain_label.text() != library_hits.EXPLAIN_IDLE, "用例前提：先得选中一条真命中"

    page.hit_list.setCurrentRow(0)          # 第 0 行是分组标题（不可选中，但会成为 current）
    _settle(qapp)
    assert page.explain_label.text() == library_hits.EXPLAIN_IDLE, \
        f"选了分组标题还留着上一条的解释：{page.explain_label.text()!r}"

    page.hit_list.setCurrentRow(_body_row(page))
    _settle(qapp)
    page.clear_btn.click()
    _settle(qapp)
    assert page.explain_label.text() == library_hits.EXPLAIN_IDLE, \
        f"回到浏览态还留着上一次查询的解释：{page.explain_label.text()!r}"


def test_解释带常驻三行且选行前后右栏不跳(window, corpus, qapp) -> None:
    """带子高按**常量**定，不按文案撑：每换一条命中就换一次字，按内容撑高会让右栏跳一下。"""
    page = _page_at(window, qapp)
    page.search_input.setText("保留期限")
    page._do_search()
    _settle(qapp)

    label = page.explain_label
    line = label.fontMetrics().lineSpacing()
    assert line > 0, "字距量到 0 —— 这条断言会恒真"
    assert label.minimumHeight() >= library_hits.EXPLAIN_LINES * line, \
        f"解释带最小高 {label.minimumHeight()}px 不够 {library_hits.EXPLAIN_LINES} 行（{line}px/行）"

    band_before, list_before = page.explain_band.height(), page.hit_list.height()
    page.hit_list.setCurrentRow(_body_row(page))
    _settle(qapp)
    assert page.hit_list.height() == list_before, \
        f"选中一条命中后命中列表高度从 {list_before} 变成 {page.hit_list.height()} —— 右栏跳了"
    assert abs(page.explain_band.height() - band_before) <= 2, \
        f"解释带高度从 {band_before} 变成 {page.explain_band.height()} —— 短文案不该把它撑高"


def test_解释行挂的是后端那一句而不是界面自己拼的(window, corpus, qapp) -> None:
    """同一个数的第二个出处就是漂移的起点：每行的解释必须逐字等于 `SearchResult.explain()`
    对同一个 `Hit` 的返回值，界面不许另写一版措辞。"""
    page = _page_at(window, qapp)
    page.search_input.setText("保留期限")
    page._do_search()
    _settle(qapp)

    result = page.ctx.search.search_in(page._query, "保留期限", limit=100)
    assert [h.doc.id for h in result.hits], "用例前提：同一条查询在服务层也得有命中"
    # 界面的分组顺序与 `rows()` 一一对应（`_show_hits` 逐个 zip），所以按下标比即可。
    rows = [(i, page.hit_list.item(i)) for i in range(page.hit_list.count())]
    hits = iter(result.hits)
    compared = 0
    for _, item in rows:
        if not (item.flags() & QtCore.Qt.ItemFlag.ItemIsSelectable):
            continue                      # 分组标题，没有对应的 Hit
        hit = next(hits)
        assert item.data(_EXPLAIN_ROLE) == result.explain(hit), \
            f"第 {compared} 条命中的解释与后端出口不一致：{item.data(_EXPLAIN_ROLE)!r}"
        compared += 1
    assert compared == len(result.hits), \
        f"面板 {compared} 行命中 vs 后端 {len(result.hits)} 条 —— 有行没对上"
