"""工具层手抄 SQL 的守卫：探针/门禁/打包冒烟都在应用**外面**读同一个库，SQL 是手抄的。

为什么要有这一条：2026-10-15 第一轮真 soak 里 `p13_soak.backlog()` 抄成了 `FROM jobs`
（真表叫 `processing_jobs`），等待排空的 46 秒里每次读库都抛 `no such table` 并被循环吞掉，
最后一条红只写着"没排空"。判据没撒谎，但**传感器是瞎的** —— 而注入自检当时 10/10 全过，
因为它喂的是现造的读数，从没碰过真表名。

两条断言分别钉住这个类的两种坏法：
① 表名必须存在于真迁移出来的 schema（静态，覆盖全部工具文件）；
② 探针那条读数必须与产品自己的 `JobRepository.counts_by_state()` 一字不差（现场，覆盖列名与口径）。
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
TOOL_GLOBS = ("tests/probes/*.py", "gates/*.py", "packaging/*.py")

# SQL 关键字只在大写形式下才是 SQL（Python 的导入是小写 `from`），所以只匹配大写。
SQL_TABLE_RE = re.compile(r"\b(?:FROM|JOIN|INSERT\s+INTO|UPDATE)\s+([a-z][a-z0-9_]*)\b")

# `sqlite_master` 是 SQLite 自己的目录表，永远不会出现在业务 schema 里。
SQLITE_OWN = {"sqlite_master", "sqlite_sequence", "sqlite_temp_master"}

# 只查"打开产品库"的工具。p1/p2/p8 这些可行性探针各自现造一份临时 schema（`pages`、`t`），
# 那正是它们要做的事，不是抄错产品表名 —— 把它们圈进来等于制造一堆假红。
# 圈定条件用"文本里出现 catalog.db"这个可观察事实，不用手写的文件清单：
# 以后谁新写一个读产品库的工具，自动落进这条断言的管辖范围。
CATALOG_MARKER = "catalog.db"


def _catalog_reading_files() -> list[Path]:
    out = []
    for glob in TOOL_GLOBS:
        for path in REPO.glob(glob):
            if CATALOG_MARKER in path.read_text(encoding="utf-8"):
                out.append(path)
    return sorted(out)


def _sql_strings(path: Path) -> list[tuple[int, str]]:
    """取这个文件里**当代码用**的字符串常量（真 SQL 都在这儿），不取 docstring 与注释。

    为什么要排除 docstring：这一类守卫的读数必须只指向真问题。p13 的注释里写着
    "上一版抄成了 `FROM jobs`" —— 那是 lesson，不是又一条坏 SQL；把它算进断言里，
    这条测试就变成"不许在注释里提 bug"。
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            head = node.body[0] if getattr(node, "body", None) else None
            if isinstance(head, ast.Expr) and isinstance(head.value, ast.Constant) \
                    and isinstance(head.value.value, str):
                docstrings.add(id(head.value))
    return [(node.lineno, node.value)
            for node in ast.walk(tree)
            if isinstance(node, ast.Constant) and isinstance(node.value, str)
            and id(node) not in docstrings]


def _table_names(engine) -> set[str]:
    conn = engine.thread_connection()
    return {r["name"] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type IN ('table','view')")}


def test_every_tool_sql_table_name_exists(ctx):
    """工具里手抄的每个表名都得在真 schema 里存在 —— 抄错一个字符就红。"""
    real = _table_names(ctx.engine)
    files = _catalog_reading_files()
    assert files, "一个读产品库的工具都没扫到 —— 这条断言已经没牙"
    wrong: list[str] = []
    checked = 0
    for path in files:
        for line_no, text in _sql_strings(path):
            for name in SQL_TABLE_RE.findall(text):
                checked += 1
                if name not in real and name not in SQLITE_OWN:
                    wrong.append(f"{path.relative_to(REPO)}:{line_no} → {name}")
    assert checked >= 40, f"只扫到 {checked} 处表名引用，少于 40 —— 正则失效了，这条断言已经没牙"
    assert not wrong, "这些表名在真 schema 里不存在，读它的 SQL 永远只会抛 no such table：\n" + "\n".join(wrong)


def test_p13_backlog_reads_the_same_numbers_as_the_product(ctx):
    """探针的队列读数必须与 `JobRepository.counts_by_state()` 完全相等。

    只比"有没有报错"不够：列名抄错、少算一个状态、GROUP BY 写错都能读成功但读出别的数。
    """
    import sys

    sys.path.insert(0, str(REPO / "tests" / "probes"))
    import p13_soak

    ctx.jobs.enqueue("scan")
    ctx.jobs.enqueue("index", doc_id=None)
    ctx.jobs.count()                      # 确认任务真的进了库，而不是断言两个空字典相等
    expected = ctx.jobs.counts_by_state()
    assert expected, "库里没有任务，这条断言什么也没比"
    assert p13_soak.backlog(ctx.paths.root) == expected
