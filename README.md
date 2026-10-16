# Windows 本地 PDF 归档与检索工具

本机运行的 PDF 归档与检索桌面应用（Windows 10 / Python 3.11 / PySide6）。
只做本地的事：扫描目录、抽取正文、建全文索引、阅读、按规则归档实体文件。
**不上传任何文档内容、提取文本、向量或元数据**；模型推理只在本地，且**不是文件搜索的必要依赖**。

> 当前进度（**2026-10-17 收尾复跑后更新；上一版核对代码状态重写于 2026-10-16**；此前这段还写"阶段 3/4/6 一行代码都没做"、"磁盘上一个文件都不会被动"，
> 都与工作树实际不符 —— 那 8 屏与阶段 4 服务都已落地并接进导航，见下）。
>
> **按交付四档如实分档**（AGENTS.md 要求区分：已实现且通过测试 / 已实现但未充分验证 / 部分实现 / 尚未实现）：
> - 阶段 0 / 1 / 2 / 5：**已实现且通过门禁**。全文检索、扫描索引、增量监测、本地 OCR 都在 `gates/` 里跑绿。
> - 阶段 3（库视图 / 检索 UI / 阅读器）：**已实现但未充分验证** —— 8 屏 S1–S8 已接进导航、全量回归 **438 passed / 4 skipped**（2026-10-17 现测），但
>   ① 库筛选与阅读器渲染**只有 shell 级测试**（能实例化、能切页，没有行为断言）；② **G2 搜索 P95 ≤500ms 已于 2026-10-17 真语料实测：P95 2,809ms → 判 RED**（阈值没放宽；19/20 条查询 ≤356ms，慢的只有 1–2 字 LIKE 通道里词太稀的那一条，读数与机制见 `docs/VERIFICATION.md` §4.15，处置等勾选见台账 **ISSUES I59**）；
>   ③ **G5 / G6**（单页渲染 ≤400ms / 禁全量预渲染）**从没立成门禁**，因为阅读器这一轮才落地（翻页延迟那条约定见台账 **ISSUES I39**，400ms 等你确认）。
> - 阶段 6（语义搜索 / AI 分类建议）：**已实现但未充分验证** —— 嵌入 / 向量 / 语义服务与各自测试在场，**质量待真语料复跑**
>   （**G15 / 台账 ISSUES I11**：目前只有 8 对自造相关样本，不足以验收）。
> - 阶段 4（归档 / 重复检测 / 撤销 / 备份，**唯一会改你磁盘的阶段**）：**已实现但磁盘行为零测试 —— 风险最高** ——
>   `ArchiveService / DedupService / BackupService` 与页面在场、已注册进 bootstrap，**但没有任何测试引用过它们**，
>   **G17 / G18 / G19**（杀进程后 journal 恢复 / 归档撤销字节一致 / 跨盘移动绝不先删源）**一条没跑**，`gates/stage4.py` 自己就明写"待真语料实测"。
>
> ⚠️ **安全口径更正**：旧文档那句"磁盘上一个文件都不会被本应用移动 / 改名 / 删除"**已不成立** —— 阶段 4 的归档/撤销会真的动文件。
> **在 G18 / G19 于专用临时文件上验证通过之前，不要拿它对你真实材料做归档**。p12 的 C8 仍盯着 `file_operations / operation_items` 不许偷写，
> 但拦截逻辑本身没被测过（见上一条与 **ISSUES I10** 长路径残留）。
>
> **2026-10-16 真实语料首扫已完成**：6 个根扫得 **10,977 份 PDF**、全量扫描 31.3 分钟、库长到 6.1GB / `text_pages` 107 万行 ——
> **G4 [反算] 全量哈希 ≤1h 实质达成**，**台账 ISSUES I20**（真语料首扫失败面）拿到真凭据（26 条全 `PermissionError` + 10 条索引终结失败均为预期内文件，零代码 bug）。
> **索引已排空（2026-10-17）**：卡住的最后 13 份用 2.0 分钟跑完，`documents` 现数 **fts_done 10,906 / failed 74 / 共 10,980 份**、`text_pages` **1,972,578 行**；
> 那 13 份为什么卡住（收尾写失败把任务永久留在 `running`）修法与守卫见台账 **ISSUES I46** / 决策 **D-050**，逐字读数在 `docs/VERIFICATION.md` 4.14 与 §4.15。
>
> **上面那次"最终交付链 ALL GREEN（807.3s / 合计 16 条）"跑的是阶段 3/4/6 零代码时的旧树** —— 新代码落地后 `gates/final.py` **尚未重跑**，
> 旧读数不能当当前覆盖度（读数原文与它自己的三条保留见 `docs/VERIFICATION.md` 4.13、台账 **ISSUES I25 / I32 / I36**）。
> 冷启动读数（源码空载 **0.344–1.639s**、满载 **2.99–3.13s**、冻结产物真桌面 **1.109s**）是负载绑定读数，阈值 1.5s **[约定]**，见 **ISSUES I17 / I25**。
>
> **还欠的收尾**：① 阶段 3/4/6 全量代码 + 界面审核轮的整改 + 本轮文档**尚未提交**（HEAD 仍停在 `dfa3cc4`）；
> ② 台账 **60 行、I1–I60 连续**，仍有 **OPEN 12 项**：**I5 / I16 / I17 / I18 / I51 / I53 / I54 / I55 / I57 / I58 / I59 / I60**
> （本轮新开三条：I57 四份用户文档过期、I58 越过 800 行那条线、I59 G2 判 RED；I46 已降到 MITIGATED）；
> ③ 一批门禁与决策**等你拍板**才能推进（**I59 的 G2 五条选项** / **I60 搜索区提示上屏的形状** / I53 ①②③ / I54 甲乙 / I55 甲乙丙 / I58 甲乙丙 /
> G8 单位与档位 / G15 的 20 条真实查询 / I39 的 400ms / I40 `volume_id` / 阶段 4 破坏性测试用哪块盘）。8 个未决问题 Q3 已答，其余见 `docs/RISKS.md`。

## 技术栈（全部为实测钉死，不是选型偏好）

| 用途 | 组件 | 为什么是这个版本 |
| --- | --- | --- |
| UI | PySide6 **6.8.3** | 6.12.0 在 Win10 19045 上 `import` 即 `WinError 127` |
| 存储与全文 | 标准库 `sqlite3`（自带 SQLite **3.41.2**）+ FTS5 `trigram` | `trigram` 需 ≥3.34；`unicode61` 对中文**零命中** |
| PDF | PyMuPDF **1.28.2** | 实测 147.9 页/s 抽取、135.1ms/页渲染（中位） |
| 监测 | watchdog **6.0.0** | Windows 走 `WindowsApiObserver` |
| 推理 | onnxruntime-directml **1.20.1**（**唯一** ORT 发行版） | ORT ≥1.21 本机 `WinError 1114`；两个 ORT 发行版共存会让 `import` **直接段错误** |
| 打包 | PyInstaller **6.22.3** `--onedir` | 产品级构建实测整包 **392.2MiB**（`packaging/build.py` 的内容断言全绿），冻结后功能与 OCR 在产物里真跑通；`--onefile` 未测（ISSUES I14） |
| GPU | 只用 **DirectML**，不用 CUDA | GTX 1060(Pascal) 实测无 `CUDAExecutionProvider` |

可选层（不装也能用基础搜索）：`requirements/ocr.txt`（RapidOCR）、`requirements/semantic.txt`（ONNX 向量）。
**装 OCR 前必读 `requirements/ocr.txt` 末尾的装包顺序** —— 直接 `pip install` 会把纯 `onnxruntime` 拽回来，
后果是启动时段错误而不是报错。

> **关于 `pip check` 的那条报错**：装完依赖后跑 `pip check` 会看到
> `rapidocr-onnxruntime 1.4.4 requires onnxruntime, which is not installed`。
> **这是预期的，不要"修"它。** 修它的办法是装回纯 `onnxruntime`，而那正是导致 `import onnxruntime`
> 段错误（exit 139）的根因（ISSUES I3）。依赖守卫 G21 把这条精确措辞列为唯一允许的错误。

## 仓库结构

```
PROJECT_SPEC.md    需求契约：产品功能范围与不可突破的边界（按 AGENTS.md 只留在本机，不入库）
docs/
  README.md          工程文档索引：哪个文件负责什么、什么时候必须改它
  VERIFICATION.md    阶段 0 实测结论与数字（所有文档里的数字都要能在这里找到出处）
  ARCHITECTURE.md    模块划分、依赖方向、线程模型、三层检索依赖关系
  DATABASE.md        数据模型、FTS5 接法、迁移与文件操作状态机、存储与备份分级
  RISKS.md           高风险决策 R1–R15 + 需要你拍板的未决问题
  DECISIONS.md       技术决策记录（含被否的替代方案与理由）
  TESTING.md         测试分层、硬门禁 G1–G21、反向测试规则、发布门禁链
  OCR.md             OCR 这一层的装与验 / 配置项 / 怎么用 / 结果读数 / 故障处理（**没有界面入口，读这个**）
  UI-SCREENS.md      界面清单（AGENTS.md 门禁：线框未逐屏确认前不写界面代码）
  ROADMAP.md         分阶段实施计划与每阶段准入门槛
  ISSUES.md          已知问题台账，行号现数到 **ISSUES I52**（2026-10-16 收尾时点；**条数不写死**，现数命令见 `docs/stage-reports/最终交付报告.md` §六；收尾必须逐条销账）
  CHANGELOG.md       阶段变更与版本记录
  REPO-JOURNAL.md    仓库结构/命名/忽略规则变更记录
  stage-reports/     每阶段交付报告（阶段 0、1、2、5、最终交付）
  ── 以下四份是**给用的人看的**，不是工程台账 ──
  INSTALL.md         装到一台新机器：环境、依赖安装顺序（OCR 那条会段错误）、数据目录、首启
  USAGE.md           日常怎么用：扫描 / 检索 / 阅读 / 点名 OCR / 状态页每个读数是什么意思
  BACKUP-RESTORE.md  备份与恢复：现在能备什么、OCR 结果为什么最贵、恢复怎么核对
  TROUBLESHOOTING.md 出问题了先看这里：三个日志各在哪、按症状分诊、哪些错误是预期的
requirements/      分层依赖清单 + 版本钉死理由
main.py            应用入口（先记 T0 再 import，冷启动才量得准）
conftest.py        把 src/ 挂进 sys.path，测试与 python main.py 用同一份源码
src/pdfarchiver/   产品代码：config / db(迁移 0001..0003) / fs / parsing / indexing / jobs / search /
                   ocr(可选层) / services / ui / diagnostics / app.py
tests/probes/      p0..p8 技术验证探针 + p9/p10 反向注入 + p11 OCR 产品路径实测 + p12 文件与库一致性
                   + p13 长时间运行采样 + p14 FTS 一致性仪表验牙，末尾打印 VERDICT
tests/unit/        纯逻辑：路径解析、设置校验、文件身份、迁移发现、OCR 版本指纹与限量推导
tests/integration/ 真实 SQLite + 真 Qt 控件：装配与迁移、仓储、异常处理、外壳、扫描、队列、索引、检索、OCR 服务与预算、
                   探针自己的 SQL 传感器与产品口径对齐（test_probe_sql_sensors.py）
tests/e2e/         真 worker + 真 watchdog + 真 PDF 的 11 条全链验收
tests/guards/      常驻守卫：依赖钉版（G21）、架构方向与 SQL 位置（AST）、迁移不丢数据
gates/             stage1.py → stage2.py → stage5.py 逐层叠加；final.py = 最终交付的分段链（9 段 + 交付文档门禁）
packaging/         build.py（PyInstaller 内容断言，缺一样就红）+ frozen_smoke.py（干净目录里跑真产物）
```

## 上手

**只想用，不想读工程台账**：装到一台新机器看 `docs/INSTALL.md`，日常操作与每个读数的意思看
`docs/USAGE.md`，备份与恢复看 `docs/BACKUP-RESTORE.md`，出问题了看 `docs/TROUBLESHOOTING.md`。
下面这一段是给**改代码的人**的最短路径。

```bash
# 1. 建 venv 并装基础层（Python 3.11 x64）
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements/base.txt

# 2. 开发工具链
.venv/Scripts/python.exe -m pip install -r requirements/dev.txt

# 3. 跑起来（首次启动会建库并写入 SPEC 3.3 的 14 个默认分类）
.venv/Scripts/python.exe main.py                        # 数据目录 = %LOCALAPPDATA%\PdfArchiver
.venv/Scripts/python.exe main.py --data-dir D:\pdfdata  # 或明确指一个目录
.venv/Scripts/python.exe main.py --data-dir <空目录> --exit-after 0.3   # 起得来也关得掉，给门禁用

# 4. 每次收尾跑这条门禁链（空载约 6.5 分钟；任何一环红就 exit=1，不许开下一阶段）
#    起跑第一行会打印机器负载 —— G1/G2 的冷启动阈值是负载绑定读数，满载必红（ISSUES I25），那时空载重跑而不是改阈值
.venv/Scripts/python.exe gates/stage5.py
#    只想快一点：--quick 只跑阶段 5 三行 / --no-injection 跳过两条注入探针（141s）
#    但**收尾必须跑全链**，快链不算销账

# 4b. 最终交付链：把九段串起来（默认只跑快的那几段，慢段要显式点名）
.venv/Scripts/python.exe gates/final.py --list                 # 每段是什么、实测耗时、该不该并进默认
.venv/Scripts/python.exe gates/final.py                        # 默认段：guards+regression+coldstart+e2e+consistency
.venv/Scripts/python.exe gates/final.py --only soak --soak-minutes 4
.venv/Scripts/python.exe gates/final.py --only package         # 重新打包 + 在干净临时目录里跑真产物
#    --all 才是全链（约 20 分钟）；被 --only 跳过的段会在输出里明写"本次未跑"

# 5. 每次开工先单跑依赖守卫（唯一能挡住段错误 exit 139 的那一步）
.venv/Scripts/python.exe -m pytest tests/guards -q

# 6. 重跑技术验证（换机器 / 升级依赖后必做；p5、p11 需要独占 GPU）
.venv/Scripts/python.exe tests/probes/p1_fts5.py
.venv/Scripts/python.exe tests/probes/p7_path_identity.py
.venv/Scripts/python.exe tests/probes/p11_ocr_shipped.py   # OCR 产品路径实测（要装 requirements/ocr.txt）
```

**启动或运行失败时看这里**：`<数据根>\logs\crash.log`（完整堆栈）与 `app.log`；
生命周期对账在 `logs\state.log`（一行一条 JSON，UTC 带 `Z`）。应用**目前没有错误弹窗**（ISSUES I18）。

## 已验证 vs 未定

**已验证可以直接依赖的**：21 条（`docs/VERIFICATION.md` 第五节 V1–V21）+ 阶段 2 的链路 + 阶段 5 的 OCR 层
+ 最终交付轮的 4.13 那一场（逐条对账见 `docs/stage-reports/`）。

**还是候选、没定下来的**：中文分词最终选型（Q1）、全文索引体积策略（外推 28–48GB，Q2）、
是否放宽量级阈值与 GB/MiB 单位口径（Q4）、语义检索验收标准与向量方案（Q5/Q6）、
界面屏数与线框（**Q7 —— 现在最大的硬阻塞**）、监测目录范围（Q8）。
**OCR 范围策略已定**（Q3，2026-10-15：只跑你显式点名的，零自动触发）。
逐条列在 `docs/RISKS.md` 与 `docs/VERIFICATION` 第六节。

**一条已知的坏消息，且没有被"优化"掉**：全量 OCR 在本机不可行 —— 全库待 OCR **1,014,112 页**，
按每日页预算 6,000 页折算 **≈169 天**（p5 那个"1,144 小时 = 143 个工作日"是历史推导，产品口径只有 169 天这一个）。
所以 OCR 不是索引的自动步骤，只能按需点名，且**每天跑满即停**。
处置与实测数字见 `docs/OCR.md` 与 **D-006 / D-028**；这条不销账（ISSUES **ISSUES I1**）。
