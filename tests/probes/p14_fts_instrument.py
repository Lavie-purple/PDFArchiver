"""外部内容表的"索引与正文对不对得齐"到底有几种**能用**的口径 —— 四种坏法各实测一遍。

跑法：
    python tests/probes/p14_fts_instrument.py        # 几秒钟，不起界面、不碰用户文件

为什么要常驻而不是留在一次性脚本里：G10 这条门禁原来写的是
`SELECT count(*) FROM docs_fts WHERE rowid NOT IN (SELECT id FROM documents)`，
2026-10-15 实测才发现两件事 —— 表名不存在（真名 `content_fts`），而且这类**免词**计数在
外部内容表上恒等于正文行数，也就是说那条断言永远不会变红（I8）。判据现在改成两个能数的方向
（`check_fts_consistency()` 的 `unindexed` / `stale_docsize`）加一种带词的 `MATCH`，
本探针就是这句话的出处：它把四种坏法分别造出来，再看每种口径分别看不看得见。

结论（每次跑都重新验一遍，不靠记忆；②③④ 各建一份独立的库，串在一个连接上读到的是叠加后的数、
分不清是谁造成的；⑤ 才是故意把三种坏法叠进同一份库，因为 rebuild 要清的就是这种混合脏状态）：

| 坏法 | `count(*) FROM content_fts` | docsize 双向 | 带词的 `MATCH` | `'integrity-check'` |
| --- | --- | --- | --- | --- |
| ② delete 触发器列清单写错（p1 的真陷阱，SQLite 不报错） | 看不见 | **看不见** | **看得见** | 通过（等于没检查） |
| ③ insert 触发器不在（正文进库、索引没有） | 看不见 | **看得见** `unindexed` | 少一条命中 | 通过 |
| ④ 正文删了、delete 触发器也没有（纯幽灵） | 看不见 | **看得见** `stale_docsize` | **看得见** | 通过 |
| ① 完好 / ⑤ rebuild 之后 | 与正文相等 | 两个方向都 0 | 两者相等 | 通过 |

② 那一行值得单独记住：漏列的 `'delete'` 命令**把 docsize 花名册里那行删掉了**，倒排里那条却还挂着 ——
所以"最像幽灵"的那种坏法，恰好是免词口径唯一看不见的那种。
`'integrity-check'` 另有一层：它在坏状态下也"通过"，且跑完数据库文件的 sha256 不变 ——
既不能当检查，也不必怕只读诊断时它改数据。

⑤ 必须走产品入口 `IndexService.rebuild_fts()`，不许在探针里自己写一遍 `VALUES('rebuild')`：
第一版就是自己写的，于是"把 `rebuild_all()` 摘掉"这条坏法当场抓不到（判据看着在测补救，其实测的是
探针那行 SQL）—— 改走产品入口 + 对账它返回的六个数之后，同一条坏法实测变红（台账 **I33**）。
"""
from __future__ import annotations

import hashlib
import sqlite3
import sys
import tempfile
from pathlib import Path
from typing import Callable

REPO = Path(__file__).resolve().parents[2]
for _p in (REPO / "src", REPO / "tests"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from pdfarchiver.db.engine import Engine            # noqa: E402
from pdfarchiver.db.migrate import migrate          # noqa: E402
from pdfarchiver.db.repositories.documents import DocumentRepository  # noqa: E402
from pdfarchiver.db.repositories.metadata import MetadataRepository    # noqa: E402
from pdfarchiver.db.repositories.text import TextRepository            # noqa: E402
from pdfarchiver.services.index_service import IndexService            # noqa: E402

TERM = '"人工智能"'


def log(msg: str) -> None:
    print(msg, flush=True)


def census(c: sqlite3.Connection) -> dict[str, int]:
    """六种口径一次取全。外部内容表能免词枚举的只有 docsize 那张影子表。"""
    return {
        "base": c.execute("SELECT count(*) FROM text_pages").fetchone()[0],
        "fts_count": c.execute("SELECT count(*) FROM content_fts").fetchone()[0],
        "docsize": c.execute("SELECT count(*) FROM content_fts_docsize").fetchone()[0],
        "ghost_notin": c.execute(
            "SELECT count(*) FROM content_fts WHERE rowid NOT IN (SELECT rowid FROM text_pages)"
        ).fetchone()[0],
        "unindexed": c.execute(
            "SELECT count(*) FROM text_pages tp WHERE tp.rowid NOT IN"
            " (SELECT id FROM content_fts_docsize)"
        ).fetchone()[0],
        "stale_docsize": c.execute(
            "SELECT count(*) FROM content_fts_docsize WHERE id NOT IN (SELECT rowid FROM text_pages)"
        ).fetchone()[0],
        "match": c.execute("SELECT count(*) FROM content_fts WHERE content_fts MATCH ?", (TERM,)).fetchone()[0],
        "match_joined": c.execute(
            "SELECT count(*) FROM content_fts JOIN text_pages tp ON tp.rowid = content_fts.rowid"
            " WHERE content_fts MATCH ?", (TERM,)
        ).fetchone()[0],
    }


def integrity_check(db: Path) -> tuple[str, bool]:
    """在 BEGIN…ROLLBACK 里跑 'integrity-check'，同时用文件 sha256 证明它改不改数据。"""
    before = hashlib.sha256(db.read_bytes()).hexdigest()
    conn = sqlite3.connect(db.as_posix(), isolation_level=None)
    try:
        conn.execute("BEGIN IMMEDIATE")
        try:
            conn.execute("INSERT INTO content_fts(content_fts) VALUES('integrity-check')")
            verdict = "通过（没报错）"
        except sqlite3.Error as exc:
            verdict = f"报错：{type(exc).__name__}: {exc}"
        conn.execute("ROLLBACK")
    finally:
        conn.close()
    return verdict, hashlib.sha256(db.read_bytes()).hexdigest() == before


def build(db: Path) -> tuple[sqlite3.Connection, Engine]:
    """真迁移出来的库（不是现造的表结构），塞 1 份文档 3 页正文，每页都含检索词。

    把 Engine 一起返回是为了收尾能真把连接关掉：Windows 上不关连接就删不掉临时目录，
    探针会在"报告完结论之后"抛一个与结论无关的 NotADirectoryError。
    """
    engine = Engine(db)
    migrate(engine, backup_dir=db.parent / "backups")   # Engine 只开连接，迁移要显式跑
    conn = engine.connect()
    conn.execute("INSERT INTO documents(path,path_key,name,ext,size_bytes,mtime_ns,created_at,updated_at)"
                 " VALUES('h:/a','h:/a','a','pdf',1,1,1,1)")
    for page_no in (1, 2, 3):
        conn.execute("INSERT INTO text_pages(doc_id,page_no,char_count,body,indexed_at) VALUES(1,?,?,?,?)",
                     (page_no, page_no * 4, f"人工智能第{page_no}页正文", page_no))
    conn.commit()
    return conn, engine


def reopen(db: Path) -> tuple[sqlite3.Connection, Engine]:
    """只开连接、不塞数据：⑤ 要在同一份已经脏掉的库上跑 rebuild，再走一次 build 会撞 path_key 唯一约束。

    取 `thread_connection()` 而不是 `connect()`：⑤ 接下来要调产品入口 `rebuild_fts()`，
    它用的就是这一条连接；两条连接各自开快照，探针对"补救之后"数出来的口径就跟产品看到的不是同一份。
    """
    engine = Engine(db)
    return engine.thread_connection(), engine


def break_delete_trigger(conn: sqlite3.Connection) -> None:
    """p1 记录的真实坏法：`'delete'` 命令的列清单少带 `old.body` —— SQLite 不报错，只留幽灵。"""
    conn.execute("DROP TRIGGER tx_pages_ad")
    conn.execute("CREATE TRIGGER tx_pages_ad AFTER DELETE ON text_pages BEGIN"
                 " INSERT INTO content_fts(content_fts, rowid, body) VALUES('delete', old.rowid, ''); END")
    conn.execute("DELETE FROM text_pages WHERE doc_id=1 AND page_no=2")


def drop_insert_trigger(conn: sqlite3.Connection) -> None:
    conn.execute("DROP TRIGGER tx_pages_ai")
    conn.execute("INSERT INTO text_pages(doc_id,page_no,char_count,body,indexed_at)"
                 " VALUES(1,4,4,'人工智能第4页正文',4)")


def drop_delete_trigger(conn: sqlite3.Connection) -> None:
    conn.execute("DROP TRIGGER tx_pages_ad")
    conn.execute("DELETE FROM text_pages WHERE doc_id=1 AND page_no=3")


def pile_up(conn: sqlite3.Connection) -> None:
    """三种坏法叠在一个库里 —— rebuild 要清的就是这种混在一起的脏状态。"""
    break_delete_trigger(conn)
    drop_insert_trigger(conn)
    drop_delete_trigger(conn)


def measure(root: Path, tag: str, mutate: Callable[[sqlite3.Connection], None] | None
            ) -> tuple[dict[str, int], Path]:
    """给一种坏法单独开一份库，返回它的六种口径读数。

    上一版是串在同一个连接上连着改，读到的是几种坏法**叠起来**的数：③ 的 `match` 被 ② 留下的
    幽灵顶平，断言当场红了 —— 红的原因是测量方法，不是产品。分开建之后每个数都知道是谁造成的。
    """
    db = root / f"{tag}.db"
    conn, engine = build(db)
    try:
        if mutate is not None:
            mutate(conn)
            conn.commit()
        return census(conn), db
    finally:
        conn.close()
        engine.close_thread_connection()


def main() -> int:
    fails: list[str] = []
    total = 0

    def check(name: str, ok: bool, measured: str) -> None:
        nonlocal total
        total += 1
        log(f"  {'绿' if ok else '红'}  {name}\n        实测：{measured}")
        if not ok:
            fails.append(name)

    with tempfile.TemporaryDirectory(prefix="p14_fts_", ignore_cleanup_errors=True) as td:
        root = Path(td)

        log("① 触发器完好")
        good, db = measure(root, "good", None)
        check("完好状态下三种口径都干净",
              good["unindexed"] == 0 and good["stale_docsize"] == 0
              and good["match"] == good["match_joined"] == good["base"],
              f"{good}")
        verdict, unchanged = integrity_check(db)
        check("'integrity-check' 不是检查：正常状态就'通过'，且不改动文件",
              verdict == "通过（没报错）" and unchanged, f"{verdict}｜文件哈希不变={unchanged}")

        log("② p1 的真实坏法：delete 触发器列清单写错（漏 old.body），SQLite 不报错")
        bad2, db2 = measure(root, "broken_delete", break_delete_trigger)
        check("免词口径全抓不到它（旧 G10 的写法就是其中之一，所以那条断言是瞎的）",
              bad2["fts_count"] == bad2["base"] and bad2["ghost_notin"] == 0
              and bad2["stale_docsize"] == 0 and bad2["unindexed"] == 0,
              f"{bad2}｜漏列的 'delete' 把 docsize 花名册里那行删掉了，倒排里那条却还挂着")
        check("带词的 MATCH 抓得到它",
              bad2["match"] > bad2["match_joined"],
              f"MATCH {bad2['match']} vs MATCH再JOIN {bad2['match_joined']}"
              f" —— 差出来的就是那条已删正文还挂在倒排里")
        verdict2, unchanged2 = integrity_check(db2)
        check("'integrity-check' 在这种坏状态下照样'通过'（等于没有检查，不许拿它当依据）",
              verdict2 == "通过（没报错）" and unchanged2, f"{verdict2}｜文件哈希不变={unchanged2}")

        log("③ 漏索引：insert 触发器不在，正文进库而索引没有")
        bad3, _ = measure(root, "no_insert_trigger", drop_insert_trigger)
        check("docsize 花名册抓得到漏索引（`unindexed` 的来处），免词的 count(*) 抓不到",
              bad3["unindexed"] == 1 and bad3["fts_count"] == bad3["base"] and bad3["match"] < bad3["base"],
              f"{bad3}")

        log("④ 正文删了、delete 触发器也没有（纯幽灵：索引里认得，表里没了）")
        bad4, _ = measure(root, "no_delete_trigger", drop_delete_trigger)
        check("这一种 docsize 也看得见（`stale_docsize` 的来处）",
              bad4["stale_docsize"] == 1 and bad4["unindexed"] == 0, f"{bad4}")
        check("带词的 MATCH 同样抓得到纯幽灵",
              bad4["match"] > bad4["match_joined"],
              f"MATCH {bad4['match']} vs MATCH再JOIN {bad4['match_joined']}")

        log("⑤ 三种坏法叠在一起的脏库，跑一次 rebuild（产品唯一的补救入口 `rebuild_fts()`）")
        dirty, db5 = measure(root, "pile", pile_up)
        dirty_state = (dirty["unindexed"], dirty["stale_docsize"], dirty["match"] - dirty["match_joined"])
        conn5, engine5 = reopen(db5)
        try:
            service = IndexService(DocumentRepository(engine5), TextRepository(engine5),
                                   MetadataRepository(engine5))
            numbers = service.rebuild_fts()      # 走产品入口，不在探针里另写一遍 'rebuild' SQL
            fixed = census(conn5)
        finally:
            conn5.close()
            engine5.close_thread_connection()
        check("rebuild 是真补救：脏状态被它清掉，三个口径重新对齐",
              dirty_state != (0, 0, 0) and fixed["unindexed"] == 0 and fixed["stale_docsize"] == 0
              and fixed["match"] == fixed["match_joined"] == fixed["base"],
              f"rebuild 前（漏索引, 幽灵花名册, 倒排幽灵）={dirty_state} → 后 {fixed}")
        check("产品入口自己报的六个数与探针独立数出来的一致（不许只回一句『重建完成』）",
              numbers["unindexed_before"] == dirty_state[0]
              and numbers["stale_before"] == dirty_state[1]
              and numbers["unindexed_after"] == fixed["unindexed"] == 0
              and numbers["stale_after"] == fixed["stale_docsize"] == 0
              and numbers["pages"] == fixed["base"] and numbers["docs"] == 1,
              f"{numbers}")

    log(f"  合计 {total} 条｜红 {len(fails)} 条")
    log("VERDICT: ALL GREEN" if not fails else f"VERDICT: RED（{len(fails)} 条：{'、'.join(fails)}）")
    return 0 if not fails else 1


if __name__ == "__main__":
    raise SystemExit(main())
