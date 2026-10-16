"""0004 · 阅读历史（阶段 3 · S2 PDF 阅读器）。

阅读器需要记住"上次读到哪一页"，所以给 documents 加两列：
- `last_read_page`：上次阅读的页码（从 1 开始，NULL 表示没读过）
- `last_read_at`：上次阅读的时间戳（NULL 表示没读过）

刻意**不加**的两样东西：
- 不建单独的 `reading_history` 表：当前需求只要求"记住上次读到哪"，不需要历史记录列表。
  等真要存"每次阅读花了多久、读了哪几页"的流水时再建表，那时这两列仍然留着当"当前进度"的读数。
- 不加"阅读总时长"列：没有可靠的方式在后台追踪用户是否真的在看，存一个猜出来的数等于假指标。
"""
from __future__ import annotations

VERSION = 4

DOCUMENTS_COLUMNS = [
    ("last_read_page", "INTEGER"),
    ("last_read_at", "INTEGER"),
]


def apply(conn) -> None:  # noqa: ANN001 - sqlite3.Connection，不 import 类型以免多一层依赖
    """整个函数在调用方的一个事务里执行：中途失败整体回滚，库回到 0003。"""
    for name, sql_type in DOCUMENTS_COLUMNS:
        conn.execute(f"ALTER TABLE documents ADD COLUMN {name} {sql_type}")
