# 实测读数 · 逐轮收尾册（承接 `docs/VERIFICATION.md` §四 的节号序列）

**这一册装什么**：`docs/VERIFICATION.md` §四 里**每一轮收尾都要追加一块**的那批读数（4.17 起）。
**那一份装什么**：环境与依赖版本、探针结论索引、以及只在阶段收尾时才涨的 4.1–4.16。

**为什么切在这一刀**（**ISSUES I71** 勾选**乙**，2026-10-18）：`tests/guards/test_file_size.py` 给台账定的线是
`MD_LIMIT = 1_200` 行，而 `docs/VERIFICATION.md` 收尾复测已到 **1,184** 行（只剩 16 行，连一句追注都装不下）。
增速的实测来源正是这一类块：勾选轮（五）**+75**、勾选轮（六）**+165**（那一条是逐字粘贴门禁与三份探针输出造成的）。
**节号序列与原文连续、内容逐字未动** —— 分册只改「它在哪一份里」，不改「它是第几块」，也不改任何一个数字。

**取数与复跑口径**：见 `docs/VERIFICATION.md` §七（那一份是口径的出处，本册不另立第二份）。

---

**§4.17–§4.25 已整批迁入 `docs/VERIFICATION-RUNLOGS-ARCHIVE.md`**（**D-059**，2026-10-24 轮二十三点算）；
**§4.26–§4.37 已整批迁入 `docs/VERIFICATION-RUNLOGS-ARCHIVE-2.md`**（**D-059** 第 4 条，2026-10-27 轮三十二点算）。
两批都是原文逐字搬走、节号不变，本册只留 §4.38 起。上面那句「这一册装什么」说的是本册的由来，
现在装的是**最近几轮**；更早的十七块请翻两个分册。

### 4.38 轮二十七（2026-10-25 13:0x 起）· **I112 甲+乙** / **I111 D+⑤** / **I109 ①** / ⑨ injection 最低负载整段 / **⑩ I110 的 2.1 倍定位（受控干预）** / 全量语义索引

用户这一轮的指令逐字：「勾选项距跟着你的建议来，⑨ injection 的真空载（CPU<10%）整段仍无读数；
⑩ I110 的 2.1 倍机制仍未定位；全量语义索引只跑过 20 份（占 10,991 的 0.18%）。也要处理执行」。
⇒ 按我自己上一轮写下的建议逐条执行：**⑩ 走乙**（背靠背第三／四场仪器化 + 受控干预）、**I112 甲 → 乙**
（上一轮的推荐顺序）、**I111 D 与 ⑤**、**I109 ①**、**⑨ 只在 CPU<10% 取**（本轮取到迄今最低档，仍不是真空载）、
**⑤ 全量语义索引真跑**。**没有新界面**，线框回环节不触发。

**A · I112 甲 + 乙：写路径的两条根因（`src/` 三份 + `tests/` 一份 + 两份存储口径文档）**：
- **甲 · 批量前向**：`services/vector_service.py:175-222` 的 `build_vectors` 从「逐页 `embed_single`（batch=1）」
  改成**一页一向量、一次前向吞 `EmbeddingService.BATCH_SIZE`（16）页**（`chunk` 切片 → 一次
  `self.embedding.embed([page.body for page in chunk])`）；取消检查按批、`monitor.advance(len(chunk))` 按批推进；
  **一批要么全写要么不写**，不留半批。
- **乙 · 容量式 `.npy`**：`semantic/vector_store.py`（+337/−… 见 `git diff --stat`）把「每批整表 `np.save` +
  `np.vstack` 再复制一遍」换成 `(capacity, 512)` int8：`DEFAULT_CAPACITY=1024`、**扩容只翻倍**
  （先写 `vectors.npy.grow` 再 `os.replace`，中途崩掉留下的还是原来那个完好文件）、**真实行数每次从
  `vector_meta` 的 `MAX(vector_idx)+1` 现读**（不缓存 ⇒ 跨实例立刻可见）、搜索与复制分块走
  `SEARCH_CHUNK_ROWS=32_768` / `COPY_CHUNK_ROWS=65_536`；**不做内存映射**（Windows 下 `mmap_mode="r+"` 后
  原地 `np.save` 撞 `[Errno 22]`，自己没关映射时 `os.replace` 撞 `[WinError 32]`）。
- **守卫**：`tests/integration/test_vector_write_path.py` **+225 行**（扩容后旧行仍读得出、跨实例写进去立刻看得见、
  停手后容量不缩），配 `vector_meta` 的 `PRAGMA foreign_keys=ON`（见 B）。
- **顺带量的搜索端换算**（`.probe_work/u27_scale_variants.log`，只记录不改代码）：四个等价写法 top1 **全等 2.7059**
  （最好一场 8.14 / 6.10 / 6.86 / 6.50s），**不换算那条 top1 变成 343.6539** ⇒ 量化换算不能省；
  换成「`asarray(f32)` 后 `q/127`」最快，但那是搜索热路径，不属于本轮写路径范围，留给搜索延迟单独一轮。

**B · I111 D + ⑤（台账 ①②⑤ 三条就这一轮销账）**：
- **D · 外键打开**：`VectorStore._connect()` 执行 `PRAGMA foreign_keys=ON` —— SQLite 默认是 0，所以
  `vector_meta.doc_id` 那条外键在产品里**一直是死的**；打开后真库孤儿行 **0**，
  并加 `test_孤儿_doc_id_插不进元数据`（不打开就绿不了）。
- **⑤ · 单只 `EmbeddingService`（先量再注入）**：`.probe_work/u27_embedding_two_instances.log` 逐行量第二只的代价 ——
  基线 RSS 39.4 MiB／206 句柄／VRAM 1,136 MiB；第一只加载 +16 条 ⇒ 257.9 MiB／419／1,376（678.1ms）；
  **第二只加载 +16 条 ⇒ 294.3 MiB／428／1,578（276.4ms）**，即 **+36.4 MiB RSS、+9 句柄、+202 MiB VRAM、276ms**；
  两实例输出 `max|Δ|=0.000e+00`（形状 (16,512) 各一）。⇒ `bootstrap` 只建一只、注入三个消费者
  （`SemanticSearchService` / `AIClassifyService` / `VectorService`），守卫
  `test_装配层_embedding_只有一份三个消费者共用`；`tests/integration/test_ai_classify_service.py` +35 行跟着换注入。

**C · I109 ①：状态页「重新读取数据库状态」挪出 GUI 线程**：`ui/pages/status_page.py` **+83 行** ——
daemon `threading.Thread` + `_text_ready = Signal(str, str)` + `finished`；点下去按钮立刻变
「正在重新读取… 已用 N 秒（界面可以继续用）」（1 秒 `QTimer` 刷新），失败把**异常原文**追加到读数后面并保留上一次的读数
（不伪装成功、也不清空）。`tests/integration/test_status_readout.py` **+95 行**。

**D · ⑨ injection 整段：跑到迄今最低负载档，但仍不是真空载**（`.probe_work/u27_injection_idle.log` /
`u27_injection_idle_summary.txt`，2026-10-25 14:01 → 14:14）：
- **整段真跑了**：**9 条判定全绿、17/17 条坏法被抓到、`EXIT=0`、`WALL=732s（12 分 12 秒）`**，末行
  `VERDICT: ALL GREEN` 两处，`injection_inflight` 由门禁自己删掉（整段全绿的唯一条件）。
- **起跑窗口不是 CPU<10%**：PRE-RUN 40 秒采样 **mean=18.1%｜median=15.2%｜max=49.5%**，门禁自己的起跑读数
  **CPU 25.5%｜可用 8,613MiB｜最吃内存 `WorkBuddy.exe 430MiB`**；跑完 14:17 再采 60 秒 **26.2–31.0%（mean 26.9%）**。
  逐进程指名（10 秒窗口）：`Qoder CN.exe` pid 19204 **持续读 15.6 MiB/s**、pid 4004 **持续写 15.9 MiB/s**
  （本会话的编辑器/索引进程，不是本轮探针），外加 `MsMpEng.exe`、`WorkBuddy.exe` / `DoubaoWork.exe` ——
  按规矩都不替用户关，所以「CPU<10%」这一档在本机当前状态下不可达。
- **这条读数推翻一个隐含前提**：历史「空载」读数 **788.9 / 793.9s** 一直被当基准，而本场 mean 18.1%
  （比那两场的口径高得多）只用 **732s**，快 **7–8%** ⇒ injection 的时长**不朝「负载越低越快」的方向变**，
  「必须真空载才算数」这个前提本身站不住。但按项目口径，`CPU<10%` 这一行**仍然没有读数**，不销账。

**E · ⑩ I110 的 2.1 倍已定位：系统页缓存装不装得下这次扫描（不是负载、不是 PRAGMA、不是并发）**：
- **仪器化背靠背两场**（`.probe_work/u27_i110_pairs.py` → `.log`／`.json`，末行 `VERDICT: MEASURED`；
  `svc._remember` 被替换成空函数 ⇒ 真库只读，`db_check.last` 一字未动）：run1 合计 **1,224.8s**、
  run2 **1,259.8s**（起跑 CPU 28.6%／13.3%，可用 8,657,967,152／8,626,507,776 B）。逐项连同设备读：
  **C4 4.659／4.554s** —— 进程逻辑读 **4,391.9 MiB**，设备读只有 **10.1／15.7 MiB**；
  **C5 45.712／45.035s** —— 26,139.0 MiB 对 **519.0／274.7 MiB**；
  C1 588.527／634.887s —— 设备读 21,649.7／23,220.1 MiB ⇒ **36.8／36.6 MiB/s**；
  C11 579.519／571.051s —— 设备读 23,546.5／23,357.4 MiB ⇒ **40.6 MiB/s**；
  `busy` 两场全程 **0.9–1.4s**。⇒ 两场都落在「快档」（C4 ≈4.6s），**快档不是偶然，是缓存装得下的常态**。
- **产品连接的 PRAGMA 读数**（同一次两场里现取）：`cache_size=-2000`（2 MB）、`mmap_size=0`、`temp_store=0`、
  `journal_mode=wal`、`synchronous=2`、`page_size=4,096`、`page_count=2,928,621`（**11.2 GiB 库**）⇒
  2 MB 页缓存装不下、mmap 是关的 ⇒ 能装多少完全由**系统页缓存**决定。
- **受控干预**（`.probe_work/u27_i110_cache_pressure.py` → `.json`，末行 `VERDICT: MEASURED`；同一进程、同一条
  `_c4_full`、同一份库）：**A1 194.196s**（设备读 5,051.3 MiB，起点可用 8,384MiB —— C11 那 23 GiB 扫描刚把缓存挤掉）
  → **A2 4.557s**（设备读 2.0 MiB）→ 触碰 4 GiB 匿名页把可用压到 **4,377.9 MiB**（安静档那场是 4,437MiB）
  → **B 188.925s**（设备读 5,121.6 MiB）→ 释放后 **C 16.57s**（618.8 MiB）。
  **B / A2 = 41.5 倍**，两次之间只差「可用内存还剩多少」。四次读数串完全相同
  （`正文 1,975,611 行｜花名册 1,975,611 行｜漏索引 0｜花名册残留 0`）。
- **撤回轮二十五那条「页缓存被排除」**：那次压的是**单条 201s 扫描自身**（现态 201.1／冷 212.3／热 210.7s，±3%），
  **没动可用内存**；而轮二十五那两场的可用内存 **2,197／3,656 MiB 都小于 C4 的 4.4 GiB 工作集** ⇒ 那次排除不作数。
  历史记录不改写，撤回写在这里。
- **剩下的边界（不销账）**：磁盘本身也慢 —— 设备读吞吐两档实测 **20–41 MiB/s** 而 `busy` 只 0.9–1.4s，
  瓶颈在**每次 4 KiB 页读的往返**而不是 SSD 带宽；这一层没拆开，也不影响「缓存决定快慢」这条结论。
- **文案四处同步**：`services/db_check.py` 模块 docstring 与 `FULL_COST`、`ui/pages/health_panel.py` docstring、
  `docs/UI-WIREFRAMES.md` S7 硬条件段；`tests/integration/test_db_check.py` 的
  `test_全库档的确认框先给成本` 把 `"跨度没定位"` 换成 `"系统页缓存" + "4.6 秒"`（**能骗过它的坏法**：把这句改回
  「跨度没定位」即红 —— 本轮真注入过一次，`1 failed` 后还原成 `10 passed`）。台账 `ISSUES I110` 残留 ① 改写成
  「乙 已做完」，并留下磁盘吞吐这条边界。
- **新快端不放过**：仪器化两场的 **20 分 25 秒 / 21 分 0 秒**把原先写的「跨度 26 分 58 秒 → 67 分钟」下界又推前了
  —— 这正是 I110 当初被开的那个错（拿过时的极端值当区间）。⇒ 三处区间口径一起改：`db_check.py` docstring
  「测过五场，跨度 26 分 58 秒 → 67 分钟」⇒「测过七场，跨度 **20 分 25 秒** → 67 分钟」、
  `health_panel.py` docstring「最快的一场 26 分 58 秒」⇒「**20 分 25 秒**（轮二十七脚本仪器化）」、
  `UI-WIREFRAMES.md` 两处「四场 / 五场」⇒「七场」；`FULL_COST` 那句枚举改成「脚本四场 20 分 25 秒、21 分 0 秒、
  约 57 分钟、约 67 分钟」，测试加断言 `20 分 25 秒` + `21 分 0 秒`（只钉慢端就是重犯旧错）。
- **几何复核**（`.probe_work/u27_cost_geometry.py`，末行 `VERDICT: ALL GREEN`；文案 450 字）：
  **1024×720** 标签高 **100 → 112**（+12）、体检表仍 **180**、状态行底边 **550 < 页高 676**；
  **1280×800** 标签高 **72 → 86**（+14）、表仍 180、底边 **604 < 756**；页上无滚动容器（`range=0` 那条判据不适用）。

**F · ⑤ 全量语义索引：真库 8,661 份候选跑到底（7 小时 30 分）**（`.probe_work/u27_full_index.py` →
`.log`／`u27_full_index_status.json`，末行 `VERDICT: DONE`；不动产品代码，走的就是 I112 甲 + 乙 之后的同一条写路径）：
- **起止**：15:08:16 → 22:38:39，**27,022.9s = 450.4 分（7 小时 30 分）**。**备份在先**：
  `data/backups/backup-20261025-045656-v8`（04:56，早于这批写 10 小时）+
  `pre-migration-0008-20261020T122144.db`（11,967,422,464 B）。
- **结果**：候选 **8,661**｜成功 **8,660**｜失败 **0**｜缺文件 **1**（`doc_id 93`，文件已不在磁盘上，按规矩跳过、
  不标 `missing`）｜嵌入 **1,966,435 页 = 写入 1,966,435 条向量**｜**72.77 页/秒**｜峰值 RSS **442.8 MiB**
  （G8 红线 1,200MiB 的 37%）。
- **终值复核（只读，跑完后现查）**：`vector_status {'done': 8,687, 'na': 2,304}`（合计 10,991）；
  `vector_meta` **1,968,159 行，idx 0…1,968,158 连续**、孤儿 **0**、重号 **0**；
  `vectors.npy` **1,073,741,952 B = 2,097,152 行 × 512 B**（容量翻倍到位，**已用 1,968,159 = 93.8%**）；
  `done` 文档的 `text_pages` 合计 **1,968,159**、空正文 **0** 行 ⇒ **向量条数与正文行数逐条相等**。
- **一处 ±1 对账（记下来而不是抹平）**：本轮写 1,966,435 + 轮二十六／二十七小样本已写 1,723 = **1,968,158**，
  库里是 **1,968,159** ⇒ 差的这 1 条落在小样本那 26 份里（它们的 `text_pages` 比当时写下的向量多 1 条），
  **不是本轮重复写**：本轮每份只处理一次、`na → done` 一步到位。终值口径以「向量 = `done` 文档的正文行」为准。
- **成本三次估算的对照（前两次作废，只留实测）**：轮二十六按 20 份外推 **19.27 小时**、轮二十七按 6 份
  106 页/秒折算 **5.2 小时**，全量真跑 **7.53 小时** ⇒ 小样本偏悲观 2.6 倍、大样本偏乐观 1.45 倍。
  **写放大已消**：450 分钟里没有任何一次整表重写（容量式追加），峰值 RSS 也远低于红线。
- **库体积**：`catalog.db` 11,995,631,616 → **12,109,783,040 B（+114,151,424 B ≈ +108.9 MiB**，全在
  `vector_meta` 与 `documents.vector_status`）；`vectors.npy` **1 GiB** 单独一份文件。
- **候选池之外**：`text_status='none'` **2,229** 份与 `failed` **74** 份没有正文可嵌，跑完仍是 `na`
  （加上 doc 93 ⇒ `na` 终值 2,304）—— 这不是失败。**I63 ⑤ 至此从「20 份 = 0.18%」变成「候选池全跑完」**。

**G · 全量回归与门禁：一条命令 802 passed／1 skipped；两处自伤都是守卫先报的**：
- **回归**：`pytest tests/unit tests/integration tests/guards -q` ⇒ **802 passed / 1 skipped in 178.34s**（exit 0）。
  轮二十六基线 794 passed / 1 skipped ⇒ 净 **+8**；`git diff tests/` 逐行数是 +9 个 `def test_` 与 1 个**原地改签名**
  （`test_探测器在按钮路径上真的抓得到那条扫描` 补 `qtbot`），8 = 9 − 1。
- **守卫单跑**：`pytest tests/guards -q` ⇒ **54 passed**（预检里 11.28s、复跑 10.44s）。
- **两处自伤都是守卫先报的（不是我看出来的）**：
  1. **台账格子结构**：预检 15:12 那场 `VERDICT: RED（1 步未过）`，原文
     「`I112 的状态字段有 2 个（要正好 1 个…）`」—— I112 处置格里写了 `状态 OPEN → **MITIGATED**`，`**` 被算成第二个状态词。
     改成不加粗后 `tests/guards` **54 passed**。
  2. **成本文案有牙**：把 `FULL_COST` 里那句「跨度来自系统页缓存（同一条 C4 命中 4.6 秒 / 冷 189 秒）」
     改回「跨度没定位（**ISSUES I110**）」⇒ `test_全库档的确认框先给成本` **1 failed, 9 deselected**；
     从 `.probe_work/u27_db_check.bak` 还原 ⇒ **10 passed in 1.85s**（备份文件用完即删）。
- **数值自伤一处（读数不一致，守卫照不到）**：`db_check.py`／`UI-WIREFRAMES.md`／`ISSUES.md` 里写的压测后可用内存
  是 **4,329 MiB**，而 `u27_i110_cache_pressure.json` 记的是 **4,377.9 MiB** ⇒ 四处一并改成 **4,378**。
  这条守卫抓不到（是跨文件的同一条读数），记在这里当反例。
- **预检两场**（`scripts/precheck.py`，`.probe_work/u27_precheck.log` / `u27_precheck_final.log`）：
  **15:12** 那场 `合计 2 步｜红 1`、`VERDICT: RED（1 步未过）` —— 红的就是台账形状那条（I112 双加粗），
  另有一条**既存**的「结构不合格 1 行（上限 1）：I35（3 格、行尾未闭合）」在限额内、不算新红；
  **终场**（本章全部文档改完之后）`54 passed in 13.28s` + `docs-inject/guards` **9 条判定全绿**
  ⇒ `合计 2 步｜红 0`、末行 `VERDICT: ALL GREEN`（10 段 SKIP 照旧逐行明写，全绿不覆盖它们）。

**H · 没测到的 / 仍欠（逐条，不打包成「都验过了」）**：
- ④ **24 小时 soak 仍未验**（12h 是上限；不许写「24h/每日已验」）。
- ⑨ injection 的**真空载门（CPU<10%）整段仍无读数**：本场 18.1% mean 是迄今最低档，且「负载越低越快」这个
  隐含前提被本场**证伪**（732s 快过历史空载 788.9／793.9s）—— 前提倒了不等于那一行有读数，两件事分开记。
- **全量语义索引的候选池口径**（`u27_full_index.py:35-36` 的现读查询）：`vector_status='na' AND text_status IN ('native','mixed')`
  ⇒ 起跑时 **8,661** 份。同一时刻的类分布（只读快照）：`native 8,461｜mixed 227｜none 2,229｜failed 74` ⇒
  **`none` 与 `failed` 两类共 2,303 份不在池内**（没有正文可嵌，本轮跑完它们仍是 `na`；这是口径不是失败）。
  跑动中留一份中途快照对账：`done 2,011｜na 8,979｜running 1`、`vector_meta 150,674 行（0…150,673）`、
  `vectors.npy` 33,554,560 B ⇒ 容量 65,536（翻倍到位），与日志 `[1970/8661]` 那行一致。
- **I111 ⑥**：`delete_by_doc` 只删 `vector_meta`、不动 `.npy` 里的行（死行占 top_k 名额）—— 本轮**没修**。
- **I112 ③**：容量只增不减 ⇒ 文件只涨不缩（终值仍 ≈ 1 GiB）—— 本轮**没修**。
- **I110 的剩余边界**：设备读吞吐两档 20–41 MiB/s、`busy` 只 0.9–1.4s ⇒ 瓶颈在 4 KiB 页读往返，
  这一层没拆开（不影响「缓存决定快慢」，但「磁盘为什么这么慢」仍没有答案）。

---

## 4.39 轮二十八 · I111 ⑥ 甲 / I112 ③ 甲 / ⑨ 真空载窗口（2026-10-25）

本轮指令逐字：「按推荐方案执行」⇒ 执行上一轮 3×3 表里的 ⑥ 甲（超量取样）、③ 甲（保持现状）、⑨ 甲（等窗口，不造假读数）。
产品代码只改 `semantic/vector_store.py` 一处读路径（**没有新界面**）。

**A · I111 ⑥ 甲：死行不再吃 `top_k` 名额**
- 现态：`delete_by_doc` 只删 `vector_meta`、不动 `.npy` 里的行（避免碎片化）⇒ 行还在、元数据没了，它在打分里仍占位，
  回查时被 `if row:` 跳过；用户设 10 条可能只看到 7 条，屏幕上没有任何解释。
- 改法（`vector_store.py:286-287`、`:302-308`、`:317-325`）：`dead = max(0, used - self.count())`、
  `want = min(top_k + dead, used)`，分块 `argpartition` 与堆都按 `want` 取，回查时**凑够 `top_k` 就 `break`**。
- 代价实测（真库只读，1,968,159 行）：`SELECT COUNT(*) FROM vector_meta` **25ms（温）／1,113ms（冷）**；
  对照满库一次语义查询 6.1s（`.probe_work/u27_search_cost.log`）⇒ 温态 <1%，冷态那 1.1s 只在首次触盘付一次。
- 真库现读（`.probe_work/u28_deadrows.txt`，`mode=ro`）：`vector_meta 1,968,159｜max_idx 1,968,158｜used 1,968,159｜dead 0`、
  `catalog.db 12,109,783,040 B`、`vectors.npy 1,073,741,952 B` ⇒ **真库今天没有死行**，所以效果只能在临时库上验。
- 守卫 `tests/integration/test_vector_store.py::test_删过向量的文档不占满命中名额`：三份各 1 页、中间那份与查询
  完全同向且被 `delete_by_doc` 删掉，`top_k=2` 必须拿回两份活文档；坏法（`want` 改回 `top_k`）真红
  **1 failed**、原文 `AssertionError: 死行吃掉命中名额：应为 2 条，实得 1`（`.probe_work/u28_badway_search.log`，
  `test_vector_store.py:155`），还原后该文件 + `test_vector_write_path.py` **23 passed**。

**B · I112 ③ 甲：容量只增不减 —— 定案保持现状（代码不改）**
- 数字：容量 **2,097,152 行**、已用 **1,968,159 行（93.8%）** ⇒ 空行 128,993 × 512B = **66,044,416 B ≈ 63.0 MiB**，
  占 `vectors.npy` 1,073,741,952 B 的 **6.2%**；换来的是「追加写、不重整、不重写整表」——全量 8,660 份
  跑出 **72.77 页/秒**（`.probe_work/u27_full_index_status.json`）时一次整表重写都没有。
- 定案理由：压缩要重写整份 1 GiB 文件并动文件格式，收益只有 63 MiB，风险是打断已验的写路径；
  93.8% 的占用离「取整浪费过半」还很远。
- **重新评估触发条件（任一命中就重开）**：① 死行 `used - COUNT(*)` 超过 `used` 的 5%；② 一次删除/重嵌掉
  ≥ 1 万行；③ 容量翻倍到 4,194,304 行（文件 ≈ 2 GiB）。

**C · ⑨ 真空载（CPU<10%）整段：仍无读数，而且这次能证明「会话活着就到不了」**
- 做法（甲）：`.probe_work/u28_idle_watch.py` —— 每 10s 采一次整机 `psutil.cpu_percent`，**连续 3 个采样点
  都 <10% 才起** `gates/final.py --only injection --data-root …`；口径写死在脚本里不许放宽，也不动任何进程。
- 结果：**55 个采样点、10 分 15 秒、0 个 <10%**（min 21.5%｜中位 44.0%｜mean 46.4%｜max 69.8%），
  所以**没有起 injection**（`.probe_work/u28_idle_watch.log`）。判据未命中就停，不为凑读数降门槛。
- **为什么这不是「运气不好」**：同一批采样里 `Qoder CN.exe` 的单核占用 **94.3–97.4%（中位 96.1%）**，
  即 8 核的 **12.01%** —— 它一个人就把整机 CPU 的地板抬到 10% 以上，**只要本会话的编辑器在跑，
  CPU<10% 在任何时刻都不可达**（不是「今天忙」，是算术）。
- 交给下一轮的两条路（不替用户做）：① 在**关掉 Qoder/ZCode** 的纯 `cmd.exe` 里跑
  `python -u gates/final.py --only injection --data-root C:/Users/lavie/AppData/Local/PdfArchiver`
  （或 `python -u .probe_work/u28_idle_watch.py --minutes 60`，窗口出现时它自己起这一段并落
  `.probe_work/u28_idle_watch.json`）；② 接受「真空载这一行永远没有读数」，把历史最低档 **18.1% mean / 732s**
  作为唯一可引用的近空载读数（引用时必须标 18.1%，**不许写成空载**）。

**D · 回归 / 守卫 / 预检：一条命令 803 passed**
- 回归：`pytest tests/unit tests/integration tests/guards -q` ⇒ **803 passed / 1 skipped in 215.05s**（exit 0）；
  轮二十七基线 802 passed / 1 skipped ⇒ 净 **+1**，就是本轮新加的那条守卫（`.probe_work/u28_regression.log`）。
- `tests/guards` 单跑 **54 passed**（14.98s；预检里同一批 13.03s）；`tests/guards/test_file_size.py` 单跑末行
  `VERDICT: ALL GREEN`，**临近线 5 份**（最紧 `test_job_queue.py` 766 行、余 34；其余 707 / 711 / 742 等，阈值没动）。
- `scripts/precheck.py` ⇒ `合计 2 步｜红 0`、末行 `VERDICT: ALL GREEN`（10 段 SKIP 照旧逐行明写，全绿不覆盖它们）。
- **守卫第三次先逮到我的裸名**：终场预检第一遍 `VERDICT: RED（1 步未过）`，点名 `docs/VERIFICATION-RUNLOGS.md:962 u28_idle_watch.py`
  ⇒ 台账档旧名计数 **38 > 37**（`.probe_work/u28_precheck.log` 那场是 37，绿；`u28_precheck_final.log` 这遍才红）。
  补上 `.probe_work/` 前缀后回到 37 —— **上限 37 没动**，与本册 §4.33 / §4.35 同一个坑（只豁免带前缀的引用）。

> **本册末行现数（2026-10-25 轮二十七收尾取）**：`CHANGELOG 1,056（余 144）｜DECISIONS 687（余 513）｜本册 884 → 900（余 300）｜分册 757（余 443）｜ISSUES 150｜UI-WIREFRAMES 1,009（余 191）`；
> **最紧的仍是 `CHANGELOG-ARCHIVE 1,064（余 136）`**。
> **台账**：`112 行｜I1–I112 连续不重号｜CLOSED 87｜MITIGATED 24｜WONTFIX 1｜OPEN 0` —— 本轮 I112 由 OPEN 转 MITIGATED（残留 ③ 条照实挂着），
> I110 残留 ① 改写成「乙 已做完」并留下磁盘吞吐这条边界，没有新增行（I109/I110/I111/I112 只改证据与状态格）。
> **测试**：`pytest tests/unit tests/integration tests/guards -q` ⇒ **802 passed / 1 skipped（178.34s，exit 0）**；`tests/guards` 单跑 **54 passed（13.28s）**；
> `scripts/precheck.py` 两场（15:12 那场 RED 是 I112 双加粗自伤，修后终场）末行 `VERDICT: ALL GREEN`（`合计 2 步｜红 0`，10 段 SKIP 照旧逐行明写）。
> **真库现数（只读，`mode=ro` 取）**：`catalog.db 12,109,783,040 B`｜`vectors.npy 1,073,741,952 B = 2,097,152 行 × 512 B（已用 93.8%）`｜
> `vector_meta 1,968,159 行（idx 0…1,968,158，孤儿 0、重号 0）`｜`vector_status done 8,687 / na 2,304`。
> **临时文件**：`.probe_work/` 顶层 **663 项（13 个子目录）｜递归 1,104 文件｜857.6 MiB｜顶层 0 字节 75 个**
> （10 份轮二十七探针脚本截成 0 字节；`u27_mm_probe`、`u27_mm_probe2` 两个工作目录与 `status_page.py.bak`／`bootstrap.py.bak` 已删）；`injection_inflight` 不在场。
> **会话日志体积（token 代理）**：**337,053,182 B｜104,887 行**（22:45 取）vs 轮二十六基线 **327,159,766 B / 102,523 行** ⇒ **+9,893,416 B｜+2,364 行**。
> **本轮 `src/` 改了 7 份**（`semantic/search_service.py`、`semantic/vector_store.py`、`services/bootstrap.py`、`services/db_check.py`、
> `services/vector_service.py`、`ui/pages/health_panel.py`、`ui/pages/status_page.py`）、**`tests/` 改了 4 份**（`test_ai_classify_service.py`、
> `test_db_check.py`、`test_status_readout.py`、`test_vector_write_path.py`）、**`docs/` 改了 6 份**（本册、`CHANGELOG.md`、`ISSUES.md`、
> `UI-WIREFRAMES.md`、`ARCHITECTURE.md`、`DATABASE.md`），`git diff --stat` 合计 **17 份 +895/−196**。**没有新界面**（S7 只改成本文案与状态页重查路线）。

> **本册末行现数（2026-10-25 轮二十八收尾取）**：`CHANGELOG 1,076（余 124）｜DECISIONS 687（余 513）｜本册 900 → 968（余 232）｜分册 757（余 443）｜ISSUES 150｜UI-WIREFRAMES 1,009（余 191）`；
> **最紧的仍是 `CHANGELOG-ARCHIVE 1,064（余 136）`**，本册这轮从余 300 掉到余 232。
> **台账**：`112 行｜I1–I112 连续不重号｜CLOSED 87｜MITIGATED 24｜WONTFIX 1｜OPEN 0` —— 本轮没有新增行、没有状态迁移：
> I111 ⑥ 的残留格由「本轮只记账不改码」改成「已修（甲）」，I112 ③ 由「压缩/整理不在本条范围」改成「定案 甲=保持现状 + 三条重开触发条件」。
> **测试**：`pytest tests/unit tests/integration tests/guards -q` ⇒ **803 passed / 1 skipped（215.05s，exit 0）**；`tests/guards` 单跑 **54 passed（14.98s）**；
> `scripts/precheck.py` 末行 `VERDICT: ALL GREEN`（`合计 2 步｜红 0`，10 段 SKIP 照旧逐行明写，`.probe_work/u28_precheck.log`）。
> **真库现数（只读，`mode=ro` 取）**：`catalog.db 12,109,783,040 B`｜`vectors.npy 1,073,741,952 B = 2,097,152 行 × 512 B（已用 93.8%）`｜
> `vector_meta 1,968,159 行（idx 0…1,968,158 稠密）｜死行 0` —— 自本轮起每次语义查询多一条 `COUNT(*)`（温 25ms／冷 1,113ms）。
> **临时文件**：`.probe_work/` 顶层 **674 项（13 个子目录）｜递归 1,103 文件｜857.7 MiB｜顶层 0 字节 75 个**；
> `.probe_work/u28_idle_watch.py` **故意不截成 0 字节** —— §4.39 C 把它写成「关掉 Qoder 后自己起 injection」的入口，截了就等于把那条路拆了。
> **会话日志体积（token 代理）**：**339,082,629 B｜105,405 行** vs 轮二十七基线 **337,053,182 B / 104,887 行** ⇒ **+2,029,447 B｜+518 行**。
> **本轮 `src/` 改了 1 份**（`semantic/vector_store.py`，+16/−3）、**`tests/` 改了 1 份**（`test_vector_store.py`，+29）、
> **`docs/` 改了 3 份**（本册、`CHANGELOG.md`、`ISSUES.md`）；**零新界面、零新入口**。

---

## 4.40 轮二十九 · 12 段整链 + 4 分钟 soak / package / 低负载 injection（2026-10-25 23:3x → 2026-10-27 00:01）

用户这一轮的指令：「1+2」（先跑 coldstart+e2e+ocr+ui-inject+g2，再跑 injection 整段）→「soak 4 分钟档 + package
（约 9 分钟；package 会重建冻结产物）都做」→「3+5+6 都做」（3 ⊂ 5：整链已含冷启动与一致性，6 = 照实记账）。
**产品代码零改动**：这一轮只跑门禁与记账，所以 `CHANGELOG.md` 不加条目（它只记实际改过的产品代码），读数全在本节。

**A · 五段一批（2026-10-25 23:4x–23:51，起跑 CPU 67.2%｜可用 1,888MiB｜Ld9BoxHeadless.exe 2,263MiB）**
- `coldstart` **RED 2.415s**（阈值 1.5s），同场 `e2e` 的冷启动读数 1.437s ⇒ 同一次开机、同一份代码，两次差 0.98s。
- `e2e` / `ocr` / `ui-inject`（36 条坏法全抓）/ `g2` 四段 **PASS**（`g2` 这一场是绿的）。
- 段末 `合计判定 9 条｜本次未跑 6 段`、末行 `VERDICT: RED（1 条未过）`（`.probe_work/u28_seg1.log`）。
- G1 隔离复跑三次（`.probe_work/u28_coldstart_isolated.log`）：**1.929s（CPU 49.6%，RED）／1.450s（59.7%，PASS）／1.358s（73.3%，PASS）**
  —— 与 CPU 非单调，这条对整机环境敏感、对 CPU% 不敏感。
- 次日 **20:58:33** 安静窗（CPU 28.7%｜可用 4,714MiB）同一段 **1.130s PASS**（`.probe_work/u28_coldstart_retry_quiet.log`）
  ⇒ 2.415s 是环境读数，**不是回归**；阈值 1.5s 一个字没动。

**B · injection 整段（2026-10-26 20:58:42 → 21:11:42，780.0s）**
9 条判定全绿：p9 **70/70**、p10 **45/45**、p16 11 条（8 坏法全抓 + 3 条反向对照成立）、p17 **3/3**、p18 **3/3**、
p21 **24/24**、p22 **33/33**、p23 **23/23**、p24 **17/17**（`.probe_work/u28_seg2_injection.log`）。这一段**不是真空载**
（起跑 CPU 47.5%），⑨ 那一行照旧不销账。

**C · 4 分钟 soak + package（2026-10-26 20:52 / 20:58 收工）**
- soak **325.4s ALL GREEN**：内存首段中位 111.3 → 末段中位 111.5MiB（**增长 +0.2**，G8 余量 1,088.5MiB）；
  S6 排空 1.0s、S7 盘上 82 = 库里 82、S8 日志 1 份、S9 p12 十四项 0 红 0 未验（`.probe_work/u28_seg4_soak.log`）。
- package **350.4s ALL GREEN**：构建 201.1s + 冻结产物冒烟 149.3s，**整包 400.1 MiB**；迁移 8 份 `.py` 与源码清单逐份相等、
  ONNX 3 个、DLL 3 个、`.dist-info` 6 份；冒烟里强杀留 1 条 `running` 残尸→重启 `recovered=1`→续跑完、documents 273 = 磁盘 273、
  运行目录在仓库外（`.probe_work/u28_seg4_package.log`）。

**D · 12 段整链（2026-10-26 21:45 起 → 2026-10-27 00:01:31；`.probe_work/u29_chain.log` 418 行）**
起跑负载 **CPU 40.8%｜可用 2,033MiB｜WorkBuddy.exe 1,054MiB**；段末 `合计判定 35 条｜本次未跑 0 段`、末行
**`VERDICT: RED（4 条未过）`**（4 = 段级：regression / coldstart / consistency / g2；consistency 内部另计 3 行红）。
- **全绿 8 段**：docs-inject 0.0s｜guards 3.7s｜e2e 15.5s（冷启动 1.278s、11 条端到端）｜injection 832.7s（9 条全绿）｜
  ui-inject 95.7s（36/36）｜ocr 32.5s（3 PASS，含每日页预算真停机）｜soak 327.9s（内存 112.8 → 113.0MiB）｜
  package 399.6s（构建 233.4s + 冒烟 166.2s）。
- **红 ① regression（244.6s）**：**816 passed / 1 failed / 1 skipped**，唯一失败是
  `tests/integration/test_app_shell.py::test_进程级冷启动实测符合G1约定` —— 与 ② 同一条 G1 计时，不是两处坏。
- **红 ② coldstart（2.3s）**：**1.519s**，超线 **19ms**；同场 e2e 1.278s、A 段安静窗 1.130s。
- **红 ③ consistency（6,186.3s）**：19 条 **红 3、未验 0** —— `C3·D:\` 盘上多 3 份、`C3·E:\` 多 2 份（漏索引），
  `C3·H:\` 库里有 1 条盘上没了却没标 `missing_since`。**根因是数据漂移，不是代码**：六个监测根的
  `last_full_scan_at` 全停在 **2026-10-16 00:21–00:28**，而多出来的 5 份 PDF mtime 是
  **2026-10-24 21:55 – 2026-10-25 03:07**（2026-10-27 现读，`.probe_work/u29_drift_files.txt`），
  缺的那 1 份是 qwenwork 应用自带的 mock `sample.pdf`（2026-10-27 现读 `FileNotFoundError`）。
  逐条计时：C1 1,086.3s｜C2 4.9s｜六行 C3 各 1,701.9s｜C4 266.1s｜C5 1,940.2s｜C11 1,178.9s｜C12 5.6s（其余 <1s）。
  消这条要走**产品路径重扫一次**，改代码消不掉。
- **红 ④ g2（63.0s）**：**P95 608.0ms vs 500ms**（P50 261｜P99 720｜max 720｜100 样本｜最差查询 `PDF`）；
  起跑 **CPU 55.3%｜可用 1,911MiB｜TOTClient-Win64-Shipping.exe 3,486MiB**。分类自检 6/6 全对；55.3% 在 60% 的「忙」线之下，
  按门禁自己的规则**判产品红、不许归因给负载**，本节照红记，不赦免。三条旁证说明红在尾部而非固定成本：
  ① 同一套 20 查询 **两小时前**在 CPU 67.2% 的场子里（A 段）是绿的；② 同一查询 5 次背靠背差 2.5 倍
  （`发票` 488–720ms、`PDF` 282–720ms）；③ `环境影响评价`（16 命中）111ms，200 命中的落在 150–450ms，成本仍随命中数走。
  与 **I110** 已定位的「系统页缓存装不装得下决定快慢」同向：3.5 GiB 常驻进程 + 只剩 1.9 GiB 可用。
  要在安静窗定点复跑才算数 —— 本轮两次（23:5x / 00:0x）都没等到，**没有为凑绿重跑到绿**。

**E · 本轮没跑到的**
consistency 那 3 条要一次产品路径重扫才消；G1 与 g2 的红要安静窗定点复跑；④ 24 小时 soak 仍未验（4 分钟档只是本轮档位）；
⑨ injection 真空载（CPU<10%）仍无读数（B 段 47.5%）。**没有一处分支是靠抬阈值或改判据变绿的**。

> **本册末行现数（2026-10-27 轮二十九收尾取）**：`CHANGELOG 1,076（余 124）｜DECISIONS 687（余 513）｜本册 968 → 1,028（余 172）｜
> 分册 757（余 443）｜ISSUES 150｜UI-WIREFRAMES 1,009（余 191）`；**最紧的仍是 `CHANGELOG-ARCHIVE 1,064（余 136）`**。
> **台账**：`112 行｜I1–I112 连续不重号｜CLOSED 87｜MITIGATED 24｜WONTFIX 1｜OPEN 0` —— 本轮**零新增行、零状态迁移**：
> 四条红没有一条是代码缺陷（两条 G1 计时是同一处、一条是数据漂移、一条是尾部长尾），所以不占台账格子，只在本节留读数。
> **测试**：整链内 `pytest` **816 passed / 1 failed / 1 skipped（241.73s）**，唯一失败是 G1 计时那一条（见 D ①②）；
> A 段同一条断言在安静窗 **1.130s 过**。**产品代码 `src/` 与 `tests/` 本轮 0 改动**。
> **真库现数（只读，2026-10-27 取）**：`catalog.db 12,109,783,040 B`｜`documents 10,991`｜`text_pages 1,975,611`｜
> 队列 `{'done': 10,941, 'failed': 75}`｜`running 0`｜`vector_status {'done': 8,687, 'na': 2,304}`｜监测根 6 个、
> 六个 `last_full_scan_at` 全停在 2026-10-16 00:21–00:28。
> **临时文件**：`.probe_work/` 顶层 **688 项（13 个子目录）｜递归 1,129 文件｜857.7 MiB｜顶层 0 字节 75 个**；
> 新增承重：`.probe_work/u28_seg1.log`、`.probe_work/u28_coldstart_isolated.log`、`.probe_work/u28_coldstart_retry_quiet.log`、
> `.probe_work/u28_seg2_injection.log`、`.probe_work/u28_seg4_soak.log`、`.probe_work/u28_seg4_package.log`、
> `.probe_work/u29_chain.log`、`.probe_work/p12_real_root.json`、`.probe_work/u29_drift_files.txt`、`.probe_work/u29_roots.txt`；
> `injection_inflight` **不在场**。
> **会话日志体积（token 代理）**：**341,514,041 B｜106,008 行**（00:20 取）vs 轮二十八基线 **339,082,629 B / 105,405 行** ⇒
> **+2,431,412 B｜+603 行**。

---

## 4.41 轮三十 · 安静窗定点复跑（G1 / g2 / 回归）+ 产品路径重扫（2026-10-27 04:4x → 06:1x）

用户这一轮的指令逐字：「consistency 3 条：需要一次产品路径重扫…G1 与 g2：安静窗定点复跑才算数…这两个能执行吗」。
两条都能执行，而且 04:4x 机器自己空下来（`TOTClient-Win64-Shipping.exe` 3,536 MiB 退场：CPU 61.2% → 25.7%、
可用 1,620 → 3,907 MiB），所以按「先量后写」的顺序：**先跑对负载敏感的两条，再动库**。
**产品代码 `src/` 与 `tests/` 本轮 0 改动**；新写的只有一次性探针 `.probe_work/u30_rescan.py`（调产品入口，零 SQL）。

**A · 安静窗三处定点复跑（阈值一处没动）**
- **g2**（段 42.6s）：`P95 326.0ms vs 500ms`（P50 142｜P99 338｜max 338｜100 样本｜最差 `发票`），
  起跑 **CPU 17.3%｜可用 3,962MiB｜chrome.exe 1,348MiB**（g2 自采时点 CPU 26.0%｜3,889MiB），
  `classification=green`；分类自检 **6/6**（含 `500ms@60%` 与 `652ms@60%` 两条边界喂数）。
  对照轮二十九同一套 20 查询 × 5 reps：**608.0ms @ CPU 55.3%｜1,911MiB｜TOTClient 3,486MiB**。
- **G1**（段 1.9s）：**1.205s**（进程总耗时 1.836s、关窗对账 1 条）；对照轮二十九 **1.519s**。
  `tests/integration/test_app_shell.py::test_进程级冷启动实测符合G1约定` 单跑 3 次全过（1.77 / 1.97 / 1.75s）。
- **regression**：按整链同口径 `pytest tests -q` ⇒ **817 passed / 1 skipped / 183.21s / exit 0**
  （`.probe_work/u30_regression_full.log`）。轮二十九那场是 816 passed / 1 failed，唯一失败就是 G1 计时。
  口径更正：先前按 `pytest tests/unit tests/integration tests/guards` 跑出 **803** 是**另一个集合**
  （`segment_regression` 跑的是 `tests` 整目录），两个数不通用。
- **作废一场**：第一次用 shell 里的 `python` 起段，`ModuleNotFoundError: No module named 'PySide6'`
  把 g2 与 coldstart 各判一条 RED —— 那是解释器选错，不是产品红；换 `.venv/Scripts/python.exe` 重跑，
  有效读数在 `.probe_work/u29b_g2_coldstart.log`，前一场不计入任何结论。

**B · 产品路径重扫（`.probe_work/u30_rescan.py`，零 SQL / 零手改库）**
- 只调 `ScanService.reconcile_path()` + `IndexService.index_document()`：5 份新 PDF → doc **10995–10999**
  （3 份原生正文 162 / 110 / 132 页 `ocr_status=na`；2 份扫描件 262 / 236 页 `stored_pages=1 / 0`、
  `text_status=none`、`ocr_status=pending` —— 按设计等用户点「送去识别」，不自动烧 OCR）；
  删掉的 qwenwork mock `sample.pdf` → doc 10980 走 `OSError → _vanish → mark_missing`，
  `missing_since=1793047826`。
- 改前逐条核对 6 条路径（5 条 `in_db: false`、sample.pdf `in_db: true`），改后 5 条 `added` + 1 条 `missing`，
  逐条落 `.probe_work/u30_rescan.json`；跑完 `queue: null`（无残留任务）。
- 为什么必须走产品路径：那 3 条红是**数据漂移**不是代码缺陷；手写 `UPDATE documents SET missing_since=…`
  只会让库与盘看着对上，索引/正文/向量仍缺口。与「探针自己的传感器也是代码」同一条理由。

**C · p12 真根 19 条（04:59:23 → 06:08:37，4,154s，`.probe_work/u30_p12_real.json`）**
`合计 19 条｜红 0 条｜未验 0 条`、末行 `VERDICT: ALL GREEN`、`walk: true`。
- C3 六行（同一趟走盘，各计 820,094ms）：lavie 68/68/缺 0｜**D: 94/95/缺 1**｜E 1969/1969/0｜
  F 5352/5352/0｜G 1655/1655/0｜**H: 1856/1857/缺 1**。D 与 H 的「库多 1」就是那两条 `missing_since`
  （H = 本轮新盖的 doc 10980；D = 跨卷搬家的 doc 93，见 D 段 I113），口径是「盘上 = 库内 − 已标缺失」，
  所以 6 行全绿 —— **不是把缺失记录算作通过，而是它本来就该在「已标缺失」那一栏**。
- 逐条计时：C0 27ms｜C1 997,851ms（`integrity_check=ok`、外键 0 条）｜C2 2,949ms（主记录 10,996 唯一）｜
  C3 820,094ms｜C4 196,592ms（1,976,016 ↔ 1,976,016，漏索引 0 / 残留 0）｜C5 1,202,780ms（1,976,016 页六项自洽）｜
  C6 210ms｜C7 25ms（`done 8,687 / na 2,309`）｜C8 1ms｜C9 2.4ms（`running 0`、`done 10,941 / failed 75`）｜
  C10 0.6ms（分类 14 个）｜C11 930,361ms（最新快照整库体检）｜C12 4,474ms（超页 0）｜C13 3ms（监测根 6 个）。
- 同一探针比轮二十九那场 **6,186.3s 快 2,032s（−33%）**：那场与整链 8 段背靠背、本场独占。
  **两场都是真读数，不互相换算**（同「门禁计时特性」的口径）。

**D · 新开 ISSUES I113（OPEN，等勾选）**
doc 93（`D:/6.Communication Social/MemoTrace/…这本书能让你睡得好…pdf`，`missing_since=1792790831`）与
doc 10994（`H:/others software/MemoTrace/…` 同名同书、341 页）是**同一本书**（`.probe_work/u30_namecheck.txt`）：
MemoTrace 目录从 D: 搬到 H:，**Windows 跨卷搬移会换 inode** ⇒ `_adopt_renamed`
（`src/pdfarchiver/services/scan_service.py:290-305`，按 `(device, file_id)` 认改名）认不出，
旧记录被 `_vanish`（同文件 `:282-288`）盖成缺失戳后留成死记录。
三条出路：**甲 删死记录（推荐）／乙 保留但在界面隐藏／丙 保持现状**，等勾选。

**E · 本轮没跑到的 / 仍欠的**
- **整链一条命令全绿仍未拿到**：轮二十九 34/35；本轮是**定点复跑**（g2 / coldstart / regression / consistency
  四段），不许写成「整链全绿」—— e2e / injection / ui-inject / ocr / soak / package 沿用轮二十九读数。
- **⑤ 新文档的向量**：5 份新文档 `vector_status=na`（非 na 仍是 8,687 份），新增 **405 页**正文
  （162 + 110 + 132 + 1 + 0）还没 embed ⇒ 语义搜索到不了它们，要单独一次向量回填。
- 2 份扫描件（262 / 236 页）等用户点「送去识别」；OCR 是用户触发，不自动跑。
- ④ 24 小时 soak 仍未验（12 小时是已验上限）；⑨ injection 真空载（CPU<10%）仍无读数
  —— 本场 17.3% 是起跑瞬间，不构成真空载。
- 安装包与代码签名仍未交付；隐私政策按用户「以后再处理」挂起（2026-10-27）。
- **没有一处分支是靠抬阈值或改判据变绿的**：g2 的 500ms、G1 的 1.5s、忙线 60% 一个字没动。

> **本册末行现数（2026-10-27 轮三十收尾取）**：`CHANGELOG 1,109（余 91）｜DECISIONS 687（余 513）｜
> 本册 1,043 → 1,110（余 90）｜分册 757（余 443）｜ISSUES 151｜UI-WIREFRAMES 1,009（余 191）`；
> **最紧的仍是 `CHANGELOG-ARCHIVE 1,064（余 136）`** —— 下一轮若要再往 `CHANGELOG.md` 里写长条目，先切册。
> **台账**：`113 行｜I1–I113 连续不重号｜CLOSED 87｜MITIGATED 24｜WONTFIX 1｜OPEN 1`；
> 本轮**新增 I113 一行（OPEN）**，其余 112 行零状态迁移 —— 四条红都不占台账（两条 G1 计时同一处、
> 一条数据漂移、一条尾部长尾），I113 是新逮到的数据残留不是本轮回归。
> **测试**：`pytest tests -q` **817 passed / 1 skipped（183.21s）**；p12 真根 **19/19**；
> `src/` 与 `tests/` 本轮 **0 改动**（新写的只有 `.probe_work/` 里的一次性探针）。
> **真库现数（只读，2026-10-27 取）**：`catalog.db 12,112,449,536 B`｜`documents 10,996`｜`text_pages 1,976,016`｜
> 队列 `{'done': 10,941, 'failed': 75}`｜`running 0`｜`vector_status {'done': 8,687, 'na': 2,309}`｜监测根 6 个。
> **临时文件**：`.probe_work/` 顶层 **698 项（13 个子目录）｜递归 1,139 文件｜857.8 MiB｜顶层 0 字节 75 个**；
> 新增承重：`.probe_work/u30_rescan.py`、`.probe_work/u30_rescan.json`、`.probe_work/u30_rescan.log`、
> `.probe_work/u30_p12_real.json`、`.probe_work/u30_p12_real.log`、`.probe_work/u30_p12_summary.txt`、
> `.probe_work/u30_p12_sel.txt`、`.probe_work/u30_namecheck.txt`、`.probe_work/u30_vectorcheck.txt`、
> `.probe_work/u30_regression_full.log`、`.probe_work/u29b_g2_coldstart.log`；`injection_inflight` **不在场**。
> **会话日志体积（token 代理）**：**344,040,730 B｜106,653 行** (06:2x 取) vs 轮二十九基线 **341,514,041 B / 106,008 行** ⇒
> **+2,526,689 B｜+645 行**。

---

## 4.42 轮三十一 · 新文档向量回填 404 页 + 12 段整链一条命令第一次全绿（2026-10-27 07:1x → 10:4x）

用户指令逐字：「整链一条命令全绿（本轮是定点复跑，不写成整链全绿）；5 份新文档 vector_status=na、新增 405 页正文未 embed（语义搜索还到不了）；执行这些把」。两件事都做了，中间逮到一条计划外的缺陷（**ISSUES I114**），所以多跑了一场整链。

**A · 向量回填 404 页**（`.probe_work/u31_vector_backfill.py`，07:18:53 → 07:19:10，零 SQL，只调产品 `VectorService`）
- 3 份原生正文全部写入：10996 **162 页**（3,244ms）｜10998 **110 页**（1,139ms）｜10999 **132 页**（1,441ms）⇒ **404 页**，`pages_skipped_empty 0`、`last_error null`。
- `vector_meta 1,968,159 → 1,968,563`；`done 8,687 → 8,690`、`na 2,309 → 2,306`。
- 2 份扫描件（10995 262 页 / 10997 236 页）`text_status=none` **被如实跳过**（回执写明「先索引才能建向量」）—— 要先走用户触发的 OCR，不代跑、不造正文。
- 真库只读现数（2026-10-27 07:19 之后未再写入）：`catalog.db 12,112,449,536 B｜documents 10,996｜text_pages 1,976,016｜vector_meta 1,968,563｜missing_since 2`。

**B · 第一场整链（07:19:21 → 08:57:36）在第 10 段后崩 —— 入账 I114**
- 起跑 **CPU 56.7%｜2,194MiB｜chrome.exe 1,553MiB**；七段全绿（docs-inject 0.0s｜guards 3.0s｜injection 752.6s｜ui-inject｜ocr｜consistency｜soak 320.9s）。
- 三条 G1 同源红：regression **816 passed / 1 failed**（`test_进程级冷启动实测符合G1约定`）｜coldstart **1.663s**｜e2e **1.604s** —— 负载场，照记不赦免。
- 崩点逐字：`File "gates/final.py", line 561, in main / print(f"        现场：{row.note[:900]}") / UnicodeEncodeError: 'gbk' codec can't encode character '\u2212' in position 24`，`EXIT=1`，package 与 g2 没跑。源字符 = `packaging/frozen_smoke.py:425` 的 `text_pages − content_fts`；`Row.note` 只留 `text[-900:]`，U+2212 在不在窗口里随那段输出的长度而变。

**C · 修法 + 守卫**
- `gates/stage1.py::harden_stdio()` 只把 stdout/stderr 的 `errors` 改 `replace`，**编码保持控制台原样**；`gates/stage1.py`–`stage6.py`、`gates/final.py`、`scripts/precheck.py` 八处 `main()` 第一条语句调用。
- `tests/guards/test_gate_stdio_encoding.py` 五条：静态位置 + 正对照（≥6 入口）+ GBK 子进程真跑两遍（带兜底 exit 0 且那行以 `?` 留下 / 不带兜底必须崩）+ 五例位置坏法。上架当场逮到 `gates/stage6.py` 没调，补上后 guards **59 passed**。

**D · 修后 package 定点复跑（290.3s 全绿）**
- build **142.9s** + smoke **147.5s**；整包 **400.1 MiB**、documents **273 / 磁盘 273**；`合计判定 2 条｜本次未跑 10 段｜VERDICT: ALL GREEN`。**边界**：这一场的 900 字窗口里恰好没有 U+2212 ⇒ 它只证明「链不再被这条路径打死」；「字符真被兜住」由 C 段 GBK 子进程那两条证明。

**E · 第二场整链（09:05:46 → 10:43:47，5,877.1s）—— 一条命令 12 段全绿，第一次**
- 起跑 **CPU 36.3%｜2,804MiB｜chrome.exe 1,784MiB**；末行 `合计判定 35 条｜本次未跑 0 段｜VERDICT: ALL GREEN`。
- docs-inject 0.0s（台账 113 行｜失效测试名 6/6）｜guards 2.4s｜**regression 199.5s → 822 passed / 1 skipped**｜coldstart 2.0s → **G1 1.342s**（进程总耗时 1.990s、关窗对账 1 条）｜e2e 13.7s（11 条端到端、带页码 6 行）｜injection **790.6s**（p9 70/70 267.5s｜p10 45/45 152.4s｜p16 11 条 29.5s｜p17 8.8s｜p18 9.9s｜p21 24/24 85.5s｜p22 33/33 99.8s｜p23 23/23 80.9s｜p24 17/17 56.4s）｜ui-inject 86.6s（p15 36 条）。
- ocr 32.6s（真引擎 6 页落库 + 预算 2 页真停机 + 4 passed）｜**consistency 4,116.9s**（注入 21/21 + 边界 1/1｜p14 1.2s｜真根 4,107.3s 19 条红 0 未验 0；C1 1,084,218ms｜C2 2,939ms｜C3 六行各 774,855ms｜C4 184,250ms｜C5 1,146,161ms｜C11 908,250ms｜C12 4,334ms）｜soak 320.7s（RSS 112.9 → 113.1 MiB、线程 15 → 12、句柄 321 → 321、积压峰值 27 / 排空 1.0s / done 123、盘上 82 / 库内 82 / 缺失 10、app.log 35KiB）｜package 261.2s（build 119.8s + smoke 141.4s）｜**g2 50.9s → P95 320ms**（P50 137 / P99 341 / 100 样本 / 最差 `发票`；起跑 CPU 3.5%｜2,787MiB；`classification=green`；分类自检 6/6）。
- 段耗时合计 **5,877.1s ≈ 98 分钟**，与墙钟对得上。**阈值一处没动**；第二场是「修完必须重跑一次完整链」，**不是跑到绿灯为止**。

**F · 仍欠的**
- 2 份扫描件（doc 10995 / 10997）要用户点「送去识别」才有正文与向量；**ISSUES I113** 仍等勾选。
- ④ 24 小时 soak 未验（12h 是上限）；⑨ injection 真空载（CPU<10%）仍无读数（本场 36.3%）；安装包与代码签名未交付；隐私政策挂起（2026-10-27）。
- 本册已贴 1,200 红线：**下一轮写长条目前先切册**。

> **本册末行现数（2026-10-27 轮三十一收尾取）**：`CHANGELOG 1,143（余 57）｜DECISIONS 687（余 513）｜本册 1,162 → 1,175（余 25）｜
> 分册 757（余 443）｜ISSUES 152｜UI-WIREFRAMES 1,009（余 191）`；**最紧的是本册自己** —— §4.42 F 已写死：下一轮写长条目前先切册。
> **台账**：`114 行｜I1–I114 连续不重号｜CLOSED 88｜MITIGATED 24｜OPEN 1（I113）｜WONTFIX 1｜结构不合格 1 行（上限 1：I35）｜失效测试名 6 处 / 上限 6`；
> 本轮新增 I114 一行并当场 CLOSED（打印编码兜底），其余 113 行零状态迁移。
> **测试**：整链 regression **822 passed / 1 skipped（199.5s）**｜guards **59 passed**｜p12 真根 **19/19**｜
> 12 段一条命令 `合计判定 35 条｜本次未跑 0 段｜VERDICT: ALL GREEN`（5,877.1s）；`scripts/precheck.py` 末行 ALL GREEN（114 行台账在场）。
> **真库现数（只读，收尾取）**：`catalog.db 12,112,449,536 B｜documents 10,996｜text_pages 1,976,016｜vector_meta 1,968,563｜
> vector_status {'done': 8,690, 'na': 2,306}｜missing_since 2｜队列 {'done': 10,941, 'failed': 75}｜监测根 6 个｜schema 8`。
> **临时文件**：`.probe_work/` 顶层 **716 项（13 个子目录）｜递归 1,157 文件｜857.9 MiB｜顶层 0 字节 75 个**；
> `injection_inflight` **不在场**；本轮承重 `u31_*`（回填 / 两场整链 / precheck / 现数）留在顶层，§4.42 的 scratch 已清空。
> **会话日志体积（token 代理）**：**347,987,493 B｜107,596 行**（10:52 取）vs 轮三十基线 **344,040,730 B / 106,653 行**
> ⇒ **+3,946,763 B｜+943 行**。

---

## 4.43 轮三十二 · I113 甲删掉跨卷搬家的死记录 + 两份扫描件 OCR 出 497 页正文 + 逮到 I116（2026-10-27 17:4x → 18:2x）

用户指令逐字：「均跟进你的建议来执行」。三件事：①I113 甲（先备份、再单事务删 doc 93）；②给 10995 / 10997 走产品自己的 OCR；③OCR 出页面后补向量回填。①②做完，③被本轮新逮到的一条缺陷挡住（**ISSUES I116**），照实报红，没有把 `text_status` 改成 `native` 凑绿。

**A · I113 甲：先备份，再单事务删 doc 93**（`.probe_work/u32_i113_backup_delete.py`，17:45:24 → 17:55:11）
- 备份先做：`catalog.db` + `vectors.npy` 拷进备份目录，**12,112,449,536 B｜47.4 s**，校验 `schema_version [8,8]`、`mismatch {}` ⇒ `BACKUP GOOD`。
- 删前逐字核对该行：`#93 043dc424…d9d7｜341 页｜1792790831`（= 2026-10-24 05:27:11 索引）。
- 单事务删净六张表：`text_pages 338｜document_metadata 1｜processing_jobs 1｜document_tags 0｜document_categories 0｜vector_meta 0`，共 1 份文档，耗时 **160.1 s**（含删前后两次全表计数）。
- 删后对账：`documents 10,996 → 10,995`｜`text_pages 1,976,016 → 1,975,678`｜`content_fts` 同步 `−338`（`fts_delta −338`，`pages_delta −338`）｜`doc_still_there 0`｜`orphan_pages 0`｜`PRAGMA foreign_key_check` **OK** ⇒ `DELETE GOOD`。
- 没有 `VACUUM`（12 GB 整库重写不值当）。死记录的直接后果是「搬家后旧卷上的行被当成还在」，机制层根因另立 **I115**（跨卷搬移，`scan_service.py:290-321`），等勾选。

**B · 两份扫描件走产品链路 OCR：497 页 / 13.05 分钟**（`.probe_work/u32_ocr_vectors.py`，17:55:57 → 18:09:00）
- 入口和界面那颗「送去识别」是同两个：`OcrService.request_ocr` + `AppContext.start_background()`；探针不绕过任务状态机、不直接写库。
- `plan_ocr`：可排队 `[10995, 10997]`｜498 页｜预算剩 6,000 页｜跳过 0；`request_ocr` 入队 **2 条**。
- 引擎 `rapidocr-onnxruntime/1.4.4+onnxruntime/1.20.1+dpi200`：doc 10995 **261 页**（页 1–261，56,139 字）｜doc 10997 **236 页**（157,331 字）⇒ **497 页｜38.1 页/分**；OCR 预算 `497 / 6,000（剩 5,503）`。
- 10995 的第 262 页不是 OCR 出来的：它 2026-10-27 04:50:23 就以 `source_kind=native`（894 字）落库，OCR 只补 1–261 ⇒ `ocr_pages_done 261 < page_count 262` 是正确计数，不是漏页。
- 全文搜索真能到（`.probe_work/u32_after_ocr_checks.py`，走 `SearchService` 而非裸 SQL，`in_fields=(FIELD_BODY,)`、`limit=5`）：`赫拉巴尔` 正文 11 行、本页 5 行全在 10997（页 235 / 14 / 16 / 3 / 1），12ms｜`倪匡散文` 正文 114 行、本页 5 行全在 10995（页 1 / 3 / 155 / 51 / 7），28ms；来源标注逐字 `OCR 识别（可能有错字）`。
- 库内对账（只读）：`text_pages 1,976,175`（= 1,975,678 + 261 + 236）、`content_fts 1,976,175` —— 两表相等。

**C · ③ 向量回填被挡住 —— 入账 I116，没有伪装成功**
- `request_vectors([10995, 10997])` 回执逐字：`点名 2 份｜该建 0 份｜新增任务 0 条｜没有可搜的正文，先索引 2 份`，`skipped={'not_searchable': [10995, 10997]}`。
- 真因：OCR 唯一写入口 `DocumentRepository.mark_ocr_result`（`db/repositories/documents.py:429-442`）只写 `ocr_status / ocr_pages_done / last_ocr_at / last_error`，**不碰 `text_status`**；向量入口票据是 `TEXT_SEARCHABLE = ("native", "mixed")`（`services/index_service.py:47`），在 `services/vector_service.py:163` 与 `:183` 两处判定 ⇒ OCR 正文进了 FTS、进不了向量入口。
- 三条路写进 I116：**甲** 加 `has_searchable_text(doc)`（`text_status ∈ TEXT_SEARCHABLE or ocr_status ∈ (OCR_DONE, OCR_PARTIAL)`）替掉那两处票据；**乙** 让 OCR 流程回写 `text_status`（等于把识别正文冒充原生正文，否决）；**丙** 只记录不修。**推荐甲**，等勾选。
- 明确没做的事：没有手改 `text_status` 让 `request_vectors` 放行 —— 那会让「原生正文」这一列说谎，也会让这条红凭空变绿。

**D · 本册第二次切册（§4.26–§4.37 搬进分册二）**
- 起因是 §4.42 F 写死的「下一轮写长条目前先切册」。切完本册 **1,175 → 459 行**；`docs/VERIFICATION-RUNLOGS-ARCHIVE-2.md` **727 行**（md5 `85fd4ec8…58b88`），§4.26–§4.37 逐字搬运、标题计数守恒。
- `tests/guards/test_doc_pointers.py` 的 `LEDGER_DOCS` 已含新分册，guards **59 passed（12.77s）**。

**E · 仍欠的**
- **I116** 等 甲/乙/丙 勾选（③向量回填要等它）；**I115** 等勾选（跨卷搬家的机制层根因，本轮只清了残留）。
- `CHANGELOG` **1,178 行（余 22）**：下一轮开篇先切册（`CHANGELOG-ARCHIVE.md` 已有先例）。
- ④ 24 小时 soak、⑨ injection 真空载（CPU<10%）、安装包与代码签名、隐私政策 —— **用户 2026-10-27 明示「这些都不做」**
  ⇒ **D-062 定案，从「仍欠」移出**：soak 证据上限永久 12h、真空载永久写「无读数（不可达）」且不抬门槛、
  交付物只认 `--onedir` 冻结产物 + 冻结冒烟、隐私边界只到 `docs/OCR.md` §五。上文各轮「24h 未验 / 无读数」
  的历史读数保留不改，改的只是它们**不再算待办**（`ROADMAP` soak 行与最终交付报告各追了一句指向 D-062）。

> **本册末行现数（2026-10-27 轮三十二收尾取，含 D-062 追记后复量）**：`CHANGELOG 1,178（余 22）｜DECISIONS 712（余 188）｜本册 495 → 506（余 694）｜分册一 757（余 443）｜分册二 727（余 473）｜ISSUES 154｜UI-WIREFRAMES 1,009（余 191）`；**最紧的是 CHANGELOG（余 22）** —— 下一轮开篇先切它。
> **台账**：`116 行｜I1–I116 连续不重号｜CLOSED 89｜MITIGATED 24｜OPEN 2（I115 / I116）｜WONTFIX 1｜结构不合格 1 行（上限 1：I35）｜失效测试名 6 处 / 上限 6`；本轮 I113 **OPEN → CLOSED**（销账条件补实测读数），新开 I115 / I116 两行均为 OPEN，其余零状态迁移。
> **测试**：`pytest tests -q` **822 passed / 1 skipped（177.06s）**｜guards 全量 **59 passed**（12.77s 一次、预检内 10.81s 一次）｜`scripts/precheck.py` 末行 `VERDICT: ALL GREEN`（docs-inject + guards 合计判定 9 条）。
> **覆盖边界**：本轮**没跑 12 段整链** —— `consistency / soak / package / g2` 不在这一场的覆盖里（预检末行逐段 SKIP 已列）；依据是 `src/` 与 `tests/` 本轮 **0 改动**、门禁阈值 **0 改动**，整链最近一次全绿是同日轮三十一的 5,877.1s / 35 判定。
> **真库现数（只读，18:1x 取）**：`catalog.db 12,113,543,168 B（vs 轮三十一末 +1,093,632 B）｜documents 10,995｜text_pages 1,976,175 = content_fts 1,976,175｜vector_meta 1,968,563｜vectors.npy 1,073,741,952 B｜vector_status {'done': 8,690, 'na': 2,305}｜ocr_status {'done': 2, 'na': 8,537, 'pending': 2,456}｜missing_since 1｜队列 {'index:done': 10,935, 'index:failed': 75, 'ocr:done': 2, 'scan:done': 5}｜监测根 6 个｜schema 8`。
> **临时文件**：`.probe_work/` 顶层 **737 项（13 个子目录）｜递归 1,179 文件｜858.1 MiB｜顶层 0 字节 79 个**；`injection_inflight` **不在场**；本轮承重 `u32_i113_backup_delete.*`、`u32_ocr_vectors.*`、`u32_after_ocr_checks.*`、`u32_db_counts.*`、`u32_regression_full.log` 留在顶层。
> **会话日志体积（token 代理）**：**352,780,358 B｜108,813 行**（18:2x 取）vs 轮三十一基线 **347,987,493 B / 107,596 行** ⇒ **+4,792,865 B｜+1,217 行**。

---

## 4.44 轮三十三 · I116 甲改向量入场券 + 497 页 OCR 正文补建 492 条向量 + CHANGELOG 再切一册 + 整链 12 段（3 红）（2026-10-28 00:0x → 02:2x）

用户指令逐字：「I116 甲（做完③，你勾一下就行）→ 下一轮开篇切 CHANGELOG + 跑一场整链。」三件按序做完；整链这一场 **35 条判定 / 3 红**，三条都据实入账，没有重跑到绿、没有抬阈值。

**A · I116 甲：向量入场券归一到 `has_searchable_text(doc)`**
- 定义只一处（`services/index_service.py`）：`doc.text_status in TEXT_SEARCHABLE or doc.ocr_status in (OCR_DONE, OCR_PARTIAL)`，`TEXT_SEARCHABLE` 仍是 `("native","mixed")`；`services/vector_service.py` 的 `_why_skipped()` 与 `build_vectors()` 两处改走它，跳过标签改成「没有可搜的正文，先索引或先识别」，失败原文同时带 `text_status` / `ocr_status` 现场值。
- **没改的东西**：OCR 的唯一写入口（`mark_ocr_result` 不碰 `text_status`）、`TEXT_SEARCHABLE` 本身、数据形状与列语义。
- `tests/integration/test_vector_write_path.py` **18 passed**（新增 2 条：`test_OCR_出过正文的扫描件也能建向量`、`test_入场券两个条件任一成立即放行`——9 组合真假表）；**坏法真注入**：谓词退回只看 `text_status` ⇒ **2 failed / 16 passed**，红的正是这两条；撤掉还原 18 passed。

**B · ③ 真库补建 492 条向量（00:0x，走产品入口、零裸 SQL）**
- `.probe_work/u33_vector_backfill.py` → `.json`：只调 `VectorService.request_vectors()` + `build_vectors()`（与界面「送去识别」之后的回填同一条路）。回执逐字「点名 2 份｜该建 2 份｜新增任务 2 条」、`skipped {}`（轮三十二这里是 `not_searchable` 两条）。
- doc 10995（《不寄的信》，`text_status=none` / `ocr_status=done`）：`pages_expected 262｜pages_embedded 256｜pages_skipped_empty 6｜4,769ms｜done`；doc 10997（《雪绒花的庆典》）：`236 / 236 / 0 / 2,563ms / done`。合计 **+492 条向量 / 7.33s**。
- 库内：`vector_meta 1,968,563 → 1,969,055`（**+492 = 256 + 236**）、`vector_status done 8,690 → 8,692`、`na 2,305 → 2,303`。
- **可搜证明用自检索**（`.probe_work/u33_selfcheck.json`，只读）：四页拿自己的正文查回 **rank 1** —— 10997 p235 **0.9262**（285 字）、p14 **0.9340**（718 字）；10995 p1 **0.9283**（21 字）、p3 **0.9308**（22 字）。197 万页的全局 top-k 争 20 个名额不是合格判据。
- **如实记两条反面/边界读数**：`"倪匡散文"` 全库 top-20 里 **3 行来自 10995** 且包揽前二（p1 `0.7035` / p3 `0.6946`）；`"赫拉巴尔"` top-20 里 **10997 零行**，扩到 top-200 才 3 行（最好 p16 `0.5458`）—— 书名查询不能代表全书召回，向量确实建了。
- **副作用（自己留下的，一行没清）**：探针先 `request_vectors()` 再直接 `build_vectors()` ⇒ 队列里留了两条 `vector:queued`（**11019 → doc 10995、11020 → doc 10997**，`attempts 0`，`created_at 1793117160`）。这两条在整链 C9 的现场读数里可见（`'queued': 2`），但 C9 判据是「running 无主」，所以仍绿。

**C · CHANGELOG 再切一册（D-059 第 4 条：活册 > 600 行）**
- `.probe_work/u33_changelog_split.py` 自检不过就拒写：切点与文末指针各须命中**恰好 1 次**，拼回去必须**逐字等于原文**才落盘；切前原件 md5 备份 `791e9ea4…`。
- 结果：活册 **1,178 → 550 行**，`勾选轮（十九）` … `勾选轮（七）` **13 段 / 631 行**逐字搬进 `docs/CHANGELOG-ARCHIVE-2.md`（**647 行**）；`勾选轮（六）` 及更早在 `CHANGELOG-ARCHIVE.md`（**1,064 行，一字未动**）。轮次标题数守恒 **26 = 13 + 13**。
- `tests/guards/test_doc_pointers.py` 的 `LEDGER_DOCS` 加新册 ⇒ guards **59 passed**。写完本轮条目后活册 **599 行（余 1）**。

**D · 整链 12 段一条命令（00:07 → 01:56:51，约 110 分钟）—— 35 条判定 / 3 红**
- 起跑负载逐字：`CPU 70.7%｜可用内存 3570MiB｜最吃内存进程 ZCode.exe 505MiB`（regression 段期间我自己还跑过两次短 pytest）；末行 `合计判定 35 条｜本次未跑 0 段` + **`VERDICT: RED（3 条未过）`**。
- 段耗时：docs-inject 0.0s｜guards 3.5s｜regression **253.3s**｜coldstart 2.0s｜e2e 18.4s｜injection **917.1s**｜ui-inject 93.0s｜ocr 33.9s｜consistency **4,535.9s**｜soak 322.5s｜package 355.1s｜g2 44.1s（合计 ≈ 6,429s）。
- **红①regression**：`823 passed / 1 failed / 0 error / 1 skipped（250.68s）`，唯一失败 `tests/integration/test_app_shell.py::test_进程级冷启动实测符合G1约定`。
- **红②e2e**：`冷启动 1.674s｜进程总耗时 2.946s｜worker 1 线程｜回收中断 0`，现场「冷启动 1.674s 超过约定 1.5s」。**同一场链的 coldstart 段自己是 `1.329s｜1.979s｜关窗对账 1 条` PASS** —— 两次冷启动差 0.345s，阈值 **1.5s 一个字没动**（I102 / I25 的 MITIGATED 残留：负载下冷启动会越线）。
- **红③consistency p12 真根**：`VERDICT: RED（2 条未过）｜4,528.6s｜合计 19 条｜红 2 条｜未验 0`。
  - `C3·D:\`：盘上 PDF **96** / 该子树主记录 **94**（已标缺失 0）⇒ 盘上有、库里没有 2 份，都是 2026-10 新落的微信 PDF（`dify安装攻略20261020.pdf`、`互联网流量集中、平台变现与商家经营成本研究.pdf`）——**数据漂移，不是代码**，与轮三十的 5 份同类。
  - `C5`：正文 **1,976,175** 页（其中 ocr 497）**6 行正文是空串** —— 定位 doc **10995** 页 **17 / 27 / 39 / 73 / 135 / 217**，`source_kind='ocr'`、`char_count=0`、`ocr_version` 非空，正是 OCR 的**页级完成标记**（`texts.ocr_versions_of()` → `pages_needing_ocr()` 靠它判 `reused`）⇒ 与 C5「不许养零信息行」正面冲突，新开 **ISSUES I117**（推荐甲：给标记行豁免），**本轮不改判据**。
- 其余九段全绿：docs-inject（三条坏法全红 + 好台账不误判）｜guards（G21 / 架构 / 四份文档 / 五分栏 / 占位符 / 实测引用 / 台账 / 失效测试名 全 PASS）｜coldstart `1.329s` PASS｜injection **917.1s**（p9 **70/70** 303.8s、p10 **45/45** 179.1s、p16 11 条 31.4s、p17 8.7s、p18 10.6s、p21 **24/24** 95.5s、p22 **33/33** 131.4s、p23 **23/23** 94.7s、p24 **17/17** 61.9s）｜ui-inject 93.0s｜ocr 33.9s（单页推理 1,798.6 / 2,143.6 / 2,912.2 ms、6 页、整本墙钟 13.74s）｜soak 322.5s（**9 条 0 红**、注入 **13/13** + 好读数 **4/4**、RSS 首段中位 112.7 → 末段中位 112.8MiB、S6 峰 35 排空 1.0s、采样 60 点最大空洞 2.0s）｜package 355.1s（构建 207.3s + 冒烟 147.8s、整包 **400.1 MiB**、documents **273 / 磁盘 273**、冻结冒烟 ALL GREEN）｜g2 44.1s（负载分类自检 **6/6**；这一段日志只落 `VERDICT: ALL GREEN`，**没打印 P95 数字**，不引用）。
- **口径纪律**：三条红都是**一场跑出来的**，没有为凑绿重跑；G1 1.5s、G2 500ms、忙线 60% 三处阈值与本轮 `src/` 代码零改动。
- **链跑的时点**：docs-inject/guards 在 00:07 读的是**切册前**的台账（`116 行｜CLOSED 89｜OPEN 2`），此时 I117 还没写 ⇒ 收尾在最终树上复跑 `scripts/precheck.py` 补这一格。

**E · 台账与文档**
- 台账：I116 **OPEN → CLOSED**（两格都贴了实测读数）；新开 **I117**（`OCR 空正文标记行 ↔ C5 口径冲突`，甲/乙/丙，**推荐甲**，明确「本轮不改判据、不改 OCR 路径」）⇒ **117 行｜I1–I117 连续不重号｜CLOSED 90｜MITIGATED 24｜OPEN 2（I115 / I117）｜WONTFIX 1｜结构不合格 1 行（上限 1）：I35**（`gates.final.ledger_check()` 现读，不是手数）。
- 文档：`CHANGELOG`（本轮条目 + 两册指针）、本册 §4.44、`DECISIONS` D-061 追注、`ARCHITECTURE`（`vector_service.py` 注释）、`README`（日志索引指向两册）。

**F · 仍欠的**
- **I115**（跨卷搬家 `_adopt_renamed` 认不出改名）、**I117**（C5 与 OCR 标记行的口径）—— 两条都等勾选，本轮零改动。
- 两处**要勾选才动**的现场：① 队列里 2 条 `vector:queued`（11019 / 11020，甲 单事务删 / 乙 开应用让 worker 跑完 / 丙 只记不动）；② `C3·D:\` 2 份未索引 PDF（走产品路径 `ScanService.reconcile_path` + `IndexService.index_document` 重扫）。
- **CHANGELOG 599 行（余 1）**：下一轮**开篇先切册再写**。
- ④ 24 小时 soak、⑨ injection 真空载（CPU<10%）、安装包与代码签名、隐私政策 —— **D-062 已定案「不做」**，不再列为待办；历史读数保留原样。

---

## 4.45 轮三十四 · I115 甲 + I117 甲 + 删 2 条 `vector:queued` + 2 份微信 PDF 入库 + p12 真根 19 条 / 2 红（2026-10-28 02:0x → 04:2x）

用户指令逐字：「① I115 跨卷搬移根因（推荐甲）｜② I117 C5 给 OCR 页级标记行豁免（推荐甲）｜
③ 两条 vector:queued（甲 删 / 乙 开应用让 worker 跑完 / 丙 只记）｜④ C3·D 那 2 份微信 PDF 重扫。
都跟进你的建议来」。四件全按推荐项做完；末尾 p12 真根 **19 条 / 红 2**，两条红都是新落盘的数据漂移 ——
没有重跑到绿、没有抬任何阈值。

**A · I115 甲：认改名补一条「按文件事实」的旁路**
- `services/scan_service.py`：`_adopt_renamed` 拆成 `_renamed_by_inode`（同卷，`(device_id, file_id)`，
  原逻辑原样搬过去）+ `_renamed_by_facts`（Windows 跨卷搬移是「复制 + 删源」、inode 换了，
  退回 `(name, size_bytes, mtime_ns)`）。
- 两条路共用同一条硬条件：候选**恰好一条**、旧路径**已不在盘上**；多于一条或任一项不等，一律不认 ——
  「不猜」没有因为多开一条旁路而放宽。仓储新增 `documents.missing_by_facts()`：
  只查 `missing_since IS NOT NULL` + `ORDER BY id LIMIT 2`（取两条只为分辨「恰好一条」）。
- `tests/integration/test_scan_service.py` **38 passed**；新增 4 条（跨卷认回同一主键／只差 mtime／
  只差 size（参数化 2 例）／事实对上多条时仍不猜）。**坏法真注入两次**：摘掉兜底 ⇒ 跨卷那两条红；
  把「恰好一条」放宽成「取第一条」⇒ 三份同名那条红；撤掉还原全绿。

**B · I117 甲：C5 只豁免「OCR 页级完成标记」**
- `tests/probes/p12_consistency.py` 的 `c5_pages()` 把空串拆两半：`source_kind='ocr' AND char_count=0
  AND ocr_version IS NOT NULL` 是标记行（`texts.ocr_versions_of()` 靠它判 `reused`，删了那几页会重烧），
  其余才是零信息垃圾；**只有真垃圾 > 0 判红**，读数改成「空串 N 行（其中 OCR 页级标记 M、真垃圾 K）」。
- 新文件 `tests/integration/test_consistency_c5.py` **2 passed**；坏法两向都真做过（删豁免 ⇒ 标记那条红；
  把豁免放宽成「任何空串都算标记」⇒ 垃圾那条红）。`p12 --inject` **22/22 条坏法 + 口径边界 1/1 ALL GREEN**
  （新增的那条坏法就是「原生正文页写成空串」）。

**C · ③ 甲：单事务删 2 条 `vector:queued`**
- 备份在先：`%TEMP%\pdfarchiver-u34-vector-queue-backup\catalog.db`，**12,113,543,168 B**
  （00:06 那份快照，尺寸与删除前的库逐字节一致）。
- 一个事务删 `kind='vector' AND state='queued'` 的两行（11019 → doc 10995、11020 → doc 10997，`attempts 0`）。
  只读复核：`processing_jobs 11,019 → 11,017`｜两条 id 都不在｜`vector:queued` **0 行**｜外键孤儿 **0**｜
  doc 10995 / 10997 仍 `vector_status=done` ⇒ `DELETE GOOD`。
- **自己踩的坑（照记）**：第一版探针把两张表各数两遍，12 GB 冷读下 10 分钟没出数（CPU 只 144 → 162s，
  瓶颈在磁盘）；杀掉自己的进程后改用廉价只读查询收口，没有再跑一次全表 count。

**D · ④ 2 份微信 PDF 走产品路径入库（零裸 SQL）**
- `ctx.scan.reconcile_path()` → `IndexService.index_document()` → `VectorService.request_vectors()`：
  `dify安装攻略20261020.pdf` **1/1 页**（171ms）、`互联网流量集中、平台变现与商家经营成本研究.pdf`
  **32/32 页**（1,129ms），两份 `text=native / fts=done`，doc **11000 / 11001**；向量回执
  「点名 2 份｜该建 2 份｜新增任务 2 条」→ 随后 `vector:done 2`。
- 库内：`documents 10,995 → 10,997`｜`text_pages 1,976,175 → 1,976,208`（**+33 = 1 + 32**，与页数对得上）｜
  `vector_meta 1,969,055 → 1,969,088`（**+33**）｜`vector_status done 8,692 → 8,694`、`na 2,303` 不变。
- **自检索 4/4 rank 1**：doc 11000 p1 **0.9296**（1,017 字）；doc 11001 p1 **0.9268**（48 字）、
  p2 **0.9309**（127 字）、p4 **0.9329**（794 字）。
- **自己踩的第二个坑**：`.probe_work/u34_rescan.py` 的等待循环调了不存在的 `status.queue_counts()`
  （`grep -rn "def queue_counts" src/` 零命中），一跑就会白睡 40 分钟；向量任务确实跑完后我停了进程，
  收口证据改用独立只读脚本补，JSON 里写明原因。

**E · p12 真根复跑（02:56 → 04:07，约 71 分钟）—— 19 条 / 红 2 / 未验 0**
- 末行 `VERDICT: RED（2 条未过）`。逐条计时：C1 **1,004,847ms**｜C3 六行同一个循环累计 **807,038ms**｜
  C4 188,158ms｜C5 **1,341,650ms**｜C11 922,237ms｜C12 4,195ms｜C2 3,236ms｜其余 ≤216ms；
  逐项合计 **4,271,616ms ≈ 4,271.6s**，与墙钟 71 分钟吻合。
- 三件待验的都转绿：**`C3·D:\` 96 / 96**（轮三十三是盘上 96 / 库里 94）｜**C5「空串 6 行
  （其中 OCR 页级标记 6、真垃圾 0）」**｜**C9 `running 0` + `{'done': 10,944, 'failed': 75}`**
  （队列里再没有 `vector:queued`）。同场其余绿：C2 主记录 10,997 两项一致｜C4 正文 = 花名册 **1,976,208**｜
  C7 `done 8,694 / na 2,303`｜C10 14 类｜C11 快照体检 922,221ms｜C12 0/0/0｜C13 六根同口径。
- **两条新红，都是数据漂移不是代码**：`C3·lavie` 盘上 69 / 库里 68，漏 1 份
  `20260812第196回 在AI时代，用AI完成弯道超车.pdf`（文件 mtime **02:11**）；`C3·H:\` 盘上 1,860 /
  库里 1,857（已标缺失 1），漏 4 份，全在 `h:/others software/xjpdfeditor/` 与 `…/xunjiepdfconverter/sample/`
  下（那两个目录时间戳 **02:04**）。两份都晚于轮三十三那场链 01:56 的收尾 —— 这一场里 E / F / G
  三个根全相等（1,969 / 5,352 / 1,655），说明判据本身没问题。
- **口径纪律**：没有为凑绿重扫、没有动任何阈值、`src/` 在这一段零改动；这一类「库只认上一次扫描」
  见新开的 **ISSUES I118**。

**F · 收尾**
- 回归：`830 passed / 1 skipped（188.75s）`（轮三十三整链里是 823 passed + 1 failed，差的 7 条正是本轮新增：
  4 条跨卷 + 2 条 C5 + 1 条参数化例；G1 冷启动那条这场是绿的 —— 安静窗口，不是改了阈值）。
- guards **59 passed**（17.06s）；`scripts/precheck.py` 末行 **ALL GREEN**（2 步 / 红 0；门禁 9 判定 / 未跑 10 段）。
- **预检途中逮到一条守卫到期并当场修掉（不抬线）**：`test_台账旧文件名不超过上限` 红在 **41 > 37**，
  多出来的 4 处**全是本轮自己新写的空指** —— 两个重扫/自检探针的裸文件名（共三处）
  与一个**还没建**的入口脚本名（I118 里推荐的那条）。按守卫自己的规矩改文档
  （探针名写全 `.probe_work/` 前缀、未建的文件名改成描述），改完正好 **37 = 上限**，复跑全绿；
  `PY_STALE_CAP` 一个字没动。**这条守卫连「描述它自己」的文字也数**：本轮第二节复核时，
  我把上面这三个裸名原样写进本节又红成 40 > 37 —— 第二次改法是本节不复述文件名，只留描述。

**G · 台账与文档**
- I115 / I117 **OPEN → CLOSED**（两格都贴了实测读数与坏法）；新开 **I118**（C3 每场红的数据漂移，甲/乙/丙，推荐甲）。
- `CHANGELOG` 先切册再写：活册 **599 → 338 行**，`轮二十四` … `勾选轮（二十）` **262 行**逐字搬进分册二
  **647 → 914 行**（排在 `勾选轮（十九）` 之前），标题数守恒 **29 = 9 + 20**；切前两份原件 md5 备份。

**H · 仍欠的**
- **I118** 等勾选（要不要把「按监测根增量重扫」固定成一个入口）；`C:\` 1 份与 `H:\` 4 份新漂移要不要
  补索引同样等勾选。
- 四项「不做」（24 小时 soak / injection CPU<10% 真空载 / 安装包与代码签名 / 隐私政策）按 **D-062**
  维持不做，不再列为待办。

> **本册末行现数（2026-10-28 轮三十四收尾取，含本轮条目写完后复量）**：`CHANGELOG 393（余 207）｜DECISIONS 720（余 180）｜本册 569 → 659（余 541）｜
> 分册一 1,064（余 136）｜分册二 914（余 286）｜ISSUES 156｜UI-WIREFRAMES 1,009（余 191）`；**最紧的是分册一（余 136）** ——
> 它下一次到 1,200 才开第三册；活册切完 338、写进本轮条目后 393，离 600 还有 207 行，不必再切。
> **台账**：`118 行｜I1–I118 连续不重号｜CLOSED 92｜MITIGATED 24｜OPEN 1（I118）｜WONTFIX 1｜结构不合格 1 行（上限 1）：I35`；
> 本轮 I115 / I117 **OPEN → CLOSED**、新开 I118 一行 OPEN，其余零状态迁移。
> **测试**：回归 **830 passed / 1 skipped（188.75s）**｜guards 全量 **59 passed**（预检三场：修空指前 11.67s 红 1、修后 **17.06s** 全绿、
> 写完全部收尾文档后的最终树复核 **10.91s** 全绿 —— 中间还有一场 40 > 37，见 F 节第二条；快慢差来自负载不是代码）｜
> p12 真根 **19 条红 2**（C3·lavie 1 份 + C3·H 4 份，都是 02:04 / 02:11 新落盘的文件）｜
> `p12 --inject` **22/22 + 1/1 ALL GREEN**｜`scripts/precheck.py` 末行 **ALL GREEN**（最终树最后一次：2 步 / 红 0，门禁 9 判定 / 未跑 10 段、台账 118 行在场）。
> **真库现数（只读，04:1x 取；p12 与回填之后零写入）**：`catalog.db 12,113,711,104 B｜documents 10,997｜text_pages 1,976,208 = content_fts 1,976,208｜
> vector_meta 1,969,088｜vectors.npy 1,073,741,952 B｜vector_status {'done': 8,694, 'na': 2,303}｜
> ocr_status {'done': 2, 'na': 8,539, 'pending': 2,456}｜missing_since 1｜队列 {'index:done': 10,935, 'index:failed': 75, 'ocr:done': 2, 'scan:done': 5, 'vector:done': 2}｜
> 监测根 6 个｜schema 8`。
> **临时文件**：`.probe_work/` 顶层 **776 项（13 个子目录）｜递归 1,218 文件｜862 MiB｜顶层 0 字节 80 个**；
> `injection_inflight` **不在场**；本轮承重 `.probe_work/u34_p12_real.log` / `u34_p12_real.json`、`.probe_work/u34_p12_inject.log`、
> `.probe_work/u34_clear_vector_queue.*`、`.probe_work/u34_rescan.*`、`.probe_work/u34_selfcheck.*`、
> `.probe_work/u34_regression.log`、`.probe_work/u34_precheck.log` / `u34_precheck2.log`、`.probe_work/u34_changelog_split.py` 留在顶层。
> **会话日志体积（token 代理）**：**363,787,051 B｜111,516 行**（04:1x 取）vs 轮三十三基线 **358,659,988 B / 110,220 行** ⇒ **+5,127,063 B｜+1,296 行**。


## 4.46 轮三十五 · I118 甲 按监测根重扫做成固定入口 + 桌面 1 份扫描件入库（2026-10-28 05:0x → 05:36:54）

用户指令逐字：「跟进你的建议来」= 我给的**选项 1**：建 I118 的固定入口 + **只补桌面那 1 份**；
`H:\Others Software\` 那 4 份软件自带样例 PDF 明确不动。两件都做完。

**A · 入口 `scripts/rescan_roots.py`（197 行，零裸 SQL）**
- 按根走 `ScanService.scan_root`；点名单文件走 `ScanService.reconcile_path` + `IndexService.index_document`；
  `--vectors` 走 `VectorService.request_vectors`。**默认只读预演**（末行 `RESCAN: DRY-RUN`），`--apply` 才写库。
  `--only <子串>` 选根、`--paths <文件…>` 只补点名的那几份 —— `C:\Users\lavie` 整棵子树会走进 AppData，
  真库这一步只能走单文件路。排空不自己起线程：`ctx.start_background()` 交给产品 worker，
  `counts_by_kind_state()` 轮询 `queued/running` 归零，超时打 `RESCAN: RED` 而不是偷偷拖长（默认 30 分钟）。
  末行刻意用 `RESCAN:` 前缀 —— `VERDICT:` 是 `gates/*` 引用脚本的专用收尾语，守卫只认那些。
- `tests/integration/test_rescan_roots_script.py` **4 passed / 5.75s**；**三条坏法真注入**
  （`.probe_work` 下那个注入脚本：备份 → 改 → 跑 → 按条目名判红 → 还原）：重扫换成空报告 ⇒ 2 条红｜
  把 `--only` 的过滤整段摘掉 ⇒ 1 条红｜把 `--paths` 分支改成死码 ⇒ 1 条红；还原后 md5
  `9a006b3f047bf9e97ab71551b5f99d86` 与原文一致、4 条复绿（`INJECT: ALL CAUGHT（3/3）`）。

**B · 真库写入：doc 11002（用户点名的那一份）**
- 预演先跑：6 个监测根逐个列出（`last_full_scan_at` 都在）、桌面那份报「库里没有」、末行 `RESCAN: DRY-RUN`
  （`.probe_work/u35_rescan_dry.log`，exit 0）。
- `--apply --vectors --paths …`：`[file] added｜doc 11002｜索引 30/30 页 text=none fts=done 186ms`
  （`.probe_work/u35_rescan_apply.log`）。只读复核（`.probe_work/u35_baseline_fast.log` 为写入前基线）：
  `documents 10,997 → 10,998`、`text_pages 1,976,208 → 1,976,238`（+30）、`vector_meta 1,969,088` **一字未变**、
  队列分布与写入前逐字相同 ⇒ **零新增 queued 行**。

**C · 口径边界：这份扫描件「全文搜得到、向量建不了」**
- 30 页 `source_kind='native'` 合计 **504 字**（12–39 字/页，是幻灯片标题，例 `BDS 炒饭会 候选边界`、`BDS 炒饭会 综合结论`）；
  `text_bearing_rate 0.0`（判据是「去空格后 ≥40 字的页」占实际读到的页，见 `parsing/classify.py`）⇒
  `text_status='none'`、`ocr_status='pending'` ⇒ `has_searchable_text()` 不放行向量。
- 于是 `--vectors` 打印 `点名 1 份｜该建 0 份｜新增任务 0 条｜没有可搜的正文`、`跳过 {'not_searchable': [11002]}` ——
  这是 **I116 甲** 的入场券在干活，不是失败。**全文通道照常**：30 行正文都进了 `content_fts`，搜标题能命中。
  要让它**语义**可搜得先「送去识别」（30 页 OCR），本轮不做（用户指令只到「补索引」）。

**D · 证据边界（明写，别当门禁读数用）**
- **p12 真根整场本轮没跑完**：05:23:22 起跑，05:28 主动中止（用户要求收敛，不为复核一行拖 70 分钟），
  `.probe_work/u35_p12_real.log` 只有数据根那一行 ⇒ **本场不作数、无读数**。
- 因此 `C3·lavie` 转绿**本轮只有产品路径证据**（doc 11002 在场、path/size 与盘上一致、`fts_status=done`、30 行正文），
  **没有门禁读数**；归**下一场整链**的 consistency 段复核。`C3·H:\` 按 **I119** 仍会红 4。

**E · 台账与文档**
- **ISSUES I118 OPEN → CLOSED**（入口已交付并验证，两格都贴读数与坏法）；新开 **I119 OPEN**（那 4 份样例的处置，甲/乙/丙，推荐甲＝给 `H:\` 根加两条排除规则）。
- `CHANGELOG` 轮三十五条目；`docs/ARCHITECTURE.md` 的 `scripts/` 逐文件表补 **`rescan_roots.py`**，
  顺带补上一直漏登的 **`precheck.py`**（轮二十三加的，之前没进那张表）。

**F · 测试与收尾**
- 全量回归 `pytest tests -q`：**834 passed / 1 skipped（217.71s）**，EXIT=0（`.probe_work/u35_regression.log`）。
  比轮三十四的 830 passed 多 4 条，正是本轮新增的 `tests/integration/test_rescan_roots_script.py`。
- `tests/guards` 全量：**59 passed（15.38s）**（`.probe_work/u35_guards_full.log`）。
- **本轮没跑 p12**：真根整场 05:23 起跑、05:28 主动中止（见 D 节），也没为它补跑 `--inject` ——
  入口的坏法证据是 `.probe_work` 下那个注入脚本的 3 向真注入（3/3 全逮 + md5 还原逐字节一致），不是 p12。
- `scripts/precheck.py` **两场**：第一场 **红 1**（`tests/guards 58 passed / 1 failed`，13.23s）——
  `test_doc_pointers.py` 的旧文件名上限 **38 > 37**，原因是我在 runlog 里裸写了 `.probe_work` 那个注入脚本的文件名，
  守卫按「src/gates/tests/packaging/scripts 之外的文件名 = 旧指针」计；**改文档不抬上限**：三处裸文件名改成描述性写法后
  复跑 **59 passed（14.01s）**、`gates/final.py docs-inject + guards` 9 判定全绿 ⇒ 末行 **VERDICT: ALL GREEN**（`.probe_work/u35_precheck.log`）。
- 收尾时顺手清掉一个我自己误建的 0 字节 `Data/PdfArchiver/catalog.db`（只读查询时 sqlite 连接的产物，真库在 `data/` 下），`rm` 前后真库未受影响。

> **本册末行现数（2026-10-28 轮三十五收尾取，含本轮条目写完后复量）**：`CHANGELOG 428（余 172）｜DECISIONS 720（余 180）｜本册 659 → 735（余 465）｜
> 分册一 1,064（余 136）｜分册二 914（余 286）｜RUNLOGS 分册一 757（余 443）｜分册二 727（余 473）｜ISSUES 157｜UI-WIREFRAMES 1,009（余 191）`；
> **最紧的仍是分册一（余 136）** —— 它下一次到 1,200 才开第三册；活册 CHANGELOG 切完 338、写进本轮条目后 428，离 600 还有 172 行。
> **台账**：`119 行｜I1–I119 连续不重号｜CLOSED 93｜MITIGATED 24｜OPEN 0｜WONTFIX 2（I14 / I119）｜结构不合格 1 行（上限 1）：I35`；
> 本轮 I118 **OPEN → CLOSED**、新开 I119 一行，随后按用户「暂时不改，维持现状」（丙）**直接 WONTFIX**，OPEN 归 0。
> **测试**：回归 **834 passed / 1 skipped（217.71s）**（多出的 4 条 = 新增的 `tests/integration/test_rescan_roots_script.py`）｜
> `tests/guards` 全量 **59 passed（15.38s）**｜**p12 真根本轮无读数**（05:23:22 起跑、05:28 按用户「要收敛」要求主动中止 ⇒ 本场不作数，
> 不为复核一行再拖 70 分钟）｜`p12 --inject` 本轮**未跑**｜`scripts/precheck.py` 末行 **VERDICT: ALL GREEN**（最终树最后一次）。
> **真库现数（只读，05:33 取；`--apply` 那次写入之后零写入）**：`catalog.db 12,113,711,104 B｜documents 10,998｜text_pages 1,976,238｜
> vector_meta 1,969,088｜vectors.npy 1,073,741,952 B｜vector_status {'done': 8,694, 'na': 2,304}｜
> ocr_status {'na': 8,539, 'pending': 2,457, 'done': 2}｜missing_since 1｜队列 {'index:done': 10,935, 'index:failed': 75, 'ocr:done': 2, 'scan:done': 5, 'vector:done': 2}｜
> 监测根 6 个`（`content_fts` 是 `text_pages` 的外部内容表，全表计数分钟级，本轮不单独计）。
> **临时文件**：`.probe_work/` 顶层 **789 项（13 个子目录）｜递归 1,231 文件｜862 MiB｜顶层 0 字节 80 个**；
> `injection_inflight` **不在场**；本轮承重 `u35_baseline_fast.log` / `u35_rescan_dry.log` / `u35_rescan_apply.log` /
> `u35_verify_doc.log` / `u35_page_bodies.log` / `u35_guards_full.log` / `u35_inject_rescan`（注入脚本，备份件 `u35_rescan_roots.py.bak` 同留）/
> `u35_p12_real.log`（中止场，只有数据根一行）/ `u35_regression.log` 留在顶层。
> **会话日志体积（token 代理）**：**367,152,492 B｜112,278 行**（05:33 取）vs 轮三十四基线 **363,787,051 B / 111,516 行**
> ⇒ **+3,365,441 B｜+762 行**；token 本身不可得（本环境 usage 恒 0，见内存 `reference-agent-worktime-token-metrics`）。

## 4.47 轮三十六 · 乙 启动即增量同步 + 丙 命中解释 + 甲 OCR 按需 + I11 丙-甲 真库 20 条评测 + 收尾（2026-10-28 05:4x → 10:2x）

用户指令逐字：「1+2+3+4」（四项产品建议全要）＋「都按你推荐」（八个编号决策全按推荐、两批执行：
乙/丙/甲 + I11 本轮，丁 库内问答（S9 新屏，抽取式）与 8·屏位 下轮，且**先过线框确认**）。

**A · 乙 启动即增量同步（I118 收口后状态读数的根因修复）**
- 实测形状：真库六根 `monitored_roots.last_full_scan_at` 全停在 **2026-10-16**，而库里文档已 10,998。
  根因不是巡检坏，是慢路按**连续运行时间**计时（`scan_verify_minutes=30` ⇒ 1800s/5s = 360 次轮询），
  应用一关一开计数器从 0 重来 —— 那个"30 分钟"在绝大多数会话里永远走不到点。
- 三处落点：`Patrol.poll()` 第一轮无条件排全量对账（`due_by_clock = self._polls == 1 or …`，
  增量式：没变的文件不排索引）；`MainWindow.start_patrol()` 起定时器**当场**跑一轮 `patrol_tick()`；
  `StatusService.sync_status()` 出 `SyncStatus`（启用根数 / 从未对账数 / `last_full_scan_at` = **各启用根里最早的那一刻** min / 排队与在跑分开）。
- 读数挂两处、同一份 `lines()`：状态栏**常驻 widget**（不走 `showMessage`，不被巡检 5 秒消息冲掉）+ S7 状态页。
- **10 条断言全绿**（`tests/integration/test_startup_sync.py`）＋ **8 条坏法真注入**
  （`.probe_work/u36_inject_startup_sync.py`：备份 → 改 → 跑 → 按条目名判红 → 还原 → md5 核对）：
  基线 10 passed；A 拆第一轮对账 ⇒ 5 failed（1/2/3 点名 + 7/9 连带）｜B 等第一个间隔 ⇒ 1｜C min 改 max ⇒ 1｜
  D 从未对账分支拆掉 ⇒ 1｜E 停用根数进来 ⇒ 1｜F 同步读数改走临时区（真被冲掉的那条机制）⇒ 1｜
  G 排队在跑并一句 ⇒ 1｜H S7 不铺 ⇒ 1；还原后 md5 逐字节一致，`INJECT: ALL CAUGHT`。
  注入设计自我纠偏一处：原想把 `addPermanentWidget` 摘掉当 F 的坏法 —— 那不会红（测试断言的是文本不是可见性），
  改成把 `refresh_sync_cell` 改走 `showMessage` 才是"被冲掉"的真机制。

**B · 丙 命中解释 = 乙 选中即解释（#258）**
- `SearchResult.explain(hit)` 是**唯一**解释文案来源（界面不各写一份）；bm25 分数**只在 trigram 分支**给
  （LIKE 分支没有相关性得分，`format_bm25` 对 |score| < 0.005 印 `≈0` 防小数假精度）；语义命中显式写「非原文匹配」；
  解释行常驻最小三行高（右栏不因切换命中而跳动）；浅扫截断与 OCR 未识别两条措辞进解释。
- **12 条断言全绿**（`tests/integration/test_hit_explain.py`）＋ **A–G 共 11 组坏法**（记录在
  `.probe_work/round36_injections.md`）：10 组如期红；**D2 如实记 0 red** —— 删 `_clear_hits` 的 `setText(EXPLAIN_IDLE)`
  不会红，`QListWidget.clear()` 自己发 `currentItemChanged(None, prev)` 由 `_on_hit_current` 复位，
  那行是意图声明不是机制，还原后测试不改（不会变红的断言当场不删，但坏法也不硬凑）。
  合并回归 `test_hit_explain + test_ui_tier + test_search_service + test_theme_contrast = 69 passed`。

**C · 甲 OCR 按需（两个入口）+ 预算不够 = 甲 只排预算内的**
- 界面入口（OCR 批量页点名识别）与脚本入口（`scripts/` 路径）都接 `OcrService` 的按需计划；
  预算不够时**贪心部分排队**：排得进的全排、排不进的整份列出来，`SKIP_BUDGET_SHORT`（预算还够一份都排不进）
  与 `SKIP_BUDGET` 分开报，`budget_note()` 四档措辞（full/partial/short/empty）。
- 常驻探针 **p25**（`tests/probes/p25_ocr_on_demand_injection.py`，**10 条坏法**）进 `gates/final.py` injection 段：
  10/10 RED、基线 9 passed（`tests/integration/test_ocr_on_demand.py`）；锚点在场与行尾由
  `tests/guards/test_probe_anchors.py` 钉住（现 11 个探针）。p23 重跑 **26 条坏法**全红。
- 过程里守卫先报两处债：p23 的 U5 锚点漂移（上轮改措辞没同步锚点行尾）→ 修锚点；
  `tests/unit/test_ocr_plan_reads.py` 一条断言还守旧契约 → 按四档新契约重写。

**D · I11 丙-甲 真库自动造 20 条查询评测（#260，I11 的"查询来源"前置落地）**
- 方法：seed 20261028 可复现；池 = native 正文 500–3000 字、文件在盘、哈希序
  `(doc_id*2654435761 + page_no*40503) % 4294967291` LIMIT 2000，一份文档只取一页；每页造两条：
  **自然句**（取整句、剥掉全部非 CJK 字符、12–60 字 —— 模拟"记得内容、忘了数字和英文"）与
  **关键词**（最长两段 CJK 截 8 字，只记录不判分）。评测走**产品通路**：语义暴力扫（VectorStore，1,969,088 条）
  + `TextRepository.search_fts/search_like`（`channel_for` 分派、LIKE 走 60,000 行预算），
  只读连接 `mode=ro` + `_ReadOnlyEngine` 只暴露 `thread_connection()`。
- 调参两次如实记：池 600 行只造出 16/20（语料被发票类短页主导），改 2000 行 + 下限 150→500 字后 20/20。
- **四判定读数**（`.probe_work/u36_i11_eval.log` / `.json`）：
  ① Recall@10（按文档）**11/20 → 红**（门槛 ≥18；按页严格口径 9/20，同红，不拿文档级读数遮）；
  ② 互补性（FTS 召不回 & 语义召得回）**11/20 → 绿**（门槛 ≥4）；
  ③ 不回归：RRF(k=60) top-1 **9/20 vs 纯 FTS top-1 1/20 → 绿**（top-10：RRF 12 / FTS 1；RRF 只离线比，产品无混合通道）；
  ④ 可定位：违规 **0 条 → 绿**（每条命中带 doc_id + page_no + score ∈ [-1,1]）。
- 未中 9 条拆账：8 条真语义未中 + 1 条数据缺口（doc 4935：native 正文在场、**0 条向量** ——
  回填要写真库，等用户勾选，本轮不写）。**G15 仍不许宣布绿**（①没过）；
  销账最后一环仍是「用户那 20 条真查询」或换口径再复测。已写 ISSUES I11（维持 MITIGATED）+ SEMANTIC-EVAL §四指针。

**E · 收尾四件事**
- 全量回归 `pytest tests -q`：**866 passed / 1 skipped（202.99s）**，EXIT=0（`.probe_work/r36_regression.log`）。
  比轮三十五的 834 多 32 条 = 新增 `test_startup_sync(10) + test_hit_explain(12) + test_ocr_on_demand(9)
  + test_ocr_batch_panel_ui 预算部分排队(1)`。
- 清临时文件 3 个（引用先核零）：tests 误留的一条最小窗宽探针用例、
  `.probe_work` 下的 OCR 注入脚本与最小窗宽量测脚本（文件名不裸写进本册 —— 守卫口径见轮三十五）。
- 文档：CHANGELOG 轮三十六条目、ISSUES I11 改写、SEMANTIC-EVAL §四、UI-SCREENS §六（丁/S9 记待办）；
  坏法总账 `.probe_work/round36_injections.md`（乙 8 + 丙 11 + 甲 10 条）。
- **整链 12 段一条命令**（10:2x → 12:0x，36 判定 / **1 红** / 未跑 0 段）：回归 866/0/1（198.2s）｜
  coldstart **0.953s**｜e2e 13.1s｜injection 697.4s（p25 10/10 红（有牙）等九条全绿）｜ui-inject 71.5s｜
  ocr 30.4s｜**consistency 4,112.8s 真根 18/19**｜soak 320.7s｜package 267.0s（400.1 MiB）｜g2 **P95 299.0ms**（CPU 43.6%）。
  唯一红 = **`C3·H:\` 漏索引 4 份迅捷样例 —— 正是 ISSUES I119 WONTFIX**（用户 2026-10-28「暂时不改，维持现状」
  定下的每场照记红），不是新缺陷；**不许为它复跑、也不许写成「整链 ALL GREEN」**，本场口径 = **35/36 绿 + I119 照记**。
  预检终场（最终树）**ALL GREEN**（首场红 1 = 又把 4 个临时文件名裸写进文档 41 > 37，改描述性写法复绿，上限未动）。

> **本册末行现数（2026-10-28 轮三十六收尾取，§4.47 写完后复量）**：`CHANGELOG 483（余 117）｜DECISIONS 720（余 180）｜本册 736 → 807（余 393）｜
> ISSUES 157（I11 行改写不增行）｜UI-WIREFRAMES 1,009（余 191）`；
> **台账**：I11 维持 **MITIGATED**（①11/20 红，G15 不绿）、CLOSED 93｜MITIGATED 24｜OPEN 0｜WONTFIX 2（I14 / I119）不变。
> **测试**：回归 **866 passed / 1 skipped（202.99s）**｜坏法注入：乙 8/8 红（md5 还原一致）｜丙 10/11 红（D2 如实记 0 red）｜
> 甲 p25 10/10 红 + p23 26 条红｜I11 评测 ①红③绿（详见 D 节）。

## 4.48 轮三十七 · 甲 命中解释改行内后缀 + 丁 库内问答新屏 S9（抽取式）+ 收尾（2026-10-28 12:0x → 23:0x）

用户指令逐字：「§0+§A · 丙 · 命中解释 甲 +§B · 甲 · OCR 按需 跟进你的建议来+§C · 乙 · 启动即增量同步
跟进你的建议来+§D · 丁 · 库内问答 甲 还有什么需要我确认」＋「换成甲」（§A 从丙升甲）＋「这四个都完成了吗」
（收尾中追问，答：甲乙丙轮三十六落地、丁本轮以抽取式落地）。

**A · 甲 命中解释 乙→甲（行内后缀）**
- `SearchResult.suffix(hit)` 成为行内解释唯一来源（`search/service.py`）：解释直接缀在命中行尾
  「`[第 N 页]… · 解释`」，S1 不再保留下方独立解释带；bm25 分数**只在 trigram 分支**给，
  LIKE 分支没有相关性得分；语义命中显式写「非原文匹配」。
- `test_hit_explain` 按 10 条重写（原 12 条里解释带专属的断言随形态退役）；**8 组坏法真注入全红**
  （备份 → 改 → 跑 → 点名判红 → 还原 → md5 逐字节一致）；合并回归
  `test_hit_explain + test_ui_tier + test_placeholder_palette + tests/guards` 绿。

**B · 丁 库内问答新屏 S9（抽取式，不接生成模型——零幻觉零模型成本）**
- 后端 `QaService.ask()`：`Answer(query, elapsed_ms, summary, note, evidences)`；
  答案句「共找到 N 段相关正文，覆盖 M 份文档。」唯一 owner 是服务；证据卡头
  「文件名｜第 N 页｜相似度 0.xx」唯一 owner 是 `Evidence.header()`；TOP_SEGMENTS=8、摘录 120 字、
  `EXCERPT_NOTE`「这里是原文摘录，不是生成的话」；向量 0 时空态引导先去 S7 建语义索引。
- 界面两栏（历史 240 / 答案 720，页宽 <960 收左栏 = D-040 的 S9 版）；证据卡双击 → S2，
  载荷与 S1 `open_in_reader` 同口径 `(doc_id, page_no)`；范围读数与「向量 已建/未建」来自
  `VectorStore.stats()` 同一次扫描（真库 196.9 万行 **25ms 温／1.1s 冷**，只在懒建页与问答后刷，I111⑥/I109 纪律）。
- 架构守卫当场咬一条：`ask_page.py` 曾 import `semantic.qa_service.Evidence` —— ui 层禁入，
  按守卫规则改鸭子类型（只读字段、丢注解），**没有为过守卫动守卫**。
- **11 条断言全绿**（`tests/integration/test_ask_page.py`，3.23s）＋ **6 条坏法真注入全红**
  （UI 拼答案句 / 卡头自拼 / 载荷丢页码 / 历史不置顶去重 / 左栏收起删掉 / 范围写死全库）；
  **守卫当场逮到一条真缺陷**：`_remember_history` 只挡位置 0 的重复，
  问「问题一→问题二→问题一」会出现两条问题一 —— 改 takeItem-摘除再插顶。
- **一个 offscreen 陷阱（记进 dialog_doubles 头注的现场版）**：证据卡双击用例首跑挂死 9 分钟 ——
  假路径触发 `reader_page` 的 `QMessageBox.critical().exec()`，offscreen 下不红、只永不结束；
  修法 = `stub_message_boxes(monkeypatch)`（轮十五 甲 的既有道具），顺带多断两条
  （切到 S2 可见 + critical 被捕获）。

**C · 收尾四件事**
- 全量回归 `pytest tests -q`：**878 passed / 1 skipped（257.80s）**，EXIT=0
  （比轮三十六多 12 条 = test_hit_explain 12→10 重写 −2、test_ask_page +11、test_app_shell 随迁 +1 …净 +12）。
- **整链 12 段一条命令**（20:48 → 22:57，分段合计 ≈7,058s，**36 判定 / 1 段红 / 未跑 0 段**）：
  docs-inject 0.0s｜guards 2.9s｜regression 224.6s（878/1）｜coldstart **1.210s**（进程总 1.916s）｜
  e2e 19.3s（冷启动 1.154s）｜injection 981.2s｜ui-inject 90.5s｜ocr 36.7s｜
  **consistency 4,971.3s 真根 19 条红 2**｜soak 324.1s｜package 359.5s（整包 **400.1 MiB**）｜
  g2 **P95 299.0ms**（CPU 43.6%）。
  两条红都在 `C3` 双向对账：① `C3·H:\` 漏索引 4 份迅捷样例 = **ISSUES I119 WONTFIX 每场照记**
  （用户 2026-10-28「暂时不改，维持现状」，不是新缺陷、不为它复跑）；② `C3·D:\` 盘 97 / 库 96，
  漏索引 1 份 = 链跑期间微信 filestorage 新落的 PDF（数据漂移，不是代码缺陷）——入库要写真库，等用户勾选。
  **本场口径 = 34/36 绿 + I119 照记 + C3·D 漂移 1 份待勾选，不许写成「整链 ALL GREEN」**；
  阈值三处（G1 1.5s / G2 500ms / 忙线 60%）一个字没动。injection 本场 981.2s vs 轮三十六 697.4s
  是整机档位（见 §4.46 同类），不换算。
- 预检首场（写文档前）**ALL GREEN**（guards 59 passed 14.20s；docs-inject + guards 9 判定）。

> **本册末行现数（2026-10-28 轮三十七收尾取，§4.48 写完后复量）**：`CHANGELOG 528（余 72）｜DECISIONS 752（余 148）｜本册 815 → 870（余 330）｜
> ISSUES 157（本轮零新增）｜UI-WIREFRAMES 1,011（余 189）`；
> **台账**：CLOSED 93｜MITIGATED 24｜OPEN 0｜WONTFIX 2（I14 / I119）不变；
> `C3·D` 那 1 份漂移是数据事实不是台账行（同轮三十 b vlgari 先例），入库后由下一场整链复核。
> **测试**：回归 **878 passed / 1 skipped（257.80s）**｜坏法注入：甲 8/8 红（md5 还原一致）｜S9 6/6 红｜
> 整链 36 判定 34 绿 + C3 两条（I119 照记 + 漂移 1 份）。

## 4.49 轮三十七追记 · C3·D 漂移 1 份走固定入口入库（用户「做你建议的执行」，2026-10-28 23:1x）

`scripts/rescan_roots.py`（I118 甲 的固定入口）：只读预演确认「库里没有」→ `--apply --paths --vectors` 真写——
doc **11003**（微信 filestorage 2026-10 新落的那份），**201/201 页、`text_status=mixed`、`fts=done`、1,349ms**；
向量「该建 1 份」当场排空 **8.0s，201 条全建成** ⇒ 语义直接可搜（与 doc 11002 的 `text=none` 被入场券拒收对照）。
只读复核：`documents 10,998 → 10,999`｜`text_pages = content_fts 1,976,238 → 1,976,439`（+201，201 页全有字）｜
`vector_meta 1,969,088 → 1,969,289`（+201）｜队列 `queued 0`、分布 done 10,945 / failed 75 与写前逐字相同。
**C3·D 由此转绿**（判据：盘 97 = 库内该子树 97 − 已标缺失 0；下一场整链 consistency 复核，不为这一行单独跑 70 分钟）；
整链口径从本场起 = **35/36 绿 + I119 照记**。写途中学费一条：写前全表 COUNT 在冷库上超时转后台，
与真写并发抓到中途快照（documents 旧值 + vector 新值混着）⇒ **弃用作证**，基线改用今晚整链 C3 对账现数。

## 4.50 轮三十八 · 收尾双执行：C3·D 转绿复核 + I11 模拟真实用户评测（2026-10-29）

用户指令逐字：「你就执行这两条」（I11 收口 + C3·D 复核，做完不再开新工作）
＋「你替我进行测试 模拟真实测试就好」（I11 的 20 条查询授权由 AI 模拟）。

**A · consistency 复核 —— C3·D 转绿确认**
- `gates/final.py --only consistency`（真库基目录），**4,793.3s**，起跑 CPU 29.4%（低负载场），
  19 条判定红 2：`C3·D:\` **不在红名单 = 转绿确认**（doc 11003 由 §4.49 入库后首场对账认可，
  ISSUES I118 固定入口就此收口）；`C3·H:\` 红 4 = **ISSUES I119** 每场照记。
- 新发现 `C3·lavie` 红 1：漏索引 1 份 = `.zcode` CLI 工具自己的 PDF 缓存
  （会话哈希文件名，非用户文档）⇒ 数据漂移、非代码缺陷，开账 **ISSUES I120**（OPEN 等勾选：
  甲 索引进库 / 乙 WONTFIX 照记【推荐】/ 丙 排除规则加 `.zcode`），本轮零写库零配置改动。

**B · I11 模拟真实用户评测（seed 20261029，全程只读）**
- `.probe_work/u37_i11_eval.py` → `.log` / `.json`：判分口径与轮三十六同源（D-035 四判定，
  产品通路 `SemanticSearchService` + `TextRepository`，RRF 离线口径）。查询造法改成
  「用户记要点敲关键词」= 页内最长两段连续中文各截 6/4 字、空格相连；同场整句风格 A/B 对照。
- **读数（判分主口径 = 用户风格关键词）**：① Recall@10（doc 级）**2/20 红**（按页 2/20）｜
  ② 互补性 **2/20 红**（门槛 ≥4）｜③ 不回归绿（RRF top-1 1/20 vs 纯 FTS top-1 0/20）｜
  ④ 可定位 0 违规绿。**A/B 整句风格：① 11/20（按页 10/20）**，与轮三十六 11/20 一致（复现）。
- 如实结论：模拟查询两个口径都到不了 18/20 门槛；「关键词」是从长句硬截的碎片
  （例「来自全球化及 向这一系」），不是真实用户会打的字 —— **模拟替代不了查询作者本人，
  I11 维持 MITIGATED、G15 仍不绿**；不再换口径复跑（复跑挑口径 = 凑绿）。
  I11 收口条件不变：用户本人 20 条真查询，贴来即跑。

**C · 台账与文档**
- ISSUES：I11 追记轮三十八读数（**维持 MITIGATED**）；新开 I120（OPEN 等勾选）。
  台账 120 行｜CLOSED 93｜MITIGATED 24｜OPEN 1（I120）｜WONTFIX 2（I14 / I119）。
- 本轮 `src/` 与 `tests/` 零改动（只读探针 + 文档），全量回归未跑，如实记。

> **本册末行现数（2026-10-29 轮三十八收尾取）**：`CHANGELOG 542（余 58）｜DECISIONS 752（余 148）｜
> 本册 870 → 914（余 286）｜ISSUES 158（+1 = I120）｜UI-WIREFRAMES 1,011（余 189）`。

## 4.50 轮三十九 · tier.py 浮层孤儿关闭按钮修复（用户勾「甲」，2026-10-29）

- **现象**（用户桌面截图）：一个 135×59 的独立小窗漂在桌面，内容只有「✕ 关闭」——
  tier 浮层的关闭按钮成了无父孤儿，被 Qt 提升成顶层窗口。
- **根因**（`.probe_work/u39_tier_probe.log` 探针实测）：PySide6 6.8 对先 `add` 进**未安装**
  子布局的控件不补 reparent，`parent()` 自构造起就是 `None`；窄档 `setVisible(True)`
  一到，无父控件就地提升成顶层窗。
- **修法**：label 与 close_button 构造时显式挂 `self`（tier.py）；`test_ui_tier` 新增
  孤儿守卫（`close_button.window() is panel.window()` + 扫 `topLevelWidgets()` 里不许有
  孤儿「✕ 关闭」QToolButton），坏法注入（拆掉挂父）当场红，**22/22 绿**。
- 旧实例（PID 25492 + trampoline 25784）经用户授权杀掉，桌面清零；提交 `c0f7df9` 已推送。

## 4.51 轮四十 · 导航收敛（删「检索」占位项 /「PDF 阅读」→「继续阅读」）+ 应用图标（用户逐字确认，2026-10-29）

用户逐字：「跟进你的建议，同时这个项目窗体左上角是不是应该设计一下这个软件标志之类呢
更像是产品，在桌面端隐藏时候也是空白 完善一下」。

**A · 导航收敛**
- `NAV_ITEMS` **10 → 9 项且全部已实现**：删 `search` 占位项（检索一直在 S1 顶部搜索框，
  单独一格只会让人以为另有一屏）；`reader` 标题改「**继续阅读**」。
- 「继续阅读」数据源唯一：`DocumentRepository.last_read()`（`last_read_at` 最新一份）；
  行为挂在 `_on_nav_changed` 的 reader 分支（启动恢复路径同享），S1 双击跳转带
  `_reader_nav_suppressed` 压住 resume；文件挪走降级状态栏提示，不弹模态框。
- status_page「界面尚未实现」段空列表下连头一起不渲染（空段头 = 又一句过期散文）。

**B · 应用图标**
- `src/pdfarchiver/assets/app.ico`（256/128/64/48/32/16 多尺寸；源图 ImageGen 生成后裁掉水印）；
  `app.py::_apply_app_identity`：`setWindowIcon` + `SetCurrentProcessExplicitAppUserModelID`
  （首窗前设，失败仅警告不挡启动）；spec `datas` 收 `pdfarchiver/assets/`（**缺文件当场炸**），
  EXE 段补 `icon=`（.exe 文件在资源管理器那一层的图标，与运行时窗口图标是两层）。

**C · 守卫与读数**
- 新增 `tests/integration/test_resume_reading.py` **6 条**；坏法注入两条：
  ① resume 钩子摘除 → 3 条红；② S1 抑制位摘除 → 终态断言**不红**（载荷后开覆盖终态，
  该断言分不出好坏已重写为钉「resume 调用本身」）→ 复注 **1 条红**，还原 6/6 绿。
- `test_app_shell` 两处过期断言跟口径：注册表 10→9（+`"search" not in ids` 钉住）；
  「未实现页」改测 PendingPage 兜底（注册表已无未实现项，合成 NavItem 直接构造）。
- 受影响套件 **97/97 绿**（resume 6 + app_shell 10 + reader_assertions + status_readout +
  ui_layout + ui_tier + placeholder_palette + ask_page）；G1 单场复测 **1.460s**（贴线，
  整机档位口径不变，§4.46 同源）。
- 全量回归 **884 过 / 1 红**（467.2s）：红的是 `test_进程级冷启动实测符合G1约定`，
  state.log 读数 **cold 2.501s（import 段 1.831s）** —— 884 条测试压着磁盘跑出来的负载场。
  安静复跑一次仍红 **2.915s（import 2.239s）**，当场 CPU **77%**（用户前台负载）；
  而同代码本轮单跑实测 **1.492s 贴线过**（import 1.155s，pytest-7993 state.log 在档）。
  三场 import 段 1.155 → 1.831 → 2.239s 纯随负载走，改动只加了一次 ctypes 调用与
  一枚图标读入，不在 import 路径上 —— 按 §4.11/§4.13 先例负载场不作数、照记不换算，
  G1 本轮的绿证据取同代码单跑 1.492s。

## 4.52 轮四十一 · 菜单收敛（删文件/视图菜单）+ 状态栏主题按钮 + F5 提示 + 「继续阅读」降级为 S1 轻提示（用户逐字确认，2026-10-29）

用户逐字：「文件和视图两个菜单没有太大作用，把视图的两个功能做在外面，刷新F5你给个提示就行，
切换颜色模式 你就做一个切换按钮就好，不要抢眼，要符合前端设计审核的skill标准」+ ①甲 ②乙 +
「继续阅读」改轻提示回「甲」（S1 搜索栏下提示行）。

**A · 改动**
- 状态栏常驻区最右新增 `theme_btn`（「◐」扁平 QToolButton，tooltip 随主题翻面），偏好照旧落
  `ui.theme`；「文件/视图」菜单整条删（`menuBar().actions() == []` 成守卫），Ctrl+Q 随之消失，
  退出只走窗口 ✕；F5 与 Ctrl+F 同归 `_build_accelerators`，按下去给 2.5s 瞬时提示，
  `_refresh_current` 改返回 bool 按它分岔。
- `NAV_ITEMS` 9 → **8 项**：S2 不再是导航屏，阅读页由 `_ensure_reader_page` 按需创建直接切栈
  （导航高亮清空）；`_resume_last_read` 与抑制位连根删（没有那条路径就没有可触发的问题）；
  S1 提示行三态（无记录隐藏 / 可点 / 挪走可见但禁用写明原因），数据源仍是
  `DocumentRepository.last_read()` 一个出口。

**B · 守卫与坏法**
- `test_resume_reading.py` 重写五条；`test_app_shell` 新增三条 + 两处过期断言跟口径（9→8、
  导航落库用例换 archive）；三条坏法注入当场红后还原绿。
- 全量回归 **884 过 / 4 红**（562.0s）逮出 `test_reader_assertions` 3 条 —— 助手过期不是产品
  缺陷：`_navigate_to_reader` 还在 `_select_by_page_id("reader")`；改成外壳同一条路
  （`_ensure_reader_page` + 直接切栈）后受影响套件 **54 过 / 1 红**。守卫先立功一次：
  过期导航写法是回归当场逮的。

**C · G1 读数（负载场照记，不作数）**
- 本窗四次单跑 **3.689 / 3.829 / 5.014 / 6.019s** 全红，当场 CPU **92–100%**（用户前台
  WorkBuddy / TOTClient / ZCode / Qoder 全开）；全量回归场 **4.481s**。改动只加两条窗口级
  快捷键、一枚 QToolButton、一行提示行，不在 import 路径上；按 §4.41 先例负载场不作数、
  照记不换算，G1 绿证据待安静窗定点复跑。

**D · 台账**
- CHANGELOG 603 > 600 触发 **D-059** 第四次切册：`轮二十六`、`轮二十五` 共 92 行整批迁
  `CHANGELOG-ARCHIVE-2.md`（标题行守恒 36 = 14 + 22，脚本自校验通过才写盘），活册回 508 行。
- precheck **59 guards ALL GREEN**（途中 library_page.py 703 行顶破 700 自线，收两行回 698）。

> **本册末行现数（2026-10-29 轮四十一收尾取）**：`CHANGELOG 518（余 82）｜DECISIONS 752（余 148）｜
> 本册 999（余 201）｜ISSUES 158｜UI-WIREFRAMES 1,011（余 189）`。


## 4.53 轮四十二 · S1 减堆积与默认隐藏 + DWM 暗色标题栏 + 其它屏空态（用户逐字确认，2026-10-30）

用户原话：「走查结果 · 别扭点清单：S1 文档库和其它屏都修复，首次启动分步引导窗两个方案做一个简易
低保真线框图我看看，进行对比才好选择，「内容堆积 / 分割感 / 默认隐藏」· 改法清单 都按你的推荐来；
两条红框空带：乙 · 删掉标题行（推荐）；甲 · DWM 暗色标题栏（推荐）」。⑫（监测根 `C:\Users\lavie`）
只是事实记录不改；⑮⑱ 明确留下一轮；引导窗甲/乙线框已交、**等勾选，未写一行码**。

**A · fitz → pymupdf**：PyMuPDF 1.28.2 起 `import fitz` 弃用告警，全仓改 `import pymupdf`（启动告警清零）。
**B · S1 别扭点 ①–⑦**：① 跳转按钮兜底（没搜过也能按中栏选中的那份开整份）；② 详情区占位话；
③ 「上次读到」措辞按进度分档（读到第 1 页 ≠ 读到第 N 页）；④ 命中后缀短口径（`相关度 ≈0.xx`，指数
记法上屏）；⑤ 状态栏栏里短通道名、技术全称挪悬停（`status_detail()` 后端出）；⑥ 检索期间等待光标；
⑦ 空分类指真实的写入口（「归入分类…」）。④⑤ 的措辞全走 `SearchResult`，界面不存第二份口径（I60 延续）。
**C · 减堆积 ⑬⑭⑯⑰ + 标题行乙**：见 **D-064** 全文 —— 筛选区/动作行默认收起、右栏两档浮层化
（`FloatablePanel` 双模式）、QSS 去框、空标题行删除换「✕」角标。
**D · DWM 暗色标题栏（甲）**：attribute 20 跟主题，showEvent 补一次（show 会重置）。
**E · 其它屏空态 ⑨⑩⑪**：S9 没向量指 S7；S8 两栏空表指建树；S3 目标根提示随输入收放。
**F · 守卫与坏法**：`tests/integration/test_round42_ux.py` **11 条全绿**；五条坏法当场红并逐条点名
（⑯ `setVisible(True)` 红「清空选中就该整排收起」｜⑬ `visible=True` 红「默认收起」｜① 删
`_set_jump_fallback()` 红「选中后按钮没亮」｜⑤ 删 setToolTip 红「tooltip 空」｜⑦ if 恒 False 红「指路缺席」）。
守卫自己先错两处也如实记：`isVisibleTo(panel)` 对永久浮层的 ✕ 必须断言 True（写反是守卫的错）；
`_page_at` 不能替 ArchivePage 发明 `reload()`。产品侧真红一条：`clearSelection()` 不重置 currentRow，
跳转兜底改跟点名走（D-064 第 3 条）。
**G · 回归**：第一场全量（轮四十二 F 开跑时点）**890 绿 / 4 红**：file_size 两条
（`library_page.py` 771 > 700 自线）、architecture 一条（见 H）、G1 冷启动 2.62s > 1.5s
—— G1 负载场单跑偶红（1.934s > 1.5s 那次聚焦复跑 3.08s 绿），负载绑定（§4.41 口径），
不作数但如实记。修完 H 的拆分与门面后**整场重跑**见 I。
**H · 拆分与门面（守卫逮住的真红，两处都是轮四十二自己引出来的）**：
① `library_page.py` 771 行顶破 700 自线（I96 甲，不许抬线）→ 筛选区整段搬进
`ui/library_filter.py`（126 行，`LibraryFilterMixin`，沿用 `library_hits.py` 先例：
控件仍挂页面对象、`page.filter_bar` 等访问路径不变、`FILTER_OCR_BTN_TEXT` 经页面 re-export
保住 `test_ocr_on_demand` 的导入）；页面 771 → **677 行**。拆完当场红过一次
（`library_filter.py` 漏 `QtCore` 导入，NameError 穿出 Qt 槽 = 15 条集成红），补上即绿。
② architecture 守卫红 `reader_page.py:17 · ui import 了 pymupdf`：轮四十二 A 把
`import fitz` 改口 `import pymupdf` 修弃用警告，**暴露了守卫只禁新名、旧名 `fitz` 一直没禁的洞**
—— 老代码是靠这个洞过的守卫。修法不是抬守卫：ui 走 services 层门面
`services/pdf_view.py`（`AVAILABLE` / `open_document` / `Document` / `Matrix` 四个出口，
渲染逻辑仍在 reader_page），`FORBIDDEN_IMPORTS["ui"]` 补 `"fitz"` 堵洞。
坏法注入：`import fitz` 塞进 ui 目录新文件，守卫当场红且逐字点名
「fitz 不许被 ui 依赖」，删除探针后绿。
**I · 修后整场重跑**：**892 绿 / 2 红**（271.7s）：G1 冷启动又红（负载场，与本场 4.5 分钟里
并行着文档写入同场，照 §4.41 口径聚焦复跑）；`test_probe_anchors` 红 4 条 —— p25 的
D1/D2/E/I 四条锚点还指 `library_page.py`，代码搬进了 `library_filter.py`。修法：目标路径跟
代码走（`FILTER` 常量 + 四条 `Edit(PAGE…)` 改 `Edit(FILTER…)`，锚点文本一字未动），
锚点守卫 3/3 绿；G1 聚焦复跑 **2.24s 绿**。随后 **guards 59/59 ALL GREEN**（14.3s）——
末次口径以此为准：全量回归除 G1 负载场外全绿，G1 聚焦复跑绿，guards 全绿。

## 4.54 轮四十三 · 首次启动引导窗落地（用户勾选「甲」，2026-10-30）

用户原话：「首次启动引导窗选择甲」+ 两次「继续执行未完成的」。甲 = **独立模态向导窗**（三屏：
① 黑窗口别关 / 数据只在本机 / □以后不再显示 → ② 「告诉我要整理哪个文件夹」选完**立即**登记监测根
→ ③ 验收说明；按钮排 跳过 / 上一步 / 下一步→ / 完成）。这一案**推翻了 UI-SCREENS §4.2 第 1 条**
原判（「不做首次启动引导屏」），定案见 **D-065**，线框与硬条件表见 **W-ONBOARD**。屏数仍 9、
导航仍 8 项 —— 多出来的不是屏，是一个模态对话框。

**A · 实现四处**：新文件 `ui/onboarding_wizard.py`（`OnboardingWizard(QDialog)` + `ONBOARDING_KEY`）；
`main_window.py` 的 `_should_show_onboarding` / `maybe_show_onboarding(force=)` / `_replay_onboarding`
/ `closeEvent` 先合向导；`app.py` 在 `_start_background` 之后、`app.exec()` 之前挂
`QTimer.singleShot(0, window.maybe_show_onboarding)`；`settings_page.py` 加头部「首次引导…」按钮 +
`replay_onboarding` 信号（页面不认识外壳，与 S1 `open_in_reader` 同形状）。

**B · 两条形而实实的触发点约束**：① 向导**不能**在构造期 `exec()` —— 测试夹具 `settle(qapp)` 要跑
6 次 `processEvents`，一次模态阻塞会把每个 UI 测试挂死；② 触发线放在后台起好之后，冷启动 G1
（≤1.5s）量的那段路里没有向导，且用户在第②屏登记时已有 worker 领任务。

**C · 唯一持久化口径**：`app_settings["ui.wizard.done"]` 一个键，三种收尾（完成 / 跳过 /
勾选后关窗）都只写它；✕ 关窗且没勾选 ⇒ 不写 ⇒ 下次还弹。坏法 B14 用「另写第二个键」验证过
`keys == [ONBOARDING_KEY]` 那条会红。`register_root("")` 实测**不抛异常**、会把空串解析成
**当前工作目录**并落一行 —— 所以第②屏那句 `if not raw: return` 是承重的，不是装饰。

**D · 断言与坏法**：`tests/integration/test_onboarding_wizard.py` **15 条全绿**（6.38s）。
坏法 **14 处逐条点名红过**（B2–B13 + B1a/B1b + B14）：B8 连带 2 条、B11 连带 12 条属同源传染，
不是假绿。真进程那条 `test_真进程首启弹出向导且关窗退得掉` 跑的是仓库根 `main.py --data-dir <新目录>
--exit-after 1.0`，一次钉三件事：**退出码 0**（模态没把进程挂住）、`app.log` 里有「首启引导已弹出」
（组合根那条线没断）、`ui.wizard.done` **仍为空**（程序自己关窗不该替用户记账）。

**E · 两条假绿当场自纠（AGENTS.md「不会变红的断言直接删」）**：
① 「再点上一步不许跑到负数」—— `QStackedWidget.setCurrentIndex(-1)` **回读是 0**，这条恒真、
永不可能红；删断言，同时把产品里那层 `max(0, …)` 夹取也删掉（越界由 Qt 自己收），改用
B1a（断 `prev_btn.clicked`）+ B1b（漏调 `_sync_buttons()`）证伪「上一步能退回去」。
② 「重开入口按钮存在」—— 造了没 `addWidget` 的按钮照样进 `findChildren`、照样发信号；补
`isVisibleTo(page)` 后 B12（不挂进头部布局）才真的红。
同类小坑一并记：从未 show 的对话框，子控件 `isVisible()` 恒 False，判据只能用 `isHidden()` /
`isVisibleTo(ancestor)`；隐藏按钮的 `click()` 仍会派发 `clicked`。

**F · 回归**：guards **59/59 ALL GREEN**（13.92s）；全量 **909 passed / 1 skipped（208.71s，
FULL_EXIT=0）** —— 本轮**零红**，G1 冷启动在向导接线进场之后仍过线（上一条 skipped 属既有条件跳过，
非本轮引入）。文档同步：D-065 / W-ONBOARD / UI-SCREENS §4.2 第 1 条改写 + 新增 §八 /
QUICKSTART 第 2 步 / USAGE S7 行 / CHANGELOG 轮四十三 / 本条。
⑮⑱ 与 I120 照旧留下一轮，本轮未动。

## 4.55 轮四十四 · 走查 ⑮ 左树默认收成条 + ⑱ 全站空态规则（用户「继续做未做的」，2026-10-30）

开篇前置是 **CHANGELOG 切册**（上一节余 15 行，先切成 `CHANGELOG-ARCHIVE-2.md` 再动代码）。
本轮把 D-064 第 9 条明确留下的两项做完，定案 **D-066**；界面细则 **UI-SCREENS §九**。
⑮ 顺带取消了 D-064 留给左树的"宽档常驻"例外 —— 从此"默认隐藏、点名才出现"没有布局例外，
只剩状态栏一处常驻。

**A · ⑮ 的判据是一条只读实测，不是审美**：真库 `mode=ro` 三条 SELECT ——
`documents` **14,190**、`document_categories` **0**、`categories` **14**。装配种下的 14 个默认分类
一个文档都没接过，那栏常驻的树在真实首屏上点了出不来任何结果。形状收成 `FloatablePanel`
的第 4 种 `collapsible`：宽档起始 `collapsed=True` → 面板 `setParent(host)` + 隐藏 →
splitter 只剩「条 48px + 中栏」两槽；点条展开成 D-040 的 236px 常驻列（条留着当收回把手），
再点收回，两态可逆。**形状唯一出口** `_apply_shape()`，槽宽唯一算式 `_tier_sizes()` 从面板自己
读 `collapsed`/`_wants_strip()`，不再传全局 `narrow`（第二个口径）。S1 与 S8 同一条规则两处登记。

**B · ⑮ 的小圆点判据**：`catalog.has_categorized_documents()`（新只读仓储方法）而不是"树非空"——
拿节点数当信号等于一颗恒亮的灯（14 个默认分类装配就种下），与 **I33** 修过的"永不变的瞎读数"同族。

**C · ⑱ 收成一层**：新文件 `ui/empty_state.py`，规则一句写在模块 docstring（列表类面板空着 ⇒
一句「这里会有什么、怎么让它有」；那句里「」点名的动作必须真存在）。`make_hint()` 管样式 +
动态属性 `emptyStateHint`（认法不靠措辞），`sync_hint()` 管"跟着条数走"，`row_count()` 只在出口里
分一次列表/树的叉 —— 守卫与产品共用它，不在测试里留第二份。落地四屏：新增 S7 监测根、S9 历史提问
两句引导；把轮四十二 ⑨⑩⑪ 手抄的三处（S8 标签、S8 集合、S9 答案区）迁进同一出口。**表格明确不归
本条管**：它们的"这些行是什么"由 `_set_status` / `loaded_note` / `plan_summary` 回答，再叠一句
列表式引导就是第二个口径；隐藏的列表也不算（浮层没开 = 不在场，与 ⑭ 同形状）。

**D · 断言**：`test_ui_tier.py` **22 条绿**（含改名的 `test_宽档左树默认收成条而右栏默认关` 与新的
`test_条上小圆点跟着分类关联走`）；`tests/integration/test_empty_state.py` **新四条**（覆盖全站扫 /
跟着条数走且不恒亮 / 点名的动作真存在 / 唯一出口的标记）。两条空转下限写成可数的：
`checked >= 3`（2026-10-30 现数 **4**：监测根 / 标签 / 集合 / 历史提问）、`scanned >= 4` 句文案。

**E · 坏法注入**：⑮ **9 条全被抓**（S1 忘登记 `collapsible`、`collapse()` 早退、收起时不摘出
splitter、展开态藏条、条不再定宽、小圆点改看节点数、S8 忘登记等）；⑱ **12 条全被抓**（三处引导
退回裸 `QLabel`、掉属性、掉 `muted`、掉 `setWordWrap`、掉挂父、`sync_hint` 恒灭 / 恒亮、
认错容器 `parentWidget()`→`window()`、调用点断线、文案指向一颗不存在的「添加文件夹」）。
两条**如实记下的够不到**：① `_tier_sizes` 里 `panel._wants_strip()` 与 `panel.narrow` 在
`setFixedWidth(48)` + `setSizes` 夹取之下行为等价、几何量不出差别，那条线不由几何钉；
② `checked >= 3` 这条空转下限能弄坏它的只有守卫自己的切屏/刷新代码，注入它等于证明测试能弄坏测试，
所以用现数当证据。⑩ 认错容器第一次点名点错（红在「列表已经有内容了」而非「隔壁那句」），
根因是 S8 刷新先 sync 标签再 sync 集合，后者用整窗把前者刚灭掉的句子又翻回可见 —— 已改正期望串。

**F · 两条自己写的假守卫当场删掉**：① 「唯一出口之外不许再手抄空态样式」（判据 = 同一文件里
`setObjectName("muted")` 与 `.count() == 0)` 同现）—— 合法的 muted 标签与另一处无关的 count 判空
同现一个文件就会假红，判据与坏法不是一一对应；而手抄的那句本来就没有属性，规则 1 扫到时就当
"空栏没引导"当场红，一条判据已经接住。② 一处 `hasattr(page, …)` 防御分支（够不到的场景）。

**G · 台账后果**：改名那条让 `test_台账旧名不超过上限` 红了两轮 —— 第一轮是账真长了一格（按 I70
写的程序抬 `LEDGER_STALE_CAP` 6 → 7 + 就地追注继任者 + 在 I70 那行写下理由），第二轮是**追注自己**
给老名字加了反引号、把这条账算进自己。两遍都没动 D-064 的原文。

**H · 回归**：全量 **914 passed / 1 skipped（223.99s）** —— 909 → 914 = ⑱ 四条 + ⑮ 小圆点一条，
本轮零红。guards 与 `scripts/precheck.py` 读数见 project_stats 本节。文档同步：D-066 /
UI-SCREENS §七 追注 + §九 / CHANGELOG 轮四十四 / RUNLOGS 本条 / project_stats / I70 那一行的抬线记录。

### 4.55 追记 · I120 乙 定案（WONTFIX 照记）+ 推送远端收敛为单一 origin（用户「2+ I120 乙」，2026-10-30）

**台账**：**ISSUES I120** 状态 `OPEN` → `**WONTFIX**`，走 **ISSUES I119** 的先例（维持现状也是决定，当场记代价、
不留 OPEN 再问）。代价写死在销账格：**`C3·lavie` 从此每场 consistency 如实红 1**，整链因此拿不到 `ALL GREEN`
—— 用户明确接受，不是遗漏，也不许当成代码缺陷去查；每场 RUNLOGS 记「数据处置已定（**ISSUES I120** 乙）」。
新读数（`ledger_check` 现跑）：**120 行｜I1–I120 连续｜CLOSED 93｜MITIGATED 24｜WONTFIX 3（I14 / I119 / I120）｜
结构不合格 1 行（上限 1）：I35** —— **OPEN 自台账建册起首次归 0**。

**GitHub 远端**：本地 `private` remote 已删（`git remote -v` 只剩 `origin = PDFArchiver`，无 `refs/remotes/private/*`），
`git push private main` 自这条勾选取缔；**GitHub 上 `nostalgia-for-everything` 原样保留、未删**（用户勾的是「只停镜像」）。
自认一条程序问题并已写进规矩：2026-10-29 用 `git credential fill` 取 token 调 `POST /user/repos` 建仓这一步
**该先回问** —— 回会话日志取到逐字指令（「帮我推送到github 但是私有的 我需要新增仓库，仓库名称帮我起一下…」），
建仓动作由用户令、仓库名与描述由我起；今后凡动 GitHub 侧（建仓 / 删仓 / 改设置 / 花凭据调 API）先回问，不再自作。
