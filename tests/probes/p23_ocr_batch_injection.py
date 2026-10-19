"""p23 · 轮十四 E（**ISSUES I67** 乙 · 批量点名面板）的坏法注入证伪。

AGENTS.md 的规矩：「每写完一条断言，先用能骗过它的坏法真注入一次；不会变红的断言直接删」。
本文件覆盖 **21 条断言**（`tests/integration/test_ocr_batch_panel_ui.py` 16 条 +
`tests/unit/test_ocr_plan_reads.py` 5 条），一条不落，坏法 **23** 条 —— 其中两条断言
（「两类跳过理由各占一行而展开指得到具体份名」「账算不出来时不展开假面板而屏上给的是后端原文」）
各自盯着屏幕上两件事，所以各配两个坏法。

跑法：
    .venv/Scripts/python.exe tests/probes/p23_ocr_batch_injection.py              # 全跑
    .venv/Scripts/python.exe tests/probes/p23_ocr_batch_injection.py B1 R1 U3     # 只跑指定 id

runner 与基线纪律沿用 p22（也就是 p9 那一套）：**复制式**注入，不碰工作区；先在未注入的
副本上跑一遍基线，基线红则整场结论不作数。判定口径与 **ISSUES I55** 一致：
`rc≠0 且 failed≥1 且 errored==0`，锚点命中不是恰好一次判「注入失效」。

编号用断言自己的字母，不用连续序号（会与 ISSUES 的 `I<n>` 撞名 —— **ISSUES I35** 清过那类歧义）：
U=读数形状（unit）· B=接线与份数 · P=面板三句逐字 · C=代价 · R=跳过理由 · G=预算闸门 ·
N=过期名单 · X=取消 · F=失败原文 · K=去重与新增条数 · W=地板宽度。
"""
from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from p9_reverse_injection import Case, Edit, _apply, _copy_repo, _run, _verdicts   # noqa: E402

CRIT = "tests/integration/test_ocr_batch_panel_ui.py::"
UNIT = "tests/unit/test_ocr_plan_reads.py::"

PANEL = "src/pdfarchiver/ui/ocr_batch_panel.py"
PAGE = "src/pdfarchiver/ui/pages/library_page.py"
SVC = "src/pdfarchiver/services/ocr_service.py"

CASES: list[Case] = [
    # —— U：读数形状（面板那三句话的源头，界面只是投影）————————————————
    Case("U1", "「不跑几份」按**类**数而不是按**份**数（两类三份只报两份）",
         UNIT + "test_点名的份数拆成该跑与不跑而两者相加就是点名",
         [Edit(SVC, "        return self.named - len(self.queueable)",
               "        return len(self.skipped)   # 注入：数类不数份")]),
    Case("U2", "理由那一行不报这一类的份数（判定②只剩半句）",
         UNIT + "test_每一类理由那一行报的是后端措辞加这一类的份数",
         [Edit(SVC, "        return f\"{SKIP_LABELS[self.reason]}（{len(self.docs)} 份）\"",
               "        return SKIP_LABELS[self.reason]")]),
    Case("U3", "展开清单不设上限，几百个文件名一起上屏",
         UNIT + "test_展开清单只列到上限而剩下的说得出还有几份",
         [Edit(SVC, "        shown = \"、\".join(doc.name for doc in self.docs[:limit])",
               "        shown = \"、\".join(doc.name for doc in self.docs)")]),
    Case("U4", "代价只报最快那一端（区间被说成一个承诺）",
         UNIT + "test_代价那句给的是主记录页数与实测区间两端",
         [Edit(SVC, "                f\"（按主记录页数算，待推理的页可能更少）｜单页实测 {lo:,}–{hi:,}ms｜\"",
               "                f\"（按主记录页数算，待推理的页可能更少）｜单页实测约 {lo:,}ms｜\"")]),
    Case("U5", "预算比较写成 `>=`（正好够被说成不够，差一错）",
         UNIT + "test_预算那三档说的是此刻够不够跑完这一批",
         [Edit(SVC, "        if self.pages_queueable > self.budget_remaining:",
               "        if self.pages_queueable >= self.budget_remaining:")]),

    # —— B：接线（几份才弹面板、按钮上写的份数就是点名的份数）———————————
    Case("B1", "分档判据永不为真，选中两份也走单份那条直接排队",
         CRIT + "test_选中两份按下去展开面板而一条也不排",
         [Edit(PAGE, "        if len(named) > 1:", "        if len(named) > 99:")]),
    Case("B2", "一份也弹面板（甲案那条老路被乙案吃掉，多一次点击才能干活）",
         CRIT + "test_只点名一份时不弹面板而是直接排队",
         [Edit(PAGE, "        if len(named) > 1:", "        if len(named) >= 1:")]),
    Case("B3", "按钮文案不带份数（按下去之前不知道自己点了几份）",
         CRIT + "test_按钮文案上写的就是点名的份数",
         [Edit(PAGE, "        self.ocr_btn.setText(OCR_BTN_TEXT if named < 2 else "
                     "f\"{OCR_BTN_TEXT}（选中 {named} 份）\")",
               "        self.ocr_btn.setText(OCR_BTN_TEXT)")]),

    # —— P：屏幕上那三句逐字来自服务层 · C：代价 · R：判定② ——————————————
    Case("P1", "那句总结改由界面自己拼（第二个口径，迟早与真排队漂开）",
         CRIT + "test_面板那三句逐字是服务层算出来的账",
         [Edit(PANEL, "        self.summary_label.setText(plan.describe())",
               "        self.summary_label.setText(f\"点名 {plan.named} 份\")")]),
    Case("P2", "执行那一步偷偷加 `force=True`（预览一套、执行另一套）",
         CRIT + "test_面板说的该跑份数与按下排队后的新增条数是同一个数",
         [Edit(PANEL, "            request = self.ctx.ocr.request_ocr(ids)",
               "            request = self.ctx.ocr.request_ocr(ids, force=True)")]),
    Case("C1", "代价那一行留空（屏幕看着有三行，其实少一行）",
         CRIT + "test_代价那句上屏的是这一批的主记录页数",
         [Edit(PANEL, "        self.cost_label.setText(plan.cost_line())",
               "        self.cost_label.setText(\"\")")]),
    Case("R1", "跳过理由的行永远不摆（判定②整条落空）",
         CRIT + "test_两类跳过理由各占一行而展开指得到具体份名",
         [Edit(PANEL, "        for item in plan.skipped:\n"
                      "            self.reason_lay.addWidget(ReasonRow(item))",
               "        for item in ():   # 注入：不摆理由行\n"
               "            self.reason_lay.addWidget(ReasonRow(item))")]),
    Case("R2", "「收起」是颗假按钮，展开之后那一行常驻占屏",
         CRIT + "test_两类跳过理由各占一行而展开指得到具体份名",
         [Edit(PANEL, "        self.detail_label.setVisible(on)",
               "        self.detail_label.setVisible(True)")]),

    # —— G：预算闸门（判定③）与它在屏幕上的形状 ————————————————
    Case("G1", "预算闸门不返回，跑满照样往下分（能绕开的限额等于没有限额）",
         CRIT + "test_预算跑满时面板先说明天恢复而按下排队原样回预算那句",
         [Edit(SVC, "            return [], {SKIP_BUDGET: list(ids)}",
               "            pass   # 注入：闸门不挡，继续逐份判")]),
    Case("G2", "预算那句只报读数不报够不够（不够跑完时屏幕上没有一句话）",
         CRIT + "test_预算不够跑完这一批时那句在面板上看得见",
         [Edit(PANEL, "        self.budget_label.setText("
                      "f\"{self.ctx.ocr.budget.describe()}｜{plan.budget_note()}\")",
               "        self.budget_label.setText(self.ctx.ocr.budget.describe())")]),
    Case("G3", "闸门那一类只报第一份（被挡住的是哪几份，屏幕上看不全）",
         CRIT + "test_预算跑满时这一类理由也指得到是哪几份",
         [Edit(SVC, "            return [], {SKIP_BUDGET: list(ids)}",
               "            return [], {SKIP_BUDGET: ids[:1]}")]),

    # —— N / X / F / K / W：面板的生命周期与两条纪律 ——————————————
    Case("N1", "换选中不收起面板（对着过期名单按「排队」）",
         CRIT + "test_换选中时面板收起不留过期名单",
         [Edit(PAGE, "        self.ocr_panel.close_panel()", "        pass   # 注入：不收旧账")]),
    Case("X1", "「取消」是颗死按钮",
         CRIT + "test_取消之后面板收起而一条也没排",
         [Edit(PANEL, "        self.cancel_btn.clicked.connect(self.close_panel)",
               "        self.cancel_btn.clicked.connect(lambda: None)")]),
    Case("F1", "算账失败时屏幕上只剩一句套话（后端原文被吞，**I84** ③）",
         CRIT + "test_账算不出来时不展开假面板而屏上给的是后端原文",
         [Edit(PANEL, "            self._set_status(f\"识别点名算不了这份账：{exc}\", danger=True)",
               "            self._set_status(\"识别点名算不了这份账\", danger=True)")]),
    Case("F2", "算不出账也展开面板（一块写着「点名 0 份」的空面板）",
         CRIT + "test_账算不出来时不展开假面板而屏上给的是后端原文",
         [Edit(PANEL, "            self.close_panel()\n            return False",
               "            self.setVisible(True)\n            return False")]),
    Case("F3", "排队那一下失败什么都不说（静默 = 用户以为按了没反应）",
         CRIT + "test_排队那一下抛异常时屏上留原文而面板不收起",
         [Edit(PANEL, "            self._set_status(f\"识别排队失败：{exc}\", danger=True)\n"
                      "            return",
               "            return   # 注入：失败不上屏")]),
    Case("K1", "把「该跑」当「新增」报（去重明明发生了，屏幕上说排了 2 条）",
         CRIT + "test_重复排队同一批时新增0条而屏幕上看得见0条",
         [Edit(SVC, "        enqueued = self.jobs.enqueue_many(\"ocr\", queueable)",
               "        enqueued = len(queueable)   # 注入：谎报新增条数")]),
    Case("W1", "面板那三行不折行（整句宽把页面顶过 D-039 的 1024 地板，侧栏被榨瘪）",
         CRIT + "test_面板展开时页面与窗口都不许顶过地板宽度",
         [Edit(PANEL, "        label.setWordWrap(True)", "        label.setWordWrap(False)")]),
]


def _label(case: Case) -> str:
    return f"p23 注入 {case.inject}｜{case.坏法}"


def main() -> int:
    wanted = [a for a in sys.argv[1:] if not a.startswith("-")]
    cases = [c for c in CASES if not wanted or c.inject in wanted]
    if not cases:
        print(f"没有这些编号：{wanted}（可选：{[c.inject for c in CASES]}）")
        return 2

    ws = Path(tempfile.mkdtemp(prefix="p23_injection_"))
    try:
        _copy_repo(ws)
        targets = sorted({t for c in cases for t in c.node.split()})
        rc, out = _run(ws, targets)
        failed, errored, passed = _verdicts(out)
        print(f"基线（未注入）：{passed} 条通过 / {failed} 失败 / {errored} 错误，exit={rc}")
        if rc != 0:
            print(out[-3000:])
            print("VERDICT: RED（基线就没过，后面的注入结论全部不作数）")
            return 1
    finally:
        shutil.rmtree(ws, ignore_errors=True)

    results: list[tuple[Case, bool, str]] = []
    for case in cases:
        one = Path(tempfile.mkdtemp(prefix="p23_case_"))
        try:
            _copy_repo(one)
            _apply(one, case)
            rc, out = _run(one, case.node.split())
            failed, errored, passed = _verdicts(out)
            caught = rc != 0 and failed >= 1 and errored == 0
            detail = (f"failed={failed} error={errored} passed={passed}" if caught
                      else out.splitlines()[-3] if out.strip() else "没有输出")
            results.append((case, caught, detail))
            print(f"  {'RED  ' if caught else 'GREEN'}  {_label(case)}")
            print(f"         -> {case.node.split('::')[-1]}｜{detail}")
        except RuntimeError as exc:                     # 锚点命中次数不对 = 注入失效
            results.append((case, False, str(exc)))
            print(f"  失效    {_label(case)}\n         -> {exc}")
        finally:
            shutil.rmtree(one, ignore_errors=True)

    missed = [r for r in results if not r[1]]
    print(f"\n抓到 {len(results) - len(missed)}/{len(results)} 条坏法")
    for case, _, detail in missed:
        print(f"  未抓到：{_label(case)} —— {detail}\n"
              f"         对应断言是摆设，按 AGENTS.md 必须删或重写")
    print("VERDICT: " + ("ALL GREEN" if not missed else "RED"))
    return 0 if not missed else 1


if __name__ == "__main__":
    raise SystemExit(main())
