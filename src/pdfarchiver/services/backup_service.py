"""备份与恢复服务 —— S6 的后端。

备份口径唯一：`sqlite3.Connection.backup()`（WAL 模式禁止文件拷贝）。
备份包是一个**目录**（`backup-YYYYMMDD-HHMMSS-v版本/`），内含 `catalog.db` + `settings.json`
（如果存在）。旧格式（单个 `.db` 文件）仍然可读，恢复时自动识别。

恢复必须写到新目录，不覆盖当前库；恢复前跑 `PRAGMA integrity_check`，坏库当场拒绝。
用户确认后再切换成新库。
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
        """备份当前库 + 设置到指定目录（默认 backups_dir）。返回备份**目录**路径。

        目录名格式：`backup-YYYYMMDD-HHMMSS-v版本/`，内含：
        - `catalog.db`（sqlite3.Connection.backup()）
        - `settings.json`（如果存在，原样拷贝）

        旧格式（单个 `.db` 文件）不再产出，但仍然可读（`restore_to_new_dir` 自动识别）。
        """
        if target_dir is None:
            target_dir = self.paths.backups_dir
        target_dir = Path(target_dir)
        target_dir.mkdir(parents=True, exist_ok=True)

        conn = self.engine.thread_connection()
        version = current_version(conn)

        now = datetime.now(timezone.utc)
        timestamp = now.strftime("%Y%m%d-%H%M%S")
        dir_name = f"backup-{timestamp}-v{version}"
        backup_dir = target_dir / dir_name
        backup_dir.mkdir(parents=True, exist_ok=True)

        db_path = backup_dir / "catalog.db"
        src_conn = sqlite3.connect(str(self.engine.path))
        try:
            dst_conn = sqlite3.connect(str(db_path))
            try:
                src_conn.backup(dst_conn)
            finally:
                dst_conn.close()
        finally:
            src_conn.close()

        settings_src = self.paths.settings_file
        if settings_src.exists():
            shutil.copy2(str(settings_src), str(backup_dir / "settings.json"))

        log.info("备份完成：%s", backup_dir)
        return backup_dir

    def list_backups(self, backup_dir: str | Path | None = None) -> list[dict]:
        """列出指定目录下的全部备份。返回 [{"path": Path, "version": int, "mtime": int,
        "kind": "dir"|"file"}, ...]。

        同时识别新格式（目录）与旧格式（单个 `.db` 文件）。
        """
        if backup_dir is None:
            backup_dir = self.paths.backups_dir
        backup_dir = Path(backup_dir)
        if not backup_dir.exists():
            return []

        backups = []

        for d in backup_dir.glob("backup-*"):
            if d.is_dir():
                version = _parse_version_from_stem(d.name)
                if version is not None:
                    backups.append({
                        "path": d,
                        "version": version,
                        "mtime": int(d.stat().st_mtime),
                        "kind": "dir",
                    })

        for p in backup_dir.glob("catalog-*.db"):
            version = _parse_version_from_stem(p.stem)
            if version is not None:
                backups.append({
                    "path": p,
                    "version": version,
                    "mtime": int(p.stat().st_mtime),
                    "kind": "file",
                })

        backups.sort(key=lambda b: b["mtime"], reverse=True)
        return backups

    def restore_to_new_dir(self, backup_path: str | Path,
                           target_dir: str | Path) -> Path:
        """把备份恢复到新目录（不覆盖当前库）。返回新库路径。

        自动识别新旧格式：
        - 新格式（目录）：从 `backup_dir/catalog.db` 拷贝，同时恢复 `settings.json`（如果存在）
        - 旧格式（单个 `.db` 文件）：直接拷贝

        恢复后跑 `PRAGMA integrity_check`，失败则删除已拷贝的文件并抛 `ValueError`。
        用户确认后，由调用方切换 engine 连接（本服务不自动切换）。
        """
        backup_path = Path(backup_path)
        target_dir = Path(target_dir)
        target_dir.mkdir(parents=True, exist_ok=True)

        new_db = target_dir / "catalog.db"
        if new_db.exists():
            raise FileExistsError(f"目标库已存在：{new_db}")

        if backup_path.is_dir():
            src_db = backup_path / "catalog.db"
            if not src_db.exists():
                raise FileNotFoundError(f"备份目录里没有 catalog.db：{backup_path}")
            shutil.copy2(str(src_db), str(new_db))

            src_settings = backup_path / "settings.json"
            if src_settings.exists():
                dst_config = target_dir / "config"
                dst_config.mkdir(parents=True, exist_ok=True)
                shutil.copy2(str(src_settings), str(dst_config / "settings.json"))
        else:
            shutil.copy2(str(backup_path), str(new_db))

        restored_engine = Engine(new_db)
        try:
            check = restored_engine.integrity_check()
        except Exception as exc:
            del restored_engine
            import gc
            gc.collect()
            import time
            for _ in range(5):
                try:
                    new_db.unlink(missing_ok=True)
                    break
                except PermissionError:
                    time.sleep(0.2)
            raise ValueError(
                f"恢复出来的库无法打开（{exc}）。已删除残留文件。") from exc
        restored_engine.close_thread_connection()
        del restored_engine

        if check != "ok":
            import gc
            gc.collect()
            import time
            for _ in range(5):
                try:
                    new_db.unlink(missing_ok=True)
                    break
                except PermissionError:
                    time.sleep(0.2)
            raise ValueError(
                f"恢复出来的库完整性检查失败：{check}。已删除残留文件。")

        log.info("恢复到新目录：%s", new_db)
        return new_db

    def list_migrations(self) -> list[dict]:
        """列出已应用的迁移。从 db/migrations/ 文件名派生（无持久化表）。

        返回 [{"order": int, "name": str, "applied": bool}, ...]。
        """
        migrations_dir = self.paths.root.parent / "src" / "pdfarchiver" / "db" / "migrations"
        if not migrations_dir.exists():
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


def _parse_version_from_stem(stem: str) -> int | None:
    """从 `backup-YYYYMMDD-HHMMSS-v版本` 或 `catalog-YYYYMMDD-HHMMSS-v版本` 里提取版本号。"""
    for part in stem.split("-"):
        if part.startswith("v") and part[1:].isdigit():
            return int(part[1:])
    return None
