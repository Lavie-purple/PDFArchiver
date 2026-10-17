"""阶段 1 验收门禁：一条命令串起「取数 → 校验 → 结论」，末行必须打印 VERDICT。

跑法：
    python gates/stage1.py                 # 全跑（约 1 分钟，含 18 条反向注入）
    python gates/stage1.py --no-injection   # 跳过注入探针，只跑回归与冷启动（约 15 秒）

红线：任何一条 RED 就打印 `VERDICT: RED（n 条）` 并以非 0 退出 —— 这条命令不绿，
阶段 1 不算收尾，不许开阶段 2（AGENTS.md「发布要有门禁」）。

冷启动数字**不在这里掐表**：由被测进程自己写进 state.log 的 `window.ready`，
门禁只读那一条。界面状态页显示的是同一个字段，两处不可能各说各话。
数据目录用系统临时目录里的空目录，不碰任何真实数据。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from shutil import rmtree

REPO = Path(__file__).resolve().parents[1]
G1_COLD_START_MAX = 1.5  # [约定] docs/ROADMAP 阶段 1；改这一处，界面和门禁同步
PYTEST_FAILED_RE = re.compile(r"(\d+) failed")
PYTEST_ERROR_RE = re.compile(r"(\d+) error")
PYTEST_PASSED_RE = re.compile(r"(\d+) passed")
PYTEST_SKIPPED_RE = re.compile(r"(\d+) skipped")


@dataclass
class Row:
    gate: str
    ok: bool
    measured: str
    note: str = ""


def _run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=str(REPO),
                          env={**os.environ, "QT_QPA_PLATFORM": "offscreen",
                               "PYTHONIOENCODING": "utf-8"},
                          capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=1800)


def _last_line(proc: subprocess.CompletedProcess[str]) -> str:
    lines = [l for l in (proc.stdout + proc.stderr).splitlines() if l.strip()]
    return lines[-1] if lines else "(无输出)"


def gate_dependency() -> Row:
    p = _run([sys.executable, "tests/guards/test_dependency_pins.py"])
    green = p.returncode == 0 and "VERDICT: ALL GREEN" in p.stdout
    return Row("G21 依赖守卫", green, _last_line(p),
               "" if green else p.stdout[-400:] + p.stderr[-400:])


def gate_architecture() -> Row:
    p = _run([sys.executable, "tests/guards/test_architecture.py"])
    green = p.returncode == 0 and "VERDICT: ALL GREEN" in p.stdout
    return Row("架构守卫（依赖方向 / SQL 位置 / 无静默吞异常 / 无本机路径字面量 / 导航分组）", green, _last_line(p),
               "" if green else p.stdout[-600:])


def gate_regression() -> Row:
    p = _run([sys.executable, "-m", "pytest", "tests", "-q", "--no-header"])
    out = p.stdout + p.stderr
    failed = _num(PYTEST_FAILED_RE, out)
    errored = _num(PYTEST_ERROR_RE, out)
    passed = _num(PYTEST_PASSED_RE, out)
    skipped = _num(PYTEST_SKIPPED_RE, out)
    summary = f"{passed} passed / {failed} failed / {errored} error / {skipped} skipped"
    return Row("全量回归", p.returncode == 0 and failed == 0 and errored == 0, summary,
               "" if p.returncode == 0 else out[-1500:])


def gate_injection() -> Row:
    p = _run([sys.executable, "tests/probes/p9_reverse_injection.py"])
    caught = re.search(r"抓到 (\d+)/(\d+) 条坏法", p.stdout)
    measured = f"{caught.group(1)}/{caught.group(2)} 条坏法被抓到" if caught else _last_line(p)
    return Row("反向注入探针（断言有没有约束力）",
               p.returncode == 0 and "VERDICT: ALL GREEN" in p.stdout, measured,
               "" if p.returncode == 0 else p.stdout[-1500:])


def gate_cold_start() -> Row:
    """真起一个进程跑 `python main.py`：解释器 + 依赖 import + 装配 + 首屏，一个都不少。"""
    work = Path(tempfile.mkdtemp(prefix="stage1_gate_"))
    try:
        t0 = time.perf_counter()
        p = _run([sys.executable, "main.py", "--data-dir", str(work), "--exit-after", "0.3"])
        wall = time.perf_counter() - t0
        if p.returncode != 0:
            return Row("G1 冷启动 + 能关窗", False, f"退出码 {p.returncode}",
                       (p.stdout + p.stderr)[-800:])
        log_file = work / "logs" / "state.log"
        if not log_file.is_file():
            return Row("G1 冷启动 + 能关窗", False, "state.log 不存在", str(work))
        events = [json.loads(l) for l in log_file.read_text(encoding="utf-8").splitlines() if l.strip()]
        ready = [e for e in events if e["event"] == "window.ready"]
        if not ready:
            return Row("G1 冷启动 + 能关窗", False, "没有 window.ready 事件",
                       json.dumps(events, ensure_ascii=False)[:500])
        cold = float(ready[-1]["cold_start_seconds"])
        shutdowns = [e for e in events if e["event"] == "shutdown"]
        ok = cold <= G1_COLD_START_MAX and bool(shutdowns)
        note = "" if shutdowns else "窗口关闭路径没留对账行 —— 关窗不等于退出"
        return Row(f"G1 冷启动 ≤ {G1_COLD_START_MAX}s [约定] + 关窗对账", ok,
                   f"冷启动 {cold:.3f}s｜进程总耗时 {wall:.3f}s｜关窗对账 {len(shutdowns)} 条", note)
    finally:
        rmtree(work, ignore_errors=True)


def _num(pat: re.Pattern[str], text: str) -> int:
    m = pat.search(text)
    return int(m.group(1)) if m else 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="gates/stage1.py", description="阶段 1 验收门禁")
    ap.add_argument("--no-injection", action="store_true",
                    help="跳过 18 条反向注入（慢，约 1 分钟）；只在临时改动后想快速复查回归时用")
    args = ap.parse_args(argv)

    checks = [gate_dependency(), gate_architecture(), gate_regression(), gate_cold_start()]
    if not args.no_injection:
        checks.append(gate_injection())

    print(f"门禁运行于 {REPO}｜python {sys.version.split()[0]}")
    for row in checks:
        print(f"  {'PASS' if row.ok else 'RED '}  {row.gate}")
        print(f"        实测：{row.measured}")
        if row.note:
            print(f"        现场：{row.note[:600]}")
    if args.no_injection:
        # 跳过不许算成一条 PASS —— 那样「N 条全绿」里就混了一件没跑的事（ISSUES I36 同一形状）
        print("  SKIP  反向注入探针（--no-injection）—— 这一场的「全绿」不含「断言有约束力」这条")
    bad = [r for r in checks if not r.ok]
    print(f"  合计判定 {len(checks)} 条")
    print("VERDICT: " + ("ALL GREEN" if not bad else f"RED（{len(bad)} 条未过）"))
    return 0 if not bad else 1


if __name__ == "__main__":
    raise SystemExit(main())
