"""坏法注入证伪 `tests/guards/test_doc_pointers.py`（AGENTS.md：每写完一条断言，先用"能骗过它的坏法"真注入一次）。

用法：
    .venv/Scripts/python.exe tests/probes/p16_doc_pointers_injection.py            # 全跑
    .venv/Scripts/python.exe tests/probes/p16_doc_pointers_injection.py P1 P4 ...   # 只跑指定 id

五条坏法各往文档里插一句"引用一个不存在的东西"，跑守卫的四条断言，要求：
1. 必须红；2. 红的必须是**对应那一条**断言（点名），不是四条一起红、也不是随便一条崩了。
P5 是**反向对照**：往台账类文档（`docs/CHANGELOG.md`）里插一个不存在的测试名，必须**仍绿** ——
这条证明"台账豁免"是刻意划出来的边界，不是守卫整体放空。
跑完立即按原字节还原；改动只落在工作区，不提交。

锚点按工作区的行尾匹配（本仓索引全是 LF，但 `core.autocrlf=true` 且没有 `.gitattributes`，
`git checkout` 出来的文件在 Windows 工作区是 CRLF，工具新写的文件是 LF）。
跑之前先确认工作区干净：它直接改文档，中途硬打断会留下注入态。
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
PY = str(REPO / ".venv" / "Scripts" / "python.exe")

GUARD = "tests/guards/test_doc_pointers.py::"
T_DEC = GUARD + "test_文档里的决策编号都真实存在"
T_ISS = GUARD + "test_文档里的台账编号都真实存在"
T_SEC = GUARD + "test_文档里的节号指针都落得下去"
T_TEST = GUARD + "test_活文档里引用的测试名都还在场"

USAGE = "docs/USAGE.md"
CHANGELOG = "docs/CHANGELOG.md"
ANCHOR = "## 九、性能与量级的真实边界"
LEDGER_ANCHOR = "# 变更日志"

# (id, 说明, 文件, 锚点, 注入内容, 该被点名的测试 node id)
MUTATIONS: list[tuple[str, str, str, str, str, list[str]]] = [
    ("P1", "引用一条不存在的决策编号", USAGE, ANCHOR,
     ANCHOR + "\n\n坏法锚：这条的口径见 D-999。\n", [T_DEC]),
    ("P2", "引用一条不存在的台账编号", USAGE, ANCHOR,
     ANCHOR + "\n\n坏法锚：与 ISSUES I999 同族。\n", [T_ISS]),
    ("P3", "引用一个不存在的节号", USAGE, ANCHOR,
     ANCHOR + "\n\n坏法锚：详见 `docs/USAGE.md` §九十九。\n", [T_SEC]),
    ("P4", "引用一个不存在的测试名", USAGE, ANCHOR,
     ANCHOR + "\n\n坏法锚：由 `test_这条根本不存在啊` 钉住。\n", [T_TEST]),
    ("P5", "台账类文档里的旧测试名不判红（反向对照）", CHANGELOG, LEDGER_ANCHOR,
     LEDGER_ANCHOR + "\n\n坏法锚：当时由 `test_这条根本不存在啊` 钉住。\n", []),
]


def _pyc_files(rel: str) -> list[Path]:
    stem = Path(rel).stem
    return list((REPO / rel).parent.glob(f"__pycache__/{stem}.*.pyc"))


def run_nodes(nodes: list[str]) -> tuple[int, str]:
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen",
               PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
    proc = subprocess.run(
        [PY, "-m", "pytest", *nodes, "-q", "--no-header", "-rf",
         "-p", "no:randomly", "-p", "no:cacheprovider"],
        cwd=str(REPO), env=env, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=600)
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def main() -> int:
    wanted = set(sys.argv[1:])
    selected = [m for m in MUTATIONS if not wanted or m[0] in wanted]

    all_nodes = sorted({n for m in selected for n in m[5]}) or [T_DEC, T_ISS, T_SEC, T_TEST]
    code, out = run_nodes(all_nodes)
    if code != 0:
        print("!! 基线就没绿，先修守卫再谈注入：\n" + out[-4000:])
        return 1
    print(f"基线 {len(all_nodes)} 条全绿\n")

    survivors, misattributed, broken_control, skipped = [], [], [], []
    for mid, desc, rel, anchor, injected, nodes in selected:
        path = REPO / rel
        raw = path.read_bytes()
        anchor_b, new_b = anchor.encode("utf-8"), injected.encode("utf-8")
        if b"\r\n" in raw:
            anchor_b = anchor_b.replace(b"\n", b"\r\n")
            new_b = new_b.replace(b"\n", b"\r\n")
        if raw.count(anchor_b) != 1:
            print(f"{mid:4} SKIP  锚点不唯一（命中 {raw.count(anchor_b)} 次）：{desc}")
            skipped.append(mid)
            continue
        try:
            path.write_bytes(raw.replace(anchor_b, new_b, 1))
            for pyc in _pyc_files(rel):
                pyc.unlink(missing_ok=True)
            code, out = run_nodes(nodes or all_nodes)
        finally:
            path.write_bytes(raw)
            for pyc in _pyc_files(rel):
                pyc.unlink(missing_ok=True)
        failed = [ln.split("::")[-1].split(" ")[0] for ln in out.splitlines()
                  if ln.startswith("FAILED ")]
        if not nodes:      # 反向对照：注入之后必须**仍然全绿**
            if code == 0:
                print(f"{mid:4} 对照成立  {desc}  ← 台账豁免边界在事")
            else:
                print(f"{mid:4} 对照破了（台账豁免没起作用，注入也判红）：{desc}\n" + out[-1500:])
                broken_control.append(mid)
        elif code == 0:
            print(f"{mid:4} 绿!! 坏法没被抓住：{desc}")
            survivors.append(mid)
        elif not failed:
            print(f"{mid:4} 红但不点名（是崩了不是断言）：{desc}\n" + out[-1500:])
            misattributed.append(mid)
        elif len(failed) != len(nodes):
            print(f"{mid:4} 红但多杀了：{desc}  ← {', '.join(failed)}（期望只有 {', '.join(nodes)}）")
            misattributed.append(mid)
        else:
            print(f"{mid:4} 红  {desc}  ← {', '.join(failed)}")

    controls = [m for m in selected if not m[5]]
    hits = [m for m in selected if m[5]]
    caught = len(hits) - len(survivors) - len(misattributed) - len(skipped)
    print(f"\n共 {len(selected)} 条（{len(hits)} 条坏法 + {len(controls)} 条反向对照）："
          f"抓住 {caught}、漏网 {len(survivors)}、点名存疑 {len(misattributed)}、"
          f"对照破 {len(broken_control)}、锚点失配 {len(skipped)}")
    if survivors:
        print("漏网：" + " ".join(survivors))
    if misattributed or broken_control or skipped:
        print("点名存疑/对照破/锚点失配："
              + " ".join(misattributed + broken_control + skipped))
    return 0 if not (survivors or misattributed or broken_control or skipped) else 2


if __name__ == "__main__":
    sys.exit(main())
