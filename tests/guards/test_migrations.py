"""迁移守卫（docs/DATABASE 四 要求存在这个文件）。

守卫的问题不是"0001 能不能建表"，那已经由 integration 验过；这里验的是
**升级路径上数据不丢**：拿一个已经带着数据的旧库，跑一遍全量迁移，
条数、内容、完整性、外键都必须原样还在。

阶段 1 时这条守卫只能拿**合成的** 0002 试（那时还没有真的 0002）。
阶段 2 有了真的 `0002_text_and_fts`，docs/ROADMAP 阶段 2 明确要求换成真实迁移再验一次 ——
所以下面的基线库故意**只跑到 0001**，然后应用真实迁移目录。
"""
from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path

import pytest

from pdfarchiver.db.engine import Engine
from pdfarchiver.db.migrate import MigrationError, current_version, migrate
from pdfarchiver.db.migrations import discover
from pdfarchiver.db.repositories.text import TextRepository

REAL_MIGRATIONS = Path(__file__).resolve().parents[2] / "src" / "pdfarchiver" / "db" / "migrations"
NEW_TABLES_AT_2 = {"text_pages", "content_fts", "content_fts_config", "content_fts_content",
                  "content_fts_data", "content_fts_docsize", "content_fts_idx"}
# 0007 才建 vector_meta（收编阶段 6 那段运行时建表），它从 0 行开始，不算数据丢失
NEW_TABLES_AT_7 = {"vector_meta"}


def _v1_dir(tmp_path: Path) -> Path:
    """只含 0001 的迁移目录 —— 用来造"阶段 2 发布时用户机器上已存在的库"。"""
    d = tmp_path / "migrations_v1"
    d.mkdir(exist_ok=True)
    shutil.copy(REAL_MIGRATIONS / "0001_initial.py", d)
    return d


@pytest.fixture
def old_db(tmp_path: Path) -> tuple[Engine, Path]:
    """一个**停在 0001** 并且带着数据的库。"""
    db = tmp_path / "catalog.db"
    engine = Engine(db)
    report = migrate(engine, backup_dir=tmp_path / "backups", migrations_dir=_v1_dir(tmp_path))
    assert report.applied == ["0001_initial"], "基线必须停在 0001，否则后面的升级断言全是空的"
    assert current_version(engine.connect()) == 1
    conn = engine.connect()
    conn.executemany("INSERT INTO tags(name, created_at) VALUES(?,?)",
                    [("标签甲", 1), ("标签乙", 2), ("标签丙", 3)])
    conn.executemany(
        "INSERT INTO documents(path, path_key, name, ext, size_bytes, mtime_ns, created_at, updated_at)"
        " VALUES(?,?,?,?,?,?,?,?)",
        [(f"H:/docs/{i}.pdf", f"h:/docs/{i}.pdf", f"{i}.pdf", "pdf", i, i, 1, 1) for i in range(5)])
    conn.execute("INSERT INTO categories(name, name_path, created_at, updated_at) VALUES('报告','报告',1,1)")
    conn.execute("INSERT INTO monitored_roots(root_path, root_key, created_at, updated_at)"
                 " VALUES('H:/docs','h:/docs',1,1)")
    conn.commit()
    conn.close()
    return engine, db


def _counts(db: Path, ignore: set[str] = frozenset()) -> dict[str, int]:
    """各表行数。`ignore` 用来排除**这次迁移新建**的表 —— 它们从 0 变成 N 不是数据丢失。"""
    conn = sqlite3.connect(str(db))
    try:
        out = {}
        for (name,) in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"):
            if name in ignore:
                continue
            out[name] = conn.execute(f"SELECT count(*) FROM {name}").fetchone()[0]
    finally:
        conn.close()
    return out


def test_真实0002升级后旧数据行数一条不丢(old_db, tmp_path) -> None:
    engine, db = old_db
    before = _counts(db)
    report = migrate(engine, backup_dir=tmp_path / "backups2", migrations_dir=REAL_MIGRATIONS)
    assert report.applied == ["0002_text_and_fts", "0003_ocr_tracking",
                              "0004_reading_history", "0005_stage4_vocab",
                              "0006_drop_volume_id", "0007_vector_meta_and_drop_pdf_version",
                              "0008_name_ci_index"]
    assert current_version(engine.connect()) == 8

    after = _counts(db, ignore=NEW_TABLES_AT_2 | NEW_TABLES_AT_7)
    assert after == before, "带数据升级把老表的内容弄丢或弄多了"
    assert after["tags"] == 3 and after["documents"] == 5 and after["monitored_roots"] == 1
    assert engine.integrity_check() == "ok"
    engine.close_thread_connection()


def test_真实0003加列后老行的OCR列是空而不是假值(old_db, tmp_path) -> None:
    """0003 给 `text_pages` 与 `documents` 各加了 OCR 相关的列，老库升级后必须留空。

    `ocr_pages_done` 是**计数**，默认 0 说的是"一页都还没识别"，与"取不到就留空"不冲突；
    另外两列（`last_ocr_at`、`ocr_version`）是"什么时候跑的、哪个版本跑的"，
    老行没跑过就必须是 NULL —— 填 0 或空串会让状态页把"从没识别过"显示成"识别过但结果是空"。
    """
    engine, db = old_db
    migrate(engine, backup_dir=tmp_path / "backups2", migrations_dir=REAL_MIGRATIONS)
    conn = sqlite3.connect(str(db))
    try:
        row = conn.execute("SELECT ocr_pages_done, last_ocr_at, ocr_status FROM documents"
                           " ORDER BY id LIMIT 1").fetchone()
    finally:
        conn.close()
    assert row == (0, None, "na"), f"老行的 OCR 列被填了假值：{row}"


def test_真实0002升级后旧内容仍然读得回来(old_db, tmp_path) -> None:
    engine, db = old_db
    migrate(engine, backup_dir=tmp_path / "backups2", migrations_dir=REAL_MIGRATIONS)
    conn = sqlite3.connect(str(db))
    try:
        rows = conn.execute("SELECT name FROM tags ORDER BY name").fetchall()
        docs = conn.execute("SELECT path_key, name, size_bytes FROM documents ORDER BY path_key").fetchall()
        root = conn.execute("SELECT root_path FROM monitored_roots").fetchall()
        # 新加的列必须是 NULL 而不是 0 或空串 —— "取不到就留空"是 SPEC 3.2 的口径
        fresh = conn.execute("SELECT device_id, text_bearing_rate FROM documents LIMIT 1").fetchone()
    finally:
        conn.close()
    assert [r[0] for r in rows] == ["标签丙", "标签乙", "标签甲"]
    assert len(docs) == 5 and all(d[0].startswith("h:/docs/") for d in docs)
    assert root == [("H:/docs",)]
    assert tuple(fresh) == (None, None), "新增列拿不到值时不许填 0 或空串冒充"


def test_升级到新版本后行数一条不丢(old_db, tmp_path) -> None:
    """再加一步**合成**的"最新号 + 1"迁移：证明这条守卫对将来的迁移同样成立，不是只认识 0002/0003。

    编号必须**从真目录里现数**再 +1，不许写死 —— 0007 一旦落地，写死 0007 的合成文件会与真迁移
    **重号**，`discover()` 直接抛 `ValueError`，这条守卫就会以一种谁也猜不到的方式红。
    """
    engine, db = old_db
    migrate(engine, backup_dir=tmp_path / "backups", migrations_dir=REAL_MIGRATIONS)
    ignore = NEW_TABLES_AT_2 | NEW_TABLES_AT_7
    before = _counts(db, ignore=ignore)
    mdir = tmp_path / "migrations"
    shutil.copytree(REAL_MIGRATIONS, mdir)
    next_order = discover(REAL_MIGRATIONS)[-1].order + 1
    (mdir / f"{next_order:04d}_add_note.py").write_text(
        f"VERSION = {next_order}\n\n\n"
        "def apply(conn):\n"
        "    conn.execute('CREATE TABLE stage4_marker(id INTEGER PRIMARY KEY, note TEXT)')\n"
        "    conn.execute(\"INSERT INTO stage4_marker(note) VALUES('新表')\")\n"
        "    conn.execute(\"ALTER TABLE tags ADD COLUMN note2 TEXT\")\n",
        encoding="utf-8")

    report = migrate(engine, backup_dir=tmp_path / "backups2", migrations_dir=mdir)
    assert report.applied == [f"{next_order:04d}_add_note"]
    assert current_version(engine.connect()) == next_order

    after = _counts(db, ignore=ignore | {"stage4_marker"})
    assert after == before, "升级把数据弄丢或弄多了"
    assert after["tags"] == 3 and after["documents"] == 5
    assert engine.integrity_check() == "ok"


def test_升级后的旧数据内容仍然读得回来(old_db) -> None:
    engine, db = old_db
    conn = sqlite3.connect(str(db))
    try:
        rows = conn.execute("SELECT name FROM tags ORDER BY name").fetchall()
        docs = conn.execute("SELECT path_key FROM documents ORDER BY path_key").fetchall()
    finally:
        conn.close()
    assert [r[0] for r in rows] == ["标签丙", "标签乙", "标签甲"]  # 按字节序，只验条数与内容都在
    assert len(docs) == 5 and all(d[0].startswith("h:/docs/") for d in docs)


def test_完整性与外键检查都干净(old_db, tmp_path) -> None:
    engine, db = old_db
    migrate(engine, backup_dir=tmp_path / "backups2", migrations_dir=REAL_MIGRATIONS)
    assert engine.integrity_check() == "ok"
    conn = sqlite3.connect(str(db))
    try:
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    finally:
        conn.close()


def test_真实迁移目录从空库一路能跑到最新版(tmp_path) -> None:
    """这条是"删库重来"的反证：只要迁移链能从头跑到尾，用户就不该被要求重建库。"""
    db = tmp_path / "catalog.db"
    engine = Engine(db)
    report = migrate(engine, backup_dir=tmp_path / "backups", migrations_dir=REAL_MIGRATIONS)
    newest = discover(REAL_MIGRATIONS)[-1].order
    assert report.to_version == newest == 8, \
        "水位必须停在迁移目录里的最新一版；这里同时是「版本号变了就要同步改 docs/DATABASE 与门禁」的哨兵"
    assert engine.integrity_check() == "ok"
    # 再跑一次必须什么都不做（幂等），否则重启会把同一迁移执行多遍
    again = migrate(engine, backup_dir=tmp_path / "backups", migrations_dir=REAL_MIGRATIONS)
    assert again.did_anything is False


def test_空库经迁移链建出的库把name排序交给索引(tmp_path) -> None:
    """**ISSUES I77** 的"甲"落在库里的唯一可见形状：0008 建的那条索引要被**查询规划器用上**。

    光验"索引在场"是不够的 —— 一条与排序表达式不同形的索引（`documents(name)` 少一个
    `COLLATE NOCASE`）名字照样对、`sqlite_master` 照样查得到，而每批取数仍然排一遍全表。
    所以这条同时钉两端：名字（文档与台账引用的就是它）与**产品那条 SQL 的执行计划**。
    取 SQL 的方式是**现拼**而不是抄字面量：它由 `SORTS["name"]` 与 `where_for_filter` 生成，
    与 `DocumentRepository.list_sorted` 逐字同源，排序口径哪天被人改掉，这条会跟着红 ——
    那正是"改了口径却没人发现每批又变成全表排序"的那件事。

    实测两种形状（空库即可复现，不必灌 8 万行；深库的读数在 `.probe_work/i77_0008_probe.log`）：
    有它 `['SCAN d USING INDEX ix_documents_name_ci']`，没有它或它不同形
    `['SCAN d', 'USE TEMP B-TREE FOR ORDER BY']`。
    """
    from pdfarchiver.db.repositories.documents import _COLS, SORTS, DocFilter, where_for_filter

    engine = Engine(tmp_path / "catalog.db")
    migrate(engine, backup_dir=tmp_path / "backups", migrations_dir=REAL_MIGRATIONS)
    conn = engine.connect()
    try:
        filters = DocFilter(include_missing=True)
        sql = (f"SELECT {_COLS} FROM documents d{where_for_filter(filters).sql_with()}"
               f" ORDER BY {SORTS['name']} LIMIT ? OFFSET ?")
        ddl = conn.execute("SELECT sql FROM sqlite_master WHERE type='index' AND name=?",
                           ("ix_documents_name_ci",)).fetchone()
        assert ddl is not None, "0008 建的那条索引不在库里（名字：ix_documents_name_ci）"
        plan = [row[3] for row in conn.execute("EXPLAIN QUERY PLAN " + sql, (50, 0)).fetchall()]
        assert "USE TEMP B-TREE FOR ORDER BY" not in plan, \
            f"浏览那一列又变成每批排一遍全表（计划：{plan}）—— 索引与排序口径不同形或已不在"
        assert "ix_documents_name_ci" in " ".join(plan), f"查询规划器没用上那条索引：{plan}"
    finally:
        conn.close()
        engine.close_thread_connection()


def test_迁移目录空时必须硬停而不是零迁移冒充成功(tmp_path) -> None:
    """`discover()` 对空目录返回 `[]` 是它自己的规矩（单测钉着），但 `migrate()` 不能把"零迁移"当成功。

    这不是假想：阶段 5 的冻结产物双击就打不开，根因是打包漏收 `migrations/*.py`，
    于是应用静默地一条迁移也没跑、一张表也没建，报错最后落在离根因八丈远的
    `seed_default_categories`（`no such table: app_settings`）。空发现必须在原地炸，
    并且**把它翻过的目录打进消息里** —— 冻结产物没有控制台，能远程诊断的只有那一行日志。
    """
    empty = tmp_path / "migrations"
    empty.mkdir()
    engine = Engine(tmp_path / "catalog.db")
    with pytest.raises(MigrationError) as e:
        migrate(engine, backup_dir=tmp_path / "backups", migrations_dir=empty)
    assert str(empty) in str(e.value), "错误消息必须带上被翻过的目录路径，否则远程看不懂崩在哪"
    assert not (tmp_path / "backups").exists(), "零迁移也不该留下一份「看起来像升级过」的快照"
    assert current_version(engine.connect()) == 0
    engine.close_thread_connection()


def test_升级后删掉正文行索引里不留幽灵行(old_db, tmp_path) -> None:
    """G10 的迁移侧：0002 建的三条触发器必须在"老库升级上来的文件"里同样生效。

    p1 实测漏写 `old.body` 时 SQLite **不报错**，只留下删不掉的幽灵行 ——
    而外部内容表上**没有免词的数数口径能抓到它**（见下一条注入的实测表），
    所以这条必须**拿词直接问索引**：删完再搜同一个词，命中数要归零。
    """
    engine, _ = old_db
    migrate(engine, backup_dir=tmp_path / "backups2", migrations_dir=REAL_MIGRATIONS)
    conn = engine.connect()
    try:
        conn.execute("INSERT INTO text_pages(doc_id, page_no, char_count, body, indexed_at)"
                     " VALUES(1, 1, 12, '人工智能行业年度报告', 1)")
        conn.commit()
        assert conn.execute("SELECT count(*) FROM content_fts WHERE content_fts MATCH '人工智能'").fetchone()[0] == 1
        conn.execute("DELETE FROM text_pages WHERE doc_id=1 AND page_no=1")
        conn.commit()
        assert conn.execute("SELECT count(*) FROM content_fts WHERE content_fts MATCH '人工智能'").fetchone()[0] == 0, \
            "G10：删掉的正文页必须从倒排里摘干净 —— 这条是带词的，才会红（见下一条注入）"
        check = TextRepository(engine).check_fts_consistency()
        assert check.aligned, check.describe()
    finally:
        conn.close()
        engine.close_thread_connection()


def test_G10仪表有没有牙_坏法注入实测三种口径(old_db, tmp_path) -> None:
    """反向注入（AGENTS.md：不会变红的断言直接删）：把 0002 的 `tx_pages_ad` 换成 p1 记过的那个坏写法，
    删一行正文，三种口径同时读数。数字全部来自本轮实测，写死在这里当"仪表的仪表"：

    | 口径 | 坏法生效后的读数 | 结论 |
    | --- | --- | --- |
    | `count(*) FROM content_fts` | 等于正文行数 | **天生瞎**：外部内容表的计数是从正文表枚举出来的 |
    | `WHERE rowid NOT IN (SELECT rowid FROM text_pages)` | 0 | **天生瞎**：同上，所以旧版 G10 用它等于没测 |
    | 带词 `MATCH` | 1 | **有牙**：倒排里那条还在，这就是幽灵 |
    | 带词 `MATCH` 再 JOIN 正文表 | 0 | 检索通路自带兜底，用户看不到幽灵，代价是索引体积与 bm25 排序 |

    这条不是"验产品对"，是"验上面那条断言抓得住东西"。哪天有人把 G10 改回数数，这条会先红。
    """
    engine, _ = old_db
    migrate(engine, backup_dir=tmp_path / "bad", migrations_dir=REAL_MIGRATIONS)
    conn = engine.connect()
    try:
        conn.execute("INSERT INTO text_pages(doc_id, page_no, char_count, body, indexed_at)"
                     " VALUES(1, 1, 12, '人工智能行业年度报告', 1)")
        conn.commit()
        conn.execute("DROP TRIGGER tx_pages_ad")
        conn.execute("CREATE TRIGGER tx_pages_ad AFTER DELETE ON text_pages BEGIN"
                     " INSERT INTO content_fts(content_fts, rowid, body) VALUES('delete', old.rowid, ''); END")
        conn.execute("DELETE FROM text_pages WHERE doc_id=1 AND page_no=1")
        conn.commit()

        check = TextRepository(engine).check_fts_consistency()
        assert check.pages == 0 == check.indexed == check.unindexed == check.stale_docsize, \
            "数数口径在坏法面前一片祥和（这就是它不能当 G10 的理由）：" + check.describe()
        ghost = conn.execute("SELECT count(*) FROM content_fts WHERE content_fts MATCH '人工智能'").fetchone()[0]
        assert ghost == 1, "带词的问法必须抓到那条幽灵，否则 G10 就没有牙了"
        surfaced = conn.execute(
            "SELECT count(*) FROM content_fts JOIN text_pages tp ON tp.rowid = content_fts.rowid"
            " WHERE content_fts MATCH '人工智能'").fetchone()[0]
        assert surfaced == 0, "检索通路 JOIN 正文表，幽灵不该进用户眼前"
    finally:
        conn.close()
        engine.close_thread_connection()
