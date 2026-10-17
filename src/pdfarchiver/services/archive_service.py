"""归档服务 —— 阶段 4：把"打算怎么搬"算成一份能预览、能执行、能撤销的批次。

三条写死在这里的契约（`docs/DATABASE.md` §五）：

1. **plan 是纯计算**：不打开文件、不写、不 rename，只 stat。预览与实际执行共用同一个
   `plan()`，所以"界面上看到的那份计划"和"真的搬出去的那批文件"是同一份数据
   （`docs/ROADMAP.md` 阶段 4 门禁「预览与实际执行的文件集合逐条一致」）。
2. **未确认绝不执行**：worker 只领 `status='previewed'` 的批次，而把批次写成 `previewed` 的
   唯一入口是 `submit()` —— 它只在界面拿到用户确认（**D-042** 丙 · 分级确认控件）之后才被调用。
3. **目标未验证绝不删源**（SPEC 3.6 / G19）：跨盘 = copy → 逐项验 sha256 → 才 `unlink` 源；
   同盘 = move。被跳过的项（冲突 / 路径过长 / 源已不见）不进 journal（**D-048**），
   只在台账里留下原因文本。

命名模板的三个变量口径见 `TEMPLATE_FIELDS` 与 `render_relative()`，全站只有这一处；
S3 的预览表与执行器落的目标路径都由它算出来。

撤销 = 另开一条 `kind='undo'`、`undo_of=原批次` 的批次，方向取反（**D-043** 甲），
走同一个执行器、同一份 journal 形状 —— 反向批次里的一条 item 与正向的一条没有区别，
所以这里不给撤销另写一套搬运代码。
"""
from __future__ import annotations

import hashlib
import logging
import os
import re
import shutil
import string
from dataclasses import dataclass
from pathlib import Path

from pdfarchiver.config.paths import AppPaths
from pdfarchiver.db.models import Job
from pdfarchiver.db.repositories.catalog import CatalogRepository
from pdfarchiver.db.repositories.documents import NS_PER_SECOND, DocumentRepository
from pdfarchiver.db.repositories.jobs import JobRepository
from pdfarchiver.db.repositories.operations import FileOperation, OperationRepository
from pdfarchiver.fs.identity import read_identity
from pdfarchiver.jobs.queue import JobCancelled, ProgressMonitor
from pdfarchiver.services.status_service import format_day

log = logging.getLogger("pdfarchiver.archive")

# Windows MAX_PATH = 260，但扩展长度前缀 `\\?\` 可支持到 32,767。
# 安全上限留 240（给目录创建与临时文件留余量）。超过此值必须用扩展前缀或缩短路径。
MAX_SAFE_PATH_LENGTH = 240
# NTFS 单个路径段上限 = 255 个 UTF-16 单元。按上限本身反算，不留余量：
# 段长是渲染出来的，超了就是在告诉用户"这个名字放不进目标目录"。
MAX_SAFE_COMPONENT_LENGTH = 255

# 模板变量的唯一口径（AGENTS.md「禁止核心概念有多个口径」）。
# {category} = 主分类的 name_path（`categories_of` 按 name_path 排序后的第一条），
#              多级分类天然变成多级目录；没有分类 → `_未分类`。
# {year}     = 文件修改时间 `documents.mtime_ns` 折算成 UTC 之后的四位年份，
#              与 `format_ts`/`format_day` 同一时区口径（D-022 / 整改计划第 7 条勾甲）；
#              取不到修改时间 → `_无年份`，不冒充某一年。
# {name}     = 原文件名去掉后缀（模板里的 `.pdf` 是用户写的字面量，不是从文件名剥出来的）。
TEMPLATE_FIELDS = ("category", "year", "name")
UNCLASSIFIED_FOLDER = "_未分类"
UNKNOWN_YEAR_FOLDER = "_无年份"

_WINDOWS_RESERVED = frozenset(
    {"con", "prn", "aux", "nul"}
    | {f"com{i}" for i in range(1, 10)}
    | {f"lpt{i}" for i in range(1, 10)})
# 路径段里不能出现的字符：Windows 保留字符 + 控制字符。`/` 与 `\` 在拆分之后才进来，
# 所以这里是"渲染完、按分隔符拆开之后"对每一段做的清洗。
_ILLEGAL_IN_COMPONENT = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


class PathTooLongError(ValueError):
    """目标路径超过系统限制（ISSUES I10）。消息里必须带路径长度与限制值。"""


class TemplateError(ValueError):
    """命名模板本身写错了（未知变量 / 绝对路径 / 用 `..` 往目标根外面跳）。

    整批层面的错误：这类模板一条都执行不了，所以当场说清楚，而不是等执行到第 N 项才炸。
    """


def validate_path_length(path: Path, *, limit: int = MAX_SAFE_PATH_LENGTH) -> None:
    """检查路径长度是否在安全范围内。超限抛 PathTooLongError（可读错误，不是 WinError 3）。

    Windows 默认 MAX_PATH = 260，但很多工具（Git、资源管理器）不支持扩展长度前缀。
    安全上限 240 = 给目录创建与临时文件留 20 字符余量。
    """
    path_str = str(path)
    if len(path_str) > limit:
        raise PathTooLongError(
            f"目标路径过长：{len(path_str)} 字符（上限 {limit}）\n"
            f"路径：{path_str}\n"
            "请缩短文件名、减少嵌套层级，或启用系统 LongPathsEnabled（ISSUES I10）"
        )


def sanitize_component(raw: str) -> str:
    """把一个要当目录名/文件名用的字符串洗成 Windows 能接受的单段。

    清洗而不是拒绝：分类名是用户在 S8 里自己打的，里面出现 `:` `/` 这类字符不应该
    导致整批归档失败；但也不能悄悄改成别的名字还不说明 —— 渲染结果会原样进预览表，
    用户在按「执行」之前看到的就是最终落地的路径。
    """
    text = _ILLEGAL_IN_COMPONENT.sub("_", str(raw)).strip().rstrip(". ")
    if len(text) > MAX_SAFE_COMPONENT_LENGTH:
        text = text[:MAX_SAFE_COMPONENT_LENGTH].rstrip(". ")
    if text.split(".")[0].lower() in _WINDOWS_RESERVED:
        text = "_" + text   # `nul.pdf`、`com1` 这类保留名会被 Windows 当成设备
    return text


def validate_template(template: str) -> None:
    """校验模板本身；错误是整批级的，一条也不会执行，所以当场抛出。"""
    if not template.strip():
        raise TemplateError("命名模板是空的：至少要写出 `{name}`，否则所有文件会落到同一个名字上")
    fields = []
    for literal, field, spec, conversion in string.Formatter().parse(template):
        if field is None:
            continue
        if spec or conversion:
            raise TemplateError(f"命名模板不支持对齐/转换写法：{{{field}{conversion or ''}{':' + spec if spec else ''}}}")
        fields.append(field)
    unknown = sorted({f for f in fields if f not in TEMPLATE_FIELDS})
    if unknown:
        raise TemplateError(
            f"命名模板里有不认识的变量：{unknown}。能用的是 {list(TEMPLATE_FIELDS)}")
    if not fields:
        raise TemplateError(f"命名模板里一个变量都没有，全部文件会落到同一个名字上；"
                            f"至少要有 {{name}}（当前模板：{template!r}）")
    # 模板自己不许往目标根外面跳：绝对路径、盘符、`..`
    if template.startswith(("/", "\\")) or re.match(r"^[A-Za-z]:", template):
        raise TemplateError(f"命名模板必须是目标根目录**下面**的相对路径，收到 {template!r}")
    for part in re.split(r"[/\\]", template):
        if part == "..":
            raise TemplateError("命名模板里不许出现 `..`：归档结果必须落在目标根目录里面")


def render_relative(template: str, values: dict[str, str]) -> tuple[str, ...]:
    """套模板 → 按分隔符拆成路径段（每段已清洗）。返回空元组表示"渲染出来什么也不是"。"""
    try:
        rendered = template.format(**values)
    except (KeyError, IndexError, ValueError) as exc:
        raise TemplateError(f"命名模板 {template!r} 渲染失败：{exc}") from exc
    parts = []
    for raw in re.split(r"[/\\]", rendered):
        if raw in ("", "."):
            continue
        if raw == "..":
            # 只有变量值里带 `..` 才会走到这里（模板自己那条在 validate_template 就炸了）。
            raise TemplateError(f"渲染结果里出现了 `..`（值：{values}），会跳出目标根目录")
        part = sanitize_component(raw)
        if not part:
            raise TemplateError(f"渲染结果里有一段清洗完是空的（原始：{raw!r}，值：{values}）")
        parts.append(part)
    return tuple(parts)


@dataclass(frozen=True)
class PlannedMove:
    """计划里的一项：从哪、到哪、怎么搬、该不该跳过。"""

    doc_id: int | None
    src_path: str
    dst_path: str
    kind: str                 # move（同盘）| copy（跨盘，验完才删源）
    skip_reason: str | None = None

    @property
    def will_move(self) -> bool:
        return self.skip_reason is None and bool(self.dst_path)


@dataclass(frozen=True)
class UndoPlan:
    """一条批次"能撤什么"的**只读**算账结果。

    S4 的确认框读它（不写库就能先把条数与原因摆出来），`submit_undo()` 也读它 ——
    界面上说"排除 3 条"和台账里落 3 条 skipped 原因，中间没有第二次判断。
    """

    moves: tuple[PlannedMove, ...]
    excluded: tuple[str, ...]
    irreversible: int


class ArchiveService:
    """归档执行：算计划 → 落成批次 → 逐项搬 → 记 journal → 更新库里的路径。"""

    def __init__(self, ops: OperationRepository, docs: DocumentRepository, paths: AppPaths,
                 catalog: CatalogRepository, jobs: JobRepository) -> None:
        self.ops = ops
        self.docs = docs
        self.paths = paths
        self.catalog = catalog
        self.jobs = jobs

    # —— 计划（纯计算）——————————————————————————————————————————————

    def template_values(self, doc_id: int) -> dict[str, str]:
        """取一份文档的三个模板变量。口径的唯一出处见 `TEMPLATE_FIELDS` 的注释。"""
        doc = self.docs.get(doc_id)
        if doc is None:
            raise LookupError(f"文档主记录不存在：doc_id={doc_id}")
        cats = self.catalog.categories_of(doc_id)
        year = (format_day(doc.mtime_ns // NS_PER_SECOND)[:4]
                if doc.mtime_ns else UNKNOWN_YEAR_FOLDER)
        return {"category": cats[0].name_path if cats else UNCLASSIFIED_FOLDER,
                "year": year,
                "name": Path(doc.name).stem}

    def plan(self, doc_ids: list[int], target_root: str, template: str) -> list[PlannedMove]:
        """把 doc_ids 渲染成逐项计划。**只 stat**：不打开文件、不写、不 rename。"""
        validate_template(template)
        root = Path(target_root)
        if not root.exists():
            raise ValueError(f"目标根目录不存在：{target_root}")
        root_abs = os.path.normcase(os.path.abspath(str(root))) + os.sep
        # ISSUES I40：跨盘判定的目标侧设备号，与 documents.device_id 同一个口径（都是 st_dev）。
        target_device = os.stat(root).st_dev

        moves: list[PlannedMove] = []
        claimed: dict[str, int] = {}     # 归一化后的目标路径 → 计划里的第几项（1 基）
        for ordinal, doc_id in enumerate(doc_ids, start=1):
            doc = self.docs.get(doc_id)
            if doc is None:
                moves.append(PlannedMove(doc_id, "", "", "move",
                                         f"文档主记录已经不在了（doc_id={doc_id}）"))
                continue
            src = doc.path
            if not Path(src).exists():
                moves.append(PlannedMove(doc_id, src, "", "move", "源文件已经不在磁盘上"))
                continue
            try:
                parts = render_relative(template, self.template_values(doc_id))
            except TemplateError as exc:
                moves.append(PlannedMove(doc_id, src, "", "move", str(exc)))
                continue
            if not parts:
                moves.append(PlannedMove(doc_id, src, "", "move", "模板渲染出来是空的"))
                continue
            dst = root.joinpath(*parts)
            dst_abs = os.path.normcase(os.path.abspath(str(dst)))
            if not dst_abs.startswith(root_abs):
                moves.append(PlannedMove(doc_id, src, str(dst), "move",
                                         "渲染结果落在目标根目录外面，已拒绝"))
                continue
            try:
                validate_path_length(dst)
            except PathTooLongError as exc:
                moves.append(PlannedMove(doc_id, src, str(dst), "move", exc.args[0].splitlines()[0]))
                continue
            key = dst_abs.casefold()
            if key == os.path.normcase(os.path.abspath(src)):
                moves.append(PlannedMove(doc_id, src, str(dst), "move", "源与目标是同一个位置"))
                continue
            if key in claimed:
                moves.append(PlannedMove(doc_id, src, str(dst), "move",
                                         f"与计划里第 {claimed[key]} 项落到同一个位置"))
                continue
            if Path(dst_abs).exists():
                moves.append(PlannedMove(doc_id, src, str(dst), "move",
                                         "目标位置已经有同名文件（默认跳过，不覆盖）"))
                continue
            claimed[key] = ordinal
            src_device = doc.device_id      # ISSUES I40：源侧设备号的唯一来源是 documents 表
            kind = "copy" if src_device is not None and src_device != target_device else "move"
            moves.append(PlannedMove(doc_id, src, str(dst), kind))
        return moves

    def preview_path_length(self, doc_ids: list[int], target_root: str,
                            template: str) -> dict[str, int | float]:
        """预览归档后的路径长度分布（ISSUES I10：路径长度是归档方案预览的显示项）。

        走 `plan()`，所以它和「执行」用的是同一份目标路径 —— 早先它自己另算了一遍
        `目标根 / 原文件名`，于是"预览说 250 字符、真跑起来是另一条路径"这种两个口径
        的账就在这里（A3 要销的就是它）。
        """
        lengths = [len(m.dst_path) for m in self.plan(doc_ids, target_root, template) if m.dst_path]
        if not lengths:
            return {"max_length": 0, "min_length": 0, "avg_length": 0, "over_limit_count": 0}
        return {"max_length": max(lengths), "min_length": min(lengths),
                "avg_length": sum(lengths) / len(lengths),
                "over_limit_count": sum(1 for x in lengths if x > MAX_SAFE_PATH_LENGTH)}

    # —— 提交（用户确认之后的那一步）——————————————————————————————————

    def submit(self, doc_ids: list[int], target_root: str, template: str) -> FileOperation:
        """把一份计划落成 `previewed` 批次并排一次后台任务。返回那条批次。

        **调用之前必须已经拿到用户确认**（**D-042** 丙 的分级控件）：这是全站唯一把批次
        写成 `previewed` 的地方，而 worker 只领 `previewed`，所以"没确认就搬文件"在这条
        链上没有代码路径可走。
        """
        moves = self.plan(doc_ids, target_root, template)
        op = self._create_batch("archive", moves, {
            "doc_ids": doc_ids, "target_root": target_root, "template": template})
        self.jobs.enqueue("archive", priority=3)
        return op

    def submit_undo(self, op_id: int) -> tuple[FileOperation, int, list[str]]:
        """给一条已执行的批次另开一条反向批次。返回（反向批次, 排除条数, 排除原因）。

        排除条件全在 `plan_undo()` 里，而 `plan_undo()` 同时是 S4 确认框读数的来源 ——
        界面上说的和批次里落的是同一份判断，不是两套。
        """
        plan = self.plan_undo(op_id)
        if not plan.moves:
            raise ValueError(f"批次 #{op_id} 没有可撤销的项："
                             + ("；".join(plan.excluded) if plan.excluded else "这一批一项都没搬成"))
        op = self._create_batch("undo", list(plan.moves), {"undo_of": op_id}, undo_of=op_id)
        self.jobs.enqueue("archive", priority=3)
        return op, len(plan.excluded), list(plan.excluded)

    def plan_undo(self, op_id: int) -> UndoPlan:
        """算出「这批能撤哪些、哪些必须排除、其中几条不可逆」。**不动盘、不写库**。

        只收 `reversible=1` 且 `state='done'` 的项（**D-043** 甲 / `docs/DATABASE.md` §5.3）：
        被排除的条数与逐条原因必须一起交给调用方，不许只是一个数（**D-043** 甲 的第 2 行）。
        反向批次的每一项是把原项的 src/dst 对调 —— 除此之外它与正向批次没有任何区别，
        所以撤销不另写一套搬运代码，走同一个执行器、同一份 journal 形状。
        """
        source = self.ops.get_operation(op_id)
        if source is None:
            raise ValueError(f"操作批次不存在：#{op_id}")
        if source.kind == "undo":
            raise ValueError(f"#{op_id} 本身就是一条撤销批次，撤销撤销批次要再往回一层，"
                             "台账会变成一条无限套娃的链；要重跑请对原批次操作")
        reasons: list[str] = []
        moves: list[PlannedMove] = []
        irreversible = 0
        for item in self.ops.list_items(op_id):
            if item.state != "done" or not item.dst_path:
                reasons.append(f"#{item.id} 没搬成（{item.state}），没有要撤回的东西")
                continue
            if not item.reversible:
                reasons.append(f"#{item.id} 被标记为不可逆，不自动撤回")
                irreversible += 1
                continue
            if not Path(item.dst_path).exists():
                reasons.append(f"#{item.id} 的目标位置文件已经不在了，不凭空造源文件")
                continue
            if Path(item.src_path).exists():
                reasons.append(f"#{item.id} 的原位置已经有新文件，撤回会把它盖掉")
                continue
            moves.append(PlannedMove(item.doc_id, item.dst_path, item.src_path, item.kind))
        return UndoPlan(tuple(moves), tuple(reasons), irreversible)

    def _create_batch(self, kind: str, moves: list[PlannedMove], plan: dict,
                      undo_of: int | None = None) -> FileOperation:
        """落一批 pending/skipped 的条目，批次停在 `previewed`（等 worker 领）。"""
        op = self.ops.create_operation(kind=kind, status="previewed", plan=plan,
                                       undo_of=undo_of)
        self.ops.attach_journal(op.id, str(self.paths.journal_dir / f"op_{op.id}.jsonl"))
        for move in moves:
            self.ops.add_item(op.id, move.doc_id, kind=move.kind,
                              src_path=move.src_path, dst_path=move.dst_path or None,
                              reversible=1 if move.will_move else 0,
                              state="pending" if move.will_move else "skipped",
                              error=move.skip_reason)
        return self.ops.get_operation(op.id) or op

    # —— 执行（后台队列的处理函数）————————————————————————————————————

    def handle(self, job: Job, monitor: ProgressMonitor) -> None:
        """队列处理函数：领走所有 `previewed` 的归档/撤销批次并逐项搬。

        签名必须是 `(job, monitor)`（`jobs/queue.py` 的 `Handler` 契约）。早先这里是
        `(job_id, doc_ids, target_root, template)`，而注册在 `bootstrap.py` 的那一行把它
        塞进了按 `handler(job, monitor)` 调用的队列 —— 任何被领到的 archive 任务都会
        当场 TypeError（**ISSUES I68**）。
        """
        processed = 0
        while True:
            op = self.ops.claim_previewed(int(job.id or 0), ("archive", "undo"))
            if op is None:
                if processed == 0:
                    log.info("archive 任务没领到任何 previewed 批次（可能已被上一条任务跑完）")
                return
            processed += self._run_batch(op, monitor, processed)

    def _run_batch(self, op: FileOperation, monitor: ProgressMonitor,
                   already_done: int) -> int:
        """跑一条批次里所有 `pending` 的项，返回它推进了多少项（给下一批算 total 用）。"""
        journal_path = op.journal_path or str(self.paths.journal_dir / f"op_{op.id}.jsonl")
        items = [i for i in self.ops.list_items(op.id) if i.state == "pending"]
        monitor.set_total(already_done + len(items))
        self.ops.write_journal(journal_path, {
            "event": "start", "op_id": op.id, "kind": op.kind, "items": len(items)})

        moved, failed = 0, 0
        for item in items:
            if monitor.cancelled():
                # 停在项与项之间：正在搬的那一项要么没开始、要么已经验完，绝不会留下半截。
                self.ops.write_journal(journal_path, {"event": "aborted", "op_id": op.id,
                                                      "moved": moved, "failed": failed})
                self.ops.finish_operation(op.id, self._batch_status(moved, failed, len(items)))
                monitor.flush()
                raise JobCancelled(f"{op.kind} 批次 #{op.id} 被取消，已搬 {moved} 项、失败 {failed} 项")
            try:
                self._execute_item(item, journal_path)
                moved += 1
            except Exception as exc:      # 一项坏不能带走整批（也不带走 worker 线程）
                log.exception("归档项失败 item_id=%s", item.id)
                self.ops.update_item_state(item.id, "failed", error=str(exc))
                self.ops.write_journal(journal_path, {
                    "event": "item_failed", "item_id": item.id, "error": str(exc)})
                failed += 1
            monitor.advance(1)

        status = self._batch_status(moved, failed, len(items))
        self.ops.finish_operation(op.id, status)
        if op.kind == "undo" and op.undo_of is not None and status == "done":
            # 整批撤销成功才把原批次标成 `undone`（`docs/DATABASE.md` §二 词表里的那一态）。
            # 部分撤销不标：原批次里还剩几项在对面，把它写成"已撤销"就是伪装成功，
            # 而 S4 的台账会因此再也看不出这批没回全。
            self.ops.finish_operation(op.undo_of, "undone")
        self.ops.write_journal(journal_path, {"event": "finish", "op_id": op.id, "status": status})
        log.info("批次 #%s(%s) 跑完：%s，搬成 %d、失败 %d", op.id, op.kind, status, moved, failed)
        return len(items)

    @staticmethod
    def _batch_status(moved: int, failed: int, total: int) -> str:
        """批次终态只从 `models.OP_STATUSES` 里取值（仓储会当场拒绝不在口径里的写法）。

        `total` 是这一批 pending 的条数，缺了它就只会谎报：取消停在 1/3 项时 `failed` 是 0，
        按"没失败就算 done"写出来的台账读数与磁盘上"还有两项没搬"直接矛盾。
        """
        if moved == 0:
            return "failed" if total else "done"
        return "done" if failed == 0 and moved == total else "partially_done"

    def _execute_item(self, item, journal_path: str) -> None:
        """执行单条：先写 journal 再动文件；跨盘 copy 验完 sha256 才删源（G19）。

        搬完之后必须 `documents.adopt_path`：路径是主记录的一部分，改了盘不改库的话
        下一次扫描只会把它标成 missing，而分类/标签/正文全都挂在旧行上。
        """
        src = Path(item.src_path)
        dst = Path(item.dst_path) if item.dst_path else None
        if dst is None:
            raise ValueError(f"操作项没有目标路径 item_id={item.id}")

        # ISSUES I10：长度自检放在建目录之前，避免半截操作后才报错
        validate_path_length(dst)

        self.ops.write_journal(journal_path, {
            "event": "item_start", "item_id": item.id, "src": str(src), "dst": str(dst),
            "kind": item.kind})

        if not src.exists():
            raise FileNotFoundError(f"源文件不存在：{src}")
        src_sha = self._sha256(src)
        dst.parent.mkdir(parents=True, exist_ok=True)

        # G19：跨盘移动绝不先删源
        if item.kind == "move":
            shutil.move(str(src), str(dst))
        elif item.kind == "copy":
            shutil.copy2(str(src), str(dst))
        else:
            raise ValueError(f"未知操作类型：{item.kind}")

        if not dst.exists():
            raise RuntimeError(f"目标文件未生成：{dst}")
        dst_sha = self._sha256(dst)
        if src_sha != dst_sha:
            raise RuntimeError(f"SHA256 不匹配：src={src_sha}, dst={dst_sha}")

        # 跨盘 copy：验证成功后才删源（SPEC 3.6 / G19）
        if item.kind == "copy":
            self.ops.write_journal(journal_path, {
                "event": "dst_verified", "item_id": item.id, "dst_sha256": dst_sha})
            src.unlink()
            self.ops.write_journal(journal_path, {"event": "src_removed", "item_id": item.id})

        if item.doc_id is not None:
            self._adopt_into_library(item.doc_id, dst)

        self.ops.update_item_state(item.id, "done", dst_sha256=dst_sha, src_sha256=src_sha)
        self.ops.write_journal(journal_path, {
            "event": "item_done", "item_id": item.id, "dst_sha256": dst_sha})

    def _adopt_into_library(self, doc_id: int, dst: Path) -> None:
        """搬完之后把新位置写回 documents（id 不变 ⇒ 分类、标签、正文、集合关系全部原地保留）。"""
        identity = read_identity(dst)
        self.docs.adopt_path(
            doc_id, path=identity.path, path_key=identity.path_key, name=identity.name,
            ext=identity.ext, size_bytes=identity.size_bytes, mtime_ns=identity.mtime_ns,
            ctime_ns=identity.ctime_ns)

    def _sha256(self, path: Path) -> str:
        h = hashlib.sha256()
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()
