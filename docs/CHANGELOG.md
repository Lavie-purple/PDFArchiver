# 变更日志

按阶段记录。版本号口径：阶段 0–7 全部走完并通过发布门禁才叫 `1.0.0`；在此之前一律 `0.x.y`，
且 `x` = 已完成的阶段号。**本文件只记实际做过并验证过的变更**，未落地的写在 `ROADMAP.md`，不写在这里。

---

## 0.0.0 · 阶段 0 环境检查与技术验证 —— 2026-10-14

**没有产品功能代码。** 本阶段交付的是"哪些技术选型在本机真的能跑"的证据，以及被证据推翻的假设。

### 新增

- **9 个技术验证探针** `tests/probes/p0..p8`，每个可独立重跑，末尾打印 `VERDICT: ALL GREEN / RED`。
- **依赖钉版守卫** `tests/guards/test_dependency_pins.py`（门禁 G21），含 4 项"坏法注入"自检。
- **分层依赖清单** `requirements/{base,ocr,semantic,dev}.txt`，每条版本钉死都附实测理由。
- **工程文档集** `docs/`：README（索引）、VERIFICATION、ARCHITECTURE、DATABASE、RISKS、TESTING、
  UI-SCREENS、ROADMAP、ISSUES、DECISIONS、CHANGELOG、REPO-JOURNAL、stage-reports/阶段0-交付报告。
  其中 8 份是从 `docs/00–08` 数字名改名来的（用 `git mv`，历史保留），改名缘由与连带引用改写见
  `docs/REPO-JOURNAL.md` R-001；DECISIONS / CHANGELOG / REPO-JOURNAL 与根 README 是本轮新建。
- **目录骨架** `src/pdfarchiver/**`（11 层，只有 `.gitkeep`，无实现）、`tests/{unit,integration}`、`gates/`。

### 已验证（可以直接依赖）

| 结论 | 证据 |
| --- | --- |
| PySide6 必须 6.8.x；6.12 导入即 `WinError 127` | p3 |
| onnxruntime 必须 ≤1.20.x；≥1.21 全部 `WinError 1114` | 逐版本二分 |
| 两个 ORT 发行版共存 → `import` **段错误 exit 139**（不是异常） | p5/p6 排障过程 |
| CUDA 不可用、DirectML 可用：OCR **6.36×**、嵌入 **7.8×** | p5/p6 |
| FTS5 `trigram` 中文可用（4 字 6.39ms）；`unicode61` 中文**静默零命中** | p1 |
| FTS5 **没有** `offsets()`；只有 `rank/snippet/bm25/highlight` | p1 |
| 外部内容表 `'delete'` 少带一列 → **静默留幽灵行** | p1 |
| 文件身份必须 `realpath`（8.3 短名把空格吃掉） | p7 |
| 监听根被改名 → **0 事件**；跨目录移动报成 `created+deleted` | p4 |
| 真实语料 **7,768 份 / 120.6GB / 202 万页 / 37.5% 纯扫描** | p0/p2 |
| `--onedir` 打包可用：247.6MB，冻结后四项依赖真实可用 | p8 |

### 改方向（被证据推翻的原计划）

- **OCR 从"索引的自动步骤"改为"用户显式触发"**：全量 101 万页需 1,144 GPU 小时（8h/天 × 143 工作日），
  而按无人值守窗口反算的预算是 284ms/页，实测 3,281ms。p5 **保持 RED**，没有调阈值凑绿。
- **量化不作为提速手段**：int8 在 DirectML 上 79.3 chunks/s，比 fp32 的 146.9 **慢 1.85×**。
- **新增一条产品级未决项**：全文索引体积外推 28–48GB（×10 档 280–480GB 不可行）→ 需选全量/子集/降密度。

### 删除

- 探针里两条**假断言**：硬编码为 `True` 的"1024 宽能显示"、以及 `is not True or ...` 式自我开脱条件。
  原则：不会变红的断言直接删，不留着制造安全感。

### 微调

- **决策编号只留一个口径**：`ARCHITECTURE.md` 五 原来自己编 D1–D10，`DECISIONS.md` 又编 D-001…，
  同一件事两套号（AGENTS.md 禁止一个概念多个口径）。现在架构表只引用 `DECISIONS.md` 的 `D-0NN`，
  并为其补登记 **D-015**（FTS5 外部内容表硬规则，规则清单本体在 `DATABASE.md` 三）、
  **D-016**（全文/向量分库）、**D-017**（阅读器渲染双通道）。
- **G21 守卫的失败消息现在打印当前解释器路径**。起因是本轮用系统 Anaconda Python 跑守卫得到 2 failed，
  消息写着"依赖树里出现了 torch"，看起来像依赖被破坏，实际是用错了解释器
  （Anaconda 里有 `torch 2.14.0`、`transformers 5.16.1`，都被 SPEC 第五节禁止）。
  `.venv` 里仍是 6 passed、独立自检 `VERDICT: ALL GREEN`。口径写进 `docs/TESTING.md` 五。
- **清掉 p7 留下的 60 层中文目录树**（最深文件路径 533 字符）。它在 `.probe_work/` 里可再生（p7 每次自己重建），
  但会让 **Git 自身的目录扫描**报 `Filename too long`，`git status` 带 `--ignored` 时直接吐警告；
  删除必须走 `\\?\` 前缀。这条实测证据已并进 `docs/ISSUES.md` I10 ——
  它说明"本机开了 LongPathsEnabled"不等于"所有工具都看得见这些路径"。

### 提交记录

| commit | 时间 | 内容 |
| --- | --- | --- |
| `ea92aec` | 2026-10-14 02:33 | 阶段 0 交付物（文档 + 探针 + 依赖清单 + 守卫 + 骨架） |
| `0e808d0` | 2026-10-14 02:37 | 从文档与探针用法示例中去掉本机用户名路径 |
| `bed65df` | 2026-10-14 02:39 | 补阶段 0 交付报告与本机资源实测值 |
| `722695b` | 2026-10-14 02:53 | 文档改名到规范名 + 本文件与 `DECISIONS.md` / `README` / `REPO-JOURNAL` |

本表同步到 `722695b`；之后的 commit 由下一次收尾时按 `git log` 追加（不预留空行）。

### 已知遗留

16 条，逐条列在 `docs/ISSUES.md`（I1–I16），其中 8 条需要用户拍板（`docs/ROADMAP.md` Q1–Q8）。
**阶段 1 不开工**，直到 Q1/Q2/Q7 有答案 —— 它们改的是表结构、产品形态和界面屏数，不是实现细节。
