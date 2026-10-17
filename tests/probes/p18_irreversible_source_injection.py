"""坏法注入证伪 **ISSUES I69** 丙（「不可逆」的口径只许有一处），AGENTS.md：
每写完一条断言，先用"能骗过它的坏法"真注入一次；不会变红的断言直接删。

归一之后三处读同一条表达式：`PlannedMove.irreversible` → S3 界面显示的那条数 → 落库的
`reversible` 字段（S4 的档就数这个字段）。三条坏法就是三种"退回各算各的"：

- S1 落库字段退回第二条表达式（`1 if will_move else 0`）
- S2 界面自己数一遍，且判据与服务不同（凡是有目标路径就算）
- S3 服务的定义退化成「能搬 = 不可逆」

每条要求红且**点名**是哪一条断言，不许三条一起红。用法（跑前确认工作区干净）：
    .venv/Scripts/python.exe tests/probes/p18_irreversible_source_injection.py
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
PY = str(REPO / ".venv" / "Scripts" / "python.exe")
SVC = REPO / "src" / "pdfarchiver" / "services" / "archive_service.py"
PAGE = REPO / "src" / "pdfarchiver" / "ui" / "pages" / "archive_page.py"
CLASS = ("tests/integration/test_archive_disk_safety.py::"
         "TestIrreversibleSingleSource")

PROP = "        return self.will_move and Path(self.dst_path).exists()"
BATCH = "reversible=0 if (not move.will_move or move.irreversible) else 1,"
COUNT = '"irreversible": sum(1 for m in moves if m.irreversible),'

# (id, 说明, 文件, 旧, 新)
MUTATIONS = [
    ("S1", "落库字段退回第二条表达式", SVC, BATCH,
     "reversible=1 if move.will_move else 0,"),
    ("S2", "界面自己数一遍且判据不同（凡是有目标路径就算）", PAGE, COUNT,
     '"irreversible": sum(1 for m in moves if m.dst_path),'),
    ("S3", "服务的定义退化成「能搬 = 不可逆」", SVC, PROP, "        return self.will_move"),
]


def run() -> tuple[int, str, list[str]]:
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen",
               PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
    proc = subprocess.run(
        [PY, "-m", "pytest", CLASS, "-q", "--no-header", "-rf",
         "-p", "no:randomly", "-p", "no:cacheprovider"],
        cwd=str(REPO), env=env, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=600)
    out = (proc.stdout or "") + (proc.stderr or "")
    failed = [ln.split("::")[-1].split(" ")[0] for ln in out.splitlines()
              if ln.startswith("FAILED ")]
    return proc.returncode, out, failed


def main() -> int:
    originals = {p: p.read_bytes() for p in (SVC, PAGE)}
    newline = {p: ("\r\n" if b"\r\n" in raw else "\n") for p, raw in originals.items()}
    code, out, _ = run()
    if code != 0:
        print("!! 基线就没绿，先修断言再谈注入：\n" + out[-2500:])
        return 1
    print("基线绿（三条断言在注入之前是真过的）\n")
    survivors = []
    for mid, desc, path, old, new in MUTATIONS:
        raw = originals[path]
        anchor = old.replace("\n", newline[path]).encode("utf-8")
        injected = new.replace("\n", newline[path]).encode("utf-8")
        if raw.count(anchor) != 1:
            print(f"{mid:3} SKIP  锚点不唯一或不在场：{desc}")
            survivors.append(mid)
            continue
        try:
            path.write_bytes(raw.replace(anchor, injected, 1))
            code, out, failed = run()
        finally:
            path.write_bytes(raw)
        tail = " | ".join(x.strip() for x in out.strip().splitlines()[-2:])
        tag = ("红（有牙）" if failed
               else ("绿!! 坏法没被抓住" if not code else "红但没点名（是崩了不是断言）"))
        print(f"{mid:3} {tag}  {desc}  "
              f"点名 {failed}  ::  {tail[:120]}")
        if not failed:
            survivors.append(mid)
    for path, raw in originals.items():
        if path.read_bytes() != raw:
            path.write_bytes(raw)
            print(f"注意：{path.name} 没还原成注入前的字节，已强制写回")
    print(f"\nVERDICT: {'ALL GREEN' if not survivors else 'RED（漏网 ' + ' '.join(survivors) + '）'}")
    return 0 if not survivors else 2


if __name__ == "__main__":
    sys.exit(main())
