# 变更日志

按阶段记录。版本号口径：阶段 0–7 全部走完并通过发布门禁才叫 `1.0.0`；在此之前一律 `0.x.y`，
且 `x` = 已完成的阶段号。**本文件只记实际做过并验证过的变更**，未落地的写在 `ROADMAP.md`，不写在这里。

---

## 0.2.0 · 阶段 2 文件扫描、PDF 识别与全文索引 —— 2026-10-14

验收口径来自 SPEC 阶段 2 的 5 条 + 你的阶段 2 指令 10 条，逐条实测结论在
`docs/stage-reports/阶段2-交付报告.md`。**仍然没有产品界面**：只扩展了已批准的「运行状态与自检」页，
Q7 未答，线框未确认，所以一屏新界面都没画（AGENTS.md 禁令）。

### 新增

- **一条真跑通的链路**：`fs`（scanner / digest / exclude / watcher）→ `parsing`（pdf / classify）→
  `indexing`（fts / normalize / snippets）→ `jobs`（WorkQueue + ProgressMonitor）→
  `services`（scan_service / index_service / patrol / status_service）→ `search`（四通道编排）。
  产品代码从 32 个文件 1,943 行长成 **54 个文件 5,560 行**。
- **迁移 0002**：`text_pages` + `content_fts`（FTS5 外部内容表，`tokenize='trigram'`）+ 三条触发器，
  `documents` 加 `device_id`、`text_bearing_rate`。这是本项目第一次**在带数据的库上**加结构。
- **四条检索通道各自可断言**：文件名 / 路径 / 元数据 / 正文。正文命中给**真页码**与可高亮片段；
  没勾正文时结果里明说"本次没有搜正文"，不许谎称走了 trigram；1–2 字查询退回 LIKE 并标注口径。
- **e2e 层**（`tests/e2e/test_stage2_acceptance.py`，11 条）：只调 `bootstrap()` + `start_background()`，
  然后只做磁盘动作，**全程不手调 `scan_root` / `index_document`**。语料现造：真扫描件（只有图没有字）、
  真截断 PDF、真 AES-256 加密件、重叠根、非 PDF 文件。
- **门禁 `gates/stage2.py`**：在 stage1 之上加两步 —— 后台生命周期（`state.log` 里
  `window.ready` → `background.started` → `shutdown` 三行齐全）与 e2e 验收（把子进程打印的真实检索行搬回门禁）。
- **状态页新增后台读数**：worker 线程数 / 监听根数 / 事件缓冲待处理 / 每条最多 N 次尝试 /
  ⚠ 文件监听线程已不在。

### 已验证（可以直接依赖）

- 全量回归 **255 passed / 0 failed / 1 skipped**（guards 14｜unit 42｜integration 189｜e2e 11）。
- 反向注入 **46/46**（1–18 阶段 1，19–46 阶段 2），明细见 `docs/TESTING.md` 四。
- **G10 FTS 幽灵行 = 0** 已常驻门禁（迁移侧 + 运行侧）。
- **扫描与索引全程不动磁盘**：整棵语料树 sha256 指纹前后相等（e2e）。
- 崩溃恢复：真把一条 `index` 任务留在 `running` 中间态，重开进程后 `recover()` 接着跑完（e2e）。
- 冷启动 0.455s / 0.464s（门禁 2 次读数，仍 `offscreen` → I17）。

### 改方向（与设计稿不一致的地方，全部有据）

- **`text_pages` 不用 `(doc_id,page_no)` 主键**，改成 `rowid INTEGER PRIMARY KEY` + 同名唯一索引：
  FTS5 外部内容表只能指向同库同连接里有 rowid 的表（p1 实测）。见 **D-024**、`DATABASE.md` 2.3。
- **`fts_status` 从不写 `running`**。"正在索引"抄进文档表就造出一个"进程一崩永远出不来"的状态；
  现在崩溃时文档停在 `pending`/`stale`，`resume_pending()` 自然捞回来。见 `index_service` 文件头口径 2。
- **永久故障只消耗 1 次尝试**（`PermanentFailure` → 直接 `failed`），3 次重试预算留给瞬时故障。见 **D-026**。
- **界面定时器上不扫目录**：`patrol` 只排任务，重活交给 worker。见 **D-025** 与 `ARCHITECTURE.md` 三。
- **正文与全文索引同库、向量另库**：D-016 的"分库"只落实了向量那一半，全文那一半被外部内容表的
  硬约束钉在主库里。见 **D-024**。

### 更正（收尾复测时发现的，不改写上面的记录，只追加）

- **修掉两个"看起来通了、其实一次都没通过"的产品 bug**（详见阶段 2 报告第五节 + **D-027**）：
  ① `fs/watcher.py` 的处理器没继承 `FileSystemEventHandler`、没有 `dispatch` → observer 线程
  在**第一条事件**上就死掉，而 `watched_roots` 照旧显示 1；
  ② `diagnostics/logs.py` 的 `threading.excepthook` 读 `args.exc_info`（`ExceptHookArgs` 没这字段）→
  钩子自己抛异常，worker 崩溃现场一行不剩。
- **删掉两条假断言**：旧版 `test_后台线程里的异常也会留痕` 自己造假对象喂 `exc_info`，永远绿；
  阶段 1 的 p4 探针自带处理器类，从没调用过生产代码。两者都重写成"真的走一遍会坏的路"。
- **撤回一条写错的因果**：一度以为 e2e 的"重扫不重抽"测的是索引侧哈希短路，实测那条路走的是
  **扫描侧根本不排任务**。于是拆成两条坏法（I45 索引侧 / I46 扫描侧）分别钉住。
- **I43 第一版抓不到**：把 `watcher_alive=True` 注在"后台正在跑"的断言上，而那时监听确实是活的。
  补一条"半路真让它死一次"的测试（`ctx.watch.stop()` 后再读快照）才有约束力 —— 这正是
  AGENTS.md「不会变红的断言直接删或重写」的正面案例。
- 顺手清掉仓库根一个已废弃的临时脚本 `_reverse_inject_tmp.py`（被 `tests/probes/p9_reverse_injection.py` 取代）。

### 提交记录

| commit | 时间 | 内容 |
| --- | --- | --- |
| `643c21e` | 2026-10-14 19:26 | 扫描 / 索引 / 检索链路 + 迁移 0002 + 两个静默失灵的产品级修复（`src` 现 54 个文件 5,560 行） |
| `035efb3` | 2026-10-14 19:27 | 三层测试 255 条、e2e 11 条、监听接线 10 条、反向注入扩到 46 条、`gates/stage2.py` |

本表同步到 `035efb3`；文档那一条（本文件 + `docs/stage-reports/阶段2-交付报告.md` + 决策 D-024…D-027）
按既有做法在下一次收尾时用 `git log` 追加，不预留空行。

### 已知遗留

`docs/ISSUES.md`：**I15**（界面屏数未确认，现在是阶段 3 唯一硬阻塞）、**I16**（量级红线全部仍是反算）、
**I17**（所有读数来自 offscreen）、**新增 I19**（事件词表与 watchdog 版本耦合）、
**新增 I20**（真实用户目录首扫的失败面未知：长路径 / 权限 / 网络盘 / 链接环只在 `tmp_path` 验过）。

---

## 0.1.0 · 阶段 1 桌面应用骨架与数据库 —— 2026-10-14

验收口径来自你的阶段 1 指令 6 条，逐条实测结论在 `docs/ROADMAP.md` 阶段 1 表与
`docs/stage-reports/阶段1-交付报告.md`。**没有产品功能**：不扫描、不索引、不 OCR、不移动任何文件。

### 新增

- **可运行的应用**：`main.py` + `src/pdfarchiver/app.py`（组合根）+ `ui/`（窗口、导航注册表、两页）。
  启动 → 点导航切页 → 关窗 → 重启回到上次那一屏，全程是真 Qt 控件，不是截图。
- **`config` 层**：`paths.py`（数据目录三级解析：参数 > `PDFARCHIVER_DATA_DIR` > `%LOCALAPPDATA%\PdfArchiver`）、
  `settings.py`（`DEFAULTS` + 类型校验 + 原子写 + `describe()` 打印"当前值/默认值/来源"三列）。
- **`db` 层**：`engine.py`（WAL / busy_timeout / foreign_keys / 每线程连接 / `Backup API` 快照 / `integrity_check`）、
  `migrate.py`（迁移前必须快照、缺快照目录直接拒绝、单迁移一个 `BEGIN IMMEDIATE`）、
  `migrations/0001_initial.py`（13 张表 + 唯一索引含 `COLLATE NOCASE`）、`repositories/`×5、`models.py`。
- **`services` 层**：`bootstrap.py`（装配顺序本身是规矩：日志早于任何可能失败的事、迁移早于任何读写）、
  `status_service.py`（界面唯一取数口，不缓存）、`session_service.py`、`default_catalog.py`（SPEC 3.3 的 14 个分类，种一次）。
- **`diagnostics` 层**：`app.log`（轮转）/ `crash.log`（`sys.excepthook` + `threading.excepthook`）/
  `state.log`（一行一条 JSON 的生命周期对账），时间戳统一 UTC `Z`。
- **测试 107 条**：`tests/unit/`×4（42）+ `tests/integration/`×4（53）+ `tests/guards/`×2 新增（12 含依赖守卫）。
  全量结果 **106 passed / 0 failed / 0 error / 1 skipped**（跳过的是 8.3 短名实测，开发盘未生成短名）。
- **架构守卫加了第 4 项检查：源码字符串常量里不许出现本机路径字面量**（盘符 `H:/`、家目录 `/home/`、`Users/`）。
  这是验收 6「不依赖开发者机器上的固定绝对路径」唯一能机器判定的形式；
  配套注入 I18 证明它会变红（把 `"C:/Users/dev/PDF归档库"` 写进 `services/status_service.py`）。
- **反向注入探针** `tests/probes/p9_reverse_injection.py`：把 18 种"能骗过断言的坏法"注入到系统临时目录里的
  **仓库副本**（工作区产品代码一行未改），逐条验证对应测试必然变红。结果 **18/18 被抓到**。
- **阶段 1 门禁链** `gates/stage1.py`：依赖守卫 → 架构守卫 → 全量回归 → 冷启动实测（读 `state.log` 的
  `window.ready`）→ 反向注入，末行 `VERDICT: ALL GREEN`，任一红即非 0 退出。
  并已验证**门禁本身有牙齿**：副本里弄坏 `identity.py` → 回归项变红 exit=1；把 G1 阈值改成 0.001s → G1 变红 exit=1。

### 已验证（可以直接依赖）

| 结论 | 证据 |
| --- | --- |
| 空库首启建出 13 张表，`integrity_check = ok`，`applied = ['0001_initial']` | `test_空库首启建出全部表` |
| 第二次启动什么都不做（0 迁移、0 新快照、默认模板不重种） | `test_重启第二次不重复建表` |
| 迁移中途失败真的回到原样（半成品表消失、0001 的行数不变、版本仍为 1） | `test_迁移中途失败回到原样` + 注入 I7 |
| 迁移失败时异常对象带着快照文件路径 | `test_迁移失败时异常里带快照路径` |
| 带数据的旧库升级后行数一条不丢、内容读得回、`foreign_key_check` 干净 | `tests/guards/test_migrations.py`（5 条） |
| 同一路径重复扫描只刷新文件事实，**不动**索引状态与人工确认位 | `test_同一路径重复写只留一条且只刷新文件事实` + 注入 I8 |
| 分类同层同名被唯一索引拒绝、跨层可同名；标签大小写不敏感；AI 建议永远 `confirmed=0` | `tests/integration/test_repositories.py` |
| 删除监测根**不碰磁盘**（只停用记录） | `test_监测根增删改查且不碰磁盘` |
| 用户把默认模板全删后重启不复活 | `test_默认模板种过就不再长回来` + 注入 I9 |
| 设置文件损坏 / 库损坏 / 库被锁：三处都留下 sqlite 或 json 原文 + 库/文件路径，装配返回 `EXIT_BOOTSTRAP_FAILED=2` | `tests/integration/test_error_handling.py`（12 条） |
| 冷启动 G1 实测 **18 次读数全部 ≤ 1.031s**（阈值 1.5s **[约定]**）：门禁入口 13 次 0.409–0.910s、中位 0.486s | `gates/stage1.py` 的 `gate_cold_start()`；读数由进程自报进 `state.log`（D-021），明细表与"成因未查明"的三条撤回记录在 `VERIFICATION` 4.10 |

### 改方向（与阶段 0 文档不一致的地方，全部有据）

- **阶段 1 不等 Q1/Q2/Q7 就开工**（原准入门槛要求先答）。摘掉 Q1/Q2 的手段是**本阶段不建 FTS 表**
  （有断言钉住 `text_pages/content_fts/duplicate_groups` 不存在），Q7 摘不掉 → **一屏产品界面都没画**，
  交付的是不含布局决策的运行时外壳。见 **D-018**，`ROADMAP` 阶段 1/2 的偏离段已同步。
- **默认标签一个都不 seed**：SPEC 3.3 只给了分类模板，没给标签清单。凭空编一批"合同/发票"是假数据。见 **D-020**。
- **`app_settings` 表新增为"应用内部状态"专用**，与用户设置 `settings.json` 分两处、各自唯一口径。见 **D-019**。
- **日志时间戳从"本地 + 偏移"改成 UTC `Z`**，并干掉 `logging` 默认的无偏移 `asctime`。
  起因是反向注入 I16（裸本地时间却标 `Z`，格式合法、时刻差 8 小时）——只有跨表比时刻才抓得住。见 **D-022**。

### 微调

- `subprocess` 收发统一显式 `encoding="utf-8", errors="replace"`：本机控制台是 GBK，
  子进程回显的是中文报错，解码炸了现场就没了（阶段 0 踩过、这次补上）。
- 已填实的层删掉 `.gitkeep`（`config` / `db/migrations` / `db/repositories` / `diagnostics` / `fs` /
  `services` / `ui/pages` / `gates`），仍空的 8 层保留占位。见 `docs/REPO-JOURNAL.md` R-006。
- `migrate()` 的 `MigrationError` 现在带 `db=` 与 `.snapshot`：失败消息里能直接看到是哪个库、回到哪份副本。

### 更正（收尾复测时发现的，不改写上面的记录，只追加）

- **撤回一条已经写进去的因果解释**：冷启动读数分散的原因一度写成"`python -c` 入口跳过 `sitecustomize`，
  所以慢出约 0.6s"。复测证伪 —— 同一 `-c` 入口 0.403s、`-m pytest` 内 0.376s，且各次平台设置没变。
  最终表述改成**只报分布不报原因**：18 次读数 0.344–1.031s，门禁入口 13 次 0.409–0.910s（中位 0.486s），
  成因未查明；四种候选解释各自怎么被排除或撤回的记在 `VERIFICATION` 4.10。
  教训：没有对照实验支撑的"原因"不进文档，写"未解释"比写错因便宜。

### 提交记录

| commit | 时间 | 内容 |
| --- | --- | --- |
| `fc0a5d9` | 2026-10-14 04:31 | 应用外壳 + 13 张表 + 迁移机制 + config/diagnostics/services 层（3,932 行里的产品代码部分） |
| `137904c` | 2026-10-14 04:32 | 三层测试 106 条、常驻守卫、18 条反向注入探针、`gates/stage1.py` |
| `467d96c` | 2026-10-14 04:33 | 12 份文档同步 + `docs/stage-reports/阶段1-交付报告.md` + 决策 D-018…D-023 |

一处笔误如实记：`467d96c` 的标题写"五条决策登记"，实际新增 **6** 条（D-018…D-023，
其中 D-023 是写交付报告时发现"迁移安全策略没有决策登记"才补的）。commit 已提交不改历史，
以本表为准。

本表同步到 `467d96c`；之后的 commit 由下一次收尾时按 `git log` 追加（不预留空行）。

### 已知遗留

见 `docs/ISSUES.md`：I15 仍 **OPEN**（产品界面一屏未画），本轮新增 I17（真机首屏未核对，所有 UI 断言跑在
offscreen 平台）与 I18（没有 GUI 错误弹窗，装配失败只写 `crash.log` + stderr + 退出码 2）。
阶段 0 的 I1–I14 状态未变，其中 Q1–Q8 仍需你拍板。

---

## 0.0.0 · 阶段 0 环境检查与技术验证 —— 2026-10-14

**没有产品功能代码。** 本阶段交付的是"哪些技术选型在本机真的能跑"的证据，以及被证据推翻的假设。

### 新增

- **9 个技术验证探针** `tests/probes/p0..p8`，每个可独立重跑，末尾打印 `VERDICT: ALL GREEN / RED`。
- **依赖钉版守卫** `tests/guards/test_dependency_pins.py`（门禁 G21），含 4 项"坏法注入"自检。
- **分层依赖清单** `requirements/{base,ocr,semantic,dev}.txt`，每条版本钉死都附实测理由。
- **工程文档集** `docs/`：README（索引）、VERIFICATION、ARCHITECTURE、DATABASE、RISKS、TESTING、
  UI-SCREENS、ROADMAP、ISSUES、DECISIONS、CHANGELOG、REPO-JOURNAL、stage-reports/阶段0-交付报告。
  其中 8 份是从 `docs/00–08` 数字名改名来的（用 `git mv`，历史保留），改名缘由与连带引用改写见
  `docs/REPO-JOURNAL.md` R-001；DECISIONS / CHANGELOG / REPO-JOURNAL 与根 README 是本轮新建。
- **目录骨架** `src/pdfarchiver/**`（11 层，只有 `.gitkeep`，无实现）、`tests/{unit,integration}`、`gates/`。

### 已验证（可以直接依赖）

| 结论 | 证据 |
| --- | --- |
| PySide6 必须 6.8.x；6.12 导入即 `WinError 127` | p3 |
| onnxruntime 必须 ≤1.20.x；≥1.21 全部 `WinError 1114` | 逐版本二分 |
| 两个 ORT 发行版共存 → `import` **段错误 exit 139**（不是异常） | p5/p6 排障过程 |
| CUDA 不可用、DirectML 可用：OCR **6.36×**、嵌入 **7.8×** | p5/p6 |
| FTS5 `trigram` 中文可用（4 字 6.39ms）；`unicode61` 中文**静默零命中** | p1 |
| FTS5 **没有** `offsets()`；只有 `rank/snippet/bm25/highlight` | p1 |
| 外部内容表 `'delete'` 少带一列 → **静默留幽灵行** | p1 |
| 文件身份必须 `realpath`（8.3 短名把空格吃掉） | p7 |
| 监听根被改名 → **0 事件**；跨目录移动报成 `created+deleted` | p4 |
| 真实语料 **7,768 份 / 120.6GB / 202 万页 / 37.5% 纯扫描** | p0/p2 |
| `--onedir` 打包可用：247.6MB，冻结后四项依赖真实可用 | p8 |

### 改方向（被证据推翻的原计划）

- **OCR 从"索引的自动步骤"改为"用户显式触发"**：全量 101 万页需 1,144 GPU 小时（8h/天 × 143 工作日），
  而按无人值守窗口反算的预算是 284ms/页，实测 3,281ms。p5 **保持 RED**，没有调阈值凑绿。
- **量化不作为提速手段**：int8 在 DirectML 上 79.3 chunks/s，比 fp32 的 146.9 **慢 1.85×**。
- **新增一条产品级未决项**：全文索引体积外推 28–48GB（×10 档 280–480GB 不可行）→ 需选全量/子集/降密度。

### 删除

- 探针里两条**假断言**：硬编码为 `True` 的"1024 宽能显示"、以及 `is not True or ...` 式自我开脱条件。
  原则：不会变红的断言直接删，不留着制造安全感。

### 微调

- **决策编号只留一个口径**：`ARCHITECTURE.md` 五 原来自己编 D1–D10，`DECISIONS.md` 又编 D-001…，
  同一件事两套号（AGENTS.md 禁止一个概念多个口径）。现在架构表只引用 `DECISIONS.md` 的 `D-0NN`，
  并为其补登记 **D-015**（FTS5 外部内容表硬规则，规则清单本体在 `DATABASE.md` 三）、
  **D-016**（全文/向量分库）、**D-017**（阅读器渲染双通道）。
- **G21 守卫的失败消息现在打印当前解释器路径**。起因是本轮用系统 Anaconda Python 跑守卫得到 2 failed，
  消息写着"依赖树里出现了 torch"，看起来像依赖被破坏，实际是用错了解释器
  （Anaconda 里有 `torch 2.14.0`、`transformers 5.16.1`，都被 SPEC 第五节禁止）。
  `.venv` 里仍是 6 passed、独立自检 `VERDICT: ALL GREEN`。口径写进 `docs/TESTING.md` 五。
- **清掉 p7 留下的 60 层中文目录树**（最深文件路径 533 字符）。它在 `.probe_work/` 里可再生（p7 每次自己重建），
  但会让 **Git 自身的目录扫描**报 `Filename too long`，`git status` 带 `--ignored` 时直接吐警告；
  删除必须走 `\\?\` 前缀。这条实测证据已并进 `docs/ISSUES.md` I10 ——
  它说明"本机开了 LongPathsEnabled"不等于"所有工具都看得见这些路径"。

### 提交记录

| commit | 时间 | 内容 |
| --- | --- | --- |
| `ea92aec` | 2026-10-14 02:33 | 阶段 0 交付物（文档 + 探针 + 依赖清单 + 守卫 + 骨架） |
| `0e808d0` | 2026-10-14 02:37 | 从文档与探针用法示例中去掉本机用户名路径 |
| `bed65df` | 2026-10-14 02:39 | 补阶段 0 交付报告与本机资源实测值 |
| `722695b` | 2026-10-14 02:53 | 文档改名到规范名 + 本文件与 `DECISIONS.md` / `README` / `REPO-JOURNAL` |
| `818d94e` | 2026-10-14 02:56 | 决策编号统一成单一口径 + 补 D-015/016/017 |
| `5550c8c` | 2026-10-14 02:58 | I10 长路径实测证据，清掉 p7 的 60 层目录树 |

本表同步到 `5550c8c`；阶段 1 的 commit 见上一节（0.1.0）的提交记录表，不在此重复。

### 已知遗留

16 条，逐条列在 `docs/ISSUES.md`（I1–I16），其中 8 条需要用户拍板（`docs/ROADMAP.md` Q1–Q8）。
~~阶段 1 不开工，直到 Q1/Q2/Q7 有答案。~~ **这句已被阶段 1 的实际做法推翻**：你直接下令开工，
我用"阶段 1 不建 FTS 表 + 一屏产品界面都不画"把 Q1/Q2/Q7 从本阶段的阻塞项里摘掉，
而不是绕过它们 —— 全过程、代价与撤销成本写在 **D-018**。
