"""worker 线程里不许有裸 `signal.emit(...)` —— 三处回主线程的形状只许有一份。

背景同 `tests/integration/test_worker_reply.py`：worker 的最后一行去 `emit` 时，接收方的
C++ 侧可能已经先没了，抛 `RuntimeError: Internal C++ object (…) already deleted`，
穿不出线程、由 `threading.excepthook` 记进 crash.log。**行为断言只能钉住它走过的那一站**，
下一个人在第四处里写裸 `emit` 时它看不见 —— 所以这里按 AST 把 `src/pdfarchiver/ui/` 全扫一遍。

两条判据与各自的坏法（2026-11-03 都真注入过一次，见 `.probe_work/r59_badway.log`）：

1. 任何被当作 `threading.Thread(target=…)` 传出去的函数体里，出现 `X.emit(…)` → 红，
   点名文件、函数名和行号。坏法：把 `library_page.py` 那一行改回裸 `self._search_ready.emit(...)`。
2. 有这种 worker 的文件集合，必须等于 `ui/thread_reply.py` 说明里点名的那三处，
   且那三个文件名确实写在其 docstring 里。坏法：在 `ui/tier.py` 里加一个用 `emit_if_alive`
   的 worker → 红（说明「一共三处」不再真），改文案后才会绿。

第 2 条防的是文档变散文：那句「一共三处」如果和代码数不上，就没有任何东西会提醒改它。
"""
from __future__ import annotations

import ast
from pathlib import Path

from pdfarchiver.ui import thread_reply

UI_ROOT = Path(thread_reply.__file__).resolve().parent
DOC_NAMED = ("library_page.py", "status_page.py", "health_panel.py")


def _module_thread_names(tree: ast.Module) -> set[str]:
    """这个文件里 `threading` 模块（和裸 `Thread`）可能被叫作的名字。

    只认字面量 `threading` 的话，`import threading as th` 一写守卫就静默看不见 —— A3 第一次
    注入就是这么绿的（2026-11-03，`.probe_work/r59_badway.log`）。
    """
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            names.update(a.asname or a.name for a in node.names if a.name == "threading")
        elif isinstance(node, ast.ImportFrom) and node.module == "threading":
            names.update(a.asname or a.name for a in node.names if a.name == "Thread")
    return names


def _thread_target(call: ast.Call, names: set[str]) -> str | None:
    """这个 Call 是不是 `threading.Thread(...)`／`Thread(...)`，是的话它 target= 的函数名。"""
    func = call.func
    is_thread = (isinstance(func, ast.Attribute) and func.attr == "Thread"
                 and isinstance(func.value, ast.Name) and func.value.id in names) \
        or (isinstance(func, ast.Name) and func.id in names)
    if not is_thread:
        return None
    for kw in call.keywords:
        if kw.arg == "target" and isinstance(kw.value, ast.Name):
            return kw.value.id
    return None


def _workers(tree: ast.Module) -> list[ast.FunctionDef]:
    """文件里所有「被起成后台线程」的函数（三处都是方法体内定义的 `work` 闭包）。"""
    names = _module_thread_names(tree)
    found: list[ast.FunctionDef] = []
    for holder in (n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)):
        for call in (c for c in ast.walk(holder) if isinstance(c, ast.Call)):
            name = _thread_target(call, names)
            if name is None:
                continue
            found.extend(sub for sub in ast.walk(holder)
                         if isinstance(sub, ast.FunctionDef) and sub.name == name)
    return found


def test_worker_线程里不许有裸_emit() -> None:
    offenders: list[str] = []
    for py in sorted(UI_ROOT.rglob("*.py")):
        for work in _workers(ast.parse(py.read_text(encoding="utf-8"))):
            for call in (c for c in ast.walk(work) if isinstance(c, ast.Call)):
                if isinstance(call.func, ast.Attribute) and call.func.attr == "emit":
                    offenders.append(f"{py.name}::{work.name}:{work.lineno} 裸 emit @ {call.lineno}")
    assert not offenders, (
        "后台线程最后一行必须走 ui/thread_reply.py::emit_if_alive —— 接收方的 C++ 侧可能"
        f"已经先没了，裸 emit 抛 RuntimeError 出不了线程：{offenders}")


def test_有worker的文件与_thread_reply_点名的三处一致() -> None:
    files = {py.name for py in sorted(UI_ROOT.rglob("*.py"))
             if _workers(ast.parse(py.read_text(encoding="utf-8")))}
    assert files == set(DOC_NAMED), (
        f"ui/ 下真在后台线程里回主线程的文件是 {sorted(files)}，"
        f"而 thread_reply.py 的说明写的是 {sorted(DOC_NAMED)} —— 两处必须一起改")
    doc = thread_reply.__doc__ or ""
    missing = [name for name in DOC_NAMED if name not in doc]
    assert not missing, f"thread_reply.py 的说明里没点名这几个站点文件：{missing}"
