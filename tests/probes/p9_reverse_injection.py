"""P9 反向注入探针：证明阶段 1–2 的每条硬断言真的能变红。

AGENTS.md 的规矩是「每写完一条断言，先用能骗过它的坏法真注入一次；不会变红的断言直接删」。
这里做的就是把"坏法"批量注入一遍，看每条断言是否**必然**失败：

  注入后仍然全绿  ⇒  这条断言是摆设，必须删或重写
  注入后变红      ⇒  这条断言有约束力

跑法：python tests/probes/p9_reverse_injection.py
末行 VERDICT: ALL GREEN 表示 46 条坏法全部被抓到（1–18 是阶段 1，19–46 是阶段 2）。
`node` 可以用空格分隔多个测试节点，要求它们**全部**变红；空格在这里不是测试名的一部分。

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
               '\nNAV_ITEMS.append(NavItem("library", "重复入口", "probe", False))  # 注入\n',
               append=True)]),
    Case("5", "把阶段 4 才定口径的分组表提前建出来",
         "tests/integration/test_bootstrap_and_migration.py::test_阶段4的表在阶段2仍然不存在",
         [Edit("src/pdfarchiver/db/migrations/0001_initial.py", "        APP_SETTINGS,\n    ]",
               '        APP_SETTINGS,\n        "CREATE TABLE duplicate_groups(x TEXT)",\n    ]')]),
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
         "tests/integration/test_status_readout.py::test_刷新按钮重查数据库",
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

    # —— 阶段 2：扫描 / 索引 / 检索 / 任务读数 ————————————————————————
    Case("19", "任务收尾不补齐工作量，状态 done 而进度停在 64/1000",
         "tests/integration/test_job_queue.py::test_进度按步长攒着写最后补齐 "
         "tests/integration/test_status_tasks.py::test_真索引一份文档后读数各栏都对",
         [Edit("src/pdfarchiver/db/repositories/jobs.py",
               ' done=coalesce(total, done), last_error=NULL WHERE id=?',
               ' last_error=NULL WHERE id=?')]),
    Case("20", "整本一页都没读出来，却把 fts_status 写成 done（虚假有效结果）",
         "tests/integration/test_index_service.py::test_打开成功但一页都没读出来算失败而不是已索引",
         [Edit("src/pdfarchiver/services/index_service.py",
               "        if verdict.text_status == TEXT_FAILED:", "        if False:")]),
    Case("21", "正文命中的页码写死成第 1 页",
         "tests/integration/test_search_service.py::test_正文通道给出页码与可高亮片段 "
         "tests/integration/test_index_service.py::test_索引完能从正文搜出命中页码与片段",
         # 锚点必须打在 `search_fts` 那条 SQL 上（bm25 是它的指纹）。
         # 第一版打在 `pages()` 的 `SELECT doc_id, page_no, ...` 上 —— 那条查询是"读整本文页"，
         # 检索结果根本不经过它，于是注入照样全绿，而这恰恰是 I21 本该抓不到的样子。
         [Edit("src/pdfarchiver/db/repositories/text.py",
               "tp.doc_id, tp.page_no, tp.body, tp.source_kind, bm25(content_fts) AS score",
               "tp.doc_id, 1 AS page_no, tp.body, tp.source_kind, bm25(content_fts) AS score")]),
    Case("22", "故障列表只查终结状态，正在重试的那条原文看不见",
         "tests/integration/test_status_tasks.py::test_重试中的任务既算重试也带着原文出现在读数里",
         [Edit("src/pdfarchiver/db/repositories/jobs.py",
               'WHERE last_error IS NOT NULL"', 'WHERE last_error IS NOT NULL'
               " AND state IN ('done','failed','cancelled')\"")]),
    Case("23", "「重试中」不看状态，早就放弃的文件永远挂在上面",
         "tests/integration/test_status_tasks.py::test_试满上限后不再算重试而是留下失败终态",
         [Edit("src/pdfarchiver/db/repositories/jobs.py",
               '            " WHERE attempts>1 AND state IN (" + _LIVE_MARKS + ") GROUP BY kind",'
               ' LIVE_STATES).fetchall()',
               '            " WHERE attempts>1 GROUP BY kind", ()).fetchall()')]),
    Case("24", "故障读数不封顶，八千条一起灌进文本框",
         "tests/integration/test_status_tasks.py::test_故障读数最多列十条并按最新优先",
         [Edit("src/pdfarchiver/services/status_service.py",
               "        rows = self.jobs.recent_errors(MAX_ERROR_LINES)",
               "        rows = self.jobs.recent_errors(1000)")]),
    Case("25", "扫描已经成功了，界面上还挂着上一次的错误",
         "tests/integration/test_status_tasks.py::test_监测根上次扫描错误显示出来且成功一次就清空",
         [Edit("src/pdfarchiver/db/repositories/roots.py",
               'last_full_scan_at=?, last_scan_error=?',
               'last_full_scan_at=?, last_scan_error=coalesce(?, last_scan_error)')]),
    Case("26", "暂停的根在读数里也标成启用",
         "tests/integration/test_status_tasks.py::test_暂停的根在读数里标出来",
         [Edit("src/pdfarchiver/services/status_service.py",
               '                mark = "已暂停" if not root.enabled else "启用"',
               '                mark = "启用"')]),
    Case("27", "total=0 也照样输出百分比（拿 0 除）",
         "tests/integration/test_status_tasks.py::test_排队中的任务算条数不算进度",
         [Edit("src/pdfarchiver/services/status_service.py", "            if total:", "            if True:")]),
    Case("28", "界面只留一个标题，不渲染任何任务读数",
         "tests/integration/test_status_readout.py::test_状态页显示扫描与索引任务的读数",
         [Edit("src/pdfarchiver/ui/pages/status_page.py",
               '        parts += ["", "== 扫描与索引任务：进度 / 错误 / 重试 ==", '
               '*bg.lines(), *tasks.lines()]',
               '        parts += ["", "== 扫描与索引任务：进度 / 错误 / 重试 =="]')]),
    Case("29", "任务读数缓存起来，刷新按钮不再重查",
         "tests/integration/test_status_readout.py::test_刷新按钮同样重查任务读数",
         [Edit("src/pdfarchiver/ui/pages/status_page.py",
               "        tasks = self.ctx.status.read_tasks(max_attempts=bg.max_attempts)",
               "        tasks = getattr(self, \"_cached\", None) or "
               "self.ctx.status.read_tasks(max_attempts=bg.max_attempts)\n"
               "        self._cached = tasks")]),
    Case("30", "定时器亮灯但不巡检，事件永远没人处理",
         "tests/integration/test_patrol_tick.py::test_巡检一轮就把脏根排成一条扫描任务",
         [Edit("src/pdfarchiver/ui/main_window.py", "",
               "\nfrom pdfarchiver.services.patrol import PatrolReport  # 注入用\n", append=True),
          Edit("src/pdfarchiver/ui/main_window.py",
               "            report = self.ctx.patrol.poll()", "            report = PatrolReport()")]),
    Case("31", "巡检异常只挡住除零，别的异常把定时器打死",
         "tests/integration/test_patrol_tick.py::test_巡检抛异常时定时器不许停并且状态栏留下原文",
         [Edit("src/pdfarchiver/ui/main_window.py",
               "        except Exception as exc:  # noqa: BLE001",
               "        except ZeroDivisionError as exc:  # noqa: BLE001")]),
    Case("32", "定时器间隔写死成默认值而不是取巡检器的口径",
         "tests/integration/test_patrol_tick.py::test_巡检定时器与巡检器同一个间隔口径",
         [Edit("src/pdfarchiver/ui/main_window.py",
               "        timer.start(int(self.ctx.patrol.poll_seconds * 1000))", "        timer.start(5000)")]),
    Case("33", "后台没起来也对界面谎报在跑",
         "tests/integration/test_status_tasks.py::test_后台没起时读数说未启动而不是说一切正常",
         [Edit("src/pdfarchiver/services/bootstrap.py", "        if self.queue is None:", "        if False:")]),
    Case("34", "监听根数恒报 0，事件流断了自己不知道",
         "tests/integration/test_status_tasks.py::test_后台起来后读数给出线程数与监听根数",
         [Edit("src/pdfarchiver/services/bootstrap.py",
               "watched_roots=len(self.watch.observed_roots) if self.watch else 0,",
               "watched_roots=0,")]),
    Case("35", "run() 忘了起后台：界面能开，任务永远没人领",
         "tests/integration/test_app_shell.py::test_进程级冷启动实测符合G1约定",
         [Edit("src/pdfarchiver/app.py",
               "    if not _start_background(ctx, window):", "    if True:")]),
    Case("36", "MATCH 表达式不转义，用户输入的 AND / 引号变成运算符",
         "tests/integration/test_search_service.py::test_查询词里的FTS运算符被当成普通字符",
         [Edit("src/pdfarchiver/indexing/fts.py",
               "    return '\"' + text.replace('\"', '\"\"') + '\"'", "    return text")]),
    Case("37", "文件已经没了还照样搜出来（SPEC 3.4 禁止的虚假有效结果）",
         "tests/integration/test_search_service.py::test_缺失文档默认不进结果但可以显式包含",
         [Edit("src/pdfarchiver/db/repositories/documents.py",
               '        clauses.append("d.missing_since IS NULL")', "        pass")]),

    # —— 38–45：阶段 2 收尾时真崩过的两类「静默失灵」————————————————
    # 这两类坏法的共同点不是"算错一个数"，而是**没有任何表面症状**：
    # observer 线程一死，根还列着、队列还在跑、界面照样说正常；崩溃钩子自己一崩，
    # 连那行 AttributeError 都不会留在任何地方。所以每条都必须有断言能咬住。

    Case("38", "watchdog 处理器退回没有基类的那一版（实测踩过的原始事故）",
         "tests/integration/test_watcher_events.py::test_处理器满足watchdog要求的回调形状",
         [Edit("src/pdfarchiver/fs/watcher.py",
               "class _BufferHandler(FileSystemEventHandler):", "class _BufferHandler:")]),
    Case("39", "dispatch 不查词表，任何事件类型都塞进缓冲区",
         "tests/integration/test_watcher_events.py::test_watchdog新增的事件类型不许把处理器打死",
         [Edit("src/pdfarchiver/fs/watcher.py",
               "        kind = _WATCHDOG_KINDS.get(event.event_type)\n        if kind is not None:",
               "        kind = event.event_type\n        if True:")]),
    Case("40", "事件词表写成 dict.fromkeys（值全是 None，四种事件一律被丢掉）",
         "tests/integration/test_watcher_events.py::test_四种文件事件各自进缓冲区并带上根",
         [Edit("src/pdfarchiver/fs/watcher.py",
               "_WATCHDOG_KINDS = {kind: kind for kind in EVENT_KINDS}",
               "_WATCHDOG_KINDS = dict.fromkeys(EVENT_KINDS)")]),
    Case("41", "取消监听只删自己字典里的 handler，不向 watchdog 退订",
         "tests/integration/test_watcher_events.py::test_取消监听之后那个根不再交来事件",
         [Edit("src/pdfarchiver/fs/watcher.py",
               "                self._observer.unschedule(watch)   # type: ignore[arg-type]",
               "                pass")]),
    Case("42", "崩溃钩子按不存在的 args.exc_info 取异常（线程现场整个丢掉）",
         "tests/integration/test_error_handling.py::test_后台线程里的异常也会留痕",
         [Edit("src/pdfarchiver/diagnostics/logs.py",
               '             "".join(traceback.format_exception(args.exc_type, args.exc_value, args.exc_traceback)))',
               '             "".join(traceback.format_exception(*args.exc_info)))')]),
    Case("43", "监听线程死了也对界面说活着",
         "tests/integration/test_status_tasks.py::test_监听线程半路死了读数当场跟着翻脸",
         [Edit("src/pdfarchiver/services/bootstrap.py",
               "                               watcher_alive=bool(self.watch.is_alive()) if self.watch else False,",
               "                               watcher_alive=True,")]),
    Case("44", "读数里不写那行 ⚠，断流说成一切正常",
         "tests/integration/test_status_tasks.py::test_监听线程死了读数必须把它说出来",
         [Edit("src/pdfarchiver/services/bootstrap.py",
               "        if not self.watcher_alive and self.watched_roots:", "        if False:")]),
    Case("45", "索引时不做哈希短路，每次都把正文重抽一遍",
         "tests/integration/test_index_service.py::test_短路索引给出的结论写在describe里",
         [Edit("src/pdfarchiver/services/index_service.py",
               "        if not doc.sha256 or doc.sha256 != digest:", "        if True:")]),
    Case("46", "扫描时不看索引状态，每一份都再排一次索引任务",
         "tests/integration/test_scan_service.py::test_再扫一遍全是未变且不重复排索引",
         [Edit("src/pdfarchiver/services/scan_service.py",
               "    return fts_status in NEEDS_INDEX_STATUSES", "    return True")]),
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
        targets = sorted({t for c in CASES for t in c.node.split()})
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
                rc, out = _run(one, case.node.split())
                failed, errored, passed = _verdicts(out)
                caught = rc != 0 and failed >= 1 and errored == 0
                first = next((ln for ln in out.splitlines()
                              if ln.startswith("E   ") or "AssertionError" in ln
                              or "ArchitectureError" in ln or "Failed" in ln), "")
                results.append((case, caught, failed, errored, passed, first.strip()[:110]))
                print(f"  {'RED  ' if caught else 'GREEN'}  p9 注入 I{case.inject} {case.坏法}")
                print("         -> " + " + ".join(t.split("::")[-1] for t in case.node.split())
                      + f"｜failed={failed} error={errored} passed={passed}")
                if first:
                    print(f"         原文：{first.strip()[:110]}")
            finally:
                shutil.rmtree(one, ignore_errors=True)

        missed = [r for r in results if not r[1]]
        print(f"\n抓到 {len(results) - len(missed)}/{len(results)} 条坏法")
        for case, _, _, _, _, _ in missed:
            print(f"  未抓到：p9 注入 I{case.inject} {case.坏法} —— 对应断言是摆设，按 AGENTS.md 必须删或重写")
        print("VERDICT: " + ("ALL GREEN" if not missed else "RED"))
        return 0 if not missed else 1
    finally:
        shutil.rmtree(ws, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
