"""工具侧的 subprocess 不许跟随解释器的偏好编码 —— 门禁因此不可复现。

现场（2026-10-18 重建冻结产物那一场）：`packaging/frozen_smoke.py` 里两条 `taskkill`
用 `capture_output=True, text=True` 而没有写 `encoding=`，于是解码编码取
`locale.getpreferredencoding()`。不带 `PYTHONUTF8` 时那是 cp936，恰好对得上 taskkill 的
OEM 输出；带上 `PYTHONUTF8=1` 之后它变成 UTF-8，「成」的 GBK 字节 `0xB3 0xC9` 当场
`UnicodeDecodeError`，读线程炸、`--only package` 判 RED。同一条命令、同一份源码，只因为
调用方有没有设环境变量而一绿一红 —— 这不是产品缺陷，是**门禁不可复现**。

口径沿用 `docs/ISSUES.md` 附「编码不是 bug 是口径」那一行，本守卫钉的是它的**可判定部分**：
凡是「把子进程输出取回 Python 里」的 text 模式调用，必须**显式写出** `encoding=` 与 `errors=`。
值允许是什么由调用点决定 —— 读 Python 工具的输出一律 `utf-8`，读控制台工具（taskkill）
按机器真实的 OEM 代码页（`packaging/frozen_smoke.py` 的 `console_encoding()`）。
两种都比"跟随解释器"强，因为解释器的偏好编码会被 `PYTHONUTF8` 改掉，而子进程的编码不会。

判据只盯输出被取回来的调用（`capture_output`，或 stdout/stderr 是 `subprocess.PIPE`）：
`text=True` 但把输出重定向到文件对象的不算 —— 那种调用根本不解码
（`tests/probes/p13_soak.py:416` 就是这一类，它注释里写明了为什么用文件而不是管道）。

跑法：
    python -m pytest tests/guards/test_subprocess_encoding.py -q
    python tests/guards/test_subprocess_encoding.py    # 独立跑，末行 VERDICT
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
TOOL_DIRS = ("packaging", "gates", "scripts", "tests")
CALL_NAMES = {"run", "Popen", "check_output"}   # check_call 不把输出取回 Python，不在范围内
OWNERS = {"subprocess", ""}          # 裸 `run(...)` = `from subprocess import run`
WATCHED_FLOOR = 15                   # 现数 18 处 / 14 个文件；下限留 3 处余量，见正对照那条


def _owner(func: ast.expr) -> str | None:
    """`subprocess.run(...)` → "subprocess"；裸 `run(...)` → ""；其余 → None（不认）。"""
    if isinstance(func, ast.Name):
        return ""
    if isinstance(func, ast.Attribute):
        base = func.value
        if isinstance(base, ast.Name):
            return base.id
        # `x.subprocess.run` 这种链不在范围内
    return None


def _captured(call: ast.Call) -> bool:
    """输出会不会被取回 Python 里 —— 只有会解码的调用才需要声明编码。"""
    func_name = getattr(call.func, "attr", None) or getattr(call.func, "id", None)
    if func_name == "check_output":        # 它天生把 stdout 读回来
        return True
    kw = {k.arg: k.value for k in call.keywords if k.arg}
    if kw.get("capture_output") is not None:
        return True
    return any(isinstance(kw.get(name), ast.Attribute) and kw[name].attr == "PIPE"
               for name in ("stdout", "stderr"))


def _texty(call: ast.Call) -> bool:
    kw = {k.arg for k in call.keywords if k.arg}
    return "text" in kw or "universal_newlines" in kw


def _encoding_calls(tree: ast.AST) -> list[ast.Call]:
    out: list[ast.Call] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = getattr(node.func, "attr", None) or getattr(node.func, "id", None)
        if name not in CALL_NAMES:
            continue
        if _owner(node.func) not in OWNERS:
            continue
        if _texty(node) and _captured(node):
            out.append(node)
    return out


def _tool_files() -> list[Path]:
    files: list[Path] = []
    for d in TOOL_DIRS:
        root = REPO / d
        if not root.is_dir():
            continue
        files.extend(p for p in root.rglob("*.py") if "__pycache__" not in p.parts)
    return sorted(files)


def check_subprocess_encodings() -> tuple[list[str], int]:
    """返回（问题清单, 被核到的调用处数）。后者给正对照用，防止判据被改松到 0 条。"""
    problems: list[str] = []
    watched = 0
    for path in _tool_files():
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (SyntaxError, UnicodeDecodeError) as exc:
            problems.append(f"{path.relative_to(REPO)}: 解析失败（{exc}）—— 这条守卫看不见它的内容")
            continue
        for node in _encoding_calls(tree):
            watched += 1
            kw = {k.arg for k in node.keywords if k.arg}
            missing = [k for k in ("encoding", "errors") if k not in kw]
            if missing:
                name = getattr(node.func, "attr", None) or getattr(node.func, "id", None)
                problems.append(
                    f"{path.relative_to(REPO)}:{node.lineno} `subprocess.{name}` 把输出取回 Python "
                    f"却没写 `{'` / `'.join(missing)}` —— 它跟随解释器的偏好编码，"
                    "换一台机器或设了 PYTHONUTF8 就会在读线程里炸")
    return problems, watched


def test_取回输出的_subprocess_必须显式声明编码() -> None:
    problems, _ = check_subprocess_encodings()
    if problems:
        raise AssertionError("\n".join(problems))


def test_判据打在真东西上而不是空集合() -> None:
    """正对照：被盯住的调用必须还有几十处。判据被改松、或工具侧调用整批消失，都要先看一眼。"""
    _, watched = check_subprocess_encodings()
    assert watched >= WATCHED_FLOOR, (
        f"只核到 {watched} 处『取回输出 + text 模式』的 subprocess 调用（下限 {WATCHED_FLOOR}）"
        f"—— 扫描范围（{'/'.join(TOOL_DIRS)}）、`_texty`、`_captured` 三处之一被动过")


if __name__ == "__main__":
    found, n = check_subprocess_encodings()
    for p in found:
        print("  RED  " + p)
    print(f"  INFO 核到 {n} 处取回输出的 text 模式 subprocess 调用")
    print("VERDICT: " + ("ALL GREEN" if not found else f"RED（{len(found)} 条）"))
    sys.exit(0 if not found else 1)
