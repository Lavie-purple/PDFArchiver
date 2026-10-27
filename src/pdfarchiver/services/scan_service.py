"""扫描与对账 —— 把"磁盘上现在有什么"变成 `documents` 表里的事实。

这是阶段 2 的中枢，也是**唯一**允许把文件系统状态写进文档主记录的地方
（`fs/` 不碰库、`db/` 不认识磁盘，两边都由这一层牵起来）。

四条口径写在这里，别处不许各有版本：

1. **一条主记录 = 一个规范化路径**（D-005）。重叠监测根重复扫到同一个文件时，
   `upsert` 走 `path_key` 冲突分支，只刷文件事实，不动索引状态。
   所以"加了两个互相包含的根"不会产生两份文档，也不会把已建好的正文索引冲掉。
2. **内容是否变化，看 (size, mtime_ns)，不看路径**（SPEC 阶段 2 安全要求）。
   路径相同不代表内容相同；索引阶段还会用 sha256 兜一层（`services/index_service.py`），
   所以"改名字不改内容"和"改内容不改名字"都有对应的判据。
3. **要不要索引，只看 `documents.fts_status`**（`NEEDS_INDEX_STATUSES`，与重启续跑同一个口径）。
   本层不接受"强制重扫全部"这种调用时开关：那样同一件事就有了两个答案（磁盘状态 vs 参数），
   而"重新索引全部"的正确做法是把状态打成 `stale` —— 库里的事实说了话，队列自然就跟上。
4. **删除只改状态，不删数据**：`missing_since` 打时间戳，正文页与索引行留着。
   检索层默认口径 `missing_since IS NULL`（`documents.where_for_filter`）已经把缺失文档挡在
   结果之外，所以"虚假的有效结果"不会出现；而文件被移动/改名后又能原地回来，不必重抽 200 万页。
   改名/移动另外靠 `(device_id, file_id)` 认，跨卷搬移（inode 换了）退回
   `(name, size_bytes, mtime_ns)` 认：单条候选且旧路径已消失才 `adopt_path`，
   **换路径不换主键**，用户打在这份文档上的分类、标签、备注全部原地保留；认不出来就老实建新记录，不猜。

错误处理遵循"一个坏目录不许中断整场扫描"：`fs.scanner` 把打不开的目录作为条目交出来，
这里只计数、留原文，然后继续走。原文同时写进 `monitored_roots.last_scan_error`，
状态页因此能回答"为什么这个根的文件数比昨天少"。

全量扫描的量级是 7,768 份（×10 档 8 万），所以**每个文件一次事务**在这里是不允许的：
"又看见它了"攒起来走 `mark_scanned_many`，"欠一次索引"攒起来走 `enqueue_many`，
一次扫描的写事务数与文件数解耦。单文件路径（文件事件）仍逐条处理，因为它一次只有一个。
"""
from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field

from pdfarchiver.db.models import Document, MonitoredRoot, now_ts
from pdfarchiver.db.repositories.documents import NEEDS_INDEX_STATUSES, DocumentRepository
from pdfarchiver.db.repositories.jobs import JobRepository
from pdfarchiver.db.repositories.roots import RootRepository
from pdfarchiver.fs.exclude import Exclusions
from pdfarchiver.fs.identity import FileIdentity, identity_key, read_identity
from pdfarchiver.fs.scanner import KIND_ERROR, KIND_EXCLUDED, KIND_OTHER, iter_tree
from pdfarchiver.fs.watcher import CREATED, DELETED, MODIFIED, MOVED, FsEvent
from pdfarchiver.jobs.queue import JobCancelled

log = logging.getLogger("pdfarchiver.scan")

# 对账结论。每个值都必须对应一个可数的动作，界面直接拿它做统计，不再自己归类一次。
ADDED = "added"
CHANGED = "changed"
UNCHANGED = "unchanged"
ADOPTED = "adopted"          # 改名/移动：认出来了，换了路径没换主键
MISSING = "missing"          # 磁盘上不见了
GONE = "gone"                # 记录本来就没有，无事可做
MAX_ERROR_MESSAGES = 20      # 报告里最多留几条原文；全留下在一万个坏目录时没人看得完


@dataclass
class ScanReport:
    """一个监测根的一次对账。计数口径与 `ScanItem.kind` 一一对应，不另立分类。"""

    root_key: str
    root_path: str
    pdfs: int = 0
    added: int = 0
    changed: int = 0
    unchanged: int = 0
    adopted: int = 0
    missing: int = 0
    excluded: int = 0
    other_ext: int = 0
    index_enqueued: int = 0
    errors: list[str] = field(default_factory=list)
    error_count: int = 0
    cancelled: bool = False
    took_ms: int = 0

    @property
    def has_errors(self) -> bool:
        return self.error_count > 0

    def summarize(self) -> str:
        parts = [f"{self.root_path}：PDF {self.pdfs}",
                 f"新增 {self.added}", f"改动 {self.changed}", f"改名 {self.adopted}",
                 f"未见 {self.missing}", f"未变 {self.unchanged}",
                 f"排队索引 {self.index_enqueued}"]
        if self.excluded or self.other_ext:
            parts.append(f"排除 {self.excluded}/非 PDF {self.other_ext}")
        if self.error_count:
            parts.append(f"读不出的条目 {self.error_count}")
        if self.cancelled:
            parts.append("已取消")
        return "｜".join(parts) + f"（{self.took_ms} ms）"


@dataclass(frozen=True)
class _Outcome:
    action: str
    doc_id: int | None = None
    needs_index: bool = False


def _to_doc(identity: FileIdentity) -> Document:
    """文件事实 → 主记录骨架。索引状态一律留 pending：这一层只负责"有没有这个文件"。"""
    return Document(
        path=identity.path, path_key=identity.path_key, name=identity.name, ext=identity.ext,
        size_bytes=identity.size_bytes, mtime_ns=identity.mtime_ns, ctime_ns=identity.ctime_ns,
        file_id=identity.file_id, device_id=identity.device, is_pdf=1,
        last_scanned_at=now_ts())


def _needs_index(fts_status: str) -> bool:
    return fts_status in NEEDS_INDEX_STATUSES


class ScanService:
    """`scan` 任务的执行体，也是文件事件的落点。

    线程不在这里：调度在 `jobs/queue.py`，定时器在 `services/patrol.py`。
    本类全部方法都是**同步且可重入**的，单测可以直接调，不需要起线程。
    """

    def __init__(self, documents: DocumentRepository, roots: RootRepository,
                 jobs: JobRepository, *, exclusions: Exclusions | None = None) -> None:
        self.documents = documents
        self.roots = roots
        self.jobs = jobs
        self.exclusions = exclusions or Exclusions.of()

    # —— 全量 / 增量扫描 ——————————————————————————————————

    def scan_root(self, root: MonitoredRoot, *, should_stop=None) -> ScanReport:
        """走完一棵子树并与主记录对账。

        "未见即缺失"的判据只在**走完了**才成立：中途取消或根目录整个读不动时，
        没被看见不等于不存在（网络盘掉线会瞬间"删掉"八千份文档）。
        """
        report = ScanReport(root_key=root.root_key, root_path=root.root_path)
        started = time.perf_counter()
        seen_keys: set[str] = set()
        seen_ids: list[int] = []
        pending_index: list[int] = []
        cancel_requested = False

        for item in iter_tree(root.root_path, self._exclusions_for(root), should_stop=should_stop):
            if item.kind == KIND_EXCLUDED or item.kind == KIND_OTHER:
                if item.kind == KIND_EXCLUDED:
                    report.excluded += 1
                else:
                    report.other_ext += 1
                if item.identity is not None:
                    # 排除 = 明知它在那里而不去动它；它照样"在这个根里存在"，
                    # 不记进 seen_keys 的话，一个被排除的目录会在每轮扫描里"消失"一次。
                    seen_keys.add(item.identity.path_key)
                continue
            if item.kind == KIND_ERROR:
                report.error_count += 1
                if len(report.errors) < MAX_ERROR_MESSAGES:
                    report.errors.append(f"{item.path}｜{item.detail}")
                log.warning("扫描条目读不出来：%s｜%s", item.path, item.detail)
                continue
            if item.identity is None:      # 理论不会发生；真发生了就是 fs 层的 bug，不许静默吞
                log.error("PDF 条目没有文件身份，跳过：path=%s kind=%s", item.path, item.kind)
                continue
            report.pdfs += 1
            seen_keys.add(item.identity.path_key)
            outcome = self.reconcile_identity(item.identity, scanned_sink=seen_ids)
            self._count(report, outcome)
            if outcome.needs_index and outcome.doc_id is not None:
                pending_index.append(outcome.doc_id)
            if should_stop is not None and should_stop():
                break

        # 循环外再问一次：`iter_tree` 是"每进一个目录查一次取消位"，所以取消可能发生在
        # **一个条目都没交出来**的时候（根目录第一个 scandir 前就停了）。只认循环里的那次 break，
        # 这种扫描会被当成"走完了"，于是整棵树的文件全被判成缺失。
        cancel_requested = should_stop is not None and should_stop()
        report.cancelled = cancel_requested
        if cancel_requested:
            # 中途取消：本轮的"又看见了"照实写（它确实看见了），索引任务照实排（排了不亏，
            # 队列会去重），但**不判缺失** —— 没走到的枝不等于不存在的文件。
            self.documents.mark_scanned_many(seen_ids)
            report.index_enqueued = self.jobs.enqueue_many("index", pending_index)
            report.took_ms = int((time.perf_counter() - started) * 1000)
            log.info("扫描被取消，不判定缺失：%s", root.root_path)
            self._record(root, report)
            return report

        self.documents.mark_scanned_many(seen_ids)
        report.index_enqueued = self.jobs.enqueue_many("index", pending_index)
        report.missing = self._mark_missing(root, seen_keys)
        report.took_ms = int((time.perf_counter() - started) * 1000)
        self._record(root, report)
        log.info("扫描完成 %s", report.summarize())
        return report

    def scan_all(self, *, should_stop=None) -> list[ScanReport]:
        """把所有启用的监测根各走一遍。重叠根各自判定"我这棵子树里没看见"，
        但缺失判定按 `root_key` 前缀圈范围，所以一个根里的文件不会因为另一个根而误判。"""
        return [self.scan_root(root, should_stop=should_stop) for root in self.roots.list_enabled()]

    def handle(self, job, monitor) -> None:
        """`scan` 任务的处理函数。进度按"根"计 —— 扫到第几个根就是几分之几，
        一个根都没配的时候不排队、不假装跑完。"""
        roots = self.roots.list_enabled()
        if not roots:
            log.warning("没有启用的监测根，扫描任务无事可做")
            return
        monitor.set_total(len(roots))
        for index, root in enumerate(roots, start=1):
            if monitor.cancelled():
                raise JobCancelled(f"扫描任务被取消（已完成 {index - 1}/{len(roots)} 个根）")
            self.scan_root(root, should_stop=monitor.cancelled)
            monitor.advance()

    # —— 单个文件：事件与扫描共用的一条路 ——————————————————

    def reconcile_identity(self, identity: FileIdentity, *,
                           scanned_sink: list[int] | None = None) -> _Outcome:
        """一个磁盘文件 → 一条主记录该有的状态。幂等：同一个 identity 连调两次，第二次是不变。

        `scanned_sink` 是给全量扫描用的批量出口：把"这轮又看见它了"的 doc_id 放进这个列表，
        由调用方一次刷库；不传就是单文件路径，立刻写。
        """
        known = self.documents.facts_by_key(identity.path_key)
        if known is None:
            adopted = self._adopt_renamed(identity, scanned_sink)
            if adopted is not None:
                return adopted
            doc = self.documents.upsert(_to_doc(identity))
            return _Outcome(ADDED, doc.id, needs_index=True)
        if known.size_bytes != identity.size_bytes or known.mtime_ns != identity.mtime_ns:
            self.documents.upsert(_to_doc(identity))       # 只刷文件事实；索引状态交给下一句
            self.documents.invalidate_index(known.doc_id)
            return _Outcome(CHANGED, known.doc_id, needs_index=True)
        if known.missing_since is not None:
            # 走的是"路径没变、大小和 mtime 也没变，但它曾被判过缺失"——文件挪回来了。
            # `upsert` 的冲突分支同时写 `missing_since=NULL` 和 `last_scanned_at`，所以这一支不必再 `_mark_seen`；
            # 索引状态照旧（内容没动，正文还有效），摘掉戳记它就重新回到检索结果里。
            self.documents.upsert(_to_doc(identity))
            log.info("文件回来了，索引状态保持 %s：%s", known.fts_status, identity.path)
        else:
            self._mark_seen(known.doc_id, scanned_sink)
        return _Outcome(UNCHANGED, known.doc_id, needs_index=_needs_index(known.fts_status))

    def reconcile_path(self, path: str) -> _Outcome:
        """文件事件用的入口：先取身份，再走同一条对账路。取不到身份就是文件已经不在了。"""
        try:
            identity = read_identity(path)
        except OSError as exc:
            log.info("路径取不到身份，按消失处理：%s｜%s: %s", path, type(exc).__name__, exc)
            # 走 `_vanish` 而不是直接回一个 MISSING：后者只回答"这个路径没了"，
            # 而库里那条主记录必须真的被打上缺失戳记，否则它继续出现在检索结果里
            # （SPEC 阶段 2 安全要求「文件被删除后不许继续显示虚假的有效结果」）。
            return self._vanish(path)
        return self.reconcile_identity(identity)

    def reconcile_event(self, event: FsEvent) -> _Outcome:
        """把一条 watchdog 事件变成对账动作。

        事件**只是提示**（P4：跨目录移动给的是 created+deleted 两条、可乱序可重复、
        根目录自己改名则一条都没有），所以这里不信任事件的"内容"，只把它当"该再看一眼哪个路径"，
        每个分支都以磁盘现状为准重算。删除事件还要再 `exists()` 确认一次 ——
        误判删除的代价是把用户的文档标成缺失，而漏判删除由周期校验补回来。
        """
        if event.kind in (CREATED, MODIFIED):
            return self.reconcile_path(event.path)
        if event.kind == MOVED:
            if event.dest_path:
                return self.reconcile_path(event.dest_path)
            return self._vanish(event.path)
        if event.kind == DELETED:
            return self._vanish(event.path)
        raise ValueError(f"未知事件类型 {event.kind}；合法值 {CREATED}/{MODIFIED}/{MOVED}/{DELETED}")

    def _vanish(self, path: str) -> _Outcome:
        if os.path.exists(path):
            return _Outcome(UNCHANGED)      # 事件说没了、磁盘说还在：听磁盘的
        known = self.documents.facts_by_key(identity_key(path))
        if known is None:
            return _Outcome(GONE)
        marked = self.documents.mark_missing(known.path_key)
        return _Outcome(MISSING, known.doc_id) if marked else _Outcome(UNCHANGED, known.doc_id)

    # —— 改名识别 ————————————————————————————————————————

    def _adopt_renamed(self, identity: FileIdentity,
                       scanned_sink: list[int] | None = None) -> _Outcome | None:
        """新路径没记录 → 找回它原来的记录，两条路：先按 `(device_id, file_id)`，
        认不到再按文件事实 `(name, size_bytes, mtime_ns)`（**ISSUES I115** 甲）。

        两条路都只在两个条件同时成立时才认：候选**恰好一条**（多条 = 硬链接/同名同大小，
        认哪条都是猜），且旧路径**已经不在磁盘上**（还在 = 这真的是一份新文件，不是改名）。
        内容与名字同时变（改名后又编辑过）也认：先换路径，再按 (size, mtime) 判要不要重索引。
        """
        old = self._renamed_by_inode(identity)
        if old is None:
            old = self._renamed_by_facts(identity)
        if old is None:
            return None
        content_changed = old.size_bytes != identity.size_bytes or old.mtime_ns != identity.mtime_ns
        if not self.documents.adopt_path(
                old.doc_id, path=identity.path, path_key=identity.path_key, name=identity.name,
                ext=identity.ext, size_bytes=identity.size_bytes, mtime_ns=identity.mtime_ns,
                ctime_ns=identity.ctime_ns):
            return None
        log.info("认作改名：id=%s %s → %s", old.doc_id, old.path, identity.path)
        if content_changed:
            self.documents.invalidate_index(old.doc_id)
        self._mark_seen(old.doc_id, scanned_sink)
        return _Outcome(ADOPTED, old.doc_id,
                        needs_index=content_changed or _needs_index(old.fts_status))

    def _renamed_by_inode(self, identity: FileIdentity):
        """同卷改名：inode 没变，认 `(device_id, file_id)`。"""
        if identity.device is None or identity.file_id is None:
            return None
        candidates = self.documents.by_inode(identity.device, identity.file_id)
        others = [c for c in candidates if c.path_key != identity.path_key]
        if len(others) != 1:
            if len(others) > 1:
                log.warning("同一 inode 有 %d 条记录（硬链接？），不自动认改名：%s",
                            len(others), identity.path)
            return None
        return None if os.path.exists(others[0].path) else others[0]

    def _renamed_by_facts(self, identity: FileIdentity):
        """跨卷搬移：inode 换了（Windows 是「复制 + 删源」），退回文件事实认。
        三项全等且**恰好一条**已判缺失的记录才认；多于一条或任一项不等，一律不认 ——
        「不猜」这条规则在两条旁路上是同一条硬条件。"""
        matches = self.documents.missing_by_facts(
            identity.name, identity.size_bytes, identity.mtime_ns)
        if len(matches) != 1:
            if len(matches) > 1:
                log.warning("有 %d 条缺失记录的文件事实全等（同名同大小同时间），不猜改名：%s",
                            len(matches), identity.path)
            return None
        return None if os.path.exists(matches[0].path) else matches[0]

    def _mark_seen(self, doc_id: int, scanned_sink: list[int] | None) -> None:
        """`scanned_sink` 是批量出口：全量扫描把 doc_id 攒给调用方一次刷库；
        不传（事件路径，一次一个文件）就立刻写。两条路都必须刷新"最后一次看见"的时间，
        否则状态页上的"多久没扫到它了"会指着上一次扫描说假话。"""
        if scanned_sink is None:
            self.documents.mark_scanned(doc_id)
        else:
            scanned_sink.append(doc_id)

    # —— 缺失判定 ————————————————————————————————————————

    def _mark_missing(self, root: MonitoredRoot, seen_keys: set[str]) -> int:
        """这个根的子树里，走完一遍都没再看见的主记录 → 标缺失。

        只按 `root_key` 前缀圈候选，不看别的根：重叠根下同一份文件被另一个根扫到过
        不代表它在本根里还在（本根的走查就是它的全部真相）。
        """
        missing = 0
        for state in self.documents.scan_states_under(root.root_key):
            if state.path_key not in seen_keys:
                if self.documents.mark_missing(state.path_key):
                    missing += 1
        return missing

    def _exclusions_for(self, root: MonitoredRoot) -> Exclusions:
        try:
            extra = json.loads(root.exclude_globs or "[]")
        except json.JSONDecodeError as exc:
            log.error("监测根 %s 的排除规则不是合法 JSON，本根按内置规则扫：%s", root.root_key, exc)
            return self.exclusions
        if not isinstance(extra, list):
            log.error("监测根 %s 的排除规则不是列表（%s），按内置规则扫", root.root_key, type(extra))
            return self.exclusions
        return Exclusions.of([str(g) for g in extra]) if extra else self.exclusions

    @staticmethod
    def _count(report: ScanReport, outcome: _Outcome) -> None:
        if outcome.action == ADDED:
            report.added += 1
        elif outcome.action == CHANGED:
            report.changed += 1
        elif outcome.action == ADOPTED:
            report.adopted += 1
        elif outcome.action == UNCHANGED:
            report.unchanged += 1

    def _record(self, root: MonitoredRoot, report: ScanReport) -> None:
        error = None
        if report.errors:
            error = report.errors[0] + (f"（另有 {report.error_count - 1} 条）"
                                        if report.error_count > 1 else "")
        elif report.cancelled:
            error = "扫描中途取消，本轮未判定缺失"
        self.roots.mark_full_scan(root.root_key, error=error)

    # —— 断点续扫 ————————————————————————————————————————

    def resume_pending(self, *, limit: int = 5000) -> int:
        """把上次没做完 / 被打断的文档重新排进队列。启动时调用一次。

        口径与扫描侧同为 `NEEDS_INDEX_STATUSES`，所以"扫描排过但没有跑完"的文档在这里
        不会被漏掉，也不会被排两遍（`enqueue_many` 按 (kind, doc_id) 对未终结任务去重）。
        """
        pending = self.documents.ids_needing_index(limit)
        enqueued = self.jobs.enqueue_many("index", pending)
        if pending:
            log.info("断点续扫：%d 份待索引，新排 %d 条任务", len(pending), enqueued)
        return enqueued
