# Windows 本地 PDF 归档与检索工具

本机运行的 PDF 归档与检索桌面应用（Windows 10 / Python 3.11 / PySide6）。
只做本地的事：扫描目录、抽取正文、建全文索引、阅读、按规则归档实体文件。
**不上传任何文档内容、提取文本、向量或元数据**；模型推理只在本地，且**不是文件搜索的必要依赖**。

> 当前进度：**阶段 2（扫描 / 索引 / 全文检索）与阶段 5（本地 OCR）已完成**，并已在 2026-10-15 走完
> **最终交付链** `gates/final.py`：八段一条命令、各段自报耗时相加 **807.3s**、`合计判定 16 条｜VERDICT: ALL GREEN`
> （全量回归 355 passed / 1 skipped，反向注入 46/46 + 45/45 + p12 17/17 + p13 11/11，冻结产物冒烟 29 行全过）。
> 逐字读数在 `docs/VERIFICATION.md` 4.13，交付判断在 `docs/stage-reports/最终交付报告.md`。
> **有三件还不能说**：① 冷启动阈值 1.5s 是**负载绑定**读数，机器不空闲时同一条命令会判 RED（21 分钟后那次
> 判红 3 条，当时 CPU 96.5%），阈值一格没放宽，见 ISSUES **I25**；② "长时间运行"只有 **4 分钟**证据，
> 且那一场从未真留下积压（排空 0.0s），见 ISSUES **I32**；③ 那 16 条全绿里**有一行是没跑的占位判定**
> （没给 `--data-root` 时的"一致性核查 p12 对真实数据根"，它不可能变红却计了数），见 ISSUES **I36** ——
> 所以**别把条数当覆盖度**，真实现场那一次是另开的 `--only consistency` 补的。
> **阶段 3（分类树 / 标签 / 智能集合 / 搜索 UI / 阅读器）、阶段 4（归档 / 重复 / 撤销 / 备份）与阶段 6（语义搜索 /
> AI 分类建议）一行代码都没做** —— 阶段 3 与 6 卡在 Q7 界面线框逐屏确认与 Q5/Q6 模型选型（AGENTS.md 禁令在案），
> 阶段 4 是唯一会改你磁盘的阶段，按纪律要单独确认。
> **现在能跑的**：启动窗口、看"运行状态与自检"页（含后台进度 / 错误 / 重试 / 监听线程是否还活着）、
> 监测多个目录并增量扫描、真 PDF 抽正文、FTS5 trigram 全文检索（文件名 / 路径 / 元数据 / 正文四通道，
> 正文命中给**真页码**）、重启后一切还在、对**你显式点名的**扫描书页跑本地 OCR 并把识别文本进索引、
> **磁盘上一个文件都不会被本应用移动 / 改名 / 删除**：`fileops/` 与 `backup/` 两层至今零代码，
> 界面那三条断言钉住"未实现页不放假控件"，p12 的 C8 盯着 `file_operations` / `operation_items` 两张空表不许偷写。
> **界面仍然只有阶段 1 那一屏**：OCR 这一层目前**没有界面入口**，用法在服务层，见 `docs/OCR.md`。
> 8 个未决问题里 Q3 已答（2026-10-15），其余仍等你拍板，见 `docs/RISKS.md`。
> 冷启动读数：源码空载历次 **0.344–1.639s**（交付链那一场现场打印 **0.437s**）、满载（CPU 96.5%）**2.99–3.13s**、
> **冻结产物 1.109s**（这条是**真桌面**取的数，本项目第一次不是 `offscreen` —— 但"人眼看过首屏"仍然没有），
> 阈值 1.5s **[约定]** —— 这是**负载绑定**读数，见 ISSUES **I17** / **I25**。

## 技术栈（全部为实测钉死，不是选型偏好）

| 用途 | 组件 | 为什么是这个版本 |
| --- | --- | --- |
| UI | PySide6 **6.8.3** | 6.12.0 在 Win10 19045 上 `import` 即 `WinError 127` |
| 存储与全文 | 标准库 `sqlite3`（自带 SQLite **3.41.2**）+ FTS5 `trigram` | `trigram` 需 ≥3.34；`unicode61` 对中文**零命中** |
| PDF | PyMuPDF **1.28.2** | 实测 147.9 页/s 抽取、135.1ms/页渲染（中位） |
| 监测 | watchdog **6.0.0** | Windows 走 `WindowsApiObserver` |
| 推理 | onnxruntime-directml **1.20.1**（**唯一** ORT 发行版） | ORT ≥1.21 本机 `WinError 1114`；两个 ORT 发行版共存会让 `import` **直接段错误** |
| 打包 | PyInstaller **6.22.3** `--onedir` | 产品级构建实测整包 **392.2MiB**（`packaging/build.py` 的内容断言全绿），冻结后功能与 OCR 在产物里真跑通；`--onefile` 未测（I14） |
| GPU | 只用 **DirectML**，不用 CUDA | GTX 1060(Pascal) 实测无 `CUDAExecutionProvider` |

可选层（不装也能用基础搜索）：`requirements/ocr.txt`（RapidOCR）、`requirements/semantic.txt`（ONNX 向量）。
**装 OCR 前必读 `requirements/ocr.txt` 末尾的装包顺序** —— 直接 `pip install` 会把纯 `onnxruntime` 拽回来，
后果是启动时段错误而不是报错。

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
  ISSUES.md          已知问题台账 I1–I36（收尾必须逐条销账；当前 CLOSED 11｜MITIGATED 8｜OPEN 17）
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
#    起跑第一行会打印机器负载 —— G1/G2 的冷启动阈值是负载绑定读数，满载必红（I25），那时空载重跑而不是改阈值
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
处置与实测数字见 `docs/OCR.md` 与 **D-006 / D-028**；这条不销账（ISSUES **I1**）。
