"""架构守卫（docs/ARCHITECTURE 二）。

用 AST 扫，不靠人记。三条规则各自能骗过它一次以上，所以每条都配了反向注入实验
（见 docs/TESTING.md 的"反向注入"一节）。

跑法：
    python -m pytest tests/guards/test_architecture.py -q
    python tests/guards/test_architecture.py          # 独立跑，末行 VERDICT
"""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src"
PKG = SRC / "pdfarchiver"

# 模块前缀 → 禁止 import 的前缀。方向只有一个：ui → services → 能力层 → db → config。
FORBIDDEN_IMPORTS: dict[str, tuple[str, ...]] = {
    "ui": ("pdfarchiver.db", "pdfarchiver.fs", "pdfarchiver.parsing", "pdfarchiver.indexing",
           "pdfarchiver.search", "pdfarchiver.ocr", "pdfarchiver.semantic", "pdfarchiver.fileops",
           "pdfarchiver.backup", "pdfarchiver.jobs", "pymupdf"),
    "services": ("pdfarchiver.ui",),
    "db": ("pdfarchiver.ui", "pdfarchiver.services", "pdfarchiver.ui", "pdfarchiver.fileops",
           "pdfarchiver.ocr", "pdfarchiver.semantic", "pymupdf"),
    "fs": ("pdfarchiver.ui", "pdfarchiver.services", "pdfarchiver.db"),
    "parsing": ("pdfarchiver.ui", "pdfarchiver.services", "pdfarchiver.db"),
    "indexing": ("pdfarchiver.ui", "pdfarchiver.services", "pdfarchiver.db"),
    "search": ("pdfarchiver.ui", "pdfarchiver.semantic", "pymupdf"),
    "ocr": ("pdfarchiver.ui", "pdfarchiver.semantic"),
    "semantic": ("pdfarchiver.ui", "pdfarchiver.ocr"),
    "fileops": ("pdfarchiver.ui", "pdfarchiver.services"),
    "backup": ("pdfarchiver.ui", "pdfarchiver.services"),
    "jobs": ("pdfarchiver.ui", "pdfarchiver.services"),
    "config": ("pdfarchiver.ui", "pdfarchiver.services", "pdfarchiver.db"),
    "diagnostics": ("pdfarchiver.ui", "pdfarchiver.services", "pdfarchiver.db"),
}

# SQL 只许出现在真正管库的地方（docs/ARCHITECTURE 一：只有 repositories 能写 SQL）。
SQL_ALLOWED_PATHS = ("db/repositories/", "db/migrations/", "db/migrate.py", "db/engine.py")
SQL_RE = re.compile(
    r"\b(SELECT\s+\S+\s+FROM|INSERT\s+INTO|UPDATE\s+\S+\s+SET|DELETE\s+FROM|"
    r"CREATE\s+(UNIQUE\s+)?TABLE|CREATE\s+(UNIQUE\s+)?INDEX|PRAGMA\s+\w+)\b", re.I)

MAX_NAV_ITEMS_BEFORE_GROUPING = 20  # AGENTS.md「入口超 20 项就上分组 + 搜索」

# 阶段 1 验收 6：代码里不许出现本机路径字面量（盘符 / 家目录）。
MACHINE_LOCAL_PATH_RE = re.compile(r"[A-Za-z]:[\\/]{1,2}|[/\\]home[/\\]|[/\\]Users[/\\]")


class ArchitectureError(AssertionError):
    """守卫失败。消息里必须写清违反了 docs/ARCHITECTURE 的哪一条。"""


def _modules() -> list[Path]:
    return sorted(p for p in PKG.rglob("*.py"))


def _layer_of(path: Path) -> str:
    rel = path.relative_to(PKG).as_posix()
    return rel.split("/")[0] if "/" in rel else ""


def _imported_names(tree: ast.AST) -> list[tuple[int, str]]:
    out: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out += [(node.lineno, a.name) for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                out.append((node.lineno, node.module))
    return out


def _docstring_ids(tree: ast.AST) -> set[int]:
    """文档字符串里出现 SQL 关键字不算违规 —— 它给人读，不进 execute。"""
    ids = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = getattr(node, "body", [])
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
                    and isinstance(body[0].value.value, str):
                ids.add(id(body[0].value))
    return ids


def _string_constants(tree: ast.AST) -> list[tuple[int, str]]:
    skip = _docstring_ids(tree)
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in skip:
            out.append((node.lineno, node.value))
    return out


def check_import_direction() -> list[str]:
    problems: list[str] = []
    for path in _modules():
        layer = _layer_of(path)
        banned = FORBIDDEN_IMPORTS.get(layer, ())
        if not banned:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for lineno, name in _imported_names(tree):
            for bad in banned:
                if name == bad or name.startswith(bad + "."):
                    rel = path.relative_to(SRC.parent).as_posix()
                    problems.append(
                        f"{rel}:{lineno} · {layer} import 了 {name}；"
                        f"docs/ARCHITECTURE 二 规定依赖只能自上而下（{bad} 不许被 {layer} 依赖）")
    return problems


def check_sql_only_where_it_belongs() -> list[str]:
    problems: list[str] = []
    for path in _modules():
        rel = path.relative_to(PKG).as_posix()
        if any(rel.startswith(allowed) or rel.endswith(allowed) for allowed in SQL_ALLOWED_PATHS):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for lineno, text in _string_constants(tree):
            m = SQL_RE.search(text)
            if m:
                problems.append(
                    f"src/pdfarchiver/{rel}:{lineno} 出现 SQL 片段 `{m.group(0)[:40]}`；"
                    "docs/ARCHITECTURE 一：只有 db/repositories 能写 SQL")
    return problems


def check_no_silent_swallow() -> list[str]:
    """AGENTS.md：关键区禁止裸 `except: pass`。要么记下来，要么把类型写窄到不会误伤。"""
    problems: list[str] = []
    for path in _modules():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ExceptHandler):
                continue
            only_pass = all(isinstance(s, (ast.Pass, ast.Continue)) for s in node.body) \
                and len(node.body) > 0
            if not only_pass:
                continue
            if node.type is None or (isinstance(node.type, ast.Name) and node.type.id == "Exception"):
                rel = path.relative_to(SRC.parent).as_posix()
                what = "裸 except" if node.type is None else "except Exception"
                problems.append(f"{rel}:{node.lineno} {what} 里只有 pass —— 故障会被静默吞掉")
    return problems


def check_no_machine_local_path_literal() -> list[str]:
    """阶段 1 验收 6「不依赖开发者机器上的固定绝对路径」的机器判据。

    只查字符串常量里的两类本机痕迹：盘符路径（`H:/…`、`C:\\Users\\…`）与家目录字面量
    （`/home/…`、`Users/<名>`）。数据目录一律来自 `config/paths.py` 的三级解析，
    代码里出现具体路径就说明有人在把本机当默认值。
    """
    problems: list[str] = []
    for path in _modules():
        rel = path.relative_to(SRC.parent).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for lineno, text in _string_constants(tree):
            m = MACHINE_LOCAL_PATH_RE.search(text)
            if m:
                problems.append(
                    f"{rel}:{lineno} 字符串常量里有本机路径 `{m.group(0)[:40]}`；"
                    "路径必须由 config/paths.resolve_data_root() 解析，不许写死（验收 6）")
    return problems


def check_nav_entries_grouped() -> list[str]:
    """AGENTS.md「每加一个新入口先搜是否已有同功能入口；入口超 20 项就上分组 + 搜索」。"""
    sys.path.insert(0, str(SRC))
    from pdfarchiver.ui.nav import NAV_ITEMS  # 注册表是数据，import 它不算把 UI 拖进测试

    problems: list[str] = []
    ids = [i.page_id for i in NAV_ITEMS]
    if len(ids) != len(set(ids)):
        problems.append(f"ui/nav.py 导航 page_id 重复：{ids}")
    if len(NAV_ITEMS) > MAX_NAV_ITEMS_BEFORE_GROUPING:
        problems.append(
            f"导航入口已有 {len(NAV_ITEMS)} 项，超过 {MAX_NAV_ITEMS_BEFORE_GROUPING}，"
            "必须加分组与搜索框（AGENTS.md）")
    return problems


def all_problems() -> list[str]:
    return (check_import_direction() + check_sql_only_where_it_belongs()
            + check_no_silent_swallow() + check_no_machine_local_path_literal()
            + check_nav_entries_grouped())


def test_架构守卫全绿() -> None:
    problems = all_problems()
    if problems:
        raise ArchitectureError("\n".join(problems))


if __name__ == "__main__":
    found = all_problems()
    for p in found:
        print("  RED  " + p)
    print("VERDICT: " + ("ALL GREEN" if not found else f"RED（{len(found)} 条）"))
    sys.exit(0 if not found else 1)
