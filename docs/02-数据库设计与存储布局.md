# 数据库设计与存储布局

覆盖 SPEC 第 5、6、7 项：数据模型、迁移机制、文件身份与路径规则、文件操作与恢复、存储关系。

## 一 · 存储布局：什么放哪、能不能丢

数据根目录默认 `%LOCALAPPDATA%\PdfArchiver\`（与用户 PDF 分离，SPEC 3.8）。

```
%LOCALAPPDATA%\PdfArchiver\
  data\
    catalog.db          主库：文档主记录、元数据、分类、标签、集合、任务、操作日志
    catalog.db-wal      运行期存在，退出/检查点后消失
    content.db          FTS5 全文索引（外部内容表指向 catalog.db 的 text_pages）
    vectors.bin         语义向量索引（semantic 层私有；可整目录删除后重建）
    cache\              渲染缩略图等可再生缓存
  config\settings.json  用户设置
  logs\                 app.log / crash.log / state.log
  models\               按需下载的模型（embedding）；OCR 模型随程序包，不在此处
```

分类原则 —— **每个文件属于哪一档，决定备份和丢失后果**：

| 档 | 内容 | 丢了会怎样 | 备份策略 |
| --- | --- | --- | --- |
| A 不可再生 | 用户 PDF 本体 | 真损失 | **本程序不备份用户 PDF**，只提示 |
| B 难再生 | `catalog.db` 的人工成果：分类确认、标签、集合、归档映射 | 要重做人工标注 | 备份必须包含；用 SQLite Backup API 一致性快照 |
| C 可再生 | `content.db` 全文索引、`text_pages` 正文、OCR 文本 | 重扫一遍（OCR 极贵，见下） | 默认不纳入备份，可选项 |
| D 纯缓存 | `cache\`、缩略图 | 无所谓 | 不备份 |

**OCR 结果虽然理论可再生，但实测代价是 P5 孤跑的 1,144 小时（DirectML，101 万页全量）／7,278 小时（CPU），
按每天 8 小时无人值守算是 143 个工作日，事实上不可再生。**
所以 `text_pages(source_kind='ocr')` 在备份档位上按 **B 类**处理，默认纳入备份。这是一条容易搞错的设计点。

## 二 · 表结构（首版）

命名保留 SPEC 4.2 给的表名。全部表带 `rowid` 主键；路径类字段一律 `COLLATE NOCASE`。

### 2.1 documents —— 文件身份与主记录

```sql
CREATE TABLE documents(
  id                INTEGER PRIMARY KEY,
  path              TEXT NOT NULL,              -- 规范化展示路径（realpath 结果，保留原大小写）
  path_key          TEXT NOT NULL COLLATE NOCASE,  -- 身份键 = path.casefold()
  volume_id         TEXT,                       -- 卷序列号（GetVolumeInformationEx）
  file_id           INTEGER,                    -- NTFS 文件 ID（os.stat().st_ino，实测可用）
  name              TEXT NOT NULL,
  ext               TEXT NOT NULL,
  size_bytes        INTEGER NOT NULL,
  mtime_ns          INTEGER NOT NULL,
  ctime_ns          INTEGER,
  sha256            TEXT,                       -- 惰性计算：只有去重/校验/归档时才算
  page_count        INTEGER,
  pdf_version       TEXT,
  is_pdf            INTEGER NOT NULL DEFAULT 1,
  is_encrypted      INTEGER NOT NULL DEFAULT 0,
  needs_pass        INTEGER NOT NULL DEFAULT 0,
  is_repaired       INTEGER NOT NULL DEFAULT 0,  -- 降级状态，不算成功（P2 实测要求）
  parse_status      TEXT NOT NULL,              -- ok | degraded | failed | pending
  text_status       TEXT NOT NULL,              -- none|native|ocr|mixed|pending|failed
  ocr_status        TEXT NOT NULL,              -- na|pending|running|done|failed|skipped
  fts_status        TEXT NOT NULL,              -- pending|running|done|failed|stale
  vector_status     TEXT NOT NULL,              -- na|pending|running|done|failed|stale
  category_confirmed INTEGER NOT NULL DEFAULT 0, -- AI 建议未经确认不得触发文件动作
  last_scanned_at   INTEGER,
  last_indexed_at   INTEGER,
  last_error        TEXT,
  missing_since     INTEGER,                    -- 文件不见了但记录保留（SPEC 3.2 路径非永久身份）
  created_at        INTEGER NOT NULL,
  updated_at        INTEGER NOT NULL
);
CREATE UNIQUE INDEX ux_documents_path_key ON documents(path_key);   -- 重叠根去重靠它（P7 已验证）
CREATE INDEX ix_documents_sha ON documents(sha256);                 -- 内容重复检测
CREATE INDEX ix_documents_missing ON documents(missing_since) WHERE missing_since IS NOT NULL;
```

**唯一口径**：一个规范化路径 = 一条主记录。多个监测根覆盖同一文件时靠 `ux_documents_path_key` 拒绝插入（P4/P7 实测：B 根重复扫插入 0 条、总数仍 3）。
同一内容出现在不同路径 = **多条记录 + 一条重复组**，绝不自动合并（SPEC 3.7）。

### 2.2 其余表（要点）

| 表 | 用途 | 关键约束/口径 |
| --- | --- | --- |
| `monitored_roots` | 监测根 | `root_key COLLATE NOCASE` 唯一；存 `enabled`、`last_full_scan_at`、排除规则外键 |
| `document_metadata` | PDF 元数据 1:1 | 字段缺失就留 NULL，**禁止编造**（SPEC 3.2）；带 `source` 标明来自 Info 还是文件名推断 |
| `categories` | 分类树 | `parent_id` 自引用；`name_path` 冗余列便于导出与筛选；不许代码里写死分类（SPEC 3.3） |
| `tags` / `document_tags` | 多标签 | 文档↔标签多对多 |
| `document_categories` | 文档↔分类 | 多对多；带 `origin`(manual\|ai) + `confirmed` |
| `text_pages` | 正文按页 | `(doc_id,page_no)` 主键；`source_kind` native\|ocr；`char_count`；**FTS 外部内容表指向它** |
| `content_fts` | FTS5 | `tokenize='trigram'`，`content='text_pages'`，配 3 个触发器（见 2.3） |
| `collections` | 智能集合 | 存**查询条件 JSON**，不复制文件（SPEC 3.3.5） |
| `file_operations` | 操作批次 | `status` planned\|previewed\|running\|partially_done\|done\|failed\|undone；`journal_path` |
| `operation_items` | 逐文件条目 | `src`/`dst`/`kind`(move\|rename\|copy)/`state` pending\|done\|failed\|skipped + `error` + `reversible` |
| `processing_jobs` | 任务队列 | `kind` scan\|index\|ocr\|vector\|archive；`state` queued\|running\|paused\|done\|failed\|cancelled；`attempts`、`progress` |
| `duplicate_groups` | 内容重复 | 按 `sha256` 分组；只报告不删除 |
| `app_settings` | 设置 | key/value + `schema_version` |
| `schema_version` | 迁移水位 | 单行；`version`、`applied_at` |

## 三 · FTS5 的正确接法（三条踩过坑的硬规则）

P1 探针实测出来的，写库前必须照做，否则索引悄悄错：

1. **外部内容表的列名必须与 content 表一致**。列名不一致时 `INSERT INTO fts(fts) VALUES('rebuild')`
   直接 `SQL logic error`。（我们曾因此把 `text` 改名 `body`。）
2. **必须建齐 AFTER INSERT / UPDATE / DELETE 三个触发器**，否则正文改了索引不动。
3. **`'delete'` 命令必须带上被索引列的旧值**：
   ```sql
   INSERT INTO content_fts(content_fts, rowid, body) VALUES('delete', old.rowid, old.body);
   ```
   漏掉 `old.body` 时 SQLite **不报错**，但索引里留着幽灵行 —— 删除的文件永远还能被搜到。
   P1 的 `delete_trigger_trap` 就是专门证这个：错误写法下删除后仍命中 1 条，而内容表已 0 行。

另外两条口径：
- `offsets()` 在 FTS5 **不存在**（实测 `pragma_function_list` 只有 `rank/snippet/bm25/highlight`）。
  页码靠 `text_pages` 的行本身定位，片段高亮位置在 Python 侧算。
- trigram 分词对 1–2 字查询召回差，索引层对短查询**退回 LIKE**，并在结果里标明用了哪种口径（P1 实测已按此实现）。

## 四 · 迁移机制

- `db/migrations/` 下按 `0001_initial.py`、`0002_...` 顺序编号，每个导出 `VERSION` 和 `apply(conn)`。
- 启动时读 `schema_version`，只跑未应用的迁移；**每个迁移自带备份前置检查**：迁移前强制做一次
  SQLite Backup API 快照到 `data\backups\pre-migration-<version>-<ts>.db`，失败可回退。
- 禁止"改结构就让用户删库重来"（SPEC 4.2 明确要求）。
- 守卫测试：`tests/guards/test_migrations.py` 用旧版本库跑一遍全量迁移，断言迁移后
  `PRAGMA integrity_check` = ok 且行数不丢。

## 五 · 文件操作：预览 / 执行 / 日志 / 恢复 / 撤销

SPEC 3.6 的要求，按"事务回滚 ≠ 磁盘回滚"来实现。

### 5.1 生命周期

```
plan(纯计算)  →  preview(UI)  →  [用户确认]  →  journal 落盘  →  execute 逐项
      ↓                                                              ↓
  不碰磁盘                                                   每项立刻回写状态
                                                                   ↓
                                       undo plan(可选) ← 完成/部分失败/中断
```

- **plan 阶段绝不打开、绝不写、绝不 rename**。`tests/integration/test_archive_preview.py`
  断言预览前后整个目录的 `mtime` 集合完全不变 —— 预览唯一能被证伪的方式就是这个。
- **未确认绝不执行**：`file_operations.status` 从 `previewed` 到 `running` 必须有显式用户确认调用。

### 5.2 journal（崩溃恢复的依据）

执行前把整个计划写成 JSONL，一行一项，**先写日志再动文件**：

```json
{"op_id":123,"item":7,"action":"move","src":"H:/a.pdf","dst":"F:/归档/2026/a.pdf",
 "src_size":1024,"src_mtime_ns":...,"src_sha256":"...","state":"pending"}
```

状态机：`pending → copying → src_verified → dst_written → dst_verified → src_removed → done`
每步都要 `fsync` 后回写。**只有 `dst_verified` 成功之后才允许删源**（SPEC 3.6 跨盘要求）。

- 程序启动时扫 `status IN ('running','previewed')` 的批次，读 journal 找不一致项：
  - 源在、目标不在 → 回到 `pending`，可安全重跑
  - 源在、目标在且哈希相同 → 记 `orphan_dst`，交用户判断（不自动删任何一边）
  - 源不在、目标在且哈希相同 → 记 `done`
  - 两边都不在 → 标 `lost`，**红色上报**，绝不静默
- 磁盘空间：执行前按待复制总量查 `shutil.disk_usage`，不足直接拒绝并说明差多少。

### 5.3 撤销

- 只有 `reversible=1` 的项进撤销计划（跨盘复制后删源 = 可逆；覆盖已有同名文件 = **不可逆**，
  默认拒绝，或先备份目标再动）。
- 撤销是**另开一个 `file_operations` 批次**，方向取反，同样走 journal。
- 撤销后必须回到"先全量哈希校验，再更新数据库"的顺序，不允许只改库不验盘。

## 六 · 备份与恢复

- 备份用 `sqlite3.Connection.backup()`（P1 实测：产出独立文件、`integrity_check` ok、行数一致），
  **不是**复制 `.db` 文件（WAL 下会备份到不一致状态）。
- 备份包内容：`catalog.db` 快照 + `settings.json` + `file_operations` 历史 + OCR 文本（B 类）+ 清单文件
  （时间、schema_version、文档数、页数、文本字节数、OCR 页数）。
- 恢复流程：校验清单 → 落到新目录 → 跑 `integrity_check` → **强制"重新校验文件"**：
  逐条比对记录里的路径/大小/mtime，失效路径进 `missing_since`，交用户重新定位而不是删记录。
- 迁移到新机器：`content.db` 与 `vectors.bin` 默认不带走，在新机重建（C 类）；
  但提供"连 OCR 文本一起带走"的开关，因为 OCR 重建代价是几百小时（P5）。
