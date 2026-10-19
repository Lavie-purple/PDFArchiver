"""OCR 编排 —— 谁该跑、跑到哪一页、跑完写什么状态（阶段 5）。

`ocr/engine.py` 只管"识别一页"，这一层只管决策与落库。分成两层是为了让"要不要重跑"
只有一个判据（`parsing.classify.ocr_is_current`），界面、队列、状态页问的是同一个函数。

八条口径：

1. **只跑用户显式点名的文档**（阶段 5 决策 Q3=甲）。这一层没有"扫一遍全库把 pending 都排上"
   的入口 —— p5 实测那条路是 1,144 GPU 小时 = 143 个工作日。D-006 的"用户显式触发"在这里
   落地成 `request_ocr(doc_ids)`：没有 doc_ids 就没有任务。点名的份数不等于进队列的份数，
   回执 `OcrRequest` 必须说清每一份为什么没进去（指到 doc_id），否则"我明明勾了 40 份"
   和"队列里只有 3 份"之间的差额就没人解释得了。
   **入场券是一份可用的正文判定**（`classify.ocr_ready`）：还没索引的文档连"哪几页缺字"都不知道，
   直接跑会把文字版 PDF 的每一页都识别一遍。
2. **页级幂等，不是本级**。`text_pages.ocr_version` 记每一页当初是哪个版本跑出来的：
   混合文档重跑只补没跑过的页，引擎升版也只重跑旧版页。**空白页照样记版本** ——
   识别成功但没字，是"这一页本来就没字"，与"这一页失败了"是两件事（见第 3 条）。
3. **失败页不写行**。出图失败或推理抛异常的页什么都不写，于是下次的 `pages_needing_ocr`
   自然把它算回待办 —— 重试不需要额外的状态位。反过来若给失败页写了空行，
   它就永远被当成"跑过了"，瞬时故障（显存不够、临时占用）会被记成永久结论。
4. **单页失败连坐范围止于该页**。整本打不开 / 加密要密码才是这份文档失败
   （`PermanentFailure`，重试也不会有第二个结果）。全部页都失败写 `failed`，
   有失败但其余进去了写 `partial`，**绝不因为"大部分成功"就写 done** ——
   写 done 等于对界面宣布"这本书搜得全"，而它有几页一个字都没进去。
5. **OCR 文本与原生文本是两个来源**（`source_kind='native'` / `'ocr'`），检索层必须能分开说。
   SPEC 五·不得把未经验证的识别文字伪装成准确的原始文本。
6. **一次只握一页位图**：`iter_page_images()` 是生成器，逐页出图、逐页识别、逐页落库
   （一页一事务）。最大单文件 946 页 / 1.1GB（p2），200dpi 单页位图约 11MB ——
   攒一整本再处理就是 ~10GB 内存，这条路根本走不通（AGENTS.md 禁止全量加载）。
7. **每日页预算跑满即停**（G13 作废重定，推导见 `ocr/budget.py` 与 docs/DECISIONS.md D-028）：
   停在半路的那份写 `partial` 并把原因留进 `last_error`；一页都来不及跑的写回 `pending`，
   状态绝不前进 —— 写 done 就等于宣布"这本书搜得全"。未识别的页没有版本行，明天自动回到待办。
8. **单页耗时超过反算上限就不跑下去了**：那一页不写行（下次重来），整份停下。
   拦的是病态文件，不是"今天显卡被别人占着所以慢两倍"—— 上限取实测最大值 ×2，就是为了这个。

这一层**只读用户文件**：不出图落盘、不改名、不移动、不删除（SPEC 3.6 默认不动用户文件）。
"""
from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field

from pdfarchiver.db.models import Document, TextPage
from pdfarchiver.db.repositories.documents import DocumentRepository
from pdfarchiver.db.repositories.jobs import JobRepository
from pdfarchiver.db.repositories.text import TextRepository
from pdfarchiver.indexing.normalize import normalize_page_text
from pdfarchiver.jobs.queue import JobCancelled, PermanentFailure
from pdfarchiver.ocr.budget import PAGE_MS_RANGE, OcrBudget, page_timeout_ms
from pdfarchiver.ocr.engine import OcrEngine, OcrPage
from pdfarchiver.parsing.classify import MIN_CHARS_PER_BEARING_PAGE, OCR_DONE, OCR_NA, \
    OCR_PARTIAL, OCR_PENDING, ocr_is_current, ocr_ready
from pdfarchiver.parsing.pdf import PdfOpenError, PdfReader

log = logging.getLogger("pdfarchiver.ocr.service")

# ISSUES I21：连续 N 页超时就把这份判 failed（熔断器）。
# 进程隔离故意不做（D-008 串行 + 页级幂等已保证杀进程不丢已入库的页），
# 但如果整本都是病态页，逐页烧 GPU 时间而不产出就是浪费。
# 阈值 3 = 给偶发慢页留余量（显卡临时被占），连续 3 页都超时基本说明这份文件有问题。
CONSECUTIVE_TIMEOUT_LIMIT = 3


@dataclass
class OcrOutcome:
    """一份文档的一次 OCR。状态页、测试、门禁读的都是这个，不各自拼一遍。"""

    doc_id: int
    pages_expected: int = 0
    pages_recognized: int = 0
    pages_reused: int = 0
    pages_failed: int = 0
    chars_added: int = 0
    ocr_status: str = "pending"
    skipped_current: bool = False
    stopped_on_budget: bool = False
    stopped_on_timeout: bool = False
    stopped_on_circuit_breaker: bool = False  # ISSUES I21：连续超时熔断
    took_ms: int = 0
    last_error: str | None = None

    def describe(self) -> str:
        out = (f"应识别 {self.pages_expected} 页｜本次新识别 {self.pages_recognized} 页｜"
               f"版本未变直接复用 {self.pages_reused} 页｜失败 {self.pages_failed} 页｜"
               f"新增 {self.chars_added} 字｜ocr_status={self.ocr_status}")
        if self.skipped_current:
            out += "｜已是当前版本，连文件都没开"
        if self.stopped_on_budget:
            out += "｜今日页预算用满，停在半路"
        if self.stopped_on_timeout:
            out += "｜单页耗时超过上限，这份停下"
        if self.stopped_on_circuit_breaker:
            out += f"｜连续 {CONSECUTIVE_TIMEOUT_LIMIT} 页超时，熔断器触发"
        return out

    @property
    def ms_per_page(self) -> float:
        """本次实际推理的均值。**没有推理过就返回 0**，不拿复用的页数摊薄出一个好看的均值。"""
        return round(self.took_ms / self.pages_recognized, 1) if self.pages_recognized else 0.0


def pages_needing_ocr(native: dict[int, int], done_versions: dict[int, str | None],
                      page_count: int, version_now: str) -> tuple[list[int], int]:
    """该跑哪几页 —— 唯一判据。`page_count` 用 PDF 自己的页数（1 基连续）。

    返回 `(待跑的页码, 可直接复用的页数)`。"原生字数已达 p2 口径的 40 字"的页不在两者之内：
    它有字，本来就不用 OCR。判定阈值只在 `parsing.classify` 有一份，这里只调用。
    """
    todo: list[int] = []
    reused = 0
    for page_no in range(1, page_count + 1):
        if native.get(page_no, 0) >= MIN_CHARS_PER_BEARING_PAGE:
            continue
        if done_versions.get(page_no) == version_now:
            reused += 1
            continue
        todo.append(page_no)
    return todo, reused


SKIP_ABSENT = "absent"
SKIP_NO_VERDICT = "no_verdict"
SKIP_NOT_NEEDED = "not_needed"
SKIP_CURRENT = "already_current"
SKIP_BUDGET = "budget_exhausted"

# 理由的中文名只在这里写一份：回执要给界面看，界面不许自己再翻译一遍（AGENTS.md 禁止核心概念多口径）。
SKIP_LABELS = {
    SKIP_ABSENT: "库里没有这份主记录",
    SKIP_NO_VERDICT: "没有可用的正文判定，先索引",
    SKIP_NOT_NEEDED: "判定为不需要 OCR",
    SKIP_CURRENT: "已是当前引擎版本",
    SKIP_BUDGET: "今天的页预算已用满（明日自动恢复）",
}


@dataclass(frozen=True)
class OcrRequest:
    """一次点名的回执。`skipped` 是 理由 → doc_id 列表，指得到具体是哪几份。

    `queueable` 与 `enqueued` 可以不一样：前者是"该跑"，后者是队列里**新增**的条数
    （同名任务已在队列里时 `enqueue_many` 去重，不重复计工）。
    """

    named: int
    queueable: int
    enqueued: int
    skipped: dict[str, list[int]] = field(default_factory=dict)

    def describe(self) -> str:
        out = f"点名 {self.named} 份｜该跑 {self.queueable} 份｜新增任务 {self.enqueued} 条"
        for reason, ids in sorted(self.skipped.items()):
            out += f"｜{SKIP_LABELS[reason]} {len(ids)} 份"
        return out


#: 面板上那一行"展开"之后列几个文件名。再多就只是滚动条，不是信息（判定②要的是"指得到是哪几份"）。
NAME_PREVIEW_LIMIT = 12


@dataclass(frozen=True)
class SkippedDoc:
    """被跳过的某一份：id 给机器，名字给人看。"""

    doc_id: int
    name: str


@dataclass(frozen=True)
class SkippedReason:
    """一类跳过理由连同它底下那几份 —— **ISSUES I67** 销账判定②要求的形状：每一类都能指到具体是哪几份。"""

    reason: str
    docs: tuple[SkippedDoc, ...]

    def label(self) -> str:
        return f"{SKIP_LABELS[self.reason]}（{len(self.docs)} 份）"

    def name_preview(self, limit: int = NAME_PREVIEW_LIMIT) -> str:
        shown = "、".join(doc.name for doc in self.docs[:limit])
        left = len(self.docs) - limit
        return shown + (f"（还有 {left} 份没列出）" if left > 0 else "")


@dataclass(frozen=True)
class OcrPlan:
    """一次批量点名**还没写队列之前**的账：这一批会跑几份、哪几份不跑、为什么不跑、要烧多少页。

    与 `OcrRequest` 的差别只有"不 enqueue"这一件：份数与理由走的是同一个 `_split`，
    所以面板上那句「该跑 7 份」与按下「排队」之后回执里那句「该跑 7 份」不会有一天不一样。
    线框 §I67-yi 那句「估算归服务层算，界面重算就是两个口径」在这里落地。
    """

    named: int
    queueable: tuple[int, ...]
    skipped: tuple[SkippedReason, ...]
    pages_queueable: int
    budget_remaining: int

    @property
    def skipped_count(self) -> int:
        return self.named - len(self.queueable)

    def describe(self) -> str:
        out = f"点名 {self.named} 份｜该跑 {len(self.queueable)} 份｜不跑 {self.skipped_count} 份"
        for item in self.skipped:
            out += f"｜{SKIP_LABELS[item.reason]} {len(item.docs)} 份"
        return out

    def cost_line(self) -> str:
        """代价那句。页数是**主记录口径**（`documents.page_count` 合计），不等于要推理的页数 ——
        已经有原生文字层的页不必 OCR，所以这句是上限而不是承诺，措辞里必须带着这件事。"""
        if not self.pages_queueable:
            return "这一批没有该跑的份，不烧页"
        lo, hi = PAGE_MS_RANGE
        return (f"这一批该跑的那几份主记录共 {self.pages_queueable:,} 页"
                f"（按主记录页数算，待推理的页可能更少）｜单页实测 {lo:,}–{hi:,}ms｜"
                f"预计 {self.pages_queueable * lo / 60_000:.1f}–"
                f"{self.pages_queueable * hi / 60_000:.1f} 分钟")

    def budget_note(self) -> str:
        """今日预算够不够跑完这一批。不够时必须上屏 —— 别让人对着一条永远不动的队列猜（**I67** ③）。"""
        if self.budget_remaining <= 0:
            return "今天的页预算已经用满：按下「排队」一条也不会进队列，明日自动恢复"
        if self.pages_queueable > self.budget_remaining:
            return ("今日预算不够跑完这一批：跑满即停，剩下的明天自动回到待办"
                    "（预算是资源闸门，强制也不绕）")
        return "今日预算够跑完这一批"


class OcrService:
    """`kind='ocr'` 任务的处理体，也是"用户点名重识别"的唯一入口。

    一个实例服务所有 worker 线程；跨文档没有共享状态（每份的页码集合都在方法局部生灭），
    真正的串行发生在 `OcrEngine` 的推理锁里（D-008）。
    """

    def __init__(self, documents: DocumentRepository, texts: TextRepository,
                 jobs: JobRepository, engine: OcrEngine, budget: OcrBudget) -> None:
        self.documents = documents
        self.texts = texts
        self.jobs = jobs
        self.engine = engine
        self.budget = budget

    # —— 显式触发（阶段 5 决策 Q3=甲）————————————————————————

    def request_ocr(self, doc_ids: list[int] | tuple[int, ...], *,
                    force: bool = False) -> OcrRequest:
        """把用户点名的文档排进 OCR 队列，并如实回执哪几份没排、为什么。

        `force=True` 时不做"判过不需要 OCR / 已是当前版本"这两道短路，但仍然**按页**决定是否重跑：
        版本没变的页一个字都不会再推理 —— 强制整本重跑一次的成本是按小时计的。
        """
        ids = sorted({int(i) for i in doc_ids})
        if not ids:
            return OcrRequest(named=0, queueable=0, enqueued=0)
        budget_hit = self.budget.exhausted()
        docs = self.documents.by_ids(ids)
        queueable, skipped = self._split(ids, docs, force, budget_hit=budget_hit)
        enqueued = self.jobs.enqueue_many("ocr", queueable)
        request = OcrRequest(named=len(ids), queueable=len(queueable), enqueued=enqueued,
                             skipped=skipped)
        if budget_hit:
            log.warning("OCR 排队被每日页预算挡住：%s｜%s", self.budget.describe(), request.describe())
        else:
            log.info("OCR 排队：%s｜%s", request.describe(),
                     "; ".join(f"{r}={v}" for r, v in sorted(skipped.items())) or "无跳过")
        return request

    def plan_ocr(self, doc_ids: list[int] | tuple[int, ...], *,
                 force: bool = False) -> OcrPlan:
        """批量点名面板（**ISSUES I67** 乙）要的那份账：算清哪几份该跑、哪几份不跑、为什么不跑。

        与 `request_ocr` 唯一的差别是**不写队列**，判据走的是同一个 `_split`。
        界面要想知道"该跑几份"只有这一条路：它自己判 `ocr_ready`、自己比版本号，
        就是第二个口径 —— 那两份数迟早会跟真排队的那份漂开（线框 §I67-yi 第三条硬条件）。
        代价：每份要读两三次库（`_is_current` 那条），是 O(点名份数) 的一次遍历，
        与真排队时服务层本来就做的那一遍同一量级。
        """
        ids = sorted({int(i) for i in doc_ids})
        remaining = self.budget.remaining()
        if not ids:
            return OcrPlan(named=0, queueable=(), skipped=(), pages_queueable=0,
                           budget_remaining=remaining)
        docs = self.documents.by_ids(ids)
        queueable, skipped = self._split(ids, docs, force, budget_hit=remaining <= 0)
        items = tuple(
            SkippedReason(
                reason,
                tuple(SkippedDoc(doc_id, docs[doc_id].name if doc_id in docs else "（主记录不在了）")
                      for doc_id in sorted(skipped_ids)))
            for reason, skipped_ids in sorted(skipped.items()))
        return OcrPlan(named=len(ids), queueable=tuple(queueable), skipped=items,
                       pages_queueable=sum(int(docs[i].page_count or 0) for i in queueable),
                       budget_remaining=remaining)

    def _split(self, ids: list[int], docs: dict[int, Document], force: bool, *,
               budget_hit: bool) -> tuple[list[int], dict[str, list[int]]]:
        """把点名的一串 id 分成「该跑」与「按理由归类的不跑」—— `request_ocr` 与 `plan_ocr` 共用这一条。

        两处各写一遍，"面板上说的"与"排队之后的回执"就是两个口径，那是 **ISSUES I60** 那一族。
        """
        if budget_hit:
            # 预算是资源闸门，不是幂等短路，所以 `force` 也不绕它：能绕开限额的限额等于没有限额。
            # 要今天就跑完，改 `settings.json` 的 `ocr_daily_page_budget`（并重启），别改代码。
            return [], {SKIP_BUDGET: list(ids)}
        queueable: list[int] = []
        skipped: dict[str, list[int]] = {}
        for doc_id in ids:
            reason = self._why_skipped(docs.get(doc_id), force)
            if reason is None:
                queueable.append(doc_id)
            else:
                skipped.setdefault(reason, []).append(doc_id)
        return queueable, skipped

    def _why_skipped(self, doc: Document | None, force: bool) -> str | None:
        """点名的一份能不能进队列；能进返回 None，不能进返回理由常量。"""
        if doc is None:
            return SKIP_ABSENT          # 主记录不在了就不排，别让 worker 拿到一条空任务
        if not ocr_ready(doc.text_status):
            return SKIP_NO_VERDICT
        if doc.ocr_status == OCR_NA and not force:
            return SKIP_NOT_NEEDED      # 判过不需要 OCR（原生文字版 / 整本读不出）
        if not force and self._is_current(doc):
            return SKIP_CURRENT
        return None

    def _is_current(self, doc: Document) -> bool:
        if not doc.page_count:
            return False
        doc_id = int(doc.id)  # type: ignore[arg-type]
        done = self.texts.ocr_versions_of(doc_id)
        _todo, reused = self._plan(doc, done)
        return ocr_is_current(ocr_status=doc.ocr_status, ocr_pages_done=len(done),
                              stored_version=_sole_version(done), version_now=self.engine.version_stamp,
                              pages_expected=reused + len(_todo)) and not _todo

    # —— 任务入口 ——————————————————————————————————————

    def handle(self, job, monitor) -> None:
        """`kind='ocr'` 的处理函数。`doc_id=NULL` 是用法错误，不是"扫全部"（见模块说明第 1 条）。"""
        if job.doc_id is None:
            raise PermanentFailure("OCR 任务必须指向一份具体文档；全库自动 OCR 按 D-006 不存在")
        self.ocr_document(int(job.doc_id), monitor)

    def ocr_document(self, doc_id: int, monitor=None, *, force: bool = False) -> OcrOutcome:
        """识别一份文档的待办页。`monitor=None` 供测试与"就识别这一份"的直接调用使用。"""
        doc = self.documents.get(doc_id)
        if doc is None:
            raise PermanentFailure(f"主记录 {doc_id} 不存在，无法 OCR")
        if doc.missing_since is not None or not os.path.exists(doc.path):
            self.documents.mark_missing(doc.path_key)
            raise PermanentFailure(f"文件已不在磁盘上：{doc.path}")
        if not ocr_ready(doc.text_status):
            # 没有正文判定就不知道哪几页缺字（见模块说明第 1 条）。这条不能省：
            # 对一份从没索引过的文字版 PDF 直接跑 OCR，会把每页都识别一遍，
            # 还把"OCR 识别（可能有错字）"的文本压到原生文本前面。
            raise PermanentFailure(
                f"这份还没有可用的正文判定（text_status={doc.text_status}），"
                f"先索引才能算出缺字的页：{doc.path}")

        started = time.perf_counter()
        version_now = self.engine.version_stamp
        done = self.texts.ocr_versions_of(doc_id)
        todo, reused = self._plan(doc, done)
        expected = len(todo) + reused

        # 整本级短路：待办为空且库里那几页就是当前版本 —— 连 PDF 都不必打开。
        if not force and expected and not todo and ocr_is_current(
                ocr_status=doc.ocr_status, ocr_pages_done=len(done),
                stored_version=_sole_version(done), version_now=version_now,
                pages_expected=expected):
            return self._skipped(doc_id, expected, reused, doc.ocr_status, started)

        try:
            with PdfReader(doc.path) as reader:
                outcome = self._run(doc, reader, todo, reused, expected, version_now,
                                    monitor, force, done)
        except PdfOpenError as exc:
            self.documents.mark_ocr_result(doc_id, ocr_status="failed",
                                           ocr_pages_done=len(self.texts.ocr_versions_of(doc_id)),
                                           last_error=f"{type(exc.cause).__name__}: {exc.cause}"[:500])
            raise PermanentFailure(str(exc)) from exc
        outcome.took_ms = int((time.perf_counter() - started) * 1000)
        log.info("OCR 结束 id=%s %s｜%s", doc_id, outcome.describe(), doc.path)
        return outcome

    def _plan(self, doc: Document, done: dict[int, str | None]) -> tuple[list[int], int]:
        """待跑页 —— 只读库，不开文件、不解析 PDF。"""
        doc_id = int(doc.id)  # type: ignore[arg-type]
        native = self.texts.native_page_chars(doc_id)
        return pages_needing_ocr(native, done, int(doc.page_count or 0), self.engine.version_stamp)

    def _skipped(self, doc_id: int, expected: int, reused: int, status: str,
                 t0: float) -> OcrOutcome:
        outcome = OcrOutcome(doc_id=doc_id, pages_expected=expected, pages_reused=reused,
                             ocr_status=status, skipped_current=True,
                             took_ms=int((time.perf_counter() - t0) * 1000))
        log.info("OCR 短路 id=%s %s", doc_id, outcome.describe())
        return outcome

    # —— 一份文档的识别 ——————————————————————————————————

    def _run(self, doc: Document, reader: PdfReader, todo: list[int], reused: int,
             expected: int, version_now: str, monitor, force: bool,
             done: dict[int, str | None]) -> OcrOutcome:
        doc_id = int(doc.id)  # type: ignore[arg-type]
        if reader.info.needs_pass:
            self.documents.mark_ocr_result(doc_id, ocr_status="failed",
                                           ocr_pages_done=len(done),
                                           last_error="PDF 已加密且需要密码，无法出图")
            raise PermanentFailure(f"PDF 已加密且需要密码：{doc.path}")

        page_count = int(reader.info.page_count or expected)
        if force:
            # 强制整本重识别 = 先把这份的 OCR 页清干净（原生页不动）。
            self.texts.delete_ocr_pages(doc_id)
            native = self.texts.native_page_chars(doc_id)
            todo, reused = pages_needing_ocr(native, {}, page_count, version_now)
            expected = len(todo) + reused
        elif int(doc.page_count or 0) != page_count and page_count:
            # 库里的页数与文件实际的页数不一样（索引之后文件被改过），待办按实际页数重算。
            native = self.texts.native_page_chars(doc_id)
            todo, reused = pages_needing_ocr(native, self.texts.ocr_versions_of(doc_id),
                                             page_count, version_now)
            expected = len(todo) + reused

        outcome = OcrOutcome(doc_id=doc_id, pages_expected=expected, pages_reused=reused)
        if not todo:
            outcome.ocr_status = _status_when_nothing_to_do(doc, expected, reused)
            self.documents.mark_ocr_result(doc_id, ocr_status=outcome.ocr_status,
                                           ocr_pages_done=len(self.texts.ocr_versions_of(doc_id)),
                                           last_error=None)
            return outcome

        pending = set(todo)
        # 进度按"这次真正要推理的页数"报，不按整本页数：混合文档第二次跑只剩 2 页待办，
        # 报 0/946 会让界面看起来像卡死（AGENTS.md：不许模拟进度，也不许留下没人看的分母）。
        if monitor is not None:
            monitor.set_total(len(todo))
        first_error: str | None = None
        consecutive_timeouts = 0  # ISSUES I21：连续超时计数
        for image in reader.iter_page_images(dpi=self.engine.dpi):
            if image.page_no not in pending:
                continue
            if self.budget.exhausted():
                self._stop_here(doc_id, outcome, reused,
                                f"跑到第 {image.page_no} 页之前今天的页预算用满"
                                f"（{self.budget.describe()}），未识别的页留在待办里", budget=True)
            pending.discard(image.page_no)
            if image.error is not None:
                outcome.pages_failed += 1
                first_error = first_error or f"第 {image.page_no} 页出图｜{image.error}"
                consecutive_timeouts = 0  # 出图失败不算超时，重置计数
            else:
                page: OcrPage = self.engine.recognize(image.page_no, image.pixels)
                self.budget.consume()      # 烧掉的 GPU 时间不论成败都已发生，失败页同样计入预算
                limit = page_timeout_ms(self.engine.provider)
                if page.error is None and page.took_ms > limit:
                    outcome.pages_failed += 1
                    consecutive_timeouts += 1
                    # ISSUES I21：连续超时熔断 —— 整本都是病态页时及时停下，不继续烧 GPU
                    if consecutive_timeouts >= CONSECUTIVE_TIMEOUT_LIMIT:
                        outcome.stopped_on_circuit_breaker = True
                        self._stop_here(
                            doc_id, outcome, reused,
                            f"连续 {consecutive_timeouts} 页识别超时"
                            f"（上限 {limit}ms/页，{self.engine.provider}），"
                            f"熔断器触发（阈值 {CONSECUTIVE_TIMEOUT_LIMIT}）；"
                            "这份文件可能整本都是病态页，停下等下次手动检查",
                            timeout=True)
                    else:
                        self._stop_here(doc_id, outcome, reused,
                                        f"第 {page.page_no} 页识别耗时 {page.took_ms:.0f}ms，"
                                        f"超过单页上限 {limit}ms（{self.engine.provider} 实测最大值 ×2 反算）；"
                                        "这一页不入库，整份停下等下次", timeout=True)
                elif page.error is not None:
                    outcome.pages_failed += 1
                    consecutive_timeouts = 0  # 推理错误不算超时，重置计数
                    first_error = first_error or f"第 {page.page_no} 页识别｜{page.error}"
                else:
                    consecutive_timeouts = 0  # 成功页重置计数
                    body = normalize_page_text(page.text)
                    outcome.chars_added += len(body)
                    outcome.pages_recognized += 1
                    self._record_page(doc_id, page.page_no, body, version_now)
            if monitor is not None:
                monitor.advance()
                if monitor.cancelled():
                    self._flush_partial(doc_id, outcome, first_error)
                    raise JobCancelled(f"第 {image.page_no}/{page_count} 页时取消，"
                                       f"已识别的 {outcome.pages_recognized} 页已入库")
            if not pending:
                break

        outcome.last_error = first_error
        outcome.ocr_status = _status_for(outcome, reused)
        self.documents.mark_ocr_result(doc_id, ocr_status=outcome.ocr_status,
                                       ocr_pages_done=len(self.texts.ocr_versions_of(doc_id)),
                                       last_error=first_error)
        return outcome

    def _record_page(self, doc_id: int, page_no: int, body: str, version_now: str) -> None:
        """一页一事务：崩溃或取消之后，已识别的页都在库里，下次接着跑剩下的。"""
        self.texts.upsert_pages(doc_id, [TextPage(
            doc_id=doc_id, page_no=page_no, body=body, source_kind="ocr",
            char_count=len(body), ocr_version=version_now)])

    def _flush_partial(self, doc_id: int, outcome: OcrOutcome, first_error: str | None) -> None:
        """取消/中断时把"已经吃下来的页数"如实写进去，否则下次的幂等判据看不见这次的成果。"""
        outcome.ocr_status = OCR_PARTIAL
        self.documents.mark_ocr_result(doc_id, ocr_status=OCR_PARTIAL,
                                       ocr_pages_done=len(self.texts.ocr_versions_of(doc_id)),
                                       last_error=first_error or "用户在跑到一半时取消")

    def _stop_here(self, doc_id: int, outcome: OcrOutcome, reused: int, reason: str, *,
                   budget: bool = False, timeout: bool = False) -> None:
        """停下这一份：如实写状态与原因，再抛 `JobCancelled` 让进度停在真实跑过的页数上。

        为什么抛 `JobCancelled` 而不是正常返回：正常返回会走队列的 `_finish_success`，
        那里把 `done` 补成 `total`（阶段 2 的反向注入 I19 抓的就是它）——
        一份只跑了一半的文档被记成"跑完了"，界面上就再也没人知道还有页没进去。
        `reason` 会原样落进任务行的 `last_error`（队列 `jobs/queue.py` 的第 3 条规矩：
        处理函数判停是第三种停，落 `cancelled` 终态），所以这句话必须自己说清
        停在哪一页、今天已经跑了多少页、以及明天会不会自动恢复。
        """
        outcome.stopped_on_budget = budget
        outcome.stopped_on_timeout = timeout
        outcome.last_error = reason
        outcome.ocr_status = _status_for(outcome, reused)
        self.documents.mark_ocr_result(doc_id, ocr_status=outcome.ocr_status,
                                       ocr_pages_done=len(self.texts.ocr_versions_of(doc_id)),
                                       last_error=reason)
        log.warning("OCR 提前停下 id=%s｜%s｜%s", doc_id, reason, outcome.describe())
        raise JobCancelled(reason)


def _sole_version(done: dict[int, str | None]) -> str | None:
    """这一份的 OCR 版本指纹。页与页指纹不一致（引擎中途升过版）时返回 None = 当作过期。"""
    versions = {v for v in done.values() if v is not None}
    return versions.pop() if len(versions) == 1 else None


def _status_when_nothing_to_do(doc: Document, expected: int, reused: int) -> str:
    """没有任何待办页时的状态：本来就不需要 OCR 的写 `na`，跑过的按跑过的算。"""
    if expected == 0:
        return "na"          # 每页原生字数都够 —— 这份不需要 OCR
    return OCR_DONE if reused else doc.ocr_status


def _status_for(outcome: OcrOutcome, reused: int) -> str:
    """`ocr_status` 的唯一流转。判据只有一条主线：**有没有页真的没进去**。

    - 一页没成、本来也没有可复用的、且有失败页 = `failed`；
    - 被预算或单页上限停在半路 = `partial`；一页都来不及跑的写回 `pending`（状态不许前进，
      停在 `partial` 会让"今天什么都没跑"和"跑了一半"两个读数长得一模一样）；
    - 有失败但其余进去了 = `partial`；其余 `done`。
    - **连续超时熔断 = `failed`**（ISSUES I21）：整本都是病态页，不是"跑了一半"，
      是"这份文件有问题"，写 failed 才能让界面显示红色而不是黄色。
    **绝不因为"大部分成功"就写 done** —— 写 done 等于对界面宣布"这本书搜得全"。
    """
    nothing_done = not (outcome.pages_recognized or reused or outcome.pages_failed)
    if outcome.stopped_on_budget and nothing_done:
        return OCR_PENDING
    if outcome.stopped_on_circuit_breaker:
        return "failed"  # ISSUES I21：熔断器触发 = 整份判失败，不是 partial
    if outcome.pages_recognized == 0 and not reused and outcome.pages_failed:
        return "failed"
    if outcome.stopped_on_budget or outcome.stopped_on_timeout or outcome.pages_failed:
        return OCR_PARTIAL
    return OCR_DONE
