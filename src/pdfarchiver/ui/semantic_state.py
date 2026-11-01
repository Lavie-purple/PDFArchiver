"""「语义模型在不在本机」在界面层的唯一出口（轮五十一 Q1 乙 / Q3 乙 / Q4 乙）。

单独一个模块的理由和 `ui/library_hits.py` 那条一样：这件事被三个入口消费（S1「语义搜索」、
S1「AI 推荐分类」+「为当前文档建向量」、S9「提问」），文案与红字规则各抄三份必然会漂。
**界面不判定**：判定住在语义层，装配时快照成 `AppContext.semantic_ready` 一个布尔，这里只读它 ——
模型目录的路径口径在 UI 层出现第二份，就是 **ISSUES I37** 那条的老毛病。

`absent_or_original` 藏的是**绝对路径**，不是错误本身：原文逐字进日志（AGENTS.md 排障条
「报错必须能被远程诊断」），屏上只留一句人话。这句之所以不是猜测 —— `semantic/` 里
`raise FileNotFoundError` 只有 `embedding.py` 那两条（模型文件、分词器文件），由
`tests/integration/test_model_absent_entries.py` 钉着；别层（archive / backup）抛的同类型异常
走的是别的入口，不经过这里。
"""
from __future__ import annotations

import logging

from PySide6 import QtWidgets

_LOG = logging.getLogger(__name__)

ABSENT_SHORT = "语义模型不在本机"
ABSENT_REASON = f"{ABSENT_SHORT}，完整原因已写进日志"
# Q4 乙：两层都要说到 —— ①现在做不了 ②放好模型要重启才生效。只说①就成了新的假话
# （线框 §3「为什么不轮询」那段记的代价）。`models` 是相对目录名、不是绝对路径（Q3 乙禁的是后者）；
# 模型版本号**不写在这里**：那是语义层自己的口径，抄进文案就有了第二份。
DISABLE_TIP = (f"现在用不了：{ABSENT_SHORT}。把语义模型放到数据目录的 models 下，重启应用才生效 —— "
               "界面只在建窗时读一次，不重启不会自己变亮。")


def apply_state(widget: QtWidgets.QWidget, *, ready: bool) -> None:
    """不在场 = 禁用 + 统一指路；在场 = **一条都不动**。

    在场那一支什么都不做是有意的：Q1 乙承诺「在场时三处行为与现状逐字同」，而各屏的按钮本来
    就有自己那层成因（没选中行 ⇒ 禁用）。这里替它 `setEnabled(True)` 就把那层判据顶掉了。
    """
    if ready:
        return
    widget.setEnabled(False)
    widget.setToolTip(DISABLE_TIP)


def absent_or_original(exc: BaseException, *, prefix: str = "") -> str:
    """失败读文的唯一出口：模型缺席给一句（原文进日志），其余失败照旧回后端原文。

    判据取异常类型而不是 `semantic_ready` 的快照：用户真能走到的是"在场建窗 → 模型被删走 → 点"，
    那一刻快照是过期的 `True`，按快照走就把带盘符的长路径吐上了屏。
    """
    if isinstance(exc, FileNotFoundError):
        _LOG.warning("语义能力不可用，界面只上一句；后端原文如下：%s", exc)
        return f"{prefix}{ABSENT_REASON}"
    return f"{prefix}{exc}"
