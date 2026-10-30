"""S5 · 重复文件检测 —— 两段式（D-045 定案乙）：① 判重范围与代价 → ② 结果表。

判重口径唯一：`documents.sha256`（字节级同哈希）。
本屏不放删除按钮，清理走 S3→S4 归档批次链（可预览、可撤销）。

布局定案：
- ① 段：发起前的代价读数（待算哈希份数/体积/预计耗时）+ 大按钮
- ② 段：上次扫描结果汇总 + 重复组表（按浪费量倒序）
- 行内注语：硬链接标 `(硬链接)`、已消失标 `(已消失 YYYY-MM-DD)`

数据来源硬条件（全部走仓储，UI 不写 SQL）：
- 参与/未参与：`DocumentRepository.count_hashed_vs_unhashed()`
- 待算哈希代价：`DocumentRepository.unhashed_stats()`
- 硬链接组数：`DocumentRepository.count_hardlink_groups()`
- 重复组列表：`DocumentRepository.duplicate_groups()`
- 组内成员：`DocumentRepository.duplicate_group_members()`
- 汇总读数：`DocumentRepository.dedup_summary()`
- 判重进度：`JobRepository.latest_of_kind("dedup")` 的 `done` / `total`
"""
from __future__ import annotations

import logging

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QLabel, QPushButton,
                                QTableWidget, QTableWidgetItem, QGroupBox,
                                QProgressBar, QMessageBox)

from pdfarchiver.services.bootstrap import AppContext
from pdfarchiver.services.status_service import format_day
from pdfarchiver.ui.action_row import ActionRow
from pdfarchiver.ui.format import format_bytes as _format_bytes
from pdfarchiver.ui.table_layout import CELL_PADDING_WIDTH, loaded_line, set_table_columns

log = logging.getLogger("pdfarchiver.ui.dedup")

_SHA_DISPLAY_LEN = 8
_BYTES_PER_SEC = 240 * 1024 * 1024

# 任务状态 → 这一屏上怎么说。六个合法状态一个都不许漏：漏掉的那个要么显示成英文单词，
# 要么（更坏）显示成空串。覆盖度由 `test_progress_state_vocabulary` 对着仓储的 `STATES` 钉住。
_STATE_READING = {
    "running": "判重进行中",
    "queued": "判重已排队",
    "paused": "判重已暂停",
    "done": "判重完成",
    "failed": "判重失败",
    "cancelled": "判重已取消",
}
# 未终结 = 已经排过了，不该再让人按一次「发起」。(与仓储 `LIVE_STATES` 同集合，同一测试钉住)
_LIVE_STATES = ("queued", "running", "paused")


class DedupPage(QWidget):
    """S5 重复文件检测页。两段式布局（乙定案）：① 代价 → ② 结果表。"""

    def __init__(self, ctx: AppContext) -> None:
        super().__init__()
        self.ctx = ctx
        # 「发起」按钮的两个前置事实，各自只由一个方法写：见 `_sync_start_button`
        self._unhashed_count: int | None = None
        self._active_job = None
        self._init_ui()
        self.reload()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        self._build_stage1(layout)
        self._build_stage2(layout)
        self._build_progress_bar(layout)

    def _build_stage1(self, parent_layout: QVBoxLayout) -> None:
        """① 判重范围与代价 —— 发起前就给代价读数。"""
        group = QGroupBox("① 判重范围与代价")
        group_layout = QVBoxLayout()

        self.lbl_participation = QLabel("参与判重：- 份｜未参与（没算过哈希）：- 份")
        self.lbl_participation.setWordWrap(True)
        group_layout.addWidget(self.lbl_participation)

        self.lbl_cost = QLabel("待算哈希：- 份 ≈ - MB，按实测 240MB/s 预计耗时 -")
        self.lbl_cost.setWordWrap(True)
        self.lbl_cost.setObjectName("muted")
        group_layout.addWidget(self.lbl_cost)

        btn_row = ActionRow()
        self.btn_start = QPushButton("发起全库判重")
        self.btn_start.setObjectName("searchBtn")
        self.btn_start.setMinimumHeight(32)
        self.btn_start.clicked.connect(self._start_dedup)
        btn_row.add_button(self.btn_start)

        self.btn_refresh = QPushButton("刷新读数")
        self.btn_refresh.clicked.connect(self.reload)
        btn_row.add_button(self.btn_refresh)
        self.action_row = btn_row

        group_layout.addWidget(btn_row)
        group.setLayout(group_layout)
        parent_layout.addWidget(group)

    def _build_stage2(self, parent_layout: QVBoxLayout) -> None:
        """② 结果汇总 + 重复组表。"""
        summary_group = QGroupBox("② 上次判重结果")
        summary_layout = QVBoxLayout()

        self.lbl_summary = QLabel("重复组：-｜多余副本：-｜若清理可回收：-")
        self.lbl_summary.setWordWrap(True)
        summary_layout.addWidget(self.lbl_summary)

        self.lbl_hardlink_note = QLabel("")
        self.lbl_hardlink_note.setWordWrap(True)
        self.lbl_hardlink_note.setObjectName("muted")
        summary_layout.addWidget(self.lbl_hardlink_note)

        summary_group.setLayout(summary_layout)
        parent_layout.addWidget(summary_group)

        # 表头之前那条汇总说的是"库里有多少组"，这一行说的是"表格里有多少组" ——
        # 两个数分开摆，取满 `limit` 时才不会把"没列出来"说成"不存在"（**ISSUES I76**）
        self.loaded_note = QLabel("")
        self.loaded_note.setWordWrap(True)
        self.loaded_note.setObjectName("muted")
        parent_layout.addWidget(self.loaded_note)

        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(["浪费量", "SHA256（前8位）", "份数", "路径（悬停看全长）", "状态"])
        # 判重页并进 `set_table_columns` 定宽口径（ISSUES I61 选甲）：与其他 7 张表同一套口径，
        # 列宽按内容上限反算 + CELL_PADDING_WIDTH。路径列（col=3）作为 stretch_col 吸收剩余。
        # 500 组档上限实测：浪费量最长 "999.99 GB"、SHA 固定 8 字符、份数 ≤3 位、状态最长 "缺+硬链接"。
        # 列头宽度也要算进去："SHA256（前8位）" = 107px + 23 = 130px。
        set_table_columns(self.table, widths={
            0: 103,  # 浪费量：10 字符内容 + 23 内边距
            1: 130,  # SHA256 前 8 位：列头 107px + 23（列头比内容宽）
            2: 63,   # 份数：3 位数字 + 23
            4: 103,  # 状态：5 中文字 + 23
        }, stretch_col=3)  # 路径列吸收剩余
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        parent_layout.addWidget(self.table, 1)

    def _build_progress_bar(self, parent_layout: QVBoxLayout) -> None:
        """判重任务的进度块。默认收起，只在库里真有 `kind=dedup` 的任务行时才出现。

        百分比文字是关掉的，两个理由都量过：
        1. 线框 **§S5「进度」**的硬条件是「只读 `done`/`total` 这两个数，不许出现整库判重总进度
           百分比这种合并假数」—— 份数写在旁边的标签上，条子本身只表达比例。
        2. Qt 把进度条文字**横着压在进度块上**，块是 `accent` 填充：`text_primary` 落在上面
           浅色 **4.19:1**、暗色 **2.98:1**，两套主题都不过 AA。标签落在正文底上（4.69 / 6.96）。
        """
        self.progress_bar = QProgressBar()
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setVisible(False)
        parent_layout.addWidget(self.progress_bar)

        self.lbl_progress = QLabel("")
        self.lbl_progress.setWordWrap(True)
        self.lbl_progress.setObjectName("muted")
        self.lbl_progress.setVisible(False)
        parent_layout.addWidget(self.lbl_progress)

        # 进度那句认给 ① 段的行末（**ISSUES I121** ④）：进度条是它的同伴，两个一起搬 ——
        # 把句子挪进行末而把条子留在页底，等于把一句读数劈成两半。地板档两个都回原位。
        self.action_row.absorb(parent_layout, self.lbl_progress,
                               companions=(self.progress_bar,))

    def reload(self) -> None:
        self._reload_participation()
        self._reload_summary()
        self._reload_groups()
        self.reload_progress()

    def reload_progress(self) -> None:
        """只刷进度那一块 —— 定时器每 tick 调这条，不调 `reload()`。

        `reload()` 里的组表要查 500 组、每组再查一次成员，把它挂到 5 秒一次的定时器上
        等于每 tick 做一次接近全量的重查；而进度只需要 `latest_of_kind` 那一行。

        末尾那一次 `action_row.sync()` 不是保险丝：这一格搬不搬的判据要看那句**可见不可见**，
        而 `setVisible` 不发信号（`textChanged` 在还藏着的时候就已经发过了）。三个出口都用
        `finally` 走同一条，改天多一个提前 return 也不会漏刷。
        """
        try:
            self._apply_progress_reading()
        finally:
            self.action_row.sync()

    def _apply_progress_reading(self) -> None:
        job = self.ctx.jobs.latest_of_kind("dedup")
        self._active_job = job
        self._sync_start_button()
        if job is None:
            self.progress_bar.setVisible(False)
            self.lbl_progress.setVisible(False)
            return
        head = _STATE_READING[job.state]
        if not job.total:
            if job.state in _LIVE_STATES:
                # `set_total` 还没跑到（刚排队、还没数出待算份数）：区间给 0..0 是 Qt 的忙碌条，
                # 说的是"在干了，总量还不知道"；硬撑一个 0% 的满量程条反而像卡死。
                self.progress_bar.setVisible(True)
                self.progress_bar.setRange(0, 0)
                self.lbl_progress.setText(f"{head}：待算份数还没数出来")
            else:
                # 任务已经终结而 total 仍是 0：一份都没算过，也就没有"份数"可报。
                # 还挂忙碌条 +「还没数出来」是在说任务仍在干，与状态栏的终结态直接矛盾
                # （**ISSUES I105**：轮十九真机截图 S5 上逮到的就是这一句）。
                self.progress_bar.setVisible(False)
                text = f"{head}：没有要算的份数" if job.state == "done" else head
                if job.state != "done" and job.last_error:
                    text += f"｜故障原文：{job.last_error}"
                self.lbl_progress.setText(text)
            self.lbl_progress.setVisible(True)
            return
        self.progress_bar.setRange(0, job.total)
        self.progress_bar.setValue(job.done)
        text = f"{head}：第 {job.done:,}/{job.total:,} 份"
        if job.last_error:
            text += f"｜故障原文：{job.last_error}"
        self.lbl_progress.setText(text)
        self.progress_bar.setVisible(True)
        self.lbl_progress.setVisible(True)

    def _sync_start_button(self) -> None:
        """「发起全库判重」只在**还有份没算过哈希**且**没有判重任务活着**时亮着。

        两个条件分开写会互相覆盖（谁最后刷新谁说了算）：计数那里写完 enabled，
        进度这里又改一遍，结果就是定时器一 tick 把已经排过的按钮重新点亮，
        按下去只弹一句「判重已在进行」。
        """
        live = self._active_job is not None and self._active_job.state in _LIVE_STATES
        pending = (self._unhashed_count or 0) > 0
        self.btn_start.setEnabled(pending and not live)

    def _reload_participation(self) -> None:
        """① 段：参与/未参与读数 + 待算哈希代价。"""
        hashed, unhashed = self.ctx.documents.count_hashed_vs_unhashed()
        total = hashed + unhashed
        self.lbl_participation.setText(
            f"参与判重：{hashed:,} 份｜未参与（没算过哈希）：{unhashed:,} 份｜全库：{total:,} 份")

        stats = self.ctx.documents.unhashed_stats()
        count = stats["count"]
        self._unhashed_count = count
        total_bytes = stats["total_bytes"]
        size_mb = total_bytes / 1024 / 1024
        seconds = total_bytes / _BYTES_PER_SEC if total_bytes > 0 else 0
        minutes = int(seconds // 60)
        secs = int(seconds % 60)

        if count == 0:
            self.lbl_cost.setText("全部文件已算过哈希，无需再次判重。")
        else:
            self.lbl_cost.setText(
                f"待算哈希：{count:,} 份 ≈ {size_mb:,.0f} MB，"
                f"按实测 240MB/s 预计耗时 {minutes} 分 {secs} 秒")
        self._sync_start_button()

    def _reload_summary(self) -> None:
        """② 段：汇总读数 + 硬链接排除注语。"""
        summary = self.ctx.documents.dedup_summary()
        group_count = summary["group_count"]
        # 留给下面的 `_reload_groups` 用：**重复组数只许有这一条 SQL**（`dedup_summary`），
        # 再造一个 `count_duplicate_groups` 就是同一个概念第二个口径（AGENTS.md「禁止核心
        # 概念有多个口径」）。`reload()` 里两段按顺序跑，取数只有一次。
        self._group_total = group_count
        excess_count = summary["excess_count"]
        reclaimable = summary["reclaimable_bytes"]

        self.lbl_summary.setText(
            f"重复组：{group_count:,} 组｜多余副本：{excess_count:,} 份｜"
            f"若清理可回收：{_format_bytes(reclaimable)}")

        hardlink_groups = self.ctx.documents.count_hardlink_groups()
        if hardlink_groups > 0:
            self.lbl_hardlink_note.setText(
                f"⚠ 其中硬链接同份 {hardlink_groups:,} 组 → 已从「可回收」里排除（读数口径唯一）")
        else:
            self.lbl_hardlink_note.setText("无硬链接重复（所有副本均可回收）")

    def _reload_groups(self) -> None:
        """② 段：重复组表。组数上限取仓储层默认值，界面不定数（**ISSUES I76**）。"""
        groups = self.ctx.documents.duplicate_groups()
        self.table.setRowCount(len(groups))

        for i, g in enumerate(groups):
            sha_short = g["sha256"][:_SHA_DISPLAY_LEN] if g["sha256"] else "-"
            waste = g["waste_size"]
            waste_text = _format_bytes(waste)
            paths_text, status_text = self._render_group_info(g["sha256"])

            self.table.setItem(i, 0, QTableWidgetItem(waste_text))
            self.table.setItem(i, 1, QTableWidgetItem(sha_short))
            self.table.setItem(i, 2, QTableWidgetItem(str(g["count"])))

            path_item = QTableWidgetItem(paths_text)
            path_item.setToolTip(paths_text)
            self.table.setItem(i, 3, path_item)

            self.table.setItem(i, 4, QTableWidgetItem(status_text))

        self.loaded_note.setText(loaded_line(self._group_total, len(groups), "组重复"))

    def _render_group_info(self, sha256: str) -> tuple[str, str]:
        """组内路径摘要（带行内注语）+ 状态摘要。"""
        members = self.ctx.documents.duplicate_group_members(sha256)
        parts = []
        has_missing = False
        has_hardlink = False

        for m in members:
            path = m["path"]
            if m["missing_since"] is not None:
                has_missing = True
                ts = format_day(m["missing_since"])
                parts.append(f"{path}（已消失 {ts}）")
            elif m["is_hardlink"]:
                has_hardlink = True
                parts.append(f"{path}（硬链接）")
            else:
                parts.append(path)

        paths_text = " ｜ ".join(parts)

        if has_missing and has_hardlink:
            status_text = "缺+硬链接"
        elif has_missing:
            status_text = "缺"
        elif has_hardlink:
            status_text = "硬链接"
        else:
            status_text = "在"

        return paths_text, status_text

    def _start_dedup(self) -> None:
        """发起判重任务（走后台队列，KINDS 已含 dedup）。"""
        existing = self.ctx.jobs.list(states=("queued", "running", "paused"))
        for job in existing:
            if job.kind == "dedup":
                QMessageBox.information(
                    self, "判重已在进行",
                    f"已有判重任务（ID {job.id}，状态 {job.state}），请等待完成后再发起。")
                return

        job = self.ctx.jobs.enqueue("dedup", doc_id=None, priority=5)
        if job is None:
            QMessageBox.information(self, "已排过", "判重任务已在队列中。")
            return

        QMessageBox.information(
            self, "判重已发起",
            f"判重任务已入队（ID {job.id}）。\n进度打在这一屏的进度块上。")
        self.reload_progress()  # 按钮改灰由 `_sync_start_button` 决定，不在这里另写一遍 enabled
