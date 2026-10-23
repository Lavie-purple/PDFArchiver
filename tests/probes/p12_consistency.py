"""P12 文件与数据库一致性核查 —— 交付阶段需求第 4 条（"检查文件与数据库的一致性"）的工具化答案。

跑法：
    python tests/probes/p12_consistency.py                      # 查默认数据根（%LOCALAPPDATA%\\PdfArchiver）
    python tests/probes/p12_consistency.py --data-root <路径>    # 查指定数据根（比如冻结冒烟留下的现场）
    python tests/probes/p12_consistency.py --inject             # 反向注入自检（注入段在 p12_inject.py）
    python tests/probes/p12_consistency.py --c11-deep           # C11 对每份快照都跑整库体检（慢，逐份计时）
    python tests/probes/p12_consistency.py --no-file-walk       # 跳过盘上遍历 —— 整场会判 RED，见下面第 3 条

三条规矩：

1. **只读**。全程 `file:...?mode=ro` 打开库，不写用户的库、不动用户的文件（AGENTS.md：
   不做不可逆操作）。唯一会写的东西是 `--inject` 模式下临时目录里的副本。
   应用正在跑时 WAL 可能要恢复，只读会打不开 —— 那时脚本原样把这句话打给你，不改库。
2. **对账用产品自己的口径**，不另写一套：盘上有什么 = `fs/scanner.iter_tree` +
   `fs/exclude.Exclusions`；"属于某个监测根的子树" = 复用仓储里那条
   `path_key LIKE like_prefix(root_key) ESCAPE '\\'`；状态字段的允许值全部 import 自
   写这些字段的模块。两套口径的探针第二天就会和软件吵架，那时候它已经不说明任何问题。
3. **未验 ≠ 通过**。凡是因环境而没跑的条目（`--no-file-walk` 跳过的遍历、应用还在跑时的
   队列残留检查、一份快照都没有的备份目录）都显式印成「未验」，并让整场门禁变红。
   这个调子是阶段 5 定下的：跳过的真引擎测试一条也没验。

十四条对账：

    C0  水位停在迁移目录里的最新版          C6  状态列取值都在口径内
    C1  库自身健康（integrity / fk_check）   C7  向量状态取值都在口径内（产品里没人推进它）
    C2  路径唯一性与 path_key 口径           C8  文件操作状态取值都在口径内
    C3  盘上文件 ↔ 库里主记录 双向对账       C9  无进程时队列里不许有 running 残留
    C4  正文表 ↔ 索引花名册 双向对账       C10 分类树父链可达、无环、name_path 一致
                                          （倒排幽灵免词测不到，见 c4_fts 说明）
    C5  正文页自洽（字数/来源/OCR 版本）     C11 最新快照整库体检（--c11-deep 逐份）
    C12 正文页页码不超过库里记的页数         C13 监测根根键与 identity_key 同口径

C7/C8 是反伪装用的：阶段 6 已交付（C7 换成真口径，见 `c7_vector_domain` 注释），阶段 4 已交付
（C8 换成真口径，见 `c8_op_domain` 注释）。这两条在对应阶段真交付时同步改成了该阶段的口径。

耗时提示：C3 要真走一遍目录树（真实语料 7,768 份/202 万页那次是分钟级），C11 的整库
`integrity_check`（与库大小同量级）默认只跑最新一份快照，其余快照只开库读版本 —— 每次迁移
都会多一份 12GB 级快照，逐份体检会把真根核查从分钟级抬到小时级（**ISSUES I98**）；要逐份
体检就显式加 `--c11-deep`（跑前先看快照份数）。想快就先 `--no-file-walk`，但那时它不算验过。
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from pdfarchiver.config.paths import AppPaths  # noqa: E402
from pdfarchiver.db.migrations import discover  # noqa: E402
from pdfarchiver.db.models import VECTOR_STATUSES, OP_STATUSES, ITEM_STATES  # noqa: E402
from pdfarchiver.db.repositories.documents import SEARCHABLE_STATUSES  # noqa: E402
from pdfarchiver.db.repositories.jobs import KINDS, STATES  # noqa: E402
from pdfarchiver.db.sqltext import like_prefix  # noqa: E402
from pdfarchiver.fs.exclude import Exclusions  # noqa: E402
from pdfarchiver.fs.identity import identity_key  # noqa: E402
from pdfarchiver.fs.scanner import KIND_ERROR, KIND_EXCLUDED, KIND_OTHER, KIND_PDF, iter_tree  # noqa: E402
from pdfarchiver.parsing.classify import OCR_STATUSES, TEXT_STATUSES  # noqa: E402
from pdfarchiver.services.default_catalog import DEFAULT_CATEGORY_TEMPLATE  # noqa: E402
from _timed import breakdown, timed  # noqa: E402 同级模块：逐条计时（见 _timed.py）

REAL_MIGRATIONS = REPO / "src" / "pdfarchiver" / "db" / "migrations"

# 允许值一律取自"写这个字段的那一处"，不在探针里另立口径：
#   text_status ← parsing/classify.TEXT_STATUSES（"还没解析过"由扫描层写 pending）
#   parse_status ← services/index_service._parse_status（ok/degraded/failed）+ 扫描层的 pending
#   fts_status   ← db/repositories/documents.SEARCHABLE_STATUSES
TEXT_LEGAL = frozenset(TEXT_STATUSES) | {"pending"}
PARSE_LEGAL = frozenset({"pending", "ok", "degraded", "failed"})
OCR_LEGAL = frozenset(OCR_STATUSES)
VECTOR_LEGAL = frozenset(VECTOR_STATUSES)   # 阶段 6 已交付，口径取 `db/models.VECTOR_STATUSES`
DOCS_UNDER_ROOT_SQL = "SELECT path_key, missing_since FROM documents WHERE path_key LIKE ? ESCAPE '\\'"


@dataclass
class Row:
    code: str
    label: str
    ok: bool
    measured: str
    unverified: bool = False

    @property
    def mark(self) -> str:
        return "未验" if self.unverified else ("绿" if self.ok else "红")

    def render(self) -> str:
        return f"  {self.mark}  {self.code}  {self.label}\n        {self.measured}"


def _ro(db: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _scalar(conn: sqlite3.Connection, sql: str, *args) -> object:
    return conn.execute(sql, args).fetchone()[0]


def _brief(items, limit: int = 3) -> str:
    return " ｜ ".join(str(x) for x in list(items)[:limit])


# ——————————————————————————————————————————— 十二条对账 ———————————————————————————————————————————

def c0_version(conn: sqlite3.Connection) -> Row:
    newest = discover(REAL_MIGRATIONS)[-1].order
    at = int(_scalar(conn, "SELECT coalesce(max(version), 0) FROM schema_version"))
    return Row("C0", "水位停在迁移目录里的最新版", at == newest,
               f"库里 v{at}｜迁移目录最新 v{newest}"
               f"｜迁移清单 {[m.label for m in discover(REAL_MIGRATIONS)]}")


def _health(conn: sqlite3.Connection, what: str) -> tuple[bool, str]:
    """打开来数一遍结构完整性。C1 与 C11 共用它 —— 所以 C11 的注入同时证明这条有约束力。"""
    try:
        integrity = [r[0] for r in conn.execute("PRAGMA integrity_check").fetchall()]
        fks = [tuple(r) for r in conn.execute("PRAGMA foreign_key_check").fetchall()]
    except sqlite3.DatabaseError as exc:
        return False, f"{what} 读不动：{type(exc).__name__}: {exc}"
    if integrity == ["ok"] and not fks:
        return True, "integrity_check=ok｜foreign_key_check 0 条"
    return False, (f"{what}：integrity_check={_brief(integrity)}｜外键违规 {len(fks)} 条 {_brief(fks)}")


def c1_health(conn: sqlite3.Connection) -> Row:
    ok, measured = _health(conn, "主库")
    return Row("C1", "库自身健康（integrity_check 与外键）", ok, measured)


def c2_path_keys(conn: sqlite3.Connection) -> Row:
    total = int(_scalar(conn, "SELECT count(*) FROM documents"))
    distinct = int(_scalar(conn, "SELECT count(DISTINCT path_key) FROM documents"))
    mismatched = [r["path"] for r in conn.execute("SELECT path, path_key FROM documents")
                  if identity_key(r["path"]) != r["path_key"]]
    problems = []
    if distinct != total:
        problems.append(f"{total} 行只有 {distinct} 个不同 path_key —— 唯一性被绕过过")
    if mismatched:
        problems.append(f"{len(mismatched)} 行的 path_key 不等于 identity_key(path)"
                        f"，例：{_brief(mismatched)}")
    return Row("C2", "主记录路径唯一、path_key 与 identity_key 同口径", not problems,
               f"主记录 {total} 条｜" + ("；".join(problems) if problems else "两项全部一致"))


def c3_files_vs_db(conn: sqlite3.Connection, *, walk: bool) -> list[Row]:
    roots = [dict(r) for r in conn.execute(
        "SELECT root_path, root_key, exclude_globs, last_full_scan_at, enabled, label"
        " FROM monitored_roots ORDER BY root_path")]
    if not roots:
        return [Row("C3", "盘上文件 ↔ 库里主记录 双向对账", True,
                    "库里一个监测根都没有，无账可对（首启后还没扫描就是这种状态）")]
    rows: list[Row] = []
    for root in roots:
        name = Path(root["root_path"]).name or root["root_path"]
        code = f"C3·{name}"
        if not root["enabled"]:
            rows.append(Row(code, "该根已停用，不参与对账", True,
                            f"{root['root_path']} enabled=0"))
            continue
        if not walk:
            rows.append(Row(code, "盘上文件 ↔ 库里主记录 双向对账", False,
                            f"被 --no-file-walk 跳过：{root['root_path']} 一个字也没核对",
                            unverified=True))
            continue
        if not Path(root["root_path"]).is_dir():
            rows.append(Row(code, "该根不在这台机器上，未对账（外置盘/网络盘掉线？）", True,
                            f"{root['root_path']} 不存在；库里该子树条目按台账保留"
                            f"（上次全量扫描 last_full_scan_at={root['last_full_scan_at']}）"))
            continue
        exclusions = Exclusions.of(json.loads(root["exclude_globs"] or "[]"))
        on_disk: set[str] = set()
        tally = {KIND_EXCLUDED: 0, KIND_OTHER: 0, KIND_ERROR: 0}
        errors: list[str] = []
        for item in iter_tree(root["root_path"], exclusions):
            if item.kind == KIND_PDF:
                on_disk.add(identity_key(item.path))
            else:
                tally[item.kind] += 1
                if item.kind == KIND_ERROR:
                    errors.append(item.detail)
        db_rows = {r["path_key"]: r["missing_since"] for r in
                   conn.execute(DOCS_UNDER_ROOT_SQL, (like_prefix(root["root_key"]),))}
        not_in_db = sorted(on_disk - set(db_rows))
        gone_unmarked = sorted(k for k, m in db_rows.items() if m is None and k not in on_disk)
        back_but_marked = sorted(k for k, m in db_rows.items() if m is not None and k in on_disk)
        problems = []
        if not_in_db:
            problems.append(f"盘上有、库里没有（漏索引）{len(not_in_db)} 个，例：{_brief(not_in_db)}")
        if gone_unmarked:
            problems.append(f"库里有、盘上没了却没标 missing_since（漏标缺失）{len(gone_unmarked)} 个，"
                            f"例：{_brief(gone_unmarked)}")
        if back_but_marked:
            problems.append(f"文件已回来但 missing_since 没清 {len(back_but_marked)} 个，"
                            f"例：{_brief(back_but_marked)}")
        marked = sum(1 for m in db_rows.values() if m is not None)
        rows.append(Row(code, "盘上文件 ↔ 库里主记录 双向对账", not problems,
                        f"盘上 PDF {len(on_disk)}｜该子树主记录 {len(db_rows)}（已标缺失 {marked}）｜"
                        f"排除 {tally[KIND_EXCLUDED]}｜非 PDF {tally[KIND_OTHER]}｜读不动的目录 "
                        f"{tally[KIND_ERROR]}"
                        f"{('，例：' + _brief(errors)) if errors else ''}"
                        + ("" if not problems else " ── " + "；".join(problems))))
    return rows


def c4_fts(conn: sqlite3.Connection) -> Row:
    """正文表 ↔ 索引花名册（`content_fts_docsize`）双向对账。

    四种坏法各实测过一遍（`tests/probes/p14_fts_instrument.py`，常驻探针），结论写在这儿免得下次再猜：
      · `count(*) FROM content_fts` 是从**正文表**枚举出来的，永远等于正文行数 → 不能当"索引里有几条"用；
      · 免词能测的只有 docsize 双向：漏索引（正文有、花名册没有）与残留（花名册有、正文没有）；
      · 倒排里的**幽灵条目**（p1 那个 delete 触发器列清单写错的坏法）在这里**测不到** ——
        外部内容表没有免词口径：空前缀 `MATCH ''` 报语法错，`integrity-check` 四种坏状态全部"通过"。
        所以 C4 绿只说明"没漏索引、花名册没残留"，不说明"倒排里没有幽灵"；
        后者由 `tests/guards/test_migrations.py` 里那条**带词**的 G10 注入守着，
        且检索通路每次 `JOIN text_pages`，幽灵进不了用户眼前。
    """
    pages = int(_scalar(conn, "SELECT count(*) FROM text_pages"))
    indexed = int(_scalar(conn, "SELECT count(*) FROM content_fts_docsize"))
    unindexed = int(_scalar(conn, "SELECT count(*) FROM text_pages tp"
                                  " WHERE tp.rowid NOT IN (SELECT id FROM content_fts_docsize)"))
    stale = int(_scalar(conn, "SELECT count(*) FROM content_fts_docsize"
                              " WHERE id NOT IN (SELECT rowid FROM text_pages)"))
    ok = unindexed == 0 and stale == 0 and pages == indexed
    return Row("C4", "正文表 ↔ 索引花名册 双向对账", ok,
               f"正文 {pages} 行｜花名册 {indexed} 行｜漏索引 {unindexed}｜花名册残留 {stale}"
               + ("" if ok else " ── 索引与正文两张皮，跑一次全文索引重建再对账")
               + "｜本口径测不到倒排幽灵（免词口径全瞎，由带词的 G10 守着）")


def c5_pages(conn: sqlite3.Connection) -> Row:
    """ISSUES I90 甲：字数口径必须与写入口径同源 —— 产品用 Python `len(body)`（models.py:141、
    ocr_service.py:400），探针原来用 SQLite `length(body)`。正文夹 U+0000 时 SQLite 遇 NUL 即截断，
    两个数分家 1,310 行，而**没有一行字数真的写错** —— 报的是探针自己的第四个 length 函数，不是缺陷。
    改成：先用 SQL `char_count <> length(body)` 圈候选（Python len 与 SQL len 只在含 NUL 时才不等，
    而产品写的 char_count 恒等于 Python len，所以真正字数分家的行必然也进候选 → 候选集是安全超集，
    不会漏报），再把候选行取回 Python 侧用 `len(body)` 定生死。顺带数出正文里夹 NUL 的行（**I90 乙**
    入库前该剥掉、真库那批该重写，这条让它在 p12 上如实红，而不是藏在字数红灯背后）。
    """
    char_bad = nul_bad = 0
    char_examples: list[str] = []
    for r in conn.execute("SELECT doc_id, page_no, char_count, body FROM text_pages"
                          " WHERE char_count <> length(body)"):
        if "\x00" in r["body"]:
            nul_bad += 1  # 字数没写错（len==char_count），但正文夹着 NUL
        if r["char_count"] != len(r["body"]):
            char_bad += 1
            char_examples.append(f"doc{r['doc_id']}p{r['page_no']} 记 {r['char_count']} 实际 {len(r['body'])}")
    kind_bad = int(_scalar(conn, "SELECT count(*) FROM text_pages"
                                 " WHERE source_kind NOT IN ('native','ocr')"))
    ocr_no_version = int(_scalar(conn, "SELECT count(*) FROM text_pages"
                                       " WHERE source_kind='ocr' AND ocr_version IS NULL"))
    native_with_version = int(_scalar(conn, "SELECT count(*) FROM text_pages"
                                            " WHERE source_kind='native' AND ocr_version IS NOT NULL"))
    empty_body = int(_scalar(conn, "SELECT count(*) FROM text_pages WHERE body=''"))
    total = int(_scalar(conn, "SELECT count(*) FROM text_pages"))
    ocr_rows = int(_scalar(conn, "SELECT count(*) FROM text_pages WHERE source_kind='ocr'"))
    problems = []
    if char_bad:
        problems.append(f"{char_bad} 行的 char_count 与 Python len(body) 分家（状态页的字数是假的），"
                        f"例：{_brief(char_examples)}")
    if nul_bad:
        problems.append(f"{nul_bad} 行正文夹着 U+0000（SQL 侧 length/substr 会遇 NUL 即截断，"
                        f"入库前该剥掉 —— 见 ISSUES I90 乙）")
    if kind_bad:
        problems.append(f"{kind_bad} 行的 source_kind 不在 native/ocr 之内")
    if ocr_no_version:
        problems.append(f"{ocr_no_version} 行 OCR 正文没有 ocr_version —— 幂等判据看不见它，"
                        f"下次会把同一页再烧一遍")
    if native_with_version:
        problems.append(f"{native_with_version} 行原生正文带着 ocr_version（来源口径混了）")
    if empty_body:
        problems.append(f"{empty_body} 行正文是空串（索引里养着零信息行）")
    return Row("C5", "正文页自洽（字数口径 / 无 NUL / 来源 / OCR 版本列）", not problems,
               f"正文 {total} 页（其中 ocr {ocr_rows}）｜"
               + ("；".join(problems) if problems else "六项全部自洽"))


def _domain_problems(conn: sqlite3.Connection, table: str, column: str, legal: frozenset[str]) -> list[str]:
    marks = ",".join("?" * len(legal))
    n = int(_scalar(conn, f"SELECT count(*) FROM {table} WHERE {column} NOT IN ({marks})", *sorted(legal)))
    if not n:
        return []
    vals = [r[0] for r in conn.execute(
        f"SELECT DISTINCT {column} FROM {table} WHERE {column} NOT IN ({marks})", sorted(legal))]
    return [f"{table}.{column} 有 {n} 行落在口径外（出现值 {vals}｜允许值 {sorted(legal)}）"]


def c6_status_domains(conn: sqlite3.Connection) -> Row:
    bad: list[str] = []
    for column, legal in (("text_status", TEXT_LEGAL), ("parse_status", PARSE_LEGAL),
                          ("ocr_status", OCR_LEGAL), ("fts_status", SEARCHABLE_STATUSES)):
        bad += _domain_problems(conn, "documents", column, frozenset(legal))
    bad += _domain_problems(conn, "processing_jobs", "state", frozenset(STATES))
    bad += _domain_problems(conn, "processing_jobs", "kind", frozenset(KINDS))
    total = int(_scalar(conn, "SELECT count(*) FROM documents"))
    return Row("C6", "状态字段取值都在口径内（可计数的硬条件）", not bad,
               f"主记录 {total} 条｜" + ("；".join(bad) if bad else "主记录四个状态列 + 队列两列全部合法"))


def c7_vector_domain(conn: sqlite3.Connection) -> Row:
    """阶段 6 的真口径：`vector_status` 取值必须在 `VECTOR_STATUSES` 内。

    **谁推进它**：全仓 grep 确认没有任何产品代码推进 `vector_status`（只有 `Document` 默认值
    `na` 落库），所以它是**读数**不是判定；非 `na` 只可能来自测试夹具或手工写入（**ISSUES I63**）。
    """
    bad = _domain_problems(conn, "documents", "vector_status", VECTOR_LEGAL)
    dist = {r[0]: r[1] for r in conn.execute(
        "SELECT vector_status, count(*) FROM documents GROUP BY vector_status").fetchall()}
    non_na = sum(n for v, n in dist.items() if v != "na")
    return Row("C7", "向量状态取值都在口径内（产品里没有任何代码推进它，见 ISSUES I63）",
               not bad,
               f"非 na 的行 {non_na} 条｜分布 {dist or '空'}｜"
               + (bad[0] if bad else "全部合法（产品里没人写它，所以恒为 na 或测试夹具值）"))


def c8_op_domain(conn: sqlite3.Connection) -> Row:
    bad: list[str] = []
    op_dist = {r[0]: r[1] for r in conn.execute(
        "SELECT status, count(*) FROM file_operations GROUP BY status")}
    for v in op_dist:
        if v not in OP_STATUSES:
            bad.append(f"file_operations.status='{v}' 不在口径 {OP_STATUSES}")
    item_dist = {r[0]: r[1] for r in conn.execute(
        "SELECT state, count(*) FROM operation_items GROUP BY state")}
    for v in item_dist:
        if v not in ITEM_STATES:
            bad.append(f"operation_items.state='{v}' 不在口径 {ITEM_STATES}")
    return Row("C8", "文件操作状态取值都在口径内（阶段 4 已交付，口径出处：operations.py 模块 docstring）",
               not bad,
               f"file_operations 分布 {op_dist or '空'}｜operation_items 分布 {item_dist or '空'}｜"
               + (bad[0] if bad else "全部合法"))


def c9_queue(conn: sqlite3.Connection, alive: tuple[bool, str]) -> Row:
    label = "无进程时队列里不许有 running 残留"
    app_alive, note = alive
    if app_alive:
        return Row("C9", label, False,
                   f"检测到应用在跑（{note}）—— 这条要在应用停止后才查得准，本次未验",
                   unverified=True)
    dist = {r[0]: r[1] for r in conn.execute(
        "SELECT state, count(*) FROM processing_jobs GROUP BY state")}
    running = dist.get("running", 0)
    return Row("C9", label, running == 0,
               f"running {running}（必须为 0，否则上次退出没回收）｜"
               f"各状态分布 {dist or '队列是空的'}｜"
               + ("残留会让恢复流程以为还在跑，watchdog 与限量都会跟着算错" if running else "干净"))


def c10_tree(conn: sqlite3.Connection) -> Row:
    nodes = {r["id"]: dict(r) for r in conn.execute(
        "SELECT id, name, parent_id, name_path FROM categories")}
    problems: list[str] = []
    orphans = [n["name_path"] for n in nodes.values()
               if n["parent_id"] is not None and n["parent_id"] not in nodes]
    if orphans:
        problems.append(f"{len(orphans)} 个节点的父节点不存在，例：{_brief(orphans)}")
    cycles: list[str] = []
    for node in nodes.values():
        seen = {node["id"]}
        cur = node
        while cur["parent_id"] is not None:
            parent = nodes.get(cur["parent_id"])
            if parent is None:
                break
            if parent["id"] in seen:
                cycles.append(node["name_path"])
                break
            seen.add(parent["id"])
            cur = parent
    if cycles:
        problems.append(f"{len(cycles)} 个节点的父链成环（侧栏永远走不出来），例：{_brief(cycles)}")
    stale = [f"{n['name_path']} 应为 {p}/{n['name']}"
             for n in nodes.values()
             for p in [(nodes[n["parent_id"]]["name_path"] if n["parent_id"] in nodes else "")]
             if n["name_path"] != (f"{p}/{n['name']}" if p else n["name"])]
    if stale:
        problems.append(f"{len(stale)} 个节点的 name_path 与父链不一致，例：{_brief(stale)}")
    dangling = int(_scalar(conn, "SELECT count(*) FROM document_categories dc"
                                 " WHERE NOT EXISTS (SELECT 1 FROM documents d WHERE d.id = dc.doc_id)"))
    if dangling:
        problems.append(f"document_categories 里 {dangling} 行指向已不存在的文档")
    template = sum(1 + len(children) for children in DEFAULT_CATEGORY_TEMPLATE.values())
    return Row("C10", "分类树自洽（父链可达 / 无环 / name_path 与父链一致）", not problems,
               f"分类 {len(nodes)} 个（默认模板算出来是 {template} 个）｜"
               + ("；".join(problems) if problems else "四项全部自洽"))


def c11_backups(data_root: Path, deep: bool = False) -> Row:
    # 目录口径必须问产品自己：快照住在 `<root>/data/backups`（`AppPaths.backups_dir`），
    # 不是 `<root>/backups`。第一版在这里写死了根目录，结果真冻结现场（快照明明有 3 份）
    # 被判成「一份快照都没有」的未验 —— 探针和数据根吵架，正是模块说明第 2 条要避免的事。
    backup_dir = AppPaths.resolve(data_root).backups_dir
    snaps = sorted(backup_dir.glob("*.db")) if backup_dir.is_dir() else []
    if not snaps:
        return Row("C11", "最新快照整库体检，其余快照开库读版本", False,
                   "backups/ 里一份快照都没有 —— 从没跑过迁移就不会有，但交付时不能拿「没有」当「验过」",
                   unverified=True)
    # ISSUES I98 乙：默认「最新一份才是真正的回滚点」只体检它，其余快照仍要打开 + 读版本；
    # 逐份 integrity_check 的代价随迁移次数线性增长（每迁移一次多一份 12GB 级快照），
    # 所以逐份体检是显式的 `--c11-deep`，不是默认行为。
    newest = max(snaps, key=lambda p: (p.stat().st_mtime_ns, p.name))
    bad: list[str] = []
    detail: list[str] = []
    checked: list[str] = []
    for snap in snaps:
        size = snap.stat().st_size
        if size == 0:
            bad.append(f"{snap.name} 是 0 字节")
            continue
        try:
            conn = _ro(snap)
        except sqlite3.DatabaseError as exc:
            bad.append(f"{snap.name} 打不开：{type(exc).__name__}: {exc}")
            continue
        try:
            # 迁移前的第一份快照来自空库：那时连 schema_version 都还没有，v0 是它的正当取值
            version = int(_scalar(conn, "SELECT coalesce(max(version), 0) FROM schema_version")) \
                if conn.execute("SELECT count(*) FROM sqlite_master WHERE name='schema_version'"
                                " AND type='table'").fetchone()[0] else 0
            detail.append(f"{snap.name} {round(size / 1024)}KiB@v{version}")
            if deep or snap == newest:
                t0 = time.perf_counter()
                ok, measured = _health(conn, snap.name)
                checked.append(f"{snap.name} {round((time.perf_counter() - t0) * 1000)}ms")
                if not ok:
                    bad.append(measured)
        except sqlite3.DatabaseError as exc:
            bad.append(f"{snap.name} 读不动：{type(exc).__name__}: {exc}")
        finally:
            conn.close()
    if deep:
        label = "全部快照整库体检（--c11-deep）"
        scope = f"--c11-deep：整库体检跑了全部 {len(snaps)} 份"
    else:
        label = "最新快照整库体检，其余快照开库读版本"
        scope = (f"整库体检只跑最新一份，其余 {len(snaps) - 1} 份仅开库读版本"
                 f"（旧快照内部损坏不在本口径内，ISSUES I98；逐份体检加 --c11-deep）")
    shown = _brief(checked, 8)
    extra = "" if len(checked) <= 8 else f"（另有 {len(checked) - 8} 份未展开）"
    health = f"整库体检 {len(checked)} 份：{shown}{extra}"
    return Row("C11", label, not bad,
               f"快照 {len(snaps)} 份｜{_brief(detail, 4)}｜{health}｜{scope}"
               + ("" if not bad else " ── " + "；".join(bad)))


def c12_page_range(conn: sqlite3.Connection) -> Row:
    over = int(_scalar(conn, "SELECT count(*) FROM text_pages tp"
                             " JOIN documents d ON d.id = tp.doc_id"
                             " WHERE d.page_count IS NOT NULL AND tp.page_no > d.page_count"))
    below = int(_scalar(conn, "SELECT count(*) FROM text_pages WHERE page_no < 1"))
    dup = int(_scalar(conn, "SELECT count(*) FROM (SELECT doc_id, page_no FROM text_pages"
                            " GROUP BY doc_id, page_no HAVING count(*) > 1)"))
    return Row("C12", "正文页页码不超过库里记的页数", over == 0 and below == 0 and dup == 0,
               f"超页 {over}｜页码 <1 {below}｜同页重复 {dup}"
               f"（page_count 的口径来自解析器，不是人工填的；页码越界=正文与文件对不上）")


def c13_root_keys(conn: sqlite3.Connection) -> Row:
    """ISSUES I89 丙：监测根根键必须是 `identity_key` 口径（`c:/users/lavie`），不是原生
    Windows 写法（`C:\\Users\\lavie`）。C2 钉的是 `documents.path_key`，这一条钉它孪生的另一处
    —— 全库子树查询（`path_key LIKE like_prefix(root_key)`）按 root_key 拼前缀，登记错了那个
    根"下面有哪些文档"就恒返回 0 条。红就点名是哪一行（与 **ISSUES I88**「规则而不是补丁」同形状：
    把只在真库才照得到的坏法，升成一条常驻断言）。
    """
    rows = [dict(r) for r in conn.execute("SELECT root_path, root_key FROM monitored_roots")]
    bad = [r["root_key"] for r in rows if identity_key(r["root_key"]) != r["root_key"]]
    return Row("C13", "监测根根键与 identity_key 同口径（子树查询认这个前缀）", not bad,
               f"监测根 {len(rows)} 个｜"
               + (f"{len(bad)} 行的 root_key 不等于 identity_key(root_key)，例：{_brief(bad)}"
                  if bad else "每行 root_key 都等于 identity_key(root_key)"))


def run_checks(db: Path, data_root: Path, *, walk: bool,
               alive_check: bool = True, c11_deep: bool = False) -> list[Row]:
    alive = _app_running() if alive_check else (False, "注入模式：核的是临时副本，没有别的手在写它")
    conn = _ro(db)
    try:
        rows = [timed(c0_version, conn), timed(c1_health, conn), timed(c2_path_keys, conn)]
        rows += timed(c3_files_vs_db, conn, walk=walk)
        rows += [timed(c4_fts, conn), timed(c5_pages, conn), timed(c6_status_domains, conn),
                 timed(c7_vector_domain, conn), timed(c8_op_domain, conn), timed(c9_queue, conn, alive),
                 timed(c10_tree, conn), timed(c11_backups, data_root, deep=c11_deep),
                 timed(c12_page_range, conn), timed(c13_root_keys, conn)]
    finally:
        conn.close()
    return rows


def _app_running() -> tuple[bool, str]:
    """C9 的前提是"这台机器上没有别的手在改队列"。查不到 psutil 时按"没有活进程"处理并说明。"""
    try:
        import psutil
    except ImportError:
        return False, "psutil 取不到，按无活进程处理"
    hits = []
    for proc in psutil.process_iter(["name", "cmdline"]):
        try:
            name = (proc.info["name"] or "").lower()
            cmd = " ".join(proc.info["cmdline"] or []).lower()
        except (psutil.Error, OSError):  # 个别进程读不到（已退出/没权限）不影响别的进程
            continue
        if name == "pdfarchiver.exe" or ("python" in name and "main.py" in cmd):
            hits.append(f"{proc.pid}:{name}")
    return bool(hits), ", ".join(hits[:3])


# 反向注入自检（夹具 + 21 条坏法 + C11 口径边界）拆到同级的 p12_inject.py：
# `main()` 里延迟导入，顶层不反向依赖（否则两个模块成环）。


# ——————————————————————————————————————————————— 主流程 ———————————————————————————————————————————————

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="文件与数据库一致性核查（详见模块文档）")
    ap.add_argument("--data-root", default=None, help="要核查的数据根（默认按产品口径解析）")
    ap.add_argument("--out", default=None, help="把结果写成 JSON")
    ap.add_argument("--inject", action="store_true", help="反向注入自检（只动临时目录里的副本）")
    ap.add_argument("--c11-deep", action="store_true",
                    help="C11 对每份快照都跑整库体检（慢；默认只体检最新一份）")
    ap.add_argument("--no-file-walk", action="store_true",
                    help="跳过盘上遍历；该条会显式判为未验，整场门禁随之变红")
    args = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    out = Path(args.out) if args.out else None
    if args.inject:
        from p12_inject import inject_mode  # noqa: PLC0415 拆出模块：注入段独立成 p12_inject.py
        return inject_mode(out)

    paths = AppPaths.resolve(args.data_root)
    data_root, db = paths.root, paths.catalog_db
    print(f"数据根：{data_root}（来源：{paths.source}）｜库：{db.name}")
    if not db.is_file():
        print(f"  红  库不存在：{db}")
        print("VERDICT: RED（1 条未过）")
        return 1
    try:
        rows = run_checks(db, data_root, walk=not args.no_file_walk, c11_deep=args.c11_deep)
    except sqlite3.DatabaseError as exc:
        print(f"  红  只读方式打不开库：{type(exc).__name__}: {exc}")
        print("        应用正在跑时 WAL 可能要恢复，只读打不开 —— 关闭应用后重跑；探针不改库")
        print("VERDICT: RED（1 条未过）")
        return 1

    for row in rows:
        print(row.render())
    print("  逐条计时：" + breakdown(rows))
    bad = [r for r in rows if not r.ok and not r.unverified]
    skipped = [r for r in rows if r.unverified]
    if out:
        payload = {"data_root": str(data_root), "source": paths.source, "walk": not args.no_file_walk,
                   "rows": [{"code": r.code, "label": r.label, "ok": r.ok, "ms": getattr(r, "ms", None),
                             "unverified": r.unverified, "measured": r.measured} for r in rows]}
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"  INFO 结果已写出 {out}")
    print(f"  合计 {len(rows)} 条｜红 {len(bad)} 条｜未验 {len(skipped)} 条"
          + (f"（{[r.code for r in skipped]} —— 没跑过就是没验过，不给绿）" if skipped else ""))
    print("VERDICT: " + ("ALL GREEN" if not bad and not skipped
                         else f"RED（{len(bad)} 条未过"
                              + (f"，{len(skipped)} 条未验" if skipped else "") + "）"))
    return 0 if not bad and not skipped else 1


if __name__ == "__main__":
    raise SystemExit(main())
