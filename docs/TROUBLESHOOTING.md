# 故障排查

> 写法约定：每条都是「现象 → 第一去处 → 判据 → 处置」，并标出对应的 `docs/ISSUES.md` 编号。
> 所有引号里的字符串是代码或日志里的**原文**，不是转述（AGENTS.md：排障只认原始证据）。
> 求助时请把 `crash.log` 的完整一段原样贴出来，不要转述成"它报了一个错"。

## 〇、先搞清三件事，后面都靠它

**1）你的数据根在哪。** 启动时界面第一屏就写着，长这样：

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

**3）退出码**：`0` 正常；`2` 启动失败。`console=False` 打包出来的 exe **没有 stdout**，
所以双击失败时屏幕上什么都没有 —— 这是已知缺口（**I18**），不是你的机器坏了。

## 一、双击没反应 / 一闪就没了（I18）

1. 先看 `crash.log` 是否存在。存在 → 直接跳到最后一节的原文，按它的内容对症下药。
2. 不存在 → 看 `state.log` 有没有 `window.ready`。有，说明窗口真起来了，只是被别的窗口挡住或在别的显示器上。
3. 两条都没有 → 用命令行起一次，让 stderr 露出来：
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

## 二、界面上除了「运行状态与自检」全是"未实现"

**这不是坏了。** 阶段 3 的界面线框（Q7）没逐屏确认，按 AGENTS.md 的禁令一行界面代码都没写（**I15**）。
现在能用的能力与它们真正的入口，见 `docs/USAGE.md` §一 那张表。
`docs/ISSUES.md` I23 记的正是这件事的后果：OCR 的预算与跳过原因在界面上没有出口。

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
| 一个文件都没扫到 | 从没注册监测根（**界面上没有注册入口**） | 按 `docs/USAGE.md` §四 用 `roots.add(path, identity_key(path))` |
| 只扫到一半 | 监测根路径写法与实际不符：`root_key` 存的是**规范化后小写**的形式 | 用 `identity_key(路径)` 生成，别手写字符串 |
| 深层中文目录看不见 | 长路径限制（**I10**）。本机 `LongPathsEnabled=1`，最深实测 **533 字符**仍成功，但**第三方工具**（Git、资源管理器）可能看不见 | 缩短目录层级或把根挪到浅位置；阶段 4 才给可读的错误文案 |
| 根目录被改名或删除后毫无反应 | watchdog 对这件事**完全盲**（实测 **0 事件**，**I5**） | 等周期校验（默认 30 分钟，`scan_verify_minutes`）或手动跑一次全量对账 |
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
3. **是扫描件，且那一页从没显式跑过 OCR。** OCR 正文只处理你点名的页（D-028，**I1**）。
   判据：状态页 `OCR 状态：… 库里已存 OCR 正文 x 页`；`docs/OCR.md` 有全量口径（1,014,112 页 ≈ 169 天）。
4. **正文还没索引完。** 状态页 `文档索引状态：共 N 份｜done=…｜还欠一次索引 x（口径 pending+stale）`。
   非 0 就还没跑完；跑完再看。
5. **索引与正文表对不齐。** 判据：p12 `C4` 那行
   `正文 544 行｜花名册 544 行｜漏索引 0｜花名册残留 0`。
   `漏索引 > 0` → 有页没进倒排，跑 `ctx.indexer.rebuild_fts()`（实测能把漏的补回来）。
   ⚠️ **已知仪器盲区（I8）**：外部内容表的"幽灵行"（已删正文仍留在倒排里）**没有免词的检测口径** ——
   `count(*) FROM content_fts`、`rowid NOT IN (…)`、`integrity_check` 在坏状态下全部看不出问题。
   你现在看不到幽灵结果，只因为检索通路每次 `JOIN text_pages`；`rebuild_fts()` 是补救入口
   （`tests/probes/p14_fts_instrument.py` ⑤：三种坏法叠进同一份库时 `漏索引 1 / 花名册残留 1 / 倒排幽灵 2`，
   一次 rebuild 后三个数全归 0。它返回六个数（`pages`、`docs`、`unindexed_before`、`unindexed_after`、
   `stale_before`、`stale_after`），也就是"补之前欠了多少、补之后还剩多少"的现场对账）。

## 六、OCR 相关的四类报错（原文照抄）

| 原文 | 含义 | 处置 |
| --- | --- | --- |
| `可选 OCR 层没装：缺发行包 rapidocr-onnxruntime。装法见 requirements/ocr.txt（必须按文件里的顺序装，先装 onnxruntime-directml 再装 rapidocr）` | 版本指纹读不到发行包元数据 | **源码环境**：按顺序重装。**冻结产物**里出现这句基本就是 **I26** —— 打包没收 `.dist-info`，模块 import 得到但 `importlib.metadata.version()` 抛 `PackageNotFoundError`。重新跑 `packaging/build.py`，它已带 `.dist-info` 内容断言 |
| `可选 OCR 层没装：import rapidocr_onnxruntime 失败（…）` | 真没装 | `requirements/ocr.txt` 按序装 |
| `onnxruntime 没有可用 provider，现有 […]` | DirectML 不可用且 CPU 也没被列出 | 先看 `app.log` 里有没有 `OCR 引擎就绪 provider=…`；正常情况没有 DML 会退回 CPU，两者结果逐字一致（p5 实测）。两个 provider 都没有就是 ORT 装坏了 |
| `OCR 引擎初始化失败（provider=…）：<类型>: <原文>` | 引擎构造失败，异常原样留住 | 贴出这一整行求助；不要只说"OCR 起不来" |

装了可选层但**同时装了两个 ORT 发行版**（`onnxruntime` 与 `onnxruntime-directml` 共存）时，
`import` 不是报错而是**直接段错误**（退出码 **139**）。判据：`pip list | findstr onnxruntime` 出现两行。
处置：只留 `-directml`。顺带一条**不要修**的假告警：`pip check` 会说
`rapidocr-onnxruntime 1.4.4 requires onnxruntime, which is not installed.` —— 这是**故意**的（**I3**），
依赖守卫 G21 把这条措辞列为唯一允许的 `pip check` 错误。

**跑到一半自己停了**：看 `app.log` 有没有触发每日页预算（`ocr_daily_page_budget`，默认 6,000 页/日）。
这是限流不是故障；预算口径见 `docs/OCR.md`。⚠️ 单页超时只能在推理**返回之后**判定，
超时那一页照样记账（**I21**）—— 所以"今天用了几页"可能包含没产出正文的页。

## 七、数据库层面

| 现象 | 判据 | 处置 |
| --- | --- | --- |
| 状态页 `完整性检查 integrity_check =` 后面不是 `ok` | `Engine.integrity()` 返回第一条损坏描述，绝不抛 | 立即按 `docs/BACKUP-RESTORE.md` §三 做法 A 拷一份现场，再用 `data\backups\` 里的快照恢复（§四）。**别在这个库上继续跑扫描** |
| `database is locked` | `busy_timeout_ms=5000` 用尽。第一屏「设置」块能看到生效值 | 多为两个进程共用同一数据根（比如同时跑探针和应用）。关掉多余进程；确认只有一份应用在跑 |
| 迁移失败 | `MigrationError` 带着 `snapshot` 路径；迁移在单事务里回滚，库停在原版本 | 快照就是回退点，路径写在异常里。按 §四 用 `Connection.backup()` 灌回去 |
| 队列里留有 `running` | p12 `C9` 那行：`running 0（必须为 0，否则上次退出没回收）` | 非 0 就启动一次应用 —— `WorkQueue.recover()` 会重新排队；实测杀进程后重启 `recovered` 非 0 且最终全部 `done` |

## 八、打包 / 冻结产物

| 现象 | 成因（都是实测过的） | 处置 |
| --- | --- | --- |
| exe 双击起不来，日志里 `迁移目录里一个迁移也没有` | PyInstaller 静态分析收不到 `db/migrations/*.py`（它们是"被发现才执行"的文件） | `packaging/build.py` 已有内容断言；重跑构建 |
| 冻结里 OCR 报"没装"，但 venv 里 `import` 正常 | **I26**：`.dist-info` 默认不进包，`importlib.metadata.version()` 抛 `PackageNotFoundError` | 确认 spec 里的 `copy_metadata(...)` 还在；`build.py` 那行断言的实测输出应形如 `包内 ['onnxruntime_directml-1.20.1.dist-info', 'rapidocr_onnxruntime-1.4.4.dist-info']｜缺 无` |
| 冻结里 OCR 出 0 页 / 正文空 / 库内版本 None / `app.log` 没有 `OCR 引擎就绪` 行 | 全是上一行的派生症状，**不是四个独立故障** | 修 `.dist-info` 后四条一起消失（实测复跑 `VERDICT: ALL GREEN`） |
| 换机器起不来 | 缺 VC++ 运行库（onnxruntime / PyMuPDF 都依赖） | 见 `docs/INSTALL.md` §A.5；判断方法是命令行起一次看 stderr |
| 想在另一台机器确认 OCR 用没用上显卡 | —— | `findstr "OCR 引擎就绪" <数据根>\logs\app.log`，看 `provider=` 是 `DmlExecutionProvider` 还是 CPU |

## 九、"很慢" / 门禁自己变红了

- **冷启动超过 1.5s**：这是负载绑定读数。空载实测 **0.44–0.77s**，
  满载（CPU 96.5%、可用内存 2,199MiB）实测 **2.99–3.13s**（**I25**）。
  判据：`state.log` 的 `window.ready.cold_start_seconds`，和 `app.log` 那行
  `冷启动 x.xxxs（进程起来→窗口就绪）门禁 G1 [约定] ≤1.5s`。
  处置：空载重跑，**不要放宽阈值**（这条是被明确禁止的处置）。
- **同一负载还会抬 OCR 耗时**：空载 **1,985–2,835ms/页** → 满载 **2,565–3,379ms/页**。
  跨负载比较这两个数没有意义。
- **内存**：OCR 真引擎单进程实测峰值 **806–1,131MiB**，G8 红线 1.2GB 的余量不足 100MiB，
  而且**从没在 UI + 索引 + OCR 同时活的情况下压测过**（**I16**）。
  低内存机器上让 OCR 单独跑。
- **所有冷启动读数都是 `QT_QPA_PLATFORM=offscreen` 取的**，真机首屏没有人看过（**I17**）。
  所以"启动慢"这句话目前不能用实测数据支持，也不能否认。

## 十、求助前请准备这些（一次到位）

1. `crash.log` **最后一整段**原样粘贴（含 traceback），不要转述。
2. `state.log` 最后 10 行。
3. 界面「运行状态与自检」那一屏的**全文**（可以直接从 `QPlainTextEdit` 里选中复制）。
4. 数据根路径 + `(来源=…)` 那一行。
5. 你运行的到底是哪个产物：`PdfArchiver.exe`（冻结）还是 `python -m pdfarchiver.app`（源码），
   以及 `--version` 输出（当前 `PdfArchiver 0.5.0`）。
6. 一条只读核查结果：`p12_consistency.py --data-root "<数据根>"` 的完整输出。
7. 出问题时的机器负载（任务管理器：CPU 占用、可用内存），因为 §九 那批红是这个原因。

## 十一、这份文档里"还不知道怎么修"的清单

诚实记录，对应 `docs/ISSUES.md`：

| 编号 | 事实 | 现在的处置 |
| --- | --- | --- |
| I18 | 双击失败时界面不给任何提示，只能去翻日志目录 | 临时缓解就是本文 §一；错误上报屏属 Q7 之后的界面范围 |
| I5 | 监听根被改名/删除，watchdog 一个事件都不发 | 靠 30 分钟周期校验兜；不是修好的 |
| I10 | 长路径 + 第三方工具看不见深层目录 | 阶段 4 归档前自检 + 可读文案 |
| I8 | 外部内容 FTS 的倒排幽灵没有免词检测口径 | 检索通路 `JOIN` 兜住用户 + `rebuild_fts()` 补救 |
| I21 | 单页超时无法中途取消，杀推理线程会漏约 701MiB 显存 | 不做运行中取消；整本病态页时才考虑熔断 |
| I16 | 组合内存上限从未压测 | OCR 单独跑；低内存机器注意 |
| I17 / I25 | 首屏从未在真实桌面平台核对；性能阈值负载绑定 | 空载重跑；不放宽阈值 |
| I22 | 库损坏 = 几天的 GPU 时间归零，且没有备份/恢复功能 | 只有手工路径，见 `docs/BACKUP-RESTORE.md` |
