"""分级确认控件 —— **D-042** 丙 定的「全站唯一危险操作控件形状」的两条分支。

S3「执行归档」和 S4「整批撤销」共用这一条，而它存在的全部意义是**按钮在人看过之前按不下去**，
所以这一组只读一个数：确认键的 `isEnabled()`。分档本身由 `DangerSummary.irreversible` 决定
（不是"看着危不危险"），两档各由一条断言钉住；`confirm_dangerous()` 里那句 `exec()` 会堵住
测试线程，因此测的是同一个构造函数 `build_confirm_box()`。

**不记忆任何一次选择**（`docs/UI-SCREENS.md` §S3 的硬约束：不许默认勾选 / 倒计时自动开始 /
记住上次选择）在这里是可测的：每次构造出来复选框未勾、确认词为空、确认键禁用。
"""
from __future__ import annotations

from PySide6 import QtWidgets

from pdfarchiver.ui.confirm import (CONFIRM_PLACEHOLDER, CONFIRM_WORD, DangerSummary,
                                    build_confirm_box)


def test_全可逆那档由复选框放行而确认键一进来是禁用的(qapp) -> None:
    box = build_confirm_box(None, title="确认执行归档", verb="归档",
                            summary=DangerSummary(will_run=7, same_disk=5, cross_disk=2,
                                                  irreversible=0))
    assert box.check_toggle is not None and box.word_input is None, (
        "全可逆的一档要打字会让人学会乱填（**D-042** 被否方案段）")
    assert box.accept_button.text() == "执行归档"
    assert not box.accept_button.isEnabled(), "一进来就能按 = 没有确认这一步"
    assert not box.check_toggle.isChecked(), "默认勾选就是把确认降级成一次点击"

    box.check_toggle.setChecked(True)
    assert box.accept_button.isEnabled()
    box.check_toggle.setChecked(False)
    assert not box.accept_button.isEnabled(), "记住上一次的勾选，按钮就永远开着了"


def test_含不可逆那档必须逐字输入确认词(qapp) -> None:
    box = build_confirm_box(None, title="确认执行归档", verb="归档",
                            summary=DangerSummary(will_run=3, same_disk=1, cross_disk=1,
                                                  irreversible=1))
    assert box.word_input is not None and box.check_toggle is None, (
        "含不可逆项还只给一个勾选，等于把覆盖别人文件当成一次点击")
    assert box.word_input.placeholderText() == CONFIRM_PLACEHOLDER
    assert not box.accept_button.isEnabled()

    for wrong in ("", "   ", CONFIRM_WORD[:-1], CONFIRM_WORD + "然后覆盖",
                  "确认不可逆 " + CONFIRM_WORD):
        box.word_input.setText(wrong)
        assert not box.accept_button.isEnabled(), f"输入 {wrong!r} 就放行，确认词形同虚设"

    box.word_input.setText(f"  {CONFIRM_WORD}  ")
    assert box.accept_button.isEnabled(), "粘贴带进来的首尾空白不该算成「打错了」"


def test_回车不许替人做决定(qapp) -> None:
    """模态框一打开焦点就在第一个控件上，回车若是确认，"手快"就能替代"看过了"。"""
    for summary in (DangerSummary(2, 2, 0, 0), DangerSummary(2, 1, 0, 1)):
        box = build_confirm_box(None, title="确认执行归档", verb="归档", summary=summary)
        assert box.accept_button.autoDefault() is False
        assert box.accept_button.isDefault() is False


def test_影响条数那一行只能由计划里的四个数拼出(qapp) -> None:
    box = build_confirm_box(None, title="确认撤销批次 #3", verb="撤销",
                            summary=DangerSummary(3, 1, 2, 0))
    assert box.headline.text() == (
        "将撤销 3 项：同盘 rename 1｜跨盘 copy+verify+delete 2｜不可逆 0")
    assert box.windowTitle() == "确认撤销批次 #3 —— 本机会改动磁盘上的文件", (
        "标题必须说清这一机会动本机磁盘")


def test_排除原因逐条落在确认框里而不是汇成一句(qapp) -> None:
    """**D-043** 甲 的第 2 行：撤销排除的**条数与原因必须显示**，不许只显示"撤销成功"。"""
    reasons = ("#7 的目标位置文件已经不在了，不凭空造源文件",
               "#8 的原位置已经有新文件，撤回会把它盖掉")
    box = build_confirm_box(None, title="确认撤销批次 #4", verb="撤销",
                            summary=DangerSummary(5, 5, 0, 0,
                                                  lines=("排除 2 项，原因逐条：",) + reasons))
    shown = [label.text() for label in box.findChildren(QtWidgets.QLabel)]
    assert shown[0].startswith("将撤销 5 项")
    assert "排除 2 项，原因逐条：" in shown
    for reason in reasons:
        assert reason in shown, f"原因被汇总成一句了：{reason!r} 不在屏上"
