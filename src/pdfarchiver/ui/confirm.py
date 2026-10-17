"""分级确认控件 —— **D-042** 丙 定的「全站唯一危险操作控件形状」。

定案原文（`docs/DECISIONS.md` **D-042**）：

> 确认控件 **丙 · 分级**：全部可逆 → 复选框 + 影响条数；含不可逆项 → **必须输入确认词**。
> 从此是**全站唯一的危险操作控件形状**：S4 的撤销、S6 的恢复都复用同一条，不许任一屏自造第三种。

两档的分界不是"看起来危不危险"，而是**这一批里有没有执行之后回不去的项**
（`irreversible > 0`）。为什么不能一律复选框：那会把"覆盖掉别人的文件"降级成一个勾选；
为什么不能一律输确认词：日常九十几项纯移动也要打字，用户很快学会乱填（**D-042** 被否方案段）。
`docs/UI-SCREENS.md` §三 另有一条同向红线：危险操作**不许 `QMessageBox.question` 一下就完**，
所以这里是一个自己画的 `QDialog`，控件都挂成具名属性，好让测试能驱动它们。

**不记忆任何一次选择**（§S3 的硬约束"不许有默认勾选、倒计时自动开始、记住上次选择"）：
每次进来复选框都是未勾、确认词都是空的、确认按钮都是禁用的。
"""
from __future__ import annotations

from dataclasses import dataclass, field

from PySide6 import QtWidgets

# 要输入的确认词。写在这一处而不是各屏各写一句：确认词是"我在承担不可逆后果"这句话的签名，
# 两个屏用不同的词就等于凭空分出两种危险等级，而词表没人维护。
CONFIRM_WORD = "确认不可逆"
CONFIRM_PLACEHOLDER = f"逐字输入：{CONFIRM_WORD}"


@dataclass(frozen=True)
class DangerSummary:
    """确认框要如实报出来的那四个数，外加逐条形需要人看的原因。

    数字**只能由调用方从计划里算**（S3 走 `ArchiveService.plan()`、S4 走 `plan_undo()`）：
    控件自己不查库、不猜条数。
    """

    will_run: int
    same_disk: int
    cross_disk: int
    irreversible: int
    lines: tuple[str, ...] = field(default=())

    @property
    def needs_confirm_word(self) -> bool:
        return self.irreversible > 0


def confirm_dangerous(parent: QtWidgets.QWidget | None, *, title: str, verb: str,
                      summary: DangerSummary) -> bool:
    """弹出分级确认框，返回用户是否确认执行。

    `verb` 是动作名（「归档」「撤销」），只出现在标题与按钮上；影响条数那几句全部由
    `summary` 拼，控件不猜自己要干什么。
    """
    return build_confirm_box(parent, title=title, verb=verb,
                             summary=summary).exec() == QtWidgets.QDialog.DialogCode.Accepted


def build_confirm_box(parent: QtWidgets.QWidget | None, *, title: str, verb: str,
                      summary: DangerSummary) -> QtWidgets.QDialog:
    """构造那个对话框。单独成一个函数是为了**不开模态也能驱动里面的控件** ——
    `exec()` 会堵住测试线程，而这一屏最要命的两条性质（复选框没勾不许确认、确认词打错不许确认）
    只能读按钮的 `isEnabled()` 来验。
    """
    box = QtWidgets.QDialog(parent)
    box.setWindowTitle(f"{title} —— 本机会改动磁盘上的文件")
    box.setModal(True)
    box.check_toggle = None
    box.word_input = None

    lay = QtWidgets.QVBoxLayout(box)
    box.headline = QtWidgets.QLabel(
        f"将{verb} {summary.will_run} 项：同盘 rename {summary.same_disk}"
        f"｜跨盘 copy+verify+delete {summary.cross_disk}｜不可逆 {summary.irreversible}")
    box.headline.setWordWrap(True)
    lay.addWidget(box.headline)

    for line in summary.lines:
        extra = QtWidgets.QLabel(line)
        extra.setWordWrap(True)
        extra.setObjectName("muted")
        lay.addWidget(extra)

    buttons = QtWidgets.QDialogButtonBox(
        QtWidgets.QDialogButtonBox.StandardButton.Ok
        | QtWidgets.QDialogButtonBox.StandardButton.Cancel)
    box.accept_button = buttons.button(QtWidgets.QDialogButtonBox.StandardButton.Ok)
    box.accept_button.setText(f"执行{verb}")
    # 回车不是确认：模态框一打开焦点就在第一个控件上，Enter 等于确认的话"手快"就能替代
    # "看过了"，而这个对话框存在的全部意义是让人先看一遍。
    box.accept_button.setAutoDefault(False)
    box.accept_button.setEnabled(False)
    buttons.button(QtWidgets.QDialogButtonBox.StandardButton.Cancel).setText("取消，什么都不做")
    buttons.accepted.connect(box.accept)
    buttons.rejected.connect(box.reject)

    if summary.needs_confirm_word:
        hint = QtWidgets.QLabel(
            f"这批里含 {summary.irreversible} 项「不可逆」改动："
            f"请输入确认词「{CONFIRM_WORD}」才能执行。")
        hint.setWordWrap(True)
        lay.addWidget(hint)
        box.word_input = QtWidgets.QLineEdit()
        box.word_input.setPlaceholderText(CONFIRM_PLACEHOLDER)
        lay.addWidget(box.word_input)
        box.word_input.textChanged.connect(
            # 比对去掉首尾空白：粘贴时带一个尾空格是很常见的，而"打错了"和"多粘了一个空格"
            # 是两件事，后者不该让人以为自己没输对确认词。
            lambda text: box.accept_button.setEnabled(text.strip() == CONFIRM_WORD))
    else:
        box.check_toggle = QtWidgets.QCheckBox(f"我确认要{verb}这 {summary.will_run} 项文件")
        lay.addWidget(box.check_toggle)
        box.check_toggle.toggled.connect(box.accept_button.setEnabled)

    lay.addWidget(buttons)
    return box
