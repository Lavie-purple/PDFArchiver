"""0002 · 正文与全文索引表（阶段 2）。

这是本项目第一次**在带着数据的库上**加结构，所以每一句都受 `tests/guards/test_migrations.py`
的"旧库升级后行数一条不丢"约束：只加表、加列、加触发器，**不 ALTER 任何已有列、不删任何东西**。

三条口径写在这里，改结构前先看它们：

1. `text_pages.rowid` 用 `INTEGER PRIMARY KEY` 直接当 rowid 别名 —— FTS5 外部内容表
   只能指向同库同连接里有 rowid 的表（p1 实测）。`doc_id/page_no` 用唯一索引保证一页只有一行。
2. `content_fts` 是**外部内容表**（`content='text_pages'`），索引本体存 token，正文只有一份。
   代价是三条触发器必须写全，且 `'delete'` 命令必须带上 `old.body`（docs/DATABASE 三，
   p1 `delete_trigger_trap` 实测：漏列**不报错**，只留下删不掉的幽灵行）。
3. `tokenize='trigram'`：p1 实测 `unicode61` 对中文命中 **0**，trigram 对 ≥3 字查询 6.39ms。
   1–2 字查询 trigram 召不回，由 `search` 层显式退回 LIKE 并在结果里标注口径（D-004 / D-015）。

分词器与"是否分库存放"是两条**未拍板**的假设（Q1 / Q2 / D-025），见 docs/RISKS 2.1、2.9。
"""
from __future__ import annotations

VERSION = 2

# 重命名采纳要靠 (device, file_id, size, mtime) 四元组判断"同一个文件换了路径"，
# 而 file_id(st_ino) 只在一块卷内唯一 —— 必须连 device 一起存，否则跨盘同名同 inode 会误判。
DOCUMENTS_COLUMNS = [
    ("device_id", "INTEGER"),
    # text_bearing_rate = 有正文页占抽样页的比例，是"这份是不是扫描件"的唯一口径（与 p2 探针同算法）。
    # 阶段 3 的阅读器与阶段 5 的 OCR 都靠它决定要不要显示"未检索正文"，所以必须落库而不是每次重算。
    ("text_bearing_rate", "REAL"),
]

TEXT_PAGES = """
CREATE TABLE text_pages(
  rowid        INTEGER PRIMARY KEY,
  doc_id       INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  page_no      INTEGER NOT NULL,
  source_kind  TEXT NOT NULL DEFAULT 'native',
  char_count   INTEGER NOT NULL,
  body         TEXT NOT NULL,
  indexed_at   INTEGER NOT NULL
)
"""
TEXT_PAGES_IDX = [
    "CREATE UNIQUE INDEX ux_text_pages_doc_page ON text_pages(doc_id, page_no)",
]

CONTENT_FTS = """
CREATE VIRTUAL TABLE content_fts USING fts5(
  body,
  content='text_pages',
  content_rowid='rowid',
  tokenize='trigram'
)
"""

# 三条触发器，一条都不能少。'delete' 命令的列清单必须与建表时的索引列完全一致。
TRIGGERS = [
    """
CREATE TRIGGER tx_pages_ai AFTER INSERT ON text_pages BEGIN
  INSERT INTO content_fts(rowid, body) VALUES (new.rowid, new.body);
END
""",
    """
CREATE TRIGGER tx_pages_ad AFTER DELETE ON text_pages BEGIN
  INSERT INTO content_fts(content_fts, rowid, body) VALUES ('delete', old.rowid, old.body);
END
""",
    """
CREATE TRIGGER tx_pages_au AFTER UPDATE ON text_pages BEGIN
  INSERT INTO content_fts(content_fts, rowid, body) VALUES ('delete', old.rowid, old.body);
  INSERT INTO content_fts(rowid, body) VALUES (new.rowid, new.body);
END
""",
]


def apply(conn) -> None:  # noqa: ANN001 - sqlite3.Connection，不 import 类型以免多一层依赖
    """整个函数在调用方的一个事务里执行：中途失败就整体回滚，库回到 0001。"""
    for name, sql_type in DOCUMENTS_COLUMNS:
        conn.execute(f"ALTER TABLE documents ADD COLUMN {name} {sql_type}")
    statements = [TEXT_PAGES, *TEXT_PAGES_IDX, CONTENT_FTS, *TRIGGERS]
    for sql in statements:
        conn.execute(sql)


# 本迁移**故意不做**的两件事，免得被当成遗漏：
# 1. 不建 `duplicate_groups` —— 重复检测在阶段 4，分组口径（按 sha256 还是按内容相似）届时按实测再定。
# 2. 不把 `text_pages` / `content_fts` 拆到单独的 `content.db` —— 见 D-025：外部内容表与内容表
#    必须同库，分库要把迁移执行器改成多库水位，收益到阶段 4 备份才体现。当前用
#    `indexing.rebuild_all()` 在**行级**提供"索引删掉重建"的等价能力（G10 断言幽灵行 = 0）。
