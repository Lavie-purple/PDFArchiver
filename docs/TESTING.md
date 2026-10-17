# 测试计划与验收门禁

本文件的每条阈值都标了来源：**[反算]** = 由实测单耗 × 真实量级推出来；**[约定]** = 我拍的，需要你确认。
不许出现"看起来合理"的数字。量级基线取实测 8,000 份 / 202 万页，压力档 ×10 取 80,000 份 / 2,020 万页。

---

## 一 · 测试分层

| 层 | 位置 | 跑什么 | 何时跑 |
| --- | --- | --- | --- |
| L0 探针（技术前提） | `tests/probes/p0..p14` | 独立可运行脚本，末尾打印 `VERDICT` | 换机器 / 换依赖版本 / 怀疑环境时 |
| L0b 断言自证 | `tests/probes/p9_reverse_injection.py` | 把 **46** 种坏法注进**临时副本**，逐条确认对应测试真会变红（1–18 阶段 1，19–46 阶段 2） | 每阶段收尾（已进 `gates/stage1.py` 与 `gates/stage2.py`） |
| L0b 断言自证（四份，**2026-10-18 起常驻门禁链**） | `tests/probes/p15_archive_ui_injection.py`／`p16_doc_pointers_injection.py`／`p17_handler_shape_injection.py`／`p18_irreversible_source_injection.py` | 同类坏法注入，守的是（四）（五）两轮新上架的断言：界面↔磁盘链路 **36** 条、文档指针守卫 **5** 条（含 1 条反向对照）、队列 handler 形状核对 **3** 条、`irreversible` 口径唯一 **3** 条 —— 合计 **47** 条。**判据本轮统一成一条**：红 **且** `FAILED` 行点名到该坏法登记的那条测试 —— 「红但不点名」（把断言改成崩溃）与「锚点今天落不进去」同等算漏。**R-012 已勾乙**：p16/p17/p18 进 `--only injection`（实测 **332s**），p15 单开 `--only ui-inject`（实测 **70s**）；p17/p18 的末行口径同时由 `ALL INJECTIONS CAUGHT` 改成门禁认的 `VERDICT: ALL GREEN`（进门禁链的入场券） | `gates/final.py --only injection`／`--only ui-inject`；锚点落不落得进去由 `tests/guards/test_probe_anchors.py` 秒级预检（**ISSUES I73**） |
| LG 守卫（结构规则） | `tests/guards/` | `test_dependency_pins.py`（G21）、`test_architecture.py`（AST 现 7 条：依赖方向 / SQL 位置 / 静默吞异常 / 本机路径字面量 / 导航分组 / 语义层模型根单源 / **界面不许自己拼时间串**）、`test_migrations.py`（旧库带数据升级不丢行）、`test_file_size.py`（**AGENTS.md 那条"单文件超 800 行就拆"的断言**：`.py` ≤800 / `.md` ≤1,200，两条口径的出处与拆法见 **D-054** 与 `docs/REPO-JOURNAL.md` R-010）、`test_schema_columns.py`（**ISSUES I62** 甲+丁，定案 **D-055**：A 列级双向对账 —— 文档声明的列 ⇄ `table_info` 实际列；B 迁移目录外不许 DDL，唯一例外按语句放行 `migrate.py` 那条 `SCHEMA_TABLE`。坏法注入 13/13 达标）、`test_test_hygiene.py`（AST 扫 `tests/` 整棵树禁同名 `def test_` —— 定义同名会把前一条**静默遮蔽**，本轮就是靠它逮到两条）、`test_doc_pointers.py`（**ISSUES I70**，2026-10-17 上架：文档里的四类引用也是断言 —— 决策编号 `D-<n>` / 台账行号 `ISSUES I<n>` / `某文档 §n` 节号 / **活文档**引用的 `test_*` 函数名；带日期的台账类文档在第四类上豁免，但旧名条数钉死在 `LEDGER_STALE_CAP`，超一条就红。四类 + 上限各配一条坏法、另配一条"台账写旧名必须仍绿"的反向对照，见 `tests/probes/p16_doc_pointers_injection.py`）、`test_probe_anchors.py`（**ISSUES I73**，2026-10-18 上架：把六份反向注入探针表里的 **133** 条坏法锚点在各自目标文件里逐条数一遍，要求**恰好命中 1 次** —— 锚点漂移原先要等整段 332s 的门禁跑到 p10 才报 RED，现在不到 1s 就红；顺带钉「探针与其注入目标不许混用 CR CR LF 行尾」，因为 `test_file_size.py` 的 `splitlines()` 会把那种文件数成两倍行数） | 每次改动；架构守卫可独立跑并打印 `VERDICT` |
| L1 单元 | `tests/unit/` | 纯函数：路径归一、分词预切、文件名解析、规则引擎、体积/耗时预算计算。**阶段 1 已有**：路径解析、设置校验、文件身份、迁移发现 | 每次改动 |
| L2 集成 | `tests/integration/` | 真实 SQLite（临时文件，**不 mock**）：建表 + 触发器 + FTS 一致性 + 迁移。**阶段 1**：装配与迁移、仓储层、异常处理、应用外壳（真 Qt 控件）。**阶段 2 新增**：`test_scan_service.py` 34、`test_job_queue.py` 27、`test_index_service.py` 23、`test_search_service.py` 20、`test_status_tasks.py` 16、`test_watcher_events.py` 10 | 每次改动 |
| L3 端到端 | `tests/e2e/test_stage2_acceptance.py`（11 条） | **只走真链路**：`bootstrap()` + `start_background()` + 真 `WindowsApiObserver` + 真 worker，然后只做磁盘动作（落盘 / 改内容 / 改名 / 删除 / 重开进程），**全程不手调 `scan_root` / `index_document`**。语料在 `tmp_path` 现造：真扫描件（只有图没有字）、真截断 PDF、真 AES-256 加密件、重叠根、非 PDF 文件。归档与撤销要到阶段 4 才接进这条链 | 每阶段收尾（已进 `gates/stage2.py`） |
| L4 量级压测 | `tests/load/` | 合成 N 份 PDF 灌进管线，测吞吐/体积/内存曲线 | 阶段 2、阶段 7 |
| L5 冻结冒烟 | `tests/probes/p8_packaging.py` | 打包产物里真实跑 PDF/FTS5/ORT/Qt | 发布前 |

约定：
- **禁止 mock 数据库**。L2/L3 一律用真实 SQLite；理由见 `00-阶段0验证结论.md` 4.2 —— 本项目最容易出的错（幽灵行、
  `unicode61` 零命中、`'delete'` 少带一列导致静默不一致）在 mock 里永远测不出来。
- UI 测试用 `pytest-qt` + `QT_QPA_PLATFORM=offscreen`，**不打扰用户桌面**。
- 每个探针/测试产物写 UTF-8 JSON 到 `.probe_work/` 或 `tests/_out/`，两者都已 gitignore。
- Windows 控制台一律 `sys.stdout.reconfigure(encoding="utf-8", errors="replace")`，否则中文断言输出不可读。
- **`subprocess` 的收发都要显式 `encoding="utf-8", errors="replace"`**（本机控制台默认 GBK）：
  子进程回显的是中文报错原文，用默认编码解码会在测试里抛 `UnicodeDecodeError`，把"应用启动失败"这个真现场销毁。
- 测试的数据目录一律是 `tmp_path` 下的临时目录，**不读也不写 `%LOCALAPPDATA%`** —— 阶段 1 验收第 6 条
  （不依赖开发者机器的固定绝对路径）就是靠"所有断言都在临时目录里成立"来证的，不是靠搜代码里没有 `H:\` 来证的。

---

## 二 · 硬门禁表（红线）

| # | 断言（可计数） | 阈值 | 来源 | 阶段 |
| --- | --- | --- | --- | --- |
| G1 | 冷启动到首屏可交互 | ≤ **1.5s** | **[约定]** 待你确认。阶段 1 共 **18 次读数 0.344–1.031s**（门禁入口 13 次 0.409–0.910s、中位 0.486s），**均为 `offscreen` 平台，真机未测 → ISSUES I17**；分散成因未查明，两条已被撤回的错误解释记在 `VERIFICATION` 4.10。口径：由进程自己写进 `state.log` 的 `window.ready.cold_start_seconds`，门禁与界面读同一条（D-021） | 1 |
| G2 | 搜索 P95 端到端（含 bm25 排序 + snippet，返回 200 条候选） | 基线 ≤ **500ms**；×10 ≤ **1.5s** | **[反算]** p1 实测 `bm25_top50=134ms@30万行`；线性外推到 202 万行 ≈ 900ms → **说明基线也可能顶不住，必须先做 L4 实测定分片策略**。**2026-10-17 真语料实测：P95 = 2,809ms → 判 RED**（阈值没放宽，见 **ISSUES I59**；读数表见 `docs/VERIFICATION.md` §4.15）。顺带证伪了这条外推本身：19/20 条查询 ≤356ms，慢的只有 1–2 字 LIKE 通道里"词太稀、要往表里走很深"的那一条。**同日处置落地后（甲+乙，见 D-051）同一 20 条查询复跑：P50 135 / P95 328 / max 332ms → GREEN**，阈值与判据一字未动，代价是撞预算的那条 LIKE 查询召回 200→169 行且**结果自报"未扫完"**；前后对照见 §4.16。**这条 GREEN 不会自己复跑** —— G2 至今不是 `gates/final.py` 的常驻段（**ISSUES I59** 残留项，处置是任务 #89） | 2 |
| G3 | 首建全量文本索引总耗时 | ≤ **6h**（实测投影 3.80h） | **[反算]** p2 抽取中位 **147.9 页/s** × 202 万页 | 2 |
| G4 | 全量哈希一遍 | ≤ **1h**（实测投影 9–39min） | **[反算]** p2 sha256 中位 240MB/s、最差 54.8MB/s × 120.6GB | 3 |
| G5 | 单页渲染（150dpi） | 中位 ≤ **400ms**（实测 135.1ms，留 3× 余量给大页） | **[反算]** p2 均值 286.8ms 已接近，最差页必须实测 | 2 |
| G6 | **禁止全量预渲染** | 任何"把所有页都渲一遍存起来"的路径必须被断言拒掉 | p2/p0：202 万页 ×135ms = **75.9h**，缓存体积按 846KB/页 ≈ **1.7TB** | 2 |
| G7 | 单 worker 处理完一个文件后的 RSS 回落 | delta ≤ **100MB**（实测最大 68.2MB，中位 6.75MB） | **[反算]** p2 `rss_delta_mb_after_close` | 2 |
| G8 | 进程总 RSS | ≤ **1.2GB**（UI+索引+一个后台任务同时活） | **[反算]** p3 空 UI 139MB + p5 OCR RSS +336MB + p2 worker 68MB + 余量 | 2 |
| G9 | GPU 任务并发数 | **同一时刻 ≤ 1**（OCR 与嵌入不得并行） | **[反算]** p5：空闲 1369MiB，OCR 单进程吃 701MiB 后剩 668MiB | 2 |
| G10 | FTS 与主表一致性 | **三个方向**同时干净：`check_fts_consistency()` 的 `unindexed` = 0 且 `stale_docsize` = 0，并且带词 `MATCH` 命中数 = `MATCH` 再 JOIN 主表后的命中数 | **[反算]** p1 已证明漏列**不报错只留幽灵**；五种口径对四种坏法的可见性由 `tests/probes/p14_fts_instrument.py` 每次重测。**旧写法 `SELECT count(*) FROM docs_fts WHERE rowid NOT IN (SELECT id FROM documents)` 是错的**（表名不存在，且外部内容表上这类**免词**计数恒等于正文行数、永远不会变红），2026-10-15 作废，见 ISSUES I8 | 2 起每阶段 |
| G11 | 监测批量事件丢失率 | = **0**（300 文件批量） | p4 实测 302/300 | 3 |
| G12 | 监测根被改名/删除后的自愈 | ≤ **60s** 内自检并上报 | **[约定]** p4 证明事件流完全看不见（0 事件），必须有外部看门狗 | 3 |
| G13 | **作废重定（2026-10-15，D-028，你勾选 甲）** —— 原来的"单页耗时预算 284ms/页"已被证伪（实测差 11.6×，且那假设本身不成立）。换成两条：① **单页超时** DML **30,000ms** / CPU **165,000ms**，超时那页不入库、整份停下；② **每日页预算 6,000 页/日**，跑满即停且进度可见 | **[反算]** ①= p5 该档实测**最慢单页 ×2**（14,072 / 80,291ms）向上取整到 5s 格，未实测的 provider 取最宽档；②= 8h 无人值守 ÷ 实测**最慢可持续** 4.193s/页 ≈ 6,868 → 千位向下取整。两条反算关系由 `tests/unit/test_ocr_limits.py` 断言，改数必须同时改实测出处 | 5 |
| G14 | 查询向量生成 | ≤ **50ms/条**（实测 108.9ms/16 条 = 6.8ms/条） | **[反算]** p6 fp32+DML | 6 |
| G15 | 语义召回 Recall@10 | 需你先给 **20 条真实查询-期望文档** 才能建此门禁 | 未定 —— p6 只有我自造的 8 对 | 6 |
| G16 | 全文索引体积上限 | ≤ **?GB** —— **必须先由你拍板**，见下第三节 | **[反算]** 外推 28–48GB | 2 |
| G17 | 文件操作崩溃恢复 | 杀掉进程后重启，`file_operations` 里每条 `pending/copying/…` 状态都能被恢复矩阵归类，**未知状态数 = 0** | docs/DATABASE 状态机 | 4 |
| G18 | 撤销正确性 | 归档→撤销后，源路径存在、字节数一致、sha256 一致，**且目标已消失** | SPEC 阶段 4 | 4 |
| G19 | 跨盘移动绝不先删源 | 断言"删源之前目标校验必须已通过"，用注入故障证明它会红 | docs/DATABASE 状态机 | 4 |
| G20 | 打包冒烟 | exe 退出码 0 且 `pymupdf/fts5_trigram/onnxruntime/qt` 四项全非空 | p8 实测全绿 | 7 |
| G21 | 依赖守卫 | `onnxruntime`（非 directml）出现在依赖树 → **直接失败**；PySide6 ≠ 6.8.x → **直接失败**；ORT > 1.20.x → **直接失败** | 2.1/2.2（装错不是报错，是段错误 exit 139） | 全程 |

### 阶段 2 收工时（2026-10-14）这张表的真实状态

**只有两条从"反算"变成了"实测"，其余全部仍是反算。** 因为真实语料一次都没扫过（Q8 未答）：

| 门禁 | 状态 | 说明 |
| --- | --- | --- |
| G10 幽灵行 = 0 | ✅ **已进门禁常驻** | 迁移侧（`tests/guards/test_migrations.py`）与运行侧（`test_index_service.py`）都断言；p1 已证明漏列**不报错**，所以只能靠断言。**2026-10-15 更正**：这一行当时挂着的还有一条**永远不会变红**的免词计数（ISSUES I8），判据已换成上表 G10 那三个方向，可重跑的出处是 `tests/probes/p14_fts_instrument.py` |
| G1 冷启动 | ✅ 本阶段门禁 2 次读数 **0.455s / 0.464s** | 仍全部 `offscreen`（ISSUES I17）；阈值 1.5s 是 **[约定]**，等你真机核对后重定 |
| G11 批量事件丢失率 = 0 | ⚠ **部分** | p4 的 302/300 是探针自己发的量；本阶段 e2e 只覆盖"单个文件落盘 → 自己变成可搜"，另有 `test_取消监听之后那个根不再交来事件` 覆盖退订。**批量事件在生产的 EventBuffer 上没测过** |
| G12 根消失自愈 ≤60s | ⚠ **机制在、数字没量** | `test_根目录不存在时不判缺失也不崩` + 慢路周期校验已落地；≤60s 是 **[约定]**，要在真机开一次才成立 |
| G2 / G3 / G4 / G7 / G8 / G16 | ❌ **未实测** | e2e 里那 0–4ms 是 5 份小语料的单次读数，**不构成 P95**；量级数字全部记 **ISSUES I16 / ISSUES I20**。**2026-10-17 更正其中 G2 一项**：真语料排空后已实测，**P95 2,809ms → RED**（**ISSUES I59**），同日处置落地后复跑 **328ms → GREEN**（§4.16），其余五条照旧未实测 |
| G5 / G6（渲染、禁止全量预渲染） | ❌ **还没有被测对象** | 阅读器是阶段 3 的事，本阶段一行渲染代码都没写 |
| G9 / G13 / G14 / G15 | — 不属于本阶段 | OCR 与语义按 D-006 / D-014 留在阶段 5 / 6 |

### 阶段 5 收工时（2026-10-15）这张表的真实状态

G13 已按 D-028 作废重定，下面只列**这一步真量到的数**。三次独立运行（同一台机器、同一份真语料样本
**S1**：一本扫描书第 217 页起 6 页、原生文本层 0 字；代号对应真名见 `docs/OCR.md` 的说明，**不入库**），
全部由 `gates/stage5.py` 现场打印，
没有任何数字从上一次结果里抄。最后一次是**完整链**（stage1 三条 + stage2 两条 + stage5 三条 + 全量回归 +
两条反向注入探针），墙钟 **382s**（01:27:47 → 01:34:09，exit 0，`VERDICT: ALL GREEN`）。
**这条链 21 分钟后在同一条命令上判了 RED（3 条），三条全是 G1/G2 的冷启动读数**（01:55 起跑时 CPU 96.5%、
可用内存 2,199MiB，显卡跑前 util 已 97%）—— 原始输出与配对读数在 `docs/VERIFICATION.md` 4.12，台账 **ISSUES I25**。
**因此有一条现在不能说**：上面那次 ALL GREEN 的 382s 里**还没有**新增的那条可选层断言；
含它的完整链要等机器空载时再跑一次才算数。

| 门禁 | 状态 | 实测读数 |
| --- | --- | --- |
| G13-① 单页超时 | ✅ **机制已验，数没被顶到** | 单页推理 **1,985.2–5,780.0ms**（6 页 × 三次；三次的 min/均值/max 依次为 1985.2/2281.5/2835.0、2264.3/2639.2/3269.5、2357.3/3577.7/5780.0）—— 距 DML 档 30,000ms 上限最差只差 5.2×；上限由 `test_单页耗时超过反算上限时那页不入库整份停下` 用注入慢页真触发过。整本墙钟（含出图与落库）**14.72s = 2,453.3ms/页**，队列收尾 0.154s。**第四次读数是满载机器**（01:55，CPU 96.5%）：单页 2,565.7 / 2,846.9 / 3,379.1ms、整本墙钟 18.42s（3,070.0ms/页）—— 仍离上限 8.9×，但说明**耗时读数只能在同负载下比较** |
| G13-② 每日页预算 | ✅ **真停过机** | 门禁把预算给死 2 页 → 真引擎推理 2 页（墙钟 2.04s = 1,018ms/页）后停在第 3 页，任务 `cancelled`、文档 `partial`、库里 2 行、待办剩 `[3, 4]`、`attempts=1`（没被重试吃掉预算）；停机原因原话进 `last_error`：「跑到第 3 页之前今天的页预算用满（今日 OCR 已用 2 页 / 预算 2 页（剩 0 页，UTC 日 2026-10-14））」 |
| G8 进程总 RSS ≤1.2GB | ⚠ **三次真机读数：峰值 806–1,131MiB** | 启动态 72.2–72.4MiB → 跑完 457–822MiB；完整链这次峰值 **894.0MiB**（比启动态 +821.8MiB）。峰值由 0.05s 采样线程采集。**注意这只有单 worker**：OCR 推理串行（D-008）是它不翻倍的原因，两本并行必炸 |
| G9 GPU 并发 ≤1 | ✅ 引擎锁 | `test_多线程推理同一时刻只有一个在跑`；跑前 `nvidia-smi` util **100%**（本机另有程序在用卡）→ 这正是 D-028 用 ×2 余量而不是 1.2× 的原因 |
| 显存实际占用（需求原文"记录 GPU 使用情况"） | ✅ 有读数，**没有断言** | 完整链这次（同一张 GTX 1060）：跑前 free **1,983MiB** / used 4,047MiB / util 99% → 跑后 free **651MiB** / used 5,379MiB / util 98% —— 一轮 6 页 OCR 把可用显存压掉 **1,332MiB**。探针同时打印自己的 caveat：DirectML 落在哪个适配器没有公开查询接口，这是 `nvidia-smi` 问到的那张卡 |
| G10 FTS 一致性 | ✅ 每阶段常驻 | P11 实测 OCR 文本与花名册对得齐：`unindexed=0`、`stale_docsize=0`、`pages=indexed`（OCR 正文走同一张外部内容表）。**2026-10-15 更正**：这一行原先写的是「P11 实测 `ghost_rows = 0`」，那个字段出自已被作废的瞎口径（ISSUES I8），读数名随 `check_fts_consistency()` 一起换了 |
| 识别质量 | ✅ **只有合成页能报百分比** | 有标准答案的那 1 页：逐字命中 **12/12（1.0）**、行均相似度 **1.0**、单页 971.1–1,190ms（三次）。真实语料那 6 页**没有人工转写**，只报结构：每页 586–963 字、30–47 行，且每页取出的 6 字连续中文词都能搜回原页 |
| 追溯 / 出处 | ✅ | 6 个取自识别正文的词全部命中预期页；出处标签只有一组 `['OCR 识别（可能有错字）']` —— 没有一条被说成"原生正文" |
| 幂等（不重复处理未变化的文件） | ✅ | 第二次点名回执"该跑 0 份｜新增任务 0 条｜已是当前引擎版本 1 份"，**新增推理 0 次** |
| 控制组（整页图 + 隐形字层） | ✅ **零推理** | 真语料控制组 **C1** 抽 6 页：字层 2,833 字已在正文索引里 → `inferences_added = 0`。真语料读不到时探针**自己合成**同一批字（`render_mode=3` 隐形层），这条不许退化成 skipped |
| G2 / G3 / G16 等 | ❌ **阶段 5 那轮仍未实测** | 阶段 5 没碰这些口径；量级数字照旧记在 ISSUES I16 / ISSUES I20。（G2 已于 2026-10-17 实测判 **RED**，见 **ISSUES I59**；这一行保留的是阶段 5 当时的口径） |

**这一轮新增的自动化**：`tests/unit/test_ocr_{engine,idempotency,limits}.py`、
`tests/integration/test_ocr_{service,budget,real_engine}.py`、`tests/probes/p10_reverse_injection_ocr.py`
（**45 条**反向注入，抓到 45/45）、`tests/probes/p11_ocr_shipped.py`、`gates/stage5.py`；
OCR 断言合计 **92 条**（六个文件 18/22/6/34/8/4，`--collect-only` 逐文件数出来的），
全量回归 **351 收集**（guards 15｜unit 88｜integration 237｜e2e 11；阶段 2 收工时是 327）。
其中最后 1 条是收尾时补的：`test_没装可选层时应用侧模块照样import得进来` —— 它把
`rapidocr_onnxruntime` 在**子进程**里塞成 `None`，要求应用侧三个模块照样 import 进来、
且 `OcrEngine().ensure()` 抛的 `OcrUnavailable` 原文里带着 `requirements/ocr.txt`。
补它的起因是 `docs/OCR.md` 里引用了一条**根本不存在的测试名**，而那条声明本身是对的
（此前口头保证，没有断言）。坏法自证：往 `ocr/engine.py` 加一行模块级 `from rapidocr_onnxruntime import RapidOCR`
→ 这条立刻 **FAILED**，撤掉后恢复绿 —— 它抓得住真退化。
满载下把负载绑定的那条 `test_进程级冷启动实测符合G1约定` deselect 掉再跑：**349 passed / 1 skipped / 1 deselected in 105.20s**，
这是"其余 350 条与机器负载无关"的读数。
完整链一条命令跑法：`.venv/Scripts/python.exe gates/stage5.py`（空载 **382s**，末行 `VERDICT: ALL GREEN`；
起跑第一行自己打印 `起跑负载：CPU x%｜可用内存 xMiB｜最吃内存进程 …`，满载时 G1/G2 必红 —— 见 **ISSUES I25**）；
`--quick` 只跑阶段 5 三行、`--no-injection` 跳过两条注入探针（141s）。

### 最终交付收工时（2026-10-15 04:31 → 05:05）这张表的真实状态

**上面那句"含新增断言的完整链还欠一次空载 ALL GREEN"已销账**：`gates/final.py` 那一场八段链起跑负载
**CPU 14.1%｜可用内存 5,145MiB**，`合计判定 16 条｜VERDICT: ALL GREEN`（退出码 0），
其中 `regression` 段 **355 passed / 0 failed / 0 error / 1 skipped** —— 那 355 条含阶段 5 收尾补的可选层断言、
含本轮新增的 `test_probe_sql_sensors.py` 两条。逐字输出在 `docs/VERIFICATION.md` 4.13。
阈值**一格没放宽**，所以这条销账是"重跑拿到绿"，不是"改判据让它看起来绿"。

| 这一轮新增的判据 | 落在哪 | 现在能不能常驻 |
| --- | --- | --- |
| 交付文档在场性（四份用户文档 + 报告五分栏 + 无占位符 + 每份引用当次实测） | `gates/final.py::gate_docs()`，在 `guards` 段里 | ✅ 常驻，且 `docs-inject` 那条证明它会被残缺报告与 `TBD` 文档打红 |
| 盘 ↔ 库一致性十三条（C0–C12） | `tests/probes/p12_consistency.py`，`consistency` 段 | ✅ 常驻（17 条坏法自检全过）；**对真实数据根那行仍明写"本次未跑"**，因为默认数据根在本机不存在 —— 不许读成"真实现场已核" |
| 长跑九条（S1–S9，进程树采样） | `tests/probes/p13_soak.py`，`soak` 段 | ⚠ 常驻但**证据有界**：`--minutes` 默认 4 分钟，且 S6 那次排空 0.0s —— **ISSUES I32** OPEN |
| G10 那几种口径谁能看见哪一种坏法（10 条） | `tests/probes/p14_fts_instrument.py`，`consistency` 段 | ✅ 常驻；⑤ 与第 10 条现在走**产品入口** `IndexService.rebuild_fts()`，摘掉补救会红（**ISSUES I33**） |
| 探针自己的 SQL 传感器与产品口径对齐 | `tests/integration/test_probe_sql_sensors.py`（2 条，进 `regression`） | ✅ 常驻（静态 `ast` 核对 + 一条等式） |
| 冻结产物内容与干净目录冒烟 | `packaging/build.py` + `packaging/frozen_smoke.py`，`package` 段 | ⚠ 在链里，但要 `--only package` 点名（**约 255s**），默认段不含它 |
| G2 搜索 P95 ≤500ms、G3 首建 ≤6h、L4 ×10 档 | —— | ❌ **不在最终链里**：这一轮当时没有新增任何这类读数（**ISSUES I16** / **ISSUES I20**）。**2026-10-17 G2 单独实测判 RED**，入口是一次性脚本 `scripts/g2_search_benchmark.py`（真库绑定读数，**没有**做成 `gates/final.py` 的常驻段），读数见 `docs/VERIFICATION.md` §4.15、处置等勾选见 **ISSUES I59**；G3 与 L4 ×10 照旧未实测 |

`gates/final.py` 的两条口径值得单独说清，因为它们最容易被后来人写坏：

1. **它不新增判定口径**。九段每段调的都是各阶段门禁/探针里**已经存在**的那份断言（`from stage1 import …`），
   交付链只负责编排与"跳过必须留痕"。想改判据要回到对应阶段的脚本里改，改这里等于悄悄换标准（**V19**）。
2. **"全绿"的范围由输出自己说**。被 `--only` 跳过的段每一段都打一行 `SKIP 未跑的段：…  这一场的「全绿」不覆盖它`，
   合计行写 `本次未跑 N 段`。所以引用某一场结论时必须连那几行 SKIP 一起引，不许只引末行。
3. **`合计判定 N 条` 这个 N 现在还不干净**（**ISSUES I36**，OPEN）：`segment_consistency()` 在没给 `--data-root` 时
   追加的 `PASS 一致性核查 p12 对真实数据根` 结构上永远不会变红 —— 文本诚实（自己写着"本次未跑"），
   计数不诚实。所以引用那一场时要说清 **16 条里有一件是没跑的**，别把条数当覆盖度。
   规则已一次性写进 `docs/REPO-JOURNAL.md` R-009 第 5 条：**没跑的东西用 `SKIP`/普通打印表达（不进 `checks`），
   或者干脆算 RED**。本轮没动 `gates/final.py`，因为一改就让已抄录的 16 / 8 / 3 三份原文条数全部作废（**D-034** 末尾）。

---

## 三 · 本轮新算出来的一条硬约束（需要立刻拍板）

全文索引体积。p2 实测中位 **2,294.6 字/页**，可提取文本页 **100.8 万页** → 正文约 **6.9GB**；
乘以实测索引膨胀率（trigram 最短行 6.91× / 真实整页 4.03×）→ **FTS 索引 28–48GB**，
再叠语义向量 **7.71GB**（fp32）。也就是说：**为 120GB 的语料在本机再写 36–56GB 索引**。

到 ×10 压力档就是 **280–480GB**，直接不可行。

三个可选项（勾选其一，我不替你选）：
1. **全量索引**：接受基线 ~40GB 索引，明确不支持 ×10 量级，界面显示索引体积与剩余磁盘。
2. **子集索引**：只对"已确认分类/加入集合"的文档建全文索引，其余只索引文件名与元数据。索引体积由用户控制。
3. **降密度**：正文不落全量，按段落/前 N 字截断，或改用 bigram+压缩、或只对短查询走 LIKE。

我的建议是 **2**（把体积决定权交给用户，且天然满足"首建 6h"和"查询 500ms"两条门禁），但这改的是产品定义，必须你确认。
→ 已写入 `03-风险清单与验证方法.md` 未决项。

---

## 四 · 断言自身的质量门禁（反向测试）

AGENTS.md 要求：每写完一条断言，先用"能骗过它的坏法"真注入一次。下表是**阶段 0 实际发生过的伪成功**，
每条都是先写出来、再用坏法戳穿、然后改断言的：

| 断言 | 骗过它的坏法 | 结果 | 处置 |
| --- | --- | --- | --- |
| p3「QtPdf 可用」 | 我调了不存在的方法名（`renderPage/unload/metadata`），再 `except` 吞掉 | 曾经判 False | 改正 API 后**收紧**断言：要求 `load==Error.None_` + 页数>0 + 图像非空 |
| p3「1024 宽能显示」 | 硬编码 `res[...] = True` | **能骗过**（假绿） | **删掉该断言**，改为真实要求：无对应可测事实就不许写进门禁 |
| p3「中文绘制正常」 | 只判"没抛异常" | 骗不过方块/tofu | 改为 `f.family() == "Microsoft YaHei"`（解析后族名必须等于请求族名） |
| p5「待 OCR 页量级」 | `kind == "scanned"` 拼错标签 | 投影全 0（假绿：不需要 OCR！） | 改成读真实标签 `scanned_image`，并断言 `corpus_pages_needing_ocr > 0` |
| p5「5000ms 达标」 | 阈值拍脑袋，怎么都能过 | 无意义 | 换成由无人值守窗口**反算**的 284ms，并保留由此产生的 **RED** |
| p6「向量有效」 | `attention_mask` 传全 0 → 池化出零向量 | 相似度会全 0，"无异常"通过 | `embed()` 返回**真实 mask**，并断言 pooled 非零 |
| p6「语义比关键词好」 | 只比数值大小 | 排序反了也能过 | 改成方向断言 `score_should_win > score_should_lose`，并要求 margin > 0.02 |
| p6「吞吐」 | 只跑 3 批 | 13.9↔25.0 chunks/s 随机摆 | 扩到 320 个真实文本块 / 20 批，指标改名 `*_end_to_end`（含分词） |
| p7「路径归一」 | 只用 `normpath`，不碰短名 | 短名 `报告A~1.PDF` 与长名不等，但样例太巧会过 | 引入 8.3 短名实测，强制 `realpath`，并把大小写断言翻成 `is True` |
| p8「hidden imports 生效」 | `--hidden-import` 写错也不报 | 冻结后 import 失败仍可能被判绿 | 冒烟必须**真的 import 并产出**（建 PDF、建 FTS 表、列 providers、建控件） |

规则沉淀进后续开发：
- 断言不许写 `x is not True or ...` 这类"自我开脱"式复合条件（阶段 0 出现过一次，已删）。
- 每条新断言提交前，先在本地把它**改坏一次**并确认真的变红；做不到就删掉这条断言。
- 阈值只有两种合法来源：实测单耗 × 量级反算，或写明 **[约定]** 并等你确认。

### 阶段 1 的反向注入（18 条，全部可重跑）

上面那张表是手记，容易被抄漏；阶段 1 把它变成**脚本**：`tests/probes/p9_reverse_injection.py`。
每条注入都在系统临时目录里的**仓库副本**上做（工作区代码一行不改），先跑未注入基线（11 条目标测试全绿），
再逐条注入并**要求**对应测试 `failed>=1 且 error==0` —— 用错误(collection/fixture error)冒充失败不算抓到。
结果：**18/18 被抓到，VERDICT: ALL GREEN**。

| # | 坏法（假装做对了什么） | 该变红的断言 | 抓到时的原始报错 |
| --- | --- | --- | --- |
| ISSUES I1 | UI 越过 services 直接 `import pdfarchiver.db` | 架构守卫 | `ArchitectureError` |
| ISSUES I2 | 把 SQL 字符串写进 `services/` | 架构守卫 | `ArchitectureError` |
| ISSUES I3 | `except Exception: pass` 咽掉故障 | 架构守卫 | `ArchitectureError` |
| ISSUES I4 | 导航注册表塞重复 `page_id` | 架构守卫 | `ArchitectureError` |
| ISSUES I5 | 阶段 1 就提前建 `content_fts` | `test_documentation_matches_actual_schema（阶段 1 那条「不建的表」断言已随 0002 建出 `content_fts` 作废，现在表集合由它双向对账，缺表与多表都红）` | `assert not ({'content_fts',…} & …)` |
| ISSUES I6 | 取消"没有快照目录就拒绝迁移"护栏 | `test_没有快照目录就拒绝迁移` | 没拿到预期的 `MigrationError` |
| ISSUES I7 | 迁移失败时不回滚，直接 `COMMIT` | `test_迁移中途失败回到原样` | `半个迁移留下了表 —— 事务没兜住` |
| ISSUES I8 | 重复扫描连 `parse_status` 一起覆盖 | `test_同一路径重复写只留一条且只刷新文件事实` | `重新扫描不能把索引状态冲掉` |
| ISSUES I9 | 忽略"已种过"标记，只看表空不空 | `test_默认模板种过就不再长回来` | `assert False is True`（用户的删除被复活） |
| ISSUES I10 | 状态页标签数写死成 0 | `test_刷新按钮重查数据库` | `刷新必须是重新查库，不是重排一遍旧文本` |
| ISSUES I11 | 在未实现的屏上摆 `QPushButton` 充数 | `test_未实现页不放任何假控件` | `assert [<QPushButton>] == []` |
| ISSUES I12 | 关窗只关窗口，不关连接、不留对账行 | `test_关窗真的关掉连接并留下对账行` | `assert <sqlite3.Connection> is None` |
| ISSUES I13 | 不往 `state.log` 写 `window.ready` | `test_进程级冷启动实测符合G1约定` | `没有 window.ready 事件：[…]` |
| ISSUES I14 | 把阈值改成 0.001s（验证读数参与判定） | 同上 | `G1 [约定] ≤1.5s，实测 0.344s` |
| ISSUES I15 | 身份键少做一次 `casefold` | `test_身份键全小写` | `'…报告 A.pdf' != '…报告 a.pdf'` |
| ISSUES I16 | **裸本地时间却标 `Z`**（格式合法、时刻差 8 小时） | `test_三个日志出口用同一个时间口径` | `app.log 1791921130 vs state.log 1791949930` |
| ISSUES I17 | `app.log` 行首退回标准库的本地无偏移时间 | 同上 | `app.log 行首不是 UTC+Z：2026-10-14T03:52:11.332 INFO` |
| ISSUES I18 | 把开发机自己的路径当默认值写进 `services/`（`"C:/Users/dev/PDF归档库"`） | 架构守卫 | `…字符串常量里有本机路径…路径必须由 config/paths.resolve_data_root() 解析，不许写死（验收 6）` |

ISSUES I16 是这批里最有价值的一条：**光看格式永远查不出来**。它证明"跨表比对同一瞬间"那条断言不是装饰，
所以 D-022 的两条断言（同格式 + 同时刻）一条都不能省。

### 阶段 2 的反向注入（ISSUES I19–ISSUES I46，共 28 条，同一脚本可重跑）

阶段 2 把探针从 18 条扩到 46 条，新增的 28 条全部围绕本阶段新写的链路：任务队列、索引短路、
四条检索通道、状态读数、文件监听接线。**结果：46/46 被抓到，`VERDICT: ALL GREEN`。**

| # | 坏法（假装做对了什么） | 该变红的断言 | 抓到时的原始报错（截断） |
| --- | --- | --- | --- |
| ISSUES I19 | 任务收尾不补齐工作量，状态 `done` 而进度停在 64/1000 | `test_进度按步长攒着写最后补齐` | `assert ('done' == 'done'` |
| ISSUES I20 | 整本一页都没读出来，却把 `fts_status` 写成 `done`（虚假有效结果） | `test_打开成功但一页都没读出来算失败而不是已索引` | `DID NOT RAISE PermanentFailure` |
| ISSUES I21 | 正文命中的页码写死成第 1 页 | `test_正文通道给出页码与可高亮片段` | `assert ('合同…' == '…')`（文件名先对不上） |
| ISSUES I22 | 故障列表只查终结状态，正在重试的那条原文看不见 | `test_重试中的任务既算重试也带着原文出现在读数里` | `IndexError: list index out of range` |
| ISSUES I23 | 「重试中」不看状态，早就放弃的文件永远挂在上面 | `test_试满上限后不再算重试而是留下失败终态` | `已终结的行不该算重试中：{'index': 1}` |
| ISSUES I24 | 故障读数不封顶，八千条一起灌进文本框 | `test_故障读数最多列十条并按最新优先` | `assert 15 == 10` |
| ISSUES I25 | 扫描已经成功了，界面上还挂着上一次的错误 | `test_监测根上次扫描错误显示出来且成功一次就清空` | `扫描已经成功了，界面上不许还挂着上一次的错误` |
| ISSUES I26 | 暂停的根在读数里也标成启用 | `test_暂停的根在读数里标出来` | `'[已暂停]' in '  任务：…'` 不成立 |
| ISSUES I27 | `total=0` 也照样输出百分比（拿 0 除） | `test_排队中的任务算条数不算进度` | `ZeroDivisionError: float division by zero` |
| ISSUES I28 | 界面只留一个标题，不渲染任何任务读数 | `test_状态页显示扫描与索引任务的读数` | `没起 worker 就要说没起，不许显示成正在跑` |
| ISSUES I29 | 任务读数缓存起来，刷新按钮不再重查 | `test_刷新按钮同样重查任务读数` | `assert '任务条数  index：queued=2' in …` |
| ISSUES I30 | 定时器亮灯但不巡检，事件永远没人处理 | `test_巡检一轮就把脏根排成一条扫描任务` | `assert [] ` |
| ISSUES I31 | 巡检异常只挡住除零，别的异常把定时器打死 | `test_巡检抛异常时定时器不许停并且状态栏留下原文` | `OSError: 移动盘被拔掉了` |
| ISSUES I32 | 定时器间隔写死成默认值而不是取巡检器的口径 | `test_巡检定时器与巡检器同一个间隔口径` | `定时器间隔没跟巡检器取同一个数：5000ms` |
| ISSUES I33 | 后台没起来也对界面谎报在跑 | `test_后台没起时读数说未启动而不是说一切正常` | `'NoneType' object has no attribute 'thread_count'` |
| ISSUES I34 | 监听根数恒报 0，事件流断了自己不知道 | `test_后台起来后读数给出线程数与监听根数` | `注册了 1 个根就该在听 1 个：BackgroundState(…)` |
| ISSUES I35 | `run()` 忘了起后台：界面能开，任务永远没人领 | `test_进程级冷启动实测符合G1约定` | `启动失败：` |
| ISSUES I36 | MATCH 表达式不转义，用户输入的 `AND` / 引号变成运算符 | `test_查询词里的FTS运算符被当成普通字符` | `fts5: syntax error near "审阅要点"` |
| ISSUES I37 | 文件已经没了还照样搜出来（SPEC 3.4 禁止的虚假有效结果） | `test_缺失文档默认不进结果但可以显式包含` | `assert [Hit(doc=Docu…)] == []` |
| ISSUES I38 | watchdog 处理器**退回没有基类的那一版**（实测踩过的原始事故） | `test_处理器满足watchdog要求的回调形状` | `没继承基类就没有 dispatch，observer 线程会当场死掉` |
| ISSUES I39 | `dispatch` 不查词表，任何事件类型都塞进缓冲区 | `test_watchdog新增的事件类型不许把处理器打死` | `assert [FsEvent(kind…)] == []` |
| ISSUES I40 | 事件词表写成 `dict.fromkeys`（值全是 `None`，四种事件一律被丢掉） | `test_四种文件事件各自进缓冲区并带上根` | `缓冲区里应该有且只有一条事件，实际 []` |
| ISSUES I41 | 取消监听只删自己字典里的 handler，不向 watchdog 退订 | `test_取消监听之后那个根不再交来事件` | `退订只删了字典里的 handler，emitter 还在往它身上灌事件` |
| ISSUES I42 | 崩溃钩子按**不存在的** `args.exc_info` 取异常（线程现场整个丢掉） | `test_后台线程里的异常也会留痕` | `线程异常没落进 crash.log —— 钩子拿异常参数的字段名错了` |
| ISSUES I43 | 监听线程死了也对界面说活着（把 `watcher_alive` 写死 `True`） | `test_监听线程半路死了读数当场跟着翻脸` | `监听线程已经退出，读数还在说活着` |
| ISSUES I44 | 读数里不写那行 ⚠，断流说成一切正常 | `test_监听线程死了读数必须把它说出来` | `监听断了却没在读数里出现：  后台：worker 线程 2｜监听根 1` |
| ISSUES I45 | 索引时不做哈希短路，每次都把正文重抽一遍 | `test_短路索引给出的结论写在describe里` | `assert (True and False)` |
| ISSUES I46 | 扫描时不看索引状态，每一份都再排一次索引任务 | `test_再扫一遍全是未变且不重复排索引` | `已经索引好的文档，重扫不该再抽一遍正文` |

**这批里最值得记的三条**：

- **ISSUES I38 / ISSUES I42 的坏法就是当初真实写错的那一版**。它们不是为了凑数编的 —— 见 `docs/stage-reports/阶段2-交付报告.md` 第五节。
- **ISSUES I43 一开始抓不到**。第一版把 `watcher_alive=True` 注入到"后台正在跑"的那条断言上，而那时监听**确实是活的**，
  注入等于没注入。改法是补一条真让它**半路死掉**的测试（`ctx.watch.stop()` 后再读一次快照），
  坏法才 measurable。这正是 AGENTS.md「不会变红的断言直接删或重写」的正面案例。
- **ISSUES I45 也一开始抓不到**。原以为 e2e 的"重扫不重抽"测的是索引短路，实测那条路走的是**扫描侧不排任务**；
  短路只在有人真排了 `index` 任务时才被走到。于是拆成两条：ISSUES I45 钉索引侧（`_unchanged`），
  **ISSUES I46 钉扫描侧**（`_needs_index`）—— 两个不同的失效模式，两种不同的坏法。

### 界面审核轮的反向注入（9 条，2026-10-17 现场复跑）

**这一批不进上面那张 `I<n>` 编号表**：同一个字形 `I<n>` 在项目里已有三本账（台账行号 / p9 坏法 / p10 坏法），
p9 表已经用到 ISSUES I46，再往下加必然与台账新开的行撞号 —— 病因与处置记在 **ISSUES I35**（OPEN）。
所以这一批用「注入 · 类名-序号」的写法，编号本身不承载引用。

| 断言 | 坏法（假装做对了什么） | 抓到时的原始报错（点名片段） | 结果 |
| --- | --- | --- | --- |
| `test_architecture.py::test_界面不许自己拼时间串` | 临时副本的 `ui/pages/backup_page.py` 里加一个 `datetime.now().strftime(...)` | `backup_page.py:265 调了 .strftime(…) —— 界面自己拼时间串就是第二个口径` | 抓到 1 条 |
| 同上 | 副本的 `dedup_page.py` 只换成带时区的 datetime：`fromtimestamp(0)`（**不拼串**） | `dedup_page.py:332 调了 .fromtimestamp(…)` | 抓到 1 条 |
| 同上 | 副本的 `library_page.py` 走 `time.localtime(0)`（换模块不换口径病） | `library_page.py:425 调了 .localtime(…)` | 抓到 1 条 |
| 同上（**对照组**） | 副本的 `archive_page.py` 合法地 `import datetime` 但**不造时间串**（返回 `datetime.MINYEAR`） | —— | **未被误报**（守卫盯的是造串动作，不是 import；否则将来真要算日期差的界面会被自己拦死） |
| `test_status_readout.py::test_没接上执行器的按钮不许伪装成功` | 「执行归档」的文案改回「已将 N 份文档提交到归档队列」 | `文案谎报了后果：'已将 1 份文档提交到归档队列…'` | 红且点名 |
| 同上 | 处理器**偷偷建批次**（`create_operation("archive")`），文案还说"没接上" | `界面在背地里建批次了` | 红且点名 |
| 同上 | 把文案里「磁盘」两字抹掉（其余照旧诚实） | `没接上执行器的按钮必须明说磁盘上没动过` | 红且点名 |
| `test_status_readout.py::test_状态读数里的缺什么只许来自两个列表` | 状态页页尾塞回一句散文「语义搜索与归档、备份恢复的界面都还没实现」 | `状态读数在用散文宣称「没实现」：…` | 红且点名 |
| 同上 | 把 `DISK_EFFECT_LINE` 追加两遍（磁盘口径出现两份） | `磁盘口径出现了不止一份` | 红且点名 |

**基线与还原读数**：时间口径那组基线（工作区真源码）**0 条**，注入 4/4、`VERDICT: ALL GREEN`；
文案那组 **5/5 全红且点名**，还原后复跑 `exit=0`（探针最后一步就是复跑这两条守卫，不绿就报 RED）。

**两条方法上的交代**（写下来是为了下一轮不必重新讨论）：

- 时间口径那组走 **临时副本**（同 p9 的规矩，工作区代码一行不改）—— 因为守卫只是 AST 扫目录，
  把 `ui/` 复制到临时目录、把模块级 `PKG/SRC` 指过去就够了。**每条注入要求"恰好 1 条命中且行号在预期文件里"**，
  只判"有没有红"会漏掉"报在别处"这种错位。
- 文案那组**真的改工作区文件**再 `finally` 还原 —— 因为那两条断言跑的是**活着的 Qt 窗口**（真点按钮、真读弹窗、
  真数台账行数），副本里既没有可复用的 venv 路径，重跑整个 fixture 的成本也高于收益。
  代价写清楚：**这种方法在中途被杀时会留下改动**，所以跑它之前工作树必须已 `git status` 过一遍，
  且探针自带"还原后复跑必须 exit=0"这一步（缺了它，探针就变成"改坏了还不知道"的凶手）。
- 注入 3 一开始是**无效坏法**：只改了弹窗第二段（那段本来就不含「磁盘」），守卫合理地判绿 ——
  与 ISSUES I43 / I45 同一类"坏法打不到判据"。换成改掉**含「磁盘」的那一行**才真的红。
  留在这里的理由：`能变红` 不是坏法的属性，是**坏法与判据是否对撞**的属性。



### 因坏法测不到而重写的两条测试（不许留假断言）

| 原断言 | 为什么是摆设 | 重写后 |
| --- | --- | --- |
| `test_后台线程里的异常也会留痕`（旧版自己 `class A: exc_info=(…)` 喂给钩子） | 钩子读哪个字段它都能造出来，永远绿 | 真起一个会崩的 `threading.Thread`，轮询 `crash.log` 等堆栈出现，并断言留下的是哪个线程名 |
| p4 探针自带的处理器类 | 测的是探针自己的类，`fs/watcher.py` 里的生产类一次都没被调用过 | 新增 `tests/integration/test_watcher_events.py`（10 条）**import 产品里的 `_BufferHandler` 与 `WatchManager`**，含真起 observer 线程收真事件的两条 |

另外单独验证过**门禁链自己不是橡皮章**（同样在副本里做，见 `docs/VERIFICATION` 4.10）：
弄坏 `identity.py` → 门禁的"全量回归"项变红、`exit=1`；把 G1 阈值改成 0.001s → G1 自己变红、`exit=1`。

---

## 五 · 发布门禁链（阶段 7 起生效）

一次串联，任何一环非零退出即停止，**末行必须打印 `VERDICT: ALL GREEN`，否则发不出去**：

**前置条件：全部命令必须用 `.venv` 里的解释器跑**（`.venv/Scripts/python.exe -m pytest ...`）。
用系统 Python 会让 G21 变红 —— 那不是依赖坏了，是那台解释器里装着本项目禁止的包。
实测本机 Anaconda（`D:\3.DevelopmentProgrammingTools\anaconda3\python.exe`）里有
`torch 2.14.0` 与 `transformers 5.16.1`，直接触发 `test_no_gpu_framework_that_pulls_cuda` 和
`test_project_has_onnxruntime_when_optional_layers_installed`（2 failed / 4 passed）。
守卫的失败消息里现在会打印 `当前解释器：...`，就是为了让人一眼分辨这两种红。

```
gates/
  stage1.py              # ✅ 阶段 1 收尾用这条：G21 → 架构守卫 → 全量回归 → 冷启动实测 → 反向注入
  stage2.py              # ✅ 阶段 2 收尾：在 stage1 之上加「新 · 后台生命周期」「新 · 阶段 2 端到端」（不占 G 编号，见 ISSUES I28）
  stage5.py              # ✅ 阶段 5 收尾：再加 OCR 三行（产品路径实测 / 预算真停机 / 真引擎套件不许 skip）；--quick / --no-injection
  final.py               # ✅ 最终交付链：十一段 + docs-inject（2026-10-15 上架时九段；2026-10-18 把 p16/p17/p18 并进 `injection` 段、p15 单开 `ui-inject` 段），分段编排**不新增判定口径**
                         #    guards regression coldstart e2e injection ocr consistency soak package
                         #    默认只跑快段；被 --only 跳过的段在输出里明写"本次未跑"，末行恒为 VERDICT: …
  # 以下按阶段推进再建，不提前摆空文件：
  02_lint.py             # ruff + （可选）mypy 关键模块            —— 阶段 2
  03_unit.py             # L1                                     —— 阶段 2
  04_integration.py      # L2（真实 SQLite）                       —— 阶段 2
  05_e2e.py              # L3（真小语料全链）                       —— 阶段 2 起
  06_scale.py            # L4：8,000 份基线 + ×10 合成档，出 G2/G3/G5/G6/G7/G8/G16 数字 —— 阶段 2
  07_build.py            # PyInstaller --onedir                    —— 阶段 7
  08_frozen_smoke.py     # G20：跑产物 exe                          —— 阶段 7
  09_readback.py         # 产物回读版本号与体积                     —— 阶段 7
```

`gates/stage1.py` 的两条口径值得单独说清，因为它们最容易被写成"看起来在验"：

1. **冷启动不在门禁里掐表**。被测进程自己把 `cold_start_seconds` 写进 `state.log` 的 `window.ready`，
   门禁只读那一条；界面状态页显示的也是同一条字段。两处各量一次必然出现两个数（D-021）。
2. **数据目录用系统临时目录**。门禁不碰 `%LOCALAPPDATA%`，也不碰任何真实语料 —— 它跑一次不该留下任何副作用。

```bash
.venv/Scripts/python.exe gates/stage1.py                 # 全跑，约 1 分钟
.venv/Scripts/python.exe gates/stage1.py --no-injection  # 约 15 秒，但"断言有约束力"这一条未被验证（输出里会明写）
```

每条门禁输出统一字段：`name / expected / actual / pass`，汇总成 `gates_result.json`，
报告里必须逐条列出，**不允许只报"全部通过"**。

---

## 六 · 各阶段收尾必须回答的三个问题

1. **验证证据是什么**：测试输出 / JSON / 截图，路径写出来，禁止转述。
2. **哪些还是候选**：不许把候选写成已定（阶段 0 的 C1–C10 见 `00` 第六节）。
3. **已知问题清单是否清零**：本轮新增的未销账项必须列在原位，不许滚动丢失。