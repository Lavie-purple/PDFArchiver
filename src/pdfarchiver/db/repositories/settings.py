"""`app_settings` 读写 —— 只放**应用内部状态**（列宽、上次阅读位置、界面记忆）。

用户配置的唯一口径仍然是 `config/settings.json`（见 `config/settings.py`）。
同一个概念不许有两个存放处，所以这个类明确拒绝冒充设置管理器：
它的键由代码内部产生，不出现在 settings.json 里，也不受 settings.json 的校验管。
"""
from __future__ import annotations

import json
import logging
from typing import Any

from pdfarchiver.db.engine import Engine
from pdfarchiver.db.models import now_ts

log = logging.getLogger("pdfarchiver.db.settings")


class SettingsRepository:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def set(self, key: str, value: Any, *, kind: str = "ui") -> None:
        """值一律 JSON 编码存放 —— 不偷偷把 str 当裸文本写进列里（读回来类型会不一致）。"""
        conn = self.engine.thread_connection()
        with self.engine.transaction(conn, on_error=f"写入应用状态 {key} 失败"):
            conn.execute(
                "INSERT INTO app_settings(key, value_json, kind, updated_at) VALUES(?,?,?,?)"
                " ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json,"
                " kind=excluded.kind, updated_at=excluded.updated_at",
                (key, json.dumps(value, ensure_ascii=False), kind, now_ts()))

    def get(self, key: str, default: Any = None) -> Any:
        row = self.engine.thread_connection().execute(
            "SELECT value_json FROM app_settings WHERE key=?", (key,)).fetchone()
        if row is None:
            return default
        try:
            return json.loads(row["value_json"])
        except json.JSONDecodeError as exc:
            log.warning("app_settings[%s] 内容不是合法 JSON，按默认值处理：%s", key, exc)
            return default

    def all_keys(self) -> list[str]:
        rows = self.engine.thread_connection().execute(
            "SELECT key FROM app_settings ORDER BY key").fetchall()
        return [r["key"] for r in rows]

    def count(self) -> int:
        return self.engine.thread_connection().execute("SELECT count(*) FROM app_settings").fetchone()[0]
