# OCR · 配置、使用与故障处理

阶段 5 落的是**本地** OCR（RapidOCR + ONNX Runtime DirectML）。这一份是用户视角的操作手册；
架构与决策理由在 `docs/ARCHITECTURE.md` 三、`docs/DECISIONS.md` D-006 / D-028 / D-029 / D-030 / D-031 / D-032。

> **先说清一件事**：这一层**没有界面入口**。导航里的 OCR 项点开是"未实现说明页"（AGENTS.md 硬禁令：
> 线框未经逐屏确认不许写界面代码 → **ISSUES I23**）。能力全部在 `services/ocr_service.py`，
> 下面的"怎么用"给的是与服务层完全相同的调用路径 —— 它与 `gates/stage5.py` 里跑绿的三条实测是同一条码路，
> 不是设想出来的接口。

---

## 一 · 装与验

**装**：顺序不能省，`pip install -r requirements/ocr.txt` 单独跑会把纯 CPU 的 `onnxruntime` 拽进来，
而两个发行版往同一个包目录写 → `import onnxruntime` **段错误 exit 139**（不是报错，是捕不到的崩溃）。
逐条命令与原因写在 `requirements/ocr.txt` 末尾「装包陷阱」。

**验**（三步，从快到慢）：

| 命令 | 验什么 | 期望读数 |
| --- | --- | --- |
| `python -c "import onnxruntime as o; print(o.__version__, o.get_available_providers())"` | 依赖树没装错 | `1.20.1 ['DmlExecutionProvider', 'CPUExecutionProvider']` |
| `python -m pytest tests/integration/test_ocr_real_engine.py -q` | 真推理真的把图里的中文识别进索引并标明出处 | 4 条 **passed**，出现 `skipped` 就说明可选层没装上 |
| `python gates/stage5.py --quick` | 产品路径端到端 + 每日页预算真停机 + 真引擎套件不退化 | 末行 `VERDICT: ALL GREEN`，并现场打印耗时/内存/显卡/逐字命中率 |

没装可选层时应用**照常起**，OCR 层报"不可用"，扫描与索引不受影响。这条不是口头保证，是被断言钉着的：
`tests/integration/test_ocr_service.py::test_没装可选层时应用侧模块照样import得进来` 在**子进程**里把
`rapidocr_onnxruntime` 塞成 `None`，再 import `pdfarchiver.app` / `services.bootstrap` / `services.ocr_service`
（三个都必须成功），然后要求 `OcrEngine().ensure()` 抛出的 `OcrUnavailable` 原文里带着 `requirements/ocr.txt`。
用子进程是因为主进程已经 import 过真引擎，在这里断言等于自证。

---

## 二 · 配置项

启动时应用会把每项的「当前默认值 / 用户覆盖值 / 来源文件」打印出来并写进 `logs/app.log`；
禁止运行时改配置文件，改了要重启（AGENTS.md）。

| 项 | 默认 | 放哪 | 改它意味着什么 |
| --- | --- | --- | --- |
| `ocr_daily_page_budget` | **6,000 页/日** | `config/settings.json`（用户设置，D-019） | 6,000 是 **8 小时无人值守 ÷ 实测最慢可持续 4.193s/页** 反算出来的（D-028）。调小只是让它更早停；调大就是把 GPU 时间往外烧，全库 1,014,112 页按 6,000/日也要 **169 天** |
| `worker_threads` | **1**（ISSUES I46 甲，2026-10-16 由 2 改小） | 同上 | OCR 推理另有**引擎级串行锁**（D-008），两个 worker 同时领到 OCR 任务也只会有一个在推理；调它不会让 GPU 并行。写密集的 `index` 同理 —— SQLite 只有单一写者，多开只抢锁（本机 `AppData\Local\PdfArchiver\config\` 实测为空，无历史覆盖值） |
| 出图分辨率 `OCR_DPI` | **200**，写在 `parsing/pdf.py` | 代码，**不是设置** | 它进了版本指纹，改一格 = 整库判定过期 = 1,144 GPU 小时级别的重跑。要改必须重做实测（`test_出图分辨率钉在实测那一档` 会先红） |
| 单页超时 | DML **30,000ms** / CPU **165,000ms** | 代码 `ocr/budget.py` | = 该 provider 实测最慢单页 ×2。没实测过的 provider 自动取最宽档。超时那页**不入库**、整份停下 |
| 重试上限 | 3 次 | 队列 `WorkQueue.max_attempts` | 只对**瞬时故障**计数；永久故障（打不开、要口令、整本读不出字、`doc_id` 为空）一次定终态，不烧重试预算（D-026） |
| 收尾写重试 | 3 次 + 退避 `(1.0, 3.0)`s | 代码 `jobs/queue.py::FINISH_WRITE_ATTEMPTS`，**不是设置** | 与上一行**不是同一个口径**：上一行管"处理函数自己失败"（回队重跑整份），这一行只管"任务已跑完、只差把终态那一行 UPDATE 写进库时撞锁"（ISSUES I46 乙 / D-050）。最坏 `3×5s` 忙等 + `1+3s` 退避 ≈ **19s** `[约定]`，由守卫断言 ≤30s |

---

## 三 · 怎么用（当前的唯一路径）

### 3.1 点名几份来跑

```python
from pdfarchiver.services.bootstrap import bootstrap

ctx = bootstrap()                      # 不带参数 = 用系统本地应用数据目录
ids = [12, 13, 14]                     # documents.doc_id；界面没有列表页，先从库里查
receipt = ctx.ocr.request_ocr(ids)
print(receipt.describe())              # 点名 3 份｜该跑 1 份｜新增任务 1 条｜判定为不需要 OCR 2 份
queue = ctx.start_background()
queue.wait_until_idle(timeout=3600.0)
ctx.shutdown()
```

`request_ocr()` 只**排队**，不直接跑；跑的是后台 worker。回执的四类理由各指得出具体是哪几份：
库里没有这份主记录 / 没有可用的正文判定（先索引） / 判定为不需要 OCR / 已是当前引擎版本 / 今天的页预算已用满。
**没有"整库自动 OCR"这个入口**：`doc_id` 为空的任务直接判永久失败（D-006 · Q3 甲，注入 ISSUES I12 钉着）。

### 3.2 什么时候会（也应该）重跑

- **不会**重跑：同一引擎版本 + 同一 DPI 下已经落库的页。判据是**页级**的 `text_pages.ocr_version`（D-029）。
  换显卡、升级驱动、从 DML 降到 CPU **都不会**让整库过期 —— 版本串里故意不含 provider。
- **会**重跑：升级 `rapidocr-onnxruntime` / `onnxruntime`、或改了 DPI（版本串变了）；
  以及上一次**失败的那些页**（失败页一行都不写，下次只补它，D-031）。
- **强制重识别**：`ctx.ocr.request_ocr(ids, force=True)` 或直接 `ctx.ocr.ocr_document(doc_id, force=True)`。
  `force` 绕过"已是当前版本"，但**不绕过每日页预算** —— 限量是资源约束，不是幂等判据。
- **整库索引重建**：`ctx.indexer.rebuild_fts()`，返回 `{pages, docs, unindexed_before, unindexed_after,
  stale_before, stale_after}` 六个可核对的数 —— 后四个是 `check_fts_consistency()` 的两个方向
  （该进索引却没进的 / 索引里多出来的花名册行）在重建前后的读数。
  OCR 文本**不需要单独的重建入口**：它与原生正文住在同一张 `text_pages`，重算投影时一起进去，
  来源按行上的 `source_kind` 区分。

### 3.3 看结果

| 想知道 | 读哪 |
| --- | --- |
| 这份文档跑没跑完 | `documents.ocr_status`，五个值：`na / pending / done / partial / failed`。`partial` = 有失败页，**不许**读成"搜得全" |
| 这本书里有几页是 OCR 出来的 | `documents.ocr_pages_done`（计数，不参与任何状态判定） |
| 某页识别成了什么 | `text_pages` 里 `source_kind='ocr'` 的那行 `body`，带 `page_no` 与 `ocr_version` |
| 搜到的这句是 OCR 的还是原本的 | 检索结果的出处标签只有两种：**「原生正文」**与**「OCR 识别（可能有错字）」**（D-031） |
| 全库进度 | `ctx.status.snapshot()`：`ocr_by_status` 分组计数 + `ocr_pages`（库里已存 OCR 正文页数） |
| 今天还剩多少页预算 | `ctx.ocr.budget.describe()`，形如 `今日 OCR 已用 2 页 / 预算 2 页（剩 0 页，UTC 日 2026-10-14）` |
| 为什么停在半路 | 任务行的 `last_error`，例如 `跑到第 3 页之前今天的页预算用满（…），未识别的页留在待办里`（D-030） |

"今天"只有一个口径：**UTC 日**。预算行里带日期字段，换日自动归零，不需要任何定时任务（D-032）。

---

## 四 · 故障处理

先查唯一读数，再动手。症状相同的两件事，处置可能完全相反。

| 症状 | 唯一读数 | 原因 | 处置 |
| --- | --- | --- | --- |
| 一点 OCR 就说不可用 | `OcrUnavailable` 原文点名**缺哪个包、怎么装** | 可选层没装 / 装坏了 | 按 `requirements/ocr.txt` 的顺序重装；`pip check` 那条 `rapidocr-onnxruntime requires onnxruntime` 是**预期噪声**，不许"顺手修好"（ISSUES I3、D-002） |
| `import onnxruntime` 直接崩（exit 139） | 崩溃前无任何异常 | 两个 ORT 发行版共存 | 先卸两个再**只**装 `onnxruntime-directml==1.20.1`；常驻守卫 G21 |
| 某份 PDF 永远 `failed` | 任务行 `last_error` 写明 `needs_pass` / 打开失败 / 一页都没读出来 | 永久故障 | 不是 bug。加密件要口令的走"人工处理"，别指望重试；重试预算只给瞬时故障（D-026） |
| 一份书 `partial`，第 2 页起没动 | `last_error` 里点名是哪一页、哪种失败（出图 or 识别） | 单页失败被隔离了 | 再点一次名：只补失败页。整本不会因为一页坏掉而停在第 2 页（ISSUES I10 注入验证过） |
| 跑着跑着停了，任务 `cancelled` | `last_error` 是 `跑到第 N 页之前今天的页预算用满（…）` | 预算用满，**这是设计行为** | 明天自动恢复额度；要今天就跑完就调大 `ocr_daily_page_budget`（后果见 D-028 第 3 条） |
| 某页被"超时"停下 | `last_error` 带具体毫秒数 | 该页耗时 > 该 provider 的实测反算上限 | 上限是按**实测最慢 ×2** 定的，正常页不会误杀（`test_CPU降级按CPU的实测上限不误杀慢而正常的页`）。真有一类病态页就一直撞，说明该重做实测了，不是该放宽 |
| 关应用后重启，某份又跑了一遍 | 任务行留在 `running` → 下次启动 `recover()` 收回 `queued` | **退出打断 ≠ 用户取消**（D-030） | 正常。索引与 OCR 都可重入，页级幂等保证不会重复烧同一页 |
| GPU 占用看着不对 / 特别慢 | `gates/stage5.py` 现场打印的 `nvidia-smi` 前后行 | 本机有别的东西在用卡（实测跑前 util 100%） | 单页耗时 2,264–5,780ms 是同一台机器两次读数区间；×2 余量正是为此（D-028） |
| 显存回不来 | 进程 RSS/显存只降不回 | **推理一旦提交就收不回来**（ISSUES I21） | 不要试图"停线程"——那会漏 ~701MiB 显存。唯一干净出路是退出应用重启；已入库的页不丢 |
| 库坏了，OCR 文本没了 | `data/backups/pre-migration-*.db` 只有迁移前快照 | **备份/恢复属阶段 4，还没实现**（ISSUES I22） | 当前无解：重跑 = 169 天口径的量。在阶段 4 落地前，不要清空 `data\` 目录 |

日志位置：`<数据根>\logs\app.log`（轮转）、`crash.log`（未捕获异常 + 线程异常）、
`state.log`（一行一条 JSON 对账：`window.ready` / `background.started` / `shutdown`）。
时间戳唯一口径是 UTC ISO 带 `Z`（D-022）。

---

## 五 · 数据与隐私边界

- **样本代号**：阶段 5 的实测文档里出现的 **S1 / C1** 是真实语料的两本，不是编号索引。
  S1 = 抽出连续 6 页做产品路实测的**真无字扫描正文**样本；C1 = 整页图 + **隐形文本层**的**控制组**样本
  （它一页都不该推理，是"普通文字 PDF 不反复 OCR"那条验收的真语料证据）。
  代号 ↔ 真名的对应关系只写在 gitignored 的 `.probe_work/`（`p2_pdf_result.json` 的
  `kind == "scanned_image"` 候选 + `p0_corpus_census.json` 的目录），**入库的文档与探针里不出现真实文件名与真实目录名**
  —— 规则见 `docs/REPO-JOURNAL.md` R-003，收尾时 `git grep` 扫过。
- **不上传任何内容**：图像、文本、元数据全部留在本机；依赖里没有任何网络调用路径。
- OCR 文本与原生正文同表同索引（`text_pages`），按 B 档（事实上不可再生）应在阶段 4 纳入备份 —— 现在还没有（ISSUES I22）。
- 识别结果**永远**带出处标签，且 `partial` 与 `done` 是两个不同读数：不把未经验证的识别文字伪装成原始文本（SPEC 五）。
- 没有"置信度"这一列：p5 实测 RapidOCR 只给行文本，逐行分数**没被验证过能否横向比较**，
  存进库就等于把假指标写进事实层。

## 六 · 这一层明确不做

自动触发全库 OCR（D-006/Q3）、整本一次渲染再批量识别（内存红线）、把 OCR 与嵌入同时扔上显卡（D-008）、
运行中抢占单页推理（ISSUES I21）、OCR 结果编辑与"修正识别文字"的界面（SPEC 阶段 5 明令不做 PDF 编辑）。
