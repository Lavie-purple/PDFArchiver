"""AI 分类建议：基于文档向量与分类语义中心的相似度推荐分类。

算法：
1. 对每个分类，聚合其下所有文档的页面向量，算出"语义中心"（均值向量）
2. 给定待分类文档，将其文本向量化
3. 与每个分类中心算余弦相似度，返回 top-N

缓存策略：分类中心向量缓存在内存，分类变动时失效。
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass

import numpy as np

from pdfarchiver.db.repositories.catalog import CatalogRepository
from pdfarchiver.db.repositories.documents import DocumentRepository
from pdfarchiver.semantic.embedding import EmbeddingService
from pdfarchiver.semantic.vector_store import VectorStore

log = logging.getLogger("pdfarchiver.semantic.classify")


@dataclass(frozen=True)
class CategorySuggestion:
    category_id: int
    category_name: str
    score: float


class AIClassifyService:
    """AI 分类建议服务。线程不安全。"""

    def __init__(
        self,
        catalog: CatalogRepository,
        documents: DocumentRepository,
        embedding: EmbeddingService,
        vector_store: VectorStore,
    ) -> None:
        self._catalog = catalog
        self._documents = documents
        self._embedding = embedding
        self._vectors = vector_store
        self._centers: dict[int, np.ndarray] | None = None

    def _build_centers(self) -> dict[int, np.ndarray]:
        if self._centers is not None:
            return self._centers

        centers: dict[int, np.ndarray] = {}
        categories = self._catalog.list_categories()
        all_vecs = self._vectors.get_vectors()

        for cat in categories:
            doc_ids = self._catalog.docs_in_category(cat.id)
            if not doc_ids:
                continue

            vectors_f32_parts: list[np.ndarray] = []
            for doc_id in doc_ids:
                indices = self._vectors.vector_indices_for_doc(doc_id)
                if not indices or max(indices) >= len(all_vecs):
                    continue
                vecs = all_vecs[indices].astype(np.float32) / 127.0
                norms = np.linalg.norm(vecs, axis=1, keepdims=True)
                norms = np.clip(norms, 1e-9, None)
                vecs = vecs / norms
                vectors_f32_parts.append(vecs)

            if vectors_f32_parts:
                stacked = np.vstack(vectors_f32_parts)
                center = stacked.mean(axis=0)
                norm = np.linalg.norm(center)
                if norm > 1e-9:
                    center = center / norm
                centers[cat.id] = center

        self._centers = centers
        log.info("分类中心向量已构建：%d 个分类有向量", len(centers))
        return centers

    def invalidate_cache(self) -> None:
        self._centers = None

    def suggest(
        self,
        text: str,
        top_n: int = 5,
        min_score: float = 0.3,
    ) -> list[CategorySuggestion]:
        if not text.strip():
            return []

        centers = self._build_centers()
        if not centers:
            log.info("无分类有向量数据，无法推荐")
            return []

        query_vec = self._embedding.embed_single(text)

        suggestions: list[CategorySuggestion] = []
        categories_by_id = {c.id: c for c in self._catalog.list_categories()}

        for cat_id, center in centers.items():
            score = float(np.dot(query_vec, center))
            if score >= min_score:
                cat = categories_by_id.get(cat_id)
                if cat:
                    suggestions.append(CategorySuggestion(
                        category_id=cat_id,
                        category_name=cat.name,
                        score=round(score, 4),
                    ))

        suggestions.sort(key=lambda s: s.score, reverse=True)
        return suggestions[:top_n]

    def suggest_for_doc(
        self,
        doc_id: int,
        top_n: int = 5,
        min_score: float = 0.3,
    ) -> list[CategorySuggestion]:
        doc = self._documents.get(doc_id)
        if not doc:
            return []

        text = doc.name
        if doc.path:
            dirname = os.path.basename(os.path.dirname(doc.path))
            if dirname:
                text = f"{dirname} {text}"

        return self.suggest(text, top_n=top_n, min_score=min_score)
