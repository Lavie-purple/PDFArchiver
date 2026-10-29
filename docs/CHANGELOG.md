# 变更日志

按阶段记录。版本号口径：阶段 0–7 全部走完并通过发布门禁才叫 `1.0.0`；在此之前一律 `0.x.y`，
且 `x` = **已完成的最大阶段号**（允许跳号：没做的阶段在条目里点名，不许让人以为 0–x 全通过）。
**本文件只记实际做过并验证过的变更**，未落地的写在 `ROADMAP.md`，不写在这里。

---

## 轮四十二（2026-10-30）—— fitz 改口 pymupdf + S1 别扭点批（①–⑦）+ 减堆积批（⑬⑭⑯⑰ + 标题行）+ DWM 暗色标题栏 + 其它屏空态（⑨⑩⑪）

走查批（用户 2026-10-30 逐字确认）：「S1 文档库和其它屏都修复……『内容堆积 / 分割感 / 默认隐藏』·
改法清单都按你的推荐来；两条红框空带：乙 · 删掉标题行（推荐）；甲 · DWM 暗色标题栏（推荐）」；
⑫（监测根 C:\Users\lavie）确认为事实记录不改。首次启动分步引导窗线框已交、等勾选（未实现）。

- **A · fitz 改口**：`import fitz` 旧名 1.28 起打弃用警告 → 统一 `pymupdf`。拆分时暴露架构守卫
  只禁新名的洞（见 F ②），最终落法：ui 经 `services/pdf_view.py` 门面拿渲染入口。
- **B · S1 别扭点 ①–⑦**：① 跳转按钮兜底（没命中列表时按选中的文档开整份；可用性跟**点名**走 ——
  修出产品真红：Qt `clearSelection()` 不重置 currentRow，兜底改认 `_selected_doc_ids()`）；
  ② 详情区空态占位文字；③ 「上次读到」措辞按进度分档（第 1 页 = 刚翻开，不说"读到第 1 页"）；
  ④ 检索中等待光标（try/finally 保证异常路径归还）；⑤ 状态栏短口径、技术全称进悬停
  （tooltip 也由后端 `status_detail()` 出，界面不存第二份口径）；⑥ 空分类在状态栏指真实写入口
  （「归入分类…」按钮）；⑦ 清除按钮语义收窄为"只清查询词，不动 chips"。
- **C · 减堆积批**：⑬ 筛选区默认收起（「筛选与集合」开关，有条件自动展开 / 无条件自动收起，
  手动意愿 `_filter_manual` 在条件数变化前生效）；⑯ 动作行（送去识别 + 三颗写入按钮）点名 ≥1 份
  才出现；⑭ 右栏改永久浮层默认关（`FloatablePanel` 双模式，选中即唤出、✕ 关掉后不追着开）；
  标题行乙：浮层去标题行，✕ 收成角标；⑰ theme.py QSS 去面板边框标题条（减分割感）。
- **D · DWM 暗色标题栏（甲）**：暗色档窗口标题栏同步变暗（DwmSetWindowAttribute 属性 20），
  `_apply_theme` 与 `showEvent` 两处生效。
- **E · 其它屏空态 ⑨⑩⑪**：S9/S8/S3 空态补话（空白与"坏了"要说得出区别）。
- **F · 收尾两处守卫真红（都是本轮自己引出来的）**：
  ① `library_page.py` 771 行顶破 700 自线 → 筛选区整段搬进 `ui/library_filter.py`
  （`LibraryFilterMixin`，I96 甲 第二次按主题拆，沿用 `library_hits.py` 先例），页面 **677 行**；
  `test_ocr_on_demand` 的 `FILTER_OCR_BTN_TEXT` 导入经页面 re-export 不断链。
  ② 架构守卫红 `reader_page.py:17 · ui import 了 pymupdf`：A 批改口暴露「守卫只禁新名、
  旧名 `fitz` 没禁」的洞。修法：ui 改走 `services/pdf_view.py` 门面（AVAILABLE / open_document /
  Document / Matrix 四出口），`FORBIDDEN_IMPORTS["ui"]` 补 `"fitz"` 堵洞；坏法注入当场红且逐字
  点名「fitz 不许被 ui 依赖」。p25 四条注入锚点目标路径随代码搬（锚点文本不动）。
- **回归与读数**：第一场 890 绿 / 4 红（file_size ×2、architecture、G1 2.62s 负载场）→ 修后整场
  **892 绿 / 2 红**（271.7s；probe_anchors 4 条失配 → 目标路径跟代码走后 3/3 绿；G1 聚焦复跑
  **2.24s 绿**，负载场口径 §4.41）。**guards 59/59 ALL GREEN**。守卫比人眼先立功两次
  （行数自线、fitz 旧名洞），11 条轮四十二守卫 + 5 条坏法注入全过（详单 VERIFICATION §4.53）。

---

## 轮四十一（2026-10-29）—— 菜单收敛（删文件/视图菜单）+ 状态栏主题按钮 + F5 提示 + 「继续阅读」降级为 S1 轻提示

用户逐字确认（2026-10-29）：「文件和视图两个菜单没有太大作用，把视图的两个功能做在外面，刷新F5
你给个提示就行，切换颜色模式 你就做一个切换按钮就好，不要抢眼」+ ①甲（状态栏半月按钮）②乙
（「文件」菜单连 Ctrl+Q 整条删，退出只走窗口 ✕）+ 「继续阅读」改轻提示（回「甲」）。

- **① 状态栏主题按钮**：`theme_btn`（`QToolButton`「◐」，扁平 `autoRaise` + 指针光标）挂状态栏
  常驻区最右（`sync_label` 之后）；tooltip 说"按下去会到哪边"（暗色时「切换到浅色模式」），
  `_apply_theme` 每次刷新；偏好照旧落 `ui.theme`。
- **② 删「文件/视图」菜单**：`_build_menus` 整个删除，`menuBar().actions() == []` 成守卫；
  Ctrl+Q（StandardKey.Quit）随之消失，退出只走窗口 ✕；F5 快捷键保留（`_build_accelerators`，
  与 Ctrl+F 同一窗口级归属），按下去回一条瞬时提示（2.5s 自动消）：可刷新屏「已刷新 · 当前屏
  数据已重查」，不可刷新屏（S2）如实回「当前屏没有可刷新的内容」；`_refresh_current` 改返回
  bool，提示按它分岔。
- **③ 「继续阅读」降级为 S1 轻提示**：`NAV_ITEMS` 9 → **8 项**，S2 不再是导航屏 —— 阅读页由
  外壳按需创建（`_ensure_reader_page`）直接切栈，导航高亮清空（没有行比停在旧屏的行诚实）；
  抑制位 `_reader_nav_suppressed` 与 `_resume_last_read` 连同它们的坏法一起删除（没有"导航自动
  接上"这条路径就没有可被触发的问题）。S1 搜索栏下新增「上次读到 《…》 · 第 N 页 —— 点此继续」
  提示行（`QToolButton` 扁平，默认隐藏）：有记录才出现，点击经 `open_in_reader` 信号
  （`(doc_id, None)`，与命中面板同一载荷口径）打开最近那份、落在上次那页；文件挪走了**可见但
  禁用**并写明原因。数据源仍是 `DocumentRepository.last_read()` 一个出口；`reload()` 与建页时
  各刷一次。
- **守卫**：`test_resume_reading.py` 重写为提示行版五条（无记录整行隐藏 / 可见可点且点击落上次
  那页 / 挪走可见但禁用 / 注册表 8 项且无 reader / 图标）；`test_app_shell` 新增三条（菜单栏删净
  且无残留 action / 主题按钮切换+持久化+tooltip / F5 两屏分岔提示），两处过期断言跟口径
  （注册表 9→8；导航落库用例从 reader 换到 archive）。三条坏法注入当场红（按钮不接线 /
  提示行不填内容 / F5 不发话）。预检 59 guards ALL GREEN（途中 library_page.py 703 行顶破
  700 自线，注释与代码各收一行回 698）。
- **回归与读数**：全量回归 **884 过 / 4 红**（562.0s）：G1 负载场 + `test_reader_assertions`
  3 条 —— 后者是**测试助手过期**不是产品缺陷：`_navigate_to_reader` 还在 `_select_by_page_id
  ("reader")`，S2 已不占导航格；助手改成外壳同一条路（`_ensure_reader_page` + 直接切栈）后
  受影响套件 **54 过 / 1 红**，红的是 G1。G1 本窗四次单跑 **3.689 / 3.829 / 5.014 / 6.019s**
  全红，当场 CPU **92–100%**（用户前台应用全开）；按 §4.41 先例负载场不作数、照记不换算，
  改动不在 import 路径上（菜单→两条快捷键、一枚 QToolButton、一行提示行），安静窗定点复跑
  归安静窗。**守卫比坏法先立功一次**：test_reader_assertions 的过期导航写法是全量回归当场
  逮出来的，不是靠人眼。
- **切册**：本册 603 行 > 600，按 **D-059** 第 4 条第四次切册 —— `轮二十六`、`轮二十五`
  共 92 行整批逐字迁 `CHANGELOG-ARCHIVE-2.md`（标题行守恒 36 = 14 + 22），活册回到 508 行。

## 轮四十（2026-10-29）—— 导航收敛（删「检索」占位项 /「PDF 阅读」→「继续阅读」）+ 应用图标

用户逐字确认（2026-10-29）：「跟进你的建议，同时这个项目窗体左上角是不是应该设计一下这个软件标志之类呢
更像是产品，在桌面端隐藏时候也是空白 完善一下」。

- **① 删「检索」占位项**：`NAV_ITEMS` 从 10 项回到 **9 项且全部已实现**（检索功能一直在 S1 顶部
  搜索框，单独占一格只会让人以为另有一屏）；状态页「界面尚未实现」段在空列表下连头一起不渲染。
- **② 「PDF 阅读」→「继续阅读」**：数据源唯一 —— `DocumentRepository.last_read()`
  （`last_read_at` 最新一份）；行为挂在 `_on_nav_changed` 的 reader 分支上，启动恢复路径
  （`last_nav_page` 指到 reader）同享。S1 双击跳转（`_open_in_reader`）带抑制位压住 resume，
  不许先把最近读的那份真开一遍再换目标；文件被挪走时降级为状态栏提示，不弹模态框。
- **③ 应用图标**：`src/pdfarchiver/assets/app.ico`（多尺寸 256/128/64/48/32/16，源图裁掉水印），
  `app.py` 新增 `_apply_app_identity`（`setWindowIcon` + Windows `SetCurrentProcessExplicitAppUserModelID`
  任务栏分组，必须在首窗前设）；spec 的 `datas` 收 `pdfarchiver/assets/`（缺文件当场炸 —— 同一族坑：
  纯数据文件不进 PYZ，spec 不收 = 冻结产物退回系统默认图标），EXE 段补 `icon=`（.exe 文件本身
  在资源管理器/快捷方式里的那层图标）。
- **守卫**：新增 `tests/integration/test_resume_reading.py` 六条（无记录给指引 / 有记录接上那份并落页 /
  挪走降级提示 / S1 带压不叠加【钉的是调用本身，终态断言分不出好坏】/ 注册表无占位项 / 图标非空多尺寸）；
  两条坏法注入当场红；`test_app_shell` 两处过期断言跟口径（注册表 10→9；「未实现页」改测 PendingPage 兜底）。
  受影响套件 97/97 绿；全量回归 884 过 / 1 红（G1 负载场照记不换算，绿证据取同代码
  单跑 1.492s 贴线，见 RUNLOGS §4.51）。

---

## 轮三十九（2026-10-29）—— 甲 tier.py 浮层孤儿关闭按钮修复（`c0f7df9`）

PySide6 6.8 对先 `add` 进未安装子布局的控件不补 reparent：tier 浮层窄档 `setVisible(True)` 把
无父的「✕ 关闭」QToolButton 提升成 135×59 桌面顶层窗。修法：label + close_button 构造时显式挂 `self`；
`test_ui_tier` 新增孤儿守卫（`window()` 判据 + `topLevelWidgets` 扫描），坏法注入当场红，22/22 绿。

---

## 轮三十八（2026-10-29）—— 收尾双执行：C3·D 转绿复核 + I11 模拟真实用户评测（`src/` 与 `tests/` 零改动）

用户「你就执行这两条」＋「你替我进行测试 模拟真实测试就好」。

- **C3·D 转绿确认**：`--only consistency` 一场 4,793.3s（低负载场），doc 11003 首场对账认可，
  ISSUES I118 固定入口收口；整链口径从此 **35/36 绿 + ISSUES I119 照记**。
  新发现 `C3·lavie` 漏索引 1 份 `.zcode` 工具缓存 ⇒ 开账 **ISSUES I120**（OPEN 等勾选，推荐乙照记）。
- **I11 模拟评测**（seed 20261029，判分口径同轮三十六）：用户风格关键词 ① **2/20 红**、② 2/20 红、
  ③④ 绿；整句 A/B ① 11/20（复现轮三十六）。模拟替代不了查询作者本人 ——
  **I11 维持 MITIGATED、G15 不绿**，不换口径复跑凑绿；收口条件不变：用户本人 20 条真查询。

---


## 轮三十七（2026-10-28）—— 甲 命中解释改行内后缀（乙→甲）；丁 库内问答 S9 落地（第 9 屏，抽取式）

线框四项逐字确认记 **D-063**（用户 2026-10-28 勾「§0+§A 甲」「§B/§C 跟进你的建议来」「§D 甲」「换成甲」）。

- **甲 · 命中解释 乙→甲（行内后缀）**。撤掉轮三十六的常驻解释带（选中即出、常驻三行），
  改成接在命中行尾的短后缀。文案 owner 仍只有后端一处：`SearchResult.suffix(hit)`
  （**ISSUES I60** 族：界面里不存在第二份解释）；页码与出处不再重复（`rows()` 行首已带），
  后缀只补**通道口径与 bm25 分数**，且 bm25 只在 trigram 支报 —— LIKE 与三条非正文通道
  没有相关性得分，行尾出现 0.00 就是假读数。`tests/integration/test_hit_explain.py`
  按行内后缀重写（10 条断言）；坏法 8 条真注入全红，还原后 md5 一致。
- **丁 · 库内问答 S9 落地**（第 9 屏；屏数 D-039 的 8 → 9，清单已按 AGENTS 规矩重过，
  唯一口径 `UI-SCREENS.md` §六）。
  - 后端：`semantic/qa_service.py` 新增 `QaService.ask()` —— **抽取式，不生成**：答案句 =
    检索统计（「共找到 N 段相关正文，覆盖 M 份文档。」/ 空结果「没有找到相关正文。」+
    向量库为空时注明先去 S7 建索引），证据 = 语义 top-8 段的原**文摘录**（`text_pages.body`
    折叠空白截 120 字，**ISSUES I116** 甲 的「有可搜正文才入场」同源判定），卡头
    「文件名｜第 N 页｜相似度 0.xx」出自 `Evidence.header()`。摘录卡常驻一行
    「这里是原文摘录，不是生成的话」（SPEC 五·不许凭空编造的正面声明）。
  - 新读数 `VectorStore.stats()`：一次扫描出「向量条数 / 覆盖文档份数」两个读数
    （196.8 万行实测温 25ms / 冷 1.1s，**ISSUES I111** ⑥），只挂 S9 页惰性构建与每次提问后，
    不挂巡检与建窗路径（**ISSUES I109** 禁区不进）。`TextRepository.body_of_page()`
    取单页正文 —— 不用 `pages_of`（946 页的最大单份为个数拷整本，不干那个）。
  - 界面：`ui/pages/ask_page.py` 两栏（左「历史提问」240px **内存态**：去重置顶、上限 20 条、
    点击重问；右答案区保底 720px）；页宽 < 960px（1024 地板档）左栏收起（`setVisible(False)`，
    历史提问不是任何读数的唯一载体，收走不丢信息）；检索异常按 **ISSUES I84** ③ 落红字 +
    原文并清掉旧证据卡；证据卡双击 → S2，载荷口径与 S1 同一份 `(doc_id, page_no)`；
    证据卡 QSS 与解释带/提示条同一族（`QFrame#evidenceCard`）。
  - 两条措辞差量如实记账（**I11** 族先例 = 轮十五 D）：① 范围读数写**「范围：全库（N 份）」**
    （线框的「当前筛选」在 S9 没有对应控件，语义通道本就不看筛选）；② 历史提问是**内存态**，
    重开应用即清空（不加新表）。`ui` 层不 import `pdfarchiver.semantic`（架构守卫钉着），
    `Evidence` 走鸭子类型 —— S1 对语义命中同款先例。
  - 测试 `tests/integration/test_ask_page.py` **11 passed**；坏法 6 条真注入全红
    （答案句界面重拼 / 卡头界面自拼 / 双击丢页码 / 历史改 append / 删 1024 收起 / 范围读数硬编），
    还原后 md5 一致。**守卫当场逮到一条真缺陷**：`_remember_history` 只挡顶条重复、
    中段同名旧条不摘 —— 首跑即红，修后再跑绿（这条红是真牙的证据，不是误报）。
    另踩**既有坑一次**：双击用例走进 S2 对假路径弹模态 `QMessageBox.critical`，
    offscreen 下不红、只永不结束 —— 装 `dialog_doubles.stub_message_boxes` 替身后 3.2s 跑完
    （`dialog_doubles.py` 头注记的就是这条坑）。
- 全量回归 **878 passed / 1 skipped（257.8s）**，EXIT=0；导航注册表 9 → 10 项
  （9 屏 + `search` 占位），`test_app_shell` 入口数断言随迁。整链 12 段与预检读数见
  `VERIFICATION-RUNLOGS.md` §4.48。

## 轮三十六（2026-10-28）—— 乙 启动即增量同步；丙 命中解释；甲 OCR 按需 + 预算内只排预算内的；I11 查询来源换成真库自动生成

用户这一轮的指令逐字：「1+2+3+4」（四项全做）与「都按你推荐」—— 八个推荐项分两批做完，
本轮交付前六项；丁 · 库内问答 S9（抽取式答案）按 AGENTS 规矩**先出线框等逐屏确认**，未写界面代码。

- **乙 · 启动即增量同步**。实测根因：巡检慢路按**连续运行时间**计时（`scan_verify_minutes=30`
  ⇒ 360 次轮询），应用一关一开计数器从 0 重来 —— 真库六根 `last_full_scan_at` 全停在
  **2026-10-16**，而库里文档已涨到 10,998，关机期间磁盘上发生了什么从没认过账。修法三处：
  `Patrol.poll()` 第一轮无条件排一场全量对账（增量：没变的文件不排索引）；
  `MainWindow.start_patrol()` 起定时器**当场**跑一轮不等第一个 5 秒间隔；
  新读数 `StatusService.sync_status()`（`SyncStatus`）——「全库同步到哪个时刻」取各启用根里
  **最早**的那一刻（保守口径：只要有一个根没对过账就不存在"全库同步到某刻"），从未对账的根
  单独数一格，排队/在跑分开；落点两处：状态栏右侧**常驻**格（不走 `showMessage`，不被巡检
  每 5 秒那句冲掉）+ S7 状态页一块（同一个方法，两个口径不会分家）。只碰
  `monitored_roots` + `processing_jobs` 两处便宜查询，**不碰 `text_pages`**（**ISSUES I109** 丙 同源）。
  测试 `tests/integration/test_startup_sync.py` **10 passed**；坏法 **8 条全红**
  （`.probe_work/u36_inject_startup_sync.py`：第一轮拆掉 → 5 failed；当场对账拆掉 / 取 max /
  「从未」分支拆掉 / 停用根数进来 / 走临时区 / 两口径并一句 / S7 不铺上屏 → 各 1 failed），
  还原后 md5 与原文一致。
- **丙 · 命中解释（选中即解释）**。后端 `SearchResult.explain(hit)` 是 S1 右栏那条解释带的
  **唯一文案来源**：只用检索时本来就带回来的字段，不重跑查询；bm25 **只在 trigram 支**报
  （LIKE 与三条非正文通道没有相关性得分，报 `0.00` 就是假读数 —— `indexing/fts.format_bm25`
  给 `≈0` 下限，量化到 0.00 的那档改说「≈0」）；浏览 / 非正文 / 正文（trigram 与 LIKE、
  浅扫未扫完）各有各的一句话，语义命中明写「非原文匹配」。界面 `ui/library_hits.py` 右栏
  常驻三行解释带，选中即出、清空即复位，最小高钉住不跳。测试 `tests/integration/test_hit_explain.py`
  **12 条断言**；坏法 A–G **13 条真注入**（`.probe_work/u36_inject_startup_sync.py` 同期记录
  在 `.probe_work/round36_injections.md`：其中 D2「删掉 `_clear_hits` 里的复位行」**0 红**
  —— `QListWidget.clear()` 自己会发 `currentItemChanged`，那行是意图声明不是机制，如实记录后
  还原），最终 `test_hit_explain + test_ui_tier + test_search_service + test_theme_contrast = 69 passed`。
- **甲 · OCR 按需（顶栏文件夹级 + 情境提示条，两个入口都要）+ 预算不够只排预算内的**。
  入口一：S1 顶栏「按筛选识别 OCR」按钮 —— 名单取**当前筛选条**下「还没识别过的扫描件」
  （`doc_filter_from_query` 把筛选 dict 换算成 `DocFilter`，只有这一处解释，**ISSUES I60** 同族），
  名单为空时按钮置灰；入口二：右栏情境提示条 —— 关键词搜索**零命中**且这个筛选下真有
  未识别扫描件时才出现（三态：给原因 / 有命中即收起 / 语义通道一律收起），一键把**整批**送 OCR。
  预算语义改贪心部分排队：`_split` 排得进多少排多少（余量 `min(pages, left)`），排不下的份
  `SKIP_BUDGET_SHORT`（「排不下，明日再排」）与 `SKIP_BUDGET`（「已用满，别按」）分列；
  `budget_note()` 四档（用满 / 不够只排一部分 / 跑不到底 / 够），「正好够」不许说成不够
  （`partial_tail` 用 `>` 不用 `>=`，差一错钉死），部分排队时明说最后一份会停在半路记 partial。
  测试：`test_ocr_on_demand.py` 9 条断言 + `test_ocr_batch_panel_ui.py` 18 条 + `test_ocr_plan_reads.py`
  5 条全绿；**新常驻探针 `tests/probes/p25_ocr_on_demand_injection.py`（10 条坏法）进
  `gates/final.py` injection 段**，10/10 RED；`p23` 同步扩到 **26 条坏法**（四档口径与
  partial 文案各配齐）。**守卫先报一次**：锚点守卫逮到 p23 #U5 的锚点被四档改写碰没 ——
  追查发现那条单测本身已经**陈旧**（还在断言旧三档文案），重写成四档口径后锚点跟着搬，复跑全绿。
- **I11 丙-甲 · 查询来源换成真库自动生成**（挂账的"查询仍是我模拟的 20 条"就此销掉）。
  `.probe_work/u36_i11_eval.py`（全程只读）：seed 20261028、抽样池 native 500–3,000 字在盘页
  2,000 行哈希序、每份一页一句、剥掉非 CJK 后 12–60 字当查询（模拟"记得内容记不住数字/英文"），
  20 份文档 20 条；语义走产品 `SemanticSearchService`（1,969,088 向量暴力扫，单条 1.9–4.1s），
  正文走产品 `TextRepository`（通道选择同源 `channel_for`）。**D-035 四判定：① Recall@10
  （doc 级）11/20 红（门槛 ≥18；按页严格 9/20 如实记）；② 互补性 11/20 绿；③ 不回归绿
  （RRF top-1 9/20 vs 纯 FTS top-1 1/20）；④ 可定位 0 违规绿**。9 条未中逐条查过：
  8 条期望页向量在场 = 语义真没找到（自动句信息量低，是这套查询口径的难度）；
  1 条（doc 4935）该份向量 0 而正文在场 = 数据缺口，回填等勾选。**G15 仍不许宣布绿**，
  读数照实进 **ISSUES I11**（台账已更新）与 `docs/SEMANTIC-EVAL.md` §四。
- **收尾**：全量回归 **866 passed / 1 skipped**（上轮 834）；临时文件清零
  （tests 误留的最小窗宽探针一条 + `.probe_work` 下的 OCR 注入与最小窗宽量测脚本两条，均已删）。
  **整链 12 段一条命令 36 判定 / 1 红 / 未跑 0 段**：唯一红 = `C3·H:\` 漏索引 4 份迅捷样例 =
  **ISSUES I119 WONTFIX 照记**（用户接受的代价，不是新缺陷，不许复跑凑绿）——本场口径
  **35/36 绿**（coldstart 0.953s｜injection 697.4s｜consistency 4,112.8s 真根 18/19｜package 400.1 MiB｜g2 P95 299.0ms）。


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

## 分册：更早的轮次在两册

2026-10-28 这一天第三次切（**D-059** 第 4 条的再切线：活册 > 600 行）。切前 599 行，
`轮二十四` … `勾选轮（二十）` 共 **262 行**逐字搬进 [`docs/CHANGELOG-ARCHIVE-2.md`](CHANGELOG-ARCHIVE-2.md)（排在 `勾选轮（十九）` 之前，时间上更近）；
`勾选轮（十九）` 及更早仍在同一册，`勾选轮（六）` 及更早仍在 [`docs/CHANGELOG-ARCHIVE.md`](CHANGELOG-ARCHIVE.md)。
标题数守恒（搬前全部轮次标题 = 活册 + 分册二 + 第一分册，一条没改、一条没删）。

写新一轮一律追加在本文件；本文件超过 600 行就把最早的一整批轮次整轮迁进**第二分册**（**D-059**）。
