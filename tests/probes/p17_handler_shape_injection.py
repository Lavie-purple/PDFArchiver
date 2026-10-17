"""坏法注入证伪 **ISSUES I68** 甲（队列处理函数的形状核对），AGENTS.md：每写完一条断言，
先用"能骗过它的坏法"真注入一次；不会变红的断言直接删。

核对长在 `WorkQueue.__init__`：`inspect.signature(fn).bind(None, None)` 不成就 ValueError 并点名种类。
三条坏法各自是一种"看着像守卫"的写法：

- H1 只 bind 一个位置参数 —— 「少收一个」的 handler 被放行（archive 当年的 bug 是**多**收，
  这一条盯的是反方向）
- H2 捕获后不上抛、只记日志 —— 永远绿
- H3 只核对 archive 一种 —— 以后新加的种类带坏签名照样装上

用法（改动只落在工作区，跑完按原字节还原；跑之前确认工作区干净）：
    .venv/Scripts/python.exe tests/probes/p17_handler_shape_injection.py
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
PY = str(REPO / ".venv" / "Scripts" / "python.exe")
SRC = REPO / "src" / "pdfarchiver" / "jobs" / "queue.py"
NODE = ("tests/integration/test_job_queue.py::"
        "test_处理函数形状不合队列契约时装配当场拒绝")

BIND = "inspect.signature(fn).bind(None, None)"
RAISE = ('                raise ValueError(\n'
         '                    f"处理函数 {kind} 不合队列契约 handler(job, monitor)：{exc}"\n'
         '                ) from exc')
LOOP = "for kind, fn in sorted(handlers.items()):"

MUTATIONS = [
    ("H1", "bind 只给一个位置参数（少收一个的坏 handler 就放行了）", BIND,
     "inspect.signature(fn).bind(None)"),
    ("H2", "捕获后不上抛，只记日志（永远绿）", RAISE,
     "                logging.getLogger(__name__).warning('shape %s', kind)"),
    ("H3", "核对只盯 archive，其它种类不看", LOOP,
     LOOP + "\n            if kind != \"archive\":\n                continue"),
]


def run() -> tuple[int, str]:
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen",
               PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
    proc = subprocess.run(
        [PY, "-m", "pytest", NODE, "-q", "--no-header",
         "-p", "no:randomly", "-p", "no:cacheprovider"],
        cwd=str(REPO), env=env, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=600)
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def main() -> int:
    raw = SRC.read_bytes()
    newline = "\r\n" if b"\r\n" in raw else "\n"
    survivors = []
    code, out = run()
    if code != 0:
        print("!! 基线就没绿，先修守卫再谈注入：\n" + out[-2500:])
        return 1
    print("基线绿（注入之前这条断言是真过的）\n")
    for mid, desc, old, new in MUTATIONS:
        anchor = old.replace("\n", newline).encode("utf-8")
        injected = new.replace("\n", newline).encode("utf-8")
        if raw.count(anchor) != 1:
            print(f"{mid:3} SKIP  锚点不唯一或不在场：{desc}")
            survivors.append(mid)
            continue
        try:
            SRC.write_bytes(raw.replace(anchor, injected, 1))
            code, out = run()
        finally:
            SRC.write_bytes(raw)
        failed = [ln.split("::")[-1].split(" ")[0] for ln in out.splitlines()
                  if ln.startswith("FAILED ")]
        tail = " | ".join(x.strip() for x in out.strip().splitlines()[-2:])
        named = NODE.split("::")[-1] in failed
        tag = ("红（有牙）" if named
               else ("绿!! 坏法没被抓住" if not code else "红但没点名（是崩了不是断言）"))
        print(f"{mid:3} {tag}  {desc}  ← {', '.join(failed) or '无'}  ::  {tail[:130]}")
        if not named:
            survivors.append(mid)
    if SRC.read_bytes() != raw:
        print("注意：源文件没还原成注入前的字节，已强制写回")
        SRC.write_bytes(raw)
    print(f"\nVERDICT: {'ALL GREEN' if not survivors else 'RED（漏网 ' + ' '.join(survivors) + '）'}")
    return 0 if not survivors else 2


if __name__ == "__main__":
    sys.exit(main())
