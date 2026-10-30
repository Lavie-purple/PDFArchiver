"""分类树 + 标签 + 文档关联。

SPEC 3.3：分类不许写死在代码里。所以这里只提供 CRUD，
`services/default_catalog.py` 里的默认模板是**数据**，用户可改可删，代码不含分类判断逻辑。

「归入分类 / 加标签 / 移除标签」的**批量版**在本文件（**ISSUES I78** 甲，2026-10-19）：
界面一次点名几份，这里开**一个**事务写完，并返回一份 `LinkReceipt` —— 屏幕上那句回执
只有这一个出处，界面不许自己数"新增了几条"（沿用 **ISSUES I60** 那条"格式化只有一个出口"）。

子树谓词也统一在一个私有方法里（`_subtree_ids`）：原先删分类与合并分类都用
`name_path LIKE '父/子%'`，那个 `%` 允许紧跟**任意**字符，所以「财务/报销」会把兄弟
「财务/报销单据」整枝一起圈进去 —— 见 `test_子树谓词不许把兄弟分类圈进来`。
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from pdfarchiver.db.engine import Engine, DatabaseError
from pdfarchiver.db.models import Category, Tag, now_ts
from pdfarchiver.db.repositories.documents import MAX_BULK_IDS

#: 三类批量写入的措辞表：`(动词, 变动条数的说法, 没变动那份的说法)`。
#: 单列成表是因为 `unchanged` 在"加"和"删"两个方向上意思相反，混成一句就会说错。
LINK_COPY = {
    "category": ("已归入", "新增", "原本已在"),
    "tag": ("已加标签", "新增", "原本已有"),
    "tag_removal": ("已移除标签", "移除", "原本没有"),
}


@dataclass(frozen=True)
class LinkReceipt:
    """一次批量关联写入的计数。`named` 是去重后的点名份数，`changed + unchanged == named`。"""

    kind: str
    target_name: str
    named: int
    changed: int
    unchanged: int

    def describe(self) -> str:
        """回执的唯一格式化出口 —— 界面拿到它就直接上屏，不再拼第二个口径。"""
        if self.kind not in LINK_COPY:
            raise ValueError(f"未知的关联写入类型：{self.kind}（措辞表里没有这一档）")
        verb, moved, idle = LINK_COPY[self.kind]
        return (f"{verb}「{self.target_name}」· 点名 {self.named} 份 · "
                f"{moved} {self.changed} 条 · {idle} {self.unchanged} 份")


class CatalogRepository:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    # ---- 内部：整枝展开 ----

    def _subtree_ids(self, conn, category_id: int) -> list[int]:
        """这一枝的全部分类 id（**含自己**），按 `parent_id` 逐层取。

        为什么不用 `name_path LIKE '财务/报销%'`：那个 `%` 允许紧跟任意字符，所以它会连
        兄弟「财务/报销单据」一起命中。删分类与合并分类都拿这个结果去 `DELETE`，
        于是"删一个分类"会变成"删掉一整族分类并把它们的文档关联一起 cascade 走"
        （`document_categories.category_id` 是 `ON DELETE CASCADE`，**2026-10-19 现测**）。
        逐层取的成本是树深次查询，而分类树的量级是几十到几百行（`count_categories` 的读数），
        不是文档数 —— 这里省下来的那一次查询不值这个风险。
        """
        ids = [category_id]
        frontier = [category_id]
        while frontier:
            marks = ",".join("?" * len(frontier))
            rows = conn.execute(
                f"SELECT id FROM categories WHERE parent_id IN ({marks})", frontier).fetchall()
            frontier = [row["id"] for row in rows]
            ids.extend(frontier)
        return ids

    def _bulk_doc_ids(self, doc_ids: Iterable[int]) -> list[int]:
        """批量入口的公共前置：保序去重、空点名与超上限都当场拒。

        上限沿用 `documents.MAX_BULK_IDS`（同一个数、同一个理由），不另立第二个口径。
        """
        unique = list(dict.fromkeys(doc_ids))
        if not unique:
            raise DatabaseError("没有点名任何文档", ValueError("空批量"))
        if len(unique) > MAX_BULK_IDS:
            raise ValueError(f"一次操作 {len(unique)} 份超出 {MAX_BULK_IDS}；"
                             "大批量请按条件分批，不要把 ID 列表整个塞进参数")
        return unique

    def subtree_ids(self, category_id: int) -> list[int]:
        """这一枝的全部分类 id（**含自己**）。谓词只有 `_subtree_ids` 那一条，这里是带前置检查的公开口。

        为什么要公开：`services/export_service.py` 的「含子分类」要的正是这一串 id，而它自己不许写
        SQL（依赖方向，**D-054**）。让服务层去 `name_path LIKE` 就是当年那条把兄弟整枝圈进来的
        坏谓词的第二次登场 —— 见本文件顶部那段。
        """
        conn = self.engine.thread_connection()
        if conn.execute("SELECT id FROM categories WHERE id=?", (category_id,)).fetchone() is None:
            raise DatabaseError(f"分类不存在：{category_id}", ValueError("外键前置检查"))
        return self._subtree_ids(conn, category_id)

    # ---- 分类 ----

    def add_category(self, name: str, parent_id: int | None = None, note: str | None = None) -> Category:
        name = name.strip()
        if not name:
            raise DatabaseError("分类名不能为空", ValueError("空分类名"))
        conn = self.engine.thread_connection()
        ts = now_ts()
        parent_path = ""
        if parent_id is not None:
            row = conn.execute("SELECT name_path FROM categories WHERE id=?", (parent_id,)).fetchone()
            if row is None:
                raise DatabaseError(f"父分类不存在：{parent_id}", ValueError("外键前置检查"))
            parent_path = row["name_path"]
        name_path = f"{parent_path}/{name}" if parent_path else name
        with self.engine.transaction(conn, on_error=f"新建分类 {name} 失败"):
            cur = conn.execute(
                "INSERT INTO categories(name, parent_id, name_path, note, created_at, updated_at)"
                " VALUES(?,?,?,?,?,?)", (name, parent_id, name_path, note, ts, ts))
        return Category(id=cur.lastrowid, name=name, parent_id=parent_id,
                        name_path=name_path, note=note, created_at=ts, updated_at=ts)

    def list_categories(self) -> list[Category]:
        rows = self.engine.thread_connection().execute(
            "SELECT id,name,parent_id,name_path,note,created_at,updated_at"
            " FROM categories ORDER BY name_path COLLATE NOCASE").fetchall()
        return [Category(**dict(r)) for r in rows]

    def category_tree(self) -> list[tuple[Category, int]]:
        """(分类, 层级) 的先序展开，给侧栏树用；层级由 name_path 的斜杠数决定，不递归查库。"""
        out: list[tuple[Category, int]] = []
        for c in self.list_categories():
            out.append((c, c.name_path.count("/")))
        return out

    def count_categories(self) -> int:
        return self.engine.thread_connection().execute("SELECT count(*) FROM categories").fetchone()[0]

    def has_categorized_documents(self) -> bool:
        """库里到底有没有"文档 ↔ 分类"的关联 —— 左栏收成条时那颗小圆点读它（**D-066** / ⑮）。

        取 `LIMIT 1` 而不是 `count(*)`：要回答的只是"有没有"，而 `count(*)` 在这张关联表
        长到百万行档就是一趟全索引扫描（**ISSUES I109** 记的就是这类读数）。
        """
        return self.engine.thread_connection().execute(
            "SELECT 1 FROM document_categories LIMIT 1").fetchone() is not None

    def _repath_subtree(self, conn, category_id: int, old_path: str, new_path: str,
                        ts: int) -> None:
        """改名或挪父子之后，把整枝后代的 `name_path` 前缀换掉 —— 一条规则，两处共用。

        后代按 `parent_id` 取，不按 `name_path LIKE '旧路径/%'` 取：后者要拿的正是此刻在改的
        那个串，改错了就直接查空（**rename** 那一处当年就是这么写的，两处各留一份就会各漂各的）。
        """
        for child_id in self._subtree_ids(conn, category_id)[1:]:
            child_path = conn.execute("SELECT name_path FROM categories WHERE id=?",
                                      (child_id,)).fetchone()["name_path"]
            conn.execute("UPDATE categories SET name_path=?, updated_at=? WHERE id=?",
                         (new_path + child_path[len(old_path):], ts, child_id))

    def rename_category(self, category_id: int, new_name: str) -> Category:
        """改名并更新所有子分类的 name_path。"""
        new_name = new_name.strip()
        if not new_name:
            raise DatabaseError("分类名不能为空", ValueError("空分类名"))
        conn = self.engine.thread_connection()
        old = conn.execute("SELECT id,name,parent_id,name_path,note,created_at FROM categories WHERE id=?",
                           (category_id,)).fetchone()
        if old is None:
            raise DatabaseError(f"分类不存在：{category_id}", ValueError("外键前置检查"))
        parent_path = old["name_path"].rsplit("/", 1)[0] if "/" in old["name_path"] else ""
        new_path = f"{parent_path}/{new_name}" if parent_path else new_name
        ts = now_ts()
        with self.engine.transaction(conn, on_error=f"改名分类 {category_id} 失败"):
            conn.execute("UPDATE categories SET name=?, name_path=?, updated_at=? WHERE id=?",
                         (new_name, new_path, ts, category_id))
            self._repath_subtree(conn, category_id, old["name_path"], new_path, ts)
        return self.get_category(category_id)

    def reparent_category(self, category_id: int, new_parent_id: int | None) -> Category:
        """移动到新的父分类下，更新 name_path 和所有子分类的 name_path。

        成环前置检查：把自己或自己的子孙当新父亲，`name_path` 就会写出一个自指的串
        （`财务/合同/财务/合同/…`），界面上那一枝直接找不回来 —— 这是**挪**不是**改**，
        所以宁可当场拒，不许静默把子树变成孤儿。
        """
        conn = self.engine.thread_connection()
        old = conn.execute("SELECT id,name,name_path FROM categories WHERE id=?",
                           (category_id,)).fetchone()
        if old is None:
            raise DatabaseError(f"分类不存在：{category_id}", ValueError("外键前置检查"))
        if new_parent_id is not None:
            parent = conn.execute("SELECT name_path FROM categories WHERE id=?",
                                  (new_parent_id,)).fetchone()
            if parent is None:
                raise DatabaseError(f"父分类不存在：{new_parent_id}", ValueError("外键前置检查"))
            if new_parent_id in self._subtree_ids(conn, category_id):
                raise DatabaseError(
                    f"不能把「{old['name']}」挪进它自己或它的子分类里", ValueError("成环前置检查"))
            new_parent_path = parent["name_path"]
        else:
            new_parent_path = ""
        new_path = f"{new_parent_path}/{old['name']}" if new_parent_path else old["name"]
        ts = now_ts()
        with self.engine.transaction(conn, on_error=f"移动分类 {category_id} 失败"):
            conn.execute("UPDATE categories SET parent_id=?, name_path=?, updated_at=? WHERE id=?",
                         (new_parent_id, new_path, ts, category_id))
            self._repath_subtree(conn, category_id, old["name_path"], new_path, ts)
        return self.get_category(category_id)

    def delete_category(self, category_id: int) -> None:
        """删除这一整枝分类，连带它们的文档关联（子分类的关联由整枝列表显式删掉）。"""
        conn = self.engine.thread_connection()
        if conn.execute("SELECT id FROM categories WHERE id=?", (category_id,)).fetchone() is None:
            raise DatabaseError(f"分类不存在：{category_id}", ValueError("外键前置检查"))
        with self.engine.transaction(conn, on_error=f"删除分类 {category_id} 失败"):
            subtree = self._subtree_ids(conn, category_id)
            marks = ",".join("?" * len(subtree))
            conn.execute(f"DELETE FROM document_categories WHERE category_id IN ({marks})", subtree)
            conn.execute(f"DELETE FROM categories WHERE id IN ({marks})", subtree)

    def merge_categories(self, source_id: int, target_id: int) -> int:
        """把源整枝并进目标分类：源**与它子孙**名下的文档全部改指目标，然后删掉源整枝。

        返回源整枝名下的文档份数（界面上要能说"并过去几份"，而这个数只有这里数得准）。

        为什么是两条语句而不是一条 `UPDATE`：`UPDATE OR IGNORE` 撞主键（这份文档已经在目标类里）
        时那行**留在原处不动**，紧跟的 `DELETE` 把这类残留清掉 —— 于是"两边都有"的一份文档
        不会变成两行，也不会一行都没有。顺序反了就是把关联删没了。
        """
        conn = self.engine.thread_connection()
        source = conn.execute("SELECT name FROM categories WHERE id=?", (source_id,)).fetchone()
        if source is None:
            raise DatabaseError(f"源分类不存在：{source_id}", ValueError("外键前置检查"))
        target = conn.execute("SELECT name FROM categories WHERE id=?", (target_id,)).fetchone()
        if target is None:
            raise DatabaseError(f"目标分类不存在：{target_id}", ValueError("外键前置检查"))
        if target_id in self._subtree_ids(conn, source_id):
            raise DatabaseError(f"不能把「{source['name']}」并进它自己的子分类「{target['name']}」里",
                                ValueError("成环前置检查"))
        with self.engine.transaction(conn, on_error=f"合并分类 {source_id} -> {target_id} 失败"):
            subtree = self._subtree_ids(conn, source_id)
            marks = ",".join("?" * len(subtree))
            moved = conn.execute(
                f"SELECT count(DISTINCT doc_id) FROM document_categories WHERE category_id IN ({marks})",
                subtree).fetchone()[0]
            conn.execute(
                f"UPDATE OR IGNORE document_categories SET category_id=? WHERE category_id IN ({marks})",
                (target_id, *subtree))
            conn.execute(f"DELETE FROM document_categories WHERE category_id IN ({marks})", subtree)
            conn.execute(f"DELETE FROM categories WHERE id IN ({marks})", subtree)
        return moved

    def get_category(self, category_id: int) -> Category:
        row = self.engine.thread_connection().execute(
            "SELECT id,name,parent_id,name_path,note,created_at,updated_at FROM categories WHERE id=?",
            (category_id,)).fetchone()
        if row is None:
            raise DatabaseError(f"分类不存在：{category_id}", ValueError("查询失败"))
        return Category(**dict(row))

    # ---- 标签 ----

    def add_tag(self, name: str, color: str | None = None) -> Tag:
        name = name.strip()
        if not name:
            raise DatabaseError("标签名不能为空", ValueError("空标签名"))
        conn = self.engine.thread_connection()
        ts = now_ts()
        with self.engine.transaction(conn, on_error=f"新建标签 {name} 失败"):
            cur = conn.execute("INSERT INTO tags(name, color, created_at) VALUES(?,?,?)",
                               (name, color, ts))
        return Tag(id=cur.lastrowid, name=name, color=color, created_at=ts)

    def list_tags(self) -> list[Tag]:
        rows = self.engine.thread_connection().execute(
            "SELECT id,name,color,note,created_at FROM tags ORDER BY name COLLATE NOCASE").fetchall()
        return [Tag(**dict(r)) for r in rows]

    def count_tags(self) -> int:
        return self.engine.thread_connection().execute("SELECT count(*) FROM tags").fetchone()[0]

    def rename_tag(self, tag_id: int, new_name: str) -> Tag:
        new_name = new_name.strip()
        if not new_name:
            raise DatabaseError("标签名不能为空", ValueError("空标签名"))
        conn = self.engine.thread_connection()
        with self.engine.transaction(conn, on_error=f"改名标签 {tag_id} 失败"):
            conn.execute("UPDATE tags SET name=? WHERE id=?", (new_name, tag_id))
        return self._get_tag(tag_id)

    def delete_tag(self, tag_id: int) -> None:
        """删除标签及其所有 document_tags 关联。"""
        conn = self.engine.thread_connection()
        with self.engine.transaction(conn, on_error=f"删除标签 {tag_id} 失败"):
            conn.execute("DELETE FROM document_tags WHERE tag_id=?", (tag_id,))
            conn.execute("DELETE FROM tags WHERE id=?", (tag_id,))

    def merge_tags(self, source_id: int, target_id: int) -> int:
        """把源标签并进目标标签：源名下的文档关联全部改指目标，然后删掉源。

        返回**源名下的文档份数**（界面上要能说"并过去几份"，而这个数只有这里数得准 ——
        与 `merge_categories` 同一条口径，那边也是自己数、让界面转述）。

        三条前置检查都在这一层，界面不重算一遍（口径只有一个）：
        - 源不存在 / 目标不存在 → 拒。修前没有这两条：`DELETE` 打在不存在的 id 上就是静默
          无操作，而屏幕上那句"已并过去"照样说给用户听。
        - 源 == 目标 → 拒。**这一条修前是最要命的**：`UPDATE OR IGNORE` 把 `tag_id` 改成
          它自己（等于无操作），紧跟的那条 `DELETE FROM document_tags WHERE tag_id=?`
          就把这个标签的**全部关联删光**，`tags` 行也跟着删 —— 按下去是"删标签"，不是"合并"。

        为什么是两条语句而不是一条 `UPDATE`：`UPDATE OR IGNORE` 撞主键（这份文档已经挂着目标
        那个标签）时那行**留在原处不动**，紧跟的 `DELETE` 把这类残留清掉 —— 于是"两边都有"的
        一份文档不会变成两行，也不会一行都没有。顺序反了就是把关联删没了（同 `merge_categories`）。
        """
        conn = self.engine.thread_connection()
        source = conn.execute("SELECT name FROM tags WHERE id=?", (source_id,)).fetchone()
        if source is None:
            raise DatabaseError(f"源标签不存在：{source_id}", ValueError("外键前置检查"))
        target = conn.execute("SELECT name FROM tags WHERE id=?", (target_id,)).fetchone()
        if target is None:
            raise DatabaseError(f"目标标签不存在：{target_id}", ValueError("外键前置检查"))
        if source_id == target_id:
            raise DatabaseError(f"不能把「{source['name']}」并进它自己", ValueError("自我合并前置检查"))
        with self.engine.transaction(conn, on_error=f"合并标签 {source_id} -> {target_id} 失败"):
            moved = conn.execute("SELECT count(DISTINCT doc_id) FROM document_tags WHERE tag_id=?",
                                 (source_id,)).fetchone()[0]
            conn.execute("UPDATE OR IGNORE document_tags SET tag_id=? WHERE tag_id=?",
                         (target_id, source_id))
            conn.execute("DELETE FROM document_tags WHERE tag_id=?", (source_id,))
            conn.execute("DELETE FROM tags WHERE id=?", (source_id,))
        return moved

    def _get_tag(self, tag_id: int) -> Tag:
        row = self.engine.thread_connection().execute(
            "SELECT id,name,color,note,created_at FROM tags WHERE id=?", (tag_id,)).fetchone()
        if row is None:
            raise DatabaseError(f"标签不存在：{tag_id}", ValueError("查询失败"))
        return Tag(**dict(row))

    # ---- 文档 ↔ 分类 / 标签 ----

    def link_categories(self, doc_ids: Iterable[int], category_id: int, *,
                        origin: str = "manual", confirmed: int = 1) -> LinkReceipt:
        """把**一批**文档归进一个分类，一个事务写完，返回一份能直接上屏的回执。

        为什么要有批量版而不是让界面循环调单份版：循环 N 次就是 N 个事务，中途崩一次就留下
        "前 k 份进了、后面没进"这种界面上看不出来的半截状态；而 **ISSUES I78** 记的就是
        "用户能建分类却没有任何一处能把文档归进去"，入口第一次落地就得是**整批成或整批不成**。

        多分类是**共存**的：这一条只加关联，不动这些文档在别的分类里的行 —— 主键是
        `(doc_id, category_id)`，S1 那一列也按"一份文档可以在几个分类里"显示（至多三个名字）。
        幂等：已经在里面的那几份不新增行，计进 `unchanged`。

        `origin='ai'` 时 `confirmed` 必须由调用方显式传 0 —— SPEC 3.3：AI 建议未经人工确认
        不得触发文件动作，所以这里的默认值刻意是"人工已确认"，AI 路径不可能误用默认值。
        """
        ids = self._bulk_doc_ids(doc_ids)
        conn = self.engine.thread_connection()
        target = conn.execute("SELECT name FROM categories WHERE id=?", (category_id,)).fetchone()
        if target is None:
            raise DatabaseError(f"分类不存在：{category_id}", ValueError("外键前置检查"))
        marks = ",".join("?" * len(ids))
        ts = now_ts()
        with self.engine.transaction(conn, on_error=f"批量归入分类 {category_id} 失败"):
            have = {row["doc_id"] for row in conn.execute(
                f"SELECT doc_id FROM document_categories WHERE category_id=? AND doc_id IN ({marks})",
                (category_id, *ids))}
            to_add = [doc_id for doc_id in ids if doc_id not in have]
            if to_add:
                conn.executemany(
                    "INSERT INTO document_categories(doc_id, category_id, origin, confirmed, added_at)"
                    " VALUES(?,?,?,?,?)",
                    [(doc_id, category_id, origin, confirmed, ts) for doc_id in to_add])
        return LinkReceipt(kind="category", target_name=target["name"], named=len(ids),
                           changed=len(to_add), unchanged=len(ids) - len(to_add))

    def link_category(self, doc_id: int, category_id: int, *, origin: str = "manual",
                      confirmed: int = 1) -> bool:
        """单份版就是"批量版点一份" —— 只留一条 SQL 路径，不另立第二个口径。已关联返回 False。"""
        return self.link_categories([doc_id], category_id, origin=origin,
                                    confirmed=confirmed).changed > 0

    def link_tags(self, doc_ids: Iterable[int], tag_id: int, *,
                  origin: str = "manual", confirmed: int = 1) -> LinkReceipt:
        """把**一批**文档打上同一个标签（SPEC 阶段 3 的「批量打标签」，**ISSUES I78** ②）。"""
        ids = self._bulk_doc_ids(doc_ids)
        conn = self.engine.thread_connection()
        target = conn.execute("SELECT name FROM tags WHERE id=?", (tag_id,)).fetchone()
        if target is None:
            raise DatabaseError(f"标签不存在：{tag_id}", ValueError("外键前置检查"))
        marks = ",".join("?" * len(ids))
        ts = now_ts()
        with self.engine.transaction(conn, on_error=f"批量加标签 {tag_id} 失败"):
            have = {row["doc_id"] for row in conn.execute(
                f"SELECT doc_id FROM document_tags WHERE tag_id=? AND doc_id IN ({marks})",
                (tag_id, *ids))}
            to_add = [doc_id for doc_id in ids if doc_id not in have]
            if to_add:
                conn.executemany(
                    "INSERT INTO document_tags(doc_id, tag_id, origin, confirmed, added_at)"
                    " VALUES(?,?,?,?,?)",
                    [(doc_id, tag_id, origin, confirmed, ts) for doc_id in to_add])
        return LinkReceipt(kind="tag", target_name=target["name"], named=len(ids),
                           changed=len(to_add), unchanged=len(ids) - len(to_add))

    def link_tag(self, doc_id: int, tag_id: int, *, origin: str = "manual",
                 confirmed: int = 1) -> bool:
        return self.link_tags([doc_id], tag_id, origin=origin, confirmed=confirmed).changed > 0

    def unlink_tags(self, doc_ids: Iterable[int], tag_id: int) -> LinkReceipt:
        """从**一批**文档上摘掉一个标签，只摘这一个 —— 别的标签一条都不动（销账判定①②）。"""
        ids = self._bulk_doc_ids(doc_ids)
        conn = self.engine.thread_connection()
        target = conn.execute("SELECT name FROM tags WHERE id=?", (tag_id,)).fetchone()
        if target is None:
            raise DatabaseError(f"标签不存在：{tag_id}", ValueError("外键前置检查"))
        marks = ",".join("?" * len(ids))
        with self.engine.transaction(conn, on_error=f"批量移除标签 {tag_id} 失败"):
            have = {row["doc_id"] for row in conn.execute(
                f"SELECT doc_id FROM document_tags WHERE tag_id=? AND doc_id IN ({marks})",
                (tag_id, *ids))}
            if have:
                gone = ",".join("?" * len(have))
                conn.execute(f"DELETE FROM document_tags WHERE tag_id=? AND doc_id IN ({gone})",
                             (tag_id, *sorted(have)))
        return LinkReceipt(kind="tag_removal", target_name=target["name"], named=len(ids),
                           changed=len(have), unchanged=len(ids) - len(have))

    def unlink_tag(self, doc_id: int, tag_id: int) -> bool:
        return self.unlink_tags([doc_id], tag_id).changed > 0

    def tags_of(self, doc_id: int) -> list[Tag]:
        return self.tags_by_doc_ids([doc_id]).get(doc_id, [])

    def tags_by_doc_ids(self, doc_ids: Iterable[int]) -> dict[int, list[Tag]]:
        """一批文档的标签，**一条**查询取回（与 `categories_by_doc_ids` 同一条理由）。

        「移除标签」那个浮层要把"这几份里各有几份带这个标签"数出来，逐行调 `tags_of`
        在 200 行档就是 200 条 SQL —— 那是 **ISSUES I51** 已经判过的那类错。
        """
        unique = list(dict.fromkeys(doc_ids))
        if not unique:
            return {}
        if len(unique) > MAX_BULK_IDS:
            raise ValueError(f"一次取 {len(unique)} 条超出 {MAX_BULK_IDS}；"
                             "大批量请按条件分页取文档，不要把 ID 列表塞进参数")
        marks = ",".join("?" * len(unique))
        rows = self.engine.thread_connection().execute(
            f"SELECT d.doc_id AS doc_id,t.id,t.name,t.color,t.note,t.created_at"
            f" FROM tags t JOIN document_tags d ON d.tag_id=t.id"
            f" WHERE d.doc_id IN ({marks}) ORDER BY d.doc_id, t.name COLLATE NOCASE",
            unique).fetchall()
        grouped: dict[int, list[Tag]] = {}
        for r in rows:
            item = dict(r)
            grouped.setdefault(item.pop("doc_id"), []).append(Tag(**item))
        return grouped

    def categories_of(self, doc_id: int) -> list[Category]:
        rows = self.engine.thread_connection().execute(
            "SELECT c.id,c.name,c.parent_id,c.name_path,c.note,c.created_at,c.updated_at"
            " FROM categories c JOIN document_categories d ON d.category_id=c.id"
            " WHERE d.doc_id=? ORDER BY c.name_path COLLATE NOCASE", (doc_id,)).fetchall()
        return [Category(**dict(r)) for r in rows]

    def categories_by_doc_ids(self, doc_ids: list[int]) -> dict[int, list[Category]]:
        """一批文档的分类，**一条**查询取回。

        为什么要有这一条：文档表每一行都要显示「分类」，逐行调 `categories_of` 在 1,000
        行档就是 1,000 条 SQL（**ISSUES I51** 修前实测 `per_row_categories_queries=1000`）。
        排序与 `categories_of` 用同一个 `ORDER BY c.name_path COLLATE NOCASE`，只是多带一层
        `doc_id`：同一份文档显示哪几个分类、按什么顺序显示，两处不可能各说各话。
        没有分类的文档不出现在返回值里（调用方按"取不到就是空列表"读）。
        """
        unique = set(doc_ids)
        if not unique:
            return {}
        if len(unique) > MAX_BULK_IDS:
            raise ValueError(f"一次取 {len(unique)} 条超出 {MAX_BULK_IDS}；"
                             "大批量请按条件分页取文档，不要把 ID 列表塞进参数")
        marks = ",".join("?" * len(unique))
        rows = self.engine.thread_connection().execute(
            "SELECT d.doc_id AS doc_id,c.id,c.name,c.parent_id,c.name_path,c.note,"
            "c.created_at,c.updated_at"
            " FROM categories c JOIN document_categories d ON d.category_id=c.id"
            f" WHERE d.doc_id IN ({marks}) ORDER BY d.doc_id, c.name_path COLLATE NOCASE",
            sorted(unique)).fetchall()
        grouped: dict[int, list[Category]] = {}
        for r in rows:
            item = dict(r)
            grouped.setdefault(item.pop("doc_id"), []).append(Category(**item))
        return grouped

    def docs_in_category(self, category_id: int, limit: int = 1000) -> list[int]:
        """返回某分类下的文档 ID 列表。"""
        rows = self.engine.thread_connection().execute(
            "SELECT doc_id FROM document_categories WHERE category_id = ?",
            (category_id,)).fetchall()
        return [r["doc_id"] for r in rows[:limit]]

    def docs_in_subtree(self, category_id: int, limit: int = 1000) -> list[tuple[int, str]]:
        """整枝（含子分类）名下的文档 `(doc_id, 文件名)`，给"删之前先看一眼"用。

        为什么要有它：§S8 定案写着「删除分类前必须先检查该类下是否还有文件，有则拒绝并给
        文件清单」，而 S8 右键菜单上就是**照那句写的菜单项标题** —— 标签承诺了而代码不查，
        就是 **ISSUES I80** 那一类"界面宣称它会做它不做的事"。
        与 `docs_in_category` 的差别只在整枝 vs 单枝，所以另起一个名字，不改那条的语义
        （`semantic/classify_service.py:58` 用的就是单枝版）。
        """
        conn = self.engine.thread_connection()
        if conn.execute("SELECT id FROM categories WHERE id=?", (category_id,)).fetchone() is None:
            raise DatabaseError(f"分类不存在：{category_id}", ValueError("外键前置检查"))
        subtree = self._subtree_ids(conn, category_id)
        marks = ",".join("?" * len(subtree))
        rows = conn.execute(
            f"SELECT d.doc_id AS doc_id,doc.name AS name FROM document_categories d"
            f" JOIN documents doc ON doc.id=d.doc_id WHERE d.category_id IN ({marks})"
            f" ORDER BY doc.name COLLATE NOCASE LIMIT ?", (*subtree, limit)).fetchall()
        return [(row["doc_id"], row["name"]) for row in rows]
