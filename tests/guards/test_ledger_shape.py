"""台账那张表的**格子结构**也要有机器守着 —— 只数状态与编号，照不到"多写了一列"。

现场（2026-10-18 收尾时自己照出来的）：上一轮给 **ISSUES I86** 追注销账证据时，我在正文里
写了一个**裸竖线**（本该写 `\\|`）。`split('|')` 把它当分列符，于是那一行从 6 格变成 7 格，
Markdown 渲染时「残留事实不销账」那半段被甩成表外的第 7 列 —— 内容还在文件里，表里已经没有了。
而链上原有的两条台账判据**一个字都没报**：那一行照只有一个 `**CLOSED**`，照编号照样连续。
同一族的第三条是 **ISSUES I35**：2026-10-15 那轮把行首从 `| I<n> |` 改成 `| ISSUES I<n> |` 时，
它的行尾闭合竖线也没了，正文跨了两个物理行、整行只有 3 格。这条按「带日期的记录不改写」保留，
所以本守卫带一个上限，形状与 `LEDGER_STALE_CAP` 一致：**历史伤可以留着，但不许再涨**。

判据只有一条，而且是静态的：`| ISSUES I<n> |` 开头的每一行，先把转义竖线换成占位符再切，
必须正好 6 格（`编号｜标题｜状态｜事实｜后果｜销账条件`）且最后一个切分段是空串（=行尾闭合）。
口径不在本文件另立，直接 import 门禁那一份（`gates/final.py` 的 `LEDGER_CELL_COUNT` /
`LEDGER_SHAPE_CAP` / `ledger_shape_rows`），免得守卫与链各数一遍、数出两个答案。

跑法：
    python -m pytest tests/guards/test_ledger_shape.py -q
    python tests/guards/test_ledger_shape.py      # 独立跑，末行 VERDICT
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "gates"))

from final import (  # noqa: E402  口径来自门禁，本文件不另立一套
    LEDGER_CELL_COUNT,
    LEDGER_SHAPE_CAP,
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
