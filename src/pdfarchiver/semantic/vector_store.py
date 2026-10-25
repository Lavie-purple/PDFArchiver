"""向量存储：把 512 维 int8 向量落盘，支持增删查。

按 D-036 定：
- int8 存储（1.93GB / 4M chunks）
- 1 chunk/页（只给已索引正文的页建）
- 暴力搜索（ANN 列为待测档）

存储结构：
- vectors.npy：**整份读进内存**的 int8 数组（N, 512）—— 不做内存映射：Windows 上
  `np.load(..., mmap_mode="r+")` 之后同一个文件再 `np.save` 原地重写，实测
  `OSError: [Errno 22] Invalid argument`（2026-10-25 现场复现，明细见 **ISSUES I111** 证据格）
- vector_meta 表：doc_id, page_no, vector_idx 映射。**由迁移 `0007` 建**，本模块只读不建
  （运行时建表会让同一个 `schema_version` 对应两种库形状 —— **ISSUES I62**）
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import numpy as np

from pdfarchiver.config.paths import AppPaths


class VectorSchemaMissing(RuntimeError):
    """库里没有 `vector_meta`。结构只能由迁移建，这里只验不建（见 `_require_table`）。"""


class VectorStore:
    """向量存储。线程不安全（SQLite 连接不共享）。"""

    DIM = 512
    DTYPE = np.int8

    def __init__(self, data_root: Path | None = None) -> None:
        from pdfarchiver.config.paths import resolve_data_root
        self._data_root = data_root or resolve_data_root()
        self._paths = AppPaths.resolve(self._data_root)
        self._vectors_path = self._paths.data_dir / "vectors.npy"
        self._db_path = self._paths.catalog_db
        self._vectors: np.ndarray | None = None
        self._next_idx = 0

    def _require_table(self, conn: sqlite3.Connection) -> None:
        """前置断言：`vector_meta` 必须已由迁移 `0007` 建好，这里只验不建。

        以前这一段是 `CREATE TABLE IF NOT EXISTS`，后果是库里有没有这张表取决于"这段代码
        有没有跑到过"：空库首迁后是 19 张表，跑过一次语义搜索是 20 张，而两者报的都是
        `schema_version=6`。结构变更只能是一条迁移（`docs/DATABASE.md` 四），
        由 `tests/guards/test_schema_columns.py` 规则 B 钉住。
        """
        if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='vector_meta'"
                        " LIMIT 1").fetchone() is None:
            raise VectorSchemaMissing(
                f"库 {self._db_path} 里没有表 vector_meta —— 它由迁移 0007 建，"
                f"说明这个库没走到最新水位（正常启动会自动迁移；手工指库或老产物留下的库要"
                f"先用本版本启动一次）")

    def _load_vectors(self) -> np.ndarray:
        """加载或创建向量文件。"""
        if self._vectors is not None:
            return self._vectors

        if self._vectors_path.exists():
            # 不使用内存映射，直接加载到内存（避免 Windows 文件锁定问题）
            self._vectors = np.load(self._vectors_path)
            # 读取下一个可用索引
            conn = sqlite3.connect(self._db_path)
            try:
                self._require_table(conn)
                row = conn.execute("SELECT MAX(vector_idx) FROM vector_meta").fetchone()
                self._next_idx = (row[0] + 1) if row and row[0] is not None else 0
            finally:
                conn.close()
        else:
            # 创建空文件
            self._vectors = np.zeros((0, self.DIM), dtype=self.DTYPE)
            self._next_idx = 0
        return self._vectors

    def add(self, doc_id: int, page_no: int, vector: np.ndarray) -> int:
        """添加一个向量，返回 vector_idx。

        vector 必须是 (512,) 的 float32 数组，会被转成 int8。
        """
        assert vector.shape == (self.DIM,), f"向量维度必须是 {self.DIM}"
        assert vector.dtype == np.float32, "向量必须是 float32"

        conn = sqlite3.connect(self._db_path)
        try:
            self._require_table(conn)

            # 检查是否已存在
            existing = conn.execute(
                "SELECT vector_idx FROM vector_meta WHERE doc_id = ? AND page_no = ?",
                (doc_id, page_no)
            ).fetchone()
            if existing:
                # 更新现有向量
                idx = existing[0]
                vectors = self._load_vectors()
                vectors[idx] = (vector * 127).astype(self.DTYPE)
                np.save(self._vectors_path, vectors)
                return idx

            # 添加新向量
            vectors = self._load_vectors()
            idx = self._next_idx
            self._next_idx += 1

            # 扩展数组
            new_row = (vector * 127).astype(self.DTYPE).reshape(1, -1)
            if len(vectors) == 0:
                new_vectors = new_row
            else:
                new_vectors = np.vstack([vectors, new_row])
            np.save(self._vectors_path, new_vectors)
            self._vectors = new_vectors

            # 记录元数据
            conn.execute(
                "INSERT INTO vector_meta (doc_id, page_no, vector_idx) VALUES (?, ?, ?)",
                (doc_id, page_no, idx)
            )
            conn.commit()
            return idx
        finally:
            conn.close()

    def add_batch(self, items: list[tuple[int, int, np.ndarray]]) -> list[int]:
        """批量添加向量。items = [(doc_id, page_no, vector), ...]。"""
        if not items:
            return []

        conn = sqlite3.connect(self._db_path)
        try:
            self._require_table(conn)
            vectors = self._load_vectors()

            indices = []
            new_vectors_list = []
            new_meta = []

            for doc_id, page_no, vector in items:
                assert vector.shape == (self.DIM,)
                assert vector.dtype == np.float32

                # 检查是否已存在
                existing = conn.execute(
                    "SELECT vector_idx FROM vector_meta WHERE doc_id = ? AND page_no = ?",
                    (doc_id, page_no)
                ).fetchone()

                if existing:
                    idx = existing[0]
                    vectors[idx] = (vector * 127).astype(self.DTYPE)
                    indices.append(idx)
                else:
                    idx = self._next_idx
                    self._next_idx += 1
                    new_vectors_list.append((vector * 127).astype(self.DTYPE))
                    new_meta.append((doc_id, page_no, idx))
                    indices.append(idx)

            # 保存更新
            if new_vectors_list:
                if len(vectors) == 0:
                    new_vectors = np.vstack([v.reshape(1, -1) for v in new_vectors_list])
                else:
                    new_vectors = np.vstack([vectors] + [v.reshape(1, -1) for v in new_vectors_list])
                np.save(self._vectors_path, new_vectors)
                self._vectors = new_vectors
            elif len(vectors) > 0:
                # 只更新了现有向量，没有新增
                np.save(self._vectors_path, vectors)

            # 记录元数据
            if new_meta:
                conn.executemany(
                    "INSERT INTO vector_meta (doc_id, page_no, vector_idx) VALUES (?, ?, ?)",
                    new_meta
                )
                conn.commit()

            return indices
        finally:
            conn.close()

    def delete_by_doc(self, doc_id: int) -> int:
        """删除某个文档的所有向量，返回删除数量。"""
        conn = sqlite3.connect(self._db_path)
        try:
            self._require_table(conn)
            rows = conn.execute(
                "SELECT vector_idx FROM vector_meta WHERE doc_id = ?",
                (doc_id,)
            ).fetchall()
            if not rows:
                return 0

            conn.execute("DELETE FROM vector_meta WHERE doc_id = ?", (doc_id,))
            conn.commit()
            # 不物理删除向量文件里的行（避免碎片化），只删元数据
            return len(rows)
        finally:
            conn.close()

    def search(self, query_vector: np.ndarray, top_k: int = 10) -> list[tuple[int, int, float]]:
        """暴力搜索最相似的 top_k 个向量。

        返回 [(doc_id, page_no, score), ...]，score 是余弦相似度（-1 到 1）。
        """
        assert query_vector.shape == (self.DIM,)
        assert query_vector.dtype == np.float32

        vectors = self._load_vectors()
        if len(vectors) == 0:
            return []

        conn = sqlite3.connect(self._db_path)
        try:
            self._require_table(conn)

            # 转成 float32 计算余弦
            vectors_f32 = vectors.astype(np.float32) / 127.0
            query_norm = query_vector / np.linalg.norm(query_vector)

            # 计算余弦相似度（向量已归一化，内积 = 余弦）
            scores = vectors_f32 @ query_norm

            # 取 top_k
            top_indices = np.argsort(scores)[::-1][:top_k]

            results = []
            for idx in top_indices:
                row = conn.execute(
                    "SELECT doc_id, page_no FROM vector_meta WHERE vector_idx = ?",
                    (int(idx),)
                ).fetchone()
                if row:
                    results.append((row[0], row[1], float(scores[idx])))

            return results
        finally:
            conn.close()

    def count(self) -> int:
        """返回向量总数。"""
        conn = sqlite3.connect(self._db_path)
        try:
            self._require_table(conn)
            row = conn.execute("SELECT COUNT(*) FROM vector_meta").fetchone()
            return row[0] if row else 0
        finally:
            conn.close()

    def close(self) -> None:
        """释放资源。"""
        self._vectors = None

    def vector_indices_for_doc(self, doc_id: int) -> list[int]:
        """某文档在 vector_meta 里的所有 vector_idx。"""
        conn = sqlite3.connect(self._db_path)
        try:
            self._require_table(conn)
            rows = conn.execute(
                "SELECT vector_idx FROM vector_meta WHERE doc_id = ?", (doc_id,)).fetchall()
            return [r[0] for r in rows]   # 默认 row_factory 是元组，按名字取会 TypeError
        finally:
            conn.close()

    def get_vectors(self) -> np.ndarray:
        """公开访问向量数组（加载后缓存）。"""
        return self._load_vectors()
