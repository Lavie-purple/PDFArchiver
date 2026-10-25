"""向量写路径 —— 钉住 **ISSUES I63** 丙 + 丁：`VectorStore.add*` 真有产品调用方、
`"vector"` 任务真能入队并被 worker 调度、`vector_status` 真有人推进。

入账之前这一层在仓库里的形状（**ISSUES I63** 现测）：`VectorStore.add / add_batch /
delete_by_doc` 在 `src/` 下零产品调用方（只有 `gates/stage6.py` 夹具用），`jobs.KINDS` 里
的 `"vector"` 从不入队，`vector_status` 恒为 `Document` 默认值 `na`。于是 p12 C7「向量状态
取值都在口径内」恒绿，但那个绿只是"全都停在初始值"的读数，不是判定。

这九条各自钉住一个会坏的地方：

1. **点名进队（丁的入队路径）**：`request_vectors` 把该建的排进队列，回执分开数 `named /
   queueable / enqueued`，没正文的那份当场被挡在门外并指到具体 doc_id。
2. **worker 真调度（丁的调度侧）**：起一条**真** `WorkQueue`，排一条 `"vector"` 任务，
   它必须被领走并跑完 —— 证明 `bootstrap` 的 handlers 字典里那条 `"vector"` 接上了。
3. **成功推进 + 向量真落盘（丙）**：`build_vectors` 之后 `vector_status` 从 `na` 走到 `done`，
   且 `VectorStore.count()` 随页数增长 —— 比只数状态更能证明 `VectorStore.add_batch` 真被调了。
4. **重嵌先清旧向量（丙的 `delete_by_doc` 调用方）**：连建两次，向量总数不翻倍。
5. **模型没装不许伪装成功**：`embed_single` 抛 `FileNotFoundError` 时写 `failed` + 原文进
   `last_error`，绝不写 `done`，也绝不停在 `na`（"跑不了"≠"没跑"）。
6. **没正文不建空向量**：`text_status` 不在 `TEXT_SEARCHABLE` 的那份直接拒，状态一个字节不动。
7. **空正文页跳过**：`char_count=0` 的那一页不塞进语义索引 —— 与"这一页本来就没字"同一件事。
8. **全进程只许一只 `VectorStore`（**ISSUES I111** 丁）**：装配层把同一只实例注入读侧、写侧与
   AI 分类建议。这条是结构判据，防的是"再长回两只"。
9. **建完当场搜得到，不必重启（**ISSUES I111** 甲的用户可见后果）**：先搜一次把读侧缓存锁成空，
   再走写路径建向量，同一场会话里必须立刻搜得到 —— 修之前这一段是 0 命中。

跑法：
    .venv/Scripts/python.exe -m pytest tests/integration/test_vector_write_path.py -q
"""
from __future__ import annotations

import time
from pathlib import Path

import numpy as np
import pytest

from pdfarchiver.db.models import Document, TextPage
from pdfarchiver.fs.identity import identity_key
from pdfarchiver.jobs.queue import PermanentFailure
from pdfarchiver.semantic.vector_store import VectorStore
from pdfarchiver.services.bootstrap import AppContext, bootstrap
from pdfarchiver.services.vector_service import (
    SKIP_NOT_SEARCHABLE, VECTOR_DONE, VECTOR_FAILED, VectorService)


class StubEmbedding:
    """把"这一页正文"换成一个确定向量，绕开 ONNX 模型（模型在 CI 上不存在）。

    只实现 `VectorService` 用到的 `embed_single` —— 契约就是那一个方法，不假装是完整引擎。
    同一文本永远返回同一向量（按哈希做种子），让"重嵌先清旧"那条断言不受随机性干扰。
    """

    def __init__(self, *, raise_missing: bool = False) -> None:
        self._raise = raise_missing
        self.calls: list[str] = []

    def embed_single(self, text: str) -> np.ndarray:
        if self._raise:
            raise FileNotFoundError("语义模型不存在：…/model_int8.onnx\n请先下载 bge-small-zh-v1.5")
        self.calls.append(text)
        rng = np.random.RandomState(abs(hash(text)) % (2 ** 32))
        vec = rng.randn(512).astype(np.float32)
        return vec / np.linalg.norm(vec)


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
          *, text_status: str = "native") -> int:
    """在盘上放一个真文件（`build_vectors` 会核对它还在），写入这些页正文，返回 doc_id。

    `bodies` 里空串代表"这一页本来就没字"（`char_count=0`），用来验空页不建向量。
    """
    file = tmp_path / name
    file.write_bytes(b"%PDF-1.7 fake")
    doc = ctx.documents.upsert(Document(
        path=str(file), path_key=identity_key(str(file)), name=name,
        size_bytes=8, mtime_ns=1_760_000_000_000_000_000, sha256=f"{name!r:0<64}"[:64],
        text_status=text_status, fts_status="done"))
    doc_id = int(doc.id)
    pages = [TextPage(doc_id=doc_id, page_no=n, source_kind="native",
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


def test_空正文页不建向量(ctx, tmp_path) -> None:
    """口径 6：`char_count=0` 的页跳过，与"这一页本来就没字"同一件事。"""
    doc_id = _seed(ctx, tmp_path, "半空.pdf", ["有字的页", "", "也有字"])

    outcome = _fresh_vector_service(ctx, StubEmbedding()).build_vectors(doc_id)

    assert outcome.pages_expected == 3
    assert outcome.pages_skipped_empty == 1 and outcome.pages_embedded == 2, outcome.describe()
    assert _store(ctx).count() == 2, "空页建了向量 = 往语义索引塞一条谁都不该命中的行"


def test_装配层只有一只_vector_store_三个消费者共用(ctx) -> None:
    """**ISSUES I111** 丁：把「同一进程只许一只 `VectorStore`」钉成断言，防止再长回两只。

    向量缓存（`_vectors` 那条 numpy 数组与 `_next_idx`）是**每只实例自己的**，所以两只实例
    等于两份互不知情的账：读的那只看不见写的那只刚落盘的东西。坏法实测见本文件末尾的注。
    """
    writer = ctx.vector.vector_store
    assert ctx.semantic_search._vectors is writer, (
        "语义搜索自己 new 了一只 VectorStore —— 它的向量缓存不会被写路径刷新，"
        "刚建好的向量在同一场会话里永远搜不到（ISSUES I111）")
    assert ctx.ai_classify._vectors is writer, "AI 分类建议用的不是写路径那一只"


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

