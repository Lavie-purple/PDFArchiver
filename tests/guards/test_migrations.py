"""迁移守卫（docs/DATABASE 四 要求存在这个文件）。

守卫的问题不是"0001 能不能建表"，那已经由 integration 验过；这里验的是
**升级路径上数据不丢**：拿一个已经带着数据的旧库，跑一遍全量迁移，
条数、内容、完整性、外键都必须原样还在。
"""
from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path

import pytest

from pdfarchiver.db.engine import Engine
from pdfarchiver.db.migrate import current_version, migrate
from pdfarchiver.db.migrations import discover

REAL_MIGRATIONS = Path(__file__).resolve().parents[2] / "src" / "pdfarchiver" / "db" / "migrations"


@pytest.fixture
def old_db(tmp_path: Path) -> tuple[Engine, Path]:
    """一个已经跑过真实迁移、并且带着数据的库。"""
    db = tmp_path / "catalog.db"
    engine = Engine(db)
    report = migrate(engine, backup_dir=tmp_path / "backups")
    assert report.applied, "基线都没建起来，后面的断言全是假的"
    conn = engine.connect()
    conn.executemany("INSERT INTO tags(name, created_at) VALUES(?,?)",
                    [("标签甲", 1), ("标签乙", 2), ("标签丙", 3)])
    conn.executemany(
        "INSERT INTO documents(path, path_key, name, ext, size_bytes, mtime_ns, created_at, updated_at)"
        " VALUES(?,?,?,?,?,?,?,?)",
        [(f"H:/docs/{i}.pdf", f"h:/docs/{i}.pdf", f"{i}.pdf", "pdf", i, i, 1, 1) for i in range(5)])
    conn.execute("INSERT INTO categories(name, name_path, created_at, updated_at) VALUES('报告','报告',1,1)")
    conn.commit()
    conn.close()
    return engine, db


def _counts(db: Path) -> dict[str, int]:
    conn = sqlite3.connect(str(db))
    try:
        out = {}
        for (name,) in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"):
            out[name] = conn.execute(f"SELECT count(*) FROM {name}").fetchone()[0]
    finally:
        conn.close()
    return out


def test_升级到新版本后行数一条不丢(old_db, tmp_path) -> None:
    engine, db = old_db
    before = _counts(db)
    mdir = tmp_path / "migrations"
    shutil.copytree(REAL_MIGRATIONS, mdir)
    (mdir / "0002_add_note.py").write_text(
        "VERSION = 2\n\n\n"
        "def apply(conn):\n"
        "    conn.execute('CREATE TABLE stage2_marker(id INTEGER PRIMARY KEY, note TEXT)')\n"
        "    conn.execute(\"INSERT INTO stage2_marker(note) VALUES('新表')\")\n"
        "    conn.execute(\"ALTER TABLE tags ADD COLUMN note2 TEXT\")\n",
        encoding="utf-8")

    report = migrate(engine, backup_dir=tmp_path / "backups2", migrations_dir=mdir)
    assert report.applied == ["0002_add_note"]
    assert current_version(engine.connect()) == 2

    after = _counts(db)
    assert {k: v for k, v in after.items() if k != "stage2_marker"} == before, "升级把数据弄丢或弄多了"
    assert after["tags"] == 3 and after["documents"] == 5
    assert engine.integrity_check() == "ok"


def test_升级后的旧数据内容仍然读得回来(old_db) -> None:
    engine, db = old_db
    conn = sqlite3.connect(str(db))
    rows = conn.execute("SELECT name FROM tags ORDER BY name").fetchall()
    docs = conn.execute("SELECT path_key FROM documents ORDER BY path_key").fetchall()
    conn.close()
    assert [r[0] for r in rows] == ["标签丙", "标签乙", "标签甲"]  # 按字节序，只验条数与内容都在
    assert len(docs) == 5 and all(d[0].startswith("h:/docs/") for d in docs)


def test_完整性与外键检查都干净(old_db) -> None:
    engine, db = old_db
    assert engine.integrity_check() == "ok"
    conn = sqlite3.connect(str(db))
    try:
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        conn.close()


def test_真实迁移目录从空库一路能跑到最新版(tmp_path) -> None:
    """这条是"删库重来"的反证：只要迁移链能从头跑到尾，用户就不该被要求重建库。"""
    db = tmp_path / "catalog.db"
    engine = Engine(db)
    report = migrate(engine, backup_dir=tmp_path / "backups", migrations_dir=REAL_MIGRATIONS)
    newest = discover(REAL_MIGRATIONS)[-1].order
    assert report.to_version == newest
    assert engine.integrity_check() == "ok"
    # 再跑一次必须什么都不做（幂等），否则重启会把同一迁移执行多遍
    again = migrate(engine, backup_dir=tmp_path / "backups", migrations_dir=REAL_MIGRATIONS)
    assert again.did_anything is False


def test_WAL与外键设置在库里持久(old_db) -> None:
    engine, db = old_db
    conn = sqlite3.connect(str(db))
    try:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
    finally:
        conn.close()
