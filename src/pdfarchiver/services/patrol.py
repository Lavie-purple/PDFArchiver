"""周期巡检 —— 把"事件流"和"定期校验"接到扫描/索引任务上（SPEC 阶段 2 第 5 条）。

SPEC 要的是**两件事一起**：文件监测事件 + 定期校验，避免遗漏。为什么两个都要，
P4 实测已经给过答案：300 个文件落盘一条不丢，但**被监听的目录自身改名是 0 条事件** ——
纯靠事件，根没了都不会有人发现。

所以这一层的分工是：

- **事件走快路**：一条 PDF 事件 → 一次 `reconcile_event`（一个 `stat`），新文件当场进主记录。
  这条路便宜，所以每次轮询都跑。
- **校验走慢路，但只排队不亲自跑**：脏根出现过事件、或到了周期点，就排一条 `scan` 任务。
  巡检器自己**绝不**扫描目录 —— 它跑在界面线程的定时器上，一次全量走查在 8,000 份的量级
  是把界面冻住几秒到几十秒（AGENTS.md 禁止全量加载），干活的是 `jobs/queue.py` 的 worker 线程。
- **`scan` 任务天然去重**：`doc_id=NULL` 的同类任务只排一条未终结的（`jobs.enqueue` 的
  `IFNULL(doc_id,-1)` 分支）。所以 300 个文件一次性落盘 = 300 次逐条对账 + **一场**重扫，
  而不是 300 场重扫。

时间口径只有一个，都在设置里：`scan_poll_seconds`（快路多久看一眼）与
`scan_verify_minutes`（慢路最迟多久保证走一遍）。巡检器自己不猜默认值。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from pdfarchiver.db.repositories.jobs import JobRepository
from pdfarchiver.fs.watcher import EventBuffer
from pdfarchiver.services.scan_service import (ADOPTED, ADDED, CHANGED, GONE, MAX_ERROR_MESSAGES,
                                               MISSING, UNCHANGED, ScanService)

log = logging.getLogger("pdfarchiver.patrol")


@dataclass
class PatrolReport:
    """一次轮询的账。界面拿它回答"刚才那几秒发生了什么"，数字口径与 `ScanReport` 同源。"""

    events: int = 0
    added: int = 0
    changed: int = 0
    adopted: int = 0
    missing: int = 0
    unchanged: int = 0
    gone: int = 0
    index_enqueued: int = 0
    scan_enqueued: bool = False
    dirty_roots: tuple[str, ...] = ()
    errors: list[str] = field(default_factory=list)

    @property
    def did_anything(self) -> bool:
        return bool(self.events or self.scan_enqueued or self.index_enqueued)

    def summarize(self) -> str:
        if not self.did_anything:
            return "无事发生"
        parts = [f"事件 {self.events}", f"新增 {self.added}", f"改动 {self.changed}",
                 f"改名 {self.adopted}", f"消失 {self.missing}", f"排队索引 {self.index_enqueued}"]
        if self.scan_enqueued:
            parts.append(f"排队重扫（脏根 {len(self.dirty_roots)}）")
        if self.errors:
            parts.append(f"出错 {len(self.errors)}")
        return "｜".join(parts)


class Patrol:
    """定时器每次调 `poll()` 一下。自身不持线程、不持连接，只做"该排什么队"的判断。"""

    def __init__(self, scan: ScanService, jobs: JobRepository, buffer: EventBuffer, *,
                 poll_seconds: float, verify_minutes: float) -> None:
        if poll_seconds <= 0 or verify_minutes <= 0:
            raise ValueError(f"轮询与校验间隔必须是正数；收到 poll_seconds={poll_seconds}"
                             f" verify_minutes={verify_minutes}")
        self.scan = scan
        self.jobs = jobs
        self.buffer = buffer
        self.poll_seconds = float(poll_seconds)
        self.verify_minutes = float(verify_minutes)
        # 换算成"第几次轮询走一次慢路"：向上取整，保证实际间隔不短于设置的那个值。
        self.verify_every_polls = max(1, -(-int(verify_minutes * 60) // max(1, int(poll_seconds))))
        self._polls = 0

    def poll(self) -> PatrolReport:
        """处理积压事件，并按需排一次全量对账。异常一律咽不下：逐条留原文，继续处理下一条 ——
        一个坏路径不许把定时器打死，那等于此后所有事件都没人管了。"""
        self._polls += 1
        report = PatrolReport()
        due_by_clock = self._polls % self.verify_every_polls == 0

        for event in self.buffer.drain():
            report.events += 1
            try:
                outcome = self.scan.reconcile_event(event)
            except (OSError, ValueError) as exc:
                if len(report.errors) < MAX_ERROR_MESSAGES:
                    report.errors.append(f"{event.kind} {event.path}｜{type(exc).__name__}: {exc}")
                log.exception("处理文件事件失败：%s %s", event.kind, event.path)
                continue
            self._tally(report, outcome)

        dirty = tuple(sorted(self.buffer.take_dirty_roots()))
        report.dirty_roots = dirty
        # 两条触发：脏根（事件说到过）与到点（事件什么都没说，比如根整个没了）。
        # 只认前者的话，"根目录被改名"这种 0 事件的场景永远不会被校验到（P4 实测）。
        if dirty or due_by_clock:
            report.scan_enqueued = self.jobs.enqueue("scan") is not None
        if report.did_anything:
            log.info("巡检第 %d 次轮询：%s", self._polls, report.summarize())
        return report

    def _tally(self, report: PatrolReport, outcome) -> None:
        action = outcome.action
        if action == ADDED:
            report.added += 1
        elif action == CHANGED:
            report.changed += 1
        elif action == ADOPTED:
            report.adopted += 1
        elif action == MISSING:
            report.missing += 1
        elif action == UNCHANGED:
            report.unchanged += 1
        elif action == GONE:
            report.gone += 1
        if outcome.needs_index and outcome.doc_id is not None:
            # 这里必须真的排上队：事件说"有个新文件"，主记录写了但没人抽正文，
            # 那份文档就永远搜不到，而界面上它看起来一切正常。
            if self.jobs.enqueue("index", int(outcome.doc_id)) is not None:
                report.index_enqueued += 1
