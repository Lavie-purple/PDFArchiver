"""S1 表格底下那一排「归入分类 / 加标签 / 移除标签」—— **ISSUES I78** 甲（2026-10-19）。

SPEC 阶段 3 那两条验收（「分类和标签能够持久化」「智能集合可根据保存的查询条件返回真实结果」）
在**产品路径上**做不到，是因为 `CatalogRepository.link_*` 三条写方法在 `src/` 下零调用点：
用户能建分类、建标签，却没有任何一处能把一份文档归进去。这一排按钮就是那"一处"。

形状取线框 `docs/wireframes/2026-10-19-round14-i67-i78.html` §I78-jia（2026-10-19 勾甲）：
工具栏按钮 + 就地展开的目标清单，用 `QPushButton.setMenu` 实现 —— Qt 自己画那枚 ▾，
所以按钮文本不带 ▾（带就是两枚箭头）。

四条不是偏好而是后果的约定：
- **id 只走 `QAction.setData`**。回调要是从标题里解析 id，那么在 S8 改过一次名之后，
  界面就会把「合同」写到别的分类上 —— 名字给人看，id 给机器。
- **每次展开重取清单**。分类与标签的字典在 S8 能增删改名；菜单建一次就固化，用户新建一个
  分类回到 S1 看不到它，那又是 **ISSUES I80** 那一类"界面宣称它会做它不做的事"。
- **回执那句逐字来自 `LinkReceipt.describe()`**（**ISSUES I60**：格式化只有后端一个出口）。
  界面不许自己数"新增了几条"—— 那是 `document_categories` 表里的事，只有写它的地方数得准。
- **不弹详情浮层**：这三颗按钮的结果已经在状态栏那一条上（与选中一行看详情是两件事），
  窄档再顺手把浮层掀起来会把用户刚看清的表格盖掉。
"""
from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Protocol

from PySide6 import QtWidgets

from pdfarchiver.services.bootstrap import AppContext

#: `(后端 id, 显示名, 层级)`。层级只给分类树用（标签恒 0），缩进用**全角空格**：
#: 半角空格在菜单项里会被字距吃掉、两档字体下的层级不一致。
Entry = tuple[int, str, int]

INDENT = "　"


class Receipt(Protocol):
    """这一排按钮对"回执"只提一个要求：`describe()` 给出一句能直接上屏的话。

    真身在 `db/repositories/catalog.py` 的 `LinkReceipt`（**ISSUES I60**：格式化只有后端一个出口），
    这里写成协议而不是 import —— ui 层禁止依赖 db 层。
    """

    def describe(self) -> str: ...


class CatalogLinkBar(QtWidgets.QWidget):
    """三颗按钮 + 它们的目标菜单；表格的选中态与状态栏都由宿主页面递进来。"""

    def __init__(self, ctx: AppContext, *, selected_ids: Callable[[], list[int]],
                 set_status: Callable[..., None], on_written: Callable[[list[int]], None],
                 parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.ctx = ctx
        self._selected_ids = selected_ids
        self._set_status = set_status
        self._on_written = on_written

        lay = QtWidgets.QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.link_category_btn = self._button(
            "归入分类", "把选中的这几份归进一个分类（只加关联，不动它们在别的分类里的行）",
            self._category_entries, "已在的不会重复加", self._on_link_category)
        self.link_tag_btn = self._button(
            "加标签", "给选中的这几份打上一个标签",
            self._tag_entries, "已有的不会重复打", self._on_link_tag)
        self.unlink_tag_btn = self._button(
            "移除标签", "从选中的这几份上摘掉一个标签（别的标签一条不动）",
            self._tag_entries, "只摘这一个", self._on_unlink_tag)
        for btn in (self.link_category_btn, self.link_tag_btn, self.unlink_tag_btn):
            lay.addWidget(btn)
        lay.addStretch(1)
        self.refresh_enabled()

    def _button(self, text: str, tip: str, entries: Callable[[], list[Entry]],
                note: str, on_triggered) -> QtWidgets.QPushButton:
        btn = QtWidgets.QPushButton(text)
        btn.setObjectName("searchBtn")
        btn.setToolTip(tip)
        btn.setEnabled(False)        # 没有点名对象就不许点得动（**ISSUES I74** 三件套同一条）
        btn.setMenu(_link_menu(f"{text}", note, entries, btn))
        btn.menu().triggered.connect(on_triggered)
        return btn

    def refresh_enabled(self) -> None:
        """选中态变了就重算：有点名对象才亮。"""
        on = bool(self._selected_ids())
        for btn in (self.link_category_btn, self.link_tag_btn, self.unlink_tag_btn):
            btn.setEnabled(on)

    def _category_entries(self) -> list[Entry]:
        return [(c.id, c.name, c.name_path.count("/"))
                for c in self.ctx.catalog.list_categories()]

    def _tag_entries(self) -> list[Entry]:
        return [(t.id, t.name, 0) for t in self.ctx.catalog.list_tags()]

    def _on_link_category(self, action: QtWidgets.QAction) -> None:
        self._write(self.ctx.catalog.link_categories, action.data(), "归入分类失败")

    def _on_link_tag(self, action: QtWidgets.QAction) -> None:
        self._write(self.ctx.catalog.link_tags, action.data(), "加标签失败")

    def _on_unlink_tag(self, action: QtWidgets.QAction) -> None:
        self._write(self.ctx.catalog.unlink_tags, action.data(), "移除标签失败")

    def _write(self, write: Callable[[Iterable[int], int], "Receipt"],
               target_id: int | None, fail_note: str) -> None:
        """一次点击 = 仓储层一个事务；屏幕上那句就是它给的回执，失败时给后端原文（**ISSUES I84** ③）。

        `Receipt` 是 `db.repositories.catalog.LinkReceipt` 的窄协议，不是 import：
        ui 层禁止 import db 层（`tests/guards/test_architecture.py` 的 `FORBIDDEN_IMPORTS["ui"]`），
        而这里用到的只有 `.describe()` 这一个方法。
        """
        ids = self._selected_ids()
        if target_id is None or not ids:
            return
        try:
            receipt = write(ids, target_id)
        except Exception as exc:
            self._set_status(f"{fail_note}：{exc}", danger=True)
            return
        # `changed == 0` 不染红（与「送去识别」那条不同）：幂等写入"一条都没新增"是因为
        # **状态本来就已经对了**，不是失败；那句回执里「原本已在 N 份」已经把这件事写在屏幕上。
        self._set_status(receipt.describe())
        self._on_written(list(ids))


def _link_menu(title: str, note: str, entries: Callable[[], list[Entry]],
               parent: QtWidgets.QWidget) -> QtWidgets.QMenu:
    menu = QtWidgets.QMenu(parent)
    menu.aboutToShow.connect(lambda: _fill_menu(menu, title, note, entries()))
    return menu


def _fill_menu(menu: QtWidgets.QMenu, title: str, note: str, items: list[Entry]) -> None:
    menu.clear()
    head = menu.addAction(f"{title} · {note}")
    head.setEnabled(False)          # 说明行不是目标：禁用之后它不会触发一次写入
    if not items:
        empty = menu.addAction("（清单是空的，先去「分类与标签」建一个）")
        empty.setEnabled(False)
        return
    for target_id, name, depth in items:
        action = menu.addAction(INDENT * depth + name)
        action.setData(target_id)
