"""p12 的反向注入自检 —— 从 `p12_consistency.py` 拆出的注入段（拆分时那份已贴 800 行红线，ISSUES I58）。

入口仍在 p12：`python tests/probes/p12_consistency.py --inject`，`main()` 里延迟导入本模块。
每条坏法都是"能骗过对应断言的写法"，逐条打进临时数据根，看那一条会不会红 ——
红 = 断言有约束力；不红 = 这条断言是摆设，按 AGENTS.md 直接删或改写。
C1 的坏法不单独注入：毁主库等于毁整个前提，而 C11 用的是同一个 `_health()`，那里注入就够。
C11 的「旧快照能打开但内部损坏」在默认口径下必须保持绿且明写（I98 乙的成本封顶），
而 `--c11-deep` 必须把同一份旧快照抓红 —— 两个方向都由 `_c11_scope_case` 守。

为什么 `from p12_consistency import …` 不成环：p12 顶层从不反向 import 本模块，只在
`main()` 里延迟导入；本模块运行时 p12 已经定义完。p12 作为 `__main__` 跑时这里会把同一份
代码再导入一次（模块名 `p12_consistency`），两边没有可变状态，用的是同一套函数定义。
"""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from pdfarchiver.config.paths import AppPaths  # noqa: E402
from pdfarchiver.fs.identity import identity_key, normalize_path  # noqa: E402
from p12_consistency import Row, _brief, _health, _ro, run_checks  # noqa: E402


INJECTIONS: list[tuple[str, str, str]] = [
    ("C0", "库停在旧版本，迁移目录却已经更靠前",
     "DELETE FROM schema_version; INSERT INTO schema_version(version, applied_at) VALUES(2, 1);"),
    ("C2", "path_key 与 identity_key(path) 不再同口径",
     "UPDATE documents SET path_key='h:/x/篡改.pdf' WHERE id=1;"),
    ("C2", "把唯一索引去掉后直接写出重复 path_key",
     "DROP INDEX ux_documents_path_key;"
     " INSERT INTO documents(path, path_key, name, ext, size_bytes, mtime_ns, created_at, updated_at)"
     " SELECT path, path_key, name, ext, size_bytes, mtime_ns, created_at, updated_at"
     " FROM documents WHERE id=1;"),
    ("C4", "delete 触发器的 rowid 列写错：花名册少一条、又多挂一条（正文与索引双向两张皮）",
     "DROP TRIGGER tx_pages_ad;"
     " CREATE TRIGGER tx_pages_ad AFTER DELETE ON text_pages BEGIN"
     "  INSERT INTO content_fts(content_fts, rowid, body) VALUES('delete', old.doc_id, old.body);"
     " END;"
     " DELETE FROM text_pages WHERE doc_id=1 AND page_no=2;"),
    ("C4", "正文行绕过触发器进库（等于少一条索引）",
     "DROP TRIGGER tx_pages_ai;"
     " INSERT INTO text_pages(doc_id, page_no, char_count, body, indexed_at)"
     " VALUES(1, 40, 4, '漏索引', 1);"),
    ("C5", "char_count 与正文字数分家",
     "UPDATE text_pages SET char_count=99999 WHERE doc_id=1 AND page_no=1;"),
    ("C5", "OCR 正文丢了版本号",
     "UPDATE text_pages SET ocr_version=NULL WHERE doc_id=2 AND page_no=1;"),
    # ISSUES I90 乙：char_count 写成真实 Python len(3)，所以「字数分家」不红，只有新加的 NUL 子检查红。
    ("C5", "正文夹着 U+0000（字数没写错，但 SQL 侧 length/substr 遇 NUL 即截断，入库前该剥掉）",
     "INSERT INTO text_pages(doc_id, page_no, char_count, body, indexed_at)"
     " VALUES(1, 3, 3, 'A' || char(0) || 'B', 1);"),
    # ISSUES I117 甲：C5 只对「OCR 页级完成标记」豁免；原生正文写空串仍是零信息行，必须红。
    ("C5", "原生正文页写成空串（不是 OCR 页级标记，豁免不覆盖它）",
     "INSERT INTO text_pages(doc_id, page_no, source_kind, char_count, body, indexed_at)"
     " VALUES(1, 41, 'native', 0, '', 1);"),
    ("C6", "text_status 写成库里根本没有的值",
     "UPDATE documents SET text_status='no_text' WHERE id=1;"),
    ("C6", "队列 state 写成口径外的值",
     "INSERT INTO processing_jobs(kind, doc_id, state, created_at) VALUES('index', 1, 'in-flight', 1);"),
    ("C7", "向量状态写成口径外的值（写入方 = VectorService，非 na 有真来源）",
     "UPDATE documents SET vector_status='vectorized' WHERE id=1;"),
    ("C8", "file_operations.status 写成口径外的值",
     "INSERT INTO file_operations(kind, status, created_at) VALUES('move', 'cancelled', 1);"),
    ("C9", "没有进程却留着一条 running",
     "INSERT INTO processing_jobs(kind, doc_id, state, created_at) VALUES('index', 1, 'running', 1);"),
    ("C10", "分类 name_path 与父链不一致",
     "UPDATE categories SET name_path='胡说' WHERE parent_id IS NOT NULL;"),
    ("C11", "最新快照能打开、版本读得动，但整库结构坏了（体检那条路必须红）",
     "__corrupt_newest_internals__"),
    ("C11", "最新快照被写成打不开的样子",
     "__corrupt_backup__"),
    ("C11", "旧快照被写成打不开的样子（每份仍要开库读版本）",
     "__corrupt_old_backup__"),
    ("C12", "库里记的页数比实际入库页码还小",
     "UPDATE documents SET page_count=1 WHERE id=1;"),
    # ISSUES I89 丙：首字母大写 → identity_key(root_key) 对不上，C13 必须点名。
    # 只翻 C13 不翻 C3：C3 的子树 LIKE 对 ASCII 大小写不敏感，故 `C:/…/%` 仍命中 `c:/…` 的 path_key。
    ("C13", "监测根根键写成原生 Windows 大小写（子树查询按 identity_key 前缀会认不出）",
     "UPDATE monitored_roots SET root_key = upper(substr(root_key,1,1)) || substr(root_key,2);"),
    ("C3", "盘上多出一份 PDF 而库里没有（漏索引）",
     "__add_file_on_disk__"),
    ("C3", "文件从盘上没了而库里没标缺失",
     "__delete_file_on_disk__"),
]


def _fixture(root: Path) -> Path:
    """现场搭一个小数据根：真迁移 + 真默认分类 + 3 份 PDF（两份有正文，一份 OCR 正文）。"""
    from pdfarchiver.db.engine import Engine
    from pdfarchiver.db.migrate import migrate
    from pdfarchiver.db.repositories.catalog import CatalogRepository
    from pdfarchiver.db.repositories.settings import SettingsRepository
    from pdfarchiver.services.default_catalog import seed_default_categories

    corpus = root / "corpus"
    corpus.mkdir(parents=True, exist_ok=True)
    data_root = root / "data_root"
    for i in range(1, 4):
        (corpus / f"报告{i}.pdf").write_bytes(b"%PDF-1.4\n%%EOF\n")

    engine = Engine(data_root / "data" / "catalog.db")
    # 快照目录按产品口径给（`<root>/data/backups`），fixture 与 c11_backups 用同一个来源
    backups = AppPaths.resolve(data_root).backups_dir
    migrate(engine, backup_dir=backups)
    seed_default_categories(CatalogRepository(engine), SettingsRepository(engine))
    conn = engine.connect()
    conn.execute("INSERT INTO monitored_roots(root_path, root_key, label, enabled, exclude_globs,"
                 " created_at, updated_at) VALUES(?,?,?,1,'[]',1,1)",
                 (normalize_path(corpus), identity_key(corpus), "注入语料"))
    for i in range(1, 4):
        path = normalize_path(corpus / f"报告{i}.pdf")
        conn.execute(
            "INSERT INTO documents(path, path_key, name, ext, size_bytes, mtime_ns, page_count,"
            " parse_status, text_status, fts_status, ocr_status, vector_status, created_at, updated_at)"
            " VALUES(?,?,?,?,?,1,3,'ok','native','done','na','na',1,1)",
            (path, identity_key(path), f"报告{i}.pdf", "pdf", 13))
    conn.execute("INSERT INTO text_pages(doc_id, page_no, char_count, body, indexed_at)"
                 " VALUES(1, 1, 6, '人工智能报告', 1)")
    conn.execute("INSERT INTO text_pages(doc_id, page_no, char_count, body, indexed_at)"
                 " VALUES(1, 2, 4, '产业趋势', 2)")
    conn.execute("INSERT INTO text_pages(doc_id, page_no, source_kind, char_count, body, indexed_at,"
                 " ocr_version) VALUES(2, 1, 'ocr', 5, '扫描件文字', 1, 'probe-v1')")
    conn.commit()
    conn.close()
    engine.snapshot_to(backups / "fixture-snapshot.db")
    engine.close_thread_connection()
    return data_root


def _break_rootpage(db: Path) -> None:
    """让库仍能打开、schema_version 仍读得动，但 integrity_check 必报错：
    把 documents 的根页指到 categories 的根页（同一页被两处引用）。"""
    conn = sqlite3.connect(str(db))
    try:
        donor = conn.execute("SELECT rootpage FROM sqlite_master"
                             " WHERE type='table' AND name='categories'").fetchone()[0]
        conn.execute("PRAGMA writable_schema=ON")
        conn.execute("UPDATE sqlite_master SET rootpage=? WHERE type='table' AND name='documents'",
                     (donor,))
        conn.commit()
    finally:
        conn.close()


def _apply(name: str, sql: str, data_root: Path) -> str:
    """把一条坏法打进副本。需要动文件系统的坏法在这里处理，返回注入说明。"""
    corpus = data_root.parent / "corpus"
    if sql == "__corrupt_backup__":
        victim = max(AppPaths.resolve(data_root).backups_dir.glob("*.db"),
                     key=lambda p: (p.stat().st_mtime_ns, p.name))
        victim.write_bytes(b"this is not a sqlite database at all" * 40)
        return f"（把最新快照 {victim.name} 写成非 sqlite 内容）"
    if sql == "__corrupt_newest_internals__":
        victim = max(AppPaths.resolve(data_root).backups_dir.glob("*.db"),
                     key=lambda p: (p.stat().st_mtime_ns, p.name))
        _break_rootpage(victim)
        return f"（把 {victim.name} 的 documents 根页指到 categories，库仍能打开）"
    if sql == "__corrupt_old_backup__":
        ordered = sorted(AppPaths.resolve(data_root).backups_dir.glob("*.db"),
                         key=lambda p: (p.stat().st_mtime_ns, p.name))
        victim = ordered[-2]  # 最新一份（fixture-snapshot.db）不动，只毁次新
        victim.write_bytes(b"this is not a sqlite database at all" * 40)
        return f"（把旧快照 {victim.name} 写成非 sqlite 内容，最新一份不动）"
    if sql == "__add_file_on_disk__":
        (corpus / "漏索引新文件.pdf").write_bytes(b"%PDF-1.4\n%%EOF\n")
        return "（盘上新增一份 PDF，库里没有）"
    if sql == "__delete_file_on_disk__":
        (corpus / "报告3.pdf").unlink()
        return "（删掉盘上一份文件，而库里那条 missing_since 仍为 NULL）"
    conn = sqlite3.connect(str(data_root / "data" / "catalog.db"))
    try:
        conn.executescript(sql)
        conn.commit()
    finally:
        conn.close()
    return ""


def _by_code(rows: list[Row]) -> dict[str, list[Row]]:
    out: dict[str, list[Row]] = {}
    for row in rows:
        out.setdefault(row.code.split("·")[0], []).append(row)
    return out


def _c11_scope_case(root: Path) -> tuple[bool, str]:
    """I98 乙的口径边界 + `--c11-deep` 的反向证明：旧快照「能打开但内部损坏」在默认口径下
    保持绿（成本封顶的代价，必须明写），而 `--c11-deep` 必须把同一份旧快照抓红 ——
    两个方向都验，这个开关才不是摆设。"""
    data_root = _fixture(root)
    backups = AppPaths.resolve(data_root).backups_dir
    newest = max(backups.glob("*.db"), key=lambda p: (p.stat().st_mtime_ns, p.name))
    old = backups / "older-snapshot.db"
    old.write_bytes(newest.read_bytes())
    _break_rootpage(old)
    # 必须放在 _break_rootpage 之后：写库会把 mtime 刷成现在，否则它会被当成「最新一份」
    stamp = newest.stat().st_mtime - 60
    os.utime(old, (stamp, stamp))
    conn = _ro(old)
    try:
        damaged, _ = _health(conn, old.name)
    finally:
        conn.close()
    # 走 run_checks 而不是直接调 c11_backups：验的是 CLI 那条共用路径（argparse → run_checks → C11）
    base = data_root / "data" / "catalog.db"
    rows = _by_code(run_checks(base, data_root, walk=False, alive_check=False))
    deep_rows = _by_code(run_checks(base, data_root, walk=False, alive_check=False, c11_deep=True))
    row, deep = rows["C11"][0], deep_rows["C11"][0]
    disclosed = "仅开库读版本" in row.measured and "I98" in row.measured
    snap_count = len(list(backups.glob("*.db")))
    deep_named = (deep.label == "全部快照整库体检（--c11-deep）"
                  and f"整库体检 {snap_count} 份" in deep.measured)
    ok = row.ok and damaged is False and disclosed and not deep.ok and deep_named
    return ok, (f"旧快照 integrity_check={'红' if damaged is False else '绿（注入没生效）'}"
                f"｜默认 C11={'绿' if row.ok else '红'}｜明写={disclosed}"
                f"｜--c11-deep={'红（抓到了）' if not deep.ok else '绿（没抓到）'}"
                f"｜deep 读数={'对' if deep_named else '不对'}")


def inject_mode(out: Path | None) -> int:
    work = Path(tempfile.mkdtemp(prefix="p12_inject_"))
    caught: list[str] = []
    missed: list[str] = []
    try:
        base = _fixture(work / "baseline")
        baseline = run_checks(base / "data" / "catalog.db", base, walk=True, alive_check=False)
        print("  基线（干净数据根）：" + " ".join(f"{r.code}{r.mark}" for r in baseline))
        dirty = [r for r in baseline if not r.ok and not r.unverified]
        if dirty:
            print("  基线本身就不干净，注入判定全部作废："
                  + "；".join(f"{r.code} {r.measured}" for r in dirty))
            return 1
        for idx, (code, name, sql) in enumerate(INJECTIONS, start=1):
            case_root = work / f"case{idx}"
            data_root = _fixture(case_root)
            note = _apply(name, sql, data_root)
            rows = _by_code(run_checks(data_root / "data" / "catalog.db", data_root,
                                       walk=True, alive_check=False))
            hit = [r for r in rows.get(code, []) if not r.ok]
            (caught if hit else missed).append(f"{code} ← {name}")
            print(f"  {'抓到' if hit else '漏了'}  {code} ← {name} {note}")
            if not hit:
                print("        注入后该条仍是："
                      + _brief([r.measured for r in rows.get(code, [])] or ["（这条根本没跑）"]))
        scope_ok, scope_note = _c11_scope_case(work / "scope")
        print(f"  {'守住' if scope_ok else '没守住'}  口径边界 ← 默认不体检旧快照、"
              f"--c11-deep 必须抓红 {scope_note}")
        total = len(INJECTIONS)
        print(f"\n  注入自检：抓到 {len(caught)}/{total} 条坏法｜"
              f"口径边界 {1 if scope_ok else 0}/1（默认明写 + deep 抓红）")
        if missed:
            print("  没抓到的断言（没有约束力，该删或改写）：" + "；".join(missed))
        if not scope_ok:
            print("  口径边界没守住：要么默认口径没明写，要么 --c11-deep 没抓到损坏的旧快照")
        if out:
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps({"caught": caught, "missed": missed, "total": total,
                                       "c11_scope_ok": scope_ok},
                                      ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"  INFO 结果已写出 {out}")
        print("VERDICT: " + (f"ALL GREEN（{len(caught)}/{total} + 口径边界 1/1）"
                             if not missed and caught and scope_ok
                             else f"RED（漏了 {len(missed)} 条坏法"
                                  + ("" if scope_ok else "，口径边界没守住") + "）"))
        return 0 if not missed and caught and scope_ok else 1
    finally:
        shutil.rmtree(work, ignore_errors=True)
