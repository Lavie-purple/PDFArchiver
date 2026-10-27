# 变更日志

按阶段记录。版本号口径：阶段 0–7 全部走完并通过发布门禁才叫 `1.0.0`；在此之前一律 `0.x.y`，
且 `x` = **已完成的最大阶段号**（允许跳号：没做的阶段在条目里点名，不许让人以为 0–x 全通过）。
**本文件只记实际做过并验证过的变更**，未落地的写在 `ROADMAP.md`，不写在这里。

---

## 轮三十五（2026-10-28）—— I118 甲：按监测根重扫做成固定入口；桌面那 1 份扫描件走产品路径入库（向量按 I116 甲 如实拒收）

用户这一轮的指令逐字：「跟进你的建议来」—— 我给的推荐是**选项 1**：建 I118 的固定入口 + 只补桌面那 1 份；
`H:\Others Software\` 那 4 份软件自带样例 PDF **不动**（既不入库、也不排除）。两件都按推荐做完。

- **甲 · 新入口 `scripts/rescan_roots.py`（197 行）** —— 只走产品入口、零裸 SQL：
  按根用 `ScanService.scan_root`，点名单文件用 `ScanService.reconcile_path` + `IndexService.index_document`，
  `--vectors` 走 `VectorService.request_vectors`。**默认是只读预演**（打印 `RESCAN: DRY-RUN`，一行不写），
  加 `--apply` 才写库。两个筛选各自解决一个真问题：`--only <子串>` 只挑匹配的根；
  `--paths <文件…>` 只补点名的几份 —— `C:\Users\lavie` 整棵子树会走进 AppData，全根扫不现实，所以真库这一步
  只能走单文件路。排空不自己起线程：`ctx.start_background()` 交给产品的 worker，靠
  `counts_by_kind_state()` 轮询 `queued/running` 归零，超时打 `RESCAN: RED` 而不是偷偷拖长（默认 30 分钟）。
  末行用 `RESCAN:` 前缀是**刻意**的 —— `VERDICT:` 是 `gates/*` 引用脚本的专用收尾语，守卫只认那些脚本。
- **甲 · 测试 `tests/integration/test_rescan_roots_script.py`（4 passed / 5.75s）** —— 按根重扫把新落盘文件
  补进库并建好正文（断言 `fts_status=done`、正文页数 2）｜不带 `--apply` 一个字不写｜`--only` 不匹配的根一根都不碰｜
  `--paths` 只索引点名的那一份。**三条坏法真注入**（`.probe_work/u35_inject_rescan.py`）：重扫换成空报告 ⇒ 2 条红；
  把 `--only` 的过滤整段摘掉 ⇒ 1 条红；把 `--paths` 分支改成死码 ⇒ 1 条红；还原后 md5
  `9a006b3f047bf9e97ab71551b5f99d86` 与原文一致、4 条复绿。
- **真库写入（用户点名的那一份）** —— 先跑只读预演：6 个监测根逐个列出、桌面那份报「库里没有」、末行 `RESCAN: DRY-RUN`。
  再 `--apply --vectors --paths …`：`[file] added｜doc 11002｜索引 30/30 页 text=none fts=done 186ms`。
  只读复核：`documents 10,997 → 10,998`、`text_pages 1,976,208 → 1,976,238`（+30）、
  `vector_meta 1,969,088` **一字未变**、队列分布与写入前逐字相同（没有新增 queued 行）。
- **这份是扫描件，向量被如实拒收** —— 30 页 `source_kind='native'` 的正文合计只有 **504 字**（12–39 字/页，
  是页码与页脚，不是正文）⇒ `text_bearing_rate 0.0`、`text_status='none'`、`ocr_status='pending'`。
  于是 `--vectors` 打印 `点名 1 份｜该建 0 份｜新增任务 0 条｜没有可搜的正文`、`跳过 {'not_searchable': [11002]}` ——
  这是 **I116 甲** 定下的入场券（有没有可搜的正文）在干活，不是失败。
  **口径边界要写清**：全文**已经搜得到**它（30 行正文进了 `content_fts`，每页是幻灯片标题，
  如 `BDS 炒饭会 候选边界`）；建不了的是**向量**，因为 `text_bearing_rate 0.0`（判据是「去空格后 ≥40 字的页」占比，
  见 `parsing/classify.py`）⇒ `text_status='none'` ⇒ 入场券不放行。要让它**语义**搜得到得先「送去识别」（30 页 OCR），
  本轮不做：用户的指令只到「补索引」。
- **那 4 份维持不动**：`H:\Others Software\` 下迅捷 PDF 工具自带的 `使用手册 / 常见问题` 属软件样例，
  按选项 1 不入库 ⇒ `C3·H:\` 仍会数出「盘上有、库里没有 4 个」，所以 **I118 不整条销账**（入口已交付并验证，
  余下是数据处置待勾选：索引 / 给 H:\ 根加两条排除 / 维持红）。
- **p12 真根复跑**：读数与逐条判定见 `docs/VERIFICATION-RUNLOGS.md` §4.46。

## 轮三十四（2026-10-28）—— I115 甲：跨卷搬移按文件事实认改名；I117 甲：C5 给 OCR 页级标记行豁免；删掉 2 条残留 `vector:queued`；2 份微信 PDF 走产品路径入库

用户这一轮的指令逐字：「① I115 跨卷搬移根因（推荐甲）｜② I117 C5 给 OCR 页级标记行豁免（推荐甲）｜
③ 两条 vector:queued（甲 删 / 乙 开应用让 worker 跑完 / 丙 只记）｜④ C3·D 那 2 份微信 PDF 重扫。
都跟进你的建议来」。四件都按推荐项做完。

- **① I115 甲 · 认改名补一条按文件事实的旁路** —— `services/scan_service.py` 把 `_adopt_renamed` 拆成两条路：
  `_renamed_by_inode`（同卷改名，`(device_id, file_id)`，原逻辑原样搬过去）与 `_renamed_by_facts`
  （Windows 跨卷搬移是「复制 + 删源」、inode 换了，退回 `(name, size_bytes, mtime_ns)` 认）。
  两条路共用同一条硬条件：候选**恰好一条**、且**旧路径已经不在磁盘上**；多于一条或任一项不等，一律不认 ——
  「不猜」这条规则没有因为多开一条旁路而放宽。仓储侧新增 `documents.missing_by_facts(name, size, mtime)`：
  只查 `missing_since IS NOT NULL`、`ORDER BY id LIMIT 2`（取两条只为分辨「恰好一条」）。
  认出来走的是 `adopt_path`，**主键不变** —— 分类、标签、备注、正文索引原地保留。
- **① 测试** —— `tests/integration/test_scan_service.py` **38 passed**，新增 4 条：跨卷搬移换 inode 后认回同一
  主键（并断言 `documents.count()==1`、`missing_since` 清掉、`fts_status` 仍是 `done`）｜只差 mtime｜只差 size
  （参数化 2 条）｜文件事实对上**多条**缺失记录时不猜。坏法真注入两次：把兜底整个摘掉 ⇒ 跨卷那条红；
  把「恰好一条」放宽成「取第一条」⇒ 那份三份同名（丙盘）的红。撤掉还原全绿。
- **② I117 甲 · C5 只豁免「OCR 页级完成标记」** —— `tests/probes/p12_consistency.py` 的 `c5_pages()` 把空串行
  拆成两半数：`source_kind='ocr' AND char_count=0 AND ocr_version IS NOT NULL` 是**标记行**
  （`texts.ocr_versions_of()` 靠它判 `reused`，删了那几页会重烧一遍），其余空串才是零信息垃圾。
  读数格式改成「空串 N 行（其中 OCR 页级标记 M、真垃圾 K）」，**只有 K > 0 判红**。
  判据没有整体放宽：`--inject` 里补了一条坏法「原生正文页写成空串（豁免不覆盖它）」。
- **② 测试** —— 新文件 `tests/integration/test_consistency_c5.py` **2 passed**；坏法两向都真做过
  （删掉豁免 ⇒ 「标记的那条」红；把豁免放宽成「任何空串都算标记」⇒ 「垃圾那条」红）。`p12 --inject`
  **22/22 条坏法 + 口径边界 1/1 ALL GREEN**。
- **③ 甲 · 单事务删 2 条 `vector:queued`** —— `.probe_work/u34_clear_vector_queue.py`：先用
  `%TEMP%\pdfarchiver-u34-vector-queue-backup\catalog.db` 那份 **12,113,543,168 B** 快照（00:06 做的，
  尺寸与删除前的库逐字节一致），再一个事务删 `kind='vector' AND state='queued'` 的两行
  （11019 → doc 10995、11020 → doc 10997，`attempts 0`）。只读复核（`.probe_work/u34_clear_vector_queue.json`）：
  `processing_jobs 11,019 → 11,017`、两条 id 都不在、`vector:queued` **0 行**、外键孤儿 **0**、
  doc 10995 / 10997 仍是 `vector_status=done` ⇒ `DELETE GOOD`。
- **④ · 2 份微信 PDF 走产品路径入库（零裸 SQL）** —— `ctx.scan.reconcile_path()` →
  `IndexService.index_document()` → `VectorService.request_vectors()`：`dify安装攻略20261020.pdf` **1/1 页**、
  `互联网流量集中、平台变现与商家经营成本研究.pdf` **32/32 页**，两份都 `text=native / fts=done`（doc 11000 / 11001）；
  向量回执「点名 2 份｜该建 2 份｜新增任务 2 条」，随后 `vector:done 2`。文档 **10,995 → 10,997**，
  正文 **1,976,175 → 1,976,208 页**（+33 = 1 + 32，与页数对得上），向量 `done 8,692 → 8,694`。
  自检索 **4/4 拿自己的正文查回 rank 1**（`1/1` @0.9296 与 `3/3` @0.9268 / 0.9309 / 0.9329）。
  **据实记一条自己的失误**：`.probe_work/u34_rescan.py` 的等待循环调了**不存在**的
  `status.queue_counts()`（`grep -rn "def queue_counts" src/` 零命中），脚本会白睡 40 分钟；
  向量任务跑完后我停了进程，收口证据改用独立只读脚本 `.probe_work/u34_selfcheck.py` 补，
  JSON 里也写明了这件事。
- **p12 真根复跑（71 分钟，19 条 / 2 红）** —— `.probe_work/u34_p12_real.log`，末行 `VERDICT: RED（2 条未过）`。
  三件待验的都转绿：**C3·D:\ 96 / 96**（轮三十三是盘上 96 / 库里 94）、**C5「空串 6 行（其中 OCR 页级标记 6、
  真垃圾 0）」**、**C9 `running 0`＋`{'done': 10,944, 'failed': 75}`**（队列里再没有 `vector:queued`）。
  另两处**新红，都是数据漂移、不是代码**：`C3·lavie` 盘上 69 / 库里 68（漏 1 份
  `20260812第196回 在AI时代，用AI完成弯道超车.pdf`，文件 mtime **02:11**）；`C3·H:\` 盘上 1,860 / 库里 1,857
  （漏 4 份，全在 `h:/others software/xjpdfeditor/` 与 `…/xunjiepdfconverter/sample/` 下，那两个目录的时间戳
  是 **02:04**）—— 两份都落在轮三十三那一场链（01:56 收）之后。**没有为凑绿重扫，也没有动任何阈值**；
  这两根要不要补索引等勾选（本轮新开 **ISSUES I118** 记这一类）。
- **台账**：I115 / I117 **OPEN → CLOSED**，两格都贴了实测读数、坏法与销账条件。
- **文档**：本文件按 **D-059** 第 4 条先切册再写 —— 活册 **599 → 338 行**，`轮二十四` … `勾选轮（二十）`
  **262 行**逐字搬进 [`docs/CHANGELOG-ARCHIVE-2.md`](CHANGELOG-ARCHIVE-2.md)（**647 → 914 行**，排在
  `勾选轮（十九）` 之前），标题数守恒 **29 = 9 + 20**；`docs/VERIFICATION-RUNLOGS.md` 追加 §4.45；
  `docs/ISSUES.md` 两行销账 + 新开 I118。

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



## 分册：更早的轮次在两册

2026-10-28 这一天第三次切（**D-059** 第 4 条的再切线：活册 > 600 行）。切前 599 行，
`轮二十四` … `勾选轮（二十）` 共 **262 行**逐字搬进 [`docs/CHANGELOG-ARCHIVE-2.md`](CHANGELOG-ARCHIVE-2.md)（排在 `勾选轮（十九）` 之前，时间上更近）；
`勾选轮（十九）` 及更早仍在同一册，`勾选轮（六）` 及更早仍在 [`docs/CHANGELOG-ARCHIVE.md`](CHANGELOG-ARCHIVE.md)。
标题数守恒（搬前全部轮次标题 = 活册 + 分册二 + 第一分册，一条没改、一条没删）。

写新一轮一律追加在本文件；本文件超过 600 行就把最早的一整批轮次整轮迁进**第二分册**（**D-059**）。
