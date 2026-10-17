"""最终交付门禁：把全部阶段的闸门、一致性核查、长跑采样与打包冒烟串成可分段的链。

跑法（**这条链总时长超过一个终端命令的舒适区，所以按段跑**）：

    python gates/final.py                       # 默认段：guards + regression + coldstart + e2e + consistency
    python gates/final.py --list                # 打印每段是什么、实测耗时、该不该并进默认
    python gates/final.py --only package        # 只跑打包段（build.py + 冻结冒烟）
    python gates/final.py --only injection      # 只跑两条反向注入（p9 + p10，约 5 分钟）
    python gates/final.py --only soak --soak-minutes 4
    python gates/final.py --all --data-root "<要核查的数据根>"

红线与阶段 1/2/5 的门禁完全一致：任何一条 RED 就打印 `VERDICT: RED（n 条）` 并非 0 退出，
末行永远是 `VERDICT: …`，脚本化调用只认这一行。

三条设计约束：

1. **不新增判定口径。** 这一段只做"编排 + 汇总"，每条判据仍然是它自己那份门禁/探针里的断言。
   这里出现的所有性能数字都是**当次实测**打印，不写死（阶段 5 定下的规矩）。
2. **跳过必须说出来并留痕。** 任何被 `--only` 跳过的段，输出里显式标"本次未跑"，
   不许让"这一场全绿"被读成"整个项目全绿"。`--all` 才是全链。
3. **交付文档在场性是一条可断言的硬条件**（`gate_docs`）：交付报告必须五分栏齐、
   四份用户文档必须存在且含当次实测引用、禁止占位符残留。这条的坏法注入见 `--inject-docs`。
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from stage1 import REPO, Row, _last_line, _run  # noqa: E402
from stage5 import _machine_load  # noqa: E402 复用同一份负载读数口径，不写第二份

P12 = "tests/probes/p12_consistency.py"
P13 = "tests/probes/p13_soak.py"
P14 = "tests/probes/p14_fts_instrument.py"
BUILD = "packaging/build.py"
SMOKE = "packaging/frozen_smoke.py"

USER_DOCS = ["docs/INSTALL.md", "docs/USAGE.md", "docs/BACKUP-RESTORE.md", "docs/TROUBLESHOOTING.md"]
REPORT_GLOB = "docs/stage-reports/最终交付报告.md"
# 五分栏是交付需求原文定的口径，缺任何一栏就等于报告没按需求写
FIVE_COLUMNS = ["已实现且已通过测试", "已实现但尚未充分验证", "部分实现", "尚未实现", "已知问题及其影响"]
PLACEHOLDER_RE = re.compile(r"TBD|TODO|待填|<<[^>]*>>|此处省略")

LEDGER_ROW_RE = re.compile(r"^\| ISSUES I(\d+)\b")
LEDGER_STATUS_RE = re.compile(r"\*\*(OPEN|MITIGATED|CLOSED|WONTFIX)\*\*")


def ledger_check(text: str) -> tuple[list[str], list[str]]:
    """台账自身的三条口径：每行**有且只有一个**合法状态、编号从 I1 连续、不重号。
    返回 (缺陷列表, 读数列表)。

    为什么要在门禁里数，而不是只在文档里写一句"收尾逐条销账"：2026-10-16 收尾时发现
    `docs/stage-reports/最终交付报告.md` §六 那条"现数命令"的正则**已经过期成打空**了 ——
    **ISSUES I35** 的命名空间改写把行首从 `| I<n> |` 变成了 `| ISSUES I<n> |`，命令没跟着改，
    跑出来是 `0 Counter({})`，看着像台账空了。**静默失效的判定等于没有判定**，所以这条进了链。
    """
    defects: list[str] = []
    nums: list[int] = []
    seen: set[int] = set()
    tally: dict[str, int] = {}
    for line in text.splitlines():
        m = LEDGER_ROW_RE.match(line)
        if not m:
            continue
        n = int(m.group(1))
        nums.append(n)
        if n in seen:
            defects.append(f"I{n} 重号")
        seen.add(n)
        states = LEDGER_STATUS_RE.findall(line)
        if len(states) != 1:
            defects.append(f"I{n} 的状态字段有 {len(states)} 个（要正好 1 个，"
                           f"且只能是 OPEN/MITIGATED/CLOSED/WONTFIX 加粗之一）")
        else:
            tally[states[0]] = tally.get(states[0], 0) + 1
    gaps = [n for n in range(1, max(nums) + 1) if n not in seen] if nums else ["空台账"]
    if gaps:
        defects.append(f"编号断档：{gaps}")
    reading = [f"{len(nums)} 行｜I1–I{max(nums) if nums else 0} 连续",
               "｜".join(f"{k} {v}" for k, v in sorted(tally.items()))]
    return defects, reading


def _gate(name: str, cmd: list[str], *, hint: str = "") -> Row:
    """把一个"探针/脚本自己判生死"的东西接进门禁：退出码 0 且末行 ALL GREEN 才算过。"""
    p = _run(cmd)
    text = (p.stdout or "") + (p.stderr or "")
    green = p.returncode == 0 and "VERDICT: ALL GREEN" in text
    return Row(name, green, _last_line(p), hint or text[-900:])


def gate_docs() -> list[Row]:
    """交付文档的在场性与诚实性：存在的文件名不算过，内容结构才算。"""
    rows: list[Row] = []
    missing = [d for d in USER_DOCS if not (REPO / d).is_file()]
    sizes = {d: (REPO / d).stat().st_size for d in USER_DOCS if (REPO / d).is_file()}
    rows.append(Row("交付文档四份在场（安装 / 使用 / 备份恢复 / 故障排查）",
                    not missing,
                    "｜".join(f"{Path(d).name} {round(s / 1024)}KiB" for d, s in sizes.items())
                    + (f" ── 缺 {missing}" if missing else ""),
                    ""))

    report = REPO / REPORT_GLOB
    if not report.is_file():
        rows.append(Row("最终交付报告五分栏齐全", False, f"报告不存在：{REPORT_GLOB}", ""))
    else:
        text = report.read_text(encoding="utf-8", errors="replace")
        absent = [c for c in FIVE_COLUMNS if c not in text]
        rows.append(Row("最终交付报告五分栏齐全", not absent,
                        f"报告 {round(report.stat().st_size / 1024)}KiB｜缺栏 {absent or '无'}"))

    placeholders = {}
    for d in USER_DOCS + [REPORT_GLOB]:
        f = REPO / d
        if not f.is_file():
            continue
        hits = PLACEHOLDER_RE.findall(f.read_text(encoding="utf-8", errors="replace"))
        if hits:
            placeholders[Path(d).name] = len(hits)
    rows.append(Row("交付文档里没有占位符残留（TBD / TODO / 待填 / 省略）", not placeholders,
                    f"命中 {placeholders or '无'}"))

    no_evidence = [Path(d).name for d in USER_DOCS
                   if (REPO / d).is_file() and "实测" not in (REPO / d).read_text(encoding="utf-8", errors="replace")]
    rows.append(Row("每份用户文档都引用了当次实测读数", not no_evidence,
                    f"没有「实测」字样的 {no_evidence or '无'}"))

    ledger = REPO / "docs/ISSUES.md"
    defects, summary = ledger_check(ledger.read_text(encoding="utf-8", errors="replace")) \
        if ledger.is_file() else (["台账文件不存在"], [])
    rows.append(Row("已知问题台账逐条有状态、编号连续不重号", not defects,
                    "｜".join(summary) + (f" ── {defects}" if defects else "")))

    stale, cap = _ledger_stale_pointers()
    rows.append(Row(f"台账里失效的测试名不超过 {cap} 处（**ISSUES I70** 丙）", stale <= cap,
                    f"现数 {stale} 处，上限 {cap}",
                    "涨了就说明这一轮留下了新的过期名字：就地追注继任者，别抬上限"))
    return rows


def _ledger_stale_pointers() -> tuple[int, int]:
    """台账旧名条数与上限。口径直接取守卫那份函数与那个常量，不在门禁里再数一遍
    （本文件设计约束 1：门禁只做编排，不新增判定口径）。"""
    sys.path.insert(0, str(REPO / "tests" / "guards"))
    from test_doc_pointers import LEDGER_STALE_CAP, ledger_stale_test_names  # noqa: E402
    return len(ledger_stale_test_names()), LEDGER_STALE_CAP


def gate_docs_injection() -> Row:
    """上面那六条里三条能注入的坏法：临时造一份残缺报告、一份占位符文档与一份坏台账，要求被抓到。
    台账旧名那条的坏法注入不在这里，见 `tests/probes/p16_doc_pointers_injection.py` 的 P6。"""
    import tempfile

    with tempfile.TemporaryDirectory(prefix="final_docs_") as td:
        root = Path(td)
        (root / "docs" / "stage-reports").mkdir(parents=True)
        (root / "docs" / "stage-reports" / "最终交付报告.md").write_text(
            "# 报告\n\n已实现且已通过测试：全部\n\n<!-- 缺三栏 -->\n", encoding="utf-8")
        (root / "docs" / "USAGE.md").write_text("# 使用\n\n性能：TBD\n", encoding="utf-8")
        bad = []
        text = (root / "docs" / "stage-reports" / "最终交付报告.md").read_text(encoding="utf-8")
        absent = [c for c in FIVE_COLUMNS if c not in text]
        if len(absent) != 4:
            bad.append(f"五分栏缺失只抓到 {len(absent)} 项（应 4 项）")
        if not PLACEHOLDER_RE.search((root / "docs" / "USAGE.md").read_text(encoding="utf-8")):
            bad.append("占位符 TBD 没被抓到")
        if "实测" in (root / "docs" / "USAGE.md").read_text(encoding="utf-8"):
            bad.append("好读数误判（不该算坏法）")
        # 台账坏法两条：编号断档（缺 I2）+ 某行状态字段不是那四个词之一
        ledger_bad, _ = ledger_check("| ISSUES I1 | a | **OPEN** | b |\n"
                                     "| ISSUES I3 | c | **FIXED someday** | d |\n")
        if len(ledger_bad) != 2:
            bad.append(f"台账坏行只抓到 {len(ledger_bad)} 项（应 2 项：编号断档 + 状态字段非法）")
        ledger_good, _ = ledger_check("| ISSUES I1 | a | **OPEN** | b |\n"
                                      "| ISSUES I2 | c | **WONTFIX** | d |\n")
        if ledger_good:
            bad.append(f"好台账被误判：{ledger_good}")
    return Row("交付文档门禁自己有没有牙（坏法注入实测）", not bad,
               "残缺报告 + TBD 文档 + 坏台账：抓到 "
               + ("、".join(bad) if bad else "三条坏法全红、好台账不误判"))


def segment_guards() -> list[Row]:
    from stage1 import gate_architecture, gate_dependency  # noqa: PLC0415
    return [gate_dependency(), gate_architecture()] + gate_docs()


def segment_regression() -> list[Row]:
    from stage1 import gate_regression  # noqa: PLC0415
    return [gate_regression()]


def segment_coldstart() -> list[Row]:
    from stage1 import gate_cold_start  # noqa: PLC0415
    return [gate_cold_start()]


def segment_e2e() -> list[Row]:
    from stage2 import gate_background_lifecycle, gate_e2e_acceptance  # noqa: PLC0415
    return [gate_background_lifecycle(), gate_e2e_acceptance()]


def segment_injection() -> list[Row]:
    from stage1 import gate_injection  # noqa: PLC0415
    from stage5 import gate_ocr_injection  # noqa: PLC0415
    return [gate_injection(), gate_ocr_injection()]


def segment_ocr() -> list[Row]:
    from stage5 import gate_budget_stop, gate_real_engine_suite, gate_shipped_measurement  # noqa: PLC0415
    return [gate_shipped_measurement(), gate_budget_stop(), gate_real_engine_suite()]


def segment_consistency(data_root: str | None) -> list[Row]:
    rows = [_gate("一致性探针 p12 反向注入自检（17 条坏法）",
                  [sys.executable, P12, "--inject"], hint=""),
            # G10 的判据本身也要被验一次：p14 把四种坏法各造一遍，看哪几种口径能看见（I8 的出处）
            _gate("FTS 一致性仪表有没有牙 p14（四种坏法 × 五种口径实测）",
                  [sys.executable, P14], hint="")]
    if data_root:
        rows.append(_gate(f"一致性核查 p12 对指定数据根（{data_root}）",
                          [sys.executable, P12, "--data-root", data_root]))
    else:
        rows.append(Row("一致性核查 p12 对真实数据根", False,
                        "本次未跑：没给 --data-root。默认数据根 %LOCALAPPDATA%\\PdfArchiver 在本机不存在，"
                        "**这行是 RED，不许把它读成「真实现场已核查」；要变绿必须给 --data-root**"))
    return rows


def segment_soak(minutes: float) -> list[Row]:
    return [_gate("长跑探针 p13 反向注入自检（判据有没有牙）", [sys.executable, P13, "--inject"]),
            _gate(f"长跑采样 p13 真跑 {minutes} 分钟（资源 / 日志 / 积压 / 退出码）",
                  [sys.executable, P13, "--minutes", str(minutes)])]


def segment_package() -> list[Row]:
    return [_gate("打包构建门禁（内容断言：迁移 .py / OCR 模型 / DLL / .dist-info）",
                  [sys.executable, BUILD]),
            _gate("冻结产物冒烟（首启 / 扫描 / 检索 / OCR / 重启 / 被杀恢复 / 无本机路径）",
                  [sys.executable, SMOKE])]


G2_BENCH = "scripts/g2_search_benchmark.py"


def segment_g2() -> list[Row]:
    """G2 搜索 P95 真库实测（默认不进全链，需 --only g2 显式跑）。"""
    return [_gate("G2 搜索 P95 真库实测（20 查询 × 5 reps，P95 ≤ 500ms）",
                  [sys.executable, G2_BENCH])]


SEGMENTS: dict[str, tuple[str, list[str]]] = {
    "guards": ("依赖守卫 + 架构守卫 + 交付文档在场性", ["~15s"]),
    "regression": ("全量回归（pytest tests/，条数只认当次输出，不写死）", ["~50s"]),
    "coldstart": ("G1 冷启动 + 关窗对账", ["~5s"]),
    "e2e": ("新 · 后台生命周期 + 阶段 2 端到端（真 PDF / 真 worker / 真监听）", ["~40s"]),
    "injection": ("p9 + p10 反向注入（断言到底有没有约束力）", ["~296s"]),
    "ocr": ("阶段 5 三条：产品路径实测 / 预算真停机 / 真引擎套件不许 skip", ["~200s"]),
    "consistency": ("p12 注入自检 + p14 一致性仪表验牙 + （给了 --data-root 就）核查真实现场", ["~15s"]),
    "soak": ("p13 注入自检 + 真长跑采样", ["~330s @4 分钟"]),
    "package": ("build.py 内容断言 + 冻结产物冒烟全阶段", ["~262s"]),
    "g2": ("G2 搜索 P95 真库实测（绑定真库，默认不进全链）", ["~30s"]),
}
DEFAULT_ORDER = ["guards", "regression", "coldstart", "e2e", "consistency"]


def build(name: str, args: argparse.Namespace) -> list[Row]:
    if name == "guards":
        return segment_guards()
    if name == "regression":
        return segment_regression()
    if name == "coldstart":
        return segment_coldstart()
    if name == "e2e":
        return segment_e2e()
    if name == "injection":
        return segment_injection()
    if name == "ocr":
        return segment_ocr()
    if name == "consistency":
        return segment_consistency(args.data_root)
    if name == "soak":
        return segment_soak(args.soak_minutes)
    if name == "package":
        return segment_package()
    if name == "g2":
        return segment_g2()
    if name == "docs-inject":
        return [gate_docs_injection()]
    raise SystemExit(f"未知段 {name}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="gates/final.py", description="最终交付门禁（分段链）")
    ap.add_argument("--only", action="append", default=None, choices=list(SEGMENTS) + ["docs-inject"],
                    help="只跑指定段，可重复")
    ap.add_argument("--all", action="store_true", help="全链（约 15–20 分钟，超过多数 CI 单命令上限）")
    ap.add_argument("--data-root", default=None, help="要核查一致性并写进交付报告的数据根")
    ap.add_argument("--soak-minutes", type=float, default=4.0, help="长跑采样时长（默认 4 分钟）")
    ap.add_argument("--list", action="store_true", help="列出每段是什么与耗时量级")
    args = ap.parse_args(argv)

    if args.list:
        print(f"共 {len(SEGMENTS)} 段｜默认跑 {' + '.join(DEFAULT_ORDER)}")
        for name, (what, cost) in SEGMENTS.items():
            print(f"  {name:<12} {cost[0]:>16}  {what}")
        print("  docs-inject     ~1s  交付文档门禁自己的坏法注入")
        return 0

    order = list(SEGMENTS) if args.all else (args.only or DEFAULT_ORDER)
    if args.all:
        order = ["docs-inject"] + order
    skipped = [s for s in SEGMENTS if s not in order]

    print(f"门禁运行于 {REPO}｜python {sys.version.split()[0]}")
    print(f"        {_machine_load()}")
    print(f"        本次跑 {len(order)} 段：{' + '.join(order)}")

    checks: list[Row] = []
    for name in order:
        t0 = time.perf_counter()
        rows = build(name, args)
        took = time.perf_counter() - t0
        print(f"  ── 段 {name}（{took:.1f}s）")
        for row in rows:
            print(f"  {'PASS' if row.ok else 'RED '}  {row.gate}")
            print(f"        实测：{row.measured}")
            if row.note:
                print(f"        现场：{row.note[:700]}")
        checks += rows

    for s in skipped:
        print(f"  SKIP  未跑的段：{s}（{SEGMENTS[s][0]}）—— 这一场的「全绿」不覆盖它")
    bad = [r for r in checks if not r.ok]
    print(f"  合计判定 {len(checks)} 条｜本次未跑 {len(skipped)} 段")
    print("VERDICT: " + ("ALL GREEN" if not bad else f"RED（{len(bad)} 条未过）"))
    return 0 if not bad else 1


if __name__ == "__main__":
    raise SystemExit(main())
