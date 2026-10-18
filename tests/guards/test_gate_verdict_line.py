"""谁自报生死，谁就必须用门禁链那一句口径 —— 末行 `VERDICT: ALL GREEN`。

现场（2026-10-18 重建 g2 段那一场）：`scripts/g2_search_benchmark.py` 自己判 **GREEN**
（P95=343ms，达标），而 `gates/final.py::_gate` 只认 `VERDICT: ALL GREEN`，于是外层判 **RED**。
同一次实测两份结论，而且 RED 那行里明明白白写着「实测：VERDICT: GREEN」—— 读门禁输出的人
还得自己发现这两句是一回事。这类账 `docs/CHANGELOG.md:109` 记着已经犯过一次（p9 那句
`ALL INJECTIONS CAUGHT` 就是这么改掉的），**改完没把规则变成断言，所以又长回来一次**。

判据只有一条，而且是静态的：门禁链引用到的脚本里，只要出现了 "VERDICT" 字样（=它自报生死），
文件里就必须出现链认的那句 `ALL GREEN`。不解析"到底哪一行是末行"，因为 f-string 与
`"VERDICT: " + ("ALL GREEN" if … else "RED（…）")` 两种写法在全仓混用，静态解析出的"末行"
不可靠，硬解析只会造出一堆假红（第一版就是这么写出 20 条噪声的）。
**失败那句写 `RED（n 条）` 不算违规** —— 那是链认的另一半，只在坏法注入里当反例用。

口径来源不是本文件：`gates/final.py:99` 的 `_gate` 写死了
`p.returncode == 0 and "VERDICT: ALL GREEN" in text`。本守卫钉的是"被引用的脚本"与
"它打印的那句"不许分家。

跑法：
    python -m pytest tests/guards/test_gate_verdict_line.py -q
    python tests/guards/test_gate_verdict_line.py    # 独立跑，末行 VERDICT
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
HARNESS_GLOBS = ("gates/*.py",)
CHAIN_VERDICT = "ALL GREEN"          # 链里唯一认的那句后缀（与 _gate 同源）
WATCHED_FLOOR = 15                   # 现数 21 个自报生死的被引用脚本；下限留余量，见正对照那条


def _string_constants(tree: ast.AST) -> list[tuple[int, str]]:
    out: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            out.append((node.lineno, node.value))
    return out


def _referenced_scripts() -> list[Path]:
    """门禁链引用到的脚本：`gates/*.py` 里以字符串字面量出现、且在仓库里真实存在的 `.py` 路径。
    覆盖 `P12 = "tests/probes/p12_consistency.py"` 与 `_run([sys.executable, "main.py", …])`
    两种写法。"""
    found: dict[Path, None] = {}
    for pattern in HARNESS_GLOBS:
        for harness in REPO.glob(pattern):
            tree = ast.parse(harness.read_text(encoding="utf-8"), filename=str(harness))
            for _, value in _string_constants(tree):
                if not value.endswith(".py"):
                    continue
                target = (REPO / value).resolve()
                if target.is_file():
                    found.setdefault(target)
    return sorted(found)


def _verdict_defects(rel: str, consts: list[tuple[int, str]]) -> tuple[int, list[str]]:
    """一个脚本的判定本体：它自不自报生死，自报的话链能不能读绿。

    逻辑只留这一份 —— 走磁盘的和坏法注入那条调的是同一个函数；写成两份的话，注入验的
    就不是真正在跑的那套判据，等于没有牙。返回 (是否自报生死 0/1, 问题清单)。"""
    claims = [v for _, v in consts if "VERDICT" in v]
    if not claims:
        return 0, []                       # 不自报生死的（产品入口 `main.py`）不管
    if any(CHAIN_VERDICT in v for _, v in consts):
        return 1, []
    return 1, [
        f"{rel}: 它会打印 VERDICT（{claims[:2]}）却没有 `{CHAIN_VERDICT}` 这一句 —— "
        f"门禁 `_gate` 只认「VERDICT: {CHAIN_VERDICT}」，于是它自己判绿、链子判红，"
        "同一个判定两个口径（AGENTS.md 禁止）"]


def check_chain_verdicts() -> tuple[list[str], int]:
    """返回（问题清单, 被核到的自报生死的脚本数）。后者给正对照用，防止判据被改松到 0 条。"""
    problems: list[str] = []
    watched = 0
    for path in _referenced_scripts():
        rel = path.relative_to(REPO).as_posix()
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (SyntaxError, UnicodeDecodeError) as exc:
            problems.append(f"{rel}: 解析失败（{exc}）—— 这条守卫看不见它的内容")
            continue
        seen, defects = _verdict_defects(rel, _string_constants(tree))
        watched += seen
        problems.extend(defects)
    return problems, watched


def test_链引用到的脚本都用链里那句_verdict() -> None:
    problems, _ = check_chain_verdicts()
    if problems:
        raise AssertionError("\n".join(problems))


def test_判据打在真东西上而不是空集合() -> None:
    """正对照：自报生死的被引用脚本必须还有二十个上下。范围或判据被改松，先看这条。"""
    _, watched = check_chain_verdicts()
    assert watched >= WATCHED_FLOOR, (
        f"只核到 {watched} 个「被门禁引用且自报生死」的脚本（下限 {WATCHED_FLOOR}）"
        f"—— 扫描范围（{'/'.join(HARNESS_GLOBS)}）或 `_verdict_defects` 里 `claims` 那处被动过")


def test_坏法真能让它红() -> None:
    """这条守卫自己的牙：把 g2 那一场原样复现一遍，必须被抓到；改对了必须放行。"""
    cases = {
        # g2 出事那一场：自己判 GREEN，链子只认 ALL GREEN
        "bad-green": ("import sys\nverdict = 'GREEN'\nprint(f'VERDICT: {verdict}')\nsys.exit(0)\n",
                      True),
        # 上一轮真实犯过的另一种：末行干脆不叫 VERDICT
        "bad-alias": ("print('ALL INJECTIONS CAUGHT')\nprint('VERDICT: 见上一行')\n", True),
        "good-ternary": ("print('VERDICT: ' + ('ALL GREEN' if not bad else f'RED（{len(bad)} 条）'))\n",
                         False),
        "good-fstring": ("verdict = 'ALL GREEN'\nprint(f'VERDICT: {verdict}')\n", False),
        "silent": ("print('只是普通脚本，不自报生死')\n", False),
    }
    for name, (source, expect_hit) in cases.items():
        _, defects = _verdict_defects(name, _string_constants(ast.parse(source)))
        assert bool(defects) is expect_hit, (
            f"{name} 判成 {defects or '绿'}，期望 {'红' if expect_hit else '绿'}")


if __name__ == "__main__":
    found, n = check_chain_verdicts()
    for p in found:
        print("  RED  " + p)
    print(f"  INFO 核到 {n} 个被门禁引用且自报生死的脚本")
    print("VERDICT: " + ("ALL GREEN" if not found else f"RED（{len(found)} 条）"))
    sys.exit(0 if not found else 1)
