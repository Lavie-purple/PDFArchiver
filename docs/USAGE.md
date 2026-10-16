# 使用指南 —— 现在这个应用到底能怎么用

> 口径先说清楚：本指南只写**实测过**的用法。每一段「实测输出」都是这台机器上跑出来的原文，
> 不是示意、不是伪代码。凡是只能通过命令行用的能力，这里就写命令行，不假装界面上有按钮。
> 装在哪里、怎么装见 `docs/INSTALL.md`；OCR 单独有 `docs/OCR.md`；
> 备份与恢复见 `docs/BACKUP-RESTORE.md`；出问题见 `docs/TROUBLESHOOTING.md`。

## 一、一句话现状

| 你想做的事 | 今天能不能做 | 从哪里做 |
| --- | --- | --- |
| 启动应用、看这台机器的真实状态 | ✅ 能 | 双击 `PdfArchiver.exe`，首屏就是「运行状态与自检」 |
| 扫描目录、抽正文、建全文索引 | ✅ 后端能，**界面上没有入口** | 命令行注册监测根（见 §四） |
| 全文检索（文件名 / 路径 / 元数据 / 正文，带页码） | ✅ 后端能，**界面上没有搜索框** | 命令行（见 §五） |
| 分类树、多标签、按分类标签筛选 | ✅ 数据层能，**界面上没有清单页** | 命令行（见 §六） |
| 对扫描件跑本地 OCR | ✅ 后端能，**界面上没有按钮** | 命令行 / 测试，见 `docs/OCR.md` |
| 在应用里读 PDF、翻页、跳页码、看阅读历史 | ❌ 未实现（阶段 3） | —— |
| 按规则移动 / 改名 / 归档实体文件 | ❌ 未实现（阶段 4） | —— |
| 重复检测、撤销、备份向导、恢复 | ❌ 界面未实现（阶段 4）；迁移快照是自动的 | 手工见 `docs/BACKUP-RESTORE.md` |
| 语义搜索、AI 分类建议 | ❌ 未实现（阶段 6） | —— |

**应用不会自己动你磁盘上的 PDF。** 全代码里没有任何移动、改名、删除用户文件的调用；
界面最后一行就写着这件事（见 §三实测输出）。

## 二、启动与退出

```
PdfArchiver.exe                        # 双击或命令行，正常退出码 0
PdfArchiver.exe --data-dir D:\我的归档库   # 换数据根目录（搬家、多库、测试都用它）
PdfArchiver.exe --exit-after 20        # 起来 20 秒后自己关（冒烟验证用）
PdfArchiver.exe --version              # PdfArchiver 0.5.0
```

源码运行时把 `PdfArchiver.exe` 换成 `.venv\Scripts\python.exe -m pdfarchiver.app`。

- 退出码只有两个：`0` 正常，`2` 是启动失败（配置读不动 / 数据库打不开 / 后台起不来）。
  非 0 时崩溃堆栈一定落在 `<数据根>\logs\crash.log`，不是弹个框就完了。
- 关窗即干净退出：worker 线程停、watchdog 停、`state.log` 补一条关闭事件。
  任务没跑完就关窗不会丢 —— 下次启动会把中断的行回收重排（见 §七）。

## 三、界面：今天真的只有一屏

导航列 8 项，只有第 1 项有页面；其余 7 项显示的是"未实现 + 卡在哪个决定上"的说明文字，
不是空壳控件。下面是从冻结产物之外、用同一份代码渲染出来的**逐字实测输出**（库里是 273 份的示例语料；
唯一改动是路径里的本机用户名抹成 `...`，其余字符照抄）：
**这句"只有第 1 项有页面"和下面那行 `worker_threads=2 [默认]` 都抓于 2026-10-15 的交付轮，均已过期** ——
八屏界面此后已实现（**ISSUES I57** 记的就是这份文档整体没跟着更新），`worker_threads` 现行默认是 **1**
（**ISSUES I46** 甲 / D-050）；这一整块是逐字照抄的现场读数，所以不改里面的数字，只在这里标明。

```
== 运行时 ==
应用版本 = 0.5.0
数据根目录=C:\Users\...\AppData\Local\Temp\frozen_smoke_1015_032932\data_root (来源=显式参数)
日志目录 = C:\Users\...\AppData\Local\Temp\frozen_smoke_1015_032932\data_root\logs
备份目录 = C:\Users\...\AppData\Local\Temp\frozen_smoke_1015_032932\data_root\data\backups
本次装配耗时 = 0.018s
冷启动（进程起来到窗口就绪）= 0.512s 门禁 G1 [约定] ≤1.5s

== 设置（生效值 / 是否覆盖 / 来源）==
设置来源：内置默认值（...\config\settings.json 尚不存在）
  archive_default_template='{category}/{year}/{name}.pdf' [默认]
  busy_timeout_ms=5000 [默认]
  gpu_tasks_concurrent=1 [默认]
  log_keep_files=5 [默认]
  ocr_daily_page_budget=6000 [默认]
  scan_poll_seconds=5 [默认]
  scan_verify_minutes=30 [默认]
  worker_threads=2 [默认]

== 数据库 ==
  结构版本 schema_version = 3
  文档主记录 = 273（其中标记缺失 0）
  分类 = 14，标签 = 0
  监测根目录 = 1
  任务 = done=276
  应用内部状态条数 = 3
  库文件 = ...\data_root\data\catalog.db

== 默认分类写入结果 ==
  未写入模板（已种过或用户已有分类）

== 扫描与索引任务：进度 / 错误 / 重试 ==
  后台未启动：没有 worker 线程、没有文件监听，任务行只会被排进队列而没人领
  任务条数  index：done=273
  进度（按页）index：545 / 545 页 = 100.0%
  ...
  文档索引状态：共 273 份｜done=273｜还欠一次索引 0（口径 pending+stale）
  OCR 状态：done=1｜na=271｜pending=1｜库里已存 OCR 正文 1 页
  重试中：无（每条最多 3 次尝试）
  最近故障：无（库里没有一行带着 last_error）
  监测根上次全量对账
    · [启用] .../corpus｜上次 2026-10-14 19:31:20Z

== 界面尚未实现 ==
  · 文档库（SPEC 3.2 / 3.3）—— 未实现：Q7 线框未确认（docs/UI-SCREENS.md）
  · 检索（SPEC 3.4）—— 未实现：Q7 线框未确认（后端全文检索阶段 2 已交付）
  · PDF 阅读（SPEC 3.5）—— 未实现：Q7 线框未确认；渲染通道已定（D-017），页面渲染后端未实现
  · 归档预览与确认（SPEC 3.6）—— 未实现：Q7 线框未确认；文件操作属阶段 4，后端与界面都未实现
  · 重复检测（SPEC 3.7）—— 未实现：Q7 线框未确认；重复检测属阶段 4，后端与界面都未实现
  · 监测与索引设置（SPEC 3.1 / 3.2）—— 未实现：Q7 线框未确认（后端扫描与索引阶段 2 已交付）
  · 备份与恢复（SPEC 3.8）—— 未实现：Q7 线框未确认；备份向导属阶段 4，恢复界面未实现

界面上没有任何按钮会移动、改名或删除磁盘上的文件。
OCR 后端已交付（装了可选层就能用，但没有界面入口）；语义搜索（阶段 6）与文件归档、
备份恢复的界面（阶段 4）后端和界面都还没实现。
```

怎么读这一屏：

- **每一个数字都是现算的**。页面里没有一个写死的数字；按下「重新读取数据库状态」就是重查一遍库。
  这个按钮存在的意义就是让"重启后数据还在"当场可验（见 §七）。
- `后台未启动` 那行只在**用探针方式单独装配上下文**时出现（没调 `start_background()`）。
  正常双击启动的应用一定显示 worker 线程数与监听根数；显示成"后台未启动"就是启动失败。
- `设置来源` 一行给出"内置默认值"还是"用户覆盖值 + 来源文件"，这是硬要求：
  你没写 `settings.json` 时它不会假装是你的选择。
- 状态页与启动路径**不跑任何同步库检查**（`integrity_check` / `quick_check` 的代价都与库大小同量级，
  2026-10-16 在 6.1GB 真语料库上实测：`integrity_check` 19 小时+未完、`quick_check` 冷/热缓存 452s / 478s，
  塞进启动路径会把应用冻死，见台账 **ISSUES I45**）。库健康核查的唯一入口是离线探针 `tests/probes/p12_consistency.py`
  （可自行限速，不在产品启动路径里跑）。

## 四、第一次扫描：目前没有界面入口，所以用命令行

⚠️ 这是本指南里唯一一个"产品能力齐但界面缺位"的地方。注册监测根的操作在数据层
（`RootRepository`）已经完整交付并有测试覆盖，但没有对应的屏幕。以下脚本可直接复制运行。

```python
from pathlib import Path
from pdfarchiver.services.bootstrap import bootstrap
from pdfarchiver.fs.identity import identity_key

ctx = bootstrap(Path(r"D:\归档库"))            # 数据根目录；不存在会自动建
corpus = Path(r"H:\文档")
ctx.roots.add(corpus.as_posix(), identity_key(corpus), label="我的工作文档")
for rep in ctx.scan.scan_all():
    print(rep.summarize())
queue = ctx.start_background()                 # worker 线程 + 文件监听 + 断点续扫
```

实测输出（273 份合成样本语料，这台机器）：

```
① 扫描： C:/Users/.../corpus：PDF 273｜新增 273｜改动 0｜改名 0｜未见 0｜未变 0｜排队索引 273（319 ms）
② 后台：worker 2 线程｜监听根 1 个
③ 队列排空耗时 2.4s｜任务状态 = {'done': 273}
④ 库： 结构版本 schema_version = 3 / 文档主记录 = 273（其中标记缺失 0） / 分类 = 14，标签 = 0 /
      监测根目录 = 1 / 任务 = done=273 / 应用内部状态条数 = 1
```

之后只要用同一个数据根启动应用，`roots` 表里那条根就会被自动监听 —— 也就是说
**注册一次，以后新增/改动文件不用管**（watchdog 增量 + 每 30 分钟一次周期校验，
`scan_verify_minutes` 可改）。

扫描阶段的口径（`ScanReport.summarize()` 的六个词，别混用）：

| 词 | 含义 | 判据 |
| --- | --- | --- |
| `新增` | 第一次见到的文件 | 路径与身份都是新的 |
| `改动` | 同一个文件内容变了 | 身份键相同、大小或 mtime 变了 |
| `改名` | 内容没变、路径变了 | 按 `(dev, inode)` 类身份识别，**不是按文件名** |
| `未见` | 库里记着但磁盘上找不到 | 标 `missing`，**不删库里的行，也不删磁盘文件** |
| `未变` | 什么都不用做 | 身份与路径都对得上 |
| `排队索引` | 本轮排进正文抽取队列的份数 | 不等于已经抽完，要看 `任务状态` |

## 五、检索：四个通道，口径写死在结果里

```python
from pdfarchiver.search.service import Criteria, FIELD_BODY, FIELD_FILENAME

r = ctx.search.search(Criteria(text="冷链物流",
                               in_fields=(FIELD_BODY, FIELD_FILENAME)))
print(r.channel_label, len(r.hits), r.matching_documents, r.took_ms)
for h in r.hits:
    print(h.field_label, h.page_no, h.snippet.line(), h.highlight())
```

实测输出：

```
trigram 短语检索（4 字）｜命中 5｜筛选内 273 份｜1ms｜各通道 {'filename': 1, 'body': 4}
   doc#1 第None页 文件名｜正文来源=native
     片段：冷链物流温度记录仪校准规程.pdf
     高亮区间：(0, 4)｜matched=True
   doc#1 第1页 正文｜正文来源=native
     片段：冷链物流温度记录仪校准规程，第 1 条要求 …
     高亮区间：(0, 4)｜matched=True
```

必须知道的几件事：

1. **口径只有一个名字**。`r.channel_label` 会明说这次是"trigram 短语检索（4 字）"还是
   "只检索文件名 / 路径 / 元数据（本次没有搜正文）"。中文查询词**少于 3 个字**时 trigram
   索引帮不上忙，会自动落到 `LIKE` 兜底通道，标签会跟着变 —— 不要按"结果条数"猜自己用了哪条通道。
2. **正文命中带真页码**（`h.page_no`）。文件名/路径/元数据通道没有页码，是 `None`，不是 0。
3. **高亮位置是 Python 侧算的**（SQLite 这个版本没有 `offsets()`）。当折叠规则不一致导致
   算不出位置时，`h.snippet.matched=False`、`h.highlight()` 返回 `None` —— 该行仍然出现在结果里，
   只是不高亮。程序不会编一个位置出来。
4. **正文来源分两种**：`native`（PDF 自带文字层）与 `ocr`（本地识别）。
   `h.body_source` 说的是这个，别把 OCR 文本当成原生正文引用。
5. 筛选条件全在 `Criteria` 里：`root_key` / `category_ids` / `tag_ids` / `tag_match_all` /
   `modified_from`+`modified_to`（**UTC unix 秒**，比的是文件修改时间）/ `fts_status` /
   `min_pages` / `min_size_bytes` / `include_missing` / `missing_only` / `sort` / `limit` / `offset`。
   分页是 `limit`+`offset`，**不存在"一次取全库"**。

## 六、分类与标签：数据层可用，界面没有清单页

```python
c = ctx.catalog.add_category("合同审查", note="按需自建")
t = ctx.catalog.add_tag("待复核")
ctx.catalog.link_category(doc_id, c.id)          # 一份文档可以挂多个分类
ctx.catalog.link_tag(doc_id, t.id)
ctx.catalog.categories_of(doc_id); ctx.catalog.tags_of(doc_id)
```

实测输出（在数据根的一份临时副本上做的，副本已删）：

```
[写] 新建分类 id=15 name=合同审查｜标签 id=1 name=待复核｜样例文档 id=1 冷链物流温度记录仪校准规程.pdf
[写] link_category -> True | link_tag -> True
[写] categories_of = ['合同审查'] | tags_of = ['待复核']
[写后查] 浏览模式（未输入查询词，排序 relevance）｜命中 1｜符合筛选 1 份
[写后查] 按标签筛 → 符合筛选 1 份｜命中 1
[树] 层级示例（缩进=深度）：
   合同审查 (id=15, parent=None)
   文档类型 (id=7, parent=None)
     产品手册 (id=12, parent=7)
     技术文档 (id=11, parent=7)
     标准规范 (id=14, parent=7)
     白皮书 (id=13, parent=7)
```

- 首次建库会种下 **14 个**默认分类（两层），这是实测数字，改默认模板要走迁移，不是改常量。
- `origin` / `confirmed` 两个参数是给"AI 建议分类"预留的口径（阶段 6）：机器给的一律
  `origin="ai_suggested", confirmed=0`，人工确认后才有 `confirmed=1`。今天全是手工，所以全是 1。
- **导出分类与标签清单**是阶段 3 第 10 项，未实现。想现在拿清单只能自己查 `categories` / `tags` 两张表。

## 七、重启之后东西还在吗 —— 自己验一遍

1. 启动应用，记下「文档主记录 = N」「任务 = done=…」「监测根上次全量对账」那几行。
2. 关窗口（正常关闭，别用任务管理器杀）。
3. 再启动，按「重新读取数据库状态」。

判据：**数字一致，且 `logs/crash.log` 不存在**。冻结产物的实测就是这样走的 —— 干净目录首启、
扫描 273/273、正文入库、关窗、再起，二次启动读数与一次启动相同，`integrity_check = ok`。

非正常关闭（杀进程 / 断电）也要能恢复：启动时 `WorkQueue.recover()` 把上次停在 `running`
的行重新排队，`state.log` 里 `background.started` 事件带 `recovered` 与 `resume_index` 两个数字。
杀进程实测：重启后 `recovered` 非 0，任务最终全部 `done`，没有一行卡在 `running`。

## 八、日志：出问题先看这三个文件

| 文件 | 内容 | 什么时候看 |
| --- | --- | --- |
| `<数据根>\logs\app.log` | 轮转运行日志（2MB × `log_keep_files`=5） | 想知道扫描/索引/OCR 每一步发生了什么 |
| `<数据根>\logs\state.log` | 一行一条 JSON 的生命周期事件（启动、迁移、后台启动、关闭、失败） | 事后对账"它到底起来了没有、什么时候关的" |
| `<数据根>\logs\crash.log` | 未捕获异常与线程内异常，含完整 traceback，追加不轮转 | 只要它存在就是有故障；退出码 2 必读 |

时间戳一律 UTC 带 `Z` 后缀，不用本地时区 —— 远程帮人诊断时不用猜对方在哪个时区。

关键事件行（`state.log`）的正常序列：

```
startup.begin → migration.applied → startup.done → background.started → window.ready
```

`window.ready` 里的 `cold_start_seconds` 就是界面上那行冷启动读数；阈值 1.5s 是**约定值**，
不是实测保证 —— 满载机器上实测到过 3.129s（`docs/ISSUES.md` ISSUES I25）。

## 九、性能与量级的真实边界

- 冷启动：源码空载 **0.428–0.77s**（交付链那一场现场打印 **0.437s**，G1 阈值 1.5s **[约定]**），
  满载（CPU 96.5%）**2.99–3.13s**；**冻结产物 1.109s** —— 比源码慢 2.5 倍，这是打包带来的真实代价。
  G1/G2 是负载绑定读数，必须连着门禁第一行的负载一起比。
- 扫描：273 份合成样本全量对账 **319–332ms**；正文索引队列排空 **2.4s**（worker 2 线程）。
- 检索：本指南的示例 **0–1ms**；这是 273 份小库的读数。**门禁 G2（搜索 P95 ≤ 500ms）还没有
  在真实量级上实测过**（`docs/ROADMAP.md` 门禁表把它列为"未实测，仍是反算值"），
  所以别拿这个 0–1ms 推断 7,768 份/202 万页时的表现。
- OCR：单页 **1,985–3,379ms**（DML 加速，负载影响明显），日预算默认 6,000 页，见 `docs/OCR.md`。
- 库文件：**唯一量到过一次**的读数是冻结冒烟那场 273 份 / 544 页正文 → `catalog.db`
  **864,256 字节**（≈844KiB，正常关闭后 `-wal` / `-shm` 已合回主文件；出处 `docs/BACKUP-RESTORE.md` 二）。
  真实语料跑满会是几百 MB 级，但这句是**外推**，目前**没有**在真实 7,768 份上做过完整扫描实测。

## 十、这份指南里"未验证"的部分

诚实清单（对应交付报告的五分栏）：

- **真机首屏没有人眼看过**：所有界面实测都是 `offscreen` 平台渲染的真 Qt 控件文本，
  截图级核对没做过（`docs/ISSUES.md` ISSUES I17）。
- **你的真实语料（7,768 份 / 2,024,504 页）从来没被这台机器上的应用扫过**：
  `%LOCALAPPDATA%\PdfArchiver` 这个默认数据根在本机不存在。§四的实测用的是 273 份合成样本。
  要按真实量级验证，请按 §四脚本换 `roots.add(r"H:\文档", identity_key(r"H:\文档"))`，
  然后在空闲时段跑，并记录 `state.log` 的耗时。
- **阶段 3 / 4 / 6 的界面一律未实现**，所以本指南没法写"点哪个按钮"。
  界面线框（Q7）还没逐屏确认，按 AGENTS.md 的禁令不画控件。
