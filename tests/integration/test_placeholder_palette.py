"""占位色接线守卫（**ISSUES I50** 乙，2026-10-17）。

`tests/unit/test_theme_contrast.py` 量的是**令牌之间**的对比度 —— 它证明 `text_secondary`
压在 `input_bg` 上是 4.69:1 / 5.71:1，但**证明不了这个值真的落到了屏上**。这两件事必须分开
才有牙：上一轮就是因为 QSS 里写着一条 `QLineEdit::placeholder { color: #adb5bd }`，读代码的
人以为占位色已经有了，而它渲染回来是 0 个红像素（**ISSUES I49**）。

三条断言，各自对应的坏法不同：
① 每个能显示占位文字的控件都拿到了 role —— 坏法：删掉 `main_window` 里任一处
   `apply_palette` 调用。页面是**惰性创建**的，启动时那次遍历不到还没建出来的页，
   所以「建页时补设」这一处漏掉就会有一屏没占位色；`QPlainTextEdit` 那类
   `QAbstractScrollArea` 少设 viewport 一份，也在这里红（实测：控件自身那份一个
   事件循环就被样式表重解析抹回 `#212529`）。
② 切主题后 role 跟着换 —— 坏法：`_toggle_theme` 只重设 QSS 不重设调色板。
③ QSS 里不许再有 placeholder 规则 —— 坏法：把那条死选择器加回来，代码看着「两处都写了」，
   实际只有调色板那份生效，另一份是永不自检的假声明。
"""
from __future__ import annotations

import re

import pytest
from PySide6 import QtGui, QtWidgets

from pdfarchiver.ui.nav import NAV_ITEMS
from pdfarchiver.ui.theme import ThemeManager

#: 与 `ThemeManager.PLACEHOLDER_WIDGETS` 同一组类型 —— 遍历口径不许比实现窄。
CAPABLE = (QtWidgets.QLineEdit, QtWidgets.QPlainTextEdit, QtWidgets.QTextEdit)


@pytest.fixture
def window(qapp, ctx):
    from pdfarchiver.ui.main_window import MainWindow

    w = MainWindow(ctx, cold_start_seconds=0.42)
    w.show()
    # 逐屏切一遍：页面是 `_on_nav_changed` 里惰性建的，不切就遍历不到
    for row, item in enumerate(NAV_ITEMS):
        if item.implemented:
            w.nav.setCurrentRow(row)
            QtWidgets.QApplication.processEvents()
    yield w
    w.close()
    ctx.shutdown()


def _capable_widgets(win: QtWidgets.QMainWindow) -> list[QtWidgets.QWidget]:
    found: list[QtWidgets.QWidget] = []
    for kind in CAPABLE:
        found.extend(win.findChildren(kind))
    return found


def _placeholder_color(widget: QtWidgets.QWidget) -> str:
    """读**实现写进去的那一份**调色板。

    `QPlainTextEdit` / `QTextEdit` 是 `QAbstractScrollArea`：设在控件自身的那份一个事件循环
    就被 Qt 按样式表重解析抹回 `#212529`（微探针实测），真正落屏的是 viewport 那一份 ——
    读错地方这条守卫就是假的。
    """
    sink = (widget.viewport() if isinstance(widget, QtWidgets.QAbstractScrollArea)
            else widget)
    role = QtGui.QPalette.ColorRole.PlaceholderText
    return sink.palette().color(role).name().lower()


def test_每个可显示占位文字的控件都拿到主题的占位色(window) -> None:
    # 必须过一遍事件循环再读：不设 viewport 的坏法在「设了立刻读」时是绿的，
    # 到下一次重解析才掉回 `#212529`。
    QtWidgets.QApplication.processEvents()
    widgets = _capable_widgets(window)
    # 判据退化守卫：遍历口径写错（比如忘了 QPlainTextEdit）时这里会变空，
    # 而「空列表全部满足」是假绿，所以先要求真的数到了东西。
    assert len(widgets) >= 5, f"只认出 {len(widgets)} 个可显示占位文字的控件，守卫已失效"
    token = window.theme.colors.text_secondary.lower()
    wrong = [f"{type(w).__name__}({w.objectName()}) = {_placeholder_color(w)}"
             for w in widgets if _placeholder_color(w) != token]
    assert not wrong, (
        f"有 {len(wrong)} 个控件的占位色不是主题令牌 {token}（不设时 Qt 拿正文字色按 "
        "50% alpha 混，浅色实测 3.12:1 / 暗色 4.09:1，都不过 AA）：\n  " + "\n  ".join(wrong))


def test_切主题之后占位色跟着换(window) -> None:
    """暗色下不重设 role = 浅色主题那个灰压在暗输入框上，对比度整条作废。"""
    started = window.theme.theme
    window._toggle_theme()
    assert window.theme.theme != started
    test_每个可显示占位文字的控件都拿到主题的占位色(window)


def test_QSS里不许再出现placeholder规则(window) -> None:
    """`QLineEdit::placeholder {}` 是死选择器：填纯红 `#ff0000` 渲染回来 0 个红像素。

    留着它的害处不是没用，而是**看起来像已经修过了** —— **ISSUES I49** 里那条
    `#adb5bd`（2.07:1）就这样在代码里躺着，没人知道它从没上过屏。
    """
    for theme in (ThemeManager.LIGHT, ThemeManager.DARK):
        window.theme.set_theme(theme)
        # 注释里那句「`QLineEdit::placeholder` 是死选择器」是**说明**，不是声明；
        # 先把注释剥掉再判，否则守卫会在「解释了为什么不能用它」那段文字上假红。
        qss = re.sub(r"/\*.*?\*/", "", window.theme.generate_qss(), flags=re.S).lower()
        assert "placeholder" not in qss, f"{theme} 主题的 QSS 里又出现了占位规则（死选择器）"
