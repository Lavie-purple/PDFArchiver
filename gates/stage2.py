"""阶段 2 验收门禁：在阶段 1 的闸门之上，加两条只有阶段 2 才有的实测。

跑法：
    python gates/stage2.py                  # 全跑（含 46 条反向注入，约 5–8 分钟）
    python gates/stage2.py --no-injection   # 跳过注入探针（约 1 分钟）

红线与阶段 1 一样：任何一条 RED 就打印 `VERDICT: RED（n 条）` 并非 0 退出。

新增的两条为什么必须由门禁跑、而不是"测试里有就算验过"：

1. **新 · 阶段 2 端到端验收（真 PDF / 真 worker / 真监听）** —— 阶段 2 的验收原文要的是
   "必须运行自动化测试并**展示真实搜索结果**"。门禁把 `tests/e2e` 的 `-s` 输出里
   那几行 `查询「…」` 原文抓回来打印，并把"检索到的行数"作为实测数字写进结论。
   没有这几行，门禁只是在报一个绿勾，而不是在展示证据。
2. **新 · 后台生命周期** —— 冷启动只证明界面打得开；worker 线程起没起、监听根挂没挂上、
   关窗有没有对账行，是 `state.log` 里的 `background.started` / `shutdown` 两件事。
   这一条同时兜住阶段 2 真崩过的那类事故：后台静默失灵时，界面上是看不出来的。

冷启动数字仍然不在这里掐表：读被测进程自己写进 `state.log` 的 `window.ready`，
与界面状态页同一个字段，两处不可能各说各话。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
import time
from pathlib import Path
from shutil import rmtree

sys.path.insert(0, str(Path(__file__).resolve().parent))
from stage1 import (G1_COLD_START_MAX, REPO, Row, _num, _run,  # noqa: E402
                    PYTEST_ERROR_RE, PYTEST_FAILED_RE, PYTEST_PASSED_RE)

SEARCH_EVIDENCE_RE = re.compile(r"^查询「")


def gate_e2e_acceptance() -> Row:
    """跑 `tests/e2e` 并把它打印出来的真实搜索结果搬进门禁输出。"""
    p = _run([sys.executable, "-m", "pytest", "tests/e2e", "-q", "-s", "--no-header"])
    out = p.stdout + p.stderr
    failed = _num(PYTEST_FAILED_RE, out)
    errored = _num(PYTEST_ERROR_RE, out)
    passed = _num(PYTEST_PASSED_RE, out)
    evidence = [ln for ln in out.splitlines() if SEARCH_EVIDENCE_RE.match(ln.strip())]
    located = [ln for ln in out.splitlines() if "[第 " in ln]
    summary = (f"{passed} 条端到端通过｜真实检索结论 {len(evidence)} 行｜"
               f"带页码的命中 {len(located)} 行")
    ok = p.returncode == 0 and failed == 0 and errored == 0 and len(evidence) >= 6 and located
    note = "" if ok else out[-1500:]
    for line in evidence[:8]:
        print(f"        证据：{line.strip()[:200]}")
    return Row("新 · 阶段 2 端到端验收（真 PDF / 真 worker / 真监听，展示真实搜索结果）", ok, summary, note)


def gate_background_lifecycle() -> Row:
    """真起一个进程：窗口就绪 → 后台起来 → 关窗对账，三件事都得在 state.log 里留行。"""
    work = Path(tempfile.mkdtemp(prefix="stage2_gate_"))
    try:
        t0 = time.perf_counter()
        p = _run([sys.executable, "main.py", "--data-dir", str(work), "--exit-after", "1.0"])
        wall = time.perf_counter() - t0
        if p.returncode != 0:
            return Row("新 · 后台生命周期（worker + 监听 + 关窗对账）", False, f"退出码 {p.returncode}",
                       (p.stdout + p.stderr)[-800:])
        log_file = work / "logs" / "state.log"
        if not log_file.is_file():
            return Row("新 · 后台生命周期（worker + 监听 + 关窗对账）", False, "state.log 不存在", str(work))
        events = [json.loads(l) for l in log_file.read_text(encoding="utf-8").splitlines() if l.strip()]
        by_name = {e["event"]: e for e in events}
        ready = by_name.get("window.ready")
        started = by_name.get("background.started")
        shutdown = by_name.get("shutdown")
        problems = []
        if ready is None:
            problems.append("没有 window.ready")
        if started is None:
            problems.append("没有 background.started —— 任务只会被排进队列而没人领")
        if shutdown is None:
            problems.append("没有 shutdown 对账行（关窗不等于退出）")
        if started is not None and int(started.get("threads", 0)) < 1:
            problems.append(f"worker 线程数为 {started.get('threads')}")
        cold = float(ready["cold_start_seconds"]) if ready else float("inf")
        if cold > G1_COLD_START_MAX:
            problems.append(f"冷启动 {cold:.3f}s 超过约定 {G1_COLD_START_MAX}s")
        measured = (f"冷启动 {cold:.3f}s｜进程总耗时 {wall:.3f}s｜"
                    f"worker {started.get('threads') if started else '—'} 线程｜"
                    f"回收中断 {started.get('recovered') if started else '—'}")
        return Row(f"新 · 后台生命周期（worker + 监听 + 关窗对账，冷启动 ≤ {G1_COLD_START_MAX}s [约定]）",
                   not problems, measured, "；".join(problems))
    finally:
        rmtree(work, ignore_errors=True)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="gates/stage2.py", description="阶段 2 验收门禁")
    ap.add_argument("--no-injection", action="store_true",
                    help="跳过 46 条反向注入（慢，约 3–5 分钟）；只在临时改动后想快速复查回归时用")
    args = ap.parse_args(argv)

    from stage1 import (gate_architecture, gate_cold_start, gate_dependency,  # noqa: PLC0415
                        gate_injection, gate_regression)

    checks = [gate_dependency(), gate_architecture(), gate_cold_start(),
              gate_background_lifecycle(), gate_e2e_acceptance(), gate_regression()]
    if not args.no_injection:
        checks.append(gate_injection())
    else:
        checks.append(Row("反向注入探针", True, "本次 --no-injection 跳过",
                          "注意：跳过注入时，「断言有约束力」这条没有被验证"))

    print(f"门禁运行于 {REPO}｜python {sys.version.split()[0]}")
    for row in checks:
        print(f"  {'PASS' if row.ok else 'RED '}  {row.gate}")
        print(f"        实测：{row.measured}")
        if row.note:
            print(f"        现场：{row.note[:600]}")
    bad = [r for r in checks if not r.ok]
    print("VERDICT: " + ("ALL GREEN" if not bad else f"RED（{len(bad)} 条未过）"))
    return 0 if not bad else 1


if __name__ == "__main__":
    raise SystemExit(main())
