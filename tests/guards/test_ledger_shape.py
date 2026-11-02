"""台账那张表的**格子结构**也要有机器守着 —— 只数状态与编号，照不到"多写了一列"。

现场（2026-10-18 收尾时自己照出来的）：上一轮给 **ISSUES I86** 追注销账证据时，我在正文里
写了一个**裸竖线**（本该写 `\\|`）。`split('|')` 把它当分列符，于是那一行从 6 格变成 7 格，
Markdown 渲染时「残留事实不销账」那半段被甩成表外的第 7 列 —— 内容还在文件里，表里已经没有了。
而链上原有的两条台账判据**一个字都没报**：那一行照只有一个 `**CLOSED**`，照编号照样连续。
同一族的第三条是 **ISSUES I35**：2026-10-15 那轮把行首从 `| I<n> |` 改成 `| ISSUES I<n> |` 时，
它的行尾闭合竖线也没了，正文跨了两个物理行、整行只有 3 格。这条按「带日期的记录不改写」保留，
所以本守卫带一个上限，形状与 `LEDGER_STALE_CAP` 一致：**历史伤可以留着，但不许再涨**。

判据第一条是静态的格数口径：`| ISSUES I<n> |` 开头的每一行，先把转义竖线换成占位符再切，
必须正好 6 格（`编号｜标题｜状态｜事实｜后果｜销账条件`）且最后一个切分段是空串（=行尾闭合）。
**2026-11-02 轮五十六 甲** 加了两条同族的锁：`MITIGATED` 行必须在销账格里写「退出判据：」、
`LIMIT` 行必须写「重开触发：」，且 `MITIGATED` 条数不超过 `LEDGER_MITIGATED_CAP`。
加它们的理由就写在本次现场：`MITIGATED` 从轮二十五的 20 涨到 23，跨十二轮**没有一次下降**，
而逐条核实之后 23 条里有 5 条的销账条件早已满足（**ISSUES I109** 最典型：台账写着
「按钮那条路径仍是同步的」，`status_page.py:161` 却早就在 `threading.Thread` 里跑了）。
**没有可判的退出条件，"逐条销账"就退化成一句口号。**
口径不在本文件另立，直接 import 门禁那一份（`gates/final.py` 的 `LEDGER_CELL_COUNT` /
`LEDGER_SHAPE_CAP` / `LEDGER_MITIGATED_CAP` / `ledger_shape_rows`），免得守卫与链各数一遍、数出两个答案。

跑法：
    python -m pytest tests/guards/test_ledger_shape.py -q
    python tests/guards/test_ledger_shape.py      # 独立跑，末行 VERDICT
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "gates"))

from final import (  # noqa: E402  口径来自门禁，本文件不另立一套
    LEDGER_CELL_COUNT,
    LEDGER_MITIGATED_CAP,
    LEDGER_ROW_RE,
    LEDGER_SHAPE_CAP,
    LEDGER_STATUS_RE,
    LIMIT_REOPEN_MARK,
    MITIGATED_EXIT_MARK,
    ledger_check,
    ledger_shape_rows,
)

LEDGER = REPO / "docs" / "ISSUES.md"
#: 现数 93 行；下限留余量，防的是"扫了个空集合然后假绿"（同 `test_gate_verdict_line` 那个 floor）
ROW_FLOOR = 60
#: 允许在册的历史伤，逐条点名。名单变了 = 这一轮新写坏了，就地修那行，不是把名单加长。
KNOWN_SHAPE_WOUNDS = ["I35"]


def _text() -> str:
    return LEDGER.read_text(encoding="utf-8", errors="replace")


def test_扫到的台账行数打在真东西上而不是空集合() -> None:
    n = int(ledger_check(_text())[1][0].split(" 行")[0])
    assert n >= ROW_FLOOR, f"只扫到 {n} 行台账，少于下限 {ROW_FLOOR}：正则已经打空"


def test_历史伤不超过上限且就是点名那几条() -> None:
    found = ledger_shape_rows(_text())
    assert len(found) <= LEDGER_SHAPE_CAP, (
        f"结构不合格 {len(found)} 行 > 上限 {LEDGER_SHAPE_CAP}：{found}。"
        "新写坏的那行是这一轮加的：裸竖线改成 \\|、行尾补上闭合竖线，别抬上限")
    ids = [f.split("（")[0] for f in found]
    assert ids == KNOWN_SHAPE_WOUNDS, f"在册历史伤变了：{ids} != {KNOWN_SHAPE_WOUNDS}"


def test_上限内的伤不判红但必须把读数上屏() -> None:
    one = "| ISSUES I1 | a | **OPEN** | b | c | 这句没写完就换行\n"
    defects, reading = ledger_check(one)
    assert defects == [], f"一条历史伤而已，不该判红：{defects}"
    assert f"结构不合格 1 行（上限 {LEDGER_SHAPE_CAP}）：I1（5 格、行尾未闭合）" in reading[-1], reading


def test_超出上限的新伤必须判红且点名到行() -> None:
    two = ("| ISSUES I1 | a | **OPEN** | b | c | d 里写了 | 裸竖线 |\n"
           "| ISSUES I2 | a | **OPEN** | b | c | 行尾没闭合\n")
    defects, _ = ledger_check(two)
    assert len(defects) == 1 and "表格结构不合格" in defects[0], defects
    assert "I1（7 格）" in defects[0] and "I2（5 格、行尾未闭合）" in defects[0], defects[0]


def test_转义竖线不算多出一列() -> None:
    good = "| ISSUES I1 | a | **OPEN** | b | 写法是 \\| 而不是裸竖线 | d |\n"
    assert ledger_shape_rows(good) == [], ledger_check(good)[0]


def test_格数口径改动时本守卫立刻有反应() -> None:
    """正对照：把链里那个 6 改成 5，真台账必须当场判红 —— 证明判据真在数格子，不是背好的字符串。"""
    import final

    original = final.LEDGER_CELL_COUNT
    try:
        final.LEDGER_CELL_COUNT = 5
        assert ledger_shape_rows(_text()), "改成 5 格还扫不出伤：判据没接在格数上"
    finally:
        final.LEDGER_CELL_COUNT = original


def test_MITIGATED不写退出判据就判红且点名到字面量() -> None:
    defects, _ = ledger_check("| ISSUES I1 | a | **MITIGATED** | b | c | 只写了残留事实不销账 |\n")
    assert len(defects) == 1, f"该正好一条缺陷：{defects}"
    assert MITIGATED_EXIT_MARK in defects[0], defects
    good, _ = ledger_check(f"| ISSUES I1 | a | **MITIGATED** | b | c | {MITIGATED_EXIT_MARK}C3 漂移归零且有断言 |\n")
    assert good == [], f"写了判据的好台账被误判：{good}"


def test_LIMIT不写重开触发就判红且不误判写了的() -> None:
    defects, _ = ledger_check("| ISSUES I1 | a | **LIMIT** | b | c | 本机跑不了全量 |\n")
    assert len(defects) == 1, f"该正好一条缺陷：{defects}"
    assert LIMIT_REOPEN_MARK in defects[0], defects
    good, _ = ledger_check(f"| ISSUES I1 | a | **LIMIT** | b | c | {LIMIT_REOPEN_MARK}换上 GPU |\n")
    assert good == [], f"写了触发的好台账被误判：{good}"


def test_棘轮锁接在真台账上而不是只过合成串() -> None:
    """三件事合在一条：① 现台账的 MITIGATED 条数不超过上限、② 每一条真行都带退出判据、
    ③ 把其中一条真行的标记抹掉，判据必须当场变红。
    为什么不只测合成串：接线断了守卫会一直绿（**ISSUES I35** 那次静默失效的教训）。
    状态一律用门禁那一份正则 `LEDGER_STATUS_RE` 数，不在本文件另立一套 —— 上一轮就是因为
    这里用了 `"MITIGATED" in line` 的子串口径，把正文里提到这个词的 CLOSED 行也算了进来。"""
    text = _text()
    defects, reading = ledger_check(text)
    mit = int(re.search(r"MITIGATED (\d+)", reading[1]).group(1))
    assert mit <= LEDGER_MITIGATED_CAP, (
        f"现台账 MITIGATED {mit} 条 > 上限 {LEDGER_MITIGATED_CAP}：棘轮响了。"
        "去查有没有「退出判据已经满足却没改状态」的那几条，别抬这条线")
    missing = [d for d in defects if MITIGATED_EXIT_MARK in d]
    assert missing == [], f"这些 MITIGATED 行没写退出判据：{missing}"
    limit_missing = [d for d in defects if LIMIT_REOPEN_MARK in d]
    assert limit_missing == [], f"这些 LIMIT 行没写重开触发：{limit_missing}"
    rows = [line for line in text.splitlines()
            if LEDGER_ROW_RE.match(line) and LEDGER_STATUS_RE.findall(line) == ["MITIGATED"]]
    assert rows, "现台账里一条 MITIGATED 都没有，这条正对照会假绿"
    tampered = rows[0].replace(MITIGATED_EXIT_MARK, "退出判据被抹掉了")
    assert tampered != rows[0], f"抹不掉标记，说明排第一的那条根本没带它：{rows[0][:40]}"
    hit, _ = ledger_check(tampered + "\n")
    assert any(MITIGATED_EXIT_MARK in d for d in hit), hit


def test_MITIGATED上限挪到零时真台账必须变红并点名() -> None:
    """正对照：现数低于上限时这条判据不发声，所以把线挪到 0，真台账要当场变红 ——
    证明上限真接在状态计数上，而不是抄在文档里的一句承诺。"""
    import final

    original = final.LEDGER_MITIGATED_CAP
    try:
        final.LEDGER_MITIGATED_CAP = 0
        defects, reading = ledger_check(_text())
    finally:
        final.LEDGER_MITIGATED_CAP = original
    hits = [d for d in defects if "MITIGATED" in d and "上限" in d]
    assert len(hits) == 1, f"把上限挪到 0 却只抓到 {len(hits)} 项：{defects}"
    # 点名必须指到真行：括号里列出的每个编号，台账里要真有这一行，且条数与状态计数对得上。
    # 只断言"抓到一条"是不够的 —— 那种判据被一条措辞变化的假点名糊弄得过去。
    bracketed = re.search(r"（(.*?)）", hits[0])
    assert bracketed, f"上限缺陷没把编号列在括号里：{hits[0]}"
    named = re.findall(r"I(\d+)", bracketed.group(1))
    lines = _text().splitlines()
    for i in named:
        assert any(ln.startswith(f"| ISSUES I{i} |") for ln in lines), f"点名了 I{i}，台账里没有这行"
    counted = int(re.search(r"MITIGATED (\d+)", reading[1]).group(1))
    assert len(named) == counted, f"点名 {len(named)} 条 ≠ 状态计数 {counted} 条：{hits[0]}"
    assert "账内（OPEN+MITIGATED）" in reading[2], f"结算读数不在第 3 项：{reading}"


def main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = []
    for fn in tests:
        try:
            fn()
        except AssertionError as exc:
            failed.append(f"{fn.__name__}: {exc}")
    print(f"台账结构守卫 {len(tests)} 条｜失败 {len(failed)} 条")
    for f in failed:
        print("  红 " + f)
    print("VERDICT: ALL GREEN" if not failed else "VERDICT: RED")
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
