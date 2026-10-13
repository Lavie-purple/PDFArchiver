# 架构与模块边界

依据 `PROJECT_SPEC.md` 4.1 的 11 层划分。本文件定义**每个目录负责什么、不许负责什么**，
阶段 1 起按此落地，不允许把文件操作、数据库、UI、搜索、OCR、AI 写进同一个模块。

## 一 · 目录结构

```
src/pdfarchiver/
  __init__.py
  app.py                  # 组合根：建容器、接线、启动/退出。不含业务规则
  config/                 # 设置读写、数据目录解析、默认值表
    settings.py           #   唯一口径：设置项名字 + 默认值 + 校验
  db/                     # 数据库与索引层
    engine.py             #   连接工厂（每线程独立连接）、WAL、busy_timeout
    migrations/           #   顺序编号的迁移脚本 + schema_version 表
    models.py             #   表结构常量与行数据类
    repositories/         #   每张表/聚合的读写；只有这里能写 SQL
  fs/                     # 文件扫描与监测层
    identity.py           #   路径规范化与文件身份（规则见 docs/VERIFICATION 4.8 与 docs/DATABASE 二·2.1）
    scanner.py            #   全量/增量扫描，产出变更集
    watcher.py            #   watchdog 封装，只产事件，不改库
    exclude.py            #   排除规则
  parsing/                # 文档解析层
    pdf.py                #   PyMuPDF：元数据、页数、文本抽取、渲染、search_for
    classify.py           #   原生/扫描/混合判定（text_bearing_rate）
  indexing/               # 全文搜索层
    fts.py                #   trigram FTS5 外部内容表 + 触发器
    snippets.py           #   命中片段与页码（Python 侧算偏移，FTS5 无 offsets()）
  search/                 # 搜索编排：文件名/元数据/全文/筛选/排序
  ocr/                    # OCR 任务层
    engine.py             #   RapidOCR 封装；后端可选 cpu/directml，失败可降级
    queue_ops.py          #   任务拆分、进度、重试
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
  jobs/                   # 后台任务队列：暂停/恢复/重试/进度/并发上限
  backup/                 # 备份、恢复、迁移
  services/               # 应用服务层：把上面各层编排成用例（ScanService 等）
  ui/                     # UI 层，只用 services/，不 import db.repositories
    main_window.py
    pages/                #   每个界面一个文件，对应 docs/UI-SCREENS.md 的编号
    workers.py            #   QThread/Signal 桥；主线程绝不做扫描/索引/OCR
    models_qt.py          #   Qt 表格/树模型（虚拟化）
  diagnostics/            # crash.log / state.log / 自检页数据源
tests/
  probes/                 # 阶段 0 的技术验证探针（保留，可重跑）
  unit/                   # 纯逻辑，无 UI、无真实文件
  integration/            # 临时目录 + 真实 SQLite + 真实 PDF 样本
  guards/                 # pytest 形态的守卫：依赖版本锁、架构依赖方向、性能红线
gates/                    # 门禁链（01_deps_guard … 09_readback，串联取数→校验→发布，末行 VERDICT: ALL GREEN）
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
- **GPU 任务全局串行**：P5 孤跑实测单个 OCR(DirectML) 进程吃掉 **701MiB** 显存，把本机空闲从 1369MiB 压到 668MiB；
  而嵌入模型（P6 fp32）也要在同一块卡上跑。两个 GPU 任务同时启动就是 1400MiB > 1369MiB，直接 OOM。
  队列必须保证「同一时刻最多一个 GPU 任务」，
  且 OCR/嵌入要能在 UI 提示下让位给阅读器。
- 取消：worker 每处理一页检查一次取消位；PyMuPDF 的页面级调用是可安全中断的粒度。

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

| # | 决策 | 依据 | 状态 |
| --- | --- | --- | --- |
| D1 | 全文用 FTS5 `trigram` 外部内容表 | P1：中文查询命中正常，30 万行 13.7s；`unicode61` 命中 0 | 已验证 |
| D2 | 命中偏移在 Python 侧算，不用 `offsets()` | P1：`pragma_function_list` 证明 FTS5 只有 `rank/snippet/bm25/highlight` | 已验证 |
| D3 | 外部内容表必须配 3 个触发器，delete 命令带上被索引列 | P1 `delete_trigger_trap`：漏列不报错，留下删不掉的幽灵行 | 已验证 |
| D4 | 路径身份用 `realpath` 不是 `normpath` | P7：8.3 短名把空格吃掉（`报告 A.pdf`→`报告A~1.PDF`），纯字符串无法归一 | 已验证 |
| D5 | 主记录唯一性用 `path_key COLLATE NOCASE` 唯一索引 | P7：重叠根重复扫描 3 条记录不膨胀；大小写变体被索引拒绝 | 已验证 |
| D6 | OCR/嵌入后端默认 DirectML，CPU 兜底 | P5：OCR **6.36×**（25,835→4,062ms/页均值）；P6：嵌入 **7.8×**（18.8→146.9 chunks/s）；CUDA 本机实测不可用 | 已验证 |
| D6b | 量化（int8）**不作为提速手段**，只用于省体积 | P6：int8+DirectML 79.3 chunks/s **慢于** fp32 的 146.9 —— 「量化必提速」已被证伪 | 已验证 |
| D6c | OCR 移出自动索引流程，改为显式触发 | P5：全量 101 万页需 1,144h(DML)，而无人值守预算反算是 284ms/页，实测 3,281ms | 已验证（范围待用户勾，docs/RISKS 2.2） |
| D7 | onnxruntime 只装 directml 单一发行版 | 2.2：两个发行版共存导致 import 段错误 | 已验证 |
| D8 | 全文与向量分库存放 | P1：trigram 索引 ≈ 原文 6.9×；P6：4.04M 向量 fp32 ≈ 7.7GB | 设计中 |
| D9 | 阅读器用 PyMuPDF 渲染 + QtPdf 备选 | P3：两条通道都出图，fitz 135ms/页中位、QtPdf 43–50ms | 已验证 |
| D10 | 不依赖文件监听作为唯一变更来源 | P4：被监听目录自身被重命名 → 0 事件；必须定期全量校验 | 已验证 |

## 六 · 明确不做（阶段 0 决定，不是遗漏）

- 不支持 DOCX/XLSX/PPTX/EPUB 解析归档（SPEC 2.1）。
- 不做图书馆业务（借阅/ISBN/馆藏，SPEC 2.2）。
- 首版不做 PDF 编辑、批注保存。
- 不自动移动、合并、删除用户文件（SPEC 3.6/3.7；默认只报告）。
- 不引入云端服务；不上传任何文档内容、文本、向量、元数据。
