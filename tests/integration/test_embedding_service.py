"""语义嵌入层测试。"""
import numpy as np
import pytest
from pathlib import Path

from pdfarchiver.semantic.embedding import EmbeddingService


@pytest.fixture
def embedding_service(data_root: Path) -> EmbeddingService:
    """用 .probe_work 作为数据根，模型在那里。"""
    # 把模型从 .probe_work/models 复制到 data_root/models
    import shutil
    src = Path(".probe_work/models/bge-small-zh-v1.5")
    dst = data_root / "models" / "bge-small-zh-v1.5"
    if src.exists() and not dst.exists():
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(src, dst)
    return EmbeddingService(data_root)


def test_embed_returns_correct_shape(embedding_service: EmbeddingService) -> None:
    """空列表 → (0, 512)，单条 → (512,)，批量 → (N, 512)。"""
    empty = embedding_service.embed([])
    assert empty.shape == (0, 512)
    assert empty.dtype == np.float32

    single = embedding_service.embed(["测试文本"])
    assert single.shape == (1, 512)

    batch = embedding_service.embed(["第一条", "第二条", "第三条"])
    assert batch.shape == (3, 512)


def test_embed_vectors_are_normalized(embedding_service: EmbeddingService) -> None:
    """bge-small-zh-v1.5 输出已归一化，L2 范数应该接近 1。"""
    vectors = embedding_service.embed(["测试归一化"])
    norms = np.linalg.norm(vectors, axis=1)
    np.testing.assert_allclose(norms, 1.0, rtol=1e-5)


def test_embed_single_matches_batch(embedding_service: EmbeddingService) -> None:
    """单条和批量应该给出相同结果（确定性）。"""
    text = "同一条文本"
    single = embedding_service.embed_single(text)
    batch = embedding_service.embed([text])
    np.testing.assert_allclose(single, batch[0], rtol=1e-5)


def test_embed_different_texts_give_different_vectors(embedding_service: EmbeddingService) -> None:
    """不同文本的向量应该不同。"""
    vectors = embedding_service.embed(["人工智能", "番茄炒蛋"])
    assert not np.allclose(vectors[0], vectors[1], atol=1e-3)


def test_embed_similar_texts_have_high_cosine(embedding_service: EmbeddingService) -> None:
    """语义相似的文本余弦相似度应该高。"""
    vectors = embedding_service.embed([
        "人工智能产业的市场规模持续扩大",
        "AI 行业的市场容量仍在增长",
    ])
    cosine = np.dot(vectors[0], vectors[1])
    assert cosine > 0.6, f"相似文本余弦应该 > 0.6，实际 {cosine}"


def test_embed_dissimilar_texts_have_low_cosine(embedding_service: EmbeddingService) -> None:
    """语义无关的文本余弦相似度应该低。"""
    vectors = embedding_service.embed([
        "人工智能产业的市场规模持续扩大",
        "今天晚饭做了番茄炒蛋和米饭",
    ])
    cosine = np.dot(vectors[0], vectors[1])
    assert cosine < 0.4, f"无关文本余弦应该 < 0.4，实际 {cosine}"
