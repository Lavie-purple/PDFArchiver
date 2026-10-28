"""最终交付门禁：把全部阶段的闸门、一致性核查、长跑采样与打包冒烟串成可分段的链。

跑法（2026-10-21 实测单命令跑完 12 段 4,023.1s，后台命令时限给到 ≥4,200s 即可；分段跑仍可用）：

    python gates/final.py                       # 默认段：guards + regression + coldstart + e2e + consistency
    python gates/final.py --list                # 打印每段是什么、实测耗时、该不该并进默认
    python gates/final.py --only package        # 只跑打包段（build.py + 冻结冒烟）
    python gates/final.py --only injection      # 只跑常驻的坏法注入（p9 + p10 + p16 + p17 + p18 + p21 + p22 + p23 + p24 + p25）
    python gates/final.py --only ui-inject      # 只跑 p15 那 36 条界面与磁盘链路坏法（2026-10-21 整链 61.2s）
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
from stage1 import (GATE_TIMEOUT_SECONDS, REPO, Row, _last_line, _run,  # noqa: E402
                    harden_stdio)
from stage5 import _machine_load  # noqa: E402 复用同一份负载读数口径，不写第二份

P12 = "tests/probes/p12_consistency.py"
P13 = "tests/probes/p13_soak.py"
P14 = "tests/probes/p14_fts_instrument.py"
P15 = "tests/probes/p15_archive_ui_injection.py"
P16 = "tests/probes/p16_doc_pointers_injection.py"
P17 = "tests/probes/p17_handler_shape_injection.py"
P18 = "tests/probes/p18_irreversible_source_injection.py"
P21 = "tests/probes/p21_saved_search_injection.py"
P22 = "tests/probes/p22_category_export_injection.py"
P23 = "tests/probes/p23_ocr_batch_injection.py"
P24 = "tests/probes/p24_tag_merge_injection.py"
P25 = "tests/probes/p25_ocr_on_demand_injection.py"
BUILD = "packaging/build.py"
SMOKE = "packaging/frozen_smoke.py"
#: 真根 p12 的完整 19 条落在这里。链里每行现场只留最后 900 字（`row.note[:900]`），
#: 2026-10-21 那场唯一的红行就被截掉了 —— 读的人只看见「RED（1 条未过）」却不知道红在哪。
#: 有了这份 JSON，红行永远可回查；路径写在每行的「实测」里，不会被截断。
P12_REAL_OUT = REPO / ".probe_work" / "p12_real_root.json"

#: 注入段的「进行中」标记。探针都是先改源码/文档、跑一次、再在 `finally` 里还原；
#: 被强杀（TaskStop / 超时杀子进程）时 `finally` 不会跑，坏法就留在工作区。
#: 2026-10-21 实测：p17 的 H3 残留（只核对 archive）让 job_queue 的正常断言变成
#: `DID NOT RAISE`，下一场全量回归把注入残留读成了产品缺陷。标记在起跑前检查，
#: 在场就拒绝起跑 —— 宁可让人去还原，也不许再产出这种假红。
INJECTION_INFLIGHT = REPO / ".probe_work" / "injection_inflight"

#: 带 `--data-root` 的一致性核查单独那一档超时。**按实测反算，不是拍的**：
#: 2026-10-18 真根（10,977 份 / 202 万页语料）p12 一场跑了 **3,661.7s**
#: （`.probe_work/serial_run_status.json`）—— 那时 `backups/` 里只有 KB 级快照。
#: 2026-10-20 真库升 v8 后多了 12GB 的 0008 快照，当时 C11 对**每份**快照跑
#: `_health()`，三份 12GB 级库（主库 + 0007 + 0008）各一次 `integrity_check`，
#: 同一场 p12 实测 **8,730s**（12:26:08→14:51:38，`.probe_work/p12_i97_after.log`）。
#: 此后按 **ISSUES I98 乙** 把 C11 改成「整库体检只跑最新一份快照，其余只开库读版本」，
#: 真根的成本上限压成 2 次 12GB 体检（主库 C1 + 最新快照 C11）；17,460s 仍按那场
#: 8,730s 的 **2×** 保留，作为迁移 0009 之前的保守天花板 —— 0009 再加一份 12GB 快照时
#: 先复测，再按同一规则重算（C11 的线性增长已被 I98 乙切断，剩下的是主库体量在涨）。
REAL_ROOT_TIMEOUT = 17460.0

USER_DOCS = ["docs/INSTALL.md", "docs/USAGE.md", "docs/BACKUP-RESTORE.md", "docs/TROUBLESHOOTING.md"]
REPORT_GLOB = "docs/stage-reports/最终交付报告.md"
# 五分栏是交付需求原文定的口径，缺任何一栏就等于报告没按需求写
FIVE_COLUMNS = ["已实现且已通过测试", "已实现但尚未充分验证", "部分实现", "尚未实现", "已知问题及其影响"]
PLACEHOLDER_RE = re.compile(r"TBD|TODO|待填|<<[^>]*>>|此处省略")

LEDGER_ROW_RE = re.compile(r"^\| ISSUES I(\d+)\b")
LEDGER_STATUS_RE = re.compile(r"\*\*(OPEN|MITIGATED|CLOSED|WONTFIX)\*\*")

#: 台账表格的格子口径：`| 编号 | 标题 | 状态 | 事实 | 后果 | 销账条件 |` 共 6 格。
#: 为什么要数格子：2026-10-18 收尾时发现自己上一轮在 I86 那行写进了一个**裸竖线** ——
#: 它不是转义符而是分列符，渲染时把「残留事实不销账」那半段甩成了第 7 列（等于从表里掉出去）。
#: 而上面那两条老判据对这件事完全无感：那一行照样只有一个 `**CLOSED**`、编号照样连续。
LEDGER_CELL_COUNT = 6
#: 允许的历史伤条数。现数 1 处 = **ISSUES I35**（2026-10-15 写成四格、正文还跨了两物理行的历史行）。
#: 与 `LEDGER_STALE_CAP` 同一形状：带日期的记录不改写，但**不许再涨**；涨了就地修，不抬这条线。
LEDGER_SHAPE_CAP = 1
_ESC_PIPE = "\x01"


def ledger_row_cells(line: str) -> list[str]:
    """把一行台账切成格子：先把转义竖线 `\\|` 换成占位符再切，
    这样「正文里转义过」与「真多出一列」两种形状被分开数（前者无害，后者是伤）。"""
    return line.replace("\\|", _ESC_PIPE).split("|")


def ledger_shape_rows(text: str) -> list[str]:
    """结构不合格的台账行（格子数不是 6，或行尾没有闭合竖线），逐条点名。
    单独成一个函数而不是埋在 `ledger_check` 的循环里：守卫与门禁共用这一个口径。"""
    out: list[str] = []
    for line in text.splitlines():
        m = LEDGER_ROW_RE.match(line)
        if not m:
            continue
        cells = ledger_row_cells(line)
        if len(cells) - 2 != LEDGER_CELL_COUNT or cells[-1].strip():
            out.append(f"I{m.group(1)}（{len(cells) - 2} 格"
                       f"{'、行尾未闭合' if cells[-1].strip() else ''}）")
    return out


def ledger_check(text: str) -> tuple[list[str], list[str]]:
    """台账自身的四条口径：每行**有且只有一个**合法状态、编号从 I1 连续、不重号、
    每行格子结构与表头一致（6 格且以竖线闭合）。返回 (缺陷列表, 读数列表)。

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
    shape = ledger_shape_rows(text)
    gaps = [n for n in range(1, max(nums) + 1) if n not in seen] if nums else ["空台账"]
    if gaps:
        defects.append(f"编号断档：{gaps}")
    if len(shape) > LEDGER_SHAPE_CAP:
        defects.append(f"表格结构不合格 {len(shape)} 行 > 上限 {LEDGER_SHAPE_CAP}："
                       + "、".join(shape)
                       + f"（每行要正好 {LEDGER_CELL_COUNT} 格且以竖线闭合；"
                         "正文里的竖线必须写成 `\\|`）")
    reading = [f"{len(nums)} 行｜I1–I{max(nums) if nums else 0} 连续",
               "｜".join(f"{k} {v}" for k, v in sorted(tally.items())),
               f"结构不合格 {len(shape)} 行（上限 {LEDGER_SHAPE_CAP}）：{'、'.join(shape) or '无'}"]
    return defects, reading


def _gate(name: str, cmd: list[str], *, hint: str = "",
          timeout: float = GATE_TIMEOUT_SECONDS) -> Row:
    """把一个"探针/脚本自己判生死"的东西接进门禁：退出码 0 且末行 ALL GREEN 才算过。

    超时那一档现在会自己说明自己：原先 `TimeoutExpired` 直接把整段炸掉，读的人分不清
    「产品坏了」与「闸门时间到」，而真根一致性恰恰只有后者（**ISSUES I91**）。
    每条实测尾巴上都带「耗时」（轮十八 ⑥）：consistency / injection 段的耗时要读得出分布，
    不靠事后猜哪一段慢。
    """
    t0 = time.perf_counter()
    try:
        p = _run(cmd, timeout=timeout)
    except subprocess.TimeoutExpired:
        return Row(name, False,
                   f"闸门时间到：这一档上限 {timeout:.0f}s（不是产品判定，是链的天花板 —— "
                   f"要跑更长的现场就把 --data-root 那条走 {REAL_ROOT_TIMEOUT:.0f}s 那一档）",
                   hint)
    text = (p.stdout or "") + (p.stderr or "")
    green = p.returncode == 0 and "VERDICT: ALL GREEN" in text
    return Row(name, green,
               f"{_last_line(p)}｜耗时 {time.perf_counter() - t0:.1f}s", hint or text[-900:])


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
    rows.append(Row("已知问题台账逐条有状态、编号连续不重号、格子结构与表头一致", not defects,
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
        # 台账坏法三条：编号断档（缺 I2）+ 某行状态字段不是那四个词之一 + 表格结构（裸竖线多出
        # 一列 / 行尾没闭合）。后两条故意同时喂，判据要能只报「结构」那一档一次。
        ledger_bad, _ = ledger_check("| ISSUES I1 | a | **OPEN** | b | c | d |\n"
                                     "| ISSUES I3 | c | **FIXED someday** | d | e | f |\n")
        if len(ledger_bad) != 2:
            bad.append(f"台账坏行只抓到 {len(ledger_bad)} 项（应 2 项：编号断档 + 状态字段非法）")
        ledger_good, _ = ledger_check("| ISSUES I1 | a | **OPEN** | b | c | d |\n"
                                      "| ISSUES I2 | c | **WONTFIX** | d | e | f |\n")
        if ledger_good:
            bad.append(f"好台账被误判：{ledger_good}")
        ledger_shape, read_shape = ledger_check("| ISSUES I1 | a | **OPEN** | b | c | 没闭合\n"
                                                "| ISSUES I2 | c | **OPEN** | d | e | f | g |\n")
        hits = [d for d in ledger_shape if "表格结构不合格" in d]
        if len(ledger_shape) != 1 or len(hits) != 1:
            bad.append(f"表格结构坏法抓到 {len(ledger_shape)} 项（应正好 1 项且是新那一档）："
                       f"{ledger_shape}")
        if not any("结构不合格 2 行" in r for r in read_shape):
            bad.append(f"结构读数没上屏：{read_shape}")
    return Row("交付文档门禁自己有没有牙（坏法注入实测）", not bad,
               "残缺报告 + TBD 文档 + 坏台账（编号断档 / 非法状态 / 裸竖线与未闭合行）：抓到 "
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
    """坏法注入常驻段。四条判据的**口径是同一条**：红 **且** `FAILED` 行点名到该坏法登记的那条测试，
    只红不点名（崩溃冒充断言）算漏。p15 那一族覆盖归档界面与磁盘链路，单开一段（见 `segment_ui_injection`）。"""
    from stage1 import gate_injection  # noqa: PLC0415
    from stage5 import gate_ocr_injection  # noqa: PLC0415
    INJECTION_INFLIGHT.parent.mkdir(parents=True, exist_ok=True)
    INJECTION_INFLIGHT.write_text(
        "坏法注入段进行中。这个文件还在 = 上一次没走到收尾，源码/文档可能残留坏法。\n"
        "先按各探针说明还原工作区，再删除本文件；不要直接重跑门禁。\n",
        encoding="utf-8")
    # 只有整段全绿才删标记：红行可能是探针没还原完，超时更是直接杀了子进程。
    # 被强杀时这里不会执行，下一次起跑会在 preflight 拒绝 —— 宁可挡住重跑，也不许误判。
    try:
        rows = [gate_injection(), gate_ocr_injection(),
            _gate("p16 文档指针守卫：四档空指 + 台账旧名上限（P1–P6 + 反向对照）", [sys.executable, P16]),
            _gate("p17 队列处理函数形状核对：三条坏法（H1 少收参数 / H2 吞异常 / H3 只盯一种）",
                  [sys.executable, P17]),
            _gate("p18 「不可逆」口径唯一：三条坏法（S1 落库字段 / S2 界面自己数 / S3 服务定义退化）",
                  [sys.executable, P18]),
            _gate("p21 智能集合 24 条坏法（a/b/c/d/e/n 五条硬断言 + k chips 接线 + s S8 那一栏 + "
                  "p 两张表漂移 + g 分档算术 + h1 结构性写）", [sys.executable, P21]),
            _gate("p22 分类清单导出 33 条坏法（a/b/c/d/e 五条线框硬断言 + u 口径来源 + n 落盘纪律 + "
                  "r 回执 + f 格式与空值 + g 门 + w 接线）", [sys.executable, P22]),
            _gate("p23 批量点名面板 26 条坏法（U 读数形状 + B 分档接线 + P 预览执行同源 + C 代价 "
                  "+ R 理由行 + G 预算闸门 + N 过期名单 + X 取消 + F 失败上屏 + K 谎报新增 + W 折行）",
                  [sys.executable, P23]),
            _gate("p24 标签合并 17 条坏法（a 数据 / b 拒 / c 入口 / d 同源 + w 接线）",
                  [sys.executable, P24]),
            _gate("p25 OCR 按需 10 条坏法（A 待识别定义 + B 读数认筛选 + C 截断要说 + D 按筛选不按勾选 "
                  "+ E 空名单置灰 + F/G/H 提示条三态 + I 整批送）", [sys.executable, P25])]
        if all(r.ok for r in rows):
            INJECTION_INFLIGHT.unlink(missing_ok=True)
        return rows
    except BaseException:
        # 标记必须留给下一次起跑看：异常路径下没人能保证探针的 finally 跑过
        raise


def segment_ui_injection() -> list[Row]:
    """S3 四道闸 / 预览执行同源 / S4 撤销 / 状态页磁盘口径那 36 条坏法（2026-10-18 实测 70s，不进默认段）。"""
    return [_gate("p15 归档界面与磁盘链路 36 条坏法（C1–C11 / A1–A13 / O1–O8 / S1 / P1–P3）",
                  [sys.executable, P15])]


def segment_ocr() -> list[Row]:
    from stage5 import gate_budget_stop, gate_real_engine_suite, gate_shipped_measurement  # noqa: PLC0415
    return [gate_shipped_measurement(), gate_budget_stop(), gate_real_engine_suite()]


def segment_consistency(data_root: str | None) -> list[Row]:
    rows = [_gate("一致性探针 p12 反向注入自检（坏法逐条真注入 + C11 口径边界明写）",
                  [sys.executable, P12, "--inject"], hint=""),
            # G10 的判据本身也要被验一次：p14 把四种坏法各造一遍，看哪几种口径能看见（I8 的出处）
            _gate("FTS 一致性仪表有没有牙 p14（四种坏法 × 五种口径实测）",
                  [sys.executable, P14], hint="")]
    if data_root:
        row = _gate(f"一致性核查 p12 对指定数据根（{data_root}）",
                    [sys.executable, P12, "--data-root", data_root,
                     "--out", str(P12_REAL_OUT)],
                    timeout=REAL_ROOT_TIMEOUT)
        row.measured += f"｜完整 19 条见 {P12_REAL_OUT.relative_to(REPO)}"
        rows.append(row)
    else:
        # 这句原来写死「默认数据根 %LOCALAPPDATA%\PdfArchiver 在本机不存在」—— 那是阶段 0/1 的
        # 事实，真语料首扫之后就过期了。机器的状态不许抄成常量：改成现场数一遍，
        # 读数与判定各说各的（**ISSUES I87**）。
        # 取默认根只走产品自己那条口径（显式参数 > 环境变量 > 系统目录），门禁不许自己拼第二遍
        # —— 设了 PDFARCHIVER_DATA_DIR 时，用 os.environ 现读会报出一个不是产品真正在用的根。
        from pdfarchiver.config.paths import resolve_data_root  # noqa: PLC0415
        default_root = resolve_data_root()
        exists = default_root.is_dir()
        rows.append(Row("一致性核查 p12 对真实数据根", False,
                        f"本次未跑：没给 --data-root。默认数据根 {default_root} "
                        f"{'**在场**' if exists else '**不在场**'}；"
                        "门禁不自己默认去碰真库（要显式指定，见 I64 那条「用户数据不当夹具」），"
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
G2_BENCH_NAME = "G2 搜索 P95 真库实测（20 查询 × 5 reps，P95 ≤ 500ms）"
G2_LOAD_RETRY_WAIT = 90.0


def _g2_run() -> subprocess.CompletedProcess[str]:
    return _run([sys.executable, G2_BENCH])


def segment_g2() -> list[Row]:
    """G2 搜索 P95 真库实测（绑定真库；`--all` 会跑它，`--only g2` 也跑）。

    负载场与产品红分开（**ISSUES I25**，2026-10-21 轮十八）：探针自己采起跑负载，
    超 500ms 且机器忙时以退出码 3 收场 —— 判据一个字没放宽，只是别再把负载场读成
    "产品坏了"。这里遇到 3 等 90s 重试一次；两次都忙就记「环境不合格」，
    main() 的末行与产品红分开（`VERDICT: 环境不合格（不作数，重跑）`）。
    """
    inject = _gate("G2 负载分类自检（真实历史读数喂 classify）",
                   [sys.executable, G2_BENCH, "--inject"])
    first = _g2_run()
    if first.returncode == 0 and "VERDICT: ALL GREEN" in (first.stdout or ""):
        return [inject, Row(G2_BENCH_NAME, True, _last_line(first), "")]
    if first.returncode != 3:
        return [inject, Row(G2_BENCH_NAME, False, _last_line(first), (first.stdout or "")[-900:])]
    print(f"        第一次是负载场（{_last_line(first)}），等 {G2_LOAD_RETRY_WAIT:.0f}s 重试一次")
    time.sleep(G2_LOAD_RETRY_WAIT)
    second = _g2_run()
    if second.returncode == 0 and "VERDICT: ALL GREEN" in (second.stdout or ""):
        return [inject, Row(G2_BENCH_NAME, True,
                            f"重试后 {_last_line(second)}（第一次为负载场，不作数）", "")]
    if second.returncode == 3:
        return [inject, Row(G2_BENCH_NAME, False,
                            f"环境不合格（两次起跑都忙）｜第一次 {_last_line(first)}｜"
                            f"重试 {_last_line(second)}",
                            "探针自己采了两次起跑负载；判据 ≤500ms 未放宽 —— "
                            "这条不是产品红，等机器空闲后重跑 g2 段")]
    return [inject, Row(G2_BENCH_NAME, False,
                        f"重试后 {_last_line(second)}", (second.stdout or "")[-900:])]


SEGMENTS: dict[str, tuple[str, list[str]]] = {
    "guards": ("依赖守卫 + 架构守卫 + 交付文档在场性", ["1.4–2.8s"]),
    "regression": ("全量回归（pytest tests/，条数只认当次输出，不写死）", ["49.6–236.8s（2026-10-21 782 条）"]),
    "coldstart": ("G1 冷启动 + 关窗对账", ["1.0–2.0s"]),
    "e2e": ("新 · 后台生命周期 + 阶段 2 端到端（真 PDF / 真 worker / 真监听）", ["10.1–15.2s"]),
    # 415.3s 是 2026-10-18 五份探针空载上限；680.5s（轮十四 p21 入段）与 966.3s（轮十四 E 后八份）
    # 都是负载场 —— 680.5s 那场 p9 在**基线**就判红，红的是负载绑定的冷启动读数（**ISSUES I25**），
    # 不是产品坏了，也不是断言没牙。三档负载条件不同，不许互相换算。
    # p22（轮十四 D）单跑 73s、p23（轮十四 E）单跑 83.4s；p24 是 2026-10-20 轮十五 B 入段的第九份
    # （`tests/guards/test_probe_anchors.py` 那张表里含本段不跑的 p15，是第十份）。
    # 2026-10-20 九份同场**空载复跑 = 788.9s**，九份全绿（p9 69/69、p10 45/45、p16 8 坏法 + 3 对照、
    # p17 3、p18 3、p21 24、p22 25、p23 23、p24 17）；起跑 CPU 26.9%、可用内存 3,186MiB、最吃内存的
    # 进程 Qoder CN.exe 566MiB。此前 06:07 那场被**系统休眠 5.5h** 拖到 p10 的 1800s 上限而中断，
    # 那场墙钟作废（不是产品红、不是断言没牙），可比读数只认 788.9s 这一场。阈值一条没放宽。
    # 2026-10-21 整链内（r16c）**793.9s** 同量级，p22 此时已是 33/33。三条空载读数（788.9 / 793.9）
    # 与负载场 966.3s、五份时代 415.3s 并列展示，不互相换算。
    # p25 是 2026-10-28 轮三十六 C 入段的第十一份（p9 69、p10 45、p16 8+3、p17 3、p18 3、
    # p21 24、p22 33、p23 26、p24 17、p25 10 —— `test_probe_anchors.py` 那张表另含不进本段的 p15）。
    "injection": ("p9 + p10 + p16 + p17 + p18 + p21 + p22 + p23 + p24 + p25 反向注入（断言到底有没有约束力）",
                  ["788.9s / 793.9s（空载，2026-10-20 / 21，九份全绿）｜966.3s（负载场，八份）"]),
    "ui-inject": ("p15 归档界面与磁盘链路 36 条坏法（不进默认段）",
                  ["71.8s（2026-10-18）｜61.2s（2026-10-21 整链内）"]),
    "ocr": ("阶段 5 三条：产品路径实测 / 预算真停机 / 真引擎套件不许 skip", ["28.4–30.6s"]),
    "consistency": ("p12 注入自检 + p14 一致性仪表验牙 + （给了 --data-root 就）核查真实现场",
                    ["3.5–5.7s ＋真根另加 2,323.3s（r16c）／5,502.8s（r16）"]),
    "soak": ("p13 注入自检 + 真长跑采样", ["288.8–289.6s @4 分钟"]),
    "package": ("build.py 内容断言 + 冻结产物冒烟全阶段", ["241.9–255.0s｜238.1s（2026-10-21）"]),
    "g2": ("G2 搜索 P95 真库实测（绑定真库；--all 会跑；负载场判「环境不合格」不作数）",
                  ["83.9s（2026-10-18）｜33.7s（2026-10-21 整链内）"]),
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
    if name == "ui-inject":
        return segment_ui_injection()
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


def preflight_injection_residue() -> Row | None:
    """注入段被强杀时标记会留下：源码/文档可能还带着探针写进去的坏法。

    这时任何一段的读数都不可信，直接拒绝起跑。2026-10-21 轮十七实测过一次：
    p17 的 H3 残留（只核对 archive）让 job_queue 的正常断言变成 `DID NOT RAISE`，
    下一场全量回归把注入残留读成了产品缺陷。
    """
    if not INJECTION_INFLIGHT.exists():
        return None
    return Row("上一次坏法注入段没有收尾", False,
               f"标记还在：{INJECTION_INFLIGHT.relative_to(REPO)}",
               "src/ 或 docs/ 可能残留探针写进去的坏法；先按各探针说明还原工作区，"
               "再删除这个标记。标记在场时门禁拒绝起跑，避免把注入残留误判成产品缺陷。")


def main(argv: list[str] | None = None) -> int:
    harden_stdio()
    ap = argparse.ArgumentParser(prog="gates/final.py", description="最终交付门禁（分段链）")
    ap.add_argument("--only", action="append", default=None, choices=list(SEGMENTS) + ["docs-inject"],
                    help="只跑指定段，可重复")
    ap.add_argument("--all", action="store_true",
                    help="全链（2026-10-21 实测 4,023.1s ≈ 67 分钟；需后台时限 ≥4,200s）")
    ap.add_argument("--data-root", default=None, help="要核查一致性并写进交付报告的数据根")
    ap.add_argument("--soak-minutes", type=float, default=4.0, help="长跑采样时长（默认 4 分钟）")
    ap.add_argument("--list", action="store_true", help="列出每段是什么与耗时量级")
    args = ap.parse_args(argv)

    if args.list:
        print(f"共 {len(SEGMENTS)} 段｜默认跑 {' + '.join(DEFAULT_ORDER)}")
        for name, (what, cost) in SEGMENTS.items():
            print(f"  {name:<12} {cost[0]:>22}  {what}")
        print("  docs-inject           ~1s  交付文档门禁自己的坏法注入")
        print(f"  耗时是 2026-10-18 分段实测（`.probe_work/b1_seg*.log`）＋ 2026-10-21 整链实测"
              f"（`.probe_work/final_chain_r16c.log`，4,023.1s 全链），"
              f"injection 那几行是九份同场空载（含 p22 / p23 / p24）的读数，"
              f"并保留 966.3s（负载场，八份）与 415.3s（2026-10-18，五份）两条历史读数 —— "
              f"探针数与负载条件都不同，不许互相换算；"
              f"跑临时库的段共用 {GATE_TIMEOUT_SECONDS:.0f}s 那一档，"
              f"带 --data-root 的真根核查单独走 {REAL_ROOT_TIMEOUT:.0f}s 那一档（I91）")
        return 0

    residue = preflight_injection_residue()
    if residue is not None:
        print(f"门禁运行于 {REPO}｜python {sys.version.split()[0]}")
        print(f"  RED   {residue.gate}")
        print(f"        实测：{residue.measured}")
        print(f"        现场：{residue.note[:900]}")
        print("  合计判定 1 条｜本次未跑 0 段")
        print("VERDICT: RED（1 条未过）")
        return 1

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
                print(f"        现场：{row.note[:900]}")
        checks += rows

    for s in skipped:
        print(f"  SKIP  未跑的段：{s}（{SEGMENTS[s][0]}）—— 这一场的「全绿」不覆盖它")
    bad = [r for r in checks if not r.ok]
    # 「环境不合格」不是产品红：G2 在忙机器上超线（I25）时判的不是产品，是这台机器这次不能当量尺。
    # 只有**全部**红行都是环境不合格才走 2 号退出码 —— 混着真红时按红报，不许让一条环境行掩护真问题。
    env_only = bool(bad) and all("环境不合格" in r.measured for r in bad)
    print(f"  合计判定 {len(checks)} 条｜本次未跑 {len(skipped)} 段")
    if env_only:
        print(f"VERDICT: 环境不合格（{len(bad)} 条不作数，等机器空闲后重跑）")
        return 2
    print("VERDICT: " + ("ALL GREEN" if not bad else f"RED（{len(bad)} 条未过）"))
    return 0 if not bad else 1


if __name__ == "__main__":
    raise SystemExit(main())
