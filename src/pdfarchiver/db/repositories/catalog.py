"""分类树 + 标签 + 文档关联。

SPEC 3.3：分类不许写死在代码里。所以这里只提供 CRUD，
`services/default_catalog.py` 里的默认模板是**数据**，用户可改可删，代码不含分类判断逻辑。
"""
from __future__ import annotations

from pdfarchiver.db.engine import Engine, DatabaseError
from pdfarchiver.db.models import Category, Tag, now_ts
from pdfarchiver.db.repositories.documents import MAX_BULK_IDS


class CatalogRepository:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

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
            # 更新所有子分类的 name_path
            children = conn.execute(
                "SELECT id, name_path FROM categories WHERE name_path LIKE ? || '/%'",
                (old["name_path"],)).fetchall()
            for child in children:
                new_child_path = new_path + child["name_path"][len(old["name_path"]):]
                conn.execute("UPDATE categories SET name_path=?, updated_at=? WHERE id=?",
                             (new_child_path, ts, child["id"]))
        return self._get_category(category_id)

    def reparent_category(self, category_id: int, new_parent_id: int | None) -> Category:
        """移动到新的父分类下，更新 name_path 和所有子分类的 name_path。"""
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
            new_parent_path = parent["name_path"]
        else:
            new_parent_path = ""
        new_path = f"{new_parent_path}/{old['name']}" if new_parent_path else old["name"]
        ts = now_ts()
        with self.engine.transaction(conn, on_error=f"移动分类 {category_id} 失败"):
            conn.execute("UPDATE categories SET parent_id=?, name_path=?, updated_at=? WHERE id=?",
                         (new_parent_id, new_path, ts, category_id))
            # 更新所有子分类的 name_path
            children = conn.execute(
                "SELECT id, name_path FROM categories WHERE name_path LIKE ? || '/%'",
                (old["name_path"],)).fetchall()
            for child in children:
                new_child_path = new_path + child["name_path"][len(old["name_path"]):]
                conn.execute("UPDATE categories SET name_path=?, updated_at=? WHERE id=?",
                             (new_child_path, ts, child["id"]))
        return self._get_category(category_id)

    def delete_category(self, category_id: int) -> None:
        """删除分类及其所有子分类，同时删除 document_categories 关联。"""
        conn = self.engine.thread_connection()
        cat = conn.execute("SELECT name_path FROM categories WHERE id=?", (category_id,)).fetchone()
        if cat is None:
            raise DatabaseError(f"分类不存在：{category_id}", ValueError("外键前置检查"))
        with self.engine.transaction(conn, on_error=f"删除分类 {category_id} 失败"):
            # 删除所有子分类的关联
            conn.execute(
                "DELETE FROM document_categories WHERE category_id IN"
                " (SELECT id FROM categories WHERE name_path LIKE ? || '%')",
                (cat["name_path"],))
            # 删除所有子分类
            conn.execute("DELETE FROM categories WHERE name_path LIKE ? || '%'", (cat["name_path"],))

    def merge_categories(self, source_id: int, target_id: int) -> None:
        """将 source 的所有文档关联移到 target，然后删除 source。"""
        conn = self.engine.thread_connection()
        source = conn.execute("SELECT id, name_path FROM categories WHERE id=?", (source_id,)).fetchone()
        target = conn.execute("SELECT id FROM categories WHERE id=?", (target_id,)).fetchone()
        if source is None:
            raise DatabaseError(f"源分类不存在：{source_id}", ValueError("外键前置检查"))
        if target is None:
            raise DatabaseError(f"目标分类不存在：{target_id}", ValueError("外键前置检查"))
        with self.engine.transaction(conn, on_error=f"合并分类 {source_id} -> {target_id} 失败"):
            # 移动关联（跳过已存在的）
            conn.execute(
                "UPDATE OR IGNORE document_categories SET category_id=?"
                " WHERE category_id=?", (target_id, source_id))
            # 删除剩余的（已存在于 target 的）
            conn.execute("DELETE FROM document_categories WHERE category_id=?", (source_id,))
            # 删除源分类及其子分类
            conn.execute("DELETE FROM categories WHERE name_path LIKE ? || '%'", (source["name_path"],))

    def _get_category(self, category_id: int) -> Category:
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

    def merge_tags(self, source_id: int, target_id: int) -> None:
        """将 source 的所有文档关联移到 target，然后删除 source。"""
        conn = self.engine.thread_connection()
        with self.engine.transaction(conn, on_error=f"合并标签 {source_id} -> {target_id} 失败"):
            # 移动关联（跳过已存在的）
            conn.execute(
                "UPDATE OR IGNORE document_tags SET tag_id=? WHERE tag_id=?",
                (target_id, source_id))
            # 删除剩余的（已存在于 target 的）
            conn.execute("DELETE FROM document_tags WHERE tag_id=?", (source_id,))
            conn.execute("DELETE FROM tags WHERE id=?", (source_id,))

    def _get_tag(self, tag_id: int) -> Tag:
        row = self.engine.thread_connection().execute(
            "SELECT id,name,color,note,created_at FROM tags WHERE id=?", (tag_id,)).fetchone()
        if row is None:
            raise DatabaseError(f"标签不存在：{tag_id}", ValueError("查询失败"))
        return Tag(**dict(row))

    # ---- 文档 ↔ 分类 / 标签 ----

    def link_category(self, doc_id: int, category_id: int, *, origin: str = "manual",
                      confirmed: int = 1) -> bool:
        """已关联返回 False（幂等），新建关联返回 True。

        `origin='ai'` 时 `confirmed` 必须由调用方显式传 0 —— SPEC 3.3：AI 建议未经人工确认
        不得触发文件动作，所以这里的默认值刻意是"人工已确认"，AI 路径不可能误用默认值。
        """
        conn = self.engine.thread_connection()
        with self.engine.transaction(conn, on_error="文档挂分类失败"):
            cur = conn.execute(
                "INSERT INTO document_categories(doc_id, category_id, origin, confirmed, added_at)"
                " VALUES(?,?,?,?,?) ON CONFLICT(doc_id, category_id) DO NOTHING",
                (doc_id, category_id, origin, confirmed, now_ts()))
        return cur.rowcount > 0

    def link_tag(self, doc_id: int, tag_id: int, *, origin: str = "manual", confirmed: int = 1) -> bool:
        conn = self.engine.thread_connection()
        with self.engine.transaction(conn, on_error="文档挂标签失败"):
            cur = conn.execute(
                "INSERT INTO document_tags(doc_id, tag_id, origin, confirmed, added_at)"
                " VALUES(?,?,?,?,?) ON CONFLICT(doc_id, tag_id) DO NOTHING",
                (doc_id, tag_id, origin, confirmed, now_ts()))
        return cur.rowcount > 0

    def unlink_tag(self, doc_id: int, tag_id: int) -> bool:
        conn = self.engine.thread_connection()
        with self.engine.transaction(conn, on_error="取消标签失败"):
            cur = conn.execute("DELETE FROM document_tags WHERE doc_id=? AND tag_id=?",
                               (doc_id, tag_id))
        return cur.rowcount > 0

    def tags_of(self, doc_id: int) -> list[Tag]:
        rows = self.engine.thread_connection().execute(
            "SELECT t.id,t.name,t.color,t.note,t.created_at FROM tags t"
            " JOIN document_tags d ON d.tag_id=t.id WHERE d.doc_id=? ORDER BY t.name COLLATE NOCASE",
            (doc_id,)).fetchall()
        return [Tag(**dict(r)) for r in rows]

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
