"""文档主记录读写。唯一口径：**一个规范化路径 = 一条主记录**（D-005，p7 实测）。

重叠监测根重复扫到同一文件时，靠 `ux_documents_path_key` 拒绝插入，
所以这里一律用 `INSERT ... ON CONFLICT(path_key) DO UPDATE`，不许先查后插（有竞态）。

阶段 2 加了三件事，都是扫描链路要的：
1. `device_id` 进事实列 —— 重命名采纳要靠 `(device_id, file_id, size, mtime)` 四元组，
   `st_ino` 只在一块卷内唯一，不带 device 就可能把跨盘同 inode 的两个文件当成同一个。
2. `mark_index_result()` 是**索引状态的唯一写入口**：一次写清 parse/text/fts/ocr 四个状态 +
   页数 + 哈希 + 错误，中途失败整体回滚，不留"正文写了一半但 fts_status=done"的假成功。
3. `adopt_path()` 处理移动/重命名（SPEC 3.2「文件路径不是永久身份标识」）：
   **改路径，不改 id** —— 主键不变，分类、标签、集合关联全部原地保留。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from pdfarchiver.db.engine import Engine
from pdfarchiver.db.models import Document, now_ts
from pdfarchiver.db.sqltext import like_contains, like_prefix

_COLS = """
  id, path, path_key, name, ext, size_bytes, mtime_ns, ctime_ns, file_id, device_id, sha256,
  page_count, text_bearing_rate, is_pdf, needs_pass, is_repaired, parse_status, text_status,
  ocr_status, ocr_pages_done, last_ocr_at, fts_status, vector_status, category_confirmed,
  last_scanned_at, last_indexed_at, last_error, missing_since, created_at, updated_at
"""


@dataclass(frozen=True)
class DocScanState:
    """对账一次扫描要用的最小投影。不要把整个 Document 拉进内存再做集合运算 ——
    8,000 份是小事，×10 档 8 万份时投影能省掉一倍的对象开销（AGENTS.md 禁止 O(n²) 与全量加载）。"""

    doc_id: int
    path_key: str
    path: str
    size_bytes: int
    mtime_ns: int
    device_id: int | None
    file_id: int | None
    sha256: str | None
    fts_status: str
    missing_since: int | None


@dataclass(frozen=True)
class DocFilter:
    """筛选条件。检索与浏览共用这一份定义，两处不可能各说各话。

    时间只有一个口径：`modified_from/to` 比的是 `documents.mtime_ns`（**文件修改时间**，UTC 秒）。
    PDF 里的 CreationDate 是"文档自称的创建时间"，那是另一个概念，不许混进来（AGENTS.md 禁止
    核心概念多口径）；要按它筛是阶段 5 的事，届时得先把两个口径都摆到界面上让人选。
    """

    root_key: str | None = None            # 只看在某个监测根子树里的
    category_ids: tuple[int, ...] = ()
    tag_ids: tuple[int, ...] = ()
    tag_match_all: bool = False            # False=任一标签，True=同时具备全部标签
    modified_from: int | None = None       # UTC unix 秒（含）
    modified_to: int | None = None         # UTC unix 秒（含）
    fts_status: str | None = None
    min_size_bytes: int | None = None
    min_pages: int | None = None
    missing_only: bool = False             # 只看磁盘上已经不存在的
    include_missing: bool = False          # False=结果里不出现缺失文档（SPEC 3.4：不许显示虚假的有效结果）


# 排序口径只在这里定义一次，界面负责贴中文名。
SORTS: dict[str, str] = {
    "name": "d.name COLLATE NOCASE, d.id",
    "path": "d.path, d.id",
    "mtime": "d.mtime_ns DESC, d.id",
    "size": "d.size_bytes DESC, d.id",
    "pages": "d.page_count DESC, d.id",
    "indexed": "d.last_indexed_at DESC, d.id",
}
FIELD_COLUMNS = frozenset({"name", "path"})
# docs/DATABASE 二 的 fts_status 取值，一处抄这份就要在别处对不上，所以由单测断言它等于文档里的集合
SEARCHABLE_STATUSES = frozenset({"pending", "running", "done", "failed", "stale"})
# 什么算"还欠一次索引"。唯一口径，扫描侧与重启侧都从这里取：
# `failed` 故意不在内 —— 它是"试过且知道为什么不行"，每扫一遍就重排一次等于把同一个坏文件
# 反复烧重试预算；要救它得先改掉文件本身。`running` 也不在，任务正在跑。
NEEDS_INDEX_STATUSES = ("pending", "stale")
_NEEDS_INDEX_MARKS = ",".join("?" * len(NEEDS_INDEX_STATUSES))
MAX_BULK_IDS = 2000  # 一次检索最多 200 行 ×4 个字段通道，再留一倍余量；超上限=用法错了，不是量大
NS_PER_SECOND = 1_000_000_000  # mtime_ns 与"UTC 秒"口径之间的唯一换算处
# 变量个数上限：SQLite 默认 999，SQLITE_MAX_VARIABLE_NUMBER 在 3.32 之前是硬限制。
# 分块按 500 走 = 一半的量，留足余量给同一句里的其它参数（AGENTS.md：阈值按最大量级反算）。
SCANNED_CHUNK = 500


def _to_doc(row) -> Document:
    return Document(**{k: row[k] for k in row.keys()})


class DocumentRepository:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def upsert(self, doc: Document) -> Document:
        """按 path_key 幂等写入。已存在就只刷新**文件层面的事实**，
        **不动索引状态与分类确认位**（反向注入 I8 钉住这条：重新扫描不能把 fts_status=done 冲回 pending，
        否则每次重扫都要把全部正文重来一遍）。
        `sha256` 归到"索引阶段的事实"里一起保：扫描只 stat 文件、不算哈希，传进来的必然是 None，
        直接覆盖等于每扫一次就把指纹擦一次 —— 而那个指纹正是"内容没变，不必重抽"的唯一依据。
        要清掉它只能由索引阶段写回（`mark_index_result`）。"""
        conn = self.engine.thread_connection()
        ts = now_ts()
        if not doc.created_at:
            doc.created_at = ts
        doc.updated_at = ts
        with self.engine.transaction(conn, on_error=f"写入文档主记录失败 {doc.path}"):
            conn.execute(
                """
                INSERT INTO documents (path, path_key, name, ext, size_bytes, mtime_ns, ctime_ns,
                  file_id, device_id, sha256, page_count, text_bearing_rate, is_pdf, needs_pass,
                  is_repaired, parse_status, text_status, ocr_status, fts_status, vector_status,
                  category_confirmed, last_scanned_at, last_indexed_at, last_error, missing_since,
                  created_at, updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(path_key) DO UPDATE SET
                  size_bytes=excluded.size_bytes, mtime_ns=excluded.mtime_ns,
                  ctime_ns=excluded.ctime_ns, file_id=excluded.file_id, device_id=excluded.device_id,
                  sha256=COALESCE(excluded.sha256, documents.sha256),
                  name=excluded.name, ext=excluded.ext,
                  missing_since=NULL, last_scanned_at=excluded.last_scanned_at,
                  updated_at=excluded.updated_at
                """,
                (doc.path, doc.path_key, doc.name, doc.ext, doc.size_bytes, doc.mtime_ns,
                 doc.ctime_ns, doc.file_id, doc.device_id, doc.sha256, doc.page_count,
                 doc.text_bearing_rate, doc.is_pdf, doc.needs_pass, doc.is_repaired, doc.parse_status,
                 doc.text_status, doc.ocr_status, doc.fts_status, doc.vector_status,
                 doc.category_confirmed, doc.last_scanned_at, doc.last_indexed_at, doc.last_error,
                 doc.missing_since, doc.created_at, doc.updated_at))
        row = conn.execute(f"SELECT {_COLS} FROM documents WHERE path_key=?",
                           (doc.path_key,)).fetchone()
        return _to_doc(row)

    def get_by_path_key(self, path_key: str) -> Document | None:
        row = self.engine.thread_connection().execute(
            f"SELECT {_COLS} FROM documents WHERE path_key=?", (path_key,)).fetchone()
        return _to_doc(row) if row else None

    def get(self, doc_id: int) -> Document | None:
        row = self.engine.thread_connection().execute(
            f"SELECT {_COLS} FROM documents WHERE id=?", (doc_id,)).fetchone()
        return _to_doc(row) if row else None

    def list(self, limit: int = 500, offset: int = 0) -> list[Document]:
        rows = self.engine.thread_connection().execute(
            f"SELECT {_COLS} FROM documents ORDER BY name COLLATE NOCASE LIMIT ? OFFSET ?",
            (limit, offset)).fetchall()
        return [_to_doc(r) for r in rows]

    def count(self) -> int:
        return self.engine.thread_connection().execute("SELECT count(*) FROM documents").fetchone()[0]

    def count_missing(self) -> int:
        return self.engine.thread_connection().execute(
            "SELECT count(*) FROM documents WHERE missing_since IS NOT NULL").fetchone()[0]

    def counts_by_fts_status(self) -> dict[str, int]:
        conn = self.engine.thread_connection()
        rows = conn.execute("SELECT fts_status, count(*) AS n FROM documents GROUP BY fts_status").fetchall()
        return {r["fts_status"]: r["n"] for r in rows}

    def counts_by_ocr_status(self) -> dict[str, int]:
        """OCR 侧的"还欠多少份"，与 `counts_by_fts_status` 完全对称：一条分组查询数出来。

        状态取值只有 `parsing.classify.OCR_STATUSES` 那五个，这里不另列名单 ——
        界面上"待 OCR"和"识别中"分不清是谁的锅，就该由这一行的数说清楚，而不是由展示层再算。
        """
        conn = self.engine.thread_connection()
        rows = conn.execute("SELECT ocr_status, count(*) AS n FROM documents GROUP BY ocr_status").fetchall()
        return {r["ocr_status"]: r["n"] for r in rows}

    def ids_needing_index(self, limit: int = 5000) -> list[int]:
        """重启/重建后把"没做完的活"重新排进队列用（验收：索引恢复）。

        口径 = `NEEDS_INDEX_STATUSES`，且**磁盘上还在**。缺失的文档不算 ——
        给它排一条索引任务只会得到一个必然失败的任务，而它的正文页留在库里也不再会被检索到
        （默认筛选带 `missing_since IS NULL`）。"""
        rows = self.engine.thread_connection().execute(
            f"SELECT id FROM documents WHERE missing_since IS NULL AND fts_status IN ({_NEEDS_INDEX_MARKS})"
            " ORDER BY id LIMIT ?", (*NEEDS_INDEX_STATUSES, limit)).fetchall()
        return [int(r["id"]) for r in rows]

    def scan_states_under(self, root_key: str) -> list[DocScanState]:
        """取某个监测根**子树内**的全部主记录投影，供扫描器对账。

        用 `root_key` 前缀匹配而不是 JOIN 别的表：一份文件可以同时落在多个重叠根下，
        "它属于哪个根"这件事没有唯一答案，只有"它在这次扫描的这棵子树里有没有被发现"有答案。
        """
        like = like_prefix(root_key)
        conn = self.engine.thread_connection()
        rows = conn.execute(
            r"""
            SELECT id AS doc_id, path_key, path, size_bytes, mtime_ns, device_id, file_id,
                   sha256, fts_status, missing_since
            FROM documents
            WHERE path_key LIKE ? ESCAPE '\'
            """, (like,)).fetchall()
        return [DocScanState(**dict(r)) for r in rows]

    def facts_by_key(self, path_key: str) -> DocScanState | None:
        row = self.engine.thread_connection().execute(
            """
            SELECT id AS doc_id, path_key, path, size_bytes, mtime_ns, device_id, file_id,
                   sha256, fts_status, missing_since
            FROM documents WHERE path_key=?
            """, (path_key,)).fetchone()
        return DocScanState(**dict(row)) if row else None

    def by_inode(self, device_id: int, file_id: int) -> list[DocScanState]:
        """重命名采纳用：同一个卷内同一个文件 ID 的主记录。正常只有 0 或 1 条，
        返回列表是因为硬链接场景确实可能有多条 —— 那时**不自动采纳**，交给人判断。"""
        rows = self.engine.thread_connection().execute(
            """
            SELECT id AS doc_id, path_key, path, size_bytes, mtime_ns, device_id, file_id,
                   sha256, fts_status, missing_since
            FROM documents WHERE device_id=? AND file_id=?
            """, (device_id, file_id)).fetchall()
        return [DocScanState(**dict(r)) for r in rows]

    def adopt_path(self, doc_id: int, *, path: str, path_key: str, name: str, ext: str,
                   size_bytes: int, mtime_ns: int, ctime_ns: int | None) -> bool:
        """移动 / 重命名：换路径、换身份键，**主键 id 不变**，所以分类、标签、集合关系原地保留。
        正文页按 doc_id 关联，也跟着保留 —— 路径变了不等于内容变了。"""
        conn = self.engine.thread_connection()
        ts = now_ts()
        with self.engine.transaction(conn, on_error=f"重命名采纳失败 doc_id={doc_id}"):
            cur = conn.execute(
                "UPDATE documents SET path=?, path_key=?, name=?, ext=?, size_bytes=?, mtime_ns=?,"
                " ctime_ns=?, missing_since=NULL, last_scanned_at=?, updated_at=? WHERE id=?",
                (path, path_key, name, ext, size_bytes, mtime_ns, ctime_ns, ts, ts, doc_id))
        return cur.rowcount > 0

    def mark_scanned(self, doc_id: int) -> None:
        conn = self.engine.thread_connection()
        ts = now_ts()
        with self.engine.transaction(conn, on_error=f"记录扫描时间失败 doc_id={doc_id}"):
            conn.execute("UPDATE documents SET last_scanned_at=?, updated_at=? WHERE id=?",
                         (ts, ts, doc_id))

    def mark_scanned_many(self, doc_ids: Iterable[int]) -> int:
        """批量刷新"这次扫描里又看见它了"。
        逐条 `mark_scanned` 在全量扫描是 8,000 个独立事务（×10 档 8 万个），
        而这件事本质是一次集合操作 —— 分块 `IN` 走，一个事务一批。"""
        ids = sorted(set(int(i) for i in doc_ids))
        if not ids:
            return 0
        conn = self.engine.thread_connection()
        ts = now_ts()
        touched = 0
        with self.engine.transaction(conn, on_error=f"批量记录扫描时间失败（{len(ids)} 条）"):
            for start in range(0, len(ids), SCANNED_CHUNK):
                chunk = ids[start:start + SCANNED_CHUNK]
                marks = ",".join("?" * len(chunk))
                cur = conn.execute(
                    f"UPDATE documents SET last_scanned_at=?, updated_at=? WHERE id IN ({marks})",
                    (ts, ts, *chunk))
                touched += cur.rowcount
        return touched

    def mark_missing(self, path_key: str) -> bool:
        """文件不见了要**保留记录**（SPEC 3.2：路径不是永久身份），只打时间戳。
        时间戳只认 `now_ts()` 一个口径（UTC unix 秒），不引入本地 naive 时间。"""
        conn = self.engine.thread_connection()
        ts = now_ts()
        with self.engine.transaction(conn, on_error=f"标记缺失失败 {path_key}"):
            cur = conn.execute(
                "UPDATE documents SET missing_since=?, updated_at=? WHERE path_key=? AND missing_since IS NULL",
                (ts, ts, path_key))
        return cur.rowcount > 0

    def mark_index_result(self, doc_id: int, *, sha256: str | None, page_count: int | None,
                          parse_status: str, text_status: str, text_bearing_rate: float | None,
                          fts_status: str, ocr_status: str, needs_pass: int = 0,
                          is_repaired: int = 0, is_pdf: int = 1, last_error: str | None = None) -> None:
        """索引结果的唯一写入口。一次写完，不留"正文写了一半但状态是 done"的中间态。"""
        conn = self.engine.thread_connection()
        ts = now_ts()
        with self.engine.transaction(conn, on_error=f"写索引结果失败 doc_id={doc_id}"):
            conn.execute(
                "UPDATE documents SET sha256=?, page_count=?, parse_status=?, text_status=?,"
                " text_bearing_rate=?, fts_status=?, ocr_status=?, needs_pass=?, is_repaired=?,"
                " is_pdf=?, last_error=?, last_indexed_at=?, updated_at=? WHERE id=?",
                (sha256, page_count, parse_status, text_status, text_bearing_rate, fts_status,
                 ocr_status, needs_pass, is_repaired, is_pdf, last_error, ts, ts, doc_id))

    def mark_ocr_result(self, doc_id: int, *, ocr_status: str, ocr_pages_done: int,
                        last_error: str | None = None) -> None:
        """OCR 结果的唯一写入口（与 `mark_index_result` 之于正文索引同一条规矩：一处写、别处只读）。

        `ocr_status` 的合法取值只有 `parsing.classify.OCR_STATUSES` 那五个，
        状态机由 `services/ocr_service.py` 判，这一层只负责"一次写完不留半个"。
        """
        conn = self.engine.thread_connection()
        ts = now_ts()
        with self.engine.transaction(conn, on_error=f"写 OCR 结果失败 doc_id={doc_id}"):
            conn.execute(
                "UPDATE documents SET ocr_status=?, ocr_pages_done=?, last_ocr_at=?,"
                " last_error=?, updated_at=? WHERE id=?",
                (ocr_status, ocr_pages_done, ts, last_error, ts, doc_id))

    def reset_ocr_tracking(self, doc_id: int) -> None:
        """正文被整本重抽时把 OCR 计数清零 —— OCR 的那些行已经被 `replace_pages` 删掉了。

        不清零就会留下"`ocr_pages_done=900` 而库里一行 OCR 文本都没有"的谎。
        状态位 `ocr_status` 由调用方在同一次 `mark_index_result` 里写，这里不越界重复写。
        """
        conn = self.engine.thread_connection()
        with self.engine.transaction(conn, on_error=f"重置 OCR 计数失败 doc_id={doc_id}"):
            conn.execute("UPDATE documents SET ocr_pages_done=0, last_ocr_at=NULL, updated_at=?"
                         " WHERE id=?", (now_ts(), doc_id))

    def set_fts_status(self, doc_id: int, status: str, *, error: str | None = None) -> None:
        conn = self.engine.thread_connection()
        with self.engine.transaction(conn, on_error=f"更新索引状态失败 doc_id={doc_id}"):
            conn.execute("UPDATE documents SET fts_status=?, last_error=?, updated_at=? WHERE id=?",
                         (status, error, now_ts(), doc_id))

    def invalidate_index(self, doc_id: int) -> None:
        """内容变了但路径没变：把状态打回 stale/pending，**等重新索引**。
        只改状态、不删正文 —— 删正文是索引任务自己的事（先删后写在一个事务里）。"""
        conn = self.engine.thread_connection()
        with self.engine.transaction(conn, on_error=f"索引失效标记失败 doc_id={doc_id}"):
            conn.execute(
                "UPDATE documents SET fts_status='stale', text_status='pending', updated_at=? WHERE id=?",
                (now_ts(), doc_id))

    def set_error(self, doc_id: int, message: str) -> None:
        conn = self.engine.thread_connection()
        with self.engine.transaction(conn, on_error=f"写入文档错误状态失败 doc_id={doc_id}"):
            conn.execute("UPDATE documents SET last_error=?, parse_status='failed', updated_at=? WHERE id=?",
                         (message, now_ts(), doc_id))

    # —— 检索与筛选（docs/SPEC 3.4 四类字段里的三类：文件名 / 路径 / 状态） ——————————————

    def count_matching(self, f: DocFilter) -> int:
        w = where_for_filter(f)
        return self.engine.thread_connection().execute(
            f"SELECT count(*) FROM documents d{w.sql_with()}", w.params).fetchone()[0]

    def by_ids(self, doc_ids: list[int] | tuple[int, ...]) -> dict[int, Document]:
        """按 ID 批量取主记录（检索层把命中 ID 变成能展示的信息）。

        返回字典而不是列表：调用方手里的顺序是相关性序，这里不该悄悄排成 ID 序。
        ID 个数有上限 `MAX_BULK_IDS`：一次检索的命中行数就那么多，超出来说明调用方
        在拿它当"取全表"用 —— 那种用法要写进筛选条件，不该拼在一句 SQL 的参数里。"""
        unique = set(doc_ids)
        if not unique:
            return {}
        if len(unique) > MAX_BULK_IDS:
            raise ValueError(f"一次取 {len(unique)} 条超出 {MAX_BULK_IDS}；"
                             "大批量请按条件筛选，不要把 ID 列表塞进参数")
        marks = ",".join("?" * len(unique))
        rows = self.engine.thread_connection().execute(
            f"SELECT {_COLS} FROM documents WHERE id IN ({marks}) ORDER BY id",
            sorted(unique)).fetchall()
        return {r["id"]: _to_doc(r) for r in rows}

    def field_hits(self, needle: str, *, column: str, filters: DocFilter,
                   limit: int = 200) -> list[Document]:
        """文件名（`name`）或完整路径（`path`）的"包含"匹配。
        列名走 `FIELD_COLUMNS` 白名单而不是拼参数 —— 拼接等于把 SQL 注入面交给调用方。"""
        if column not in FIELD_COLUMNS:
            raise ValueError(f"不允许按 {column!r} 匹配；可选 {sorted(FIELD_COLUMNS)}")
        w = where_for_filter(filters)
        rows = self.engine.thread_connection().execute(
            f"SELECT {_COLS} FROM documents d{w.sql_with(f'd.{column} LIKE ?')}"
            " ORDER BY d.name COLLATE NOCASE, d.id LIMIT ?",
            (*w.params, like_contains(needle), limit)).fetchall()
        return [_to_doc(r) for r in rows]

    def list_sorted(self, filters: DocFilter, *, sort: str, limit: int, offset: int = 0) -> list[Document]:
        """没打字、只按条件浏览（SPEC 3.4 的筛选半边）。排序口径见 `SORTS`，只定义一处。"""
        if sort not in SORTS:
            raise ValueError(f"未知排序 {sort!r}；可选 {sorted(SORTS)}")
        w = where_for_filter(filters)
        rows = self.engine.thread_connection().execute(
            f"SELECT {_COLS} FROM documents d{w.sql_with()} ORDER BY {SORTS[sort]} LIMIT ? OFFSET ?",
            (*w.params, limit, offset)).fetchall()
        return [_to_doc(r) for r in rows]


@dataclass(frozen=True)
class SqlWhere:
    """`DocFilter` 编译出的 WHERE 片段 + 参数。

    `sql_with(*extra)` 把调用方自己的条件追加在筛选条件**之后**，参数顺序与之一致
    （`(*w.params, *extra_params)`）。追加而不是各写一份，是为了让四条检索通道共用同一套
    筛选口径：谁都不许在自己的 SQL 里另写一遍 `missing_since IS NULL`。
    """

    clauses: tuple[str, ...]
    params: tuple[object, ...]

    def sql_with(self, *extra_clauses: str) -> str:
        joined = [*self.clauses, *extra_clauses]
        return (" WHERE " + " AND ".join(joined)) if joined else ""


def where_for_filter(f: DocFilter) -> SqlWhere:
    """把 `DocFilter` 编译成 `SqlWhere`。

    别名固定为 `d`，四条检索通道（文件名 / 路径 / 元数据 / 正文）都靠它拼在一起：
    筛选口径只写这一处，元数据与正文通道 import 它，不再自己抄一遍。
    """
    clauses: list[str] = []
    params: list[object] = []
    if f.missing_only:
        clauses.append("d.missing_since IS NOT NULL")
    elif not f.include_missing:
        clauses.append("d.missing_since IS NULL")
    if f.root_key:
        clauses.append(r"d.path_key LIKE ? ESCAPE '\'")
        params.append(like_prefix(f.root_key))
    if f.fts_status is not None:
        if f.fts_status not in SEARCHABLE_STATUSES:
            raise ValueError(f"未知索引状态 {f.fts_status!r}；可选 {sorted(SEARCHABLE_STATUSES)}")
        clauses.append("d.fts_status = ?")
        params.append(f.fts_status)
    if f.min_size_bytes is not None:
        clauses.append("d.size_bytes >= ?")
        params.append(f.min_size_bytes)
    if f.min_pages is not None:
        clauses.append("d.page_count >= ?")
        params.append(f.min_pages)
    # 时间口径只有一个：documents.mtime_ns（文件修改时间，UTC）。
    # PDF 里的 CreationDate 是另一个概念（文档声称的创建时间），不混进这个筛选。
    if f.modified_from is not None:
        clauses.append("d.mtime_ns >= ?")
        params.append(f.modified_from * NS_PER_SECOND)
    if f.modified_to is not None:
        clauses.append("d.mtime_ns <= ?")
        params.append(f.modified_to * NS_PER_SECOND)
    if f.category_ids:
        marks = ",".join("?" * len(f.category_ids))
        clauses.append(f"d.id IN (SELECT doc_id FROM document_categories WHERE category_id IN ({marks}))")
        params += list(f.category_ids)
    if f.tag_ids:
        marks = ",".join("?" * len(f.tag_ids))
        if f.tag_match_all:
            clauses.append(
                f"d.id IN (SELECT doc_id FROM document_tags WHERE tag_id IN ({marks})"
                f" GROUP BY doc_id HAVING count(DISTINCT tag_id) = ?)")
            params += list(f.tag_ids) + [len(f.tag_ids)]
        else:
            clauses.append(f"d.id IN (SELECT doc_id FROM document_tags WHERE tag_id IN ({marks}))")
            params += list(f.tag_ids)
    return SqlWhere(tuple(clauses), tuple(params))
