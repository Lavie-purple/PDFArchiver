# 备份与恢复说明

> 先说结论：**备份/恢复有界面了（S6），但它只做两件事** —— 用 `sqlite3.Connection.backup()`
> 把 `catalog.db` 拷一份出来、以及把某个备份灌进一个**新目录**（绝不覆盖当前库）。
> 界面不会把 `settings.json`、分类标签、OCR 文本打包成一个"备份包"，也不做恢复前校验 ——
> 那些仍在下面 §三/§四 的手工流程里。**迁移前自动快照**照旧在跑（每次结构升级前生成）。
> 本文写的是"S6 界面能做什么"+"界面没覆盖的怎么手工补"，全部步骤都在本机实测过。
>
> 备份对象口径不变：`catalog.db` 里**含**人工分类标签与 OCR 正文（B 档，不可轻易再生），
> 所以只要备份了这个库，就保住了最难重建的东西。

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

## 二、备份从哪来：S6 界面按钮 + 迁移前自动快照

现在有**两个来源**：

1. **S6「备份与恢复」页的「创建备份」按钮** —— 见 §三·甲，产出 `catalog-时间戳-v版本.db`。
2. **每次结构迁移前的自动快照** —— 见下面「生成时机与位置」，产出 `pre-migration-*.db`。

### 迁移前自动快照 · 生成时机与位置

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

## 三、备份：界面按钮（甲）与手工（A/B）

关键约束：库跑在 WAL 模式下（`PRAGMA journal_mode=WAL`），**应用运行中直接复制 `catalog.db`
会备到不一致状态** —— 已提交的数据可能还在 `catalog.db-wal` 里没落回主文件。这条写进
`docs/DATABASE.md` 六，不是建议，是必须。所以下面三种做法都绕开了"运行中拷文件"。

### 做法 甲：S6 界面的「创建备份」按钮（推荐）

侧栏进「备份与恢复」→ 第一个标签「备份」→ 二选一：

- **「创建备份」**：用 `sqlite3.Connection.backup()` 备份当前库到 `data\backups\`，
  文件名 `catalog-YYYYMMDD-HHMMSS-v结构版本.db`，成功弹窗给出完整路径。
- **「备份到...」**：同上，但目标目录由你选。

按钮可以在应用运行时点（它走的是 Backup API，不拷文件，所以一致）。
**注意它只备 `catalog.db`** —— `settings.json` 不在里面。要连设置一起备，用下面做法 A。

### 做法 A：复制整个 `data\` 目录（要连 settings.json 一起备时用）

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

## 四、恢复

**核心安全约束：本程序不提供任何"自动覆盖当前库"的路径** —— 无论界面还是脚本。
S6 的恢复按钮只把备份灌进一个**新目录**，然后提示你重启应用指向新库；下面 §四·手工 的
`src.backup(dst)` 也只是把某份快照恢复到指定库文件，要你亲手选源和目标。

### 方式 甲：S6 界面的「恢复到新目录」按钮

侧栏「备份与恢复」→ 第二个标签「恢复」：

1. **「选择备份文件」** → 选一个 `catalog-*.db` 或 `pre-migration-*.db`。
2. **「恢复到新目录...」** → 选一个空目录，程序把备份复制成该目录下的 `catalog.db`。
3. 弹窗明确告诉你：**"当前应用仍在使用旧库。要使用新库，请重启应用并指定新数据目录。"**
   即用 `PdfArchiver.exe --data-dir <那个新目录>` 重启。

界面恢复**不做**：清单校验、`integrity_check`、路径重新对账。恢复完请照 §五 跑一致性探针。

### 方式 乙：手工脚本（要精确挑某一份快照、或想在原目录内换库时用）

⚠️ 下面脚本会把某份快照灌回 `catalog.db`，**等于覆盖那个库**，所以第 0 步先保住现状。

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
   在 S7「设置与状态」→「监测目录」点「添加目录…」重新登记（批量登记见 `docs/USAGE.md` §四 的命令行），
   然后一次全量扫描就能把 C 档数据重建回来：

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
| 以为"恢复数据库 = 恢复 PDF 文件" | **完全两件事。** 数据库只记路径与元数据，本程序从备份角度是"文件清单"，不是"文件仓库"。PDF 丢了它变不出来（A 档）。`file_operations` + `operation_items` 记的是"文件被本程序移动过"的历史，但**今天界面上没有任何按钮会真的移动文件**（**ISSUES I55**，S3「执行归档」不生成批次、S4「整批撤销」执行器未实现），所以别指望靠本程序把丢掉的 PDF 找回来 |

## 七、换机器 / 搬家

- 要带走的：`<数据根>\data\catalog.db`（或 §三 的备份文件）+ `<数据根>\config\settings.json`。
- 不用带走的：`data\cache\`（D 档）、全文索引花名册（C 档，`ctx.indexer.rebuild_fts()` 重建）。
- 建议带走的：**OCR 文本**。它在 `catalog.db` 里，所以整库带走就包含了
  （S6「创建备份」拷的就是这个库，天然含 OCR 正文；无需额外开关）。
- 新机第一次启动会跑迁移（并生成快照），之后在 **S7「设置与状态」→「监测目录」→「添加目录…」**
  重新登记监测根（界面入口已交付，**ISSUES I66** 2026-10-17 销账；批量登记见 `docs/USAGE.md` §四 的命令行）。
  跨机器的路径写法变化会被标成 `missing` 而**不是**删记录，交给你重新定位 ——
  这是 `docs/DATABASE.md` 六规定的恢复流程，今天只能靠 p12 的 C3 条目把差异算给你看。

## 八、S6 交付到哪一步了（对照 `docs/DATABASE.md` 六的目标形态）

`docs/DATABASE.md` 六定的目标分三块，现状逐块如实标注：

1. **备份按钮 —— 部分交付**。S6 有「创建备份 / 备份到...」按钮，走 `sqlite3.backup()`，文件名带版本。
   **但备份对象只有 `catalog.db`**：`settings.json`、清单文件（文档数 / 页数 / OCR 页数）都还没进备份包。
   要连设置一起备，仍用 §三 做法 A。
2. **恢复流程 —— 部分交付**。S6「恢复到新目录」做到了"落到新目录、不覆盖现场"这一条安全底线。
   **但没有**清单校验、没有恢复前 `integrity_check`、没有强制重新校验文件路径 ——
   恢复完请照 §五 手工跑一致性探针（p12 的 C3 会把盘上↔库里差异算给你，失效路径靠扫描重标 `missing`）。
3. **归档与撤销 —— 后端已交付，界面没有入口**。`ArchiveService` 是真的会搬文件：建批次（`file_operations`）
   → 逐条计划（`operation_items`）→ 写 journal → 同盘 rename / 跨盘 copy+校验+删源 → 更新状态，
   G17（journal 崩溃后可逐条归类）与 G19（**验证没过绝不先删源**）已由
   `tests/integration/test_archive_disk_safety.py` 用真临时文件验过。
   **但从 S3 走不到这条链**：「执行归档」不生成 job（`archive_page.py:159` 的 `_execute_archive` 只报"没动盘"），
   「整批撤销」的反向批次执行器**还没实现**（D-043 定的 `kind='undo'` + `undo_of=原批次` 只有仓储层字段，没有服务），
   因此 **G18 撤销正确性今天无法测**。挂账见 **ISSUES I55**，磁盘口径以状态页的 `DISK_EFFECT_LINE` 为准。
   p12 探针的 C8 也已随之从"两张表恒为空"换成"操作状态取值都在口径内"的真口径
   （出处 `tests/probes/p12_consistency.py` 的 `c8_op_domain`）。
   ⚠️ §五 那段探针输出里 C8 还印着"0 行"——那是 2026-10-15 冻结冒烟现场（没跑过归档）的逐字读数，
   照旧不许改数字；真跑过归档后它会是合法的非空分布。

**还没做的**：备份包合并 `settings.json` + 清单文件、恢复前自动 `integrity_check`。
这两项落地前，本文的 §三 做法 A 与 §五 探针仍是完整备份/校验的唯一可靠路径。
