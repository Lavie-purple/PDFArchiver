"""门禁的打印阶段不许把整条链打死 —— 编不出来的字符降级，读数照留。

现场（2026-10-27 轮三十一，整链一条命令那场）：`packaging/frozen_smoke.py` 的输出里
带 `text_pages − content_fts`（U+2212），它原样进了 `Row.measured`；`gates/final.py`
往 GBK 控制台打印现场时 `UnicodeEncodeError`，链在 soak 之后、package 之前断掉 ——
前 9 段已经跑完的读数全靠日志才救回来。同类事故 2026-10-22 在 `tests/probes/p13_soak.py`
的 `log()` 里犯过一次，当时只在那一条探针里兜住，所以这次换个口径收口：

1. **谁打印现场谁先兜底。** 门禁入口（`gates/*.py` 与 `scripts/precheck.py`）的 `main()`
   头三条语句里必须调 `harden_stdio()` —— 它把 stdout/stderr 的 `errors` 改成 `replace`，
   编不出来的字符变 `?`，整行读数照常留下。编码本身不动：改成 UTF-8 会让 GBK 屏上的
   中文全成乱码，那不是修，是换个坏法。
2. **兜底必须真有牙。** 同一段代码在 GBK 子进程里跑两遍：带兜底退出码 0 且那行以 `?`
   出现；不带兜底必须 `UnicodeEncodeError` 非 0 退出。两条一起，才说明这条守卫盯的是
   真会崩的那一步，而不是一句装饰。

跑法：
    python -m pytest tests/guards/test_gate_stdio_encoding.py -q
    python tests/guards/test_gate_stdio_encoding.py    # 独立跑，末行 VERDICT
"""
from __future__ import annotations

import ast
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
GATES = REPO / "gates"
HELPER = "harden_stdio"
WATCHED_GLOBS = ("gates/*.py",)
EXTRA_ENTRIES = (REPO / "scripts" / "precheck.py",)
MAX_LEAD = 3                         # 兜底必须出现在 main() 的前三条语句里

#: 真语料里的那一个字符（U+2212 减号），不是 ASCII '-' —— 它在 GBK 里编不出来。
MINUS = "\u2212"

PROBE_BODY = """
import sys
sys.path.insert(0, {gates!r})
from stage1 import harden_stdio
{harden}
print("现场：text_pages {minus} content_fts = 0")
"""


def _watched_files() -> list[Path]:
    files: list[Path] = []
    for pattern in WATCHED_GLOBS:
        files.extend(p for p in REPO.glob(pattern) if "__pycache__" not in p.parts)
    files.extend(p for p in EXTRA_ENTRIES if p.is_file())
    return sorted(set(files))


def _harden_is_early(tree: ast.AST) -> bool:
    """`main()` 的前 MAX_LEAD 条语句里有没有调 harden_stdio()。"""
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef) or node.name != "main":
            continue
        for stmt in node.body[:MAX_LEAD]:
            for call in ast.walk(stmt):
                if not isinstance(call, ast.Call):
                    continue
                name = getattr(call.func, "id", None) or getattr(call.func, "attr", None)
                if name == HELPER:
                    return True
        return False
    return False


def check_entry_hardening() -> tuple[list[str], int]:
    """返回（问题清单, 被核到的入口数）。后者给正对照用，防止判据被改松到 0 条。"""
    problems: list[str] = []
    watched = 0
    for path in _watched_files():
        rel = path.relative_to(REPO).as_posix()
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (SyntaxError, UnicodeDecodeError) as exc:
            problems.append(f"{rel}: 解析失败（{exc}）—— 这条守卫看不见它的内容")
            continue
        if not any(isinstance(n, ast.FunctionDef) and n.name == "main" for n in ast.walk(tree)):
            continue                 # 没有 main() 的模块不是入口，管不着
        watched += 1
        if not _harden_is_early(tree):
            problems.append(
                f"{rel}: main() 的前 {MAX_LEAD} 条语句里没有 `{HELPER}()` —— "
                "子进程输出里出现 GBK 编不出的字符（U+2212 等）时，这条入口会崩在打印阶段，"
                "把已经跑完的读数一起带走")
    return problems, watched


def _run_probe(harden: bool) -> subprocess.CompletedProcess[str]:
    code = PROBE_BODY.format(gates=str(GATES), minus=MINUS,
                             harden=f"{HELPER}()" if harden else "")
    env = {**os.environ, "PYTHONIOENCODING": "gbk", "PYTHONUTF8": "0"}
    return subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                          encoding="gbk", errors="replace", env=env, timeout=120)


def test_门禁入口都在_main_开头兜住打印编码() -> None:
    problems, _ = check_entry_hardening()
    if problems:
        raise AssertionError("\n".join(problems))


def test_判据打在真东西上而不是空集合() -> None:
    """正对照：被核到的入口必须还有门禁那几个。范围被改松、或 main() 全被改名，先看这条。"""
    _, watched = check_entry_hardening()
    assert watched >= 6, (
        f"只核到 {watched} 个带 main() 的门禁入口 —— 扫描范围（{'/'.join(WATCHED_GLOBS)} + "
        f"scripts/precheck.py）或 `_harden_is_early` 里的 main 匹配被动过")


def test_兜底在_GBK_控制台下真的救得回那行读数() -> None:
    good = _run_probe(harden=True)
    assert good.returncode == 0, f"带兜底仍然崩了：{(good.stderr or '')[-400:]}"
    assert "现场：text_pages ? content_fts = 0" in (good.stdout or ""), (
        f"那行读数没有以降级形式留下：{(good.stdout or '')[-200:]!r}")


def test_坏法真能让它红_不兜底必须崩() -> None:
    """这条守卫自己的牙：把 harden_stdio() 拿掉，同一段代码必须非 0 退出。"""
    bad = _run_probe(harden=False)
    assert bad.returncode != 0, "不兜底竟然也跑通了 —— 判据没有盯住真会崩的那一步"
    assert "UnicodeEncodeError" in (bad.stderr or ""), (
        f"崩的原因不是编码：{(bad.stderr or '')[-400:]}")


def test_静态判据的坏法注入() -> None:
    """位置判据本身：早调放行，没调 / 调晚了都必须红。"""
    cases = {
        "good-first": ("def main():\n    harden_stdio()\n    print('x')\n", True),
        "good-third": ("def main():\n    a = 1\n    b = 2\n    harden_stdio()\n", True),
        "bad-missing": ("def main():\n    print('x')\n", False),
        "bad-late": ("def main():\n    print('1')\n    print('2')\n    print('3')\n    harden_stdio()\n", False),
        "bad-other-func": ("def helper():\n    harden_stdio()\ndef main():\n    print('x')\n", False),
    }
    for name, (source, expect_ok) in cases.items():
        got = _harden_is_early(ast.parse(source))
        assert got is expect_ok, f"{name} 判成 {'放行' if got else '红'}，期望 {'放行' if expect_ok else '红'}"


if __name__ == "__main__":
    found, n = check_entry_hardening()
    for p in found:
        print("  RED  " + p)
    print(f"  INFO 核到 {n} 个门禁入口")
    print("VERDICT: " + ("ALL GREEN" if not found else f"RED（{len(found)} 条）"))
    sys.exit(0 if not found else 1)
