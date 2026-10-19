"""监测根目录读写。唯一性同样走 `COLLATE NOCASE` 唯一索引（D-005）。

SPEC 3.1 要"添加、暂停、恢复、移除"和"配置排除目录与排除规则"，全部落在这张表上；
**移除监测根只删配置、绝不删文档主记录、更不碰磁盘** —— 用户把一个根从监测列表里拿掉，
不代表他要丢掉这 8,000 条记录和上面的分类标注。
"""
from __future__ import annotations

import json

from pdfarchiver.db.engine import Engine
from pdfarchiver.db.models import MonitoredRoot, now_ts
from pdfarchiver.fs.identity import identity_key

_COLS = "id, root_path, root_key, label, enabled, exclude_globs, last_full_scan_at, last_scan_error, created_at, updated_at"


class RootRepository:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def add(self, root_path: str, root_key: str, label: str | None = None,
            exclude_globs: list[str] | None = None) -> MonitoredRoot:
        conn = self.engine.thread_connection()
        ts = now_ts()
        globs = json.dumps(exclude_globs or [], ensure_ascii=False)
        # ISSUES I89 甲：库里子树查询只认 identity_key 口径（`c:/users/lavie`），原生 Windows
        # 写法（`C:\Users\lavie`）拼出的 LIKE 前缀一条都命中不了。在源头归一一次，让"传错根键"
        # 这件事不可能发生 —— 而不是靠每个调用方各自记得调 identity_key（全站一处，不是两处）。
        root_key = identity_key(root_key)
        with self.engine.transaction(conn, on_error=f"添加监测根 {root_path} 失败"):
            conn.execute(
                "INSERT INTO monitored_roots(root_path, root_key, label, enabled, exclude_globs,"
                " created_at, updated_at) VALUES(?,?,?,?,?,?,?) ON CONFLICT(root_key) DO UPDATE SET"
                " root_path=excluded.root_path, label=COALESCE(excluded.label, monitored_roots.label),"
                " exclude_globs=excluded.exclude_globs, enabled=1,"
                " last_scan_error=NULL, updated_at=excluded.updated_at",
                (root_path, root_key, label, 1, globs, ts, ts))
        return self.by_key(root_key)  # type: ignore[return-value]

    def by_key(self, root_key: str) -> MonitoredRoot | None:
        row = self.engine.thread_connection().execute(
            f"SELECT {_COLS} FROM monitored_roots WHERE root_key=?", (root_key,)).fetchone()
        return MonitoredRoot(**dict(row)) if row else None

    def list(self) -> list[MonitoredRoot]:
        rows = self.engine.thread_connection().execute(
            f"SELECT {_COLS} FROM monitored_roots ORDER BY root_path COLLATE NOCASE").fetchall()
        return [MonitoredRoot(**dict(r)) for r in rows]

    def list_enabled(self) -> list[MonitoredRoot]:
        rows = self.engine.thread_connection().execute(
            f"SELECT {_COLS} FROM monitored_roots WHERE enabled=1 ORDER BY root_path COLLATE NOCASE").fetchall()
        return [MonitoredRoot(**dict(r)) for r in rows]

    def set_enabled(self, root_key: str, enabled: bool) -> bool:
        conn = self.engine.thread_connection()
        with self.engine.transaction(conn, on_error="切换监测根状态失败"):
            cur = conn.execute("UPDATE monitored_roots SET enabled=?, updated_at=? WHERE root_key=?",
                               (1 if enabled else 0, now_ts(), root_key))
        return cur.rowcount > 0

    def set_exclude_globs(self, root_key: str, globs: list[str]) -> bool:
        conn = self.engine.thread_connection()
        with self.engine.transaction(conn, on_error=f"写入排除规则失败 {root_key}"):
            cur = conn.execute("UPDATE monitored_roots SET exclude_globs=?, updated_at=? WHERE root_key=?",
                               (json.dumps(globs, ensure_ascii=False), now_ts(), root_key))
        return cur.rowcount > 0

    def mark_full_scan(self, root_key: str, *, error: str | None = None) -> None:
        """记本次全量扫描的时刻与错误。`error=None` 时**清空老错误** ——
        留着上一次的失败信息会让人以为现在还是坏的（同一个概念两个口径）。"""
        conn = self.engine.thread_connection()
        with self.engine.transaction(conn, on_error=f"记录扫描结果失败 {root_key}"):
            cur = conn.execute(
                "UPDATE monitored_roots SET last_full_scan_at=?, last_scan_error=?, updated_at=?"
                " WHERE root_key=?", (now_ts(), error, now_ts(), root_key))
            if cur.rowcount == 0:
                raise ValueError(f"监测根不存在，无法记录扫描结果：{root_key}")

    def remove(self, root_key: str) -> bool:
        """只删监测配置，不动任何用户文件（SPEC 3.6 默认不动磁盘），也不删文档主记录。"""
        conn = self.engine.thread_connection()
        with self.engine.transaction(conn, on_error="移除监测根失败"):
            cur = conn.execute("DELETE FROM monitored_roots WHERE root_key=?", (root_key,))
        return cur.rowcount > 0

    def count(self) -> int:
        return self.engine.thread_connection().execute("SELECT count(*) FROM monitored_roots").fetchone()[0]
