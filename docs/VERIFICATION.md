# 阶段 0 · 技术验证结论

本文件只写**实测结果**。每条结论后面标证据来源（探针脚本 + 产物 JSON）。
产物 JSON 在 `.probe_work/`（已 gitignore：里面含本机真实路径与真实文件名，不入库）。
没跑过的东西一律进第六节的「候选 / 未决」表，不混进结论。

探针脚本 `tests/probes/p0..p8` 全部可重跑，末尾打印 `VERDICT: ALL GREEN` 或 `RED`。
**p5 现在是 RED，而且是故意的** —— 它测出来的量级证明「全量 OCR」这条路线在本机不可行，
我没有为了让它变绿去调阈值（阈值本身也是反算出来的，见 4.6）。

重跑方式见第七节。

---

## 一 · 环境与依赖版本（实测）

| 项 | 实测值 | 性质 |
| --- | --- | --- |
| OS | Windows 10 build 19045（`sys.getwindowsversion()`） | 已确认 |
| 机器名 / 架构 | `DESKTOP-7VQSACS` / AMD64，**8 逻辑核** | 已确认 |
| 内存 | **15.86GB** 总（= 宣称的 16GB），本次实测时刻可用仅 **2.33GB（load 85%）** | 已确认；**注意**：开发时这台机不是空载的，内存红线必须在低可用时刻也测一遍 |
| 磁盘剩余 | C: 267.6GB 空闲；**H: 133.5GB 空闲** | 已确认；H: 的剩余空间直接约束索引体积策略（见 docs/RISKS 2.9：外推 28–48GB） |
| GPU | GTX 1060 6GB，驱动 582.66，算力 6.1（Pascal）；`nvidia-smi` 实测**空闲显存只有 1369MiB**（p5 孤跑时刻） | 已确认 |
| 工具链 | git 2.55.0.windows.5、pip 26.2.1、PyInstaller 6.22.3 | 已确认 |
| Python（项目 venv） | **3.11.7 64bit** | 已确认 |
| SQLite（`sqlite3` 模块自带） | **3.41.2** | 已确认；`trigram` 要求 ≥3.34，满足 |
| `LongPathsEnabled`（`SYSTEM\CurrentControlSet\Control\FileSystem`） | **1（已开启）** | 已确认 |
| PySide6 | 6.12.0 装得上、**导入即崩**；**6.8.3 可用** | 已验证，见 2.1 |
| PyMuPDF | 1.28.2 可用 | 已验证，见 4.3 |
| onnxruntime | 1.21.0 / 1.22.0 / 1.23.2 / 1.24.4 / 1.26.0 **全部 DLL 初始化失败**；**1.19.2 / 1.20.1 可用** | 已验证，见 2.2 |
| onnxruntime-directml | **1.20.1 可用**，providers = `DmlExecutionProvider, CPUExecutionProvider` | 已验证，见 2.2 |
| RapidOCR | rapidocr-onnxruntime 1.4.4，模型随 wheel 打包（det 4.7MB + rec 10.9MB + cls 0.6MB） | 已验证，见 4.6 |
| watchdog | 6.0.0，Windows 走 `WindowsApiObserver` | 已验证，见 4.5 |
| PyInstaller | 6.22.3，`--onedir` 构建 + 冻结冒烟通过 | 已验证，见 4.9 |

---

## 二 · 版本锁死条款（硬约束，不是偏好）

### 2.1 PySide6 必须钉在 6.8.x

`PySide6==6.12.0` 安装成功，但 `import PySide6.QtCore` 报 `[WinError 127] 找不到指定的程序`；
`ctypes.WinDLL('Qt6Core.dll')` 同样 127 —— 是 Qt 6.12 的 `Qt6Core.dll` 引用了本机 user32/kernel32 没有的导出函数。
同一 venv 换 `PySide6-Essentials==6.8.3 + shiboken6==6.8.3` → `IMPORT OK qt 6.8.3`。

→ `requirements/base.txt` 写 `PySide6==6.8.3`，**不许写 `PySide6>=6.8`**。

### 2.2 onnxruntime 必须钉在 ≤1.20.x，且全项目只允许一个发行版

1.21+ 的 `onnxruntime.dll` 直接 `LoadLibrary` 就返回 `WinError 1114`（DLL 初始化例程失败），与 Python 版本无关。
逐版本实测二分：**1.19.2 OK / 1.20.1 OK / 1.21.0 起全灭**。
排查过程中排除的伪线索：PE 导入表里全部依赖 DLL 都存在；`api-ms-win-core-path-l1-1-0` 是 API set 虚拟项，不是缺失；本机 `msvcp140 = 14.51` 是新版，不是运行库缺失。

另一个**装包陷阱**（这个更危险，因为它不报错）：`onnxruntime` 与 `onnxruntime-directml` 都往同一个 `onnxruntime/` 包目录写，
先后装两个 → `import onnxruntime` **直接段错误 exit 139**，没有任何异常可捕获。

→ 依赖只允许 `onnxruntime-directml==1.20.1`（它自带 CPU EP）；安装校验脚本必须断言纯 `onnxruntime` 不在依赖树里。

### 2.3 CUDA 不可用，DirectML 可用 —— 这是实测出来的，不是推断

`onnxruntime.get_available_providers()` 返回 `['DmlExecutionProvider','CPUExecutionProvider']`，**没有 CUDA**。
叠加两层原因：装的是 directml 发行版；Pascal(sm_61) 在现代 CUDA 12/13 已弃用。

→ SPEC 第五节明令的那条假设（「GTX 1060 支持 CUDA ⇒ 推理后端兼容」）**已被证伪**。
本项目所有 GPU 路径只走 DirectML，且 CPU 后端必须在无 GPU 的机器上也能独立跑通（p5 已双向实测）。

---

## 三 · 探针结论索引

| 探针 | 主题 | 结果 | 关键实测数字 |
| --- | --- | --- | --- |
| p0 | 真实语料普查 | ✅ | 扫 186,748 个目录，**7,768 份 PDF / 120.6GB** |
| p1 | FTS5 中文全文 | ✅ | 30 万行：trigram 建索引 13.7s / 4 字查询 6.4ms；unicode61 中文命中 **0** |
| p2 | PDF 抽取/渲染/分类 | ✅ | 40 份真实文件 10,413 页；抽取 302.5 页/s；150dpi 渲染中位 135.1ms |
| p3 | 桌面 UI 与渲染管线 | ✅ | Qt 6.8.3 全绿；QtPdf 打开 26.1ms / 渲染 43.4ms；全进程 RSS 139.3MB |
| p4 | 文件监测 watchdog | ✅ | 300 文件批量 **0 丢失**；被监听根被改名 → **0 事件** |
| p5 | OCR 前端 | ❌ **不达标（有意保留）** | DirectML 中位 3,281ms/页 vs 预算 284ms；全量 101 万页 ≈ **1,144 小时**。**该 284ms 预算已于 2026-10-15 作废重定（D-028）**，产品口径改成"超时 + 每日页预算"，见 4.12 |
| p6 | 语义向量 | ✅ | 512 维；fp32+DML 146.9 chunks/s（全量 7.6h）；int8 **反而更慢** |
| p7 | 路径与文件身份 | ✅ | `realpath` + `COLLATE NOCASE` 唯一索引，15 条断言全绿 |
| p8 | Windows 打包 | ✅ | 构建 267.3s / 产物 247.6MB；冻结 exe 冒烟全绿 |
| **p9** | **断言有没有约束力**（反向注入，阶段 1 新增，阶段 2 扩到 46 条） | ✅ **46/46** | 46 种"能骗过断言的坏法"全部被抓到（1–18 阶段 1，19–46 阶段 2）；每次注入都在系统临时目录的**仓库副本**里做，工作区产品代码一行未改 |
| **p10** | **OCR 这一层的断言有没有牙齿**（阶段 5 新增的反向注入） | ✅ **45/45** | 45 种坏法（含"把 OCR 伪装成原生正文""失败页写空串冒充跑过""预算只查不扣"）全部让对应断言真变红；同样在临时副本里做 |
| **p11** | **OCR 产品路径端到端实测**（真引擎 + 真语料扫描书页 + 真队列 + 真 FTS） | ✅ **9 项判定 0 未过** | 6 页识别 586–963 字/页；单页 1,985–2,835ms；峰值 RSS 894MiB；显存 free 1,983→651MiB；幂等新增推理 **0**；控制组新增推理 **0**；详见 4.12 |
| e2e | 阶段 2 真链路验收（真 PDF / 真 worker / 真 watchdog，`tests/e2e/`） | ✅ **11/11** | 5 份重叠根语料跑完整链路；四条通道真实命中；正文页码 2、3 是真页码；全程不动磁盘（sha256 指纹前后相等）；crash.log 零线程异常 |
| 守卫 | `tests/guards/`：G21 依赖、架构（AST）、迁移不丢数据 | ✅ | 三条都能独立跑并打印 `VERDICT`；阶段 1 起进 `gates/stage1.py` |

---

## 四 · 逐条实测详情

### 4.1 语料量级（p0）—— 与 SPEC 的「约 5,000 份」不符，以实测为准

扫描根：`C:/Users/<当前用户>`、`D:/`、`E:/`、`F:/`、`G:/`、`H:/`，遍历 186,748 个目录，未超时。

- **7,768 份 PDF / 129,546,147,822 B = 120.6GB**；单文件 p50 3.7MB、p90 37.5MB、p99 220MB、**最大 1,157,502,758B（1.1GB）**
- 尺寸分布：<1MB 1,708 / 1–10MB 4,067 / 10–50MB 1,464 / 50–200MB 443 / **≥200MB 86 份**
- 分盘：E: 1,778 / F: 2,694（80.7GB）/ G: 1,513 / H: 1,706 / C: 50 / D: 27
- 最挤的单一目录 722 份（完整分盘与目录明细只在 `.probe_work/p0_corpus_census.json`，含真实路径，不入库）

→ 设计基线取 **8,000 份 / 120GB / 200 万页**，性能红线按 **×10（8 万份）** 反算压力余量。
→ 「存在 1.1GB 单文件、946 页单文件」是硬事实，禁止任何"一次性加载整个文件"的写法。

### 4.2 全文检索（p1）—— trigram 可用，bigram 是备选，unicode61 直接出局

300,000 行真实中文语料，同一份数据分别建四种表：

| 方案 | 建索引 | 库体积 / 原文比 | 4 字中文查询 | 2 字中文查询 | 单字 |
| --- | --- | --- | --- | --- | --- |
| `unicode61` | — | 69.4MB | **命中 0** | 命中 0 | 命中 0 |
| `trigram` | 13.74s（+原始表 4.07s） | 122.9MB / **6.91×** | **6.39ms** ✅ | 499ms（退化到 LIKE 回退） | 424ms（同上） |
| `bigram`（自写预分词） | 17.37s | 263.9MB / **14.83×** | 6.95ms | 1.42ms | 0.14ms（命中 0，需 LIKE，542ms） |

- trigram ≥3 字符走 FTS，1–2 字符必须显式 LIKE 回退，否则结果静默为空 —— **这是会骗人的坑，已写进 docs/DATABASE 的硬规则**
- 可用辅助函数实测只有 `rank, snippet, bm25, highlight`；**FTS5 没有 `offsets()`**（`no such function`），高亮只能靠 `highlight()`/`snippet()`
- external-content 表同步：insert 命中 1、update 后旧标记 0 新标记 1、delete 后 0 —— 全绿，前提是三条触发器都写对、`'delete'` 命令带上被索引列（不带就静默留幽灵行，docs/DATABASE 已作为陷阱断言固化）
- 规模化下 `bm25` 取 top20 = 6.54ms
- WAL 下 1 写 12 并发读：读 p99 = 1.01ms，无错误；`Connection.backup()` 出 364,544B 快照，`integrity_check` = ok，行数一致

### 4.3 PDF 抽取 / 渲染 / 类型判定（p2）

按 p0 尺寸分桶各抽 8 份（40 份真实文件，共 10,413 页）：

- 打开+逐页取文本 **302.5 页/s**；页数中位 179、均值 260.3、**最大 946**
- 150dpi 渲染：均值 286.8ms、**中位 135.1ms**
- 进程 RSS 48.4 → 174.6MB（40 份串行、边处理边释放，未泄漏）
- 类型判定分布：`native_text` 23 / `mixed` 2 / **`scanned_image` 15**，可提取文本页占比均值 0.562
- 边界样本（自建）：0 字节、纯垃圾字节、截断、加密 —— `is_pdf` / `needs_pass` / `is_repaired` 能区分，且 `TOOLS.mupdf_display_errors(False)` 后不打印噪声

→ **37.5%（抽样口径）是纯扫描页**，这个数字直接决定了 4.6 的结论。

### 4.4 UI 与渲染管线（p3，`QT_QPA_PLATFORM=offscreen`）

- Qt 6.8.3：`QApplication` 创建 OK；200×6 `QTableWidget` + `QTreeWidget` + `QLineEdit` 控件树离屏出图成功
- **QtPdf（PySide6.QtPdf）实测可用**：真实语料 PDF（94 页）`load` = `Error.None_`，打开 26.1ms，`render` 成 1000×1400 QImage 43.4ms，图像非空，`getAllText(0)` 能取到字
  - 注意真实 API 是 `load / render / close / metaData(field) / getAllText(pageIdx)`，**不是** `renderPage / unload / metadata`；第一轮"QtPdf 不可用"是我调错方法，不是库的问题
- PyMuPDF → QImage 桥接：`pix.samples` + `Format_RGB888` + `.copy()`，转换 2.6ms（fitz 侧 open+render 51.5ms），图像非空
- **QWebEngineView 可用但代价另算**：实例化 RSS +32.7MB、0.29s —— 是否引入仍是待决项（docs/RISKS 未单列，见本文 六 · C4）
- 跨线程：`QThread` + `Signal` 走 `QueuedConnection`，5 个进度事件按序 + done 载荷回主线程，往返 85.0ms
- 中文绘制：请求 `Microsoft YaHei` 实际解析到同一 family（`resolved_ok true`），出图非方块
- 全进程 RSS 起 45.1 → 终 139.3MB

→ 渲染主路径定为 **PyMuPDF → QImage**（p2/p3 双测），QtPdf 作为 PDF 元信息/文本兜底。

### 4.5 文件监测（p4，watchdog 6.0.0 `WindowsApiObserver`）

- 批量 300 文件：写入 0.21s，收到 **302 个 created**，丢失率 -0.007（无丢失）
- **被监听目录本身被重命名 → delta 事件 0**：observer 还挂在旧句柄上，对根改名完全盲。→ 必须有周期性根存在性自检 + 全量扫描兜底
- 跨目录移动被上报成 `created + deleted`，**不是** `moved` → 不能只信 moved 事件
- 中文路径事件延迟 0.9ms，路径字符串无损
- 645 个事件 **0 起顺序违规**（无 modified 先于 created）
- 停止监听期间新增 2 个文件 → 事件流不可见，**只能靠扫描发现** → 增量监测与全量对账两条路都必须存在

### 4.6 OCR（p5）—— 结论：全量 OCR 在本机不可行，必须改成按需 / 可勾选

真实扫描页样本（一份 190 页的扫描版图书，1700×2200px；书名只存在于 gitignore 的产物 JSON 里），
CPU 与 DirectML 各跑同 14 页，**识别文本逐字一致**（`text_identical true`，814.9 字/页）。

| 后端 | 初始化 | 均值 | 中位 | 页/分钟 | RSS 增量 |
| --- | --- | --- | --- | --- | --- |
| CPU | 3.3s | 25,835ms | 20,931ms | 2.3 | +33.7MB |
| DirectML | 1.86s | **4,062ms** | **3,281ms** | 14.8 | +335.7MB |

- 加速比 **6.36×**（对比过，不是自我安慰）
- 显存实测消耗 **701MB**，DirectML 跑完剩 668MB（起始空闲 1369MB）→ GPU 余量本就紧张，这直接支撑了 docs/ARCHITECTURE 的「GPU 任务全局串行」
- **门槛不是拍脑袋定的**：由「8 小时无人值守窗口至少推进 10% 待 OCR 页」反算 → 每页预算 **284ms**。DirectML 中位 3,281ms，**差 11.6 倍**。
  该假设标为 `A-OCR-1`，**尚未与用户确认**（docs/RISKS · 2.2）。
- 全量推算（按 p0/p2 真实数字）：待 OCR 页 **1,014,112** → CPU **7,277.7h** / DirectML **1,144.2h**（每天 8h 无人值守 = **143 个工作日**）

→ 已验证：DirectML 快 6.36× 但远达不到无人值守预算；未达标事实保留为 RED，不调阈值粉饰。
→ 架构处理：OCR 从「建索引的一部分」降级为**用户显式触发、按目录/按文件勾选、可断点续跑**的能力，且在 p6 语义层里明确不依赖 OCR。

### 4.7 语义向量（p6）—— 真实 ONNX BERT，无 torch

模型 `model_optimized.onnx`（fp32 90.4MB）/ `model_int8.onnx`（22.8MB），输出 `last_hidden_state` rank 3，
mean-pooling 用的是**真实 attention mask**（tokenizer 默认不 padding，`enable_truncation + enable_padding` 补上；`token_type_ids` 由 `np.zeros_like(ids)` 补，单句输入下等价正确）。

| 模型 | 后端 | 实测吞吐 | 全量耗时（404 万块） |
| --- | --- | --- | --- |
| fp32 | DirectML | **146.9 chunks/s** | **7.6h** ✅ |
| fp32 | CPU | 18.8 chunks/s | 59.8h |
| int8 | DirectML | **79.3 chunks/s（比 fp32 慢）** | 14.2h |
| int8 | CPU | 20.7 chunks/s | 54.3h |

- **「量化一定更快」被证伪**：DirectML 上 int8 反而比 fp32 慢 1.85× → 默认走 **fp32 + DirectML**，量化不作为提速手段（它只省体积：向量库 7.71GB → 1.93GB）
- 质量（fp32:cpu 向量）：相关对余弦均值 **0.6724**，无关对 **0.2969**，分离度 **0.3755**，且**两组区间不重叠**（`min_related_above_max_unrelated true`）
- 方向性陷阱（不是只测数值大小，是测排序方向会不会反）：查「能源」margin **+0.1206**、查「课件」margin **+0.1817**，两条都 `direction_correct true`
- 全量向量体积：fp32 **7.71GB** / int8 1.93GB（按 2 块/页、4,044,409 块）

→ 语义层可行，且**比 OCR 便宜两个数量级**（7.6h vs 1144h）。但语义检索依赖"已有文本"，扫描页没有文本就只能空有向量 —— 依赖图见 docs/ARCHITECTURE 第五节。

### 4.8 路径与文件身份（p7，15 条断言全绿）

核心规则（已固化为 `identity_key = norm(path).casefold()`）：

```
norm(path) = os.path.realpath(path) → normpath → 反斜杠转 /
```

**必须 `realpath` 不能只 `normpath`**：8.3 短名把空格直接吃掉（`报告 A.pdf` → `报告A~1.PDF`），
纯字符串规范化无法把短名和长名归一；实测短名经 `realpath` 后 identity_key 与长名一致。

实测覆盖：
- 同一文件的 3 种大小写写法（`CaseTest`/`cAsEtEsT`、`报告 A.pdf`/`报告 a.pdf`）→ **identity_key 唯一（1 个）**，`COLLATE NOCASE` 唯一索引拒绝重复插入
- 冗余分隔符 4 种写法 → 归一为 1 个 key
- 长路径 **533 字符**（>260）用**普通 API 直接创建成功**（因 `LongPathsEnabled=1`），扩展前缀 `\\?\` 同样成功
- 监听根互相嵌套（B 在 A 内）：A 插入 3 条，B 经唯一索引后**插入 0 条**，主表总量 3 = 期望 3
- 同内容不同路径：hash 相同、identity_key 不同（**不能因为内容相同就合并成一条记录**）
- 同路径内容变更：size / mtime / hash 三者都变
- 断链与不可达（伪盘符、UNC）：`stat` 抛异常，`os.walk` 返回空而不崩
- NTFS `st_dev / st_ino` 可用，且透过短名仍然一致

→ 待确认：`LongPathsEnabled=1` 是本机现状，**不是可以假设的目标机前提**（docs/RISKS 三 · 已排除伪风险第 2 条已就此留了阶段 4 自检要求）。

### 4.9 Windows 打包（p8，PyInstaller 6.22.3 `--onedir`）

- 构建 exit 0，耗时 **267.3s**，产物 **247.6MB**
- 冻结后的 exe 独立冒烟（4.9s）返回：

```json
{"pymupdf":"1.28.2","pdf_pages":1,"onnxruntime":"1.20.1",
 "providers":"DmlExecutionProvider,CPUExecutionProvider",
 "fts5_trigram_hits":1,"sqlite":"3.41.2","qt":"6.8.3","widget_created":true}
```

→ 关键点是**冻结环境里三件容易丢的东西都在**：SQLite 的 `trigram` 分词器（frozen 里真实建表并命中中文）、
DirectML provider（`.dll` 被收进来了）、Qt 6.8.3 控件创建。
→ 结论：`--onedir` 可行；`--onefile` 未测（解压到临时目录会让"数据目录在哪"变复杂，暂不选）。

### 4.10 阶段 1 骨架与数据库实测（2026-10-14，`gates/stage1.py`）

原始输出（`.venv/Scripts/python.exe gates/stage1.py`，本机，非转述；阶段 1 收尾那一次）：

```
门禁运行于 H:\AI project\demo19｜python 3.11.7
  PASS  G21 依赖守卫                     实测：VERDICT: ALL GREEN
  PASS  架构守卫（依赖方向 / SQL 位置 / 无静默吞异常 / 无本机路径字面量 / 导航分组）  实测：VERDICT: ALL GREEN
  PASS  全量回归                         实测：106 passed / 0 failed / 0 error / 1 skipped
  PASS  G1 冷启动 ≤ 1.5s [约定] + 关窗对账 实测：冷启动 0.453s｜进程总耗时 1.015s｜关窗对账 1 条
  PASS  反向注入探针（断言有没有约束力）   实测：18/18 条坏法被抓到
VERDICT: ALL GREEN
```

- **冷启动读数：本阶段共 18 次，全部在 `QT_QPA_PLATFORM=offscreen` 下**（口径：被测进程自报
  `state.log` 的 `window.ready.cold_start_seconds`，见 D-021）：

  | 入口 | 次数 | 读数（秒） |
  | --- | --- | --- |
  | 门禁 `gate_cold_start()`（`python main.py --data-dir <临时> --exit-after 0.3`） | 13 | 0.409 / 0.419 / 0.440 / 0.451 / 0.453 / 0.465 / 0.486 / 0.489 / 0.526 / 0.603 / 0.612 / 0.777 / 0.910 |
  | 临时副本里的进程级测试 `test_进程级冷启动实测符合G1约定` | 2 | 0.344 / 0.376 |
  | 开发期与内联 `python -c` 入口 | 3 | 0.693 / 1.008 / 1.031 |

  **18 次全部 ≤ 1.031s ≤ 阈值 1.5s [约定]**，门禁入口 13 次的中位 **0.486s**。
  **读数分散但没有已查明的成因**，本阶段不再对成因下结论：
  ① 一度写成"`-c` 入口跳过 `sitecustomize` 所以慢 0.6s"—— 随后同一 `-c` 入口复测 0.403s，机制不成立，已撤回；
  ② 0.910s 那一次本机同时有一个 Python 进程在扫 8MB 日志 —— 并发是**候选**解释，没做对照；
  ③ 同一入口先后三批分别是 0.409–0.526s、0.603–0.777s、又回到 0.453/0.489s —— 连"时间漂移"都不是解释。
  留下来的事实只有一条：**分布 0.344–1.031s，最大仍在阈值内**。
  这 18 处读数**都不是真实桌面平台** —— 见 ISSUES I17，真机首屏必须由你亲眼看一次并给数字。
  另：commit 之后又跑了一次 `gates/stage1.py --no-injection` 做提交后确认，读数 **0.401s**（第 19 次，
  不计入上表的交付读数集，只证明提交出去的树是绿的；全量回归同样 106 passed / 1 skipped）。
- **13 张表**：`documents / monitored_roots / categories / document_categories / tags / document_tags /
  document_metadata / collections / processing_jobs / file_operations / operation_items / app_settings /
  schema_version`。**故意不建** `text_pages / content_fts / duplicate_groups`，而且有断言反过来证明它们不存在
  （Q1/Q2 未答，建了阶段 2 就是返工）。
- **迁移的安全边界**：`backup_dir` 缺失 → 直接拒绝迁移（不动结构）；迁移中途失败 → 回滚 + 异常里带
  `pre-migration-0002-*.db` 快照路径；带 3 标签 / 5 文档 / 1 分类的旧库升级到新版本 →
  逐表行数不变、内容读得回、`integrity_check = ok`、`PRAGMA foreign_key_check` 空。
- **跳过的那 1 条是事实不是失败**：8.3 短名实测在测试用的临时卷上不产生短名，按实际结果 `skip` 并说明原因，
  真凭据在 p7（同一台机器、真实语料目录上 15 条断言全绿）。

**门禁链自己有没有牙齿**（在系统临时目录的副本里做，工作区未改）：

```
A 弄坏 casefold      → exit=1｜变红的门禁项：['全量回归']｜实测：105 passed / 1 failed / 0 error / 1 skipped
B G1 阈值改成 0.001s → exit=1｜变红的门禁项：G1 冷启动｜实测：冷启动 1.031s
```

即：门禁不是把测试结果抄一遍的橡皮章 —— 产品代码坏一条，回归项就红；阈值不可达到，读数自己就红。

---

### 4.11 阶段 2 扫描 / 索引 / 检索链路实测（2026-10-14，`gates/stage2.py`）

原始输出（`.venv/Scripts/python.exe gates/stage2.py`，本机，非转述）：

```
门禁运行于 H:\AI project\demo19｜python 3.11.7
  PASS  G21 依赖守卫
        实测：VERDICT: ALL GREEN
  PASS  架构守卫（依赖方向 / SQL 位置 / 无静默吞异常 / 无本机路径字面量 / 导航分组）
        实测：VERDICT: ALL GREEN
  PASS  G1 冷启动 ≤ 1.5s [约定] + 关窗对账
        实测：冷启动 0.464s｜进程总耗时 1.028s｜关窗对账 1 条
  PASS  G2 后台生命周期（worker + 监听 + 关窗对账，冷启动 ≤ 1.5s [约定]）
        实测：冷启动 0.455s｜进程总耗时 1.619s｜worker 2 线程｜回收中断 0
  PASS  G2 端到端验收（真 PDF / 真 worker / 真监听，展示真实搜索结果）
        实测：11 条端到端通过｜真实检索结论 6 行｜带页码的命中 6 行
  PASS  全量回归
        实测：255 passed / 0 failed / 0 error / 1 skipped
  PASS  反向注入探针（断言有没有约束力）
        实测：46/46 条坏法被抓到
VERDICT: ALL GREEN
```

**测的是什么、没测什么，先说清**：

- 端到端 11 条全部跑在 `tmp_path` 下的**真造 PDF** 上：真 drafted-then-rasterized 的纯扫描件（只有图没有字）、
  真截断文件（`%PDF-1.7` + 4096 个 0 字节）、真 AES-256 用户口令加密件、真重叠监测根、真 `WindowsApiObserver` 线程。
  链路里**没有人手调 `scan_root` / `index_document`** —— 只有 `bootstrap()` + `start_background()` + 落盘动作。
  真实语料（7,768 份 / 120.6GB / 202 万页）**一次都没扫过**：Q8 未答，`ROADMAP` 末行禁令在生效（记 **ISSUES I20**）。
- **G3 / G7 / G8 / L4 仍然是反算，不是实测**（p2 单耗 × 量级）。本阶段没有产出任何内存与吞吐数字。

真实检索读数（`pytest tests/e2e -s` 打印、门禁原样搬回，非转述；耗时随负载浮动，另一次跑的是 0–4ms）：

```
查询「人工智能」    ｜口径：只检索文件名 / 路径 / 元数据（本次没有搜正文）｜符合筛选的文档 5 份｜取回 文件名 1 行｜本页 1 行｜耗时 0ms
查询「子目录」      ｜同上｜取回 路径 1 行｜本页 1 行｜耗时 0ms          ← 文件名通道 0 行，两条通道确实分开
查询「政策研究室」  ｜同上｜取回 元数据 1 行，并说明命中的是 `author` 列｜耗时 0ms
查询「违约责任的举证」｜口径：trigram 短语检索（7 字）｜取回 正文 1 行｜ [第 2 页] 合同审阅要点汇编.pdf｜耗时 0ms
查询「附则的生效日期」｜口径：trigram 短语检索（7 字）｜取回 正文 1 行｜ [第 3 页] 合同审阅要点汇编.pdf｜耗时 0ms
查询「审阅要点」    ｜口径：trigram 短语检索（4 字）｜取回 文件名 1 行、元数据 1 行、路径 1 行、正文 1 行｜本页 4 行｜耗时 0ms
```

页码是**真页码**：语料 B 有 3 页，两个检索词分别只出现在第 2、第 3 页，写死 `page_no=1` 的实现骗不过断言
（反向注入 ISSUES I21「正文命中的页码写死成第 1 页」确实让它变红）。

**抓出的两个静默失灵**（详见 `docs/stage-reports/阶段2-交付报告.md` 第五节，两者都已修 + 各有反向注入）：

1. `fs/watcher.py` 的 `_BufferHandler` 没继承 `FileSystemEventHandler` → watchdog 调 `handler.dispatch(event)`
   时 `AttributeError`，**observer 线程在第一条事件上就死掉**，而 `watched_roots` 照旧显示 1、界面毫无察觉。
   修法三处一起：继承基类 + 词表过滤 `dispatch`、`WatchManager.is_alive()`、`BackgroundState.watcher_alive`
   + 状态页 `⚠ 文件监听线程已不在`。为什么阶段 1 没发现：p4 探针自带处理器类，从没走生产代码 —— 已归并入
   `docs/ISSUES.md` 附「接第三方库的回调」一条规则。
2. `diagnostics/logs.py` 的 `threading.excepthook` 读 `args.exc_info`，而 `ExceptHookArgs` 的字段是
   `exc_type / exc_value / exc_traceback` —— **钩子自己抛异常，worker 崩溃现场一行都不剩**。
   同时把那条"用假对象造 `exc_info`"的假断言换成真起一个会崩的线程再轮询 `crash.log`。

**FTS5 侧新实测**：`content_fts` 外部内容表 + 三条触发器在 0002 里第一次带数据落地，
G10（幽灵行 = 0）在迁移侧与运行侧都常驻断言；trigram 对 ≥3 字中文查询在本机 5 份小语料上 0–4ms，
与 p1 的 6.39ms（10 万行级）同量级，1–2 字查询仍按 D-004 显式退回 LIKE 并在结果里标注口径。

### 4.12 阶段 5 本地 OCR 实测（2026-10-15，`gates/stage5.py`）

原始输出（`.venv/Scripts/python.exe gates/stage5.py`，本机，非转述；01:27:47 → 01:34:09 = **382s**，exit 0）：

```
门禁运行于 H:\AI project\demo19｜python 3.11.7
  PASS  G21 依赖守卫
        实测：VERDICT: ALL GREEN
  PASS  架构守卫（依赖方向 / SQL 位置 / 无静默吞异常 / 无本机路径字面量 / 导航分组）
        实测：VERDICT: ALL GREEN
  PASS  G1 冷启动 ≤ 1.5s [约定] + 关窗对账
        实测：冷启动 0.767s｜进程总耗时 1.413s｜关窗对账 1 条
  PASS  G2 后台生命周期（worker + 监听 + 关窗对账，冷启动 ≤ 1.5s [约定]）
        实测：冷启动 0.572s｜进程总耗时 1.814s｜worker 2 线程｜回收中断 0
  PASS  G2 端到端验收（真 PDF / 真 worker / 真监听，展示真实搜索结果）
        实测：11 条端到端通过｜真实检索结论 6 行｜带页码的命中 6 行
  PASS  G5 产品路径端到端实测（真语料扫描件 / 真队列 / 真引擎）
        实测：队列任务 done 进度 [6, 6]｜落库 6 页｜探针 9 项判定，未过 0 项
  PASS  G5 每日页预算真停机（真引擎跑到用满即停）
        实测：预算 2 页 → 真推理 2 页后停在第 3 页，任务 cancelled、文档 partial、待办剩 [3, 4]
  PASS  G5 真引擎测试套件（不许用 skip 冒充验过）
        实测：4 passed / 0 failed / 0 error / 0 skipped
  PASS  全量回归
        实测：349 passed / 0 failed / 0 error / 1 skipped
  PASS  反向注入探针（断言有没有约束力）
        实测：46/46 条坏法被抓到
  PASS  G5 OCR 反向注入探针（阶段 5 的断言有没有约束力）
        实测：45/45 条坏法被抓到
VERDICT: ALL GREEN
```

**同一条命令 21 分钟后再跑一次，判了 RED —— 三条未过全是负载绑定**（原始输出取自
`.probe_work/stage5_final.log`，01:55:40 起跑，非转述；`现场：` 那几行是 pytest 自己的报错头，
门禁按 600 字截断，原样保留）：

```
门禁运行于 H:\AI project\demo19｜python 3.11.7
  PASS  G21 依赖守卫
        实测：VERDICT: ALL GREEN
  PASS  架构守卫（依赖方向 / SQL 位置 / 无静默吞异常 / 无本机路径字面量 / 导航分组）
        实测：VERDICT: ALL GREEN
  RED   G1 冷启动 ≤ 1.5s [约定] + 关窗对账
        实测：冷启动 3.129s｜进程总耗时 4.575s｜关窗对账 1 条
  RED   G2 后台生命周期（worker + 监听 + 关窗对账，冷启动 ≤ 1.5s [约定]）
        实测：冷启动 2.988s｜进程总耗时 4.888s｜worker 2 线程｜回收中断 0
        现场：冷启动 2.988s 超过约定 1.5s
  PASS  G2 端到端验收（真 PDF / 真 worker / 真监听，展示真实搜索结果）
        实测：11 条端到端通过｜真实检索结论 6 行｜带页码的命中 6 行
  PASS  G5 产品路径端到端实测（真语料扫描件 / 真队列 / 真引擎）
        实测：队列任务 done 进度 [6, 6]｜落库 6 页｜探针 9 项判定，未过 0 项
  PASS  G5 每日页预算真停机（真引擎跑到用满即停）
        实测：预算 2 页 → 真推理 2 页后停在第 3 页，任务 cancelled、文档 partial、待办剩 [3, 4]
  PASS  G5 真引擎测试套件（不许用 skip 冒充验过）
        实测：4 passed / 0 failed / 0 error / 0 skipped
  RED   全量回归
        实测：349 passed / 1 failed / 0 error / 1 skipped
        现场：appdata')

    def test_进程级冷启动实测符合G1约定(data_root) -> None:
  PASS  反向注入探针（断言有没有约束力）
        实测：46/46 条坏法被抓到
  PASS  G5 OCR 反向注入探针（阶段 5 的断言有没有约束力）
        实测：45/45 条坏法被抓到
VERDICT: RED（3 条未过）
```

三条未过**是同一条断言**（G1、G2 各测一次冷启动，全量回归里失败的那条就是
`tests/integration/test_app_shell.py::test_进程级冷启动实测符合G1约定`）。成因不是猜的，是同时刻取到的：

| 读数 | 值 | 怎么来的 |
| --- | --- | --- |
| CPU 占用 | **86.6% → 96.5%**（8 逻辑核） | `psutil.cpu_percent(interval=2.0)` 当场跑两次 |
| 可用内存 | **2,665MiB → 2,199MiB**（已用 83.6%） | `psutil.virtual_memory()` |
| 前排进程 | 一个占 **3,220–3,231MiB** 的游戏客户端 | `psutil.process_iter` 按 RSS 排序（进程名不进文档） |
| 显卡 | p11 起跑**之前** util 已经 **97%**、free 1,851MiB | 探针打印的 `显卡·跑之前` 行 |

负载同样抬高了 OCR 读数：单页推理从空载的 **1,985.2 / 2,281.5 / 2,835.0ms** 变成满载的
**2,565.7 / 2,846.9 / 3,379.1ms**，整本墙钟 14.72s → **18.42s**，合成页逐字命中仍是 **12/12**，
控制组仍 **0 次推理** —— 即**结构性结论跨负载稳定，时间类读数不稳定**。

把那条负载绑定的测试 deselected，其余全部在满载下重跑一次：
`349 passed, 1 skipped, 1 deselected in 105.20s`（此刻 CPU 仍 96.5%）——
这就是"其余 350 条与负载无关"的直接证据。

**处置**：阈值一格都没放宽。`gates/stage5.py` 起跑新增一行 `起跑负载：CPU x%｜可用内存 xMiB｜最吃内存进程 …`，
把成因与读数绑在同一条输出里（只记录、不参与判定）。**因此上面这次 RED 的负载行是补记的，不是那次跑打印的**
—— 下一次跑才会自带。台账见 **ISSUES I25**；这条链目前**还没有一次"含新增可选层断言"的 ALL GREEN**，
空载复跑之前不许那样宣称。

G5 第一条里 `tests/probes/p11_ocr_shipped.py` 现场打印的性能与质量读数（**这是本文件里唯一一组 OCR 性能数**，
同一条命令每次跑都会重打一遍，门禁不抄上一次的结果）：

```
样本：S1 第 217 页起 6 页｜原生文本层 0 字｜索引后 text_status=none
引擎：provider=DmlExecutionProvider｜初始化 1.016s｜onnxruntime 1.20.1
耗时：单页推理 1985.2 / 2281.5 / 2835.0 ms（6 页）｜整本墙钟 14.72s（含出图与落库 2453.3ms/页）｜队列收尾 0.154s
内存：启动态 72.2MiB → 跑完 532.4MiB｜峰值 894.0MiB（比启动态 +821.8MiB）
显卡·跑之前：['NVIDIA GeForce GTX 1060, 1983, 4047, 99']
显卡·跑之后：['NVIDIA GeForce GTX 1060, 651, 5379, 98']
识别质量（真实页，无人工转写）：每页字数 [673, 756, 731, 963, 604, 586]｜每页行数 [30, 47, 30, 32, 33, 30]
识别质量（合成页，有标准答案）：逐字命中 12/12（1.0）｜行均相似度 1.0｜单页 971.1ms
追溯：6 个取自识别正文的词，命中页均含预期页｜出处标签 ['OCR 识别（可能有错字）']
幂等：点名 1 份｜该跑 0 份｜新增任务 0 条｜已是当前引擎版本 1 份｜第二次点名新增推理 0 次
控制组（整页图 + 隐形字层）：C1｜新增推理 0 次｜字层已经在正文索引里（2833 字 / 6 页）
```

**这一段里唯一被改动的一格是样本名**：探针现场打印的是用户库里的真实文件名，按 R-003「真实文件名不入库」
换成代号 **S1**（抽 6 页的扫描正文样本）与 **C1**（整页图 + 隐形字层的控制组样本）。
两个代号对应的真名由探针自己写在 `.probe_work/p11_ocr_shipped_result.json`（gitignored，重跑即再生），
其余每一个数字都是原样搬运。

`显卡·…` 四列的口径是 `nvidia-smi --query-gpu=name,memory.free,memory.used,utilization.gpu`，
即 **跑前 free 1,983MiB / used 4,047MiB / util 99% → 跑后 free 651MiB / used 5,379MiB**。
探针随读数打印自己的 caveat：DirectML 落在哪个适配器没有公开查询接口，这是 `nvidia-smi` 问到的那张卡。

G5 第二条（预算真停机）的现场读数：

```
预算：这里给死 2 页；生产默认 6,000 页/日（一次门禁跑不到那个量），同一条码路
推理：真引擎实际推理 2 页｜墙钟 2.04s（1018ms/页）
任务：点名回执「点名 1 份｜该跑 1 份｜新增任务 1 条」→ state=cancelled｜done/total=2/4｜attempts=1
停机原因：跑到第 3 页之前今天的页预算用满（今日 OCR 已用 2 页 / 预算 2 页（剩 0 页，UTC 日 2026-10-14））
文档：ocr_status=partial｜库里 OCR 行 2 页｜主记录记 2 页｜待办剩 [3, 4]
```

**测的是什么、没测什么，先说清**：

- **同一样本三次独立运行的散布**：单页推理 **1,985.2 / 2,264.3 / 2,357.3**（各自 min）到 **2,835.0 / 3,269.5 / 5,780.0**（各自 max），
  含出图落库 **2,453.3–3,842ms/页**，峰值 RSS **806–1,131MiB**。三次都在同一台机器、同一份 PDF、同一批页上。
  **没有取平均** —— 最慢那次跑之前 `nvidia-smi` util 已经是 **100%**（本机另有程序在用卡），这正是 D-028
  用「实测最慢 ×2」而不是 ×1.2 定超时上限的原因。
  **第四次是同一条链在满载机器上跑的**（01:55，CPU 96.5%）：单页 **2,565.7 / 2,846.9 / 3,379.1ms**、
  整本墙钟 **18.42s**（含出图落库 **3,070.0ms/页**）、峰值 RSS **896.4MiB** —— 时间类读数更差，
  而**逐字命中 12/12、控制组 0 次推理、幂等第二次点名新增推理 0 次、落库 6 页**这四条结构性读数一格没变。
  这就是本项目可以宣称的边界：**结构性结论跨负载稳定，耗时与内存读数只在同负载条件下可比**（**ISSUES I25**）。
- **识别质量只有合成页能报百分比**。真实语料那 6 页没有人工转写，所以只报结构与"取出的 6 字词能搜回原页"；
  把 12/12 说成"OCR 准确率 100%"是假话，那是探针自己合成、自己知道答案的一页。
- **控制组防的是真事故**：整页图 + `render_mode=3` 隐形字层的扫描件，字层已在正文索引里 → 新增推理 **0 次**。
  真语读不到时探针**自己合成**同一批字，两条路都产出同一个读数；门禁的 G5 第三条把"全套真引擎测试全 skip"判 RED。
- **量级红线仍未压测**：G3 首建 ≤6h、G7 单文件 RSS 回落、G8 进程 1.2GB、L4 ×10 档 —— OCR 侧只新增了**单点**读数（**ISSUES I16**）。
  CPU 档在**有 DirectML 的本机上永远不会被走到**，所以"无 GPU 机器独立完成同一批 OCR"这条**没有真机读数**（留给阶段 7）。
- **真实语料一份没扫过**：OCR 全部跑在 `tmp_path` 与探针样本上，Q8 未答（**ISSUES I20**）。
  "全库待 OCR 1,014,112 页"是 p5 的**抽样外推**，不是这套代码扫出来的。
- 机器可读产物：`p11_ocr_shipped_result.json`（`--out` 默认落 `.probe_work/`，收尾会清零，重跑探针即可再生）。

### 4.13 最终交付链实测（2026-10-15，`gates/final.py` 八段一条命令）

跑法与口径：`.venv\Scripts\python.exe gates\final.py --only coldstart --only e2e --only regression
--only consistency --only soak --only injection --only ocr --only package`
（原始输出 `.probe_work/final_chain_1015.log`，14,078 字节。收尾只删了**当场写的脚本与被后续读数取代的 log**，
这一份与 `frozen_smoke_result.json` 留在 gitignored 的现场目录里当原始证据 —— 不入库，重跑即再生）。
**`guards` 段故意没在这一场里**：它含交付文档在场性判定，而报告当时还没写 ——
链自己在输出里就把这一段标成"未跑"，不许拿这一场的 ALL GREEN 给报告背书。

```
门禁运行于 H:\AI project\demo19｜python 3.11.7
        起跑负载：CPU 14.1%｜可用内存 5145MiB｜最吃内存进程 MemCompression 598MiB
        本次跑 8 段：coldstart + e2e + regression + consistency + soak + injection + ocr + package
  ── 段 coldstart（1.0s）      PASS  G1 冷启动 ≤ 1.5s [约定] + 关窗对账
  ── 段 e2e（10.1s）           PASS ×2（后台生命周期 0.428s｜11 条端到端｜带页码命中 6 行）
  ── 段 regression（49.6s）    PASS  全量回归 355 passed / 0 failed / 0 error / 1 skipped
  ── 段 consistency（3.5s）    PASS ×3（p12 注入 17/17｜p14 ALL GREEN｜真实现场"本次未跑"）
  ── 段 soak（288.8s）         PASS ×2（p13 注入全绿 + 真跑 4.0 分钟 9/9）
  ── 段 injection（170.9s）    PASS ×2（p9 46/46、p10 45/45）
  ── 段 ocr（28.4s）           PASS ×3（产品路径 / 预算真停机 / 真引擎套件 4 passed 0 skipped）
  ── 段 package（255.0s）      PASS ×2（build.py 内容断言 + 冻结冒烟）
  SKIP  未跑的段：guards（依赖守卫 + 架构守卫 + 交付文档在场性）—— 这一场的「全绿」不覆盖它
  合计判定 16 条｜本次未跑 1 段
VERDICT: ALL GREEN
```

八段墙钟相加 **807.3s（13 分 27 秒）**；这场链的**起止时刻是反推的**，不是门禁自己打的（它只打每段耗时）：
`.probe_work` 里 `final_chain_1015.log` 与 `frozen_smoke_result.json` 的最后写入都是 **04:44:55**，
减 807.3s → 起跑 **约 04:31:28**；再用末段互验 —— 冻结冒烟的临时目录名 `frozen_smoke_1015_044235`
（04:42:35 起跑）＋ build 111.2s ＋ 冒烟 139.7s ≈ package 段自报的 **255.0s**，三条对得上。
每条 PASS 的读数都是**当次现场打印**，没有一条从 4.10/4.11/4.12 抄。
**这 16 条里有一条不算验过**：consistency 段的"一致性核查 p12 对真实数据根"在没给 `--data-root` 时是一行
**结构上不可能变红**的 `PASS`，它的"实测"文本自己写着"本次未跑"—— 所以 `合计判定 16 条` ≠ 16 件覆盖到的事，
真实现场那一次是另开的 `--only consistency`（下面"报告写完之后的三场补跑"里的第二场）补的。这条毛病记在 **ISSUES I36**（OPEN），
改法与为什么收尾时没改都写在 **D-034** 末尾。

**逐字关键读数**（都来自上面那一场）：

- 冷启动：源码 **0.437s**（G1 阈值 1.5s **[约定]**）、后台生命周期那次 **0.428s**；
  **冻结产物 1.109s**（`cold_start_seconds=1.109`，同一阈值内，但比源码慢 2.5 倍 —— 这是打包带来的真实代价）。
- 回归：**355 passed / 1 skipped**（那 1 条 skip 是无 DirectML 时才走的 CPU 档）；
  同一条链在**注入坏法之后**当场变红的记录见下面「两条补做的注入」。
- 长跑（4.0 分钟真采样，进程树求和口径）：
  首段 RSS 中位 **83.4** → 末段 **83.8MiB**（增长 **+0.4**，全程 83.0–83.8）、G8 余量 1,116.2MiB；
  线程 13 → 10（峰值 15）、句柄峰值 315；排空用时 **0.0s**｜结束时队列 `{'done': 90}`；
  盘上 PDF **52** ＝ 库里未标缺失 **52**（已标缺失 10）；`app.log` 相关 **1 份｜28KiB｜126 行**；
  S9 用 p12 复查这场长跑现场 **13 条全绿 0 未验**；快照 3 份 `@v0/@v1/@v2`（8/120/148KiB）。
  ⚠️ `排空 0.0s` 不等于"大积压能排空"，见 **ISSUES I32** —— 交付报告把这条放在"已实现但尚未充分验证"。
- OCR 产品路径（真引擎真扫描书 **S1** 第 217 页起 6 页，原生文本层 0 字）：
  `provider=DmlExecutionProvider`｜初始化 0.707s｜onnxruntime 1.20.1｜
  单页推理 **1691.0 / 2006.4 / 2647.6ms**｜整本墙钟 **12.75s**（含出图落库 **2125.0ms/页**）｜队列收尾 0.152s｜
  启动态 72.4MiB → 跑完 540.5MiB、峰值 **869.2MiB**｜显存跑前 free 1,676MiB → 跑后 free 3,280MiB
  （GTX 1060 4,354MiB 总量，util 0%→32%）｜每页字数 [673, 756, 731, 963, 604, 586]、每页行数 [30, 47, 30, 32, 33, 30]｜
  合成页逐字命中 **12/12**、行均相似度 **1.0**、单页 984.3ms｜6 个取自识别正文的词命中页均含预期页、
  出处标签只有 `['OCR 识别（可能有错字）']`｜幂等第二次点名**新增推理 0 次**｜
  控制组 **C1**（整页图 + 隐形字层）**新增推理 0 次**（字层已在正文索引里，2833 字 / 6 页）｜
  预算给死 2 页 → 真推理 2 页后停在第 3 页，`state=cancelled`、`done/total=2/4`、`attempts=1`、
  文档 `ocr_status=partial`、待办剩 `[3, 4]`、复用 2 页。
  样本真名↔代号只留在 gitignored 的 `.probe_work/`（R-008），上面这行里的书名不出现在任何入库文件。
- 打包（`--only package` 用**当前源码**重建，ISSUES I30 的残留因此清掉）：
  整包 **392.2MiB**｜`_internal` 明细合计 374.3MiB ＝ 实际 374.3MiB（对账相等）｜构建 111.2s｜
  OCR 层在场 `{'rapidocr': True, 'onnxruntime': True}`、3 个 `.onnx` 模型、3 个推理 DLL
  （`DirectML.dll` / `onnxruntime.dll` / `onnxruntime_providers_shared.dll`）、
  版本指纹要读的 `.dist-info` 6 份（含 `onnxruntime_directml-1.20.1`、`rapidocr_onnxruntime-1.4.4`）、
  迁移脚本按 `.py` 进包且与源目录清单一致、构建日志 `ERROR` 行 **0 条**；
  产物自报版本：`dist\PdfArchiver\PdfArchiver.exe --version` → **`PdfArchiver 0.5.0`**（退出码 0；2026-10-15 读数，
  轮十七重打包后为 `1.0.0`，见 `docs/VERIFICATION-RUNLOGS.md` §4.27）。
- 冻结产物冒烟 29 行全过，关键几条：干净目录首启退出码 0、优雅关闭 True（0.35s）、峰值 RSS 108.8MiB、
  采样 12 次；`crash.log` **0 个**；`schema_version=3`、默认分类 14；两批语料 **273/273** 在册；
  正文 **304 行**、`text_pages − content_fts = 0`（这两个数是在**第一批 153 份**抽完正文时量的，
  第二批只验到"文档数 = 磁盘数 = 273"，所以不许把"273 份 ↔ 304 行"读成同一时刻的两个数）；
  **另有一场更早的独立冒烟**用的是 273 份 / **544 页正文**那份语料 ——
  `docs/BACKUP-RESTORE.md`（543 ≠ 544 那条恢复实测）与 `docs/TROUBLESHOOTING.md` 里的 544 都出自那一场上，
  **两场的数各自成场，不许混用**（这也是为什么两份文档的文档数一样、正文数不一样）；
  OCR 在**冻结产物里**真跑通（1 页、等 4.1s、峰值 RSS 528.2MiB、
  线程 46、句柄 654；识别正文前 120 字非空、版本戳 `rapidocr-onnxruntime/1.4.4+onnxruntime/1.20.1+dpi200`）；
  重启前后计数一致；**强杀恢复**：残尸 1 条 → `background.started.recovered = 2` → 未完成 0 条、失败 0 条；
  事件序列 `['startup.begin','startup.done','window.ready','background.started','shutdown']`；
  产出的配置与日志里**不含**开发机仓库路径 / venv 路径（扫了 2 个文件，命中=无）；
  运行目录在仓库外（`%TEMP%\frozen_smoke_1015_044235\`）。

**两条补做的坏法注入**（交付需求"每写完一条断言先用能骗过它的坏法真注入一次"，本轮欠账清零）：

1. **`rebuild` 只读数不补救**：把 `services/index_service.py` 的 `self.texts.rebuild_all()` 换成 `pass`。
   第一版 p14 的 ⑤ **当场没变红**（9/9 仍 ALL GREEN）—— 因为它在探针里自己写了一遍 `VALUES('rebuild')`，
   压根没走产品入口（**ISSUES I33**）。改成 `import` 产品的 `IndexService.rebuild_fts()` 并核对它返回的六个数之后：
   p14 → `VERDICT: RED（2 条…）` 退出码 1，产品入口返回
   `{'pages': 2, 'docs': 1, 'unindexed_before': 1, 'unindexed_after': 1, 'stale_before': 1, 'stale_after': 1}`
   （`after` 不为 0 就是"没补救"的铁证），门禁 `--only consistency` → `VERDICT: RED（1 条未过）` 退出码 1。
   撤销注入 → p14 **10/10 ALL GREEN**、门禁 **ALL GREEN** 退出码 0。
2. **标题不含版本号**：`main_window.py` 改回写死 `"PDF 归档工具"`（去掉 `v{__version__}`）→
   `tests/integration/test_app_shell.py::test_窗口真实显示并列出全部导航项` **FAILED**，
   全量回归 **1 failed, 354 passed, 1 skipped in 54.44s**，门禁 `--only regression` →
   `VERDICT: RED（1 条未过）`（57.1s）。撤销后 18 条相关断言 3.31s 全绿。
   这条断言的来源与口径见 **ISSUES I30**（唯一存放处 = `__init__.py::__version__`）。

**报告写完之后的三场补跑**（上面那一场不含 `guards`，报告本身因此一直没有被机器验过在场性）：

```
        起跑负载：CPU 75.9%｜可用内存 3516MiB｜最吃内存进程 MemCompression 781MiB
        本次跑 3 段：guards + regression + docs-inject
  ── 段 guards（0.9s）       PASS ×6（G21 依赖守卫｜架构守卫｜四份文档在场 9/16/14/14KiB｜
                                   报告 19KiB 缺栏 无｜占位符命中 无｜四份都含"实测"）
  ── 段 regression（55.7s）  PASS  全量回归 355 passed / 0 failed / 0 error / 1 skipped
  ── 段 docs-inject（0.0s）  PASS  残缺报告 + TBD 文档：抓到 两条都变红
  合计判定 8 条｜本次未跑 7 段
VERDICT: ALL GREEN
```

```
        起跑负载：CPU 46.6%｜可用内存 2895MiB｜最吃内存进程 chrome.exe 712MiB
        本次跑 1 段：consistency
  ── 段 consistency（3.3s）  PASS ×3（p12 注入 17/17｜p14 ALL GREEN｜真实现场"本次未跑"）
  合计判定 3 条｜本次未跑 8 段
VERDICT: ALL GREEN
```

```
门禁运行于 H:\AI project\demo19｜python 3.11.7
        起跑负载：CPU 49.9%｜可用内存 3565MiB｜最吃内存进程 chrome.exe 624MiB
        本次跑 2 段：guards + docs-inject
  ── 段 guards（0.9s）       PASS ×6（G21 依赖守卫｜架构守卫｜四份文档在场 10/17/14/14KiB｜
                                   报告 25KiB 缺栏 无｜占位符命中 无｜四份都含"实测"）
  ── 段 docs-inject（0.0s）  PASS  残缺报告 + TBD 文档：抓到 两条都变红
  SKIP  未跑的段：×8（regression｜coldstart｜e2e｜injection｜ocr｜consistency｜soak｜package）
        —— 这一场的「全绿」不覆盖它们
  合计判定 7 条｜本次未跑 8 段
VERDICT: ALL GREEN
```

第三场跑在 **D-034 + ISSUES I36 落进台账、四份用户文档与 README 的读数全部改写、`.probe_work/` 里当场写的
5 个 `scratch_*.py` 与被后续读数取代的 13 份 log 删掉之后**，只验"文档这一层还在不在、门禁自己还有没有牙"，
`SKIP` 那 8 段是真没跑 —— 这一场没有 `regression`，所以**这一场的绿不覆盖代码**（代码自 05:01 那场之后没动过）。
上面这段抄自 `.probe_work/final_docs_1015c.log`。同一条判据在文档定稿前后**留档 5 场**（`final_docs_1015b…f.log`；此后每次改文档都可以再跑，判据与条数不变，不再逐场留档）：
b 打 `报告 24KiB`｜`guards 0.7s`，c/d/e 打 `报告 25KiB`｜`guards 0.9s`，f 打 `报告 25KiB`｜`guards 0.7s`；
五场的 `10/17/14/14KiB`｜`缺栏 无`｜`占位符命中 无`｜`合计判定 7 条｜本次未跑 8 段`｜`VERDICT: ALL GREEN` **一字不差**，
变的只有负载行和上面那两个随文档字节走的数字 —— 这类"抄录本身让被抄的读数过期"的自指与 **ISSUES I36** 同族：门禁的条数与体积读数只描述**跑它那一刻**的文档状态。

`consistency` 这一场是**必须补的**：那两场注入把 `index_service.py` / `main_window.py` / 三份探针
（`p12` / `p13` / `p14`）都动过又改回来，而 4.13 的八段链跑在 04:44:55，早于这些改动落定的时刻。
p14 单独跑一次的自报是 `合计 10 条｜红 0 条`（`.probe_work/p14_clean_1015.log`），其中新加的第 10 条：
`{'pages': 2, 'docs': 1, 'unindexed_before': 1, 'unindexed_after': 0, 'stale_before': 1, 'stale_after': 0}`
—— 产品入口报的数与探针独立 `census()` 数出来的数**同时**归零才算绿。
链外其余各段（`e2e` / `soak` 真跑 / `ocr` / `package`）在这之后的改动**只有 docstring 与注释**，
被 `regression` 那 355 条覆盖到了（`test_probe_sql_sensors.py` 会用 `ast` 重读这些文件），
没有重跑真机 OCR 与真打包 —— 这一场的 ALL GREEN **不覆盖**它们，上面三段输出里明写了"未跑 7 段 / 8 段 / 8 段"。

**这一场仍然测不到的**（不许被 16 条全绿盖过去）：
真实现场一致性没核（`%LOCALAPPDATA%\PdfArchiver` 在本机不存在，那一行明写"本次未跑"）
——【**2026-10-18 更正**，不改写上面这句原文：它是 2026-10-15 那一场的**本机状态**，而 2026-10-18 现读默认根
`C:\Users\lavie\AppData\Local\PdfArchiver` **在场**（`.probe_work/i87_else_branch.txt`）。
今天仍未跑的真实原因换成了另外两件：门禁不默认去碰真库（要显式 `--data-root`）+ 第一次带它就撞满 1800s
上限（`.probe_work/b1_1018_seg1_reallll.log`），那一档已提到 7300s（**ISSUES I87** / **I91**）】；
真实语料 7,768 份 / 202 万页**一份都没扫过**（**ISSUES I20**）；G2 搜索 P95、G3 首建 ≤6h、G8 1.2GB、
L4 ×10 档仍是**反算值**（**ISSUES I16**）；长跑只有分钟级（**ISSUES I32**）。


**提交之后，对"已提交的那棵树"再跑一次默认五段链**（`final_committed_1015.log`，那一场跑在代码与文档分 6 个提交落地之后，
作者身份走命令行 `-c user.name=… -c user.email=…` 传入，**不动 git config、不 push**）：

```
门禁运行于 H:\AI project\demo19｜python 3.11.7
        起跑负载：CPU 21.7%｜可用内存 4318MiB｜最吃内存进程 WorkBuddy.exe 533MiB
        本次跑 5 段：guards + regression + coldstart + e2e + consistency
  ── 段 guards（0.7s）       PASS ×6
  ── 段 regression（51.7s）  PASS  全量回归 355 passed / 0 failed / 0 error / 1 skipped
  ── 段 coldstart（1.1s）    PASS  G1 冷启动 0.497s｜进程总耗时 1.077s｜关窗对账 1 条
  ── 段 e2e（10.0s）         PASS ×2（后台生命周期 冷启动 0.573s｜11 条端到端｜带页码的命中 6 行）
  ── 段 consistency（3.0s）  PASS ×3（p12 注入 17/17｜p14 ALL GREEN｜真实现场"本次未跑"）
  合计判定 13 条｜本次未跑 4 段
VERDICT: ALL GREEN
```

这一段量的是**交付物本身**：跑在提交之后，跑完 `git status --short` 无输出（工作树干净）。
`injection / ocr / soak / package` 四段没在这一场重跑，它们的读数仍是 04:31–04:44 那场八段链的原文 ——
这一场的绿**不覆盖**那四段，输出末行的"本次未跑 4 段"就是这句话。**这一段自己也是一次文档改动**：
报告 §八 的 `docs` 行数与体积在把它写进去之后重数，并和它进同一个 commit，所以 §八 那行说的是
"含本段的这棵树"，不是上一版。

### 4.14 真实语料首扫实测（2026-10-16，`scripts/real_corpus_first_scan.py`）—— 第一次在 6.1GB 真库上跑，Q8 已答、禁令解除

**这是 §4.11/§4.13 里"真实语料一份都没扫过（ISSUES I20）"那句话被推翻的现场**（历史读数保留其自身时点，不改写）。

| 量 | 读数 | 口径 / 出处 |
| --- | --- | --- |
| 扫得 PDF 数 | **10,977 份 / 6 个监测根** | 取代 p0 的 7,768（那次未覆盖部分目录，以首扫现数为准） |
| 全量扫描相 | **31.3 分钟（1880.518s）** | 逐根 `scan_root`；哈希并入索引链路，故 **G4 [反算] 全量哈希 ≤1h 实质达成** |
| 索引排空相 | 等满上限，verdict **TIMEOUT（按设计，非失败）** | `index_drain` 上限内未排空，续跑见 `scripts/resume_indexing.py` |
| 库体积 | **6.1GB** `catalog.db` | `%LOCALAPPDATA%\PdfArchiver\data\catalog.db` |
| `text_pages` 行 | **1,071,379** | 正文入库行数 |
| 峰值 RSS | **469.6MB** | 首扫进程 |
| 扫描失败面 | **26 条全 `PermissionError`**（系统目录，符合排除逻辑） | **ISSUES I20 现在有真凭据**：长路径/权限面在真目录量过 |
| 索引终结失败 | **10 条 = 2 FileDataError + 5 加密 PDF + 3 无文本层扫描件** | **零代码 bug**，全为预期内文件状态 |
| 启动阻塞（连带发现） | `integrity_check` 在 6.1GB 库 **19h+ 未完**；`quick_check` 冷 **452.3s** / 热 **478.2s** | 判死；修法与守卫见 **ISSUES I45**；修复后 `bootstrap` **1.521s** |

**仍未测到（不许被本表盖过去）**：**G2 搜索 P95 ≤500ms** —— 本轮当时尚未跑（用户指令"等待索引完成后跑 G2"）；
**2026-10-17 队列排空后已跑完，判 RED**，读数与本节的关系见 **§4.15**。
G11/G12 watcher 压力、I32 小时级长跑仍待真监听场景补测。索引续跑实测有一条可复算观察：**排空速率先慢后快**
（冷文件缓存 ~5/min →  warmed 后 ~23/min+），属负载绑定读数，与 **ISSUES I25** 冷启动慢同一族成因。

---

### 4.15 G2 搜索 P95 真语料实测（2026-10-17，`scripts/g2_search_benchmark.py`）—— 第一次跑通就判 RED

**起跑现场**：真实数据根、真 `SearchService.search(Criteria(limit=200))` 入口、队列已排空（**ISSUES I46** 修完后 2.0 分钟排完）。
脚本此前从没成功跑过（第一次栽在 Windows 的 `sqlite3` URI 反斜杠上，`unable to open database file`；已改成 `DB.as_posix()`）。

| 量 | 读数 | 口径 / 出处 |
| --- | --- | --- |
| 库 | `documents` fts_done **10,906 / 10,980**、`text_pages` **1,972,578 行** | 脚本自己现数（§4.14 那次的 1,071,379 行是排空**前**的时点数） |
| 样本 | 20 查询 ×（1 次预热 + 5 次计时）= **100 个计时样本** | 服务自量的端到端 `took_ms`，含 bm25 排序 + snippet + 四通道合并 |
| 分位 | **P50 168ms / P95 2,809ms / P99 3,406ms / max 3,406ms** | 报告 `AppData\Local\PdfArchiver\logs\g2_benchmark.json`（`verdict: RED`） |
| 判定 | **RED**（基线 500ms，**未放宽、未改口径**） | **ISSUES I59** 等勾选。**2026-10-17 更新**：处置已定（甲+乙，**D-051**）并复跑，同一判据下 P95 328ms → **GREEN**，前后对照见 **§4.16** |
| 慢在谁 | **只有 `'发票'`**（med 2,994 / max 3,406）；**其余 19 条全部 ≤356ms**（`engineering` 356、`人工智能` 273、`quarterly report` 262） | 逐条读数在报告 `per_query` |
| 「1–2 字必然慢」 | **当场证伪**：四条两字查询 `北京` 197/207、`教育` 155/179、`法律` 182/196 都很快 | 同表 |

**机制（DB 级现测，只读连接 `file:…?mode=ro`）** —— 不是"表大了就慢"，是"要为凑满 200 条往表里走多深"：

```
EXPLAIN QUERY PLAN（LIKE 通道那条 SQL）
  SCAN tp USING INDEX ux_text_pages_doc_page          ← 按 (doc_id,page_no) 索引序走
  SEARCH d USING INTEGER PRIMARY KEY (rowid=?)        ← 凑满 LIMIT 200 即停
```

| 查询 | 第 200 行落在 | 扫过行数 = 全表占比 | LIMIT 200 耗时 |
| --- | --- | --- | --- |
| `发票` | `doc_id=3065` | **334,924 = 17.0%** | **2,676ms**（新连接 4 次 2,657 / 2,676 / 2,762 / 3,058；同连接热跑 2,511 / 2,608 / 2,614 / 2,698） |
| `北京` | `doc_id=192` | 11,903 = 0.6% | 104ms（新连接 4 次 94–104） |
| `教育` | `doc_id=46` | 7,159 = 0.4% | 50ms |
| `法律` | `doc_id=192` | 11,884 = 0.6% | 90ms |

- 词频侧证：全表只有 **874 行**正文含"发票"（为数这个那一条无索引 `SELECT COUNT(*) … LIKE` 跑了 **181,826ms**，顺带量到"没有索引序可借时全表扫是多少"）。起跑负载 CPU 21%、可用内存 3,775MiB。
- **撤回一条先前写下的推断**：p1 的 `LIKE 499ms@30万行 × 6.6 ≈ 3.3s` 与 2,994ms 数量级吻合，曾被当作本条的解释。本轮实测说明**吻合是巧合**——决定耗时的是第 200 条命中的位置，行数只是间接因素。`search/service.py:32` 那句按 499ms 反算 `CHANNEL_LIMIT=200` 的注释依据因此不成立，**当时只记不改**（改它等于动门禁反算链，等勾选）。
**2026-10-17 更新**：随 **D-051** 一起改掉 —— 注释现在写的是实测机制（"第 200 条命中的位置"），反算链换挂在 `LIKE_SCAN_ROWS` 上并按**最大量级**（1,972,578 行）重算。
- 一条离群读数如实保留：同一 SQL 在某次探针里量到 **12,458ms**，随后 8 次稳定在 2,511–3,058ms；那次探针紧跟在一次被我中途杀掉的 181s 全表扫描之后，**成因未验，不当结论用**。

**本表没盖住的**：G3 首建 ≤6h、L4 ×10 档、G5/G6、G7/G8/G16、G17/G18/G19 全部仍未实测；G2 这条**没有**做成 `gates/final.py` 的常驻段（真库绑定读数），入口是上面那支一次性脚本。

**逐字 stdout 留在哪**：`.probe_work/g2_1017.log`（本次跑的分位与 VERDICT 原文）与 `.probe_work/resume_drain_1017.log`（13 份排空那 2.0 分钟的回执）。
这两份**故意保留**、不按"临时文件清零"删 —— 机器产物 `AppData\Local\PdfArchiver\logs\` 会轮转（本会话刚刚亲眼看着一份 37MB 的 app.log 轮走，见 **ISSUES I46** 那条证据衰减），
而 `.probe_work/` 虽在 gitignore 在册却是承重的（**ISSUES I34** 的教训是"证据出处不许指向会被删的 scratch"，这两条既然不删就可以当出处）。

### 4.16 D-051 落地后复跑 G2：同一 20 条查询的前后对照（2026-10-17，`scripts/g2_search_benchmark.py --reps 5`）

同一条命令、同一库、同一 20 条查询、同一判据（**P95 ≤ 500ms，没放宽、没改口径**），差别只有实现：正文 LIKE 通道带上
`scan_budget=LIKE_SCAN_ROWS=60_000` 行的深度预算并在越界时自报未扫完（**D-051**）。

| 量 | 前（§4.15） | 后 | 出处 |
| --- | --- | --- | --- |
| P50 | 168ms | **135ms** | `.probe_work/g2_1017.log` / `.probe_work/g2_after_budget_B.log` |
| P95 | 2,809ms | **328ms** | 同上，判据两侧都是脚本自己算的 |
| P99 / max | 3,406ms | **332ms** | 同上 |
| 判定 | **RED** | **GREEN** | 两份日志末行 `VERDICT:` 原文 |
| 最差查询 | `'发票'` med 2,994 / max 3,406 | `'发票'` med **329** / max **332** | 同表 |
| `'发票'` 命中行数 | 200 | **169** | **这就是买这 8.5× 花的钱**，见下 |

**代价是召回，不是速度**：20 条里只有 `'发票'` 一条真的撞到预算，命中 200→169 行；其余 19 条行数一条没变
（`合同条款` 163、`环境影响评价` 16、`财务审计` 21、`quarterly report` 8、`施工组织设计` 7 —— 本来就是 FTS 通道，预算碰不到它们）。
耗时侧：`北京` 197→186、`教育` 155→134、`法律` 182→181、`engineering` 313→259，快的那点是加边界条件后扫描提前退出带来的，
**不作为收益主张**（四次读数内互有来回，属噪声量级）。

**为什么最终形态不是先写的那版**：窗口子查询 JOIN 回主表（"形状 A"）把 1–2 字查询拖到 **358ms**、浅查询一起变慢，
A/B 对照探针 `.probe_work/i59_budget_shape_probe.py` 当场把它否掉；改成"一次覆盖索引探查拿到边界 `doc_id` + 原单趟 SQL 加 `tp.doc_id <= 边界`"（"形状 B"，
探查本身 2.9ms）。这条**是实测改写的决定，不是设计时想到的**，记进 **D-051** 的理由。

**仍未盖住的**：G3 首建 ≤6h、L4 ×10 档、G5/G6、G7/G8/G16、G17/G18/G19 全部未实测；G2 到今天**还是**没做成 `gates/final.py` 的常驻段
（真库绑定读数），一次性脚本 means 这组数字不会自己复跑 —— 处置在 **任务 #89**（`--only g2`）。
`scan_budget` 是**行预算不是时间预算**，语料涨、机器换、SQLite 计划变都会让它漂移，所以这版 GREEN 的有效性依赖"每次都现量"而不是写在文档里的 328ms。

**2026-10-18 更正上面那段的最后一句**（不改写它，只标它哪一半已经过期）：`--only g2` 已落地。
现在 `g2` 在 `gates/final.py` 的 `SEGMENTS` 里（`--only g2` 与 `--all` 都会跑它），但**不在 `DEFAULT_ORDER`** 里
（默认链不跑它 —— 绑真库、且读数是负载绑定的，把它放进默认链会让"跑一遍全链"取决于那台机器当时在忙什么）。
所以"这组数字不会自己复跑"这句今天只对**默认链**成立，不再对整条门禁成立。


> ⚠️ **4.17 起已迁出**（2026-10-18，**ISSUES I71** 勾选**乙**）：从「勾选轮（三）收尾读数」开始的
> **逐轮收尾块**切进 `docs/VERIFICATION-RUNLOGS.md`，节号连续、内容逐字未动，只改在哪一份里。
> 本册此后只收阶段级读数；再往本册追加逐轮收尾块，等于回到那条 1,200 行的线上。

## 五 · 已验证的决策（可以直接依赖）

| # | 决策 | 证据 |
| --- | --- | --- |
| V1 | PySide6 6.8.3 + `PyMuPDF→QImage` 渲染主路径 | 2.1、4.4 |
| V2 | SQLite FTS5 用 **external-content 表**，WAL，每线程独立连接 | 4.2 |
| V3 | 中文全文：trigram 为主 + 1–2 字显式 LIKE 回退（bigram 作为候选备胎） | 4.2 |
| V4 | 文件身份 = `realpath` 归一 + `COLLATE NOCASE` 唯一索引 | 4.8 |
| V5 | 监测必须叠加"全量对账扫描"，且要自检监听根是否被改名/删除 | 4.5 |
| V6 | OCR/嵌入只走 **DirectML + CPU 双后端**，CUDA 不在任何路径上 | 2.3、4.6、4.7 |
| V7 | OCR 为**可选、显式点名触发**能力，**零自动触发**，不进自动索引流程；全量按 6,000 页/日折算 **≈169 天**（Q3 已于 2026-10-15 选定"只跑显式点名的"） | 4.6、4.12、`test_不点名就一条OCR任务都不排` |
| V8 | 语义嵌入 fp32 + DirectML（146.9 chunks/s，全量 7.6h），量化不用于提速 | 4.7 |
| V9 | 打包 `PyInstaller --onedir`，冻结后功能实测可用。**体积口径更正（2026-10-15）**：4.9 那个 **247.6MB** 是可行性探针用的临时 spec（不含 OCR 模型与 `.dist-info`）；产品级 `packaging/build.py` 实测 **392.2MiB**（4.13）。两个数量的不是同一件事，**对外引用体积只许引 392.2MiB** | 4.9（探针）、4.13（产品） |
| V10 | 量级基线 8,000 份 / 120GB / 200 万页；红线按 ×10 反算 | 4.1 |
| V11 | 迁移必须"先快照后动结构"，失败靠 `BEGIN IMMEDIATE` 回滚回到原样 | 4.10、`test_迁移中途失败回到原样` + 注入 ISSUES I7 |
| V12 | 主记录幂等写用 `INSERT … ON CONFLICT(path_key) DO UPDATE`，不用"先查后写" | 4.10、注入 ISSUES I8（多刷一个 `parse_status` 立刻变红） |
| V13 | 时间只有一个口径：库里 UTC unix 秒、日志 UTC ISO 带 `Z`、性能数字由进程自报 | D-021、D-022、注入 ISSUES I13/ISSUES I14/ISSUES I16/ISSUES I17 |
| V14 | `PySide6` 控件必须在 `QApplication` 存在之后构造 —— 否则**进程直接 abort（exit 127，无 traceback）** | 阶段 1 开发期实测；测试夹具因此统一依赖 `qapp` |
| V15 | OCR 限量用**两条**：单页超时（DML 30,000ms / CPU 165,000ms）+ 每日页预算 6,000 页 —— 不是"单页耗时预算 284ms" | D-028；4.12 三次实测 1,985–5,780ms；`test_单页耗时超过反算上限时那页不入库整份停下`、`test_跑到一半预算用满剩下的页留在待办`、注入 p10 |
| V16 | OCR 版本**按页存**，指纹含引擎/运行时/DPI 但**不含 provider** —— 换显卡不该让整库重跑 | D-029；`test_版本指纹里没有provider_换显卡不该让整库重跑`、`test_真引擎跑完第二次一页都不再推理`（4.12：新增推理 0 次） |
| V17 | OCR 文本与原生文本**同住 `text_pages`**，靠 `source_kind` 区分 → FTS 触发器、幽灵行守卫、片段与页码全部自动适用，**不给 OCR 单独建表也不单独建索引** | 4.12；`test_OCR文本进全文索引且标明出处`、`test_删掉OCR行全文索引不留幽灵行`、`test_索引重建把OCR文本一起重算` |
| V18 | 失败页**不写行**，`partial ≠ done`，出处标签必须区分"原生正文"与"OCR 识别（可能有错字）" | D-031；4.12 实测出处标签只有一组；`test_失败页不写行下次只补它`、`test_全部页失败才判failed部分成功绝不判done` |
| V19 | 交付验收**不新增判定口径**，只用一条分段链把各阶段既有门禁/探针编排起来；被 `--only` 跳过的段必须在输出里明写"本次未跑" | `gates/final.py` 头部三条设计约束；4.13 那一场的 `SKIP 未跑的段：guards` 就是这条的现场生效 |
| V20 | 长跑采样的口径 = **整棵进程树求和**（本机 venv 的 `python.exe` 是 launcher 壳，真解释器在子进程） | 4.13 soak 行（RSS 中位 83.4→83.8MiB）；坏读数一侧见 **ISSUES I29**（3.7MiB 那次）；由 `tests/integration/test_probe_sql_sensors.py` 两条守卫钉住 |
| V21 | 冻结产物的冷启动**比源码慢一个量级差**（1.109s vs 0.437s），但仍在 G1 的 1.5s **[约定]** 内 —— 打包后的首屏时限必须单独实测，不许拿源码读数代 | 4.13 两条读数（同一台机器同一场链） |

## 六 · 候选 / 未决（**不许当成已定事实**）

| # | 事项 | 状态 | 说明 |
| --- | --- | --- | --- |
| C1 | trigram vs 自写 bigram 最终选型 | **候选，待用户勾** | 两者都跑通；trigram 库小一半（6.91× vs 14.83×），bigram 短查询快（1.42ms vs 499ms）。取舍取决于用户更在意体积还是 2 字词命中速度 |
| C2 | OCR 范围策略 | **已定（2026-10-15，Q3 甲）** | 选 **1（只跑显式点名的）**，零自动触发；2 的"分层推进"没做也不许顺手做。3 的限额机制保留但只作用于点名之后的批量（每日 6,000 页）。详见 docs/RISKS · 2.2、**D-028**、V7/V15。**残留**：全库 169 天这件事没被消掉（**ISSUES I1**） |
| C3 | 向量存储方案（暴力扫 vs ANN） | **候选** | 404 万块 ×512 维 fp32 = 7.71GB；暴力 cosine 一遍是 2GB 级 IO。未做检索延迟实测 |
| C4 | 是否引入 QWebEngineView | **候选** | 可用、+32.7MB，但收益未定 |
| C5 | 语义评测集 | **未决** | p6 的 4 对相关/无关是我自造的；SPEC 要求的 20 条真实查询还没有 |
| C6 | 界面清单与线框 | **未决，现在同时阻塞阶段 3 与阶段 5 的三个 OCR 屏** | AGENTS.md 明令：线框未逐屏确认前禁止写界面代码。阶段 1 只交付了不含布局决策的运行时外壳（D-018），**A/B/A′ 一个都没画**；阶段 5 因此**只有服务层能力**，OCR 的点名/结果/预算三屏全部未动（**ISSUES I23**）。产品屏数、最小窗口宽度、导航分组方式全部还是你的决定 |
| C7 | 监控根目录与数据目录最终路径 | **未决** | p0 扫出的 6 个根里明显混有用户不想被索引的内容；阶段 1 的默认数据目录 `%LOCALAPPDATA%\PdfArchiver` 只是可用回落，不是你认可的落点（Q8） |
| C8 | 目标机 `LongPathsEnabled` | **未决** | 本机 =1 是现状不是前提；需安装时自检 + 引导 |
| C9 | `--onefile` 打包 | **未测** | 当前只验证 onedir |
| C10 | 16GB 内存下的并发上限 | **未压测** | 各组件 RSS 单点测了，组合起来没测 |
| C11 | **G1 的 1.5s 阈值与"offscreen 读数能不能代表真机"** | **未决** | 1.5s 是 **[约定]**；实测散布已扩到 **空载 0.344–1.639s、满载 3.129s**（2026-10-15 完整链两次：空载 0.767s 全绿、满载 3.129s 判红，满载那次当场取到 CPU 96.5% / 可用内存 2,199MiB 的配对读数 → **ISSUES I25 / D-033**），全部在 `QT_QPA_PLATFORM=offscreen` 下取，真实 windows 平台要加窗口合成与字体加载，只能等你在桌面上看一次（ISSUES I17，含过渡规矩） |
| C12 | 默认分类模板的形状 | **候选，待确认** | SPEC 3.3 的 14 项已按原文落成数据（`default_catalog.py`）。**标签一个没 seed** —— SPEC 没给清单，编就是假数据（D-020）。要不要给标签模板、给哪些，是你的决定 |
| C13 | **CPU 后端在"没有 GPU 的机器"上独立完成同一批 OCR** | **本机无法自证** | p5 验过 `text_identical`（同一批页 DML 与 CPU 逐字一致），但本轮所有门禁跑在有 DirectML 的机器上，**CPU 档永远走不到**；CPU 档目前只有 165,000ms 超时上限、串行锁与降级路径的断言。真机读数留给阶段 7 打包冒烟 |
| C14 | **OCR 文本的备份/恢复一致性** | **未做** | OCR 行是 **169 天**才算得出来的东西，现在住在还没有备份路径的库里（备份属阶段 4）。阶段 4 落地时验收口径是"备份包里 OCR 的**页数**与恢复后读数一致"，不是"文件存在就算成"（**ISSUES I22**） |

（更细的风险条目与验证方法在 `docs/RISKS.md`。）

---

## 七 · 怎么重跑

```bash
# 全部探针都可重复执行；产物落在 .probe_work/
python tests/probes/p0_corpus_census.py      # ~数分钟，只读扫描
python tests/probes/p1_fts5.py               # 30 万行，建 4 种表
python tests/probes/p2_pdf.py
QT_QPA_PLATFORM=offscreen python tests/probes/p3_ui_render.py
python tests/probes/p4_watchdog.py           # ~31s
python tests/probes/p5_ocr.py                # GPU 任务，跑的时候别并行
python tests/probes/p6_embedding.py
python tests/probes/p7_path_identity.py
python tests/probes/p8_packaging.py          # ~4.5 分钟构建
python tests/probes/p9_reverse_injection.py  # 阶段 1 起；实测 166s，46 条反向注入（在临时副本里做）

# 阶段 1 起：验收门禁一条命令（含上面 p9），末行必须 VERDICT: ALL GREEN
.venv/Scripts/python.exe gates/stage1.py
.venv/Scripts/python.exe gates/stage1.py --no-injection   # 快速复查（约 15 秒）

# 阶段 2 起：在 stage1 之上加「后台生命周期」与「e2e 真链路验收（打印真实搜索结果）」两步
.venv/Scripts/python.exe gates/stage2.py
.venv/Scripts/python.exe gates/stage2.py --no-injection   # 约 1 分钟，但「断言有约束力」这一步没被验证

# 阶段 5 起：再加三步（产品路径实测 / 每日页预算真停机 / 真引擎套件不许退化成 skip）
.venv/Scripts/python.exe gates/stage5.py                 # 空载实测 382s（含两条注入），末行 VERDICT: ALL GREEN
.venv/Scripts/python.exe gates/stage5.py --no-injection  # 141s；--quick 只跑阶段 5 三行
#   **跑之前看机器闲不闲**：门禁第一行现在自己打印 `起跑负载：CPU x%｜可用内存 xMiB｜最吃内存进程 …`。
#   G1/G2 的冷启动阈值是负载绑定的读数，满载时那两行必红（实测过，见 4.12 与 ISSUES I25）——
#   出现这种情况就空载重跑，**不许放宽阈值**，也不许拿空载那次绿来宣称"这次也过了"。
python tests/probes/p10_reverse_injection_ocr.py         # 实测 130s，45 条 OCR 反向注入
python tests/probes/p11_ocr_shipped.py                   # **要独占 GPU**；单次约 40s，性能读数每次现量
#   注意：p11 自带 --timeout 900（页预算/慢卡兜底），在"单命令 10 分钟就杀"的执行环境里
#   必须显式把命令 timeout 放到 600s 上限跑，否则只会看到三行引擎日志 —— stdout 是块缓冲，进程被杀就全丢。

# 真跑一次应用：起来、显示窗口、0.3 秒后自己关窗（--data-dir 指到空目录就是全新库）
.venv/Scripts/python.exe main.py --data-dir "<空目录>" --exit-after 0.3
```

依赖安装（含 2.1/2.2 的锁死）见 `requirements/`。

**读数在哪一册**：本册只收**阶段级**读数；`### 4.17` 起那些"每轮收尾追加一块"的**逐轮读数块**在
`docs/VERIFICATION-RUNLOGS.md`，两册共用同一条节号序列（切册口径与原因见 **ISSUES I71**）。
