"""0007 · 把 `vector_meta` 收进迁移链 + 删 `documents.pdf_version` 死列（ISSUES I62 的"甲"）。

两件事各自为什么：

**① 建 `vector_meta` 与 `ix_vector_meta_doc`。** 阶段 6 落地时这张表是由
`semantic/vector_store.py` 在**运行时** `CREATE TABLE IF NOT EXISTS` 建出来的，于是：
- 空库首迁后的 `sqlite_master` 是 19 张表，而"跑过语义搜索的人"的库是 20 张 ——
  同一个版本号对应两种库形状，`docs/DATABASE.md` §2.5 那条"表数只有一个口径"直接被破；
- 老产物（不认识 `vector_meta` 的构建）打开新库没影响，但**新产物打开只按迁移链建出来的库**时，
  表要等第一次跑到 `VectorStore` 才存在，中途任何按表查询都会撞 `no such table`。
所以结构变更只能是一条迁移（`docs/DATABASE.md` 四），由
`tests/guards/test_schema_columns.py` 规则 B 钉住：迁移目录之外不许出现 DDL。

DDL 与 `vector_store.py` 原来那段**逐字一致**（列、约束、索引名都不变），并用
`IF NOT EXISTS` —— 已经用运行时建过表的现存库（包括开发机这份真实库）碰 0007 必须是**无操作**，
不能报错，也不该重建一张空表把已有向量元数据清掉。

**② 删 `documents.pdf_version`。** 与 0006 删 `volume_id` 同一族（**ISSUES I40** 的复发形状）：
0001 建了列，`parsing/pdf.py` 也确实从 PDF 的 `metadata['format']` 读出了值，
但**全项目没有任何一处把它写进库或从库里读出来** —— 列恒 NULL，`PdfInfo.pdf_version` 那个字段
同样零引用。留着只会让下一个开发者照 `DATABASE.md` 以为库里有 PDF 版本可读。
用户已决定删（不实现"把 PDF 版本落库"），同 0006 的处置口径。

`ALTER TABLE … DROP COLUMN` 需要 SQLite ≥ 3.35（本机 sqlite3 模块实测 3.41.2，0006 已在用）。
"""
from __future__ import annotations

VERSION = 7


def apply(conn) -> None:  # noqa: ANN001 - sqlite3.Connection，不 import 类型以免多一层依赖
    """整个函数在调用方的一个事务里执行：中途失败整体回滚，库回到 0006。"""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS vector_meta (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            doc_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
            page_no INTEGER NOT NULL,
            vector_idx INTEGER NOT NULL UNIQUE,
            UNIQUE(doc_id, page_no)
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS ix_vector_meta_doc ON vector_meta(doc_id)")
    conn.execute("ALTER TABLE documents DROP COLUMN pdf_version")


def rollback(conn) -> None:
    """回到 0006：加回 pdf_version（值已丢，只能留 NULL），并把 0007 建的表与索引撤掉。

    与 0006 一样，这条**只由人手动执行**（迁移执行器只往前不往后，见 `db/migrate.py` 规矩 3）。
    删表会连向量元数据一起丢，所以先确认 `vector_meta` 是不是真有人要回退到没有它的版本。
    """
    conn.execute("DROP INDEX IF EXISTS ix_vector_meta_doc")
    conn.execute("DROP TABLE IF EXISTS vector_meta")
    conn.execute("ALTER TABLE documents ADD COLUMN pdf_version TEXT")
