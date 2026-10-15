# 数据库设计与存储布局

覆盖 SPEC 第 5、6、7 项：数据模型、迁移机制、文件身份与路径规则、文件操作与恢复、存储关系。

## 一 · 存储布局：什么放哪、能不能丢

数据根目录：显式 `--data-dir` > 环境变量 `PDFARCHIVER_DATA_DIR` > `%LOCALAPPDATA%\PdfArchiver\`
（与用户 PDF 分离，SPEC 3.8；非 Windows 走 `XDG_DATA_HOME` / `~/.local/share`）。
**没有一处写死的盘符**，来源会打印在日志、状态栏和状态页上（`AppPaths.describe()`）。

阶段 1 实际建出来的目录树（`AppPaths.mkdirs()`，5 个；★ = 阶段 1 已有真实内容）：

```
<数据根>\
  data\★
    catalog.db★         主库：0001 的 12 张表（documents / monitored_roots / categories / document_categories /
                        tags / document_tags / document_metadata / collections / processing_jobs /
                        file_operations / operation_items / app_settings）+ `schema_version` 水位表（由 `migrate.py` 建）
                        + 0002 的 `text_pages` + 0002 的 FTS5 虚表 `content_fts`
    backups\★           迁移前的 Backup API 一致性快照 pre-migration-NNNN-<ts>.db
    cache\★             空着 —— 渲染缩略图缓存属阶段 3
    ~~content.db~~      **不建这个文件**：0002 落地时全文索引进了 `catalog.db` 本体（D-024，理由见 docs/DECISIONS）
    vectors.bin         语义向量索引（semantic 层私有；可整目录删除后重建）**未建，阶段 6**
  config\settings.json★ 用户设置（唯一口径，见 D-019；应用内部状态一律进 app_settings 表，不放这里）
  logs\★                app.log（轮转）/ crash.log（未捕获+线程异常）/ state.log（一行一条 JSON 对账）
  models\               按需下载的模型（embedding）；OCR 模型随程序包。**阶段 1 不建这个目录**
```

`catalog.db-wal` / `-shm` 运行期存在，干净退出后消失 —— 看到它们不代表库坏了。
迁移失败留下的快照**只增不删**，回退靠它（`docs/DATABASE` 四）。

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
  volume_id         TEXT,                       -- ⚠️ **死列**：0001 建了它，但全项目代码零读写，恒 NULL。
                                              --   判"同盘/跨盘"用 0002 加的 `device_id`（`os.stat().st_dev`，盘符级）；
                                              --   卷序列号这条路**没实现**，要用就先实现再改口径（ISSUES I40）
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
| `text_pages` | 正文按页 | `(doc_id,page_no)` **唯一索引**（rowid 另用，见 2.3）；`source_kind` native\|ocr；`char_count`；**FTS 外部内容表指向它**；只有 `index_service` 一处写 |
| `content_fts` | FTS5 | `tokenize='trigram'`，`content='text_pages'`，配 3 个触发器（实际形状见 2.3，硬规则见第三节） |
| `collections` | 智能集合 | 存**查询条件 JSON**，不复制文件（SPEC 3.3.5） |
| `file_operations` | 操作批次 | `status` planned\|previewed\|running\|partially_done\|done\|failed\|undone；`journal_path` |
| `operation_items` | 逐文件条目 | `src`/`dst`/`kind`(move\|rename\|copy)/`state` pending\|done\|failed\|skipped + `error` + `reversible` |
| `processing_jobs` | 任务队列 | `kind` scan\|index\|ocr\|vector\|archive；`state` queued\|running\|paused\|done\|failed\|cancelled；`attempts`、`progress` |
| `duplicate_groups` | 内容重复 —— **故意不建**（阶段 4 再定分组口径） | 设计意图是「按 `sha256` 分组；只报告不删除」，但**库里没有这张表**：`0001_initial.py:235` 与 `0002_text_and_fts.py:86` 两处注释明写不建，断言 `test_阶段1刻意不建的表确实不存在` 反向钉住。在此之前去重读取**只许** `GROUP BY sha256` 现算现查（走 `ix_documents_sha`，见 `docs/UI-WIREFRAMES.md` §S5）；要建它必须走**第 4 条迁移**（`VERSION = 4`），不许运行时 `ALTER` —— 出处 **ISSUES I44** |
| `app_settings` | **应用内部状态**（导航记忆、列宽、"默认模板已种过"标记） | key/value，value 存 JSON。**不存用户设置** —— 用户设置唯一口径是 `config/settings.json`（D-019）。坏 JSON 回落默认值但必须留 warning，不许静默 |
| `schema_version` | 迁移水位 | 单行；`version`、`applied_at` |

### 2.3 迁移 0002 实际落地的差异（以实现为准，不是设计稿）

0002 是第一次**在带数据的库上加结构**（`src/pdfarchiver/db/migrations/0002_text_and_fts.py`）。
与上面"首版设计"的三处差异，都是被硬约束逼出来的，改结构前先读它们：

| 项 | 首版设计 | 实际落地 | 为什么 |
| --- | --- | --- | --- |
| `text_pages` 主键 | `(doc_id,page_no)` 主键 | `rowid INTEGER PRIMARY KEY`（rowid 别名）+ **唯一索引** `ux_text_pages_doc_page(doc_id,page_no)` | FTS5 外部内容表只能指向**同库同连接里有 rowid 的表**（p1 实测）。表约束没少，只是换了表达方式 |
| `documents` 加列 | — | `device_id`、`text_bearing_rate` | 改名采纳要靠 device+file_id+size+mtime 四元组，`file_id(st_ino)` 只在单卷内唯一；`text_bearing_rate` 是"这份是不是扫描件"的**唯一口径**（与 p2 探针同算法），阅读器与 OCR 都读它，所以落库而不是每次重算 |
| 触发器 | "配 3 个触发器" | `tx_pages_ai` / `tx_pages_ad` / `tx_pages_au`，`'delete'` 命令带 `old.body` | 第三节硬规则 3；漏列**不报错**，只留幽灵行 |

**`fts_status` 的写入口径（阶段 2 定的，改索引链路前必须知道）**：
这一列只用 `pending` / `stale` → `done` / `failed` 四个值，**从不写 `running`**。
"任务在不在跑"由 `processing_jobs` 那一行说，它是进程内状态；把"正在索引"抄进文档表，
就造出一个"进程一崩就永远出不来"的状态 —— 重启后既没人当它未完成（`NEEDS_INDEX_STATUSES` 里没有它），
也没人当它完成。现在崩溃时文档仍停在 `pending`/`stale`，`resume_pending()` 自然把它捞回来。
**唯一口径**：`documents.NEEDS_INDEX_STATUSES = ("pending","stale")`，扫描侧、重启侧、状态页三处都读这一份。

**`processing_jobs.progress` 的口径**：由 `ProgressMonitor` 按 `PROGRESS_STEP_PAGES=64` 攒着写，
终态补齐在 `JobRepository.succeed()` 里做（`done=total`、`progress=1.0`、清 `last_error`），
不靠处理函数记得 `flush()`。见 D-025。

### 2.4 迁移 0003 实际落地的差异（阶段 5，`0003_ocr_tracking.py`）

只做**加列**，不建新表（你在阶段 5 决策 4 勾选「甲 · 加列」）：

| 列 | 类型 | 谁写 | 唯一口径 |
| --- | --- | --- | --- |
| `text_pages.ocr_version` | `TEXT`，原生页留 `NULL` | `OcrService._record_page()` 逐页写 | **幂等的唯一判据**：`rapidocr-onnxruntime/<ver>+onnxruntime/<ver>+dpi<dpi>`，**故意不含 provider**（D-029）。`NULL` 与 `''` 是两件事：前者"没跑过 OCR"，后者不存在 |
| `documents.ocr_pages_done` | `INTEGER NOT NULL DEFAULT 0` | 每次识别收尾 | **计数不是状态**。状态只有一个口径 = `documents.ocr_status`（取值见 `parsing/classify.OCR_STATUSES`）。这一列不参与任何流转判定，只供状态页读数 |
| `documents.last_ocr_at` | `INTEGER` | 同上 | 列名跟着既有 `last_scanned_at` / `last_indexed_at` 走，不起第三个名字 |

**刻意没加的两样**（都不是遗漏，改结构前先读 `0003_ocr_tracking.py` 的模块文档）：
- 不给 `ocr_status` 建部分索引：待 OCR 的文档在真实语料上是千级（p0 实测 7,768 份），
  `COUNT(*) WHERE ocr_status='pending'` 全表扫几毫秒，为一个几毫秒的读加写放大不值；
- **不加"OCR 置信度"列**：p5 实测 RapidOCR 只给行文本，**逐行分数没被验证过能不能横向比较**，
  把一个没验证过的分数写进事实层就等于凭空编指标（SPEC 五）。

**升级证据**：`tests/guards/test_migrations.py` 的真实迁移链一路跑到 `version=3`
（`applied == ["0002_text_and_fts", "0003_ocr_tracking"]`），并有一条专门盯 0003 的假值问题：
`test_真实0003加列后老行的OCR列是空而不是假值` —— 老行的 `ocr_version` 必须是 `NULL`，
写成 `''` 或 `'unknown'` 都会让那一份在下次点名时被误判"已经跑过"。
`tests/integration/test_bootstrap_and_migration.py` 另有一份**列清单**（0003 只加列不加表）钉住新库建到 version=3。
每日页预算的**已用页数**不进 `documents`，进 `app_settings`（内部状态，D-019/D-032）——
它是"今天跑了多少"，不是"这份文档的财产"。

### 2.5 表数只有一个口径（2026-10-15 补，ISSUES I44）

"现在有几张表"在文档里出现过 **12 / 13** 两个数说同一件事（`docs/ARCHITECTURE.md` 一 与 `docs/DATABASE.md` 四 曾写
"`0001_initial` 13 张表"，而本节一 的存储布局写"0001 的 12 张表"），AGENTS.md 禁止核心概念多口径，所以定死：

| 口径 | 数 | 怎么来的（可现跑复算，不许抄旧数） |
| --- | --- | --- |
| 迁移文件里的 `CREATE TABLE` | 0001 = **12**、0002 = **1**（`text_pages`）+ 1 张 FTS5 虚表 `content_fts`、0003 = **0** | `grep -c CREATE TABLE src/pdfarchiver/db/migrations/*.py` |
| 空库首启后的"表" | 阶段 1 当时报的 **13** = 上面 12 张 + `schema_version` | `schema_version` 由 `db/migrate.py:20` 的 `SCHEMA_TABLE` 建，**不在任何迁移文件里** |
| 当前 `sqlite_master` 里 `type='table'` 且非 `sqlite_%` | **19** | = 内容表 14（含 `content_fts`）+ `schema_version` + FTS5 自动建的 4 张影子表 `content_fts_config / _data / _docsize / _idx` |

**写法规矩**：说"首版几张表"一律带上面哪一行；说"现有几张表"必须现跑现数并写明 `sqlite_master` 那个口径；
历史阶段报告里的 13 是**它自己时点的读数**，不改写，但今后新文档不许再把它当成当前数。

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
   **这一种坏法恰好是所有"免词口径"唯一看不见的那一种** —— 漏列的 `'delete'` 会把
   `content_fts_docsize` 里那行删掉，倒排里那条却还挂着，所以 `count(*)`、`NOT IN`、docsize 双向
   四个数全都很干净；能看见它的只有**带词的 `MATCH`**（`MATCH` 命中数 vs `MATCH` 再 JOIN 正文表）。
   五种口径对四种坏法的可见性由 `tests/probes/p14_fts_instrument.py` 每次重测（台账 **I8**），
   `'integrity-check'` 在那四种坏状态下全部"通过"、也不改动文件，**不许拿它当检查**。

另外两条口径：
- `offsets()` 在 FTS5 **不存在**（实测 `pragma_function_list` 只有 `rank/snippet/bm25/highlight`）。
  页码靠 `text_pages` 的行本身定位，片段高亮位置在 Python 侧算。
- trigram 分词对 1–2 字查询召回差，索引层对短查询**退回 LIKE**，并在结果里标明用了哪种口径（P1 实测已按此实现）。

## 四 · 迁移机制（阶段 1 已落地）

本节是**实现细节的唯一存放处**；为什么这样选、否掉了哪些方案（alembic / 内嵌 SQL 数组 / 失败后拿备份恢复）
登记在 `DECISIONS.md` **D-023**，两边改其一必须同步另一处。

- `db/migrations/` 下按 `0001_initial.py`、`0002_...` 顺序编号，每个导出 `VERSION` 和 `apply(conn)`。
  发现方式是 `importlib` **按路径加载**（模块名以数字开头不能 `import`），文件名不合 `NNNN_slug.py`、
  `VERSION` 与文件名序号不一致、序号重复 —— 三种情况都直接抛 `ValueError`，不"尽量解释一下"。
- 启动时读 `schema_version`（单行水位：`version` + `applied_at`），只跑未应用的迁移；
  **迁移前强制**做一次 SQLite Backup API 快照到 `backups/pre-migration-<NNNN>-<ts>.db`。
  **没有 `backup_dir` 就拒绝迁移**（抛 `MigrationError`，一个字段的 DDL 都不执行）——
  "先改结构再想办法备份"在这个项目里不是一种取舍，是一种破坏。
- 禁止"改结构就让用户删库重来"（SPEC 4.2）。`test_真实迁移目录从空库一路能跑到最新版` 就是这条的可执行版本。
- 实现时踩到的一条必须写在这：**`conn.isolation_level` 要设成 `None`**。
  sqlite3 的旧式隐式事务会让 DDL 的提交时机不可控（你以为在事务里，其实已经落地了），
  所以 `migrate.py` 手动 `BEGIN IMMEDIATE` / `COMMIT` / `ROLLBACK`，一个迁移一个事务。
- 失败时异常对象带着 `.snapshot`（回退用那份副本的路径）与 `db=`（哪个库），
  并且同时留在 `app.log`（含 sqlite 原文）与 `state.log`（`startup.migration_failed`）。
- 守卫测试：`tests/guards/test_migrations.py` 用**带数据的旧版本库**跑一遍全量迁移，5 条断言已实测通过 ——
  逐表行数不变（新表除外）、旧内容读得回来、`PRAGMA integrity_check` = ok、`PRAGMA foreign_key_check` 空、
   WAL 与外键设置在库里持久。反向注入 I7（把回滚改成 `COMMIT`）确实让它变红。
- **阶段 1 只有 `0001_initial`（它建 12 张表；空库首启实测 13 张，多出的那张是 `schema_version`，由 `db/migrate.py` 建）**。`text_pages` / `content_fts` / `duplicate_groups`
  是**有意没建**，不是遗漏：分词器（Q1）与索引体积策略（Q2）未答，duplicate 分组口径属阶段 4。
  有断言反向钉住它们不存在（`test_阶段1刻意不建的表确实不存在`）。
  → 阶段 2 会以 **`0002`** 第一次真跑"带数据升级"，届时 `test_migrations.py` 里的合成 0002 要换成真实 0002 再验一次。

## 五 · 文件操作：预览 / 执行 / 日志 / 恢复 / 撤销

SPEC 3.6 的要求，按"事务回滚 ≠ 磁盘回滚"来实现。

> **当前状态（阶段 5 收尾时核对）**：本节是**契约设计**，`file_operations` / `operation_items`
> 两张表已在 `0001` 建出并有无事可做的断言守着，但**执行器、journal、撤销与恢复矩阵尚未实现** ——
> 全部属于阶段 4。下面提到的断言（`mtime` 集合不变、恢复矩阵未知状态数 = 0）是阶段 4 的**验收要求**，
> 现在还不存在对应测试文件；在此之前把本节读成"待办"，不要读成"已验"。

### 5.1 生命周期

```
plan(纯计算)  →  preview(UI)  →  [用户确认]  →  journal 落盘  →  execute 逐项
      ↓                                                              ↓
  不碰磁盘                                                   每项立刻回写状态
                                                                   ↓
                                       undo plan(可选) ← 完成/部分失败/中断
```

- **plan 阶段绝不打开、绝不写、绝不 rename**。阶段 4 必须用一条"`preview` 前后整个目录的
  `mtime` 集合完全不变"的断言来钉住它 —— 预览唯一能被证伪的方式就是这个。
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
