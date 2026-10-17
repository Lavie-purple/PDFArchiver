"""库结构卫生守卫 —— 两条，都来自 2026-10-17 的现测（台账 **ISSUES I62**，用户勾的"丁"）。

**A · `documents` 的列：文档 ⇄ 库 双向对账。**
比的是 `docs/DATABASE.md` §2.1 那张 `CREATE TABLE documents(...)` 与**刚迁移完的临时库**里
`PRAGMA table_info(documents)` 的列名集合，两个方向各一条：
- 文档声明了、库里没有 → 文档给了一张不存在的表里的一个不存在的列。**本轮真抓到**：
  迁移 `0006_drop_volume_id` 已经把 `volume_id` 删了，§2.1 却还把它画在表里（**ISSUES I40**
  那一族的复发 —— 那条说的正是"文档给了一张不存在的表/列"）。
- 库里有、整份文档里查不到这个名字 → 迁移加了列而文档没跟上。**本轮真抓到**：`0004` 加的
  `last_read_page` / `last_read_at` 全文档零提及。

为什么只管 `documents`：§2.1 是全文档**唯一**一处逐列 DDL，其余表在 §2.2 是"要点"表。
把这条推广到全部表要先给 18 张表逐列编目（现测有 **47** 个列名在 `DATABASE.md` 里查不到，
其中 7 个还属于 FTS5 自动建的影子表），那是一次单独的文档工作，欠账挂在 **ISSUES I62**，
**不在这里顺手放宽规则**。表级的对账在 `tests/test_guard_schema_consistency.py`（那条只看表名）。

**B · DDL 只许待在 `db/migrations/` 里。**
`src/` 下除迁移目录外出现 `CREATE TABLE / CREATE INDEX / ALTER TABLE / DROP …` 即红。
唯一例外是 `db/migrate.py` 建水位表 `schema_version` —— `docs/DATABASE.md` §2.5 明写它
"不在任何迁移文件里"，所以例外按**语句**放行而不是按**文件**放行（只放那一条含 `SCHEMA_TABLE` 的）。
这条不是风格洁癖：运行时 `CREATE TABLE IF NOT EXISTS` 建出来的表**不在迁移链里**，
于是空库首迁后的 `sqlite_master` 与"跑过产品的人的库"不是同一个形状，而老产物碰到新库时
`INSERT` 列表里的列名一旦对不上就是启动即崩（阶段 5 冻结产物"双击打不开"那次的形状）。
**本轮真抓到**：`semantic/vector_store.py` 自己建 `vector_meta`。

坏法注入台账：`.probe_work/i62_guard_injection.py`（判据同 **ISSUES I55** —— 红且**点名到那句断言消息**）。

跑法：
    python -m pytest tests/guards/test_schema_columns.py -q
    python tests/guards/test_schema_columns.py      # 独立跑，末行 VERDICT
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

DB_DOC = ROOT / "docs" / "DATABASE.md"
SRC = ROOT / "src" / "pdfarchiver"
MIGRATIONS = "db/migrations/"
# §2.1 解析出的列数下限 [约定]：现数 27（2026-10-17 甲落地后，§2.1 删了 volume_id 与 pdf_version）。
# 它**不参与口径判定**，只用来抓"解析器坏了 / 那一节被改名" —— 那种情况下 A 的两个方向都会
# 因为集合是空的而双双假绿。
DECLARED_MIN = 20

# 迁移目录之外，`src/` 里出现任何一个就是 B 的违规。`SCHEMA_TABLE_OK` 那条例外按语句匹配。
DDL_PATTERN = re.compile(
    r"\b(CREATE\s+(?:VIRTUAL\s+|UNIQUE\s+)?(?:TABLE|INDEX|TRIGGER|VIEW)|"
    r"ALTER\s+TABLE|DROP\s+TABLE|DROP\s+COLUMN|DROP\s+INDEX|DROP\s+TRIGGER)\b",
    re.IGNORECASE)
KEYWORD_STARTS = frozenset({"PRIMARY", "UNIQUE", "CONSTRAINT", "FOREIGN", "CHECK"})


def _documents_block(text: str) -> str:
    """§2.1 里那段 `CREATE TABLE documents( ... );`。"""
    m = re.search(r"CREATE TABLE documents\s*\(.*?\n\s*\);", text, re.DOTALL)
    return m.group(0) if m else ""


def _declared_columns(text: str) -> list[str]:
    block = _documents_block(text)
    names: list[str] = []
    for raw in block.splitlines()[1:]:
        line = raw.split("--")[0].strip()
        if not line or line.startswith((")", "CREATE")):
            continue
        head = line.split()[0]
        if head.upper() in KEYWORD_STARTS:
            continue
        names.append(head.lower().rstrip(",("))
    return names


def _db_columns(paths: AppPaths) -> tuple[set[str], int]:
    """空库一路迁到最新版之后的 `documents` 列名集合 + 当时的表数。"""
    engine = Engine(paths.catalog_db)
    try:
        migrate(engine, backup_dir=paths.backups_dir)
        conn = engine.connect()
        try:
            cols = {r[1].lower() for r in conn.execute("PRAGMA table_info(documents)")}
            tables = conn.execute(
                "SELECT count(*) FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            ).fetchone()[0]
        finally:
            conn.close()
        return cols, int(tables)
    finally:
        engine.close_thread_connection()


def check_documents_columns() -> list[str]:
    """A：文档声明的列必须真在库里；库里的列必须在文档里出现。"""
    text = DB_DOC.read_text(encoding="utf-8")
    declared = _declared_columns(text)
    problems: list[str] = []
    if not declared:
        return [f"`docs/DATABASE.md` §2.1 那段 `CREATE TABLE documents(...)` 没解析到 —— "
                "小节改名或 DDL 块被删，会让 A 的两个方向双双假绿（这是最坏的一种假绿）"]
    if len(declared) < DECLARED_MIN:
        return [f"§2.1 只解析出 {len(declared)} 个列名（下限 {DECLARED_MIN}，现数 27）—— "
                "解析器或那一节坏了，A 的两个方向都不可信"]

    with tempfile.TemporaryDirectory(prefix="guard_columns_") as td:
        paths = AppPaths.resolve(td)
        paths.mkdirs()
        actual, _ = _db_columns(paths)

    for name in declared:
        if name not in actual:
            problems.append(
                f"§2.1 声明了 `documents.{name}`，库里没有（列已删/已改名，文档还画着它）—— "
                f"现数：库里 {len(actual)} 列；这是 **ISSUES I40** 那一族（文档给了一张不存在的列）")
    for name in sorted(actual):
        if not re.search(rf"\b{re.escape(name)}\b", text):
            problems.append(
                f"库里有 `documents.{name}`，整份 `docs/DATABASE.md` 查不到这个名字 —— "
                "迁移加了列而文档没跟上（新列必须在 §2.1 或"
                "「迁移 NNNN 实际落地的差异」那一节里出现）")
    return problems


def _non_code_lines(source: str) -> set[int]:
    """注释行与 docstring 覆盖的行号 —— 这些位置的 DDL 字样**不是**在执行建表。

    不这么做就会稳定误报：本仓库的规矩是把踩过的坑写在模块文档里，而"I62 那次是运行时
    `CREATE TABLE IF NOT EXISTS` 建的表"这种句子正好含有禁词（实测第一次跑就红在
    `vector_store.py` 的解释性 docstring 上）。字符串常量**不在**豁免范围内 ——
    把 SQL 拼在普通字符串里再 `execute` 才是这条规则要抓的形状。
    """
    skip: set[int] = set()
    for lineno, raw in enumerate(source.splitlines(), 1):
        if raw.lstrip().startswith("#"):
            skip.add(lineno)
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return skip                       # 让上层按"读不到"处理，不在这里冒充解析成功
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        body = getattr(node, "body", None)
        if not body:
            continue
        first = body[0]
        if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) \
                and isinstance(first.value.value, str):
            skip.update(range(first.lineno, (first.end_lineno or first.lineno) + 1))
    return skip


def check_ddl_only_in_migrations() -> list[str]:
    """B：迁移目录之外，`src/` 里不许有建表/改表语句（注释与 docstring 不算）。

    范围只到 `src/`：`tests/` 与 `gates/` 里合法地要出现合成迁移和夹具 SQL，把它们一起扫
    只会逼人给守卫开例外，那比漏报更糟。`gates/stage6.py` 曾经手抄过一份 `documents` 建表语句
    并且已经少了一列（`is_encrypted`），本轮改成走真迁移链（**ISSUES I62**）。
    """
    problems: list[str] = []
    for path in sorted(SRC.rglob("*.py")):
        rel = path.relative_to(ROOT).as_posix()
        if MIGRATIONS in rel:
            continue
        source = path.read_text(encoding="utf-8")
        skip = _non_code_lines(source)
        for lineno, line in enumerate(source.splitlines(), 1):
            if lineno in skip or not DDL_PATTERN.search(line):
                continue
            # 水位表是唯一例外，且**按语句**放行：只放 `migrate.py` 里那条引用 SCHEMA_TABLE 的。
            if rel.endswith("db/migrate.py") and "SCHEMA_TABLE" in line:
                continue
            problems.append(
                f"{rel}:{lineno} 在迁移目录之外执行 DDL：`{line.strip()[:90]}` —— "
                "结构变更必须是一条新迁移（`docs/DATABASE.md` 四：改一条已经应用过的迁移，"
                "对现存库静默无效；运行时建表则让库形状取决于'这一段代码有没有跑到过'）")
    return problems


def check_all() -> list[str]:
    return check_documents_columns() + check_ddl_only_in_migrations()


def test_documents的列与文档双向对账() -> None:
    problems = check_documents_columns()
    if problems:
        raise AssertionError("\n".join(problems))


def test_ddl只许待在迁移目录里() -> None:
    problems = check_ddl_only_in_migrations()
    if problems:
        raise AssertionError("\n".join(problems))


if __name__ == "__main__":
    found = check_all()
    for p in found:
        print("  RED  " + p)
    doc_text = DB_DOC.read_text(encoding="utf-8")
    print(f"§2.1 声明 {len(_declared_columns(doc_text))} 列；扫了 "
          f"{len(list(SRC.rglob('*.py')))} 个 src 模块")
    print("VERDICT: " + ("ALL GREEN" if not found else f"RED（{len(found)} 条）"))
    sys.exit(0 if not found else 1)
