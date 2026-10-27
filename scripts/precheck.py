"""收尾前置一键预检 —— 把「自伤红」挡在整链之前。

**为什么有这一条**（2026-10-24 轮二十三，用户点名处置）：轮二十二整链 35 条判定里 3 条红
全都不是产品缺陷 —— ① regression 与 ② injection/p16 是同一个根因（新写的文档把
`.probe_work/` 探针名写成裸名，失效 `.py` 名字 46 > 上限 37），③ consistency 是把
`--data-root` 传深了一层。三条都要花整链量级的时间才被发现，而它们各自只要 2 秒 / 20 秒
就能判 —— 所以收尾前先跑这一条，红了就地修，别拿整链当第一道筛子。

**两步**（顺序固定，前一步红就停）：
  1) `pytest tests/guards -q` —— 文档指针 / 台账结构 / 文件长度 / 编码 / 依赖方向…
  2) `gates/final.py --only docs-inject --only guards` —— 交付文档门禁自己的坏法注入
     + 依赖与架构守卫（与整链里同名的两段逐字同源）。

跑法：
    python scripts/precheck.py             # 末行只有一条 VERDICT
    python scripts/precheck.py --verbose   # 透传子命令全部输出
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PY = sys.executable

sys.path.insert(0, str(REPO / "gates"))
from stage1 import harden_stdio  # noqa: E402  与门禁链同一个兜底，不写第二份

#: 顺序固定：守卫全量在最前，门禁两段在后（门禁自己也会起子进程，放后面少一次冷启动叠加）。
STEPS: list[tuple[str, list[str]]] = [
    ("tests/guards（守卫全量）", [PY, "-m", "pytest", "tests/guards", "-q"]),
    ("gates/final.py docs-inject + guards", [PY, "gates/final.py",
                                             "--only", "docs-inject", "--only", "guards"]),
]


def _run(argv: list[str]) -> tuple[bool, str]:
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
    proc = subprocess.run(argv, cwd=REPO, env=env, capture_output=True,
                          text=True, encoding="utf-8", errors="replace")
    return proc.returncode == 0, (proc.stdout or "") + (proc.stderr or "")


def _tail(text: str, lines: int) -> str:
    rows = [ln for ln in text.splitlines() if ln.strip()]
    return "\n".join(rows[-lines:])


def main(argv: list[str] | None = None, runner=_run) -> int:
    harden_stdio()
    ap = argparse.ArgumentParser(prog="scripts/precheck.py", description=__doc__.splitlines()[0])
    ap.add_argument("--verbose", action="store_true", help="透传两步的全部输出")
    args = ap.parse_args(argv)

    print(f"收尾预检运行于 {REPO}｜python {sys.version.split()[0]}")
    red = 0
    for i, (name, cmd) in enumerate(STEPS, 1):
        ok, out = runner(cmd)
        print(f"  {'PASS' if ok else 'RED '}  {i}/{len(STEPS)}  {name}")
        if args.verbose:
            print(out.rstrip())
        else:
            print("        " + _tail(out, 6 if ok else 30).replace("\n", "\n        "))
        if not ok:
            red += 1
            print("        现场：这一步红了就不再往下跑 —— 整链不替它兜底")
            break
    print(f"  合计 {len(STEPS)} 步｜红 {red}")
    print("VERDICT: " + ("ALL GREEN" if not red else f"RED（{red} 步未过）"))
    return 0 if not red else 1


if __name__ == "__main__":
    raise SystemExit(main())
