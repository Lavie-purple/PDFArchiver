"""架构守卫（docs/ARCHITECTURE 二）。

用 AST 扫，不靠人记。现 8 条：import 方向 / 方向表键的在场性（**ISSUES I94** 甲）/
SQL 只属于 repositories / 不许静默吞异常 / 不许本机路径字面量 / 导航入口分组 /
语义层模型根单源 / 界面不许自己拼时间串。
按 AGENTS.md「每写完一条断言先真注入一次」，每条都要能被一次真注入变红才算守卫；
已做过的坏法记录在 docs/TESTING.md 的"反向注入"一节（阶段 1 那批起脚本化，
`tests/probes/p9_reverse_injection.py`）。

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
# 键必须是 `src/pdfarchiver/` 下真实存在、且至少含一个 .py 的目录 —— **ISSUES I94** 甲：
# 曾有两行 `fileops` / `backup`，那两个包在 src 下只有一个零字节 .gitkeep，
# PKG.rglob("*.py") 一个都扫不出来 ⇒ 那两行是恒真的"守卫"。
# 由 `check_direction_keys_reach_files` 钉着，坏法见 p9 注入 I47（临时加一个不存在的层名当键）。
FORBIDDEN_IMPORTS: dict[str, tuple[str, ...]] = {
    "ui": ("pdfarchiver.db", "pdfarchiver.fs", "pdfarchiver.parsing", "pdfarchiver.indexing",
           "pdfarchiver.search", "pdfarchiver.ocr", "pdfarchiver.semantic",
           "pdfarchiver.jobs", "pymupdf", "fitz"),
    # `fitz` 是 pymupdf 的弃用旧名（1.28 起打警告）：轮四十二 前阅读器靠它绕开了上面的
    # `pymupdf` 禁令，改口时当场红 —— 旧名同单禁止，堵掉这个洞（S2 现走 services/pdf_view 门面）。
    "services": ("pdfarchiver.ui",),
    "db": ("pdfarchiver.ui", "pdfarchiver.services", "pdfarchiver.ocr",
           "pdfarchiver.semantic", "pymupdf"),
    "fs": ("pdfarchiver.ui", "pdfarchiver.services", "pdfarchiver.db"),
    "parsing": ("pdfarchiver.ui", "pdfarchiver.services", "pdfarchiver.db"),
    "indexing": ("pdfarchiver.ui", "pdfarchiver.services", "pdfarchiver.db"),
    "search": ("pdfarchiver.ui", "pdfarchiver.semantic", "pymupdf"),
    "ocr": ("pdfarchiver.ui", "pdfarchiver.semantic"),
    "semantic": ("pdfarchiver.ui", "pdfarchiver.ocr"),
    "jobs": ("pdfarchiver.ui", "pdfarchiver.services"),
    "config": ("pdfarchiver.ui", "pdfarchiver.services", "pdfarchiver.db"),
    "diagnostics": ("pdfarchiver.ui", "pdfarchiver.services", "pdfarchiver.db"),
}

# SQL 只许出现在真正管库的地方（docs/ARCHITECTURE 一：只有 repositories 能写 SQL）。
# semantic/vector_store.py 是向量存储层（管理 .npy + vector_meta 表），属数据基础设施，同 db/engine.py。
SQL_ALLOWED_PATHS = ("db/repositories/", "db/migrations/", "db/migrate.py", "db/engine.py",
                     "semantic/vector_store.py")
SQL_RE = re.compile(
    r"\b(SELECT\s+\S+\s+FROM|INSERT\s+INTO|UPDATE\s+\S+\s+SET|DELETE\s+FROM|"
    r"CREATE\s+(UNIQUE\s+)?TABLE|CREATE\s+(UNIQUE\s+)?INDEX|PRAGMA\s+\w+)\b", re.I)

MAX_NAV_ITEMS_BEFORE_GROUPING = 20  # AGENTS.md「入口超 20 项就上分组 + 搜索」

# 阶段 1 验收 6：代码里不许出现本机路径字面量（盘符 / 家目录）。
MACHINE_LOCAL_PATH_RE = re.compile(r"[A-Za-z]:[\\/]{1,2}|[/\\]home[/\\]|[/\\]Users[/\\]")

# 界面层造出一个时间字符串所需的全部方法名（见 check_ui_time_formatting_single_exit）。
TIME_BUILDERS = frozenset({"strftime", "fromtimestamp", "utcfromtimestamp", "localtime"})


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


def check_direction_keys_reach_files() -> list[str]:
    """**ISSUES I94** 甲：方向表的每个键都必须至少扫到一个 .py 文件。

    恒真的守卫比没有守卫更糟 —— 它让「有牙」这件事被记在账上。旧版方向表里 `fileops`
    与 `backup` 两行扫的是 `src/pdfarchiver/fileops/` 与 `src/pdfarchiver/backup/`，
    这两个目录下各只有一个零字节 .gitkeep（不是可导入的包），PKG.rglob("*.py") 给不出
    任何一个文件 ⇒ 那两行永远满足，`archive_service` 里如果真出现 `import pdfarchiver.ui`
    本该由 `fileops` 那一行拦住 —— 它拦不住。这条断言就是让这种"空转规则"下次一加入
    当场红。
    """
    problems: list[str] = []
    layers_on_disk = {_layer_of(p) for p in _modules() if _layer_of(p)}
    for key in FORBIDDEN_IMPORTS:
        if key not in layers_on_disk:
            problems.append(
                f"FORBIDDEN_IMPORTS 里的键 `{key}` 在 src/pdfarchiver/{key}/ 下扫不到任何 .py 文件 —— "
                "这一行是恒真的空守卫（**ISSUES I94** 甲：`fileops` 与 `backup` 是 SPEC 层名，"
                "实际落点在 `services/archive_service.py` 与 `services/backup_service.py`，"
                "受 `services` 那一行管辖。要保留方向表里的这条约束，必须把它写进真正承载 "
                "代码所在的层，或删掉这一行）")
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


def check_semantic_model_path_single_source() -> list[str]:
    """ISSUES I37：语义层的模型根只许从 config.paths.models_dir 取，不许出现第二处路径字面量。

    与「探针自己的传感器也是代码」同族：如果 semantic/ 里有人硬编码了 `data/models/` 或
    `.probe_work/models/`，阶段 6 的"缺模型即降级"判据就会看错地方，永远报"模型缺失"。
    """
    # 只查 semantic/ 目录下的 .py 文件
    semantic_dir = PKG / "semantic"
    if not semantic_dir.exists():
        return []

    # 禁止的路径字面量模式（排除 docstring 与注释）
    banned_patterns = [
        re.compile(r'["\'](?:data|\.probe_work|models)[/\\]'),  # data/models/ .probe_work/models/
        re.compile(r'["\'][^"\']*models[^"\']*["\']'),  # 任何含 "models" 的字符串常量
    ]
    # 允许的引用（config.paths.models_dir 是唯一合法来源）
    allowed_patterns = [
        re.compile(r'self\._paths\.models_dir'),
        re.compile(r'paths\.models_dir'),
        re.compile(r'config\.paths'),
    ]

    problems: list[str] = []
    for path in semantic_dir.rglob("*.py"):
        rel = path.relative_to(SRC.parent).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        skip_ids = _docstring_ids(tree)
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                if id(node) in skip_ids:
                    continue
                val = node.value
                # 检查是否包含路径字面量（排除合法引用）
                if "models" in val.lower() and not any(p.search(val) for p in allowed_patterns):
                    # 只报真正像路径的（含 / 或 \）
                    if "/" in val or "\\" in val:
                        problems.append(
                            f"{rel}:{node.lineno} 字符串常量里有模型路径字面量 `{val[:50]}`；"
                            "ISSUES I37：语义层模型根只许从 config.paths.models_dir 取")
    return problems


def check_ui_time_formatting_single_exit() -> list[str]:
    """界面层不许自己拼时间串 —— 全站唯一出口是 `services/status_service`（整改计划第 7 条勾甲）。

    三个方法名就是造一个时间字符串所需的全部工具：`strftime`（拼串）、`fromtimestamp`
    （把秒变成带时区的 datetime）、`localtime` / `utcfromtimestamp`（同一件事的另外两条路）。
    拦这三个而不是拦 `import datetime`，是因为这条规则要钉的是**显示口径**：
    UI 里 import datetime 却不调它们，造不出一个能被读成"本地时间却标 Z"的串。

    为什么留两个出口不算破口：`format_ts`（到秒 + `Z`）与 `format_day`（到日）读同一份
    UTC 秒，只差截断粒度，且 §S5 线框自己要求日粒度（「必须显示"已消失（日期）"」）。
    口径唯一指的是**时区与标注**，不是指函数个数；两条都住在同一个模块里，才拦得住漂移。
    """
    ui_dir = PKG / "ui"
    problems: list[str] = []
    for path in sorted(ui_dir.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr in TIME_BUILDERS:
                rel = path.relative_to(SRC.parent).as_posix()
                problems.append(
                    f"{rel}:{node.lineno} 调了 `.{node.attr}(...)` —— 界面自己拼时间串就是第二个口径；"
                    "显示一律走 services/status_service.format_ts（到秒，带 `Z`）或 format_day（到日）"
                    "（AGENTS.md「禁止核心概念有多个口径」，D-022 把同一条规则写给了日志）")
    return problems


def all_problems() -> list[str]:
    return (check_import_direction() + check_direction_keys_reach_files()
            + check_sql_only_where_it_belongs()
            + check_no_silent_swallow() + check_no_machine_local_path_literal()
            + check_nav_entries_grouped() + check_semantic_model_path_single_source()
            + check_ui_time_formatting_single_exit())


def test_架构守卫全绿() -> None:
    problems = all_problems()
    if problems:
        raise ArchitectureError("\n".join(problems))


def test_界面不许自己拼时间串() -> None:
    """单独点名：第 7 条勾甲的落地判据。合进 `test_架构守卫全绿` 会让失败信息淹没在六条规则里。"""
    problems = check_ui_time_formatting_single_exit()
    if problems:
        raise ArchitectureError("\n".join(problems))


def test_方向表每个键至少扫到一个文件() -> None:
    """**ISSUES I94** 甲单独点名：空转的守卫比没有守卫更糟。

    合进 `test_架构守卫全绿` 会让「新加了一层但代码还没落地」这种形状被淹没在七条规则里；
    分出来才好用 —— p9 注入 I47 的坏法就是加一个假键，只有这一条能精确点名。
    """
    problems = check_direction_keys_reach_files()
    if problems:
        raise ArchitectureError("\n".join(problems))


if __name__ == "__main__":
    found = all_problems()
    for p in found:
        print("  RED  " + p)
    print("VERDICT: " + ("ALL GREEN" if not found else f"RED（{len(found)} 条）"))
    sys.exit(0 if not found else 1)
