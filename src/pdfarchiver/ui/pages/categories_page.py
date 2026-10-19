"""S8 分类与标签管理 —— 三栏常驻（甲 · 2026-10-15 定案）。

左栏：分类树（支持增删改名 + 右键改父类/合并）
中栏：标签列表（支持增删改名；`merge_tags` 在产品里仍无入口 —— 记在 **ISSUES I78** 销账那行）
右栏：智能集合（**ISSUES I78** 乙，2026-10-19 补齐"保存筛选条件"那一半）——
每一行写着它此刻命中几份（数由 `documents.count_matching` 出，与回放那张表同一个 WHERE），
**双击 = 把那条集合存的条件灌回 S1 顶栏并立即回放**。

右栏为什么没有「新建」这颗按钮：修前它存的是 `query={}` —— 一条集合等于"全库"，回放它只是
重新显示全部文档，一个改变不了任何读数的入口（**ISSUES I11** 那一类）。存的动作只有一处：
S1 那排 chips 旁边的「存为智能集合」（条件就在那里产生，`ui/collection_bar.py`）。
这一栏留下「复制为新」，它复制的是**已经有条件**的那条。

双击而不是单击：这一栏的三颗按钮都读"当前选中那一行"，单击已经是"点名"了；
把回放挂在单击上，用户每次点选都会跳走一屏。

**1024 档必须收起左栏的树侧栏** —— 这条是 **D-039** 尺寸段点名的界面断言
（「不是"到时候看"」），落地方式是 S1 那一份 `ui/tier.py`：树整块变成 420px 浮层，
原位留一条 48px 的「分类」条。同一把尺子两处用，不各写一遍切档代码。

左分类树的**右键菜单**是 **ISSUES I78** 甲（2026-10-19）补上的：`reparent_category` 与
`merge_categories` 在仓储层早就定义过，但产品里零调用点 —— 于是"改父类"和"合并"这两件事
在界面上不存在，而 §S8 定案写着分类树"支持增删改名**移动**"。右键上那颗「删除（先检查类下
有无文件）」也跟着这一定案：删之前先查整枝，有文件就拒绝并给出清单（§S8 定案的第二条后果）。

数据全部来自 `AppContext.catalog` 与 `AppContext.collection`（集合的三个读数——命中数、
可用性、存/覆盖——都只有服务层给得出，这一页不再直取 `collections` 仓储）。
"""
from __future__ import annotations

from PySide6 import QtCore, QtGui, QtWidgets

from pdfarchiver.services.bootstrap import AppContext
from pdfarchiver.services.collection_service import CollectionEntry
from pdfarchiver.ui.tier import LEFT_COLUMN_WIDTH, FloatablePanel, sync_tier

#: 「放到最外层」在下拉清单里的那一行的载荷。分类 id 由 sqlite 自增、从 1 起，
#: 所以负数可以当"没有父亲"用而永不与真 id 相撞 —— 不需要再造一个 `chosen: bool`。
ROOT_LABEL = "（放到最外层）"
ROOT_TARGET = -1

#: 删除前那份"类下还有文件"的清单最多列几行。这是**清单**不是**总数**（§S8 定案要的是给人
#: 看一眼是什么文件），所以多出来的只说"还有更多"，不编一个总数。
DELETE_PREVIEW_ROWS = 12


class CategoriesPage(QtWidgets.QWidget):
    """S8：三栏常驻；窄档按 D-039 收起分类树。"""

    #: 双击一条集合 → 外壳把 S1 换到这一屏并回放这份条件（载荷是 `CollectionEntry` 整条，
    #: 与 `LibraryPage.open_in_reader` 同一做法：页面不知道外壳的存在，外壳也不懂集合）。
    play_requested = QtCore.Signal(object)

    def __init__(self, ctx: AppContext, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.ctx = ctx

        splitter = QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal)
        self.splitter = splitter

        # 左栏：分类树。树下面的三颗按钮（新建/改名/删除）在浮层里跟着树一起收 ——
        # 若只把树收起来而把编辑按钮留在页面上，1024 档这一屏就变成"能改看不见"。
        self.tree_panel = FloatablePanel(self, "分类树",
                                        column_width=LEFT_COLUMN_WIDTH, strip_label="分类")
        self.category_tree = QtWidgets.QTreeWidget()
        self.category_tree.setHeaderHidden(True)
        # 右键菜单 = 「改父类… / 与…合并…」这两个动作的唯一入口（**ISSUES I78** 甲）。
        # 不放按钮：树下面那一排已经三颗（新建/改名/删除），再加三颗在 236px 的定宽栏里
        # 会换行成两排，而这三个动作只在"选中了某一枝"时才有意义 —— 右键的语义正好是它。
        self.category_tree.setContextMenuPolicy(QtCore.Qt.ContextMenuPolicy.CustomContextMenu)
        self.category_tree.customContextMenuRequested.connect(self._show_category_menu)
        self.tree_panel.body.addWidget(self.category_tree, 1)
        cat_btns = QtWidgets.QHBoxLayout()
        self.add_cat_btn = QtWidgets.QPushButton("新建")
        self.add_cat_btn.clicked.connect(self.add_category)
        self.rename_cat_btn = QtWidgets.QPushButton("改名")
        self.rename_cat_btn.clicked.connect(self.rename_category)
        self.delete_cat_btn = QtWidgets.QPushButton("删除")
        self.delete_cat_btn.clicked.connect(self.delete_category)
        cat_btns.addWidget(self.add_cat_btn)
        cat_btns.addWidget(self.rename_cat_btn)
        cat_btns.addWidget(self.delete_cat_btn)
        self.tree_panel.body.addLayout(cat_btns)
        self.tree_panel.attach(splitter)

        # 中栏：标签列表
        center = QtWidgets.QWidget()
        center_lay = QtWidgets.QVBoxLayout(center)
        center_lay.setContentsMargins(8, 8, 8, 8)
        tag_title = QtWidgets.QLabel("标签")
        tag_title.setObjectName("sectionTitle")
        center_lay.addWidget(tag_title)
        self.tag_list = QtWidgets.QListWidget()
        center_lay.addWidget(self.tag_list, 1)
        tag_btns = QtWidgets.QHBoxLayout()
        self.add_tag_btn = QtWidgets.QPushButton("新建")
        self.add_tag_btn.clicked.connect(self.add_tag)
        self.rename_tag_btn = QtWidgets.QPushButton("改名")
        self.rename_tag_btn.clicked.connect(self.rename_tag)
        self.delete_tag_btn = QtWidgets.QPushButton("删除")
        self.delete_tag_btn.clicked.connect(self.delete_tag)
        tag_btns.addWidget(self.add_tag_btn)
        tag_btns.addWidget(self.rename_tag_btn)
        tag_btns.addWidget(self.delete_tag_btn)
        center_lay.addLayout(tag_btns)
        splitter.addWidget(center)

        # 右栏：智能集合
        right = QtWidgets.QWidget()
        right_lay = QtWidgets.QVBoxLayout(right)
        right_lay.setContentsMargins(8, 8, 8, 8)
        coll_title = QtWidgets.QLabel("智能集合")
        coll_title.setObjectName("sectionTitle")
        right_lay.addWidget(coll_title)
        self.collection_list = QtWidgets.QListWidget()
        self.collection_list.itemDoubleClicked.connect(self._on_collection_activated)
        right_lay.addWidget(self.collection_list, 1)
        coll_btns = QtWidgets.QHBoxLayout()
        self.rename_coll_btn = QtWidgets.QPushButton("改名")
        self.rename_coll_btn.clicked.connect(self.rename_collection)
        self.copy_coll_btn = QtWidgets.QPushButton("复制为新")
        self.copy_coll_btn.clicked.connect(self.copy_collection)
        self.delete_coll_btn = QtWidgets.QPushButton("删除（不动文档）")
        self.delete_coll_btn.setToolTip("只删这一行保存的查询；文档与它们的分类/标签关联一条不动（SPEC 3.3.5）")
        self.delete_coll_btn.clicked.connect(self.delete_collection)
        coll_btns.addWidget(self.rename_coll_btn)
        coll_btns.addWidget(self.copy_coll_btn)
        coll_btns.addWidget(self.delete_coll_btn)
        right_lay.addLayout(coll_btns)
        splitter.addWidget(right)

        self._panels = [self.tree_panel]
        # 宽档的树按 D-039/D-040 同一把尺子取 236px 定宽（`_tier_sizes` 在切档时推），
        # 拖窗口时该长的是标签与集合两栏（条是 fixedWidth、浮层定宽，默认 stretch 0）。
        splitter.setStretchFactor(splitter.indexOf(center), 1)
        splitter.setStretchFactor(splitter.indexOf(right), 1)

        main_lay = QtWidgets.QVBoxLayout(self)
        main_lay.setContentsMargins(0, 0, 0, 0)
        main_lay.addWidget(splitter)

        self.reload()

    def resizeEvent(self, event: QtGui.QResizeEvent) -> None:  # noqa: N802 - Qt 命名
        super().resizeEvent(event)
        sync_tier(self.splitter, self._panels, self.width())

    def reload(self) -> None:
        """重查三栏数据。"""
        self._reload_categories()
        self._reload_tags()
        self._reload_collections()

    def _reload_categories(self) -> None:
        self.category_tree.clear()
        tree = self.ctx.catalog.category_tree()
        items_by_path: dict[str, QtWidgets.QTreeWidgetItem] = {}
        for cat, depth in tree:
            item = QtWidgets.QTreeWidgetItem([cat.name])
            item.setData(0, QtCore.Qt.ItemDataRole.UserRole, cat.id)
            if depth == 0:
                self.category_tree.addTopLevelItem(item)
            else:
                parent_path = cat.name_path.rsplit("/", 1)[0]
                parent_item = items_by_path.get(parent_path)
                if parent_item:
                    parent_item.addChild(item)
            items_by_path[cat.name_path] = item
        self.category_tree.expandAll()

    def _reload_tags(self) -> None:
        self.tag_list.clear()
        for tag in self.ctx.catalog.list_tags():
            self.tag_list.addItem(tag.name)

    def _reload_collections(self) -> None:
        """整列重查：每一行带着**它自己那条** `CollectionEntry`（不是行号）。

        行号当句柄会错位在"列表刚重排过"那一刻 —— 三颗按钮与双击都读"当前那一行"，
        而 `entries()` 每次都重新查库，所以把条目本身塞进 `UserRole`，读的时候直接取，
        不靠"第几行等于第几条"这个临时前提。上屏那句由 `label()` 出（**ISSUES I60**）。
        """
        self.collection_list.clear()
        for entry in self.ctx.collection.entries():
            item = QtWidgets.QListWidgetItem(entry.label())
            item.setData(QtCore.Qt.ItemDataRole.UserRole, entry)
            self.collection_list.addItem(item)

    # ---- 右键菜单（**ISSUES I78** 甲：改父类 / 合并 的唯一入口）----

    def category_menu(self, item: QtWidgets.QTreeWidgetItem) -> QtWidgets.QMenu:
        """造这一枝的右键菜单。**菜单动作的标题从这里出，不许在别处再抄一遍** ——
        p9 注入 I<n> 里「菜单上少一项」要能让断言变红，两处各写一份就注不成。

        菜单上**没有**「导出此分类清单…」：那是 **ISSUES I78** 丙（轮 D），现在加上去
        就是一颗点了没反应的菜单项。
        """
        name = item.text(0)
        menu = QtWidgets.QMenu(self)
        for title, slot in (
            ("改名…", self.rename_category),
            ("改父类…", self.reparent_category),
            (f"与…合并「{name}」", self.merge_category),
            ("", None),
            ("删除（先检查类下有无文件）", self.delete_category),
        ):
            if slot is None:
                menu.addSeparator()
                continue
            menu.addAction(title).triggered.connect(slot)
        return menu

    def _show_category_menu(self, pos: QtCore.QPoint) -> None:
        item = self.category_tree.itemAt(pos)
        if item is None:
            return
        # 菜单动作全部读 `currentItem()`，所以右键先要把选中挪过去 ——
        # 否则"在 A 上右键、执行了 B"这种错位会一直留在界面上。
        self.category_tree.setCurrentItem(item)
        self.category_menu(item).exec(self.category_tree.mapToGlobal(pos))

    def _pick_category(self, title: str, prompt: str, *, exclude_id: int,
                       allow_root: bool) -> int | None:
        """让人从"除自己以外的全部分类"里挑一个，返回它的 id（取消返回 None）。

        `exclude_id` 是**被操作的那一枝自己**：把自己当新父亲 / 并进自己，仓储层会当场拒
        （`reparent_category` 的成环检查），但那一拒的原文是 `分类不存在` 一类的技术话术，
        不如一开始就不给这一项。子孙**不**排除 —— 「把父亲挪到自己的一级子下面」是最常见的
        手滑，那条由仓储层拒，UI 不重算一遍树（口径只有一个，见 `reparent_category` 的注释）。

        `ROOT_TARGET` 是「放到最外层」的载荷；真分类 id 由 sqlite 自增、从 1 起，两者不会撞。
        """
        choices: list[tuple[int | None, str]] = []
        if allow_root:
            choices.append((None, ROOT_LABEL))
        choices += [(c.id, c.name_path) for c in self.ctx.catalog.list_categories()
                    if c.id != exclude_id]
        if not choices:
            QtWidgets.QMessageBox.information(self, title, "没有可放的分类")
            return None
        labels = [label for _, label in choices]
        label, ok = QtWidgets.QInputDialog.getItem(self, title, prompt, labels, 0, False)
        if not ok:
            return None
        picked = choices[labels.index(label)][0]
        return ROOT_TARGET if picked is None else picked

    def _current_category_id(self, action: str) -> int | None:
        """树上当前选中的分类 id；没选中就回一句提示并返回 None。

        改名 / 改父类 / 合并 / 删除 四件事都只在"选中了某一枝"时才有意义，同一条前置检查
        只写这一处（AGENTS.md「禁止同类问题逐个打补丁」）。
        """
        item = self.category_tree.currentItem()
        if item is None:
            QtWidgets.QMessageBox.information(self, action, f"请先选择一个分类再{action}")
            return None
        return item.data(0, QtCore.Qt.ItemDataRole.UserRole)

    def add_category(self) -> None:
        name, ok = QtWidgets.QInputDialog.getText(self, "新建分类", "分类名:")
        if ok and name.strip():
            selected = self.category_tree.currentItem()
            parent_id = selected.data(0, QtCore.Qt.ItemDataRole.UserRole) if selected else None
            try:
                self.ctx.catalog.add_category(name.strip(), parent_id=parent_id)
                self._reload_categories()
            except Exception as exc:
                QtWidgets.QMessageBox.critical(self, "新建分类失败", str(exc))

    def rename_category(self) -> None:
        cat_id = self._current_category_id("改名")
        if cat_id is None:
            return
        new_name, ok = QtWidgets.QInputDialog.getText(self, "改名分类", "新名称:")
        if ok and new_name.strip():
            try:
                self.ctx.catalog.rename_category(cat_id, new_name.strip())
                self._reload_categories()
            except Exception as exc:
                QtWidgets.QMessageBox.critical(self, "改名分类失败", str(exc))

    def reparent_category(self) -> None:
        """改父类（**ISSUES I78** 甲）：整枝挪走，子孙的 `name_path` 由仓储层一条规则跟着改。"""
        cat_id = self._current_category_id("改父类")
        if cat_id is None:
            return
        target_id = self._pick_category("改父类", "放到哪个分类下:",
                                        exclude_id=cat_id, allow_root=True)
        if target_id is None:
            return
        try:
            self.ctx.catalog.reparent_category(cat_id, None if target_id == ROOT_TARGET else target_id)
            self._reload_categories()
        except Exception as exc:
            QtWidgets.QMessageBox.critical(self, "改父类失败", str(exc))

    def merge_category(self) -> None:
        """把当前整枝并进另一个分类（**ISSUES I78** 甲）。

        「并进哪一枝」是让人自己点的，不是"同名自动并"，所以这里不需要重名检查；
        「源整枝不能是自己的子孙」由 `merge_categories` 仓储层拒（口径只有一个）。
        """
        cat_id = self._current_category_id("合并")
        if cat_id is None:
            return
        target_id = self._pick_category("合并分类", "把这一整枝并进哪个分类:",
                                        exclude_id=cat_id, allow_root=False)
        if target_id is None:
            return
        try:
            moved = self.ctx.catalog.merge_categories(cat_id, target_id)
        except Exception as exc:
            QtWidgets.QMessageBox.critical(self, "合并分类失败", str(exc))
            return
        self._reload_categories()
        QtWidgets.QMessageBox.information(
            self, "合并分类", f"已并过去 · 移动 {moved} 份文档的分类关联")

    def delete_category(self) -> None:
        """删除这一整枝 —— 但**先检查类下有无文件，有则拒绝并给清单**（§S8 定案的后果）。

        拒人不删，是因为 `document_categories` 的两条外键是 `ON DELETE CASCADE`：删掉分类
        就把这些文档的"归入"抹掉了，而文档本身还在库里 —— 从界面看等同于"文件丢了分类"，
        而这正是 §S8 定案要拦的那一步。
        出路只写一条真实的：右键「与…合并…」把整枝的关联挪走。「归入分类」是**加**不减，
        所以它不能把这一枝清空，指它等于指一条走不通的路。
        """
        cat_id = self._current_category_id("删除")
        if cat_id is None:
            return
        try:
            docs = self.ctx.catalog.docs_in_subtree(cat_id, limit=DELETE_PREVIEW_ROWS + 1)
        except Exception as exc:
            QtWidgets.QMessageBox.critical(self, "删除分类失败", str(exc))
            return
        if docs:
            lines = [name for _, name in docs[:DELETE_PREVIEW_ROWS]]
            if len(docs) > DELETE_PREVIEW_ROWS:
                lines.append("…还有更多")
            QtWidgets.QMessageBox.warning(
                self, "无法删除分类",
                "这一枝（含子分类）名下还有文件，按定案拒绝删除。\n\n"
                + "\n".join(lines)
                + "\n\n先用右键「与…合并…」把这些文档并进别的分类，再回来删。")
            return
        reply = QtWidgets.QMessageBox.question(
            self, "删除分类",
            "确定要删除这个分类及其所有子分类吗？",
            QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No)
        if reply == QtWidgets.QMessageBox.StandardButton.Yes:
            try:
                self.ctx.catalog.delete_category(cat_id)
                self._reload_categories()
            except Exception as exc:
                QtWidgets.QMessageBox.critical(self, "删除分类失败", str(exc))

    def add_tag(self) -> None:
        name, ok = QtWidgets.QInputDialog.getText(self, "新建标签", "标签名:")
        if ok and name.strip():
            try:
                self.ctx.catalog.add_tag(name.strip())
                self._reload_tags()
            except Exception as exc:
                QtWidgets.QMessageBox.critical(self, "新建标签失败", str(exc))

    def rename_tag(self) -> None:
        selected = self.tag_list.currentRow()
        if selected < 0:
            QtWidgets.QMessageBox.information(self, "改名标签", "请先选择一个标签")
            return
        tags = self.ctx.catalog.list_tags()
        tag = tags[selected]
        new_name, ok = QtWidgets.QInputDialog.getText(self, "改名标签", "新名称:")
        if ok and new_name.strip():
            try:
                self.ctx.catalog.rename_tag(tag.id, new_name.strip())
                self._reload_tags()
            except Exception as exc:
                QtWidgets.QMessageBox.critical(self, "改名标签失败", str(exc))

    def delete_tag(self) -> None:
        selected = self.tag_list.currentRow()
        if selected < 0:
            QtWidgets.QMessageBox.information(self, "删除标签", "请先选择一个标签")
            return
        tags = self.ctx.catalog.list_tags()
        tag = tags[selected]
        reply = QtWidgets.QMessageBox.question(
            self, "删除标签",
            f"确定要删除标签「{tag.name}」吗？\n关联的文档标签也会被删除。",
            QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No)
        if reply == QtWidgets.QMessageBox.StandardButton.Yes:
            try:
                self.ctx.catalog.delete_tag(tag.id)
                self._reload_tags()
            except Exception as exc:
                QtWidgets.QMessageBox.critical(self, "删除标签失败", str(exc))

    # ---- 智能集合（**ISSUES I78** 乙：这一栏只改名 / 复制 / 删除，存的条件在 S1 产生）----

    def _current_collection(self, action: str) -> CollectionEntry | None:
        """当前那一行存的条目；没选中就回一句提示并返回 None。

        改名 / 复制 / 删除 / 双击回放 四件事都只在"选中了某一行"时才有意义，同一条前置检查
        只写这一处（与 `_current_category_id` 同一条纪律，AGENTS.md「禁止同类问题逐个打补丁」）。
        """
        item = self.collection_list.currentItem()
        if item is None:
            QtWidgets.QMessageBox.information(self, action, f"请先选择一个集合再{action}")
            return None
        entry = item.data(QtCore.Qt.ItemDataRole.UserRole)
        return entry if isinstance(entry, CollectionEntry) else None

    def _on_collection_activated(self, item: QtWidgets.QListWidgetItem) -> None:
        """双击一行 → 让外壳切到 S1 并回放这条集合存的条件。

        无条件为假的那条（旧版「新建」留下的 `query={}`）照旧发信号：S1 会把它显示成
        「无筛选条件」那一句，而不是在这儿拦下来 —— 拦在页面上就等于"点了没反应"。
        """
        entry = item.data(QtCore.Qt.ItemDataRole.UserRole)
        if isinstance(entry, CollectionEntry):
            self.play_requested.emit(entry)

    def rename_collection(self) -> None:
        entry = self._current_collection("改名")
        if entry is None:
            return
        new_name, ok = QtWidgets.QInputDialog.getText(self, "改名集合", "新名称:", text=entry.name)
        if ok and new_name.strip():
            try:
                self.ctx.collection.rename(entry.id, new_name.strip())
                self._reload_collections()
            except Exception as exc:
                QtWidgets.QMessageBox.critical(self, "改名集合失败", str(exc))

    def copy_collection(self) -> None:
        """把这一条存的条件原样复制成一条新集合（名字必须现取 —— 重名由仓储层拒）。"""
        entry = self._current_collection("复制为新")
        if entry is None:
            return
        new_name, ok = QtWidgets.QInputDialog.getText(
            self, "复制为新集合", "新集合名:", text=f"{entry.name} 的副本")
        if not ok or not new_name.strip():
            return
        try:
            self.ctx.collection.copy_as_new(entry.id, new_name.strip())
            self._reload_collections()
        except Exception as exc:
            QtWidgets.QMessageBox.critical(self, "复制为新失败", str(exc))

    def delete_collection(self) -> None:
        entry = self._current_collection("删除")
        if entry is None:
            return
        reply = QtWidgets.QMessageBox.question(
            self, "删除集合",
            f"确定要删除智能集合「{entry.name}」吗？\n\n只删这一行保存的查询，"
            "文档和它们的分类/标签关联一条不动。",
            QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No)
        if reply == QtWidgets.QMessageBox.StandardButton.Yes:
            try:
                self.ctx.collection.delete(entry.id)
                self._reload_collections()
            except Exception as exc:
                QtWidgets.QMessageBox.critical(self, "删除集合失败", str(exc))
