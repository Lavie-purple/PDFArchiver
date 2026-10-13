# 变更日志

按阶段记录。版本号口径：阶段 0–7 全部走完并通过发布门禁才叫 `1.0.0`；在此之前一律 `0.x.y`，
且 `x` = 已完成的阶段号。**本文件只记实际做过并验证过的变更**，未落地的写在 `ROADMAP.md`，不写在这里。

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

（本表在提交后按 `git log` 追加，不预留空行。）

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

本表同步到 `5550c8c`；之后的 commit 由下一次收尾时按 `git log` 追加（不预留空行）。

### 已知遗留

16 条，逐条列在 `docs/ISSUES.md`（I1–I16），其中 8 条需要用户拍板（`docs/ROADMAP.md` Q1–Q8）。
~~阶段 1 不开工，直到 Q1/Q2/Q7 有答案。~~ **这句已被阶段 1 的实际做法推翻**：你直接下令开工，
我用"阶段 1 不建 FTS 表 + 一屏产品界面都不画"把 Q1/Q2/Q7 从本阶段的阻塞项里摘掉，
而不是绕过它们 —— 全过程、代价与撤销成本写在 **D-018**。
