"""语义搜索服务：整合 embedding + 向量存储，提供文本到文本的检索。

按 D-036 定：
- 1 chunk/页（只给已索引正文的页建）
- int8 存储（1.93GB / 4M chunks）
- 暴力搜索（ANN 列为待测档）

用法：
    service = SemanticSearchService()
    results = service.search("人工智能在医疗领域的应用", top_k=10)
    # results = [(doc_id, page_no, score), ...]
"""
from __future__ import annotations

from pathlib import Path

from pdfarchiver.config.paths import AppPaths
from pdfarchiver.semantic.embedding import EmbeddingService
from pdfarchiver.semantic.vector_store import VectorStore


class SemanticSearchService:
    """语义搜索服务。线程不安全（内部组件都不线程安全）。"""

    def __init__(self, data_root: Path | None = None) -> None:
        self._data_root = data_root or AppPaths.resolve().root
        self._embedding = EmbeddingService(self._data_root)
        self._vectors = VectorStore(self._data_root)

    def search(self, query: str, top_k: int = 10) -> list[tuple[int, int, float]]:
        """搜索最相似的 top_k 个向量。

        返回 [(doc_id, page_no, score), ...]，score 是余弦相似度（-1 到 1）。
        """
        if not query.strip():
            return []

        # 把查询文本转成向量
        query_vector = self._embedding.embed([query])[0]

        # 在向量库里搜
        return self._vectors.search(query_vector, top_k=top_k)

    def count(self) -> int:
        """返回向量总数。"""
        return self._vectors.count()

    def close(self) -> None:
        """释放资源。"""
        self._vectors.close()
