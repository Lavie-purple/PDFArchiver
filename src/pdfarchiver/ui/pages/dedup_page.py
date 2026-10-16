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
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
                                QTableWidget, QTableWidgetItem, QHeaderView, QGroupBox,
                                QProgressBar, QMessageBox)

from pdfarchiver.services.bootstrap import AppContext
from pdfarchiver.services.status_service import format_day

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

        btn_row = QHBoxLayout()
        self.btn_start = QPushButton("发起全库判重")
        self.btn_start.setObjectName("searchBtn")
        self.btn_start.setMinimumHeight(32)
        self.btn_start.clicked.connect(self._start_dedup)
        btn_row.addWidget(self.btn_start)

        self.btn_refresh = QPushButton("刷新读数")
        self.btn_refresh.clicked.connect(self.reload)
        btn_row.addWidget(self.btn_refresh)
        btn_row.addStretch()

        group_layout.addLayout(btn_row)
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

        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(["浪费量", "SHA256（前8位）", "份数", "路径（悬停看全长）", "状态"])
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.Stretch)
        header.setSectionResizeMode(4, QHeaderView.ResizeToContents)
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

    def reload(self) -> None:
        self._reload_participation()
        self._reload_summary()
        self._reload_groups()
        self.reload_progress()

    def reload_progress(self) -> None:
        """只刷进度那一块 —— 定时器每 tick 调这条，不调 `reload()`。

        `reload()` 里的组表要查 500 组、每组再查一次成员，把它挂到 5 秒一次的定时器上
        等于每 tick 做一次接近全量的重查；而进度只需要 `latest_of_kind` 那一行。
        """
        job = self.ctx.jobs.latest_of_kind("dedup")
        self._active_job = job
        self._sync_start_button()
        if job is None:
            self.progress_bar.setVisible(False)
            self.lbl_progress.setVisible(False)
            return
        head = _STATE_READING[job.state]
        if not job.total:
            # `set_total` 还没跑到（刚排队、还没数出待算份数）：区间给 0..0 是 Qt 的忙碌条，
            # 说的是"在干了，总量还不知道"；硬撑一个 0% 的满量程条反而像卡死。
            self.progress_bar.setRange(0, 0)
            self.lbl_progress.setText(f"{head}：待算份数还没数出来")
        else:
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
        excess_count = summary["excess_count"]
        reclaimable = summary["reclaimable_bytes"]

        if reclaimable >= 1024 * 1024 * 1024:
            reclaim_text = f"{reclaimable / 1024 / 1024 / 1024:.2f} GB"
        else:
            reclaim_text = f"{reclaimable / 1024 / 1024:.1f} MB"

        self.lbl_summary.setText(
            f"重复组：{group_count:,} 组｜多余副本：{excess_count:,} 份｜"
            f"若清理可回收：{reclaim_text}")

        hardlink_groups = self.ctx.documents.count_hardlink_groups()
        if hardlink_groups > 0:
            self.lbl_hardlink_note.setText(
                f"⚠ 其中硬链接同份 {hardlink_groups:,} 组 → 已从「可回收」里排除（读数口径唯一）")
        else:
            self.lbl_hardlink_note.setText("无硬链接重复（所有副本均可回收）")

    def _reload_groups(self) -> None:
        """② 段：重复组表。"""
        groups = self.ctx.documents.duplicate_groups(limit=500)
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


def _format_bytes(n: int) -> str:
    if n >= 1024 * 1024 * 1024:
        return f"{n / 1024 / 1024 / 1024:.2f} GB"
    if n >= 1024 * 1024:
        return f"{n / 1024 / 1024:.1f} MB"
    if n >= 1024:
        return f"{n / 1024:.1f} KB"
    return f"{n} B"
