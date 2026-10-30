"""走查 **⑱**「全站空态规则」（**D-066**）的守卫：一条规则一次核，不是逐屏打补丁。

规则两句在 `src/pdfarchiver/ui/empty_state.py` 的模块 docstring 里（唯一定义处）：

1. 列表类面板（`QListWidget` / `QTreeWidget`）**空着且在场** ⇒ 同一容器里必须有一句
   **看得见的**空态引导；
2. 那句里用「」点名的动作，必须在产品里真有一个入口（按钮文本或导航项标题含它）。

为什么判据这么定：「这句话写得像不像引导」机器判不了，但「空栏旁边有没有一句在场的文案」
与「它指的那个动作找不找得到」都可数。第 2 条与 `test_stage6_copy.py` 的
`test_空态文案不许指向产品里不存在的动作` 同族（**ISSUES I84** ②），那次是逐屏改，这一条
把范围升成全站：新增一屏忘了指路，这里当场红。

`QTableWidget` 不归本条管：那几张表的"这些行是什么"由状态行/说明条回答（S1 的
`_set_status`、S4 的 `loaded_note`、S3 的 `plan_summary`），再叠一句列表式引导就是同一件事
的第二个口径。隐藏的列表也不算（浮层没开时它本来就不在场 —— 与 **D-064** ⑭ 同一形状）。

"下一屏自己再抄四行 `QLabel` + `muted` + `setWordWrap` + `setVisible(count == 0)`"（轮四十二
⑨⑩⑪ 抄过三遍的那个形状）不单独立一条：手抄的那句没有属性，规则 1 扫到时就当它是"空栏没引导"
当场红，同一条判据已经接住 —— 再写一条文件级文本扫描，判据与坏法不是一一对应（合法的
`setObjectName("muted")` 与另一处无关的 `.count() == 0)` 同现一个文件就会假红）。
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

from PySide6 import QtWidgets

from pdfarchiver.ui.empty_state import EMPTY_STATE_PROPERTY, make_hint, row_count
from pdfarchiver.ui.nav import NAV_ITEMS
from tests.conftest import settle as _settle

_SRC_UI = Path(__file__).resolve().parents[2] / "src" / "pdfarchiver" / "ui"
QUOTED = re.compile(r"「([^」]+)」")
LIST_LIKE = (QtWidgets.QListWidget, QtWidgets.QTreeWidget)


def _hints_of(widget) -> list[QtWidgets.QLabel]:
    """同一容器里那几句 ⑱ 引导（靠属性认，不靠措辞）。"""
    host = widget.parentWidget()
    if host is None:
        return []
    return [label for label in host.findChildren(QtWidgets.QLabel)
            if label.property(EMPTY_STATE_PROPERTY) is True]


def _visit_all_pages(window, qapp):
    """逐屏切过去并刷一遍，** yield 的时候这一屏正可见** —— 然后才许量。

    两件事都不能省：页面是惰性构建的，没切过去的屏上还没有控件；而 `QStackedWidget` 里
    隐藏的页 `isVisible()` 恒 False，全部切完再统一扫会一个都扫不到（实测 `checked=0`）。
    """
    for item in NAV_ITEMS:
        window._select_by_page_id(item.page_id)
        _settle(qapp)
        window._refresh_current()
        _settle(qapp)
        yield item, window._pages[item.page_id]


def test_空着的列表面板必有一句在场的引导(window, qapp) -> None:
    """规则 1：开局就是空的栏，不许是一块空框。"""
    misses: list[str] = []
    checked = 0
    for item, page in _visit_all_pages(window, qapp):
        # findChildren 不吃元组（PySide6 只收一个 type），按类型各扫一遍
        for widget in [found for kind in LIST_LIKE for found in page.findChildren(kind)]:
            if not widget.isVisible() or row_count(widget):
                continue          # 不在场的、有内容的都不归这条管
            checked += 1
            if not any(hint.isVisible() for hint in _hints_of(widget)):
                name = next((attr for attr, value in vars(page).items()
                             if value is widget), type(widget).__name__)
                misses.append(f"{item.title}（{item.page_id}）的 `{name}`")
    assert checked >= 3, (
        f"只扫到 {checked} 个空列表（2026-10-30 现数 4：监测根 / 标签 / 集合 / 历史提问）"
        " —— 扫不到就是这条守卫在空转")
    assert not misses, "这些列表面板空着却没有一句引导：" + "、".join(misses)


def test_引导跟着条数走_有内容之后要让位(window, qapp, ctx) -> None:
    """规则 1 的反面：灯不能恒亮。同一个容器里两句引导，一句该灭、一句该留。

    为什么两句一起量：只断言"有了标签就灭"，把 `sync_hint` 写成恒 `setVisible(False)` 也绿；
    同时看邻居（集合还是空的 ⇒ 它那句必须在）才能钉住"跟着**这张列表**的条数走"。
    """
    ctx.catalog.add_tag("守卫用标签")
    window._select_by_page_id("categories")
    _settle(qapp)
    page = window._pages["categories"]
    page.reload()
    _settle(qapp)
    assert page.tag_list.count() > 0, "用例前提：标签得真的进了列表"
    assert not page.tag_hint.isVisible(), "列表已经有内容了，那句「还没有标签」还占着屏"
    assert page.collection_list.count() == 0, "用例前提：这一轮没建过集合"
    assert page.coll_hint.isVisible(), "隔壁那句空着的引导不该被一起灭掉"


def test_引导点名的动作在产品里真存在(window, qapp) -> None:
    """规则 2：`make_hint` 的文案里「」括起来的每一样，界面上得真找得到。

    文案从**源码的字符串常量**取而不是从运行时控件取：运行时的标签文本可能被别的读数改写
    （S9 答案区那句就是随向量读数变的），拿常量核对才是在核"写代码的人指的那条路"。
    """
    # 必须先把每一屏建起来并切过去，`findChildren` 才找得到那些屏上的按钮
    for _item, _page in _visit_all_pages(window, qapp):
        pass
    vocabulary: set[str] = set()
    for button in window.findChildren(QtWidgets.QAbstractButton):
        if button.text().strip():
            vocabulary.add(button.text().strip())
    for item in NAV_ITEMS:
        vocabulary.add(item.title)

    misses: list[str] = []
    scanned = 0
    for path in sorted(_SRC_UI.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id == "make_hint" and node.args):
                continue
            try:
                text = ast.literal_eval(node.args[0])
            except ValueError:          # 文案由变量拼出来的调用点，本条不猜
                continue
            scanned += 1
            for phrase in QUOTED.findall(text):
                if not any(phrase in known for known in vocabulary):
                    misses.append(f"{path.name}:{node.lineno} 指向「{phrase}」")
    assert scanned >= 4, f"只核到 {scanned} 句 `make_hint` 文案，守卫在空转"
    assert not misses, "这些空态引导把人指向界面上不存在的动作：" + "；".join(misses)


def test_make_hint造的控件带着可认的标记(qapp) -> None:
    """属性是守卫与 `sync_hint` 唯一的认法 —— 它掉了，上面几条会一起变成摆设。"""
    host = QtWidgets.QWidget()
    hint = make_hint("还没有东西：点「新建」。", host)
    assert hint.property(EMPTY_STATE_PROPERTY) is True, "属性没挂上，守卫认不出这是空态引导"
    assert hint.objectName() == "muted" and hint.wordWrap(), "样式不再由唯一出口负责了"
    assert hint.parent() is host, "显式挂父是硬要求（PySide6 6.8 不补 reparent，轮三十九）"
