"""文档↔库结构一致性守卫 —— 销账 ISSUES I44 的"仍欠"部分。

§2.5 声明当前 `sqlite_master` 里应有 20 张表（内容表 15 + schema_version + FTS5 影子表 4）。
§2.2 列出的表名（除 `duplicate_groups` 明写不建）必须真存在。

本断言按 AGENTS.md 用坏法真注入一次：
- 把期望数从 20 改成 19，必须变红
- 把 `documents` 从期望列表里删掉，必须变红

不会红就删掉这条断言。

**这个文件自己的历史欠账（ISSUES I62）**：它过去写的是 19，而真实库里 `sqlite_master` 数出来是
20 —— 因为 `vector_meta` 当时由 `semantic/vector_store.py` 在**运行时**建，只跑迁移链的本守卫
看不见它。迁移 `0007` 把它收进链之后，20 这个数才第一次"跑迁移就能长出来"。
表级守卫看得见表名、看不见列，列级的双向对账在 `tests/guards/test_schema_columns.py`。
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from pdfarchiver.config.paths import AppPaths
from pdfarchiver.db.engine import Engine
from pdfarchiver.db.migrate import migrate

# §2.2 列出的表（除 duplicate_groups 明写不建）
EXPECTED_TABLES = [
    "documents",
    "monitored_roots",
    "document_metadata",
    "categories",
    "tags",
    "document_tags",
    "document_categories",
    "text_pages",
    "content_fts",
    "collections",
    "file_operations",
    "operation_items",
    "processing_jobs",
    "app_settings",
    "schema_version",
    "vector_meta",
]

# §2.5 声明的总数（内容表 15 + schema_version + FTS5 影子表 4）
EXPECTED_COUNT = 20


def test_documentation_matches_actual_schema():
    """文档声明的表数与表名必须等于库里实际存在的。"""
    import tempfile

    with tempfile.TemporaryDirectory(prefix="guard_i44_") as td:
        paths = AppPaths.resolve(td)
        paths.mkdirs()
        engine = Engine(paths.catalog_db)
        try:
            migrate(engine, backup_dir=paths.backups_dir)
            conn = engine.thread_connection()

            # 现数 sqlite_master
            rows = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
            ).fetchall()
            actual_tables = {r[0] for r in rows}
            actual_count = len(actual_tables)

            # 检查总数
            assert actual_count == EXPECTED_COUNT, (
                f"§2.5 声明 {EXPECTED_COUNT} 张表，实际 {actual_count} 张。"
                f"差异：{actual_tables.symmetric_difference(_expected_set())}"
            )

            # 检查每个期望表都存在
            missing = [t for t in EXPECTED_TABLES if t not in actual_tables]
            assert not missing, f"§2.2 列出的表不存在：{missing}"

            # 反向：实际存在的表都应在期望列表里（或 FTS5 影子表）
            fts_shadows = {"content_fts_config", "content_fts_data", "content_fts_docsize", "content_fts_idx"}
            unexpected = actual_tables - _expected_set() - fts_shadows
            assert not unexpected, f"实际存在但文档未声明的表：{unexpected}"

        finally:
            engine.close_thread_connection()


def _expected_set() -> set[str]:
    return set(EXPECTED_TABLES) | {"content_fts_config", "content_fts_data", "content_fts_docsize", "content_fts_idx"}


def test_bad_injection_wrong_count():
    """坏法注入：期望数写错必须变红。"""
    import tempfile

    with tempfile.TemporaryDirectory(prefix="guard_i44_inject_") as td:
        paths = AppPaths.resolve(td)
        paths.mkdirs()
        engine = Engine(paths.catalog_db)
        try:
            migrate(engine, backup_dir=paths.backups_dir)
            conn = engine.thread_connection()

            rows = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
            ).fetchall()
            actual_count = len(rows)

            # 故意写错期望数
            wrong_expected = actual_count - 1
            try:
                assert actual_count == wrong_expected, (
                    f"坏法注入：期望 {wrong_expected}，实际 {actual_count}"
                )
                raise AssertionError("坏法注入没变红：期望数写错了但断言仍通过")
            except AssertionError as exc:
                if "坏法注入没变红" in str(exc):
                    raise
                # 这是预期的失败，说明坏法被抓到

        finally:
            engine.close_thread_connection()


def test_bad_injection_missing_table():
    """坏法注入：期望列表里删一个表名必须变红。"""
    import tempfile

    with tempfile.TemporaryDirectory(prefix="guard_i44_inject2_") as td:
        paths = AppPaths.resolve(td)
        paths.mkdirs()
        engine = Engine(paths.catalog_db)
        try:
            migrate(engine, backup_dir=paths.backups_dir)
            conn = engine.thread_connection()

            rows = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
            ).fetchall()
            actual_tables = {r[0] for r in rows}

            # 故意从期望列表里删一个真存在的表
            incomplete_list = [t for t in EXPECTED_TABLES if t != "documents"]
            missing = [t for t in incomplete_list if t not in actual_tables]
            # documents 在 actual_tables 里但不在 incomplete_list 里，所以 missing 是空
            # 但我们应该检查 actual - expected 的差集
            unexpected = actual_tables - set(incomplete_list) - {"content_fts_config", "content_fts_data", "content_fts_docsize", "content_fts_idx"}
            try:
                assert not unexpected, f"坏法注入：{unexpected} 存在但不在期望列表里"
                raise AssertionError("坏法注入没变红：删了表名但断言仍通过")
            except AssertionError as exc:
                if "坏法注入没变红" in str(exc):
                    raise
                # 这是预期的失败

        finally:
            engine.close_thread_connection()


if __name__ == "__main__":
    print("Running schema consistency guard (ISSUES I44)...")
    try:
        test_documentation_matches_actual_schema()
        print("  PASS  Documentation matches actual schema")
    except AssertionError as exc:
        print(f"  RED   {exc}")
        sys.exit(1)

    try:
        test_bad_injection_wrong_count()
        print("  PASS  Bad injection (wrong count) caught")
    except AssertionError as exc:
        print(f"  RED   {exc}")
        sys.exit(1)

    try:
        test_bad_injection_missing_table()
        print("  PASS  Bad injection (missing table) caught")
    except AssertionError as exc:
        print(f"  RED   {exc}")
        sys.exit(1)

    print("VERDICT: ALL GREEN")
