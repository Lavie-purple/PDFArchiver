"""智能集合 —— 存查询条件 JSON，不复制文件（SPEC 3.3.5）。

智能集合是"保存的检索条件"，不是文件分组。每次打开集合时现跑查询，
所以集合本身不占磁盘空间，只占一行 records。
"""
from __future__ import annotations

import json

from pdfarchiver.db.engine import Engine, DatabaseError
from pdfarchiver.db.models import now_ts


class Collection:
    def __init__(self, id: int, name: str, query_json: str, note: str | None, created_at: int) -> None:
        self.id = id
        self.name = name
        self.query_json = query_json
        self.note = note
        self.created_at = created_at

    @property
    def query(self) -> dict:
        """解析后的查询条件。"""
        return json.loads(self.query_json)


class CollectionRepository:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def add(self, name: str, query: dict, note: str | None = None) -> Collection:
        """新建智能集合。query 必须是可 JSON 序列化的字典。"""
        name = name.strip()
        if not name:
            raise DatabaseError("集合名不能为空", ValueError("空集合名"))
        query_json = json.dumps(query, ensure_ascii=False, sort_keys=True)
        conn = self.engine.thread_connection()
        ts = now_ts()
        with self.engine.transaction(conn, on_error=f"新建集合 {name} 失败"):
            cur = conn.execute(
                "INSERT INTO collections(name, query_json, note, created_at) VALUES(?,?,?,?)",
                (name, query_json, note, ts))
        return Collection(id=cur.lastrowid, name=name, query_json=query_json, note=note, created_at=ts)

    def list(self) -> list[Collection]:
        rows = self.engine.thread_connection().execute(
            "SELECT id,name,query_json,note,created_at FROM collections ORDER BY name COLLATE NOCASE"
        ).fetchall()
        return [Collection(**dict(r)) for r in rows]

    def get(self, collection_id: int) -> Collection:
        row = self.engine.thread_connection().execute(
            "SELECT id,name,query_json,note,created_at FROM collections WHERE id=?",
            (collection_id,)).fetchone()
        if row is None:
            raise DatabaseError(f"集合不存在：{collection_id}", ValueError("外键前置检查"))
        return Collection(**dict(row))

    def rename(self, collection_id: int, new_name: str) -> Collection:
        new_name = new_name.strip()
        if not new_name:
            raise DatabaseError("集合名不能为空", ValueError("空集合名"))
        conn = self.engine.thread_connection()
        with self.engine.transaction(conn, on_error=f"改名集合 {collection_id} 失败"):
            conn.execute("UPDATE collections SET name=? WHERE id=?", (new_name, collection_id))
        return self.get(collection_id)

    def update_query(self, collection_id: int, query: dict) -> Collection:
        """更新集合的查询条件。"""
        query_json = json.dumps(query, ensure_ascii=False, sort_keys=True)
        conn = self.engine.thread_connection()
        with self.engine.transaction(conn, on_error=f"更新集合 {collection_id} 失败"):
            conn.execute("UPDATE collections SET query_json=? WHERE id=?", (query_json, collection_id))
        return self.get(collection_id)

    def delete(self, collection_id: int) -> None:
        conn = self.engine.thread_connection()
        with self.engine.transaction(conn, on_error=f"删除集合 {collection_id} 失败"):
            conn.execute("DELETE FROM collections WHERE id=?", (collection_id,))

    def count(self) -> int:
        return self.engine.thread_connection().execute("SELECT count(*) FROM collections").fetchone()[0]
