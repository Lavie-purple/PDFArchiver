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
- `CHANGELOG` **1,172 行（余 28）**：下一轮开篇先切册（`CHANGELOG-ARCHIVE.md` 已有先例）。
- ④ 24 小时 soak 未验（12h 是上限）；⑨ injection 真空载（CPU<10%）结构性不可达；安装包与代码签名未交付；隐私政策挂起（2026-10-27）。

> **本册末行现数（2026-10-27 轮三十二收尾取）**：`CHANGELOG 1,174（余 26）｜DECISIONS 687（余 513）｜本册 495 → 503（余 697）｜分册一 757（余 443）｜分册二 727（余 473）｜ISSUES 154｜UI-WIREFRAMES 1,009（余 191）`；**最紧的是 CHANGELOG（余 26）** —— 下一轮开篇先切它。
> **台账**：`116 行｜I1–I116 连续不重号｜CLOSED 89｜MITIGATED 24｜OPEN 2（I115 / I116）｜WONTFIX 1｜结构不合格 1 行（上限 1：I35）｜失效测试名 6 处 / 上限 6`；本轮 I113 **OPEN → CLOSED**（销账条件补实测读数），新开 I115 / I116 两行均为 OPEN，其余零状态迁移。
> **测试**：`pytest tests -q` **822 passed / 1 skipped（177.06s）**｜guards 全量 **59 passed**（12.77s 一次、预检内 10.81s 一次）｜`scripts/precheck.py` 末行 `VERDICT: ALL GREEN`（docs-inject + guards 合计判定 9 条）。
> **覆盖边界**：本轮**没跑 12 段整链** —— `consistency / soak / package / g2` 不在这一场的覆盖里（预检末行逐段 SKIP 已列）；依据是 `src/` 与 `tests/` 本轮 **0 改动**、门禁阈值 **0 改动**，整链最近一次全绿是同日轮三十一的 5,877.1s / 35 判定。
> **真库现数（只读，18:1x 取）**：`catalog.db 12,113,543,168 B（vs 轮三十一末 +1,093,632 B）｜documents 10,995｜text_pages 1,976,175 = content_fts 1,976,175｜vector_meta 1,968,563｜vectors.npy 1,073,741,952 B｜vector_status {'done': 8,690, 'na': 2,305}｜ocr_status {'done': 2, 'na': 8,537, 'pending': 2,456}｜missing_since 1｜队列 {'index:done': 10,935, 'index:failed': 75, 'ocr:done': 2, 'scan:done': 5}｜监测根 6 个｜schema 8`。
> **临时文件**：`.probe_work/` 顶层 **737 项（13 个子目录）｜递归 1,179 文件｜858.1 MiB｜顶层 0 字节 79 个**；`injection_inflight` **不在场**；本轮承重 `u32_i113_backup_delete.*`、`u32_ocr_vectors.*`、`u32_after_ocr_checks.*`、`u32_db_counts.*`、`u32_regression_full.log` 留在顶层。
> **会话日志体积（token 代理）**：**352,780,358 B｜108,813 行**（18:2x 取）vs 轮三十一基线 **347,987,493 B / 107,596 行** ⇒ **+4,792,865 B｜+1,217 行**。
