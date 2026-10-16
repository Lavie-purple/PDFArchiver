"""迁移 0006：删除 `documents.volume_id` 死列（ISSUES I40 收尾）。

该列在 0001 建表时就存在，文档注释写着"卷序列号（GetVolumeInformationEx）"，
但全项目代码零读写、恒 NULL。真正在用的身份列是 0002 加的 `device_id`。

用户已决定删除（不实现卷序列号），理由：
- `device_id`（`os.stat().st_dev`）已足够判定同盘/跨盘
- 保留一个恒 NULL 的列只会误导未来开发者（ISSUES I40 的触发点就是照文档去读它）
- SQLite `DROP COLUMN` 在 3.35.0+ 可用，Python 3.12 内置 SQLite 3.45+
"""
from __future__ import annotations

VERSION = 6


def apply(conn) -> None:
    conn.execute("ALTER TABLE documents DROP COLUMN volume_id")


def rollback(conn) -> None:
    conn.execute("ALTER TABLE documents ADD COLUMN volume_id TEXT")
