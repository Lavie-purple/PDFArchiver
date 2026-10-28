"""向量存储：把 512 维 int8 向量落盘，支持增删查。

按 D-036 定：
- int8 存储（1.93GB / 4M chunks）
- 1 chunk/页（只给已索引正文的页建）
- 暴力搜索（ANN 列为待测档）

存储结构（**ISSUES I112** 乙 之后）：
- `vectors.npy`：`(capacity, 512)` 的 int8 `.npy`，**capacity 只增不减**；真实行数是
  `MAX(vector_idx)+1`（由 `vector_meta` 说了算，文件末尾没用到的行是零）。新增向量直接写到
  第 used 行 —— 满库（约 190 万页）那条老路每份文档都 `np.vstack` + `np.save` 整份重写，
  累计 **5.06 TiB** 写入、还要一次约 1.9 GiB 的瞬时峰值；现在只有扩容时写一次，累计约 2× 终值。
- `vector_meta` 表：doc_id, page_no, vector_idx 映射。**由迁移 `0007` 建**，本模块只读不建
  （运行时建表会让同一个 `schema_version` 对应两种库形状 —— **ISSUES I62**）

三条存储侧规矩：

1. **不长期持有映射**：每次读写现开现关。Windows 上实测两种后果 —— 同进程另有一只映射时
   `os.replace` 报 `PermissionError [WinError 5]`，自己没关映射时报 `[WinError 32]`
   （`.probe_work/u27_memmap_probe.log` 第 2、5 段）；而 `SemanticSearchService.close()` 全站
   零调用方（**ISSUES I111** ④），"靠 close 释放"是空头承诺。
2. **以 `vector_meta` 为准**：`used` 每次都从库里现读 `MAX(vector_idx)+1`，不缓存在实例上 ——
   另一进程（门禁、命令行工具）写进去的向量，这只实例下一次操作就看得见（**ISSUES I111** ①）。
3. **扩容只翻倍**：先写 `vectors.npy.grow` 再 `os.replace`，中途崩掉留下的还是原来那个完好文件。
"""
from __future__ import annotations

import heapq
import os
import sqlite3
from pathlib import Path

import numpy as np

from pdfarchiver.config.paths import AppPaths

# 首次建文件时的容量（行）。满库靠翻倍；从 1 行起步要扩 21 次，每次都是整份搬运。
DEFAULT_CAPACITY = 1024
# 搜索时一次转 float32 的行数：32k × 512 × 4B ≈ 64 MiB，满库扫描峰值不再按整库算。
SEARCH_CHUNK_ROWS = 32_768
# 扩容搬迁时一次复制的行数（int8，32 MiB）。
COPY_CHUNK_ROWS = 65_536


class VectorSchemaMissing(RuntimeError):
    """库里没有 `vector_meta`。结构只能由迁移建，这里只验不建（见 `_require_table`）。"""


class VectorFileMismatch(RuntimeError):
    """`vectors.npy` 的行数覆盖不了 `vector_meta` 报的 used —— 文件被截断或库不是这一份。"""


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

    def _connect(self) -> sqlite3.Connection:
        """本模块所有连接的统一出口：打开外键（**ISSUES I111** D）。

        迁移 `0007` 给 `vector_meta.doc_id` 声明了 `REFERENCES documents(id) ON DELETE CASCADE`，
        但 SQLite 默认不执行外键（`PRAGMA foreign_keys` 默认 0）⇒ 这条约束在产品里一直是死的：
        给不存在的 `doc_id` 插元数据插得进去（I111 D 临时库实测 `vector_meta 5 行｜库里 0 份文档`）。
        打开之后这类插入当场 `IntegrityError`；真库现数孤儿行 0（2026-10-25 `LEFT JOIN` 实测），
        打开它不会改动任何现有行，删文档的级联清理也才真正生效。
        """
        conn = sqlite3.connect(self._db_path)
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

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

    # —— 文件侧 ——————————————————————————————————————

    def _used_rows(self, conn: sqlite3.Connection | None = None) -> int:
        """已分配的向量行数 = `MAX(vector_idx)+1`。以库为准，不缓存（规矩 2）。"""
        own = conn is None
        if own:
            conn = self._connect()
        try:
            self._require_table(conn)
            row = conn.execute("SELECT MAX(vector_idx) FROM vector_meta").fetchone()
            return (row[0] + 1) if row and row[0] is not None else 0
        finally:
            if own:
                conn.close()

    def _open(self, *, writable: bool) -> np.ndarray | None:
        """现开一份映射；文件还不存在返回 None。用完必须交给 `_release`。"""
        if not self._vectors_path.exists():
            return None
        return np.load(self._vectors_path, mmap_mode="r+" if writable else "r")

    @staticmethod
    def _release(mapped: np.ndarray | None) -> None:
        """flush + 关映射。Windows 上不关就没法 `os.replace`（见模块头规矩 1）。"""
        if mapped is None:
            return
        if mapped.flags.writeable:
            mapped.flush()
        mm = getattr(mapped, "_mmap", None)
        if mm is not None and not mm.closed:
            mm.close()

    def _capacity(self) -> int:
        mapped = self._open(writable=False)
        if mapped is None:
            return 0
        try:
            return int(mapped.shape[0])
        finally:
            self._release(mapped)

    def _mismatch(self, capacity: int, used: int) -> VectorFileMismatch:
        return VectorFileMismatch(
            f"vectors.npy 只有 {capacity} 行，而 vector_meta 报到第 {used} 行 —— "
            f"文件被截断，或者这个库不是那份文件：{self._vectors_path}")

    def _grow_to(self, capacity: int) -> None:
        """把文件扩到 `capacity` 行：已有 used 行原样搬过去，未用行留零。"""
        used = self._used_rows()
        tmp = self._vectors_path.with_name(self._vectors_path.name + ".grow")
        if tmp.exists():
            tmp.unlink()
        new = np.lib.format.open_memmap(tmp, mode="w+", dtype=self.DTYPE,
                                        shape=(capacity, self.DIM))
        old = self._open(writable=False)
        try:
            if old is not None and used:
                for start in range(0, used, COPY_CHUNK_ROWS):
                    stop = min(start + COPY_CHUNK_ROWS, used)
                    new[start:stop] = old[start:stop]
            new.flush()
        finally:
            self._release(old)
            self._release(new)
        os.replace(tmp, self._vectors_path)

    def _write_rows(self, rows: list[tuple[int, np.ndarray]]) -> None:
        """把 `(vector_idx, int8 行)` 写进文件；容量不够先翻倍扩容。

        调用方保证先写向量、后写元数据：中途崩掉只会留下没有元数据指向的行，而下次的
        `MAX(vector_idx)` 还是同一个数，那些行会被原地覆盖，不会变成谁都能搜到的幽灵。
        """
        if not rows:
            return
        used = self._used_rows()
        need = max(idx for idx, _ in rows) + 1
        capacity = self._capacity()
        if used > capacity:
            raise self._mismatch(capacity, used)
        if need > capacity:
            grown = max(DEFAULT_CAPACITY, capacity)
            while grown < need:
                grown *= 2
            self._grow_to(grown)

        mapped = self._open(writable=True)
        if mapped is None:
            raise VectorFileMismatch(f"扩容后找不到 {self._vectors_path}")
        try:
            for idx, row in rows:
                mapped[idx] = row
            mapped.flush()
        finally:
            self._release(mapped)

    # —— 写路径 ——————————————————————————————————————

    def add(self, doc_id: int, page_no: int, vector: np.ndarray) -> int:
        """添加一个向量，返回 vector_idx。

        vector 必须是 (512,) 的 float32 数组，会被转成 int8。
        """
        assert vector.shape == (self.DIM,), f"向量维度必须是 {self.DIM}"
        assert vector.dtype == np.float32, "向量必须是 float32"
        return self.add_batch([(doc_id, page_no, vector)])[0]

    def add_batch(self, items: list[tuple[int, int, np.ndarray]]) -> list[int]:
        """批量添加向量。items = [(doc_id, page_no, vector), ...]。"""
        if not items:
            return []

        conn = self._connect()
        try:
            self._require_table(conn)
            base = self._used_rows(conn)
            indices: list[int] = []
            writes: list[tuple[int, np.ndarray]] = []
            new_meta: list[tuple[int, int, int]] = []

            for doc_id, page_no, vector in items:
                assert vector.shape == (self.DIM,)
                assert vector.dtype == np.float32
                row = (vector * 127).astype(self.DTYPE)

                existing = conn.execute(
                    "SELECT vector_idx FROM vector_meta WHERE doc_id = ? AND page_no = ?",
                    (doc_id, page_no)
                ).fetchone()
                if existing:
                    idx = int(existing[0])
                else:
                    idx = base + len(new_meta)
                    new_meta.append((doc_id, page_no, idx))
                indices.append(idx)
                writes.append((idx, row))

            self._write_rows(writes)
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
        conn = self._connect()
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
            # 不物理删除向量文件里的行（避免碎片化），只删元数据；
            # 这些死行由 `search()` 按 `used - COUNT(*)` 超量取样抵掉（ISSUES I111 ⑥）
            return len(rows)
        finally:
            conn.close()

    # —— 读路径 ——————————————————————————————————————

    def search(self, query_vector: np.ndarray, top_k: int = 10) -> list[tuple[int, int, float]]:
        """暴力搜索最相似的 top_k 个向量。

        返回 [(doc_id, page_no, score), ...]，score 是余弦相似度（-1 到 1）。

        分块打分（**ISSUES I112** 乙）：老写法 `vectors.astype(np.float32) / 127` 在满库
        （约 190 万行）上是 3.9 GiB 瞬时分配 —— 本机实测一次查询 **66.5s**；分块后同一场
        **6.1s**、峰值 64 MiB。`/127` 挪到查询向量上（存的是 `round(v*127)`），省掉一整趟
        1 GiB 的除法（`.probe_work/u27_search_cost.log` / `u27_scale_variants.log`）。

        超量取样（**ISSUES I111** ⑥）：`delete_by_doc` 按设计只删 `vector_meta`、不动 `.npy`
        里的行，所以死行仍参与打分。先按 `used - COUNT(*)` 数出死行，取 `top_k + 死行数`
        个候选再回查元数据 —— 否则死行会把名额吃掉，用户设 10 条只看到 7 条且没有任何提示。
        `COUNT(*)` 在 196.8 万行上实测 **25ms（温）/ 1.1s（冷）**，相对一次查询的秒级成本可忽略。
        """
        assert query_vector.shape == (self.DIM,)
        assert query_vector.dtype == np.float32
        if top_k <= 0:
            return []

        used = self._used_rows()
        if used == 0:
            return []
        dead = max(0, used - self.count())
        want = min(top_k + dead, used)
        mapped = self._open(writable=False)
        if mapped is None:
            raise self._mismatch(0, used)
        try:
            capacity = int(mapped.shape[0])
            if used > capacity:
                raise self._mismatch(capacity, used)

            query_scaled = (query_vector / np.linalg.norm(query_vector)) / 127.0
            best: list[tuple[float, int]] = []
            for start in range(0, used, SEARCH_CHUNK_ROWS):
                stop = min(start + SEARCH_CHUNK_ROWS, used)
                chunk = np.asarray(mapped[start:stop], dtype=np.float32)
                scores = chunk @ query_scaled
                k = min(want, scores.shape[0])
                for pos in np.argpartition(-scores, k - 1)[:k]:
                    cand = (float(scores[pos]), start + int(pos))
                    if len(best) < want:
                        heapq.heappush(best, cand)
                    elif cand[0] > best[0][0]:
                        heapq.heapreplace(best, cand)
            ranked = sorted(best, key=lambda item: (-item[0], item[1]))
        finally:
            self._release(mapped)

        conn = self._connect()
        try:
            self._require_table(conn)
            results = []
            for score, idx in ranked:
                row = conn.execute(
                    "SELECT doc_id, page_no FROM vector_meta WHERE vector_idx = ?",
                    (idx,)
                ).fetchone()
                if row:
                    results.append((row[0], row[1], score))
                    if len(results) == top_k:
                        break
            return results
        finally:
            conn.close()

    def count(self) -> int:
        """返回向量总数。"""
        conn = self._connect()
        try:
            self._require_table(conn)
            row = conn.execute("SELECT COUNT(*) FROM vector_meta").fetchone()
            return row[0] if row else 0
        finally:
            conn.close()

    def stats(self) -> tuple[int, int]:
        """（向量条数, 覆盖文档份数），一次扫描出两个读数 —— S9 顶栏「范围」与
        「向量 已建/未建」的唯一出处（轮三十七 丁）。

        `COUNT(*)` 在 196.8 万行上实测 **25ms（温）/ 1.1s（冷）**（**ISSUES I111** ⑥ 的测量，
        与 `search` 的秒级成本同量级）。这条只在 S9 页惰性构建与每次提问后调用，
        不挂在巡检或建窗路径上 —— 那是 **ISSUES I109** 已经付过学费的禁区。
        """
        conn = self._connect()
        try:
            self._require_table(conn)
            row = conn.execute(
                "SELECT COUNT(*), COUNT(DISTINCT doc_id) FROM vector_meta").fetchone()
            return (row[0], row[1])
        finally:
            conn.close()

    def vector_indices_for_doc(self, doc_id: int) -> list[int]:
        """某文档在 vector_meta 里的所有 vector_idx。"""
        conn = self._connect()
        try:
            self._require_table(conn)
            rows = conn.execute(
                "SELECT vector_idx FROM vector_meta WHERE doc_id = ?", (doc_id,)).fetchall()
            return [r[0] for r in rows]   # 默认 row_factory 是元组，按名字取会 TypeError
        finally:
            conn.close()

    def get_vectors(self) -> np.ndarray:
        """已分配行（前 used 行）的 int8 数组**副本**。没有向量时是 (0, 512)。

        必须是副本：`AIClassifyService._build_centers` 拿它做花式索引并在整个分类循环里用，
        返一份随映射关闭就失效的视图等于埋雷。满库这份副本约 964 MiB —— 与 I112 之前
        「整份读进内存」同量级，乙 省的是写放大与扩容峰值，不是这一处。
        """
        used = self._used_rows()
        if used == 0:
            return np.zeros((0, self.DIM), dtype=self.DTYPE)
        mapped = self._open(writable=False)
        capacity = 0 if mapped is None else int(mapped.shape[0])
        if mapped is None or used > capacity:
            self._release(mapped)
            raise self._mismatch(capacity, used)
        try:
            return np.array(mapped[:used], dtype=self.DTYPE)
        finally:
            self._release(mapped)

    def close(self) -> None:
        """保留给既有调用方（`SemanticSearchService.close`）：本类不再长期持有映射，
        每次读写现开现关，没有可释放的东西（见模块头规矩 1）。"""
