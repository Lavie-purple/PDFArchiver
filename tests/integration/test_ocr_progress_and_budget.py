"""OCR 编排（阶段 5 第 4、7、9 条 + G13 作废重定后的两件）：队列领取、取消、重识别、内存、页预算。

从 `test_ocr_service.py` 拆出（**ISSUES I58** 丙，2026-10-17；800 行这条线管所有 `.py`，
见 **REPO-JOURNAL R-010**）。拆开的是同一条链的两半：那一份管"哪几页该跑、跑完写什么行"，
这一份管"任务在队列里怎么被领走、跑到一半怎么停、界面上的读数怎么说"。
样本与引擎替身由 `tests/integration/ocr_doubles.py` 一份提供，两边共享。

「控制并发、内存和资源占用」（G13 作废重定后的两件）在这一份里：页预算用满就停在半路、
单页耗时超过实测反算的上限就不入库；两件都不许把任务记成跑完（走 `JobCancelled`）。
推理本身由 `test_ocr_real_engine.py` 用真引擎验，性能数字由 `gates/stage5.py` 现测。
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from pdfarchiver.db.repositories.jobs import TERMINAL_STATES
from pdfarchiver.jobs.queue import JobCancelled, WorkQueue
from pdfarchiver.ocr.budget import OcrBudget, page_timeout_ms
from pdfarchiver.services import ocr_service
from tests.integration.ocr_doubles import (
    V1,
    _FakeEngine,
    _FakeReader,
    _clear_jobs,
    _doc_id,
    _fake_images,
    _scanned,
    _textual,
)

REPO = Path(__file__).resolve().parents[2]


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
