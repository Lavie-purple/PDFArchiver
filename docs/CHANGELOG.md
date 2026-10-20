# 变更日志

按阶段记录。版本号口径：阶段 0–7 全部走完并通过发布门禁才叫 `1.0.0`；在此之前一律 `0.x.y`，
且 `x` = **已完成的最大阶段号**（允许跳号：没做的阶段在条目里点名，不许让人以为 0–x 全通过）。
**本文件只记实际做过并验证过的变更**，未落地的写在 `ROADMAP.md`，不写在这里。

---

## 勾选轮（十六）—— 2026-10-20 ~ 2026-10-21 · **不升版本号**，把真根一致性从 3 红推到 **19/19 全绿**，并用一条命令跑完整链

轮十五收尾后台账 OPEN 只剩 **I97**（真根 C0 / C3·D / C5 三条红）。本轮按「做未完成的，跟进你推荐的」
依次做掉五件事：**I97 乙**（用产品迁移器升真库）、**C3·D 补索引**、**C5 清空正文**、**I98 乙**（C11
只体检最新快照）、**I99**（G20 首启竞态）；随后第一次把**真机写路径**与**整链**两件证据同时拿到。

- **A · I97 乙 · 真库迁移 0008（2026-10-20 12:21）** —— 用产品自己的迁移器把真库 v7 → v8，
  `version_before = 7｜version_after = [(8,)]`，新增 `ix_documents_name_ci`；迁移前经
  `Connection.backup()` 留快照 `pre-migration-0008-20261020T122144.db`（**11,967,422,464 B**，与源库同字节）；
  重跑同一迁移器 `did_anything=False applied=[] 0.018s`（幂等）。证据 `.probe_work/i97_migrate.log`。
- **B · I97 乙 · C3·D 两批共补索引 10 份（15:00 / 次日 02:15–02:24）** —— 全部走**产品路径**
  （扫描 → 解析 → 正文），不手写 `documents`：doc **10981–10985**（448/432 页等）与
  **10986–10990**（33 / 352 / 458 / 342 / 407 页）。**C5** 的 1 行空正文来自一份 20 页扫描件
  （`parse=ok text=none ocr=pending fts=done`），删其 1 行 `text_pages` 后重索引为 20 页。
  收尾现数：`documents 10,987｜text_pages 1,975,216｜empty_bodies 0｜jobs_pending 0`
  （`.probe_work/i97_fix_roots_1456.log` / `i97_fix_roots2.log`）。真库累计 10,977 → 10,987。
- **C · I98 乙 · C11 只体检最新快照** —— 旧口径对主库 + 0007 + 0008 三份 12GB 级库各跑一次
  `integrity_check`（单份约 44 分钟），真根 p12 被抬到 **8,730s**；改成「最新一份整库体检、
  其余 7 份开库读版本」，并把「旧快照内部损坏不在本口径内」逐字印成边界行。注入 **21/21 + 边界 1/1**。
  读数：r16 **5,502.8s** / r16c **2,323.3s**（同代码，差 2.37 倍，原因未查明，按慢的预告）。
- **D · 真根 p12 首次全绿（2026-10-21）** —— `.probe_work/p12_real_root.json` **19 条 `ok:true`、
  `unverified:false`**：C0 v8 + 8 个迁移、C1 `integrity_check=ok`、C2 主记录 10,987 两项一致、
  C3 六根 68/89/1967/5352/1655/1856 各相等且已标缺失 0、C4 正文与花名册各 1,975,216、C5 六项自洽、
  C6 全合法、C7/C8/C9/C12 干净、C10 分类 14、C13 六根 `root_key == identity_key`、C11 最新快照 ok。
  **I97 / I98 同时 CLOSED**；门禁那一行的 700 字截断另行定位（任务 #168），读数本身没红。
- **E · I99 · G20 首启竞态** —— `packaging/frozen_smoke.py` 原来 `time.sleep(6.0)` 后直接发 WM_CLOSE，
  机器慢时窗口还没 ready 就被关掉：坏法真注入 `退出码 1｜优雅关闭=False（30.42s）｜等窗口 0.2s
  （window.ready 未到）｜峰值 RSS 2.1MiB｜句柄 3｜线程 1`（`.probe_work/g20_inject_red_r16.log`）。
  改成 `wait_for_window_ready()` 等 `state.log` 的 `window.ready`（上限 `FIRST_READY_TIMEOUT = 60.0`），
  复跑 `退出码 0｜优雅关闭=True（0.71s）｜等窗口 8.95s（window.ready 到）｜峰值 RSS 136.0MiB`
  （`.probe_work/g20_green_r16.log`），整链内同一行 **0.27s / 4.44s**。
- **F · 真机写路径 27/27** —— `QT_QPA_PLATFORM` 未设（`platform: windows`）跑六屏截图 1280×800：
  `27 checks, 0 fail`，`verdict: ALL GREEN`，含并入对话框 3 份、导出 4 行 5 列 CSV、OCR 面板
  「点名 2 份｜该跑 1 份」、归档 3 项、撤销批次 #2；工作目录 `work_dir_removed: true`
  （`.probe_work/real_ui_1020/report.json`）。这是轮十五欠的「真机手点证据」的自动版本。
- **G · 整链一条命令 ALL GREEN（2026-10-21 02:59:47 → 04:06:53）** —— `--all --data-root` 12 段
  **4,023.1s**，`合计判定 34 条｜本次未跑 0 段`，末行 `VERDICT: ALL GREEN`；起跑
  **CPU 43.6%｜可用内存 7,071MiB**。回归 **782 passed / 1 skipped（236.8s）**；injection 九份 **793.9s**；
  package **238.1s、400.0MiB、273/273**；G2 **P95 299.0ms**（同日前两场 652.0 / 1,055.0ms，
  三条必须一起引，**ISSUES I25**）；soak S6 排空仍 **0.0s**（I32 维持 MITIGATED）。
  证据 `.probe_work/final_chain_r16c.log`。
- **H · 收尾与口径同步** —— 两场未计入的尝试如实留档：r16（7,652.3s、3 红：p12 旧口径 /
  G20 / G2 负载）与 r16b（CPU 99.8% 下 G1 假红、e2e 后中止）。代码侧把三处标签改成实现现数：
  `gates/final.py` p22 **33 条**、`--list` 耗时补 2026-10-21 整链读数、`--all` 帮助 23 → **67 分钟**；
  `tests/probes/p13_soak.py` S9 **14 条**；`p12_consistency.py` docstring **十四条**。
  台账现读 **99 行｜CLOSED 77｜MITIGATED 21｜OPEN 0｜WONTFIX 1**。逐字读数见
  `docs/VERIFICATION-RUNLOGS.md` §4.26。

**本轮仍欠**：① 安装包与代码签名未交付（用户输入依赖）；② 隐私问题按用户口径「以后再处理」；
③ 真机证据是自动断言 27 条 + 六张截图，仍不是人眼逐屏核对（**ISSUES I17** 的残余）；
④ 长跑仍是 4 分钟 / S6 排空 0.0s（**ISSUES I32** MITIGATED）；⑤ C11 旧快照只开库读版本，
其内部损坏不在口径内（边界已明写）；⑥ 真根一致性 5,502.8s 与 2,323.3s 的 2.37 倍分散未查明；
⑦ **下一步轮十七**：版本升 `1.0.0` 并重打包（用户已勾选，等本轮推完再做）。

---

## 勾选轮（十五）—— 2026-10-20 · **不升版本号**，按「都跟进你的推荐来执行」把轮十四留下的五条一次做完：I96 甲 / `merge_tags` 入口 /「已归档」口径 / 线框措辞 / I95 乙

轮十四收尾时台账 OPEN 只剩 **I95**（真库三条手写演示数据）与 **I96**（`library_page.py` 只剩 5 行），
另有四条编号项等勾选。用户一句「都跟进你的推荐来执行」把五条一并授权；本轮按推荐各做一个独立提交
（A–E），再补收尾（F）：p24 进常驻段、**空载** injection 读数、全量回归与文档落账。

- **A · I96 甲（`855653f`，01:44:48）** —— S1 右栏整段（命中面板 + 文档详情 + AI 推荐分类）搬进
  `src/pdfarchiver/ui/library_hits.py`（**248** 行），用 mixin 混进 `LibraryPage`；控件仍挂在
  `page.right_panel` / `page.hit_list` 上，测试的访问路径一条没改。`library_page.py` **795 → 592 行**。
  长度守卫补第四档 `TIGHT_LIMITS`：判据读**真文件现数**，越过给拆过的文件单独钉的 700 就红 ——
  I96 记的正是「临近只打印、越线才红」那一路。六档坏法实测（701 红 / 正好 700 绿 / 撤自线后 701
  放行 / 名单里放不存在文件必红），全量回归 **760 passed / 1 skipped**，收线 node id 消失 0 条。
- **B · `merge_tags`（`ad0404f`，02:18:15）** —— S8 中栏「并入…」补上 I78 甲最后一格。先挖出的是
  一处**真 bug**：修前 `merge_tags(a, a)` 会把该标签的全部文档关联连同 tags 行一起删光。三条前置
  检查（源不存在 / 目标不存在 / 并给自己）落在仓储层，返回值改成源名下的文档份数、界面只转述
  （**D-043** / **ISSUES I60** 同源纪律）。断言 `tests/integration/test_tag_merge_ui.py` **16** 条；
  新探针 `tests/probes/p24_tag_merge_injection.py` **17 条抓到 17/17**。全量回归 **776 passed / 1 skipped**。
- **C · 「已归档」（`97a57b3`，04:33:17）** —— I78 残留②：仓储层 `last_archive_destinations()`
  一批一条 SQL，按 `max(id)` 取每份文档最后一笔 `state='done'` 且批次 `kind='archive'` 的落点；
  服务层 `is_archived(path_key, dst)` 用 `identity_key` 归一化做「当前位置 ⇄ 归档落点」；导出列
  **勾了才取**，表头带口径名「已归档（按最后一笔归档落点）」，默认五列不变。断言 **31** 条
  （新增 6），p22 坏法 **33 条抓到 33/33**。全量回归 **782 passed / 1 skipped**（此后 D/E 未加断言）。
- **D · 线框措辞（`1db39d8`，04:34:04）** —— 三处列措辞按实现改回：标题→文件名、大小 (MB)→大小 (字节)、
  文字层→正文覆盖率；硬断言 (d) 的只读指纹从三张表扩到五张（`file_operations` / `operation_items`
  也进）。`docs/UI-WIREFRAMES.md` §S8 定案记录追记本条（I78 残留③）。
- **E · I95 乙（`75947cf`，本轮收尾前）** —— 真库那三条手写演示数据（ids 1–3）先备份后删除。备份走
  `sqlite3.Connection.backup()`（运行中库的唯一合法路径）：`%TEMP%\pdfarchiver-i95-backup\catalog.db`
  **11,967,422,464 B**，判定 `BACKUP GOOD`（九张表逐表行数 = 源库、schema v7、三条演示行都在）。
  删除前再核一遍实时行，单事务删 `documents` 3 行与全部 `doc_id` 子表行（各表残留 **0**），
  `foreign_key_check` **0**、耗时 **198.2s**；现库 `documents` **10,980 → 10,977**、
  `text_pages` 1,972,578 不变。真根 p12 复跑 **19 条 16 绿 3 红**，**C2 / C6 转绿**（`.probe_work/p12_i95_after.log/.json`，2026-10-20）；
  剩的 3 红都不是 I95：**C0**（库 v7 / 迁移目录 v8，`0008_name_ci_index` 未应用）、**C3·D**
  （`D:\` 4 份微信 PDF 未入索引）、**C5**（1 行正文是空串）—— 已另立 **ISSUES I97**，
  推荐先应用迁移 0008。旧预测「只剩 I89 6 条 + I90 1 条 = 7 红」已过期：那两条在轮十二就销账了。
  2026-10-19 那份 11,140 MiB 回退备份原样保留；**ISSUES I64** 的「测试不许按 id 硬编码、
  真库不当夹具」规矩不变。
- **F · 收尾** —— `p24` 进 `--only injection` 常驻段（段内 **九份**探针），锚点守卫现读
  **259 条 / 46 个文件**；空载 injection 段 **788.9s @CPU 26.9%**、`VERDICT: ALL GREEN`
  （九份全绿：p9 69/69、p10 45/45、p16 8 坏法 + 3 对照、p17 3、p18 3、p21 24、p22 25、p23 23、p24 17；
  起跑可用内存 3,186MiB。06:07 那场因**系统休眠 5.5h** 被 p10 的 1800s 上限打断，墙钟作废 ——
  不是产品红，也不是断言没牙）；全量回归 **782 passed / 1 skipped in 213.05s**。台账闭合：**97 行｜CLOSED 74｜MITIGATED 21｜
  OPEN 1｜WONTFIX 1**（I95 / I96 本轮销账；新开 I97 承接真根余下 3 红）。逐字读数见
  `docs/VERIFICATION-RUNLOGS.md` §4.25。

**本轮仍欠**：① 11 段整链仍没有一场跑完过；② 安装包与代码签名未交付；③ 本轮新写的界面写路径
（并入对话框 / 导出列）仍没有真机手点证据，全部是 `QT_QPA_PLATFORM=offscreen` 的几何与行为断言；
④ `tests/integration/test_category_export_ui.py` 现 **791 行**（距 `.py` 红线 800 只剩 **9**），
下一轮第一个动作应先按主题拆它 —— 与 I96 同一条规则，不抬阈值；⑤ **ISSUES I97** 的真根 3 红
一条方案未勾（C0 迁移 / C3·D 补扫 / C5 空串），不自行动用户库。

---

## 界面写路径轮（十四）—— 2026-10-19 ~ 2026-10-20 · **不升版本号**，销账 I67（甲+乙）与 I78（甲+乙+丙）：OCR 批量点名面板 + 四条产品写路径接进界面

上一轮收尾后台账只剩三行需要用户输入：I67、I78、I95。前两条卡在 AGENTS.md 的线框门（新控件不许
未经逐屏确认就写代码），所以本轮第一件事是出**一页黑白线框**（
`docs/wireframes/2026-10-19-round14-i67-i78.html`，每条 2–3 个高差异方案），用户勾
「**I67 甲先乙后 + I78 甲 + 乙 + 丙**」并补一句「均跟进推荐来」，随后五件事各做一个独立提交；
I95 涉及改用户真库，留在账上等当面勾选。

- **A · I67 甲（`ed0bdca`，2026-10-19）** —— OCR 在界面上的第一个触发点：S1 表格底下那颗
  「送去识别」。回执那句逐字是 `OcrRequest.describe()` + `OcrBudget.describe()`，界面不自己数；
  新增 0 条时**染红**（「按了但一条没进队列」必须在屏幕上看得见）。断言
  `tests/integration/test_ocr_entry_ui.py` **10** 条，坏法是 `p9` 的 Case 48/49（各红在对应那条上
  且点名）。`UNWIRED_ACTIONS` 里 OCR 那条随之清空。
- **B · I78 甲（`3089965`）** —— 文档↔分类/标签的写路径：S1 三颗批量按钮（归入分类 / 加标签 /
  移除标签，新文件 `ui/catalog_links.py`）+ `ui/library_rows.py`，一次点击 = 一批文档一次写库；
  顺带把台账证据格里「不能挪父子、不能合并」也接了（S8 左栏右键菜单 → `reparent_category` /
  `merge_categories`，成环那一拒留在仓储层）。断言 `tests/integration/test_catalog_writes_ui.py`
  **19** 条；`p9` 这一轮从 49 条扩到 **69 条、抓到 69/69**；全量回归 **686 passed / 1 skipped**。
  诚实记录一条：其中 `I58` 那条坏法第一次跑是绿的（断言从来没有真的重复插过），
  按「不会变红的断言直接删或重写」改的是**断言**而不是判据。
- **C · I78 乙（`e02b925`）** —— 智能集合真的存下筛选条件：S1 顶栏那一排 chips 就是能进
  `query_json` 的那份 dict（`ui/collection_bar.py` + `services/collection_service.py`），
  读写同源、选中即回放、「覆盖此集合」让 `update_query` 有了调用方。断言
  `tests/integration/test_saved_search_ui.py` 23 个函数；新探针 `p21_saved_search_injection.py`
  **24 条抓到 24/24** 并升为 `--only injection` 常驻成员。本轮真正的收获是一条**结构性红**：
  `CollectionRepository.add()` 的 INSERT 漏写 NOT NULL 的 `updated_at`，被第一条测试（存→关→开）
  当场撞红 —— 按「发现一类先问还有哪些同类」没有只补这一处，而是新增守卫
  `tests/guards/test_insert_covers_notnull.py` 全仓扫（现数 91 模块 / 21 条 INSERT / 0 漏）。
- **D · I78 丙（`6107050`）** —— 分类清单导出接进 S8 右键，`services/export_service.py` 是列口径
  唯一出处（每列的值只有一个出处；大小写**原始字节数**而不是 UI 那个显示串）。断言
  `tests/integration/test_category_export_ui.py` **25** 条 + 新探针 `p22_category_export_injection.py`
  **25 条抓到 25/25**；全量回归 **738 passed / 1 skipped**。**「已归档」那一列故意不做** ——
  它没有唯一口径，理由写在模块 docstring 而不是当作遗漏。
- **E · I67 乙（`9fe6fdb`，2026-10-20）** —— 批量点名面板：选中多份时按钮写上份数，按下先
  **就地展开**（不是模态框）把这笔账摆上屏 —— 点名 / 该跑 / 不跑的各是哪几份（**五类**理由各占一行、
  展开到具体份名）/ 这一批要烧多少页（`PAGE_MS_RANGE = (1_985, 5_780)`，两端都上屏）/ 今日预算够不够
  跑完。账由新增的 `plan_ocr(ids)` 算，它和排队列的 `request_ocr(ids)` **共用同一条 `_split()`**
  （预览一行任务也不写）—— 与 S3 归档预览的 `plan()/submit()` 同源同形（**D-043**、**ISSUES I60**）。
  断言 **21** 条（`test_ocr_plan_reads.py` 5 + `test_ocr_batch_panel_ui.py` 16，含 1024 地板档几何
  那条）；新探针 `p23_ocr_batch_injection.py` **23 条抓到 23/23**（单跑 83.4s）入段；
  全量回归 **759 passed / 1 skipped**（E 段当场一场 257.58s 未留日志，故此处引**收尾最终树复跑**那场：
  `240.43s`，逐字见 `.probe_work/full_regression_round14.txt`）。
- **门禁侧的闭合读数**：`--only injection` 段从六份探针涨到**八份**（p21 / p22 / p23 依次入段），
  锚点守卫 `tests/guards/test_probe_anchors.py` 从 138 条 / 34 个文件涨到 **233 条 / 45 个文件**；
  2026-10-20 那场八份同场 **966.3s 全绿**（p9 69/69、p10 45/45、p16 8+3、p17 3、p18 3、p21 24、
  p22 25、p23 23）—— 但**起跑 CPU 54.4%，不是空载场**，与 2026-10-18 的 415.3s 不可互相换算，
  **空载段读数仍欠**（**ISSUES I25**；本轮没有为拿好看数字放宽任何阈值）。
- **本轮新撞到的一条竞态**（记在这里是因为它改变下一轮怎么跑门禁）：`p15 / p16 / p17 / p18` 四份
  探针是把坏法**就地写进真实工作树**再在 `finally` 还原的（只有 p9/p10/p21/p22/p23 走临时副本），
  所以 injection 段在跑的时候并发读文档守卫会拿到注入态 —— 本轮实测出现一次 `PY_STALE_CAP` 假红
  （29 > 28，多出来那一处正是 p16 临时写进本册的那枚假 `.py` 文件名，它的定义在
  `tests/probes/p16_doc_pointers_injection.py`，段一结束自己回 28 / ALL GREEN。本轮收尾复跑时这句
  引号里的假名又把自己数成了一处，改成指真文件才不与上限打架 —— **上限没动过**）。
  **规则**：段在跑时不碰 `docs/` 与 `src/`，也不并发跑任何读文档的守卫。
- **台账闭合（2026-10-20 收尾现读，门禁 `ledger_check` 口径）**：全册 **96 行｜I1–I96 连续｜
  CLOSED 72｜MITIGATED 21｜OPEN 2｜WONTFIX 1**，格子结构与表头一致（唯一那行 3 格的 **ISSUES I35**
  在既有上限内）。本轮销掉 **ISSUES I67**（甲 2026-10-19 / 乙 2026-10-20，三条销账判定逐条对上）与
  **ISSUES I78**（甲/乙/丙 全落）；收尾时新开一条 **ISSUES I96** —— 本轮五段接线把
  `library_page.py` 从 686 行写到 **795 行（距 `.py` 红线 800 只剩 5 行）**，而长度守卫对"临近"
  只点名不判红（那条 pytest 喂的是合成分布），所以这道违约风险在门禁里是隐形的。**OPEN 剩两条 =
  I95**（用户真库里那三条手写演示数据）+ **I96**。
- **仍欠的用户输入**（编号清单已给，等勾选，本轮不做）：**甲** `merge_tags` 要不要给界面入口；
  **乙** 导出列措辞改不改回线框（「大小 (字节)」↔「大小 (MB)」、「正文覆盖率」↔「文字层」、
  名称列取文件名还是标题）；**丙**「已归档」那一列要不要先立唯一口径再进导出；
  **丁** = I95 那三条演示数据（行内已有甲/乙/丙三案，推荐 乙，**动手前必须先备份**）；
  **戊** = I96 那 5 行余量（甲 按主题拆 / 乙 只拆测试 / 丙 写下轮第一个动作 / 丁 抬红线=明确不要，
  推荐 甲）。

---

## 守卫在场性轮（十三）—— 2026-10-19 · **不升版本号**，销账 I94 甲：架构守卫里那两行"永远满足"的空规则

上一轮收尾时用户说「处理遗留问题」，本轮做 I94 甲（其它 I67/I78/I95 需要线框或改用户真库，
等勾选，不在本轮）。

- **I94 甲 · 架构守卫方向表键的在场性**：`tests/guards/test_architecture.py` 的 `FORBIDDEN_IMPORTS`
  里 `fileops`/`backup` 那两行键被删 —— 那两个目录在 `src/pdfarchiver/` 下各只有一个 `.gitkeep`、
  没有任何 `.py`，`PKG.rglob("*.py")` 一个都扫不出来 ⇒ **两行恒真**；`ui` 与 `db` 禁列里的
  `pdfarchiver.fileops` 与 `pdfarchiver.backup` 一并清掉（"不许 import 一个不存在的包"不是保护，
  是空转）。守卫新增第 8 条 `check_direction_keys_reach_files`：方向表每个键必须在
  `src/pdfarchiver/<key>/` 下至少扫到一个 `.py` 文件，且单独点名 `test_方向表每个键至少扫到一个文件`。
  **坏法真注入过**：`p9_reverse_injection.py` Case 47 临时加 `"madeup_layer": ("pdfarchiver.ui",)`
  假键，要求精确点名 —— 本机现跑一次：注入后 `test_方向表每个键至少扫到一个文件` FAILED，
  报「FORBIDDEN_IMPORTS 里的键 `madeup_layer` 在 `src/pdfarchiver/madeup_layer/` 下扫不到任何
  `.py` 文件」；字节还原后 `3 passed`。归档/备份链路的实际方向约束由 `services` 那一行管辖，
  今天的 `archive_service.py` 若真出现 `import pdfarchiver.ui` 仍会被抓住。
  `docs/ARCHITECTURE.md` §二 与图同步（"任何层 import `fileops.execute`" 那句删掉，
  图里的 `{fs, parsing, indexing, search, ocr, semantic, fileops, backup}` 收成不含空目录的
  `{fs, parsing, indexing, search, ocr, semantic, jobs}`）。
- 顺带一条同类清扫：全仓 `DeprecationWarning: invalid escape sequence` 由 **4 处** 一次改光 ——
  `services/vector_service.py:25` `%LOCALAPPDATA%\PdfArchiver\models`（`'\P'`，上一轮 commit 842dff4 引入）、
  `scripts/real_corpus_first_scan.py:1` 模块 docstring `<数据根>\logs\first_scan_report.json`（`'\l'`）、
  `tests/probes/p7_path_identity.py:1` 模块 docstring `\\?\ 前缀`（`'\ '`）与
  `tests/probes/p7_path_identity.py:314` 判据标签 `\\?\ 前缀`（`'\ '`，改成 `\\?\\ ` 保持渲染一致）。
  前 3 处把 docstring 加 `r"""` 前缀变 raw string；第 4 处（判据字符串，会被写进 JSON 报告）
  用双反斜杠 `\\` 替换 `\ `，可读文本完全不变。
  触发本轮的是 **AGENTS.md「禁止同类问题逐个打补丁 —— 发现一类先问『还有哪些地方是同类』，一次性声明规则」**
  —— 我跑 I94 断言时只看到 `'\P'`，若不查同类就只改一处，正是要禁止的逐个打补丁。
  全仓 `compileall src tests scripts` 现回 `0 invalid escape warnings remain`；
  Python 3.13+ 会把这类升成 SyntaxError，本轮相当于提前摘掉三颗雷。

---

## 向量写路径轮（十二）—— 2026-10-19 · **不升版本号**，交 D3（I63 丙+丁）与 D4（I80 丙）：语义向量写路径接进产品

按用户「均跟进推荐来」把台账 I74–I93 那批编号方案的推荐项逐条落地。本节记 D3/D4 两件（其余 轮十二 项在台账逐条销账，收尾时并入）。

- **I63 丙+丁 · 语义向量写路径接进产品**（**D-061**）：新增 `services/vector_service.py`（与 `ocr_service.py`
  同形状），`request_vectors(doc_ids)` 是"用户点名建向量"的唯一入口，沿用 OCR 阶段 5 Q3=甲 的显式点名口径、
  不做全库自动（一条 embedding 任务对 946 页文件就是 946 次前向，按 D-006 不自动跑）。它给
  `VectorStore.add_batch/delete_by_doc` 补上产品调用方、经新增的 `documents.set_vector_status/invalidate_vector`
  把 `vector_status` 从 `na` 推到 `done/failed/stale`、`bootstrap` handlers 接上 `"vector": self.vector.handle`
  且真能经 `jobs.enqueue_many("vector", …)` 入队被 worker 调度。模型没装写 `failed`+原文绝不伪装 `done`；
  没可搜正文入场即拒、状态不动；空页跳过；逐页 `monitor.cancelled()` 可取消、中途停留 `stale`。
  **新测试** `tests/integration/test_vector_write_path.py` **7 passed**。**六条坏法真注入过**（A 不筛空页 /
  B 摘 `delete_by_doc` / C 伪装成功 / D 放开正文门禁 / E `_why_skipped` 不判正文 / F 摘 vector handler，逐条对应
  一条测试变红、字节还原后 7 passed）—— 其中**注入 B 证伪出一条假守卫**：原「重嵌不翻倍」删掉 `delete_by_doc`
  仍绿（`add_batch` 按 `(doc_id,page_no)` 去重本就不翻倍），改成「页变少留孤儿」场景后重注入才真变红。
  `p10` 反向注入探针 cases #26/#28 的锚点因这行 handler 字典变化而过期，re-point 到新行（保留 vector 段），
  复跑 **45/45 ALL GREEN**。全量回归 `649 passed / 1 skipped`。残留：服务层写路径在场，但 `ui/` 下还没有
  "建向量"入口，只走 GUI 时 `vector_status` 仍停在 `na` 直到该入口落地或手工 enqueue —— 该入口按 AGENTS.md
  要先过线框，另挂待确认项，不属本条范围。
- **I80 丙 · 备份包含 settings.json + 恢复前 integrity_check**：`BackupService.create_backup()` 从
  单个 `.db` 改成 `<时间戳>-v<版本>/` 目录（`catalog.db` + `settings.json` 若在场），`list_backups()` 认新目录格式
  与旧单文件两路，`restore_to_new_dir()` 恢复后跑一次 `PRAGMA integrity_check` 并在坏库时拒绝（Windows 文件锁
  下清尸是尽力而为）。新 `tests/integration/test_backup_i80.py` **4 passed**，与既有 e2e 3 条合 **7 passed**。
  残留：清单文件（manifest）未加入 —— 消费者不存在，属 YAGNI，等跨版本迁移校验需要时再补。
- **I89 丙（真库数据，备份在先）+ I90 乙（真库重写，同一份备份之后）**：详见台账 I89 / I90 的已销账格。
  备份用 `Connection.backup()` 走 WAL 唯一合法路径，56.7s 完成 11,957,972,992 字节快照，逐表行数对账 15 表 +
  影子表 `content_fts_docsize` 全等（不跑 `integrity_check` —— `engine.py` 记的 19h+ 天花板，11GB 不可行，
  以行数替代）。I89 那 6 行 `UPDATE monitored_roots SET root_key=identity_key(root_key) WHERE id=?`，键打在
  rowid 别名上避开 `ux_roots_key` NOCASE 唯一索引的过渡态碰撞；I90 那 1,310 行走单个事务、逐行
  `normalize_page_text(body)` 重算 `char_count=len(body)`，靠 `0002_text_and_fts.py:68` 的 `tx_pages_au`
  触发器同步倒排，不手碰 `content_fts`。只读复测（`mode=ro`）：C13 干净、按根前缀 `like_prefix(root_key)` 命中
  从**全 0** 变 68｜79｜1967｜5352｜1655｜1856（子树文档合计 10,977，主记录 10,980），NUL 剩 0、
  `text_pages == content_fts_docsize == 1,972,578`，产品 `match_expression('及数据')` 反查 1,455 命中且被抽的
  rowid 确在其中 —— 1,310 次 UPDATE 真同步进了 trigram 索引。**备份保留未删**（`…\AppData\Local\Temp\`
  `pdfarchiver-i89i90-backup\catalog.db`），是这两场真库改动的唯一回退路径。
- **I5 / I16 · 长压测真机 L4 复跑**：p20 `--only delete` **6 条全绿**（`.probe_work/p20_delete_only2.log`，
  实测 4s 事件路发现、原路径消失=True、10/10 标缺失、库里 `last_scan_error` 有 `FileNotFoundError: [WinError 3]`
  原文落点）、p19 整场 **8 条全绿**（`.probe_work/p19_real.log` + `.probe_work/p19_combined_memory_result.json`，
  组合峰值 C 386.5MiB、单点 OCR 对照 D 359.4MiB，判定档 1,200MiB 余量 +813.5、宽松档 1,228.8MiB 余量 +842.3，
  m4 分层归因 +27.1MiB，m6 起跑/收摊可用 3717/3648MiB 上屏，m5 核 D 进程未加载 Qt）。rename 那一场是
  **2026-10-18** I92 乙 落地的读数（`.probe_work/p20_real.log` n5 实测 1,799s ≤ 1,810s 慢路对得上反算，
  n4 全部 10/10 标缺失），I93 甲 拆的 G12①／②两条口径各带实测数一起写进 `docs/TESTING.md` 与
  `docs/ROADMAP.md`。**I5 / I16 一起 CLOSED**。复跑过程中改出一条探针侧的门：p20 起点新增
  `open_index_or_ocr_jobs()` 判 `pending/running` 的 index/ocr 归零才动手 —— 本场首次 rerun 撞了
  `shutil.rmtree(corpus)` 卡 WinError 32 partial-delete 只 6/10，加上等位门后 n1 转绿且延迟读数可采信
  （p20 `--inject` 复跑 **12/12 坏法｜8/8 好读数**，判据自身未变）。
- **台账闭合状态（2026-10-19 收尾时）**：I74–I93 二十条中 **15 条 CLOSED**（I74/I75/I76/I78 未列 I78 是
  新开的 4 项功能等勾选，暂不 CLOSED；I82/I83/I85/I86/I87/I88/I89/I90/I91/I92/I93 全部 CLOSED 或已销账），
  **2 条 MITIGATED**（I77 乙未做、I81 乙未做，各自另立线框门），**1 条 OPEN**（I78 阶段 3 四项能力等勾选，
  与 A5 线框轮同期）。本轮另开两条新账 **I94**（架构守卫两行方向规则扫空目录恒真）与 **I95**（真库里
  ids 1/2/3 三条手写演示数据），都按 AGENTS「不代勾选」等用户。

---

## 真根读数轮（十一）—— 2026-10-18 · **不升版本号**，I86 切册 + I81/I84 甲销账 + 真根三场读数，新账 I87–I93

这一轮按用户「按照推荐顺序进行执行」那条，交掉上一轮欠的四件：**I86**（长度线）、**I81 甲**（备份恢复端到端）、
**I84 甲**（阶段 6 文案与容错）、**B**（真机与整链证据）。真根现场照出来的缺陷**入账而不顺手修** ——
**I89** 那一条要改用户真库里的 6 行，本场只做 `mode=ro` 只读实测，**一行数据没碰**。

- **I86 甲+乙 · 切册**：`docs/CHANGELOG-ARCHIVE.md` **1,064 行 / 14 个 `## ` 小节**、`docs/DECISIONS-ARCHIVE.md`
  **577 行 / 38 条（`D-001`–`D-038`）**，活册收成 **132 / 618 行**；口径与新重切线（活册 >600 / >900 才再切，不许一轮一切）
  记在 **D-059**。写盘前 `.probe_work/i86_split.py` 三重校验（标题数守恒 + 行切片首尾逐字闭合 + 边界编号双查），任一不符就拒绝。
- **I86 乙 · 守卫从「只拦已越线」加到「临近也点名」**：`tests/guards/test_file_size.py` 第三档 `WARN_REMAINING = 100`
  （**[约定]** = 一轮整改的写入量）+ `test_临近线的那份必须被点名`（合成读数：余 50 必点名、余 150 必不点名）
  + `test_读数打在真东西上而不是空集合`（现数 ≥60 份，防扫空集合假绿）；`test_doc_pointers.py::_decision_files()` 改认
  `docs/DECISIONS*.md` 并新增 `test_分册里的编号仍然算在场`。**坏法真注入过**：把 `_decision_files()` 改回只认活册 →
  `2 failed, 4 passed in 32.70s`，红的正是那两条（逐字点名 `docs/VERIFICATION.md:783/793/797/802/803` 引用的
  `D-031/D-028/D-018/D-033/D-020`「而 `docs/DECISIONS*.md`（活册 + 分册）里没有这条编号」+「决策定义处只有 1 份」），
  字节还原后 `6 passed`（`.probe_work/i86_badway_docpointers.txt`）。
- **I81 甲 · 备份→恢复→开库端到端**（新 `tests/integration/test_backup_restore_e2e.py`，**3 passed**）：逐表行数对账 +
  恢复后 FTS 真搜得回那句独有句子 + 已存在目标拒绝覆盖（`FileExistsError`、原字节不变、不留 `-wal`）。
  **这条测试先抓到我自己的一个瞎口径**：初稿用 `count(*) FROM content_fts` 数倒排，注入坏法②（把倒排 `delete-all` 清空）后
  它**照样报 2**，而同库 `MATCH` 已经搜成 0 条 —— 外部内容表的 `count(*)` 读的是内容表，与 **ISSUES I8** 同一个理由；
  改成影子表 `content_fts_docsize` 之后那条坏法才变红。三档坏法逐字在 `.probe_work/i81_badway.txt`
  （①`{'document_tags': (2, 0)}` ②`{'fts_docsize': (2, 0)}` + `搜成 0 条（应为 1）：[]` ③`DID NOT RAISE FileExistsError`），
  每档结束 `文件已还原 = True`。**残留**：`rebuild_fts()` 在 `src/` 下仍零调用点 ⇒ I81 记 MITIGATED 不记 CLOSED。
- **I84 甲 · 阶段 6 那两处入口的话改到与后端同源**（`library_page.py` **34 插入 / 7 删除**，零新控件、零布局改动，不碰线框门）：
  tooltip 从「基于**文档内容**…」改成「按文件名与所在目录名推荐分类（不读文档正文）」（与 `classify_service.py:131-136` 逐字同源）；
  空态那句去掉指向不存在动作的「请先执行语义索引」，并把这句话扫成**全 `src/` 零出现**的断言而不只查那一屏；
  `_do_semantic_search` 补 `except Exception` 走与 AI 分类同一个红字口径，并新增 `_set_status()` 作状态栏**唯一**染色出口
  （原先四处各自 `setText`、谁都不管颜色 = 同一概念第四个口径）。新测试 `tests/integration/test_stage6_copy.py`
  **5 passed in 1.03s**，含一条负对照（失败紧接着成功，那行必须退回 `muted`，防"一次失败变常驻"）；
  **五档坏法全红且逐条点名**（`.probe_work/i84_badway.txt`），其中③那档把 `except Exception` 换成 `except KeyboardInterrupt`
  后，报错原文 `FileNotFoundError: 语义模型不存在：（本场假路径）bge-small-zh-v1.5/onnx/model_int8.onnx` 穿出 Qt 槽。
  **I84 乙（模型缺席时把勾选框置灰）是新交互态，仍未过线框门，一行代码没写。**
- **真根三场读数**（**B1**，11 段链吃不到单命令 600s 上限 ⇒ 分段；`.probe_work/serial_run_status.json`）：
  p12 带 `--data-root` 跑真根 **3,661.7s**、`合计 18 条｜红 9 条｜未验 0 条`、`VERDICT: RED（9 条未过）`；
  p19（组合内存）**36.3s**；p20（根自愈）**1,809.6s**、`合计 12 条｜红 3 条`（n2 一条 + n6 两条）。
- **p19 复跑那次读数值得单记**：上一场 m1 那条红已在代码里修好（窗口 D 的读数挪到 m1 判定之前），本场复跑
  `m1 转绿`（`A 108.1MiB｜B 110.7MiB｜C 392.7MiB｜D 357.9MiB` 四路都在场，`.probe_work/p19_real_11.log`），
  而**红转移到 m2** —— `窗口内完成 index +0｜churn 入库 0/12`。成因不是同一个：m2 要的三路增量在出厂默认
  `worker_threads=1` 下**不可能同时在场**（单 worker 被 OCR 占满，index 只能排队），于是这条断言在产品正确时也会红。
  连带一条必须写下来的读数边界：**G8 那个 392.7MiB 实测到的其实是「界面 + OCR」两路同场**，不能读成三路。
- **新入账 7 条（I87–I93），逐条给甲/乙/丙/丁等勾选**：I87 机器状态被抄成常量（甲已做：门禁那行改成现场数 + 只走
  `resolve_data_root`，四处文档落点未同步 ⇒ MITIGATED）；I88 同一个 G2 判定有两个答案（甲+乙已做：脚本末行收回链里那一句，
  `--only g2` 复跑 `VERDICT: ALL GREEN`，另立常驻守卫 `tests/guards/test_gate_verdict_line.py` 扫 21 个自报生死的脚本 ⇒ CLOSED）；
  I89 真库六个监测根的 `root_key` 全是原生 Windows 路径 ⇒ 按现口径 `LIKE` **每行命中 0**，换 `identity_key` 口径命中 **10,977** 条；
  I90 真库 **1,310 行** `char_count` 与 SQL `length(body)` 分家，实测**全部**因正文含 U+0000（`length()` 遇 NUL 即止），
  **没有一行字数写错**；I91 门禁共享超时 1,800s < 真根一致性 3,661.7s ⇒ `consistency` 段在真库上**结构性恒红**；
  I92 两个探针各有一条生产不可达的判据（p19 m1 已修、m2 与 p20 n6 未修）；I93 G12 那条 60s **[约定]** 被实测证伪一半
  （delete **5s** 成立、rename **1,799s** —— 只能等 30 分钟一次的周期校验）。
- **本轮自己踩的（同类，都是"锚点/口径没先核"）**：① `count(*) FROM content_fts` 那个瞎口径（见 I81 那条）是**我自己的注入**照出来的，
  不是 review 照出来的 —— 没有那档坏法，这条测试会一直绿着数一个不反映索引状态的数；② 台账那格我**两次**把 Edit 的
  `old_string` 与 `new_string` 写成同一句（只想改一个状态词），白丢两次调用 —— 改状态格必须带着行首锚点整格替换；
  ③ 注入脚本第一版把三档坏法串在同一场跑，后两档**继承了第一档的红**（读数看着对，其实归因错了），
  改成每档先 `SRC.write_bytes(before)` 还原，才拿到"一档对一条坏法"的唯一对应读数；
  ④ 测试里那条 FTS 查询词我先写了两个字，trigram 分词下**恒 0 命中**（假绿的另一面是假红），改成 ≥3 字；
  ⑤ 一次探针脚本 `SyntaxError: f-string expression part cannot include a backslash`（本场 venv 是 3.11）与
  `UnboundLocalError: lines`（函数里 `lines += [...]` 把模块级列表变成局部）—— 两条都是本仓库的老坑，本轮又各踩一次。
- **没测到的 / 仍欠**：① I89–I93 **一条方案都没勾**，其中 I89 的修复要动用户真库、I90 乙 含一次真库正文重写，**不自行执行**；
  ② `consistency` 段带真根必红（I91），所以 11 段整链到今天**仍没有一场跑完过**；③ I84 乙 / I74 / I75 / I76 / I77 / I79 等
  界面档仍等勾选，A5 OCR 入口仍只有线框；④ `rebuild_fts()` 零调用点、`VectorStore.add*` 零产品调用方（D3）；
  ⑤ 备份仍只含 `catalog.db`，不含 `settings.json`（D4）；⑥ 安装包（.msi/.exe）与代码签名**未交付**，本机无证书。

---

## 交付报告轮（十）—— 2026-10-18 · **不升版本号**，补三份阶段交付报告（3 / 4 / 6）+ 台账 I78–I86

这一轮只做「还差哪些东西才算做完」里的 **D**（阶段交付报告）与 **C** 的边界标注，
**没写一行界面或 schema 代码** —— 新账全部是"入账 + 编号方案等勾选"，一条没动。

- **三份新报告**：`docs/stage-reports/阶段3-交付报告.md`、`阶段4-交付报告.md`、`阶段6-交付报告.md`。
  每份都带 2026-10-18 的门禁现场打印，且每份都明写 **门禁绿 ≠ SPEC 该阶段已达成**，并点名本阶段门禁**判不到**的那几条验收。
- **本场读数**（原始日志在 `.probe_work/`，不入库）：`gates/stage3.py` 7 判定 / `stage4.py` 8 判定 / `stage6.py` 7 判定，
  末行都是 `VERDICT: ALL GREEN`；全量回归 **594 passed, 4 skipped in 134.51s**；打包段 **399.9MiB**、237.1s、`VERDICT: ALL GREEN`。
- **新入账 9 条（I78–I86）**：阶段 3 四项 SPEC 能力无产品写路径（I78）、四处已接线零断言（I79）、备份不含设置与清单（I80）、
  恢复侧零端到端断言 + `rebuild_fts()` 无人调（I81）、文档模块树 9 个空指（I82）、`test_semantic_search.py` 三条恒 SKIP（I83）、
  阶段 6 两处文案与一条没接住的异常（I84）、嵌入吞吐三套口径（I85）、长度线只拦「已越线」不拦「下一轮必越线」（I86）。逐条给甲/乙/丙/丁，标了哪些**要过线框**。
- **我自己写坏又当场发现的一处**：插台账 I78–I81 时用长行的**前缀**当 Edit 锚点，把 I75 截成了半行。
  结构检查（逐行数 `| ISSUES` 行的闭合）当场抓到，按行边界修回；`git diff --numstat docs/ISSUES.md` = `3 0` —— I75 与 HEAD 逐字相同。
  教训写进了下一轮的做法：长行只做整行前缀定位 + 行内唯一子串替换，绝不用前缀当锚。
- **两处旧说法被现测推翻**：G2「没做成常驻段」（真相是两个口径：`SEGMENTS` 在场、`DEFAULT_ORDER` 不含 ——
  `docs/TESTING.md` 两处当场改，`docs/VERIFICATION.md` 那段带日期的记录只追不改）；
  「全量嵌入吞吐复核 146.9 chunks/s = PASS」引的是 **fp32**，而产品加载 `model_int8.onnx` → 新立 **ISSUES I85**。
- **`docs/stage-reports/最终交付报告.md` 顶部追记**（10-15 那段原文一字未动）：逐条点名被取代的是哪几句，
  并把交付边界复述一遍 —— **安装包（.msi/.exe 安装器）与代码签名 = 未交付**，本机无证书，不许写成已交付。

## 勾选轮（九）—— 2026-10-18 · **不升版本号**，交上一轮欠的第六条：I51 文档库那一列改成一批一批取

上一轮勾的六条里，「**I51 = 本轮做**」是这一轮的全部范围（其余五件已在轮（七）（八）交掉）。
它也是本仓库第一次把**一条规则全站扫一遍**而不是只修报出来的那一屏 —— 扫出来的另外三张表另立 **ISSUES I76**。

- **缺陷的真身不是台账原话写的「一次性构造 8 万个 item」**（`list()` 的 1,000 上限先把它截断了）：
  实测 8,000 份的库里表格里 **1,000 行**、**永远看不见 7,000 份**，而状态栏写「共 1000 份文档」= 把没显示说成不存在；
  ×10 档 8 万份时看不见 **79,000 份**；1,000 行就是 **1,000 条**分类 SQL。
- **改法（D-058）**：批次大小只取服务层 `DEFAULT_PAGE_SIZE`（界面不再定任何数）、排序复用 `SORTS["name"]`
  （改前界面自己 `casefold` 排一遍 = 同一件事第二个口径，已消失）、那行话由 `SearchResult.status_line()` 一处拼、
  分类整批取（一批 **1** 条 SQL）、一次浏览只把全库数**一遍**（`search(known_total=…)` —— `ix_documents_missing`
  是部分索引、数 `IS NULL` 用不上它 ⇒ 每批重数就是每批扫全表 = Θ(行数²)，AGENTS.md「禁止 O(n²)」）。
- **修后实测**：8,000 份档首屏 **0.016s / 50 行 / 批量分类 1 条**，`_load_more()` **159 批 7.949s** 到库尾、
  不重不漏，库尾那行「共 8000 份文档｜表格里 8000 行」；8 万份档首屏 **0.071s**。
- **本轮唯一一条「断言其实没牙」的现场**：M10 只翻 `_browse_active` 仍是 **GREEN** ——
  `_browse_exhausted=True` 独立挡住了 `_load_more()`。改成同时翻两个标志才变红，并另立 **M10b**
  作预期为绿的负对照。13 条坏法全红 + 1 条负对照，末行 `VERDICT: ALL RED AS DESIGNED`。
- **我自己写进去的一个真 bug，是被新测试抓住的**：`_populate_table()` 先 `setRowCount(0)` 再写行 ⇒ 命中表被清空，
  测试报「命中 0 行」；手工点界面不会看见（它只在有查询词那条路上）。
- **两条残留入账而不是藏**：**ISSUES I77**（滚过的行不释放 + `documents` 上没有 name 索引 ⇒ offset 79,950
  一批 **772.9ms**，补索引后 **12.4ms**、写侧 +7.4% —— schema 改动等勾选，推荐 丙 = 甲+乙）与
  **ISSUES I76**（S3/S5/S4 三张表同样静默截断，本轮一处没动）。
- **8 万行一路滚到底那个数是外推，不是实测**：`after_80000.json` 跑了 40 分钟没写完、被我中止，
  改成深度采样（五个 offset 逐档读数）；**122.1s** = 浅处实测每行 1.526ms × 行数，台账里就这么标的。

## 勾选轮（八）—— 2026-10-18 · **不升版本号**，I17 真机首屏核对：第一次有人看见真首屏

上一轮交出去的六条已全部落地（I71 乙切册 / I69 丁先线框 / 探针乙进链 / `save()` 甲明写 /
OCR 入口出线框 / I51 本轮做）。这一轮做 **ISSUES I17**：那条一直挂着「要用户配合截图」的账，
按用户那句话改由我自己开真窗口跑 —— 「I17 真人首屏核对这个其实可以你自己打开的截图的」。

- **一条前提被证伪**：`gates/stage1.py:44-49` 的 `_run()` 给每条子命令注入
  `QT_QPA_PLATFORM=offscreen`，所以此前 18 次冷启动读数量的是一个「没有屏幕的 Qt」。
  真机跑 21 场之后，「offscreen 通常比真机快」这个假设**不成立**：真机稳态 0.781–1.067s
  落在离屏区间 0.344–1.031s 的上半段，同量级。**`G1_COLD_START_MAX = 1.5` 一处没动**。
- **两轮，第一轮 RED 红得对**：第一场 2.778s（今天这台机器第一次读进 Qt 的 DLL），
  且每场 `shutdown_rows=2` —— 我写的 `>= 1` 判据被驱动自己那行满足，等于没牙。
  修成 `== 1` 且 `startup_rows == 1` 之后第二轮 **ALL GREEN**：11 场 `cold=0.800–0.898`、
  11 张图 md5 全不同、`app.log` ERROR 1 条（故意造的截断 PDF，原文进台账）、Traceback 0。
  探针另外三处返工（DWM 可见边框裁剪 / 旧 PNG 会让「图数=场数」假满足 / 语料份数写死）一并记在
  `VERIFICATION-RUNLOGS` 4.22。**2.778s 的归因没证死**（要清系统缓存，本机没那工具），
  按「事实 + 未证归因」记，不写成结论。
- **逐屏核对逮到两条真缺陷，只取数、一行代码没改**（界面改动要过用户的逐屏确认）：
  **ISSUES I74** —— `theme.py` 里 `:disabled` 出现 **0** 次，实测同一按钮可用态与禁用态
  像素直方图**逐格相同**（正向对照证明取色法有效：清空 QSS 时两态确实不同），而 4 个
  不可逆动作的门（确认对话框的确认词 / 执行归档 / 恢复 / 开始判重）全靠禁用态说话；
  **ISSUES I75** —— S7 上半区被 `QSplitter` 按 sizeHint 冻在 36% 窗高，任务/故障读数
  默认看不见（800 高可见 14/48 行；最大化仍是 36%，下半区空着 418px）。
- **真实语料到今天一次都没被真机核对用过**（故意的：一登记 `_start_background()` 就会
  自动续跑它那份积压）。G4／G17／G18／G19 的性能档仍无真机读数，`gates/final.py` 除
  guards／injection／ui-inject 三段外其余 8 段仍未从门禁里跑过。


## 勾选轮（七）—— 2026-10-18 · **不升版本号**，执行上一轮交出去的六条编号方案，第一步是切册

用户指令是「需要你勾选的六条均按照你推荐来」，另加一句「**I17 真人首屏核对这个其实可以你自己打开的截图的**」
—— 于是那条"要外部配合"的真机项改由我开真窗口截图。勾选结果：**I71 = 乙** ·
**I69 丁 = 甲，但先出线框再写码** · **探针常驻 = 乙（p16/p17/p18 进链，p15 单独 `--only`）** ·
**`settings.save()` = 甲（明写）** · **OCR 入口 = 出线框** · **I51 = 本轮做**。

- **I71 乙 · 把「逐轮收尾读数」从 `docs/VERIFICATION.md` 切出来**：动的是 `### 4.17`–`### 4.20` 这四块
  （**345 行**；一整轮的收尾块就是一块），**逐字**搬进新册 `docs/VERIFICATION-RUNLOGS.md` —— 节号序列连续、
  内容一字未改，改的只是"它在哪一份里"。按 `docs/REPO-JOURNAL.md` **R-010** 的口径切在**读数块**这一刀，
  而不是按行数硬砍：这四块的共同职责就是"每轮收尾追加一块"，而留下的那半本才是阶段级读数。
  切完 `docs/VERIFICATION.md` **1,184 → 844 行**（余量 16 → **356**）。配套三件：① 跨文件指针改指新册
  **7 处**（CHANGELOG 4＋DECISIONS 1＋REPO-JOURNAL 1＋ROADMAP 1），另把 **4 处**承前省略文件名的裸引用
  （`现读见 §4.20` 这类）补全成 `docs/…` + `§` 挨着的写法 —— 裸引用正是 `tests/guards/test_doc_pointers.py`
  第 3 档**查不出**的那一类（它只认文件名与 § 挨在一起），这次是把它们改成它能查的形状；
  ② 新册加进该守卫的 `LEDGER_DOCS`（有日期的读数记录：测试名那一档对它不生效，编号与节号两档照查）；
  ③ `docs/README.md` 与 `README.md` 各加一行索引，写明 4.17 起在哪一册。
  复跑读数逐字贴在 `docs/VERIFICATION-RUNLOGS.md` 末尾那条同日追记里，包括**「读数被自己的记录污染」
  第五次落在这条追记自己身上**那笔账。
- **I71 状态 OPEN → MITIGATED（不写 CLOSED）**：`docs/DECISIONS.md` 仍是 **1,101** 行（余量 **99**），
  增速那条账没变（`+165` 那一轮的原因分析在新册 §4.20 ⑥），甲档（三本一起按阶段切）没做。
  DECISIONS 到 ~1,150 行时仍要单独开一轮 —— 它不是收尾读数块，是逐条编号决定，切它要动的指针多一个量级。

### 勾选轮（七）第二步 · 把四份一次性坏法探针请进门禁链（同一天，销账 **ISSUES I72 / I73**）

- **`injection` 段从 2 条判定变 5 条**（p9 + p10 + **p16 + p17 + p18**），p15 单开 `ui-inject` 段；p17/p18 的末行口径由
  `ALL INJECTIONS CAUGHT` 改成门禁只认的 `VERDICT: ALL GREEN`。四份探针的判据统一成一条：**红，且 `FAILED` 行点名到
  该坏法登记的那条测试**（只红不点名 = 崩溃冒充断言，算漏）。
- **常驻链第一次真跑就红**：p10 的 #8／#26／#28 三条锚点已被上一轮改代码顶掉（熔断器往锚点中间插了一行、
  `bootstrap` 的 handler 字典撑成多行），原文 `RuntimeError: 注入锚点命中 0 次（要求恰好 1 次）` 逐字进台账（**I73** CLOSED）。
- **上架秒级预检 `tests/guards/test_probe_anchors.py`**：六份探针表 **133** 条锚点逐条要求在目标文件里**恰好命中 1 次**；
  它自己三条断言各真注入过一次（含「某份表被清空必须红」，防的就是守卫静默变永真）。同族规则：**新探针上架必须把表接进 `anchors()`**。
- **时长从估算换成实测**：`injection` **332s**、`ui-inject` **70s** —— 此前引用的「光 p15 约 4 分钟」「~338s／~248s」全是我拍的数，
  而那条估算正是"要不要常驻"的决策依据；`--all` 标称由约 21 分钟改约 23 分钟。
- **p10 行尾归一**：288 处 CR CR LF（**已在 HEAD 里**）→ 全文 CRLF；那种行尾被 `test_file_size.py` 的 `splitlines()` 数成 577 行（真实 289）。
- **I72 落笔**：`docs/USAGE.md` §三 两条 + `docs/BACKUP-RESTORE.md` §七 一条 —— 九键只读、`config/settings.py:106 save()` 产品侧零调用点、
  两个「设置」不是一个东西。**界面改键**那一档留在 W-OCR 那轮，本轮不偷偷加入口。
- **两屏线框已出，未写一行界面代码**（AGENTS.md 的线框门）：`docs/UI-WIREFRAMES.md` §W-OCR 与 §W-CONFLICT，各 2 案 + 各 3 条待勾事项。
- 读数：`pytest tests` **577 passed / 4 skipped in 130.19s**（+3 精确对上守卫那三条）｜`tests/guards` **30 passed in 29.18s**｜
  `--only guards` 8 条全绿｜台账 **73 行｜CLOSED 48｜MITIGATED 19｜OPEN 5｜WONTFIX 1**｜`--only injection` 与 `--only ui-inject` 各
  `VERDICT: ALL GREEN`。逐字在 `docs/VERIFICATION-RUNLOGS.md` §4.21。

---

## 分册：更早的轮次在 `CHANGELOG-ARCHIVE.md`

2026-10-18 这一册到线（**1,180 / 红线 1,200**），按 **D-054** 执行切册：勾选轮（六）及更早的
**1,054 行**逐字搬进 [`docs/CHANGELOG-ARCHIVE.md`](CHANGELOG-ARCHIVE.md)，一条没改、一条没删，标题数守恒
（搬前 18 个 `## ` 标题 = 活册 4 + 分册 14）。
口径两册一致：**只记实际做过并验证过的变更**。写新一轮一律追加在本文件，本文件超过 600 行就把最早的一整批轮次整轮迁进分册（**D-059**）。
