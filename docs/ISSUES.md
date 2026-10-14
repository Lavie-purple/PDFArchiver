# 已知问题台账

收尾四件事之一：**「已知问题」必须逐条销账**，不许滚动丢失。
状态只有三种：`OPEN`（未处理）/ `MITIGATED`（有缓解但仍存在）/ `CLOSED`（已验证据）。
新发现的同类问题**先归条再修**（AGENTS.md：禁止同类问题逐个打补丁）。

| # | 问题 | 状态 | 证据 | 影响 | 销账条件 |
| --- | --- | --- | --- | --- | --- |
| I1 | 全量 OCR 在本机不可行：DirectML 单页中位 **3,281ms**，无人值守反算预算 **284ms**，差 11.6× | **OPEN** | `p5_ocr_result.json`；`VERDICT: RED` | 扫描版正文搜不到（抽样 37.5% 是纯扫描件） | 用户就 Q3 三选一，并把选定方案写回 SPEC 阶段 5 验收标准 |
| I2 | 全文索引外推 **28–48GB**（×10 档 280–480GB 直接不可行） | **OPEN** | p2 中位 2,294.6 字/页 × 100.8 万文本页 × 实测膨胀 4.03–6.91× | 决定产品形态，不只是容量问题 | 用户就 Q2 三选一 |
| I3 | `pip check` 报 `rapidocr-onnxruntime requires onnxruntime, which is not installed` | **MITIGATED** | 本轮 `pip check` 原文（见 docs/ISSUES 附） | 看着像坏了，其实是我们**故意**只留 directml 发行版 | 依赖守卫 G21 把这条精确措辞列为唯一允许的错误；任何其他 `pip check` 输出判失败。需在 README 写明「不要修这条」 |
| I4 | `PySide6 6.12` / `onnxruntime>=1.21` 在本机装得上但用不了 | **MITIGATED** | docs/VERIFICATION 2.1、2.2 | 误升级会让应用起不来，且 ORT 共存是**段错误不是报错** | G21 已挡；升级任一者必须先重跑 p3/p5/p6/p8 |
| I5 | 文件监听对「被监听根被改名/删除」完全盲（实测 **0 事件**） | **OPEN** | `p4_watchdog_result.json` `root_renamed.delta_events == 0`；阶段 2 新证据：`test_根目录不存在时不判缺失也不崩`、`test_巡检一轮就把脏根排成一条扫描任务` | 只靠事件 → 索引与磁盘长期不一致 | 慢路周期校验已落地并各有断言；剩余销账条件是阶段 3 的 L4 压测证据（G12 的 ≤60s 保证要在真机上量一次） |
| I6 | 停止监听期间的变更，事件流永远看不见 | **MITIGATED** | p4 `offline_change.detectable_only_by_scan == true`；阶段 2 e2e `test_重启之后一切还在且重扫不必重抽`、`test_进程被杀留下的running残尸重启后接着跑完` | 冷启动必须有一次全量对账 | 全量对账 + 增量事件两条路都有 e2e 证据；真语料首扫仍需 Q8 |
| I7 | FTS5 **没有** `offsets()`（`no such function`） | **CLOSED** | p1 `aux.offsets.works == false` | 命中高亮/偏移方案要改 | 已定 D2：Python 侧算偏移；断言已在 p1 固化 |
| I8 | FTS5 外部内容表 `'delete'` 命令少带一列 → 静默留幽灵行，**SQLite 不报错** | **MITIGATED** | docs/DATABASE 三 · 硬规则 3；p1 `external_content_sync` | 删掉的文件还能搜到，且看不出来 | 阶段 2 起 G10（幽灵行数 = 0）常驻每阶段门禁 |
| I9 | 8.3 短名把空格吃掉（`报告 A.pdf` → `报告A~1.PDF`），纯字符串规范化归一不了 | **CLOSED** | p7 `short_name` 全组 | 同一文件产生多条主记录 | 已定 D4：`os.path.realpath` 必走；p7 15 条断言全绿 |
| I10 | 目标机 `LongPathsEnabled` 无法假设（本机 =1 是现状不是前提）；**且 =1 也只救 Win32 API，不救第三方工具** | **OPEN** | p7 注册表实读 =1、最深文件路径 **533 字符**、普通 API 与 `\\?\` 前缀都创建成功（`plain_api_created: true`）；本轮新证据：同一棵树让 **Git 自身的目录扫描**报 `warning: could not open directory... Filename too long`（`git status --ignored`），删除它必须走 `\\?\` 前缀的 `shutil.rmtree` | 长路径中文目录归档可能失败；打包、清理临时目录、任何外部工具（Git/资源管理器）都可能看不见深层内容 | 阶段 4 归档目标路径生成前自检 + 可读错误文案（不许抛 WinError 3）；**路径长度作为归档方案预览的显示项**；清理逻辑统一走扩展长度前缀 |
| I11 | 语义质量只有 **8 对我自造的**相关/无关样本，不足以验收 | **OPEN** | docs/RISKS 2.4 | 可能"模型跑通但检索难用" | 用户给 Q5 的 20 条真实查询 → 建 G15 Recall@10 |
| I12 | 向量检索未选型：404 万块 fp32 = 7.71GB，暴力扫需要 8GB 级内存装不下 | **OPEN** | p6 `scale` | 阶段 6 起不来 | 用户就 Q6 三选一；选型后必须实测建库时间，不许照搬宣传数字 |
| I13 | 语料实测 **7,768 份 / 120.6GB / 202 万页**，SPEC 写的是"约 5,000 份" | **MITIGATED** | p0 / p2 | 按错的量级算红线会全线失真 | 已按实测基线 + ×10 档重写 docs/TESTING；SPEC 待用户确认后同步 |
| I14 | 打包只验了 `--onedir`，`--onefile` 未测 | **OPEN** | p8 | 若最终要单文件分发，数据目录位置策略要重做 | 阶段 7 前明确是否要 onefile；不要就标 `WONTFIX` |
| I15 | 界面屏数与线框**未经确认**，产品界面一屏都没画 | **OPEN** | docs/UI-SCREENS、`ui/nav.py` 里 7 项 `implemented=False` | 阶段 1 只有运行时外壳；阶段 2 扫描完的结果**没有地方看** | 用户答 Q7；每屏 ≥2 个高差异黑白线框逐屏确认。阶段 1 的处置记录在 **D-018**（外壳不含布局决策，可回退） |
| I16 | 组合起来的内存上限没压测过（各组件是单点测的） | **OPEN** | p2/p3/p5/p6 各自 RSS；且本轮实测机器 **load 85%、可用内存仅 2.33GB** | G8 的 1.2GB 目前是推算不是实测；机器不是空载的 | 阶段 2 L4 实测：UI + 索引 + 一个后台任务同时活的峰值；并在低可用内存时刻各跑一次 |
| I17 | **阶段 1 的所有 UI 断言与 G1 冷启动读数都在 `QT_QPA_PLATFORM=offscreen` 下取的**，真实桌面平台未核对 | **OPEN** | 冷启动 18 次读数 **0.344–1.031s**（门禁入口 13 次 0.409–0.910s、中位 0.486s）全部 offscreen；offscreen 不做窗口合成与真实字体加载，**通常比真机快**。读数分散的**成因未查明**：入口方式、平台、并发负载、时间漂移四种解释都试过且都不成立或被撤回，明细见 `VERIFICATION` 4.10 | 验收 1「能启动能关闭」在编程意义上成立，但"首屏看起来对不对、真机多少秒"没有人看过 | 你在桌面上真跑一次 `python main.py`，截图首屏 + 给出状态页显示的冷启动数；G1 若按真机数字重定，同步改 `gates/stage1.py` 的 `G1_COLD_START_MAX` 一处 |
| I18 | 应用**没有 GUI 错误提示**：装配失败只写 `crash.log` + stderr + 退出码 2，双击图标的人看到的是"闪退" | **OPEN** | `test_装配失败时组合根返回非0并把堆栈写进crash_日志`；`app.run` 的失败分支 | 双击启动失败时用户拿不到任何信息，只能去翻日志目录 —— 而日志目录在哪他也不知道 | 「错误上报屏 / 系统托盘提示」属于 Q7 的界面范围，等 Q7 之后补；阶段 1 故意没做（不做没确认过的界面）。临时缓解：`README` 与 `个人用的启动方式.md` 写明失败时先看 `<数据根>\logs\crash.log` |
| I19 | 事件词表与 **watchdog 版本**耦合：`_WATCHDOG_KINDS` 只收 created/deleted/modified/moved，新版本新增的类型被显式忽略 | **MITIGATED** | 阶段 2 实测事故：处理器缺 `dispatch` 时 observer 线程在第一条事件上死掉而界面毫无察觉（`watched_roots` 照旧 1）；watchdog 6.0 还会发 opened/closed/closed_no_write | 升级 watchdog 后某类变化不再进事件流，而周期校验会悄悄兜住 → 表现为"索引变慢"而不是"坏了" | 升级 watchdog 必须重跑 `tests/integration/test_watcher_events.py`（10 条，含 `test_watchdog新增的事件类型不许把处理器打死`）；`BackgroundState.watcher_alive` + 状态页 ⚠ 行是死亡的唯一出口 |
| I20 | **真实用户目录**首次扫描的失败面未知：长路径（I10）、权限拒绝、网络盘、符号链接环都只在 `tmp_path` 上验过 | **OPEN** | 阶段 2 全部 e2e 跑在临时目录（ROADMAP 末行禁令：Q8 未答前 `fs/scanner` 只许在临时目录跑） | 真语料 7,768 份 / 120.6GB 首扫时可能出现"整批扫不动但只报了一条错"或"半个盘被判缺失" | Q8 给出监测范围后，首扫必须带 `exclude` 白名单 + 分批 + `MAX_ERROR_MESSAGES` 封顶读数，并留下真机数字（G3/G7/G8/L4 一起做） |

## 附 · I3 的 `pip check` 原文

```
rapidocr-onnxruntime 1.4.4 requires onnxruntime, which is not installed.
```

**这一行是预期的，不要去"修"它。** 修它的办法是把纯 `onnxruntime` 装回来，而那正是
docs/VERIFICATION 2.2 里 `import onnxruntime` 段错误（exit 139）的成因。

## 附 · 归并过的同类问题（防止逐个打补丁）

| 类别 | 一次声明的规则 | 已覆盖的实例 |
| --- | --- | --- |
| 「库没坏，是我调错方法」 | 判定不可用之前必须先核对**真实签名**，再收紧断言 | p3 QtPdf 的 `render/close/metaData/getAllText(page)`；`QFontDatabase.families()` 是静态方法 |
| 「断言能骗过」 | 每条新断言先用坏法真注入一次，做不到就删掉 | docs/TESTING 四 · **46 条**坏法（1–18 阶段 1，19–46 阶段 2），含 2 条已删除的假断言与 2 条**因坏法测不到而重写过的测试**（假 `exc_info` 对象、假 handler 类） |
| 「接第三方库的回调」 | 测试必须 **import 产品里的那个类/函数**，不许在测试里另写一个形状相同的等价物 —— 否则测的是测试自己 | watchdog `_BufferHandler` 缺 `dispatch`（I38–I41）、`threading.ExceptHookArgs` 没有 `exc_info`（I42）；两者都是"链路看起来通了，其实一次都没通过" |
| 「阈值拍脑袋」 | 阈值只有两种合法来源：实测单耗 × 量级反算，或标注 **[约定]** 待确认 | G1/G12 **[约定]**；其余 **[反算]** |
| 「同一个概念两处存放」 | 每个核心概念**先定唯一存放处 + 唯一口径**，再写代码；有第二处就必须说明谁读哪个 | 用户设置→`settings.json`、内部状态→`app_settings`（D-019）；时间→库内 UTC 秒 / 日志 UTC `Z`（D-022）；冷启动→`state.log` 的 `window.ready`（D-021）；分类"已种过"→`app_settings` 标记而不是判空表（D-020） |
| 「编码不是 bug 是口径」 | 产品侧日志文件一律 UTF-8；测试与门禁的 `subprocess` 收发一律显式 `encoding="utf-8", errors="replace"` | p0/p2/p5/p6 探针；阶段 1 的 `gates/stage1.py` 与 `test_进程级冷启动实测符合G1约定` |
| 「乱码不是 bug 是编码」 | 探针统一 `stdout.reconfigure(utf-8)` + 结果写 UTF-8 JSON | p0/p2/p5/p6 的中文输出 |
