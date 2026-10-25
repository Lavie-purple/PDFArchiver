"""向量存储测试。"""
import numpy as np
import pytest
from pathlib import Path

from pdfarchiver.db.models import Document
from pdfarchiver.semantic.vector_store import VectorStore


def _make_doc(ctx, path_key: str, name: str, sha256: str, device_id: int, file_id: int, page_count: int) -> int:
    """创建测试文档并返回 doc_id。"""
    doc = Document(
        path=f"C:/test/{name}",
        path_key=path_key,
        name=name,
        ext="pdf",
        size_bytes=1000,
        mtime_ns=1000000000,
        ctime_ns=1000000000,
        file_id=file_id,
        device_id=device_id,
        sha256=sha256,
        page_count=page_count,
        text_bearing_rate=0.8,
        is_pdf=1,
        needs_pass=0,
        is_repaired=0,
        parse_status="ok",
        text_status="native",
        ocr_status="na",
        ocr_pages_done=0,
        fts_status="done",
        vector_status="done",
        category_confirmed=0,
        last_scanned_at=1000000,
        last_indexed_at=1000000,
        missing_since=None,
    )
    saved = ctx.documents.upsert(doc)
    return saved.id


@pytest.fixture
def vector_store(ctx) -> VectorStore:
    """用测试上下文的数据根。"""
    return VectorStore(ctx.paths.root)


def test_add_and_search(vector_store: VectorStore, ctx) -> None:
    """添加向量后能搜到。"""
    # 创建测试文档
    doc_id = _make_doc(ctx, "test/doc1.pdf", "doc1.pdf", "a" * 64, 1, 1, 1)

    # 添加向量
    vector = np.random.randn(512).astype(np.float32)
    vector = vector / np.linalg.norm(vector)
    idx = vector_store.add(doc_id, 1, vector)
    assert idx >= 0

    # 搜索应该能找到自己
    results = vector_store.search(vector, top_k=1)
    assert len(results) == 1
    assert results[0][0] == doc_id
    assert results[0][1] == 1
    # int8 量化会损失精度，0.9 已经是很高的相似度
    assert results[0][2] > 0.9


def test_add_batch(vector_store: VectorStore, ctx) -> None:
    """批量添加。"""
    doc_id = _make_doc(ctx, "test/doc2.pdf", "doc2.pdf", "b" * 64, 1, 2, 3)

    items = [
        (doc_id, i, np.random.randn(512).astype(np.float32))
        for i in range(3)
    ]
    # 归一化
    items = [(d, p, v / np.linalg.norm(v)) for d, p, v in items]

    indices = vector_store.add_batch(items)
    assert len(indices) == 3
    assert vector_store.count() >= 3


def test_delete_by_doc(vector_store: VectorStore, ctx) -> None:
    """删除文档的向量。"""
    doc_id = _make_doc(ctx, "test/doc3.pdf", "doc3.pdf", "c" * 64, 1, 3, 2)

    vector_store.add(doc_id, 1, np.random.randn(512).astype(np.float32))
    vector_store.add(doc_id, 2, np.random.randn(512).astype(np.float32))

    deleted = vector_store.delete_by_doc(doc_id)
    assert deleted == 2


def test_search_empty(vector_store: VectorStore) -> None:
    """空库搜索返回空列表。"""
    query = np.random.randn(512).astype(np.float32)
    results = vector_store.search(query, top_k=10)
    assert results == []


def test_search_returns_top_k(vector_store: VectorStore, ctx) -> None:
    """搜索返回 top_k 个结果。"""
    doc_id = _make_doc(ctx, "test/doc4.pdf", "doc4.pdf", "d" * 64, 1, 4, 5)

    # 添加 5 个向量
    for i in range(5):
        vector = np.random.randn(512).astype(np.float32)
        vector_store.add(doc_id, i + 1, vector / np.linalg.norm(vector))

    # 搜索 top 3
    query = np.random.randn(512).astype(np.float32)
    results = vector_store.search(query / np.linalg.norm(query), top_k=3)
    assert len(results) == 3


def test_count(vector_store: VectorStore, ctx) -> None:
    """计数正确。"""
    initial = vector_store.count()

    doc_id = _make_doc(ctx, "test/doc5.pdf", "doc5.pdf", "e" * 64, 1, 5, 2)

    vector_store.add(doc_id, 1, np.random.randn(512).astype(np.float32))
    vector_store.add(doc_id, 2, np.random.randn(512).astype(np.float32))

    assert vector_store.count() == initial + 2


def test_删过向量的文档不占满命中名额(vector_store: VectorStore, ctx) -> None:
    """**ISSUES I111** ⑥ 甲：`delete_by_doc` 只删元数据，死行仍参与打分。

    死行分数排进前 `top_k` 时会被回查元数据那一步静默跳过 —— 用户设 2 条只看到 1 条，
    屏幕上没有任何提示。修法是先按 `used - COUNT(*)` 数出死行，取 `top_k + 死行数` 个候选。
    坏法：把 `want` 改回 `top_k`（等于删掉这处修复）⇒ 本条报 `应为 2 条，实得 1`。
    """
    keep_a = _make_doc(ctx, "test/keep_a.pdf", "keep_a.pdf", "1" * 64, 1, 11, 1)
    dead = _make_doc(ctx, "test/dead.pdf", "dead.pdf", "2" * 64, 1, 12, 1)
    keep_b = _make_doc(ctx, "test/keep_b.pdf", "keep_b.pdf", "3" * 64, 1, 13, 1)

    def unit(pos: int) -> np.ndarray:
        vec = np.zeros(VectorStore.DIM, dtype=np.float32)
        vec[pos] = 1.0
        return vec

    vector_store.add(keep_a, 1, unit(0))
    vector_store.add(dead, 1, unit(0))      # 与查询完全同向：删掉后它是分数最高的死行
    vector_store.add(keep_b, 1, unit(1))

    assert vector_store.delete_by_doc(dead) == 1
    assert vector_store.count() == 2, "元数据里只剩两份活文档"

    results = vector_store.search(unit(0), top_k=2)

    assert len(results) == 2, f"死行吃掉命中名额：应为 2 条，实得 {len(results)}"
    assert {doc_id for doc_id, _page, _score in results} == {keep_a, keep_b}
