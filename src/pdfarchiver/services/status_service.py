"""把"现在库到底是什么状态"算给界面看。

阶段 1 的界面外壳只允许显示**能算出来的事实**：条数、版本、路径、完整性。
阶段 2 补上第二块读数 —— SPEC 3.7 的第 10 项要"显示扫描与索引任务的进度、错误和重试状态"，
所以有了 `read_tasks()`。两块读数的口径各自唯一，且**每个数字都写清它是什么的数**：

- 「任务条数」= `processing_jobs` 的行数，一条任务一行，与工作量无关；
- 「进度（按页）」= 同类任务 `done`/`total` 之和，索引类任务按页累计，
  所以 8,000 份文档的进度显示的是页数而不是"3 / 8000 个任务"；
- 「重试中」= `attempts>1` 且未终结的任务条数，`max_attempts` 由队列层给；
- 「还欠一次索引」= `documents.NEEDS_INDEX_STATUSES`（pending/stale），与扫描侧、重启侧同一份，
  不在这里另列一遍状态名 —— 那是第二个口径。
- 「库里已存 OCR 正文」= `text_pages` 里 `source_kind='ocr'` 的行数（一份的数由
  `count_ocr_pages(doc_id)` 给，两者只差范围，算法一份）。它要扫全表，是这里唯一一条
  量级跟着库走的读数，所以有一个开关能不要它（`with_ocr_pages`，**ISSUES I109** 丙），
  不要它时界面上写「未现数」而不是 `0 页`。
- 「全库同步到哪个时刻」（`sync_status()`，轮三十六 乙）= 各**启用**根 `last_full_scan_at`
  里最早的那一刻，外加 scan 任务排队/在跑条数与从未对过账的根数。取最早那一刻是保守口径：
  只要还有一个根没对过账，就不存在"全库同步到某刻"这件事。

这里不出现"就绪/正常"这类笼统结论，也不出现任何不是从查询里算出来的数。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from pdfarchiver.db.engine import Engine
from pdfarchiver.db.migrate import current_version
from pdfarchiver.db.models import MonitoredRoot
from pdfarchiver.db.repositories.catalog import CatalogRepository
from pdfarchiver.db.repositories.documents import (NEEDS_INDEX_STATUSES, DocumentRepository)
from pdfarchiver.db.repositories.jobs import JobRepository
from pdfarchiver.db.repositories.roots import RootRepository
from pdfarchiver.db.repositories.settings import SettingsRepository
from pdfarchiver.db.repositories.text import TextRepository

# 界面上一屏最多列几条故障。按"人一次读得完"定，不是按库里有多少错误定 ——
# 全量首轮 8,000 份文档一起失败时，把 8,000 行原文灌进文本框就是 AGENTS.md 禁止的全量渲染。
MAX_ERROR_LINES = 10


def format_ts(ts: int | None) -> str:
    """UTC 秒 → 给人读的时刻。None 一律显示"从未"，不冒充 1970-01-01。

    **界面时间的唯一出口**（整改计划第 7 条 · 用户勾甲，2026-10-16）：界面上一律 UTC，
    并且必须带 `Z` —— 不带标注的时刻在用户眼里就是本地时间，本项目为这类账已经付过一次
    （**D-022**：日志三出口因为"裸本地时间却标 `Z`"注入过一条坏法）。
    """
    if ts is None:
        return "从未"
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%d %H:%M:%S") + "Z"


def format_day(ts: int | None) -> str:
    """UTC 秒 → 给人读的**日期**（日粒度）。与 `format_ts` 同一个口径、同一个模块。

    存在的全部理由是 **S5 线框自己要求的粒度**：`docs/UI-WIREFRAMES.md` §S5 数据来源表
    写的是「必须显示"已消失（日期）"」，画的那行也是 `missing_since 2026-09-11（已消失）` ——
    在路径摘要那种一行的注语里塞时分秒会把注语本身变成噪音。
    它不是第二个时间口径：同一份 UTC，只是截到日；因此它也只许和 `format_ts` 住在一起，
    界面自己 `strftime` 拼串由 `test_界面不许自己拼时间串` 钉住。
    """
    if ts is None:
        return "从未"
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%d")


@dataclass(frozen=True)
class CatalogStatus:
    schema_version: int
    documents: int
    missing_documents: int
    categories: int
    tags: int
    roots: int
    jobs_by_state: dict[str, int]
    app_setting_keys: int
    db_path: str

    def lines(self) -> list[str]:
        """给人读的固定顺序清单。空库要能一眼看出是空的（0 而不是"无数据"字样）。"""
        jobs = ", ".join(f"{k}={v}" for k, v in sorted(self.jobs_by_state.items())) or "无任务"
        return [
            f"结构版本 schema_version = {self.schema_version}",
            f"文档主记录 = {self.documents}（其中标记缺失 {self.missing_documents}）",
            f"分类 = {self.categories}，标签 = {self.tags}",
            f"监测根目录 = {self.roots}",
            f"任务 = {jobs}",
            f"应用内部状态条数 = {self.app_setting_keys}",
            f"库文件 = {self.db_path}",
        ]


@dataclass(frozen=True)
class TaskError:
    """一行故障：哪类任务、第几次尝试、哪份文档、原文是什么。

    只有原文没有文档名等于让用户自己去猜是哪个文件；只有文档名没有尝试次数
    等于看不出它是在重试还是已经放弃。
    """

    kind: str
    state: str
    attempts: int
    doc_name: str | None
    error: str

    def line(self) -> str:
        who = self.doc_name if self.doc_name else "（不针对具体文档）"
        return f"· {self.kind}[{self.state}] 第 {self.attempts} 次尝试｜{who}｜{self.error}"


@dataclass(frozen=True)
class SyncStatus:
    """「全库同步到哪个时刻」的唯一读数（轮三十六 乙）。

    四个数字只碰两处便宜查询 —— `monitored_roots` 的几行与 `processing_jobs` 的一次
    GROUP BY。**不碰 `text_pages`**：那条全表计数在真库上要 201–212 秒（**ISSUES I109** 丙），
    而这一格挂在 5 秒巡检节拍上（状态栏那一格）。

    `last_full_scan_at` 取的是**各启用根里最早的那一刻**，不是最新的那一刻：
    "全库都对到过哪里"只有在每一根都对到过之后才成立，取最新那一刻会把
    "还有 3 个根从没对过账"说成"同步到了今天"。从未对过账的根数单独给一格，
    这样"从未"和"很早以前"在界面上始终是两句不同的话。
    """

    roots_enabled: int
    roots_never_scanned: int
    last_full_scan_at: int | None
    scan_queued: int
    scan_running: int

    @property
    def busy(self) -> bool:
        return bool(self.scan_queued or self.scan_running)

    def summary(self) -> str:
        """状态栏那一格的一句话（`ui/main_window.py` 的常驻控件用它）。"""
        if not self.roots_enabled:
            return "同步：没有启用的监测根"
        tail = "｜同步中" if self.busy else "｜空闲"
        if self.roots_never_scanned:
            return f"同步：{self.roots_never_scanned}/{self.roots_enabled} 个根从未全量对账{tail}"
        return f"同步到 {format_ts(self.last_full_scan_at)}{tail}"

    def lines(self) -> list[str]:
        """S7 那一块的四行读数。排队与在跑分开写：只有一个 worker，排着不等于在走。"""
        return [
            f"  启用监测根 = {self.roots_enabled}（其中从未全量对账 {self.roots_never_scanned}）",
            f"  全库同步到 = {format_ts(self.last_full_scan_at)}（口径：各启用根里最早的那一刻）",
            f"  scan 任务：排队 {self.scan_queued}｜在跑 {self.scan_running}",
        ]


@dataclass(frozen=True)
class TaskStatus:
    jobs_by_kind_state: dict[tuple[str, str], int]
    work_by_kind: dict[str, tuple[int, int]]
    retried_by_kind: dict[str, int]
    max_attempts: int
    fts_by_status: dict[str, int]
    ocr_by_status: dict[str, int]
    #: 库里已存 OCR 正文页数。算法只有一份 —— `TextRepository.count_ocr_pages_all()`，
    #: 别把它换成写入侧的累计计数（`ocr_stats`），那是**第二个口径**（**ISSUES I109** 乙 未勾）。
    #: `None` 不是「0 页」而是「这一轮没数」：那条 SQL 要扫 `text_pages` 全表，
    #: 真库 1,975,611 行实测单条 201–212s，所以自动节拍上不要它（**ISSUES I109** 丙）。
    ocr_pages: int | None
    documents: int
    errors: list[TaskError]
    roots: list[MonitoredRoot]

    def count(self, kind: str, *states: str) -> int:
        return sum(self.jobs_by_kind_state.get((kind, s), 0) for s in states)

    @property
    def index_backlog(self) -> int:
        """还欠一次索引的文档数。口径 = `NEEDS_INDEX_STATUSES`，唯一一份。"""
        return sum(self.fts_by_status.get(s, 0) for s in NEEDS_INDEX_STATUSES)

    def _pages_text(self) -> str:
        """「库里已存 OCR 正文 …」那一小段的两种说法。

        没数过的时候不许显示 `0 页` —— "库里一页 OCR 文本都没有"和"这一轮没数"
        在界面上必须是两句不同的话（**ISSUES I109** 丙：那条计数要扫 `text_pages` 全表，
        已经从 5 秒巡检节拍与建窗路径上摘掉，只有状态块上那颗按钮会要它）。
        """
        if self.ocr_pages is None:
            return "未现数（这条要全库扫描，按「重新读取数据库状态」才数）"
        return f"{self.ocr_pages:,} 页"

    def lines(self) -> list[str]:
        """固定顺序的读数块。空队列也要有行，否则"没输出"和"还没跑"在界面上分不开。"""
        out: list[str] = []
        kinds = sorted({k for k, _ in self.jobs_by_kind_state})
        if not kinds:
            out.append("  任务：队列里没有任何行（还没扫描过）")
        for kind in kinds:
            per_state = " / ".join(
                f"{s}={self.count(kind, s)}"
                for s in ("queued", "running", "paused", "done", "failed", "cancelled")
                if self.count(kind, s))
            out.append(f"  任务条数  {kind}：{per_state}")
            done, total = self.work_by_kind.get(kind, (0, 0))
            if total:
                out.append(f"  进度（按页）{kind}：{done:,} / {total:,} 页 = {done * 100.0 / total:.1f}%")
        out.append(f"  文档索引状态：共 {self.documents} 份｜"
                   + "｜".join(f"{s}={n}" for s, n in sorted(self.fts_by_status.items()))
                   + f"｜还欠一次索引 {self.index_backlog}（口径 pending+stale）")
        out.append("  OCR 状态："
                   + ("｜".join(f"{s}={n}" for s, n in sorted(self.ocr_by_status.items())) or "无一行")
                   + f"｜库里已存 OCR 正文 {self._pages_text()}")
        retried = "｜".join(f"{k}={n}" for k, n in sorted(self.retried_by_kind.items()))
        out.append(f"  重试中：{retried or '无'}（每条最多 {self.max_attempts} 次尝试）")
        if self.errors:
            out.append(f"  最近故障（含正在重试的，最多列 {MAX_ERROR_LINES} 条）")
            out += [f"    {e.line()}" for e in self.errors]
        else:
            out.append("  最近故障：无（库里没有一行带着 last_error）")
        if self.roots:
            out.append("  监测根上次全量对账")
            for root in self.roots:
                mark = "已暂停" if not root.enabled else "启用"
                out.append(f"    · [{mark}] {root.root_path}｜上次 {format_ts(root.last_full_scan_at)}")
                if root.last_scan_error:
                    out.append(f"      ⚠ 上次扫描错误：{root.last_scan_error}")
        else:
            out.append("  监测根：一个都没添加，所以不会有任何扫描发生")
        return out


class StatusService:
    """界面与自检页共用的唯一取数口。不做缓存 —— 阶段 1 的量级不值得缓存，缓存只会让"读到旧数"变成 bug。"""

    def __init__(self, engine: Engine, documents: DocumentRepository, catalog: CatalogRepository,
                 roots: RootRepository, jobs: JobRepository, app_settings: SettingsRepository,
                 texts: TextRepository) -> None:
        self.engine = engine
        self.documents = documents
        self.catalog = catalog
        self.roots = roots
        self.jobs = jobs
        self.app_settings = app_settings
        self.texts = texts

    def read(self) -> CatalogStatus:
        conn = self.engine.thread_connection()
        return CatalogStatus(
            schema_version=current_version(conn),
            documents=self.documents.count(),
            missing_documents=self.documents.count_missing(),
            categories=self.catalog.count_categories(),
            tags=self.catalog.count_tags(),
            roots=self.roots.count(),
            jobs_by_state=self.jobs.counts_by_state(),
            app_setting_keys=self.app_settings.count(),
            db_path=str(self.engine.path),
        )

    def sync_status(self) -> SyncStatus:
        """「全库同步到哪个时刻」+「此刻有没有一场在跑」（轮三十六 乙）。

        口径只认 `monitored_roots.last_full_scan_at` 那一列 —— 它唯一的写入方是
        `ScanService._record` → `RootRepository.mark_full_scan`（一棵子树走完才写），
        所以这里没有第二本账，只做 min 与计数。
        """
        roots = self.roots.list_enabled()
        stamps = [r.last_full_scan_at for r in roots]
        never = sum(1 for s in stamps if s is None)
        by_state = self.jobs.counts_by_kind_state()
        return SyncStatus(
            roots_enabled=len(roots),
            roots_never_scanned=never,
            last_full_scan_at=None if never or not stamps else min(stamps),
            scan_queued=by_state.get(("scan", "queued"), 0),
            scan_running=by_state.get(("scan", "running"), 0),
        )

    def read_tasks(self, *, max_attempts: int, with_ocr_pages: bool = True) -> TaskStatus:
        """任务面板的读数。SQL 全在 `db/repositories/jobs.py` 与 `documents.py`，这里只做组合。

        `max_attempts` 由调用方（组合根）传进来，因为它是**队列层**的口径（`jobs/queue.py`），
        不是库里的列；在这里读成默认值就会出现"界面说最多 3 次、队列实际按别的数放弃"的两个口径。

        `with_ocr_pages` 是**唯一**一处能把那条全库计数关掉的开关，默认开着（= 完整读数）。
        要关掉它的只有界面线程（**ISSUES I109** 丙）：`count_ocr_pages_all()` 在 `source_kind`
        上没有索引可用，真库 1,975,611 行实测单条 **201–212s**，而巡检节拍是 5 秒一次 ——
        挂在自动刷新上等于让 S7 一在屏就把界面线程按住几分钟。
        关掉后 `ocr_pages` 是 `None`，界面上显示成「未现数」而不是 0 页。
        """
        rows = self.jobs.recent_errors(MAX_ERROR_LINES)
        ids = {int(r.doc_id) for r in rows if r.doc_id is not None}
        docs = self.documents.by_ids(sorted(ids))
        errors = [TaskError(kind=r.kind, state=r.state, attempts=r.attempts,
                            doc_name=docs[r.doc_id].name if r.doc_id else None,
                            error=r.last_error or "") for r in rows]
        kinds = sorted({k for k, _ in self.jobs.counts_by_kind_state()})
        return TaskStatus(
            jobs_by_kind_state=self.jobs.counts_by_kind_state(),
            work_by_kind={k: self.jobs.sum_progress(k) for k in kinds},
            retried_by_kind=self.jobs.counts_retried_by_kind(),
            max_attempts=max_attempts,
            fts_by_status=self.documents.counts_by_fts_status(),
            ocr_by_status=self.documents.counts_by_ocr_status(),
            ocr_pages=self.texts.count_ocr_pages_all() if with_ocr_pages else None,
            documents=self.documents.count(),
            errors=errors,
            roots=self.roots.list(),
        )
