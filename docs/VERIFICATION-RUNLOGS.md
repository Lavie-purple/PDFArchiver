# 实测读数 · 逐轮收尾册（承接 `docs/VERIFICATION.md` §四 的节号序列）

**这一册装什么**：`docs/VERIFICATION.md` §四 里**每一轮收尾都要追加一块**的那批读数（4.17 起）。
**那一份装什么**：环境与依赖版本、探针结论索引、以及只在阶段收尾时才涨的 4.1–4.16。

**为什么切在这一刀**（**ISSUES I71** 勾选**乙**，2026-10-18）：`tests/guards/test_file_size.py` 给台账定的线是
`MD_LIMIT = 1_200` 行，而 `docs/VERIFICATION.md` 收尾复测已到 **1,184** 行（只剩 16 行，连一句追注都装不下）。
增速的实测来源正是这一类块：勾选轮（五）**+75**、勾选轮（六）**+165**（那一条是逐字粘贴门禁与三份探针输出造成的）。
**节号序列与原文连续、内容逐字未动** —— 分册只改「它在哪一份里」，不改「它是第几块」，也不改任何一个数字。

**取数与复跑口径**：见 `docs/VERIFICATION.md` §七（那一份是口径的出处，本册不另立第二份）。

---

**§4.17–§4.25 已整批迁入 `docs/VERIFICATION-RUNLOGS-ARCHIVE.md`**（**D-059**，2026-10-24 轮二十三点算）：
九块原文逐字搬走、节号不变，本册只留 §4.26 起。上面那句「这一册装什么」说的是本册的由来，
现在装的是**最近几轮**；早期九块请翻分册。

### 4.26 真根闭环轮（十六）收尾读数（2026-10-20 12:03:27 → 2026-10-21 04:06:53，销账 **I97** / **I98**，新开并销 **I99**）

**起止（墙钟，不折算成单一“活跃”数）**：本地 **10-20 12:03:27**（轮十五 F 最后一条 commit `2dd6cf7`）→
**10-21 04:06:53**（整链 `rc=0`）= **16.06 h**。其中三段无人值守的机器时间可逐条对：
① 12:26:08–14:51:38 p12 真根一场 **8,730s**（I98 的证据，2.4 h）；② 00:00:56–02:08:32 第一条整链 **7,652.3s**；
③ 02:59:47–04:06:53 第二条整链 **4,023.1s**。**15:01→00:00:56 之间约 9 h 没有任何命令证据**（机器空闲），
不计入任何“实测耗时”。会话日志（本环境 `usage.*` 恒 0，只能拿体积当代理）：**252,886,852 B / 83,094 行**
（04:12 取），比轮十五收尾的 **238,643,669 B / 79,228 行** 是 **+14,243,183 B / +3,866 行**（跨 16.06 h，含 summary 压缩）。

**真库改动（三笔，快照都在先）**：
1. **迁移 0008 应用**（I97①）：产品迁移器把真库 **v7 → v8**、建 `ix_documents_name_ci`；迁移前快照
   `pre-migration-0008-20261020T122144.db` **11,967,422,464 B**；同一脚本复跑 `did_anything=False applied=[]`
   （`.probe_work/i97_migrate.log`，起 12:21、落 12:26）。
2. **第一批补索引 + 清空正文**（I97②③）：产品路径写 5 份（doc 10981–10985，448／10／11／584／15 页），
   再把一份 20 页扫描件在 `text_pages` 里那 **1 行空串**删掉并重索引（`before_pages 1 / deleted_pages 1 /
   text=none / ocr=pending`），收尾 `empty_bodies 0｜jobs_pending 0`（`.probe_work/i97_fix_roots_1456.log`，15:00）。
3. **第二批补索引**：5 份（doc 10986–10990，33／352／458／342／407 页），收尾
   `documents 10,987｜text_pages 1,975,216｜empty_bodies 0｜jobs_pending 0`（`.probe_work/i97_fix_roots2.log`，02:15:40–02:24:44）。
   `D:\` 从 p12 当时报的「83 PDFs / 79 records」到最终 **89/89**（盘上读数同期也从 83 涨到 89，两批共写入 10 条）。

**真根 p12（19/19 全绿，第一次）**：`.probe_work/p12_real_root.json`（2026-10-21 03:57，`source=显式参数`、`walk=true`）——
C0 v8 且 8 段迁移全在；C1 `integrity_check=ok｜foreign_key_check 0 条`；C2 主记录 **10,987** 两项一致；
C3 六根 **68/68、89/89、1967/1967、5352/5352、1655/1655、1856/1856**（已标缺失各 0）；
C4 **1,975,216/1,975,216/0/0**；C5 六项自洽；C6 状态列全合法；C9 `running 0`（`{'done': 10941, 'failed': 75}`）；
C10 分类 14；C12 0/0/0；C13 六根 `root_key == identity_key`；**C11 8 份快照，只对最新一份跑整库体检**
（`integrity_check=ok｜foreign_key_check 0 条`），其余 7 份开库读版本 —— 探针自己印出这条口径边界
（旧快照内部损坏不在本口径内）。p12 自检 **21/21 + 口径边界 1/1**。

**第二条整链（`.probe_work/final_chain_r16c.log`，唯一作数的一场）**：12 段、**34 条判定、本次未跑 0 段**，
`rc=0 chain end 2026-10-21 04:06:53`、末行 `VERDICT: ALL GREEN`。起跑 **CPU 43.6%｜可用内存 7071MiB｜
最吃内存 MsMpEng.exe 402MiB**。各段：docs-inject 0.0s／guards 2.8s／regression **236.8s（782 passed /
0 failed / 0 error / 1 skipped）**／coldstart 2.0s（冷启动 1.310s）／e2e 12.8s（11 条 + 6 行真实命中）／
injection **793.9s**（p9 69/69、p10 45/45、p16 8 坏法 + 3 对照、p17 3、p18 3、p21 24/24、p22 **33/33**、
p23 23/23、p24 17/17）／ui-inject 61.2s／ocr 28.9s（真引擎套件 4 passed）／consistency **2,323.3s**
（p12 注入 21/21 + 边界 1/1；真根 19/19）／soak 289.6s／package **238.1s**／g2 33.7s。
**段耗时相加 4,023.1s ≈ 67.1 分钟**；这是本项目第一次把 12 段放进**一条命令**跑完（I91 那条“超单命令上限”至此有了正面读数）。

**soak（4 分钟）**：S5 112.2→112.4MiB（+0.2）；S6 排空 **0.0s**（`{'done': 88}`）；S7 盘上 52／库里 52／已标缺失 10；
S8 1 份 28KiB／124 行；S9 临时 p12 **14 条红 0**。**S6 的 0.0s 仍是 ISSUES I32 的已知口径边界，不许写“排空已验证”**。
门禁标题里两处历史字面量本轮改成现数：`gates/final.py` 的 p22 「25 条」→ **33 条**、
`tests/probes/p13_soak.py` 的 S9 「13 条」→ **14 条**（只改字符串，不改判据）。

**package（400.0MiB）**：构建 **96.8s**、整包 **400.0MiB**、迁移 **8/8**、OCR DLL **3**、`.dist-info` **6**；
冻结冒烟 **137.3s**、273/273 在册、`schema_version=8`、分类 14、冷启动 **3.342s**、
事件 `['startup.begin','startup.done','window.ready','background.started','shutdown']`、无开发机路径、临时目录已清理。
**G20 那一行这次是真桌面（非 offscreen）**：`退出码 0｜优雅关闭=True（0.27s）｜等窗口 4.44s（window.ready 到）｜
峰值 RSS 121.5MiB｜峰值句柄 747｜峰值线程 13｜采样 9 次`（`.probe_work/frozen_smoke_result.json`）。

**G2 同一天三个读数，必须一起读**：**652.0ms**（`.probe_work/final_chain_r16.log`，起跑 CPU 41.8%）／
**1,055.0ms**（`.probe_work/g2_idle_r16.log`，起跑 CPU 75.1%、TOTClient 4,203MiB —— 文件名里的“idle”是当时的误称，
现场并不空载）／**299.0ms**（`.probe_work/final_chain_r16c.log`，起跑 CPU 43.6%，P50 123.0／P99 320.0／max 320.0「发票」）。
判据 ≤500ms 一个字没动；**G2 仍是负载绑定读数（ISSUES I25）**，绿的那场只能说“这一次在 500ms 内”。

**两场不作数的链，不抹掉**：
- `.probe_work/final_chain_r16.log`（00:00:56–02:08:32，**7,652.3s**）：RED **3 条** —— p12 真根（当时 C3·D + C5 两条红）、
  冻结产物冒烟（G20 竞态：`退出码 1｜优雅关闭=False（30.42s）｜等窗口 0.2s（window.ready 未到）`，
  `.probe_work/g20_inject_red_r16.log`）、G2（P95 652.0ms）。三条分别由 I97 修复、I99 修复、轻载复跑解决。
- `.probe_work/final_chain_r16b.log`（02:49:33 起，**中止**）：起跑 **CPU 99.8%｜可用内存 2369MiB｜
  TOTClient 4,168MiB**，regression 判 `781 passed / 1 failed / 1 skipped in 320.0s`，红的那条现场截断里可见
  `test_进程级冷启动实测符合G1约定` —— 负载假红（ISSUES I25 同族），链在 e2e 之后被我中止，**没有末行判定，不作数**。

**G20 竞态的证据（I99）**：修前 `等窗口 0.2s` 就发 WM_CLOSE，打给一个还没有窗口的进程 → `退出码 1｜
优雅关闭=False（30.42s）`（`.probe_work/g20_inject_red_r16.log`）；修后先等 `window.ready` 再发 WM_CLOSE →
`退出码 0｜优雅关闭=True（0.71s）｜等窗口 8.95s`（`.probe_work/g20_green_r16.log`）。判据仍是“ready + 优雅 + rc 0”，
`FIRST_READY_TIMEOUT = 60.0s` 对实测 8.95s 是 **6.7 倍**。整链里同一行是 4.44s。

**真机界面证据（非 offscreen）**：`.probe_work/real_ui_1020/report.json`（2026-10-20T12:54:23）——
`platform=windows`、`platform_env="<unset>"`、6 张 1280×800 截图、**27 条检查 0 失败**、`verdict=ALL GREEN`、
`work_dir_removed=true`；回执含合并搬 3 份、导出 4 行 CSV 5 列、OCR 面板「点名 2 份｜该跑 1 份」、
归档 3 项落盘、撤销批次 #2 排空。

**同一口径的两场 consistency 耗时差要一起看**：r16 **5,502.8s**、r16c **2,323.3s**（同一份代码、同一份库，
差 2.37 倍），原因未查明（负载与页缓存都在候选里，不编原因）；`REAL_ROOT_TIMEOUT` 维持 **17,460s**，
对慢的那场仍 **3.17 倍**、对 10-20 的 8,730s 是 **2 倍**。**不拿快的读数去缩上限**。

**没测到的 / 仍欠（不许混进上面那些绿）**：① 安装包与代码签名**仍未交付**（冻结目录能跑 ≠ 可分发安装包）；
② soak 只有 4 分钟，小时级没跑（I32）；③ G2 仍是负载绑定的单场绿；④ 旧快照**内部损坏**不在 C11 口径内
（I98 乙 的明写边界）；⑤ 版本号仍是 **0.5.0** —— 阶段 0–7 的发布门禁刚第一次全绿，升 1.0.0 是下一轮的正事；
⑥ 轮十六的代码与台账改动在本文写作时**尚未提交**，提交后以 `git log` 为准。

> **本册末行现数（2026-10-21 真根闭环轮（十六）收尾取）**：
> `DECISIONS 687｜VERIFICATION 856｜本册 846｜CHANGELOG 460｜ISSUES 137`（`wc -l`＝`splitlines()`＝守卫判定那条口径；
> 上一块轮（十五）按 §4.25 保留为历史、不动。本轮涨 CHANGELOG 404→460（+56 = 轮（十六）那一整块）、
> ISSUES 134→137（+3，现读 **99 行｜CLOSED 77｜MITIGATED 21｜WONTFIX 1**）、本册 758→846（+88 = §4.26 自身）；
> DECISIONS / VERIFICATION 主册未动 —— 本轮没开新决策。
> `.md` 侧无临近线（最紧的是 `UI-WIREFRAMES 951`，余 249）；`.py` 侧临近 6 份，原先 791 行的那份界面测试已按主题
> 拆成 `tests/integration/category_export/`（最大一份的现数见守卫打印）。
> 现册里带 `**本册末行现数**` 标题的块共 **7 块**（轮（七）／（八）／（九）／（十二）／（十三）／（十四）／（十五））+ 本轮这块**活的**。

### 4.27 版本收口轮（十七）收尾读数（2026-10-21 04:21:42 → 14:17:32，销账 **I100** / **I101**，**I102** 维持 MITIGATED）

**起止（墙钟，不折算成单一“活跃”数）**：轮十六最后一条 commit `4aa5dcf` **04:21:42** → 整链 r17c `rc=0`
**14:17:32** = **9.93 h**。其中 **05:58 → 12:08 本机休眠约 6.17 h**（05:58 修后 soak 收尾、12:08 重新开工），
**有效工作约 3.76 h**。会话日志（本环境 `usage.*` 恒 0，只能拿体积当代理）：**261,079,061 B / 85,179 行**
（14:18 取），比轮十六收尾的 **255,010,699 B / 83,617 行** 是 **+6,068,362 B / +1,562 行**（跨 9.93 h，含休眠与 summary 压缩）。

**版本与产物（`1.0.0` 的物证）**：`src/pdfarchiver/__init__.py` 为 `__version__ = "1.0.0"`；源码运行
`python -m pdfarchiver.app --version` → `PdfArchiver 1.0.0`。整链 package 段用 1.0.0 源码重建：构建 **142.8s**、
整包 **400.0 MiB**、迁移 **8/8**、OCR DLL **3**、`.dist-info` **6**。链后复跑
`dist\PdfArchiver\PdfArchiver.exe --version` → **`PdfArchiver 1.0.0`**、**退出码 0**、stderr **0 字节**
（stdout 首行 `fitz` 弃用警告是预期；`.probe_work/exe_version_r17c_out.txt` / `_err.txt`）。

**三场链，只有最后一场作数**：
- **r17（第一次，`.probe_work/final_chain_r17.log`）**：12 段全跑完，**RED 1 条** —— 只有 `长跑采样 p13` 红 5 条：
  采样 **0 点**、S3–S5“没有读数”、S4 还写着“非 Windows”。同场 S6–S9 全绿、应用干净关闭。定位为 **I100**：
  探针在自己进程里调产品 `bootstrap()`（装进程级 excepthook），`Sampler` 线程在 venv launcher 交接时抛
  `NoSuchProcess`，被写进被测应用的 `crash.log`（**2,127 字节**），采样线程随即静默死掉。
- **I100 修复后（`.probe_work/soak_r17_fixed.log`）**：`Sampler` 改逐进程 BFS + `marker` 兜底、采样异常写进
  `errors`、`bootstrap_without_hooks()` 还原两个钩子；守卫 `test_probe_sampler.py` **3** 条（坏法 **3 failed**
  → 还原 **3 passed in 3.56s**）。同代码复跑 4 分钟 soak：**9 条全绿**、采样 **118** 点、`crash.log 0 字节`、
  S3 **15 → 12**、S4 **321 → 321**、S5 **111.7 → 111.8MiB（+0.1）**。
- **r17b（`.probe_work/final_chain_r17b.log`，中止）**：regression 判 `784 passed / 1 failed / 0 error / 1 skipped`，
  红在 `test_进程级冷启动实测符合G1约定`；门禁现场只留 900 字，断言原文被截掉，pytest 临时根随后被轮换删除，
  无法回查（**I102**，单条复跑 2.09s 绿、`test_app_shell.py` 10/10 绿，未复现）。我主动停链后，p17 的 H3 坏法
  （`if kind != "archive": continue`）因 `finally` 没跑到而留在 `src/pdfarchiver/jobs/queue.py`，下一场全量回归把它
  读成 `DID NOT RAISE ValueError`（**I101**）。还原后单条 **0.20s** 过、整套 **785 passed / 1 skipped in 210.76s**
  （`.probe_work/regression_r17_repro.log` / `regression_r17_clean.log`）。
- **两条修法都做了坏法对照**：`gates/final.py` 新增 `INJECTION_INFLIGHT` 标记 + 起跑前 `preflight_injection_residue()`，
  手工造标记 → `RED 上一次坏法注入段没有收尾` 且 guards 一条没跑；删标记 → **8 条 ALL GREEN**。
  `gates/stage1.py::gate_regression` 失败时把完整 pytest 输出写进 `.probe_work/regression_full.txt`，并把
  `short test summary` 的失败节点名顶到「实测」里 —— 下一次同类红不必再靠猜。

**终场 12 段整链（`.probe_work/final_chain_r17c.log`，唯一作数的一场）**：12 段、**34 条判定、本次未跑 0 段**、
`rc=0`、末行 **`VERDICT: ALL GREEN`**。起跑 **CPU 21.2%｜可用内存 4,530MiB｜最吃内存 MemCompression 842MiB**。
墙钟 **12:33:34 → 14:17:32 = 6,238s（103.97 分钟）**。各段：docs-inject 0.0s／guards 1.7s／
regression **213.5s（785 passed / 0 failed / 0 error / 1 skipped）**／coldstart 1.5s（冷启动 **0.858s**、
进程总耗时 1.476s、关窗对账 1 条）／e2e 13.1s（后台生命周期冷启动 0.802s、11 条端到端、6 行真实检索）／
injection **1,414.7s**（p9 **69/69**、p10 **45/45**、p16 **8 坏法 + 3 对照**、p17 3、p18 3、p21 24/24、
p22 33/33、p23 23/23、p24 17/17 ⇒ **225 条坏法**）／ui-inject 68.8s（p15 **36/36**）／ocr 29.9s
（6 页 / 9 项判定 0 未过；预算 2 页真停机；真引擎套件 **4 passed**）／consistency **3,824.2s**
（p12 注入 **21/21 + 边界 1/1**、p14 10/10、真根 **19/19**）／soak 303.4s／package **319.1s**／g2 45.5s。
**段耗时相加 6,235.4s**，与墙钟差 2.6s（段间开销）。

**比轮十六同规模链慢 2,212s，慢在哪要一起看**：r16c **4,023.1s** → r17c **6,235.4s**；增加的大头是
consistency **2,323.3 → 3,824.2s（+1,500.9）** 与 injection **793.9 → 1,414.7s（+620.8）**，其余段合计只差约 +90s。
同一天 r17 第一场的 injection 是 **858.7s**、consistency **3,041.4s**，同一份代码三场分散（injection 858.7 / 1,414.7
差 **1.65 倍**；consistency 跨轮 3,041.4 / 3,824.2 / 5,502.8 / 2,323.3）。起跑负载三场都不高，**原因未查明，不编原因，
也不拿快的读数去缩 `REAL_ROOT_TIMEOUT = 17,460s`**（对 3,824.2s 仍有 **4.57 倍**余量，对 5,502.8s 是 **3.17 倍**）。

**真根 p12（19/19，第二次全绿）**：`.probe_work/p12_real_root.json`（`source=显式参数`、`walk=true`）——
C0 v8 且 8 段迁移全在；C1 `integrity_check=ok｜foreign_key_check 0 条`；C2 主记录 **10,987** 两项一致；
C3 六根 **68/68、89/89、1967/1967、5352/5352、1655/1655、1856/1856**（已标缺失各 0）；
C4 **1,975,216/1,975,216/0/0**；C9 `running 0`（`{'done': 10941, 'failed': 75}`）；C10 分类 14；
C11 **8 份快照，只对最新一份跑整库体检**（`integrity_check=ok｜foreign_key_check 0 条`），其余 7 份开库读版本；
C12 0/0/0；C13 六根 `root_key == identity_key`。本次最新快照是 `pre-migration-0004-20261021T140627.db`
（soak 那场留下的 148KiB@v3），p12 自检 **21/21 + 口径边界 1/1**。

**soak（4 分钟，`.probe_work/final_chain_r17c.log` 段内）**：注入自检 **11/11 坏法 + 3/3 好读数**；真跑 **9 条全绿** ——
S5 **111.2 → 111.3MiB（+0.1）**、S6 排空 **0.0s**（`{'done': 88}`）、S7 盘上 52／库里 52／已标缺失 10、
S8 1 份 28KiB／124 行、S9 临时 p12 **14 条红 0**。门禁行的 900 字裁剪把 S1–S4 只留了“峰值 319”；
同代码独立场的完整读数见上（118 点、crash.log 0 字节、S3 15→12、S4 321→321）。
**S6 的 0.0s 仍是 ISSUES I32 的已知口径边界，不许写“排空已验证”**。

**package（400.0 MiB）**：构建 **142.8s**；冻结冒烟 **152.1s**、**273/273** 在册、`schema_version=8`、分类 14、
事件 `['startup.begin','startup.done','window.ready','background.started','shutdown']`、无开发机路径、临时目录已清理。
**G20 那一行是真桌面（非 offscreen）**：`退出码 0｜优雅关闭=True（0.5s）｜等窗口 6.89s（window.ready 到）｜
峰值 RSS 162.9MiB｜峰值句柄 829｜峰值线程 14｜采样 14 次`；冻结进程首次 `window.ready` 的
`cold_start_seconds=4.936`（`.probe_work/frozen_smoke_result.json`）。

**G2 同一天两个读数，必须一起读**：**340.0ms**（`.probe_work/final_chain_r17.log`，r17 第一场）／
**422.0ms**（`.probe_work/final_chain_r17c.log`，P50 196.0／P99 491.0／max 491.0「发票」；100 样本、
`text_pages=1,975,216`）。判据 ≤500ms 一个字没动；**G2 仍是负载绑定读数（ISSUES I25）**，
绿的那场只能说“这一次在 500ms 内”。同日另外两场 299.0ms（r16c）与 652.0ms（r16）一并作背景，不互相换算。

**没测到的 / 仍欠（不许混进上面那些绿）**：① 安装包与代码签名**仍未交付**（冻结目录能跑 ≠ 可分发安装包）；
② 隐私按用户口径“以后再处理”；③ soak 只有 4 分钟，小时级没跑（I32）；④ G2 仍是负载绑定的单场绿（I25）；
⑤ 旧快照**内部损坏**不在 C11 口径内（I98 乙 明写边界）；⑥ **I102 未销账** —— r17b 那条 G1 红没有复现，
只补了“下次能读到断言原文”，没有拿到根因；⑦ 真机证据仍是自动断言，不是人眼逐屏（I17 残余）。

> **本册末行现数（2026-10-21 版本收口轮（十七）收尾取）**：
> `DECISIONS 687｜VERIFICATION 857｜本册 935｜CHANGELOG 510｜ISSUES 140`（`wc -l`＝`splitlines()`＝守卫判定那条口径；
> 上一块轮（十六）按 §4.26 保留为历史、不动。本轮本册 847 → 935（+88 = §4.27 自身）；CHANGELOG 460 → 510
> （+50 = 轮（十七）那一整块）；ISSUES 137 → 140（+3：I100/I101/I102，现读 **102 行｜CLOSED 79｜MITIGATED 22｜
> WONTFIX 1**）；DECISIONS / VERIFICATION 主册未动 —— 本轮没开新决策。
> `.md` 侧无临近线（最紧的是 `UI-WIREFRAMES 951`，余 249）；`.py` 侧临近 5 份，最紧 `p12_consistency.py` 799（余 1）。
> 现册里带 `**本册末行现数**` 标题的块共 **8 块**（轮（七）／（八）／（九）／（十二）／（十三）／（十四）／（十五）／（十六））+ 本轮这块**活的**。

### 4.28 勾选轮（十八）收尾读数（2026-10-21 14:22 → 21:50，销账 **I102 / I103**，r18 34/35 后定点 19/19）

**起止（墙钟，不折算成单一“活跃”数）**：轮十七最后一条 commit `3c759e7` **14:21:58** → 本块落笔 **21:43** = **7.35 h**。其中 **15:47 → 18:32 本机休眠约 2.75 h**（30 分钟 soak 跑到第 30 分钟时被冻结），**有效工作约 4.60 h**。会话日志（本环境 `usage.*` 恒 0，只能拿体积当代理）：**271,349,026 B｜87,595 行**（轮十七基线 261,079,061 B / 85,179 行 ⇒ **+10,269,965 B｜+2,416 行**；2026-10-21 21:41:56 取数）。

**A · I32 甲 · p13 S6 真观测到积压，不再空转**：`tests/probes/p13_soak.py` 加 `BURST_ADD = 30`（一页 PDF 种进 `corpus/burst`）、`BURST_OBSERVE_MAX = 30.0s`、`BURST_OBSERVE_POLL = 0.25s`；判据改成 `drained and peak_open > 0`，观察不到非终态积压判未验。注入自检 **12/12 坏法 + 3/3 好读数**（坏法 7c `peak_open=0` 必红）。真跑 4 分钟：**S6 峰值 35 / 排空 1.0s / `{'done': 123}`**（`.probe_work/soak_r18.log`，118 点、S5 +0.1MiB、S3 15→12、S4 321→321）；30 分钟：**峰值 34 / 1.0s / `{'done': 592}`**。

**B · I25 乙 · G2 负载场与产品红分开**：`scripts/g2_search_benchmark.py::classify(p95_ms, cpu_pct, avail_mib)`，`LOAD_CPU_BUSY = 60.0`、`LOAD_AVAIL_MIN_MIB = 1536`；绿只有一条：**P95 ≤ 500ms**（忙不参与绿条件）；不达标且忙 → rc=3，不达标且不忙 → 红。`gates/final.py` g2 段遇 rc=3 等 **90s** 重试一次，仍 rc=3 以「环境不合格」收尾（rc=2）。分类自检六组真实历史读数 **6/6**（`.probe_work/round18_g2_inject.log`）。整链真跑 **P95 372ms**（P50 155 / P99 417 / max 417「engineering」；CPU 46.8%、可用 3,619MiB；100 样本、`text_pages=1,975,216`）。**残留**：90s 重试分支未在真负载场活过。

**C · ⑥ 甲 · 逐条计时**：`tests/probes/_timed.py` 的 `timed()` / `breakdown()`；p12 每条 Row 挂 `ms`、末尾「逐条计时」、JSON 带 `ms`；`gates/stage1.py` / `stage5.py` 的注入行带 `｜耗时`。整链：injection **674.0s**（p9 187.6 / p10 115.7 / p16 133.6 / p17 5.7 / p18 6.8 / p21 58.1 / p22 69.6 / p23 55.7 / p24 41.4）；consistency **4,057.0s** = 5.4 + 1.0 + 4,050.6。真根逐条：C1 **1,045.9s**、C3 六根共用一次 walk **713.1s**、C4 **192.5s**、C5 **1,181.0s**、C11 **910.1s**，五项 **4,042.5s = 99.8%**；其余合计 ≈6.5s。跨轮快慢仍未查明。

**D · I102 CLOSED · 冷启动三相 + 30 场**：`window.ready` 带 `phases`（import／装配／建窗）。30 场（warmup + 30，全 rc=0）：**min 1.221 / 中位 1.373 / max 2.289s，8/30 超 1.5s**；超线八场 CPU 63.3–87.3%，CPU ≤62.7% 四场全 ≤1.33s；负载 CPU 58.1–87.3%、可用 4,448–4,563MiB；最强场 import 2.019s = cold 的 **88%**，30 场 import 占 80–88%，assemble 39–77ms、window 104–256ms（`.probe_work/round18_i102_30x.log` / `i102_coldstart_30x.json`）。完整断言原文取到：`AssertionError: G1 [约定] ≤1.5s，实测 1.95s` + `assert 1.95 <= 1.5` + `test_app_shell.py:183` + `1 failed, 63 passed in 34.50s`（`.probe_work/round18_stage1_inject_note.log`；那场 p9 基线段负载真红，注入结论不作数）。**G1 1.5s 一处没动**。

**E · I32 乙 · 30 分钟 soak**：`--soak-seconds 1800`；**9/9 全绿**、885 点、120 轮、**1,801.8s**。S1 rc=0 / RSS 中位 111.6MiB；S2 crash.log 0B / Traceback 0；S3 12→12（峰 17）；S4 321→321；S5 **111.5→112.6MiB（+1.1）**、109.8–113.8、G8 余量 1,086.2；S6 **34 / 1.0s / `{'done': 592}`**；S7 290/290（缺 64）；S8 1 份 164KiB / 729 行；S9 14 条 0 红（`.probe_work/round18_soak_30min.log`）。**口径**：15:17:25 起跑、15:47 休眠、18:32 恢复、18:33:24 落盘；30 分钟是进程实际运行时间，不是连续墙钟。窗口内与 #172/#178 的轻量验证并行（G2 分类自检、p9 聚焦单条），不是空载场。I32 仍未销账（小时级没跑）。

**F · I103 CLOSED · 备份保留（21:49 授权后执行乙）**：8 份 ≈22.3GiB 的初测现场见本块首段；先逐份只读核对（v0–v7 全部可打开；0001–0006 空库共 757,760B、0007 v6/10,980 条、0008 v7/10,977 条），删 0007 与六份小快照共 21 个文件，保留主库 v8 + 0008。删后 `backups/` **1 份 11,967,422,464B ≈11.15GiB**、主库+备份 **≈22.3GiB**（原 ≈33.4GiB）、C 盘可用 **203G → 215G**；0008 复核 `OK v7 documents=10977`。保留规则进 `docs/BACKUP-RESTORE.md`；产品仍不自动清理（`.probe_work/i103_before.txt` / `i103_after.txt` / `i103_backups_before_ls.txt`）。

**G · 整链 r18（34/35）+ C3·D 真数据漂移 + 定点 p12**：18:34:06 → 20:09:28.949 = **5,722.8s（95.38 分钟）**；起跑 CPU 29.7% / 可用 4,609MiB / MemCompression 654MiB；**35 条判定、0 段未跑、34 绿 / 1 红、CHAIN_EXIT=1**。红 = 真根 p12 **C3·D 盘上 90 / 库里 89**，漏 `d:/wechat files/…/2026-10/2026年中国电竞行业研究报告.pdf`（链跑期间真数据新增；红 JSON 另存 `.probe_work/p12_real_root_chain_r18_red.json`）。产品路径补入 **doc 10991 / 21 页 / native / fts=done**；真库 **10,987 → 10,988**、`text_pages 1,975,216 → 1,975,237`、空正文 0、待办 0（`.probe_work/r18_index_wx_pdf.log`；2026-10-21 只读复核 `missing_since=NULL`、正文 21 页）。随后定点复跑 p12：**19 条全绿、未验 0 条**（20:29:44 → 21:40:10 = **4,226s**；C1 1,048.6s / C3 763.7s / C4 196.3s / C5 1,249.7s / C11 965.2s）；C2 **10,988**；C3 六根 **68/90/1967/5352/1655/1856** 各相等；C4 **1,975,237/1,975,237、漏 0/残留 0**；C5 1,975,237 页六项自洽；C9 **running 0**（done 10,941 / failed 75）；C11 8 份、最新 `integrity_check=ok` / FK 0；C12 0/0/0；C13 六根一致（`.probe_work/p12_real_root_r18_after_index.log` / `p12_real_root.json`）。**首启 20:15 那场被会话生命周期回收（日志 0 字节、无产出），读数取 20:29 重启的这场**。**这不是整链全绿** —— 链是 34/35，复跑只替换那一行。
段读数：docs-inject 0.0 / guards 3.1 / regression **215.2（785 passed / 0 failed / 0 error / 1 skipped）** / coldstart 1.4（**0.831s**）/ e2e 12.0（冷 0.830s、11 条、6 行真实检索）/ injection **674.0（225 条坏法）** / ui-inject 58.8（36/36）/ ocr 29.7（9 条 0 失败、预算停 2 页、真引擎 4 passed）/ consistency **4,057.0** / soak 320.8（9/9；S6 29 / 1.0s / `{'done': 123}`）/ package 289.9（构建 147.1 + 冒烟 142.8、400.0MiB、273/273；G20 真桌面 `优雅关闭=True（0.4s）｜窗口 5.67s｜RSS 174.5MiB｜句柄 859｜线程 17`）/ g2 58.1（6/6 + **P95 372ms**）。段和 **5,720.0s**，墙钟差 **2.8s**。

**H · p9 #13 锚点修复（#178，先修再跑链）**：#174 把 `state_event(...)` 改成四行，p9 #13 整行锚点失配；`tests/guards/test_probe_anchors.py` 先报 **259 条锚点 / 1 条失配**。锚点改成精确四行（替换体 `pass`），守卫 **51 passed in 58.98s**；聚焦坏法删 `phases` → `AssertionError: 没有 window.ready 事件` 在 `tests/integration/test_app_shell.py:181`，**1 failed / 0 passed**（`.probe_work/round18_p9_case13_check.log`）。完整 p9 没单跑（基线段含负载敏感 G1），整链里 **69/69**。

**台账与守卫**：guards 段现读 **103 行｜I1–I103 连续｜CLOSED 81｜MITIGATED 21｜OPEN 0｜WONTFIX 1｜结构不合格 1 行（上限 1）：I35**；本轮 **I102 / I103 均 CLOSED**（I103 为 21:49 授权后补执行）。链后复跑 docs-inject + guards 两次：**9 条 ALL GREEN（docs-inject 0.0s + guards 2.4s / 2.2s，rc=0；`.probe_work/final_docs_guards_r18.log` / `final_docs_guards_r18_i103.log`）**。文件长度守卫：`扫了 212 个 .py 与 31 个 .md｜临近线（余量 ≤100 行）6 份`，最紧 `tests/probes/p12_consistency.py` **800（余 0）**（另有 `test_job_queue.py 766`、`p19_combined_memory.py 742`、`theme.py 717`、`p13_soak.py 716`、`test_saved_search_ui.py 707`）。

**临时文件**：`.probe_work/` **444 项 / 848 MiB**（承重保留：`final_chain_r18.log`、`p12_real_root_chain_r18_red.json`、`p12_real_root.json`、`p12_real_root_r18_before_index.json`（补索引前 18/19 现场）、`p12_real_root_r18_after_index.log`、`final_docs_guards_r18.log`、`final_docs_guards_r18_i103.log`、`i103_before.txt` / `i103_after.txt` / `i103_backups_before_ls.txt`、`r18_index_wx_pdf.*`、`round18_soak_30min.log` / `p13_soak_30min_result.json`、`soak_r18.log`、`round18_i102_30x.log` / `i102_coldstart_30x.json`、`round18_g2_inject.log`、`round18_stage1_inject_note.log`、`round18_p9_case13_check.*`、`frozen_smoke_result.json`、`packaging_build_report.json`）。清理：`tmp_p12_timed/`（本轮计时用的临时数据根，30 个文件）清空；一份 10-18 遗留的一次性脚本与本轮的 `.probe_work/launch_p12_r18.py`、`.probe_work/tmp_patch_i103.py` 一并清空；`%TEMP%\p13_soak_1yi2rw_8` 是轮十七承重现场，保留；30 分钟与 4 分钟 soak 的临时根均已自清理；`frozen_smoke_1015_*` 是 10-15 遗留，未动。

**没测到的 / 仍欠（不许混进上面那些绿）**：① 安装包与代码签名未交付；② 隐私以后再处理；③ soak 只到 30 分钟（I32 未销账）；④ G2 90s 重试分支未活过；⑤ C11 旧快照内部损坏不在口径内（I98 乙）；⑥ consistency / injection 跨轮快慢未查明；⑦ I103 已销账（备份留最新 1 份；产品不自动清理）；⑧ 真机证据仍是自动断言（I17 残余）；⑨ 整链 r18 是 34/35，定点 p12 19/19 不是整链重跑。

> **本册末行现数（2026-10-21 勾选轮（十八）收尾取）**：
> `DECISIONS 687｜VERIFICATION 857｜本册 968｜CHANGELOG 596｜ISSUES 141` —— 轮十七 935 / 510 / 140 ⇒
> 本册 +33、CHANGELOG +86、ISSUES +1，DECISIONS / VERIFICATION 主册未动（`wc -l`＝`splitlines()`＝守卫判定那条口径；上一块轮（十七）按 §4.27 保留为历史、不动）。
> `.md` 侧无临近线（最紧的是 `UI-WIREFRAMES 951`，余 249）；`.py` 侧临近表见上一段的「台账与守卫」。
> 现册里带 `**本册末行现数**` 标题的块共 **9 块**（轮（七）／（八）／（九）／（十二）／（十三）／（十四）／（十五）／（十六）／（十七））+ 本轮这块**活的**。

### 4.29 勾选轮（十九）收尾读数（2026-10-21 21:50 → 2026-10-22 02:28，销账 **I32**，修 **I104 / I105**，另修探针两处）

**起止（墙钟，不折算成单一“活跃”数）**：轮十八最后一条 commit `463140a` **2026-10-21 21:50:47** → 本块落笔并提交 **2026-10-22 02:27:59**（`git log -1 --format=%ad`，收尾 commit `b924cf4`）= **4.62 h**。其中两场 2 小时 soak 的等待占 ≈3.95 h（第一场 22:05–00:05 作废；第二场 00:12:26–02:13:41），有效工作约 **0.7 h**。节点：G2 三向 21:54–21:59｜真桌面截图 22:00–22:09｜I104 复现与修复 22:02–22:15｜I105 修复与断言 22:14–22:20｜第一场 soak 22:05–00:05（休眠打断，弃用）｜探针诊断与修复 00:05–00:12｜第二场 soak 00:12–02:13｜回归与门禁 02:14–02:24｜文档编辑与提交 02:24–02:28。会话日志（本环境 `usage.*` 恒 0，只能拿体积当代理）：**279,036,598 B｜89,633 行**（轮十八基线 271,349,026 B / 87,595 行 ⇒ **+7,687,572 B｜+2,038 行**；2026-10-22 02:26 取数）。

**A · I32 CLOSED · 2 小时连续 soak（第二场，00:12:26 → 02:13:41）**：`--minutes 120 --keep`，探针侧 `SetThreadExecutionState` 防休眠。**9/9 全绿**、采样 **3,550 点｜跨度 7,198.5s｜最大采样空洞 2.1s**、480 轮 churn、`{'done': 2078}`。S1 rc=0；S2 `crash.log 0 字节 / Traceback 0`；S3 **12→12**（峰 17）；S4 **321→321**（峰 323）；S5 **111.8 → 103.7MiB（-8.1）**、全程 68.1–114.7、G8 余量 1,085.3；S6 **峰值 34 / 排空 2.0s**；S7 **1010/1010**（已标缺失 110）；S8 **1 份 579KiB / 2,575 行**；S9 p12 **14 条 0 红 0 未验**（逐条 C0 13ms／C1 16ms／C2 130ms／C3·corpus 429ms／C4 1ms／C5 3ms／C11 26ms，合计 <1s）。`state.log`：`startup.begin` 00:12:26.408 → `background.started` 00:12:26.518（threads 1 / watched 1）→ `shutdown` 02:13:41.716，7,275.3s（`.probe_work/round19_soak_120min.log` / `round19_soak_120min_result.json` / `round19_soak_120min_app.log` / `round19_soak_120min_state.log`）。**边界**：2 小时是本条验到的上限，天级/通宵仍未测。

**A′ · 第一场 2 小时作废（22:05 → 00:05）—— 休眠 + 探针编码两处真事故**：结果 JSON 的采样 `t` 出现 **2,170.4s（96795.1→98965.5）** 与 **822.4s（101002.8→101825.2）** 两个空洞，同时 `S1` 报 `NoSuchProcess: pid 19136 及其子进程都不在了`、S6 峰值 0、S7 盘上 702／库里 670、S9 14 条红 1 —— 应用在积压种入前已退，三条连带红不是产品坏。探针随后在打印 S5 时 `UnicodeEncodeError: 'gbk' codec can't encode character '\u2212'`（`p13_soak.py:594`），**库已跑完、结果没打出来**（`.probe_work/round18_soak_120min.log`）。处置：按「休眠场读数不作数」弃用；修 `log()` 编码兜底、加采样空洞判据（>10s 判读数不作数）与防休眠请求，再起第二场。

**B · I25 补证 · G2 90s 重试分支三向真触发**：只把 `scripts/g2_search_benchmark.py` 换成替身、门禁代码一行不改，用 `.probe_work/g2_stub_seq.txt` 控制序列：`(3,0)` → **rc 0**（段耗时 **90.5s**，首跑负载场、重试转绿）；`(3,3)` → **rc 2「环境不合格」**（**90.4s**，两次都忙，不算产品红）；`(3,1)` → **rc 1 RED**（**90.3s**，重试后仍不达标必须红）。三次都真等满 90s；替身 sha256 前后一致 `5c306992…`、逐字节还原（`.probe_work/round18_g2_retry.log`）。**口径**：这三场证明的是「分支会走、三种出口各自正确」，不是在真实负载场里恰好撞上重试；G2 判据 ≤500ms 一个字没动。

**C · I17 补证 · 真桌面 10 张截图包**：去掉 `offscreen`，`platform=windows`，10 张 **1400×880**（含暗色），14 项检查 ALL GREEN；每张带字节数与 md5（`.probe_work/screens_r18/report.json`、`r19_screens_after_fix.log`）：`seed_documents`／`dedup_group_found`／`backup_created`／`library_search_rows`／`reader_page_open`／`categories_tags`／`dedup_table_groups`／`dedup_done_total_zero`／`dedup_progress_truthful`／`backup_table_rows`／`archive_preview_picked`／`archive_files_landed`／`operations_rows`／`ten_shots_nonblank_and_distinct`。我逐张看过 S1（库）／S4（分类）／S5（判重）／S8（归档预览）。**仍未销 I17**：这是自动断言 + 我的眼睛，不是用户本人逐屏。

**D · I104 CLOSED · 归档失败回滚目标副本**：`_execute_item` 搬运前记 `dst_existed`，move/copy 失败与 copy 的 `src.unlink()` 失败都走 `_rollback_created_dst` —— 只删「本次新建、源仍在、逐字节一致」的目标副本，并写 `item_rollback`；回滚自身失败只记 `item_rollback_failed`，不盖原异常。真复现（真实 `CreateFileW` 占住源 PDF，不含 `FILE_SHARE_DELETE`）：修复前 `failed` 且目标目录多一份与源同字节的副本；修复后 `partially_done 3/2/1`、LANDED 只有 2 份、HB-001 源仍在 5,032B、journal `item_start → item_rollback → item_failed`（`.probe_work/r19_archive_repro_after_fix.log`）。回归 `TestI104RollbackWhenSourceLocked`：同盘 move / 跨盘 copy 两条；坏法删回滚 → 2 条精确红、还原 sha256 一致（`.probe_work/r19_i104_i105_injection.log`）。

**E · I105 CLOSED · 判重 `total=0` 终结态不装忙**：只有 `queued/running/paused` 的 `total=0` 显示不定进度条；`done` 收起进度条并显示「没有要算的份数」；`failed/cancelled` 显示状态词 + `last_error` 原文。真桌面截图断言 `dedup_done_total_zero=('done', 0)`、`dedup_progress_truthful` 通过；回归 done / failed 两条；坏法把终态退回避忙分支 → 2 条精确红（同一份注入日志）。

**F · 探针修复与自检**：`tests/probes/p13_soak.py` 三处 —— `log()` 编码兜底（GBK 下 `−` 降级成 `?`，不再崩）；S1 采样空洞判据 `SAMPLE_GAP_MAX = 10.0`（坏法 62s 空洞真注入）；`_prevent_sleep()` / `_allow_sleep()`。注入自检 **13/13 坏法 + 4/4 好读数**，并在 `PYTHONIOENCODING=gbk` 下真跑通过、2 分钟实跑 **9/9 ALL GREEN**（`.probe_work/round19_p13_inject_gbk.log` / `_utf8.log`、`round19_soak_smoke_2min.log`）。

**G · 回归 / 门禁 / 台账**：第一次全量回归 **788 passed / 1 failed / 1 skipped** —— 红的是 `test_doc_pointers.py::test_台账旧文件名不超过上限`（**37 > 35**：轮十八清掉的 `.probe_work/launch_p12_r18.py`、`.probe_work/tmp_patch_i103.py` 在 RUNLOGS §4.28 里必须留名）。按守卫自己的规矩逐条写明来由，`PY_STALE_CAP 35 → 37`；复跑 **789 passed / 1 skipped / 0 failed / 0 error（245.38s）**（`round19_regression.log` / `round19_regression2.log` / `round19_doc_pointers.log`）。`docs-inject + guards` **9 条 ALL GREEN、本次未跑 10 段**（`round19_docs_guards.log`）；台账 **105 行｜I1–I105 连续｜CLOSED 84｜MITIGATED 20｜OPEN 0｜WONTFIX 1｜结构不合格 1 行（上限 1）：I35**，本轮 **I32 / I104 / I105 均 CLOSED**。文件长度守卫：`扫了 212 个 .py 与 31 个 .md｜临近线（余量 ≤100 行）6 份`，最紧 `p12_consistency.py` **800（余 0）**、`p13_soak.py` **771（余 29）**。

**临时文件**：`.probe_work/` **478 项 / 851 MiB**（承重保留：本轮的 `round19_soak_120min.log` / `_result.json` / `_app.log` / `_state.log`、`round18_soak_120min.log`（作废场）、`round18_g2_retry.log`、`screens_r18/`（10 张 + `report.json`）、`r19_screens_after_fix.log`、`r19_archive_repro_after_fix.log`、`r19_i104_i105_injection.log`、`round19_p13_inject_gbk.log` / `_utf8.log`、`round19_soak_smoke_2min.log`、`round19_regression*.log`、`round19_docs_guards.log`、`round19_doc_pointers.log`）。清理：一次性脚本与备份 `.probe_work/tmp_fix_g2_log.py`、`.probe_work/tmp_g2_fixed_stdout.txt`、`.probe_work/round18_g2_retry_fixed.txt`、`.probe_work/r19_mutate.py`、`.probe_work/_i104_backup.py`、`.probe_work/_i105_backup.py`、`.probe_work/g2_real_backup.py` 全部 truncate 为 0（备份与产品文件 sha256 已逐份核对一致）；`%TEMP%\p13_soak_cddtrfhl`（第二场现场，8.5MiB，app.log 已复制）与 `%TEMP%\p13_soak_1yi2rw_8`（轮十七承重）保留；第一场的临时根已由探针自清理；`frozen_smoke_1015_*` 未动。

**没测到的 / 仍欠（不许混进上面那些绿）**：① 安装包与代码签名未交付；② 隐私以后再处理；③ soak 只到 2 小时，天级/通宵未测；④ C11 旧快照内部损坏不在口径内（I98 乙）；⑤ consistency / injection 跨轮快慢仍未查明；⑥ 真机证据仍是自动断言 + 我看图，不是用户本人逐屏（I17 残余）。

> **本册末行现数（2026-10-22 勾选轮（十九）收尾取）**：
> `DECISIONS 687｜VERIFICATION 857｜本册 998｜CHANGELOG 645｜ISSUES 143` —— 轮十八 968 / 596 / 141 ⇒
> 本册 +30、CHANGELOG +49、ISSUES +2，DECISIONS / VERIFICATION 主册未动（`wc -l`＝`splitlines()`＝守卫判定那条口径；上一块轮（十八）按 §4.28 保留为历史、不动）。
> `.md` 侧无临近线（最紧的是 `UI-WIREFRAMES 951`，余 249）；`.py` 侧临近表见上一段的「台账与守卫」。
> 现册里带 `**本册末行现数**` 标题的块共 **10 块**（轮（七）／（八）／（九）／（十二）／（十三）／（十四）／（十五）／（十六）／（十七）／（十八））+ 本轮这块**活的**。

### 4.30 勾选轮（二十）收尾读数（2026-10-22 02:28 → 2026-10-24 07:13，24h soak 按用户 ② 缩到 12h 并跑满，途中修 **I106**）

**起止（墙钟，不折算成单一“活跃”数）**：轮十九最后一条 commit `27391c7` **2026-10-22 02:28:31** → 本块落笔并提交 **2026-10-24 07:13**（`git log -1`） = **约 52.6 h**。其中 soak 等待占 ≈**49.2 h**（24h 第一场 13h40m、第二场 17h05m、第三场中止 4h28m、12h 场 14h01m），另含最后一天等 p12 真根 **1.22 h**（05:30:41 → 06:43:39）；有效工作约 **3.4 h**。节点：I106 复现与修复 10-23 12:27–12:28｜12h 场 16:58:36–20:59:53｜台账/文档 21:00–23:30｜真根漂移速查 10-24 04:5x–05:25｜产品路径补账 05:26–05:30｜p12 真根 05:30–06:43｜回归/门禁 06:49–06:56｜文档编辑 06:57–07:13。会话日志（本环境 `usage.*` 恒 0，只能拿体积当代理）：**288,790,076 B｜92,341 行**（轮十九基线 279,036,598 B / 89,633 行 ⇒ **+9,753,478 B｜+2,708 行**；2026-10-24 06:59 取数）。

**A · 12 小时 soak（`--minutes 720 --keep`，09-23 16:58:36 → 20:59:53，14h01m）—— 9/9 全绿**：采样 **21,067 点｜投放 2,880 轮｜43,201.2s**，`churn_unlink_skipped=0`。S1 rc=0｜最大采样空洞 **2.6s**｜RSS 中位 **76.4MiB**；S2 `crash.log 0 字节 / Traceback 0`；S3 **12→12**（峰 17）；S4 **321→321**（峰 323）；S5 **75.3 → 75.6MiB（+0.3）**、全程 **3.0–120.6**、G8 余量 **1,079.4**；S6 峰值积压 **17**、排空 **7.1s**、`{'done': 12711}`；S7 盘上 **5,810**／库里未标缺失 **5,810**（已标缺失 **1,110**）；S8 日志 **2 份 3,546KiB**（当前 7,032 行）；S9 p12 **14 条全绿 0 未验**（逐条 C0 32ms／C1 270ms／C2 1,699ms／C3·corpus 6,373ms／C11 49ms，合计 <9s）。`state.log`：`startup.begin` 2026-10-23T08:58:35Z → `shutdown` 2026-10-23T20:59:53Z（`.probe_work/round20_soak_720min_r1.log` / `_app.log` / `_state.log` / `p13_soak_result.json`）。**边界**：12 小时是本条验到的上限，**24 小时未验**——不许写成天级。

**A′ · 24 小时两场腰斩 + 第三场主动中止（原样引 meta）**：第一场 `2026-10-22T05:31:45 → 19:11:39`（**57%**），被 `19:11:43 optionalfeatures.exe` / `19:11:50 winlogon` 发起的**机器重启**切断（app.log 直到 19:11:39 都在正常索引，无 Traceback）；第二场 `2026-10-22T19:21:59 → 2026-10-23T12:27:07`（**71.2%**），探针 `_churn` 删刚投放的 `soak_add_61500_2.pdf` 撞上应用正在读取（`WinError 32`），异常冒到 `main()` 把应用带走（产品侧 app.log 无 Traceback、crash.log 不存在）—— 即 **I106**；第三场 `12:28:46 → 16:57:00`（**4h28m**）按用户勾选 **②「缩到 12h 并如实写明边界」** 主动中止，现场作废（`.probe_work/round20_soak_1440min_r2_meta.txt` / `_r3_meta.txt`）。**口径**：三场的读数都不进上面 A 的绿，只有 12h 场算数。

**B · I106 CLOSED · 探针 churn 撞 Windows 文件锁**：`_unlink_retry(path, attempts=5, delay=0.2)`，重试耗尽记 `_UNLINK_SKIPS` 并跳过该文件（不抛）；结果 JSON 带 `churn_unlink_skipped`。复现验证：held-open 0.4s 的 3 次全部跳过、关掉后同路径成功、重试期间释放也成功；12h 场 `churn_unlink_skipped=0`、2,880 轮全投放（`docs/ISSUES.md` I106；复现三向真跑 ALL GREEN：held-open 返回 False / skipped=1 / 文件仍在，after-close 返回 True，released-mid-retry 返回 True——`.probe_work/r20_unlink_repro.log`；场读数见 `.probe_work/round20_soak_720min_r1.log` / `_r3_meta.txt`）。**产品侧一行未改**。

**C · `--c11-deep` · 旧快照逐份整库体检**：`tests/probes/p12_consistency.py` 从 800 行降到 **576**（拆出 `tests/probes/p12_inject.py` 272 行），C11 默认只体检最新快照（I98 乙），加 `--c11-deep` 逐份。夹具 10 份、损坏 `older-snapshot.db`：默认 `rc=1 ok=True`（仅最新整库体检）；deep `rc=1 ok=False` 并点名 `older-snapshot.db：integrity_check=*** in database main *** / 2nd reference to page 9 / Page 3 is never used / NULL value in documents.path_key`；默认 vs deep 的 7 条对照断言 ALL GREEN（`.probe_work/r20_p12_deep_e2e.log`），拆件后 `--inject` 真跑 **21/21 条坏法 + 口径边界 1/1**（`.probe_work/round20_p12_inject.log` / `r20_p12_inject.json`）。

**D · consistency / injection 跨轮快慢 A/B（同机背靠背，顺序跑，未并行）**：A **852.0s**（起跑 CPU 42.9%／可用 4,120MiB）、B **867.5s**（33.9%／4,781MiB），**+1.8%**；r18 整链同段 **674.2s**。九条探针 r20 均值 / r18 = **1.18–1.43x（均值 1.28x）**，**没有一条单独变慢** ⇒ 这一层差是整机档位（负载/内存压缩/夜间频率），不是探针代码（`.probe_work/r20_inject_ab_summary.txt` / `r20_inject_a.log` / `r20_inject_b.log`）。**口径**：A/B 证明的是「同场两跑一致」，不是「跨轮变慢已查明」。

**E · I17 十屏 contact sheet + 用户勾选清单**：把轮十九的 10 张真桌面截图（`platform=windows`、1400×880、含暗色）拼成一张带标题对照图，并生成逐屏勾选清单；14 项自动断言 ALL GREEN（`.probe_work/screens_r18/contact_sheet.png` / `I17_CHECKLIST.md` / `report.json`）。**I17 仍未 CLOSED**：需要用户本人逐屏打勾。

**F · 真根漂移清零 + p12 真根 19/19**：只读速查（复用产品 `iter_tree`/`Exclusions`/`identity_key`，逐根 68/91/1,967/5,352/1,655/1,857，总耗时 ≈1,326.9s）发现 D 漏索引 2、漏标缺失 1，H 漏索引 1（`.probe_work/r20_drift_before.json`）。全部走产品路径补账：`reconcile_path` → `index_document`，缺失那条走 `_vanish` → `mark_missing`——D 补 **doc 10992（29 页）/ 10993（7 页）**、doc 93 打缺失、H 补 **doc 10994（338/341 页）**，失败 0（`.probe_work/r20_index_drift.log`）。随后 p12 真根 **05:30:41 → 06:43:39 = 4,378s，19 条全绿、未验 0 条**：C2 **10,991**；C3 六根 **68 / 91（标缺失 1，库内 92）/ 1967 / 5352 / 1655 / 1857**；C4 **1,975,611/1,975,611、漏 0/残留 0**；C5 **1,975,611 页（ocr 0）、六项自洽**；C9 **running 0**（done 10,941 / failed 75）；C10 14 分类；C11 快照 1 份 `pre-migration-0008-20261020T122144.db 11,686,936KiB@v7`、整库体检 **939,804ms**；C12 超页 0；C13 六根一致（`.probe_work/p12_real_root_r20.log` / `.json`）。**计时口径**：C3 六行共享同一次 walk 的 **975,995ms**，六行不是相加（`.probe_work/p12_real_root_r20.log` 逐条计时）；C1 1,074,180ms、C5 1,180,940ms、C11 939,820ms 是单条。

**G · 回归 / 门禁 / 台账 / 文件长度**：全量回归 **789 passed, 1 skipped, 0 failed / 285.82s**（最终树；前一场 292.86s，改用最终树重跑后取这一场，`.probe_work/round20_regression_final.log` / `round20_regression.log`）。`docs-inject + guards` **9 条 ALL GREEN、本次未跑 10 段**（`.probe_work/round20_docs_guards.log` / 终版文档编辑后复跑 `round20_docs_guards_final.log`）；台账 **106 行｜I1–I106 连续｜CLOSED 85｜MITIGATED 20｜OPEN 0｜WONTFIX 1｜结构不合格 1 行（上限 1）：I35**，本轮 **I106 CLOSED**。文件长度守卫：`扫了 213 个 .py 与 31 个 .md｜临近线（余量 ≤100 行）5 份`——`p13_soak.py 794（余 6）`、`test_job_queue.py 766（余 34）`、`p19_combined_memory.py 742（余 58）`、`theme.py 717（余 83）`、`test_saved_search_ui.py 707（余 93）`（`.probe_work/r20_file_size_guard.log`）。**最紧那份只余 6 行，下一轮写 p13 之前先按主题拆。**

**临时文件**：`.probe_work/` **529 项 / 858 MiB**（承重保留：`round20_soak_720min_r1.log` / `_app.log` / `_state.log`、`p13_soak_result.json` 与 `p13_soak_result_720min_r1.json`、`round20_soak_1440min*`（两场腰斩与中止场）、`r20_p12_deep_e2e.log`、`r20_unlink_repro.log`、`round20_p12_inject.log` / `r20_p12_inject.json`、`r20_inject_a.log` / `r20_inject_b.log` / `r20_inject_ab_summary.txt` / `r20_inject_ab_table.txt`、`screens_r18/contact_sheet.png` / `I17_CHECKLIST.md` / `report.json`、`r20_drift_before.json` / `r20_drift_before.log`、`r20_index_drift.log`、`p12_real_root_r20.log` / `.json`、`round20_regression.log`、`round20_docs_guards.log`、`r20_file_size_guard.log`、`r20_file_lines.log`）。清理：一次性脚本 `.probe_work/r20_d_gone.py`、`.probe_work/r20_drift_check.py`、`.probe_work/r20_index_drift.py`、`.probe_work/r20_file_lines.py`、`.probe_work/r20_contact_sheet.py`、`.probe_work/r20_index_wx_pdf.py`、`.probe_work/r20_soak_watch.sh` 一律 **truncate 为 0**（产物与日志保留；`.probe_work/` 前缀是守卫 `PY_EXEMPT_PREFIX` 的白名单口径，不是漏写）。`%TEMP%\p13_soak_*` 六个现场：`1yi2rw_8` 2.0M（轮十七承重）、`cddtrfhl` 8.5M（轮十九）、`y__zpmjb` 22M（24h 第三场中止）、`sflorq9f` 44M（12h 场，`--keep`）、`234b6zq4` 55M / `x0o2q_br` 67M（两场 24h 腰斩），合计 ≈199M，**都留着**（现场可复查，不动）。

**没测到的 / 仍欠（不许混进上面那些绿）**：① 安装包与代码签名未交付；② 隐私以后再处理；③ **24 小时未验**（12h 是验到的上限；两场分别被机器重启与探针自伤切断）；④ C11 旧快照内部损坏不在默认口径内（I98 乙，需要时加 `--c11-deep`）；⑤ consistency / injection 跨轮快慢定位到「整机档位」，未再做更细的归因；⑥ I17 仍是自动断言 + 我看图/contact sheet，**不是用户本人逐屏**；⑦ 本轮 p12 是定点复跑 19/19，不是整链 11 段重跑。

> **本册末行现数（2026-10-24 勾选轮（二十）收尾取）**：
> `DECISIONS 687｜VERIFICATION 857｜本册 1028｜CHANGELOG 703｜ISSUES 144` —— 轮十九 998 / 645 / 143 ⇒
> 本册 +30、CHANGELOG +58、ISSUES +1，DECISIONS / VERIFICATION 主册未动（`wc -l`＝`splitlines()`＝守卫判定那条口径；上一块轮（十九）按 §4.29 保留为历史、不动）。
> `.md` 侧无临近线（最紧的是 `UI-WIREFRAMES 951`，余 249）；`.py` 侧临近表见上一段的「回归 / 门禁 / 台账 / 文件长度」。
> 现册里带 `**本册末行现数**` 标题的块共 **11 块**（轮（七）／（八）／（九）／（十二）／（十三）／（十四）／（十五）／（十六）／（十七）／（十八）／（十九））+ 本轮这块**活的**。

### 4.31 修复轮（二十一）收尾读数（2026-10-24 07:13 → 14:15，销账 **I107**，新开 **I108**）

**起止（墙钟）**：上一 commit `b1fb6dc` **2026-10-24 07:13:36** → 本块落笔并提交 **≈14:15** = **约 7.0 h**。其中 I107 的复现 → 修复 → 守卫 → 重拍 → 收尾集中在 **13:55–14:15（≈0.35 h）**；上半日是 I17 十屏逐屏核对 + 用户问答（含等用户回话的间隔，未逐段计时，不折算成"有效工时"）。会话日志（本环境 `usage.*` 恒 0，只能拿体积当代理）：**292,579,207 B｜93,406 行**（轮二十基线 288,790,076 B / 92,341 行 ⇒ **+3,789,131 B｜+1,065 行**；14:13 取数）。

**A · I107 复现与定位（S3 计划表目标路径画成 `C…`）**：轮二十 I17 逐屏核对在 `r18_08_archive_preview.png` 上读到三行目标路径都只有一个 `C…`。用产品路径复现（`bootstrap` → `MainWindow` → `archive._load_documents()` → 勾 3 份 → `_generate_preview()`，模型里 `len(dst_path)` 正常是 99/103/99），四组对照：`_plan_repro_full.png` 原样复现 `C…`；`_plan_nowrap.png`（`setWordWrap(False)`）恢复；`_plan_elidemid.png`（`ElideMiddle`）恢复；`_plan_slashes.png`（同一单元格换成正斜杠串）原来就正常。**定位**：单行行高 + `ElideRight` 对「反斜杠 + CJK 混排的整段不可断词」把 260px 单元格画成首字符；**不是**列宽、不是取数。**离屏不复现**：`_plan_mix.png` 的 ink 宽在 wrap True/False 下都是 248px（离屏无 CJK 字形），所以这条退化只能在真桌面看。

**B · 修复（一处中心改动覆盖 8 张表）**：`ui/table_layout.py::set_table_columns()` 在 `setStretchLastSection(False)` 之后加 `table.setWordWrap(False)`。全站 8 张表（archive 2 / backup 2 / library 1 / operations 2 / dedup 1）都经这里，且都是单行行高。顺带把同一段注释里「判重页自己配表头」的旧话改准（I61 之后它也走这里）。

**C · 守卫 + 坏法注入**：`tests/integration/test_ui_tier.py::test_每张表都是单行行高_不许开自动换行` 逐屏 `_select_by_page_id` → `reload()` → `findChildren(QTableWidget)`，断言每张表 `wordWrap()` 为假并扫到 **8** 张。**坏法真注入**（把那行注释掉）→ **1 failed**，断言点名 `test_ui_tier.py:307` 与具体页面；还原后 `test_ui_tier.py` **21 passed / 5.06s**（文件 sha256 与备份一致，已核对）。**边界**：离屏画不出这条退化，守卫钉的是**开关位**；绘制结果仍由真桌面截图复核，docstring 里写明。

**D · 十屏重拍 + contact sheet + 清单措辞**：`.probe_work/r18_screens_real.py` 原样重跑（真 windows 平台、`%TEMP%` 合成语料、1400×880、DPR 1.5 ⇒ PNG 2100×1320）：`report.json` **14 项 ALL GREEN**、10 张非空且互不相同（`ten_shots_nonblank_and_distinct` PASS）；08 目标路径读作 `C:\Users\lavie\AppData\Local\Temp…`。`contact_sheet.png` 按新 md5 重建（2032×4432，带 14 项断言清单与 I107 前后对照）。`I17_CHECKLIST.md` 按实现改四处：05 明写「默认分类写入结果」「扫描与索引任务」两块**在状态框内要向下滚动**；07 三列改为「文件名 / 版本 / 修改时间」（无大小列）；08 写明修前 `C…`、修后读到什么；09 改为「ID / 类型 / 状态 / 总数 / 完成 / 失败」并写明详情表**要先点中批次**；另注明 01/02/10 的横向滚动条是 I48/I61 的定宽口径。**I17 仍未 CLOSED**：需要用户本人逐屏打勾。

**E · 新开 I108（OPEN，等勾选）**：09 的「操作项详情」在未选中批次时是一张没有任何提示的空表 —— 批次表有 1 行、`done`、完成 3，下面什么都没有。甲＝未选中时显示一行「先点一条批次」；乙＝`reload()` 后默认选中最新一条。`operations_page.py` 的 `reload()` 不设默认选中、`_on_op_selected()` 在 `currentRow() < 0` 时只 `setRowCount(0)`，代码与截图一致（只读核对，未改）。

**F · 回归 / 门禁 / 台账 / 文件长度**：全量回归 **790 passed, 1 skipped, 0 failed / 289.17s**（轮二十基线 789，+1 是 C 段那条新守卫；`.probe_work/r21_regression.log`）。`docs-inject + guards` **9 条 ALL GREEN、本次未跑 10 段**（`.probe_work/r21_docs_guards.log`）；其中「台账里失效的测试名」现数 **6 处 / 上限 6**（未涨）。台账 **108 行｜I1–I108 连续｜CLOSED 86｜MITIGATED 20｜OPEN 1｜WONTFIX 1｜结构不合格 1 行（上限 1）：I35**，本轮 **I107 CLOSED**、**I108 OPEN**。文件长度守卫：`扫了 213 个 .py 与 31 个 .md｜临近线（余量 ≤100 行）6 份` —— `p13_soak.py 794（余 6）`、`test_job_queue.py 766（余 34）`、`test_ui_tier.py 711（余 89，本轮新进）`、`test_saved_search_ui.py 707（余 93）`、`p19_combined_memory.py 742（余 58）`、`theme.py 717（余 83）`。**最紧那份仍只余 6 行，下一轮写 p13 之前先按主题拆。**

**临时文件**：`.probe_work/` **550 项 / 860 MiB**（轮二十 529 项 / 858 MiB）。承重保留：`screens_r18/`（10 张新图 + `contact_sheet.png` + `I17_CHECKLIST.md` + `report.json`）、`_plan_repro_full.png` / `_plan_nowrap.png` / `_plan_elidemid.png` / `_plan_slashes.png` / `_plan_mix.png` / `_plan_cell.png` 及各 `_crop*.png`、`_r21_08_plan_crop.png`、`r21_regression.log`、`r21_docs_guards.log`。一次性脚本与备份 `.probe_work/r20_plan_cell_probe.py`、`.probe_work/r20_plan_repro.py`、`.probe_work/r20_ink_probe.py`、`.probe_work/_i107_backup.py`、`.probe_work/r21_contact_sheet.py` **一律 truncate 为 0**（`.probe_work/_i107_backup.py` 与还原后的 `table_layout.py` sha256 已核对一致）。

**没测到的 / 仍欠（不许混进上面那些绿）**：① **I17 仍未 CLOSED** —— 十屏要用户本人逐屏打勾；② I108 等勾选，未动代码；③ 本守卫钉的是「关闭自动换行」这个开关位，**不是**绘制结果（离屏无 CJK 字形）；④ 本轮只跑 `docs-inject + guards`，其余 10 段门禁未跑；⑤ 安装包与签名仍未交付、24 小时 soak 仍未验（沿用轮二十边界）。

> **本册末行现数（2026-10-24 修复轮（二十一）收尾取）**：
> `DECISIONS 687｜VERIFICATION 857｜本册 1054｜CHANGELOG 746｜ISSUES 146` —— 轮二十 1028 / 703 / 144 ⇒
> 本册 +26、CHANGELOG +43、ISSUES +2，DECISIONS / VERIFICATION 主册未动（`wc -l`＝`splitlines()`＝守卫判定那条口径；上一块轮（二十）按 §4.30 保留为历史、不动）。
> `.md` 侧无临近线（最紧的是 `UI-WIREFRAMES 951`，余 249）；`.py` 侧临近表见上一段「回归 / 门禁 / 台账 / 文件长度」。
> 现册里带 `**本册末行现数**` 标题的块共 **12 块**（轮（七）／（八）／（九）／（十二）／（十三）／（十四）／（十五）／（十六）／（十七）／（十八）／（十九）／（二十））+ 本轮这块**活的**。

### 4.32 勾选轮（二十二）收尾读数（2026-10-24 14:15 → 14:3x，**I17 用户勾选销账** + **I108 甲**）

**起止（墙钟）**：上一 commit `759e047` **2026-10-24 14:15:20** → 本块落笔 **≈14:36** = **约 0.35 h**。节点：用户答复「10 屏全过 / I108 甲」14:15｜I108 实现 + 测试 + 坏法 14:16–14:19｜十屏重拍 + 拼图 14:19–14:22｜台账/清单 14:22–14:30｜回归（两场）14:24–14:34｜文档 14:31–14:36。会话日志（本环境 `usage.*` 恒 0，只能拿体积当代理）：**294,178,916 B｜93,841 行**（14:33 取；轮二十一基线 292,949,984 B / 93,481 行 ⇒ **+1,228,932 B｜+360 行**）。

**A · I17 CLOSED（用户本人逐屏，第一次）**：`screens_r18/I17_CHECKLIST.md` 十项全部勾「☑ 过」，含两处设计取舍 —— 05「默认分类写入结果 / 扫描与索引任务两块要在状态框内向下滚动」接受、09「未选批次时详情为空表」接受（随即改选了 I108 甲）。**口径**：勾选时看的是 14 项断言那一版；09 随后按甲多了一行提示，整包重拍为 15 项 —— 这层时间顺序写进清单头部，不把"用户勾过的"与"当前屏上的"混成一件事。

**B · I108 甲（S4 详情空态提示）**：`ui/pages/operations_page.py` 在标题与详情表之间加 `item_hint`（muted），文案「先点上面一条批次，详情才会列出它搬了哪些文件」；`_sync_item_hint()` 在 `reload()` 与 `_on_op_selected()` 后统一同步 `setVisible(op_table.currentRow() < 0)`。`reload()` 仍不设默认选中 —— 乙被否的理由是「撤销选中批次」会在没人选的时候就可点。09 屏读数：提示可读、详情 0 行（`.probe_work/_r21_09_hint_crop.png`）。

**C · 守卫 + 坏法注入**：`tests/integration/test_archive_execute_ui.py::test_没选中批次时详情区写明先点批次` —— 未选中：批次 1 行 / `currentRow() < 0` / 详情 0 行 / 提示可见且文案对；选中：详情 1 行 / 提示不可见。**坏法真注入**（`setVisible(...)` 改恒 `False`）→ **1 failed** 并点名 `test_archive_execute_ui.py:346`；还原后该文件 **16 passed**。

**D · 十屏重拍（15 项断言）**：`.probe_work/r18_screens_real.py` 加 `operations_item_hint` 检查后整包重跑（真 windows、1400×880、DPR 1.5 ⇒ 2100×1320）：`report.json` **15 项 ALL GREEN**、10 张非空且 md5 互不相同（09 = 66,976B / `47fbf58123de`；08 目标路径仍读作 `C:\Users\lavie\AppData\Local\Temp…`）。`contact_sheet.png` 重建为 **1980×3698 / 1,226,916B**（一次性脚本 `.probe_work/r21b_contact_sheet.py` 用完 truncate 为 0）。

**E · 守卫先报：轮二十一的 §4.31 写了 4 处裸探针文件名**：`docs-inject` 的「台账旧文件名 ≤ 37」红在 **41 处**（补完 §4.31 两处又量到 **38**），多出来的全是 `.probe_work/r20_plan_repro.py` / `.probe_work/r20_ink_probe.py` / `.probe_work/_i107_backup.py` / `.probe_work/r21_contact_sheet.py` —— 裸名等于宣称仓库里该有这些文件。修法：逐个补 `.probe_work/` 前缀（`PY_EXEMPT_PREFIX` 白名单），**上限 37 未动**；复跑该条 **1 passed**。

**F · 回归 / 门禁 / 台账 / 文件长度**：全量回归 **791 passed, 1 skipped, 0 failed / 291.54s**（轮二十一 790，+1 = C 段新用例；第一场 301.17s 因 E 段而红，修后重跑取这一场，`.probe_work/r22_regression.log`）。`docs-inject + guards` 于本轮文档定稿后复跑（读数见末行）；台账 **108 行｜I1–I108 连续｜CLOSED 87｜MITIGATED 20｜OPEN 0｜WONTFIX 1｜结构不合格 1 行（上限 1）：I35**，**I108 CLOSED**、OPEN 归零。文件长度守卫：`扫了 213 个 .py 与 31 个 .md｜临近线 6 份` —— `p13_soak 794（余 6）`、`test_job_queue 766（余 34）`、`p19_combined_memory 742（余 58）`、`theme 717（余 83）`、`test_ui_tier 711（余 89）`、`test_saved_search_ui 707（余 93）`；本轮新增用例把 `test_archive_execute_ui.py` 推到 **462 行**，不在临近线。

**临时文件**：`.probe_work/` **554 项 / 860 MiB**（轮二十一 550 项）。新增承重：`r22_regression.log`、`_r21_09_hint_crop.png`、`_r21b_sheet_head.png`；`.probe_work/r21b_contact_sheet.py` **truncate 为 0**。`screens_r18/` 10 张图 + `contact_sheet.png` + `I17_CHECKLIST.md` + `report.json` 全部更新为 15 项版本。

**没测到的 / 仍欠（不许混进上面那些绿）**：① 本轮只跑 `docs-inject + guards`，其余 10 段门禁未跑；② I108 走的是甲，乙（默认选中）未实现、也不打算实现；③ 安装包与签名仍未交付；④ **24 小时 soak 仍未验**（12h 是验到的上限）；⑤ 05 屏「要滚才看全」只是用户接受了现状，没有改成自适应高度；⑥ 本轮 I17 的勾选针对 14 项那版，09 多出的那一行由「甲」这条决策本身背书，未再单独请用户复核。

> **本册末行现数（2026-10-24 勾选轮（二十二）收尾取）**：
> `DECISIONS 687｜VERIFICATION 857｜本册 1080｜CHANGELOG 783｜ISSUES 146` —— 轮二十一 1054 / 746 / 146 ⇒
> 本册 +26、CHANGELOG +37、ISSUES +0，DECISIONS / VERIFICATION 主册未动（`wc -l`＝`splitlines()`＝守卫判定那条口径；上一块轮（二十一）按 §4.31 保留为历史、不动）。
> `.md` 侧无临近线（最紧的是 `UI-WIREFRAMES 951`，余 249）；`.py` 侧临近表见上一段「回归 / 门禁 / 台账 / 文件长度」。
> 现册里带 `**本册末行现数**` 标题的块共 **13 块**（轮（七）／（八）／（九）／（十二）／（十三）／（十四）／（十五）／（十六）／（十七）／（十八）／（十九）／（二十）／（二十一））+ 本轮这块**活的**。

### 4.33 整链补跑（2026-10-24 14:38 → 15:56，12 段 35 判定 → 3 红定点复跑）

**起跑（墙钟）**：14:38:22 → 整链落 VERDICT **15:09:14**（12 段合计 1,852.6s ≈ 30.9 min）；随后三条红逐条复跑到 **15:56**。命令：
`gates/final.py --all --data-root "C:/Users/lavie/AppData/Local/PdfArchiver"`（日志 `.probe_work/final_chain_r22.log`）。

**口径先说清**：整链那一场是 **32/35 绿**，不是全绿。三条红都不是产品缺陷，但要逐条修后**定点复跑**才转绿 —— 定点重跑只替换那三行，**不能把整链写成 35/35 ALL GREEN**（同轮十八那条口径）。
另：14:36 起跑的**第一场已作废**（stdout 被块缓冲、日志 0 字节，我在无法观察时误杀 regression/e2e 子进程）；中止后核对工作树干净、清掉标记，改 `python -u` 重起。**作废那一场不回填任何读数。**

**A · 红 1/3 —— `regression`**：`790 passed / 1 failed / 1 skipped / 297.25s`，红在 `tests/guards/test_doc_pointers.py::test_台账旧文件名不超过上限`：**46 > 37**。根因是本轮 §4.32 的 E 段与「临时文件」段把 **9 处**探针名写成了裸名（CHANGELOG 4 处 + RUNLOGS 4 处 + `.probe_work/r21b_contact_sheet.py` 1 处）。修法：逐个补 `.probe_work/` 前缀，**上限 37 一个字没动**；独立复跑该守卫 **37 处、VERDICT: ALL GREEN**（`.probe_work/r22_p16_after.log`）。

**B · 红 2/3 —— `injection` 里的 p16**：同一条根因（`1 failed, 7 passed in 117.15s`）。补前缀后复跑 `p16_doc_pointers_injection.py`：**11 条（8 坏法 + 3 反向对照）｜抓住 8、漏网 0、点名存疑 0、对照破 0、锚点失配 0｜ALL GREEN**（`.probe_work/r22_p16_probe.log`）。

**C · 红 3/3 —— `consistency` 真根**：`0.3s` 红在 C0 之前的「库不存在：`…\PdfArchiver\data\data\catalog.db`」。这是**调用参数传深了一层**：p12 用 `AppPaths.resolve(data_root)`，自己会拼 `data/`。不是数据不一致，也不是产品问题。

**D · 三条红的定点复跑**：
- 回归：**791 passed / 1 skipped / 289.71s**（`.probe_work/r22_regression2.log`）。
- p16：见 B。
- 真根：`--only consistency --data-root "C:/Users/lavie/AppData/Local/PdfArchiver"` → p12 注入自检 **21/21 + 口径边界 1/1**、p14 **ALL GREEN**、真根 **19 条｜红 0｜未验 0**（`.probe_work/r22_consistency_real.log` / `p12_real_root.json`）。真根逐条计时：C1 1,037,900ms｜C5 1,241,146ms｜**C11 961,441ms**（最新一份 11,686,936KiB@v7 整库体检）｜C3·六盘各 785,823ms｜C4 218,742ms｜C2 3,367ms；库 **v8**、主记录 **10,991**、正文 **1,975,611** 行、`running 0`、`na` 全量 10,991。
- 清标记的判据：注入段**只有整段全绿才删** `injection_inflight`，p16 红使它按设计留了下来；`git status --short` 只有两份文档改动 ⇒ 源码已由探针还原，确认后才删标记重跑。

**E · 其余九段读数（整链那一场，全部 PASS）**：coldstart **1.045s**；e2e 生命周期冷启动 **1.016s** + **11 条端到端通过**；injection p9 **69/69**（225.6s）、p10 **45/45**（140.1s）、p17 3、p18 3、p21 24、p22 33、p23 23、p24 17；ui-inject p15 **36 条**（74.4s）；ocr 三条（落库 6 页 / 预算 2 页真停机 / 引擎套件 **4 passed 0 skipped**）；soak 4 分钟（**60 点、最大空洞 2.0s、RSS 112.4 → 112.6MiB、积压峰 18 排空 1.0s、S7 82/82、S8 1 份、S9 14 条**）；package **400.0MiB**、构建 147.7s、冒烟 141.3s（273/273、recover 1 条）；g2 **P95 = 326.0ms**（直接复跑探针取数：20 查询 × 5 reps、起跑 CPU 4.9%，`.probe_work/r22_g2_value.log`）。

**没测到的 / 仍欠**：① 整链那场按上面的口径是 32/35，三行绿的证据来自定点复跑，**不是同一场**；② **24 小时 soak 仍未验**（4 分钟采样与 12h 档都不等于 24h）；③ 安装包与代码签名仍未交付；④ I108 乙明确不实现；⑤ 本轮未重跑 `--c11-deep`（旧快照内部损坏仍按 I98 的口径不算）。

> **本册末行现数（2026-10-24 整链补跑收尾取）**：
> `DECISIONS 687｜VERIFICATION 857｜本册 1113｜CHANGELOG 794｜ISSUES 146` —— 轮二十二 §4.32 1080 / 783 / 146 ⇒
> 本册 +33、CHANGELOG +11、ISSUES +0，DECISIONS / VERIFICATION 主册未动（`wc -l`＝`splitlines()`＝守卫判定那条口径；§4.31/§4.32 按历史保留、不改写）。
> 文件长度守卫直接跑：`扫了 213 个 .py 与 31 个 .md｜临近线（余量 ≤100 行）7 份`——`p13_soak.py 794（余 6）`、
> `test_job_queue.py 766（余 34）`、`p19_combined_memory.py 742（余 58）`、`theme.py 717（余 83）`、
> `test_ui_tier.py 711（余 89）`、`test_saved_search_ui.py 707（余 93）`、
> **本册 1113（余 87，本轮新进临近线）**；台账 108 行、失效测试名 6 处（上限 6，未涨）。
> 现册里带 `**本册末行现数**` 标题的历史块共 **14 块**（轮（七）……（二十二））+ 本轮这块**活的**。


### 4.34 轮二十三（2026-10-24）· 先拆再写 / 收尾预检 / 真库小样本语义实跑

**这一轮做了什么**：用户勾 **1 + 4 + 5②**，外加「本轮三条红全是自伤，处理了」。三条红的共同形状
（裸探针文件名 ×2、`--data-root` 传深一层）被拆成两件事：**先把会超线的文件拆掉**，**把上一轮踩过的坑
变成起跑前就判的预检**。

**A · 切册（**D-059**）**：`VERIFICATION-RUNLOGS.md` **1,113 → 372 行**，§4.17–§4.25 **九块**整批
逐字搬进 `docs/VERIFICATION-RUNLOGS-ARCHIVE.md`（**757 行**）。守恒断言由 `.probe_work/u23_split_runlogs.py`
当场跑：切片首/尾必须是 `### 4.17` / `### 4.26`、**节号 17 = 分册 9 + 活册 8**、跨文件指针
**16 行**只改文件名（同一行混着两个册的引用就直接 assert 失败）。分册已进
`tests/guards/test_doc_pointers.py` 的 `SELF_DEFINING` / `LEDGER_DOCS`（台账类现在是 **9 份**）。

**A2 · p13 拆分**：`tests/probes/p13_soak.py` **687 行** + `tests/probes/p13_soak_inject.py`
**142 行**；`main()` 内延迟导入，顶层不反向依赖。副产物：`test_subprocess_encoding.py` 里那条
`p13_soak.py:416` 的过期行号被改成不带行号的描述（拆分后挪到 465）——**行号一挪就是假指针**。

**A3 · 守卫自己的性能缺陷（本轮新发现）**：`_resolve_md()` 每解析一个引用就 `rglob` 一次全仓，
把 `.venv`（**16,393 文件 / 1,424 目录**）整个走一遍；三个守卫文件同跑 **>18 分钟挂死**
（两个 python 进程、167s CPU），`faulthandler` 堆栈点名的就是它。改成 `os.walk` 剪枝**建一次索引**后：
doc_pointers **9 passed / 5.35s**、guards 全量 **54 passed / 30.56s**。

**B · 收尾预检一键脚本**：`scripts/precheck.py` 两步固定顺序 —— `pytest tests/guards` →
`gates/final.py --only docs-inject --only guards`；子进程显式 `encoding="utf-8"`；任一红即停；
末行唯一 `VERDICT:`。实跑：**PASS 1/2（54 passed, 39.11s）｜PASS 2/2（门禁 9 条 ALL GREEN）｜
VERDICT: ALL GREEN**，总 **~60s**。接线守卫 `tests/guards/test_precheck.py` 三条：argv 必须带
两个 `--only`、假红 runner 只许跑 1 步、假绿 runner 必须打出 `PASS  1/2` / `PASS  2/2`。

**C · 真库小样本语义实跑**（`tests/probes/p25_semantic_sample.py`，只读）：
真库以 `mode=ro` + `pragma query_only=1` 打开，`random.Random(20261024).sample(300)`
（`text_status ∈ {native, mixed}`、`page_count 1–60`），每份前 7 页 →
**300 份 / 1,709 页 / 651,964 字**。嵌入走产品 `EmbeddingService`（bge-small-zh int8，DirectML）：

| 读数 | 值 |
| --- | --- |
| provider | `['DmlExecutionProvider', 'CPUExecutionProvider']` |
| 模型加载 | **1.66s** |
| 吞吐 | **1,709 页 / 23.46s = 13.7 ms/页 = 72.86 页/秒** |
| RSS | 130.3 → 281.7 MiB（**+151.4**） |
| 全量折算 | 1,975,611 页 ÷ 72.86 = **7.53 小时** |
| 库体积 | int8 **0.94 GiB** ／ fp32 **3.77 GiB** |

召回（top-10，期望是「某份的第 1 页」）：**语义按文档 19/20、按页 16/20｜全文自然句 0/20｜
全文关键词 12/20｜互补 16/20**。4 条按页错的里有 **3 条是同一份文档的别的页**
（277 得 277:6、286 得 286:2、332 得 332:4），只有 346 连文档都没进（top1 是 332:4）。
3 条关键词 0 命中的都是**带空格的两词串**（`服饰 时尚` / `国庆 出游` / `元宇宙 电商`）——
产品按 `match_expression()` 把整串当**一个短语**，不拆词；直接查库 `数据 治理` 仍有 167 条，
证明不是系统性坏，是口径。2 字词（`塔罗` / `圣杯`）走 `MIN_FTS_CHARS=3` 的 LIKE 回退，都命中。

**两处探针自己的 bug（先修再报数，首跑读数作废）**：① 命中判定写成 `[d, p] in [(d, p)]` ——
**列表 vs 元组恒为 False**，导致首跑全文通道恒 0/20；② 2 字关键词一律进 FTS 而 trigram 组不出 gram，
产品口径本应走 LIKE。修前直接查库反证：`竞品分析` 命中 `(255,1)` 第 2 名、`数据的本质` 命中 `(245,1)`。
另：**上一场报的「全量 47.77 小时」作废** —— 那是 120 页小样本（11.49 页/秒）被首跑预热摊薄，
本场 1,709 页把预热摊薄掉后是 **7.53h**，以本场为准。

**D · 收尾回归（第一场是负载场，不许记成全绿）**：`pytest tests` 第一场 **793 passed / 1 failed /
1 skipped in 466.21s**，唯一红是 `test_进程级冷启动实测符合G1约定`（**5.439s** > 1.5s；单独复跑仍 **3.593s**）。
同场负载：**`TOTClient-Win64-Shipping.exe` 365% CPU / 2.9GiB**、可用内存仅 **2.1GiB** —— 这条是
**负载绑定**项（**ISSUES I25**），而本轮改动**不碰启动路径**（只有文档、守卫、探针）。
按既有口径 deselect 后复跑：**793 passed / 1 skipped / 1 deselected in 216.29s**（同一套代码，
比负载场快一倍多 ⇒ 慢的是机器不是代码）；负载降下来后**单条复跑 G1：1 passed，冷启动 1.055s**
（`import_to_run 0.797s｜assemble 0.179s｜window 0.079s`，与历史 1.045s 对齐）。
**口径**：G1 那行的绿来自**负载撤掉后的单条复跑**，不是第一场同一时刻的读数。

**没测到的 / 仍欠**：① 查询是**我模拟的** 20 条，不是用户手里那 20 条真查询 ⇒ **ISSUES I11 不销账**；
② 按页严格口径 **16/20 低于** D-035 的 18/20 门槛，**不许**拿 19/20 的文档级读数宣布 G15 绿；
③ 样本只覆盖每份**前 7 页**（全库 1,975,611 页里抽 1,709 页），长文档后半段的表现未测；
④ 真库 `vector_status` 仍是全 `na`、没有建库入口（产品侧那半条见 **ISSUES I63**），本轮是**只读探针**；
⑤ 本轮未跑整链（只跑预检的两步），其余 10 段门禁未跑；⑥ **24 小时 soak 仍未验**。

> **本册末行现数（2026-10-24 轮二十三收尾取 · 切册后第一块）**：
> `DECISIONS 687｜VERIFICATION 857｜本册 455｜分册 757｜CHANGELOG 846｜ISSUES 146` ——
> 轮二十二整链块记的是 本册 1,113 / CHANGELOG 794 / ISSUES 146 ⇒ 本轮 **本册 −658、分册 +757**
> （§4.17–§4.25 九块整批搬走，再写进 §4.34 与这一块）、CHANGELOG **+52**、ISSUES **+0**（只改 I11
> 那一行的证据，没加行）；DECISIONS / VERIFICATION 主册未动（`wc -l`＝`splitlines()`＝守卫判定那条口径；
> 旧块按历史保留、不改写）。**本册从 1,113（余 87）回到 455（余 745），退出临近线。**
> `.md` 侧最紧的是 `CHANGELOG-ARCHIVE 1,064（余 136）`——注意它与本册是两份，别把两册加起来比红线。
> `.py` 侧：`test_job_queue.py 766（余 34）`、`p19_combined_memory.py 742（余 58）`、
> `theme.py 717（余 83）`、`test_ui_tier.py 711（余 89）`、`test_saved_search_ui.py 707（余 93）`；
> `p13_soak.py` 从 794 降到 **687**，**退出临近线**。
> **块数口径**：切册后本册只剩 **8 块**（轮十六…二十二整链）—— 更早那 9 块随 §4.17–§4.25 进了分册；
> 上面几句「共 12 / 13 / 14 块」是切册**之前**的陈述，按历史保留、不改写。加本轮这块 = **9 块**。
