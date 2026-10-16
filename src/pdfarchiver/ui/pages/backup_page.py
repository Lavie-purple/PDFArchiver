"""S6 · 备份与恢复向导 —— 三标签页：备份 | 恢复 | 迁移历史。

备份口径唯一：`sqlite3.Connection.backup()`（WAL 模式禁止文件拷贝）。
备份文件名必须带版本号（`catalog-YYYYMMDD-HHMMSS-v版本.db`）。
恢复必须写到新目录，不覆盖当前库。
迁移历史从 `db/migrations/` 文件名派生（无持久化表）。
"""
from __future__ import annotations

import logging
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
                                QTableWidget, QTableWidgetItem, QGroupBox,
                                QTabWidget, QFileDialog, QMessageBox, QTextEdit)

from pdfarchiver.services.bootstrap import AppContext
from pdfarchiver.services.status_service import format_ts
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

        btn_row = QHBoxLayout()
        self.btn_backup = QPushButton("创建备份")
        self.btn_backup.setObjectName("searchBtn")
        self.btn_backup.clicked.connect(self._create_backup)
        btn_row.addWidget(self.btn_backup)

        self.btn_backup_to = QPushButton("备份到...")
        self.btn_backup_to.clicked.connect(self._create_backup_to)
        btn_row.addWidget(self.btn_backup_to)

        self.btn_refresh_backups = QPushButton("刷新列表")
        self.btn_refresh_backups.clicked.connect(self._reload_backups)
        btn_row.addWidget(self.btn_refresh_backups)
        btn_row.addStretch()
        layout.addLayout(btn_row)

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
        """恢复标签页。"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(8, 8, 8, 8)

        info = QLabel("从备份恢复。恢复必须写到新目录，不覆盖当前库。")
        info.setWordWrap(True)
        layout.addWidget(info)

        btn_row = QHBoxLayout()
        self.btn_select_backup = QPushButton("选择备份文件")
        self.btn_select_backup.clicked.connect(self._select_backup)
        btn_row.addWidget(self.btn_select_backup)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        self.lbl_selected = QLabel("未选择备份文件")
        self.lbl_selected.setWordWrap(True)
        layout.addWidget(self.lbl_selected)

        self.btn_restore = QPushButton("恢复到新目录...")
        self.btn_restore.setObjectName("searchBtn")
        self.btn_restore.clicked.connect(self._restore_to_new_dir)
        self.btn_restore.setEnabled(False)
        layout.addWidget(self.btn_restore)

        self.lbl_restore_result = QLabel("")
        self.lbl_restore_result.setWordWrap(True)
        layout.addWidget(self.lbl_restore_result)

        layout.addStretch()
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

    def _reload_backups(self) -> None:
        """刷新备份列表。"""
        backups = self.ctx.backup.list_backups()
        self.backup_table.setRowCount(len(backups))
        for i, b in enumerate(backups):
            self.backup_table.setItem(i, 0, QTableWidgetItem(b["path"].name))
            self.backup_table.setItem(i, 1, QTableWidgetItem(f"v{b['version']}"))
            mtime = format_ts(b["mtime"])
            self.backup_table.setItem(i, 2, QTableWidgetItem(mtime))

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

    def _select_backup(self) -> None:
        """选择备份文件。"""
        path, _ = QFileDialog.getOpenFileName(
            self, "选择备份文件", str(self.ctx.paths.backups_dir),
            "数据库文件 (*.db)")
        if not path:
            return
        self._selected_backup = path
        self.lbl_selected.setText(f"已选择：{_elided(path, self.lbl_selected)}")
        self.lbl_selected.setToolTip(path)
        self.btn_restore.setEnabled(True)

    def _restore_to_new_dir(self) -> None:
        """恢复到新目录。"""
        if not hasattr(self, "_selected_backup"):
            return
        target = QFileDialog.getExistingDirectory(self, "选择恢复目标目录")
        if not target:
            return
        try:
            new_db = self.ctx.backup.restore_to_new_dir(self._selected_backup, target)
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
            QMessageBox.critical(self, "恢复失败", f"恢复时出错：\n{exc}")
