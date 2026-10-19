"""S1 顶栏那一排筛选 chips + 「存为集合」—— **ISSUES I78** 乙（2026-10-19，线框 §I78-yi）。

它替掉的是什么：此前 S1 的筛选条件只有一个来源（点分类树），屏幕上看不见"现在到底筛了些什么"，
也没有任何地方能把这组条件留下来。SPEC 阶段 3 那条「智能集合可根据保存的查询条件返回真实结果」
因此一直做不到 —— `CollectionRepository` 会存 `query_json`，可产品里没有人能*产生*一份条件。

形状与线框的两处差别（都由 §S1 定案的算术决定，不是偏好）：
- 线框把 chips 与三颗按钮画在**同一行**；中栏在窗口 1280 那一档只有 463px（`test_ui_layout` 现测），
  四颗按钮 `minimumSizeHint` 实测吃掉约 390px，chips 只剩 49px = 一枚都放不下。所以拆成两行：
  chips 单独一行（横向可滚，拉伸项是它，按钮不吃它的宽度），动作按钮一行。
- 线框那颗「另存一份」在 S8 已经有同功能的「复制为新」，两处各一份等于两个入口做同一件事
  （AGENTS.md「每加一个新入口，先全站搜是否已有同功能入口」）。这里改成「覆盖此集合」——
  它同时是 `update_query` 在产品里的第一个调用点（硬断言 (e)），而「另存一份」并不需要提供
  第二条改条件的路。

一条不是偏好而是后果的约定：
- **这一条只认 dict，不 import `Criteria`**。`ui` 层禁止 import `search`/`db`
  （`tests/guards/test_architecture.py` 的 `FORBIDDEN_IMPORTS["ui"]`），所以界面上的筛选状态
  就是那份能直接进 `query_json` 的 plain dict —— 读写同源要成立，靠的正是"屏幕上的条件"与
  "存下来的条件"是同一样东西，而不是两份互转。哪些键能出现由 `search.QUERY_FIELDS` 定，
  这一张条件表与它的漂移由 `test_筛选条这张表与集合能存的字段同一批` 钉住。
- **删一枚 chip = 从 dict 里去掉那个键**，不是"置成默认值"。`Criteria.from_query` 对缺键与
  null 一律落回默认（那是它的注释里写明的口径），所以去掉键与"这一条不设条件"是同一件事；
  留着键写 `False`/`null` 会让存进集合的 dict 出现两种写法。
- **`tag_match_all` 没有标签时既不上屏也不留下**。它在库里只在 `tag_ids` 非空时才改变 WHERE，
  一条改变不了任何读数的条件显示在屏幕上，就是 **ISSUES I11** 那一类"界面宣称它会做它不做的事"。
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from PySide6 import QtCore, QtWidgets

from pdfarchiver.services.bootstrap import AppContext
from pdfarchiver.services.collection_service import CollectionEntry, day_end, day_start
from pdfarchiver.services.status_service import format_day
from pdfarchiver.ui.format import format_bytes, parse_size

#: `fts_status` 的取值与中文说法。取值集合由 `db.repositories.documents.SEARCHABLE_STATUSES`
#: 定（界面无从 import），所以这张表**必须与它一字不差**，漂移由单测当场红。
#: 措辞按那一列的语义（文档正文索引推进到哪一步），不写「文字层」—— 那一列管的不是有没有字，
#: 而是这些字进没进倒排。
FTS_LABELS: dict[str, str] = {
    "pending": "待索引",
    "running": "索引中",
    "done": "已索引",
    "failed": "索引失败",
    "stale": "要重索引",
}

_DAY_HELP = "要写成 2026-01-01 这样（年-月-日）"


@dataclass(frozen=True)
class Condition:
    """一枚可添加的条件：菜单上那句、chip 上那句、以及点它时问人什么。"""

    field: str          # `query` 里的那个键名（唯一口径，见 `search.QUERY_FIELDS`）
    menu: str           # 「添加条件」菜单上的文字
    prefix: str         # chip 前缀
    op: str             # chip 里的关系词；`""` = 这条没有值（开关型）
    ask: str            # 取值方式，见 `FilterBar._ask` 的分支
    multi: bool = False  # 值是一串 id：每枚 chip 只删自己那一个


#: 顺序就是菜单顺序，与 `QUERY_FIELDS` 同一批字段（单测钉住，不许两处各自增减）。
CONDITIONS: tuple[Condition, ...] = (
    Condition("category_ids", "分类…", "分类", "=", "category", multi=True),
    Condition("tag_ids", "标签…", "标签", "=", "tag", multi=True),
    Condition("tag_match_all", "标签要全部命中", "标签要全部命中", "", "flag"),
    Condition("root_key", "监测根…", "监测根", "=", "root"),
    Condition("modified_from", "修改时间 从某天起…", "修改时间", "≥", "day_from"),
    Condition("modified_to", "修改时间 到某天止…", "修改时间", "≤", "day_to"),
    Condition("fts_status", "索引状态…", "索引状态", "=", "fts"),
    Condition("min_pages", "页数至少…", "页数", "≥", "pages"),
    Condition("min_size_bytes", "大小至少…", "大小", "≥", "size"),
    Condition("missing_only", "只看磁盘上已缺失", "只看磁盘上已缺失", "", "flag"),
)
BY_FIELD = {c.field: c for c in CONDITIONS}


class FilterBar(QtWidgets.QWidget):
    """chips 的显示与编辑都在这里；取数与翻页在宿主页面 —— 这一条只往外递一份新 dict。"""

    def __init__(self, ctx: AppContext, *, on_query_changed: Callable[[dict], None],
                 set_status: Callable[..., None],
                 parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.ctx = ctx
        self._on_changed = on_query_changed
        self._set_status = set_status
        self._query: dict = {}
        self._saved: CollectionEntry | None = None

        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)

        top = QtWidgets.QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        self.chip_scroll = QtWidgets.QScrollArea()
        self.chip_scroll.setObjectName("chipStrip")
        self.chip_scroll.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        self.chip_scroll.setWidgetResizable(True)
        self.chip_scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.chip_scroll.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.chip_row = QtWidgets.QWidget()
        self._chip_lay = QtWidgets.QHBoxLayout(self.chip_row)
        self._chip_lay.setContentsMargins(0, 0, 0, 0)
        self._chip_lay.setSpacing(6)
        self.chip_scroll.setWidget(self.chip_row)
        top.addWidget(self.chip_scroll, 1)

        self.add_btn = QtWidgets.QPushButton("添加条件")
        self.add_btn.setObjectName("searchBtn")
        self.add_btn.setToolTip("加一条筛选条件；这一排 chips 就是现在筛的东西")
        self.add_btn.setMenu(self._condition_menu())
        top.addWidget(self.add_btn)
        lay.addLayout(top)

        bottom = QtWidgets.QHBoxLayout()
        bottom.setContentsMargins(0, 0, 0, 0)
        self.source_label = QtWidgets.QLabel("")
        self.source_label.setObjectName("muted")
        self.source_label.setWordWrap(False)
        bottom.addWidget(self.source_label, 1)
        self.clear_btn = QtWidgets.QPushButton("清除全部")
        self.clear_btn.setObjectName("clearBtn")
        self.clear_btn.clicked.connect(lambda: self.apply_query({}))
        self.save_btn = QtWidgets.QPushButton("存为智能集合")
        self.save_btn.setObjectName("searchBtn")
        self.save_btn.clicked.connect(self._on_save)
        self.overwrite_btn = QtWidgets.QPushButton("覆盖此集合")
        self.overwrite_btn.setObjectName("searchBtn")
        self.overwrite_btn.clicked.connect(self._on_overwrite)
        for btn in (self.clear_btn, self.save_btn, self.overwrite_btn):
            bottom.addWidget(btn)
        lay.addLayout(bottom)

        self._render()

    # ---- 对外：宿主页面唯一的两个入口 ----

    def apply_query(self, query: dict, *, saved: CollectionEntry | None = None) -> None:
        """换上这一组条件并重画 chips，然后把新 dict 递给宿主（宿主负责重新取数）。

        `saved` 只由「从 S8 点开一个集合」和「存 / 覆盖成功」那两条路给，**省略 = 保持原样**。
        就地改一枚 chip 不许丢掉集合的身份 —— 否则「覆盖此集合」只能在"屏幕上这一排和存进去的
        那份一模一样"时点亮，而那一次覆盖是个空动作；真正要它的「点开集合 → 改条件 → 写回同一条」
        反而按不到（本轮现测就这么红）。改了什么不靠熄灭按钮表达，靠出处那句话（见 `_render`）。
        """
        self._adopt(query, saved=saved)
        self._on_changed(dict(self._query))

    def _adopt(self, query: dict, *, saved: CollectionEntry | None = None) -> None:
        """换状态、重画，但**不**重新取数 —— 存完/覆盖完那一次条件一个字都没变。"""
        self._query = {k: v for k, v in query.items() if not self._is_default(v)}
        if saved is not None:
            self._saved = saved
        self._render()

    def query(self) -> dict:
        return dict(self._query)

    def set_field(self, field: str, value: object) -> None:
        """宿主替用户换掉**某一条**条件（点分类树 = 换掉「分类」那一串），其余 chips 不动。"""
        query = dict(self._query)
        query[field] = value
        self.apply_query(query)

    def drop_field(self, field: str) -> None:
        """去掉某一条条件（分类树的「显示全部」= 去掉「分类」，别的条件留着）。"""
        query = dict(self._query)
        self._without(query, field)
        self.apply_query(query)

    @staticmethod
    def _without(query: dict, field: str) -> None:
        query.pop(field, None)
        if field == "tag_ids":
            # 「标签要全部命中」只能挂在标签上：标签没了还留着它，等于往集合里存一条
            # 屏幕上看不见、却会被带进下一次回放的空条件。
            query.pop("tag_match_all", None)

    def refresh(self) -> None:
        """条件没变、字典变了（S8 改过分类名）之后重画一遍文案。"""
        self._render()

    # ---- chips ----

    @staticmethod
    def _is_default(value: object) -> bool:
        """空串 / 空清单 / None / False 都不算一条条件 —— 与 `Criteria` 的默认值同一判据。"""
        return value is None or value == "" or value == [] or value is False

    def _chips(self) -> list[tuple[Condition, object]]:
        out: list[tuple[Condition, object]] = []
        for cond in CONDITIONS:
            value = self._query.get(cond.field)
            if self._is_default(value):
                continue
            if cond.field == "tag_match_all" and not self._query.get("tag_ids"):
                continue     # 没有标签时它不改任何一行 SQL，见模块 docstring
            if cond.multi:
                out += [(cond, one) for one in value]
            else:
                out.append((cond, value))
        return out

    def _render(self) -> None:
        while self._chip_lay.count():
            item = self._chip_lay.takeAt(0)
            if widget := item.widget():
                widget.deleteLater()
        chips = self._chips()
        if not chips:
            self._chip_lay.addWidget(self._placeholder())
        else:
            for cond, value in chips:
                self._chip_lay.addWidget(self._chip(cond, value))
        self._chip_lay.addStretch(1)
        self.source_label.setText(self._source_text())
        self.save_btn.setEnabled(bool(chips))
        self.overwrite_btn.setEnabled(self._saved is not None and bool(chips))
        for btn, why in ((self.save_btn, "先加至少一条条件，才有一条集合可存"),
                         (self.overwrite_btn, self._overwrite_hint())):
            btn.setToolTip("" if btn.isEnabled() else why)

    def _overwrite_hint(self) -> str:
        if self._saved is None:
            return "只有从「分类与标签 → 智能集合」点开一条集合之后才能覆盖"
        return "先加至少一条条件 —— 覆盖是把屏幕上这一排写回集合，空的一排等于「看全库」"

    def _source_text(self) -> str:
        """出处那一格说两件事：这一排是从哪条集合来的，以及现在还是不是它那一排。"""
        if self._saved is None:
            return "当前条件还没存成集合"
        if self._matches_saved():
            return f"来自集合「{self._saved.name}」"
        return f"来自集合「{self._saved.name}」· 已改动，覆盖才写回"

    def _matches_saved(self) -> bool:
        """屏幕上这一排与存着的那份是不是同一条条件 —— 两份 dict 就地比，不 import `Criteria`。

        存着的那份是 `Criteria.to_query()` 规范化后的**全键** dict，屏幕上的是稀疏的（只留非默认
        值），所以两边先各收成稀疏、再把 list 与 tuple 一视同仁。
        """
        return self._saved is not None and self._sparse(self._saved.query) == self._sparse(
            self._query)

    @staticmethod
    def _sparse(query: dict) -> dict:
        return {k: (list(v) if isinstance(v, (list, tuple)) else v)
                for k, v in query.items() if not FilterBar._is_default(v)}

    def _placeholder(self) -> QtWidgets.QLabel:
        label = QtWidgets.QLabel("（没有筛选条件 · 中栏现在是全库列表）")
        label.setObjectName("muted")
        return label

    def _chip(self, cond: Condition, value: object) -> QtWidgets.QFrame:
        chip = QtWidgets.QFrame()
        chip.setObjectName("filterChip")
        lay = QtWidgets.QHBoxLayout(chip)
        lay.setContentsMargins(6, 0, 2, 0)
        lay.setSpacing(2)
        text = QtWidgets.QLabel(self._chip_text(cond, value))
        text.setObjectName("muted")
        lay.addWidget(text)
        cross = QtWidgets.QToolButton()
        cross.setObjectName("chipRemove")
        cross.setText("×")
        cross.setToolTip("去掉这一条")
        cross.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        cross.clicked.connect(lambda _=False, c=cond, v=value: self._remove(c, v))
        lay.addWidget(cross)
        return chip

    def _chip_text(self, cond: Condition, value: object) -> str:
        if not cond.op:
            return cond.prefix
        return f"{cond.prefix} {cond.op} {self._value_text(cond.field, value)}"

    def _value_text(self, field: str, value: object) -> str:
        if field in ("category_ids", "tag_ids", "root_key"):
            label = self._label_of(field, value)
            return label if label is not None else f"{value}（已不在字典里）"
        if field == "fts_status":
            return FTS_LABELS.get(str(value), f"{value}（不认识的状态）")
        if field in ("modified_from", "modified_to"):
            return format_day(int(value))       # 时间串只有 `status_service.format_day` 一个出口
        if field == "min_size_bytes":
            return format_bytes(int(value))     # 字节口径只有 `ui/format.format_bytes` 一个出口
        return str(value)

    def _label_of(self, field: str, value: object) -> str | None:
        options = dict(self._options(field))
        return options.get(value)

    # ---- 加 / 删 ----

    def _condition_menu(self) -> QtWidgets.QMenu:
        menu = QtWidgets.QMenu(self)
        menu.aboutToShow.connect(lambda: _fill(menu))
        menu.triggered.connect(self._on_menu_pick)
        return menu

    def _on_menu_pick(self, action: QtWidgets.QAction) -> None:
        """菜单认 `setData` 里的字段名，不认标题（与 `ui/catalog_links.py` 同一条约定）。"""
        cond = BY_FIELD.get(str(action.data()))
        if cond is not None:
            self._on_add(cond)

    def _on_add(self, cond: Condition) -> None:
        value = self._ask(cond)
        if value is None:
            return
        query = dict(self._query)
        if cond.multi:
            held = list(query.get(cond.field) or [])
            if value not in held:
                held.append(value)
            query[cond.field] = held
        else:
            query[cond.field] = value
        self.apply_query(query)

    def _remove(self, cond: Condition, value: object) -> None:
        query = dict(self._query)
        if cond.multi:
            held = [one for one in query.get(cond.field) or [] if one != value]
            if held:
                query[cond.field] = held
            else:
                self._without(query, cond.field)
        else:
            self._without(query, cond.field)
        self.apply_query(query)

    def _ask(self, cond: Condition) -> object | None:
        """问出这一条的值；取消返回 None。字段各问各的，所以按 `ask` 分支，不做统一表单。"""
        if cond.ask == "flag":
            return True
        if cond.ask in ("category", "tag", "root", "fts"):
            return self._ask_pick(cond.ask)
        if cond.ask in ("day_from", "day_to"):
            return self._ask_day(cond)
        if cond.ask == "pages":
            return self._ask_pages(cond)
        return self._ask_size(cond)

    def _ask_pick(self, kind: str) -> object | None:
        field = {"category": "category_ids", "tag": "tag_ids",
                 "root": "root_key", "fts": "fts_status"}[kind]
        options = self._options(field)
        if not options:
            QtWidgets.QMessageBox.information(self, "添加条件", _empty_hint(field))
            return None
        labels = [label for _, label in options]
        title = BY_FIELD[field].menu.rstrip("…")
        label, ok = QtWidgets.QInputDialog.getItem(self, title, "选一个:", labels, 0, False)
        return options[labels.index(label)][0] if ok else None

    def _ask_day(self, cond: Condition) -> object | None:
        text, ok = QtWidgets.QInputDialog.getText(
            self, cond.menu.rstrip("…"), f"哪一天？（{_DAY_HELP}）")
        if not ok:
            return None
        try:
            return day_end(text) if cond.ask == "day_to" else day_start(text)
        except ValueError as exc:
            self._set_status(f"日期读不出来：{exc}｜{_DAY_HELP}", danger=True)
            return None

    def _ask_pages(self, cond: Condition) -> object | None:
        text, ok = QtWidgets.QInputDialog.getText(self, cond.menu.rstrip("…"), "至少几页？")
        if not ok:
            return None
        try:
            return int(text.strip())
        except ValueError:
            self._set_status(f"页数要写成整数，收到「{text}」", danger=True)
            return None

    def _ask_size(self, cond: Condition) -> object | None:
        text, ok = QtWidgets.QInputDialog.getText(
            self, cond.menu.rstrip("…"), "至少多大？（50 MB / 1.5 GB）")
        if not ok:
            return None
        try:
            return parse_size(text)
        except ValueError as exc:
            self._set_status(f"{exc}", danger=True)
            return None

    def _options(self, field: str) -> list[tuple[object, str]]:
        """每次现取（分类与标签的字典在 S8 能增删改名，缓存一次就固化成一份过期清单）。"""
        if field == "category_ids":
            return [(c.id, c.name_path) for c in self.ctx.catalog.list_categories()]
        if field == "tag_ids":
            return [(t.id, t.name) for t in self.ctx.catalog.list_tags()]
        if field == "root_key":
            return [(r.root_key, r.root_path) for r in self.ctx.roots.list()]
        return [(s, label) for s, label in FTS_LABELS.items()]

    # ---- 存 / 覆盖 ----

    def _on_save(self) -> None:
        name, ok = QtWidgets.QInputDialog.getText(self, "存为智能集合", "集合名:")
        if not ok or not name.strip():
            return
        note, ok = QtWidgets.QInputDialog.getText(self, "存为智能集合", "备注（可不填）:")
        try:
            coll = self.ctx.collection.save(name.strip(), self._query,
                                           note=note.strip() if ok and note.strip() else None)
            hits = self.ctx.collection.count(self._query)     # 数由 SQL 数，界面不数表格行
        except Exception as exc:
            self._set_status(f"存集合失败：{exc}", danger=True)
            return
        # 换上**存进去的那一份**（`Criteria.to_query()` 规范化过：tuple→list、键固定）：
        # 屏幕上的 chips 与库里的 `query_json` 从此是同一份东西（硬断言 (a)(b)），
        # 而「覆盖此集合」也立刻有了对象 —— 刚存的那条就是当前状态。
        self._adopt(coll.query, saved=CollectionEntry(coll.id, coll.name, dict(coll.query), hits))
        self._set_status(f"已存为集合「{coll.name}」· 命中 {hits} 份")

    def _on_overwrite(self) -> None:
        if self._saved is None:
            return
        try:
            coll = self.ctx.collection.overwrite(self._saved.id, self._query)
            hits = self.ctx.collection.count(self._query)
        except Exception as exc:
            self._set_status(f"覆盖集合失败：{exc}", danger=True)
            return
        self._adopt(coll.query, saved=CollectionEntry(coll.id, coll.name, dict(coll.query), hits))
        self._set_status(f"已覆盖集合「{coll.name}」· 现在命中 {hits} 份")


def _fill(menu: QtWidgets.QMenu) -> None:
    """每次展开重取：条件表是代码里的一张常量表，重取的是"这张表此刻有哪些条"。"""
    menu.clear()
    for cond in CONDITIONS:
        menu.addAction(cond.menu).setData(cond.field)


def _empty_hint(field: str) -> str:
    if field == "root_key":
        return "监测列表还是空的：先去「监测设置」登记一个根目录"
    if field == "category_ids":
        return "分类还是空的：先去「分类与标签」建一个分类"
    if field == "tag_ids":
        return "标签还是空的：先去「分类与标签」建一个标签"
    return "索引状态一个都没有：这不可能，请把这句话报出来"

