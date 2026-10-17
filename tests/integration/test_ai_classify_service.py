"""AIClassifyService 测试 —— 钉住 ISSUES I63 乙：空表与有表两路，以及 vector_indices_for_doc 的 r[0] 修法。

ISSUES I63 现测（2026-10-17）：AIClassifyService 零测试，`vector_indices_for_doc` 的 `r["vector_idx"]`
在默认 row_factory 下必 TypeError，只有在 vector_meta 有行时才走到 —— 而产品里没有生产者，所以这条
崩溃今天触发不了；它属于"等第一个接生产者的人踩"，本轮顺手修了（改成 `r[0]`），且没有测试覆盖。

本测试集钉住三件事：
1. `_build_centers` 空表路径：vector_meta 无数据时返回空 dict，不崩
2. `_build_centers` 有表路径：有向量数据时能算出分类中心
3. `vector_indices_for_doc` 的 `r[0]` 修法不再退化：默认 row_factory 下按索引取不 TypeError
"""
from __future__ import annotations

import numpy as np
import pytest
from pathlib import Path

from pdfarchiver.db.models import Document
from pdfarchiver.semantic.classify_service import AIClassifyService
from pdfarchiver.semantic.embedding import EmbeddingService
from pdfarchiver.services.bootstrap import AppContext, bootstrap


class MockEmbedding(EmbeddingService):
    """模拟 embedding 服务（用随机向量代替真模型，避免加载 ONNX）。"""
    def __init__(self):
        self._dim = 512  # VectorStore.DIM = 512

    @property
    def dim(self) -> int:
        return self._dim

    def embed_single(self, text: str) -> np.ndarray:
        # 用文本哈希当种子，保证同一文本返回同一向量
        rng = np.random.RandomState(hash(text) % (2**32))
        vec = rng.randn(self._dim).astype(np.float32)
        return vec / np.linalg.norm(vec)

    def embed_batch(self, texts: list[str]) -> np.ndarray:
        return np.stack([self.embed_single(t) for t in texts])

    def unload(self) -> None:
        pass


@pytest.fixture
def ctx(tmp_path: Path) -> AppContext:
    """用 bootstrap 初始化上下文（自动跑迁移）。"""
    context = bootstrap(tmp_path)
    try:
        yield context
    finally:
        context.shutdown()


def test_build_centers_空表返回空dict(ctx: AppContext):
    """ISSUES I63 乙：vector_meta 无数据时 `_build_centers` 返回空 dict，不崩。"""
    # 直接用 ctx.ai_classify，它的 embedding 是真实的 EmbeddingService
    # 但我们用 mock 替换它以避免加载 ONNX 模型
    from pdfarchiver.semantic.vector_store import VectorStore
    from pdfarchiver.semantic.embedding import EmbeddingService
    
    mock_embedding = MockEmbedding()
    vector_store = VectorStore(ctx.paths.root)
    service = AIClassifyService(ctx.catalog, ctx.documents, mock_embedding, vector_store)

    # 创建一个分类，但没有文档也没有向量
    cat_id = ctx.catalog.add_category("测试分类", parent_id=None)
    assert cat_id is not None

    centers = service._build_centers()
    assert centers == {}, "没有向量数据时应该返回空 dict"


def test_build_centers_有表路径能算出中心(ctx: AppContext):
    """ISSUES I63 乙：有向量数据时能算出分类中心。"""
    from pdfarchiver.semantic.vector_store import VectorStore
    
    mock_embedding = MockEmbedding()
    vector_store = VectorStore(ctx.paths.root)
    service = AIClassifyService(ctx.catalog, ctx.documents, mock_embedding, vector_store)

    # 创建分类
    cat = ctx.catalog.add_category("财务", parent_id=None)

    # 创建文档并加入分类
    doc1 = Document(
        path="D:\\docs\\发票1.pdf", path_key="d:\\docs\\发票1.pdf",
        name="发票1.pdf", size_bytes=1000, sha256="a" * 64,
        text_status="done", fts_status="done")
    doc1_result = ctx.documents.upsert(doc1)
    ctx.catalog.link_category(doc1_result.id, cat.id)

    doc2 = Document(
        path="D:\\docs\\发票2.pdf", path_key="d:\\docs\\发票2.pdf",
        name="发票2.pdf", size_bytes=2000, sha256="b" * 64,
        text_status="done", fts_status="done")
    doc2_result = ctx.documents.upsert(doc2)
    ctx.catalog.link_category(doc2_result.id, cat.id)

    # 给文档加向量（add_batch 要求 float32，内部量化为 int8 存储）
    vec1 = mock_embedding.embed_single("发票1")
    vec2 = mock_embedding.embed_single("发票2")
    vector_store.add_batch([
        (doc1_result.id, 0, vec1),
        (doc2_result.id, 0, vec2),
    ])

    centers = service._build_centers()
    assert cat.id in centers, "有向量数据的分类应该在 centers 里"
    assert centers[cat.id].shape == (512,), f"中心向量维度应该是 512，实际 {centers[cat.id].shape}"


def test_vector_indices_for_doc_默认row_factory不崩(ctx: AppContext):
    """ISSUES I63 乙：钉住 `vector_indices_for_doc` 的 `r[0]` 修法。

    默认 row_factory 是元组，按名字 `r["vector_idx"]` 取会 TypeError。
    这条测试钉住修法不再退化。
    """
    from pdfarchiver.semantic.vector_store import VectorStore
    
    vector_store = VectorStore(ctx.paths.root)
    
    # 加两条向量（维度必须匹配 VectorStore.DIM = 512，类型必须是 float32）
    vec = np.random.randn(512).astype(np.float32)
    vector_store.add_batch([
        (1, 0, vec),
        (1, 1, vec),
        (2, 0, vec),
    ])

    # doc_id=1 应该有 2 个索引（page 0 和 1）
    indices = vector_store.vector_indices_for_doc(1)
    assert sorted(indices) == [0, 1], f"doc_id=1 应该有索引 [0, 1]，实际 {indices}"

    # doc_id=2 应该有 1 个索引（page 0），全局索引是 2（前两个给了 doc_id=1）
    indices = vector_store.vector_indices_for_doc(2)
    assert indices == [2], f"doc_id=2 应该有索引 [2]，实际 {indices}"

    # doc_id=999 不存在，应该返回空列表
    indices = vector_store.vector_indices_for_doc(999)
    assert indices == [], f"不存在的 doc_id 应该返回空列表，实际 {indices}"


def test_suggest_无向量数据返回空列表(ctx: AppContext):
    """ISSUES I63 戊的前置：无向量数据时 suggest 返回空列表，UI 应显示空态提示。"""
    from pdfarchiver.semantic.vector_store import VectorStore
    
    mock_embedding = MockEmbedding()
    vector_store = VectorStore(ctx.paths.root)
    service = AIClassifyService(ctx.catalog, ctx.documents, mock_embedding, vector_store)

    # 创建分类但没有向量
    ctx.catalog.add_category("测试分类", parent_id=None)

    suggestions = service.suggest("测试文本")
    assert suggestions == [], "无向量数据时应该返回空列表"


def test_suggest_for_doc_文档不存在返回空列表(ctx: AppContext):
    """边界条件：doc_id 不存在时返回空列表。"""
    from pdfarchiver.semantic.vector_store import VectorStore
    
    mock_embedding = MockEmbedding()
    vector_store = VectorStore(ctx.paths.root)
    service = AIClassifyService(ctx.catalog, ctx.documents, mock_embedding, vector_store)

    suggestions = service.suggest_for_doc(999)
    assert suggestions == [], "不存在的 doc_id 应该返回空列表"
