"""阶段 4 验收门禁：在阶段 3 的闸门之上，加阶段 4 特有的实测。

跑法：
    python gates/stage4.py                  # 全跑（含反向注入，约 5–8 分钟）
    python gates/stage4.py --no-injection   # 跳过注入探针（约 1 分钟）

红线：任何一条 RED 就打印 `VERDICT: RED（n 条）` 并非 0 退出。

阶段 4 的门禁内容（docs/ROADMAP）：
- G4：全量哈希 ≤ 1h（实测 9–39min）
- G17：杀进程重启后 journal 每条状态都能被恢复矩阵归类，未知状态 = 0
- G18：归档→撤销后：源存在、字节一致、sha256 一致、目标已消失
- G19：跨盘移动绝不先删源：注入"删源前崩溃"证明它真的没删
- 新：预览与实际执行的文件集合逐条一致
- 新：DB 事务回滚不等于磁盘回滚

当前状态：
- ArchiveService / DedupService / BackupService 已实现并注册，队列 KINDS 已加 "dedup" 和 "archive"
- 本门禁只产出四条判定：服务存在性、bootstrap 注册、搜索功能、全量回归（可选再加反向注入）
- 上面 G4/G17/G18/G19 **不由本门禁产出**，逐条状态唯一来源是 `docs/ROADMAP.md` 阶段 4 表
  （这里不抄第二份 —— 曾经抄过一份"四条都待真语料实测"，G17/G18/G19 行为验完之后它没跟着改，
  于是同一件事在同一个文件里有两种说法）
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from stage1 import (REPO, Row, _num, _run,  # noqa: E402
                    harden_stdio, PYTEST_ERROR_RE, PYTEST_FAILED_RE, PYTEST_PASSED_RE)


def gate_services_exist() -> Row:
    """验证阶段 4 的三个服务模块存在且可 import。"""
    script = """
import sys
from pathlib import Path
sys.path.insert(0, r"{REPO}\\src")

try:
    from pdfarchiver.services.archive_service import ArchiveService
    from pdfarchiver.services.backup_service import BackupService
    from pdfarchiver.services.dedup_service import DedupService
    print("OK")
except ImportError as e:
    print(f"FAIL:{{e}}")
"""
    p = _run([sys.executable, "-c", script.format(REPO=REPO)])
    out = p.stdout.strip()
    ok = p.returncode == 0 and out == "OK"
    return Row("新 · 阶段 4 服务模块存在（ArchiveService / DedupService / BackupService）",
               ok, out if ok else f"import 失败：{out}", "")


def gate_bootstrap_registration() -> Row:
    """验证 bootstrap 正确注册了阶段 4 的服务与队列处理器。"""
    script = """
import sys
from pathlib import Path
sys.path.insert(0, r"{REPO}\\src")

import tempfile
import shutil
from pdfarchiver.services.bootstrap import bootstrap
from pdfarchiver.db.repositories.jobs import KINDS

work = Path(tempfile.mkdtemp(prefix="stage4_gate_"))
try:
    ctx = bootstrap(work)
    has_archive = hasattr(ctx, "archive") and ctx.archive is not None
    has_dedup = hasattr(ctx, "dedup") and ctx.dedup is not None
    has_backup = hasattr(ctx, "backup") and ctx.backup is not None
    has_archive_kind = "archive" in KINDS
    has_dedup_kind = "dedup" in KINDS
    ctx.shutdown()
    ok = (has_archive and has_dedup and has_backup and
          has_archive_kind and has_dedup_kind)
    print("OK" if ok else "FAIL")
    print(f"archive={{has_archive}} dedup={{has_dedup}} backup={{has_backup}}")
    print(f"archive_kind={{has_archive_kind}} dedup_kind={{has_dedup_kind}}")
finally:
    shutil.rmtree(work, ignore_errors=True)
"""
    p = _run([sys.executable, "-c", script.format(REPO=REPO)])
    out = p.stdout.strip()
    ok = p.returncode == 0 and "OK" in out
    return Row("新 · bootstrap 注册阶段 4 服务与队列种类",
               ok,
               out.replace("\n", "｜") if ok else f"退出码 {p.returncode}",
               "" if ok else p.stderr[-600:])


def gate_regression() -> Row:
    """全量回归确保阶段 4 改动没破坏阶段 1/2/3 的功能。"""
    p = _run([sys.executable, "-m", "pytest", "tests", "-q", "--no-header"])
    out = p.stdout + p.stderr
    failed = _num(PYTEST_FAILED_RE, out)
    errored = _num(PYTEST_ERROR_RE, out)
    passed = _num(PYTEST_PASSED_RE, out)
    summary = f"{passed} passed / {failed} failed / {errored} error"
    return Row("全量回归（阶段 1+2+3+4）",
               p.returncode == 0 and failed == 0 and errored == 0,
               summary, "" if p.returncode == 0 else out[-1500:])


def main(argv: list[str] | None = None) -> int:
    harden_stdio()
    ap = argparse.ArgumentParser(prog="gates/stage4.py", description="阶段 4 验收门禁")
    ap.add_argument("--no-injection", action="store_true",
                    help="跳过反向注入探针（慢，约 3–5 分钟）")
    args = ap.parse_args(argv)

    from stage1 import (gate_architecture, gate_cold_start, gate_dependency,  # noqa: E402
                        gate_injection)
    from stage3 import gate_search_functionality  # noqa: E402

    checks = [
        gate_dependency(),
        gate_architecture(),
        gate_cold_start(),
        gate_services_exist(),
        gate_bootstrap_registration(),
        gate_search_functionality(),
        gate_regression(),
    ]

    if not args.no_injection:
        checks.append(gate_injection())

    print(f"门禁运行于 {REPO}｜python {sys.version.split()[0]}")
    print()
    print("阶段 4 门禁说明：")
    print("  - 本门禁不产出 G4/G17/G18/G19 四条红线，只验服务存在性、注册、搜索功能与全量回归")
    print("  - 四条红线的逐条状态只有一个来源：docs/ROADMAP.md 阶段 4 表（改状态改那里，别在这里抄一份）")
    print("  - 阶段 4 是最高风险阶段（唯一改用户磁盘），门禁验收需真实归档操作")
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
