"""语义搜索服务测试。

2026-10-18 之前这个文件有三条在**默认跑法下恒 SKIP**（**ISSUES I83**）：`_model_available()`
查的是 `ctx.paths.models_dir`，而模型只躺在 `.probe_work/models/` 里 —— 同目录的
`test_embedding_service.py` 会自己 `copytree` 进临时根，这个文件不拷，于是「查询文本 →
embedding → `VectorStore.search()` → 命中」这条**串起来的**路一条断言都没跑过，
而 skip 不进门禁的 `passed/failed` 计数，绿灯里看不见它今天没跑。
现在补同款拷贝 fixture，三条真跑；本机没有模型时仍然如实 SKIP（不是静默 SKIP：
`-rs` 数得出来，而全场 skip 总数记在 **ISSUES I83** 那一行）。
"""
import shutil
from pathlib import Path

import numpy as np
import pytest

from pdfarchiver.db.models import Document
from pdfarchiver.semantic.embedding import EmbeddingService
from pdfarchiver.semantic.search_service import SemanticSearchService
from pdfarchiver.semantic.vector_store import VectorStore

#: 一次性模型的源（`.probe_work/models/` 是 gitignored 的本机证据根，不是产品依赖）。
MODEL_SOURCE = Path(".probe_work/models") / EmbeddingService.MODEL_NAME


def _model_available(ctx) -> bool:
    """检查模型文件是否存在 —— 路径只从 `EmbeddingService` 那三个常量拼（**ISSUES I37**：
    模型根不许有第二处字面量，测试自己拼一份就是第二个口径）。"""
    return (ctx.paths.models_dir / EmbeddingService.MODEL_NAME
            / EmbeddingService.MODEL_FILE).exists()


def _install_model(ctx) -> None:
    """把模型从 `.probe_work/models/` 拷进本场的临时根，和 `test_embedding_service.py` 同一口径。"""
    if not MODEL_SOURCE.is_dir():
        return
    dst = ctx.paths.models_dir / EmbeddingService.MODEL_NAME
    if dst.exists():
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(MODEL_SOURCE, dst)


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
    """用测试上下文的数据根，并把模型先拷进去（**ISSUES I83** 甲：不拷就是三条恒 SKIP）。"""
    _install_model(ctx)
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
