"""0001 · 首版表结构。

严格照 docs/DATABASE 二 的口径实现，只有两处是阶段 1 的有意取舍，写在文件末尾的注释里。
"""
from __future__ import annotations

VERSION = 1

# 路径类列一律 COLLATE NOCASE：p7 实测同一文件的大小写变体必须撞唯一索引。
DOCUMENTS = """
CREATE TABLE documents(
  id                   INTEGER PRIMARY KEY,
  path                 TEXT NOT NULL,
  path_key             TEXT NOT NULL COLLATE NOCASE,
  volume_id            TEXT,
  file_id              INTEGER,
  name                 TEXT NOT NULL,
  ext                  TEXT NOT NULL,
  size_bytes           INTEGER NOT NULL,
  mtime_ns             INTEGER NOT NULL,
  ctime_ns             INTEGER,
  sha256               TEXT,
  page_count           INTEGER,
  pdf_version          TEXT,
  is_pdf               INTEGER NOT NULL DEFAULT 1,
  is_encrypted         INTEGER NOT NULL DEFAULT 0,
  needs_pass           INTEGER NOT NULL DEFAULT 0,
  is_repaired          INTEGER NOT NULL DEFAULT 0,
  parse_status         TEXT NOT NULL DEFAULT 'pending',
  text_status          TEXT NOT NULL DEFAULT 'pending',
  ocr_status           TEXT NOT NULL DEFAULT 'na',
  fts_status           TEXT NOT NULL DEFAULT 'pending',
  vector_status        TEXT NOT NULL DEFAULT 'na',
  category_confirmed   INTEGER NOT NULL DEFAULT 0,
  last_scanned_at      INTEGER,
  last_indexed_at      INTEGER,
  last_error           TEXT,
  missing_since        INTEGER,
  created_at           INTEGER NOT NULL,
  updated_at           INTEGER NOT NULL
)
"""

MONITORED_ROOTS = """
CREATE TABLE monitored_roots(
  id                 INTEGER PRIMARY KEY,
  root_path          TEXT NOT NULL,
  root_key           TEXT NOT NULL COLLATE NOCASE,
  label              TEXT,
  enabled            INTEGER NOT NULL DEFAULT 1,
  exclude_globs      TEXT NOT NULL DEFAULT '[]',
  last_full_scan_at  INTEGER,
  last_scan_error    TEXT,
  created_at         INTEGER NOT NULL,
  updated_at         INTEGER NOT NULL
)
"""

# SPEC 3.3：分类树不许写死在代码里 —— 这里只建容器，默认模板由 services 层作为"数据"种下去。
CATEGORIES = """
CREATE TABLE categories(
  id          INTEGER PRIMARY KEY,
  name        TEXT NOT NULL,
  parent_id   INTEGER REFERENCES categories(id) ON DELETE CASCADE,
  name_path   TEXT NOT NULL,
  note        TEXT,
  created_at  INTEGER NOT NULL,
  updated_at  INTEGER NOT NULL
)
"""
CATEGORIES_IDX = [
    "CREATE UNIQUE INDEX ux_categories_parent_name ON categories(parent_id, name COLLATE NOCASE)",
    "CREATE INDEX ix_categories_name_path ON categories(name_path)",
]

DOCUMENT_CATEGORIES = """
CREATE TABLE document_categories(
  doc_id      INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  category_id INTEGER NOT NULL REFERENCES categories(id) ON DELETE CASCADE,
  origin      TEXT NOT NULL DEFAULT 'manual',
  confirmed   INTEGER NOT NULL DEFAULT 1,
  added_at    INTEGER NOT NULL,
  PRIMARY KEY (doc_id, category_id)
)
"""

TAGS = """
CREATE TABLE tags(
  id          INTEGER PRIMARY KEY,
  name        TEXT NOT NULL COLLATE NOCASE,
  color       TEXT,
  note        TEXT,
  created_at  INTEGER NOT NULL
)
"""
TAGS_IDX = ["CREATE UNIQUE INDEX ux_tags_name ON tags(name)"]

DOCUMENT_TAGS = """
CREATE TABLE document_tags(
  doc_id     INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  tag_id     INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
  origin     TEXT NOT NULL DEFAULT 'manual',
  confirmed  INTEGER NOT NULL DEFAULT 1,
  added_at   INTEGER NOT NULL,
  PRIMARY KEY (doc_id, tag_id)
)
"""

DOCUMENT_METADATA = """
CREATE TABLE document_metadata(
  doc_id          INTEGER PRIMARY KEY REFERENCES documents(id) ON DELETE CASCADE,
  title           TEXT,
  author          TEXT,
  subject         TEXT,
  creator_tool    TEXT,
  producer        TEXT,
  pdf_created_at  TEXT,
  pdf_modified_at TEXT,
  keywords        TEXT,
  language        TEXT,
  source          TEXT NOT NULL DEFAULT 'pdf_info'
)
"""

COLLECTIONS = """
CREATE TABLE collections(
  id           INTEGER PRIMARY KEY,
  name         TEXT NOT NULL COLLATE NOCASE,
  query_json   TEXT NOT NULL,
  note         TEXT,
  created_at   INTEGER NOT NULL,
  updated_at   INTEGER NOT NULL
)
"""

PROCESSING_JOBS = """
CREATE TABLE processing_jobs(
  id           INTEGER PRIMARY KEY,
  kind         TEXT NOT NULL,
  doc_id       INTEGER REFERENCES documents(id) ON DELETE CASCADE,
  state        TEXT NOT NULL,
  priority     INTEGER NOT NULL DEFAULT 5,
  attempts     INTEGER NOT NULL DEFAULT 0,
  progress     REAL NOT NULL DEFAULT 0,
  total        INTEGER,
  done         INTEGER NOT NULL DEFAULT 0,
  last_error   TEXT,
  created_at   INTEGER NOT NULL,
  started_at   INTEGER,
  finished_at  INTEGER
)
"""
PROCESSING_JOBS_IDX = [
    "CREATE INDEX ix_jobs_state_kind ON processing_jobs(state, kind)",
    "CREATE INDEX ix_jobs_doc ON processing_jobs(doc_id)",
]

FILE_OPERATIONS = """
CREATE TABLE file_operations(
  id             INTEGER PRIMARY KEY,
  kind           TEXT NOT NULL,
  status         TEXT NOT NULL,
  plan_json      TEXT,
  journal_path   TEXT,
  items_total    INTEGER NOT NULL DEFAULT 0,
  items_done     INTEGER NOT NULL DEFAULT 0,
  items_failed   INTEGER NOT NULL DEFAULT 0,
  undo_of        INTEGER REFERENCES file_operations(id),
  created_at     INTEGER NOT NULL,
  started_at     INTEGER,
  finished_at    INTEGER
)
"""

OPERATION_ITEMS = """
CREATE TABLE operation_items(
  id           INTEGER PRIMARY KEY,
  op_id        INTEGER NOT NULL REFERENCES file_operations(id) ON DELETE CASCADE,
  doc_id       INTEGER REFERENCES documents(id) ON DELETE SET NULL,
  kind         TEXT NOT NULL,
  src_path     TEXT NOT NULL,
  dst_path     TEXT,
  state        TEXT NOT NULL DEFAULT 'pending',
  reversible   INTEGER NOT NULL DEFAULT 1,
  error        TEXT,
  src_sha256   TEXT,
  dst_sha256   TEXT,
  updated_at   INTEGER NOT NULL
)
"""
OPERATION_ITEMS_IDX = ["CREATE INDEX ix_items_op_state ON operation_items(op_id, state)"]

APP_SETTINGS = """
CREATE TABLE app_settings(
  key         TEXT PRIMARY KEY,
  value_json  TEXT NOT NULL,
  kind        TEXT NOT NULL DEFAULT 'ui',
  updated_at  INTEGER NOT NULL
)
"""


def apply(conn) -> None:  # noqa: ANN001 - sqlite3.Connection，不 import 类型以免多一层依赖
    """建首版全部表。整个函数在调用方的一个事务里执行，中途失败一起回滚。"""
    statements: list[str] = [
        DOCUMENTS,
        "CREATE UNIQUE INDEX ux_documents_path_key ON documents(path_key)",
        "CREATE INDEX ix_documents_sha ON documents(sha256)",
        "CREATE INDEX ix_documents_missing ON documents(missing_since) WHERE missing_since IS NOT NULL",
        MONITORED_ROOTS,
        "CREATE UNIQUE INDEX ux_roots_key ON monitored_roots(root_key)",
        CATEGORIES,
        *CATEGORIES_IDX,
        DOCUMENT_CATEGORIES,
        TAGS,
        *TAGS_IDX,
        DOCUMENT_TAGS,
        DOCUMENT_METADATA,
        COLLECTIONS,
        "CREATE UNIQUE INDEX ux_collections_name ON collections(name)",
        PROCESSING_JOBS,
        *PROCESSING_JOBS_IDX,
        FILE_OPERATIONS,
        OPERATION_ITEMS,
        *OPERATION_ITEMS_IDX,
        APP_SETTINGS,
    ]
    for sql in statements:
        conn.execute(sql)


# 阶段 1 的三处有意取舍，不是遗漏：
# 1. 不建 text_pages / content_fts —— 分词器选型是 Q1、索引体积策略是 Q2，两题未答，
#    现在建了阶段 2 就得返工；它们作为迁移 0002 进去。
# 2. 不建 duplicate_groups —— 重复检测在阶段 4，届时按实测再定分组口径。
# 3. `app_settings` 只存**应用内部状态**（阅读历史、列宽、上次筛选）。用户配置的唯一口径仍是
#    `config/settings.json`（docs/ARCHITECTURE 一）—— 同一个概念不许有两个存放处。
