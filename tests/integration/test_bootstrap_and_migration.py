"""空库启动 → 建表 → 迁移 → 重启不重复；以及"故意让迁移中途失败"的真注入。

对应 docs/ROADMAP 阶段 1 两条「新」门禁：
  空库启动→建表→迁移→`integrity_check` ok；重启第二次不重复建表
  迁移前有 Backup API 快照，且**故意让迁移中途失败**能回到原样（这条必须真注入一次）

D-012 禁止 mock 数据库，所以这里全部是真 sqlite3 文件。
"""
from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path

import pytest

from pdfarchiver.db.engine import DatabaseError, Engine
from pdfarchiver.db.migrate import MigrationError, current_version, migrate
from pdfarchiver.services.bootstrap import bootstrap

REAL_MIGRATIONS = Path(__file__).resolve().parents[2] / "src" / "pdfarchiver" / "db" / "migrations"

STAGE1_TABLES = {
    "documents", "monitored_roots", "categories", "document_categories", "tags", "document_tags",
    "document_metadata", "collections", "processing_jobs", "file_operations", "operation_items",
    "app_settings", "schema_version",
}
# 0002 建的正文表与全文索引表。content_fts 是外部内容表，SQLite 会另建 content_fts_* 影子表，
# 所以下面一律用"包含"断言，不用 == 全表清单 —— 影子表名是 SQLite 的实现细节，不该被我们钉死。
STAGE2_TABLES = {"text_pages", "content_fts"}
# 0003 只加列、不加表，所以这里是一张列清单而不是表清单。
STAGE3_DOCUMENT_COLUMNS = {"ocr_pages_done", "last_ocr_at"}


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


def _db_at_v1(data_root: Path) -> Engine:
    """造一个**停在 0001** 的库 —— 这就是阶段 2 发布时用户机器上已存在的真实状态。

    要测"带数据升级"和"升级中途失败"，必须从 v1 起步；拿跑完 0002 的库去应用一个假 0002，
    水位已经 ≥2，迁移根本不会执行，断言全是空的。
    """
    m1 = data_root / "m_v1"
    m1.mkdir(parents=True, exist_ok=True)
    shutil.copy(REAL_MIGRATIONS / "0001_initial.py", m1)
    engine = Engine(data_root / "data" / "catalog.db")
    report = migrate(engine, backup_dir=data_root / "backups", migrations_dir=m1)
    assert report.applied == ["0001_initial"]
    return engine


def test_空库首启建出全部表(data_root: Path) -> None:
    ctx = bootstrap(data_root)
    try:
        tables = _tables(ctx.paths.catalog_db)
        assert STAGE1_TABLES | STAGE2_TABLES <= tables
        assert ctx.schema_version == 7
        # 启动路径不再跑同步库检查（2026-10-16 判死：6.1GB 真库上 integrity_check 19h+、
        # quick_check 452s+）。这里在 MB 级测试库上直接查 PRAGMA，验的是"迁移建出来的库健康"。
        conn = ctx.engine.thread_connection()
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert ctx.migration.did_anything and ctx.migration.applied == [
            "0001_initial", "0002_text_and_fts", "0003_ocr_tracking",
            "0004_reading_history", "0005_stage4_vocab", "0006_drop_volume_id",
            "0007_vector_meta_and_drop_pdf_version"]
    finally:
        ctx.shutdown()


def test_0002建出的全文索引表结构与触发器齐全(data_root: Path) -> None:
    """FTS 外部内容表的三条触发器少一条，索引就会静默不一致（docs/DATABASE 三）。
    这条断言只看目录里真有什么，不看代码写了什么。"""
    ctx = bootstrap(data_root)
    conn = ctx.engine.thread_connection()
    try:
        triggers = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name='text_pages'")}
        assert {"tx_pages_ai", "tx_pages_ad", "tx_pages_au"} == triggers
        cols = [r[1] for r in conn.execute("PRAGMA table_info(text_pages)")]
        # 最后一列 ocr_version 是 0003 追加的：OCR 的幂等判定按页比这个数，它必须在库里，
        # 而且必须在 `body` 之后 —— 老库升级上来的行靠 DEFAULT NULL 留空，位置错了会串列。
        assert cols == ["rowid", "doc_id", "page_no", "source_kind", "char_count", "body",
                        "indexed_at", "ocr_version"]
        # 外部内容表必须指向 text_pages，且列名与内容表一致 —— 不一致时 rebuild 直接 SQL logic error
        fts_sql = conn.execute("SELECT sql FROM sqlite_master WHERE name='content_fts'").fetchone()[0]
        assert "content='text_pages'" in fts_sql and "tokenize='trigram'" in fts_sql
        doc_cols = {r[1] for r in conn.execute("PRAGMA table_info(documents)")}
        assert {"device_id", "text_bearing_rate"} <= doc_cols, "重命名采纳与扫描件判定要用的列没加上"
    finally:
        ctx.shutdown()


def test_阶段4的表在阶段2仍然不存在(data_root: Path) -> None:
    """duplicate_groups 的分组口径（按 sha256 还是按内容相似）要到阶段 4 按实测再定，提前建就是返工。
    反向对照：text_pages / content_fts 现在**必须**已经存在。"""
    ctx = bootstrap(data_root)
    ctx.shutdown()
    tables = _tables(ctx.paths.catalog_db)
    assert "duplicate_groups" not in tables
    assert STAGE2_TABLES <= tables, "0002 没有真的应用，全文索引无从谈起"


def test_重启第二次不重复建表(data_root: Path) -> None:
    first = bootstrap(data_root)
    first.catalog.add_tag("重启前打的标签")
    first.shutdown()
    snaps_before = sorted(p.name for p in first.paths.backups_dir.glob("*.db"))

    second = bootstrap(data_root)
    try:
        assert second.migration.did_anything is False
        assert second.migration.from_version == second.migration.to_version == 7
        assert sorted(p.name for p in second.paths.backups_dir.glob("*.db")) == snaps_before, \
            "没有待应用迁移时不许产生新快照"
        assert second.catalog.count_tags() == 1
        assert second.seed.skipped is True, "第二次启动不许再种一遍默认分类"
        assert second.catalog.count_categories() == 14
    finally:
        second.shutdown()


def _columns(db: Path, table: str) -> set[str]:
    conn = sqlite3.connect(str(db))
    try:
        return {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
    finally:
        conn.close()


def test_每一步迁移前都有可用快照且快照停在迁移之前(data_root: Path) -> None:
    ctx = bootstrap(data_root)
    ctx.shutdown()
    snaps = sorted(p.name for p in ctx.paths.backups_dir.glob("pre-migration-*.db"))
    assert len(snaps) == 7 and snaps == sorted(snaps), \
        "应用了 0001/0002/0003/0004/0005/0006/0007 七个迁移，就该有七次迁移前快照"
    assert all(n.startswith("pre-migration-000") for n in snaps)

    s1 = ctx.paths.backups_dir / snaps[0]
    s2 = ctx.paths.backups_dir / snaps[1]
    s3 = ctx.paths.backups_dir / snaps[2]
    assert "documents" not in _tables(s1), "0001 之前的快照里不该有 documents"
    mid = _tables(s2)
    assert "documents" in mid, "0002 之前的快照必须有 0001 的成果"
    assert not (STAGE2_TABLES & mid), "快照必须在迁移**之前**拍，否则回退点就是脏的"
    # 0003 只加列，所以它的回退点只能用列来验：有 0002 的表、没有 0003 的列。
    assert STAGE2_TABLES <= _tables(s3), "0003 之前的快照必须有 0002 的成果"
    assert not (STAGE3_DOCUMENT_COLUMNS & _columns(s3, "documents")), "加列迁移的快照必须停在加列之前"
    assert STAGE3_DOCUMENT_COLUMNS <= _columns(ctx.paths.catalog_db, "documents")

    conn = sqlite3.connect(str(s2))
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
    engine = _db_at_v1(data_root)
    db = engine.path
    conn = engine.connect()
    conn.execute("INSERT INTO tags(name, created_at) VALUES('失败前就有了的标签', 1)")
    conn.commit()
    conn.close()
    before_rows = engine.connect().execute("SELECT count(*) FROM tags").fetchone()[0]

    mdir = data_root / "migrations_with_bad"
    mdir.mkdir()
    shutil.copy(REAL_MIGRATIONS / "0001_initial.py", mdir)
    _write_migration(mdir, "0002_boom.py", (
        "VERSION = 2\n\n\n"
        "def apply(conn):\n"
        "    conn.execute('CREATE TABLE should_not_survive(x INTEGER)')\n"
        "    raise RuntimeError('故意注入的迁移中途失败')\n"))

    with pytest.raises(MigrationError, match="已回滚"):
        migrate(engine, backup_dir=data_root / "backups2", migrations_dir=mdir)

    tables = _tables(db)
    assert "should_not_survive" not in tables, "半个迁移留下了表 —— 事务没兜住"
    assert "documents" in tables, "回滚把 0001 的成果也弄丢了"
    assert "content_fts" not in tables, "回滚必须连 FTS 虚表一起撤销"
    assert current_version(engine.connect()) == 1
    conn = engine.connect()
    try:
        assert conn.execute("SELECT count(*) FROM tags").fetchone()[0] == before_rows
    finally:
        conn.close()
        engine.close_thread_connection()
    assert engine.integrity_check() == "ok"


def test_迁移失败时异常里带快照路径(data_root: Path) -> None:
    engine = _db_at_v1(data_root)
    mdir = data_root / "m"
    mdir.mkdir()
    shutil.copy(REAL_MIGRATIONS / "0001_initial.py", mdir)
    _write_migration(mdir, "0002_boom.py", "VERSION = 2\n\n\ndef apply(conn):\n    raise ValueError('x')\n")
    with pytest.raises(MigrationError) as e:
        migrate(engine, backup_dir=data_root / "backups", migrations_dir=mdir)
    assert e.value.snapshot is not None and e.value.snapshot.is_file()
    engine.close_thread_connection()


def test_坏迁移修好后能继续往前(data_root: Path) -> None:
    """失败不是终点：把 0002 换成好版本，同一个库要能正常升上去（SPEC 4.2 不许让用户删库重来）。"""
    engine = _db_at_v1(data_root)
    db = engine.path
    bad = data_root / "m_bad"
    bad.mkdir()
    shutil.copy(REAL_MIGRATIONS / "0001_initial.py", bad)
    _write_migration(bad, "0002_boom.py", "VERSION = 2\n\n\ndef apply(conn):\n    raise ValueError('x')\n")
    with pytest.raises(MigrationError):
        migrate(engine, backup_dir=data_root / "backups", migrations_dir=bad)

    report = migrate(engine, backup_dir=data_root / "backups", migrations_dir=REAL_MIGRATIONS)
    assert report.applied == ["0002_text_and_fts", "0003_ocr_tracking",
                              "0004_reading_history", "0005_stage4_vocab",
                              "0006_drop_volume_id", "0007_vector_meta_and_drop_pdf_version"], \
        "真实迁移必须能接着坏迁移留下的 v1 库一路往上走"
    assert current_version(engine.connect()) == 7
    assert STAGE2_TABLES <= _tables(db)
    assert engine.integrity_check() == "ok"
    engine.close_thread_connection()


def test_运行时建过vector_meta的现存库升0007是无操作而不是撞表(data_root: Path) -> None:
    """模拟**开发机真实库**那条路径：老代码在运行时 `CREATE TABLE IF NOT EXISTS vector_meta`，
    所以 0007 面对的是一个**已经有这张表、而且可能带着行**的库。

    这条断言钉两件事，两件都是"双击打不开"的形状：
    - 0007 必须过得去（靠 `IF NOT EXISTS`），不能报 `table vector_meta already exists`；
    - 已有的元数据行必须一条不少（靠"不 DROP 再建"，而是真的什么都不做）。
    """
    engine = _db_at_v1(data_root)
    v6 = data_root / "m_v6"
    shutil.copytree(REAL_MIGRATIONS, v6)
    (v6 / "0007_vector_meta_and_drop_pdf_version.py").unlink()
    report = migrate(engine, backup_dir=data_root / "backups", migrations_dir=v6)
    assert current_version(engine.connect()) == 6 and report.to_version == 6

    conn = engine.connect()
    conn.execute("INSERT INTO documents(path, path_key, name, ext, size_bytes, mtime_ns,"
                 " created_at, updated_at) VALUES('H:/docs/旧.pdf','h:/docs/旧.pdf','旧.pdf','pdf',1,1,1,1)")
    doc_id = conn.execute("SELECT id FROM documents WHERE path_key='h:/docs/旧.pdf'").fetchone()[0]
    # 逐字照老 `vector_store.py:39-48` 的形状建，这才是现存库的真样子
    conn.execute("""
        CREATE TABLE vector_meta (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            doc_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
            page_no INTEGER NOT NULL,
            vector_idx INTEGER NOT NULL UNIQUE,
            UNIQUE(doc_id, page_no)
        )
    """)
    conn.execute("INSERT INTO vector_meta(doc_id, page_no, vector_idx) VALUES(?, 3, 7)", (doc_id,))
    conn.commit()
    conn.close()

    applied = migrate(engine, backup_dir=data_root / "backups", migrations_dir=REAL_MIGRATIONS)
    assert applied.applied == ["0007_vector_meta_and_drop_pdf_version"], \
        "现存库升 0007 必须只应用这一条，且不能因为表已存在而失败"
    conn = engine.connect()
    try:
        assert [tuple(r) for r in conn.execute(
            "SELECT doc_id, page_no, vector_idx FROM vector_meta").fetchall()] \
            == [(doc_id, 3, 7)], "0007 把现存库已有的向量元数据弄丢或弄改了"
        assert "pdf_version" not in _columns(engine.path, "documents"), "死列没删掉"
        assert "ix_vector_meta_doc" in {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='vector_meta'")}, \
            "现存库那条路径上老代码建的索引名与迁移建的同名，IF NOT EXISTS 后必须仍在"
    finally:
        conn.close()
    assert engine.integrity_check() == "ok"
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
