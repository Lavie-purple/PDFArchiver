"""正文页与全文索引读写 —— SQL 只许出现在这一层（docs/ARCHITECTURE 一）。

三条来自实测的规矩，改动前先看：

1. **外部内容表的正文只有一份**（在 `text_pages`），`content_fts` 里只有倒排。
   所以写入必须走 `text_pages`，由三条触发器同步索引；直接写 `content_fts` 会把两边写歪。
2. **删一份文档的正文 = 删 `text_pages` 的行**，触发器负责从索引里摘干净。
   `delete` 命令漏带 `old.body` 时 SQLite 不报错，只留幽灵行（p1 `delete_trigger_trap`）——
   这种幽灵**没有免词的可测口径**（见 `check_fts_consistency()` 里那张实测表），所以它由
   触发器的行为断言守着（G10 用例：删完再搜必须搜不到），能测的两向由 `check_fts_consistency()`
   每次门禁都数一遍。
3. **短查询走 LIKE**。trigram 需要 ≥3 个字符才能构成一个 gram（p1：2 字词 trigram 命中 0），
   1–2 字查询由 `search` 层显式选 LIKE 通道，并在结果里标明用的是哪种口径，不许静默返回 0 条。
"""
from __future__ import annotations

from dataclasses import dataclass

from pdfarchiver.db.engine import Engine
from pdfarchiver.db.models import TextPage, now_ts
from pdfarchiver.db.repositories.documents import DocFilter, where_for_filter
from pdfarchiver.db.sqltext import like_contains


@dataclass(frozen=True)
class PageHit:
    """一条正文命中。`body` 是整页文本，片段由 `indexing/snippets.py` 在 Python 侧算
    （FTS5 没有 `offsets()`，D-015）。"""

    doc_id: int
    page_no: int
    body: str
    source_kind: str
    score: float


@dataclass(frozen=True)
class FtsConsistency:
    """全文索引与正文表的可测对账结果。口径只有两条，都是**能数出来**的：
    `unindexed`=正文在库里但索引花名册没有它；`stale_docsize`=花名册里还挂着已被删的正文行。
    倒排里的幽灵条目不在这里（测不到，理由见 `check_fts_consistency()`），别把它当"幽灵行计数"。
    """

    pages: int
    indexed: int
    unindexed: int
    stale_docsize: int

    @property
    def aligned(self) -> bool:
        return self.unindexed == 0 and self.stale_docsize == 0 and self.pages == self.indexed

    def as_dict(self) -> dict[str, int]:
        """探针/门禁把它整个塞进报告 JSON，读数要能远程对着看。"""
        return {"pages": self.pages, "indexed": self.indexed,
                "unindexed": self.unindexed, "stale_docsize": self.stale_docsize}

    def describe(self) -> str:
        return (f"正文 {self.pages} 行｜索引花名册 {self.indexed} 行｜"
                f"未进索引 {self.unindexed}｜花名册残留 {self.stale_docsize}")


class TextRepository:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine
    def replace_pages(self, doc_id: int, pages: list[TextPage]) -> int:
        """整体替换某文档的正文页。删旧 + 插新在**一个事务**里：
        中途失败要么全不做，要么全做完，不许留下"半本正文 + fts_status=done"。"""
        conn = self.engine.thread_connection()
        ts = now_ts()
        with self.engine.transaction(conn, on_error=f"写入正文失败 doc_id={doc_id}"):
            conn.execute("DELETE FROM text_pages WHERE doc_id=?", (doc_id,))
            conn.executemany(
                "INSERT INTO text_pages(doc_id, page_no, source_kind, char_count, body, indexed_at)"
                " VALUES(?,?,?,?,?,?)",
                [(doc_id, p.page_no, p.source_kind, p.char_count, p.body, ts) for p in pages])
        return len(pages)

    def delete_for_doc(self, doc_id: int) -> int:
        conn = self.engine.thread_connection()
        with self.engine.transaction(conn, on_error=f"清除正文失败 doc_id={doc_id}"):
            cur = conn.execute("DELETE FROM text_pages WHERE doc_id=?", (doc_id,))
        return cur.rowcount

    # —— OCR 专用（阶段 5）——

    def upsert_pages(self, doc_id: int, pages: list[TextPage]) -> int:
        """按页写入，已有的页**覆盖**，不碰没提到的页。

        为什么必须有这个方法而不是复用 `replace_pages`：后者"先删整本再插"，那是原生抽取的语义
        （文件内容变了，旧正文一个字都不能留）。而 OCR 的语义是"这份 900 页的书这次只补第 400 页"，
        删整本等于把前 899 页的识别成果扔掉重跑 —— p5 实测那是 3,281ms/页 的重跑。

        用 `INSERT OR REPLACE`：SQLite 里 replace = 先删后插，所以 `tx_pages_ad` 与 `tx_pages_ai`
        两条触发器都会走，索引跟着正文对齐（外部内容表的三条硬规则见 `0002_text_and_fts`）。
        """
        conn = self.engine.thread_connection()
        ts = now_ts()
        with self.engine.transaction(conn, on_error=f"写入 OCR 正文失败 doc_id={doc_id}"):
            conn.executemany(
                "INSERT OR REPLACE INTO text_pages(doc_id, page_no, source_kind, char_count,"
                " body, indexed_at, ocr_version) VALUES(?,?,?,?,?,?,?)",
                [(doc_id, p.page_no, p.source_kind, p.char_count, p.body, ts, p.ocr_version)
                 for p in pages])
        return len(pages)

    def ocr_versions_of(self, doc_id: int) -> dict[int, str | None]:
        """已有的 OCR 页 → 当初那次的版本指纹。幂等跳过逐页比这个数，不比整本。"""
        rows = self.engine.thread_connection().execute(
            "SELECT page_no, ocr_version FROM text_pages"
            " WHERE doc_id=? AND source_kind='ocr'", (doc_id,)).fetchall()
        return {int(r["page_no"]): r["ocr_version"] for r in rows}

    def native_page_chars(self, doc_id: int) -> dict[int, int]:
        """原生正文的 页码 → 字数。OCR 层用它决定"哪些页还缺字"，全程只读库不再解析 PDF。

        只回原生行：OCR 自己写的页不算"已经有字"，否则第一页识别完，第二遍就认为它不用跑了
        —— 那正是「普通文字 PDF 不应无意义地反复执行 OCR」这条要求反过来的情形。
        """
        rows = self.engine.thread_connection().execute(
            "SELECT page_no, char_count FROM text_pages WHERE doc_id=? AND source_kind='native'",
            (doc_id,)).fetchall()
        return {int(r["page_no"]): int(r["char_count"]) for r in rows}

    def count_ocr_pages(self, doc_id: int) -> int:
        return self.engine.thread_connection().execute(
            "SELECT count(*) FROM text_pages WHERE doc_id=? AND source_kind='ocr'",
            (doc_id,)).fetchone()[0]

    def count_ocr_pages_all(self) -> int:
        """全库已经存下的 OCR 正文页数（状态读数用）。
        与 `count_ocr_pages(doc_id)` 的差别只有范围，所以 SQL 只多一个 WHERE 少一个 doc_id ——
        分成两个方法是故意的：`doc_id=None` 表示"全部"会让"这份有几页"和"库里有几页"共用一个签名，
        正是 AGENTS.md 禁止的那种多口径。
        """
        return self.engine.thread_connection().execute(
            "SELECT count(*) FROM text_pages WHERE source_kind='ocr'").fetchone()[0]

    def delete_ocr_pages(self, doc_id: int) -> int:
        """只删 OCR 页（整本重识别前用）。原生页不动 —— 那是文件里本来就有的字，不是识别出来的。"""
        conn = self.engine.thread_connection()
        with self.engine.transaction(conn, on_error=f"清除 OCR 正文失败 doc_id={doc_id}"):
            cur = conn.execute("DELETE FROM text_pages WHERE doc_id=? AND source_kind='ocr'",
                               (doc_id,))
        return cur.rowcount

    def count_pages(self, doc_id: int) -> int:
        """这份文档在库里有几页正文。走 `ux_text_pages_doc_page` 的覆盖扫描，不碰 `body` 列 ——
        短路判据用它而不是 `pages_of`：后者为了数个数把整本文本拷进内存，
        946 页的文档就是白读一遍（p2 最大单文件实测）。"""
        return self.engine.thread_connection().execute(
            "SELECT count(*) FROM text_pages WHERE doc_id=?", (doc_id,)).fetchone()[0]

    def pages_of(self, doc_id: int) -> list[TextPage]:
        """这一份的正文页，按页码升序。`ocr_version` 必须在列 ——
        少选一列就等于交出一个永远为 None 的字段，读它的人不会报错，只会以为"这页没记过版本"。"""
        rows = self.engine.thread_connection().execute(
            "SELECT doc_id, page_no, source_kind, char_count, body, ocr_version FROM text_pages"
            " WHERE doc_id=? ORDER BY page_no", (doc_id,)).fetchall()
        return [TextPage(**dict(r)) for r in rows]

    def search_fts(self, match: str, filters: DocFilter, *, limit: int = 200) -> list[PageHit]:
        """trigram 短语检索。`match` 必须是 `indexing.fts.match_expression()` 产出的**已转义**串，
        不能是用户原始输入 —— FTS5 查询语法里的 `"`、`(`、`AND` 会被当成运算符。

        筛选条件走 `documents.where_for_filter`，与文件名 / 路径 / 元数据三条通道**同一份**：
        同一次检索里"按分类筛完搜正文"和"按分类筛完看文件名"必须得到同一批候选文档。
        JOIN documents 还兜住了安全要求「文件删除后不许继续显示虚假的有效结果」——
        默认口径就带 `missing_since IS NULL`，被删掉的文件的正文根本进不了结果集。
        """
        w = where_for_filter(filters)
        rows = self.engine.thread_connection().execute(
            "SELECT tp.doc_id, tp.page_no, tp.body, tp.source_kind, bm25(content_fts) AS score"
            " FROM content_fts JOIN text_pages tp ON tp.rowid = content_fts.rowid"
            f" JOIN documents d ON d.id = tp.doc_id{w.sql_with('content_fts MATCH ?')}"
            " ORDER BY score LIMIT ?",
            (*w.params, match, limit)).fetchall()
        return [PageHit(**dict(r)) for r in rows]

    def search_like(self, needle: str, filters: DocFilter, *, limit: int = 200) -> list[PageHit]:
        """1–2 字查询的 LIKE 通道：`score` 恒为 0（LIKE 没有相关性得分），
        排序退回"文档序 + 页序"。界面必须显示"慢速匹配"，因为这条是全文扫描（p1：30 万行 499ms）。"""
        w = where_for_filter(filters)
        rows = self.engine.thread_connection().execute(
            "SELECT tp.doc_id, tp.page_no, tp.body, tp.source_kind, 0.0 AS score"
            " FROM text_pages tp JOIN documents d ON d.id = tp.doc_id"
            + w.sql_with(r"tp.body LIKE ? ESCAPE '\'")
            + " ORDER BY tp.doc_id, tp.page_no LIMIT ?",
            (*w.params, like_contains(needle), limit)).fetchall()
        return [PageHit(**dict(r)) for r in rows]

    def check_fts_consistency(self) -> FtsConsistency:
        """G10：全文索引与正文表对不对得齐。只报**测得到**的两件事，并说清测不到什么。

        外部内容表（`content_fts` 只存倒排，正文在 `text_pages`）能免词枚举的口径只有影子表
        `content_fts_docsize` 的花名册。四种坏法实测（`tests/probes/p14_fts_instrument.py`，
        每次跑都重新验一遍）：

        | 坏法 | `count(*) FROM content_fts` | docsize 双向 | 带词的 `MATCH` |
        | --- | --- | --- | --- |
        | 删正文时 delete 触发器列清单写错（p1 的真实陷阱，SQLite 不报错） | **看不见**（恒等于正文行数） | **看不见** | **看得见** |
        | insert 触发器不在（正文进库、索引没有） | 看不见 | `unindexed` 看见 | 少一条命中 |
        | 正文删了、delete 触发器也没有（纯幽灵） | 看不见 | `stale_docsize` 不一定看见 | **看得见** |
        | 一切正常 | 0 | 0 | 相等 |

        所以：**倒排里的幽灵条目在本产品里测不到**（空前缀 `MATCH ''` 直接报语法错，
        FTS5 的 `integrity-check` 对外部内容表在四种坏状态下全部"通过"，等于没有检查）。
        这一面由两条别的东西兜住：
        ① 迁移里那三条触发器是**行为**验的（`tests/guards/test_migrations.py` 的 G10 用例：
        删完正文再 `MATCH` 必须为 0 —— 触发器写坏它会红，实测过）；
        ② 检索通路每次都 `JOIN text_pages`（`search_fts`），幽灵条目进不了结果集，
        用户不会看到"已删文件的正文命中"，代价只是索引体积与 bm25 的排序。
        补救入口是 `rebuild_all()`：实测坏状态下 rebuild 之后 `MATCH` 与 docsize 全部对齐。
        """
        conn = self.engine.thread_connection()
        pages = conn.execute("SELECT count(*) FROM text_pages").fetchone()[0]
        indexed = conn.execute("SELECT count(*) FROM content_fts_docsize").fetchone()[0]
        unindexed = conn.execute(
            "SELECT count(*) FROM text_pages tp WHERE tp.rowid NOT IN (SELECT id FROM content_fts_docsize)"
        ).fetchone()[0]
        stale = conn.execute(
            "SELECT count(*) FROM content_fts_docsize WHERE id NOT IN (SELECT rowid FROM text_pages)"
        ).fetchone()[0]
        return FtsConsistency(pages=pages, indexed=indexed, unindexed=unindexed, stale_docsize=stale)

    def rebuild_all(self) -> None:
        """让外部内容表与内容表重新对齐（`text_pages` 是真身，索引只是投影）。"""
        conn = self.engine.thread_connection()
        with self.engine.transaction(conn, on_error="全文索引重建失败"):
            conn.execute("INSERT INTO content_fts(content_fts) VALUES('rebuild')")

    def stats(self) -> dict[str, int]:
        conn = self.engine.thread_connection()
        pages = conn.execute("SELECT count(*) FROM text_pages").fetchone()[0]
        docs = conn.execute("SELECT count(DISTINCT doc_id) FROM text_pages").fetchone()[0]
        chars = conn.execute("SELECT coalesce(sum(char_count), 0) FROM text_pages").fetchone()[0]
        return {"pages": pages, "docs": docs, "chars": chars}
