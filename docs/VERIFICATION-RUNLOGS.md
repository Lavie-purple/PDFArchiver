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

### 4.22 勾选轮（八）· I17 真机首屏核对：第一次有人看见真首屏（2026-10-18，两轮 21 场真进程）

**这条为什么一直空着**：`gates/stage1.py:44-49` 的 `_run()` 给**每一条**子命令注入
`QT_QPA_PLATFORM=offscreen`，G1 那句 `python main.py` 也不例外。offscreen 不做窗口合成、
不加载真实字体 —— 此前 18 次冷启动读数（0.344–1.031s）量的是一个「没有屏幕的 Qt」，
而「首屏看起来对不对」这件事从来没有人核对过。

**驱动**：`.probe_work/i17_real_first_screen.py`。三条边界：只用临时语料 + 临时数据目录
（真实语料一登记，`_start_background()` 就会自动续跑它那份积压，不是这一轮该动的东西）；
零点击执行按钮；切页走产品自己的 `ui.last_nav_page`。9 个导航项各一场 + 文档库最大化 +
设置与状态最大化 = 11 场，**一场一个新进程 = 一次真冷启动读数**，判据沿用 G1 那一条
（`state.log` 里 `window.ready` 带 `cold_start_seconds` 且有一条 `shutdown`），
红线 `G1_COLD_START_MAX = 1.5` 不在这里另立口径。

**第一轮（`run.log`）判 RED，而且红得对**：`launches=10 cold=0.781..2.778 shots=10
errors=1 traceback=0`。超线的是今天这台机器**第一次**把 PySide6 那套 DLL 读进内存的那一场
（2.778s），后 9 场 0.781–1.067s。同一份 report 里每场 `shutdown_rows=2` —— 驱动自己往同一份
`state.log` 写了 `startup.begin/…/shutdown` 三条，把我那条 `>= 1` 的判据满足了两遍。
**判据没牙是我自己写的判据的缺陷**，见下面「探针返工」。

**第二轮（`run2.log`）ALL GREEN**，逐字：

```
seed: {"drained": true, "documents": 64, "missing": 0, "roots": 1, "jobs_by_state": {"done": 63, "failed": 1}, "fts_by_status": {"done": 63, "failed": 1}, "ocr_pages": 0, "index_backlog": 0}
library        cold=0.83 exit=0 size=[1922, 1246] md5=91257c2b46e9 shutdown=1
search         cold=0.873 exit=0 size=[1922, 1246] md5=6d5ea4ee02c0 shutdown=1
reader         cold=0.824 exit=0 size=[1922, 1246] md5=2f2e41c6ad1a shutdown=1
archive        cold=0.818 exit=0 size=[1922, 1246] md5=0c2e3de21029 shutdown=1
operations     cold=0.826 exit=0 size=[1922, 1246] md5=ac3521ffaea9 shutdown=1
duplicates     cold=0.834 exit=0 size=[1922, 1246] md5=4d6cec8e89e8 shutdown=1
monitor        cold=0.898 exit=0 size=[1922, 1246] md5=1d001d3523a0 shutdown=1
categories     cold=0.8 exit=0 size=[1922, 1246] md5=387f10d94cdd shutdown=1
backup         cold=0.805 exit=0 size=[1922, 1246] md5=2a2a9cebef2c shutdown=1
library_max    cold=0.882 exit=0 size=[5120, 2114] md5=8f5156c4e54e shutdown=1
monitor_max    cold=0.853 exit=0 size=[5120, 2114] md5=df07f26e1ced shutdown=1
launches=11 cold=0.8..0.898 shots=11 errors=1 traceback=0
VERDICT: ALL GREEN
```

11 场 `exit=0`、`startup_rows=1`、`shutdown_rows=1`（关窗对账行在真机平台同样落得下来）、
`window.ready` 在场；11 张图 md5 全不相同（`duplicate_shots: {}`）；`app.log` 251 行里
ERROR **1 条**、WARNING 0、Traceback 0、启动失败 0，那 1 条 ERROR 是故意造的截断 PDF，原文：
`任务 62(index) 判定为不可重试失败（不再排第二次）：…损坏文件 截断的 PDF.pdf｜FileDataError:
Failed to open file …`。语料 64 份（60 中文名 + 1 条 127 字符深路径 + 1 份无文字层 +
1 份截断 + 1 份字节级重复），从磁盘 `rglob("*.pdf")` 数出来再与库里对，不写死。

**真机 vs 离屏（这条是 I17 的核心疑问，答案是「没有那回事」）**：真机稳态 0.781–1.067s
（第二轮 0.800–0.898）落在离屏区间 0.344–1.031s 的**上半段**，不是「离屏通常比真机快」，
两边同量级；1.5s 红线在真机稳态下同样成立，**`gates/stage1.py` 的阈值一处都没动**。
唯一超线的是第一轮第一场 2.778s，第二轮第一场 0.830s。两次唯一的差别是这台机器今天第一次
把 Qt 的 DLL 读进内存。**归因（系统文件缓存）与数据一致，但没有证死** —— 要证它得清一次
系统缓存再跑，那需要管理员工具，本机没有。所以这里按「事实 + 未证归因」记，不写成结论。

**逐屏核对（真字体、真合成，中文第一次是真的）**：9 屏首屏全部正常渲染，侧栏 9 项 + 图标 +
选中态在位；S1 三栏在 1280 与最大化档（本机 3413 逻辑宽）下都成立；S1 表格 5 列在 1280 档
需要横向滚动 —— 这是 **D-039/D-040** 定过的地板档行为，不是缺陷。**两条真缺陷**另记台账：

- **ISSUES I74 · 主题里一条 `:disabled` 都没有，禁用态与可用态像素完全相同**。
  正向对照先证明取色法有效：清空 QSS 走 Qt 默认样式时，同一按钮两态**不同**
  （可用 `#fefefe/#f9f9f9` vs 禁用 `#eeeeee/#c4c4c4`）；换上 `theme.py generate_qss()` 之后：
  普通按钮两态直方图**逐格相同**（`#ffffff`×1292 / `#dee2e6`×88 / `#495057`×48），
  主按钮 `#searchBtn` 两态**逐格相同**（`#2563eb`×1392 / `#ffffff`×48）。
  `grep -oE ":[a-z][a-z-]*" theme.py` 数出来：`:hover` 10、`:selected` 7、`:pressed` 1、
  `:focus` 1、`:checked` 1、**`:disabled` 0**。QSS 一旦显式写 `background-color` + `color`，
  Qt 就不再拿调色板的 Disabled 组画字 —— 主题拿走了默认态，又没补回来。
  影响面是 14 处 `setEnabled`，其中 4 处是**危险动作的门**：`confirm.py:92`（不输确认词不许执行）、
  `archive_page.py:279`（执行归档，真搬文件）、`backup_page.py:142`（恢复，覆盖当前库）、
  `dedup_page.py:203`（开始判重）。
- **ISSUES I75 · S7 上半区被 `QSplitter` 按 sizeHint 比例冻在 36%，任务/故障读数默认看不见**。
  offscreen 几何（`.probe_work/s7_splitter_probe.py`，量的是几何与比例，与平台无关）：
  窗口高 800 → `splitter.sizes=[276, 479]`（上半区 36%）、读数框视口 192px、内容 48 行 ×
  行高 13px = 624px → 不滚动可见 **14/48 行**，看不见 34 行（70%）；窗口高 1409（本机最大化档）
  → `sizes=[499, 865]`，**仍是 36%**，可见 31/48，看不见 17 行（35%），而下半区同一时刻有
  **418px 空白**。36% 这个数不是巧合：两栏 sizeHint 258 / 447 = 36.6%，与两个窗高下实测的
  36% 吻合 —— 即 `setStretchFactor(0, 1)` / `(1, 1)` 那两行（`settings_page.py:82-83`）
  在初始分配上不起作用，比例被 sizeHint 冻住。真机最大化截图独立印证：可见到「分类 = 14，标签 = 0」，
  其后的 `== 默认分类写入结果 ==`、`== 扫描与索引任务：进度 / 错误 / 重试 ==`、`== 界面尚未实现 ==`、
  `== 还没接到界面上的动作 ==` 与磁盘口径那句，全在窄缝自己的滚动条里 —— 而 S7 存在的理由
  （AGENTS.md「启动必须打印当前默认值 / 用户覆盖值 / 来源文件」+ SPEC 4.3「数据库损坏要能被知道」）
  就写在那五块里。

**探针返工四处（全在第二轮之前修掉，逐字记在这里，因为下一轮还会踩）**：① 判据没牙 ——
`shutdown_rows >= 1` 被驱动自己写的那条 `shutdown` 满足，改成 `== 1` 且 `startup_rows == 1`，
并把切片起点挪到驱动那次装配之后；② 裁剪把 Windows 的**不可见缩放边框**裁进去了 ——
`GetWindowRect` 给 1942×1256，可见边框要用 `DwmGetWindowAttribute(DWMWA_EXTENDED_FRAME_BOUNDS)`
= 1922×1246（本机 150% 缩放下每边约 11px，最大化那张还会连带裁进邻桌 11px）；③ 第一轮留下的
旧 PNG 会让「图数 = 场数」拿旧图满足，起跑先删 `real_*.png` / `stdout_*.txt`；④ 语料份数写死
63 与库里 64 不一致，改成从磁盘数。

**没测到的（不许混进上面那些绿）**：① 真实语料到今天**一次都没被这一轮用过**（故意的，
见上面那条边界），G4／G17／G18／G19 的性能档仍无真机读数；② `gates/final.py` 除
guards／injection／ui-inject 三段外，其余 8 段今天都没从门禁里跑过；③ I74 / I75 只到
**取到数**，一条代码都没改（界面改动要过用户的逐屏确认，见本轮编号清单）；④ 临时数据目录
收尾删不净：`work_dir_removed` 记的是 `WinError 32 另一个程序正在使用此文件`，残留
`data\logs\app.log` 与 `state.log` 两个文件，手工删的。**这条不是产品缺陷**：
`logs.py:66` 的 `RotatingFileHandler` 是进程级的，`ctx.shutdown()` 故意不关它（产品关窗后
进程就退了，`state_event` 反倒是每写一次开合一次）；是驱动在同一个进程里 bootstrap 了 11 次
同一个数据目录，句柄一直在。已按此改驱动（rmtree 前先把 owned handler 逐个 close 再摘掉）。


**文档层自己的返工三处（都在这一节自己身上，所以记在这里）**：① 更新本册末行现数时用了「替换所有匹配」，把 **§4.20 那条历史读数**一起改掉了（`本册 377` 被覆盖）—— 从 `git show HEAD:docs/VERIFICATION-RUNLOGS.md` 取回原文逐字恢复（那条 blob 是 LF，要 `splitlines()`）；② 更狠的一半：§4.22 的插入点选在**当时那条活行上**，等于把勾选轮（七）那块历史现数**整块删掉**，而轮（七）留下轮（六）那块时是保留的 —— 已按原样补回（`.probe_work/i17_restore_hist.py`，插点唯一 + 只改最后一处 + 行数三处复数一致）。**规则重述**：这类同名格式的行只有**最后一行是活的**，改前先数匹配条数；插新段时旧块留着；③ 本机埋点脚本数台账状态时**又**踩了转义竖线 —— `split("|")` 把 I42 那格（正文里有 `pending\|done\|failed\|skipped`）切成两格，`CLOSED` 少数 1 得 48，而门禁那行是 **49**。权威口径是门禁那一行；「转义竖线不是分隔符」这条这次落成了代码（`.probe_work/i17_ledger_count.py`，与门禁逐字一致），不再只写在文字里。


### 4.23 勾选轮（九）—— I51 文档库那一列改成一批一批取（2026-10-18，销账 **ISSUES I51**，新开 **I76 / I77**，落 **D-058**）

**取数路径**：三档库全在 `%TEMP%` 下的临时库里造（`bootstrap(data_root)`），**真实语料 10,977 份一次都没被这一轮用过**
（沿用 **ISSUES I64** 那条：库里 ids 1–3 是用户数据，不许当夹具）。名字用长中文名
`归档范围与保留期限的请示（复函稿）附件全部版本第N版.pdf`，`sha256` 用 `{n:064x}` 保证唯一。

**修前 / 修后同一把尺**（`.probe_work/i51_1018/paging_probe.py before|after <份数>`，两边都只调页面对象自己的入口，
探针里不重写一遍取数）：

| 读数 | 修前 8,000 份 | 修前 80,000 份 | 修后 8,000 份 |
| --- | --- | --- | --- |
| 首屏秒数 | 0.156 | 0.255 | **0.016** |
| 表格里几行 | 1,000 | 1,000 | **50** |
| 库里多少份 | 8,000 | 80,000 | 8,000 |
| **看不见多少份** | **7,000** | **79,000** | 0（滚到库尾共 8,000 行） |
| 逐行分类 SQL | **1,000 条** | **1,000 条** | **0 条**（批量 **1** 条） |
| 状态栏那行 | 「共 1000 份文档」 | 「共 1000 份文档」 | 「共 8000 份文档｜表格里已有 50 行，滚动到底继续取下一批」 |
| 到库尾的方式 | 反事实：只能把 `list(limit=全库)` 抬上去（AGENTS.md 禁止的那条路） | 同左 | `_load_more()` 循环 **159 批 / 7.949s** |
| 库尾那行 | — | — | 「共 8000 份文档｜表格里 8000 行」 |
| 顺序与重复 | — | — | `table_order_matches_repository_name_order=true`／`duplicate_ids_in_table=0` |

读数文件：`before_8000.json`、`before_80000.json`、`after_8000.json`。8 万份档的「一路滚到底」是**外推**不是实测 ——
`after_80000.json` 真跑了 40 分钟没写完、被我中止（那个后台任务号 `b75f6yd8o`），改成深度采样
（`browse_depth_probe.py` → `depth_80000.json`）：

| 深度（offset） | 每批后端 ms｜只数一遍（现在的代码） | 每批后端 ms｜带全库重数（修前每批都付） | 补 name 索引之后 |
| --- | --- | --- | --- |
| 0 | 64.3 | 81.7 | 1.7 |
| 1,000 | 83.6 | 91.8 | 1.7 |
| 10,000 | 217.8 | 224.5 | 2.9 |
| 40,000 | 468.9 | 466.9 | 6.7 |
| 79,950 | **772.9** | 770.2 | **12.4** |

- `count_matching` 单独一句在 8 万份上是 **5.2ms**（补索引后 4.7ms —— 那条本来就不是索引能救的，
  `ix_documents_missing` 只收 `IS NOT NULL`，而筛选用的是 `IS NULL`）。它在浅处只值 17ms、在深处被排序吃掉，
  所以「带全库重数」那一列在 40,000 之后**不比**「只数一遍」慢 —— 这两列的差别只在浅处，别把它读成单调。
- **真正的代价随深度线性涨**：64.3 → 772.9ms（×12），因为 `ORDER BY d.name COLLATE NOCASE … LIMIT ? OFFSET ?`
  每批把整个匹配集排一遍。**这才是 8 万份档的主导成本，不是重数。**
- 浅处 Qt 侧 **1.526 ms/行**（20 批恰好加 1,000 行 / 1.526s ⇒ 两个数撞在一起是巧合，不是同一个字段）
  ×80,000 行 = **122.1s 外推**。
- 索引那一档（`index_write_probe.py`，同一份临时库里补
  `CREATE INDEX ix_documents_name_ci ON documents(name COLLATE NOCASE)`）：读侧最深一档 **62×**（772.9 → 12.4ms），
  建索引 **0.337s@8万份**，写侧 **0.908 → 0.975 ms/份（+7.4%）**。**没动 schema**，等勾选（**ISSUES I77** 甲/乙/丙，推荐 丙）。

**测试**：新文件 `tests/integration/test_library_paging_ui.py` **15 passed in 4.49s**；
连同 `test_search_service.py` + `test_ui_tier.py` **62 passed in 15.30s**；全量
`pytest tests -q` → **592 passed, 4 skipped in 152.71s**（上块 577/4 ⇒ **+15，正好是新文件那 15 条**，
本轮没删任何一条测试），日志 `.probe_work/regress_1018_i51.txt`。**改完最后一行文档注释后按提交的那棵树复跑**：**592 passed, 4 skipped in 138.25s**、同三文件 **62 passed in 15.65s** —— 条数一字未动，只有墙钟差，对得上这次 commit 的是这一场（`.probe_work/regress_1018_i51_final.txt`）。

**门禁 guards 段（提交前那棵树）**：`合计判定 8 条｜本次未跑 10 段｜VERDICT: ALL GREEN`；台账那行 `77 行｜I1–I77 连续｜CLOSED 50｜MITIGATED 19｜OPEN 7｜WONTFIX 1`（上块 75／CLOSED 49／OPEN 6 ⇒ 行数 +2 是 I76/I77、I51 由 OPEN 转 CLOSED ⇒ **50+19+7+1=77，三个数对平**）；旧名那行 `现数 6 处，上限 6` 没涨。日志 `.probe_work/final_guards_1018_round9c.log`（同树先跑过 `…round9.log`／`…round9b.log`，两场都跑在文档最后几笔之前，已被这场取代）。

**反向注入**（`injection_probe.py` → `injection_results.json`，每条改完立刻按字节还原并复核）：
M1–M13 十三条坏法**全部 RED**、末行 `VERDICT: ALL RED AS DESIGNED`；
**M10b 是故意留在里面的负对照（预期 GREEN）**。

- **本轮唯一一条「断言其实没牙」的现场就是 M10**：把 `_browse_active` 翻成 False 之后测试仍然 GREEN ——
  不是锚点没落进去（`matches: 1`、`1 passed, 14 deselected`），而是 `_browse_exhausted=True` **独立**挡住了
  `_load_more()`。所以「浏览态标志」这一条**不是**被单点守住的。处理：把 M10 改成同时翻两个标志（变 RED），
  并另立 M10b 记录「只翻一个不会红」这个事实 —— **不假装一条断言守住了两个标志**。
- 每条坏法跑的是 `pytest tests/integration/test_library_paging_ui.py -k <中文名>`，中文 `-k` 在这套环境下可用。

**本轮自己写进去的真 bug（被新测试抓住，不是手工点出来的）**：`_populate_table()` 里
`setRowCount(0)` 之后紧接 `_write_rows(0, docs)` —— Qt 往不存在的行 `setItem` 会**静默丢弃**，于是查询命中表被清空、
测试报「命中 0 行」。改成 `setRowCount(len(docs))`。这条只在**有查询词**那条路上出现，滚动浏览路径一切正常，
所以界面手点看不见。

**文档层这一轮踩了四处（都记下来，因为都是同类）**：
① **Edit 锚点截断**：给 ISSUES.md 追加 I76/I77 时，锚点选了 I75 那一行的**前缀**，于是只替换掉前 ~105 个字符，
把 I75 的后三格**接到了 I77 那行末尾**（I77 变成 7 格、I75 消失）。修法是从 `git show HEAD:docs/ISSUES.md`
取回整行**逐字**拼回，并先证明孤儿尾巴与 HEAD **byte 相同**才敢拼（`.probe_work/repair_i75_1018.py`，
`tail matches HEAD verbatim: True`）。**规则**：台账这种一行一格、单格上千字的表，锚点要么整行要么行首标识，
不许截半格。**复数**：全表 77 行里非 6 格的只有 3 行（I15/I35/I67），与 HEAD 完全一致 ⇒ 本轮损伤已清。
② **转置抄错**：`project_stats.md` 把上块的回归时长写成 `155.69s`，所引日志那行是 `135.69s` —— 已改正并写明
「复述时长要从日志尾部逐字复制」。
③ **没数过的估数**：**ISSUES I77** 乙 那一档我写的是「8 处 item 型断言」，实际数出来是
**6 个文件 25 处**（`item_assert_count.py`：test_ui_tier 7／test_archive_execute_ui 6／test_library_paging_ui 4／
④ **`project_stats.md` 本轮新块落错了地方，而且落点正是记这条教训的那一行**：插入时锚的是**第一处** `## 待补`，可第一处是 轮（六）⑨ 行里那个带反引号的**提及**，不是文末的真标题 ⇒ 整块落进 轮（六）的表格中间、⑨ 行被劈成两半（我的 `## 勾选轮（九）` 标题被粘在 451 行行尾，孤儿尾巴掉到 474 行）。修法是**按行索引 + 边界断言**（先断言表头那行与末行「没测到的」的位置、拼回后该行恰好 3 格），块整体挪到真 `## 待补` 之前并补回标题；diff 只有两处（`replace old[450:474]→new[450:451]`、`insert new[516:542]`），行数 545 → 548。**这个文件按 AGENTS.md 不入库，没有 HEAD 基线可拼** —— 能修全凭两半都还在原地没被覆盖。同一轮里修脚本自己还踩一条：`for k, l in enumerate(block)` 里边遍历边 `block.insert(k, …)` 会把游标顶回去，**无限循环**（表现为脚本无输出地挂着，`faulthandler` 定位到那一行）；改成先 `one(prefix)` 取唯一索引再改。⇒ 规则不是「锚长一点」，是**同名东西不唯一时不许用字符串锚**；改法要么整行、要么索引 + 断言边界。
test_ui_layout 4／test_monitor_roots_ui 3／test_app_shell 1）。已按现数改正。

**同族一次声明（AGENTS.md「禁止同类问题逐个打补丁」）**：随 I51 一起扫全站 `limit=` 取数点，命中三处
（`archive_page.py:246` `list(limit=500)`、`dedup_page.py:249` `duplicate_groups(limit=500)`、
`operations_page.py:79` `list_operations(limit=100)`），**本轮一处都没动**，全部并成 **ISSUES I76** 一条等勾选。

**没测到的（不许混进上面那些绿）**：① 真实语料（10,977 份）**一次都没被这一轮用过**，全是临时库里造的合成分布；
② 8 万行滚到底只有**外推**（见上），而且滚过去的行**不释放** —— 线框字面那句「只渲染视口内 ~25 行」还没做到
（**ISSUES I77** 乙）；③ 分类树/搜索链路以外的三张表（**I76**）仍是静默截断；④ 这一轮**没跑**
`gates/final.py` 除 guards 外的任何一段，也没跑 injection 常驻段（那五份探针跑的是产品侧注入表，
本轮的 13 条坏法是 `.probe_work/` 里的一次性脚本，**尚未接进门禁链** —— 要不要接，等勾选）；
⑤ 台账余量本轮又收紧：`DECISIONS 1,101 → 1,134`（余 99 → **66**）、`CHANGELOG 1,134 → 1,159`（余 **41**），
**ISSUES I71** 那句「下一轮的第一个动作就是它」现在对 CHANGELOG 也成立。


> **本册末行现数（2026-10-18 勾选轮（八）收尾取）**：
> `DECISIONS 1101｜VERIFICATION 847｜本册 549｜CHANGELOG 1134`（`wc -l`＝`splitlines()`＝守卫判定那条口径；
> 本行是本册最后一行，后面再涨只改这一行，不动上面任何一句 —— §4.20 追记里那句同名规矩从今天起换了落点）。
> **本册末行现数（2026-10-18 勾选轮（九）收尾取）**：
> `DECISIONS 1134｜VERIFICATION 847｜本册 646｜CHANGELOG 1159`（`wc -l`＝`splitlines()`＝守卫判定那条口径；
> 本行是本册最后一行，同一轮里后面再涨只改这一行。**上一块（轮（八））按 §4.22 那条规则保留为历史，没有覆盖** ——
> 本行是本册最后一行，同一轮里后面再涨只改这一行。**上一块（轮（八））按 §4.22 那条规则保留为历史，没有覆盖** —— 现册里这类行共 **4 块**：轮（六）／轮（七）／轮（八）／本轮**活的**（本轮这块起于 642 行）。
> **认轮次标题，不认行号** —— 本册正文每涨一块，上面那些行号就集体往下漂移一位（勾选轮（七）把这条写进过指针旁边）。
> **本册末行现数（2026-10-19 向量写路径轮（十二）收尾取）**：
> `DECISIONS 687｜VERIFICATION 856｜本册 652｜CHANGELOG 249`（`wc -l`＝`splitlines()`＝守卫判定那条口径；
> 上一块轮（九）保留为历史，不动。**I86 甲** 切册后 DECISIONS 活册收成 618、本涨到 687（D-060 / D-061 两块）；
> CHANGELOG 活册收成 132、本轮 249 = 132 + 轮（十二）那一大块；VERIFICATION 主册未动，仍 856（余 344）。
> `tests/guards/test_file_size.py` 的 `MD_LIMIT=1200` 那档现在**没有**任何一份临近 100 以内（最紧的是
> `DECISIONS 687 余 513`），所以本册这条末行现数不是"下一轮第一个动作"，只是把本轮读数落在这里）。
> **本册末行现数（2026-10-19 守卫在场性轮（十三）收尾取）**：
> `DECISIONS 687｜VERIFICATION 856｜本册 659｜CHANGELOG 282｜ISSUES 132`（`wc -l`＝`splitlines()`＝守卫判定那条口径；
> 上一块轮（十二）按 §4.22 保留为历史、不动。本轮只涨 CHANGELOG 249→282（+33 = 轮（十三）那一整块）与
> 本册 652→659（+7 = 这一块自身）；DECISIONS / VERIFICATION 主册 / ISSUES 未动 —— I94 甲 改的是守卫代码与文档正文，
> 没开新决策也没换台账行）。现册里带 `**本册末行现数**` 标题的历史块共 **4 块**（轮（七）／轮（八）／轮（九）／轮（十二））
> + 本轮这块**活的**；轮（六）以前那些轮用的是别的措辞，不计入这类。
> `tests/guards/test_file_size.py` 的 `MD_LIMIT=1200` 那档现在**没有**任何一份临近 100 以内（最紧的是 `DECISIONS 687 余 513`）。

### 4.24 界面写路径轮（十四）收尾读数（2026-10-19 19:19 → 2026-10-20 01:12，销账 **I67 甲+乙** 与 **I78 甲+乙+丙**，新开 **I96**）

**起止（墙钟，不重算成单一"活跃"数）**：本地 **10-19 19:19:17**（轮十三收尾那条 commit `4cf86cd`）→
**10-20 01:12** = **5.88 h**。五段提交时刻逐条可对（`git log --date=iso-local`）：A `ed0bdca` 20:00:52／
B `3089965` 21:25:02／C `e02b925` 23:06:45／D `6107050` 23:56:03／E `9fe6fdb` 00:53:54。
会话日志现 **226,762,895 B / 75,968 行**（本环境 `usage.*` 恒 0，只能拿体积当代理）；与 轮（十一）落的那个数
（179,332,350 B / 62,369 行）比是 **+47,430,545 B / +13,599 行** —— 这一笔**跨 轮十二–轮十四 三轮**，
因为 轮（十二）那一格只写了「与上一轮相比增量」而没落数。**不回溯伪造增量归属**，只把今天的现数与那条漏记一起写在这里。

**门禁读数（逐字从日志尾部复制）**：全量回归 **`759 passed, 1 skipped in 240.43s`**
（`.probe_work/full_regression_round14.txt`，收尾最终树；本轮最后一场 B 段之后是
`686 passed, 1 skipped in 228.28s`，+73 = C/D/E 三段新增断言，本轮**一条测试没删**）。
`--only injection` 八份同场 **966.3s**、`VERDICT: ALL GREEN`（`.probe_work/injection_1020.log`）：
p9 69/69、p10 45/45、p16 8 坏法 + 3 对照、p17 3、p18 3、p21 24、p22 25、p23 23 —— **起跑 CPU 54.4%、
可用内存 3,096MiB，不是空载场**（**ISSUES I25**），与 2026-10-18 那 415.3s 不可互相换算，**空载读数仍欠**。
文档指针守卫独立跑 **9 passed in 71.70s**；锚点守卫现读 **233 条 / 45 个文件**（该数由守卫自印，不在此抄成常量）。

**本轮收尾逮到的一条真红（不是负载假红，也不是并发竞态）**：第一次收尾全量回归
`1 failed, 758 passed`，红的正是 `test_台账旧文件名不超过上限`（**29 > 28**），多出来那一处是
**我自己写进 `docs/CHANGELOG.md` 的那句竞态说明里逐字引用了 p16 的假文件名**。判据没有错，
错的是引用 —— 台账类文档允许「列出不存在的名字」但受上限约束，而一句解释竞态的话不需要把那枚假名再抄一遍。
改法是把引用改成指**真文件**（`tests/probes/p16_doc_pointers_injection.py`），改后 `9 passed`、
回归回到 759。**上限一条没放宽**。同族全仓扫一遍的结论：`docs/` 里 `坏法锚` 只剩 1 处命中，
是 `docs/TESTING.md` 在解释这个术语本身；代码侧 5 处命中全在 p16 的载荷表与锚点守卫本体（含 `__pycache__`）
⇒ **工作树无注入残留**。这条教训单独值得记一轮：竞态与自伤**读起来一模一样**（都是 29 > 28），
区别只在「段还在跑」还是「我的文档里真多了一枚假名」—— 判定方法是 `git status` 那两份文件的
`git diff` 里能不能看见那枚名字，能看见就是自伤。

**长度约束这一轮真的开始还债（新开 I96）**：`library_page.py` **686 → 795 行**（`git diff 4cf86cd..HEAD`
数得 15 个 hunk / 9 个新 def —— A 的 OCR 入口、B 的分类标签关联、C 的集合筛选条、D 的导出右键、
E 的批量点名面板**五处接线全落在同一屏**），距 `.py` 红线 800 **只剩 5 行**。`test_file_size.py` 独立跑
逐字 `扫了 202 个 .py 与 31 个 .md｜临近线（余量 ≤100 行）6 份`，末行仍 `VERDICT: ALL GREEN` ——
六份里本轮长出来三份（`library_page.py` 余 **5**、`test_saved_search_ui.py` 727 余 73、`theme.py` 717 余 83），
另三份是历史遗留（`test_job_queue.py` 766／`p12_consistency.py` 722／`p19_combined_memory.py` 737）。
**看清那条 pytest 判的是什么**：`test_临近线的那份必须被点名` 喂的是合成分布（`PY_LIMIT - 50`），
所以真实余量再小也不会让 pytest 变红，只有越线那一档才红 ⇒ 这道风险在门禁链里是**隐形**的，
只有收尾时人去读那六行打印才看得见。`.md` 侧本轮无临近。

**台账闭合（门禁 `ledger_check` 口径，2026-10-20 现读）**：**96 行｜I1–I96 连续｜CLOSED 72｜MITIGATED 21｜
OPEN 2｜WONTFIX 1**，缺陷 0 条，结构不合格 1 行（上限 1，仍是 I35）。OPEN 两条 = **I95**（真库那三条手写
演示数据）与本轮新开的 **I96**。

**没测到的 / 仍欠（不许混进上面那些绿）**：① **空载 injection 读数仍欠**（本轮那场是负载场）；
② 五条编号方案**一条没勾**（甲 `merge_tags` 界面入口／乙 导出列措辞／丙「已归档」唯一口径／
丁 I95／戊 I96）；③ 本轮新写的四段界面写路径**没有做过真机手点**（I17 那一类），全部证据是
`QT_QPA_PLATFORM=offscreen` 的几何与行为断言；④ 11 段整链到今天**仍没有一场跑完过**；
⑤ 安装包与代码签名未交付。

> **本册末行现数（2026-10-20 界面写路径轮（十四）收尾取）**：
> `DECISIONS 687｜VERIFICATION 856｜本册 713｜CHANGELOG 352｜ISSUES 133`（`wc -l`＝`splitlines()`＝守卫判定那条口径；
> 上一块轮（十三）按 §4.22 保留为历史、不动。本轮涨 CHANGELOG 282→352（+70 = 轮（十四）那一整块）、ISSUES 132→133（+1 = 新开的 **I96**）、本册 659→713（+54 = §4.24 那 48 行 + 本块 6 行）；DECISIONS 与 VERIFICATION 主册未动 —— 本轮没开新决策。
> `.md` 侧本轮仍无临近线（最紧的是 `UI-WIREFRAMES 949`，余 251），**但 `.py` 侧临近 6 份、最紧 `library_page.py` 只剩 5 行** ⇒ 已开 **ISSUES I96** 等勾选（推荐 甲 = 按主题拆）。
> 现册里带 `**本册末行现数**` 标题的历史块共 **5 块**（轮（七）／轮（八）／轮（九）／轮（十二）／轮（十三））+ 本轮这块**活的**。

### 4.25 勾选轮（十五）收尾读数（2026-10-20 01:22:54 → 收尾，按「都跟进你的推荐来执行」做完轮十四留下的五条：A I96 甲 / B merge_tags / C「已归档」/ D 线框措辞 / E I95 乙）

**起止（墙钟）**：本地 **10-20 01:22:54**（轮十四 F 收尾 commit `332b2a2` 之后）→ 本轮 F 收尾完成。
六段提交时刻逐条可对（`git log --date=iso-local`）：A `855653f` 01:44:48／B `ad0404f` 02:18:15／
C `97a57b3` 04:33:17／D `1db39d8` 04:34:04／E `75947cf` 06:07:59／F **（本条提交）**。
**06:07–11:40 之间本机休眠约 5.5h**（见下），这段不计入任何「实测耗时」，只解释 E→F 的墙钟为何看起来很长。

**A–D 的断言读数**（抄每段收尾时的全量回归）：A `760 passed / 1 skipped`（+1 = 新的长度守卫）／
B `776 passed / 1 skipped`（+16 = 标签合并）／C `782 passed / 1 skipped`（+6 = 已归档；p22 25→33 同步）；
D 只改文案与只读指纹，不加断言。E 只动用户库与两条注释，不加断言。

**E · 真库改动（本场唯一直接动用户数据的动作，备份在先）**：备份
`%TEMP%\pdfarchiver-i95-backup\catalog.db` **11,967,422,464 B**，`[verify] VERDICT: BACKUP GOOD`，
三条演示行 `{1: abc123, 2: def456, 3: ghi789}` 在快照里都在；单事务删除 ids 1–3，七张子表残留各 **0**、
`foreign_key_check` **0**、耗时 **198.2s**；现库 `documents` **10,977（原 10,980）**、`text_pages` **1,972,578 不变**。
真根 p12 复跑（`.probe_work/p12_i95_after.log/.json`）：**19 条 16 绿 3 红**，`C2` / `C6` 转绿；剩 3 红都不是 I95 ——
**C0** 库 v7 / 迁移目录 v8（`0008_name_ci_index` 未应用）、**C3·D** `D:\` **83 PDFs / 79 records**（4 份微信 PDF 未入索引）、
**C5** 正文 1,972,578 页里 **1 行是空串**。已另立 **ISSUES I97**（推荐先应用迁移 0008）。
旧预测「只剩 I89 6 + I90 1 = 7 红」是过期账：那两条在轮十二就销了。

**injection 段（九份同场，含新入段的 p24）**：**788.9s、`VERDICT: ALL GREEN`**
（`.probe_work/final_injection_r15b.log`）：p9 69/69、p10 45/45、p16 8 坏法 + 3 对照、p17 3、p18 3、
p21 24、p22 25、p23 23、p24 17 —— 合计 **217 条坏法**。起跑 **CPU 26.9%、可用内存 3,186MiB**、
最吃内存进程 Qoder CN.exe 566MiB，是空载场；与 966.3s（负载场，八份）/ 415.3s（五份）不可换算。
**同一天 06:07 那场必须记一笔**：起跑后本机休眠，直到 11:40 才恢复，p10 被 1800s 上限杀掉
（`.probe_work/final_injection_r15.log`，`elapsed=20010s`）—— 那是**休眠**不是产品红；复跑只认 788.9s 这一场。

**全量回归（收尾最终树）**：**782 passed, 1 skipped in 213.05s**（`.probe_work/full_regression_round15.txt`）。
锚点守卫 **259 条 / 46 个文件**（p24 的 17 条入表）；文档指针守卫 9 passed；
台账现读 **97 行｜CLOSED 74｜MITIGATED 21｜OPEN 1｜WONTFIX 1**（I95 / I96 销账，新开 I97）；
长度守卫 `扫了 202 个 .py 与 31 个 .md｜临近线 6 份`，最紧的是 `test_category_export_ui.py` **791 行（余 9）**。

**没测到的 / 仍欠（不许混进上面那些绿）**：① **11 段整链仍没有一场跑完过**（consistency 带真根必红，I97）；
② 安装包与代码签名未交付；③ 本轮新写的界面写路径（并入对话框 / 导出列）仍没有真机手点证据，
全部是 `QT_QPA_PLATFORM=offscreen` 的几何与行为断言；④ `test_category_export_ui.py` 距红线只剩 9 行，
下一轮第一个动作应拆它；⑤ I97 三条红**一条方案未勾**，不自行应用迁移 / 重扫。

> **本册末行现数（2026-10-20 勾选轮（十五）收尾取）**：
> `DECISIONS 687｜VERIFICATION 856｜本册 758｜CHANGELOG 404｜ISSUES 134`（`wc -l`＝`splitlines()`＝守卫判定那条口径；
> 上一块轮（十四）按 §4.24 保留为历史、不动。本轮涨 CHANGELOG 352→404（+52 = 轮（十五）那一整块）、
> ISSUES 133→134（+1 = 新开 **I97**；I95 / I96 只改状态不增行）、本册 713→758（+45 = §4.25 自身）；
> DECISIONS / VERIFICATION 主册未动 —— 本轮没开新决策，验证主册的口径由本册承接。
> `.md` 侧无临近线（最紧的是 `UI-WIREFRAMES 951`，余 249）；`.py` 侧临近 6 份、最紧 `test_category_export_ui.py` 791（余 9）。
> 现册里带 `**本册末行现数**` 标题的块共 **6 块**（轮（七）／（八）／（九）／（十二）／（十三）／（十四））+ 本轮这块**活的**。

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

**临时文件**：`.probe_work/` **444 项 / 848 MiB**（承重保留：`final_chain_r18.log`、`p12_real_root_chain_r18_red.json`、`p12_real_root.json`、`p12_real_root_r18_before_index.json`（补索引前 18/19 现场）、`p12_real_root_r18_after_index.log`、`final_docs_guards_r18.log`、`final_docs_guards_r18_i103.log`、`i103_before.txt` / `i103_after.txt` / `i103_backups_before_ls.txt`、`r18_index_wx_pdf.*`、`round18_soak_30min.log` / `p13_soak_30min_result.json`、`soak_r18.log`、`round18_i102_30x.log` / `i102_coldstart_30x.json`、`round18_g2_inject.log`、`round18_stage1_inject_note.log`、`round18_p9_case13_check.*`、`frozen_smoke_result.json`、`packaging_build_report.json`）。清理：`tmp_p12_timed/`（本轮计时用的临时数据根，30 个文件）清空；一份 10-18 遗留的一次性脚本与本轮的 `launch_p12_r18.py`、`tmp_patch_i103.py` 一并清空；`%TEMP%\p13_soak_1yi2rw_8` 是轮十七承重现场，保留；30 分钟与 4 分钟 soak 的临时根均已自清理；`frozen_smoke_1015_*` 是 10-15 遗留，未动。

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

**G · 回归 / 门禁 / 台账**：第一次全量回归 **788 passed / 1 failed / 1 skipped** —— 红的是 `test_doc_pointers.py::test_台账旧文件名不超过上限`（**37 > 35**：轮十八清掉的 `launch_p12_r18.py`、`tmp_patch_i103.py` 在 RUNLOGS §4.28 里必须留名）。按守卫自己的规矩逐条写明来由，`PY_STALE_CAP 35 → 37`；复跑 **789 passed / 1 skipped / 0 failed / 0 error（245.38s）**（`round19_regression.log` / `round19_regression2.log` / `round19_doc_pointers.log`）。`docs-inject + guards` **9 条 ALL GREEN、本次未跑 10 段**（`round19_docs_guards.log`）；台账 **105 行｜I1–I105 连续｜CLOSED 84｜MITIGATED 20｜OPEN 0｜WONTFIX 1｜结构不合格 1 行（上限 1）：I35**，本轮 **I32 / I104 / I105 均 CLOSED**。文件长度守卫：`扫了 212 个 .py 与 31 个 .md｜临近线（余量 ≤100 行）6 份`，最紧 `p12_consistency.py` **800（余 0）**、`p13_soak.py` **771（余 29）**。

**临时文件**：`.probe_work/` **478 项 / 851 MiB**（承重保留：本轮的 `round19_soak_120min.log` / `_result.json` / `_app.log` / `_state.log`、`round18_soak_120min.log`（作废场）、`round18_g2_retry.log`、`screens_r18/`（10 张 + `report.json`）、`r19_screens_after_fix.log`、`r19_archive_repro_after_fix.log`、`r19_i104_i105_injection.log`、`round19_p13_inject_gbk.log` / `_utf8.log`、`round19_soak_smoke_2min.log`、`round19_regression*.log`、`round19_docs_guards.log`、`round19_doc_pointers.log`）。清理：一次性脚本与备份 `tmp_fix_g2_log.py`、`tmp_g2_fixed_stdout.txt`、`round18_g2_retry_fixed.txt`、`r19_mutate.py`、`_i104_backup.py`、`_i105_backup.py`、`g2_real_backup.py` 全部 truncate 为 0（备份与产品文件 sha256 已逐份核对一致）；`%TEMP%\p13_soak_cddtrfhl`（第二场现场，8.5MiB，app.log 已复制）与 `%TEMP%\p13_soak_1yi2rw_8`（轮十七承重）保留；第一场的临时根已由探针自清理；`frozen_smoke_1015_*` 未动。

**没测到的 / 仍欠（不许混进上面那些绿）**：① 安装包与代码签名未交付；② 隐私以后再处理；③ soak 只到 2 小时，天级/通宵未测；④ C11 旧快照内部损坏不在口径内（I98 乙）；⑤ consistency / injection 跨轮快慢仍未查明；⑥ 真机证据仍是自动断言 + 我看图，不是用户本人逐屏（I17 残余）。

> **本册末行现数（2026-10-22 勾选轮（十九）收尾取）**：
> `DECISIONS 687｜VERIFICATION 857｜本册 998｜CHANGELOG 645｜ISSUES 143` —— 轮十八 968 / 596 / 141 ⇒
> 本册 +30、CHANGELOG +49、ISSUES +2，DECISIONS / VERIFICATION 主册未动（`wc -l`＝`splitlines()`＝守卫判定那条口径；上一块轮（十八）按 §4.28 保留为历史、不动）。
> `.md` 侧无临近线（最紧的是 `UI-WIREFRAMES 951`，余 249）；`.py` 侧临近表见上一段的「台账与守卫」。
> 现册里带 `**本册末行现数**` 标题的块共 **10 块**（轮（七）／（八）／（九）／（十二）／（十三）／（十四）／（十五）／（十六）／（十七）／（十八））+ 本轮这块**活的**。
