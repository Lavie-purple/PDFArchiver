"""INSERT 语句卫生守卫 —— 一条，来自 2026-10-19 的现测（台账 **ISSUES I78** 乙）。

**`src/` 里每条 `INSERT INTO t(列…) ` 必须写全 `t` 的「NOT NULL 且无 DEFAULT」列。**

为什么这一条值得存在，而不是一处修一次：`CollectionRepository.add()` 的 INSERT 只写了
`created_at`，漏了同样 `NOT NULL` 无默认值的 `updated_at`，于是**产品里从来没有一次新建集合成功过**
—— 每一次都抛 `sqlite3.IntegrityError: NOT NULL constraint failed: collections.updated_at`。
它挂了整整三个阶段没人发现，因为**没有任何测试走到过"存一条集合"这一步**（界面产生不出一份筛选
条件，服务层也就从没被调用）。等 I78 乙 把界面接上，第一个测试就撞红了。
「智能集合从来没被真正用过」原来有两层原因，仓储层这一层是修完界面也看不见的。

这一类坏法有名字：**一条结构性写不全的 INSERT，其失败方式是"这个功能整个不存在"，而不是
"某个边界情况出错"**。所以它不会自己冒出来，只能被"每次插入都必经"的这条断言抓到。

三条边界，都是为了让它**不会天天误报**：
- **只看 `NOT NULL` 且 `dflt_value IS NULL` 且非主键的列。** 有默认值的列不写会落默认值；
  可为 NULL 的列不写落 NULL；主键（`INTEGER PRIMARY KEY`）自己会填 rowid。这三类都不是这一条的
  范围 —— 把它们也算进来会让守卫长红，而长红的守卫等于没有守卫。
- **SQL 取的是 AST 里的字符串常量**，相邻字面量在编译期已经拼成一个节点，所以跨行拼接的列名表
  不会被截断（第一版按源码文本正则切，把 `"\n  "` 里的引号当成了列名的一部分，误报两条）。
  docstring 里的 SQL 字样**不算**：本仓库的规矩是把踩过的坑写在模块文档里，
  `text.py` 的 docstring 里就有一句 `INSERT OR REPLACE INTO text_pages(…)`。
- **FTS5 影子表（`_config` / `_data` / `_docsize` / `_idx`）跳过** —— 那些表只有 SQLite 自己写。
  外部内容表 `content_fts` 本身要扫：它的 INSERT（`VALUES('optimize')` 那一类命令）由我们发，
  只是它没有 NOT NULL 列，所以现数是零要求。

没写进来的第二半，以及为什么故意不写：**「列数与 `?` 个数不等」也属于同一族**（一插就
`OperationalError: Incorrect number of bindings`）。本轮按现测把它否了 —— 合法写法里 VALUES 内可以
放字面量（`operations.py` 建批次那条就是 9 列 6 个 `?`，其余是 `'pending'` / `NULL` /
`strftime(...)`），要判对就得解析 SQL 表达式，那是另一个量级的守卫，而它抓的东西**现有测试全都抓得住**
（绑定数一错，任何走到这条语句的测试当场红，不像漏列那样能被默认值悄悄绕过）。挂账在
**ISSUES I78** 乙 的备注里，不在这里顺手放宽或收紧规则。

坏法注入台账：`tests/probes/p21_saved_search_injection.py` 的 **h1**（把 `collections.add` 那句
INSERT 的 `updated_at` 去掉，判据同 **ISSUES I55** —— 红且**点名到那句断言消息**）。

跑法：
    python -m pytest tests/guards/test_insert_covers_notnull.py -q
    python tests/guards/test_insert_covers_notnull.py      # 独立跑，末行 VERDICT
"""
from __future__ import annotations

import ast
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from pdfarchiver.config.paths import AppPaths
from pdfarchiver.db.engine import Engine
from pdfarchiver.db.migrate import migrate

SRC = ROOT / "src" / "pdfarchiver"
INSERT = re.compile(
    r"INSERT\s+(?:OR\s+\w+\s+)?INTO\s+(?P<table>[\w_]+)\s*\((?P<cols>[^)]*)\)",
    re.IGNORECASE)
FTS_SHADOW_SUFFIX = ("_config", "_data", "_docsize", "_idx")
# [约定] 现数 21（2026-10-19）。它**不参与口径判定**，只用来抓"扫描器坏了" ——
# 那种情况下每条 INSERT 都因为一条都没扫到而假绿，是最坏的一种假绿。
MIN_STATEMENTS = 15


def _required_columns(paths: AppPaths) -> dict[str, list[str]]:
    """空库一路迁到最新版之后，每张表"必须被写、否则整条 INSERT 直接 IntegrityError"的列。"""
    engine = Engine(paths.catalog_db)
    try:
        migrate(engine, backup_dir=paths.backups_dir)
        conn = engine.connect()
        try:
            names = [r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
            out: dict[str, list[str]] = {}
            for name in names:
                if name.endswith(FTS_SHADOW_SUFFIX):
                    continue
                out[name.lower()] = [
                    row[1].lower() for row in conn.execute(f"PRAGMA table_info({name})")
                    if row[3] and row[4] is None and not row[5]        # NOT NULL / 无默认 / 非主键
                ]
            return out
        finally:
            conn.close()
    finally:
        engine.close_thread_connection()


def _sql_literals(path: Path) -> list[tuple[int, str]]:
    """这个文件里"像是 SQL 的字符串常量"：(行号, 内容)。docstring 不算。"""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    docstrings: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            first = (node.body or [None])[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) \
                    and isinstance(first.value.value, str):
                docstrings.add(id(first.value))
    return [(node.lineno or 0, node.value)
            for node in ast.walk(tree)
            if isinstance(node, ast.Constant) and isinstance(node.value, str)
            and id(node) not in docstrings and INSERT.search(node.value)]


def check_insert_covers_required_columns() -> list[str]:
    """A：`src/` 里每条 INSERT 的列名表，必须盖住那张表的必填列。"""
    with tempfile.TemporaryDirectory(prefix="guard_inserts_") as td:
        paths = AppPaths.resolve(td)
        paths.mkdirs()
        required = _required_columns(paths)

    statements = 0
    problems: list[str] = []
    for path in sorted(SRC.rglob("*.py")):
        rel = path.relative_to(ROOT).as_posix()
        for lineno, sql in _sql_literals(path):
            for m in INSERT.finditer(sql):
                statements += 1
                table = m.group("table").lower()
                cols = {c.strip().strip("\"'`").lower()
                        for c in m.group("cols").split(",")}
                cols.discard("")
                missing = sorted(set(required.get(table, [])) - cols)
                if missing:
                    problems.append(
                        f"{rel}:{lineno} `INSERT INTO {table}` 没写 {missing} —— 这几列 "
                        f"`NOT NULL` 且无默认值，这一插**每一次**都以 `IntegrityError` 失败"
                        f"（现测：`collections.updated_at` 漏了三个阶段，结果是「这个功能整个"
                        f"不存在」而不是「某处出错」）")
    if statements < MIN_STATEMENTS:
        problems.append(
            f"只扫到 {statements} 条 INSERT（下限 {MIN_STATEMENTS}，现数 21）—— 扫描器或 "
            "`_sql_literals` 坏了，上面那条此刻不可信（漏扫会让守卫永远绿）")
    return problems


def check_all() -> list[str]:
    return check_insert_covers_required_columns()


def test_INSERT写全必填列() -> None:
    problems = check_insert_covers_required_columns()
    if problems:
        raise AssertionError("\n".join(problems))


if __name__ == "__main__":
    found = check_all()
    for p in found:
        print("  RED  " + p)
    modules = sorted(SRC.rglob("*.py"))
    n = sum(len(INSERT.findall(sql)) for path in modules for _, sql in _sql_literals(path))
    print(f"扫了 {len(modules)} 个 src 模块、{n} 条 INSERT")
    print("VERDICT: " + ("ALL GREEN" if not found else f"RED（{len(found)} 条）"))
    sys.exit(0 if not found else 1)
