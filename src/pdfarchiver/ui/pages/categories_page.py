"""S8 分类与标签管理 —— 三栏常驻（甲 · 2026-10-15 定案）。

左栏：分类树（支持增删改名移动）
中栏：标签列表（支持增删改名合并）
右栏：智能集合（支持增删改查）

**1024 档必须收起左栏的树侧栏** —— 这条是 **D-039** 尺寸段点名的界面断言
（「不是"到时候看"」），落地方式是 S1 那一份 `ui/tier.py`：树整块变成 420px 浮层，
原位留一条 48px 的「分类」条。同一把尺子两处用，不各写一遍切档代码。

数据全部来自 `AppContext.catalog` 和 `AppContext.collections` 的真查询。
"""
from __future__ import annotations

from PySide6 import QtCore, QtGui, QtWidgets

from pdfarchiver.services.bootstrap import AppContext
from pdfarchiver.ui.tier import LEFT_COLUMN_WIDTH, FloatablePanel, sync_tier


class CategoriesPage(QtWidgets.QWidget):
    """S8：三栏常驻；窄档按 D-039 收起分类树。"""

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
        right_lay.addWidget(self.collection_list, 1)
        coll_btns = QtWidgets.QHBoxLayout()
        self.add_coll_btn = QtWidgets.QPushButton("新建")
        self.add_coll_btn.clicked.connect(self.add_collection)
        self.rename_coll_btn = QtWidgets.QPushButton("改名")
        self.rename_coll_btn.clicked.connect(self.rename_collection)
        self.delete_coll_btn = QtWidgets.QPushButton("删除")
        self.delete_coll_btn.clicked.connect(self.delete_collection)
        coll_btns.addWidget(self.add_coll_btn)
        coll_btns.addWidget(self.rename_coll_btn)
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
        self.collection_list.clear()
        for coll in self.ctx.collections.list():
            self.collection_list.addItem(coll.name)

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
        selected = self.category_tree.currentItem()
        if not selected:
            QtWidgets.QMessageBox.information(self, "改名分类", "请先选择一个分类")
            return
        cat_id = selected.data(0, QtCore.Qt.ItemDataRole.UserRole)
        new_name, ok = QtWidgets.QInputDialog.getText(self, "改名分类", "新名称:")
        if ok and new_name.strip():
            try:
                self.ctx.catalog.rename_category(cat_id, new_name.strip())
                self._reload_categories()
            except Exception as exc:
                QtWidgets.QMessageBox.critical(self, "改名分类失败", str(exc))

    def delete_category(self) -> None:
        selected = self.category_tree.currentItem()
        if not selected:
            QtWidgets.QMessageBox.information(self, "删除分类", "请先选择一个分类")
            return
        cat_id = selected.data(0, QtCore.Qt.ItemDataRole.UserRole)
        reply = QtWidgets.QMessageBox.question(
            self, "删除分类",
            "确定要删除这个分类及其所有子分类吗？\n关联的文档分类也会被删除。",
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

    def add_collection(self) -> None:
        name, ok = QtWidgets.QInputDialog.getText(self, "新建智能集合", "集合名:")
        if ok and name.strip():
            try:
                # 默认查询条件：空查询（匹配所有文档）
                self.ctx.collections.add(name.strip(), query={})
                self._reload_collections()
            except Exception as exc:
                QtWidgets.QMessageBox.critical(self, "新建集合失败", str(exc))

    def rename_collection(self) -> None:
        selected = self.collection_list.currentRow()
        if selected < 0:
            QtWidgets.QMessageBox.information(self, "改名集合", "请先选择一个集合")
            return
        colls = self.ctx.collections.list()
        coll = colls[selected]
        new_name, ok = QtWidgets.QInputDialog.getText(self, "改名集合", "新名称:")
        if ok and new_name.strip():
            try:
                self.ctx.collections.rename(coll.id, new_name.strip())
                self._reload_collections()
            except Exception as exc:
                QtWidgets.QMessageBox.critical(self, "改名集合失败", str(exc))

    def delete_collection(self) -> None:
        selected = self.collection_list.currentRow()
        if selected < 0:
            QtWidgets.QMessageBox.information(self, "删除集合", "请先选择一个集合")
            return
        colls = self.ctx.collections.list()
        coll = colls[selected]
        reply = QtWidgets.QMessageBox.question(
            self, "删除集合",
            f"确定要删除智能集合「{coll.name}」吗？",
            QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No)
        if reply == QtWidgets.QMessageBox.StandardButton.Yes:
            try:
                self.ctx.collections.delete(coll.id)
                self._reload_collections()
            except Exception as exc:
                QtWidgets.QMessageBox.critical(self, "删除集合失败", str(exc))
