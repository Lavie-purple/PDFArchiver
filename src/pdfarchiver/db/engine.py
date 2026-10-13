"""连接工厂 —— WAL、busy_timeout、每线程独立连接（docs/ARCHITECTURE 三）。

三条来自实测的规矩，不是风格：
- `sqlite3.Connection` 默认 ``check_same_thread=True``，**共享连接给 worker 会直接抛**，
  所以这里"每次要连接就新建一条"，跨线程复用一律由调用方（worker）自己持有自己的连接。
- WAL 是持久设置，写进库文件头，建库时设一次即可（p1 实测：写 2 万行期间并发读 12 次不出错）。
- 备份**只走 ``Connection.backup()``**。复制 .db 文件在 WAL 下会备到不一致状态（docs/DATABASE 六）。
"""
from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

DEFAULT_BUSY_TIMEOUT_MS = 5000  # 与 config/settings.py 同源，改一边就要改另一边


class DatabaseError(RuntimeError):
    """所有对上层暴露的数据库故障。消息里必须带原始 sqlite3 文本 —— 只报"失败了"没法诊断。"""

    def __init__(self, what: str, exc: BaseException, *, db: str = "") -> None:
        super().__init__(f"{what}｜{type(exc).__name__}: {exc}" + (f"｜库={db}" if db else ""))
        self.cause = exc
        self.what = what


class Engine:
    """一个库文件 = 一个 Engine。连接是它的产物，不是它的状态。"""

    def __init__(self, db_path: str | Path, *, busy_timeout_ms: int = DEFAULT_BUSY_TIMEOUT_MS,
                 foreign_keys: bool = True) -> None:
        self.path = Path(db_path)
        self.busy_timeout_ms = busy_timeout_ms
        self.foreign_keys = foreign_keys
        self._local = threading.local()
        self.in_memory = self.path.as_posix() == ":memory:"

    def connect(self) -> sqlite3.Connection:
        """新建一条连接。内存库返回的连接每次都是空库，只给单测用。"""
        try:
            if not self.in_memory:
                self.path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(str(self.path), timeout=self.busy_timeout_ms / 1000)
            conn.row_factory = sqlite3.Row
            conn.execute(f"PRAGMA busy_timeout={self.busy_timeout_ms}")
            conn.execute("PRAGMA foreign_keys=ON")
            if not self.in_memory:
                conn.execute("PRAGMA journal_mode=WAL")
            return conn
        except sqlite3.Error as exc:
            raise DatabaseError("打开数据库失败", exc, db=str(self.path)) from exc

    def thread_connection(self) -> sqlite3.Connection:
        """本线程复用一条连接；主线程 / UI 用它，worker 应当各调一次 connect()。"""
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = self.connect()
            self._local.conn = conn
        return conn

    def close_thread_connection(self) -> None:
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            conn.close()
            self._local.conn = None

    def integrity_check(self) -> str:
        """返回 'ok' 或第一条损坏描述。绝不抛 —— 损坏库要能被读出来才能上报给人。"""
        conn = self.connect()
        try:
            rows = conn.execute("PRAGMA integrity_check").fetchall()
        finally:
            conn.close()
        return rows[0][0] if rows else "no result"

    def snapshot_to(self, dest: str | Path) -> Path:
        """Backup API 一致性快照到 dest。空库也允许（迁移前快照的是"当前状态"）。"""
        dest = Path(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        src = self.connect()
        dst = sqlite3.connect(str(dest))
        try:
            src.backup(dst)
        except sqlite3.Error as exc:
            raise DatabaseError("备份快照失败", exc, db=str(self.path)) from exc
        finally:
            dst.close()
            src.close()
        return dest

    @contextmanager
    def transaction(self, conn: sqlite3.Connection, *, on_error: str = "") -> Iterator[None]:
        """要么全提交要么全回滚。回滚时把原始 sqlite 文本留在异常里。"""
        try:
            yield
            conn.commit()
        except sqlite3.Error as exc:
            conn.rollback()
            raise DatabaseError(on_error or "事务回滚", exc, db=str(self.path)) from exc
        except Exception:
            conn.rollback()
            raise
