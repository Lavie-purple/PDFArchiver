# 安装说明（INSTALL）

面向第一次拿到这份东西的人。两条路线：**A 用打包好的 exe**（推荐给不使用代码的人）、
**B 从源码跑**（开发者 / 想改代码的人）。两条都在这台 Windows 10 上真跑过，跑过的证据写在
每节末尾；**没在这台机器上验过的事我直接写"未验证"**，不冒充。

口径先说清：本文里"验证过"= 有一条能重跑的命令 + 那一次的真实读数（日志原文或脚本输出），
不是"看起来应该没问题"。全量读数在 `docs/VERIFICATION.md` 与 `docs/stage-reports/`。

---

## 0. 先决定：数据放在哪（两条路线都要）

数据根目录按**三级顺序**解析（`src/pdfarchiver/config/paths.py`），高优先级覆盖低优先级，
**启动时一定把"当前值 + 来源"打进日志**，所以事后能查是哪一条生效：

| 顺序 | 来源 | 怎么写 |
| --- | --- | --- |
| 1 | 命令行参数 | `PdfArchiver.exe --data-dir "D:\我的档案\PdfArchiverData"` |
| 2 | 环境变量 | `set PDFARCHIVER_DATA_DIR=D:\我的档案\PdfArchiverData` |
| 3 | 系统默认 | `%LOCALAPPDATA%\PdfArchiver`（一般是 `C:\Users\<你>\AppData\Local\PdfArchiver`） |

数据根里面的固定布局（产品自己建，`AppPaths.mkdirs()`）：

```
<数据根>\
  config\settings.json          设置（第一次启动时不存在 = 全部用默认值，日志会写这一行）
  data\catalog.db               目录库：主记录 / 分类 / 正文 / 全文索引 / 队列，全在这一个文件
  data\backups\                 每次迁移前的自动快照 pre-migration-*.db
  data\cache\                   出图缓存
  logs\app.log  state.log  crash.log
```

**放哪合适**：库会随正文增长（`text_pages` 存整页文本）。真实量级按本项目语料外推
全文索引 **28–48GB**（ISSUES I2，还没最终定案），所以**别放系统盘**，放空间足够的那块盘。
`--data-dir` 指到那儿即可，程序不会把任何东西写到第二处。

---

## A. 用打包好的 exe

### A.1 拿到产物

在自己机器上打一份（需要 Python 环境与依赖，见 B.1）：

```bat
.venv\Scripts\python.exe packaging\build.py
```

产物在 `dist\PdfArchiver\`（onedir 目录，不是单文件 exe）。**构建当场有 8 条内容门禁**，
末行必须打印 `VERDICT: ALL GREEN`，否则不要拿去用 —— 它检查的是"该进包的东西真进了包"：

- 迁移脚本以 `.py` 形式进包且与源目录清单一模一样（漏了它 = 一张表也不建，双击直接崩）
- OCR 三个 `.onnx` 模型在包里
- `onnxruntime` 的推理 DLL（含 `DirectML.dll`）在包里
- 版本指纹要读的 `.dist-info` 发行包元数据在包里（漏了它 = OCR 层明明在包里却被判"没装 OCR"，
  这是本项目真实踩过并修掉的坑，ISSUES I26）
- 整包体积逐项对账

本机实测（2026-10-15）：整包 **392.2 MiB**，首次构建 **350.4s**（缓存后重打 **121.0s**），
构建报告 `.probe_work\packaging_build_report.json`。

### A.2 安装 = 复制

**没有安装程序，也不需要**。把整个 `PdfArchiver\` 目录复制过去（U 盘 / 共享盘 / 解压都行），
保持目录结构完整（`PdfArchiver.exe` 旁边必须有 `_internal\`）。

为什么必须整目录复制：PyInstaller onedir 的 exe 靠 `_internal\` 找 Python 运行时与数据文件。
只拷 exe 一个文件 = 双击没反应（窗口型程序没有控制台，报错不会显示在屏幕上，去看
`%LOCALAPPDATA%\PdfArchiver\logs\crash.log`）。

### A.3 第一次启动

```bat
PdfArchiver.exe
```

起来的判据（这些是**实测过**的，不是推测）：

```
数据根 <默认位置> 建出 config / data / logs / data\backups / data\cache
logs\state.log 事件序列：startup.begin → migration.applied → startup.done → window.ready
结构版本 = 8（2026-10-18 迁移链已到 0008；2026-10-17 到 0007；2026-10-15 冻结冒烟当时抓到的是 3），默认分类 = 14 个
logs\app.log 里有一行「设置来源：内置默认值（… settings.json 尚不存在）」
没有 crash.log
```

窗口型产物**没有控制台**，`print()` 是静默的 —— 所以一切核对都看 `logs\` 里的原文行，
不要指望屏幕上出现什么。想让它起来就自己关掉（脚本化验证用）：

```bat
PdfArchiver.exe --data-dir "%TEMP%\我的数据根" --exit-after 20
```

### A.4 这台机器之外验证到哪一步（**请如实看待这张表**）

| 事项 | 状态 | 证据 |
| --- | --- | --- |
| 复制到**仓库外**的临时目录后能起、能关、能建库 | ✅ 验证过 | `packaging/frozen_smoke.py` 全部 **29 行 PASS**，`VERDICT: ALL GREEN`，**139.7s**（交付链 package 段那一场） |
| 冻结态真扫描 273 份 PDF、抽正文、全文检索命中带页码 | ✅ 验证过 | 同上（`documents 273 / 磁盘 273`、正文 **304 行**、`text_pages − content_fts = 0`） |
| 冻结态真跑本地 OCR 并把识别文本进索引 | ✅ 验证过 | `app.log` 原文：`OCR 引擎就绪 provider=DmlExecutionProvider 耗时 1.66s`，识别出渲染进图片的那句话 |
| 重启后一切还在、不重抽正文；进程被强杀后队列自动回收 | ✅ 验证过 | 重启前后 `{documents:153→153, text_pages:304→304, schema_version:3→3}`；强杀后 `background.started.recovered = 2`，续跑完 0 未完成 |
| 一致性核查（文件 ↔ 库）在冻结现场全绿 | ✅ 验证过 | `tests/probes/p12_consistency.py --data-root <现场>` → 13 条全绿 0 未验 |
| **Windows 11 / 无 GPU / 干净虚拟机**上的启动 | ❌ **未验证** | 本机是 Windows 10 19045 + 有 DirectML 显卡。按 §A.5 的步骤在那台机器上跑一次并把读数抄回来 |
| **安装程序形态**（.msi / 开始菜单 / 卸载器） | ❌ **未实现** | 项目里没有这个话题的代码，只有目录复制 |
| 数字签名 / SmartScreen 提示 | ❌ 未做 | exe 未签名，首次运行会有 SmartScreen 拦一道，见 `docs/TROUBLESHOOTING.md` |

### A.5 换一台 Windows 机器怎么验（**照抄这几步就够**）

1. 复制 `PdfArchiver\` 整目录到目标机（不放系统盘也行，路径里有中文和空格都验过）。
2. 双击 `PdfArchiver.exe`。窗口出现 → 继续；没出现 → 直接看
   `%LOCALAPPDATA%\PdfArchiver\logs\crash.log`，把原文整段抄回来（不要转述）。
3. 命令行跑一次带自动退出的启动，确认能起也能关：
   `PdfArchiver.exe --data-dir "%TEMP%\p1" --exit-after 20` → 期望退出码 0，
   且 `%TEMP%\p1\logs\state.log` 里有 `window.ready` 和 `shutdown` 两行。
4. 想看这台机器上的 OCR 走没走 GPU：跑完一次识别后
   `findstr "OCR 引擎就绪" "%TEMP%\p1\logs\app.log"`，
   期望 `provider=DmlExecutionProvider`（DirectML 显卡）或 `provider=CPUExecutionProvider`（无 GPU 时
   应退回 CPU 且**照样能识别** —— 这一条正是"未验证"要验的东西）。
5. 有仓库的目标机上再跑 `python packaging\frozen_smoke.py --keep`，末行要 `VERDICT: ALL GREEN`。

---

## B. 从源码跑

### B.1 环境（版本是钉死的，不要改成 `>=`）

必需：Windows 10/11、**Python 3.11.7 x64**（本机就是它；`onnxruntime-directml 1.20.1` 与
`PySide6 6.8.3` 的可用性都按这一版实测过，换版本等于换未验证状态）。

```bat
py -3.11 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements\base.txt
.venv\Scripts\python.exe -m pip install -r requirements\dev.txt    :: 跑测试和门禁才需要
```

要扫描件检索能力，再加 OCR 可选层。**顺序很重要，不能只 `-r ocr.txt`**：
`rapidocr-onnxruntime` 声明依赖 `onnxruntime`，直接装会把纯 CPU 版拉进来，与本项目用的
`onnxruntime-directml` 共存后 `import onnxruntime` 是**段错误**（exit 139）而不是报错。

```bat
.venv\Scripts\python.exe -m pip install onnxruntime-directml==1.20.1
.venv\Scripts\python.exe -m pip install -r requirements\ocr.txt
```

装完确认（`pip check` 里**只允许**出现这一条错误，其余都是真坏了 —— 由依赖守卫 G21 断言，ISSUES I3）：

```
rapidocr-onnxruntime 1.4.4 requires onnxruntime, which is not installed.
```

`requirements/semantic.txt` 属于阶段 6（本地语义搜索与 AI 分类建议），**引擎层与服务层写路径都已接通产品**：
装了它才有嵌入模型可下载，`SemanticSearchService` / `AIClassifyService` 才起得来；向量库也有写入方了
—— `services/vector_service.py` 调 `VectorStore.add_batch/delete_by_doc`、把 `documents.vector_status`
从 `na` 推到 `done/failed/stale`、`"vector"` 任务真能入队并被 worker 调度（**ISSUES I63** 丙/丁 已落地，
按 **D-061** 只按用户显式点名触发）。但**界面上还没有"建向量"的入口**（没有按钮调 `request_vectors`），
所以只走 GUI 的用户机上 `vector_status` 仍停在 `na`，S1 的「语义搜索」勾选与「AI 推荐分类」按钮**在真界面上
都会走到空态提示**（"语义搜索无结果（向量库为空或模型不可用）" / "暂无向量数据…"），直到该入口落地或手工 enqueue。
不装则其余功能不受影响。

### B.2 跑起来

```bat
.venv\Scripts\python.exe main.py
```

### B.3 跑测试与门禁

```bat
set QT_QPA_PLATFORM=offscreen
.venv\Scripts\python.exe -m pytest tests -q            :: 全量回归，本机实测 355 passed / 0 failed / 1 skipped（两次独立读数 49.6s / 55.7s）
.venv\Scripts\python.exe gates\stage5.py               :: 阶段 5 全链门禁（含 OCR 真推理与反向注入）
.venv\Scripts\python.exe gates\final.py --list         :: 交付链共 9 段各是什么、实测耗时、默认跑哪五段
.venv\Scripts\python.exe tests\probes\p12_consistency.py --inject   :: 一致性探针自检，期望 17/17
```

**门禁阈值是负载绑定的**：G1/G2 那两条冷启动（≤1.5s）在机器忙的时候必判 RED，那不是产品坏了
（同一份代码空载 0.57s / 满载 3.13s，ISSUES I25）。跑门禁前先让机器空闲，脚本会打印一行
`起跑负载：CPU x%｜可用内存 xMiB`，读数要连着这行一起抄，否则不可比。

### B.4 OCR 模型文件在哪

不用下载、不用配置。`rapidocr-onnxruntime` 装进环境即带三个 `.onnx` 模型
（`ch_PP-OCRv4_det_infer` / `ch_PP-OCRv4_rec_infer` / `ch_ppocr_mobile_v2.0_cls_infer`），
打包时由 `.spec` 收进 `_internal\rapidocr_onnxruntime\models\`，冻结产物里已实测在位。
语义搜索要的嵌入模型才需要单独下载 —— 推理层已实现（阶段 6），向量库的写入方也接进了服务层
（`services/vector_service.py`，**ISSUES I63** 丙/丁 已落地、按 **D-061** 只按用户显式点名触发），
但界面上还没有"建向量"的入口，所以只走 GUI 时装上模型也仍是空态，要该入口落地或手工 enqueue 才建。
这一步现在只让 `main.py` 起得来、不报"模型不可用"。
