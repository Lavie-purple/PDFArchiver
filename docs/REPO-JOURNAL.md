# 工程整理记录

AGENTS.md 元规则要求的入职手册件之一：记录**仓库结构、命名规则、忽略规则**的变更，
免得下一个人（或下一个会话）猜为什么这里长这样。

## R-001 · 2026-10-14 · 文档从数字编号改成规范文件名

**改前**：`docs/00-阶段0验证结论.md` … `docs/08-阶段0交付报告.md`（数字前缀只为排序）。
**改后**：按用途命名 —— `VERIFICATION / ARCHITECTURE / DATABASE / ROADMAP / TESTING / DECISIONS / CHANGELOG`，
加支撑件 `RISKS / UI-SCREENS / ISSUES / stage-reports/`。
**原因**：用户指定的工程文档口径就是这套名字；数字编号会让"文档属于第几阶段"和"文档是什么"混成两个口径，
阶段推进后编号顺序就乱了（`00` 已经出现两次改序）。
**连带处理**：全部交叉引用一次改写（15 个文件，含 `requirements/*.txt`、探针 docstring、守卫 docstring），
改完 `grep -rn "docs/0[0-8]"` 为空；用 `git mv` 保留历史。

## R-002 · 2026-10-14 · `PROJECT_SPEC.md` 不入库

**规则**：AGENTS.md 把「需求契约 / 工时埋点 / AI 记忆文件」列在本机工作文件区，仓库根只该有 `README.md` 与产品代码。
**动作**：`.gitignore` 追加 `PROJECT_SPEC.md`（原条目 `SPEC.md` 匹配不到这个文件名）。
**影响**：仓库里的文档引用了一个不在仓库里的文件。要改回来的方式：删掉 `.gitignore` 里那一行并提交，
不需要改任何文档内容。这条是**可逆的结构决定，不是技术结论**。

## R-003 · 2026-10-14 · 提交前的隐私扫描入口

`.probe_work/` 与 `project_stats.md` 里含真实目录名与真实文件名，已全部 gitignore。
规则：commit 前跑一次
`git grep -nI -e "<用户名>" -e "<私人目录名>" -- .`，命中即改。
已出过一次：`docs/00` 的扫描根列表和 p0 的 docstring 里写了本机用户名，见提交 `0e808d0`。

## R-004 · 2026-10-14 · 目录骨架先建后填（阶段 1 已按约定销账）

`src/pdfarchiver/` 的 11 层目录用 `.gitkeep` 占位，`gates/`、`tests/{unit,integration}` 同理。
**约定**：某一层开始有真实代码时，删掉那一层的 `.gitkeep`。
空目录不是"已经实现"，`docs/ARCHITECTURE.md` 的依赖方向表才是约束。

阶段 1 收尾时逐层核对并删除了 8 个占位：`config`、`db/migrations`、`db/repositories`、`diagnostics`、
`fs`、`services`、`ui/pages`、`gates`。
**仍然保留 8 个**，因为那 8 层真的还没有代码 —— `backup` `fileops` `indexing` `jobs` `ocr` `parsing`
`search` `semantic`。留着占位是诚实的做法：删掉就变成"目录不存在"，看仓库的人会以为设计里没有这一层。

## R-006 · 2026-10-14 · 阶段 1 落地时的三类"验证物"分界

填代码时同时冒出三种"跑一下看对不对"的东西，不划清界线就会互相抄、互相冒充。本项目的分界：

| 种类 | 位置 | 特点 | 什么时候跑 |
| --- | --- | --- | --- |
| 探针 | `tests/probes/pN_<主题>.py` | 验证**技术前提**（依赖、平台、量级），一次性、可重跑、产物写 `.probe_work/`、末尾 `VERDICT` | 换机器/换依赖/怀疑环境 |
| 守卫 | `tests/guards/test_<规则>.py` | 验证**结构规则**（依赖方向、SQL 位置、依赖版本、迁移不丢数据），常驻、每次改动都跑 | 每次改动 + 门禁链 |
| 断言自证 | `tests/probes/p9_reverse_injection.py` | 不验产品，验**测试自己有没有牙齿**：把坏法注进临时副本，要求对应测试必红 | 每阶段收尾（已进门禁链） |

守卫和断言自证的区别就是：守卫红 = 代码违反了规则；p9 红 = 规则写在测试里但**抓不住违反**。
两者都进 `gates/stage1.py`，末行统一 `VERDICT: ALL GREEN`。

## R-007 · 2026-10-14 · `gates/` 从空目录变成一条命令

阶段 0 的 `gates/` 是 `.gitkeep`。阶段 1 落第一个真门禁 `gates/stage1.py`（G21 → 架构守卫 → 全量回归 →
冷启动实测 → 反向注入），并**验证过门禁自己会变红**（副本里弄坏产品代码 / 把阈值改成不可达到，两次都 `exit=1`）。
`docs/TESTING` 五 里 01–09 那份清单是**阶段 7 的目标形态**，没到对应阶段就不建空文件 ——
空门禁比没门禁更危险，它让人以为查过了。

## R-005 · 命名与放置规则（供后续新增文件时对照）

| 类型 | 放哪 | 命名 |
| --- | --- | --- |
| 实测证据 | `docs/VERIFICATION.md` 正文 + `.probe_work/*.json`（不入库） | 探针 `pN_<主题>.py`，产物同名 `.json` |
| 决策 | `docs/DECISIONS.md` 追加一条 `D-0NN` | 一条一段，含被否方案 |
| 问题/风险 | 已知事实进 `docs/ISSUES.md`（`I-N`）；需人拍板进 `docs/RISKS.md`（`2.N`）；待验证的进 `docs/DECISIONS.md` 候选 | 三本不混用 |
| 阶段结论 | `docs/stage-reports/阶段N-交付报告.md` | 一份一阶段，写完不改历史，只追加"更正" |
| 门禁 | `docs/TESTING.md` 的 `G-N` 编号 + **每阶段一个** `gates/stageN.py`（阶段 7 才拆成 `NN_名字.py` 串行） | 阈值必须标 `[反算]` 或 `[约定]`；末行必须 `VERDICT: ALL GREEN` |
| 结构规则 | `tests/guards/test_<规则>.py` | 一条规则一个文件，能独立跑并打印 `VERDICT`，同时被 pytest 收集 |
| UI 新增一屏 | 先登记 `src/pdfarchiver/ui/nav.py`（`NavItem`，按 **SPEC 条款号**写 `spec`），再建 `ui/pages/<页名>.py` | 未经 Q7 确认的屏一律 `implemented=False` + `blocked_by` 写清卡在哪个决定；页面不许自己拼路径、开连接、写 SQL（守卫会红） |
