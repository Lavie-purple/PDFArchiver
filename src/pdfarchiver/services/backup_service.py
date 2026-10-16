"""备份与恢复服务 —— S6 的后端。

备份口径唯一：`sqlite3.Connection.backup()`（WAL 模式禁止文件拷贝）。
备份文件名必须带版本号（`catalog-YYYYMMDD-HHMMSS-v版本.db`），否则恢复时不知道跑哪个迁移。

恢复必须写到新目录，不覆盖当前库；用户确认后再切换成新库。
"""
from __future__ import annotations

import logging
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from pdfarchiver.config.paths import AppPaths
from pdfarchiver.db.engine import Engine
from pdfarchiver.db.migrate import current_version, discover

log = logging.getLogger("pdfarchiver.backup")


class BackupService:
    """备份与恢复：sqlite3.Connection.backup() 是唯一合法路径。"""

    def __init__(self, paths: AppPaths, engine: Engine) -> None:
        self.paths = paths
        self.engine = engine

    def create_backup(self, target_dir: str | Path | None = None) -> Path:
        """备份当前库到指定目录（默认 backups_dir）。返回备份文件路径。

        文件名格式：`catalog-YYYYMMDD-HHMMSS-v版本.db`。
        使用 sqlite3.Connection.backup()，WAL 模式下文件拷贝不可用。
        """
        if target_dir is None:
            target_dir = self.paths.backups_dir
        target_dir = Path(target_dir)
        target_dir.mkdir(parents=True, exist_ok=True)

        # 取当前版本号
        conn = self.engine.thread_connection()
        version = current_version(conn)

        # 生成文件名
        now = datetime.now(timezone.utc)
        timestamp = now.strftime("%Y%m%d-%H%M%S")
        filename = f"catalog-{timestamp}-v{version}.db"
        backup_path = target_dir / filename

        # 执行备份（sqlite3.Connection.backup()）
        src_conn = sqlite3.connect(str(self.engine.path))
        try:
            dst_conn = sqlite3.connect(str(backup_path))
            try:
                src_conn.backup(dst_conn)
            finally:
                dst_conn.close()
        finally:
            src_conn.close()

        log.info("备份完成：%s", backup_path)
        return backup_path

    def list_backups(self, backup_dir: str | Path | None = None) -> list[dict]:
        """列出指定目录下的全部备份文件。返回 [{"path": Path, "version": int, "mtime": int}, ...]。"""
        if backup_dir is None:
            backup_dir = self.paths.backups_dir
        backup_dir = Path(backup_dir)
        if not backup_dir.exists():
            return []

        backups = []
        for p in backup_dir.glob("catalog-*.db"):
            # 从文件名解析版本号
            parts = p.stem.split("-")
            version = None
            for part in parts:
                if part.startswith("v") and part[1:].isdigit():
                    version = int(part[1:])
                    break
            if version is not None:
                backups.append({
                    "path": p,
                    "version": version,
                    "mtime": int(p.stat().st_mtime),
                })
        # 按修改时间倒序
        backups.sort(key=lambda b: b["mtime"], reverse=True)
        return backups

    def restore_to_new_dir(self, backup_path: str | Path,
                           target_dir: str | Path) -> Path:
        """把备份恢复到新目录（不覆盖当前库）。返回新库路径。

        用户确认后，由调用方切换 engine 连接（本服务不自动切换）。
        """
        backup_path = Path(backup_path)
        target_dir = Path(target_dir)
        target_dir.mkdir(parents=True, exist_ok=True)

        new_db = target_dir / "catalog.db"
        if new_db.exists():
            raise FileExistsError(f"目标库已存在：{new_db}")

        # 拷贝备份文件到新位置
        shutil.copy2(str(backup_path), str(new_db))
        log.info("恢复到新目录：%s", new_db)
        return new_db

    def list_migrations(self) -> list[dict]:
        """列出已应用的迁移。从 db/migrations/ 文件名派生（无持久化表）。

        返回 [{"order": int, "name": str, "applied": bool}, ...]。
        """
        migrations_dir = self.paths.root.parent / "src" / "pdfarchiver" / "db" / "migrations"
        if not migrations_dir.exists():
            # 尝试从包内找
            import pdfarchiver.db.migrations as m
            migrations_dir = Path(m.__file__).parent

        all_migrations = discover(migrations_dir)
        conn = self.engine.thread_connection()
        current = current_version(conn)

        result = []
        for m in all_migrations:
            result.append({
                "order": m.order,
                "name": m.label,
                "applied": m.order <= current,
            })
        return result
