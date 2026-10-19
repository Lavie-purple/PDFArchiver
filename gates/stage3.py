"""阶段 3 验收门禁：在阶段 2 的闸门之上，加阶段 3 特有的实测。

跑法：
    python gates/stage3.py                  # 全跑（含反向注入，约 5–8 分钟）
    python gates/stage3.py --no-injection   # 跳过注入探针（约 1 分钟）

红线：任何一条 RED 就打印 `VERDICT: RED（n 条）` 并非 0 退出。

阶段 3 的门禁内容（docs/ROADMAP）：
- G2：搜索 P95 ≤ 500ms（基线）；短查询 LIKE 回退不得静默变 0 结果
- G11：300 文件批量事件丢失 = 0
- G12：监测根被改名后 ≤ 60s 自愈 [约定]
- 新：三种检索层级在完全没有模型文件的机器上全部可用

当前状态（2026-10-18 逐条对账，出处写在括号里）：
- G2 检索功能正确性：本门禁第一条判定就跑 `tests/integration/test_search_service.py`
- G2 性能（P95 ≤500ms）：**已实测**。真库第一次跑判 RED（P95 2,809ms），处置落地（**D-051** 甲+乙）
  后同一判据复跑 **P95 328ms → GREEN**（`docs/VERIFICATION.md` §4.15 / §4.16）。
  入口是 `scripts/g2_search_benchmark.py`，挂在 `gates/final.py --only g2`；它绑真实库，
  所以既不在这个门禁里判，也不进全链默认段
- G11/G12（300 文件批量 / 监测根改名自愈）：待真语料实测（**ISSUES I5 / ISSUES I20**，Q8 未答）
- 三种检索层级无模型依赖：已满足（架构断言守着）
- 界面侧（S1 / S2 / S8 等）线框已逐屏确认并落地，判定在 `gates/final.py` 的 regression 与
  guards 段，本门禁不重复判
- **SPEC 阶段 3 过去"本门禁不判"的那两条，现在各有一条产品测试钉着**（本门禁不重复判）：
  ① 智能集合过去是名字壳 —— 建集合时 `query` 恒为 `{}`、选中集合不改变任何筛选。
  **ISSUES I78** 乙（2026-10-20）补上写路径：S1 那排 chips 旁的「存为智能集合」与「覆盖此集合」
  走 `services/collection_service.py` 的 `save` / `overwrite`，后者就是 `update_query` 在产品里的
  调用点。判定在 `tests/integration/test_saved_search_ui.py`（23 条，坏法见 p21 注入 24 条）。
  ② 文档↔分类/标签过去在产品里没有写路径。**ISSUES I78** 甲（2026-10-19）：S1 表格底下那排
  「归入分类 / 加标签 / 移除标签」写 `link_categories` / `link_tags` / `unlink_tags`，S8 右键写
  `reparent_category` / `merge_categories` 并在删除前调 `docs_in_subtree`；判定在
  `tests/integration/test_catalog_writes_ui.py`（19 条，坏法见 p9 注入 I50–I69）。
  同批剩下的最后一格 `merge_tags`（标签并入）已由**轮十五 甲**（2026-10-20）接进 S8 中栏那颗
  「并入…」，判定在 `tests/integration/test_tag_merge_ui.py`（16 条，坏法见 p24 注入 17 条）——
  **这一句本身**由那里的 `test_merge_tags在产品侧有调用点了` 钉着，不再靠这里的一句描述
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from stage1 import (REPO, Row, _num, _run,  # noqa: E402
                    PYTEST_ERROR_RE, PYTEST_FAILED_RE, PYTEST_PASSED_RE)


def gate_search_functionality() -> Row:
    """跑检索层集成测试，验证四条通道（文件名/路径/元数据/正文）功能正确。"""
    p = _run([sys.executable, "-m", "pytest", "tests/integration/test_search_service.py",
              "-q", "--no-header"])
    out = p.stdout + p.stderr
    failed = _num(PYTEST_FAILED_RE, out)
    errored = _num(PYTEST_ERROR_RE, out)
    passed = _num(PYTEST_PASSED_RE, out)
    summary = f"{passed} passed / {failed} failed / {errored} error"
    ok = p.returncode == 0 and failed == 0 and errored == 0 and passed >= 15
    note = "" if ok else out[-1500:]
    return Row("G2 检索功能正确性（四条通道 + LIKE 回退 + 转义 + 分页 + 筛选）",
               ok, summary, note)


def gate_search_no_model_dependency() -> Row:
    """验证检索层不依赖模型文件：架构守卫已禁止 ui import search，
    且 search 模块本身不 import 任何模型相关代码。"""
    p = _run([sys.executable, "tests/guards/test_architecture.py"])
    out = p.stdout + p.stderr
    green = p.returncode == 0 and "VERDICT: ALL GREEN" in out
    return Row("新 · 三种检索层级在无模型机器上全部可用（架构守卫验证）",
               green, "架构守卫全绿" if green else "架构守卫失败",
               "" if green else out[-600:])


def gate_regression() -> Row:
    """全量回归确保阶段 3 改动没破坏阶段 1/2 的功能。"""
    p = _run([sys.executable, "-m", "pytest", "tests", "-q", "--no-header"])
    out = p.stdout + p.stderr
    failed = _num(PYTEST_FAILED_RE, out)
    errored = _num(PYTEST_ERROR_RE, out)
    passed = _num(PYTEST_PASSED_RE, out)
    summary = f"{passed} passed / {failed} failed / {errored} error"
    return Row("全量回归（阶段 1+2+3）",
               p.returncode == 0 and failed == 0 and errored == 0,
               summary, "" if p.returncode == 0 else out[-1500:])


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="gates/stage3.py", description="阶段 3 验收门禁")
    ap.add_argument("--no-injection", action="store_true",
                    help="跳过反向注入探针（慢，约 3–5 分钟）")
    args = ap.parse_args(argv)

    from stage1 import (gate_architecture, gate_cold_start, gate_dependency,  # noqa: E402
                        gate_injection)

    checks = [
        gate_dependency(),
        gate_architecture(),
        gate_cold_start(),
        gate_search_functionality(),
        gate_search_no_model_dependency(),
        gate_regression(),
    ]

    if not args.no_injection:
        checks.append(gate_injection())

    print(f"门禁运行于 {REPO}｜python {sys.version.split()[0]}")
    print()
    print("阶段 3 门禁说明：")
    print("  - G2 检索性能不由本门禁产出：本门禁只验功能正确性；P95 读数的入口是 `gates/final.py --only g2`（真库绑定，不进默认链）")
    print("  - G11/G12（300 文件批量 / 监测根改名自愈）待 Q8 给出真实监测范围后实测")
    print("  - 三种检索层级无模型依赖已由架构守卫守住")
    print()

    for row in checks:
        print(f"  {'PASS' if row.ok else 'RED '}  {row.gate}")
        print(f"        实测：{row.measured}")
        if row.note:
            print(f"        现场：{row.note[:600]}")
    bad = [r for r in checks if not r.ok]
    if args.no_injection:
        # 跳过不许算成一条 PASS —— 「N 条全绿」里混一件没跑的事（ISSUES I36 同一形状）
        print("  SKIP  反向注入探针（--no-injection）—— 这一场的「全绿」不含「断言有约束力」这条")
    print()
    print(f"  合计判定 {len(checks)} 条")
    print("VERDICT: " + ("ALL GREEN" if not bad else f"RED（{len(bad)} 条未过）"))
    return 0 if not bad else 1


if __name__ == "__main__":
    raise SystemExit(main())
