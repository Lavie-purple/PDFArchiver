"""S6 · 备份与恢复向导 —— 三标签页：备份 | 恢复 | 迁移历史。

备份口径唯一：`sqlite3.Connection.backup()`（WAL 模式禁止文件拷贝）。
备份文件名必须带版本号（`catalog-YYYYMMDD-HHMMSS-v版本.db`）。
恢复必须写到新目录，不覆盖当前库。
迁移历史从 `db/migrations/` 文件名派生（无持久化表）。
"""
from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
                                QPushButton, QTableWidget, QTableWidgetItem,
                                QTabWidget, QFileDialog, QMessageBox)

from pdfarchiver.config.paths import AppPaths
from pdfarchiver.services import backup_service
from pdfarchiver.services.bootstrap import AppContext
from pdfarchiver.services.status_service import format_ts
from pdfarchiver.ui.action_row import ActionRow
from pdfarchiver.ui.format import format_bytes
from pdfarchiver.ui.table_layout import CELL_PADDING_WIDTH, set_table_columns

log = logging.getLogger("pdfarchiver.ui.backup")

# 路径显示上限：主窗 1000px 减侧栏 200px 再减页面/标签页内边距 ≈ 700px 可用，
# 给单条路径留 420px（中段省略），剩下的容得下"当前库："前缀和"（结构版本 6）"后缀。
_PATH_MAX_WIDTH = 420


def _elided(path: str, ref: QWidget) -> str:
    """省略目录部分，**文件名两端都保住**（开头认盘符，结尾认是哪个库）。

    Windows 绝对路径里没有空格，在 Qt 的折行算法里是**一个不可折断的词**，
    `setWordWrap(True)` 对它有名字段无效 —— 实测一条 103 字符的路径让本页
    minimumSizeHint 停在 1027px，把主窗从 1000px 顶到 1081px、侧栏被榨到 56px，
    而且切回别的屏也不会恢复（splitter 存的是被撑大的那一份）。
    完整路径挂 tooltip（与 S5 判重表"路径（悬停看全长）"同一口径）。
    """
    fm = ref.fontMetrics()
    if fm.horizontalAdvance(path) <= _PATH_MAX_WIDTH:
        return path
    sep = max(path.rfind("/"), path.rfind("\\"))
    name = path[sep + 1:] if sep >= 0 else path
    if fm.horizontalAdvance(name) > _PATH_MAX_WIDTH:
        # 文件名本身就超预算：整条中段省略，至少两端还能看见
        return fm.elidedText(path, Qt.TextElideMode.ElideMiddle, _PATH_MAX_WIDTH)
    head = fm.elidedText(path[:sep + 1], Qt.TextElideMode.ElideMiddle,
                         _PATH_MAX_WIDTH - fm.horizontalAdvance(name))
    return head + name




class BackupPage(QWidget):
    """S6 备份与恢复向导页。三标签页布局。"""

    def __init__(self, ctx: AppContext) -> None:
        super().__init__()
        self.ctx = ctx
        self._init_ui()
        self.reload()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        tabs = QTabWidget()
        tabs.addTab(self._make_backup_tab(), "备份")
        tabs.addTab(self._make_restore_tab(), "恢复")
        tabs.addTab(self._make_migration_tab(), "迁移历史")
        layout.addWidget(tabs)

    def _make_backup_tab(self) -> QWidget:
        """备份标签页。"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(8, 8, 8, 8)

        info = QLabel("备份当前数据库。使用 sqlite3.Connection.backup()，WAL 模式安全拷贝。")
        info.setWordWrap(True)
        layout.addWidget(info)

        # 路径既允许折行、又要中段省略（见 _elided）：只做其中一件都压不住最低宽度
        self.lbl_current = QLabel("当前库：-")
        self.lbl_current.setWordWrap(True)
        layout.addWidget(self.lbl_current)

        self.action_row = ActionRow()
        self.btn_backup = QPushButton("创建备份")
        self.btn_backup.setObjectName("searchBtn")
        self.btn_backup.clicked.connect(self._create_backup)
        self.action_row.add_button(self.btn_backup)

        self.btn_backup_to = QPushButton("备份到...")
        self.btn_backup_to.clicked.connect(self._create_backup_to)
        self.action_row.add_button(self.btn_backup_to)

        self.btn_refresh_backups = QPushButton("刷新列表")
        self.btn_refresh_backups.clicked.connect(self._reload_backups)
        self.action_row.add_button(self.btn_refresh_backups)
        # 「当前库：\<路径>（结构版本 N）」那句本来贴在按钮上方，行末那根弹簧空着
        # （**ISSUES I121** ④）。它已经由 `_elided` 中段省略并挂了完整路径 tooltip，
        # 所以这一格只在**整句装得下**时才搬 —— 截第二刀会让 tooltip 之外的全文没处看。
        self.action_row.absorb(layout, self.lbl_current)
        layout.addWidget(self.action_row)

        backup_title = QLabel("已有备份：")
        backup_title.setObjectName("sectionTitle")
        layout.addWidget(backup_title)
        self.backup_table = QTableWidget()
        self.backup_table.setColumnCount(3)
        self.backup_table.setHorizontalHeaderLabels(["文件名", "版本", "修改时间"])
        # 「修改时间」显示 `2026-10-16 16:08:30Z`（定宽 20 字符，走 `status_service.format_ts`，
        # 界面唯一带标注出口 —— 整改计划第 7 条勾甲），按内容宽 + 内边距定宽。
        # 文件名走 Stretch：认盘符与尾巴靠 `_elided` 的那几条标签，不在表格里。
        set_table_columns(self.backup_table,
                          {1: 100, 2: 140 + CELL_PADDING_WIDTH}, stretch_col=0)
        self.backup_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.backup_table.setAlternatingRowColors(True)
        layout.addWidget(self.backup_table, 1)

        return widget

    def _make_restore_tab(self) -> QWidget:
        """恢复标签页：选包 = 在表里点一行，按之前就把"包里有什么、多大"摊开。

        这张表与「备份」页那张是**同一来源**（`list_backups()`，一次读、两处填）。原先这一页只能
        选**文件**，人得钻进 `backup-…\\` 目录里点那颗 `catalog.db` —— 而新备份包里还有
        `vectors.npy`，只回半个库的那条路必须从入口上就堵掉（**ISSUES I123** ①）。
        """
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(8, 8, 8, 8)

        info = QLabel("从备份恢复。恢复写到新数据根，绝不覆盖当前库。")
        info.setWordWrap(True)
        layout.addWidget(info)

        self._selected: Path | None = None
        self._selected_external = False
        self._described: dict | None = None
        self._backups: list[dict] = []

        backup_title = QLabel("已有备份：")
        backup_title.setObjectName("sectionTitle")
        layout.addWidget(backup_title)

        self.restore_table = QTableWidget()
        self.restore_table.setColumnCount(5)
        self.restore_table.setHorizontalHeaderLabels(
            ["文件名", "类型", "版本", "修改时间", "体积"])
        # 定宽按「这一列格式能产出的最宽读数 + 内边距 23」：类型「裸库」26 / 版本「v8」（列头 26）/
        # 修改时间 `2026-10-16 16:08:30Z` 140 / 体积最宽 `999.99 GB` 63。文件名吸收剩余宽度
        # （按视口运行时判，I121 ①甲）；装不下时全表横滚 —— D-040 的地板档降级，不另造形状。
        set_table_columns(self.restore_table,
                          {1: 26 + CELL_PADDING_WIDTH, 2: 100,
                           3: 140 + CELL_PADDING_WIDTH, 4: 63 + CELL_PADDING_WIDTH},
                          stretch_col=0)
        self.restore_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.restore_table.setAlternatingRowColors(True)
        self.restore_table.itemSelectionChanged.connect(self._on_pick)
        layout.addWidget(self.restore_table, 1)

        browse_row = QHBoxLayout()
        self.btn_browse_other = QPushButton("浏览其他位置…")
        self.btn_browse_other.clicked.connect(self._browse_other)
        browse_row.addWidget(self.btn_browse_other)
        browse_row.addStretch()
        layout.addLayout(browse_row)

        self.lbl_pick = QLabel("未选择备份")
        self.lbl_pick.setWordWrap(True)
        layout.addWidget(self.lbl_pick)

        self.lbl_contents = QLabel("")
        self.lbl_contents.setWordWrap(True)
        layout.addWidget(self.lbl_contents)

        target_row = QHBoxLayout()
        target_row.addWidget(QLabel("目标根："))
        self.ed_target = QLineEdit()
        self.ed_target.setPlaceholderText("一个空目录，恢复之后把它填给 --data-dir")
        self.ed_target.textChanged.connect(self._on_target_changed)
        target_row.addWidget(self.ed_target, 1)
        self.btn_pick_target = QPushButton("选目录…")
        self.btn_pick_target.clicked.connect(self._pick_target)
        target_row.addWidget(self.btn_pick_target)
        layout.addLayout(target_row)

        self.lbl_dest = QLabel("落点：（选中备份之后显示）")
        self.lbl_dest.setWordWrap(True)
        layout.addWidget(self.lbl_dest)

        self.btn_restore = QPushButton("恢复到新目录…")
        self.btn_restore.setObjectName("searchBtn")
        self.btn_restore.clicked.connect(self._restore_to_new_dir)
        self.btn_restore.setEnabled(False)
        layout.addWidget(self.btn_restore)

        self.lbl_restore_result = QLabel("")
        self.lbl_restore_result.setWordWrap(True)
        layout.addWidget(self.lbl_restore_result)

        return widget

    def _make_migration_tab(self) -> QWidget:
        """迁移历史标签页。"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(8, 8, 8, 8)

        info = QLabel("已应用的数据库迁移。从 db/migrations/ 文件名派生。")
        info.setWordWrap(True)
        layout.addWidget(info)

        self.migration_table = QTableWidget()
        self.migration_table.setColumnCount(3)
        self.migration_table.setHorizontalHeaderLabels(["序号", "迁移名", "已应用"])
        # 三列全部进列宽口径：col1 迁移名吸收剩余宽度，col0/col2 定宽 ——
        # 漏在 `set_table_columns` 外面的列停在 Qt 默认值，守卫也就看不见它们。
        set_table_columns(self.migration_table,
                          {0: 100, 2: 100}, stretch_col=1)
        self.migration_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.migration_table.setAlternatingRowColors(True)
        layout.addWidget(self.migration_table, 1)

        return widget

    def reload(self) -> None:
        """刷新全部标签页。"""
        self._reload_current_info()
        self._reload_backups()
        self._reload_migrations()

    def _reload_current_info(self) -> None:
        """显示当前库路径与版本。"""
        db_path = str(self.ctx.engine.path)
        self.lbl_current.setText(
            f"当前库：{_elided(db_path, self.lbl_current)}"
            f"（结构版本 {self.ctx.schema_version}）")
        self.lbl_current.setToolTip(db_path)
        # 路径与版本号都在这句里，改写完要重判一次它搬不搬进行末（**ISSUES I121** ④）。
        self.action_row.sync()

    def _reload_backups(self) -> None:
        """刷新备份 —— **两张表都从这里填**，同一个来源 `list_backups()`。

        恢复页那张表比备份页多两列（类型 / 体积），两列都来自 `describe_backup()`：只读清单与
        `stat`、不碰 `catalog.db`，所以刷新不增加开库开销。刷新过程中 `blockSignals`，
        否则 `setRowCount` 会先清空选中、把「选中内容」那几行刷成空态再填回来。
        """
        backups = self.ctx.backup.list_backups()
        self._backups = backups

        self.backup_table.setRowCount(len(backups))
        self.restore_table.blockSignals(True)
        self.restore_table.setRowCount(len(backups))
        for i, b in enumerate(backups):
            self.backup_table.setItem(i, 0, QTableWidgetItem(b["path"].name))
            self.backup_table.setItem(i, 1, QTableWidgetItem(f"v{b['version']}"))
            self.backup_table.setItem(i, 2, QTableWidgetItem(format_ts(b["mtime"])))

            name_item = QTableWidgetItem(b["path"].name)
            # 名字列可截断（ELIDABLE_COLUMNS），截了必须能悬停回读全文
            name_item.setToolTip(b["path"].name)
            self.restore_table.setItem(i, 0, name_item)
            self.restore_table.setItem(
                i, 1, QTableWidgetItem("包" if b["kind"] == "dir" else "裸库"))
            self.restore_table.setItem(i, 2, QTableWidgetItem(f"v{b['version']}"))
            self.restore_table.setItem(i, 3, QTableWidgetItem(format_ts(b["mtime"])))
            self.restore_table.setItem(i, 4, self._size_item(b["path"]))
        # 选中的那一行在刷新之后要还在（否则每按一次「刷新列表」都得重选一遍）；
        # 外部位置选来的包不在表里，刷新不动它。
        row = next((i for i, b in enumerate(backups)
                    if b["path"] == self._selected), None)
        if not self._selected_external:
            if row is None:
                self._selected = None
            else:
                self.restore_table.selectRow(row)
        self.restore_table.blockSignals(False)
        self._refresh_selection_texts()

    def _size_item(self, path: Path) -> QTableWidgetItem:
        """体积列：给人看的是 `format_bytes` 的口径，字节原值挂 tooltip。

        读不出来（清单坏了 / 文件半路没了）就写 `-`、把原因挂 tooltip —— 这一格不许因为
        一个坏包把整张表刷不出来，也不许假装它是 0 字节。
        """
        try:
            info = backup_service.BackupService.describe_backup(path)
        except (OSError, ValueError) as exc:
            item = QTableWidgetItem("-")
            item.setToolTip(str(exc))
            return item
        item = QTableWidgetItem(format_bytes(info["total_bytes"]))
        item.setToolTip(" ＋ ".join(f"{m['name']} {m['bytes']:,} B"
                                   for m in info["members"]))
        return item

    def _on_pick(self) -> None:
        """表里选中的那一行 ⇒ 要恢复的那个包。"""
        rows = self.restore_table.selectionModel().selectedRows()
        entry = self._backups[rows[0].row()] if rows and rows[0].row() < len(self._backups) else None
        self._selected = entry["path"] if entry is not None else None
        self._selected_external = False
        self._refresh_selection_texts()

    def _refresh_selection_texts(self) -> None:
        """把选中项摊开：选了哪个、里面有什么、恢复之后落在哪。"""
        if self._selected is None:
            self._described = None
            self.lbl_pick.setText("未选择备份")
            self.lbl_pick.setToolTip("")
            self.lbl_contents.setText("")
            self.lbl_contents.setToolTip("")
        else:
            full = str(self._selected)
            self.lbl_pick.setText(f"已选择：{_elided(full, self.lbl_pick)}")
            self.lbl_pick.setToolTip(full)
            self._refresh_contents()
        self._refresh_dest()
        self.btn_restore.setEnabled(
            self._selected is not None and bool(self.ed_target.text().strip()))

    def _refresh_contents(self) -> None:
        """「选中内容」那一行 —— 缺的那一半必须在**按之前**看得见。"""
        try:
            described = backup_service.BackupService.describe_backup(self._selected)
        except (OSError, ValueError) as exc:
            self._described = None
            # 报错原文里带着一条绝对路径，它会把这句标签顶宽 —— 中段省略 + 悬停回读全文
            # （选了一个不存在的文件、或外部拷来的包清单坏了，都是这条兜底在做）。
            detail = str(exc)
            self.lbl_contents.setText(f"读不出这个备份里有什么：{_elided(detail, self.lbl_contents)}")
            self.lbl_contents.setToolTip(detail)
            return
        self._described = described
        if not described["members"]:
            self.lbl_contents.setText("选中内容：（这个包里没有可恢复的东西）")
            self.lbl_contents.setToolTip("")
            return
        if described["kind"] == "file":
            note = "旧格式裸库：只有库，向量文件回不来"
        elif described["has_manifest"]:
            note = "清单在场 ⇒ 恢复时逐个按这份清单核对字节数"
        else:
            note = "没有清单的老包 ⇒ 有什么恢复什么"
        self.lbl_contents.setText(
            "选中内容：" + " ＋ ".join(f"{m['name']} {format_bytes(m['bytes'])}"
                                      for m in described["members"]) + f"（{note}）")
        self.lbl_contents.setToolTip(
            " ＋ ".join(f"{m['name']} {m['bytes']:,} B" for m in described["members"]))

    def _refresh_dest(self) -> None:
        """「落点」那一行：路径由 `AppPaths` 唯一算，与恢复时摆放的是同一份映射。"""
        target = self.ed_target.text().strip()
        if self._selected is None or not target:
            self.lbl_dest.setText("落点：（" + ("选中备份" if self._selected is None
                                              else "选目标根") + "之后显示）")
            self.lbl_dest.setToolTip("")
            return
        destinations = backup_service.BackupService.member_destinations(AppPaths.resolve(target))
        names = ([m["name"] for m in self._described["members"]]
                 if self._described else [backup_service.DB_MEMBER])
        full = " ＋ ".join(str(destinations[name]) for name in names if name in destinations)
        self.lbl_dest.setText(f"落点：{_elided(full, self.lbl_dest)}")
        self.lbl_dest.setToolTip(full)

    def _on_target_changed(self) -> None:
        self._refresh_dest()
        self.btn_restore.setEnabled(
            self._selected is not None and bool(self.ed_target.text().strip()))

    def _pick_target(self) -> None:
        target = QFileDialog.getExistingDirectory(self, "选择恢复目标目录")
        if target:
            self.ed_target.setText(target)

    def _browse_other(self) -> None:
        """备份在别的位置（移动硬盘 / 另一台机器拷来）时的入口。

        对话框收两种形状：包里的 `manifest.json`（点它就等于点中了那个包）与旧格式裸 `.db`。
        「点包里的 `catalog.db`」也走同一条路 —— 服务层 `as_package()` 把它归一化成整包，
        所以三种点法恢复回来的东西一样多。
        """
        path, _ = QFileDialog.getOpenFileName(
            self, "选择备份包或库文件", str(self.ctx.paths.backups_dir),
            f"备份包 ({backup_service.MANIFEST_NAME});;数据库文件 (*.db);;所有文件 (*)",
            options=QFileDialog.Option.DontUseNativeDialog)
        if not path:
            return
        chosen = backup_service.as_package(Path(path))
        row = next((i for i, b in enumerate(self._backups) if b["path"] == chosen), None)
        if row is not None:
            self.restore_table.selectRow(row)      # 与表里那一行合一，不制造两个选中态
            return
        self.restore_table.blockSignals(True)
        self.restore_table.clearSelection()
        self.restore_table.blockSignals(False)
        self._selected = chosen
        self._selected_external = True
        self._refresh_selection_texts()

    def _restore_to_new_dir(self) -> None:
        """恢复到新目录。目标根先选好再按 —— 这次不再由按钮弹目录对话框。"""
        if self._selected is None:
            return
        target = self.ed_target.text().strip()
        if not target:
            return
        try:
            new_db = self.ctx.backup.restore_to_new_dir(self._selected, target)
            shown = _elided(str(new_db), self.lbl_restore_result)
            self.lbl_restore_result.setText(
                f"恢复成功：{shown}\n"
                f"注意：当前应用仍在使用旧库。要使用新库，请重启应用并指定新数据目录。")
            self.lbl_restore_result.setToolTip(str(new_db))
            QMessageBox.information(
                self, "恢复成功",
                f"数据库已恢复到：\n{new_db}\n\n"
                f"当前应用仍在使用旧库。要使用新库，请重启应用并指定新数据目录。")
        except Exception as exc:
            # 原因里十有八九带着一条绝对路径（「目标根里已经有 vectors.npy（文件）：C:\…」），
            # 塞进这句标签会把它顶宽 —— 全文给弹窗与悬停，标签只留一句定长的话。
            detail = str(exc)
            self.lbl_restore_result.setText("恢复失败：目标根没有写入任何东西（悬停看原因）。")
            self.lbl_restore_result.setToolTip(detail)
            QMessageBox.critical(self, "恢复失败", f"恢复时出错：\n{detail}")

    def _reload_migrations(self) -> None:
        """刷新迁移历史。"""
        migrations = self.ctx.backup.list_migrations()
        self.migration_table.setRowCount(len(migrations))
        for i, m in enumerate(migrations):
            self.migration_table.setItem(i, 0, QTableWidgetItem(str(m["order"])))
            self.migration_table.setItem(i, 1, QTableWidgetItem(m["name"]))
            self.migration_table.setItem(i, 2, QTableWidgetItem("是" if m["applied"] else "否"))

    def _create_backup(self) -> None:
        """创建备份到默认目录。"""
        try:
            path = self.ctx.backup.create_backup()
            QMessageBox.information(self, "备份成功", f"备份已创建：\n{path}")
            self._reload_backups()
        except Exception as exc:
            QMessageBox.critical(self, "备份失败", f"创建备份时出错：\n{exc}")

    def _create_backup_to(self) -> None:
        """创建备份到用户选择的目录。"""
        target = QFileDialog.getExistingDirectory(self, "选择备份目录")
        if not target:
            return
        try:
            path = self.ctx.backup.create_backup(target)
            QMessageBox.information(self, "备份成功", f"备份已创建：\n{path}")
            self._reload_backups()
        except Exception as exc:
            QMessageBox.critical(self, "备份失败", f"创建备份时出错：\n{exc}")
