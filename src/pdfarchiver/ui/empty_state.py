"""全站空态的唯一出口（走查 **⑱** / 决策 **D-066**）。规则就一句：

**列表类面板空着 ⇒ 不许是一块空框，要有一句「这里会有什么、怎么让它有」的引导**；
那句里点名的动作必须在界面上真存在（由 `tests/integration/test_empty_state.py` 全站扫，
不是逐屏打补丁）。

为什么收成一层：轮四十二的 ⑨⑩⑪ 三处空态各写四行一模一样的
`QLabel` + `setObjectName("muted")` + `setWordWrap(True)` + `setVisible(count == 0)`，
下一屏加列表就是第四遍，而守卫没有可指的对象 —— 它要断言的是「这一处空态属于 ⑱ 那条规则」，
那就得有个东西把「它是一句空态引导」写在明处。这一层只管两件事：**样式**与**跟着条数走**，
文案仍然逐屏自己写（内容各不相同，抄不成一句）。

表格不在本条口径内：它们的"这些行是什么"由状态行/说明条回答（S1 的 `_set_status`、
S4 的 `loaded_note`、S3 的 `plan_summary`），再叠一句列表式引导就是同一件事的第二个口径。
"""
from __future__ import annotations

from PySide6 import QtWidgets

#: 挂在 QLabel 上的动态属性：把它标成「⑱ 那条规则管的一句空态引导」。
#: 守卫读的就是这个属性，不是措辞 —— 措辞像不像空态没法机器判定。
EMPTY_STATE_PROPERTY = "emptyStateHint"


def make_hint(text: str, parent: QtWidgets.QWidget | None = None) -> QtWidgets.QLabel:
    """造那句空态引导。`parent` 显式给（PySide6 6.8 不给没挂进布局的控件补 reparent，
    轮三十九那批「✕」孤儿顶层窗就是漏挂父爆出来的）。"""
    hint = QtWidgets.QLabel(text, parent)
    hint.setObjectName("muted")
    hint.setWordWrap(True)
    hint.setProperty(EMPTY_STATE_PROPERTY, True)
    return hint


def row_count(list_widget: QtWidgets.QWidget) -> int:
    """这一栏现在有几条：列表数 `count()`，树数一级节点 —— 分叉只在这里分一次。

    守卫与本模块的 `sync_hint` 共用它，"这一栏空不空"才只有一个口径（树没有 `count()`，
    两边各写一遍就是两个口径，轮四十二在 `test_ui_tier.py` 里踩过同一形状）。
    """
    if isinstance(list_widget, QtWidgets.QTreeWidget):
        return list_widget.topLevelItemCount()
    return list_widget.count()


def sync_hint(list_widget: QtWidgets.QWidget) -> None:
    """把**同一个容器里**那几句空态引导的可见性推到「列表空着才在」。

    容器 = `list_widget.parentWidget()`：引导与列表挂在同一个面板里，所以"这一栏空不空"
    只在这个面板的范围内回答，不会把隔壁栏的引导一起点亮。
    """
    host = list_widget.parentWidget()
    if host is None:
        return
    empty = row_count(list_widget) == 0
    for hint in host.findChildren(QtWidgets.QLabel):
        if hint.property(EMPTY_STATE_PROPERTY) is True:
            hint.setVisible(empty)
