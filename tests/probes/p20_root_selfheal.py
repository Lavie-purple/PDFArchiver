"""P20 监测根消失后的自愈延迟实测 —— 销账 ISSUES I5 的剩余条件（G12 的 ≤60s 要在真机上量一次）。

跑法：
    python tests/probes/p20_root_selfheal.py                 # 两种坏法各跑一遍（改名 + 删除）
    python tests/probes/p20_root_selfheal.py --only rename   # 只跑改名那一种
    python tests/probes/p20_root_selfheal.py --keep
    python tests/probes/p20_root_selfheal.py --inject        # 反向注入自检

**这是一场"等"出来的实测，不是快跑。** 被监听根消失是 **0 事件**（`p4_watchdog_result.json`
里 `root_renamed.delta_events == 0`，I5 的出处），能发现它的只有 `Patrol.poll()` 里那条
`due_by_clock` 慢路 —— 而它的间隔由设置里的 `scan_verify_minutes` 决定。本探针按**产品默认配置**
真等一次，所以单场时长是"设置值 + 余量"量级，不是秒级。

三条必须读清楚的诚实边界：

1. **数字的来源是设置，不是探针拍的。** 上限由 `verify_budget()` 直接从
   `config/settings.py` 的 `DEFAULTS["scan_verify_minutes"] × 60 + scan_poll_seconds × 2` 反算，
   探针自己不许出现第二个"30 分钟"字面量（AGENTS.md：同一概念只许一个口径）。
   时钟从应用第一次轮询开始算，不是从改名那一刻算，所以读数里同时给"距改名"和"距应用启动"两个数。
2. **只在专用临时目录里动磁盘。** 真实语料那 10,977 份一个字节都不碰（I64：库里 ids 1–3 是用户
   数据，不当夹具）。两种坏法（改名 / 删除）各起一个独立的应用进程与独立数据根。
3. **"自愈"在这套设计里有两半，分开判：** ①发现并上报（慢路会排一次 scan，并在库里留下读不动的
   原文），②索引与磁盘重新一致。**②按现在的实现不会发生** —— 根读不动时
   `scan_root` 走的是"不判缺失"那一支（`test_根目录不存在时不判缺失也不崩`，网络盘掉线会瞬间
   "删掉"八千份文档，所以故意不判）。n4 就是为了让这件事**在证据里明写**，而不是被
   "自愈成功"四个字糊过去。

每条判定都有对应的"能骗过它的坏法"，`--inject` 逐个真喂一次；不会变红的直接删。
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import NamedTuple

REPO = Path(__file__).resolve().parents[2]
for _p in (REPO / "src", REPO / "tests" / "probes"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

RESULT = REPO / ".probe_work" / "p20_root_selfheal_result.json"
PROGRESS = REPO / ".probe_work" / "p20_progress.log"

DOCS_PER_ROOT = 10        # 每场一个独立根里放几份（够判定"库里还有 N 条没标缺失"，不多花扫描时间）
G12_LIMIT_SECONDS = 60.0  # docs/TESTING.md 第二节 G12「≤60s 内自检并上报」**[约定]**
MARGIN_SECONDS = 300.0    # 时钟余量：轮询抖动 + 首次 settle + 起进程
OBSERVE_STEP_SECONDS = 2.0
NOTE_EVERY_SECONDS = 60.0  # 进度行间隔：本环境后台命令的 stdout 会整块丢，读数必须边走边落盘

CASES = ("rename", "delete")


@dataclass
class Row:
    gate: str
    ok: bool
    measured: str


def log(msg: str) -> None:
    print(msg, flush=True)
    PROGRESS.parent.mkdir(exist_ok=True)
    with PROGRESS.open("a", encoding="utf-8") as fh:
        fh.write(f"[{time.strftime('%H:%M:%S')}] {msg}\n")


class Budget(NamedTuple):
    """两个上限必须分开装：`clock` 是设置反算「最迟多久会被发现」，`observe` 是探针「最多等多久」。
    混用会拿探针自己的余量去放宽 n5 的判据（写的时候就错过一次）。"""

    verify_seconds: float
    poll: float
    clock: float
    observe: float
    basis: str


def verify_budget() -> Budget:
    """从设置里反算上限 —— 探针不许自带第二个「30 分钟」字面量。"""
    from pdfarchiver.config.settings import DEFAULTS

    minutes = float(DEFAULTS["scan_verify_minutes"])
    poll = float(DEFAULTS["scan_poll_seconds"])
    verify = minutes * 60.0
    clock = verify + poll * 2          # 慢路到点 + 两次轮询的粒度
    return Budget(verify, poll, clock, clock + MARGIN_SECONDS,
                  f"scan_verify_minutes={minutes}×60={verify:.0f}s + scan_poll_seconds={poll}×2"
                  f"=+{poll * 2:.0f}s → 最迟 {clock:.0f}s 被发现｜探针观察到 {clock + MARGIN_SECONDS:.0f}s"
                  f"（多 {MARGIN_SECONDS:.0f}s 余量兜进程启动与轮询抖动）")


# ───────────────────────────── 磁盘与库的读数 ─────────────────────────────

def write_corpus(corpus: Path, count: int) -> None:
    """本地画样本（不 import conftest，与 p19 同一条理由：现场要干净、独立）。"""
    import pymupdf

    corpus.mkdir(parents=True, exist_ok=True)
    for i in range(count):
        path = corpus / f"p20_{i:02d}.pdf"
        doc = pymupdf.open()
        page = doc.new_page(width=595, height=842)
        y = 40
        for k in range(12):
            page.insert_text((36, y), f"p20 监测根消失样本第{i}号第{k}行中文正文",
                             fontsize=11, fontname="china-s")
            y += 16
        doc.save(str(path))
        doc.close()


def query(data_root: Path, sql: str, args: tuple = ()) -> list[tuple]:
    import sqlite3

    uri = f"file:{(data_root / 'data' / 'catalog.db').as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=10)
    try:
        return conn.execute(sql, args).fetchall()
    finally:
        conn.close()


def scalar(data_root: Path, sql: str, args: tuple = ()) -> int:
    rows = query(data_root, sql, args)
    return int(rows[0][0]) if rows else 0


def register_root(data_root: Path, corpus: Path) -> None:
    from pdfarchiver.db.engine import Engine
    from pdfarchiver.db.repositories.roots import RootRepository
    from pdfarchiver.fs.identity import identity_key

    engine = Engine(data_root / "data" / "catalog.db", busy_timeout_ms=5000)
    try:
        RootRepository(engine).add(str(corpus).replace("\\", "/"), identity_key(corpus),
                                   label="p20 监测根")
    finally:
        engine.close_thread_connection()


def enqueue_scan(data_root: Path) -> int:
    from pdfarchiver.db.engine import Engine
    from pdfarchiver.db.repositories.jobs import JobRepository

    engine = Engine(data_root / "data" / "catalog.db", busy_timeout_ms=5000)
    try:
        return 1 if JobRepository(engine).enqueue("scan") else 0
    finally:
        engine.close_thread_connection()


def scan_jobs_after(data_root: Path, since_ts: int) -> list[tuple]:
    return query(data_root,
                 "SELECT id, created_at, state, finished_at FROM processing_jobs "
                 "WHERE kind='scan' AND created_at > ? ORDER BY created_at", (since_ts,))


def root_row(data_root: Path) -> tuple:
    return query(data_root, "SELECT last_full_scan_at, last_scan_error FROM monitored_roots")[0]


def missing_count(data_root: Path) -> int:
    return scalar(data_root, "SELECT count(*) FROM documents WHERE missing_since IS NOT NULL")


def doc_count(data_root: Path) -> int:
    return scalar(data_root, "SELECT count(*) FROM documents")


def open_index_or_ocr_jobs(data_root: Path) -> int:
    """库里还挂在 pending/running 的 index/ocr 任务条数 —— 只有降到 0 才代表解析器
    已经交回 PDF 文件句柄，`shutil.rmtree(corpus)` 才不会被 WinError 32 拦住。
    delete 那一场在 doc_count 到位但索引还在跑的时候 rmtree 会删一半文件卡一半，
    后面所有延迟读数作废（**ISSUES I5** 的真机复跑现场实测）。scan 不在此列：
    scan 只读目录、不 open PDF。"""
    return scalar(data_root,
                  "SELECT count(*) FROM processing_jobs "
                  "WHERE kind IN ('index','ocr') AND state IN ('pending','running')")


# ───────────────────────────── 判据 ─────────────────────────────

def n1_op_landed(case: str, disk: dict[str, object]) -> Row:
    """不能对一件没发生的操作报延迟。改名那一场必须"旧路径没了、新路径有了"，
    删除那一场必须"路径整个没了"。"""
    ok = bool(disk.get("gone")) and (disk.get("moved_in") if case == "rename"
                                     else disk.get("moved_in") is False)
    err = disk.get("error")
    return Row(f"n1 「{case}」这一下真的落到磁盘上了（旧路径已消失）",
               ok,
               f"原路径存在={not disk.get('gone')}｜改名后新路径存在={disk.get('moved_in')}｜"
               f"盘上 PDF 数={disk.get('pdfs_after')}"
               + (f" ── 磁盘操作报错原文：{err}" if err else "")
               + ("" if ok else " ── 操作没做成，后面的延迟读数全部无效"))


def n2_latency_vs_g12(case: str, latency: float | None, observed_at: float | None,
                      waited: float, basis: str) -> Row:
    if latency is None:
        return Row(f"n2 {case} 后 ≤{G12_LIMIT_SECONDS:.0f}s 被发现并上报（G12 [约定]）",
                   False,
                   f"等满 {waited:.0f}s（{basis}）没有任何一条新的 scan 任务被排进队列 —— "
                   f"慢路根本没触发，G12 的 60s 无从谈起")
    return Row(f"n2 {case} 后 ≤{G12_LIMIT_SECONDS:.0f}s 被发现并上报（G12 [约定]）",
               latency <= G12_LIMIT_SECONDS,
               f"实测延迟 {latency:.0f}s（距磁盘那一刻）｜从探针看见算 {observed_at:.0f}s"
               f"｜口径来源：{basis}｜超 G12 阈值 {latency / G12_LIMIT_SECONDS:.1f} 倍")


def n3_reported_somewhere(case: str, scan_error: str | None, log_hits: int) -> Row:
    ok = bool(scan_error) or log_hits > 0
    return Row(f"n3 「上报」有落点（库里有原文 或 日志里有痕迹），不是只在内存里想过",
               ok,
               f"monitored_roots.last_scan_error={str(scan_error)[:120] or 'NULL'}｜"
               f"app.log* 里与这一场相关的记录 {log_hits} 处"
               + ("" if ok else " ── 没有任何一处留下原文：这条「发现了」是不可诊断的"))


def n4_converged(case: str, docs_in_library: int, missing: int, pdfs_on_disk: int) -> Row:
    """自愈的实质：索引与磁盘重新对上。"上报了"不等于"一致了"。

    `pdfs_on_disk` 只数**登记在那条根路径下**的文件。改名后新路径里的文件不计入 —— 索引指向的是
    登记路径，新路径有货恰恰就是"对不上"本身（数进去会把这一条判成绿，实测差点犯）。"""
    consistent = docs_in_library - missing == pdfs_on_disk
    return Row(f"n4 {case} 之后索引与磁盘重新一致（自愈的实质，不是「只发现了」）",
               consistent,
               f"库里主记录 {docs_in_library} 条｜其中标了缺失 {missing} 条｜"
               f"未标缺失 {docs_in_library - missing} 条｜登记根路径下真有 PDF {pdfs_on_disk} 份"
               + ("" if consistent else
                  " ── 不一致：根读不动时故意不判缺失（网络盘掉线会瞬间「删掉」八千份），"
                  "所以这一支按现设计不会收敛，需要人重新登记或改名回来"))


def n5_clock_matches_settings(case: str, latency: float | None, expected: float,
                              basis: str) -> Row:
    """慢路的数字必须与设置反算出来的量级对得上 —— 对不上说明量的不是那条路。"""
    if latency is None:
        return Row("n5 实测延迟与设置反算的慢路量级对得上（量的确实是那条路）",
                   False, f"没有延迟读数可比；设置反算 {expected:.0f}s（{basis}）")
    ok = latency <= expected
    return Row("n5 实测延迟与设置反算的慢路量级对得上（量的确实是那条路）",
               ok,
               f"实测 {latency:.0f}s ≤ 设置反算上限 {expected:.0f}s｜{basis}"
               + ("" if ok else " ── 比慢路还晚，说明连周期校验都没按时跑（另有一条账要立）"))


def n6_app_survived(rc: int | None, crash_bytes: int, alive_to_end: bool) -> Row:
    """排除"其实是应用崩了所以没发现" —— 那会让上面所有延迟读数变成另一种东西。

    **退出码在 Windows 上不能当崩溃证据**：本场收尾用 `proc.terminate()`，它对应
    `TerminateProcess(handle, 1)`，所以一次干净终止的 `rc` **恒为 1**（**ISSUES I92**：
    原先这里判 `rc == 0`，而自检喂的好例子是 `(0, 0, True)` —— 那个三元组在生产路径上
    根本产生不出来，于是注入永远绿、真跑永远红）。存活由 `alive_to_end` 判，异常终止由
    `crash.log` 判，`rc` 只兜"既不终止也不该出现的值"。
    """
    rc_clean = rc is None or rc in (0, 1)
    ok = alive_to_end and crash_bytes == 0 and rc_clean
    return Row("n6 应用进程在整个观察期里活着且没崩（排除「没发现其实是崩了」）",
               ok,
               f"观察结束时进程还在={alive_to_end}｜crash.log {crash_bytes} 字节｜退出码 {rc}"
               "（terminate() 在 Windows 恒回 1，故 0/1 都算干净退出）"
               + ("" if ok else " ── 这一场的延迟读数不能读成「监听盲」，要按崩溃另立一条"))


# ───────────────────────────── 反向注入自检 ─────────────────────────────

def inject() -> int:
    """坏法的来源逐条写在注释里；每条都配一份好读数，证明判据不是恒红。"""
    bad: list[tuple[Row, str]] = []

    # 坏法 1：磁盘操作被 Windows 的监听句柄挡掉了（PermissionError），改名其实没做成。
    #         这是本探针最可能出现的假绿：后面"没发现"其实是"没改"
    bad.append((n1_op_landed("rename", {"gone": False, "moved_in": False,
                                        "pdfs_after": 10,
                                        "error": "PermissionError: 另一个进程正在使用此文件"}),
                "改名被占用句柄挡掉，原路径还在"))
    bad.append((n1_op_landed("delete", {"gone": False, "moved_in": False,
                                        "pdfs_after": 10, "error": None}),
                "目录没删掉（还有残留 PDF），却当成删干净了"))
    # 坏法 2a：等满了也没排 scan → n2 必须红
    bad.append((n2_latency_vs_g12("rename", None, None, 1810.0, "settings"),
                "慢路一次都没触发，没有任何 scan 任务"))
    # 坏法 2b：量出来 1,780s，远超 60s → n2 必须红（这正是本探针预期会红的样子）
    bad.append((n2_latency_vs_g12("rename", 1780.0, 1782.0, 1810.0, "settings"),
                "自愈要 1,780s：G12 的 60s 没做到"))
    # 坏法 3：只在内存里"知道"了，库里与日志里都没有原文 → n3 必须红
    bad.append((n3_reported_somewhere("rename", None, 0),
                "发现了但没留下任何可诊断的原文"))
    # 坏法 4：上报了、但索引与磁盘还是两张皮 → n4 必须红
    bad.append((n4_converged("rename", 10, 0, 0),
                "库里 10 条一份没标缺失，盘上一份都没有（现设计的真实结果）"))
    # 坏法 5：实测比设置反算还晚 → n5 必须红（说明量的不是那条路，或慢路压根没跑）
    bad.append((n5_clock_matches_settings("rename", 2600.0, 1810.0, "settings"),
                "实测 2,600s > 设置反算 1,810s：慢路没按时跑"))
    bad.append((n5_clock_matches_settings("rename", None, 1810.0, "settings"),
                "没有延迟读数，无可比"))
    # 坏法 6：其实是崩了 → n6 必须红（不能把崩溃读成"监听是盲的"）
    bad.append((n6_app_survived(1, 4096, False),
                "应用退出码 1 + crash.log 4,096 字节"))
    # 坏法 6b：进程在观察期内就自己走了（装配失败那类），crash.log 反而是空的 ——
    #         旧判据只看退出码，Windows 上干净终止也是 1，分不出这两种；靠 alive 兜住
    bad.append((n6_app_survived(1, 0, False),
                "观察期内进程就没了，但崩溃日志一个字没写"))
    # 坏法 6c：还活着但 crash.log 有内容（子线程崩了）→ 崩溃那一路单独要红
    bad.append((n6_app_survived(1, 512, True),
                "crash.log 512 字节：有崩溃记录，即便观察结束时还活着"))
    # 坏法 6d：退出码既不是 0 也不是 1（如访问违例那一类崩溃码）→ rc 那一路单独要红；
    #         alive 为真因为它是 terminate 之前采的样，最后一刻崩正好是这种组合
    bad.append((n6_app_survived(-1073741819, 0, True),
                "退出码 -1073741819（访问违例那一类），不在 0/1 之内"))

    good = [n1_op_landed("rename", {"gone": True, "moved_in": True, "pdfs_after": 10,
                                    "error": None}),
            n1_op_landed("delete", {"gone": True, "moved_in": False, "pdfs_after": 0,
                                    "error": None}),
            n2_latency_vs_g12("rename", 42.0, 43.0, 1810.0, "settings"),
            n3_reported_somewhere("rename", "FileNotFoundError: 根目录不存在", 3),
            n4_converged("rename", 10, 10, 0),
            n5_clock_matches_settings("rename", 1780.0, 1810.0, "settings"),
            # 好例子必须取生产真会产生的三元组：terminate() 之后 rc 恒 1（I92）
            n6_app_survived(1, 0, True),
            # 另一种同样可达：取样时进程仍在场，还没轮到读退出码
            n6_app_survived(None, 0, True)]

    caught = 0
    for row, why in bad:
        mark = "红" if not row.ok else "绿（← 这条断言没有牙）"
        log(f"  {mark}  {row.gate}\n        坏法：{why}\n        读数：{row.measured}")
        caught += 1 if not row.ok else 0
    passed = 0
    for row in good:
        log(f"  {'绿（好读数正确放行）' if row.ok else '红（← 判据恒红，不能用）'}  {row.gate}\n"
            f"        读数：{row.measured}")
        passed += 1 if row.ok else 0

    log(f"注入自检：抓到 {caught}/{len(bad)} 条坏法｜好读数放行 {passed}/{len(good)}")
    if caught != len(bad) or passed != len(good):
        log("VERDICT: RED（有坏法骗过判据，或有判据恒红）")
        return 1
    log("VERDICT: ALL GREEN")
    return 0


# ───────────────────────────── 一场实测 ─────────────────────────────

def run_case(case: str, work: Path, keep: bool) -> tuple[list[Row], dict[str, object]]:
    """一种坏法一场：独立数据根 + 独立应用进程 + 独立监测根。"""
    b = verify_budget()
    data_root = work / f"data_root_{case}"
    corpus = work / f"corpus_{case}"
    renamed = work / f"corpus_{case}_renamed"
    log(f"── 场 {case}：现场 {work.name}｜{b.basis}")

    write_corpus(corpus, DOCS_PER_ROOT)
    from pdfarchiver.services.bootstrap import bootstrap
    warm = bootstrap(data_root)
    warm.shutdown()
    register_root(data_root, corpus)

    env = {**os.environ, "QT_QPA_PLATFORM": "offscreen", "PYTHONIOENCODING": "utf-8",
           "PYTHONPATH": str(REPO / "src")}
    stdout_file = work / f"app_{case}.log"
    started_wall = int(time.time())
    fh = stdout_file.open("w", encoding="utf-8", errors="replace")
    proc = subprocess.Popen([sys.executable, "-m", "pdfarchiver.app",
                             "--data-dir", str(data_root),
                             "--exit-after", str(int(b.observe + 240))],
                            cwd=str(work), env=env, stdout=fh, stderr=subprocess.STDOUT,
                            text=True)
    rows: list[Row] = []
    detail: dict[str, object] = {"case": case, "verify_seconds": b.verify_seconds,
                                 "clock_seconds": b.clock, "observe_seconds": b.observe,
                                 "basis": b.basis, "app_started_at": started_wall}
    try:
        # 先让这一场有一个"已知的干净起点"：排一次扫描，等它把 N 份收进库并排空。
        # doc_count 到位只说明 scan worker 登记了主记录，index worker 还在逐份 open PDF
        # 解析正文 —— Windows 上解析器持有的句柄会让后续 `shutil.rmtree(corpus)` 卡在
        # WinError 32（本轮真机复跑现场），因此必须再等 index/ocr 队列落到 0 才动手。
        enq = enqueue_scan(data_root)
        t0 = time.perf_counter()
        while time.perf_counter() - t0 < 180 and proc.poll() is None:
            if (doc_count(data_root) >= DOCS_PER_ROOT
                    and open_index_or_ocr_jobs(data_root) == 0):
                break
            time.sleep(1.0)
        docs_before = doc_count(data_root)
        backlog = open_index_or_ocr_jobs(data_root)
        log(f"  起点：排进 scan {enq} 条｜库里主记录 {docs_before}/{DOCS_PER_ROOT}｜"
            f"index/ocr 未排空 {backlog} 条｜耗时 {time.perf_counter() - t0:.1f}s")
        detail["docs_before"] = docs_before
        detail["start_backlog"] = backlog

        # ── 动手：这一场唯一的磁盘操作，t0 之后应用只能靠慢路发现 ──
        op_t0 = time.time()
        disk: dict[str, object] = {"gone": False, "moved_in": False,
                                   "pdfs_after": -1, "error": None}
        try:
            if case == "rename":
                corpus.rename(renamed)
            else:
                shutil.rmtree(corpus)
        except OSError as exc:
            disk["error"] = f"{type(exc).__name__}: {exc}"
        disk["gone"] = not corpus.exists()
        disk["moved_in"] = renamed.exists() if case == "rename" else False
        disk["pdfs_after"] = len(list(renamed.rglob("*.pdf"))) if (case == "rename"
                                                                   and renamed.exists()) else 0
        # 索引指向的是登记路径，所以"对上一致"要拿登记路径下的货量算，新路径不算（见 n4 文档）
        disk["pdfs_under_registered"] = (len(list(corpus.rglob("*.pdf")))
                                         if corpus.exists() else 0)
        log(f"  动手：{case}｜原路径消失={disk['gone']}｜新路径在场={disk['moved_in']}｜"
            f"新路径下 {disk['pdfs_after']} 份｜登记路径下 {disk['pdfs_under_registered']} 份｜"
            f"报错={disk['error'] or '无'}")
        detail["disk"] = disk
        rows.append(n1_op_landed(case, disk))
        detail["op_at"] = int(op_t0)

        # ── 观察：只读轮询，直到出现一条"晚于动手那一刻"的 scan，或等满上限
        first: tuple | None = None
        seen_at: float | None = None
        notice_t = time.perf_counter()
        next_note = NOTE_EVERY_SECONDS
        while time.perf_counter() - notice_t < b.observe and proc.poll() is None:
            jobs = scan_jobs_after(data_root, int(op_t0))
            if jobs:
                first, seen_at = jobs[0], time.perf_counter() - notice_t
                break
            elapsed = time.perf_counter() - notice_t
            if elapsed >= next_note:
                next_note += NOTE_EVERY_SECONDS
                log(f"  观察中（{case}）已等 {elapsed:.0f}s｜库里主记录仍 "
                    f"{doc_count(data_root)} 条｜标缺失 {missing_count(data_root)} 条｜"
                    f"新的 scan 任务 0 条")
            time.sleep(OBSERVE_STEP_SECONDS)

        latency = None
        if first is not None:
            latency = float(first[1] - detail["op_at"])      # created_at − 动手那一刻，UTC 秒
            log(f"  发现（{case}）：scan 任务 id={first[0]} created_at={first[1]} "
                f"state={first[2]}｜距动手 {latency:.0f}s｜距应用启动 "
                f"{int(first[1]) - detail['app_started_at']}s｜探针看见用时 {seen_at:.0f}s")
            # 等这一条 scan 跑完，才能读"上报有没有落点""一致了一致不了"
            wait_t = time.perf_counter()
            while time.perf_counter() - wait_t < 240 and proc.poll() is None:
                if first[2] in ("done", "failed", "cancelled") or \
                        root_row(data_root)[0]:
                    break
                fresh = scan_jobs_after(data_root, int(op_t0))
                if fresh and fresh[0][2] in ("done", "failed", "cancelled"):
                    break
                time.sleep(1.0)
        else:
            log(f"  没发现（{case}）：等满 {b.observe:.0f}s 没有任何一条晚于动手时刻的 scan 任务")

        scan_error = root_row(data_root)[1]
        text = ""
        logs_dir = data_root / "logs"
        if logs_dir.exists():
            text = "".join(f.read_text(encoding="utf-8", errors="replace")
                           for f in sorted(logs_dir.glob("app.log*")))
        log_hits = text.count("扫描") if text else 0
        crash = logs_dir / "crash.log"
        crash_bytes = crash.stat().st_size if crash.exists() else 0

        rows.append(n2_latency_vs_g12(case, latency, seen_at or b.observe, b.observe, b.basis))
        rows.append(n3_reported_somewhere(case, scan_error, log_hits))
        rows.append(n4_converged(case, doc_count(data_root), missing_count(data_root),
                                 int(disk["pdfs_under_registered"] or 0)))
        rows.append(n5_clock_matches_settings(case, latency, b.clock, b.basis))

        alive_to_end = proc.poll() is None
        proc.terminate()
        rc: int | None = None
        try:
            rc = proc.wait(timeout=90)
        except subprocess.TimeoutExpired:
            proc.kill()
            rc = proc.poll()
        fh.close()
        rows.append(n6_app_survived(rc, crash_bytes, alive_to_end))
        detail.update({"latency_seconds": latency, "seen_after_seconds": seen_at,
                       "last_scan_error": scan_error, "scan_log_hits": log_hits,
                       "docs_end": doc_count(data_root), "missing_end": missing_count(data_root),
                       "exit_code": rc, "crash_bytes": crash_bytes})
    except Exception as exc:      # noqa: BLE001 - 单场炸了要把原文带回主流程，不许糊成"没发现"
        detail["error"] = f"{type(exc).__name__}: {exc}"
        log(f"  场 {case} 抛错原文：{detail['error']}")
        if proc.poll() is None:
            proc.kill()
        fh.close()
    return rows, detail


def run(cases: list[str], keep: bool) -> int:
    work = Path(tempfile.mkdtemp(prefix="p20_selfheal_"))
    PROGRESS.parent.mkdir(exist_ok=True)
    PROGRESS.write_text("", encoding="utf-8")
    b = verify_budget()
    log(f"P20 起跑：现场 {work}｜两种坏法 {'、'.join(cases)}｜{b.basis}｜"
        f"轮询 {OBSERVE_STEP_SECONDS}s")
    log(f"进度逐分钟写盘：{PROGRESS}（本环境后台命令 stdout 会整块丢，读数边走边落）")
    all_rows: list[Row] = []
    details: list[dict[str, object]] = []
    try:
        for case in cases:
            rows, detail = run_case(case, work, keep)
            all_rows.extend(rows)
            details.append(detail)
            RESULT.write_text(json.dumps({"basis": b.basis, "cases": details,
                                          "rows": [asdict(r) for r in all_rows]},
                                         ensure_ascii=False, indent=2), encoding="utf-8")
            log(f"读数已写：{RESULT}（已完成 {case}）")
    finally:
        if keep:
            log(f"--keep：现场留着 {work}")
        else:
            shutil.rmtree(work, ignore_errors=True)

    red = 0
    for r in all_rows:
        log(f"  {'绿' if r.ok else '红'}  {r.gate}\n        {r.measured}")
        red += 0 if r.ok else 1
    log(f"  合计 {len(all_rows)} 条｜红 {red} 条")
    log("VERDICT: ALL GREEN" if not red else f"VERDICT: RED（{red} 条）")
    return 0 if not red else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="监测根消失后的自愈延迟实测（详见模块文档三条诚实边界）")
    ap.add_argument("--only", choices=CASES, default=None, help="只跑某一种坏法")
    ap.add_argument("--keep", action="store_true", help="跑完保留现场目录")
    ap.add_argument("--inject", action="store_true", help="反向注入自检：每条判据真喂一次坏读数")
    args = ap.parse_args(argv)
    if args.inject:
        return inject()
    return run([args.only] if args.only else list(CASES), args.keep)


if __name__ == "__main__":
    raise SystemExit(main())
