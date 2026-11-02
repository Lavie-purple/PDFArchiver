"""验证范围冻结（**D-074** · 轮五十七 丙）—— 门禁段的数量是一条只许往下、不许往上数的线。

为什么要钉这个数：交付以后每一场门禁都在自己造欠账 —— G1 / G2 / 各段耗时量的是**这台机器今天的状态**，
不是产品行为，「读数超标但不是缺陷」那一类残差按纪律既不赦免、也不许重跑到绿，剩下的处置只有记账；
**段数越密，账越多**，这正是「欠账一直涨、不收敛」的三条机制里最硬的一条。用户 2026-11-03 的原话
「继续丙和丁」，丙 = 「以后不新增门禁段、不起长任务」（24h soak、`integrity_check` 全库档、
`--c11-deep` 一律作废为不做）。这条把那句口头的"以后"变成可当场判真伪的断言
（AGENTS.md：约束要写成硬条件，禁止"看起来对不对"）。

判据只有一条，而且是静态的：`gates/final.py::SEGMENTS` 的键数不超过 `FROZEN_SEGMENT_COUNT`。
**这是一把往下的锁**：想加一段必须先拿到用户同意并另立一条编号决定，不许抬这条线 ——
与 `LEDGER_MITIGATED_CAP` 同一形状（抬线等于把锁拆掉）。它不判"段跑不跑得过"，只判"段有没有变多"。

**这条守卫查不出什么**：它管不到"用已有段落起长任务"（`--only soak --minutes 1440` 结构上合法），
那一半靠 `docs/DECISIONS.md` **D-074** 的明文与 `docs/ISSUES.md` 表头的入册规矩；数量线只封住会自己
长账的那一半 —— 新增一段 = 每场门禁多一批必残差。

坏法注入：本文件第三条自己往里塞一个假段名，要求上一条当场变红**并点名那一段**；
注入在 `finally` 里还原。没红过的守卫不算守卫（AGENTS.md），所以这条常驻在守卫家里而不是
"某轮手动注入过一次"。

跑法：
    .venv/Scripts/python.exe -m pytest tests/guards/test_scope_freeze.py -q
    .venv/Scripts/python.exe tests/guards/test_scope_freeze.py   # 独立跑，末行 VERDICT
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "gates"))

from final import SEGMENTS  # noqa: E402  口径来自门禁，本文件不另立一套

#: 现数 11（2026-11-03 轮五十七 丙 冻结）：
#: guards / regression / coldstart / e2e / injection / ui-inject / ocr / consistency / soak / package / g2。
#: `--only docs-inject` 是链外的收尾档，不在 `SEGMENTS` 里，所以不计进这条线。
FROZEN_SEGMENT_COUNT = 11


#: 冻结那一刻的段名集合，逐字取自 `gates/final.py`（改名也抓得到：新名字不在这里）。
FROZEN_BASELINE = (
    "guards", "regression", "coldstart", "e2e", "injection", "ui-inject",
    "ocr", "consistency", "soak", "package", "g2",
)


def _extra_keys() -> list[str]:
    """比冻结那一刻多出来的段名（顺序稳定，便于报错点名）。"""
    return sorted(set(SEGMENTS) - set(FROZEN_BASELINE))


def test_门禁段数不超过冻结线() -> None:
    assert len(SEGMENTS) <= FROZEN_SEGMENT_COUNT, (
        f"门禁段数 {len(SEGMENTS)} > 冻结线 {FROZEN_SEGMENT_COUNT}"
        f"（多出来的：{'、'.join(_extra_keys())}）。**D-074** 定的是「以后不新增门禁段」——"
        "要加段先拿用户同意并另立编号决定，不许把这条线抬高（抬线等于把锁拆掉）。")


def test_冻结名单打在真段表上() -> None:
    """防"守卫自己空转"：`SEGMENTS` 若被改名或清空，上一条会因为集合变小而恒绿。"""
    assert set(FROZEN_BASELINE) <= set(SEGMENTS), (
        f"冻结名单里有段不在 `SEGMENTS`（{sorted(set(FROZEN_BASELINE) - set(SEGMENTS))}）"
        "—— 段表改名或搬走了，本守卫已经在空转")


def test_冻结线接在真段表上而不是只过合成串() -> None:
    """正对照：往 `SEGMENTS` 临时塞一个假键，上一条必须当场变红**并点名那个键**。
    为什么要在测试里注入而不是只在文档里写"注入过一次"：接线断了（比如 `SEGMENTS` 被复制成
    一份局部字典）守卫会一直绿，而 `test_ledger_shape` 里"把上限挪到 0"那一招已经证明这种
    自证可以稳定地放进守卫自己家，不必等收尾手跑一遍。"""
    import final

    fake = "u57-假段"
    assert fake not in final.SEGMENTS, "假键真在里面，那条注入就成了空转"
    final.SEGMENTS[fake] = ("坏法注入用的假段（不该在场）", ["0s"])
    try:
        try:
            test_门禁段数不超过冻结线()
        except AssertionError as exc:
            assert fake in str(exc), f"红了却没点名多出来的那一段：{exc}"
        else:
            raise AssertionError("多出一段却没变红 —— 这条冻结线是空的")
    finally:
        del final.SEGMENTS[fake]


def main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = []
    for fn in tests:
        try:
            fn()
        except AssertionError as exc:
            failed.append(f"{fn.__name__}: {exc}")
    print(f"验证范围冻结守卫 {len(tests)} 条｜冻结线 {FROZEN_SEGMENT_COUNT}｜现段数 {len(SEGMENTS)}"
          f"｜失败 {len(failed)} 条")
    for f in failed:
        print("  红 " + f)
    print("VERDICT: ALL GREEN" if not failed else "VERDICT: RED")
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
