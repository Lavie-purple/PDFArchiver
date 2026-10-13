"""分类树 + 标签 + 文档关联。

SPEC 3.3：分类不许写死在代码里。所以这里只提供 CRUD，
`services/default_catalog.py` 里的默认模板是**数据**，用户可改可删，代码不含分类判断逻辑。
"""
from __future__ import annotations

from pdfarchiver.db.engine import Engine, DatabaseError
from pdfarchiver.db.models import Category, Tag, now_ts


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
