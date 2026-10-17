# 实测读数 · 逐轮收尾册（承接 `docs/VERIFICATION.md` §四 的节号序列）

**这一册装什么**：`docs/VERIFICATION.md` §四 里**每一轮收尾都要追加一块**的那批读数（4.17 起）。
**那一份装什么**：环境与依赖版本、探针结论索引、以及只在阶段收尾时才涨的 4.1–4.16。

**为什么切在这一刀**（**ISSUES I71** 勾选**乙**，2026-10-18）：`tests/guards/test_file_size.py` 给台账定的线是
`MD_LIMIT = 1_200` 行，而 `docs/VERIFICATION.md` 收尾复测已到 **1,184** 行（只剩 16 行，连一句追注都装不下）。
增速的实测来源正是这一类块：勾选轮（五）**+75**、勾选轮（六）**+165**（那一条是逐字粘贴门禁与三份探针输出造成的）。
**节号序列与原文连续、内容逐字未动** —— 分册只改「它在哪一份里」，不改「它是第几块」，也不改任何一个数字。

**取数与复跑口径**：见 `docs/VERIFICATION.md` §七（那一份是口径的出处，本册不另立第二份）。

### 4.17 勾选轮（三）收尾读数（2026-10-17，含一条**负载红灯 + A/B 对照**）

**全量回归**：`.venv/Scripts/python.exe -m pytest tests -q -p no:cacheprovider`
→ **`471 passed, 1 failed, 4 skipped in 179.99s`**（上一块记录是 438 passed / 4 skipped；本轮新增
`test_ai_classify_service.py` 5 条，并把 I18 的两条改成断言两参签名 + `crash_log.is_file()`）。
**唯一红灯逐字原文**：

```
tests/integration/test_app_shell.py:183: AssertionError
E   AssertionError: G1 [约定] ≤1.5s，实测 2.457s
E    assert 2.457 <= 1.5
```

**这条 RED 判给了负载（ISSUES I25），而判它之前做了对照、不是直接宣布"环境问题"**：
`.probe_work/g1_ab_probe.py` 在**同一时段交替**跑 `git worktree add --detach` 出来的 HEAD 工作树
（`d573bd3`，本轮改动之前）与当前工作树，各 3 次；读数用应用自己写进 `state.log` 的
`window.ready.cold_start_seconds`（与那条测试同一口径，不是外部掐表）：

```
起跑负载：CPU 98%｜可用内存 2360MiB
HEAD     cold=6.065s / 3.032s / 2.316s   min=2.316  达标=False
工作树   cold=2.946s / 2.774s / 2.284s   min=2.284  达标=False
收口负载：CPU 86%
```

⇒ 两侧同样不达标、HEAD 的 min 还更差 ⇒ **本轮改动不是成因**。该条单跑三次也全红（1.954 / 2.457 / 2.284s），
所以旧说法"并发跑才假红"不完整 —— **变量是负载，不是并发**（同码空载的历史读数是 0.57s）。
**所以今天没有任何一份文档可以写"全量回归全绿"**；G1 要在机器空闲时复跑才算过，本轮没拿到那个读数。

**同轮其余读数**（都是现测）：`test_ui_layout.py` **29** + `test_ui_tier.py` **20** +
`test_error_handling.py` **14** + `test_job_queue.py` **38** + `test_ai_classify_service.py` **5**
= 本轮改过的五份文件合跑 **106 passed in 51.21s**；架构守卫 `test_架构守卫全绿` 在 `app.py` 那句盘符字面量
被改掉后转绿（它就是本轮全量回归里第一次 RED 的那一条，逐字原文记在 `docs/CHANGELOG.md` 勾选轮（三）返工段）；
I65 的机制证明读数 `AssertionError: assert 2 == 1`（要"摘 `q.stop()` + 主动加宽窗口"才出得来，
摘掉照原样跑 8 次全绿）。
**台账现数**：**66 行 = CLOSED 42｜MITIGATED 18｜OPEN 5｜WONTFIX 1**。数法要说明：状态列**不能按竖线切列取第 3 段**
（`ISSUES I42` / `I22` 这类正文里含转义竖线 `\|` 的行会被切偏，我第一次就这么读错过一次，把 OPEN 数成 3），
要用 `re.search(r'\|\s*\*\*(OPEN|MITIGATED|CLOSED|WONTFIX)\*\*\s*\|', 行)` 找状态**记号**。
OPEN 五条 = `I5` `I16` `I17` `I51` `I66`：前三条要真机配合，后两条要先过线框 / 勾选门。

---

### 4.18 勾选轮（四）· A1 监测根登记接线（2026-10-17，销账 **ISSUES I66**、新开 **ISSUES I67**）

**测的是什么**：S7「设置与状态」下半区「监测目录」的「添加目录...」/「移除选中」两颗按钮，
从"只弹一句假文案"改成"真的写库 + 真的挂监听 + 真的撤干净"。落点在服务层
（`services/bootstrap.py:AppContext.register_root` / `unregister_root`），界面只调它 ——
理由与读数记在台账那行里。

**新增测试**：`tests/integration/test_monitor_roots_ui.py` **10 passed in 3.49s**
（offscreen 真窗口 + 真 sqlite，无 mock，D-012；`PYTHONIOENCODING=utf-8 PYTHONUTF8=1`）。
其中 8 条测行为（库里 +1 且 `enabled=1` / 取消选择不动 / 重复登记是重新启用而不是多一行 /
移除只撤监测：`documents` 条数不变 + 磁盘目录 `exists()` 仍为真 / 确认框答否不生效 /
没选中不生效 / `start_background()` 之后 `background_state().watched_roots` 随登记 +1 随移除回落 /
界面不许再出现「只能通过配置文件」那句），另 2 条是**用户文档口径守卫**（见下）。

**坏法注入 14 条，全红且各自点名**（`.probe_work/i66_guard_injection.py`：一次一条字符串替换 →
只跑那一个 nodeid → `finally` 还原；跑法必须带 UTF-8 环境变量，否则会撞 GBK 编码崩在第 ⑪ 条，
`UnicodeEncodeError: 'gbk' codec can't encode character '\u246a'` —— 这台机器的老坑，本轮又踩一次）：

```
①:49 ②:177 ③:188 ④:158 ⑤:137 ⑥:118 ⑦:119 ⑧:120 ⑨:95 ⑩:198 ⑪:66 ⑫:240 ⑬:240 ⑭:265
```

**⑭ 第一次是假绿，这一条最有价值**：文档守卫原本的判据是"这一行里出现否定词就算老实话"，
而它要盯的那行前半句本来就写着「界面上**没有**触发入口」，于是"会**自动排队**"这半句被同行另一件事的
否定词顺手赦免 —— 注入回来照旧绿。判据改成"否定词必须紧贴那四个字（查 `line[at-2:at]`）"之后才红。
⇒ **行级邻接 ≠ 语义邻接**，凡是"这行有没有否定"型的判据都要问一句：否定的是哪半句。

**文档口径守卫的两条**（同类问题一次声明规则，AGENTS.md；这一族的成因见 **ISSUES I57**）：
① `test_用户文档不许把未接线的动作写成界面能做的事` —— 把 `README.md` / `docs/USAGE.md` 的能力表按
`ui/pages/status_page.py:32 UNWIRED_ACTIONS` 逐条对：未接线清单点名的动作所在行，状态列不许打 ✅；
未接线清单新增条目而映射表没跟上 ⇒ 守卫自己先红（否则它会安静地漏掉新条目）。
② `test_文档不许宣称OCR会自动排队` —— **D-028 / ISSUES I1** 的红线「绝不自动触发」。
本轮真从文档里删掉的假话有两句：`README.md` 原「离线 OCR 扫描件 | ✅ 能用」、
`docs/USAGE.md` §一 原「界面 S7 设置 OCR 参数，**自动排队**」，后者连产品形态都说反了
（OCR 必须按 `doc_id` 点名，`request_ocr()` 在产品侧**零调用点**）⇒ 记 **ISSUES I67**。

**同轮文档改动**：`README.md`（能力表两行 + 「怎么开始用」第 3 步）、`docs/USAGE.md`（§一 扫描行与 OCR 行、
§三 S7 行、§四 整节重写：界面按钮在前、命令行作为批量路子保留，那段逐字实测块与 Python 代码原样不动）、
`docs/BACKUP-RESTORE.md`（§五 第 3 步、§七 搬家）、`docs/TROUBLESHOOTING.md`（§三 那行、
问题表把 I66 换成 I67）。⚠️ 这一句原本写的是「§十四 问题表」，而那份文档最大的节号是 §十一 ——
**指针当时就是空的**（与 **ISSUES I34** 同一类毛病：文档里的证据指针从没被机器核对过）；
2026-10-17 归档轮插入新的 §十「跑过归档之后」后问题表顺延为 **§十二**，此处按现号改正。

**全量回归（本轮改动之后）**：`.venv/Scripts/python.exe -m pytest tests -q -p no:cacheprovider`
→ **`482 passed, 4 skipped in 153.99s`**（上一块是 471 passed / 1 failed / 4 skipped，净增 10 条 =
`test_monitor_roots_ui.py`）。**§4.17 那条唯一的红灯 G1 这次是绿的** —— 但**"绿"不等于"空载达标"**：
同一台机器上单独复跑 G1 的那条探针（同一个口径：应用自己写进 `state.log` 的
`window.ready.cold_start_seconds`）读到 **1.987s > 1.5s**，那一刻的负载是 **CPU 72%｜可用内存 1,714MiB｜
最吃内存进程是一个 4.6GiB 的游戏客户端**。⇒ **G1 的成因仍然是负载（ISSUES I25），本轮没有拿到空载读数**，
所以这句只能写成"这次跑绿了"，不能写成"首屏达标了"。回归那一刻的负载没打点（pytest 那条路不打印，
只有 `gates/stage5.py` 的起跑读数会打），这是本轮留下的一个已知缺口，不是遗漏的证据。

**交付文档门禁**：`gates/final.py` 的 `gate_docs()` 五条全 GREEN —— 四份在场
（`INSTALL 10KiB｜USAGE 18KiB｜BACKUP-RESTORE 18KiB｜TROUBLESHOOTING 17KiB`）/ 五分栏报告齐 /
无占位符 / 每份都含「实测」字样 / **台账 67 行、I1–I67 连续、CLOSED 43｜MITIGATED 18｜OPEN 5｜WONTFIX 1**；
`gate_docs_inject()`（"门禁自己有没有牙"）同时 GREEN。守卫目录 `tests/guards` **22 passed in 5.39s**。

**残留（不销账）**：① 没有真桌面人工点过一遍（offscreen 验的是库状态与监听名单，不是选择器在真人
面前的手感）⇒ 挂 **ISSUES I17**；② 台账里原候选「丙：列表补『停用』控件」没做 —— 那是新控件，
受线框确认门约束；③ G1 的空载读数仍未拿到（见上）。

---

### 4.19 勾选轮（五）· A2/A3/A4 归档链路真接上磁盘（2026-10-17，销账 **ISSUES I55 / I68**、新开 **I69 / I70**）

**测的是什么**：S3「执行归档」与 S4「整批撤销」按下之后**真的改动磁盘**，
以及这一轮顺手给"文档里的引用"装上的机器门禁。全部磁盘证据来自临时目录里的真文件
（AGENTS.md 与 **ISSUES I64** 的禁令：真实语料 `documents` 的 ids 1–3 是用户数据，不许当夹具）。

**全量回归（本轮所有改动之后）**：`.venv/Scripts/python.exe -m pytest tests -q -p no:randomly -p no:cacheprovider`
→ **`568 passed, 4 skipped in 131.95s`**。上一块（§4.18）是 `482 passed, 4 skipped in 153.99s`，
**净增 86 条**，逐条对得上（按 `def test_` 现数）：
`test_archive_disk_safety.py` 4 → **41**（+37，G17/G18/G19 与批次↔任务联动都在这份里）、
`test_archive_execute_ui.py` **15**（新）、`test_archive_template.py` **26**（新）、
`test_confirm_control.py` **5**（新）、`test_doc_pointers.py` **4**（新）、
`test_status_readout.py` 9 → **8**（−1，删掉的那条前提本轮翻转了 —— 「按钮还没接线」这件事不再成立，
留痕记在 **ISSUES I70**）。守卫目录单独跑：`tests/guards` **26 passed in 24.48s**。
文档改动之后**又复跑一次全量**：`568 passed, 4 skipped in 125.34s` —— 两次尾行一致，
证明上面那 86 条的增量不是"文档改完才凑绿的"。

**阶段 4 门禁当场复跑（`gates/stage4.py`，八条判定全 PASS，末行 `VERDICT: ALL GREEN`）**：
`G21 依赖守卫 ALL GREEN`｜`架构守卫 ALL GREEN`（依赖方向 / SQL 位置 / 无静默吞异常 / 无本机路径字面量 / 导航分组）｜
`G1 冷启动 0.856s ≤ 1.5s [约定]｜进程总耗时 1.447s｜关窗对账 1 条`｜
`阶段 4 服务模块存在 OK`｜`bootstrap 注册 OK｜archive=True dedup=True backup=True｜archive_kind=True dedup_kind=True`｜
`G2 检索功能正确性 27 passed / 0 failed / 0 error`｜`全量回归 568 passed / 0 failed / 0 error`｜
`反向注入探针 46/46 条坏法被抓到`。
⚠️ 这一场的 G1 是**绿**的，但**负载口径不变**：单次读数不等于空载达标（§4.17／§4.18 那条红灯的成因仍是
**ISSUES I25**），所以这里只写"这次跑绿了"，不写"首屏达标了"。

**坏法注入 · 界面与磁盘链路（`tests/probes/p15_archive_ui_injection.py`，一次性探针本轮转正进仓）**：
**共 36 条坏法：抓住 36、漏网 0、点名存疑 0**。判据是「红 **且** `FAILED` 行点名到该杀的那条测试」，
只红不点名不算数。覆盖 C1–C11（确认控件本体）、A1–A13（S3 四道闸与预览/执行同源）、
O1–O8（S4 撤销）、S1（台账 `undone`）、P1–P3（状态页磁盘口径与未接线栏）。
末五条现读：`O7 拒绝原因被界面重述成一句`、`O8 取消撤销之后照样提交`、`S1 部分撤销也标 undone`、
`P1 磁盘口径写两遍`、`P2 空说明仍然占一行`、`P3 未接线句子改成手抄`。

**这轮抓出一条自己的假绿（本轮最有价值的一条）**：
`test_没看过计划就不许建批次` 原先的判据是"弹窗文本含『生成预览』"，
而「请先点生成预览」与「计划已经变了」**两句都含这四个字** —— 把第一道闸整个删掉照样骗过去；
并且该测试没建目标根，它当时的红其实来自一句不相干的 `ValueError`。
补 `mkdir` + 断言点名"没看过计划"之后，A4 注入才确定性点名第一道闸。
与 **ISSUES I66** 那条「行级邻接 ≠ 语义邻接」同族：**判据能被另一句话满足，它就还不是判据**。

**新增守卫 · 文档里的引用也是断言（`tests/guards/test_doc_pointers.py`，4 条）**：
四类指针机器核对 —— 决策编号、台账行号、`某文档 §n` 节号、**活文档**里引用的 `test_*` 函数名；
只增不改的台账类文档（CHANGELOG / DECISIONS / ISSUES / VERIFICATION / VERIFICATION-RUNLOGS / REPO-JOURNAL / stage-reports）
在第四类上**豁免**（不返工改历史），旧名逐条记在 **ISSUES I70**。
现读（`python tests/guards/test_doc_pointers.py`）：

```
扫了 25 份 md、55 条决策编号、71 条台账编号、537 个测试函数
台账类文档里今天已不存在的测试名（不判红，逐条记在 ISSUES I70）：6 处
  docs/CHANGELOG.md:324 test_progress_state_vocabulary
  docs/CHANGELOG.md:516 test_阶段1刻意不建的表确实不存在
  docs/DECISIONS.md:202 test_阶段1刻意不建的表确实不存在
  docs/DECISIONS.md:722 test_阶段1刻意不建的表确实不存在
  docs/DECISIONS.md:975 test_没接上执行器的按钮不许伪装成功
  docs/ISSUES.md:55   test_阶段1刻意不建的表确实不存在
VERDICT: ALL GREEN
```

**上面这些行号会随台账增长漂移，认名字不认行号** —— 这段是当场输出的逐字粘贴，第二次复跑同一条命令
读到的是同一**六条名字**、不同行号（`CHANGELOG.md` 那两条从 252/444 漂到 324/516，就差 72/76 行）。
**这条读数一度被我自己污染成 8 处**：新写的 CHANGELOG 与 §4.19 各把一条已消失的测试名写进了反引号，
守卫照收（台账类只豁免"判红"、不豁免"计数"）—— 按本轮已有的处置改成「」引用，条数回到 6。
⇒ 记在 **ISSUES I70** 的那 6 处是**历史条目里的真指过期**，任何新写的散文都不该再往这个数上加值。

⚠️ **2026-10-18 追记：上面那段不是逐字，本段这个声明才是。** 真实输出的次序是六条带 `台账旧名  ` 前缀的行
**打在最前**、然后才是 `扫了 …` 与摘要行，且摘要句里的台账编号带星号 —— 上一段把摘要行挪到了前面、去掉了前缀、
也丢了星号，属于**转述**。原文保留不删（改历史条目等于销毁证据），逐字可复算的现读贴在 **§4.20**。
教训与 **ISSUES I70** 同族但方向相反：那次是"引用了不存在的名字"，这次是"引用了不存在的输出" ——
AGENTS.md 要"报错原文完整粘贴、禁止转述"，对本文件自己粘进来的读数同样成立。

**上架当场改掉的活文档坏指针**（每条都可 grep 复验）：
`docs/DATABASE.md` / `docs/TESTING.md` / `docs/UI-WIREFRAMES.md` 引的
「test_阶段1刻意不建的表确实不存在」（迁移 0002 建了 `content_fts` 之后这条测试就不在场了）→
改指 `test_documentation_matches_actual_schema` 并写明原因；
`docs/ARCHITECTURE.md` / `docs/DECISIONS.md` / `docs/OCR.md` / `docs/stage-reports/` 里四个改过名的旧测试名换成现名；
**ISSUES I51** 的虚拟化口径从 **D-017**（那是「阅读器渲染以 PyMuPDF 为主」）改到 **D-040**；
**ISSUES I66 / I57** 里 `TROUBLESHOOTING.md` 的问题表节号按现号 **§十二** 改正。

**这条守卫自己被证伪（`tests/probes/p16_doc_pointers_injection.py`）**：
`基线 4 条全绿` + `共 5 条（4 条坏法 + 1 条反向对照）：抓住 4、漏网 0、点名存疑 0、对照破 0、锚点失配 0`
—— P1–P4 各红且点名到各自那条断言，P5 是**反向对照**（台账里写旧名必须仍绿，证明豁免边界真的在事）。
第一版按引用形状（`D-` 那类前缀）筛问题，注入一条**不存在的编号**就漏过去了，改成按**报错句子里的固定短语**分派。

**台账现数**：`docs/ISSUES.md` **71 行**、I1–I71 连续不重号，
**CLOSED 45｜MITIGATED 17｜OPEN 8｜WONTFIX 1**。OPEN 那 8 条 =
**I5**（改名自愈压测）/ **I16**（组合内存压测）/ **I17**（真桌面首屏）/ **I51**（表格虚拟化）/
**I67**（OCR 界面入口）/ **I69**（确认词那一档今天走不到 + `irreversible` 两个口径）/
**I70**（活文档必须当场可验的规则本身）/ **I71**（三份台账距 1,200 行线的余量只够两轮，
本轮实测 `DECISIONS 1,045｜VERIFICATION 1,019｜CHANGELOG 1,013`，切册是一次独立的文档动作）。

**没测到的（不许混在上面那些绿里）**：
① **真实语料（10,977 份）到今天一次归档都没跑过** —— G4／G17／G18／G19 的**性能与耗时**档位仍无真机读数；
② `DB 事务回滚 ≠ 磁盘回滚` 那条**专门的断言还欠着**（现在只有两条各验一半的：
journal 恢复矩阵 + 跨盘不先删源），`docs/ROADMAP.md` 阶段 4 那张表里这行仍是 ⚠️；
③ 全量哈希 ≤1h 的 **G4** 未测；④ `I5`／`I16`／`I17` 三条要真机配合（§4.18 那个 G1 负载缺口同样还没补上）；
⑤ **I69** 让"输入确认词"那一档在产品里**今天走不到**，两页的「不可逆」还是两个口径。

---

### 4.20 勾选轮（六）· 三条编号方案落地 + 给"台账旧名"装上会红的上限（2026-10-18，销账 **I68 甲 / I70 丙**，**I69** 从 OPEN 降到 MITIGATED）

**测的是什么**：上一轮末尾交出的三条勾选方案 **I68 甲**（队列 handler 形状核对）、**I69 丙**（「不可逆」口径归一）、
**I70 丙**（台账旧名追注 + 写进门禁）三条落地之后，**断言有没有牙**与**行为有没有变**。磁盘证据仍全部来自临时目录里的
真文件（**ISSUES I64**：真实语料 `documents` 的 ids 1–3 是用户数据，不许当夹具）。

**全量回归**：`.venv/Scripts/python.exe -m pytest tests -q -p no:randomly -p no:cacheprovider`
→ **`574 passed, 4 skipped in 131.65s`**。上一块（§4.19）是 `568 passed, 4 skipped`，**净增 6 条**，逐条对得上：
`test_job_queue.py` **+2**（形状不合当场拒 / 真装配的五条都过）、`test_archive_disk_safety.py` **+3**
（`TestIrreversibleSingleSource` 三条：目标位已有文件才算不可逆 / 界面那条数取的是服务的口径 / 落库的可逆标记与界面同一条数）、
`test_doc_pointers.py` **+1**（`test_台账旧名不超过上限`）。6 = 本轮新增断言的全部条数，没有一条是用例改名充数。

**三条落地的口径各自钉在哪**：
- **I68 甲**：核对长在 `WorkQueue.__init__` 的 KINDS 校验之后，不在 `bootstrap` 装配之后 —— 装配点只覆盖产品那一条
  注册路径，**构造点覆盖所有构造点**。判据 `inspect.signature(fn).bind(None, None)` 一条表达式同时拦住"少收一个位置参数"
  "多要一个必需参数""builtin 取不到签名"，报错里点名是哪一种 kind。正面那一半不重抄注册字典：核对在构造点上，
  所以 `test_真装配的五条处理函数过形状核对`（走真 `start_background()`）本身就是"五条都过"的证明。
- **I69 丙**：「不可逆」现在只有 `PlannedMove.irreversible` 一处表达式；S3 界面只数不算（页面里那句 `os.path.exists`
  连同 `import os` 一起清掉），批次落库的 `reversible` 也改写这一条。**今天可达的输入上一字不变**（跳过的项仍 0、
  搬得成的仍 1），改的是"两处各算各的"这件事，不是数出来的值 —— 这也是这轮最值得写下的一条：**口径归一在今天的
  可达输入上是零行为变化的**，所以它必须靠注入而不是靠回归来证明自己有牙。
- **I70 丙**：那 6 处过期测试名就地各追注继任者（台账原文一字未动，只在同一行后面加括号），新增
  `LEDGER_STALE_CAP = 6`，守卫多一条 `test_台账旧名不超过上限`，`gates/final.py` 的 `gate_docs()` 多一行读数 ——
  条数**直接取守卫那份函数与那个常量**，门禁里不重数一遍（`gates/final.py` 的设计约束 1：门禁只做编排，不新增判定口径）。

**坏法注入现读（三份，原样抄，只裁掉每行末尾的耗时 —— 与下面那段"逐字"是两件事，这里明说是摘要）**：

```
===P17===   tests/probes/p17_handler_shape_injection.py
基线绿（注入之前这条断言是真过的）
H1  红（有牙）  bind 只给一个位置参数（少收一个的坏 handler 就放行了）  ::  FAILED tests/integration/test_job_queue.py::test_处理函数形状不合队列契约时装配当场拒绝
H2  红（有牙）  捕获后不上抛，只记日志（永远绿）                        ::  FAILED tests/integration/test_job_queue.py::test_处理函数形状不合队列契约时装配当场拒绝
H3  红（有牙）  核对只盯 archive，其它种类不看                          ::  FAILED tests/integration/test_job_queue.py::test_处理函数形状不合队列契约时装配当场拒绝
VERDICT: ALL INJECTIONS CAUGHT

===P18===   tests/probes/p18_irreversible_source_injection.py
基线绿（三条断言在注入之前是真过的）
S1  红（有牙）  落库字段退回第二条表达式                                点名 [test_落库的可逆标记与界面同一条数]
S2  红（有牙）  界面自己数一遍且判据不同（凡是有目标路径就算）          点名 [test_界面那条数取的是服务的口径, test_落库的可逆标记与界面同一条数]
S3  红（有牙）  服务的定义退化成「能搬 = 不可逆」                        点名 [test_目标位已有文件才算不可逆, test_界面那条数取的是服务的口径, test_落库的可逆标记与界面同一条数]
VERDICT: ALL INJECTIONS CAUGHT

===P16===   tests/probes/p16_doc_pointers_injection.py（本轮从 5 个节点加到 6 个）
基线 5 条全绿
P1   红  引用一条不存在的决策编号  ← test_文档里的决策编号都真实存在
P2   红  引用一条不存在的台账编号  ← test_文档里的台账编号都真实存在
P3   红  引用一个不存在的节号      ← test_文档里的节号指针都落得下去
P4   红  引用一个不存在的测试名    ← test_活文档里引用的测试名都还在场
P5   对照成立  台账类文档里的旧测试名不判红（反向对照）  ← 台账豁免边界在事
P6   红  同一条注入必须顶破台账旧名的上限（**ISSUES I70** 丙）  ← test_台账旧名不超过上限
共 6 条（5 条坏法 + 1 条反向对照）：抓住 5、漏网 0、点名存疑 0、对照破 0、锚点失配 0
```

⚠️ 每行末尾的耗时（`1 failed in 0.32s` 那一类）为了贴齐省略掉，其余字符照原样。
**P6 与 P5 是同一条注入、两种判据**：往台账里塞一个不存在的测试名，P5 必须仍绿（台账不判红）、P6 必须红（顶破上限）。
加了上限之后 P5 的反向对照分支**不能再连着跑 P6 的节点** —— 一条注入同时顶破两条判据时，对照会报成"对照破了"的假红，
所以对照现在只跑被对照的那一条断言。

**文档指针守卫现读**（`.venv/Scripts/python.exe tests/guards/test_doc_pointers.py`，逐字）：

```
台账旧名  docs/CHANGELOG.md:363 test_progress_state_vocabulary
  台账旧名  docs/CHANGELOG.md:556 test_阶段1刻意不建的表确实不存在
  台账旧名  docs/DECISIONS.md:202 test_阶段1刻意不建的表确实不存在
  台账旧名  docs/DECISIONS.md:723 test_阶段1刻意不建的表确实不存在
  台账旧名  docs/DECISIONS.md:977 test_没接上执行器的按钮不许伪装成功
  台账旧名  docs/ISSUES.md:55 test_阶段1刻意不建的表确实不存在
扫了 25 份 md、57 条决策编号、71 条台账编号、543 个测试函数
台账类文档里今天已不存在的测试名（不判红，逐条记在 **ISSUES I70**）：6 处
VERDICT: ALL GREEN
```

**这段才是逐字粘贴**，次序就是真实输出的次序（六条在前、摘要在后、每行带 `台账旧名  ` 前缀、摘要里编号带星号）。
§4.19 里那段自称逐字的其实是转述，已就地声明（**本文件写"逐字"两个字就必须能对上字符** —— 与 **ISSUES I70**
同族但方向相反：那次是引用了不存在的名字，这次是引用了不存在的输出）。行号仍会漂 —— 本轮两次复跑读到的同一对
CHANGELOG 名字从 `324/517` 变成 `363/556`，差 39 行正好是勾选轮（六）那一块的长度；`决策编号` 从 55 涨到 **57**
是本轮新登记的 **D-056／D-057**。**认名字不认行号**。

**台账现数**：`docs/ISSUES.md` **71 行**、I1–I71 连续不重号，
**CLOSED 46｜MITIGATED 18｜OPEN 6｜WONTFIX 1**（上一轮 45／17／8／1）。OPEN 那 6 条：
**I5**／**I16**／**I17** 要真机配合，**I51**／**I67** 要先过线框，**I71** 要勾选。

**文档门禁当场复跑**（`gates/final.py --only guards`，全 32 行输出逐字，无省略）：

```
门禁运行于 H:\AI project\demo19｜python 3.11.7
        起跑负载：CPU 25.7%｜可用内存 2434MiB｜最吃内存进程 Qoder CN.exe 504MiB
        本次跑 1 段：guards
  ── 段 guards（1.3s）
  PASS  G21 依赖守卫
        实测：VERDICT: ALL GREEN
  PASS  架构守卫（依赖方向 / SQL 位置 / 无静默吞异常 / 无本机路径字面量 / 导航分组）
        实测：VERDICT: ALL GREEN
  PASS  交付文档四份在场（安装 / 使用 / 备份恢复 / 故障排查）
        实测：INSTALL.md 10KiB｜USAGE.md 20KiB｜BACKUP-RESTORE.md 18KiB｜TROUBLESHOOTING.md 19KiB
  PASS  最终交付报告五分栏齐全
        实测：报告 28KiB｜缺栏 无
  PASS  交付文档里没有占位符残留（TBD / TODO / 待填 / 省略）
        实测：命中 无
  PASS  每份用户文档都引用了当次实测读数
        实测：没有「实测」字样的 无
  PASS  已知问题台账逐条有状态、编号连续不重号
        实测：71 行｜I1–I71 连续｜CLOSED 46｜MITIGATED 18｜OPEN 6｜WONTFIX 1
  PASS  台账里失效的测试名不超过 6 处（**ISSUES I70** 丙）
        实测：现数 6 处，上限 6
        现场：涨了就说明这一轮留下了新的过期名字：就地追注继任者，别抬上限
  SKIP  未跑的段：regression（全量回归（pytest tests/，条数只认当次输出，不写死））—— 这一场的「全绿」不覆盖它
  SKIP  未跑的段：coldstart（G1 冷启动 + 关窗对账）—— 这一场的「全绿」不覆盖它
  SKIP  未跑的段：e2e（新 · 后台生命周期 + 阶段 2 端到端（真 PDF / 真 worker / 真监听））—— 这一场的「全绿」不覆盖它
  SKIP  未跑的段：injection（p9 + p10 反向注入（断言到底有没有约束力））—— 这一场的「全绿」不覆盖它
  SKIP  未跑的段：ocr（阶段 5 三条：产品路径实测 / 预算真停机 / 真引擎套件不许 skip）—— 这一场的「全绿」不覆盖它
  SKIP  未跑的段：consistency（p12 注入自检 + p14 一致性仪表验牙 + （给了 --data-root 就）核查真实现场）—— 这一场的「全绿」不覆盖它
  SKIP  未跑的段：soak（p13 注入自检 + 真长跑采样）—— 这一场的「全绿」不覆盖它
  SKIP  未跑的段：package（build.py 内容断言 + 冻结产物冒烟全阶段）—— 这一场的「全绿」不覆盖它
  SKIP  未跑的段：g2（G2 搜索 P95 真库实测（绑定真库，默认不进全链））—— 这一场的「全绿」不覆盖它
  合计判定 8 条｜本次未跑 9 段
VERDICT: ALL GREEN
```

⚠️ **这一场只跑了 guards 段**，那 9 个 `SKIP` 是本门禁的规矩（未跑的段必须显式标出来，**ISSUES I36** 的成因就是
"未跑却算 PASS"），所以这行 `ALL GREEN` **不等于**整链绿 —— 整链要 `--all`，而 `--all` 需要真机配合与
`--data-root`（见 `docs/ROADMAP.md` 的交付链段与 **ISSUES I17 / I5 / I16**）。

**没测到的（不许混在上面那些绿里）**：
① **真实语料（10,977 份）到今天一次归档都没跑过**，G4／G17／G18／G19 的性能档仍无真机读数；
② `DB 事务回滚 ≠ 磁盘回滚` 那条**专门的组合场景断言还欠着**（`docs/ROADMAP.md` 阶段 4 表里这行仍是 ⚠️）；
③ **I69 丁 没做** —— 覆盖前先备份目标是一件新的危险操作语义，按 AGENTS.md 要先过线框与文案，
所以「输入确认词」那一档在产品里**今天仍走不到**（这一句现已写进 `README.md` 与 `docs/USAGE.md` §一，不再只写在代码注释里）；
④ **p15／p16／p17／p18 合起来 47 条坏法不在任何门禁链里** —— `gates/stage1.py::gate_injection` 只跑 p9 那 46 条，
这四份要等"哪一轮改了哪块"才由人肉决定复跑。让它们常驻是一次**运行时长预算**的决定（光 p15 一份约 4 分钟），**等勾选**；
⑤ **I5／I16／I17** 三条真机项与 §4.17／§4.18 那个 G1 负载缺口（**ISSUES I25**）都没动 ——
本场起跑负载 `CPU 25.7%｜可用内存 2434MiB`，这个压力下任何"首屏达标"的说法都不该引用；
⑥ **I71 的余量本轮就撞上了**：三本台账**收尾复测**的现数（`splitlines()`＝`wc -l`＝守卫判定那条口径）`DECISIONS 1,101｜VERIFICATION 1,184｜CHANGELOG 1,062`，
离 `MD_LIMIT = 1,200` 剩 **99／16／138** 行 —— 本轮增量是 `+56｜+165｜+49`，比上一轮记的「一轮 +68～+130」还大，
原因就在本文件：这一轮把三份注入输出与一份完整门禁读数**逐字**贴进来（对比 §4.19 那种转述式粘贴）。⚠️ 本处第一版写的是 1,181／1,058，那个读数取在最后几笔之前，**复测时两本又各自涨了 3 与 4 行**。
⇒ **VERIFICATION 只剩 16 行**，下一轮不论做什么都会先被 `tests/guards/test_file_size.py` RED 打断，
所以"切册"已经从 I71 里那条"两轮之内的余量账"变成**下一轮的第一个动作**。三档选项与实测数字更新在 **ISSUES I71**；
本轮**不代切** —— 切册要动成片节号指针，而 §4.20 刚把台账指针变成机器判定（P6 上限），动指针的动作必须自己单独占一轮。

> **同日追记（2026-10-18，勾选轮（六）之后同一天的勾选轮（七）开头）**：上面那句「本轮不代切」是本块写完时的状态，
> 保留不删。用户随后把六条编号方案全部按推荐勾出（**I71 = 乙**），于是切册就在这件事被勾出来的当天执行了：
> **§4.17–§4.20 这四块（345 行）逐字搬进本册**，`docs/VERIFICATION.md` 从 **1,184 行降到 844 行**（余量 16 → **356**），
> 本册起 **357 行**。搬完之后现数 `DECISIONS 1,101｜VERIFICATION 844｜CHANGELOG 1,062`，
> 只有 `DECISIONS.md`（余量 **99**）还在靠近那条线，`CHANGELOG.md` 余量 138 —— 于是 I71 从 OPEN 降到 **MITIGATED**，
> 残留事实写在台账那一行。**节号序列连续、内容逐字未动**：分册改的是"它在哪一份里"，不是"它是第几块"。
> 跨文件指针共改正 **7 处**（CHANGELOG 4 + DECISIONS 1 + REPO-JOURNAL 1 + ROADMAP 1）+ 裸引用补全文件名 **4 处**，
> 本册同时加进 `tests/guards/test_doc_pointers.py` 的 `LEDGER_DOCS`（它是有日期的读数记录，测试名那一档对它不生效，
> 但编号与节号两档照查）。改完复跑，两条现读逐字抄在这里：
> `.venv/Scripts/python.exe tests/guards/test_doc_pointers.py` 的末三行 =
> `扫了 26 份 md、57 条决策编号、71 条台账编号、543 个测试函数` /
> `台账类文档里今天已不存在的测试名（不判红，逐条记在 **ISSUES I70**）：6 处` / `VERDICT: ALL GREEN`；
> `pytest tests/guards -q` = `27 passed in 28.99s`。台账状态随本条动作变化：
> **71 行｜I1–I71 连续｜CLOSED 46｜MITIGATED 19｜OPEN 5｜WONTFIX 1**（I71 那行从 OPEN 降到 MITIGATED，
> OPEN 五条 = **I5／I16／I17／I51／I67**）。⚠️ **「读数被自己的记录污染」第五次就落在这条追记自己身上**：
> 上面那句「本册切出时 357 行」取的是**本追记写完之前**的数，这条追记又往下推了本册的行数 ——
> 所以本块的收尾现数不再往回写，统一写在本册最末一行：
> `DECISIONS 1,101｜VERIFICATION 847｜本册 377｜CHANGELOG 1,087`（`wc -l` 现取；本行是本册最后一行，
> 后面再涨只改这一行，不动上面任何一句）。

---

### 4.21 勾选轮（七）第二步 · 把四份一次性坏法探针请进门禁链，它当场逮到一条真缺陷（2026-10-18，销账 **ISSUES I72 / I73**，**R-012** 按"乙"执行）

**动作只有一句**：`gates/final.py` 的 `injection` 段由「p9 + p10」两条扩成「p9 + p10 + p16 + p17 + p18」五条判定，p15 单开 `ui-inject` 段；p17/p18 的末行口径同时由 `ALL INJECTIONS CAUGHT` 改成门禁只认的 `VERDICT: ALL GREEN`（那是进门禁链的入场券）。这几份探针的判据**统一成同一条**：红 **且** `FAILED` 行点名到该坏法登记的那条测试 —— 「红但不点名」（把断言改成崩溃，照样红）与「锚点今天落不进去」同等算漏。

**① `--only injection` 今天跑了三场：两红一绿**（三份日志都留在 `.probe_work/`，逐字取，不转述）

```
场 1  injection_chain_1018.log     ── 段 injection（232.1s）  → VERDICT: RED（1 条未过）
  PASS  反向注入探针（断言有没有约束力）
        实测：46/46 条坏法被抓到
  RED   G5 OCR 反向注入探针（阶段 5 的断言有没有约束力）
        实测：RuntimeError: 注入锚点命中 0 次（要求恰好 1 次）：src/pdfarchiver/services/ocr_service.py

场 2  injection_chain_1018b.log    ── 段 injection（322.4s）  → VERDICT: RED（1 条未过）
  PASS  G5 OCR 反向注入探针
        实测：45/45 条坏法被抓到            ← 三条锚点改到现码之后
  RED   p16 文档指针守卫：四档空指 + 台账旧名上限（P1–P6 + 反向对照）
        实测：1 failed, 4 passed in 29.20s
E           AssertionError: docs/UI-WIREFRAMES.md:755 引用 ISSUES I72，而 `docs/ISSUES.md` 里没有这一行

场 3  injection_chain_1018c.log    ── 段 injection（331.8s）  → VERDICT: ALL GREEN   ← 门禁标称值取这一场
        起跑负载：CPU 29.1%｜可用内存 2169MiB｜最吃内存进程 Qoder CN.exe 530MiB
  PASS  反向注入探针…46/46｜G5 OCR…45/45｜p16「共 6 条（5 条坏法 + 1 条反向对照）：抓住 5、漏网 0、
        点名存疑 0、对照破 0、锚点失配 0」｜p17 H1/H2/H3 三条全「红（有牙）」且点名｜p18 S1/S2/S3 同
  合计判定 5 条｜本次未跑 10 段
```

场 1 那条红**不是探针坏**：是我 10-17 改 `ocr_service.py` 的熔断器（**ISSUES I21**）时往 p10 #8 锚点那两行中间插了一行（`consecutive_timeouts = 0`），又在看 `bootstrap.py` 接 `archive`/`dedup` 时把 #26/#28 那行撑成了多行 —— 三条坏法当天**一条都落不进去**，探针直接 `RuntimeError` 退出。登记为 **ISSUES I73**（CLOSED）。
场 2 那条红是**我自己刚埋的**：线框 §W-OCR 第 4 条事实写了一句指向 **I72** 的指针，而那时台账里还没有那一行。指针守卫当场拦住"文档引用一个不存在的编号"，处置是**补 I72 那一行**（那件事本来就欠着），不是删掉线框里那句引用。

**② p15 的真实成本是 70s，不是"约 4 分钟"**：`--only ui-inject` 两场 `── 段 ui-inject（71.9s）` 与 `（69.9s）`，末行都是 `VERDICT: ALL GREEN`、`合计判定 1 条｜本次未跑 10 段`。⇒ `docs/REPO-JOURNAL.md` R-012 与本册 §4.20 ④ 那句「光 p15 一份就约 4 分钟」**是估的**，`SEGMENTS` 里两项标称（`~338s`／`~248s`）同样是我拍的。全部换成实测（332s／70s），`--all` 的 help 由「约 21 分钟」改「约 23 分钟」（按 `--list` 每段标称相加）。⚠️ 那条估算把常驻成本抬了约 **5 倍**，而它正是"等勾选"的理由本身 —— **成本没实测就别拿它做决定**。

**③ 秒级预检 `tests/guards/test_probe_anchors.py`**（I73 的处置）：不跑 pytest，把六份探针表里每条锚点在它的目标文件里数一遍，要求**恰好命中 1 次**；口径与探针自己的 `_apply` 同一条，不另立第二份。现读 `核了 133 条锚点，落在 34 个文件上` / `VERDICT: ALL GREEN`。三条断言各自真注入过一次（`.probe_work/anchor_guard_proof_1018.log`，逐字）：

```
A 锚点被改坏一个字符
   退出码 2｜红 ✓｜点名「p18 #S3」✓
B 目标文件混进 CR CR LF
   退出码 2｜红 ✓｜点名「混用行尾」✓
C 某份探针的表被清空
   退出码 2｜红 ✓｜点名「p17=0」✓
VERDICT: ALL GREEN
```

C 那条防的是最阴的一种：探针改了名、或它的表被清空，前两条断言会**静默变成永真**。同族规则写进 I73 处置栏：**新探针上架必须把它的表接进 `anchors()`**，否则这条守卫对它一无所知。

**④ p10 的行尾归一 —— 一个数错了两轮的地方**：`tests/probes/p10_reverse_injection_ocr.py` 全文写成 CR CR LF（288 处，且**已经在 HEAD 里**），`test_file_size.py` 用 `splitlines()` 数它得到 **577 行**（`wc -l` 同值），真实 **289 行**。归一后现数 `crlf=289｜裸 LF=0｜CR CR LF=0`。这条不是洁癖：两套口径数同一个东西时，只要有一个错数进了台账，之后每一次对账都在拿错的基线比。

**⑤ I72 落笔（本轮第一步的 ④）**：`docs/USAGE.md` §三 两条 + `docs/BACKUP-RESTORE.md` §七 一条，明写那九个键**只读**（`bootstrap.py:235` 装配时读一次）、`config/settings.py:106 save(settings, settings_file)` 是**模块函数**且产品侧**零调用点**（调用只在 `tests/unit/test_settings.py:104/111`），以及**两个「设置」不是一个东西**（`config/settings.py::Settings` 只读 JSON ⇄ `db/repositories/settings.py::SettingsRepository` 写库）。⚠️ 第一版我在文档里把它写成 `settings.save()`，落笔前 `grep` 现数才发现那个方法**不存在** —— 已改正。

**⑥ 本轮收尾读数**（一条命令一条数，全部现取）：
- `pytest tests -q -p no:randomly` → `577 passed, 4 skipped in 130.19s (0:02:10)`（上一轮 574，**+3 精确对上**新守卫那三条 `def test_`）；
- `pytest tests/guards -q` → `30 passed in 29.18s`（上一轮 27，同一处 +3）；
- `gates/final.py --only guards` → `合计判定 8 条｜本次未跑 10 段` + `VERDICT: ALL GREEN`，起跑负载 `CPU 16.7%｜可用内存 2667MiB｜最吃内存进程 Qoder CN.exe 473MiB`；台账行 `73 行｜I1–I73 连续｜CLOSED 48｜MITIGATED 19｜OPEN 5｜WONTFIX 1`；旧名那行 `现数 6 处，上限 6`（**没涨** ⇒ 本轮没留下新的过期测试名）；
- `--only injection`／`--only ui-inject` 见上面 ①②。
- ⚠️ **本册与 CHANGELOG 那几笔落盘之后，又把两段在最终树上重跑了一遍**：`tests/guards` **30 passed in 32.15s**（条数一字未动，29.18s→32.15s 是负载）、`--only guards` 仍 **8 条 ALL GREEN**（台账 `73 行｜I1–I73 连续｜CLOSED 48｜MITIGATED 19｜OPEN 5｜WONTFIX 1`、旧名 `现数 6 处，上限 6`），`--only injection` **312.7s ALL GREEN**。⇒ 门禁 `SEGMENTS` 的标称**仍引全绿那一场（332s），不改写成区间**：区间要的是「同一份树跑 N 次」，而这两场的树不同。逐字 `.probe_work/guards_pytest_final_1018.log`、`final_guards_1018c.log`、`injection_final_1018.log`。

**没测到的（不许混进上面那些绿）**：① 除 guards／injection／ui-inject 三段外，其余 **8 段**今天都没从门禁里跑过（`regression` 是以 `pytest tests` 直接跑的，走链的那条读数仍欠；coldstart／e2e／ocr／consistency／soak／package／g2 全在新树之外）；② 真实语料到今天**一次归档都没跑过**，G4／G17／G18／G19 的性能档无真机读数；③ **I17** 真机首屏、**I5** 改名自愈压测、**I16** 组合内存压测；④ C 块安装包与代码签名（本机无签名证书，按**未交付**标注）。

**本轮的返工与自我否证**：① 三个进了门禁 `--list` 与文档的时长（「约 4 分钟」「~338s」「~248s」）全是我估的，而它们被当成决策依据引用过；② 给 I73 写台账行时用 heredoc 把转义序列直接喂进文档，落到文件里成了**真的 CR 字节**，那一行当场变成它自己正在记录的那个缺陷（1 处 CR CR LF）→ 字节级替换成词 `CR CR LF`，规则同族：**文档正文里要写行尾，写成词，别写转义**；③ `settings.save()` 那一处（见 ⑤）；④ I72 那一行第一次插到了 I73 **之后**，`AssertionError: (83, 84)` 当场逮住编号顺序 —— 顺序也是断言；⑤ p10 那 288 处 CR CR LF 在 HEAD 里躺了三轮，`test_file_size.py` 一直"绿着"报它的行数。


> **本册末行现数（2026-10-18 勾选轮（七）第二步收尾取）**：
> `DECISIONS 1101｜VERIFICATION 847｜本册 442｜CHANGELOG 1106`（`wc -l`＝`splitlines()`＝守卫判定那条口径；
> 本行是本册最后一行，后面再涨只改这一行，不动上面任何一句 —— §4.20 追记里那句同名规矩从今天起换了落点）。
