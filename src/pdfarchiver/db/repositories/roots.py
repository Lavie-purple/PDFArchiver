"""监测根目录读写。唯一性同样走 `COLLATE NOCASE` 唯一索引（D-005）。"""
from __future__ import annotations

from pdfarchiver.db.engine import Engine
from pdfarchiver.db.models import MonitoredRoot, now_ts


class RootRepository:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def add(self, root_path: str, root_key: str, label: str | None = None) -> MonitoredRoot:
        conn = self.engine.thread_connection()
        ts = now_ts()
        with self.engine.transaction(conn, on_error=f"添加监测根 {root_path} 失败"):
            conn.execute(
                "INSERT INTO monitored_roots(root_path, root_key, label, enabled, created_at, updated_at)"
                " VALUES(?,?,?,?,?,?) ON CONFLICT(root_key) DO UPDATE SET"
                " root_path=excluded.root_path, label=COALESCE(excluded.label, monitored_roots.label),"
                " enabled=1, updated_at=excluded.updated_at",
                (root_path, root_key, label, 1, ts, ts))
        row = conn.execute("SELECT id,root_path,root_key,label,enabled,exclude_globs,"
                           "last_full_scan_at,created_at,updated_at FROM monitored_roots WHERE root_key=?",
                           (root_key,)).fetchone()
        return MonitoredRoot(**dict(row))

    def list(self) -> list[MonitoredRoot]:
        rows = self.engine.thread_connection().execute(
            "SELECT id,root_path,root_key,label,enabled,exclude_globs,last_full_scan_at,"
            "created_at,updated_at FROM monitored_roots ORDER BY root_path COLLATE NOCASE").fetchall()
        return [MonitoredRoot(**dict(r)) for r in rows]

    def set_enabled(self, root_key: str, enabled: bool) -> bool:
        conn = self.engine.thread_connection()
        with self.engine.transaction(conn, on_error="切换监测根状态失败"):
            cur = conn.execute("UPDATE monitored_roots SET enabled=?, updated_at=? WHERE root_key=?",
                               (1 if enabled else 0, now_ts(), root_key))
        return cur.rowcount > 0

    def remove(self, root_key: str) -> bool:
        """只删监测配置，不动任何用户文件（SPEC 3.6 默认不动磁盘）。"""
        conn = self.engine.thread_connection()
        with self.engine.transaction(conn, on_error="移除监测根失败"):
            cur = conn.execute("DELETE FROM monitored_roots WHERE root_key=?", (root_key,))
        return cur.rowcount > 0

    def count(self) -> int:
        return self.engine.thread_connection().execute("SELECT count(*) FROM monitored_roots").fetchone()[0]
