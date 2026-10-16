# 备份与恢复说明

> 先说结论：**这个应用目前没有备份/恢复功能。** 界面里那一栏「备份与恢复」写着"未实现"，
> 代码里 `services/backup*` 不存在（`docs/ISSUES.md` **ISSUES I22**）。
> 今天真实存在的东西只有一样：**每次数据库结构迁移之前自动生成的一致性快照**。
> 本文写的是"快照今天真的怎么用"+"你自己怎么手工备份恢复"，全部步骤都在本机实测过。
>
> 需求原文把备份与恢复排在阶段 4，而阶段 4 一行代码都没做，所以这不是"功能被砍"，是"尚未交付"。

## 一、先分清四类数据：丢了能不能再生

口径来自 `docs/DATABASE.md` 一（同一张表，不另写一套）：

| 档 | 内容 | 丢了会怎样 | 谁负责备份 |
| --- | --- | --- | --- |
| **A 不可再生** | 你磁盘上的 PDF 本体 | 真损失，无法恢复 | **本程序不备份用户 PDF**，只登记它们在哪 |
| **B 难再生** | `catalog.db` 里的人工成果：分类、标签、集合、归档映射、**OCR 正文** | 要重做人工标注；OCR 要重烧 GPU | 必须进备份包 |
| **C 可再生** | 全文索引花名册、原生正文 `text_pages(source_kind='native')` | 重扫一遍即可 | 默认不必备份 |
| **D 纯缓存** | `data\cache\`、缩略图 | 无所谓 | 不备份 |

**为什么 OCR 文本按 B 档而不是 C 档**（这条最容易搞错，所以写进正文）：
本机 DirectML 实测单页 **1,985–3,379ms**（负载相关），按每日 6,000 页预算反算，
全库待 OCR **1,014,112 页 ≈ 169 天**。所以"重扫就能恢复"这句话**对原生正文成立、对 OCR 正文不成立**。
实测证据见 §四 第 2 步：恢复快照后重扫 273 份，正文回到 **543 行**，而备份前是 **544 行** ——
差的那一行就是唯一那页 OCR 文本，重扫不会把它找回来（OCR 只处理你显式点名的页，D-028）。

## 二、今天真实存在的备份：迁移前快照

### 生成时机与位置

每次启动时若 `schema_version` 落后于 `src/pdfarchiver/db/migrations/` 里的最新编号，
**在动结构之前**用 `sqlite3.Connection.backup()` 存一份完整副本：

```
<数据根>\data\backups\pre-migration-<四位迁移序号>-<本地时间戳>.db
```

- 快照失败或迁移失败 → 异常里带着快照路径（`MigrationError.snapshot`），迁移在单事务里回滚，
  库停在原版本，不会留下"改了一半"的结构。
- 没有增量迁移的启动**不会**产生快照 —— 所以"backups 目录是空的"是正常状态，不等于坏了。
- 快照不轮转、不自动删（数量上限 = 迁移条数，目前 3 个）。

### 实测清单（冻结产物冒烟留下的现场，273 份文档）

```
  绿  C11  每份备份快照都真能打开并读出版本
        快照 3 份｜pre-migration-0001-20261015T032946.db 8KiB@v0 ｜
        pre-migration-0002-20261015T032946.db 120KiB@v1 ｜
        pre-migration-0003-20261015T032947.db 148KiB@v2
```

`@v0/@v1/@v2` 是**这份快照当时库里停的结构版本**，也就是"恢复到它 = 退回到那次迁移之前"。
第一份 8KiB 是空库（建库前的原始状态），所以它连 `schema_version` 表都还没有。

## 三、手工备份：正确做法

**没有备份按钮，所以下面三步是手工。** 关键约束：库跑在 WAL 模式下
（`PRAGMA journal_mode=WAL`），**应用运行中直接复制 `catalog.db` 会备到不一致状态** ——
已提交的数据可能还在 `catalog.db-wal` 里没落回主文件。这条写进 `docs/DATABASE.md` 六，
不是建议，是必须。

### 做法 A：复制整个 `data\` 目录（最简单）

1. **完全退出应用**（关窗口，不是最小化）。
2. 确认 `<数据根>\data\` 里只剩 `catalog.db`，没有 `catalog.db-wal` / `catalog.db-shm`。
   正常关闭会做 checkpoint 并删掉这两个文件；**如果它们还在，说明还有进程连着这个库，别拷**。
3. 把 `<数据根>\data\catalog.db` 与 `config\settings.json` 一起复制到备份位置。
   `cache\` 不用拷（D 档）；`backups\` 里的快照建议一起拷。

实测：正常关闭后 `data\` 目录里只剩 `catalog.db`（864,256 字节，273 份文档 / 544 页正文），
`-wal`/`-shm` 不残留。

### 做法 B：用 SQLite 的 Backup API（应用可能在跑时用这个）

```python
import sqlite3
from pathlib import Path

root = Path(r"D:\归档库")                      # 你的数据根
out  = root / "manual-backup.db"               # 备份目标；不要写进 data\backups\，那是快照目录
src = sqlite3.connect(root / "data" / "catalog.db")
dst = sqlite3.connect(out)
src.backup(dst)                                # 一致性快照，可以在应用运行时做
dst.close(); src.close()
print(out.stat().st_size, sqlite3.connect(out).execute("pragma integrity_check").fetchone()[0])
```

`src.backup()` 读到的是一致视图，不需要停应用。这就是产品内部用的同一个机制。

**备份要包含 OCR 文本**：OCR 正文就在 `catalog.db` 的 `text_pages(source_kind='ocr')` 里，
所以只要备份了 `catalog.db` 就等于备份了它。**不要**只备一份"重建脚本"就认为能恢复 —— 169 天。

## 四、手工恢复

⚠️ 恢复会**覆盖当前库**。按 AGENTS.md 的约束，本程序不提供任何"自动覆盖"路径；
下面的脚本是手工的、要你亲眼看一遍再按回车的。

### 第 0 步：先保住现状

```python
import shutil, sqlite3
from pathlib import Path
root = Path(r"D:\归档库")
cur = root / "data" / "catalog.db"
shutil.copy2(cur, root / "before-restore.db")           # 万一恢复错了还能回来
s = sqlite3.connect(cur); print("现状：", s.execute("select count(*) from documents").fetchone()[0], "份文档")
s.close()
```

### 第 1 步：把快照灌回 `catalog.db`

```python
import sqlite3
from pathlib import Path
root = Path(r"D:\归档库")
snap = root / "data" / "backups" / "pre-migration-0002-20261015T032946.db"
dst  = root / "data" / "catalog.db"
src = sqlite3.connect(snap); out = sqlite3.connect(dst)
src.backup(out)                    # 用 Backup API，而不是复制 .db 文件
out.close(); src.close()
```

**应用必须已经退出**再做这一步。恢复完成后正常启动即可。

### 实测输出（在冻结现场的一份副本上跑的，副本已删）

```
覆盖前 catalog.db = 864256 字节｜文档数 = 273
Backup API 覆盖完成｜dst 大小 = 864256 字节｜journal_mode = wal
恢复后首启： 结构版本 schema_version = 3 / 文档主记录 = 0（其中标记缺失 0） / 分类 = 14，标签 = 0 /
            监测根目录 = 0 / 任务 = 无任务 / 应用内部状态条数 = 1 / 库文件 = ...\data_root\data\catalog.db
```

### 第 2 步：恢复之后必须知道的三件事

1. **结构会自动升回最新版**。`pre-migration-0002` 那份停在 v1，启动时迁移 0002/0003 重跑一遍，
   所以恢复后看到的还是 `schema_version = 3`，同时 `backups\` 里**多出新的快照**（实测多出
   `pre-migration-0003-20261015T035159.db`）。这是设计行为，不是异常。
2. **人工成果退回快照时刻**。上面的实测里 `文档主记录 = 0`：选中的那份快照是**建库之前**的状态，
   它里面根本没有 `text_pages` 表、`documents` 是 0 行。所以"恢复到哪一天"要看文件名里那个
   序号 + `@v` 版本，不要凭感觉选。**默认分类会被重新种一次**（实测 14 个）。
3. **监测根要重新登记**。快照里 `roots` 是空的 → 恢复后 `监测根目录 = 0` → 应用不会扫任何目录。
   照 `docs/USAGE.md` §四 重新 `roots.add(...)`，然后一次全量扫描就能把 C 档数据重建回来：

```
重扫： ...corpus：PDF 273｜新增 273｜改动 0｜改名 0｜未见 0｜未变 0｜排队索引 273（329 ms）
队列排空 2.4s｜状态 = {'done': 273}
重扫后可检索「冷链物流」= 3 条｜正文花名册 = 正文 543 行｜索引花名册 543 行｜未进索引 0｜花名册残留 0
```

—— 原生正文 543 行全部回来了，检索照旧能用。**唯独那 1 页 OCR 文本没有**（543 ≠ 备份前的 544），
这一行差异就是 §一 说的"OCR 属 B 档"的实测证据。

## 五、恢复完怎么确认没恢复坏

跑一致性核查探针（**只读**，不写库、不动文件）：

```
.venv\Scripts\python.exe tests\probes\p12_consistency.py --data-root "D:\归档库"
```

实测输出（对冻结冒烟现场，273 份 / 544 页）：

```
数据根：C:\Users\...\frozen_smoke_1015_032932\data_root（来源：显式参数）｜库：catalog.db
  绿  C0  水位停在迁移目录里的最新版
        库里 v3｜迁移目录最新 v3｜迁移清单 ['0001_initial', '0002_text_and_fts', '0003_ocr_tracking']
  绿  C1  库自身健康（integrity_check 与外键）
        integrity_check=ok｜foreign_key_check 0 条
  绿  C2  主记录路径唯一、path_key 与 identity_key 同口径
        主记录 273 条｜两项全部一致
  绿  C3·corpus  盘上文件 ↔ 库里主记录 双向对账
        盘上 PDF 273｜该子树主记录 273（已标缺失 0）｜排除 0｜非 PDF 0｜读不动的目录 0
  绿  C4  正文表 ↔ 索引花名册 双向对账
        正文 544 行｜花名册 544 行｜漏索引 0｜花名册残留 0｜本口径测不到倒排幽灵（免词口径全瞎，由带词的 G10 守着）
  绿  C5  正文页自洽（字数口径 / 来源 / OCR 版本列）
        正文 544 页（其中 ocr 1）｜五项全部自洽
  绿  C6  状态字段取值都在口径内（可计数的硬条件）
        主记录 273 条｜主记录四个状态列 + 队列两列全部合法
  绿  C7  向量状态仍全为 na（阶段 6 未落地，非 na 只可能是偷写）
        非 na 的行 0 条｜没有一行越过 na —— 阶段 6 交付时这条要同步换成它的口径
  绿  C8  文件操作两张表仍为空（阶段 4 未落地，非空只可能是偷写）
        file_operations 0 行｜operation_items 0 行
  绿  C9  无进程时队列里不许有 running 残留
        running 0（必须为 0，否则上次退出没回收）｜各状态分布 {'done': 276}｜干净
  绿  C10  分类树自洽（父链可达 / 无环 / name_path 与父链一致）
        分类 14 个（默认模板算出来是 14 个）｜四项全部自洽
  绿  C11  每份备份快照都真能打开并读出版本
        快照 3 份｜pre-migration-0001-...db 8KiB@v0 ｜ pre-migration-0002-...db 120KiB@v1 ｜ pre-migration-0003-...db 148KiB@v2
  绿  C12  正文页页码不超过库里记的页数
        超页 0｜页码 <1 0｜同页重复 0（page_count 的口径来自解析器，不是人工填的；页码越界=正文与文件对不上）
  合计 13 条｜红 0 条｜未验 0 条
VERDICT: ALL GREEN
```

探针自己也可能错，所以它有反向注入自检（只动临时目录里的副本）：

```
.venv\Scripts\python.exe tests\probes\p12_consistency.py --inject
→ 17/17 条坏法被抓到
```

两条使用注意：

- **未验 ≠ 通过**。加 `--no-file-walk` 会跳过盘上遍历，那几条显式印成「未验」并让整场变红。
- 应用正在跑时可能读到需要恢复的 WAL，探针会**原样把这句话打给你**并且不改库。这时先关应用再跑。

## 六、绝对不要做的事

| 不要 | 为什么 |
| --- | --- |
| 清空 / 删除 `<数据根>\data\` 目录"重来一遍" | 里面可能有无法再生的 OCR 文本（169 天口径，ISSUES I22）和全部人工分类标签。先按 §三 备份 |
| 应用运行时只拷 `catalog.db` | WAL 下会拷到不一致状态。用 §三 做法 A（先关）或做法 B（Backup API） |
| 把快照复制成 `catalog.db`（`shutil.copy`） | 同上。用 `src.backup(dst)` |
| 直接编辑 `settings.json` 里的手填路径来"改库" | 库是事实来源，路径口径由扫描器算。改错会造出一批 `missing` 记录 |
| 以为"恢复数据库 = 恢复 PDF 文件" | **完全两件事。** 数据库只记路径与元数据，本程序从备份角度是"文件清单"，不是"文件仓库"。PDF 丢了它变不出来（A 档）；阶段 4 的归档操作日志 + 撤销才是为此设计的，而阶段 4 还没做 |

## 七、换机器 / 搬家

- 要带走的：`<数据根>\data\catalog.db`（或 §三 的备份文件）+ `<数据根>\config\settings.json`。
- 不用带走的：`data\cache\`（D 档）、全文索引花名册（C 档，`ctx.indexer.rebuild_fts()` 重建）。
- 建议带走的：**OCR 文本**。它在 `catalog.db` 里，所以整库带走就包含了；
  设计文档里那个"连 OCR 文本一起带走"的开关属于阶段 4，尚未实现。
- 新机第一次启动会跑迁移（并生成快照），之后按 `docs/USAGE.md` §四 重新登记监测根。
  跨机器的路径写法变化会被标成 `missing` 而**不是**删记录，交给你重新定位 ——
  这是 `docs/DATABASE.md` 六规定的恢复流程，今天只能靠 p12 的 C3 条目把差异算给你看。

## 八、阶段 4 交付之后这一份要怎么改

`docs/DATABASE.md` 六已经定死了目标形态，届时本文要补的是：

1. 备份包 = `catalog.db` 快照 + `settings.json` + `file_operations` 历史 + OCR 文本 + **清单文件**
   （时间、`schema_version`、文档数、页数、文本字节数、OCR 页数），界面上给"备份"按钮。
2. 恢复流程 = 校验清单 → 落到**新目录**（不覆盖现场）→ `integrity_check` → 强制重新校验文件路径，
   失效路径进 `missing_since` 交用户重新定位。冲突时**不许覆盖用户文件**。
3. 归档改名/移动撤销（`file_operations` + `operation_items` 两张表已经建好，今天恒为空 —— C8 就在盯这件事）。

在此之前，本文就是唯一有效的备份/恢复说明。
