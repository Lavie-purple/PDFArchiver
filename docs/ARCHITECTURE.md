# 架构与模块边界

依据 `PROJECT_SPEC.md` 4.1 的 11 层划分。本文件定义**每个目录负责什么、不许负责什么**，
阶段 1 起按此落地，不允许把文件操作、数据库、UI、搜索、OCR、AI 写进同一个模块。

## 一 · 目录结构

★ = 阶段 1 已落地且有测试覆盖；没标的仍是**设计落点**，现在不存在（不是遗漏，见 `docs/ROADMAP`）。

```
src/pdfarchiver/
  __init__.py★
  app.py★                 # 组合根：建容器、接线、启动/退出。不含业务规则
  config/                 # 设置读写、数据目录解析、默认值表
    paths.py★             #   数据目录三级解析（参数 > 环境变量 > %LOCALAPPDATA%）+ describe() 带来源
    settings.py★          #   唯一口径：设置项名字 + 默认值 + 校验 + describe 三列
  db/                     # 数据库与索引层
    engine.py★            #   连接工厂（每线程独立连接）、WAL、busy_timeout、Backup 快照、integrity_check
    migrate.py★           #   先快照后动结构；一个迁移一个事务（isolation_level=None + BEGIN IMMEDIATE）
    models.py★            #   表结构常量与行数据类
    migrations/★          #   0001_initial.py（13 张表）+ 0002_text_and_fts.py★（阶段 2：正文表 + 外部内容 FTS + 三触发器）
    repositories/★        #   documents/catalog/roots/jobs/settings/text/metadata；只有这里能写 SQL
    sqltext.py★           #   SQL 片段的唯一拼装处（占位符与 IN 列表），仓储层共用
  fs/                     # 文件扫描与监测层
    identity.py★          #   路径规范化与文件身份（规则见 docs/VERIFICATION 4.8 与 docs/DATABASE 二·2.1）
    scanner.py★           #   全量/增量扫描，产出变更集（流式 os.scandir，绝不整本读进内存）
    digest.py★            #   分块 sha256（HASH_CHUNK_BYTES=1MiB），最大单文件 1.1GB 也不能 read() 一把
    watcher.py★           #   watchdog 封装，只产事件，不改库；处理器必须继承 FileSystemEventHandler（D-027）
                          #   EventBuffer 是界与 worker 之间唯一的传话处；is_alive() 是断流的唯一读数出口
    exclude.py            #   排除规则
  parsing/                # 文档解析层
    pdf.py★               #   PyMuPDF：元数据、页数、文本抽取、渲染、search_for（阶段 3 才用渲染）
    classify.py★          #   原生/扫描/混合判定（text_bearing_rate，阈值 0.5 / 0.1，每页 ≥40 字算带字）
  indexing/               # 全文搜索层
    fts.py★               #   trigram MATCH 表达式构造（含转义）+ 1–2 字退回 LIKE 的口径分界
    snippets.py★          #   命中片段与页码（Python 侧算偏移，FTS5 无 offsets()）
    normalize.py★         #   入库前只做一件事：连续空白压成一个空格。不改大小写、不删标点、不裁长度
  search/★                # 搜索编排：文件名/元数据/全文/筛选/排序（四通道各自可断言，合并去重限量）
  ocr/                    # OCR 引擎层（**可选层整体缺席**：没装 rapidocr 时应用照常起，只报"OCR 不可用"）
    engine.py★            #   RapidOCR 封装：版本指纹（故意不含 provider，D-029）、串行锁（D-008）、
                          #   逐页返回错误对象而不抛（I 类事故：一本坏书拖死 worker）
    budget.py★            #   两条资源限量的唯一出处：单页超时（按 provider 分档）+ 每日页预算（UTC 日记账，D-028/D-032）
                          #   推导关系由 tests/unit/test_ocr_limits.py 钉住 —— 改数必须同时改实测出处
  semantic/               # 语义搜索与本地 AI 层（**可整体缺席**）
    embedder.py           #   ONNX 向量；模型缺失时抛 ModelUnavailable
    vector_store.py       #   独立向量索引文件
    hybrid.py             #   关键词 + 向量融合
    suggest.py            #   分类建议，只产建议，不落库
  fileops/                # 文件操作与恢复层（唯一能动用户文件的地方）
    plan.py               #   生成操作计划（预览用，绝不碰磁盘）
    journal.py            #   操作日志：执行前写盘，崩溃可恢复
    execute.py            #   执行 + 校验 + 失败记录
    undo.py               #   撤销计划
  jobs/★ queue.py         # 暂停/恢复/重试/进度/并发上限；ProgressMonitor 是处理函数唯一的进度笔
  backup/                 # 备份、恢复、迁移
  services/               # 应用服务层：把上面各层编排成用例
    scan_service.py★      #   scan 任务体 + 单条事件对账（快路）；唯一写 documents 文件事实的地方
    index_service.py★     #   index 任务体；四条口径见文件头（sha256 短路 / fts_status 不写 running）
    ocr_service.py★       #   ocr 任务体：入场券（ocr_ready）→ 页级幂等待办 → 逐页识别 → 按页落库带版本 →
                          #   进同一张 FTS；回执分四类（点名/该跑/新增/为什么没进，D-031）；限量在这里判停（D-028）
    patrol.py★            #   界面定时器上的巡检：只排任务，自己绝不扫目录（慢路 = 周期全量校验）
    bootstrap.py★         #   装配顺序就是规矩：目录→日志→设置→连接→迁移→模板→自检
    status_service.py★    #   界面唯一取数口；只读、不缓存
    session_service.py★   #   导航记忆等内部状态，让 UI 不必 import 仓储层
    default_catalog.py★   #   SPEC 3.3 的 14 个分类模板（数据不是代码）；靠标记"种一次"
  ui/                     # UI 层，只用 services/，不 import db.repositories
    nav.py★               #   导航注册表，按 SPEC 条款号登记；阶段 1 唯一的"界面知识"
    main_window.py★       #   外壳：左导航 + 右堆叠页 + 状态栏；关窗真关连接并留对账行
    pages/★               #   status_page（自检页，全是从库里算出的事实）/ pending_page（未实现说明页）
                          #   其余每屏一个文件、对应 docs/UI-SCREENS.md 的编号 —— 等 Q7
    workers.py            #   QThread/Signal 桥；主线程绝不做扫描/索引/OCR
    models_qt.py          #   Qt 表格/树模型（虚拟化）
  diagnostics/
    logs.py★              #   app.log（轮转）/ crash.log（sys+threading excepthook）/ state.log（一行一条 JSON）
                          #   时间戳唯一口径 log_stamp() = UTC ISO 带 Z（D-022）
tests/
  probes/                 # p0..p8 阶段 0 技术前提探针（保留可重跑）+ p9★ 反向注入（验断言有没有牙齿）
                          # 阶段 5 新增：p10★ OCR 反向注入 45 条、p11★ 产品路径端到端实测（真语料扫描件）
  unit/★                  # 纯逻辑，无 UI、无真实文件；阶段 5 新增 ocr_engine 18 / ocr_idempotency 22 / ocr_limits 6
  integration/★           # 临时目录 + 真实 SQLite；阶段 1：装配与迁移 / 仓储 / 异常处理 / 应用外壳
                          # 阶段 2 新增：扫描 34 / 队列 29（含三种"停"各一条）/ 索引 23 / 检索 20 / 状态 16 / 监听接线 10
                          # 阶段 5 新增：ocr_service 33 / ocr_budget 8 / ocr_real_engine 4（真推理，装了可选层才跑）
  guards/★                # pytest 形态的常驻守卫：依赖版本锁（G21）、架构方向 / SQL 位置 / 静默吞异常 /
  #                         本机路径字面量 / 导航分组（AST）、迁移不丢数据
  e2e/★                   # 阶段 2 已建：真 worker + 真 watchdog + 真 PDF，11 条全链验收
  load/                   # ×10 量级压测仍未建（等 Q8 给出真实监测范围，见 ISSUES I16/I20）
gates/
  stage1.py★              # 阶段 1 门禁链：G21→架构守卫→全量回归→冷启动实测→反向注入，末行 VERDICT
  stage2.py★              # 阶段 2 在其上加两步：后台生命周期（state.log 三行齐全）+ e2e 验收（搬回真实检索行）
  stage5.py★              # 阶段 5 在其上加三步：产品路径端到端实测（现场打印耗时/内存/显卡/质量/追溯/幂等/控制组）、
                          #   每日页预算真停机、真引擎套件不许退化成 skip。**这条门禁里不许出现任何写死的性能数字**
  # 01_deps_guard … 09_readback 那份拆分是阶段 7 的形态；没到对应阶段不建空门禁（R-007）
docs/                     # 工程文档，入口是 docs/README.md；文件名见那张表
requirements/             # 分层依赖清单
```

## 二 · 依赖方向（只能自上而下）

```
ui  →  services  →  {fs, parsing, indexing, search, ocr, semantic, fileops, backup}
                        ↓
                       db  →  config
```

禁止：
- `ui` import `db.repositories`、直接写 SQL、直接调 PyMuPDF
- `fs`/`parsing`/`indexing` import `ui`（回调用注入的协议，不是 Qt 信号）
- `ocr`/`semantic` 被 `search` 硬依赖：语义模块必须可整个缺席
- 任何层 import `fileops.execute`（只有 `services/archive_service` 能）

守卫测试 `tests/guards/test_architecture.py` 用 AST 扫 import，违反即 RED。

## 三 · 线程与并发模型

实测约束（P1/P3/P4）：
- `sqlite3.Connection` 默认 `check_same_thread=True` → **每个后台 worker 自己开一条连接**，不共享。
- WAL 下 1 写多读实测可行：写 2 万行期间并发读 12 次，最大 1.01ms，0 错误。
- Qt 跨线程用 `Signal` + `QueuedConnection` 实测可靠投递（P3）。

模型：
- 主线程：只做 UI 与轻量状态更新。
- `jobs/` 维护 N 个 worker 线程（默认 2，可调），每个 worker 一条 DB 连接、一个 `DocContext`。

**阶段 2 落地后这条链上真跑的线程**（`gates/stage2.py` 的 `state.log` 读数可核对：
`background.started` 里 `threads=2` + 1 条 observer）：

| 线程 | 谁起 | 干什么 | 死了会怎样 |
| --- | --- | --- | --- |
| 主线程 | Qt | 渲染 + 状态栏 + **巡检定时器** | 应用没了 |
| worker × `worker_threads`（默认 2） | `WorkQueue.start()` | 领 `scan` / `index` / `ocr` 任务；每线程一条 sqlite 连接（`engine.thread_connection()`） | `threading.excepthook` 落 `crash.log`（阶段 2 修好的一条，见 D-027） |
| `WindowsApiObserver` | `WatchManager.start()` | 把磁盘事件塞进 `EventBuffer`，**不碰库** | **以前没人知道**：`watched_roots` 照旧是 1。现在有 `is_alive()` → `BackgroundState.watcher_alive` → 状态页 ⚠ 行 |

两条纪律是阶段 2 实测逼出来的：
- **界面定时器上绝不扫目录**。`patrol` 只做两件事：排空事件缓冲逐条对账（一个 `stat`），
  以及"脏根或到点了 → 排一条 `scan` 任务"。8,000 份的一次全量走查放在主线程就是冻界面几秒到几十秒
  （AGENTS.md 禁止全量加载）。
- **处理函数拿不到 `JobRepository`**，只有 `ProgressMonitor`（写进度 + 问该不该停）。
  它一旦能直接写状态，就能写出状态流转表里不存在的边（D-025）。
- **GPU 任务全局串行**：P5 孤跑实测单个 OCR(DirectML) 进程吃掉 **701MiB** 显存，把本机空闲从 1369MiB 压到 668MiB；
  而嵌入模型（P6 fp32）也要在同一块卡上跑。两个 GPU 任务同时启动就是 1400MiB > 1369MiB，直接 OOM。
  **阶段 5 已落地的那一半**：串行做在 `ocr/engine.py` 的实例锁里（`test_多线程推理同一时刻只有一个在跑`），
  两个 worker 同时领到 OCR 任务也只会有一个在推理，另一个排在锁上 —— 队列不需要知道"这是 GPU 任务"。
  嵌入层（阶段 6）必须与 OCR 抢**同一把**全局锁，不能各锁各的。
- **OCR 的内存纪律是"一次一张图"**：`parsing/pdf.py` 出图 + `ocr_service` 逐页落库，任何"先把 N 页都渲好再一起识别"
  的写法在 946 页的书上就是 946 × 单页位图。门禁 G8 实测峰值 806–1,131MiB（启动态 72.4MiB），
  距离 1.2GB 的红线**余量不足 100MiB**（I16）—— 这也是为什么它只在**单 worker 实际推理**时成立。
- **三种"停"各有各的收尾**（D-030，阶段 5 是被这条测出来的）：用户请求取消 → 库里已是 `cancelled`；
  退出闸门拉下 → 行留 `running`，交给下次启动的 `recover()`；处理函数自己判停（抛 `JobCancelled`，
  预算用满 / 单页超时都是这种）→ 落 `cancelled` **终态**并把原因写进 `last_error`，不消耗重试预算。
  三者混淆的代价不一样：把判停写成 `done` 就是"这半本书永远不再被补"，把退出写成 `cancelled` 就是"关个应用把在跑的任务作废"。
- 取消：worker 每处理一页检查一次取消位；PyMuPDF 的页面级调用是可安全中断的粒度。
  **但 ONNX 推理一旦提交就收不回来** —— 单页超时只能在返回之后判定，判超时的同时 GPU 时间已经烧掉（I21）。

## 四 · 三层检索的依赖关系（SPEC 第 4 条要求明确）

```
文件名 / 元数据  ──► SQLite 普通列 + LIKE              依赖：仅 db
正文全文        ──► FTS5(trigram)                     依赖：parsing 抽出的文本
OCR 文本        ──► 同一张 FTS5，source_kind='ocr'     依赖：ocr 层（可失败、可重试）
语义向量        ──► 独立向量库                          依赖：semantic 层（可整体缺席）
```

硬性要求（已写进 p2/p6 探针）：
- 模型/OCR 不可用时，前两层必须照常工作。`search` 对 `semantic` 的依赖是**可选注入**，
  `ModelUnavailable` 只降级结果、不报错给用户的关键词搜索路径。
- 语义结果必须带来源（文档/页码/原文片段），UI 上必须与关键词命中视觉区分，
  不许把模型推测显示成文档原文。

## 五 · 关键设计决策（含已验证依据）

本表按**架构视角**汇总，权威登记在 `docs/DECISIONS.md`，编号列直接用那边的 `D-0NN`
（避免同一件事有两个口径）。改结论改 `DECISIONS.md`，本表只跟着同步。

| 登记号 | 决策 | 依据 | 状态 |
| --- | --- | --- | --- |
| D-004 | 全文用 FTS5 `trigram` 外部内容表 | P1：中文查询命中正常，30 万行 13.7s；`unicode61` 命中 0 | 已验证（分词策略待 Q1 确认） |
| D-015 | 命中偏移在 Python 侧算，不用 `offsets()` | P1：`pragma_function_list` 证明 FTS5 只有 `rank/snippet/bm25/highlight` | 已验证 |
| D-015 | 外部内容表必须配 3 个触发器，delete 命令带上被索引列 | P1 `delete_trigger_trap`：漏列不报错，留下删不掉的幽灵行 | 已验证 |
| D-005 | 路径身份用 `realpath` 不是 `normpath` | P7：8.3 短名把空格吃掉（`报告 A.pdf`→`报告A~1.PDF`），纯字符串无法归一 | 已验证 |
| D-005 | 主记录唯一性用 `path_key COLLATE NOCASE` 唯一索引 | P7：重叠根重复扫描 3 条记录不膨胀；大小写变体被索引拒绝 | 已验证 |
| D-007 | OCR/嵌入后端默认 DirectML，CPU 兜底 | P5：OCR **6.36×**（25,835→4,062ms/页均值）；P6：嵌入 **7.8×**（18.8→146.9 chunks/s）；CUDA 本机实测不可用 | 已验证 |
| D-007 | 量化（int8）**不作为提速手段**，只用于省体积 | P6：int8+DirectML 79.3 chunks/s **慢于** fp32 的 146.9 —— 「量化必提速」已被证伪 | 已验证 |
| D-006 | OCR 移出自动索引流程，改为显式触发 | P5：全量 101 万页需 1,144h(DML)，而无人值守预算反算是 284ms/页，实测 3,281ms | 已验证（范围待用户勾，docs/RISKS 2.2） |
| D-002 | onnxruntime 只装 directml 单一发行版 | 2.2：两个发行版共存导致 import 段错误 | 已验证 |
| D-016 | 全文与向量分库存放 | P1：trigram 索引 ≈ 原文 6.9×；P6：4.04M 向量 fp32 ≈ 7.7GB | 设计中 |
| D-017 | 阅读器用 PyMuPDF 渲染 + QtPdf 备选 | P3：两条通道都出图，fitz 135ms/页中位、QtPdf 43–50ms | 已验证 |
| D-009 | 不依赖文件监听作为唯一变更来源 | P4：被监听目录自身被重命名 → 0 事件；必须定期全量校验 | 已验证 |
| D-018 | 阶段 1 的 UI 只交付**运行时外壳**：导航由注册表驱动，产品屏一律 `implemented=False` | 线框未逐屏确认（AGENTS.md 禁止写界面代码）+ Q7 未答；`test_没有占位控件` 与注入 I11 钉住"外壳里没有假控件" | 已验证（产品屏数仍等 Q7） |
| D-019 | 用户设置存 `config/settings.json`，应用内部状态存 `app_settings` 表，**两处各一个口径** | 阶段 1 实测：`test_设置持久化跨重启`；启动打印"默认值/覆盖值/来源文件"，注入 I9 证明种子标记有约束力 | 已验证 |
| D-021 | 性能数字由**被测进程自己**写进 `state.log`，门禁与界面读同一条字段 | 避免"门禁掐一次表、界面显示另一个数"两个口径；注入 I13/I14 证明读数真参与判定 | 已验证 |
| D-022 | 日志时间戳唯一口径 = UTC ISO 8601 带 `Z`（`log_stamp()`），含 `app.log` 行首 | 反向注入 I16：裸本地时间标 `Z` 格式合法、时刻差 8 小时，只有跨表比时刻抓得住 | 已验证 |
| D-023 | 结构迁移"先快照后动结构"，无备份目录直接拒绝；`isolation_level=None` + `BEGIN IMMEDIATE` | 阶段 1 实测：`test_迁移中途失败回到原样`、`tests/guards/test_migrations.py` 8 条（0003 之后重数）、注入 I6/I7 | 已验证 |
| D-024 | 正文 + `content_fts` 进 `catalog.db` 本体；向量另库 | FTS5 外部内容表只能指向同库有 rowid 的表（p1）；分库等于放弃外部内容表、正文再拷一份（p2 膨胀 4.03–6.91×） | 已验证（迁移 0002 + G10 常驻） |
| D-025 | 处理函数只有 `ProgressMonitor` 两支笔；`done` 的进度补齐在 `JobRepository.succeed()` 里做；收尾按库里状态判流转 | 阶段 2 实测：`test_进度按步长攒着写最后补齐`、`test_试满上限后不再算重试而是留下失败终态`、e2e 残尸回收；注入 I19/I23 | 已验证 |
| D-026 | `PermanentFailure` 只消耗 1 次尝试，重试预算（3 次）留给瞬时故障 | 阶段 2 实测：损坏/加密文件各 1 次即终态，好文件不受牵连（e2e）；重试上限的唯一持有者是 `WorkQueue.max_attempts` | 已验证 |
| D-027 | 接第三方库回调的测试必须 import 产品里那个类；每个可能静默死掉的部件要有唯一

**这张视图只同步到 D-027**：阶段 5 与最终交付轮的 **D-028…D-034**（OCR 限量停机 / 版本指纹 / 页级幂等 /
被杀恢复 / 性能假红不改阈值 / 交付链只编排）没往这里搬，**权威登记在 `docs/DECISIONS.md`**。
搬动它们不是本轮的事，写在这里是为了别让人以为这张表是全量。只读数字 | 阶段 2 两个真实事故：watchdog 缺 `dispatch`（observer 死掉而界面显示 1 个根在听）、`threading.excepthook` 读不存在的 `args.exc_info`（现场全丢）；注入 I38–I44，其中 I43 第一版抓不到、补"半路死亡"测试后才有牙 | 已验证 |

## 六 · 明确不做（阶段 0 决定，不是遗漏）

- 不支持 DOCX/XLSX/PPTX/EPUB 解析归档（SPEC 2.1）。
- 不做图书馆业务（借阅/ISBN/馆藏，SPEC 2.2）。
- 首版不做 PDF 编辑、批注保存。
- 不自动移动、合并、删除用户文件（SPEC 3.6/3.7；默认只报告）。
- 不引入云端服务；不上传任何文档内容、文本、向量、元数据。
