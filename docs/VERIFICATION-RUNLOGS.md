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

### 4.35 S7「库体检」落地轮（二十四）收尾读数（2026-10-24 18:25 → 23:5x，#198 按 **1甲 2甲 3甲 4甲** 实现 + 其余 10 段门禁）

用户这一轮的指令是两条：「其余 10 段门禁跑吧」+「#198 跟进你的建议来吧」（建议 = **1甲 2甲 3甲 4甲**）。
线框已在轮二十三交付并确认，本轮第一次允许写界面代码。

**A · 实现（三层各一处，SQL 只在 repositories）**：新 `db/repositories/health.py`（253 行，
十四项的 SQL/PRAGMA 唯一落点；`TEXT/PARSE/OCR/VECTOR_LEGAL` 四个合法值集合写在这里，
`p12` 反过来 import —— 原先探针自带一份是第二个口径）；新 `services/db_check.py`（380 行，
`run(mode)` 唯一取数判定口，每条单独计时、异常变成带原文的红行，`_remember()` 只写六键）；
新 `ui/pages/health_panel.py`（203 行，`threading.Thread(daemon=True)` + 跨线程 `Signal(object)`，
不用 QThread 因为关窗会打 "Destroyed while thread is still running"）；
`services/bootstrap.py` 装配 `db_check`（构造零成本，`expected_version` 取迁移目标版本）；
`ui/pages/settings_page.py` 下半区改 `QStackedWidget` 两页就地翻页。

**B · 测试**：新 `tests/integration/test_db_check.py` **8 条**（快速十行零红 / 坏根键点名 C13 /
0 字节快照在全库档判红且 C11 只体检最新一份 / 上次体检恰好六键 / 异常变红行 / 没跑起来也给原文 /
设置页翻页跑快速体检并回写 / 全库档确认框先给成本）；`test_status_readout.py` **10 passed**。
五组坏法真注入并还原：C13 恒绿、C11 跳过 0 字节、`finished` 断线、`_remember` 多写 `detail`、
临时加第 10 张表（`test_ui_tier.py` 两处 `seen` 同时红）。受影响守卫 **62 passed**。

**C · 本轮逮到的真回归（不是负载）**：720 窗高下 S7 上半区只看得见 **13 行**（要求 ≥15），
`sizes=[258,417]`。根因是新加的「上次体检」行放在**共享标题栏**，把下半区 `minimumSizeHint`
顶高 36px ⇒ 上半区被挤。修法：那一行移进 `HealthPanel` 自己那页（隐藏时不参与尺寸），
`SettingsPage.reload_last_check()` 改调 `health_panel.set_last_check()`。
修后实测：720 档 `split=[280,395]`、可见 **15** 行；切到体检页仍是 `[280,395]`（1甲 的「翻页不跳高」）；
1409 档 `[886,478]`、可见 **61** 行 / 47 块。

**D · 真库（11GB / 主记录 10,991 / 正文 1,975,611）跑了一次产品服务的快速档**：
10 行、**9 通过 + 1 读数（C9）、0 红**、整场 **11,755ms**（最慢三项 C2 4,333ms / C12 3,798ms /
C4 3,461ms）。这条读数**推翻了线框里「秒级」那句成本说明**（那是没测过的估计），
故本轮把 `QUICK_COST` 改成「11GB 真库实测约 12 秒」、`FULL_COST` 改成同口径两场的
「约 57 分钟与约 67 分钟」，线框 §S7 补页与 `health_panel` 的措辞同步；
`test_db_check.py` 那条断言也跟着从 `"秒级"` 改成 `"约 12 秒"`。
**口径**：这一趟是脚本直接调服务的取数与判定（`_specs` + `_one`），**故意不调 `_remember()`** ⇒
真库 `app_settings` 里没有多出 `db_check.last` 那一行（真库仍只被读，没被写）。

**E · 其余 10 段门禁（一条后台命令，20:45:17 → 22:54:54 = 7,776.8s ≈ 2h09m）**：
`--only regression coldstart e2e injection ui-inject ocr consistency soak package g2`，
**26 条判定｜4 红｜1 段未跑（guards，已由预检两步覆盖）**，末行 `VERDICT: RED（4 条未过）`。
起跑负载 CPU **69.5%**、可用内存 **1,333MiB**、最吃内存进程 `TOTClient-Win64-Shipping.exe` **4,296MiB**。
四条红**同源于 G1 冷启动**（不是四个问题）：regression（801 passed / 1 failed，唯一红是
`test_进程级冷启动实测符合G1约定`）、coldstart（3.554s）、e2e（2.454s）、
injection（p9 的**基线**里含同一条 G1 ⇒ `VERDICT: RED（基线就没过…）`，其后 8 条探针全绿）。
`soak / package / g2 / consistency / ocr / ui-inject` 六段当场全绿。

**F · 四条红逐条定点复跑（负载压下去之后，只替换这四行，不是同一场）**：
p9 单独复跑 **抓到 69/69 条坏法｜ALL GREEN**（23:09）；e2e 段复跑 **ALL GREEN**，
冷启动 **1.266s**（此前同段三次读数 1.341 / 1.204 / 1.215）；coldstart 段五次读数
**1.298 / 1.456 / 1.506 / 1.523 / 2.400s**（同一套代码，抖动全在 1.5s 线附近）；
regression 第三场 **802 passed / 0 failed / 1 skipped（228.7s）｜ALL GREEN**（23:21，起跑 CPU 52.3%）。
G1 单条 10 次连测：**1.217–2.0s，9/10 次 ≤1.5s**；`window.ready` 拆分 `import_to_run 1.059–1.178s`
（占 87%）、`assemble 0.045–0.055s`、`window 0.113–0.121s` ⇒ 新增的三张模块不在启动路径上
（自测 `health_panel import 46ms`、`HealthPanel build 14ms`）。**阈值 1.5s 一处没动**（**ISSUES I25 / I102** 同源）。

**G · 真根一致性（consistency 段，5,599.4s ≈ 93.3 分）**：p12 注入自检 **21/21 + 口径边界 1/1**、
p14 仪表 **四种坏法 × 五种口径全绿**、真根 **19 条｜红 0｜未验 0**，库 **v8**、主记录 **10,991**、
正文 **1,975,611** 行、`running 0`、`done 10,941 / failed 75`。逐条计时最慢五项：
**C5 1,541,084ms、C3 每盘 1,537,579ms × 6 盘、C1 1,200,867ms、C11 1,036,524ms、C4 259,539ms**。
与轮二十二（§4.33）那场比，四个慢项同向变慢 15–24%（C1 +15.7% / C5 +24.2% / C11 +7.8% / C4 +18.6%）
而库的行数一字未变 ⇒ 差额是**机器负载**（那场起跑 CPU 63.3–87.3% 区间外的更低档，本场 69.5%）。
**所以 `FULL_COST` 从「约 57 分钟」改成「约 57 分钟与约 67 分钟」两个读数并写**，不挑对自己有利的那一个。

**H · 其余段读数**：ocr 三条（队列 done 进度 [6,6] / 预算 2 页真停在第 3 页 / 真引擎 **4 passed 0 skipped**）；
soak 4 分钟（采样 60 点、最大空洞 2.0s、RSS 112.4→112.6MiB、G8 余量 1,087.3MiB、积压峰 35 排空 1.0s、
S7 盘上 82 = 库里 82）；p13 注入自检 **13/13 + 好读数放行 4/4**；package 构建 **400.1MiB / 229.5s**、
冻结冒烟 **158.6s**（8 条 PASS，含强杀残尸 1 条被 recover 续跑、documents 273 = 磁盘 273）；
g2 分类自检 **6/6** + 真库 P95 **ALL GREEN**；ui-inject p15 **36 条坏法 ALL GREEN**。

**没测到的 / 仍欠**：① **全库档（13 项 / 约一小时）没有在界面里真跑过** —— 只在服务层跑过快速档，
全库档的判据由 p12 真根那场同口径覆盖，界面侧只验到「弹成本确认 + 按钮禁用」；
② 四条红的绿来自**定点复跑**，与那场 26 条判定**不是同一时刻**；
③ injection 整段（9 条探针）未在负载撤掉后整段复跑，只单独复跑了其中红的 p9；
④ **24 小时 soak 仍未验**（12h 是验到的上限）；⑤ 真库 `vector_status` 仍全 `na`（**ISSUES I63**）；
⑥ 体检面板尚未做**真机（非 offscreen）**截图核对 —— 本轮的几何证据都是 offscreen 量出来的。

> **本册末行现数（2026-10-24 轮二十四收尾取）**：
> `DECISIONS 687｜VERIFICATION 857｜本册 455 → 542｜分册 757｜CHANGELOG 846 → 907｜ISSUES 146｜UI-WIREFRAMES 992 → 997` ——
> 轮二十三那块记的是 本册 455 / CHANGELOG 846 ⇒ 本轮 **本册 +87**（新增 §4.35 这一块）、
> CHANGELOG **+61**（轮二十四条目 + 门禁读数对账）、ISSUES **+0**（没加行；G1 那条仍是 **I25 / I102**
> 的 MITIGATED 残留，本轮只补读数不改状态）、UI-WIREFRAMES **+5**（§S7 补页的成本措辞按实测改）。
> `.md` 侧最紧的仍是 `CHANGELOG-ARCHIVE 1,064（余 136）`；本册 542（余 658）、CHANGELOG 907（余 293）。
> `.py` 侧临近线（≥690 行）**5 份**：`test_job_queue.py 766（余 34）`、`p19_combined_memory.py 742（余 58）`、
> `theme.py 717（余 83）`、`test_ui_tier.py 711（余 89）`、`test_saved_search_ui.py 707（余 93）`；
> 本轮新增四张文件 `health.py 253 / db_check.py 380 / health_panel.py 203 / test_db_check.py 179`，
> **没有一份逼近 800**（`db_check.py` 因成本文案两处改写从 379 到 380，`test_db_check.py` 那条断言改字面量、行数不变）。
> **块数口径**：本册从 **9 块**（轮十六…二十三 + 轮二十三那块）加本轮 = **10 块**。

### 4.36 轮二十五（2026-10-25）· 真机两档 / 四条红同场转绿 / 真库全库档在界面里跑（销 ①②③⑥，新开 **I109 / I110**）

用户这一轮的指令逐字：「全库档 13 项没在界面里真跑过；四条门禁红的绿来自定点复跑、与那场 26 判定不是同一时刻；
injection 整段未空载复跑；体检面板只有 offscreen 几何证据。 按你建议执行」。
⇒ 本轮**产品代码一行没改**，只补证据 + 入账两条新事实。

**A · 真机（非 offscreen）S7 体检页两档真跑 + 截图包 —— 销 ⑥**：驱动 `.probe_work/u25_screens_health.py`
（**不设** `QT_QPA_PLATFORM` ⇒ 报告里 `platform = windows`，中文真渲染），种子小库（主记录 6 / 正文 9 行 /
迁移生成的快照 8 份）跑在隔离 `work_dir`，00:34:33 → 00:34:38，**31 条判定 ALL GREEN**，`work_dir_removed = true`
⇒ 真库这一场一个字节都没被写。两档点的都是产品自己的按钮（`QtTest.QTest.mouseClick`）：快速 10 行
（9 通过 + 1 读数 C9、0 红）、全库 13 行（12 通过 + 1 读数、0 红，`C1` 第二位 / `C5` 第五位 / `C11` 末位）；
翻页不跳高 `([417,415],[417,415])`，跑完体检仍是同一对数字；五张图 md5 各异，而「翻回设置页」那张与第一张
设置页 **md5 完全相同**（`e16a48889123`）⇒ 1甲 的「翻回原样」第一次有像素证据。两条坏法证明判据有牙：
`data_root` 指错 ⇒ `VOID_wrong_dataroot_report.json` RED（`confirm_dialog_yes_taken`、`four_shots_nonblank_and_distinct`
不成立）；把 `[库体检…]` 那颗按钮拆掉 ⇒ `VOID_inj_no_toggle/` RED（`health_side_flipped` / `full_report_arrived` /
`before_and_after_differ` / `running_shot_differs_from_before` / `bottom_row_painted` 五条不成立）。

**B · 四条 G1 同源红并进同一条命令的一场上全绿 —— 销 ②③**：
`gates/final.py --only regression --only coldstart --only e2e --only injection`（后台 `python -u`），
02:59:27 → 03:15:32 = 965s ≈ **16 分 05 秒**，起跑负载 CPU **32.4%**｜可用 **3,809MiB**｜最吃内存
`MemCompression 908MiB`；**合计判定 13 条｜0 红｜末行 `VERDICT: ALL GREEN`**（7 段 SKIP：guards / ui-inject / ocr /
consistency / soak / package / g2 —— 这一场不含它们）。轮二十四那四条红正是这四段（§4.35 E），本轮它们在
**同一时刻**成立：regression 187.5s **802 passed / 0 failed / 1 skipped**、coldstart 1.7s **冷启动 1.046s**、
e2e 13.2s（冷启动 1.009s + 11 条端到端）、injection 760.1s。
③ 的账：injection 整段 **9 条探针**在负载撤下来之后第一次同段全绿 —— 反向注入 69/69、G5 45/45、p16 8 坏法 + 3 对照、
p17 3、p18 3、p21 24/24、p22 33/33、p23 23/23、p24 17/17（**抓坏法合计 225 条**，逐段 `VERDICT: ALL GREEN`
打在 `.probe_work/u25_chain4_r25.log`）。**口径（不许写成空载）**：这一场 CPU 32.4% 是**低负载场**，
不是真空载场 —— CPU<10% 的 injection 整段读数至今仍然没有。**G1 的 1.5s 一处没动。**
`injection_inflight` 标记 03:02:52 建、整段全绿后被门禁自己删掉 ⇒ 注入的坏法全部还原，
收尾 `git status` 只剩 `docs/ISSUES.md` 的两行改动。

**C · 真库（11,995,631,616B ≈ 11.2GiB｜主记录 10,991｜正文 1,975,611）全库档 13 项走界面路径真跑 —— 销 ①**：
驱动 `.probe_work/u25_real_full.py` —— 真窗口开 S7 → 点 `health_toggle_btn` 翻到体检页 → 点「全库体检」→
确认框（正文就是 `FULL_COST`）选「是」→ 后台线程跑 13 项 → `Signal` 回主线程铺表 → `_remember()` 回写。
- **run1** 00:41:12 → 01:13:01：13 行｜12 通过 + 1 读数｜**0 红**｜服务层 **1,618.2s = 26 分 58 秒**；
  但四张截图 md5 全同（135,576B `4dd11a2713b3`）⇒ `before_and_after_differ`、`bottom_shot_scrolled` 不成立，
  **整场判 RED**，改名 `real_full_report_run1_no_visual.json` 保留：只当计时证据，不当视觉证据。根因写在脚本
  162-165 行的注释里 —— 上一场漏了点 `[库体检…]`，按钮在没露面的那一页上照样点得动、体检照样跑完，只是画不出东西。
- **run2** 01:30:37 → 02:36:53：**17 条判定 ALL GREEN**、同样 13 行 0 红、服务层 **3,390.1s = 56 分 30 秒**；
  四张图 md5 各异（162,483 / 164,774 / 195,037 / 199,810），滚到底那一张
  `range=9｜value=9｜viewport_h=135｜last_row_rect=[105,133]｜last_row_on_screen=true` ⇒ 末行 C11 真画在屏上。
- **两场的业务表零变化**：`counts_before == counts_seen == {docs 10,991｜pages 1,975,611}`（每场各测一次前后）。
- **这一轮确实写了真库两处设置**（与 §4.35 D 那趟「故意不调 `_remember()`」相反 —— 这一趟就是产品路径本身）：
  `app_settings` 里 `db_check.last` 由 run1 首次写入
  `{ts:1792860359, mode:full, total:13, red:0, readings:1, elapsed_s:1618.2}`，run2 覆盖成 `elapsed_s:3390.1`；
  另有 `ui.last_nav_page="monitor"`（`updated_at=1792867012` = run2 收尾那一刻）。两条都是产品自己的键、
  都能在界面里改回；**要不要复位 `ui.last_nav_page` 等你说，我不自己动真库。**

**D · 本轮逮到的两条新事实（入账 **ISSUES I109 / I110**，一行代码没动，等勾选）**：
- **I109**：S7 一在屏就把 `SELECT count(*) FROM text_pages WHERE source_kind='ocr'`（`source_kind` 无索引 ⇒
  `EXPLAIN QUERY PLAN = SCAN text_pages`）放在**主线程**上跑，真库单条 **201.1 / 212.3 / 210.7s**（现态 / 冷 / 热，±3%）。
  触发点两处：建窗路径（`main_window.py:101` 恢复上次所在屏 → `SettingsPage.__init__:128` → `reload_status`）与
  `patrol_tick`（`main_window.py:254-258`，S7 可见就每个 `scan_poll_seconds=5` 秒排一次）。证据 = py-spy 两次
  MainThread 栈 + `inspect.getsource` 逐字断言的 SQL + 同场 IO `read_bytes ≈ 9.9GiB`。
- **I110**：全库档成本文案写死「约 57 分钟与约 67 分钟」，而本轮同库同按钮相邻两场实测 **26 分 58 秒 / 56 分 30 秒**
  ⇒ 区间下界被自家读数打破。逐项：C1 851.2→1,081.5（1.27×）、C11 708.2→932.9（1.32×）、**C4 5.8→191.9（33×）**、
  **C5 46.7→1,178.0（25×）**，其余九项两场都在 0.0–3.9s；负载方向还是反的（CPU 60.4% 那场反而快 2.1 倍）。
  两个候选机制都做了实验并都被排除：页缓存（201.1/212.3/210.7s）与并发同表扫描互相拖慢（各自 207.7s / 209.7s = 0.99×）。
  **机制未定位。** 另记一条本场**没控住的变量**：C 的两场里 S7 全程可见 ⇒ `patrol_tick` 每 5 秒就往主线程排一次
  I109 那条 ~200s 扫描 ⇒ 两场的 C4/C5 都不是「安静库上的读数」。它两场共有、不能解释那 2.1 倍，但 I109 若走 丙，
  成本必须重测一次再定文案。
- **读数口径纠正（历史记录不改写）**：§4.35 G 段把 p12 的 C3 记成「每盘 1,537,579ms × 6 盘」—— 实际那六行里的 ms
  是同一个循环的累计值，逐项总和 5,581s 与该场总耗时 5,599.4s 吻合；四个慢项的读数本身有效，只有那句「× 6 盘」是误读。

**E · 预检**：`scripts/precheck.py` 本轮留档两次 —— **02:59:13**（`.probe_work/u25_precheck_r25b.log`，放整链之前）与
**03:35:15**（`.probe_work/u25_precheck_final.log`，文档定稿之后再收一次口），两步都 `VERDICT: ALL GREEN`
（54 条守卫 **10.81s / 9.91s**；门禁 `docs-inject + guards` 9 判定 ALL GREEN、10 段 SKIP）—— 先确认台账改动不会被自己的守卫判红，
再放 16 分钟的整链。（`.probe_work/round24_precheck.log` 那条 **00:01:24** 是轮二十四的收尾预检，不算在本轮头上。）

**没测到的 / 仍欠**：④ **24 小时 soak 仍未验**（12h 是验到的上限）；⑤ 真库 `vector_status` 仍全 `na` —— 本轮 C7 现读
逐字 `非 na 的行 0 条｜分布 {'na': 10991}｜全部合法（产品里没人写它，所以恒为 na 或测试夹具值）`（**ISSUES I63**）；
⑦ **I109** 等勾选（甲/乙/丙/丁，建议 **丙 + 丁**）；⑧ **I110** 等勾选（甲/乙/丙/丁，建议 **丙**）；
⑨ injection 的**真空载**（CPU <10%）整段读数仍没有；⑩ 全库档只跑过两场，27–67 分钟这个跨度的机制未定位 ——
所以 `FULL_COST` 那句文案本轮**没改**：改它属于 I110 的勾选结果，不该在「把证据补齐」这一轮顺手定。

> **本册末行现数（2026-10-25 轮二十五收尾取）**：
> `DECISIONS 687｜VERIFICATION 857｜本册 542 → 627｜分册 757｜CHANGELOG 907 → 946｜ISSUES 146 → 148｜UI-WIREFRAMES 997` ——
> 轮二十四那块记的是 本册 542 / CHANGELOG 907 / ISSUES 146 ⇒ 本轮 **本册 +85**（新增 §4.36 这一块）、
> CHANGELOG **+39**（轮二十五条目）、**ISSUES +2**（新开 **ISSUES I109 / I110**，两条都 **OPEN** 等勾选，没有一条被自行实现）。
> **本轮 `src/` 与 `tests/` 一行没改** —— 四条欠账全是证据欠账，不是功能欠账，所以不触发线框回环节，`.py` 侧临近线五份
> （`test_job_queue.py 766（余 34）`、`p19_combined_memory.py 742（余 58）`、`theme.py 717（余 83）`、
> `test_ui_tier.py 711（余 89）`、`test_saved_search_ui.py 707（余 93）`）与轮二十四逐字相同。
> `.md` 侧最紧的仍是 `CHANGELOG-ARCHIVE 1,064（余 136）`；本册 627（余 573）、CHANGELOG 946（余 254）。
> **块数口径**：本册从 **10 块**（§4.27…§4.35）加本轮 = **11 块**。

### 4.37 轮二十六（2026-10-25 04:0x → 13:1x）· I109 丙+丁 / I110 丙+安静档复测 / I111 甲+丁 / ⑤ 真库语义索引真写（新开 **I112**）

用户这一轮的指令逐字：「⑤ 真库 vector_status 全 na（I63）｜⑦⑧ 等上面两条勾选｜⑨ injection 真空载读数｜⑩ 27–57 分钟跨度的机制未定位。 跟进你的建议来」，
随后两条「跟进你的推荐建议来」「继续执行之前中断的后续部分」。⇒ 本轮**按我自己上一轮给出的推荐**执行：
⑦ **I109 丙 + 丁**、⑧ **I110 丙**（前置是安静库上的同口径复测）、**I111 甲 + 丁**、**⑤ ⑤ 真库小样本真写**；
⑨（真空载 injection）只在起跑 CPU <10% 时跑，本轮**没等到这个窗口**（见 F 段）；⑩ 的机制仍未定位。

**A · I109 丙 + 丁（`src/` 三处 + `tests/` 两处）**：`StatusService.read_tasks` 加 `with_ocr_pages=True` 开关，
关掉时 `ocr_pages=None`（**不是 0** —— 界面写「未现数（这条要全库扫描，按「重新读取数据库状态」才数）」，
`TaskStatus._pages_text()` 一处出两种说法）；`StatusPage` 拆两条重查路线：`reload()` 是完整的（只有
「重新读取数据库状态」那颗按钮走，tooltip 明写「那一条要逐行扫正文表，库大了要在这里等几分钟」），
`reload_progress()` 是轻版本（建窗路径与 `patrol_tick` 的 5 秒节拍都改走它，`SettingsPage.reload_status()`
跟着换）。**真库只读实测**（`.probe_work/u26_i109_light_path.txt`，末行 `VERDICT: ALL GREEN`）：在
11,995,631,616B 真库上让建窗 + 一次巡检节拍真跑，trace 捞到 **55 条语句、合计 0.309s**（最慢两条是
`documents` 的两个状态 GROUP BY，15.8 / 14.0ms；`count(*) FROM documents` 0.9ms；`processing_jobs`
三条 2.4–3.3ms；其余 ≤0.1ms），**逐行扫 `text_pages` 全表的语句：无** —— 对照被摘掉的那一条
201.1 / 212.3 / 210.7s。**丁 的两条守卫在 `tests/integration/test_status_readout.py`**：
`test_自动节拍不现数全库OCR页数`（用 sqlite `set_trace_callback` 捞这一轮**真执行过**的 SQL 逐条
`EXPLAIN QUERY PLAN`，出现不带 `USING` 的 `SCAN text_pages` 即红；并断言那一格写着「未现数」）与它的
反面配对 `test_探测器在按钮路径上真的抓得到那条扫描`（按钮路径**恰好**一条全表扫描、且显示 `0 页`）——
没有配对那条，探测器写成恒返回空列表也会绿。

**B · I110 丙 + 安静档同口径复测（真库只读，`db_check.last` 一字未动）**：上一轮 §4.36 D 自己记下的条件是
「I109 若走 丙，成本必须重测一次再定文案」。复测分两段、**不许拼成「同场 13 项」**：
- **十二项同场**（`.probe_work/u26_realdb_full_quiet.txt`，04:44 → 05:29:36 被会话生命周期切断、无末行）：
  起跑 CPU **23.1%**｜可用 4,437MiB｜最吃内存 `MemCompression 616MiB`；合计 **2,665.8s（44 分 26 秒）**，
  C1 **1,096.0s（18 分 16 秒）**、C5 **1,343.0s（22 分 23 秒）**、C4 **220.4s（3 分 40 秒）** 三条占 **99.8%**，
  其余九项 0.0–4.7s（C12 4.7 / C2 1.5 / C6 0.2）。
- **C11 单跑**（`.probe_work/u26_c11_only.py` → `.txt`，末行 `VERDICT: ALL GREEN`）：**1,156.4s（19 分 16 秒）**，
  快照 1 份 `pre-migration-0008-20261020T122144.db 11686936KiB@v7`、整库体检 1 份 1,156,368ms；
  起跑 CPU **86.7%** → 收口 16.7%（这半段落在本条自家历史区间 708.2–1,036.5s 的**上半段**）。
- **两段相加 3,822.2s ≈ 63 分 42 秒（写作文案时取「合计约 64 分钟」）**。**零写红线**：两段都没调
  `_remember()`，收尾快照里 `db_check.last` 仍是上一轮界面跑剩下的 `elapsed_s:3390.1`、字节数与
  `settings_keys` 全部一致（12:3x 复核 `updated_at=1792867009` 未动）。
- **文案四处同步**：`services/db_check.py` 的 `FULL_COST`（去掉 `**` 加粗符 —— 它是 UI 字符串）与模块 docstring、
  `ui/pages/health_panel.py` docstring、`docs/UI-WIREFRAMES.md` S7 硬条件段、`tests/integration/test_db_check.py`
  的 `test_全库档的确认框先给成本`（新增四个安静档数字 + `合计约 64 分钟` + `assert "**" not in where`）；
  `pytest tests/integration/test_db_check.py -q` ⇒ **10 passed in 3.24s**。
- **几何**（`.probe_work/u26_cost_label_geometry.py`，末行 `VERDICT: ALL GREEN`）：成本文案变长后标签
  **1024×720 86→100（+14px）/ 1280×800 58→72（+14px）**，体检表仍是 180px 下限，状态行底边
  538 < 页高 676 ⇒ 不许出现滚动条的那两块没被顶出去。
- **台账**：I110 由 OPEN 转 **MITIGATED**（丙 已落地），残留仍记：乙「2.1 倍机制未定位」不许销账。

**C · I111 甲 + 丁（本轮前半落账，读数补在这里）**：`bootstrap.py:285-291` 先建一只 `VectorStore` 再注入
`SemanticSearchService`，`search_service.py:25-34` 加可选 `vector_store` 参数（不注入仍自建，`gates/stage6.py`
两处照旧）；`vector_store.py:9` 那句「内存映射」改成「整份读进内存」（实测 `mmap_mode="r+"` 后原地
`np.save` ⇒ `OSError: [Errno 22]`，收尾删文件 ⇒ `WinError 32`）。四段实测 `.probe_work/u26_i111_proof.py`
→ `.log`（末行 `VERDICT: ALL GREEN`，只写临时目录、不碰真库）：结构两只实例 `id(reader)=…5712｜
id(writer)=…3248`；缓存致盲（写 3 页后同一实例仍 0 命中、它自己的 `count()` 已报 3；换新实例 3 命中）；
双写者 `IntegrityError: UNIQUE constraint failed: vector_meta.vector_idx`；FK 在 `VectorStore` 自开的连接上
是死的（`doc_id=999999` 插得进、`vector_meta 现有 5 行｜库里 0 份文档`）。守卫两条进
`tests/integration/test_vector_write_path.py`（第 8、9 条），连同原 7 条 **9 passed**；三条坏法
（不注入 / 构造函数忽略注入 / 只把 `ai_classify` 换第二只）分别红在指定断言上。

**D · ⑤ 真库语义索引：装模型 → 备份在先 → 20 份真写 → 当场命中 → 重启后重载**（`.probe_work/u26_semantic_pilot.py`
→ `.txt`，末行 `VERDICT: ALL GREEN`，起跑 CPU 42.3%｜可用 2,434MiB）：
- **装模型**：`.probe_work/models/bge-small-zh-v1.5` → `%LOCALAPPDATA%/PdfArchiver/models/`，
  `onnx/model_int8.onnx` **23,903,394B**，0.36s。
- **备份在先**：走产品 `BackupService.create_backup()` ⇒ `backup-20261025-045656-v8`，
  **70.1s｜11,995,631,616B**（= 真库原大小，逐字节同量级）。
- **真写**：写前 `vector_status {'na': 10991}｜vector_meta 0`；样本池 **3,273 份**（非缺失、`native/mixed`、
  1–60 页），`seed=20261025` 点名 20 份 ⇒ **20/20 done｜549 页｜549 条向量｜19.28s**；
  写后 `{'done': 20, 'na': 10971}｜vector_meta 549`，**主记录 10,991 与正文 1,975,611 前后一致**。
- **当场命中（I111 甲 的用户可见后果）**：同一只 `SemanticSearchService` 立刻搜 3 条（拿样本首页正文起题）
  ⇒ **3/3 命中来源**：`[7841,1,0.6323]`／`[7013,55,0.7396]`／`[10872,17,0.7041]`。
- **重启后重载**：另起一个进程从磁盘重载 ⇒ `count() 549`、`data/vectors.npy 281,216B`
  （= 549×512+128 头，账对得上）、同两条查询仍命中同源页。**探针自己有一处打印错误**：它把
  `vectors.npy` 取在数据根而不是 `data/` 下，打出「0B」；文件真身在 `data/vectors.npy`，产品侧无问题 ——
  这一行以本节为准，探针输出里的 `0B` 不作数。
- **配套口径订正（四处）**：C7 那三处「产品里没人推进它」在 ⑤ 落地后变成假话，本轮按实际写入方改写
  `services/db_check.py:_c7`、`db/models.py` 的 `VECTOR_STATUSES` 注释、`tests/probes/p12_consistency.py`
  的标题与测量串、`tests/probes/p12_inject.py` 的 C7 坏法名（只改文案，判定逻辑一条没动）。

**E · 新事实入账 **ISSUES I112**（写路径 2.56 倍慢 + 每份整表 `np.save` 的 O(n²) 写放大，未实现）**：
同一台机器、同一模型、同一份真语料，**写路径 28.48 页/秒**（35.1 ms/页）对 **只读批式 72.86 页/秒**
（轮二十三 `p25_semantic_sample.py`）⇒ **2.56 倍**；去掉首份冷启动（1 页 1.98s 含 session 首次加载）后
548 页 / 17.30s = 31.68 页/秒，仍差 2.30 倍 ⇒ 冷启动不是主因。根因两条：`vector_service.py:209` 逐页
`embed_single`（batch=1，而 `EmbeddingService.BATCH_SIZE=16`）；`vector_store.py:167-175` 的 `add_batch`
每份都把**整个** `vectors.npy` 重新 `np.save`、`:170` 的 `np.vstack` 再复制一遍。按最大量级反算
（**推算，不是实测**）：终值 964.8 MiB、累计写 ≈ 5.06 TiB（按本场备份 171 MB/s 折算 ≈ 9 小时顺序写）、
常驻 964.8 MiB 占 G8 红线 1,200MiB 的 80%、`vstack` 瞬时 ≈ 1.9 GiB。全量折算 **19.27 小时**（20 份小样本
线性外推，短文档把每份固定开销摊贵，属保守值）。方案甲乙丙丁见台账，**推荐 甲 → 乙**。

**F · ⑨ 真空载 injection：本轮没测到（如实记「没有读数」）**：13:00 两次采样（10s 窗口）整机
**CPU 43.8%**，占用者是 `DoubaoWork.exe` 123.6% + `WorkBuddy.exe` 68.8% + 另两只 `DoubaoWork` —— 都不是本项目的进程，
按规矩不替用户关；CPU<10% 的窗口本轮**没出现**，所以 injection 整段的真空载读数**仍然没有**。
上一轮的低负载场（CPU 32.4%、§4.36 B）不许拿来当空载。

**没测到的 / 仍欠**：④ 24 小时 soak 仍未验（12h 是上限）；⑨ 真空载 injection 仍无读数；⑩ I110 的 2.1 倍机制
仍未定位（安静档复测没解释它：C1 与 C5 都落在自家历史区间内，唯一异常仍是轮二十五那场的 C4 5.8s / C5 46.7s）；
**I112** 等勾选；I111 残留 ①②③④⑤⑥（跨进程、FK、双 `EmbeddingService`、`delete_by_doc` 死行占 top_k）
一条都没销。

> **本册末行现数（2026-10-25 轮二十六收尾取）**：`DECISIONS 687｜VERIFICATION 857｜本册 627 → 734｜分册 757｜CHANGELOG 946 → 1,000｜ISSUES 148 → 150｜UI-WIREFRAMES 997 → 1,003` ——
> 轮二十五那块记的是 本册 627 / CHANGELOG 946 / ISSUES 148 ⇒ 本轮 **本册 +107**（新增 §4.37）、
> CHANGELOG **+54**（轮二十六条目）、**ISSUES +2**（本轮新开 **I111** 与 **I112**；I109/I110/I111 三条只改状态与证据格，不增行）。
> **本轮 `src/` 改了 10 份**（`db/models.py`、`semantic/search_service.py`、`semantic/vector_store.py`、
> `services/bootstrap.py`、`services/db_check.py`、`services/status_service.py`、`ui/main_window.py`、
> `ui/pages/health_panel.py`、`ui/pages/settings_page.py`、`ui/pages/status_page.py` —— 逐份见 `git diff --stat`）、
> **`tests/` 改了 7 份**（`test_db_check.py`、`test_status_readout.py`、`test_vector_write_path.py`、
> `p9_reverse_injection.py`、`p10_reverse_injection_ocr.py`、本轮 C7 文案两处 `p12_consistency.py` / `p12_inject.py`）、
> **`docs/` 改了 7 份**（本册、`CHANGELOG.md`、`ISSUES.md`、`UI-WIREFRAMES.md`、`OCR.md`、`TROUBLESHOOTING.md`、
> `ARCHITECTURE.md` —— 最后一份是 I111 丁 顺带改的那句「内存映射」措辞）。
> **没有新界面**（S7 只改了成本文案与状态页两条重查路线，逐屏线框回环节不触发）。
> `.md` 侧最紧的仍是 `CHANGELOG-ARCHIVE 1,064（余 136）`；本册 734（余 466）、CHANGELOG 1,000（余 200）。
> **块数口径**：本册从 **11 块**（§4.26…§4.36）加本轮 = **12 块**。

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
