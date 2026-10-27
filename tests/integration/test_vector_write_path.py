"""向量写路径 —— 钉住 **ISSUES I63** 丙 + 丁：`VectorStore.add*` 真有产品调用方、
`"vector"` 任务真能入队并被 worker 调度、`vector_status` 真有人推进。

入账之前这一层在仓库里的形状（**ISSUES I63** 现测）：`VectorStore.add / add_batch /
delete_by_doc` 在 `src/` 下零产品调用方（只有 `gates/stage6.py` 夹具用），`jobs.KINDS` 里
的 `"vector"` 从不入队，`vector_status` 恒为 `Document` 默认值 `na`。于是 p12 C7「向量状态
取值都在口径内」恒绿，但那个绿只是"全都停在初始值"的读数，不是判定。

这十五条各自钉住一个会坏的地方：

1. **点名进队（丁的入队路径）**：`request_vectors` 把该建的排进队列，回执分开数 `named /
   queueable / enqueued`，没正文的那份当场被挡在门外并指到具体 doc_id。
2. **worker 真调度（丁的调度侧）**：起一条**真** `WorkQueue`，排一条 `"vector"` 任务，
   它必须被领走并跑完 —— 证明 `bootstrap` 的 handlers 字典里那条 `"vector"` 接上了。
3. **成功推进 + 向量真落盘（丙）**：`build_vectors` 之后 `vector_status` 从 `na` 走到 `done`，
   且 `VectorStore.count()` 随页数增长 —— 比只数状态更能证明 `VectorStore.add_batch` 真被调了。
4. **重嵌先清旧向量（丙的 `delete_by_doc` 调用方）**：连建两次，向量总数不翻倍。
5. **模型没装不许伪装成功**：`embed` 抛 `FileNotFoundError` 时写 `failed` + 原文进
   `last_error`，绝不写 `done`，也绝不停在 `na`（"跑不了"≠"没跑"）。
6. **没正文不建空向量**：既没有原生正文、也没有 OCR 正文的那份直接拒，状态一个字节不动
   （**ISSUES I116** 甲：入场券是「有没有可搜的正文」，OCR 出的正文同样算）。
7. **空正文页跳过**：`char_count=0` 的那一页不塞进语义索引 —— 与"这一页本来就没字"同一件事。
8. **全进程只许一只 `VectorStore`（**ISSUES I111** 丁）**：装配层把同一只实例注入读侧、写侧与
   AI 分类建议。这条是结构判据，防的是"再长回两只"。
9. **建完当场搜得到，不必重启（**ISSUES I111** 甲的用户可见后果）**：先搜一次把读侧缓存锁成空，
   再走写路径建向量，同一场会话里必须立刻搜得到 —— 修之前这一段是 0 命中。
10. **一次前向吞一批页（**ISSUES I112** 甲）**：逐页 `embed_single` 实测 28.48 页/s，同批 16 页
   一次前向 72.86 页/s。判据是**每次调用的页数**，不是总页数 —— 坏形状也照样嵌得完。
11. **取消按批生效**：第 N 批前被取消就地停，`vector_status` 回 `stale`、一条向量都不落盘。
12. **追加不重写整份文件（**ISSUES I112** 乙）**：容量够时只写新行，文件大小不动。
13. **扩容搬旧行且翻倍（乙）**：第 1025 行触发扩容，前 1024 行必须原样还在。
14. **不共用实例也看得见（**ISSUES I111** ①）**：A 先搜一次、B 再写，A 必须当场命中 ——
    `used` 现读库、文件现开现关，实例级缓存这一层已经没有了。
15. **孤儿 `doc_id` 插不进元数据（**ISSUES I111** D）**：连接打开 `PRAGMA foreign_keys=ON`，
    迁移 0007 声明的那条 FK 才真的执行。
16. **全进程只养一份 `EmbeddingService`（**ISSUES I111** ⑤）**：查询向量与建向量共用一次加载，
    不再为语义搜索另养一个 ONNX session。
17. **OCR 出的正文也能建向量（**ISSUES I116** 甲）**：`text_status=none｜ocr_status=done` 的扫描件
    必须能进队列、能建完；坏法是把谓词改回只看 `text_status`，那一条必须红。
18. **入场券四象限（**ISSUES I116** 甲）**：`partial` 算有正文、`na/pending/failed` 不算 ——
    直接钉谓词本身，不靠端到端结果反推。

跑法：
    .venv/Scripts/python.exe -m pytest tests/integration/test_vector_write_path.py -q
"""
from __future__ import annotations

import sqlite3
import time
from pathlib import Path

import numpy as np
import pytest

from pdfarchiver.db.models import Document, TextPage
from pdfarchiver.fs.identity import identity_key
from pdfarchiver.jobs.queue import JobCancelled, PermanentFailure
from pdfarchiver.semantic.vector_store import DEFAULT_CAPACITY, VectorStore
from pdfarchiver.services.bootstrap import AppContext, bootstrap
from pdfarchiver.services.index_service import has_searchable_text
from pdfarchiver.services.vector_service import (
    SKIP_NOT_SEARCHABLE, VECTOR_DONE, VECTOR_FAILED, VECTOR_STALE, VectorService)


class StubEmbedding:
    """把"这一页正文"换成一个确定向量，绕开 ONNX 模型（模型在 CI 上不存在）。

    只实现 `VectorService` 用到的 `embed` —— 契约就是那一个方法，不假装是完整引擎。
    同一文本永远返回同一向量（按哈希做种子），让"重嵌先清旧"那条断言不受随机性干扰。
    `calls` 记下**每一批的正文**：批大小为 1 也照样嵌得完，只有逐次页数能分辨好坏（I112 甲）。
    """

    def __init__(self, *, raise_missing: bool = False) -> None:
        self._raise = raise_missing
        self.calls: list[list[str]] = []

    def embed(self, texts: list[str]) -> np.ndarray:
        if self._raise:
            raise FileNotFoundError("语义模型不存在：…/model_int8.onnx\n请先下载 bge-small-zh-v1.5")
        self.calls.append(list(texts))
        rows = []
        for text in texts:
            rng = np.random.RandomState(abs(hash(text)) % (2 ** 32))
            vec = rng.randn(VectorStore.DIM).astype(np.float32)
            rows.append(vec / np.linalg.norm(vec))
        return np.vstack(rows) if rows else np.zeros((0, VectorStore.DIM), dtype=np.float32)


class _CountedMonitor:
    """只做 `VectorService` 会问的三件事，`cancel_after` 批之后报取消。"""

    def __init__(self, cancel_after: int | None = None) -> None:
        self.total: int | None = None
        self.done = 0
        self._cancel_after = cancel_after

    def set_total(self, total: int) -> None:
        self.total = total

    def advance(self, n: int = 1) -> None:
        self.done += n

    def cancelled(self) -> bool:
        return self._cancel_after is not None and self.done >= self._cancel_after


class StubQueryEmbedding:
    """只实现 `SemanticSearchService.search` 用到的 `embed`：任何查询都回同一条单位向量。

    下面那两条 `I111` 断言要证的是「写进缓存的向量当场读得到」，不是检索质量 ——
    库里只有那两条向量，top_k=10 一定把它们都吐回来，所以查询向量相不相干无所谓。
    """

    def embed(self, texts: list[str]) -> list[np.ndarray]:
        vec = np.zeros(VectorStore.DIM, dtype=np.float32)
        vec[0] = 1.0
        return [vec for _ in texts]


@pytest.fixture
def ctx(tmp_path: Path):
    context = bootstrap(tmp_path)
    try:
        yield context
    finally:
        context.shutdown()


def _seed(ctx: AppContext, tmp_path: Path, name: str, bodies: list[str],
          *, text_status: str = "native", source_kind: str = "native") -> int:
    """在盘上放一个真文件（`build_vectors` 会核对它还在），写入这些页正文，返回 doc_id。

    `bodies` 里空串代表"这一页本来就没字"（`char_count=0`），用来验空页不建向量。
    `source_kind="ocr"` 用来摆出"扫描件 OCR 完之后"的形状（正文来自识别，`text_status` 仍是 none）。
    """
    file = tmp_path / name
    file.write_bytes(b"%PDF-1.7 fake")
    doc = ctx.documents.upsert(Document(
        path=str(file), path_key=identity_key(str(file)), name=name,
        size_bytes=8, mtime_ns=1_760_000_000_000_000_000, sha256=f"{name!r:0<64}"[:64],
        text_status=text_status, fts_status="done"))
    doc_id = int(doc.id)
    pages = [TextPage(doc_id=doc_id, page_no=n, source_kind=source_kind,
                      body=b, char_count=len(b)) for n, b in enumerate(bodies, 1)]
    ctx.texts.replace_pages(doc_id, pages)
    return doc_id


def _fresh_vector_service(ctx: AppContext, embedding) -> VectorService:
    return VectorService(ctx.documents, ctx.texts, ctx.jobs, embedding,
                         _store(ctx))


def _store(ctx: AppContext):
    return VectorStore(ctx.paths.root)


def test_点名进队回执分开数且没正文的那份被挡在门外(ctx, tmp_path) -> None:
    """丁的入队路径：`request_vectors` 排该建的，回执指得到哪几份没排、为什么。"""
    ok = _seed(ctx, tmp_path, "可建.pdf", ["这一页有正文字"])
    gone = _seed(ctx, tmp_path, "无正文.pdf", ["正文其实没进表"], text_status="none")

    svc = _fresh_vector_service(ctx, StubEmbedding())
    receipt = svc.request_vectors([ok, gone, 999_999])

    assert receipt.named == 3, receipt.describe()
    assert receipt.queueable == 1 and receipt.enqueued == 1, receipt.describe()
    assert receipt.skipped.get(SKIP_NOT_SEARCHABLE) == [gone], receipt.skipped
    assert 999_999 in receipt.skipped["absent"], "库里没有的主记录要单独点名，不排空任务"


def test_真队列领走并跑完一条_vector_任务(ctx, tmp_path) -> None:
    """丁的调度侧：handlers 字典里那条 `"vector"` 真接上了 worker —— 排一条就会被领走跑完。"""
    doc_id = _seed(ctx, tmp_path, "调度.pdf", ["第一页正文", "第二页正文"])
    ctx.vector.embedding = StubEmbedding()          # 把真 embedding 换成桩，绕开模型
    assert ctx.jobs.enqueue("vector", doc_id) is not None

    queue = ctx.start_background()
    try:
        ticks = 0
        while ctx.documents.get(doc_id).vector_status != VECTOR_DONE:
            if ticks > 200:
                pytest.fail("worker 没把这条 vector 任务跑完（vector_status 停在 "
                            f"{ctx.documents.get(doc_id).vector_status}）")
            time.sleep(0.05)
            ticks += 1
    finally:
        queue.stop()

    assert _store(ctx).count() == 2, "两页正文该建两条向量"


def test_建完状态走到_done_且向量真落盘(ctx, tmp_path) -> None:
    """丙：`vector_status` 从 na 走到 done，且 `VectorStore.count()` 随页数增长（add_batch 真被调）。"""
    doc_id = _seed(ctx, tmp_path, "落盘.pdf", ["甲页文字", "乙页文字", "丙页文字"])
    assert ctx.documents.get(doc_id).vector_status == "na"
    store = _store(ctx)
    assert store.count() == 0

    outcome = _fresh_vector_service(ctx, StubEmbedding()).build_vectors(doc_id)

    assert outcome.vector_status == VECTOR_DONE, outcome.describe()
    assert outcome.pages_embedded == 3 and outcome.vectors_written == 3, outcome.describe()
    assert ctx.documents.get(doc_id).vector_status == VECTOR_DONE
    assert store.count() == 3, "状态说建好了、向量却没落盘，就是读数与真身不平"


def test_重嵌后页变少先清旧向量不留孤儿(ctx, tmp_path) -> None:
    """丙：`VectorStore.delete_by_doc` 在产品侧有了调用方。

    只重嵌同一页集合不足以证明它 —— `add_batch` 按 `(doc_id,page_no)` 去重，同名页会原地覆盖、
    本来就不翻倍（曾实测：删掉 `delete_by_doc` 这条断言照绿，是个假守卫）。真正只有 `delete_by_doc`
    能挡的是**页变少**：上一版有 2 页向量，这一版只剩 1 页正文，旧的第 2 页向量是孤儿，
    语义搜索会命中一个已经没有正文的页。清旧在前，孤儿才不存在。
    """
    doc_id = _seed(ctx, tmp_path, "重嵌.pdf", ["第一页正文", "第二页正文"])
    store = _store(ctx)

    _fresh_vector_service(ctx, StubEmbedding()).build_vectors(doc_id)
    assert store.count() == 2, store.count()

    # 正文缩到一页（模拟重新索引后页数变少），再建一次。
    ctx.texts.replace_pages(doc_id, [TextPage(doc_id=doc_id, page_no=1, source_kind="native",
                                              body="只剩这一页", char_count=len("只剩这一页"))])
    _fresh_vector_service(ctx, StubEmbedding()).build_vectors(doc_id)

    assert store.count() == 1, (f"旧的第 2 页向量成了孤儿（应为 1，实得 {store.count()}）："
                                "语义搜索会命中一个已经没有正文的页")


def test_模型没装写_failed_并把原文留在_last_error(ctx, tmp_path) -> None:
    """不许伪装成功：模型缺失当场 `failed` + 原文，不写 done，也不停在 na。"""
    doc_id = _seed(ctx, tmp_path, "缺模型.pdf", ["这一页有字"])

    with pytest.raises(PermanentFailure):
        _fresh_vector_service(ctx, StubEmbedding(raise_missing=True)).build_vectors(doc_id)

    doc = ctx.documents.get(doc_id)
    assert doc.vector_status == VECTOR_FAILED, doc.vector_status
    assert "model_int8.onnx" in (doc.last_error or ""), doc.last_error
    assert _store(ctx).count() == 0, "建失败却留了向量就是半个库"


def test_没正文的那份拒绝建且状态一个字节不动(ctx, tmp_path) -> None:
    """没可搜的正文就没东西可嵌：`build_vectors` 直接拒，状态不停在"跑了一半"的任何值。"""
    doc_id = _seed(ctx, tmp_path, "没索引.pdf", ["表里有行但没索引过"], text_status="none")

    with pytest.raises(PermanentFailure, match="先索引"):
        _fresh_vector_service(ctx, StubEmbedding()).build_vectors(doc_id)

    assert ctx.documents.get(doc_id).vector_status == "na"


def test_OCR_出过正文的扫描件也能建向量(ctx, tmp_path) -> None:
    """**ISSUES I116** 甲：入场券问「有没有可搜的正文」，不是「有没有原生正文」。

    OCR 的唯一写入口 `mark_ocr_result` 不碰 `text_status`（那一列的口径是「有没有**原生**正文」，
    `parsing/classify.py` 那张表），所以 OCR 完的扫描件是 `text_status=none｜ocr_status=done`，
    而它的正文确实在 `text_pages` 里、全文搜索也搜得到。按 `text_status` 判就把这类书永久挡在
    语义搜索之外 —— 真库 doc 10995 / 10997（497 页）2026-10-27 当场就是这么被拒的。
    """
    doc_id = _seed(ctx, tmp_path, "扫描件.pdf", ["识别出来的第一页", "识别出来的第二页"],
                   text_status="none", source_kind="ocr")
    ctx.documents.mark_ocr_result(doc_id, ocr_status="done", ocr_pages_done=2)

    svc = _fresh_vector_service(ctx, StubEmbedding())
    receipt = svc.request_vectors([doc_id])
    assert receipt.queueable == 1 and not receipt.skipped, receipt.describe()

    outcome = svc.build_vectors(doc_id)

    assert outcome.vector_status == VECTOR_DONE, outcome.describe()
    assert outcome.pages_embedded == 2 and outcome.vectors_written == 2, outcome.describe()
    assert _store(ctx).count() == 2, "OCR 正文没进语义索引 ⇒ 扫描件的语义搜索永远到不了"


def test_入场券两个条件任一成立即放行(ctx) -> None:
    """谓词本身：`text_status` 原生/混合，或 OCR 已产出正文（done/partial）—— 任一成立即放行。

    这条单独钉判据本身，不靠上一条的端到端结果反推；`partial` 必须算有正文，
    否则"236 页里有两页识别失败"的书又会被挡在门外。
    """
    cases = [("native", "na", True), ("mixed", "na", True),
             ("none", "done", True), ("none", "partial", True), ("pending", "done", True),
             ("none", "na", False), ("none", "pending", False), ("none", "failed", False),
             ("failed", "failed", False)]
    wrong = [(t, o) for t, o, want in cases
             if has_searchable_text(Document(text_status=t, ocr_status=o)) is not want]
    assert not wrong, f"这些 text_status / ocr_status 组合判错了：{wrong}"


def test_空正文页不建向量(ctx, tmp_path) -> None:
    """口径 6：`char_count=0` 的页跳过，与"这一页本来就没字"同一件事。"""
    doc_id = _seed(ctx, tmp_path, "半空.pdf", ["有字的页", "", "也有字"])

    outcome = _fresh_vector_service(ctx, StubEmbedding()).build_vectors(doc_id)

    assert outcome.pages_expected == 3
    assert outcome.pages_skipped_empty == 1 and outcome.pages_embedded == 2, outcome.describe()
    assert _store(ctx).count() == 2, "空页建了向量 = 往语义索引塞一条谁都不该命中的行"


def test_装配层只有一只_vector_store_三个消费者共用(ctx) -> None:
    """**ISSUES I111** 丁：把「同一进程只许一只 `VectorStore`」钉成断言，防止再长回两只。

    I112 乙 之后 `VectorStore` 已经不再缓存向量数组与 `_next_idx`（`used` 每次现读库、
    文件现开现关），所以"两只实例互相看不见"那个后果不复存在；这条留作**结构**判据：
    两个写者会撞在同一份 `MAX(vector_idx)` 上分索引，装配层只该有一只。
    """
    writer = ctx.vector.vector_store
    assert ctx.semantic_search._vectors is writer, (
        "语义搜索自己 new 了一只 VectorStore —— 装配层只该有一只（ISSUES I111 丁）")
    assert ctx.ai_classify._vectors is writer, "AI 分类建议用的不是写路径那一只"


def test_装配层_embedding_只有一份三个消费者共用(ctx) -> None:
    """**ISSUES I111** ⑤：查询向量与建向量共用同一只 `EmbeddingService`。

    每份 `EmbeddingService` 独占一个 ONNX session。2026-10-25 实测第二份的代价
    （`.probe_work/u27_embedding_two_instances.log`）：+36.2 MiB RSS、+9 句柄、
    整机显存 +约 200 MiB（DirectML）、懒加载 276 ms；而两个实例对同一批文本的输出
    `max|Δ|=0.000e+00` —— 多养一份换不到任何东西。
    """
    loader = ctx.vector.embedding
    assert ctx.semantic_search._embedding is loader, (
        "语义搜索另养了一个 EmbeddingService —— 同一进程只该加载一次模型（ISSUES I111 ⑤）")
    assert ctx.ai_classify._embedding is loader, "AI 分类建议另养了一个 EmbeddingService"


def test_建完向量同一场会话当场搜得到(ctx, tmp_path) -> None:
    """**ISSUES I111** 甲 的用户可见后果：不必重启。

    先把读侧缓存锁成"空"（本场第一次搜索 —— 这就是真实用户点开搜索框的那一下），
    再走**产品写路径**建向量，然后同一条查询必须命中。修之前的实测
    （`.probe_work/u26_i111_proof.log` B 段，逐字）：写前 0 命中｜写后**同一只实例**仍 0 命中｜
    而它自己的 `count()` 已经报 3｜换一只新实例同一条查询 3 命中。
    """
    doc_id = _seed(ctx, tmp_path, "当场搜得到.pdf", ["第一页正文", "第二页正文"])
    ctx.vector.embedding = StubEmbedding()
    ctx.semantic_search._embedding = StubQueryEmbedding()

    assert ctx.semantic_search.search("任何查询") == [], "第一次搜索本应是空的（库里还没有向量）"

    ctx.vector.build_vectors(doc_id)

    hits = ctx.semantic_search.search("任何查询", top_k=10)
    assert sorted((int(d), int(p)) for d, p, _ in hits) == [(doc_id, 1), (doc_id, 2)], (
        f"建完 {ctx.semantic_search.count()} 条向量后同一场会话搜不到（hits={hits}）"
        "—— 读侧那只 VectorStore 又不是写侧那一只")


def test_一次前向吞一批而不是逐页单条(ctx, tmp_path) -> None:
    """**ISSUES I112** 甲：批大小跟着模型走（`EmbeddingService.BATCH_SIZE=16`）。

    判据是**每次调用喂了几页**：逐页 `embed_single` 也能把 40 页嵌完，只有调用形状能分辨 ——
    同一批 549 页的真库实测是逐页 28.48 页/s、批 16 页 72.86 页/s。
    """
    bodies = [f"第 {n} 页正文" for n in range(1, 41)]
    doc_id = _seed(ctx, tmp_path, "批量.pdf", bodies)
    stub = StubEmbedding()

    outcome = _fresh_vector_service(ctx, stub).build_vectors(doc_id)

    sizes = [len(batch) for batch in stub.calls]
    assert sizes == [16, 16, 8], f"实际每批页数 {sizes}：逐页调用等于每次只喂模型 1 页"
    assert [t for batch in stub.calls for t in batch] == bodies, "批处理打乱了页序"
    assert outcome.pages_embedded == 40 and outcome.vectors_written == 40, outcome.describe()
    assert _store(ctx).count() == 40


def test_取消按批生效且不落半截向量(ctx, tmp_path) -> None:
    """**ISSUES I112** 甲 改了循环仍要能停：第 2 批前取消 → `stale`、一条向量都不落盘。

    旧形状逐页检查取消；新形状每批检查一次。把检查挪出循环、或让每批直接落盘，这条就红。
    """
    bodies = [f"第 {n} 页正文" for n in range(1, 41)]
    doc_id = _seed(ctx, tmp_path, "取消.pdf", bodies)
    monitor = _CountedMonitor(cancel_after=16)

    with pytest.raises(JobCancelled, match="16/40"):
        _fresh_vector_service(ctx, StubEmbedding()).build_vectors(doc_id, monitor)

    assert monitor.total == 40, "取消前要把总页数报给队列，否则进度停在 0/0 像卡死"
    assert ctx.documents.get(doc_id).vector_status == VECTOR_STALE
    assert _store(ctx).count() == 0, "停在半路却落了一半向量，下次搜索会命中半份文档"


def test_追加不重写整份向量文件(ctx, tmp_path) -> None:
    """**ISSUES I112** 乙：容量够时新增只写新行，文件大小不动。

    老写法每批都 `np.vstack` + `np.save` 整份重写（满库累计 5.06 TiB 写放大）。判据取
    「文件大小不变而 `count()` 增加」：`np.save` 写出的文件行数等于真实行数，
    第二批一进来大小必然变 —— 这条能分辨两种形状，不是只数了个数。
    """
    doc = _seed(ctx, tmp_path, "追加.pdf", ["第一页正文"])
    store = _store(ctx)
    vec = np.zeros(VectorStore.DIM, dtype=np.float32)
    vec[0] = 1.0
    store.add_batch([(doc, n + 1, vec) for n in range(3)])
    path = ctx.paths.data_dir / "vectors.npy"
    size_before = path.stat().st_size
    assert store.count() == 3

    store.add_batch([(doc, 4, vec), (doc, 5, vec)])

    assert store.count() == 5
    assert path.stat().st_size == size_before, (
        f"只加了 2 行，文件却从 {size_before} 变成 {path.stat().st_size} —— 整份又重写了一遍")
    assert int(np.load(path, mmap_mode="r").shape[0]) >= 5


def test_扩容搬旧行且翻倍(ctx, tmp_path) -> None:
    """**ISSUES I112** 乙：容量满了扩一次，已有的行必须原样搬过去、新行必须写得进去。"""
    doc = _seed(ctx, tmp_path, "扩容.pdf", ["第一页正文"])
    store = _store(ctx)
    vec = np.zeros(VectorStore.DIM, dtype=np.float32)
    vec[0] = 1.0

    store.add_batch([(doc, n + 1, vec) for n in range(DEFAULT_CAPACITY)])
    assert store.count() == DEFAULT_CAPACITY

    # 第 1025 行才触发扩容 —— 必须是在**已有 1024 行**的前提下扩，才照得到"搬旧行"。
    store.add_batch([(doc, DEFAULT_CAPACITY + 1, vec)])

    path = ctx.paths.data_dir / "vectors.npy"
    capacity = int(np.load(path, mmap_mode="r").shape[0])
    assert capacity == DEFAULT_CAPACITY * 2, f"容量应翻倍，实际 {capacity}"
    kept = store.get_vectors()
    assert kept.shape[0] == DEFAULT_CAPACITY + 1, "used 行数不对"
    assert int(kept[0][0]) == 127 and int(kept[-1][0]) == 127, (
        f"扩容把旧行搬丢了（首行首值 {int(kept[0][0])}），或新行没写进去")


def test_另一只实例写进去的向量本只立刻看得见(ctx, tmp_path) -> None:
    """**ISSUES I111** ① / **ISSUES I112** 乙 规矩 2：不共用实例也看得见。

    I111 甲 修的是「同一进程两只实例互看不见」，靠共用一只实例绕开；这条反过来钉住存储层
    自己：A 先搜一次（老写法会把缓存锁成空），B 再写，A 必须当场命中。`used` 现读库、
    文件现开现关之后，跨进程（门禁与界面同开一个数据根）没有别的分支可走。
    """
    doc = _seed(ctx, tmp_path, "两只实例.pdf", ["第一页正文"])
    reader = _store(ctx)
    writer = _store(ctx)
    query = np.zeros(VectorStore.DIM, dtype=np.float32)
    query[0] = 1.0
    assert reader.search(query) == [], "写之前本该是空的"

    writer.add(doc, 1, query)

    hits = reader.search(query)
    assert [(int(d), int(p)) for d, p, _ in hits] == [(doc, 1)], (
        f"另一只实例写入后这只仍看不到（hits={hits}）—— 实例级缓存又长回来了")


def test_孤儿_doc_id_插不进元数据(ctx) -> None:
    """**ISSUES I111** D：连接打开 `PRAGMA foreign_keys=ON`，迁移 0007 声明的 FK 才真的执行。

    修之前这条插得进去（临时库实测 `vector_meta 5 行｜库里 0 份文档`），而孤儿行永远没人清，
    13 项体检里也没有 `vectors.npy` ⇄ `vector_meta` 的对账项。
    """
    store = _store(ctx)
    vec = np.zeros(VectorStore.DIM, dtype=np.float32)
    vec[0] = 1.0

    with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
        store.add(999_999, 1, vec)

    assert store.count() == 0, "FK 拒了插入却留下了元数据"


# 上面两条 `I111` 断言的坏法实测（2026-10-25，三条都真注入过再还原，逐字结果）：
#   坏法 1｜`bootstrap.py` 那句改回 `SemanticSearchService(paths.root)`（不注入）
#          ⇒ **2 failed, 7 passed**，两条都红：结构那条红在「语义搜索自己 new 了一只 VectorStore」，
#             行为那条红在 `AssertionError: 建完 2 条向量后同一场会话搜不到（hits=[]）`。
#   坏法 2｜只把 `search_service.py` 的 `vector_store or VectorStore(...)` 改成恒自建（忽略注入参数）
#          ⇒ 同样两条都红、红字逐字相同 —— 接线的两端（装配 + 构造）任一处断掉都会显形。
#   坏法 3｜把 `ai_classify` 那只换成另 new 的 `VectorStore(paths.root)`
#          ⇒ **1 failed, 8 passed**，只红在第二条「AI 分类建议用的不是写路径那一只」，
#             行为那条照绿 —— 证明两条断言各查各的，不是同一条的两次复读。
# 乙（写后撤缓存）在甲落地后进程内已无对应分支：`add`／`add_batch` 会把新数组写回**同一只**实例
# （`vector_store.py:116`／`:170`），所以没有为它写代码；跨进程的陈旧缓存留在 ISSUES I111 的残留里。
#
# `I112` 甲 两条新断言（2026-10-25 轮二十七，两条都真注入过再还原）：
#   坏法 4｜同批 16 页仍写成 `[self.embedding.embed([p.body])[0] for p in chunk]`（逐页调用，
#          页数、页序、条数全对，只有调用形状退化）⇒ **1 failed, 10 passed**，
#          红在 `实际每批页数 [1, 1, …]` —— 证明判据咬的是前向形状本身。
#   坏法 5｜把取消检查改成只在 `start == 0` 时问（等价于挪到循环外）⇒ 同样 **1 failed, 10 passed**，
#          红在 `DID NOT RAISE JobCancelled` —— 证明"每批都问"不是装饰。
#
# `I112` 乙 / `I111` D 四条新断言（2026-10-25 轮二十七，四条都真注入过再还原）：
#   坏法 6｜`_write_rows` 写完追加一行 `np.save(self._vectors_path, np.array(mapped[:need]))`
#          （等价于老路：整份重写、文件行数等于真实行数）⇒ **1 failed, 14 deselected**，
#          红在 `只加了 2 行，文件却从 524416 变成 …`。
#   坏法 7｜扩容时 `if old is not None and False and used:`（不搬旧行）⇒ **1 failed**，
#          红在 `扩容把旧行搬丢了（首行首值 0）` —— 第一版测试只塞一批 1025 行照不到它
#          （那次注入是绿的，测试当场改成"先 1024 再 1"）。
#   坏法 8｜`search()` 里把 used 缓存到实例上（`self._cached_used`）⇒ **1 failed**，
#          红在 `另一只实例写入后这只仍看不到（hits=[]）`。
#   坏法 9｜`_connect()` 去掉 `PRAGMA foreign_keys=ON` ⇒ **1 failed**，
#          红在 `DID NOT RAISE IntegrityError`。
#
# `I111` ⑤ 一条新断言（2026-10-25 轮二十七，两条坏法各自真注入过再还原）：
#   坏法 10｜`bootstrap.py` 改回 `SemanticSearchService(paths.root, vector_store)`（语义搜索自建 embedding）
#          ⇒ **1 failed, 15 passed**，红在 `语义搜索另养了一个 EmbeddingService`。
#   坏法 11｜`ai_classify` 那只改成 `AIClassifyService(…, EmbeddingService(paths.root), …)`
#          ⇒ 同样 **1 failed, 15 passed**，红在第二句 `AI 分类建议另养了一个 EmbeddingService`
#          —— 两句断言各查一个消费者，不是同一条的两次复读。
#
# `I116` 甲 两条新断言（2026-10-28 轮三十三，坏法真注入过再还原）：
#   坏法 12｜`index_service.has_searchable_text` 改回只看原生正文
#          （`return doc.text_status in TEXT_SEARCHABLE`）⇒ **2 failed, 16 passed**，
#          一条红在 `OCR 正文没进语义索引 ⇒ 扫描件的语义搜索永远到不了`（端到端），
#          一条红在 `这些 text_status / ocr_status 组合判错了：[('none','done'), ('none','partial'), ('pending','done')]`
#          （谓词四象限）—— 两条各钉一层，不是同一句话的两次复读。

