"""坏法注入证伪（AGENTS.md：每写完一条断言，先用"能骗过它的坏法"真注入一次）。

用法：
    .venv/Scripts/python.exe tests/probes/p15_archive_ui_injection.py            # 全跑
    .venv/Scripts/python.exe tests/probes/p15_archive_ui_injection.py C1 A3 ...   # 只跑指定 id

每条坏法做一次"等价但错"的生产代码改动，跑它该杀掉的那几条测试，要求：
1. 必须红；2. 红的必须是**那条**测试（点名），不是随便一条崩了。
跑完立即按原字节还原（`finally` 里做，连 `__pycache__` 一起清），改动只落在工作区、不提交。

两条不是显然的实现细节：
- **锚点按工作区的行尾匹配**。本仓索引里全是 LF，但 `core.autocrlf=true` 且没有
  `.gitattributes`，所以 `git checkout` 出来的文件在 Windows 工作区是 CRLF，而工具新写的文件是
  LF —— 同一批锚点跨两种行尾。多行锚点在命中前统一换成 CRLF（只碰 `\n`，锚点里那个字面
  `\\n` 不受影响），否则实测会有四条报"命中 0 次"而被当成漏网。
- **跑之前先确认工作区干净**。它是直接改生产源码的，中途硬打断（Ctrl-C / 杀进程）会留下
  注入态；正常跑完每条都在 `finally` 还原。
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
PY = str(REPO / ".venv" / "Scripts" / "python.exe")

CONFIRM = "src/pdfarchiver/ui/confirm.py"
ARCHIVE = "src/pdfarchiver/ui/pages/archive_page.py"
OPS = "src/pdfarchiver/ui/pages/operations_page.py"
SERVICE = "src/pdfarchiver/services/archive_service.py"
STATUS = "src/pdfarchiver/ui/pages/status_page.py"

TCC = "tests/integration/test_confirm_control.py::"
TEX = "tests/integration/test_archive_execute_ui.py::"
TDS = "tests/integration/test_archive_disk_safety.py::TestG18Undo::"
TSR = "tests/integration/test_status_readout.py::"

# (id, 说明, 文件, 原文, 坏法, 该被点名的测试 node id)
MUTATIONS: list[tuple[str, str, str, str, str, list[str]]] = [
    # —— 分级确认控件 ——
    ("C1", "确认键一进来就能按", CONFIRM,
     "    box.accept_button.setEnabled(False)", "    box.accept_button.setEnabled(True)",
     [TCC + "test_全可逆那档由复选框放行而确认键一进来是禁用的",
      TCC + "test_含不可逆那档必须逐字输入确认词"]),
    ("C2", "回车等于确认", CONFIRM,
     "    box.accept_button.setAutoDefault(False)", "    box.accept_button.setAutoDefault(True)",
     [TCC + "test_回车不许替人做决定"]),
    ("C3", "确认词改成包含即过", CONFIRM,
     "lambda text: box.accept_button.setEnabled(text.strip() == CONFIRM_WORD))",
     "lambda text: box.accept_button.setEnabled(CONFIRM_WORD in text.strip()))",
     [TCC + "test_含不可逆那档必须逐字输入确认词"]),
    ("C4", "确认词不再容忍首尾空白", CONFIRM,
     "lambda text: box.accept_button.setEnabled(text.strip() == CONFIRM_WORD))",
     "lambda text: box.accept_button.setEnabled(text == CONFIRM_WORD))",
     [TCC + "test_含不可逆那档必须逐字输入确认词"]),
    ("C5", "不可逆那一档永不出现", CONFIRM,
     "    if summary.needs_confirm_word:", "    if False:  # injected",
     [TCC + "test_含不可逆那档必须逐字输入确认词"]),
    ("C6", "同盘/跨盘两个数写反", CONFIRM,
     'f"将{verb} {summary.will_run} 项：同盘 rename {summary.same_disk}"',
     'f"将{verb} {summary.will_run} 项：同盘 rename {summary.cross_disk}"',
     [TCC + "test_影响条数那一行只能由计划里的四个数拼出"]),
    ("C7", "标题不点名这机会动磁盘", CONFIRM,
     'box.setWindowTitle(f"{title} —— 本机会改动磁盘上的文件")', 'box.setWindowTitle(title)',
     [TCC + "test_影响条数那一行只能由计划里的四个数拼出"]),
    ("C8", "复选框默认勾上", CONFIRM,
     '        box.check_toggle = QtWidgets.QCheckBox(f"我确认要{verb}这 {summary.will_run} 项文件")\n'
     '        lay.addWidget(box.check_toggle)',
     '        box.check_toggle = QtWidgets.QCheckBox(f"我确认要{verb}这 {summary.will_run} 项文件")\n'
     '        box.check_toggle.setChecked(True)\n'
     '        lay.addWidget(box.check_toggle)',
     [TCC + "test_全可逆那档由复选框放行而确认键一进来是禁用的"]),
    ("C9", "勾选不放行确认键", CONFIRM,
     "        box.check_toggle.toggled.connect(box.accept_button.setEnabled)",
     "        pass  # injected: 断线",
     [TCC + "test_全可逆那档由复选框放行而确认键一进来是禁用的"]),
    ("C10", "排除原因汇成一句", CONFIRM,
     '        extra = QtWidgets.QLabel(line)', '        extra = QtWidgets.QLabel("；".join(summary.lines))',
     [TCC + "test_排除原因逐条落在确认框里而不是汇成一句"]),
    ("C11", "DangerSummary 的档位判据反了", CONFIRM,
     "        return self.irreversible > 0", "        return self.will_run > 0",
     [TCC + "test_全可逆那档由复选框放行而确认键一进来是禁用的"]),

    # —— S3 执行归档 ——
    ("A1", "执行键不看有没有预览", ARCHIVE,
     "        self.execute_btn.setEnabled(self._preview is not None and self._space_ok)",
     "        self.execute_btn.setEnabled(True)",
     [TEX + "test_没看过计划就不许建批次"]),
    ("A2", "执行键不看空间门禁", ARCHIVE,
     "        self.execute_btn.setEnabled(self._preview is not None and self._space_ok)",
     "        self.execute_btn.setEnabled(self._preview is not None)",
     [TEX + "test_跨盘装不下时执行键是禁用的"]),
    ("A3", "空间读数恒当充足", ARCHIVE,
     "        self._space_ok = self._space_shortfall(moves) == 0", "        self._space_ok = True",
     [TEX + "test_跨盘装不下时执行键是禁用的"]),
    ("A4", "免预览直接执行", ARCHIVE,
     "        if self._preview is None:", "        if False:  # injected",
     [TEX + "test_没看过计划就不许建批次"]),
    ("A5", "提交后不作废旧预览", ARCHIVE,
     "        op = self.ctx.archive.submit(self._selected_doc_ids(), target_root, template)\n"
     "        self._invalidate_preview()",
     "        op = self.ctx.archive.submit(self._selected_doc_ids(), target_root, template)",
     [TEX + "test_预览之后落的是同一份计划加一次后台任务"]),
    ("A6", "执行前不重算比对", ARCHIVE,
     "        if self._signature(moves) != self._preview:", "        if False:  # injected",
     [TEX + "test_旧预览不许授权执行"]),
    ("A7", "签名只认 doc_id 不认路径", ARCHIVE,
     "        return tuple((m.doc_id, m.src_path, m.dst_path, m.kind, m.skip_reason) for m in moves)",
     "        return tuple((m.doc_id,) for m in moves)",
     [TEX + "test_旧预览不许授权执行"]),
    ("A8", "跳过原因界面自己编", ARCHIVE,
     '                mark_text = move.skip_reason or "跳过（计划没给出原因）"',
     '                mark_text = "已跳过"',
     [TEX + "test_旧预览不许授权执行"]),
    ("A9", "目标路径界面自己拼", ARCHIVE,
     '            dst_text = move.dst_path or "—"',
     '            dst_text = "界面拼的/" + (move.dst_path or "—").rsplit("/", 1)[-1]',
     [TEX + "test_预览里的目标路径就是执行后磁盘上的路径"]),
    ("A10", "全跳过也建批次", ARCHIVE,
     '        if counts["run"] == 0:', '        if False:  # injected',
     [TEX + "test_全部跳过时不建批次也不弹确认"]),
    ("A11", "空间不足照样弹确认", ARCHIVE,
     "        shortfall = self._space_shortfall(moves)\n        if shortfall:",
     "        shortfall = self._space_shortfall(moves)\n        if False:  # injected",
     [TEX + "test_跨盘装不下时执行键是禁用的"]),
    ("A12", "取消确认之后照样提交", ARCHIVE,
     '                    lines=tuple(self.plan_summary.text().split("\\n")[1:]))):\n            return',
     '                    lines=tuple(self.plan_summary.text().split("\\n")[1:]))):\n            pass',
     [TEX + "test_取消确认之后库里队列磁盘都不许变"]),
    ("A13", "回执不报批次号与条数", ARCHIVE,
     '            f"已提交 #{op.id}｜共 {op.items_total} 项（其中不进执行 ',
     '            "已提交成功（共 ',
     [TEX + "test_预览之后落的是同一份计划加一次后台任务"]),

    # —— S4 整批撤销 ——
    ("O1", "没选批次也往下算", OPS,
     "        op_id = self._selected_op_id()\n        if op_id is None:",
     "        op_id = self._selected_op_id()\n        if False:  # injected",
     [TEX + "test_没选中批次时撤销只问一句而不建东西"]),
    ("O2", "没有可撤项也弹确认", OPS,
     "        if not plan.moves:", "        if False:  # injected",
     [TEX + "test_没有可撤项时不开一条空批次"]),
    ("O3", "排除原因只报条数", OPS,
     '            lines = (f"排除 {len(lines)} 项，原因逐条：",) + lines',
     '            lines = (f"排除 {len(lines)} 项",)',
     [TEX + "test_排除项的条数与逐条原因都摆在确认框里"]),
    ("O4", "排除项算进将执行条数", OPS,
     "                    will_run=len(plan.moves),",
     "                    will_run=len(plan.moves) + len(plan.excluded),",
     [TEX + "test_排除项的条数与逐条原因都摆在确认框里"]),
    ("O5", "确认框标题不点批次号", OPS,
     '                self, title=f"确认撤销批次 #{op_id}", verb="撤销",',
     '                self, title="确认撤销", verb="撤销",',
     [TEX + "test_撤销确认后另开一条反向批次并排队"]),
    ("O6", "回执不说撤销的是哪一批", OPS,
     '            f"已提交撤销批次 #{op.id}（撤销 #{op_id}）｜共 {op.items_total} 项｜排除 {excluded} 项\\n"',
     '            f"已提交撤销批次 #{op.id}｜共 {op.items_total} 项\\n"',
     [TEX + "test_撤销确认后另开一条反向批次并排队"]),
    ("O7", "拒绝原因被界面重述成一句", OPS,
     '            QtWidgets.QMessageBox.warning(self, "撤销", str(exc))',
     '            QtWidgets.QMessageBox.warning(self, "撤销", "撤销计划算不出来，请刷新后重试")',
     [TEX + "test_撤销撤销批次被拒绝并显示原因"]),
    ("O8", "取消撤销之后照样提交", OPS,
     "                    lines=tuple(x for x in lines if x))):\n            return",
     "                    lines=tuple(x for x in lines if x))):\n            pass",
     [TEX + "test_撤销取消确认之后什么都不建"]),

    # —— 执行器台账与状态页 ——
    ("S1", "部分撤销也标 undone", SERVICE,
     '        if op.kind == "undo" and op.undo_of is not None and status == "done":',
     '        if op.kind == "undo" and op.undo_of is not None:',
     [TDS + "test_部分撤销不许把原批次写成undone"]),
    ("P1", "磁盘口径写两遍", STATUS,
     '        parts += ["", DISK_EFFECT_LINE]', '        parts += ["", DISK_EFFECT_LINE, DISK_EFFECT_LINE]',
     [TSR + "test_状态读数里的缺什么只许来自两个列表"]),
    ("P2", "空说明仍然占一行", ARCHIVE,
     "        self.unwired_label.setVisible(bool(lines))", "        self.unwired_label.setVisible(True)",
     [TSR + "test_S3_的未接线说明只许与来源同生同灭"]),
    ("P3", "未接线句子改成手抄", ARCHIVE,
     '        self.unwired_label.setText(("本轮未接线：" + "；".join(lines)) if lines else "")',
     '        self.unwired_label.setText("本轮未接线：这一栏改了什么都不变" if lines else "")',
     [TSR + "test_S3_的未接线说明只许与来源同生同灭"]),
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

    # 基线：注入前先确认这些断言此刻是绿的
    all_nodes = sorted({n for m in selected for n in m[5]})
    code, out = run_nodes(all_nodes)
    if code != 0:
        print("!! 基线就没绿，先修测试再谈注入：\n" + out[-4000:])
        return 1
    print(f"基线 {len(all_nodes)} 条全绿\n")

    survivors, misattributed = [], []
    for mid, desc, rel, old, new, nodes in selected:
        path = REPO / rel
        raw = path.read_bytes()
        old_b, new_b = old.encode("utf-8"), new.encode("utf-8")
        if b"\r\n" in raw:   # 工作区是 CRLF 时按 CRLF 匹配，锚点里那个反斜杠-n 不受影响
            old_b = old_b.replace(b"\n", b"\r\n")
            new_b = new_b.replace(b"\n", b"\r\n")
        if raw.count(old_b) != 1:
            print(f"{mid:4} SKIP  锚点不唯一（命中 {raw.count(old_b)} 次）：{desc}")
            survivors.append(mid)
            continue
        try:
            path.write_bytes(raw.replace(old_b, new_b, 1))
            for pyc in _pyc_files(rel):
                pyc.unlink(missing_ok=True)
            code, out = run_nodes(nodes)
        finally:
            path.write_bytes(raw)
            for pyc in _pyc_files(rel):
                pyc.unlink(missing_ok=True)
        failed = [ln.split("::")[-1].split(" ")[0] for ln in out.splitlines()
                  if ln.startswith("FAILED ")]
        if code == 0:
            print(f"{mid:4} 绿!! 坏法没被抓住：{desc}")
            survivors.append(mid)
        elif not failed:
            print(f"{mid:4} 红但不点名（是崩了不是断言）：{desc}\n" + out[-1500:])
            misattributed.append(mid)
        else:
            print(f"{mid:4} 红  {desc}  ← {', '.join(failed)}")

    print(f"\n共 {len(selected)} 条坏法：抓住 {len(selected) - len(survivors) - len(misattributed)}、"
          f"漏网 {len(survivors)}、点名存疑 {len(misattributed)}")
    if survivors:
        print("漏网：" + " ".join(survivors))
    if misattributed:
        print("点名存疑：" + " ".join(misattributed))
    return 0 if not survivors else 2


if __name__ == "__main__":
    sys.exit(main())
