"""真引擎跑真扫描件（阶段 5 第 2、6 条）—— 这一文件里没有任何替身。

`test_ocr_service.py` 把决策与推理分开了，这里把它们合起来跑一遍：
真 RapidOCR + 真 onnxruntime + 真 sqlite FTS5 + 真 PDF。可选层没装的机器整文件 skip
（`requirements/ocr.txt` 是可选层，只装 base 的机器上扫描与全文检索照常跑）。

识别正确率的断言**由本机实测反算**，不是拍的：2026-10-14 用 `fontsize=22 / 200dpi`
的六行中文页实测 6/6 逐字命中（provider=DmlExecutionProvider，init 1.463s，
单页首次 3,783ms、预热后 608ms，RSS +340.6MiB）。下限取 5/6，留一行给不同显卡与驱动。
性能数字不在这里断言 —— 机器相关的阈值只会把测试变成 flakes；耗时/内存/GPU 由
`gates/stage5.py` 现测现报。
"""
from __future__ import annotations

import pymupdf
from pathlib import Path

import pytest

from pdfarchiver.db.repositories.jobs import TERMINAL_STATES
from pdfarchiver.fs.identity import identity_key
from pdfarchiver.jobs.queue import WorkQueue
from pdfarchiver.ocr.engine import OcrEngine, OcrUnavailable
from pdfarchiver.search.service import FIELD_BODY, Criteria, SearchService

# 六行互不相同、都是常见词组、不含数字与生僻字：识别成什么样一眼看得出来。
LINES = [
    "极地科考船次航科学考察报告",
    "人工智能产业年度监测白皮书",
    "房屋租赁合同补充条款二零零四",
    "医疗器械经营企业质量管理规范",
    "跨境电子商务综合试验区实施方案",
    "高层民用建筑消防安全管理规定",
]
MIN_VERBATIM_LINES = 5   # 本机实测 6/6；下限留一行余量，推导见模块说明


def _real_engine() -> OcrEngine:
    try:
        OcrEngine().version_stamp
    except OcrUnavailable as exc:
        pytest.skip(f"可选 OCR 层没装，真引擎用例跳过：{exc}")
    return OcrEngine()


def _build_scan_pdf(path: Path, lines: list[str], *, dpi: int = 200) -> str:
    """把字排进一页 → 渲染成位图 → 贴回一份新 PDF。产物是**零文本层**的真扫描件。

    与 `conftest._make_scanned_pdf` 的区别：那张图是个灰矩形，没有字可认。
    """
    draft_doc = pymupdf.open()
    draft = draft_doc.new_page(width=595, height=842)
    y = 90
    for line in lines:
        draft.insert_text((72, y), line, fontsize=22, fontname="china-s")
        y += 70
    stream = draft.get_pixmap(matrix=pymupdf.Matrix(dpi / 72, dpi / 72)).tobytes("png")
    draft_doc.close()

    out = pymupdf.open()
    page = out.new_page(width=595, height=842)
    page.insert_image(page.rect, stream=stream)
    path.parent.mkdir(parents=True, exist_ok=True)
    out.save(str(path))
    out.close()
    return str(path)


def _indexed_scan(ctx, root, tmp_path: Path, name="真扫描件.pdf") -> int:
    """造扫描件 → 扫进库 → 索引完 → 清空队列残行，返回 doc_id。"""
    r = root("真OCR")
    path = _build_scan_pdf(tmp_path / "真OCR" / name, LINES)
    ctx.scan.scan_root(r)
    doc_id = int(ctx.documents.facts_by_key(identity_key(path)).doc_id)
    ctx.indexer.index_document(doc_id)
    for job in ctx.jobs.list():
        ctx.jobs.succeed(int(job.id))
    ctx.jobs.clear_finished()
    assert ctx.documents.get(doc_id).text_status == "none", \
        "样本没做成扫描件（读出文本层了），后面所有断言都在验空气"
    return doc_id


def test_真引擎把图像里的中文识别进全文索引并标明出处(ctx, root, tmp_path) -> None:
    """第 2、6 条 + 「不得把未经验证的识别文字伪装成准确的原始文本」。"""
    engine = _real_engine()
    doc_id = _indexed_scan(ctx, root, tmp_path)
    ctx.ocr.engine = engine

    outcome = ctx.ocr.ocr_document(doc_id)

    assert (outcome.pages_recognized, outcome.pages_failed) == (1, 0), outcome.last_error
    assert outcome.ocr_status == "done" and outcome.chars_added > 0
    body = ctx.texts.pages_of(doc_id)[0].body
    verbatim = sum(1 for line in LINES if line in body)
    assert verbatim >= MIN_VERBATIM_LINES, f"逐字命中 {verbatim}/{len(LINES)}：{body}"
    assert outcome.ms_per_page > 0, "真推理不可能零耗时；这里是 0 就说明时间在骗人"

    hit = SearchService(ctx.documents, ctx.metadata, ctx.texts).search(
        Criteria(text=LINES[0][:4], in_fields=(FIELD_BODY,))).hits[0]
    assert int(hit.doc.id) == doc_id and hit.page_no == 1
    assert hit.body_source == "ocr" and hit.source_label == "OCR 识别（可能有错字）"


def test_真引擎跑完第二次一页都不再推理(ctx, root, tmp_path) -> None:
    """第 8 条在**真版本指纹**上的闭环：假引擎只能验逻辑，指纹串本身对不对要真的才算。"""
    engine = _real_engine()
    doc_id = _indexed_scan(ctx, root, tmp_path)
    ctx.ocr.engine = engine
    ctx.ocr.ocr_document(doc_id)
    assert engine.pages_done == 1

    second = ctx.ocr.ocr_document(doc_id)

    assert second.skipped_current is True and second.pages_recognized == 0
    assert second.pages_expected == 1
    assert engine.pages_done == 1, "已是当前版本还去推理，就是白烧 GPU 小时"


def test_真引擎对原生文字PDF一页都不推理(ctx, root, make_pdf) -> None:
    """「普通文字 PDF 不应无意义地反复执行 OCR」：文件打得开、页也出得来，
    推理一次都没发生才算数。"""
    engine = _real_engine()
    r = root("文字版")
    path = Path(make_pdf("文字版/年报.pdf", page_lines=[LINES[0]]))
    ctx.scan.scan_root(r)
    doc_id = int(ctx.documents.facts_by_key(identity_key(str(path))).doc_id)
    ctx.indexer.index_document(doc_id)
    ctx.ocr.engine = engine

    outcome = ctx.ocr.ocr_document(doc_id)

    assert (outcome.pages_expected, outcome.pages_recognized) == (0, 0)
    assert outcome.ocr_status == "na" and engine.pages_done == 0
    assert ctx.texts.count_ocr_pages(doc_id) == 0


def test_真引擎经真队列落库并把状态写回主记录(ctx, root, tmp_path) -> None:
    """第 3、4 条：起线程、走 `kind='ocr'` 任务，不手调服务方法 —— 用户点到的就是这条路。"""
    engine = _real_engine()
    doc_id = _indexed_scan(ctx, root, tmp_path)
    ctx.ocr.engine = engine
    assert ctx.ocr.request_ocr([doc_id]).enqueued == 1

    queue = WorkQueue(ctx.jobs, {"ocr": ctx.ocr.handle}, engine=ctx.engine, threads=1)
    queue.start()
    try:
        assert queue.wait_until_idle(timeout=180.0), "真引擎没在 180s 内跑完这一页"
    finally:
        queue.stop()

    job = [j for j in ctx.jobs.list(TERMINAL_STATES) if j.kind == "ocr"][0]
    doc = ctx.documents.get(doc_id)
    assert (job.state, (job.done, job.total)) == ("done", (1, 1)), job.last_error
    assert (doc.ocr_status, doc.ocr_pages_done) == ("done", 1)
    assert doc.last_ocr_at is not None, "状态页要回答「这份是什么时候识别完的」"
    assert ctx.texts.count_ocr_pages(doc_id) == 1
    assert ctx.texts.check_fts_consistency().aligned, "OCR 写进外部内容表后索引必须跟着对齐"
