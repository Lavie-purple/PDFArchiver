# Windows 本地 PDF 归档与检索工具

本机运行的 PDF 归档与检索桌面应用（Windows 10 / Python 3.11 / PySide6）。
只做本地的事：扫描目录、抽取正文、建全文索引、阅读、按规则归档实体文件。
**不上传任何文档内容、提取文本、向量或元数据**；模型推理只在本地，且**不是文件搜索的必要依赖**。

> 当前进度：**阶段 1（应用骨架 + 数据库）已完成，门禁全绿**（106 passed / 0 failed / 1 skipped，
> G1 冷启动：18 次读数 **0.344–1.031s**（门禁入口 13 次 0.409–0.910s，中位 0.486s），阈值 1.5s **[约定]**；
> **全部为 `offscreen` 平台，真机首屏未核对（ISSUES I17）**。18/18 反向注入被抓到）。
> **现在能跑的只有**：启动窗口、点导航切页、看"运行状态与自检"页、把分类/标签/设置/监测根/任务写进库并跨重启读回、
> 数据库结构迁移与失败回退。**还没有**：目录扫描、全文搜索、OCR、语义搜索、任何文件移动或归档。
> 界面只到不含布局决策的外壳，A/B/A′ 三案与 8 个未决问题仍等你拍板，见 `docs/`。

## 技术栈（全部为实测钉死，不是选型偏好）

| 用途 | 组件 | 为什么是这个版本 |
| --- | --- | --- |
| UI | PySide6 **6.8.3** | 6.12.0 在 Win10 19045 上 `import` 即 `WinError 127` |
| 存储与全文 | 标准库 `sqlite3`（自带 SQLite **3.41.2**）+ FTS5 `trigram` | `trigram` 需 ≥3.34；`unicode61` 对中文**零命中** |
| PDF | PyMuPDF **1.28.2** | 实测 147.9 页/s 抽取、135.1ms/页渲染（中位） |
| 监测 | watchdog **6.0.0** | Windows 走 `WindowsApiObserver` |
| 推理 | onnxruntime-directml **1.20.1**（**唯一** ORT 发行版） | ORT ≥1.21 本机 `WinError 1114`；两个 ORT 发行版共存会让 `import` **直接段错误** |
| 打包 | PyInstaller **6.22.3** `--onedir` | 实测产物 247.6MB，冻结后四项依赖真实可用 |
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
  UI-SCREENS.md      界面清单（AGENTS.md 门禁：线框未逐屏确认前不写界面代码）
  ROADMAP.md         分阶段实施计划与每阶段准入门槛
  ISSUES.md          已知问题台账 I1–I18（收尾必须逐条销账）
  CHANGELOG.md       阶段变更与版本记录
  REPO-JOURNAL.md    仓库结构/命名/忽略规则变更记录
  stage-reports/     每阶段交付报告（阶段 0、阶段 1）
requirements/      分层依赖清单 + 版本钉死理由
main.py            应用入口（先记 T0 再 import，冷启动才量得准）
conftest.py        把 src/ 挂进 sys.path，测试与 python main.py 用同一份源码
src/pdfarchiver/   产品代码：config / db(13 表+迁移) / fs / diagnostics / services / ui / app.py
tests/probes/      p0..p8 技术验证探针 + p9 反向注入（证明断言能变红），可重跑，末尾打印 VERDICT
tests/unit/        纯逻辑：路径解析、设置校验、文件身份、迁移发现
tests/integration/ 真实 SQLite + 真 Qt 控件：装配与迁移、仓储层、异常处理、应用外壳
tests/guards/      常驻守卫：依赖钉版（G21）、架构方向与 SQL 位置（AST）、迁移不丢数据
gates/stage1.py    阶段 1 验收门禁链，末行 VERDICT: ALL GREEN
```

## 上手

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

# 4. 每次收尾跑这条门禁链（约 1 分钟；任何一环红就 exit=1，不许开下一阶段）
.venv/Scripts/python.exe gates/stage1.py

# 5. 每次开工先单跑依赖守卫（唯一能挡住段错误 exit 139 的那一步）
.venv/Scripts/python.exe -m pytest tests/guards -q

# 6. 重跑技术验证（换机器 / 升级依赖后必做；p5 需要独占 GPU）
.venv/Scripts/python.exe tests/probes/p1_fts5.py
.venv/Scripts/python.exe tests/probes/p7_path_identity.py
```

**启动或运行失败时看这里**：`<数据根>\logs\crash.log`（完整堆栈）与 `app.log`；
生命周期对账在 `logs\state.log`（一行一条 JSON，UTC 带 `Z`）。应用**目前没有错误弹窗**（ISSUES I18）。

## 已验证 vs 未定

**已验证可以直接依赖的**：10 条（`docs/VERIFICATION.md` 第五节 V1–V10）。

**还是候选、没定下来的**：中文分词最终选型、OCR 范围策略、全文索引体积策略（外推 28–48GB）、
向量检索方案、是否引入 QWebEngine、语义检索验收标准、界面屏数与线框、监测目录范围。
逐条列在 `docs/RISKS.md` 与 `docs/VERIFICATION` 第六节。

**一条已知的坏消息**：全量 OCR 不可行 —— 实测 101 万页需 DirectML 1,144 小时（8h/天 × 143 个工作日），
所以 OCR 只能按需触发，不能当成索引的一个自动步骤。详见 `docs/VERIFICATION` 4.6。
