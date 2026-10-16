"""迁移 0005：阶段 4 口径定死（D-048 / D-049）。

1. `file_operations` 加 `job_id` 列（可空外键指向 `processing_jobs.id`）
   - 一个批次一条总控任务，`doc_id` 留 NULL
   - 与 S4 线框里"计数条只读批次那三列"的形状一致（D-049）
2. `operation_items.state` 加 CHECK 约束：`pending|done|failed|skipped`
   - 跳过的项不进 journal，journal 只记真动过的（D-048）
   - journal 是 JSONL 文件（不是数据库表），态机七态在文档里定死，不需要 CHECK
"""
from __future__ import annotations

VERSION = 5


def apply(conn) -> None:
    # 1. file_operations 加 job_id 列
    conn.execute("""
        ALTER TABLE file_operations
        ADD COLUMN job_id INTEGER NULL
        REFERENCES processing_jobs(id)
    """)

    # 2. operation_items.state 加 CHECK 约束
    # SQLite 不支持 ALTER TABLE ADD CONSTRAINT，需要重建表
    # 但 operation_items 当前零行数据，直接重建安全
    conn.execute("DROP TABLE IF EXISTS operation_items_backup")
    conn.execute("CREATE TABLE operation_items_backup AS SELECT * FROM operation_items")
    conn.execute("DROP TABLE operation_items")
    conn.execute("""
        CREATE TABLE operation_items (
            id INTEGER PRIMARY KEY,
            op_id INTEGER NOT NULL REFERENCES file_operations(id) ON DELETE CASCADE,
            doc_id INTEGER REFERENCES documents(id) ON DELETE SET NULL,
            kind TEXT NOT NULL CHECK(kind IN ('move', 'copy')),
            src_path TEXT NOT NULL,
            dst_path TEXT,
            state TEXT NOT NULL DEFAULT 'pending'
                CHECK(state IN ('pending', 'done', 'failed', 'skipped')),
            reversible INTEGER NOT NULL DEFAULT 1,
            error TEXT,
            src_sha256 TEXT,
            dst_sha256 TEXT,
            updated_at INTEGER NOT NULL
        )
    """)
    conn.execute("""
        INSERT INTO operation_items
        SELECT * FROM operation_items_backup
    """)
    conn.execute("DROP TABLE operation_items_backup")
    # 重建索引
    conn.execute("CREATE INDEX ix_items_op_state ON operation_items(op_id, state)")


def rollback(conn) -> None:
    # 回滚：删掉 job_id 列（SQLite 不支持 DROP COLUMN，需要重建表）
    conn.execute("DROP TABLE IF EXISTS file_operations_backup")
    conn.execute("""
        CREATE TABLE file_operations_backup AS
        SELECT id, plan_json, journal_path, items_total, items_done, items_failed,
               undo_of, created_at, started_at, finished_at
        FROM file_operations
    """)
    conn.execute("DROP TABLE file_operations")
    conn.execute("""
        CREATE TABLE file_operations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            plan_json TEXT NOT NULL,
            journal_path TEXT NOT NULL,
            items_total INTEGER NOT NULL DEFAULT 0,
            items_done INTEGER NOT NULL DEFAULT 0,
            items_failed INTEGER NOT NULL DEFAULT 0,
            undo_of INTEGER NULL REFERENCES file_operations(id),
            created_at INTEGER NOT NULL,
            started_at INTEGER NULL,
            finished_at INTEGER NULL
        )
    """)
    conn.execute("""
        INSERT INTO file_operations
        SELECT * FROM file_operations_backup
    """)
    conn.execute("DROP TABLE file_operations_backup")

    # 回滚 CHECK 约束：重建表不带 CHECK
    conn.execute("DROP TABLE IF EXISTS operation_items_backup")
    conn.execute("CREATE TABLE operation_items_backup AS SELECT * FROM operation_items")
    conn.execute("DROP TABLE operation_items")
    conn.execute("""
        CREATE TABLE operation_items (
            id INTEGER PRIMARY KEY,
            op_id INTEGER NOT NULL REFERENCES file_operations(id) ON DELETE CASCADE,
            doc_id INTEGER REFERENCES documents(id) ON DELETE SET NULL,
            kind TEXT NOT NULL,
            src_path TEXT NOT NULL,
            dst_path TEXT,
            state TEXT NOT NULL DEFAULT 'pending',
            reversible INTEGER NOT NULL DEFAULT 1,
            error TEXT,
            src_sha256 TEXT,
            dst_sha256 TEXT,
            updated_at INTEGER NOT NULL
        )
    """)
    conn.execute("""
        INSERT INTO operation_items
        SELECT * FROM operation_items_backup
    """)
    conn.execute("DROP TABLE operation_items_backup")
    conn.execute("CREATE INDEX ix_items_op_state ON operation_items(op_id, state)")
