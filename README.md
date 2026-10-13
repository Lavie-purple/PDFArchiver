# Windows 本地 PDF 归档与检索工具

本机运行的 PDF 归档与检索桌面应用（Windows 10 / Python 3.11 / PySide6）。
只做本地的事：扫描目录、抽取正文、建全文索引、阅读、按规则归档实体文件。
**不上传任何文档内容、提取文本、向量或元数据**；模型推理只在本地，且**不是文件搜索的必要依赖**。

> 当前进度：**阶段 0（环境检查与技术验证）已完成**，尚无产品代码。
> 阶段 0 的实测结论、被证伪的假设、以及仍需产品所有者拍板的 8 个问题，见 `docs/`。

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
docs/          设计文档（阶段 0 验证结论 / 架构 / 数据库 / 风险 / 测试门禁 / 界面清单 / 分阶段计划 / 已知问题台账 / 阶段 0 交付报告）
requirements/  分层依赖清单 + 版本钉死理由
tests/probes/  阶段 0 的 9 个技术验证探针（p0..p8），可重跑，末尾打印 VERDICT
tests/guards/  依赖钉版守卫（G21）
src/pdfarchiver/  产品代码（阶段 1 起填充；现在是空的目录骨架）
```

## 上手

```bash
# 1. 建 venv 并装基础层（Python 3.11 x64）
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements/base.txt

# 2. 开发工具链
.venv/Scripts/python.exe -m pip install -r requirements/dev.txt

# 3. 每次开工先跑依赖守卫（唯一能挡住段错误的那一步）
.venv/Scripts/python.exe -m pytest tests/guards/test_dependency_pins.py -q

# 4. 重跑技术验证（换机器 / 升级依赖后必做；p5 需要独占 GPU）
.venv/Scripts/python.exe tests/probes/p1_fts5.py
.venv/Scripts/python.exe tests/probes/p7_path_identity.py
```

## 已验证 vs 未定

**已验证可以直接依赖的**：10 条（`docs/00-阶段0验证结论.md` 第五节 V1–V10）。

**还是候选、没定下来的**：中文分词最终选型、OCR 范围策略、全文索引体积策略（外推 28–48GB）、
向量检索方案、是否引入 QWebEngine、语义检索验收标准、界面屏数与线框、监测目录范围。
逐条列在 `docs/03-风险清单与验证方法.md` 与 `docs/00` 第六节。

**一条已知的坏消息**：全量 OCR 不可行 —— 实测 101 万页需 DirectML 1,144 小时（8h/天 × 143 个工作日），
所以 OCR 只能按需触发，不能当成索引的一个自动步骤。详见 `docs/00` 4.6。
