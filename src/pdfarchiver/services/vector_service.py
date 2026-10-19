"""语义向量写路径 —— 谁该建向量、怎么建、建完写什么状态（**ISSUES I63** 丙 + 丁）。

`semantic/vector_store.py` 只管"把向量落盘"，`semantic/embedding.py` 只管"文本 → 向量"，
这一层只管**决策与落库** —— 与 `services/ocr_service.py` 是同一形状的两层拆分：
判"要不要跑"只有一个入口，界面 / 队列 / 状态页问的是同一个函数。

入账（**ISSUES I63**）之前这一层的缺法是：`VectorStore.add / add_batch / delete_by_doc`
在 `src/` 下零产品调用方（只有 `gates/stage6.py` 夹具用），`jobs.KINDS` 里的 `"vector"`
从不入队，`vector_status` 恒为 `Document` 默认值 `na` —— 所以它是**读数**不是判定：
p12 C7「向量状态取值都在口径内」恒绿，但那个"在口径内"只是"全都停在初始值 na"。
这一轮把写路径接进产品，让 `vector_status` 真有人推进、`VectorStore` 真有人调、`"vector"`
真能入队。

七条口径：

1. **只跑用户显式点名的文档**（沿用 OCR 的阶段 5 决策 Q3=甲）。这一层没有"扫一遍全库把
   pending 都排上"的入口 —— 一条 embedding 任务对一份 946 页的文件就是 946 次模型前向，
   全库自动建向量会把 GPU 时间烧在没有明确诉求的地方。`request_vectors(doc_ids)` 是唯一入口。
2. **入场券是一份可搜的正文判定**（`TEXT_SEARCHABLE`：`native` / `mixed`）：没正文就没东西可嵌。
   对一份从没索引过的文档直接建向量，只会得到一堆"空页向量"污染语义搜索。
3. **一页一向量**（D-036：1 chunk/页）。取 `texts.pages_of(doc_id)` 的每一页正文，
   整页交给模型（模型自己按 `MAX_LENGTH` 截断），不给一页造多个向量 —— 存储侧的
   `vector_meta(doc_id, page_no)` 就是按页唯一键设计的。
4. **失败一律留 `vector_status='failed'` + 原文，绝不伪装成功**（AGENTS.md 三级降级 / 不许伪装成功）。
   模型没装（`FileNotFoundError`）是这一层最常撞的失败：真库 `%LOCALAPPDATA%/PdfArchiver/models`
   今天就不存在。这种失败当场写 `failed` 并把 `FileNotFoundError` 原文进 `last_error`，
   而不是停在 `na` 让人以为"还没跑" —— "跑不了"和"没跑"是两个状态，界面上要能分开说。
5. **重嵌前先删旧向量**（`delete_by_doc`）：这是 `VectorStore.delete_by_doc` 在产品里的调用方。
   正文变了要重建时，旧向量不清就会让语义搜索同时命中新旧两版，命中页对不上真身。
6. **空正文页不建向量**：`char_count=0` 的页跳过，与"这一页本来就没字"是同一件事；
   给它建一条向量等于往语义索引里塞一条谁也不该命中的行。
7. **可取消**：逐页 embedding 是这份服务里最长的循环，每页前问一次 `monitor.cancelled()`，
   中途停下时 `vector_status` 留在 `stale`（写了半截也不算 `done`）并抛 `JobCancelled`。

这一层**只读 `text_pages`、只写 `vector_meta` + `vectors.npy` + `documents.vector_status`**：
不碰用户磁盘上的 PDF（SPEC 3.6 默认不动用户文件）。
"""
from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass

import numpy as np

from pdfarchiver.db.models import Document
from pdfarchiver.db.repositories.documents import DocumentRepository
from pdfarchiver.db.repositories.jobs import JobRepository
from pdfarchiver.db.repositories.text import TextRepository
from pdfarchiver.jobs.queue import JobCancelled, PermanentFailure
from pdfarchiver.services.index_service import TEXT_SEARCHABLE

log = logging.getLogger("pdfarchiver.vector.service")

# `vector_status` 的状态机（口径值本身在 `db/models.py` 的 `VECTOR_STATUSES`，这里只命名用到的那几个）
VECTOR_NA = "na"
VECTOR_PENDING = "pending"
VECTOR_RUNNING = "running"
VECTOR_DONE = "done"
VECTOR_FAILED = "failed"
VECTOR_STALE = "stale"

SKIP_ABSENT = "absent"
SKIP_NOT_SEARCHABLE = "not_searchable"

SKIP_LABELS = {
    SKIP_ABSENT: "库里没有这份主记录",
    SKIP_NOT_SEARCHABLE: "没有可搜的正文，先索引",
}


@dataclass
class VectorOutcome:
    """一份文档的一次向量构建。状态页、测试、门禁读的都是这个，不各自拼一遍。"""

    doc_id: int
    pages_expected: int = 0
    pages_embedded: int = 0
    pages_skipped_empty: int = 0
    vectors_written: int = 0
    vector_status: str = VECTOR_NA
    stopped_cancelled: bool = False
    took_ms: int = 0
    last_error: str | None = None

    def describe(self) -> str:
        out = (f"应建 {self.pages_expected} 页｜本次嵌入 {self.pages_embedded} 页｜"
               f"空页跳过 {self.pages_skipped_empty} 页｜写入 {self.vectors_written} 条向量｜"
               f"vector_status={self.vector_status}")
        if self.stopped_cancelled:
            out += "｜中途取消，停在半路"
        return out


@dataclass(frozen=True)
class VectorRequest:
    """一次点名的回执。`skipped` 是 理由 → doc_id 列表，指得到具体是哪几份。

    `queueable` 与 `enqueued` 可以不一样：前者是"该建"，后者是队列里**新增**的条数
    （同名任务已在队列里时 `enqueue_many` 去重，不重复计工）。
    """

    named: int
    queueable: int
    enqueued: int
    skipped: dict[str, list[int]]

    def describe(self) -> str:
        out = f"点名 {self.named} 份｜该建 {self.queueable} 份｜新增任务 {self.enqueued} 条"
        for reason, ids in sorted(self.skipped.items()):
            out += f"｜{SKIP_LABELS[reason]} {len(ids)} 份"
        return out


class VectorService:
    """`kind='vector'` 任务的处理体，也是"用户点名建向量"的唯一入口。

    一个实例服务所有 worker 线程；跨文档没有共享状态（每份的页集合都在方法局部生灭）。
    真正串行发生在 `EmbeddingService` 的推理（ONNX session 线程安全，但 DirectML 上并发前向
    会抢显存）与 `VectorStore` 的文件写里。
    """

    def __init__(self, documents: DocumentRepository, texts: TextRepository,
                 jobs: JobRepository, embedding, vector_store) -> None:
        self.documents = documents
        self.texts = texts
        self.jobs = jobs
        self.embedding = embedding
        self.vector_store = vector_store

    # —— 显式触发（沿用 OCR 的"用户点名"口径）——————————————————

    def request_vectors(self, doc_ids: list[int] | tuple[int, ...]) -> VectorRequest:
        """把用户点名的文档排进向量队列，并如实回执哪几份没排、为什么。"""
        ids = sorted({int(i) for i in doc_ids})
        if not ids:
            return VectorRequest(named=0, queueable=0, enqueued=0, skipped={})
        docs = self.documents.by_ids(ids)
        queueable: list[int] = []
        skipped: dict[str, list[int]] = {}
        for doc_id in ids:
            reason = self._why_skipped(docs.get(doc_id))
            if reason is None:
                queueable.append(doc_id)
            else:
                skipped.setdefault(reason, []).append(doc_id)
        enqueued = self.jobs.enqueue_many("vector", queueable)
        request = VectorRequest(named=len(ids), queueable=len(queueable),
                                enqueued=enqueued, skipped=skipped)
        log.info("向量排队：%s｜%s", request.describe(),
                 "; ".join(f"{r}={v}" for r, v in sorted(skipped.items())) or "无跳过")
        return request

    def _why_skipped(self, doc: Document | None) -> str | None:
        """点名的一份能不能进队列；能进返回 None，不能进返回理由常量。"""
        if doc is None:
            return SKIP_ABSENT          # 主记录不在了就不排，别让 worker 拿到一条空任务
        if doc.text_status not in TEXT_SEARCHABLE:
            return SKIP_NOT_SEARCHABLE  # 没可搜的正文就没东西可嵌
        return None

    # —— 任务入口 ——————————————————————————————————————

    def handle(self, job, monitor) -> None:
        """`kind='vector'` 的处理函数。`doc_id=NULL` 是用法错误，不是"扫全部"。"""
        if job.doc_id is None:
            raise PermanentFailure("向量任务必须指向一份具体文档；全库自动建向量按 D-006 不存在")
        self.build_vectors(int(job.doc_id), monitor)

    def build_vectors(self, doc_id: int, monitor=None) -> VectorOutcome:
        """为一份文档重建语义向量。`monitor=None` 供测试与"就建这一份"的直接调用使用。"""
        doc = self.documents.get(doc_id)
        if doc is None:
            raise PermanentFailure(f"主记录 {doc_id} 不存在，无法建向量")
        if doc.missing_since is not None or not os.path.exists(doc.path):
            self.documents.mark_missing(doc.path_key)
            raise PermanentFailure(f"文件已不在磁盘上：{doc.path}")
        if doc.text_status not in TEXT_SEARCHABLE:
            raise PermanentFailure(
                f"这份还没有可搜的正文（text_status={doc.text_status}），"
                f"先索引才能建向量：{doc.path}")

        started = time.perf_counter()
        outcome = VectorOutcome(doc_id=doc_id)
        self.documents.set_vector_status(doc_id, VECTOR_RUNNING)

        pages = self.texts.pages_of(doc_id)
        todo = [p for p in pages if p.char_count and p.body]
        outcome.pages_expected = len(pages)
        outcome.pages_skipped_empty = len(pages) - len(todo)

        if monitor is not None:
            monitor.set_total(len(todo))

        # 重嵌前先清旧向量（口径 5）：正文变了要重建时，旧向量不清会让语义搜索同时命中新旧两版。
        self.vector_store.delete_by_doc(doc_id)

        try:
            vectors: list[tuple[int, int, np.ndarray]] = []
            for page in todo:
                if monitor is not None and monitor.cancelled():
                    # 停在半路：写了半截也不算 done（口径 7），把状态留回 stale 等下次按需重跑。
                    self.documents.set_vector_status(doc_id, VECTOR_STALE)
                    outcome.vector_status = VECTOR_STALE
                    outcome.stopped_cancelled = True
                    outcome.took_ms = int((time.perf_counter() - started) * 1000)
                    raise JobCancelled(f"建向量被取消，停在第 {len(vectors)}/{len(todo)} 页")
                vec = self.embedding.embed_single(page.body)
                vectors.append((doc_id, int(page.page_no), vec))
                outcome.pages_embedded += 1
                if monitor is not None:
                    monitor.advance()
            written = self.vector_store.add_batch(vectors)
            outcome.vectors_written = len(written)
        except FileNotFoundError as exc:
            # 模型没装是最常撞的失败：当场写 failed + 原文，不停在 na 让人以为"还没跑"（口径 4）。
            self.documents.set_vector_status(doc_id, VECTOR_FAILED, error=str(exc))
            outcome.vector_status = VECTOR_FAILED
            outcome.last_error = str(exc)
            outcome.took_ms = int((time.perf_counter() - started) * 1000)
            log.warning("建向量失败 id=%s（语义模型不可用）：%s｜%s",
                        doc_id, outcome.describe(), doc.path)
            raise PermanentFailure(str(exc)) from exc

        self.documents.set_vector_status(doc_id, VECTOR_DONE)
        outcome.vector_status = VECTOR_DONE
        outcome.took_ms = int((time.perf_counter() - started) * 1000)
        log.info("建向量完成 id=%s %s｜%s", doc_id, outcome.describe(), doc.path)
        return outcome
