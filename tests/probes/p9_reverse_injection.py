"""P9 反向注入探针：证明阶段 1 的每条硬断言真的能变红。

AGENTS.md 的规矩是「每写完一条断言，先用能骗过它的坏法真注入一次；不会变红的断言直接删」。
这里做的就是把"坏法"批量注入一遍，看每条断言是否**必然**失败：

  注入后仍然全绿  ⇒  这条断言是摆设，必须删或重写
  注入后变红      ⇒  这条断言有约束力

跑法：python tests/probes/p9_reverse_injection.py
末行 VERDICT: ALL GREEN 表示 18 条坏法全部被抓到。

两件事先说清，免得结论被误读：
1. **不碰工作区**。每次注入都在系统临时目录里复制一份 `src/` + `tests/` + 入口文件后进行，
   产品代码从头到尾没被改写过一次（复制失败就直接退出，不做无备份的修改）。
2. 先跑一遍**未注入**的基线。没有这一步，"注入后变红"可能只是复制环境跑不起来，
   那不算证据。
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
COPY_ITEMS = ("src", "tests", "conftest.py", "main.py")

ARCH = "tests/guards/test_architecture.py::test_架构守卫全绿"
STAMP = "tests/integration/test_error_handling.py::test_三个日志出口用同一个时间口径"


@dataclass(frozen=True)
class Edit:
    """对副本里某个文件做一次替换或追加。anchor 必须恰好命中一次，否则判「注入失效」。"""

    path: str
    anchor: str
    replacement: str
    append: bool = False


@dataclass(frozen=True)
class Case:
    inject: str  # 坏法的编号，对应用户给的编号方案
    坏法: str  # 人话：这次假装做对了什么
    node: str  # 应该因此变红的测试
    edits: list[Edit] = field(default_factory=list)


CASES: list[Case] = [
    Case("1", "UI 越过 services 直接 import db 层", ARCH,
         [Edit("src/pdfarchiver/ui/pages/status_page.py", "",
               "\nfrom pdfarchiver.db import engine as _probe  # 注入：反向依赖\n", append=True)]),
    Case("2", "把 SQL 写到能力层（services）里", ARCH,
         [Edit("src/pdfarchiver/services/status_service.py", "",
               '\nPROBE_SQL = "SELECT count(*) FROM documents"  # 注入：SQL 漏到服务层\n', append=True)]),
    Case("3", "用 except Exception: pass 把故障咽下去", ARCH,
         [Edit("src/pdfarchiver/config/paths.py", "",
               "\n\ndef _probe_swallow(p):\n    try:\n        return open(p)\n    except Exception:\n        pass\n",
               append=True)]),
    Case("4", "导航注册表里塞进重复的 page_id", ARCH,
         [Edit("src/pdfarchiver/ui/nav.py", "",
               '\nNAV_ITEMS.append(NavItem(PAGE_STATUS, "重复入口", "probe", False))  # 注入\n', append=True)]),
    Case("5", "阶段 1 就提前建出全文索引表 content_fts",
         "tests/integration/test_bootstrap_and_migration.py::test_阶段1刻意不建的表确实不存在",
         [Edit("src/pdfarchiver/db/migrations/0001_initial.py", "        APP_SETTINGS,\n    ]",
               '        APP_SETTINGS,\n        "CREATE TABLE content_fts(x TEXT)",\n    ]')]),
    Case("6", "取消「没有快照目录就拒绝迁移」这条护栏",
         "tests/integration/test_bootstrap_and_migration.py::test_没有快照目录就拒绝迁移",
         [Edit("src/pdfarchiver/db/migrate.py", "        if backup_dir is None:", "        if False:")]),
    Case("7", "迁移失败时不回滚，直接把半成品提交",
         "tests/integration/test_bootstrap_and_migration.py::test_迁移中途失败回到原样",
         [Edit("src/pdfarchiver/db/migrate.py", "        conn.rollback()", '        conn.execute("COMMIT")')]),
    Case("8", "重复扫描时连索引状态一起覆盖掉",
         "tests/integration/test_repositories.py::test_同一路径重复写只留一条且只刷新文件事实",
         [Edit("src/pdfarchiver/db/repositories/documents.py",
               "ctime_ns=excluded.ctime_ns, file_id=excluded.file_id,",
               "ctime_ns=excluded.ctime_ns, file_id=excluded.file_id, parse_status=excluded.parse_status,")]),
    Case("9", "只看表空不空，忽略「已种过」标记",
         "tests/integration/test_repositories.py::test_默认模板种过就不再长回来",
         [Edit("src/pdfarchiver/services/default_catalog.py",
               "    if app_settings.get(_SEEDED_KEY) is True:", "    if False:")]),
    Case("10", "状态页的标签数写死成 0",
         "tests/integration/test_app_shell.py::test_刷新按钮重查数据库",
         [Edit("src/pdfarchiver/services/status_service.py",
               "            tags=self.catalog.count_tags(),", "            tags=0,")]),
    Case("11", "在未实现的屏上摆假控件充数",
         "tests/integration/test_app_shell.py::test_未实现页不放任何假控件",
         [Edit("src/pdfarchiver/ui/pages/pending_page.py", "        lay.addStretch(1)",
               '        self.probe = QtWidgets.QPushButton("假的重建索引按钮")\n        lay.addWidget(self.probe)')]),
    Case("12", "关窗只关窗口，连接与对账行都不管",
         "tests/integration/test_app_shell.py::test_关窗真的关掉连接并留下对账行",
         [Edit("src/pdfarchiver/ui/main_window.py", "        self.ctx.shutdown()", "        pass")]),
    Case("13", "不往 state.log 写 window.ready（门禁就没有数字可读）",
         "tests/integration/test_app_shell.py::test_进程级冷启动实测符合G1约定",
         [Edit("src/pdfarchiver/app.py",
               '        state_event(ctx.paths.logs_dir, "window.ready", cold_start_seconds=round(cold, 3))',
               "        pass")]),
    Case("14", "把 G1 阈值调到不可能达到，验证实测数字真的在参与判定",
         "tests/integration/test_app_shell.py::test_进程级冷启动实测符合G1约定",
         [Edit("tests/integration/test_app_shell.py", "assert cold <= 1.5,", "assert cold <= 0.0001,")]),
    Case("15", "身份键少做一次 casefold",
         "tests/unit/test_identity.py::test_身份键全小写",
         [Edit("src/pdfarchiver/fs/identity.py", "    return normalize_path(raw).casefold()",
               "    return normalize_path(raw)")]),
    Case("16", "日志戳用裸本地时间却标成 Z（格式对、时刻错）",
         STAMP,
         [Edit("src/pdfarchiver/diagnostics/logs.py",
               '    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")',
               '    return datetime.now().isoformat(timespec="milliseconds") + "Z"')]),
    Case("17", "app.log 行首退回标准库默认的本地无偏移时间",
         STAMP,
         [Edit("src/pdfarchiver/diagnostics/logs.py",
               "        return (datetime.fromtimestamp(record.created, timezone.utc)\n"
               '                .isoformat(timespec="milliseconds").replace("+00:00", "Z"))',
               '        return datetime.fromtimestamp(record.created).isoformat(timespec="milliseconds")')]),
    Case("18", "把开发机自己的路径当默认值写进服务层（验收 6）", ARCH,
         [Edit("src/pdfarchiver/services/status_service.py", "",
               '\nPROBE_ROOT = "C:/Users/dev/PDF归档库"  # 注入：本机路径字面量\n', append=True)]),
]


def _copy_repo(dest: Path) -> None:
    for item in COPY_ITEMS:
        src = REPO / item
        if src.is_dir():
            shutil.copytree(src, dest / item, ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache"))
        elif src.is_file():
            shutil.copy2(src, dest / item)
        else:
            raise RuntimeError(f"复制基线失败，找不到 {item}")


def _run(ws: Path, nodes: list[str]) -> tuple[int, str]:
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", *nodes, "-q", "-p", "no:cacheprovider", "--no-header"],
        cwd=str(ws), env={**os.environ, "QT_QPA_PLATFORM": "offscreen", "PYTHONIOENCODING": "utf-8"},
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600)
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def _apply(ws: Path, case: Case) -> None:
    for edit in case.edits:
        path = ws / edit.path
        text = path.read_text(encoding="utf-8")
        if edit.append:
            path.write_text(text + edit.replacement, encoding="utf-8")
            continue
        hits = text.count(edit.anchor)
        if hits != 1:
            raise RuntimeError(f"注入锚点命中 {hits} 次（要求恰好 1 次）：{edit.path} :: {edit.anchor!r}")
        path.write_text(text.replace(edit.anchor, edit.replacement), encoding="utf-8")


def _verdicts(out: str) -> tuple[int, int, int]:
    def num(pat: str) -> int:
        m = re.search(rf"(\d+) {pat}", out)
        return int(m.group(1)) if m else 0

    return num("failed"), num("error"), num("passed")


def main() -> int:
    ws = Path(tempfile.mkdtemp(prefix="p9_reverse_injection_"))
    try:
        _copy_repo(ws)
        targets = sorted({c.node for c in CASES})
        rc, out = _run(ws, targets)
        failed, errored, passed = _verdicts(out)
        print(f"基线（未注入）：{passed} 条通过 / {failed} 失败 / {errored} 错误，exit={rc}")
        if rc != 0:
            print(out[-3000:])
            print("VERDICT: RED（基线就没过，后面的注入结论全部不作数）")
            return 1

        results = []
        for case in CASES:
            one = Path(tempfile.mkdtemp(prefix="p9_case_"))
            try:
                _copy_repo(one)
                _apply(one, case)
                rc, out = _run(one, [case.node])
                failed, errored, passed = _verdicts(out)
                caught = rc != 0 and failed >= 1 and errored == 0
                first = next((ln for ln in out.splitlines()
                              if ln.startswith("E   ") or "AssertionError" in ln
                              or "ArchitectureError" in ln or "Failed" in ln), "")
                results.append((case, caught, failed, errored, passed, first.strip()[:110]))
                print(f"  {'RED  ' if caught else 'GREEN'}  I{case.inject} {case.坏法}")
                print(f"         -> {case.node.split('::')[-1]}｜failed={failed} error={errored} passed={passed}")
                if first:
                    print(f"         原文：{first.strip()[:110]}")
            finally:
                shutil.rmtree(one, ignore_errors=True)

        missed = [r for r in results if not r[1]]
        print(f"\n抓到 {len(results) - len(missed)}/{len(results)} 条坏法")
        for case, _, _, _, _, _ in missed:
            print(f"  未抓到：I{case.inject} {case.坏法} —— 对应断言是摆设，按 AGENTS.md 必须删或重写")
        print("VERDICT: " + ("ALL GREEN" if not missed else "RED"))
        return 0 if not missed else 1
    finally:
        shutil.rmtree(ws, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
