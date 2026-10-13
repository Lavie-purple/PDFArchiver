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

## R-004 · 2026-10-14 · 目录骨架先建后填

`src/pdfarchiver/` 的 11 层目录用 `.gitkeep` 占位，`gates/`、`tests/{unit,integration}` 同理。
**约定**：某一层开始有真实代码时，删掉那一层的 `.gitkeep`。
空目录不是"已经实现"，`docs/ARCHITECTURE.md` 的依赖方向表才是约束。

## R-005 · 命名与放置规则（供后续新增文件时对照）

| 类型 | 放哪 | 命名 |
| --- | --- | --- |
| 实测证据 | `docs/VERIFICATION.md` 正文 + `.probe_work/*.json`（不入库） | 探针 `pN_<主题>.py`，产物同名 `.json` |
| 决策 | `docs/DECISIONS.md` 追加一条 `D-0NN` | 一条一段，含被否方案 |
| 问题/风险 | 已知事实进 `docs/ISSUES.md`（`I-N`）；需人拍板进 `docs/RISKS.md`（`2.N`）；待验证的进 `docs/DECISIONS.md` 候选 | 三本不混用 |
| 阶段结论 | `docs/stage-reports/阶段N-交付报告.md` | 一份一阶段，写完不改历史，只追加"更正" |
| 门禁 | `docs/TESTING.md` 的 `G-N` + 阶段 7 起 `gates/NN_名字.py` | 阈值必须标 `[反算]` 或 `[约定]` |
