# 变更日志

按阶段记录。版本号口径：阶段 0–7 全部走完并通过发布门禁才叫 `1.0.0`；在此之前一律 `0.x.y`，
且 `x` = **已完成的最大阶段号**（允许跳号：没做的阶段在条目里点名，不许让人以为 0–x 全通过）。
**本文件只记实际做过并验证过的变更**，未落地的写在 `ROADMAP.md`，不写在这里。

---

## 轮三十三（2026-10-28）—— I116 甲：向量入场券改判「有没有可搜的正文」；497 页 OCR 正文补建向量；CHANGELOG 再切一册

用户这一轮的指令逐字：「I116 甲（做完③，你勾一下就行）→ 下一轮开篇切 CHANGELOG + 跑一场整链。」
三件按序做完。

- **① 先切册、再写这一条（D-059 第 4 条的再切线：活册 > 600 行）** —— 一次性脚本
  `.probe_work/u33_changelog_split.py` **自检不过就拒写**：切点 `## 勾选轮（十九…` 与文末指针各必须命中
  **恰好 1 次**，切完把「保留段 + 新指针」拼回去必须**逐字等于原文**才落盘。结果：活册 **1,178 → 550 行**，
  `勾选轮（十九）` … `勾选轮（七）` **13 段 / 631 行**逐字搬进新册
  [`docs/CHANGELOG-ARCHIVE-2.md`](CHANGELOG-ARCHIVE-2.md)（**647 行**，含册头与文末指针），
  `勾选轮（六）` 及更早仍在 `CHANGELOG-ARCHIVE.md`（**1,064 行，一字未动**）。标题数守恒 **26 = 13 + 13**，
  一条没改、一条没删；切前原件 md5 备份 `.probe_work/u33_changelog_before_split.md`（`791e9ea4…`）。
  `tests/guards/test_doc_pointers.py` 的 `LEDGER_DOCS` 加新册，guards **59 passed**。
- **② I116 甲 · 入场券归一到 `has_searchable_text(doc)`** —— 定义只一处
  （`services/index_service.py`）：`text_status ∈ ("native","mixed")` **或** `ocr_status ∈ (done, partial)`。
  全文与向量共用同一张票：`vector_service.py` 的 `_why_skipped` 与 `build_vectors` 的拒建文案都改走它，
  跳过标签写「没有可搜的正文，先索引或先识别」。**没有改 `text_status`**（那一列的含义是「有没有原生正文」，
  `parsing/classify.py` 的口径），也没有放宽 `TEXT_SEARCHABLE` 本身。
- **③ 497 页 OCR 正文补建向量（真库，零 SQL）** —— `request_vectors((10995, 10997))` 回执逐字
  「点名 2 份｜该建 2 份｜新增任务 2 条」、`skipped={}`（上一轮这里是 `not_searchable`）。两段实跑：
  doc 10995 **262 页 → 256 条向量**（6 页空正文跳过，4,769ms）、doc 10997 **236/236 条**（2,563ms），
  合计 **+492 条**：`vector_meta 1,968,563 → 1,969,055`、`vector_status done 8,690 → 8,692`、`na 2,305 → 2,303`。
  **自检索才是向量存在的证明**：4/4 页拿自己的正文查回 rank 1（197 万页的全局 top-k 竞争不是合格判据）。
  全文侧另记一条**如实的负读数**：「倪匡散文」top-20 有 3 行来自 doc 10995；「赫拉巴尔」top-20 **0 行**
  来自 10997、扩到 top-200 才 3 行（最好的是第 16 页 @0.5458）—— 向量确实建了，召回名次不好，
  没有为了好看去动 top-k 或改口径。
- **测试**：`tests/integration/test_vector_write_path.py` **18 passed**，新增
  `test_OCR_出过正文的扫描件也能建向量` 与 `test_入场券两个条件任一成立即放行`（9 组真假表）；
  坏法注入（把谓词退回 `text_status` 单条件）**2 failed / 16 passed**，红的正是这两条。
- **台账**：I116 **OPEN → CLOSED**，证据与销账条件两格都贴了实测读数 ⇒ **OPEN 1（I115）**。
- **文档同步**：`docs/DECISIONS.md` 在 D-061 上加**追注**（第 2 条的入场券口径被 I116 甲改写，
  旧措辞保留作历史、不改原文）；`docs/ARCHITECTURE.md` 的 `vector_service.py` 注释同步；`README.md`
  的变更日志索引改成指向两册。
- **整链 12 段一条命令（约 110 分钟）—— 35 条判定 / 3 红，末行 `VERDICT: RED（3 条未过）`**（`.probe_work/final_chain_r33.log`）：
  起跑 `CPU 70.7%｜可用 3,570MiB｜ZCode.exe 505MiB`（regression 段期间我自己还跑过两次短 pytest）。三红：
  **regression** `823 passed / 1 failed / 1 skipped（250.68s）`＝唯一失败 `test_进程级冷启动实测符合G1约定`；
  **e2e** `冷启动 1.674s`（同一场链的 coldstart 段自己是 **1.329s PASS**，两次差 0.345s，失败那次超约定 174ms）；
  **consistency p12 真根** `RED（2 条未过）｜4,528.6s｜19 条｜红 2｜未验 0`：`C3·D:\` 盘上 96 / 库里 94（2 份 2026-10
  微信 PDF 从未索引，数据漂移）+ `C5` 6 行空正文（doc 10995 页 17/27/39/73/135/217，`source_kind='ocr'`，是 OCR 的
  页级完成标记，与 C5「不许养零信息行」正面冲突 ⇒ 新开 **ISSUES I117**，推荐甲，本轮不改判据）。其余九段全绿：
  coldstart 1.329s｜injection **917.1s**（p9 70/70、p10 45/45、p16 11 条、p21 24/24、p22 33/33、p23 23/23、p24 17/17）｜
  ui-inject 93.0s｜ocr 33.9s｜soak 322.5s（9 条 0 红、注入 13/13 + 好读数 4/4、RSS 112.7 → 112.8MiB）｜
  package 355.1s（400.1 MiB、273–273、冻结冒烟 ALL GREEN）｜g2 44.1s（负载分类自检 6/6；这一段只落 `VERDICT`、
  **没打印 P95 数字**，不引用）。**没有为凑绿重跑，也没有抬任何阈值。**
- **两处自己留下的痕迹（据实记，一行没动）**：C9 现场的 `'queued': 2` 是 `.probe_work/u33_vector_backfill.py`
  先 `request_vectors` 再直接 `build_vectors` 留下的两条 `vector:queued`（11019→doc 10995、11020→doc 10997，
  `attempts 0`）；`C3·D` 那 2 份与轮三十的 5 份同属微信落盘漂移。两条都要勾选才动
  （甲 单事务删这 2 行 / 乙 下次开应用让 worker 自己跑完 / 丙 只记不动；PDF 那份走产品路径重扫）。

## 轮三十二（2026-10-27）—— I113 甲：删掉跨卷搬家留下的死记录；两份扫描件 OCR 出 497 页正文；顺带逮到 OCR 正文进不了向量入口（I116）

用户这一轮的指令逐字：「均跟进你的建议来执行」。三件都做了，第三件（向量回填）**被产品自己的入场券挡住**，
据实入账 **I116**，没有改口径凑绿。

- **① I113 甲 · 先备份后单事务删 doc 93**（`.probe_work/u32_i113_backup_delete.py` → `.json` / `_delete.log`）——
  快照 `%TEMP%\pdfarchiver-i113-backup\catalog.db` **12,112,449,536 B / 47.4s**，八张表逐表计数与源库全等
  （`mismatch {}`）、`schema_version [8, 8]`、doc 93 原行（sha256 `043dc424…d9d7`、341 页、`missing_since=1792790831`）
  在快照里可查 ⇒ **BACKUP GOOD**。
- 单事务（`BEGIN IMMEDIATE`；六张子表显式删再删主记录，`PRAGMA foreign_key_check` 非空即不提交）：
  `documents 10,996 → 10,995`、`text_pages 1,976,016 → 1,975,678`（−338）、`content_fts` 同步 **−338**、
  `document_metadata −1`、`processing_jobs −1`、`vector_meta` **不变**（doc 93 正是全量索引里唯一缺文件的那份）、
  孤儿页 **0**、外键核查 **OK**，整段（含前后各一次全表计数）**160.1s** ⇒ **DELETE GOOD**。**没动磁盘文件**（那条路径本就不存在）。
- **② 两份扫描件 OCR 497 页**（`.probe_work/u32_ocr_vectors.py`，只调产品 `OcrService.request_ocr` +
  `AppContext.start_background()`，与界面那颗「送去识别」同一条链路）—— doc 10995 **261/262 页**（OCR 56,139 字，
  第 262 页本就是原生 894 字、不算漏页）、doc 10997 **236/236 页**（157,331 字），合计 **497 页 / 13.0 分钟（38.1 页/分）**，
  两份 `ocr_status=done`、`last_error` 空、今日预算 **497 / 6,000 页**（剩 5,503）。全文搜索当场验
  （`.probe_work/u32_after_ocr_checks.py`）：`"赫拉巴尔"` 本页 5 行命中全在 doc 10997（正文 11 行）、
  `"倪匡散文"` 本页 5 行命中全在 doc 10995（正文 114 行），来源串「OCR 识别（可能有错字）」。
- **③ 向量回填被入场券挡住 → I116（OPEN）**：`request_vectors((10995,10997))` 回执逐字「点名 2 份｜该建 0 份｜
  新增任务 0 条｜没有可搜的正文，先索引 2 份」，`skipped={'not_searchable': [10995, 10997]}`。根因：入场券按
  `TEXT_SEARCHABLE=("native","mixed")`（`index_service.py:47`）判，而 OCR 的唯一写入口 `mark_ocr_result`
  （`documents.py:429-442`）只写 `ocr_status`、**不碰 `text_status`**，两份仍是 `text_status=none`。**没有把
  `text_status` 改成 `native` 凑绿** —— 那会让「有没有原生正文」这一列说假话。甲/乙/丙 已入台账，**推荐甲**。
- **RUNLOGS 再切一册（D-059）**：`docs/VERIFICATION-RUNLOGS.md` 1,175 → **459 行**，§4.26–§4.37 逐字迁入
  `docs/VERIFICATION-RUNLOGS-ARCHIVE-2.md`（**727 行**，`splitlines()` 口径），节号不变、标题数守恒 18 = 18、
  原册 md5 备份留在 `.probe_work/`；`tests/guards/test_doc_pointers.py` 的 `LEDGER_DOCS` 加新分册，
  guards 全量 **59 passed**。
- **台账**：I113 **OPEN → CLOSED**；新开 **I115**（跨卷搬移认不出改名的根因，等勾选）与 **I116**（OCR 正文进不了
  向量入口，等勾选）⇒ `116 行｜I1–I116 连续不重号｜OPEN 2`。**阈值与产品代码这一轮 0 改动**。
- **收尾后用户定案（D-062）**：对「仍欠」里的四项回「这些都不做」—— ④ 24h soak、⑨ injection 真空载（CPU<10%）
  读数、安装包与代码签名、隐私政策。四处**只改口径不改产品**：`ROADMAP.md` 的 soak 行写明证据上限永久 12h、
  `docs/stage-reports/最终交付报告.md` 加 2026-10-27 追记（三处「未交付」保留为事实、不再是欠账）、
  `docs/DECISIONS.md` **D-062** 四条可断言决定。**没有删任何历史读数，也没有抬门槛换读数**。

## 轮三十一（2026-10-27）—— 新文档向量回填 404 页 + 12 段整链一条命令第一次全绿（修掉打印阶段的编码崩链）

用户这一轮的指令逐字：「整链一条命令全绿（本轮是定点复跑，不写成整链全绿）；5 份新文档 vector_status=na、
新增 405 页正文未 embed（语义搜索还到不了）；执行这些把」。两件事都做了，中间逮到一条**不在原计划里**的缺陷
（I114），所以这一轮比计划多跑一场整链。

- **⑤ 向量回填 404 页**（`.probe_work/u31_vector_backfill.py`，零 SQL、只调产品 `VectorService`）—— 5 份新文档里
  3 份原生正文全部写入：doc 10996 **162 页**（3,244ms）、doc 10998 **110 页**（1,139ms）、doc 10999 **132 页**（1,441ms），
  合计 **404 页**；`vector_meta 1,968,159 → 1,968,563`、`vector_status done 8,687 → 8,690 / na 2,309 → 2,306`。
  另 2 份（doc 10995 262 页 / doc 10997 236 页）`text_status=none` **被如实跳过**，回执逐字「这份还没有可搜的正文
  （text_status=none），先索引才能建向量」—— 它们是扫描件，要先走用户触发的 OCR；**没有替它们造正文**，
  也没有把 `na` 改成 `pending` 来凑数。
- **第一场整链（07:19:21 → 08:57:36）在第 10 段后崩** —— docs-inject / guards / injection / ui-inject / ocr /
  consistency / soak 七段全绿；regression（816 passed / 1 failed）、coldstart（**1.663s**）、e2e（**1.604s**）
  三条 G1 同源红（起跑 **CPU 56.7%｜2,194MiB**）；随后 `gates/final.py:561` 打「现场」时 `UnicodeEncodeError`，
  package 与 g2 没跑。根因 = `packaging/frozen_smoke.py:425` 的 `text_pages − content_fts`（U+2212）进了 note ⇒
  **ISSUES I114（CLOSED）**。
- **修法：`gates/stage1.py::harden_stdio()`** —— 只把 stdout/stderr 的 `errors` 改 `replace`，**编码仍是控制台原样**
  （改 UTF-8 会让 GBK 屏上中文全成乱码）；`gates/stage1.py`–`stage6.py`、`gates/final.py`、`scripts/precheck.py`
  八处 `main()` 第一条语句调用。守卫 `tests/guards/test_gate_stdio_encoding.py` 五条，其中两条在 **GBK 子进程里真跑**：
  带兜底必须 exit 0 且那行以 `?` 留下，不带兜底必须 `UnicodeEncodeError` 非 0 退出。**900 字截断没动、阈值没动**。
- **修后 package 定点复跑**：290.3s 全绿（build 142.9s + smoke 147.5s；整包 400.1 MiB、documents 273 / 磁盘 273）。
- **第二场整链（09:05:46 → 10:43:47，5,877.1s）—— 「整链一条命令全绿」第一次拿到**：
  `合计判定 35 条｜本次未跑 0 段｜VERDICT: ALL GREEN`；起跑 **CPU 36.3%｜2,804MiB｜chrome.exe 1,784MiB**。
  逐段：docs-inject 0.0s｜guards 2.4s｜**regression 199.5s（822 passed / 1 skipped）**｜coldstart 2.0s（**G1 1.342s**、
  关窗对账 1 条）｜e2e 13.7s（11 条端到端）｜injection 790.6s（p9 70/70、p10 45/45、p16 11 条、p17 3/3、p18 3/3、
  p21 24/24、p22 33/33、p23 23/23、p24 17/17）｜ui-inject 86.6s（p15 36/36）｜ocr 32.6s（真引擎 6 页落库 +
  预算 2 页真停机 + 4 passed 套件）｜**consistency 4,116.9s（p12 真根 19 条 / 红 0 / 未验 0）**｜soak 320.7s
  （9 条全绿，RSS 112.9 → 113.1 MiB）｜package 261.2s｜**g2 50.9s（P95 320ms，P50 137 / P99 341 / 100 样本 /
  最差 `发票`，起跑 CPU 3.5%｜2,787MiB，`classification=green`，分类自检 6/6）**。
- **台账**：新增 **I114（CLOSED）** ⇒ `114 行｜I1–I114 连续不重号`；**I113 仍等勾选**，本轮没动真库一行。
- **阈值一处没动**：G1 1.5s、g2 500ms、忙线 60%、900 字截断全部原样；第一场那 3 条 G1 红**照记不赦免**（负载场），
  **没有「重跑到绿」**。

## 轮三十（2026-10-27）—— 安静窗定点复跑（G1 / g2 / 回归）+ 产品路径重扫（consistency 19/19 转绿）

用户这一轮的指令逐字：「这两个能执行吗」（指上一轮记下的两条出路：① consistency 需要一次产品路径重扫、
② G1 与 g2 要安静窗定点复跑）。两条都能执行，而且 04:4x 机器正好空下来（`TOTClient-Win64-Shipping.exe`
3,536 MiB 退场，CPU 61.2% → 25.7%、可用 1,620 → 3,907 MiB），所以按「先量后写」的顺序做：
**先跑对负载敏感的两条，再动库。产品代码与测试代码本轮 0 改动**。

- **安静窗定点复跑（三处阈值一处没动）** —— g2 真库 P95 **326.0ms**（P50 142 / P99 338 / max 338 /
  100 样本 / 最差 `发票`），起跑 **CPU 26.0%｜可用 3,889MiB**，`classification=green`；对照轮二十九
  同一套 20 查询 × 5 reps 的 **608.0ms @ CPU 55.3%｜1,911MiB**。G1 冷启动 **1.205s**（进程总耗时 1.836s、
  关窗对账 1 条）；`test_进程级冷启动实测符合G1约定` 单跑 ×3 全过（1.77 / 1.97 / 1.75s）。
  回归按整链同口径 `pytest tests -q` ⇒ **817 passed / 1 skipped / 183.21s / exit 0**
  （轮二十九那场是 816 passed / 1 failed，唯一失败就是这条 G1 计时）。
- **产品路径重扫（`.probe_work/u30_rescan.py`，零 SQL、零手改库）** —— 只调
  `ScanService.reconcile_path()` 与 `IndexService.index_document()`：5 份新 PDF → doc **10995–10999**
  （3 份原生正文 162 / 110 / 132 页；2 份扫描件 262 / 236 页 `text_status=none / ocr_status=pending`，
  按设计等用户点「送去识别」）；删掉的 qwenwork mock `sample.pdf` → doc 10980 走
  `OSError → _vanish → mark_missing`，`missing_since=1793047826`。改前 6 条路径全 `in_db: false`、
  改后 5 条 `added` + 1 条 `missing`，逐条落 `.probe_work/u30_rescan.json`。
- **p12 真根 19 条：红 0 / 未验 0 / `VERDICT: ALL GREEN`**（04:59:23 → 06:08:37，**4,154s**）。
  C3 六行（各 820,094ms，并发）：lavie 68/68/缺 0｜**D: 94/95/缺 1**｜E 1969/1969/0｜F 5352/5352/0｜
  G 1655/1655/0｜**H: 1856/1857/缺 1** —— D 与 H 的「库多 1」正是那两条 `missing_since`，
  口径是「盘上 = 库内 − 已标缺失」。其余：C1 997,851ms `integrity_check=ok`｜C2 2,949ms 主记录 10,996
  全部唯一｜C4 196,592ms 1,976,016 ↔ 1,976,016（漏 0 / 残留 0）｜C5 1,202,780ms 1,976,016 页六项自洽｜
  C11 930,361ms 最新快照整库体检｜C12 4,474ms 超页 0。同一条探针比轮二十九那场快 **2,032s（−33%）**，
  差别是负载（那场与整链 8 段背靠背、本场独占）；**两场都是真读数，不互相换算**。
- **一个坑记一次**：第一次用 shell 里的 `python` 跑段，`ModuleNotFoundError: No module named 'PySide6'`
  把 g2 与 coldstart 各判了一条 RED —— 那是解释器选错（要用 `.venv/Scripts/python.exe`），
  不是产品红，`.probe_work/u29b_g2_coldstart.log` 那一场作废。
- **新开 ISSUES I113（OPEN，等勾选）**：doc 93 与 doc 10994 是同一本书 —— MemoTrace 目录从
  `D:\6.Communication Social\` 搬到 `H:\others software\`，Windows 跨卷搬移换 inode ⇒
  `_adopt_renamed` 按设计认不出是改名，旧记录留成缺失戳。三条出路（删死记录 / 不显示 / 保持现状）待定。

## 轮二十八（2026-10-25）—— **I111 ⑥ 甲**（死行超量取样）/ **I112 ③ 甲**（容量只增不减定案）/ ⑨ injection 真空载窗口

用户这一轮的指令逐字：「按推荐方案执行」⇒ 按上一轮那张 3×3 编号表执行 ⑥ 甲、③ 甲、⑨ 甲。
**没有新界面**（只动 `semantic/vector_store.py` 一个读路径与台账），线框回环节不触发。

- **I111 ⑥ 甲：删过向量的库不再少给命中** —— `search()` 先数死行再超量取样：`dead = max(0, used - count())`、
  `want = min(top_k + dead, used)`，分块 `argpartition` 与堆都按 `want` 取，回查元数据**凑够 `top_k` 即停**；
  `delete_by_doc` 仍按设计只删 `vector_meta`、不动 `.npy`（碎片化代价照旧不背）。**代价**：每次查询多一条
  `SELECT COUNT(*) FROM vector_meta`，真库 196.8 万行实测 **25ms（温）／1,113ms（冷）**（冷态是首次触盘，只付一次），
  相对一次语义查询的秒级成本可忽略。**取值边界**：真库当前死行 **0**（`vector_meta` 1,968,159 行、
  idx 0…1,968,158 稠密、`used` 1,968,159），所以这条只在「删过文档 / 重嵌过」的库上才有实际效果。
- **守卫 + 坏法（当真红过）**：`tests/integration/test_vector_store.py::test_删过向量的文档不占满命中名额` ——
  三份各 1 页，中间那份与查询完全同向且被 `delete_by_doc` 删掉，`top_k=2` 必须拿回两份活文档；
  坏法（把 `want` 改回 `top_k`）真跑 **1 failed**，原文 `AssertionError: 死行吃掉命中名额：应为 2 条，实得 1`
  （`test_vector_store.py:155`），还原后该文件 + `test_vector_write_path.py` **23 passed**。
- **I112 ③ 甲：容量只增不减保持现状（代码不改）** —— 此刻的浪费有数：容量 2,097,152 行、已用 1,968,159（93.8%），
  空行 128,993 × 512B ≈ **63.0 MiB**，占 1 GiB 文件的 6.2%；换来的是「追加写、不重整、不重写整表」这条
  已验到 106 页/秒的写路径。**重新评估触发条件（任一命中）**：① 死行 `used - COUNT(*)` 超过 `used` 的 5%；
  ② 一次删除/重嵌掉 ≥ 1 万行；③ 容量翻倍到 4,194,304 行（文件 ≈ 2 GiB）—— 三条任一命中再做压缩/重整。

## 轮二十七（2026-10-25）—— **I112 甲+乙** / **I111 D+⑤** / **I109 ①** / ⑨ injection 最低负载整段 / **I110 的 2.1 倍定位（受控干预）** / 全量语义索引

用户这一轮的指令逐字：「勾选项距跟着你的建议来，⑨ injection 的真空载（CPU<10%）整段仍无读数；
⑩ I110 的 2.1 倍机制仍未定位；全量语义索引只跑过 20 份（占 10,991 的 0.18%）。也要处理执行」
⇒ 按上一轮写下的建议逐条执行。**没有新界面**（只动服务层、写路径、状态页与四段成本文案），线框回环节不触发。

- **I112 甲 + 乙（OPEN → MITIGATED，写路径的两条根因一起修）** —— 甲：`services/vector_service.py`
  `build_vectors` 从逐页 `embed_single`（batch=1）改成**一页一向量、一次前向吞 `BATCH_SIZE`（16）页**
  （取消按批检查、`monitor.advance(len(chunk))` 按批推进、**一批要么全写要么不写**）；乙：
  `semantic/vector_store.py` 从「每批整表 `np.save` + `np.vstack` 再复制」改成**容量式** `(capacity, 512)` int8
  （`DEFAULT_CAPACITY=1024`、扩容只翻倍、`vectors.npy.grow` → `os.replace`、真实行数每次从
  `MAX(vector_idx)+1` 现读、搜索/复制按 32,768 / 65,536 行分块、不做内存映射）。
  **真库复测**（`.probe_work/u27_real_throughput.log`）：6 份 / **1,174 页**，单份速率中位数 **106.07 页/秒**
  （最快 112.80 / 最慢 64.33）—— 对照旧逐页 **28.48** 是 **3.7 倍**，也超过批量微基准 72.86；
  `vectors.npy` 实测按 1,024 → 65,536 翻倍扩容（写到 42,115 行时仍是 65,536 容量，33,554,560 B）。
  守卫 `tests/integration/test_vector_write_path.py` **+225 行**（扩容后旧行仍读得出、跨实例写进去立刻看得见、
  停手后容量不缩）。
- **I111 D + ⑤（台账 ①②⑤ 三条销账）** —— D：`VectorStore._connect()` 打开 `PRAGMA foreign_keys=ON`
  （SQLite 默认 0 ⇒ `vector_meta.doc_id` 那条外键一直是死的），真库孤儿 **0**，新增
  `test_孤儿_doc_id_插不进元数据`；⑤：**先量再注入** —— `.probe_work/u27_embedding_two_instances.log` 实测第二只
  `EmbeddingService` 要多 **+36.4 MiB RSS／+9 句柄／+202 MiB VRAM／276ms 加载**（两实例输出 `max|Δ|=0.000e+00`），
  ⇒ `bootstrap` 只建一只注入三个消费者，配 `test_装配层_embedding_只有一份三个消费者共用`。
- **I109 ①**：状态页「重新读取数据库状态」挪到 daemon 线程（`_text_ready` + `finished` 两个信号），
  按钮即时变「正在重新读取… 已用 N 秒（界面可以继续用）」，失败追加异常原文并保留上次读数
  —— 那条 200s 级的全表读数不再冻住窗口。
- **⑨ injection 整段：跑到迄今最低负载档，仍不是真空载（不销账）** —— 9 条判定全绿、17/17 坏法被抓、
  `EXIT=0`、**WALL=732s（12 分 12 秒）**；但起跑 **CPU 25.5%**、PRE-RUN 40 秒 mean 18.1%，占用者是
  `Qoder CN.exe`（本会话编辑器，读 15.6 MiB/s）＋ `MsMpEng` ＋ 用户自己的 `WorkBuddy`/`DoubaoWork`
  —— 按规矩都不关，`CPU<10%` 这一行**仍然没有读数**。**顺带推翻一个隐含前提**：历史「空载」788.9 / 793.9s
  被当基准，本场在更忙的窗口里只用 732s（快 7–8%）⇒ injection 时长不朝「负载越低越快」走。
- **⑩ I110 的 2.1 倍定位：系统页缓存，不是负载／PRAGMA／并发** —— 仪器化背靠背两场
  （`.probe_work/u27_i110_pairs.py`，`_remember` 换空函数 ⇒ 真库只读）：**1,224.8s / 1,259.8s**，
  C4 **4.659／4.554s**（进程逻辑读 4,391.9 MiB，**设备读只有 10.1／15.7 MiB**）、C5 45.7／45.0s、
  C1 588.5／634.9s（36.8／36.6 MiB/s）、C11 579.5／571.1s（40.6 MiB/s）、`busy` 全程 0.9–1.4s。
  **受控干预**（`.probe_work/u27_i110_cache_pressure.py`）：同一进程同一条 C4 —— 194.20s → **4.56s** →
  把可用内存从 8,407 压到 **4,378 MiB** → **188.93s（设备读 5,121.6 MiB）** → 释放后 16.57s ⇒
  **41.5 倍只差缓存**。轮二十五那次「页缓存被排除」压的是单条扫描自身、没动可用内存，**撤回**。
  文案四处同步并改口径：「跨度没定位」⇒「跨度来自系统页缓存（同一条 C4 命中 4.6 秒 / 冷 189 秒）」；
  同时把仪器化两场的 **20 分 25 秒 / 21 分 0 秒**补进枚举 —— 旧下界 26 分 58 秒又被自家读数推前，
  三处区间改成「七场，20 分 25 秒 → 67 分钟」（只钉慢端就是重犯 I110 当初那个错）；
  几何复测 1024×720 标签高 100 → **112**、体检表仍 180、状态行底边 550 < 页高 676。
- **⑤ 全量语义索引：真库候选池跑到底（8,661 份 / 1,966,435 页 / 7 小时 30 分）** ——
  `.probe_work/u27_full_index.py`（不改产品代码，走 I112 甲 + 乙 之后的同一条写路径）：
  15:08:16 → 22:38:39、**27,022.9s（450.4 分）**、成功 **8,660**、失败 **0**、缺文件 **1**（`doc 93` 已不在磁盘上，
  跳过不标 missing）、**72.77 页/秒**、峰值 RSS **442.8 MiB**；备份在先的是
  `data/backups/backup-20261025-045656-v8`（04:56）。终值只读复核：`done 8,687 / na 2,304`、
  `vector_meta 1,968,159 行（idx 0…1,968,158，孤儿 0、重号 0）`、`vectors.npy 1,073,741,952 B
  = 2,097,152 行 × 512 B`（容量翻倍到位，已用 **93.8%**）、`done` 文档的 `text_pages` 合计 **1,968,159**
  ⇒ 向量条数与正文行数逐条相等；`catalog.db` 11,995,631,616 → **12,109,783,040 B**。
  **前两次折算作废**（19.27 小时 / 5.2 小时），全量实测 **7.53 小时**；写放大确认已消（整段无一次整表重写）。
- **收尾** —— 全量回归 `pytest tests/unit tests/integration tests/guards` ⇒ **802 passed / 1 skipped（178.34s）**；
  `tests/guards` 单独 **54 passed**；`scripts/precheck.py` 两步 **ALL GREEN**（54 守卫 + `docs-inject/guards` 9 判定）。
  收尾当场逮到两处：**I112 台账行在「处置」里又写了一遍加粗的 MITIGATED**（`ledger_check` 点名「状态字段有 2 个」，
  去粗后 6 passed）、**`docs/ISSUES.md` 与两处 docstring 的可用内存记成 4,329 MiB 而证据 JSON 是 4,377.9**
  （按证据改成 4,378）。一次性脚本按规矩**截成 0 字节**，证据 `.txt/.log/.json` 留在 `.probe_work/`（不入库）。

## 轮二十六（2026-10-25）—— **I109 丙+丁** / **I110 丙** + 安静档复测 / **I111 甲+丁** / **I63 ⑤** 真库语义索引真写（549 页）；新开 **I112**

用户这一轮的指令逐字：「⑤ 真库 vector_status 全 na（I63）｜⑦⑧ 等上面两条勾选｜⑨ injection 真空载读数｜
⑩ 27–57 分钟跨度的机制未定位。 跟进你的建议来」⇒ 按我自己上一轮写下的建议执行：⑤ 真做、⑨ 只在真空载下取、
其余三条按已落地的 丙/丁 收口。**没有新界面**（S7 只动了成本文案与状态页两条重查路线），线框回环节不触发。

- **I109 丙 + 丁（OPEN → MITIGATED）** —— `status_service.read_tasks` 加 `with_ocr_pages` 开关，关掉时
  `ocr_pages=None`、由 `TaskStatus._pages_text()` 一处写成「未现数（这条要全库扫描，按「重新读取数据库状态」才数）」，
  **不写 `0 页`**；`StatusPage` 拆成 `reload()`（完整，只有按钮走）与 `reload_progress()`（建窗路径 + 5 秒巡检走），
  `SettingsPage.reload_status()` 与 `StatusPage.__init__` 都换成轻版本，按钮 tooltip 明写要等几分钟。
  真库只读实测（`.probe_work/u26_i109_light_path.txt`）：11,995,631,616B 真库上建窗 + 一次巡检节拍
  **55 条语句 / 0.309s**，最慢两条 `documents` 状态 GROUP BY 15.8／14.0ms，**逐行扫 `text_pages` 全表的语句：无**
  —— 对照被摘掉的那一条 201.1／212.3／210.7s。丁 = 两条配对守卫进 `tests/integration/test_status_readout.py`
  （`set_trace_callback` 捞真执行的 SQL 逐条 `EXPLAIN QUERY PLAN`，出现不带 `USING` 的 `SCAN text_pages` 即红；
  反面那条证明按钮路径上**恰好**抓得到一条并显示 `0 页`），坏法编到 **p9 #70**。
- **I110 丙 + 安静档复测（OPEN → MITIGATED）** —— 确认框正文改读 `app_settings["db_check.last"].elapsed_s`
  （`health_panel.full_confirm_text` + `last_full_elapsed`），没有可比记录时明说没有、不拿快速档冒充；
  `FULL_COST` 改成「安静档四项（C1 18 分 16 秒 / C5 22 分 23 秒 / C11 19 分 16 秒 / C4 3 分 40 秒）+ 合计约 64 分钟
  + 两场历史 + 跨度没定位」，四处同源一并改（`db_check.py` docstring／`FULL_COST`／`health_panel.py` docstring／
  `UI-WIREFRAMES.md`），markdown 星号从纯文本 QLabel 里去掉（+几何复核、文案高 +14px、体检表仍 180）。
  复测（真库只读、不调 `_remember`）：十二项同场 **2,665.8s（44 分 26 秒）**（起跑 CPU 23.1%｜可用 4,437MiB，
  C1 1,096.0 / C5 1,343.0 / C4 220.4），C11 由 `.probe_work/u26_c11_only.py` 单跑补 **1,156.4s（19 分 16 秒）**
  ⇒ 两段合计 **3,822.2s ≈ 64 分钟**（**不是同一时刻，不许写成「同场 13 项」**）；零写核对 `db_check.last`
  仍是轮二十五的 `elapsed_s:3390.1`、库字节数未变。**2.1 倍的机制仍未定位**（残留 乙 不销账）。
- **I111 甲 + 丁（OPEN → MITIGATED）** —— `bootstrap` 先建一只 `VectorStore` 再分别注入 `SemanticSearchService`
  与 `VectorService`，`search_service` 构造加可选参数（不注入仍自建，`gates/stage6.py` 两处独立调用照旧）；
  守卫两条进 `tests/integration/test_vector_write_path.py`（同进程只许一只实例 / 建完当场搜得到不必重启，
  都用桩 embedding 绕开模型）⇒ 连同原 7 条 **9 passed**。临时库四段实测 + 三条坏法逐字见台账。
  `vector_store.py:9` 的「内存映射」改回「整份读进内存」（实测 `np.save` 撞 `OSError: [Errno 22]`），
  `ARCHITECTURE.md` 同口径更正。
- **I63 ⑤ 真库语义索引真写（第一条真向量落进 11GB 真库）** —— `.probe_work/u26_semantic_pilot.py`，顺序固定：
  装模型（`.probe_work/models/bge-small-zh-v1.5` → 产品根，0.36s / 23,903,394B）→ **备份在先**
  （`backup-20261025-045656-v8`，70.1s / 11,995,631,616B）→ 小样本真写（`seed=20261025`，池 3,273 份点名 20 份）：
  **549 页全部 done｜写入 549 条｜19.28s = 28.48 页/秒**，`vector_status {'na': 10991}` → `{'done': 20, 'na': 10971}`，
  **同一只 `SemanticSearchService` 当场 3/3 命中来源**（0.6323 / 0.7396 / 0.7041），另起新进程仍读回
  `count() 549` / `vectors.npy` 281,216B。主记录 10,991 与正文 1,975,611 前后未变；`VERDICT: ALL GREEN`。
  探针自报 `vectors.npy 0B` 是**探针取错路径**（`paths.root` vs `data/`），以 §4.37 与重启复核为准。
- **新事实入账 **ISSUES I112**（OPEN，等勾选，未实现）** —— 写路径 28.48 页/秒 对只读批式 72.86 页/秒 = **2.56 倍**
  （去掉首份冷启动仍 2.30 倍）；根因 `vector_service.py:209` 逐页 `embed_single`（batch=1）+
  `vector_store.py:167-175` 每份整表 `np.save`（`:170` 再 `vstack` 复制一遍）。按最大量级反算：终值 ≈ 964.8 MiB
  （G8 红线 1,200MiB 的 80%）、累计写 ≈ 5.06 TiB、`vstack` 瞬时 ≈ 1.9 GiB、全量折算 **19.27 小时**。
  方案甲乙丙丁已列，**推荐 甲 → 乙**。
- **⑨ 真空载 injection：本轮没测到（如实记「没有读数」）** —— 13:00 两次采样整机 **CPU 43.8%**，
  占用者是 `DoubaoWork` 123.6% + `WorkBuddy` 68.8% + 另两只 `DoubaoWork`，都不是本项目进程、按规矩不替用户关；
  CPU<10% 的窗口本轮没出现，**上一轮 CPU 32.4% 的低负载场不许拿来当空载**。
- **收尾** —— p9 **70/70**、p10 **45/45** 各自 `ALL GREEN`（p9 新坏法是「把全库正文扫描放回 5 秒巡检」）；
  全量回归 `pytest tests/integration tests/unit tests/guards` **794 passed / 1 skipped（181.38s，定稿场）**、
  `scripts/precheck.py` 两步 **9 判定 ALL GREEN**（54 守卫 + `docs-inject/guards`）。收尾当场逮到并修掉三处：
  **I109 台账行的行尾竖线在上一轮补丁里丢了**（`tests/guards/test_ledger_shape.py` 当场点名 `I109（5 格、行尾未闭合）`）、
  **一处探针脚本写成裸文件名**（`tests/guards/test_doc_pointers.py` 精确点名 `CHANGELOG.md:30`，补 `.probe_work/` 前缀后 37/37）、
  **G1 冷启动在 55–78% 负载下 1.805–2.137s 假红**（分段 `import_to_run_s 1.932 / assemble 0.269 / window 0.117`，而本轮 diff 里一行 import 都没有 ⇒ 负载档位，负载回落后连跑两次通过）。
  台账 110 → **112 行**（I111 与 I112 都是本轮新开），I109／I110／I111 三条转 MITIGATED。一次性脚本按规矩**截成 0 字节**，
  证据 `.txt/.log/.json` 留在 `.probe_work/`（不入库）。

## 轮二十五（2026-10-25）—— 把 §4.35 欠的四条证据补完（**产品代码一行未改**），新开 **I109 / I110**

用户这一轮的指令逐字：「全库档 13 项没在界面里真跑过；四条门禁红的绿来自定点复跑、与那场 26 判定不是同一时刻；
injection 整段未空载复跑；体检面板只有 offscreen 几何证据。 按你建议执行」。
四条都是**证据欠账**，不是功能欠账 ⇒ 本轮没有任何一行 `src/` 改动，也没有新的界面（不触发线框回环节）。

- **⑥ 真机（非 offscreen）几何与像素** —— `.probe_work/u25_screens_health.py` 去掉 `QT_QPA_PLATFORM`
  （报告里 `platform=windows`、中文真渲染），在隔离种子库上把 S7 两档**用 `QTest.mouseClick` 点产品自己的按钮**
  各跑一遍：**31 条判定 ALL GREEN**，快速 10 行 / 全库 13 行都 0 红，翻页不跳高 `([417,415],[417,415])`，
  五张截图 md5 各异，且「翻回设置页」那张与首张设置页 **md5 逐字节相同** —— 1甲 的「翻回原样」第一次有像素证据。
  判据有牙两条现证：`data_root` 指错 ⇒ `VOID_wrong_dataroot_report.json` RED；拆掉 `[库体检…]` 按钮 ⇒
  `VOID_inj_no_toggle/` RED（5 条不成立）。种子库跑在 `work_dir`，`work_dir_removed=true` ⇒ 真库这轮没被这一场碰过。
- **②③ 四条 G1 同源红并进同一条命令的一场上全绿** —— `gates/final.py --only regression --only coldstart
  --only e2e --only injection`：02:59:27 → 03:15:32（965s ≈ 16 分 05 秒），起跑 CPU 32.4%｜可用 3,809MiB，
  **13 条判定 0 红｜`VERDICT: ALL GREEN`**（regression 802 passed / 1 skipped、coldstart 1.046s、e2e 11 条、
  injection 760.1s）。injection 整段 9 条探针第一次在低负载下同段全绿，抓坏法合计 **225 条**。
  **诚实边界**：CPU 32.4% 是**低负载场**，不是真空载场（CPU<10% 的整段读数仍然没有）；`FULL_COST` 等文案一处没改，
  **G1 的 1.5s 一处没动**。`injection_inflight` 由门禁自己在整段全绿后删掉，收尾 `git status` 只剩台账两行。
- **① 真库全库档 13 项走界面路径真跑（两场）** —— `.probe_work/u25_real_full.py`：真窗口 S7 → 点按钮翻页 →
  点「全库体检」→ 确认框（正文即 `FULL_COST`）→ 后台线程跑完 → 铺表 → `_remember()` 回写。
  run1 **26 分 58 秒｜13 行 0 红**，但四张截图 md5 全同 ⇒ `before_and_after_differ` 等两条不成立，
  **整场判 RED**、改名 `real_full_report_run1_no_visual.json` 只留计时证据（根因：上一场漏了点翻页按钮，
  按钮在没露面的那一页上照样点得动、体检照样跑完，只是画不出东西）。run2 **56 分 30 秒｜17 条判定 ALL GREEN**，
  四张图 md5 各异，滚到底 `last_row_rect=[105,133]｜on_screen=true` ⇒ 末行 C11 真画在屏上。
  两场的 `{docs 10,991｜pages 1,975,611}` 前后一致 ⇒ 业务表零写入。
  **这一轮写了真库两处产品自己的键**：`db_check.last`（run1 首写 1,618.2s，run2 覆盖 3,390.1s）与
  `ui.last_nav_page="monitor"`（run2 收尾那一刻）；两条都能在界面里改回，**是否复位等用户说**。
- **新事实两条入账（**ISSUES I109 / I110**，等勾选，未实现）** —— I109：S7 一在屏就把无索引的
  `SELECT count(*) FROM text_pages WHERE source_kind='ocr'` 放在**主线程**上跑，真库单条 201.1／212.3／210.7s，
  触发点是建窗路径与那条 5 秒巡检定时器（与 `main_window.py:261-264` 判重页已成文的处理相矛盾），
  建议 **丙 + 丁**。I110：`FULL_COST` 写死「约 57 分钟与约 67 分钟」，而同库同按钮相邻两场实测 26 分 58 秒与
  56 分 30 秒（C4 33×、C5 25×，其余九项 0.0–3.9s，且负载方向是反的），页缓存与并发同表扫描两条机制
  都做了实验并被排除 ⇒ **机制未定位**，建议 **丙**（确认框改读 `db_check.last.elapsed_s` 报「上次实测」）。
- **读数口径纠正（历史不改写）** —— §4.35 G 段把 p12 的 C3 记成「每盘 1,537,579ms × 6 盘」，实际那六行的 ms 是
  同一个循环的累计值（逐项总和 5,581s 与该场 5,599.4s 吻合）；四个慢项读数有效，只有「× 6 盘」是误读，纠正写在 §4.36。
- **收尾** —— `scripts/precheck.py` 本轮两次两步全绿（54 守卫 10.81s + 门禁 `docs-inject/guards` 9 判定 ALL GREEN）；
  台账 110 行、逐条走到 **I102** 补了一条 2026-10-25 同场读数（状态 CLOSED 不变）；一次性脚本按规矩**截成 0 字节**，
  证据类 `.txt/.json/.png` 留在 `.probe_work/`（不入库）。

## 轮二十四（2026-10-24）—— S7「库体检」按钮（#198 · 1甲 2甲 3甲 4甲）

用户这一轮勾了 **1甲 + 2甲 + 3甲 + 4甲**，并让其余门禁照跑。四件定案各落一处：
**就地翻页**（S7 下半区第二页，不另开窗口）、**两档**（快速 10 项 / 全库 13 项）、
**只报证据**（没有重跑/修复按钮）、**只存上次时间 + 四个计数**（明细不落盘）。

- **取数层 `db/repositories/health.py`（新）** —— 十四项检查的 SQL/PRAGMA 唯一落点（架构守卫要求
  SQL 只在 repositories 里），口径与 `tests/probes/p12_consistency.py` 一致；`TEXT_LEGAL` /
  `PARSE_LEGAL` / `OCR_LEGAL` / `VECTOR_LEGAL` 四个合法值集合只写在这一处，**p12 反过来 import 它**
  （原先探针自带一份，那是第二个口径）。读快照走 `mode=ro`，不写真库。
- **服务层 `services/db_check.py`（新）** —— `run(mode)` 是唯一取数与判定口：快速档 C0/C2/C4(行数)/
  C6/C7/C8/C9(读数)/C10/C12/C13 十行，全库档插入 C1、C5 并把最慢的 C11 放最后；每条单独计时，
  **异常变成带原文的红行**而不是带走整场（`failure_report()` 兜住完全没跑起来的情况）。
  `_remember()` 只写 `ts/mode/total/red/readings/elapsed_s` 六个键到 `app_settings['db_check.last']`。
  构造零成本，真正取数只在用户点按钮时发生；`expected_version` 取迁移目标版本（C0 才是问"水位停在
  本版没有"）。线程在 `finally` 归还连接。
- **界面 `ui/pages/health_panel.py`（新）** —— `threading.Thread(daemon=True)` + 跨线程 `Signal(object)`
  回主线程（不用 QThread：关窗时不会打 "Destroyed while thread is still running"）；两颗按钮运行中同时
  禁用，`QTimer` 每 500ms 只刷新已用时长。全库档点下去先弹 57–67 分钟成本确认。表格是**第 9 张**
  `set_table_columns` 的表（定宽 220/90 + 读数列 stretch + tooltip 回读），单行行高。
- **S7 `ui/pages/settings_page.py`** —— 下半区改 `QStackedWidget`（设置页 / 体检页），标题栏右端
  `[库体检…]` 就地翻页、`[← 返回设置]` 翻回；「上次体检」行放在**体检页内**而不是标题栏 ——
  标题栏多一行会把下半区最低高度顶高 36px，720 窗高下上半区只看得见 13 行
  （`test_S7上半区按内容给高…` 实测红，故改位置；改后返回 15 行以上）。
- **守卫同步** —— `tests/integration/test_ui_tier.py` 两处 `seen == 8` → **9**（全站表格数），
  `ui/table_layout.py` 与 `docs/ARCHITECTURE.md` 的"八张表"文案同步；`p12` 的合法值改为 import。
- **回归与坏法** —— `tests/integration/test_db_check.py` 新增 **8 条**（快速十行零红 / 坏根键点名 C13 /
  0 字节快照在全库档判红且 C11 只体检最新一份 / 上次体检恰好六个键 / 异常变红行 / 没跑起来也给原文 /
  设置页翻页跑快速体检并回写 / 全库档审计成本文案），首次即 **8 passed**；受影响守卫与集成测试
  **62 passed**。五组坏法真注入全部红并点名后还原：C13 恒绿、C11 跳过 0 字节、`finished` 断线、
  `_remember` 多写 `detail` 键、临时加第 10 张表（两条 `seen` 守卫同时红）。
- **真库跑了一次产品的快速档（只读，真库零写）** —— 11GB 真库（主记录 10,991 / 正文 1,975,611）
  用服务层 `_specs` + `_one` 取数判定：**10 行｜9 通过 + 1 读数（C9）｜0 红｜整场 11,755ms**
  （最慢三项 C2 4,333 / C12 3,798 / C4 3,461ms）。**故意不调 `_remember()`** ⇒ 真库 `app_settings`
  里没有多出 `db_check.last`。这条读数**推翻了线框里「秒级」那句成本说明**（那是没测过的估计）：
  `QUICK_COST` 改成「11GB 真库实测约 12 秒」，`FULL_COST` 改成同口径两场的「约 57 分钟与约 67 分钟」，
  线框 §S7 补页、`health_panel` 状态行、`test_db_check.py` 那条断言（`"秒级"` → `"约 12 秒"`）同步。
- **其余 10 段门禁（一场后台命令，20:45:17 → 22:54:54 = 7,776.8s ≈ 2h09m）** ——
  `26 条判定｜4 红｜1 段未跑（guards，已由预检两步覆盖）`，末行 `VERDICT: RED（4 条未过）`。
  四条红**同源于 G1 冷启动**（不是四个问题）：regression（801 passed / 1 failed，唯一红仍是
  `test_进程级冷启动实测符合G1约定`）、coldstart 3.554s、e2e 2.454s、injection 的 p9 **基线**里含同一条 G1
  （其后 8 条探针全绿）。`soak / package / g2 / consistency / ocr / ui-inject` 六段当场全绿。
  起跑负载 CPU **69.5%**、可用内存 **1,333MiB**、`TOTClient-Win64-Shipping.exe` **4,296MiB**。
- **四条红逐条定点复跑（负载压下去之后；与上面那场不是同一时刻，不谎称同场全绿）** ——
  p9 **抓到 69/69 条坏法｜ALL GREEN**；e2e 段 **ALL GREEN**、冷启动 **1.266s**；coldstart 段五次读数
  **1.298 / 1.456 / 1.506 / 1.523 / 2.400s**（同一套代码，抖动全在 1.5s 线附近）；全量回归第三场
  **802 passed / 0 failed / 1 skipped（228.7s）｜ALL GREEN**（起跑 CPU 52.3%）。
- **真根一致性（consistency 段 5,599.4s ≈ 93.3 分）** —— p12 注入自检 **21/21 + 口径边界 1/1**、
  p14 仪表 **四种坏法 × 五种口径全绿**、真根 **19 条｜红 0｜未验 0**（库 **v8**、`running 0`、
  `done 10,941 / failed 75`）。四个慢项比轮二十二那场同向变慢 8–24%（C1 1,200,867 / C5 1,541,084 /
  C11 1,036,524 / C4 259,539ms）而**行数一字未变** ⇒ 差额是机器负载，所以成本文案把两场读数都写出来，
  不挑对自己有利的那一个。
- **负载事实** —— 全量回归首场 **800 passed / 1 failed / 1 skipped（335.02s）**，唯一红仍是
  `test_进程级冷启动实测符合G1约定`（2.094–2.603s；当场 CPU 74–84%，`window.ready` 的
  `import_to_run 1.826s` 占 78%）—— 与 **ISSUES I25 / I102** 同源的负载绑定项；G1 单条 10 次连测
  **1.217–2.0s、9/10 次 ≤1.5s**，拆分 `import_to_run 1.059–1.178s`（占 87%）/ `assemble 0.045–0.055s` /
  `window 0.113–0.121s` ⇒ 本轮新增的三张模块**不在启动路径上**（自测 `health_panel import 46ms`、
  `HealthPanel 构造 14ms`）。G1 阈值一处没动。

---

## 轮二十三（2026-10-24）—— 先拆再写（RUNLOGS 切册 + p13 拆分）、收尾预检一键脚本、真库小样本语义实跑

用户这一轮勾了 **1 + 4 + 5②**，另加一句「本轮三条红全是自伤，处理了」。三条红（裸探针名 ×2、
`--data-root` 传深一层）的第二条腿就是「先拆再写」与预检脚本 —— 拆掉会超线的文件，
把上一轮踩过的坑变成起跑前的一次判定。

- **A · 先拆再写** —— ① `tests/probes/p13_soak.py` 687 行 + `tests/probes/p13_soak_inject.py`
  142 行：反向注入整段搬出，`main()` 里延迟导入，顶层不反向依赖（否则两模块成环）。
  ② `docs/VERIFICATION-RUNLOGS.md` **1,113 → 372 行**，§4.17–§4.25 九块整批逐字搬进
  `docs/VERIFICATION-RUNLOGS-ARCHIVE.md`（757 行，**D-059**）：节号序列不改、标题数守恒
  （搬前 17 = 分册 9 + 活册 8）、跨文件指针只改文件名且同一行不许混两个册的引用（共改 16 行）。
  分册同时进 `tests/guards/test_doc_pointers.py` 的 `SELF_DEFINING` 与 `LEDGER_DOCS`。
  ③ 顺带修掉**守卫自己的**可扩展性缺陷：`_resolve_md()` 每解析一个引用就 `rglob` 一次全仓，
  把 `.venv`（16,393 文件 / 1,424 目录）走一遍 —— 三个守卫文件同跑 **>18 分钟挂死**，
  `faulthandler` 堆栈点名的就是它。改成 `os.walk` 剪枝**建一次索引**：doc_pointers
  **9 passed / 5.35s**、guards 全量 **54 passed / 30.56s**。④ `test_subprocess_encoding.py`
  里那条 `p13_soak.py:416` 的过期行号改成不带行号的描述（拆分后它挪到 465，行号一挪就是假指针）。
- **B · 收尾预检一键脚本** —— `scripts/precheck.py`：两步固定顺序（`pytest tests/guards` →
  `gates/final.py --only docs-inject --only guards`），子进程显式 `encoding="utf-8"`，
  任一红即停，末行唯一 `VERDICT:`。实测 **PASS 1/2（54 passed, 39.11s）+ PASS 2/2（门禁 9 条
  ALL GREEN）→ VERDICT: ALL GREEN**，总 ~60s。接线由 `tests/guards/test_precheck.py` 三条盯着：
  argv 必须带上两个 `--only`、假红 runner 只许跑 1 步且 VERDICT 为红、假绿 runner 必须打出
  `PASS  1/2` / `PASS  2/2` —— 后两条就是坏法注入（改坏 argv 接线或吞掉红步，测试立刻红）。
- **C · 真库小样本语义实跑** —— `tests/probes/p25_semantic_sample.py`：真库以 `mode=ro` +
  `pragma query_only=1` 打开，`random.Random(20261024).sample(300)` 抽 `text_status ∈ {native,
  mixed}`、`page_count 1–60` 的 300 份，每份前 7 页 → **300 份 / 1,709 页 / 651,964 字**。
  嵌入走产品的 `EmbeddingService`（bge-small-zh int8，DirectML）：加载 **1.66s**、
  **23.46s / 1,709 页 = 13.7 ms/页 = 72.86 页/秒**、RSS **130.3 → 281.7 MiB**；
  全量 **1,975,611 页 ÷ 72.86 = 7.53 小时**、int8 **0.94 GiB** / fp32 **3.77 GiB**。
  召回（top-10）：**语义按文档 19/20、按页 16/20｜全文自然句 0/20｜全文关键词 12/20｜互补 16/20**；
  4 条按页错的里有 3 条是**同一份文档的别的页**（277/286/332），只有 346 连文档都没进。
  三条关键词 0 命中是**带空格的两词串**（产品按口径把整串当一个短语，不拆词）—— 口径而不是坏。

**两处探针自己的 bug（先修再报数，旧读数作废）**：① 命中判定写的是
`[d, p] in [(d, p)]` —— **列表 vs 元组恒为 False**，所以首跑全文通道恒 0；② 2 字关键词
（如「塔罗」）在 trigram 下恒 0，产品口径本应走 LIKE（`MIN_FTS_CHARS=3`），探针却一律进 FTS。
直接查库反证过：`竞品分析` 能命中 `(255,1)` 第 2 名、`数据的本质` 命中 `(245,1)`。
另：上一场报的「全量 47.77 小时」是 **120 页小样本被首跑预热摊薄**（11.49 页/秒），
本场 1,709 页把预热摊薄掉后是 7.53h —— **以本场为准，上一场那个数作废**。

- **D · 收尾回归（第一场是负载场，不许记成全绿）** —— 全量回归第一场 **793 passed / 1 failed /
  1 skipped（466.21s）**，唯一红 `test_进程级冷启动实测符合G1约定` **5.439s**（单跑仍 3.593s）；
  同场 `TOTClient-Win64-Shipping.exe` **365% CPU / 2.9GiB**、可用内存 **2.1GiB** —— 本轮没动启动路径。
  按既有口径 deselect 后 **793 passed / 1 skipped / 1 deselected（216.29s）**；负载降下来单条复跑
  **1 passed，冷启动 1.055s**（`import_to_run 0.797s｜assemble 0.179s｜window 0.079s`）。

**口径**：查询仍是**我模拟的** 20 条，不是用户手里那 20 条真查询，所以 **ISSUES I11 不销账**；
按页严格算 16/20 **低于** D-035 的 18/20 门槛，不许拿 19/20 的文档级读数宣布 G15 绿。
G1 那行的绿来自**负载撤掉后的单条复跑**，不是第一场同一时刻的读数。

---

## 整链补跑（二十二·续）—— 2026-10-24 · 12 段 35 判定：整链 32/35，3 条红定点复跑后全绿

`gates/final.py --all --data-root "C:/Users/lavie/AppData/Local/PdfArchiver"`，整链那场 14:38:22 → 15:09:14
（1,852.6s），**32/35 绿**；三条红都不是产品缺陷：① 回归红在同一份文档 —— §4.32 又留下 **9 处裸探针名**，
「台账旧文件名」46 > 37（补 `.probe_work/` 前缀，上限未动，复跑 37 处 ALL GREEN）；② p16 同根因，
复跑 11 条（8 坏法 + 3 对照）全绿；③ p12 真根红是我把 `--data-root` **传深了一层**（探针自己会拼 `data/`），
改传基目录后真根 **19/19、0 红 0 未验**（C11 整库体检 961s）。回归复跑 **791 passed / 1 skipped / 289.71s**。
其余九段：冷启动 1.045s、e2e 11 条、注入 p9 69/69 与 p10 45/45、p15 36 条、OCR 三条、4 分钟 soak
（60 点 / 空洞 2.0s / 积压峰 18 排空 1.0s）、package 400.0MiB、G2 **P95 326.0ms**。
**口径**：定点重跑只替换那三行，不许把整链写成 35/35；另 14:36 起跑的第一场因块缓冲误杀子进程已作废，不回填读数。

## 勾选轮（二十二）—— 2026-10-24 · 用户本人十屏全过（**I17 CLOSED**）+ **I108 甲**：S4 详情区补空态提示；顺带被守卫逮到轮二十一的 4 处裸探针文件名

轮二十一交出的十屏核对清单，用户逐屏看完给出「10 屏全过」（含 05「状态框需框内滚动」与
09「未选批次时详情为空」两处取舍）。同一轮同时勾了 **I108 甲**：09 的空表要有一句话解释，
但**不做默认选中**——乙方案会让「撤销选中批次」一进页面就可点，而撤销是写磁盘的不可逆动作。

- **A · I17 CLOSED（用户本人逐屏）** —— `screens_r18/I17_CHECKLIST.md` 十项全部勾「过」，
  05 的滚动取舍与 09 的空表取舍都确认接受。至此 I17 的三层证据齐了：自动断言 + 我逐张看图 +
  **用户本人观感**；台账那一行补了 2026-10-24 的勾选追记，状态维持 **CLOSED**。
- **B · I108 甲（一处界面改动）** —— `ui/pages/operations_page.py` 在「操作项详情」标题与表格
  之间加 `item_hint` 一行「先点上面一条批次，详情才会列出它搬了哪些文件」；新增
  `_sync_item_hint()`，在 `reload()` 与 `_on_op_selected()` 之后统一同步
  `setVisible(op_table.currentRow() < 0)`。选中批次后提示撤掉，不占版面、不盖住真详情。
  `reload()` 仍然**不设默认选中**（撤销按钮的可用性保持由用户主动点击决定）。
- **C · 守卫与坏法** —— `tests/integration/test_archive_execute_ui.py` 新增
  `test_没选中批次时详情区写明先点批次`：断言 `reload()` 后批次表 1 行但 `currentRow() < 0`、
  详情 0 行、提示可见且文案含「先点上面一条批次」；选中后详情 1 行、提示不可见。
  **坏法真注入**（把 `setVisible(...)` 改成恒 `False`）→ `1 failed` 并点名
  `test_archive_execute_ui.py:346`；还原后 **16 passed**。
- **D · 十屏重拍（15 项断言）** —— `.probe_work/r18_screens_real.py` 加
  `operations_item_hint` 断言后整包重跑：`platform=windows`、10 张非空且互不相同，
  `report.json` **15 项 ALL GREEN**；09 屏读得到那句提示（`.probe_work/_r21_09_hint_crop.png`）。
  `contact_sheet.png` 按新 md5 重建（1980×3698）；`I17_CHECKLIST.md` 十项改「☑ 过」并注明
  **勾选时看的是 14 项那版、09 随后按甲多了一行**，不把两者的时间顺序含混过去。
- **E · 守卫先报：轮二十一的 §4.31 写了 4 处裸探针文件名** —— `docs-inject` 的
  「台账旧文件名 ≤ 37」当场红（41 → 38 处），多出来的全是 `.probe_work/` 下那些
  `.probe_work/r20_plan_repro.py` / `.probe_work/r20_ink_probe.py` / `.probe_work/_i107_backup.py` / `.probe_work/r21_contact_sheet.py`
  —— 写成裸名就等于宣称「仓库里该有这些文件」。修法是逐个补 `.probe_work/` 前缀
  （守卫的 `PY_EXEMPT_PREFIX` 白名单），**上限 37 一个字没动**。
- **F · 回归 / 门禁 / 台账** —— 全量回归 **791 passed / 1 skipped / 0 failed（291.54s）**，
  比轮二十一 +1（C 段那条新用例）；`docs-inject + guards` **9 条 ALL GREEN（本次未跑 10 段）**；
  台账 **108 行｜I1–I108 连续｜CLOSED 87｜MITIGATED 20｜OPEN 0｜WONTFIX 1｜
  结构不合格 1 行（上限 1）：I35**。本轮 **I108 CLOSED**，OPEN 回到 **0**。

---

## 修复轮（二十一）—— 2026-10-24 · I17 逐屏核对逮到 **I107**（表格把「反斜杠 + CJK」路径画成 `C…`）并全站修掉；十屏重拍、清单措辞按实现改

轮二十把十屏交给用户勾选。交出去之前我自己逐屏过了一遍，08（S3 归档预览）的「目标路径」三行
全部只剩一个 `C…` —— 用户根本看不出这份文件会被搬到哪。同一次核对还发现 07 / 09 两屏的
**清单措辞与实现不一致**（备份表没有「大小」列、批次表没有时间列），05 的两块任务读数在状态框
的滚动线以下。本轮把真缺陷修掉、把清单改成对着截图能逐字核对的措辞。

- **A · 复现与定位（四个对照）** —— 用产品路径复现（`bootstrap` → `MainWindow` →
  `archive._load_documents()` → 勾 3 份 → `_generate_preview()`），不改数据、不另写渲染：
  同一张计划表里 `C:\Users\lavie\AppData\Local\Temp…` 画成 `C…`，而 `C:/Users/...` 正斜杠串
  正常；`setWordWrap(False)` 与 `ElideMiddle` 两种改法都恢复；单元格宽度 260px、文本长度
  99/103 字符均正常写进模型。结论：**单行行高 + `ElideRight` 对「反斜杠 + CJK 混排的整段
  不可断词」会退化成只画首字符**，不是列宽或取数问题（`.probe_work/_plan_repro_full.png` /
  `_plan_nowrap.png` / `_plan_elidemid.png` / `_plan_slashes.png` / `_plan_mix.png`）。
- **B · 修复（一处中心改动）** —— `ui/table_layout.py::set_table_columns()` 加
  `table.setWordWrap(False)`，覆盖全站 8 张表（archive 2 / backup 2 / library 1 /
  operations 2 / dedup 1）。8 张表都是单行行高，没有一张靠换行表达内容。
- **C · 守卫与坏法** —— `tests/integration/test_ui_tier.py` 新增
  `test_每张表都是单行行高_不许开自动换行`：逐屏切页、`reload()`、`findChildren(QTableWidget)`
  后断言 `wordWrap() is False` 且扫到 **8** 张。**坏法真注入**（注释掉那行）→ `1 failed`，
  点名 `test_ui_tier.py:307` 与具体页面；还原后 **21 passed**。离屏平台**不复现**这条绘制
  退化（无 CJK 字形，wrap True/False 的 ink 宽都是 248px），所以守卫钉的是开关位，绘制结果
  由真桌面截图复核 —— 这一半写进 docstring，不冒充。
- **D · 十屏重拍 + 拼图 + 清单** —— `.probe_work/r18_screens_real.py` 原样重跑（真 windows
  平台、`%TEMP%` 合成语料、10 张 1400×880）：`report.json` **14 项 ALL GREEN**，10 张非空且
  互不相同；08 的目标路径读作 `C:\Users\lavie\AppData\Local\Temp…`。`contact_sheet.png` 按新
  md5 重建。`I17_CHECKLIST.md` 改为可逐字核对的措辞：05 明写两块任务读数**要在状态框内向下滚动**；
  07 改成「文件名 / 版本 / 修改时间」（无大小列）；08 明写目标路径修前是 `C…`、修后是什么；
  09 改成「ID / 类型 / 状态 / 总数 / 完成 / 失败」并写明**详情表要先点中批次**；另注明
  01/02/10 的横向滚动条是 I48/I61 的定宽口径。
- **E · 新开 I108（等勾选，不动代码）** —— 09 的「操作项详情」在未选中批次时是一张没有任何
  提示的空表。甲＝加一行「先点一条批次」的空态文案；乙＝`reload()` 后默认选中最新一条。
  两种都要过界面确认。
- **F · 回归 / 门禁 / 台账** —— 全量回归 **790 passed / 1 skipped / 0 failed（289.17s）**；
  `docs-inject + guards` **9 条 ALL GREEN（本次未跑 10 段）**；台账 **108 行｜I1–I108 连续｜
  CLOSED 86｜MITIGATED 20｜OPEN 1｜WONTFIX 1｜结构不合格 1 行（上限 1）：I35**，本轮 **I107
  CLOSED**、**I108 OPEN**。文件长度：`213 个 .py / 31 个 .md｜临近线 6 份`，`test_ui_tier.py`
  711（余 89）新进临近表；`p13_soak.py` 仍是最紧的 **794（余 6）**。

**I17 仍未 CLOSED**：十屏要用户本人逐屏打勾；自动断言与我自己的看图都不能替代。
（2026-10-24 追记：用户当天逐屏勾选 **10/10 过**，并选了 I108 甲 —— 见上一节「勾选轮（二十二）」。）

---

## 勾选轮（二十）—— 2026-10-24 · **24 小时 soak 按用户选择缩到 12 小时并跑满**（9/9 全绿）/ p12 增 `--c11-deep` / consistency·injection 跨轮 A/B / I17 十屏核对包；途中逮到并修掉 I106（探针 churn 撞 Windows 文件锁）

用户原要求 24 小时连续 soak。前两场分别在本机外部重启（13h40m）与探针自身的删除动作撞上
Windows 文件锁（17h05m）处被切断；第二场是**探针缺陷**，不是产品故障，修掉后按用户勾选
②「缩到 12h 并如实写明边界」，第三场按 12 小时跑满。本轮文档统一写「**12 小时已验、24 小时未验**」。

- **A · 12 小时连续 soak（`--minutes 720`）** —— **9/9 全绿、0 红**：采样 **21,067 点｜跨度 43,201.2s｜
  最大采样空洞 2.6s**、churn **2,880 轮**、`churn_unlink_skipped=0`。S1 rc=0；S2 `crash.log 0 字节 /
  Traceback 0`；S3 **12→12**（峰 17）；S4 **321→321**（峰 323）；S5 **75.3 → 75.6MiB（+0.3）**、
  中位 **76.4**、全程 3.0–120.6、G8 余量 1,079.4；S6 **峰值 17 / 排空 7.1s / `{'done': 12711}`**；
  S7 **5810/5810**（已标缺失 1,110）；S8 **2 份 / 3,546KiB / 当前 7,032 行**；S9 p12 14 条 0 红、未验 0
  （`.probe_work/round20_soak_720min_r1.log` / `p13_soak_result_720min_r1.json` / `round20_soak_720min_app.log` /
  `round20_soak_720min_state.log`）。`state.log`：`startup.begin` 2026-10-23T08:58:35Z → `shutdown`
  2026-10-23T20:59:53Z（43,201.2s）。
- **A′ · 两场 24 小时未跑满（如实留档）** —— 第一场 **05:31:45 → 19:11:39（57%）**：被
  `optionalfeatures.exe` / `winlogon` 发起的外部重启切断，应用 `app.log` 到 19:11:39 仍在正常索引、
  无 Traceback。第二场 **19:21:59 → 12:27:07（71.2%，17h05m）**：探针 `_churn` 删除刚投放的
  `soak_add_61500_2.pdf` 时撞上应用正在读该文件，Windows `PermissionError [WinError 32]` 冒到 `main()`
  把整场切断；产品侧 `app.log` 正常写到 12:27:07、无 Traceback、`crash.log` 不存在
  （**ISSUES I106**，已 CLOSED）。第三场 24h 在 **4h28m**（12:28:46 → 16:57:00）按用户 ② 主动中止，
  读数作废、现场保留。
- **B · I106 修复 · churn 删除走 `_unlink_retry`** —— `tests/probes/p13_soak.py` 新增
  `_unlink_retry(path, attempts=5, delay=0.2)`：5 次 ×0.2s 重试仍失败就**跳过并计数**，不再让
  `PermissionError` 冒到 `main()`；结果 JSON/打印新增 `churn_unlink_skipped`。复现验证 held-open
  0.4s（3 次）→ 跳过、after-close → 成功、released-mid-retry → 成功
  （`.probe_work/r20_unlink_repro.log`）。12 小时场 `churn_unlink_skipped=0`。
- **C · p12 增 `--c11-deep`（全部快照整库体检）** —— 默认口径不变：只对**最新**快照跑整库体检，
  其余快照仅开库读版本（I98 乙边界）。新开关让每份快照都跑 `integrity_check` + 外键 + 空值检查；
  夹具 10 份快照、故意损坏 `older-snapshot.db`：默认 **C11 绿**（按口径不展开旧快照），
  `--c11-deep` **红并点名** `older-snapshot.db：integrity_check=*** in database main *** /
  2nd reference to page 9 / Page 3 is never used / NULL value in documents.path_key`，
  7 条自检 **VERDICT: ALL GREEN**（`.probe_work/r20_p12_deep_e2e.log`）。p12 主体拆出
  `p12_inject.py`，主文件从 800 行降到 576 行。
- **D · consistency / injection 跨轮快慢 A/B** —— 同一台机背靠背、顺序跑、不并行：injection
  **A 852.0s / B 867.5s（+1.8%）**；九条探针单条最大差 +10.6%。与轮十八整链的 **674.2s** 相比，
  九条**一起**慢到 **1.18–1.43x（均值 1.28x）**，没有一条单独变慢 —— 结论是**整机档位**
  （负载 / 内存压缩 / 夜间频率），不是探针代码变化（`.probe_work/r20_inject_ab_summary.txt`）。
- **E · I17 十屏核对包** —— 用轮十九的真桌面 10 张（1400×880，含暗色）拼 `contact_sheet.png`，
  另出 `I17_CHECKLIST.md`（逐屏「看什么 / 过 / 不过 / 备注」）。**UI 代码零改动，故未重拍**；
  这仍是**给你本人勾选**的材料，I17 不因此关闭（`.probe_work/screens_r18/`）。
- **F · 真根漂移补账 + p12 真根复跑 19/19** —— 先做只读漂移速查（6 个监测根、约 22 分钟）：
  C/E/F/G 零漂移；**D 根盘上 91 / 库内 90**（漏索引 2 份微信 PDF + 1 条约 341 页的 PDF 已被**跨盘
  移到 H 根**、旧记录没打缺失戳）；**H 根盘上 1857 / 库内 1856**（就是那份被移过来的 PDF；跨盘复制
  换了 inode，`_adopt_renamed` 认不出）。全部走产品路径：`scan.reconcile_path` × 3 建记录并抽正文
  （doc **10992** 29 页 / **10993** 7 页 / **10994** 341 页、入库 338 页），`mark_missing` 给 doc 93
  打戳。收尾库读数：**documents 10,991｜text_pages 1,975,611｜空正文 0｜待办 0**。p12 真根复跑
  **19/19 全绿、未验 0**（05:30:41 → 06:43:39，4,378s）：C2 10,991；C3 六根 **68 / 91（标缺失 1）/
  1967 / 5352 / 1655 / 1857** 各相等；C4 **1,975,611 / 1,975,611、漏 0 / 残留 0**；C5 1,975,611 页
  六项自洽；C9 running 0（done 10,941 / failed 75）；C11 最新快照 11,686,936KiB@v7 整库体检
  **939,804ms**、ok；C12 超页 0（`.probe_work/p12_real_root_r20.log` / `.json`）。
  **计时口径**：C3 六行共享同一段函数耗时 **975,995ms**，不是六段相加。
- **G · 回归 / 门禁 / 文档** —— 全量回归 **789 passed / 1 skipped / 0 failed / 0 error（285.82s，最终树）**；
  `docs-inject + guards` **9 条 ALL GREEN、本次未跑 10 段**（`.probe_work/round20_regression_final.log` /
  `round20_docs_guards.log` / `round20_docs_guards_final.log`）；台账 **106 行｜I1–I106 连续｜CLOSED 85｜MITIGATED 20｜OPEN 0｜WONTFIX 1｜
  结构不合格 1 行（上限 1）：I35**，本轮 **I106 CLOSED**。文件长度守卫：`扫了 213 个 .py 与 31 个 .md｜
  临近线 5 份`，最紧 `p13_soak.py` **794（余 6）**（p12 拆出 `p12_inject.py` 后从 800 降到 576，
  `p12_consistency.py` 不再是临近项）。

## 分册：更早的轮次在两册

2026-10-28 这一册再切一刀（**D-059** 第 4 条的再切线：活册 > 600 行）。切前 1178 行，
`勾选轮（十九）` … `勾选轮（七）` 共 **631 行**逐字搬进 [`docs/CHANGELOG-ARCHIVE-2.md`](CHANGELOG-ARCHIVE-2.md)；
`勾选轮（六）` 及更早仍在 [`docs/CHANGELOG-ARCHIVE.md`](CHANGELOG-ARCHIVE.md)。
标题数守恒（搬前 26 个轮次标题 = 活册 13 + 分册二 13），一条没改、一条没删。

写新一轮一律追加在本文件；本文件超过 600 行就把最早的一整批轮次整轮迁进**第二分册**（**D-059**）。
本文件切册当时 **550 行**；写完轮三十三这一条后 **599 行（余 1）** —— 下一轮开篇先切册再写。
