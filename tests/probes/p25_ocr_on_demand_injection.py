"""p25 · 轮三十六 甲（**OCR 按需**：顶栏「按当前筛选送识别」+ 情境提示条）的坏法注入证伪。

AGENTS.md 的规矩：「每写完一条断言，先用能骗过它的坏法真注入一次；不会变红的断言直接删」。
本文件覆盖 `tests/integration/test_ocr_on_demand.py` 全部 **9 条断言**，坏法 **10** 条
（D1/D2 盯的是同一条「按钮按的是筛选」—— 一个坏在置灰判据、一个坏在绕开面板）。
预算那三条新坏法（整份装不下就不排 / 两类预算理由并成一类 / 面板不说「跑不到底」）
挂在 p23 的 G4/G5/G6（它们骗的是批量面板那两条断言），两边不重复。

跑法：
    .venv/Scripts/python.exe tests/probes/p25_ocr_on_demand_injection.py              # 全跑
    .venv/Scripts/python.exe tests/probes/p25_ocr_on_demand_injection.py C E          # 只跑指定 id

runner 与基线纪律沿用 p23（也就是 p9 那一套）：**复制式**注入，不碰工作区；先在未注入的
副本上跑一遍基线，基线红则整场结论不作数。判定口径与 **ISSUES I55** 一致：
`rc≠0 且 failed≥1 且 errored==0`，锚点命中不是恰好一次判「注入失效」。

编号用断言自己的字母，不用连续序号（**ISSUES I35**）：
A=待识别只认 pending · B=读数认筛选 · C=截断要说 · D=按钮按的是筛选（两条）·
E=空名单置灰 · F/G/H=提示条三态 · I=提示条整批送。
"""
from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from p9_reverse_injection import Case, Edit, _apply, _copy_repo, _run, _verdicts   # noqa: E402

ONDEMAND = "tests/integration/test_ocr_on_demand.py::"

REPO = "src/pdfarchiver/db/repositories/documents.py"
SVC = "src/pdfarchiver/services/ocr_service.py"
PAGE = "src/pdfarchiver/ui/pages/library_page.py"
HITS = "src/pdfarchiver/ui/library_hits.py"
# 轮四十二拆分（I96 甲第二次）：D1/D2/E/I 四条坏法的落点随代码搬进筛选区 mixin，
# 目标路径跟着搬 —— 锚点文本一字未动，守卫仍钉同一段代码。
FILTER = "src/pdfarchiver/ui/library_filter.py"

CASES: list[Case] = [
    # —— A：待识别的定义（没识别过的扫描件，不是「没有结论的行」）———————————
    Case("A", "待识别只认 `IS NOT NULL`（连没识别过的原生文字版也全表混进来）",
         ONDEMAND + "test_待识别只数没识别过的扫描件",
         [Edit(REPO, "f\"SELECT d.id FROM documents d{w.sql_with('d.ocr_status = ?')}\"",
               "f\"SELECT d.id FROM documents d{w.sql_with('d.ocr_status IS NOT NULL')}\""),
          Edit(REPO, "(*w.params, OCR_PENDING, limit)).fetchall()",
               "(*w.params, limit)).fetchall()"),
          Edit(REPO, "f\" FROM documents d{w.sql_with('d.ocr_status = ?')}\"",
               "f\" FROM documents d{w.sql_with('d.ocr_status IS NOT NULL')}\""),
          Edit(REPO, "(*w.params, OCR_PENDING)).fetchone()",
               "(*w.params,)).fetchone()")]),
    Case("B", "读数套漏筛选：总数与名单都不认 chips（按钮按下去是另一个库的账）",
         ONDEMAND + "test_读数跟着筛选走而不是全库待识别",
         [Edit(REPO, "        w = where_for_filter(filters)\n"
                     "        row = self.engine.thread_connection().execute(",
               "        w = SqlWhere((), ())\n"
                     "        row = self.engine.thread_connection().execute(")]),
    Case("C", "截断不说：`capped` 恒假（名单只到一部分，读数却像全量）",
         ONDEMAND + "test_名单截断时总数与这次最多送多少一起说清",
         [Edit(SVC, "        return len(self.ids) < self.documents", "        return False")]),

    # —— D/E：按钮（按的是筛选不是勾选、先给账再排队、空名单置灰）——————————
    Case("D1", "按钮要求先勾表格（文案说的是「按筛选」，行为却看勾选）",
         ONDEMAND + "test_按钮按的是筛选而不是表格里勾了哪几份",
         [Edit(FILTER, "        self.filter_ocr_btn.setEnabled(bool(pending.ids))",
               "        self.filter_ocr_btn.setEnabled("
               "bool(pending.ids) and bool(self._selected_doc_ids()))")]),
    Case("D2", "不给账直接排队（跳过批次面板，「先给账再排队」的形状被绕开）",
         ONDEMAND + "test_按钮按的是筛选而不是表格里勾了哪几份",
         [Edit(FILTER, "        self.ocr_panel.open_for(list(pending.ids))",
               "        self.ctx.ocr.request_ocr(list(pending.ids))\n"
               "        self.ocr_panel.open_for(list(pending.ids))")]),
    Case("E", "没有待识别也亮着（一颗点下去点不到任何一份的按钮）",
         ONDEMAND + "test_筛选里没有待识别时按钮置灰",
         [Edit(FILTER, "        self.filter_ocr_btn.setEnabled(bool(pending.ids))",
               "        self.filter_ocr_btn.setEnabled(True)")]),

    # —— F/G/H：提示条三态（不命中该出现 / 有命中该收起 / 收起不留空名单）———————
    Case("F", "提示条永不出现（这条横幅整个失效）",
         ONDEMAND + "test_一条都没命中时提示条说清为什么搜不到",
         [Edit(HITS, "        show = bool(empty and pending is not None and pending.ids)",
               "        show = False")]),
    Case("G", "有命中也不收起（不看 `empty`）",
         ONDEMAND + "test_有命中时提示条收起",
         [Edit(HITS, "        show = bool(empty and pending is not None and pending.ids)",
               "        show = bool(pending is not None and pending.ids)")]),
    Case("H", "空名单也挂横幅（不看 `ids`，收起时留个空壳）",
         ONDEMAND + "test_提示条收起时不留空名单",
         [Edit(HITS, "        show = bool(empty and pending is not None and pending.ids)",
               "        show = bool(empty and pending is not None)")]),
    Case("I", "提示条只送第一份（说「这一批」排的却是一份）",
         ONDEMAND + "test_提示条那颗按钮排的是这一批",
         [Edit(FILTER, "        self.ocr_panel.open_for(list(pending.ids))",
               "        self.ocr_panel.open_for(list(pending.ids)[:1])")]),
]


def _label(case: Case) -> str:
    return f"p25 注入 {case.inject}｜{case.坏法}"


def main() -> int:
    wanted = [a for a in sys.argv[1:] if not a.startswith("-")]
    cases = [c for c in CASES if not wanted or c.inject in wanted]
    if not cases:
        print(f"没有这些编号：{wanted}（可选：{[c.inject for c in CASES]}）")
        return 2

    ws = Path(tempfile.mkdtemp(prefix="p25_injection_"))
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
        one = Path(tempfile.mkdtemp(prefix="p25_case_"))
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
