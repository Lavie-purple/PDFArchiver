"""空库启动 → 建表 → 迁移 → 重启不重复；以及"故意让迁移中途失败"的真注入。

对应 docs/ROADMAP 阶段 1 两条「新」门禁：
  空库启动→建表→迁移→`integrity_check` ok；重启第二次不重复建表
  迁移前有 Backup API 快照，且**故意让迁移中途失败**能回到原样（这条必须真注入一次）

D-012 禁止 mock 数据库，所以这里全部是真 sqlite3 文件。
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from pdfarchiver.db.engine import DatabaseError, Engine
from pdfarchiver.db.migrate import MigrationError, current_version, migrate
from pdfarchiver.services.bootstrap import bootstrap

EXPECTED_TABLES = {
    "documents", "monitored_roots", "categories", "document_categories", "tags", "document_tags",
    "document_metadata", "collections", "processing_jobs", "file_operations", "operation_items",
    "app_settings", "schema_version",
}


def _tables(db: Path) -> set[str]:
    conn = sqlite3.connect(str(db))
    try:
        rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    finally:
        conn.close()
    return {r[0] for r in rows}


def _write_migration(dir_: Path, filename: str, body: str) -> Path:
    p = dir_ / filename
    p.write_text(body, encoding="utf-8")
    return p


def test_空库首启建出全部表(data_root: Path) -> None:
    ctx = bootstrap(data_root)
    try:
        assert ctx.paths.catalog_db.is_file()
        assert EXPECTED_TABLES <= _tables(ctx.paths.catalog_db)
        assert ctx.schema_version == 1
        assert ctx.status.read().integrity == "ok"
        assert ctx.migration.did_anything and ctx.migration.applied == ["0001_initial"]
    finally:
        ctx.shutdown()


def test_阶段1刻意不建的表确实不存在(data_root: Path) -> None:
    """Q1（分词器）和 Q2（索引体积）没答，全文表结构建了就得返工 —— 这条断言是"没提前建"的证据。"""
    ctx = bootstrap(data_root)
    ctx.shutdown()
    tables = _tables(ctx.paths.catalog_db)
    assert not ({"text_pages", "content_fts", "duplicate_groups"} & tables)


def test_重启第二次不重复建表(data_root: Path) -> None:
    first = bootstrap(data_root)
    first.catalog.add_tag("重启前打的标签")
    first.shutdown()
    snaps_before = sorted(p.name for p in first.paths.backups_dir.glob("*.db"))

    second = bootstrap(data_root)
    try:
        assert second.migration.did_anything is False
        assert second.migration.from_version == second.migration.to_version == 1
        assert sorted(p.name for p in second.paths.backups_dir.glob("*.db")) == snaps_before, \
            "没有待应用迁移时不许产生新快照"
        assert second.catalog.count_tags() == 1
        assert second.seed.skipped is True, "第二次启动不许再种一遍默认分类"
        assert second.catalog.count_categories() == 14
    finally:
        second.shutdown()


def test_迁移前快照是空库且可用BackupAPI读出(data_root: Path) -> None:
    ctx = bootstrap(data_root)
    ctx.shutdown()
    snaps = sorted(ctx.paths.backups_dir.glob("pre-migration-*.db"))
    assert len(snaps) == 1
    assert snaps[0].name.startswith("pre-migration-0001-")
    snap_tables = _tables(snaps[0])
    assert "documents" not in snap_tables, "0001 之前的快照里不该有 documents"
    conn = sqlite3.connect(str(snaps[0]))
    try:
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    finally:
        conn.close()


def test_没有快照目录就拒绝迁移(tmp_path: Path) -> None:
    """SPEC 4.2「避免每次修改结构都要求用户删库重来」的前提是有备份；没备份就动手是拿用户数据赌。"""
    engine = Engine(tmp_path / "x.db")
    with pytest.raises(MigrationError, match="快照目录"):
        migrate(engine, backup_dir=None)
    assert _tables(tmp_path / "x.db") == {"schema_version"}, "拒绝迁移时不该留下任何表"


def test_迁移中途失败回到原样(data_root: Path) -> None:
    """真注入：0002 先建一张表，再故意抛。库必须回到 0001 的状态，那张表不能存在。"""
    ctx = bootstrap(data_root)
    ctx.catalog.add_tag("失败前就有了的标签")
    db = ctx.paths.catalog_db
    mdir = data_root / "migrations_with_bad"
    mdir.mkdir()
    _write_migration(mdir, "0002_boom.py", (
        "VERSION = 2\n\n\n"
        "def apply(conn):\n"
        "    conn.execute('CREATE TABLE should_not_survive(x INTEGER)')\n"
        "    raise RuntimeError('故意注入的迁移中途失败')\n"))
    before_rows = ctx.catalog.count_tags()
    ctx.shutdown()

    engine = Engine(db)
    with pytest.raises(MigrationError, match="已回滚"):
        migrate(engine, backup_dir=data_root / "backups2", migrations_dir=mdir)

    tables = _tables(db)
    assert "should_not_survive" not in tables, "半个迁移留下了表 —— 事务没兜住"
    assert "documents" in tables, "回滚把 0001 的成果也弄丢了"
    assert current_version(engine.connect()) == 1
    conn = engine.connect()
    try:
        assert conn.execute("SELECT count(*) FROM tags").fetchone()[0] == before_rows
    finally:
        conn.close()
    assert engine.integrity_check() == "ok"


def test_迁移失败时异常里带快照路径(data_root: Path) -> None:
    ctx = bootstrap(data_root)
    mdir = data_root / "m"
    mdir.mkdir()
    _write_migration(mdir, "0002_boom.py", "VERSION = 2\n\n\ndef apply(conn):\n    raise ValueError('x')\n")
    ctx.shutdown()
    with pytest.raises(MigrationError) as e:
        migrate(Engine(data_root / "data" / "catalog.db"),
                backup_dir=data_root / "backups", migrations_dir=mdir)
    assert e.value.snapshot is not None and e.value.snapshot.is_file()


def test_坏迁移修好后能继续往前(data_root: Path) -> None:
    """失败不是终点：把 0002 换成好版本，同一个库要能正常升上去（SPEC 4.2 不许让用户删库重来）。"""
    ctx = bootstrap(data_root)
    db = ctx.paths.catalog_db
    ctx.shutdown()
    bad = data_root / "m_bad"
    bad.mkdir()
    _write_migration(bad, "0002_boom.py", "VERSION = 2\n\n\ndef apply(conn):\n    raise ValueError('x')\n")
    with pytest.raises(MigrationError):
        migrate(Engine(db), backup_dir=data_root / "backups", migrations_dir=bad)

    good = data_root / "m_good"
    good.mkdir()
    _write_migration(good, "0002_fixed.py",
                     "VERSION = 2\n\n\ndef apply(conn):\n"
                     "    conn.execute('CREATE TABLE added_later(x INTEGER)')\n")
    engine = Engine(db)
    report = migrate(engine, backup_dir=data_root / "backups", migrations_dir=good)
    assert report.applied == ["0002_fixed"]
    assert current_version(engine.connect()) == 2
    assert "added_later" in _tables(db)
    engine.close_thread_connection()


def test_首启就把日志和状态事件写在所选目录下(data_root: Path) -> None:
    ctx = bootstrap(data_root)
    ctx.shutdown()
    assert (ctx.paths.logs_dir / "app.log").is_file()
    state = (ctx.paths.logs_dir / "state.log").read_text(encoding="utf-8")
    for event in ("startup.begin", "migration.applied", "startup.done", "shutdown"):
        assert f'"{event}"' in state, f"state.log 缺少生命周期事件 {event}"


def test_库文件损坏时报错带sqlite原文(data_root: Path) -> None:
    data_root.mkdir(parents=True, exist_ok=True)
    db = data_root / "data" / "catalog.db"
    db.parent.mkdir(parents=True, exist_ok=True)
    db.write_bytes("这不是数据库文件".encode("utf-8") * 64)
    with pytest.raises(DatabaseError) as e:
        bootstrap(data_root)
    assert "file is not a database" in str(e.value).lower() or "not a database" in str(e.value).lower()
    assert str(db) in str(e.value), "错误信息要指得出是哪个库"
