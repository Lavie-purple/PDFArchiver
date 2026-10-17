# 故障排查

> 写法约定：每条都是「现象 → 第一去处 → 判据 → 处置」，并标出对应的 `docs/ISSUES.md` 编号。
> 所有引号里的字符串是代码或日志里的**原文**，不是转述（AGENTS.md：排障只认原始证据）。
> 求助时请把 `crash.log` 的完整一段原样贴出来，不要转述成"它报了一个错"。

## 〇、先搞清三件事，后面都靠它

**1）你的数据根在哪。** 界面**底部状态栏**一直在写（切到哪一屏都在），S7「设置与状态」上半区的
「运行状态与自检」第 2 行是同一串（都来自 `AppPaths.describe()`）：

```
数据根目录=C:\Users\...\AppData\Local\Temp\frozen_smoke_1015_032932\data_root (来源=显式参数)
```

优先级 `--data-dir` > 环境变量 `PDFARCHIVER_DATA_DIR` > `%LOCALAPPDATA%\PdfArchiver`。
`(来源=…)` 那半句会告诉你是哪一级生效的 —— 找不到数据先看这个。

**2）日志三件套**（都在 `<数据根>\logs\`）：

| 文件 | 内容 | 用途 |
| --- | --- | --- |
| `app.log` | 全部运行日志，2MB 轮转留 5 份 | 查每一步做了什么 |
| `state.log` | 一行一条 JSON 生命周期事件 | 查"到底起来了没有、什么时候关的" |
| `crash.log` | 未捕获异常 + 线程内异常，含完整 traceback，**不轮转** | 只要它存在就是有故障 |

正常启动的事件序列：`startup.begin → migration.applied → startup.done → background.started → window.ready`。
缺哪一条，故障就在那一条之前。

**3）退出码**：`0` 正常；`2` 启动失败。`console=False` 打包出来的 exe **没有 stdout**，但
装配失败 / 后台起不来时会弹一个「启动失败」对话框，把错误原文和 `crash.log` 落点写在屏幕上
（**ISSUES I18 已修**，2026-10-17）—— 双击失败不再是"一闪就没了、屏幕上什么都没有"。

## 一、双击没反应 / 一闪就没了（ISSUES I18，已修）

0. **先看有没有弹「启动失败」对话框**（标题「启动失败」、红色 Critical 图标）。装配失败或后台线程
   起不来时它会把错误原文 + `crash.log` 路径显示在屏幕上（就是 **ISSUES I18** 的处置），按正文给的路径去翻即可。
1. 没弹框、但 `crash.log` 存在 → 直接跳到最后一节的原文，按它的内容对症下药。
2. 都没有 → 看 `state.log` 有没有 `window.ready`。有，说明窗口真起来了，只是被别的窗口挡住或在别的显示器上。
3. 三条都没有 → 用命令行起一次，让 stderr 露出来：
   ```
   PdfArchiver.exe --data-dir C:\临时测试库
   ```
   源码版：`.venv\Scripts\python.exe -m pdfarchiver.app --data-dir C:\临时测试库`

### 启动失败（退出码 2）的三种成因

| 日志里能看到 | 成因 | 处置 |
| --- | --- | --- |
| `打开数据库失败` + `sqlite3.DatabaseError` | 库文件损坏或不可写 | 见 §七 |
| `迁移目录里一个迁移也没有：…`（`MigrationError`） | **打包时漏收迁移 `.py`** —— 静态分析收不到它们 | 重新打包；`packaging/build.py` 有这条内容断言（见 §八） |
| `后台启动失败 …` + 写进 `crash.log` | worker 线程或 watchdog 起不来 | 原样贴出来求助；这种情况应用会主动以非 0 退出，不会带着没人领任务的队列继续跑 |

## 二、某一屏看着是空的 / 数字像旧的

八屏界面（状态 / 文档库 / 阅读器 / 归档 / 操作日志 / 重复 / 备份 / 分类 / 设置 / 监测）都已落地，
不再是"只有第一屏有页面"。如果某一屏内容与磁盘/库现状不符，通常是**这一屏还没重查**，不是坏了：

- 状态页有「重新读取数据库状态」按钮 —— 每个数字都是点它时现算的，不点就是上次那份快照。
- 文档库/分类页在切过去时会 `reload()`；手动刷新同理重进该屏即可。
- 判重页的重复组来自最近一次 `dedup` 任务（`documents.duplicate_groups`）：没跑过判重任务时这里本就该是空的。

真正"没数据"的排查走 §三（扫不到）/ §五（搜不出）。

## 三、扫描了但库里 0 条 / 文件扫不到

先跑一条只读判断（不改任何东西）：

```
.venv\Scripts\python.exe tests\probes\p12_consistency.py --data-root "<你的数据根>"
```

- `C3·corpus  盘上文件 ↔ 库里主记录 双向对账` 会给出「盘上 PDF N｜该子树主记录 M｜排除 K」。
  `N>0, M=0` → 根没登记对；`N>M` 且差值等于排除数 → 是被 `exclude_globs` 排的。

常见原因（都实测过）：

| 现象 | 原因 | 处置 |
| --- | --- | --- |
| 一个文件都没扫到 | 从没注册监测根 —— S7「设置与状态」→「监测目录」的列表是空的 | 点「添加目录…」选中你的文件夹即可登记（**台账 ISSUES I66 已销账**，2026-10-17）；要一次登记多个根见 `docs/USAGE.md` §四 的命令行 |
| 只扫到一半 | 监测根路径写法与实际不符：`root_key` 存的是**规范化后小写**的形式 | 用 `identity_key(路径)` 生成，别手写字符串 |
| 深层中文目录看不见 | 长路径限制（**ISSUES I10**）。本机 `LongPathsEnabled=1`，最深实测 **533 字符**仍成功，但**第三方工具**（Git、资源管理器）可能看不见 | 缩短目录层级或把根挪到浅位置；归档时超限会被 `validate_path_length` 拦下并抛可读的 `PathTooLongError`（不再是 WinError 3），S3 预览也有「路径长度」显示项 |
| 根目录被改名或删除后毫无反应 | watchdog 对这件事**完全盲**（实测 **0 事件**，**ISSUES I5**） | 等周期校验（默认 30 分钟，`scan_verify_minutes`）或手动跑一次全量对账 |
| 权限不足的目录 | 扫描器数出「读不动的目录」，p12 C3 那一行会打出来 | 不是崩溃；要么给权限，要么把它写进 `exclude_globs` |

## 四、文件明明还在磁盘上，却被标成"缺失"

`文档主记录 = N（其中标记缺失 M）` 这一行的"缺失"就是 `documents.missing_since` 非空。

- 判据：p12 `C3` 那行给出「已标缺失 x」。缺失的记录**不会被删除**，磁盘上也不会被动过 ——
  这是设计（A 档文件本程序不碰）。
- 常见成因：监测根换了盘符 / 改名 / 移动；或从别的机器恢复库（§五 第 2 步）。
- 处置：把路径恢复原样再跑一次扫描，那条主记录会被重新写回（`missing_since` 置空、
  `last_scanned_at` 更新 —— `DocumentRepository.upsert` 里那句 `missing_since=NULL`）。
  如果文件确实改名了，扫描按**身份**（不是文件名）识别成"改名"，`未见` 计数会说明有多少没接上。

## 五、搜索不出东西

按这五种情况逐个排除：

1. **查询词少于 3 个字。** FTS5 用的是 `trigram`，短于 3 字命中不了索引，会走 `LIKE` 兜底通道。
   判据：`r.channel_label` 明说这次是哪条口径 —— 别看条数猜。
2. **没勾正文通道。** 只搜文件名/路径/元数据时的口径文案是
   `只检索文件名 / 路径 / 元数据（本次没有搜正文）`。
3. **是扫描件，且那一页从没显式跑过 OCR。** OCR 正文只处理你点名的页（D-028，**ISSUES I1**）。
   判据：状态页 `OCR 状态：… 库里已存 OCR 正文 x 页`；`docs/OCR.md` 有全量口径（1,014,112 页 ≈ 169 天）。
4. **正文还没索引完。** 状态页 `文档索引状态：共 N 份｜done=…｜还欠一次索引 x（口径 pending+stale）`。
   非 0 就还没跑完；跑完再看。
5. **索引与正文表对不齐。** 判据：p12 `C4` 那行
   `正文 544 行｜花名册 544 行｜漏索引 0｜花名册残留 0`。
   `漏索引 > 0` → 有页没进倒排，跑 `ctx.indexer.rebuild_fts()`（实测能把漏的补回来）。
   ⚠️ **已知仪器盲区（ISSUES I8）**：外部内容表的"幽灵行"（已删正文仍留在倒排里）**没有免词的检测口径** ——
   `count(*) FROM content_fts`、`rowid NOT IN (…)`、`integrity_check` 在坏状态下全部看不出问题。
   你现在看不到幽灵结果，只因为检索通路每次 `JOIN text_pages`；`rebuild_fts()` 是补救入口
   （`tests/probes/p14_fts_instrument.py` ⑤：三种坏法叠进同一份库时 `漏索引 1 / 花名册残留 1 / 倒排幽灵 2`，
   一次 rebuild 后三个数全归 0。它返回六个数（`pages`、`docs`、`unindexed_before`、`unindexed_after`、
   `stale_before`、`stale_after`），也就是"补之前欠了多少、补之后还剩多少"的现场对账）。

## 六、OCR 相关的四类报错（原文照抄）

| 原文 | 含义 | 处置 |
| --- | --- | --- |
| `可选 OCR 层没装：缺发行包 rapidocr-onnxruntime。装法见 requirements/ocr.txt（必须按文件里的顺序装，先装 onnxruntime-directml 再装 rapidocr）` | 版本指纹读不到发行包元数据 | **源码环境**：按顺序重装。**冻结产物**里出现这句基本就是 **ISSUES I26** —— 打包没收 `.dist-info`，模块 import 得到但 `importlib.metadata.version()` 抛 `PackageNotFoundError`。重新跑 `packaging/build.py`，它已带 `.dist-info` 内容断言 |
| `可选 OCR 层没装：import rapidocr_onnxruntime 失败（…）` | 真没装 | `requirements/ocr.txt` 按序装 |
| `onnxruntime 没有可用 provider，现有 […]` | DirectML 不可用且 CPU 也没被列出 | 先看 `app.log` 里有没有 `OCR 引擎就绪 provider=…`；正常情况没有 DML 会退回 CPU，两者结果逐字一致（p5 实测）。两个 provider 都没有就是 ORT 装坏了 |
| `OCR 引擎初始化失败（provider=…）：<类型>: <原文>` | 引擎构造失败，异常原样留住 | 贴出这一整行求助；不要只说"OCR 起不来" |

装了可选层但**同时装了两个 ORT 发行版**（`onnxruntime` 与 `onnxruntime-directml` 共存）时，
`import` 不是报错而是**直接段错误**（退出码 **139**）。判据：`pip list | findstr onnxruntime` 出现两行。
处置：只留 `-directml`。顺带一条**不要修**的假告警：`pip check` 会说
`rapidocr-onnxruntime 1.4.4 requires onnxruntime, which is not installed.` —— 这是**故意**的（**ISSUES I3**），
依赖守卫 G21 把这条措辞列为唯一允许的 `pip check` 错误。

**跑到一半自己停了**：看 `app.log` 有没有触发每日页预算（`ocr_daily_page_budget`，默认 6,000 页/日）。
这是限流不是故障；预算口径见 `docs/OCR.md`。⚠️ 单页超时只能在推理**返回之后**判定，
超时那一页照样记账（**ISSUES I21**）—— 所以"今天用了几页"可能包含没产出正文的页。

## 七、数据库层面

| 现象 | 判据 | 处置 |
| --- | --- | --- |
| 库真的损坏 | 状态页/启动**不跑任何同步库检查**（见台账 **ISSUES I45**：`integrity_check`/`quick_check` 与库大小同量级，6.1GB 实测 19h+/452s，放进启动路径会冻死应用），所以损坏不会在这里被主动报出 —— 症状是**第一条坏 SQL 以 error + sqlite 原文进 `app.log`**；要主动核查跑离线探针 `tests/probes/p12_consistency.py` 的 `C1`（`integrity_check` + `foreign_key_check`，可自行限速，不在产品路径） | 立即按 `docs/BACKUP-RESTORE.md` §三 做法 A 拷一份现场，再用 `data\backups\` 里的快照恢复（§四）。**别在这个库上继续跑扫描** |
| `database is locked` | `busy_timeout_ms=5000` 用尽。第一屏「设置」块能看到生效值 | 多为两个进程共用同一数据根（比如同时跑探针和应用）。关掉多余进程；确认只有一份应用在跑 |
| 迁移失败 | `MigrationError` 带着 `snapshot` 路径；迁移在单事务里回滚，库停在原版本 | 快照就是回退点，路径写在异常里。按 §四 用 `Connection.backup()` 灌回去 |
| 队列里留有 `running` | p12 `C9` 那行：`running 0（必须为 0，否则上次退出没回收）` | 非 0 就启动一次应用 —— `WorkQueue.recover()` 会重新排队；实测杀进程后重启 `recovered` 非 0 且最终全部 `done` |

## 八、打包 / 冻结产物

| 现象 | 成因（都是实测过的） | 处置 |
| --- | --- | --- |
| exe 双击起不来，日志里 `迁移目录里一个迁移也没有` | PyInstaller 静态分析收不到 `db/migrations/*.py`（它们是"被发现才执行"的文件） | `packaging/build.py` 已有内容断言；重跑构建 |
| 冻结里 OCR 报"没装"，但 venv 里 `import` 正常 | **ISSUES I26**：`.dist-info` 默认不进包，`importlib.metadata.version()` 抛 `PackageNotFoundError` | 确认 spec 里的 `copy_metadata(...)` 还在；`build.py` 那行断言的实测输出应形如 `包内 ['onnxruntime_directml-1.20.1.dist-info', 'rapidocr_onnxruntime-1.4.4.dist-info']｜缺 无` |
| 冻结里 OCR 出 0 页 / 正文空 / 库内版本 None / `app.log` 没有 `OCR 引擎就绪` 行 | 全是上一行的派生症状，**不是四个独立故障** | 修 `.dist-info` 后四条一起消失（实测复跑 `VERDICT: ALL GREEN`） |
| 换机器起不来 | 缺 VC++ 运行库（onnxruntime / PyMuPDF 都依赖） | 见 `docs/INSTALL.md` §A.5；判断方法是命令行起一次看 stderr |
| 想在另一台机器确认 OCR 用没用上显卡 | —— | `findstr "OCR 引擎就绪" <数据根>\logs\app.log`，看 `provider=` 是 `DmlExecutionProvider` 还是 CPU |

## 九、"很慢" / 门禁自己变红了

- **冷启动超过 1.5s**：这是负载绑定读数。空载实测 **0.44–0.77s**，
  满载（CPU 96.5%、可用内存 2,199MiB）实测 **2.99–3.13s**（**ISSUES I25**）。
  判据：`state.log` 的 `window.ready.cold_start_seconds`，和 `app.log` 那行
  `冷启动 x.xxxs（进程起来→窗口就绪）门禁 G1 [约定] ≤1.5s`。
  处置：空载重跑，**不要放宽阈值**（这条是被明确禁止的处置）。
- **同一负载还会抬 OCR 耗时**：空载 **1,985–2,835ms/页** → 满载 **2,565–3,379ms/页**。
  跨负载比较这两个数没有意义。
- **内存**：OCR 真引擎单进程实测峰值 **806–1,131MiB**，G8 红线 1.2GB 的余量不足 100MiB，
  而且**从没在 UI + 索引 + OCR 同时活的情况下压测过**（**ISSUES I16**）。
  低内存机器上让 OCR 单独跑。
- **所有冷启动读数都是 `QT_QPA_PLATFORM=offscreen` 取的**，真机首屏没有人看过（**ISSUES I17**）。
  所以"启动慢"这句话目前不能用实测数据支持，也不能否认。

## 十、跑过归档之后（S3 执行 / S4 撤销）

从 2026-10-17 起这两个按钮**会真的改动磁盘上的文件**，所以多出一批过去不存在的现象。逐条：

| 现象 | 它是不是 bug | 怎么看 |
| --- | --- | --- |
| 「执行归档」按不动 | **不是**。三种原因之一：没点过「生成预览」；预览之后又改了勾选/目标根/命名模板（计划签名变了，必须重新预览）；目标盘剩余空间不够 | 界面上方那行空间读数会写差多少；前两种情况点「生成预览」就能恢复可点 |
| 预览里某些项写着「跳过（…）」 | **不是**。目标位置已有同名文件、源文件已不在磁盘、主记录被删、目标路径超过 240 字符、同一批里两项落到同一个位置 | 跳过项**不进执行**，回执里单独报「其中不进执行 N 项」；原因原文在那一行的最后一列 |
| 批次终态是 `partially_done` 而不是 `done` | **不是**，是有项 `failed`。一项搬不成不会带走整批 | S4 选中批次 → 明细表的「错误」列给逐条原因；更细的逐步过程在 `<数据根>\data\journal\op_<批次号>.jsonl` |
| 撤销时提示"没有可撤销的项"并逐条列原因 | **不是**。撤销只收可逆项：目标位置的文件已经被挪走/删掉，或者原位置已经被新文件占了，程序**不会凭空造文件、也不会覆盖它** | 弹窗里逐条原因与 S4 明细表一致；想撤其余的，重新执行一次归档把状态理清 |
| 搬完但库里路径还是旧的 | **是**，请报上来 | 执行器会 `update_path`（`test_搬运后id不变路径变分类还在` 钉着这条）；出现说明是真缺陷 |
| 搬到一半关了窗口 / 杀了进程 | 预期可恢复。每一条都是**先写 journal 再动文件**，重启时 `WorkQueue.recover()` 把停在 `running` 的任务重新排队 | 已完成的那几项不会重搬（目标已存在会被判跳过）；journal 逐行看它停在哪一步 |

**跨盘与同盘不是一回事**：同盘是一次 `rename`，不写 `dst_verified`；跨盘是
`copy2` → 读目标算 sha256 → **两边哈希相等才删源**。所以"跨盘搬完源还在"意味着校验没过，
文件是一份没少的重复，不是丢了；"跨盘搬完源没了"则必然意味着目标已经验过。

## 十一、求助前请准备这些（一次到位）

1. `crash.log` **最后一整段**原样粘贴（含 traceback），不要转述。
2. `state.log` 最后 10 行。
3. 界面「运行状态与自检」那一屏的**全文**（可以直接从 `QPlainTextEdit` 里选中复制）。
4. 数据根路径 + `(来源=…)` 那一行。
5. 你运行的到底是哪个产物：`PdfArchiver.exe`（冻结）还是 `python -m pdfarchiver.app`（源码），
   以及 `--version` 输出（当前 `PdfArchiver 0.5.0`）。
6. 一条只读核查结果：`p12_consistency.py --data-root "<数据根>"` 的完整输出。
7. 出问题时的机器负载（任务管理器：CPU 占用、可用内存），因为 §九 那批红是这个原因。

## 十二、这份文档里"还不知道怎么修"的清单

诚实记录，对应 `docs/ISSUES.md`：

| 编号 | 事实 | 现在的处置 |
| --- | --- | --- |
| ISSUES I5 | 监听根被改名/删除，watchdog 一个事件都不发 | 靠 30 分钟周期校验兜；不是修好的 |
| ISSUES I10 | 长路径 + 第三方工具（Git / 资源管理器）看不见深层目录 | 归档前 `validate_path_length` 自检 + `PathTooLongError` 可读文案 + S3 预览「路径长度」项已落地；**残留**：清理统一走 `\\?\` 前缀的 `shutil.rmtree` 兜底还没做 |
| ISSUES I8 | 外部内容 FTS 的倒排幽灵没有免词检测口径 | 检索通路 `JOIN` 兜住用户 + `rebuild_fts()` 补救 |
| ISSUES I21 | 单页超时无法中途取消，杀推理线程会漏约 701MiB 显存 | 不做运行中取消；连续超时熔断器（阈值 3）已落地，整本病态页时才停 |
| ISSUES I16 | 组合内存上限从未压测 | OCR 单独跑；低内存机器注意 |
| ISSUES I17 / ISSUES I25 | 首屏从未在真实桌面平台核对；性能阈值负载绑定 | 空载重跑；不放宽阈值 |
| ISSUES I22 | 库损坏 = 已 OCR 正文（169 天量级）归零 | S6 有备份 / 恢复按钮（`docs/BACKUP-RESTORE.md`）；**残留**：备份只快照 `catalog.db`、无定时自动备份、恢复不跑 `integrity_check`（坏库直接恢复会照搬损坏） |
| ISSUES I67 | 扫描件识别没有界面触发入口：S7 只有 O1/O2/O3 三个读数，不会自动排队 | OCR 任务必须按 `doc_id` 点名（D-028），入口见 `docs/OCR.md`；界面入口受 AGENTS.md 线框纪律约束，本轮只入账 |
