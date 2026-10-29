"""命中行内后缀（轮三十七 甲）：每条命中行尾挂一小节**它为什么被找到**。

线框 §A 甲（2026-10-28 用户勾「换成甲」）：轮三十六 丙 · 乙 的整段解释带拆掉，解释改成
行内后缀。这一组钉四件事，缺一件行尾就会长出新的「界面自己编的数」：

1. **后缀只有后端一个 owner**。每行显示的必须是 `rows()` 那句 + `" · "` +
   `SearchResult.suffix(hit)` 的逐字拼接，界面不许另写一版措辞
   （`test_每条命中行尾挂的是后端后缀_界面不自己拼`）。
2. **分数只在 trigram 一支出现**。非正文三通道与正文 LIKE 的 `Hit.score` 恒 0.0
   （`text.search_like` 的 docstring：「LIKE 没有相关性得分」），后缀一个读数都不许报，
   否则行尾出现一个 0.00 的假相关度。
3. **不重复行首已有的事实**。页码与出处（原生 / OCR）在 `rows()` 的行首已经带了，
   后缀只补通道口径与分数 —— OCR 出处报两遍不是强调，是两个出处
   （`test_OCR_出处只在行首报一次_后缀不再重复`）。
4. **解释带必须真的不在了**。控件、样式、常量三处都拆，`suffix` 之外全站不允许存在
   第二份"为什么"的文案（`test_解释带连控件带样式一起拆干净`）。

服务层判据全部取 `SearchResult.suffix(hit)` 的返回值（后端是唯一 owner）；
界面那两条在 offscreen 里量 —— 离屏截图只有形状没有 CJK 字形，`text()` 才是能判的东西。
"""
from __future__ import annotations

import re

import pytest
from PySide6 import QtCore

from pdfarchiver.db.models import Document, TextPage
from pdfarchiver.fs.identity import identity_key
from pdfarchiver.indexing.fts import VIA_FTS, VIA_LIKE, format_bm25
from pdfarchiver.search.service import (Criteria, FIELD_BODY, FIELD_FILENAME, FIELD_METADATA,
                                        SearchService)
from pdfarchiver.ui import library_hits
from pdfarchiver.ui.main_window import DEFAULT_WINDOW_HEIGHT, DEFAULT_WINDOW_WIDTH
from pdfarchiver.ui.theme import ThemeManager
from tests.conftest import settle as _settle

_PAGE_ROLE = library_hits._HIT_PAGE_ROLE

NAMED = "归档范围与保留期限的请示.pdf"
BODY_PAGE_2 = "归档范围与保留期限的请示正文第三段"
OCR_BODY = "本授权书由归档处盖章生效，保留期限另议"

#: 「后缀里印了一个相关度**读数**」的判据（轮四十二 ④ 之后行尾写「相关度 N」而不是「bm25 N」）。
#: 只查 `"相关度" in text` 会误红：非正文与 LIKE 两支的后缀写着别的措辞，但保险起见
#: 仍然锚定到"相关度后跟数字/≈0"的形状 —— 那才是读数，措辞不算。
_BM25_READING = re.compile(r"相关度 [-\d≈]")
_PAGE_IN_TEXT = re.compile(r"第 \d+ 页")


def _assert_no_bm25_reading(text: str, channel: str) -> None:
    assert not _BM25_READING.search(text), \
        f"{channel} 没有相关性得分，后缀里却印了一个读数：{text}"


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


# —— 服务层：后缀里写的必须是真事实 ——————————————————————————

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


def test_正文命中后缀写明通道与真_bm25_页码留给行首(corpus) -> None:
    """trigram 那一支是全项目**唯一**有真相关度的地方。页码不许进后缀：
    `rows()` 的行首已经写了 `[第 2 页]`，后缀再报一遍就是同一个事实的两个出处。"""
    result = corpus["search"].search(Criteria(text="保留期限", in_fields=(FIELD_BODY,)))
    assert result.channel == VIA_FTS, f"四字查询该走 trigram，实际 {result.channel}"
    native = [h for h in result.hits if h.body_source == "native"]
    assert native and native[0].page_no == 2, f"用例前提：原生正文命中在第 2 页：{result.hits}"

    text = result.suffix(native[0])
    assert text.startswith("正文·全文索引（4 字）·相关度 "), f"通道口径没写对：{text}"
    assert not _PAGE_IN_TEXT.search(text), f"页码行首已带，后缀不许重复：{text}"
    assert "-0.00" not in text and "相关度 0.00" not in text, \
        f"相关度被量化成 0.00 —— 那与「没有得分」长得一样：{text}"

    token = re.search(r"相关度 (\S+)", text)
    assert token, f"这句话里该有一个相关度读数（或 ≈0）：{text}"
    if token.group(1) == "≈0":
        assert abs(native[0].score) < 0.005, \
            f"报了「≈0」但取回来的分数是 {native[0].score} —— 那是把真分数说小了"
    else:
        shown = float(token.group(1))
        assert abs(shown - native[0].score) <= abs(native[0].score) * 0.1, \
            f"行尾写 {shown}，后端分数是 {native[0].score} —— 不是同一个数"


def test_两字查询走慢速_LIKE_时后缀不许报_bm25(corpus) -> None:
    """`search_like` 的 `score` 恒 0.0。把它照抄到行尾，用户读到的就是「相关度 0.00」，
    而这条通道压根没算过分。"""
    result = corpus["search"].search(Criteria(text="保留", in_fields=(FIELD_BODY,)))
    assert result.channel == VIA_LIKE and result.hits, "用例前提：两字查询走 LIKE 且有命中"
    for hit in result.hits:
        assert hit.score == 0.0, "用例前提：LIKE 通道的分数恒 0"
        text = result.suffix(hit)
        assert text.startswith("正文·慢速逐页扫描（2 字，未用索引"), f"通道口径没写对：{text}"
        _assert_no_bm25_reading(text, "正文慢速 LIKE")
        assert not _PAGE_IN_TEXT.search(text), f"页码行首已带，后缀不许重复：{text}"


def test_文件名命中后缀不报页码也不报分数(corpus) -> None:
    result = corpus["search"].search(Criteria(text="复函稿", in_fields=(FIELD_FILENAME,)))
    assert [(h.field, h.doc.name) for h in result.hits] == [(FIELD_FILENAME, "请示（复函稿）.pdf")]
    text = result.suffix(result.hits[0])
    assert text.startswith("文件名 含查询词（字面匹配"), f"没写明是哪类字段、怎么匹配的：{text}"
    assert not _PAGE_IN_TEXT.search(text), f"文件名命中没有页码，编一个是假信息：{text}"
    _assert_no_bm25_reading(text, "文件名通道")


def test_元数据命中点名是哪一列(corpus) -> None:
    """「这份文档被搜出来」还不够 —— 用户得知道是标题里有还是作者里有。"""
    result = corpus["search"].search(Criteria(text="政策研究室", in_fields=(FIELD_METADATA,)))
    assert result.hits and result.hits[0].field_detail == "author", \
        f"用例前提：这条命中的是 author 列：{result.hits}"
    text = result.suffix(result.hits[0])
    assert text.startswith("元数据·author 含查询词"), f"没点名是哪一列：{text}"
    _assert_no_bm25_reading(text, "元数据通道")


def test_浅扫未扫完时后缀跟着说清(corpus, monkeypatch) -> None:
    """**D-051**：预算截停之后结果只覆盖库里靠前那一段 —— 行尾不许让它看起来是"全部"。"""
    monkeypatch.setattr("pdfarchiver.search.service.LIKE_SCAN_ROWS", 1)
    result = corpus["search"].search(Criteria(text="保留", in_fields=(FIELD_BODY,)))
    assert result.body_scan_incomplete is True, "用例前提：预算 1 行而库里有 5 页，必须被截停"
    text = result.suffix(result.hits[0])
    assert text.endswith("｜浅扫未扫完（缺的是库里靠后的页）"), f"浅扫自报没跟着后缀走：{text}"


def test_浏览模式的行也有后缀(corpus) -> None:
    """没有查询词时右栏也是那排文档 —— 它们不是"命中"，行尾得说清楚来源。"""
    result = corpus["search"].browse_documents()
    assert result.hits
    text = result.suffix(result.hits[0])
    assert "未输入查询词" in text and "不带命中位置" in text, f"浏览态的行不该被说成命中：{text}"
    _assert_no_bm25_reading(text, "浏览模式")


def test_OCR_出处只在行首报一次_后缀不再重复(corpus) -> None:
    """**SPEC 五**：识别出来的字可能有错字，用户照抄进报告之前有权知道 —— 这件事
    `rows()` 的行首 `｜OCR 识别（可能有错字）` 已经办了；后缀再写一遍"OCR"就成了
    同一个事实的两个出处，将来改措辞必漂移其一。"""
    result = corpus["search"].search(Criteria(text="保留期限", in_fields=(FIELD_BODY,)))
    ocr = [h for h in result.hits if h.body_source == "ocr"]
    assert ocr, f"用例前提：那页 OCR 正文里也带着查询词：{result.hits}"
    line = next(l for l, h in zip(result.rows(), result.hits) if h is ocr[0])
    assert "OCR 识别（可能有错字）" in line, f"行首必须带出处：{line}"
    assert "OCR" not in result.suffix(ocr[0]), f"后缀又在报一遍 OCR 出处：{result.suffix(ocr[0])}"


# —— 界面：行尾挂的就是后端那一句 ——————————————————————————

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


def test_每条命中行尾挂的是后端后缀_界面不自己拼(window, corpus, qapp) -> None:
    """同一个数的第二个出处就是漂移的起点：每行必须逐字等于 `rows()` 那句 + `" · "` +
    `SearchResult.suffix(hit)`，界面只做这一个拼接动作，不许另写一版措辞。"""
    page = _page_at(window, qapp)
    page.search_input.setText("保留期限")
    page._do_search()
    _settle(qapp)

    result = page.ctx.search.search_in(page._query, "保留期限", limit=100)
    assert [h.doc.id for h in result.hits], "用例前提：同一条查询在服务层也得有命中"
    # 界面的分组顺序与 `rows()` 一一对应（`_show_hits` 逐个 zip），所以按下标比即可。
    lines = result.rows()
    hits = iter(result.hits)
    compared = 0
    for i in range(page.hit_list.count()):
        item = page.hit_list.item(i)
        if not (item.flags() & QtCore.Qt.ItemFlag.ItemIsSelectable):
            continue                      # 分组标题，没有对应的 Hit
        hit = next(hits)
        expected = f"{lines[compared]} · {result.suffix(hit)}"
        assert item.text() == expected, \
            f"第 {compared} 条命中的行文案与后端出口不一致：\n  面板 {item.text()!r}\n  后端 {expected!r}"
        compared += 1
    assert compared == len(result.hits), \
        f"面板 {compared} 行命中 vs 后端 {len(result.hits)} 条 —— 有行没对上"

    # 后缀真的在场：正文那行必须以相关度读数收尾（真读数或「≈0」，不许只有 `rows()` 前半句）。
    text = page.hit_list.item(_body_row(page)).text()
    assert re.search(r"·相关度 (≈0|-[\d.]+)$", text), f"正文行尾没有相关度读数：{text}"


def test_解释带连控件带样式一起拆干净(window, corpus, qapp) -> None:
    """线框 §A 甲 的「0 个新控件」还有后半句：**旧控件也不许留尸**。控件与 QSS 选择器
    两处都要不在 —— 留一块看不见的解释带，就是给下一个轮次留一个"它还活着"的假象。"""
    page = _page_at(window, qapp)
    assert getattr(page, "explain_band", None) is None, "解释带控件还挂在页面上"
    assert getattr(page, "explain_label", None) is None, "解释带文字还在页面上"

    qss = ThemeManager().generate_qss()
    assert "explainBand" not in qss, "QSS 里还留着解释带的选择器 —— 死样式"
    assert "ocrHintBand" in qss, "用例前提：情境提示条（甲 · 乙）必须还在场，别拆过头"

    page.search_input.setText("保留期限")
    page._do_search()
    _settle(qapp)
    page.hit_list.setCurrentRow(_body_row(page))
    _settle(qapp)
    # 选中一条命中之后页面也不许冒出任何第二份解释控件。
    assert getattr(page, "explain_label", None) is None, "选中命中后解释带又回来了"
