"""OCR 编排（阶段 5 第 1、3、5、6、8 条）—— 真库、真 PDF、真队列，只有推理引擎是替身。

**2026-10-17 按 ISSUES I58 丙 拆开**（800 行这条线管所有 `.py`，见 **REPO-JOURNAL R-010**）：
这一份管"**哪几页该跑、跑完往库里写什么行**"；任务在队列里怎么被领走、跑到一半怎么停、
读数怎么说，在 `test_ocr_progress_and_budget.py`。样本与引擎替身两份共用，抽到
`tests/integration/ocr_doubles.py`。

样本全部由 `tests/conftest.py` 现场生成：扫描件是「整页贴图、零文本层」的真 PDF，
文字版是真文本层，混合件一页有字一页没字。库是真 sqlite3（D-012 不许 mock 数据库）。
**只有 `OcrEngine` 被换成脚本对象**：一次真推理 1.6–4.3 秒（阶段 5 实测），
而这一层要验的是「哪几页该跑、跑完写什么状态、失败怎么算」，那是决策不是推理；
推理本身由 `test_ocr_real_engine.py` 用真引擎验，性能数字由 `gates/stage5.py` 现测。

每条断言都对着阶段 5 需求的一句原话写：
「避免重复处理未变化的文件」→ 跑完再一次都不重跑、升版只重跑旧版页；
「普通文字 PDF 不应无意义地反复执行 OCR」→ 文字版一份都不推理；
「OCR 失败不能阻塞其他文件」→ 单页失败不写行、其余页照常入库；
「OCR 结果必须能够追溯到对应文档及页面」→ 行上是 (doc_id, page_no, source_kind, ocr_version)；
「不得把未经验证的识别文字伪装成准确的原始文本」→ 检索行必须带出处标签。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from pdfarchiver.indexing.fts import match_expression
from pdfarchiver.jobs.queue import PermanentFailure
from pdfarchiver.parsing.pdf import PageImage
from pdfarchiver.search.service import FIELD_BODY, Criteria, SearchService
from pdfarchiver.services import ocr_service
from tests.integration.ocr_doubles import (
    V1,
    V2,
    _FakeEngine,
    _FakeReader,
    _clear_jobs,
    _doc_id,
    _fake_images,
    _scanned,
    _textual,
)


# —— 第 1 条：识别出哪些文件等着 OCR ——————————————————————

def test_扫描件索引后被标成待OCR而文字版标成不需要(ctx, root, make_scanned_pdf, make_pdf) -> None:
    """「正文文本缺失或不足、可能需要 OCR」的判定必须在索引阶段就落进库，
    否则阶段 5 的排队没有任何依据，只能整库重跑。"""
    scanned = _scanned(ctx, root, make_scanned_pdf)
    textual = _textual(ctx, root, make_pdf)

    assert ctx.documents.get(scanned).ocr_status == "pending"
    assert ctx.documents.get(textual).ocr_status == "na"
    assert ctx.documents.get(scanned).text_status == "none"


# —— 第 3 条 + 决策 Q3=甲：显式点名才排 ————————————————————

def test_不点名就一条OCR任务都不排(ctx, root, make_scanned_pdf) -> None:
    """扫完、索引完，队列里一条 ocr 都不许有 —— 全量 OCR 是 1,144 GPU 小时（p5 外推）。"""
    doc_id = _scanned(ctx, root, make_scanned_pdf)
    assert ctx.jobs.counts_by_kind_state().get(("ocr", "queued"), 0) == 0

    assert ctx.ocr.request_ocr([]).enqueued == 0
    assert ctx.jobs.counts_by_kind_state().get(("ocr", "queued"), 0) == 0
    assert ctx.documents.get(doc_id).ocr_status == "pending", "没跑就该还是 pending，不许假装排队了"


def test_点名的份数进队列且回执指得出为什么没进(ctx, root, make_scanned_pdf, make_pdf) -> None:
    scanned = _scanned(ctx, root, make_scanned_pdf, name="扫描一.pdf")
    other = _scanned(ctx, root, make_scanned_pdf, name="扫描二.pdf", pages=1)
    textual = _textual(ctx, root, make_pdf)
    # 还没索引的一份：连「哪几页缺字」都判不出来
    never_path = Path(make_pdf("OCR/没索引.pdf", pages=1, lines=["一句话正文内容测试用"]))
    ctx.scan.scan_root(root("OCR"))
    never_indexed = _doc_id(ctx, never_path)

    receipt = ctx.ocr.request_ocr([scanned, other, textual, never_indexed, 999_999])

    assert receipt.named == 5 and receipt.queueable == 2 and receipt.enqueued == 2, receipt.describe()
    assert receipt.skipped["not_needed"] == [textual]
    assert receipt.skipped["no_verdict"] == [never_indexed]
    assert receipt.skipped["absent"] == [999_999]
    assert ctx.jobs.counts_by_kind_state()[("ocr", "queued")] == 2


def test_重复点名同一份不重复排队(ctx, root, make_scanned_pdf) -> None:
    """`queueable` 与 `enqueued` 必须分开数：去重掉的不是"没排上"，是"已经排在队里了"。"""
    doc_id = _scanned(ctx, root, make_scanned_pdf)
    first = ctx.ocr.request_ocr([doc_id])
    second = ctx.ocr.request_ocr([doc_id])
    assert (first.queueable, first.enqueued) == (1, 1)
    assert (second.queueable, second.enqueued) == (1, 0)
    assert ctx.jobs.counts_by_kind_state()[("ocr", "queued")] == 1


# —— 第 5、6 条：落库与可追溯 ————————————————————————————

def test_识别结果按页落库并带上页码与版本(ctx, root, make_scanned_pdf) -> None:
    ctx.ocr.engine = _FakeEngine(texts={1: "甲方合同 编号 A-2024-07", 2: "乙方签署 日期 二零二四年"})
    doc_id = _scanned(ctx, root, make_scanned_pdf)

    outcome = ctx.ocr.ocr_document(doc_id)

    assert (outcome.pages_expected, outcome.pages_recognized, outcome.pages_failed) == (2, 2, 0)
    assert outcome.ocr_status == "done" and outcome.chars_added > 0
    pages = {p.page_no: p for p in ctx.texts.pages_of(doc_id)}
    assert sorted(pages) == [1, 2], "页码口径与阅读器一致：从 1 开始，一页不许少"
    assert all(p.source_kind == "ocr" for p in pages.values())
    assert all(p.ocr_version == V1 for p in pages.values()), "没有版本指纹就不知道这页该不该重跑"
    assert pages[1].char_count == len(pages[1].body) > 0
    doc = ctx.documents.get(doc_id)
    assert (doc.ocr_status, doc.ocr_pages_done) == ("done", 2)
    assert doc.last_ocr_at is not None, "状态页要回答「这份是什么时候识别完的」"


def test_OCR文本进全文索引且标明出处(ctx, root, make_scanned_pdf) -> None:
    """第 6 条 + 「不得把未经验证的识别文字伪装成准确的原始文本」：搜得到是底线，
    搜到时说清是识别出来的，是底线之上的底线。"""
    ctx.ocr.engine = _FakeEngine(texts={1: "极地科考船次航次报告", 2: "第二页内容"})
    doc_id = _scanned(ctx, root, make_scanned_pdf)
    before = SearchService(ctx.documents, ctx.metadata, ctx.texts).search(
        Criteria(text="极地科考船", in_fields=(FIELD_BODY,)))
    assert before.hits == [], "没识别之前就该搜不到，否则验收里的「OCR 生效」无从对照"

    ctx.ocr.ocr_document(doc_id)

    result = SearchService(ctx.documents, ctx.metadata, ctx.texts).search(
        Criteria(text="极地科考船", in_fields=(FIELD_BODY,)))
    assert len(result.hits) == 1 and result.hits[0].page_no == 1
    hit = result.hits[0]
    assert hit.body_source == "ocr" and hit.source_label == "OCR 识别（可能有错字）"
    assert "OCR 识别" in result.rows()[0], result.rows()


def test_删掉OCR行全文索引不留幽灵行(ctx, root, make_scanned_pdf) -> None:
    """G10 的 OCR 侧：按 `source_kind='ocr'` 批量清除必须连索引一起清掉。

    两条断言各管一面，缺一面就有一个坏法溜过去（实测口径见 `check_fts_consistency`）：
    计数口径能抓"正文进库、索引没收录"，抓不到 p1 那个 `delete` 触发器列清单写错——
    那种幽灵只有**拿词直接问索引**才看得见（搜索通路自带 JOIN，问它是问不出来的）。
    """
    ctx.ocr.engine = _FakeEngine(texts={1: "撤回通知函原件丢失"})
    doc_id = _scanned(ctx, root, make_scanned_pdf)
    ctx.ocr.ocr_document(doc_id)
    assert ctx.texts.check_fts_consistency().aligned

    deleted = ctx.texts.delete_ocr_pages(doc_id)

    assert deleted == 2, "整本清除按份算：两页 OCR 行都得删掉"
    check = ctx.texts.check_fts_consistency()
    assert check.aligned, f"索引与正文两张皮：{check.describe()}"
    raw = ctx.texts.engine.thread_connection().execute(
        "SELECT count(*) FROM content_fts WHERE content_fts MATCH ?",
        (match_expression("撤回通知函"),)).fetchone()[0]
    assert raw == 0, f"倒排里还挂着 {raw} 条已删正文的条目 —— 搜索靠 JOIN 挡住了用户，但索引没摘干净"
    assert SearchService(ctx.documents, ctx.metadata, ctx.texts).search(
        Criteria(text="撤回通知函", in_fields=(FIELD_BODY,))).hits == []


def test_索引重建把OCR文本一起重算(ctx, root, make_scanned_pdf) -> None:
    """第 7 条的后半：OCR 与原生文本同住 `text_pages`，重算投影时一起进去，来源仍按行区分。"""
    ctx.ocr.engine = _FakeEngine(texts={1: "海洋牧场水质监测年报", 2: "另一页"})
    doc_id = _scanned(ctx, root, make_scanned_pdf)
    ctx.ocr.ocr_document(doc_id)

    report = ctx.indexer.rebuild_fts()

    assert report["unindexed_before"] == 0 == report["unindexed_after"], report
    assert report["stale_before"] == 0 == report["stale_after"], report
    assert report["pages"] >= 2 and report["docs"] >= 1
    assert SearchService(ctx.documents, ctx.metadata, ctx.texts).search(
        Criteria(text="海洋牧场", in_fields=(FIELD_BODY,))).hits, "重建之后照样要搜得回来"


def test_索引漏了一页时重建把它补回倒排(ctx, root, make_pdf) -> None:
    """`rebuild_fts()` 是**真补救**不是句空话：先造出"正文在库里、倒排里没有"的实际缺口，
    再用重建把它销掉，前后两个数都得在报告里说得出名字。

    缺口是关掉 insert 触发器后直写 `text_pages` 造出来的（外部内容表的索引只由触发器维护），
    这一步同时证明：计数口径确实抓得住这类坏法（`unindexed` 从 1 变 0），不是永不变的瞎数。
    """
    doc_id = _textual(ctx, root, make_pdf)
    conn = ctx.texts.engine.thread_connection()
    conn.execute("DROP TRIGGER tx_pages_ai")
    conn.execute("INSERT INTO text_pages(doc_id, page_no, source_kind, char_count, body, indexed_at)"
                 " VALUES(?, 99, 'native', 5, '重建补回的页', 1)", (doc_id,))
    conn.commit()

    broken = ctx.texts.check_fts_consistency()
    assert broken.unindexed == 1, broken.describe()
    assert SearchService(ctx.documents, ctx.metadata, ctx.texts).search(
        Criteria(text="重建补回的页", in_fields=(FIELD_BODY,))).hits == [], "漏索引的那页此时搜不到（这才是要修的状态）"

    report = ctx.indexer.rebuild_fts()

    assert (report["unindexed_before"], report["unindexed_after"]) == (1, 0), report
    after = ctx.texts.check_fts_consistency()
    assert after.aligned, after.describe()
    assert SearchService(ctx.documents, ctx.metadata, ctx.texts).search(
        Criteria(text="重建补回的页", in_fields=(FIELD_BODY,))).hits, "重建之后这页必须搜得回来"


# —— 第 8 条：幂等 ————————————————————————————————————

def test_跑完再一次都不重跑(ctx, root, make_scanned_pdf) -> None:
    engine = _FakeEngine()
    ctx.ocr.engine = engine
    doc_id = _scanned(ctx, root, make_scanned_pdf)

    first = ctx.ocr.ocr_document(doc_id)
    second = ctx.ocr.ocr_document(doc_id)

    assert first.pages_recognized == 2 and engine.calls == [1, 2]
    assert second.skipped_current is True and second.pages_recognized == 0
    assert engine.calls == [1, 2], "已是当前版本还去推理，就是白烧 GPU 小时"
    assert second.ms_per_page == 0.0, "一次都没推理就不许编一个均值出来"


def test_引擎升版后只重跑旧版本的页(ctx, root, make_pdf) -> None:
    """混合文档：有字的那页永远不跑；识别过的那页在引擎升版后重跑。"""
    r = root("OCR")
    path = Path(make_pdf("OCR/混合.pdf",
                         page_lines=[["人工智能产业年度报告的总体结论与合同审阅要点"], ["要点"]]))
    ctx.scan.scan_root(r)
    doc_id = _doc_id(ctx, path)
    ctx.indexer.index_document(doc_id)
    _clear_jobs(ctx)

    engine = _FakeEngine()
    ctx.ocr.engine = engine
    first = ctx.ocr.ocr_document(doc_id)
    # `pages_expected` 是「这份里有几页缺字、该识别」，不是文件总页数：
    # 有原生字的那页永远不进 OCR，把它算进分母就等于对界面宣布「那页也跑了」。
    assert (first.pages_expected, first.pages_recognized) == (1, 1)
    assert engine.calls == [2], "第一页有原生字，不该进 OCR"

    engine.version_stamp = V2
    second = ctx.ocr.ocr_document(doc_id)
    assert second.pages_reused == 0 and second.pages_recognized == 1
    assert engine.calls == [2, 2]
    assert [p for p in ctx.texts.pages_of(doc_id) if p.page_no == 2][0].ocr_version == V2


def test_普通文字PDF即便被点名也不推理(ctx, root, make_pdf) -> None:
    engine = _FakeEngine()
    ctx.ocr.engine = engine
    doc_id = _textual(ctx, root, make_pdf)

    assert ctx.ocr.request_ocr([doc_id]).queueable == 0
    outcome = ctx.ocr.ocr_document(doc_id)

    assert engine.calls == [] and outcome.pages_expected == 0
    assert outcome.ocr_status == "na"
    assert ctx.texts.count_ocr_pages(doc_id) == 0, "文字版一份 OCR 文本都不该写进库"


def test_失败页不写行下次只补它(ctx, root, make_scanned_pdf) -> None:
    """「OCR 失败不能阻塞其他文件」+ 重试不需要额外状态位：失败页没有版本记录，自然回到待办。"""
    engine = _FakeEngine(fails=(2,))
    ctx.ocr.engine = engine
    doc_id = _scanned(ctx, root, make_scanned_pdf)

    first = ctx.ocr.ocr_document(doc_id)

    assert (first.pages_recognized, first.pages_failed) == (1, 1)
    assert first.ocr_status == "partial" and "第 2 页" in (first.last_error or "")
    assert [p.page_no for p in ctx.texts.pages_of(doc_id)] == [1], "失败的页不许留一行空文本冒充跑过"
    assert ctx.documents.get(doc_id).ocr_pages_done == 1

    engine.fails.clear()
    second = ctx.ocr.ocr_document(doc_id)
    assert second.pages_recognized == 1 and engine.calls == [1, 2, 2], "第一次的 1、2 加第二次只补的 2"
    assert second.pages_reused == 1
    assert second.ocr_status == "done"


def test_全部页失败才判failed部分成功绝不判done(ctx, root, make_scanned_pdf) -> None:
    """写 done 等于对界面宣布「这本书搜得全」，而它有页一个字都没进去。"""
    ctx.ocr.engine = _FakeEngine(fails=(1, 2))
    doc_id = _scanned(ctx, root, make_scanned_pdf)

    outcome = ctx.ocr.ocr_document(doc_id)

    assert outcome.ocr_status == "failed" and outcome.pages_recognized == 0
    assert ctx.documents.get(doc_id).ocr_pages_done == 0
    assert ctx.texts.pages_of(doc_id) == []


def test_单页出图失败不拖垮整本(ctx, root, make_scanned_pdf, monkeypatch) -> None:
    """PyMuPDF 那侧的失败（坏页、超大图）与推理失败是两条路，各自都得不阻塞其余页。"""
    monkeypatch.setattr(ocr_service, "PdfReader", _FakeReader(
        _fake_images(3, error_pages=(2,)), page_count=3))
    engine = _FakeEngine()
    ctx.ocr.engine = engine
    doc_id = _scanned(ctx, root, make_scanned_pdf)

    outcome = ctx.ocr.ocr_document(doc_id)

    assert engine.calls == [1, 3], "第 2 页出图失败就该跳过，第 3 页照跑"
    assert (outcome.pages_recognized, outcome.pages_failed) == (2, 1)
    assert outcome.ocr_status == "partial"
    assert sorted(p.page_no for p in ctx.texts.pages_of(doc_id)) == [1, 3]


def test_加密需要密码的PDF判永久失败并留下原因(ctx, root, make_scanned_pdf, monkeypatch) -> None:
    """「再试三次也不会突然有密码」—— 这种失败不该烧掉重试预算。"""
    monkeypatch.setattr(ocr_service, "PdfReader", _FakeReader(
        [PageImage(1, error="PDF 已加密且需要密码")], page_count=1, needs_pass=True))
    doc_id = _scanned(ctx, root, make_scanned_pdf)

    with pytest.raises(PermanentFailure, match="加密"):
        ctx.ocr.ocr_document(doc_id)
    assert ctx.documents.get(doc_id).ocr_status == "failed"


def test_还没索引的文档不许直接OCR(ctx, root, make_pdf) -> None:
    """判不出缺字页就开跑，等于把文字版 PDF 的每一页都识别一遍。"""
    r = root("OCR")
    ctx.ocr.engine = _FakeEngine()
    path = Path(make_pdf("OCR/只扫描.pdf", pages=2, lines=["一句话正文内容测试用"]))
    ctx.scan.scan_root(r)
    doc_id = _doc_id(ctx, path)

    with pytest.raises(PermanentFailure, match="正文判定"):
        ctx.ocr.ocr_document(doc_id)
    assert ctx.ocr.engine.calls == []


def test_文件不在磁盘上判永久失败且标缺失(ctx, root, make_scanned_pdf) -> None:
    path = Path(make_scanned_pdf("OCR/马上删掉.pdf", pages=1))
    r = root("OCR")
    ctx.scan.scan_root(r)
    doc_id = _doc_id(ctx, path)
    ctx.indexer.index_document(doc_id)
    _clear_jobs(ctx)
    path.unlink()

    with pytest.raises(PermanentFailure, match="不在磁盘"):
        ctx.ocr.ocr_document(doc_id)
    assert ctx.documents.get(doc_id).missing_since is not None
