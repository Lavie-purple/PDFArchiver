"""S3 归档预览与确认 —— **D-042**（丙·丙·甲）＋ **D-043** 甲（执行进后台队列）。

一屏只做一件事：把"打算怎么搬"摆出来给人审，审完要一次确认，确认后**只提交、不在本屏执行**。
形状逐条对得上 `docs/UI-WIREFRAMES.md` §S3 与 `docs/DECISIONS.md` **D-042 / D-043**：

| 屏上的东西 | 唯一来源 | 为什么必须是它 |
| --- | --- | --- |
| 计划表每一行的目标路径 | `ArchiveService.plan()` | §S3「出现界面自己拼路径算出来的行判红」；预览与执行同源（阶段 4 门禁） |
| 计数条的四个数 | 同一份 `plan()` 的返回值 | 界面自算 `len(...)` 就是第二个口径 |
| 「长度」列 | `len(move.dst_path)` + `MAX_SAFE_PATH_LENGTH` | **ISSUES I10** 欠的显示项：路径长度必须是预览的显示项 |
| 「方式」列（同盘 / 跨盘） | `plan()` 的 `kind`，源侧取 `documents.device_id` | **ISSUES I40**：`volume_id` 是死列，全站只许按 `st_dev` 判 |
| 「标记」列 | `plan()` 的 `skip_reason` **原文** | 跳过没有原因文本即判红（§S3）；原因由服务算，界面不重述 |
| 确认控件 | `ui/confirm.py` 的分级形状 | **D-042** 丙 定为全站唯一形状，S4 撤销复用同一条 |
| 确认后 | `ArchiveService.submit()` → `previewed` 批次 + 一次后台任务 | **D-043** 甲：本模态不执行，只给回执「已提交 #N」并作废预览 |
| 空间不足 | `shutil.disk_usage(目标根)` + 待复制总量 | `docs/DATABASE.md` §5.2 末条：不足时「执行」是**禁用**，不是"再提醒一次" |

两个输入框（目标根 / 命名模板）**只对本次运行有效**，生效范围见 `SCOPE_NOTE` 那份常量。
"""
from __future__ import annotations

import shutil

from PySide6 import QtCore, QtGui, QtWidgets

from pdfarchiver.services.archive_service import PlannedMove
from pdfarchiver.services.bootstrap import AppContext
from pdfarchiver.ui.confirm import DangerSummary, confirm_dangerous
from pdfarchiver.ui.format import format_bytes
from pdfarchiver.ui.pages.status_page import unwired_lines
from pdfarchiver.ui.table_layout import set_table_columns

# 「方式」列的行内短写与计数条的长写：同一种搬运的两种措辞，但**只有这一处定义**。
# 线框 §S3 表格里画的就是短写（`同盘 rename` / `跨盘 c+v+d`），长写只在计数条出现一次。
SAME_DISK_ROW = "同盘 rename"
CROSS_DISK_ROW = "跨盘 c+v+d"
SAME_DISK_LONG = "同盘 rename"
CROSS_DISK_LONG = "跨盘 copy+verify+delete"

# 两个输入框的生效范围。写成一个常量、屏上只贴这一份：之前这一栏改了什么都不发生而屏上
# 一点看不出来（**ISSUES I55**），而"能改"与"改了就长期生效"是两件事，必须分开说清。
# 不写回 `settings.json` 是 AGENTS.md「禁止在应用运行时改配置文件」的直接结果；
# **D-042** 丙 定的「编辑入口挪到 S7」还欠着（挂账见 **ISSUES I55** 的收尾条目）。
SCOPE_NOTE = ("目标根目录与命名模板只对本次运行生效：改动立即作用于下面的预览与「执行归档」，"
              "但不会写回 settings.json —— 重启后回到配置文件里的那一份。")

PREVIEW_EMPTY = "还没有计划：勾选文档后点「生成预览」。"


class ArchivePage(QtWidgets.QWidget):
    """S3：归档预览与确认。"""

    def __init__(self, ctx: AppContext, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.ctx = ctx
        # 预览过的计划签名：逐项 `(doc_id, 源, 目标, 方式, 跳过原因)`。
        # 「执行」前重算一遍并逐条比对，不一致就不许执行 —— 见 `_execute_archive`。
        self._preview: tuple[tuple[object, ...], ...] | None = None
        # 预览那一份计划的"目标卷装得下"读数。`docs/DATABASE.md` §5.2 末条要的是**禁用**，
        # 不是"再提醒一次"，所以它必须在按下去之前就把按钮按住；而它只能在算完计划之后才知道，
        # 于是与 `_preview` 同生同灭（作废预览时一起清掉）。
        self._space_ok: bool = False

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        top_lay = QtWidgets.QFormLayout()
        self.target_root_input = QtWidgets.QLineEdit()
        self.target_root_input.setPlaceholderText("归档要搬去的那个根目录…")
        self.target_root_input.setText(self.ctx.settings.values.get("archive_target_root", ""))
        self.browse_btn = QtWidgets.QPushButton("选择…")
        self.browse_btn.clicked.connect(self._pick_target_root)
        root_row = QtWidgets.QHBoxLayout()
        root_row.setContentsMargins(0, 0, 0, 0)
        root_row.addWidget(self.target_root_input, 1)
        root_row.addWidget(self.browse_btn)
        root_holder = QtWidgets.QWidget()
        root_holder.setLayout(root_row)
        top_lay.addRow("目标根目录:", root_holder)

        self.template_input = QtWidgets.QLineEdit()
        # 回显只取生效值：这里再写一遍模板字面量就是第二个口径
        # （§S3「模板回显」那行钉的是"显示的串必须等于 Settings.values[...]"）。
        self.template_input.setText(self.ctx.settings.values["archive_default_template"])
        top_lay.addRow("命名模板:", self.template_input)

        self.scope_note = QtWidgets.QLabel(SCOPE_NOTE)
        self.scope_note.setObjectName("muted")
        self.scope_note.setWordWrap(True)
        top_lay.addRow(self.scope_note)

        # 未接线条目仍然只从 `status_page.UNWIRED_ACTIONS` 出来（全站那一份）。这一屏现在
        # 一条都不欠，所以列表空掉时这个标签**整块隐藏** —— 留一句光秃秃的「本轮未接线：」
        # 会让人以为后面还有内容被截断了。
        self.unwired_label = QtWidgets.QLabel()
        self.unwired_label.setObjectName("muted")
        self.unwired_label.setWordWrap(True)
        self._show_unwired()
        top_lay.addRow(self.unwired_label)

        layout.addLayout(top_lay)

        doc_title = QtWidgets.QLabel("待归档文档（从文档库勾选）")
        doc_title.setObjectName("sectionTitle")
        layout.addWidget(doc_title)
        self.doc_table = QtWidgets.QTableWidget()
        self.doc_table.setColumnCount(4)
        self.doc_table.setHorizontalHeaderLabels(["选择", "文件名", "路径", "分类"])
        # 让「分类」当吸收列而不是「文件名」：定宽那三列合计 576px，地板档（窗口 1024px）下这张
        # 表的视口实测 805px（空库读数），富余全落在吸收列上（实测「分类」229px）—— 文件名/路径
        # 保住定宽，被吃掉的是信息量最低、且左栏分类树里本来就有的那一列。地板档已经压不出更窄的
        # 视口了（**D-039** 的 1024px 地板，见 **ISSUES I52**），所以"吸收列落错地方"这一类
        # 由 `test_压到地板宽度时归档表仍保住文件名与路径` 钉住，而不是靠窗口还能更小来暴露。
        # 805px 现在是个**与行数无关**的读数（**ISSUES I54** 已销：行号列不再长出来）。
        set_table_columns(self.doc_table, {0: 56, 1: 280, 2: 240}, stretch_col=3)
        self.doc_table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.doc_table.setAlternatingRowColors(True)
        self.doc_table.itemChanged.connect(self._invalidate_preview)
        layout.addWidget(self.doc_table, 1)

        preview_title = QtWidgets.QLabel("计划表（源 → 目标 · 只读）")
        preview_title.setObjectName("sectionTitle")
        layout.addWidget(preview_title)
        self.plan_summary = QtWidgets.QLabel(PREVIEW_EMPTY)
        self.plan_summary.setObjectName("muted")
        self.plan_summary.setWordWrap(True)
        layout.addWidget(self.plan_summary)

        self.preview_table = QtWidgets.QTableWidget()
        self.preview_table.setColumnCount(5)
        self.preview_table.setHorizontalHeaderLabels(
            ["源路径", "目标路径", "长度", "方式", "标记"])
        # 五条全定宽、没有吸收列：合计 890px > 地板档视口（805px），按 `table_layout` 的口径
        # 横向滚动。§S3 明写 1024 档"先砍长度、再缩源"，而「目标 / 方式 / 标记」不许砍
        # （PROJECT_SPEC 3.6.5 明列的三项），所以这里宁可滚。
        set_table_columns(self.preview_table,
                          {0: 240, 1: 260, 2: 64, 3: 126, 4: 200}, stretch_col=None)
        self.preview_table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.preview_table.setSelectionBehavior(
            QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.preview_table.setAlternatingRowColors(True)
        layout.addWidget(self.preview_table, 1)

        btn_lay = QtWidgets.QHBoxLayout()
        self.load_btn = QtWidgets.QPushButton("加载文档库")
        self.load_btn.clicked.connect(self._load_documents)
        btn_lay.addWidget(self.load_btn)

        self.preview_btn = QtWidgets.QPushButton("生成预览")
        self.preview_btn.clicked.connect(self._generate_preview)
        btn_lay.addWidget(self.preview_btn)

        self.execute_btn = QtWidgets.QPushButton("执行归档")
        self.execute_btn.setObjectName("searchBtn")
        self.execute_btn.clicked.connect(self._execute_archive)
        btn_lay.addWidget(self.execute_btn)
        btn_lay.addStretch()
        layout.addLayout(btn_lay)

        # 输入位任何一个动过，旧预览就不再是"将要执行的那一份"，必须重算。
        self.target_root_input.textChanged.connect(self._invalidate_preview)
        self.template_input.textChanged.connect(self._invalidate_preview)
        self._update_execute_enabled()

    # —— 读数（全部来自 `plan()`，界面不自己拼路径、不自算条数）——————————

    def _show_unwired(self) -> None:
        lines = unwired_lines("S3")
        self.unwired_label.setText(("本轮未接线：" + "；".join(lines)) if lines else "")
        self.unwired_label.setVisible(bool(lines))

    def _selected_doc_ids(self) -> list[int]:
        ids: list[int] = []
        for row in range(self.doc_table.rowCount()):
            cell = self.doc_table.item(row, 0)
            if cell and cell.checkState() == QtCore.Qt.CheckState.Checked:
                ids.append(cell.data(QtCore.Qt.ItemDataRole.UserRole))
        return ids

    def _inputs(self) -> tuple[str, str]:
        return (self.target_root_input.text().strip(), self.template_input.text().strip())

    def _plan(self) -> list[PlannedMove] | None:
        """按当前输入算一份计划；算不出来时**当场把原因显示给用户**并返回 None。

        错误只有一条出口：`plan()` 抛的就是整批级错误（目标根不存在 / 模板写错），
        原文直接显示，不在界面里重述一遍（重述就是第二个口径）。
        """
        target_root, template = self._inputs()
        if not target_root:
            QtWidgets.QMessageBox.warning(self, "归档计划", "请先设置目标根目录")
            return None
        doc_ids = self._selected_doc_ids()
        if not doc_ids:
            QtWidgets.QMessageBox.warning(
                self, "归档计划", "请先在「待归档文档」里勾选要归档的文档")
            return None
        try:
            return self.ctx.archive.plan(doc_ids, target_root, template)
        except ValueError as exc:
            QtWidgets.QMessageBox.warning(self, "归档计划算不出来", str(exc))
            return None

    @staticmethod
    def _counts(moves: list[PlannedMove]) -> dict[str, int]:
        will = [m for m in moves if m.will_move]
        return {
            "total": len(moves),
            "run": len(will),
            "same": sum(1 for m in will if m.kind == "move"),
            "cross": sum(1 for m in will if m.kind == "copy"),
            "skipped": len(moves) - len(will),
            # 不可逆的口径在 `PlannedMove.irreversible`（**ISSUES I69** 丙），界面只数不算 ——
            # 两处各算各的会让同一批文件在 S3 要输确认词、在 S4 只要勾一下。
            "irreversible": sum(1 for m in moves if m.irreversible),
        }

    def _copy_bytes(self, moves: list[PlannedMove]) -> int:
        """跨盘项的待复制总量（同盘 rename 不占新空间，不计）。"""
        total = 0
        for move in moves:
            if move.kind != "copy" or move.doc_id is None:
                continue
            doc = self.ctx.documents.get(move.doc_id)
            total += doc.size_bytes if doc else 0
        return total

    def _space_shortfall(self, moves: list[PlannedMove]) -> int:
        """目标卷装不下跨盘那部分时返回差额字节数，装得下返回 0。"""
        target_root = self._inputs()[0]
        try:
            free = shutil.disk_usage(target_root).free
        except OSError:               # 盘没挂载 / 目录刚被删：不当作"空间充足"
            return -1 if self._copy_bytes(moves) > 0 else 0
        return max(0, self._copy_bytes(moves) - free)

    # —— 交互 ————————————————————————————————————————————————

    def _pick_target_root(self) -> None:
        start = self._inputs()[0] or str(self.ctx.paths.root)
        target = QtWidgets.QFileDialog.getExistingDirectory(self, "选择归档目标根目录", start)
        if target:
            self.target_root_input.setText(target)

    def _load_documents(self) -> None:
        """从文档库加载候选文档。`itemChanged` 会因这次填充逐行触发，所以整段屏蔽信号。"""
        docs = self.ctx.documents.list(limit=500)
        self.doc_table.blockSignals(True)
        self.doc_table.setRowCount(len(docs))
        for row, doc in enumerate(docs):
            checkbox = QtWidgets.QTableWidgetItem()
            checkbox.setCheckState(QtCore.Qt.CheckState.Unchecked)
            checkbox.setData(QtCore.Qt.ItemDataRole.UserRole, doc.id)
            self.doc_table.setItem(row, 0, checkbox)
            name_item = QtWidgets.QTableWidgetItem(doc.name)
            # 「文件名」「分类」是定宽装不下的可截断列（名字长度没有上限、分类是最多
            # 三个用户自定义名），口径与「路径」一致：截断了必须能悬停读回全文。
            name_item.setToolTip(doc.name)
            self.doc_table.setItem(row, 1, name_item)
            path_item = QtWidgets.QTableWidgetItem(doc.path)
            path_item.setToolTip(doc.path)
            self.doc_table.setItem(row, 2, path_item)
            cats = self.ctx.catalog.categories_of(doc.id)
            cat_str = ", ".join(c.name for c in cats[:2])
            cat_item = QtWidgets.QTableWidgetItem(cat_str)
            cat_item.setToolTip(cat_str)
            self.doc_table.setItem(row, 3, cat_item)
        self.doc_table.blockSignals(False)
        self._invalidate_preview()

    def _invalidate_preview(self, *_ignored: object) -> None:
        """让"已经预览过"作废：勾选、输入、提交之后都会走到这里。"""
        self._preview = None
        self._space_ok = False
        self._update_execute_enabled()

    def _update_execute_enabled(self) -> None:
        # 「执行」只在**看过计划**之后可用（§S3：未确认绝不执行；滚不到确认区就不算看完计划），
        # 且计划装不进目标卷时必须按住（§5.2 末条要的是禁用，不是提示）。
        self.execute_btn.setEnabled(self._preview is not None and self._space_ok)

    def _generate_preview(self) -> None:
        moves = self._plan()
        if moves is None:
            self._invalidate_preview()
            return
        self._render_plan(moves)
        self.plan_summary.setText(self._summary_text(moves))
        self._preview = self._signature(moves)
        self._space_ok = self._space_shortfall(moves) == 0
        self._update_execute_enabled()

    def _render_plan(self, moves: list[PlannedMove]) -> None:
        skipped_role = self.preview_table.palette().color(
            QtGui.QPalette.ColorGroup.Disabled, QtGui.QPalette.ColorRole.Text)
        self.preview_table.blockSignals(True)
        self.preview_table.setRowCount(len(moves))
        for row, move in enumerate(moves):
            src_item = QtWidgets.QTableWidgetItem(move.src_path)
            src_item.setToolTip(move.src_path)
            self.preview_table.setItem(row, 0, src_item)

            dst_text = move.dst_path or "—"
            dst_item = QtWidgets.QTableWidgetItem(dst_text)
            dst_item.setToolTip(dst_text)
            self.preview_table.setItem(row, 1, dst_item)

            self.preview_table.setItem(
                row, 2, QtWidgets.QTableWidgetItem(
                    str(len(move.dst_path)) if move.dst_path else "—"))

            if move.will_move:
                kind_text = SAME_DISK_ROW if move.kind == "move" else CROSS_DISK_ROW
                kind_tip = SAME_DISK_LONG if move.kind == "move" else CROSS_DISK_LONG
                mark_text = "—"
            else:
                # 「跳过没有原因文本即判红」（§S3）：原因来自 `plan()` 原文，界面不重述。
                kind_text, kind_tip = "—", "不进执行"
                mark_text = move.skip_reason or "跳过（计划没给出原因）"
            kind_item = QtWidgets.QTableWidgetItem(kind_text)
            kind_item.setToolTip(kind_tip)
            self.preview_table.setItem(row, 3, kind_item)
            mark_item = QtWidgets.QTableWidgetItem(mark_text)
            mark_item.setToolTip(mark_text)
            if not move.will_move:
                mark_item.setForeground(skipped_role)
            self.preview_table.setItem(row, 4, mark_item)
        self.preview_table.blockSignals(False)

    def _summary_text(self, moves: list[PlannedMove]) -> str:
        counts = self._counts(moves)
        return "\n".join([
            f"计划 {counts['total']} 项 = 将执行 {counts['run']}"
            f"（{SAME_DISK_LONG} {counts['same']}｜{CROSS_DISK_LONG} {counts['cross']}）"
            f"｜跳过 {counts['skipped']}（原因见「标记」列）"
            f"｜不可逆 {counts['irreversible']}",
            self._space_line(moves),
        ])

    def _space_line(self, moves: list[PlannedMove]) -> str:
        """目标卷剩余 ⇄ 待复制总量（`docs/DATABASE.md` §5.2 末条要求同屏可见）。"""
        needed = self._copy_bytes(moves)
        target_root = self._inputs()[0]
        try:
            free = shutil.disk_usage(target_root).free
        except OSError:               # 读不出来就说读不出来，不许显示上一个数
            return f"目标卷剩余空间读不出来：{target_root}｜待复制 {format_bytes(needed)}"
        line = f"目标卷剩余 {format_bytes(free)}｜待复制 {format_bytes(needed)}"
        if needed > free:
            line += f"—— 空间不足，还差 {format_bytes(needed - free)}，「执行归档」已禁用"
        return line

    @staticmethod
    def _signature(moves: list[PlannedMove]) -> tuple[tuple[object, ...], ...]:
        return tuple((m.doc_id, m.src_path, m.dst_path, m.kind, m.skip_reason) for m in moves)

    def _execute_archive(self) -> None:
        """分级确认 → `submit()` 落 `previewed` 批次 + 排一次后台任务 → 给回执。

        本屏**不执行**（**D-043** 甲）：`第 k/M 项｜journal 态｜error 原文` 那套逐态读数归 S4。
        把批次写成 `previewed` 是全站唯一入口，而 worker 只领 `previewed`
        （`OperationRepository.claim_previewed`），所以"没确认就搬文件"在这条链上
        没有代码路径可走。
        """
        if self._preview is None:
            QtWidgets.QMessageBox.warning(
                self, "执行归档", "请先点「生成预览」—— 没看过计划就不许执行")
            return

        moves = self._plan()
        if moves is None:
            return
        if self._signature(moves) != self._preview:
            # 计划变了（磁盘上的文件动了、或者勾选与输入动了）：**旧预览已经不代表将要执行的那份**。
            # 这里不"照着新计划直接执行"，因为用户看的是旧的那一份。
            self._invalidate_preview()
            self.preview_table.setRowCount(0)
            self.plan_summary.setText("计划在这之后变了，旧预览已作废。")
            QtWidgets.QMessageBox.warning(
                self, "执行归档", "现在算出来的计划和你刚看过的那份已经不一致，请重新生成预览。")
            return

        counts = self._counts(moves)
        if counts["run"] == 0:
            QtWidgets.QMessageBox.information(
                self, "执行归档",
                f"这 {counts['total']} 项全部被跳过（原因见「标记」列），"
                "一项都不会动到磁盘，所以没有要执行的批次。")
            return
        shortfall = self._space_shortfall(moves)
        if shortfall:
            QtWidgets.QMessageBox.warning(
                self, "执行归档",
                "目标卷装不下要复制的那部分"
                + (f"，还差 {format_bytes(shortfall)}" if shortfall > 0 else "（剩余空间读不出来）")
                + "，已拒绝执行。")
            return

        if not confirm_dangerous(
                self, title="确认执行归档", verb="归档",
                summary=DangerSummary(
                    will_run=counts["run"], same_disk=counts["same"],
                    cross_disk=counts["cross"], irreversible=counts["irreversible"],
                    lines=tuple(self.plan_summary.text().split("\n")[1:]))):
            return

        target_root, template = self._inputs()
        op = self.ctx.archive.submit(self._selected_doc_ids(), target_root, template)
        self._invalidate_preview()
        self.preview_table.setRowCount(0)
        self.plan_summary.setText(f"已提交批次 #{op.id}，本屏的预览已作废。")
        QtWidgets.QMessageBox.information(
            self, "已提交",
            f"已提交 #{op.id}｜共 {op.items_total} 项（其中不进执行 {counts['skipped']} 项）\n"
            "进度与 journal 态去「操作日志与撤销」那一屏看。")
