"""「这一格装不装得下」的唯一一句判据，加上盯宿主宽度变化那只观察者（**ISSUES I121** ④）。

轮四十七 把这条判据写进表格（`ui/table_layout.py` 的吸收列：`其余定宽列 + 吸收列下限 ≤ 视口`），
轮四十八 的动作行末格与阅读器「适应宽度」问的是**同一件事** —— 现在还剩多少宽。
写成三份就会有第二套、第三套口径（AGENTS.md「禁止核心概念多口径」），所以搬到这里一处。

判据只有一个形状：`定宽那部分 + 要吸收的那一格 ≤ 宿主宽`。
「宿主」是什么由调用方定：表格是 `table.viewport()`，动作行是行自己，阅读器是画布视口。
"""
from __future__ import annotations

from collections.abc import Callable

from PySide6 import QtCore, QtWidgets


def fits_absorbing(fixed_total: int, absorb_width: int, host_width: int) -> bool:
    """定宽那部分 `fixed_total` 加上要吸收的 `absorb_width`，装不装得进 `host_width`。

    装不下时调用方各自降级：表格退回全定宽 + 横向滚动（**D-040** 的地板档既定降级），
    动作行把那句留在它原来的位置。**没有第三种**：把装不下的东西硬塞进去，被压瘪的总是
    内容那一侧（实测列被压成 38px／25px 的缝，而长文字把行宿主顶宽则榨瘪侧栏 —— **I52**）。
    """
    return fixed_total + absorb_width <= host_width


class HostResizeWatcher(QtCore.QObject):
    """宿主每变一次宽，就把新的宿主宽交给一个回调。

    三条实测坑（轮四十七 一条条注入出来的，形状照搬，别改回"看着更顺"的版本）：

    - **只跟 Resize，不另接 Show**：隐藏的页切过来那一刻，Qt 会把攒下的那次改尺寸**补发**成
      一次 Resize；接两条等于把同一件事判两遍。
    - **判据只比 Python 包装对象**，`eventFilter` 里不回摸宿主之外的控件：拆窗口时别一半的
      C++ 侧可能先没，摸了就抛 `Internal C++ object already deleted` 刷屏。
    - **重入保护**：回调里改布局会回头再触发一次 Resize，`_applying` 挡掉那一层。
    """

    def __init__(self, host: QtWidgets.QWidget, on_width: Callable[[int], None]) -> None:
        super().__init__(host)          # parent 在宿主上 ⇒ 随宿主一起销毁，不留野观察者
        self._host = host
        self._on_width = on_width
        self._applying = False

    def attach(self) -> "HostResizeWatcher":
        self._host.installEventFilter(self)
        return self

    def sync(self) -> None:
        """主动走一遍：页面重写过那格的内容、或改了它的可见性之后。"""
        self._relayout()

    def eventFilter(self, watched: QtCore.QObject, event: QtCore.QEvent) -> bool:
        if event.type() != QtCore.QEvent.Type.Resize or watched is not self._host:
            return False
        self._relayout()
        return False

    def _relayout(self) -> None:
        if self._applying:
            return
        width = self._host.width()
        if width <= 0:
            return                       # 还没进过布局，此刻的读数不是宿主宽
        self._applying = True
        try:
            self._on_width(width)
        finally:
            self._applying = False
