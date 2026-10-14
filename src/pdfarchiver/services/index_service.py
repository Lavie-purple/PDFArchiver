"""正文索引 —— 把一份 PDF 变成 `text_pages` + `content_fts` + `document_metadata` + 状态位。

`scan_service` 只回答"磁盘上有没有这个文件"，这一层回答"这个文件里写了什么"。
两条链路各自只有一个写入口，界面不必猜是谁改的状态。

四条口径：

1. **内容有没有变，看 sha256；路径和文件名都不算证据**（SPEC 阶段 2 安全要求）。
   每份文档先整体算一次哈希再决定要不要抽取。全量语料 120.6GB、哈希 240MB/s（p2 实测）
   ≈ 502 秒，而抽取 200 万页按 147.9 页/s 要 3.8 小时 —— 哈希这点钱不值得省，
   它换来的是"改过名字没改内容""只被 touch 过没被改过"这两类文件**不必重抽**。
2. **`fts_status` 在这里只用四个值：`pending`/`stale` → `done` 或 `failed`，从不写 `running`**。
   任务在不在跑，`processing_jobs` 那一行说得比文档表清楚，而且它是进程内的状态；
   把"正在索引"抄进文档表，就造出了一个"进程一崩就永远出不来"的状态：
   重启后既没人把它当未完成（`NEEDS_INDEX_STATUSES` 里没有它），也没人把它当完成。
   现在崩溃时的文档还停在 `pending`/`stale`，`resume_pending()` 自然把它捞回来。
3. **一页读不出来不等于整本失败**（`parsing.pdf` 第 2 条在这里落地）：坏页不入库，
   其余页照写，`parse_status='degraded'` 并留下第一条原文。
   整本打不开、或**一页都没读出来**才叫失败 —— 后者写 `done` 会让状态页显示"这份已索引"
   而它一行正文都没有，两个字段对同一件事各说一套。失败一律留 `fts_status='failed'` + 原文。
4. **正文一个字都不许"整理"**：入库前只做 `normalize_page_text`（连续空白压成一个空格），
   那是命中问题不是美观问题（见 `indexing/normalize`）。不改大小写、不删标点、不裁长度。

**这一层不移动、不删除、不改写任何用户文件**（SPEC 3.6 / 阶段 2 安全要求）：
只读打开 PDF，写完自己的库。`PermanentFailure` 与瞬时故障分开走，理由见 `jobs/queue.py`。
"""
from __future__ import annotations

import hashlib
import logging
import os
import time
from dataclasses import dataclass

from pdfarchiver.db.models import Document, TextPage
from pdfarchiver.db.repositories.documents import DocumentRepository
from pdfarchiver.db.repositories.metadata import MetadataRepository
from pdfarchiver.db.repositories.text import TextRepository
from pdfarchiver.indexing.normalize import normalize_page_text
from pdfarchiver.jobs.queue import PROGRESS_STEP_PAGES, JobCancelled, PermanentFailure
from pdfarchiver.parsing.classify import PageTally, TEXT_FAILED, ocr_status_for
from pdfarchiver.parsing.pdf import PdfOpenError, PdfReader

log = logging.getLogger("pdfarchiver.index")

HASH_CHUNK_BYTES = 1 << 20   # 1 MiB。分块读是"绝不整本进内存"的唯一实现处，所以给它一个名字好断言
TEXT_SEARCHABLE = ("native", "mixed")   # 只有这两种 text_status 才可能从正文里搜出东西


@dataclass
class IndexOutcome:
    """一份文档的一次索引。测试和状态页读的都是这个，不再各自拼一遍。"""

    doc_id: int
    page_count: int = 0
    stored_pages: int = 0
    text_status: str = "pending"
    parse_status: str = "pending"
    ocr_status: str = "na"
    fts_status: str = "pending"
    skipped_unchanged: bool = False
    took_ms: int = 0

    @property
    def searchable(self) -> bool:
        return self.fts_status == "done" and self.text_status in TEXT_SEARCHABLE

    def describe(self) -> str:
        return (f"{self.page_count} 页 / 入库 {self.stored_pages} 页｜parse={self.parse_status} "
                f"text={self.text_status} ocr={self.ocr_status} fts={self.fts_status}"
                + ("｜哈希未变，跳过重抽" if self.skipped_unchanged else ""))


def _digest_of(path: str) -> str:
    """整文件 sha256。最大单文件 1.1GB（p2），所以必须按块喂，不许 `read()` 一把。"""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(HASH_CHUNK_BYTES), b""):
            digest.update(chunk)
    return digest.hexdigest()


class IndexService:
    """`index` 任务的处理体。一个实例服务所有 worker 线程：
    它不持有任何跨文档状态（每份文档的行都在方法局部生灭），所以无须加锁。"""

    def __init__(self, documents: DocumentRepository, texts: TextRepository,
                 metadata: MetadataRepository) -> None:
        self.documents = documents
        self.texts = texts
        self.metadata = metadata

    # —— 任务入口 ————————————————————————————————————————

    def handle(self, job, monitor) -> None:
        """`kind='index'` 的处理函数。`doc_id=NULL` 在这里是用法错误而不是"扫全部" ——
        全量扫描是 `scan` 任务的活，混在一起会让"索引一份文档"和"索引整盘"共用一个入口。"""
        if job.doc_id is None:
            raise PermanentFailure("索引任务必须指向一份具体文档；全量扫描任务的 doc_id 才是 NULL")
        self.index_document(int(job.doc_id), monitor)

    def index_document(self, doc_id: int, monitor=None) -> IndexOutcome:
        """索引一份文档。`monitor=None` 供测试与"就索引这一份"的直接调用使用。"""
        doc = self.documents.get(doc_id)
        if doc is None:
            raise PermanentFailure(f"主记录 {doc_id} 不存在，无法索引")
        if doc.missing_since is not None or not os.path.exists(doc.path):
            # 补一次缺失状态再判死：这条索引任务不该"猜"文件去哪了，而文档状态必须说真话。
            self.documents.mark_missing(doc.path_key)
            raise PermanentFailure(f"文件已不在磁盘上：{doc.path}")

        started = time.perf_counter()
        digest = _digest_of(doc.path)
        cached = self._unchanged(doc, digest)
        if cached is not None:
            cached.took_ms = int((time.perf_counter() - started) * 1000)
            log.info("索引短路 id=%s %s｜%s", doc_id, cached.describe(), doc.path)
            return cached

        try:
            with PdfReader(doc.path) as reader:
                outcome = self._extract(doc, reader, digest, monitor)
        except PdfOpenError as exc:
            # 打不开就是打不开，再试三次也不会不一样；原文必须留下（AGENTS.md 排障条）。
            self._record_failure(doc, f"{type(exc.cause).__name__}: {exc.cause}", page_count=None)
            raise PermanentFailure(str(exc)) from exc
        outcome.took_ms = int((time.perf_counter() - started) * 1000)
        log.info("索引完成 id=%s %s｜%s", doc_id, outcome.describe(), doc.path)
        return outcome

    def rebuild_fts(self) -> dict[str, int]:
        """按需重建全文索引（阶段 5 第 7 条）：`content_fts` 整表按 `text_pages` 重算。

        什么时候真需要它：外部内容表只是投影，触发器漏写、手工动过库、从备份恢复之后
        投影会与真身不一致 —— 而 `check_fts_consistency()` 的两个方向是能被数出来的证据
        （实测：坏状态下 rebuild 之后 `MATCH` 命中数与索引花名册全部重新对齐，这条是真补救）。
        返回六个可核对的数，让调用方能把"重建前 vs 重建后"说出来，而不是只回一句"重建完成"。
        OCR 文本不需要单独的重建入口：它和原生文本住在同一张 `text_pages` 里，
        重算投影时一起进去，来源仍按行上的 `source_kind` 区分。
        """
        stats = self.texts.stats()
        before = self.texts.check_fts_consistency()
        self.texts.rebuild_all()
        after = self.texts.check_fts_consistency()
        log.info("全文索引重建：正文 %d 行（%d 份）｜%s → %s",
                 stats["pages"], stats["docs"], before.describe(), after.describe())
        return {"pages": stats["pages"], "docs": stats["docs"],
                "unindexed_before": before.unindexed, "unindexed_after": after.unindexed,
                "stale_before": before.stale_docsize, "stale_after": after.stale_docsize}

    # —— 单份文档的抽取 ——————————————————————————————————

    def _extract(self, doc: Document, reader: PdfReader, digest: str, monitor) -> IndexOutcome:
        info = reader.info
        if info.needs_pass:
            self._record_failure(doc, "PDF 已加密且需要密码", page_count=info.page_count,
                                 needs_pass=1, is_repaired=info.is_repaired, is_pdf=info.is_pdf)
            raise PermanentFailure(f"PDF 已加密且需要密码：{doc.path}")

        doc_id = int(doc.id)  # type: ignore[arg-type]
        if monitor is not None:
            monitor.set_total(info.page_count)
        tally = PageTally()
        rows: list[TextPage] = []
        first_error: str | None = None
        since_check = 0
        for page in reader.iter_text_pages():
            tally.add(page)
            if page.error is not None:
                first_error = first_error or f"第 {page.page_no} 页｜{page.error}"
            else:
                body = normalize_page_text(page.text)
                if body:
                    rows.append(TextPage(doc_id=doc_id, page_no=page.page_no, body=body))
            if monitor is not None:
                monitor.advance()
                since_check += 1
                if since_check >= PROGRESS_STEP_PAGES:
                    since_check = 0
                    if monitor.cancelled():
                        # 在写库之前退出：文档状态保持 pending/stale，正文保持上一版完整副本。
                        # 半途写进去的正文会让"这份索引好了"和"这份没索引好"变成看不出区别的两件事。
                        raise JobCancelled(
                            f"第 {page.page_no}/{info.page_count} 页时取消，文档状态未写")

        verdict = tally.verdict()
        if verdict.text_status == TEXT_FAILED:
            # 一页都没读出来 = 整本读不出来，这次索引就没有成功这回事。
            # 这时候写 `fts_status='done'` 等于让两个字段对同一件事各说一套
            # （正文 0 行、text_status='failed'，而状态页上它显示"已索引"），
            # 也和文件打不开一样不该重试 —— 重试三次也不会突然读出字来。
            detail = first_error or "没有任何一页能读出内容"
            self._record_failure(doc, detail, page_count=info.page_count,
                                 needs_pass=0, is_repaired=info.is_repaired, is_pdf=info.is_pdf)
            raise PermanentFailure(f"整本读不出内容：{doc.path}｜{detail}")

        ocr_status = ocr_status_for(verdict)
        parse_status = _parse_status(info.is_repaired, verdict.text_status, verdict.error_pages)
        # 先落正文再落状态：反过来会留一小段"状态 done 而正文还是旧的"（触发器让索引跟着正文走）。
        self.texts.replace_pages(doc_id, rows)
        # 整本重抽 = OCR 那些行已经没了（replace_pages 删的是这份文档的全部正文页）。
        # 不一起清零，库里就留着"这份有 900 页 OCR 文本"的谎，而幂等判据正是照着这个数跳过的。
        self.documents.reset_ocr_tracking(doc_id)
        self.metadata.replace(doc_id, info.as_metadata_row())
        self.documents.mark_index_result(
            doc_id, sha256=digest, page_count=info.page_count,
            parse_status=parse_status, text_status=verdict.text_status,
            text_bearing_rate=verdict.text_bearing_rate,
            fts_status="done", ocr_status=ocr_status,
            needs_pass=0, is_repaired=1 if info.is_repaired else 0,
            is_pdf=1 if info.is_pdf else 0, last_error=first_error)
        return IndexOutcome(doc_id=doc_id, page_count=info.page_count, stored_pages=len(rows),
                            text_status=verdict.text_status, parse_status=parse_status,
                            ocr_status=ocr_status, fts_status="done")

    # —— 未变短路 / 失败记录 ————————————————————————————

    def _unchanged(self, doc: Document, digest: str) -> IndexOutcome | None:
        """哈希与上次一样**且正文行还在库里** → 不必重抽，把状态收回 `done` 就完事。

        两个条件缺一个都不许短路：哈希相同但正文已经不在了（清过库、删过档），
        短路等于宣布"这份能搜"而它一个字都搜不出来 —— 那正是 SPEC 禁止的虚假有效结果。
        """
        if not doc.sha256 or doc.sha256 != digest:
            return None
        doc_id = int(doc.id)  # type: ignore[arg-type]
        stored = self.texts.count_pages(doc_id)
        if stored == 0:
            return None
        if doc.fts_status != "done":
            self.documents.set_fts_status(doc_id, "done")
        return IndexOutcome(doc_id=doc_id, page_count=doc.page_count or 0, stored_pages=stored,
                            text_status=doc.text_status, parse_status=doc.parse_status,
                            ocr_status=doc.ocr_status, fts_status="done", skipped_unchanged=True)

    def _record_failure(self, doc: Document, error: str, *, page_count: int | None,
                        needs_pass: int = 0, is_repaired: bool = False, is_pdf: bool = True) -> None:
        """失败也要把状态写全：`failed` + 原文，状态页才回答得出"这份为什么搜不到"，
        而不是留一个看起来"还没开始"的 pending。`page_count=None` 就是"页数不知道"，
        不拿上一次的旧值冒充这次的结论。"""
        assert doc.id is not None
        self.documents.mark_index_result(
            int(doc.id), sha256=doc.sha256, page_count=page_count,
            parse_status="failed", text_status="failed", text_bearing_rate=None,
            fts_status="failed", ocr_status="na", needs_pass=needs_pass,
            is_repaired=1 if is_repaired else 0, is_pdf=1 if is_pdf else 0,
            last_error=error[:500])   # 截的是日志列宽，不是错误本身；完整原文在日志文件里


def _parse_status(is_repaired: bool, text_status: str, error_pages: int) -> str:
    """`parse_status` 的唯一映射：整本读不出=failed，修过或有坏页=degraded，其余 ok。
    四个取值里的 `pending` 属于"还没解析过"，由扫描层写下，不由这一层产出。"""
    if text_status == "failed":
        return "failed"
    if is_repaired or error_pages:
        return "degraded"
    return "ok"
