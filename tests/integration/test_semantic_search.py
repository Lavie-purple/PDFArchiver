"""语义搜索服务测试。"""
import numpy as np
import pytest

from pdfarchiver.db.models import Document
from pdfarchiver.semantic.search_service import SemanticSearchService
from pdfarchiver.semantic.vector_store import VectorStore


def _model_available(ctx) -> bool:
    """检查模型文件是否存在。"""
    model_path = ctx.paths.models_dir / "bge-small-zh-v1.5" / "onnx" / "model_int8.onnx"
    return model_path.exists()


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
def search_service(ctx) -> SemanticSearchService:
    """用测试上下文的数据根。"""
    return SemanticSearchService(ctx.paths.root)


def test_search_empty_query(search_service: SemanticSearchService) -> None:
    """空查询返回空列表。"""
    results = search_service.search("")
    assert results == []

    results = search_service.search("   ")
    assert results == []


def test_search_no_vectors(search_service: SemanticSearchService, ctx) -> None:
    """空库搜索返回空列表（不需要模型）。"""
    # 这个测试不需要调用 embedding，直接验空库行为
    results = search_service._vectors.search(
        np.zeros(512, dtype=np.float32), top_k=10
    )
    assert results == []


def test_search_finds_similar(search_service: SemanticSearchService, ctx) -> None:
    """搜索能找到相似的文档（需要模型）。"""
    if not _model_available(ctx):
        pytest.skip("模型文件不存在")

    # 创建测试文档
    doc_id = _make_doc(ctx, "test/ai.pdf", "ai.pdf", "a" * 64, 1, 1, 1)

    # 添加一些向量（用真实的 embedding）
    texts = [
        "人工智能在医疗领域的应用",
        "机器学习算法的原理",
        "深度学习模型训练",
    ]
    vectors = search_service._embedding.embed(texts)

    for i, vector in enumerate(vectors):
        search_service._vectors.add(doc_id, i + 1, vector)

    # 搜索相关内容
    results = search_service.search("AI 在医学上的应用", top_k=3)
    assert len(results) > 0
    # 应该能找到相关的文档
    assert any(r[0] == doc_id for r in results)


def test_search_returns_scores(search_service: SemanticSearchService, ctx) -> None:
    """搜索结果包含相似度分数（需要模型）。"""
    if not _model_available(ctx):
        pytest.skip("模型文件不存在")

    doc_id = _make_doc(ctx, "test/doc.pdf", "doc.pdf", "b" * 64, 1, 2, 1)

    # 添加一个向量
    text = "测试文本"
    vector = search_service._embedding.embed([text])[0]
    search_service._vectors.add(doc_id, 1, vector)

    # 搜索
    results = search_service.search("测试", top_k=1)
    assert len(results) == 1
    doc_id_res, page_no, score = results[0]
    assert doc_id_res == doc_id
    assert page_no == 1
    # 分数应该在合理范围内
    assert -1.0 <= score <= 1.0


def test_count(search_service: SemanticSearchService, ctx) -> None:
    """计数正确（需要模型）。"""
    if not _model_available(ctx):
        pytest.skip("模型文件不存在")

    initial = search_service.count()

    doc_id = _make_doc(ctx, "test/count.pdf", "count.pdf", "c" * 64, 1, 3, 2)

    # 添加两个向量
    texts = ["文本一", "文本二"]
    vectors = search_service._embedding.embed(texts)
    for i, vector in enumerate(vectors):
        search_service._vectors.add(doc_id, i + 1, vector)

    assert search_service.count() == initial + 2
