"""测试自身卫生守卫：**同一作用域里的同名定义会让前一个永远不被执行**。

Python 同一模块内两次 `def test_同一名字`，只有最后一次进入命名空间：前一份连同它的
断言一起变成死代码，而 `pytest -q` 报的条数一点没少 —— 看着像有两条覆盖，实际只有
一条。本仓库实测发生过：`tests/integration/test_job_queue.py` 有两对同名，其中
「退出闸门 + 用户取消同时按下」那条从没跑过，直到本轮 AST 扫出来才发现。

按 AGENTS.md「发现一类先问还有哪些地方是同类」，判据一次覆盖整棵 `tests/` 树、
覆盖**任意作用域**（模块级与函数体内都可能遮蔽），而不是只修那一个文件。
只比函数名（含 `pytest.fixture`）：两个同名 fixture 同样是后者盖掉前者。

跑法：
    python -m pytest tests/guards/test_test_hygiene.py -q
    python tests/guards/test_test_hygiene.py      # 独立跑，末行 VERDICT
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

TESTS = Path(__file__).resolve().parents[1]

FUNCTION_NODES = (ast.FunctionDef, ast.AsyncFunctionDef)


def _scopes(tree: ast.AST) -> list[tuple[str, list[ast.stmt]]]:
    """所有能发生遮蔽的作用域：模块体 + 每个函数/类的直接语句体。"""
    out: list[tuple[str, list[ast.stmt]]] = [("（模块）", list(getattr(tree, "body", [])))]
    for node in ast.walk(tree):
        if isinstance(node, (*FUNCTION_NODES, ast.ClassDef)):
            out.append((node.name, list(node.body)))
    return out


def check_no_shadowed_definitions() -> list[str]:
    problems: list[str] = []
    # 只看 pytest 会收集/执行的文件：`probes/` 下是一次性脚本，把它们拉进来只会让这条守卫
    # 因为一个语法错误而红，而那个语法错误与「同名遮蔽」毫无关系。
    files = [*TESTS.rglob("test_*.py"), *TESTS.rglob("conftest.py")]
    for path in sorted(set(files)):
        if "__pycache__" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for scope, body in _scopes(tree):
            names = [n.name for n in body if isinstance(n, FUNCTION_NODES)]
            for name in sorted({n for n in names if names.count(n) > 1}):
                lines = [str(n.lineno) for n in body
                         if isinstance(n, FUNCTION_NODES) and n.name == name]
                problems.append(
                    f"{path.relative_to(TESTS.parent)}:{scope} 里 `{name}` 定义了 "
                    f"{names.count(name)} 次（第 {', '.join(lines)} 行）—— "
                    "只有最后一次生效，前面那份的断言一条都不会跑")
    return problems


def test_tests_树里没有同名定义() -> None:
    problems = check_no_shadowed_definitions()
    if problems:
        raise AssertionError("\n".join(problems))


if __name__ == "__main__":
    found = check_no_shadowed_definitions()
    for p in found:
        print("  RED  " + p)
    print("VERDICT: " + ("ALL GREEN" if not found else f"RED（{len(found)} 条）"))
    sys.exit(0 if not found else 1)
