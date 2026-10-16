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
        parse_status="done",
        text_status="done",
        ocr_status="na",
        ocr_pages_done=0,
        fts_status="done",
        vector_status="pending",
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
