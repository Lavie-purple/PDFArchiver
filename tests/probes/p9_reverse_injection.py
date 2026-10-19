"""P9 反向注入探针：证明阶段 1–2 的每条硬断言真的能变红。

AGENTS.md 的规矩是「每写完一条断言，先用能骗过它的坏法真注入一次；不会变红的断言直接删」。
这里做的就是把"坏法"批量注入一遍，看每条断言是否**必然**失败：

  注入后仍然全绿  ⇒  这条断言是摆设，必须删或重写
  注入后变红      ⇒  这条断言有约束力

跑法：python tests/probes/p9_reverse_injection.py
末行 VERDICT: ALL GREEN 表示 69 条坏法全部被抓到（1–18 是阶段 1，19–46 是阶段 2，
47 是 **ISSUES I94** 的守卫在场性，48–49 是 **ISSUES I67** 甲 那颗「送去识别」的两侧，
50–69 是 **ISSUES I78** 甲：S1 那排「归入 / 加标签 / 移除标签」与 S8 右键菜单，
`tests/integration/test_catalog_writes_ui.py` 里 19 条断言一条不落）。
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
    # —— **ISSUES I94** 甲：方向表键的在场性 —————————————————————
    # 归并表把「自检喂的好例子必须在生产可达」定成红（**ISSUES I92**），这条是它的
    # 反向同族：**判据本身不可达**。往 FORBIDDEN_IMPORTS 里塞一个 src 下根本不存在的
    # 层名当键，那一行的 check_import_direction 一个 .py 都扫不到，永远满足。
    # 只有新增的 check_direction_keys_reach_files 会红，且必须精确点名。
    Case("47", "方向表里塞一个 `src/pdfarchiver/` 下不存在的层名当键（空转的守卫）",
         "tests/guards/test_architecture.py::test_方向表每个键至少扫到一个文件",
         [Edit("tests/guards/test_architecture.py",
               '    "diagnostics": ("pdfarchiver.ui", "pdfarchiver.services", "pdfarchiver.db"),\n}',
               '    "diagnostics": ("pdfarchiver.ui", "pdfarchiver.services", "pdfarchiver.db"),\n'
               '    "madeup_layer": ("pdfarchiver.ui",),  # 注入：src 下没有这个目录\n}'),
          ]),
    # —— **ISSUES I67** 甲：S1 那颗「送去识别」（2026-10-19 轮十四 A）———————————
    # 这条入口的两侧各注一次：禁用态（没有当前行时按不动）与接线（按下去真的调服务）。
    # 后者同时把「回执由界面自己编」注进去 —— 那正是 **ISSUES I60** 抓过的那类第二个口径。
    Case("48", "把「送去识别」建成可用态，没有当前行也按得动",
         "tests/integration/test_ocr_entry_ui.py::test_没有当前行时那颗按钮是禁用的",
         [Edit("src/pdfarchiver/ui/pages/library_page.py",
               '        self.ocr_btn.setObjectName("searchBtn")\n        self.ocr_btn.setEnabled(False)',
               '        self.ocr_btn.setObjectName("searchBtn")')]),
    Case("49", "按钮还在但不调服务，回执由界面自己编一份",
         "tests/integration/test_ocr_entry_ui.py::test_按下扫描件后排一条而状态条说得出这一条 "
         "tests/integration/test_ocr_entry_ui.py::test_request_ocr在产品侧有调用点了",
         [Edit("src/pdfarchiver/ui/pages/library_page.py",
               "            request = self.ctx.ocr.request_ocr([self._selected_doc_id])",
               "            from pdfarchiver.services.ocr_service import OcrRequest\n"
               "            request = OcrRequest(named=1, queueable=1, enqueued=1)  # 注入：自己数")]),
    # —— **ISSUES I78** 甲：S1 那排「归入 / 加标签 / 移除标签」+ S8 右键菜单（2026-10-19 轮十四 B）——
    # 这一批每条对应 `tests/integration/test_catalog_writes_ui.py` 里的一条断言，一条不落。
    # 注：I50 想注的那一行（建按钮时的 `setEnabled(False)`）**删掉不会变红** —— `__init__` 末尾
    # 还有一句 `refresh_enabled()` 把三颗按钮按住。真正承重的是那个判据本身，所以两条各注一侧。
    Case("50", "可用性判据恒真：没有点名对象三颗按钮也亮着",
         "tests/integration/test_catalog_writes_ui.py::test_没有选中任何行时三颗按钮都是死的",
         [Edit("src/pdfarchiver/ui/catalog_links.py",
               "        on = bool(self._selected_ids())",
               "        on = True  # 注入：常驻可点")]),
    Case("51", "可用性判据恒假：点名了也不亮（入口等于没有）",
         "tests/integration/test_catalog_writes_ui.py::test_选中一行后三颗一起亮起来",
         [Edit("src/pdfarchiver/ui/catalog_links.py",
               "        on = bool(self._selected_ids())",
               "        on = False  # 注入：永远灰着")]),
    Case("52", "回执那句由界面自己拼（第二个口径，**ISSUES I60** 同族）",
         "tests/integration/test_catalog_writes_ui.py::test_状态条那句逐字就是后端回执",
         [Edit("src/pdfarchiver/ui/catalog_links.py",
               "        self._set_status(receipt.describe())",
               '        self._set_status(f"已归入 {len(ids)} 份")  # 注入：界面自己数')]),
    Case("53", "按钮在、菜单在，就是不写库（六条写方法回到零调用点）",
         "tests/integration/test_catalog_writes_ui.py::test_多选三份归入一个分类表里正好三行而再点一次还是三行 "
         "tests/integration/test_catalog_writes_ui.py::test_六条写方法在产品侧各有调用点了",
         [Edit("src/pdfarchiver/ui/catalog_links.py",
               '        self._write(self.ctx.catalog.link_categories, action.data(), "归入分类失败")',
               "        pass  # 注入：按下去只刷新状态条，不写库")]),
    Case("54", "写失败时把后端原文吞掉，只留一句「失败了」",
         "tests/integration/test_catalog_writes_ui.py::test_归入失败时屏幕上留的是后端原文",
         [Edit("src/pdfarchiver/ui/catalog_links.py",
               '            self._set_status(f"{fail_note}：{exc}", danger=True)',
               '            self._set_status(f"{fail_note}（详情见日志）", danger=True)  # 注入：不给原文')]),
    Case("55", "归入不做判重：已在的再插一次",
         "tests/integration/test_catalog_writes_ui.py::test_多选三份归入一个分类表里正好三行而再点一次还是三行",
         [Edit("src/pdfarchiver/db/repositories/catalog.py",
               '        with self.engine.transaction(conn, on_error=f"批量归入分类 {category_id} 失败"):\n'
               "            have = {row[\"doc_id\"] for row in conn.execute(\n"
               '                f"SELECT doc_id FROM document_categories WHERE category_id=? '
               'AND doc_id IN ({marks})",\n'
               "                (category_id, *ids))}",
               '        with self.engine.transaction(conn, on_error=f"批量归入分类 {category_id} 失败"):\n'
               "            have = set()  # 注入：不查已有关联")]),
    Case("56", "把「归入」做成互斥：先清掉这几份的全部归入",
         "tests/integration/test_catalog_writes_ui.py::test_归入第二个分类时第一个分类的关联一条不动",
         [Edit("src/pdfarchiver/db/repositories/catalog.py",
               '        with self.engine.transaction(conn, on_error=f"批量归入分类 {category_id} 失败"):\n'
               "            have = {row[\"doc_id\"] for row in conn.execute(\n"
               '                f"SELECT doc_id FROM document_categories WHERE category_id=? '
               'AND doc_id IN ({marks})",\n'
               "                (category_id, *ids))}",
               '        with self.engine.transaction(conn, on_error=f"批量归入分类 {category_id} 失败"):\n'
               '            conn.execute(f"DELETE FROM document_categories WHERE doc_id IN ({marks})", ids)\n'
               "            have = set()  # 注入：改成「只归这一个分类」")]),
    Case("57", "摘标签时把这几份的标签一次摘光",
         "tests/integration/test_catalog_writes_ui.py::test_移除标签只摘那一个而别的标签与分类都不动",
         [Edit("src/pdfarchiver/db/repositories/catalog.py",
               '                conn.execute(f"DELETE FROM document_tags WHERE tag_id=? AND doc_id IN ({gone})",\n'
               "                             (tag_id, *sorted(have)))",
               '                conn.execute(f"DELETE FROM document_tags WHERE doc_id IN ({gone})",\n'
               "                             tuple(sorted(have)))  # 注入：不分标签")]),
    Case("58", "打标签不做判重：已有的再插一次",
         "tests/integration/test_catalog_writes_ui.py::test_打标签移除再打同一份标签只有一行",
         [Edit("src/pdfarchiver/db/repositories/catalog.py",
               '        with self.engine.transaction(conn, on_error=f"批量加标签 {tag_id} 失败"):\n'
               "            have = {row[\"doc_id\"] for row in conn.execute(\n"
               '                f"SELECT doc_id FROM document_tags WHERE tag_id=? AND doc_id IN ({marks})",\n'
               "                (tag_id, *ids))}",
               '        with self.engine.transaction(conn, on_error=f"批量加标签 {tag_id} 失败"):\n'
               "            have = set()  # 注入：不查已有标签")]),
    Case("59", "写完逐行取分类（一行一条 SQL，**ISSUES I51** 那一类）",
         "tests/integration/test_catalog_writes_ui.py::test_归入之后分类列当场改而一批只走一条查询",
         [Edit("src/pdfarchiver/ui/pages/library_page.py",
               "        held = self.ctx.catalog.categories_by_doc_ids(doc_ids)",
               "        held = {doc_id: self.ctx.catalog.categories_of(doc_id) for doc_id in doc_ids}"
               "  # 注入：逐行取")]),
    Case("60", "挪整枝只改点名的那一行，子孙的 name_path 留在旧父亲名下",
         "tests/integration/test_catalog_writes_ui.py::test_改父类之后子孙的name_path整片跟随",
         [Edit("src/pdfarchiver/db/repositories/catalog.py",
               '            conn.execute("UPDATE categories SET parent_id=?, name_path=?, updated_at=? '
               'WHERE id=?",\n'
               "                         (new_parent_id, new_path, ts, category_id))\n"
               '            self._repath_subtree(conn, category_id, old["name_path"], new_path, ts)',
               '            conn.execute("UPDATE categories SET parent_id=?, name_path=?, updated_at=? '
               'WHERE id=?",\n'
               "                         (new_parent_id, new_path, ts, category_id))\n"
               "            # 注入：不重排子孙")]),
    Case("61", "合并不改文档指向，只把源分类删掉（关联被删没了）",
         "tests/integration/test_catalog_writes_ui.py::test_合并分类后源整枝的文档指向目标而源行归零",
         [Edit("src/pdfarchiver/db/repositories/catalog.py",
               "            conn.execute(\n"
               '                f"UPDATE OR IGNORE document_categories SET category_id=? '
               'WHERE category_id IN ({marks})",\n'
               "                (target_id, *subtree))",
               "            # 注入：跳过「改指目标」这一步")]),
    Case("62", "删除不检查类下有无文件，直接删（CASCADE 抹掉归入）",
         "tests/integration/test_catalog_writes_ui.py::test_名下还有文件时删除被拒并给出清单",
         [Edit("src/pdfarchiver/ui/pages/categories_page.py",
               "        if docs:",
               "        if False:  # 注入：前置检查读空")]),
    Case("63", "前置检查读反：空枝也一律拒绝删除",
         "tests/integration/test_catalog_writes_ui.py::test_空枝才删得掉而子枝一起消失",
         [Edit("src/pdfarchiver/ui/pages/categories_page.py",
               "        if docs:",
               "        if True:  # 注入：恒拒")]),
    Case("64", "拒了但不说：仓储层的原文被界面咽下去",
         "tests/integration/test_catalog_writes_ui.py::test_把父亲挪到自己的子下面被拒而树一根不动",
         [Edit("src/pdfarchiver/ui/pages/categories_page.py",
               '        except Exception as exc:\n'
               '            QtWidgets.QMessageBox.critical(self, "改父类失败", str(exc))',
               "        except Exception:  # 注入：这一拒不上屏\n"
               "            pass")]),
    Case("65", "右键菜单少一项「改父类…」（那个动作没有入口）",
         "tests/integration/test_catalog_writes_ui.py::test_右键菜单上就那四项而选中跟着右键走",
         [Edit("src/pdfarchiver/ui/pages/categories_page.py",
               '            ("改父类…", self.reparent_category),\n',
               "")]),
    Case("66", "改父类的候选清单里把自己也放上",
         "tests/integration/test_catalog_writes_ui.py::test_自己不出现在改父类的候选清单里",
         [Edit("src/pdfarchiver/ui/pages/categories_page.py",
               "                    if c.id != exclude_id]",
               "                    ]  # 注入：不排除自己")]),
    Case("67", "「放到最外层」的哨兵 id 直接当父分类传给仓储层",
         "tests/integration/test_catalog_writes_ui.py::test_放到最外层之后前缀不再带父名",
         [Edit("src/pdfarchiver/ui/pages/categories_page.py",
               "            self.ctx.catalog.reparent_category(cat_id, "
               "None if target_id == ROOT_TARGET else target_id)",
               "            self.ctx.catalog.reparent_category(cat_id, target_id)  # 注入：哨兵不换算")]),
    Case("68", "空白处右键也弹菜单，落在第一枝上（作用于没点名的分类）",
         "tests/integration/test_catalog_writes_ui.py::test_右键空白处不开菜单",
         [Edit("src/pdfarchiver/ui/pages/categories_page.py",
               "        item = self.category_tree.itemAt(pos)\n"
               "        if item is None:\n"
               "            return",
               "        item = self.category_tree.itemAt(pos) or self.category_tree.topLevelItem(0)\n"
               "        # 注入：落空就借第一枝")]),
    # I58 第一次跑是 **GREEN**（`have` 置空在这条走不到：每轮都先摘再打，从来没有重复插）。
    # 按 AGENTS.md「不会变红的断言直接删或重写」，改的是断言而不是坏法：第一轮加一次**连着点**，
    # 并钉住那句「新增 0 条」；这一条 I69 补上"点了摘不掉"那一侧。
    Case("69", "摘标签那一步不执行：点了「移除标签」但一行都没删",
         "tests/integration/test_catalog_writes_ui.py::test_打标签移除再打同一份标签只有一行",
         [Edit("src/pdfarchiver/db/repositories/catalog.py",
               "            if have:",
               "            if False:  # 注入：DELETE 那条永不执行")]),
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
