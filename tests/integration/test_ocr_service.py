"""OCR 编排（阶段 5 第 1–9 条）—— 真库、真 PDF、真队列，只有推理引擎是替身。

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
「不得把未经验证的识别文字伪装成准确的原始文本」→ 检索行必须带出处标签；
「控制并发、内存和资源占用」（G13 作废重定后的两件）→ 页预算用满就停在半路、
  单页耗时超过实测反算的上限就不入库；两件都不许把任务记成跑完（走 `JobCancelled`）。
"""
from __future__ import annotations

import os
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from pdfarchiver.db.repositories.jobs import TERMINAL_STATES
from pdfarchiver.fs.identity import identity_key
from pdfarchiver.jobs.queue import JobCancelled, PermanentFailure, WorkQueue
from pdfarchiver.ocr.budget import OcrBudget, page_timeout_ms
from pdfarchiver.ocr.engine import OcrPage
from pdfarchiver.parsing.pdf import PageImage
from pdfarchiver.search.service import FIELD_BODY, Criteria, SearchService
from pdfarchiver.services import ocr_service

V1 = "fake/1.0+dpi200"
V2 = "fake/2.0+dpi200"
REPO = Path(__file__).resolve().parents[2]


def _doc_id(ctx, path) -> int:
    return int(ctx.documents.facts_by_key(identity_key(str(path))).doc_id)  # type: ignore[arg-type]


def _clear_jobs(ctx) -> None:
    """结掉并清空队列里上一轮留下的行，否则「这次排了几条」只是在数上一轮。"""
    for job in ctx.jobs.list():
        ctx.jobs.succeed(int(job.id))
    ctx.jobs.clear_finished()


def _scanned(ctx, root, make_scanned_pdf, name="扫描件.pdf", *, pages=2) -> int:
    """造一份只有图没有字的真 PDF，扫进库并索引完，返回 doc_id。"""
    r = root("OCR")
    path = Path(make_scanned_pdf(f"OCR/{name}", pages=pages))
    ctx.scan.scan_root(r)
    doc_id = _doc_id(ctx, path)
    ctx.indexer.index_document(doc_id)
    _clear_jobs(ctx)
    return doc_id


def _textual(ctx, root, make_pdf, name="文字版.pdf") -> int:
    r = root("OCR")
    path = Path(make_pdf(f"OCR/{name}", pages=2,
                         lines=["人工智能产业年度报告的总体结论", "第二章讲合同审阅要点与风险"]))
    ctx.scan.scan_root(r)
    doc_id = _doc_id(ctx, path)
    ctx.indexer.index_document(doc_id)
    _clear_jobs(ctx)
    return doc_id


class _FakeEngine:
    """按脚本给出每页结果的引擎替身。接口与 `OcrEngine` 一致：
    `version_stamp` / `dpi` / `provider` / `pages_done` / `recognize` —— 少一样就是替身在骗人。

    `fails` 里的页码返回带 error 的 `OcrPage` —— 替**单页推理抛异常**那条路；
    出图失败（PyMuPDF 那侧）走的是 `_FakeReader`，两条路各验各的。
    `slow_ms` 里的页码按给定的毫秒数返回耗时 —— 替**单页耗时超过反算上限**那条路。
    """

    def __init__(self, *, version: str = V1, texts: dict[int, str] | None = None,
                 fails: tuple[int, ...] = (), provider: str = "DmlExecutionProvider") -> None:
        self.version_stamp = version
        self.dpi = 200
        self.provider = provider
        self.pages_done = 0
        self.texts = dict(texts or {})
        self.fails = set(fails)
        self.slow_ms: dict[int, float] = {}
        self.calls: list[int] = []

    def recognize(self, page_no: int, pixels) -> OcrPage:
        self.calls.append(page_no)
        self.pages_done += 1
        took = self.slow_ms.get(page_no, 1.0)
        if page_no in self.fails:
            return OcrPage(page_no, "", 0, took, f"模拟第 {page_no} 页推理异常")
        return OcrPage(page_no, self.texts.get(page_no, f"第{page_no}页识别文字"), 2, took)


class _FakeReader:
    """假出图层：只用来造「某一页出图失败」和「需要密码」这两种在磁盘上不好稳定复现的条件。"""

    def __init__(self, images: list[PageImage], *, page_count: int, needs_pass: bool = False) -> None:
        self._images = images
        self.info = _FakeInfo(page_count, needs_pass)
        self.produced = 0

    def __call__(self, path: str) -> "_FakeReader":
        return self

    def __enter__(self) -> "_FakeReader":
        return self

    def __exit__(self, *exc_info) -> bool:  # noqa: ANN002
        return False

    def iter_page_images(self, dpi: int = 200):
        for image in self._images:
            self.produced += 1
            yield image


class _FakeInfo:
    def __init__(self, page_count: int, needs_pass: bool) -> None:
        self.page_count = page_count
        self.needs_pass = needs_pass


def _fake_images(page_count: int, *, error_pages: tuple[int, ...] = ()) -> list[PageImage]:
    return [PageImage(n, error=f"模拟第 {n} 页出图失败") if n in error_pages
            else PageImage(n, pixels=bytearray(64)) for n in range(1, page_count + 1)]


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
    """G10 的 OCR 侧：按 `source_kind='ocr'` 批量清除必须连索引一起清掉。"""
    ctx.ocr.engine = _FakeEngine(texts={1: "撤回通知函原件丢失"})
    doc_id = _scanned(ctx, root, make_scanned_pdf)
    ctx.ocr.ocr_document(doc_id)
    assert ctx.texts.ghost_row_count() == 0

    deleted = ctx.texts.delete_ocr_pages(doc_id)

    assert deleted == 2, "整本清除按份算：两页 OCR 行都得删掉"
    assert ctx.texts.ghost_row_count() == 0, "幽灵行 = 搜得到但点开没内容"
    assert SearchService(ctx.documents, ctx.metadata, ctx.texts).search(
        Criteria(text="撤回通知函", in_fields=(FIELD_BODY,))).hits == []


def test_索引重建把OCR文本一起重算(ctx, root, make_scanned_pdf) -> None:
    """第 7 条的后半：OCR 与原生文本同住 `text_pages`，重算投影时一起进去，来源仍按行区分。"""
    ctx.ocr.engine = _FakeEngine(texts={1: "海洋牧场水质监测年报", 2: "另一页"})
    doc_id = _scanned(ctx, root, make_scanned_pdf)
    ctx.ocr.ocr_document(doc_id)

    report = ctx.indexer.rebuild_fts()

    assert report["ghost_before"] == 0 == report["ghost_after"]
    assert report["pages"] >= 2 and report["docs"] >= 1
    assert SearchService(ctx.documents, ctx.metadata, ctx.texts).search(
        Criteria(text="海洋牧场", in_fields=(FIELD_BODY,))).hits, "重建之后照样要搜得回来"


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


# —— 第 4 条：进度、成功、失败、重试 ——————————————————————

def test_跑到一半取消时已识别的页留在库里(ctx, root, make_scanned_pdf) -> None:
    class _Monitor:
        def __init__(self) -> None:
            self.total: int | None = None
            self.advances = 0

        def set_total(self, total: int) -> None:
            self.total = total

        def advance(self, n: int = 1) -> None:
            self.advances += n

        def cancelled(self) -> bool:
            return self.advances >= 1

    engine = _FakeEngine()
    ctx.ocr.engine = engine
    doc_id = _scanned(ctx, root, make_scanned_pdf)

    with pytest.raises(JobCancelled, match="已识别"):
        ctx.ocr.ocr_document(doc_id, _Monitor())

    assert engine.calls == [1]
    assert [p.page_no for p in ctx.texts.pages_of(doc_id)] == [1]
    doc = ctx.documents.get(doc_id)
    assert (doc.ocr_status, doc.ocr_pages_done) == ("partial", 1), "中断的成果不记下来，下次就白跑一遍"

    engine2 = _FakeEngine()
    ctx.ocr.engine = engine2
    resumed = ctx.ocr.ocr_document(doc_id)
    assert engine2.calls == [2] and resumed.ocr_status == "done"


def test_OCR任务经真队列跑完并留下进度(ctx, root, make_scanned_pdf) -> None:
    """第 3 条「放入后台队列」+ 第 4 条「进度」：起真线程，不手调 `ocr_document`。"""
    engine = _FakeEngine()
    ctx.ocr.engine = engine
    doc_id = _scanned(ctx, root, make_scanned_pdf)
    assert ctx.ocr.request_ocr([doc_id]).enqueued == 1

    queue = WorkQueue(ctx.jobs, {"ocr": ctx.ocr.handle}, engine=ctx.engine, threads=1)
    queue.start()
    try:
        assert queue.wait_until_idle(timeout=30.0), "OCR 任务没在队列里跑完"
    finally:
        queue.stop()

    job = [j for j in ctx.jobs.list(TERMINAL_STATES) if j.kind == "ocr"][0]
    assert job.state == "done", job.last_error
    assert (job.done, job.total) == (2, 2), "进度按这次真正要推理的页数算，不是整本页数"
    assert ctx.documents.get(doc_id).ocr_status == "done"
    assert engine.calls == [1, 2]


def test_应用自己的队列把ocr任务领给OCR服务(ctx, root, make_scanned_pdf) -> None:
    """上一条自己搭了一张 `{"ocr": ctx.ocr.handle}` 的队列，所以它验不到**产品里那份注册表**。

    接线接错时队列照样"跑完"、任务照样 done，只是识别一次都没发生 —— 这类静默失灵
    只能从 `start_background()` 起的那条真路上验（反向注入 P10/I26、I28 就是这么被抓出来的）。
    """
    engine = _FakeEngine()
    ctx.ocr.engine = engine
    doc_id = _scanned(ctx, root, make_scanned_pdf)
    assert ctx.ocr.request_ocr([doc_id]).enqueued == 1

    queue = ctx.start_background()
    try:
        assert queue.wait_until_idle(timeout=30.0), "后台队列没把这条 ocr 跑完"
    finally:
        queue.stop()

    job = [j for j in ctx.jobs.list(TERMINAL_STATES) if j.kind == "ocr"][0]
    assert (job.state, (job.done, job.total)) == ("done", (2, 2)), job.last_error
    assert engine.calls == [1, 2], "kind='ocr' 没路由到 OCR 服务"
    assert ctx.documents.get(doc_id).ocr_status == "done"


def test_doc_id为空的OCR任务判永久失败不扫全库(ctx, root, make_scanned_pdf) -> None:
    """`doc_id=NULL` 在扫描侧是"整棵子树"，在 OCR 侧必须是用法错误 —— 否则误点一下就是 143 个工作日。"""
    _scanned(ctx, root, make_scanned_pdf)
    ctx.jobs.enqueue("ocr", None)

    queue = WorkQueue(ctx.jobs, {"ocr": ctx.ocr.handle}, engine=ctx.engine, threads=1)
    queue.start()
    try:
        assert queue.wait_until_idle(timeout=30.0)
    finally:
        queue.stop()

    job = [j for j in ctx.jobs.list(TERMINAL_STATES) if j.kind == "ocr" and j.doc_id is None][0]
    assert job.state == "failed" and "具体文档" in (job.last_error or "")
    assert job.attempts == 1, "永久失败不该把三次重试预算烧完"


def test_引擎没装时OCR任务落failed并把装法留在错误里(ctx, root, make_scanned_pdf) -> None:
    """不许退化成「看起来跑成功了但什么都没做」。"""
    from pdfarchiver.ocr.engine import OcrUnavailable

    class _Absent:
        version_stamp = property(lambda self: (_ for _ in ()).throw(
            OcrUnavailable("可选 OCR 层没装：缺发行包 rapidocr-onnxruntime")))
        dpi = 200

        def recognize(self, page_no, pixels):  # pragma: no cover - 到不了这里
            raise AssertionError("引擎没装不该走到推理")

    ctx.ocr.engine = _Absent()
    doc_id = _scanned(ctx, root, make_scanned_pdf)

    with pytest.raises(OcrUnavailable, match="rapidocr"):
        ctx.ocr.ocr_document(doc_id)
    assert ctx.texts.count_ocr_pages(doc_id) == 0


def test_没装可选层时应用侧模块照样import得进来() -> None:
    """`ocr/engine.py` 把 rapidocr 的 import 放在函数里（那一份的模块说明第 1 条），
    为的是「只扫描 + 全文检索」的部署不因缺可选层而起不来。这句话目前只是代码事实，
    本条把它变成断言 —— 在**子进程**里做，因为主进程已经 import 过真包，拦不住。

    两半一起断，缺一半就是假绿：
    ① `rapidocr_onnxruntime` 变成"一 import 就 ImportError"后，应用侧模块仍要 import 得进来；
    ② 同一进程里真去建引擎必须抛 `OcrUnavailable`，且消息里带着装法 ——
       这是①的反向证明：拦不住就说明代码根本没经过这条 import 路径，①会永远绿。
    """
    script = (
        "import sys\n"
        "sys.modules['rapidocr_onnxruntime'] = None\n"
        "import pdfarchiver.app, pdfarchiver.services.bootstrap, pdfarchiver.services.ocr_service\n"
        "print('IMPORT-OK')\n"
        "from pdfarchiver.ocr.engine import OcrEngine, OcrUnavailable\n"
        "try:\n"
        "    OcrEngine().ensure()\n"
        "except OcrUnavailable as exc:\n"
        "    print('BLOCK-OK', 'requirements/ocr.txt' in str(exc))\n"
        "else:\n"
        "    print('BLOCK-FAIL')\n"
    )
    env = dict(os.environ, PYTHONPATH=str(REPO / "src"), QT_QPA_PLATFORM="offscreen")

    out = subprocess.run([sys.executable, "-c", script], cwd=str(REPO), env=env,
                         capture_output=True, text=True, timeout=180)

    assert out.returncode == 0, f"应用侧 import 被可选层拖死了：{out.stderr[-500:]}"
    assert "IMPORT-OK" in out.stdout
    assert "BLOCK-OK True" in out.stdout, f"注入没生效或装法没写进错误：{out.stdout}{out.stderr[-300:]}"


# —— 第 7 条：按需重新识别 ————————————————————————————————

def test_强制重识别先清掉旧的OCR页再按页重跑(ctx, root, make_scanned_pdf) -> None:
    engine = _FakeEngine(texts={1: "第一版识别结果", 2: "第二版识别结果"})
    ctx.ocr.engine = engine
    doc_id = _scanned(ctx, root, make_scanned_pdf)
    ctx.ocr.ocr_document(doc_id)

    engine.texts[1] = "重识别后的新文字"
    receipt = ctx.ocr.request_ocr([doc_id], force=True)
    assert receipt.queueable == 1, "force 绕开「已是当前版本」的短路，但不绕开按页判据"

    outcome = ctx.ocr.ocr_document(doc_id, force=True)

    assert outcome.pages_reused == 0 and outcome.pages_recognized == 2
    assert {p.page_no: p.body for p in ctx.texts.pages_of(doc_id)}[1] == "重识别后的新文字"


def test_强制重识别不动原生页(ctx, root, make_pdf) -> None:
    """原生页是文件里本来就有的字，不是识别出来的 —— 重识别只清 OCR 那几行。"""
    r = root("OCR")
    path = Path(make_pdf("OCR/混合.pdf",
                         page_lines=[["人工智能产业年度报告的总体结论与合同审阅要点"], ["要点"]]))
    ctx.scan.scan_root(r)
    doc_id = _doc_id(ctx, path)
    ctx.indexer.index_document(doc_id)
    _clear_jobs(ctx)
    ctx.ocr.engine = _FakeEngine()
    ctx.ocr.ocr_document(doc_id, force=True)

    kinds = {p.page_no: p.source_kind for p in ctx.texts.pages_of(doc_id)}
    assert kinds == {1: "native", 2: "ocr"}


# —— 第 9 条：并发与内存 —————————————————————————————————

def test_一次只握一页位图(ctx, root, make_scanned_pdf, monkeypatch) -> None:
    """946 页 / 1.1GB 的书（p2 实测最大单文件）在 200dpi 下攒一整本是 ~10GB —— 必须流式。"""
    reader = _FakeReader(_fake_images(6), page_count=6)
    monkeypatch.setattr(ocr_service, "PdfReader", reader)
    backlog: list[int] = []

    class _Watching(_FakeEngine):
        def recognize(self, page_no, pixels):
            backlog.append(reader.produced - len(self.calls) - 1)
            return super().recognize(page_no, pixels)

    ctx.ocr.engine = _Watching()
    doc_id = _scanned(ctx, root, make_scanned_pdf)

    ctx.ocr.ocr_document(doc_id)

    assert max(backlog) <= 0, f"出图跑在识别前面 {max(backlog)} 页 = 攒着位图，不是逐页处理"
    assert len(backlog) == 6


def test_重跑半途崩溃后已入库的页不重复识别(ctx, root, make_scanned_pdf, monkeypatch) -> None:
    """一页一事务的意义：进程被杀之后重启，钱只花在还欠的那几页上。"""
    engine = _FakeEngine()
    ctx.ocr.engine = engine
    doc_id = _scanned(ctx, root, make_scanned_pdf)
    ctx.texts.upsert_pages(doc_id, [_page_of(doc_id, 1)])
    ctx.documents.mark_ocr_result(doc_id, ocr_status="partial", ocr_pages_done=1)

    outcome = ctx.ocr.ocr_document(doc_id)

    assert engine.calls == [2] and (outcome.pages_reused, outcome.pages_recognized) == (1, 1)
    assert outcome.ocr_status == "done"


def _page_of(doc_id: int, page_no: int):
    from pdfarchiver.db.models import TextPage
    return TextPage(doc_id=doc_id, page_no=page_no, body="上一进程识别出来的文字内容",
                    source_kind="ocr", ocr_version=V1)


# —— G13 作废重定：每日页预算与单页超时（推导见 `ocr/budget.py`）————————

def test_预算用满后点名一条都不排且回执说清原因(ctx, root, make_scanned_pdf) -> None:
    """预算是资源闸门，所以它在排队这一步就拦 —— 排进去再让 worker 空跑一趟，
    等于把队列位置和一次"看起来失败了"的任务行花在明知不该跑的东西上。"""
    ctx.ocr.engine = _FakeEngine()
    doc_id = _scanned(ctx, root, make_scanned_pdf)
    ctx.ocr.budget = OcrBudget(ctx.app_settings, pages_per_day=1)
    ctx.ocr.budget.consume()

    receipt = ctx.ocr.request_ocr([doc_id])

    assert (receipt.queueable, receipt.enqueued) == (0, 0), receipt.describe()
    assert receipt.skipped["budget_exhausted"] == [doc_id]
    assert "页预算已用满" in receipt.describe(), receipt.describe()
    assert ctx.jobs.counts_by_kind_state().get(("ocr", "queued"), 0) == 0
    assert ctx.ocr.engine.calls == [], "被预算挡住不该发生任何推理"
    assert ctx.documents.get(doc_id).ocr_status == "pending", "挡下来不改变任何库内状态"

    # force 绕开幂等短路，但**不绕开限额**：能绕开限额的限额等于没有限额。
    assert ctx.ocr.request_ocr([doc_id], force=True).queueable == 0


def test_跑到一半预算用满剩下的页留在待办(ctx, root, make_scanned_pdf) -> None:
    """第 7 条口径前半：停在半路写 `partial`，未识别的页没有版本行，明天自动回到待办，
    而且已入库的那页不许再推理一次。"""
    engine = _FakeEngine()
    ctx.ocr.engine = engine
    ctx.ocr.budget = OcrBudget(ctx.app_settings, pages_per_day=1)
    doc_id = _scanned(ctx, root, make_scanned_pdf, pages=3)

    with pytest.raises(JobCancelled, match="页预算用满"):
        ctx.ocr.ocr_document(doc_id)

    assert engine.calls == [1]
    assert [p.page_no for p in ctx.texts.pages_of(doc_id)] == [1]
    doc = ctx.documents.get(doc_id)
    assert (doc.ocr_status, doc.ocr_pages_done) == ("partial", 1)
    # 停下时必须把"停在哪一页之前"和"今天已经跑了多少页"一起留在库里，
    # 否则界面只能说"没跑完"，说不出这是限额生效还是文件有问题。
    assert "跑到第 2 页之前" in (doc.last_error or ""), doc.last_error
    assert "已用 1 页" in (doc.last_error or "") and "预算 1 页" in (doc.last_error or "")

    ctx.ocr.budget = OcrBudget(ctx.app_settings, pages_per_day=100)    # 换到"明天"的账
    next_engine = _FakeEngine()
    ctx.ocr.engine = next_engine

    resumed = ctx.ocr.ocr_document(doc_id)

    assert next_engine.calls == [2, 3], "第一页的成果不记下来，明天就白烧一遍"
    assert (resumed.pages_reused, resumed.pages_recognized) == (1, 2)
    assert resumed.ocr_status == "done"


def test_预算停在半路的任务不许记成跑完(ctx, root, make_scanned_pdf) -> None:
    """真队列版：`_finish_success` 会把 `done` 补成 `total`（阶段 2 反向注入 I19 抓的就是它）。
    一份只跑了一页的文档被记成"跑完了 3/3"，界面上就再也没人知道还有两页没进去。"""
    engine = _FakeEngine()
    ctx.ocr.engine = engine
    ctx.ocr.budget = OcrBudget(ctx.app_settings, pages_per_day=1)
    doc_id = _scanned(ctx, root, make_scanned_pdf, pages=3)
    assert ctx.ocr.request_ocr([doc_id]).enqueued == 1

    queue = WorkQueue(ctx.jobs, {"ocr": ctx.ocr.handle}, engine=ctx.engine, threads=1)
    queue.start()
    try:
        assert queue.wait_until_idle(timeout=30.0)
    finally:
        queue.stop()

    job = [j for j in ctx.jobs.list(TERMINAL_STATES) if j.kind == "ocr"][0]
    assert job.state == "cancelled", f"半本被记成 {job.state}：{job.last_error}"
    assert (job.done, job.total) == (1, 3), "进度只许停在真实跑过的页数上"
    assert ctx.documents.get(doc_id).ocr_status == "partial"


def test_一页都来不及跑时状态写回pending不前进(ctx, root, make_scanned_pdf) -> None:
    """任务排进来时预算还有余量，被别的文档先花光了 —— 这条只能从 worker 那侧发生。
    此时"今天什么都没跑"必须与"跑了一半"长得不一样：停在 `partial` 会让两个读数撞车。"""
    engine = _FakeEngine()
    ctx.ocr.engine = engine
    doc_id = _scanned(ctx, root, make_scanned_pdf, pages=2)
    ctx.ocr.budget = OcrBudget(ctx.app_settings, pages_per_day=2)
    ctx.ocr.budget.consume(2)

    with pytest.raises(JobCancelled, match="跑到第 1 页之前"):
        ctx.ocr.ocr_document(doc_id)

    assert engine.calls == []
    doc = ctx.documents.get(doc_id)
    assert doc.ocr_status == "pending", "一页没进去就不许让状态往前走"
    assert ctx.texts.count_ocr_pages(doc_id) == 0
    assert ctx.ocr.budget.remaining() == 0, "什么都没跑也不该把今天的账退回去"


def test_单页耗时超过反算上限时那页不入库整份停下(ctx, root, make_scanned_pdf) -> None:
    """第 7 条口径后半 + 第 8 条：拦的是病态文件。那一页没识别完就是不入库 ——
    半截文字进了索引比搜不到更糟，它会以"OCR 识别"的名义冒充一份不存在的正文。"""
    engine = _FakeEngine()
    engine.slow_ms[2] = page_timeout_ms("DmlExecutionProvider") + 1
    ctx.ocr.engine = engine
    ctx.ocr.budget = OcrBudget(ctx.app_settings, pages_per_day=1000)
    doc_id = _scanned(ctx, root, make_scanned_pdf, pages=3)

    with pytest.raises(JobCancelled, match="超过单页上限"):
        ctx.ocr.ocr_document(doc_id)

    assert engine.calls == [1, 2], "第 3 页不许接着跑，停下才是这条限量的语义"
    assert [p.page_no for p in ctx.texts.pages_of(doc_id)] == [1]
    doc = ctx.documents.get(doc_id)
    assert (doc.ocr_status, doc.ocr_pages_done) == ("partial", 1)
    limit = page_timeout_ms("DmlExecutionProvider")
    assert f"{limit}ms" in (doc.last_error or ""), doc.last_error
    assert ctx.ocr.budget.used_today() == 2, "超时那一页的 GPU 时间真的烧掉了，账上要看得见"


def test_CPU降级按CPU的实测上限不误杀慢而正常的页(ctx, root, make_scanned_pdf) -> None:
    """上限取实测最大值 ×2 就是为了容得下显卡争用与降级档：p5 同一批页走 CPU 均值 25,835ms，
    按 DML 那档 30,000ms 掐，降级运行的每一份都会被误判成病态文件。"""
    engine = _FakeEngine(provider="CPUExecutionProvider")
    engine.slow_ms[1] = 40_000.0      # DML 档会判超时，CPU 档（165,000ms）之内
    ctx.ocr.engine = engine
    ctx.ocr.budget = OcrBudget(ctx.app_settings, pages_per_day=1000)
    doc_id = _scanned(ctx, root, make_scanned_pdf)

    outcome = ctx.ocr.ocr_document(doc_id)

    assert outcome.ocr_status == "done" and sorted(engine.calls) == [1, 2]
    assert ctx.texts.count_ocr_pages(doc_id) == 2


# —— 状态读数 ————————————————————————————————————————

def test_状态读数给出OCR份数与已入库页数(ctx, root, make_scanned_pdf, make_pdf) -> None:
    """第 4 条「展示处理进度」在库这一侧的落点：份数与页数各是各的口径，都要能读出来。"""
    scanned = _scanned(ctx, root, make_scanned_pdf)
    _textual(ctx, root, make_pdf)
    ctx.ocr.engine = _FakeEngine()
    ctx.ocr.ocr_document(scanned)

    tasks = ctx.status.read_tasks(max_attempts=3)

    # 份数从 documents.ocr_status 数（一份一条），页数从 text_pages 数（一页一行）：
    # 两个口径不许互相代替 —— 一份 946 页的书在份数里是 1，在页数里是 946。
    assert tasks.ocr_by_status == {"done": 1, "na": 1}, tasks.ocr_by_status
    assert tasks.ocr_pages == 2, "已入库的 OCR 页数只能从 text_pages 数出来"
    line = [l for l in tasks.lines() if l.startswith("  OCR 状态：")]
    assert line and "done=1" in line[0] and "已存 OCR 正文 2 页" in line[0], tasks.lines()
