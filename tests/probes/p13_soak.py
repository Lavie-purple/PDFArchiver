"""P13 长时间运行稳定性采样 —— 交付阶段需求第 5 条（异常提示 / 日志 / 资源占用 / 长时间运行）。

跑法：
    python tests/probes/p13_soak.py                      # 默认 4 分钟
    python tests/probes/p13_soak.py --minutes 10          # 拉长
    python tests/probes/p13_soak.py --keep                # 跑完不删现场，进去看日志
    python tests/probes/p13_soak.py --inject              # 反向注入自检（只动临时目录里的东西）

被验的是**源码跑起来的真应用进程**（`python -m pdfarchiver.app`），不是这里另搭的一次装配：
子进程自己走完 bootstrap → 迁移 → 窗口就绪 → `start_background()`（worker + watchdog + 巡检定时器），
本探针只从外面看它 —— 采样用 psutil，对账用只读 sqlite。窗口用 `offscreen` 平台起，
理由与代价见 I17（比真机快，且不做窗口合成）。

**必须先读清楚的三条诚实边界：**

1. **"长时间"在这里只有几分钟。** 本工作环境单条命令上限 600s，默认 soak 240s 加上前后对账
   约 300s。小时级 / 天级挂机、"跑一整夜第 6 天崩不崩"**没有被这条探针证明过**，
   交付报告里也不许那样写。它证明的是：在持续投放文件变更的情况下，
   运行几分钟之后线程/句柄/内存不持续增长、积压能排空、日志受轮转约束、库仍然自洽。
2. **所有资源读数都是负载绑定的**（I25 同源）：同机有别的东西在跑时 RSS 与耗时会一起抬。
   所以这里只对"增长量"下断言，不对绝对值下断言（除了内存红线那条，它取的是更严的一档）。
3. **语料是本探针自己造的合成样本**（`conftest._make_pdf`），量级是几十份，
   不是真实语料的 7,768 份 / 202 万页。真实量级下的长跑稳定性仍然未验证（I20）。

判据全部写成可计数的硬条件；每条都有对应的"能骗过它的坏法"，`--inject` 逐个真注入。
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
for _p in (REPO / "src", REPO / "tests"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

P12 = "tests/probes/p12_consistency.py"
RESULT = REPO / ".probe_work" / "p13_soak_result.json"

SAMPLE_SECONDS = 2.0        # 采样间隔：再密就变成采样本身在吃 CPU，读数不再说明被测对象
CHURN_EVERY = 15.0          # 每 15 秒投放一批文件变更；短于此会被周期校验（默认 30 分钟）掩盖
CHURN_ADD = 3               # 每轮新增几份、改一份、删一份 —— 三条路都要在长跑里反复走
BULK_SEED = 20              # 起跑前库里先有多少份

THREAD_LEAK_MAX = 2         # 相对首段中位数最多再多几个线程（worker 2 + observer + Qt 内部）
HANDLE_LEAK_MAX = 200       # 相对首段中位数最多再多几个句柄
RSS_GROWTH_MAX_MIB = 80.0   # 末段中位数 - 首段中位数：几分钟内涨这么多就是留着不放
G8_LIMIT_MIB = 1200.0       # 内存红线；[约定] 单位口径按更严的 1,200MiB 一档（I16 说这条没写明）
BACKLOG_DRAIN_MAX = 90.0    # 停止投放后，队列从有活到全空最多允许多少秒
OPEN_STATES = ("queued", "running", "paused")   # `LEGAL_TRANSITIONS` 里全部非终态，一个不多一个不少
LOG_ROTATION_SLACK = 1      # 轮转份数只许比 log_keep_files 多 1（当前那份）


@dataclass
class Row:
    gate: str
    ok: bool
    measured: str


def log(msg: str) -> None:
    print(msg, flush=True)


# ───────────────────────────── 造现场 ─────────────────────────────

def build_corpus(corpus: Path) -> int:
    """合成样本树：起跑先有 BULK_SEED 份，churn 目录空着等运行期投放。"""
    from conftest import _make_pdf

    corpus.mkdir(parents=True, exist_ok=True)
    for i in range(BULK_SEED):
        _make_pdf(corpus / f"soak_seed_{i:03d}.pdf", pages=2,
                  lines=[f"soak 起始样本第 {i} 号，含可检索中文字串"])
    (corpus / "churn").mkdir(exist_ok=True)
    return len(list(corpus.rglob("*.pdf")))


def seed_library(data_root: Path, corpus: Path) -> None:
    """登记监测根 + 排一条全量扫描。与 `packaging/frozen_smoke.py` 同一条服务层路。"""
    from pdfarchiver.db.engine import Engine
    from pdfarchiver.db.repositories.jobs import JobRepository
    from pdfarchiver.db.repositories.roots import RootRepository
    from pdfarchiver.fs.identity import identity_key

    engine = Engine(data_root / "data" / "catalog.db", busy_timeout_ms=5000)
    try:
        RootRepository(engine).add(str(corpus).replace("\\", "/"), identity_key(corpus),
                                   label="soak 临时语料")
        JobRepository(engine).enqueue("scan")
    finally:
        engine.close_thread_connection()


def query(data_root: Path, sql: str, args: tuple = ()) -> list[tuple]:
    """只读打开库。应用正在写的时候读不到就原样报错，不猜一个数。"""
    uri = f"file:{(data_root / 'data' / 'catalog.db').as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=10)
    try:
        return conn.execute(sql, args).fetchall()
    finally:
        conn.close()


def backlog(data_root: Path) -> dict[str, int]:
    """队列按状态的条数 —— 与 `JobRepository.counts_by_state()` 同一条口径、同一张表名。

    这里手抄 SQL 是有代价的：上一版抄成了 `FROM jobs`（真表叫 `processing_jobs`），
    于是 S6 在整整 46 秒的等待里每次都抛 `no such table` 然后被循环吞掉，读数只剩
    `{'读库失败': 'no such table: jobs'}` —— 判据没撒谎（它报了红），但**传感器是瞎的**。
    表名与列名由 `tests/integration/test_probe_sql_sensors.py` 钉住，不再靠肉眼。
    """
    return dict(query(data_root, "SELECT state, count(*) FROM processing_jobs GROUP BY state"))


# ───────────────────────────── 采样 ─────────────────────────────

class Sampler:
    """后台线程采 RSS / CPU / 线程数 / 句柄数。只记录，判定在事后按分段中位数算。

    **采的是整棵进程树，不是 `Popen` 那个 pid**：本机 venv 的 `python.exe` 是个 3.8MiB / 3 线程的
    启动壳，真跑 Qt 的是它 spawn 出来的子进程（实测同一时刻子进程 76.6MiB / 11 线程 / 258 句柄）。
    只盯 launcher 会采出一组"线程 1、句柄 50、RSS 3.7MiB"的漂亮数字 —— 前三轮 soak 的 S3/S4/S5
    就是这么绿的，绿得没有意义（两侧读数的对账记在 `docs/ISSUES.md` **I29**）。
    """

    def __init__(self, proc: subprocess.Popen[str],
                 interval: float = SAMPLE_SECONDS) -> None:
        self.proc = proc
        # interval 是给「同一棵树要量峰值而不是趋势」的探针（p19）留的口子：2s 采趋势够用，
        # 但一次几秒就完成的内存尖峰会被 2s 网格整个漏掉。默认值不变，p13 的读数口径不变。
        self.interval = interval
        self.samples: list[dict[str, float]] = []
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.errors: list[str] = []

    def start(self) -> "Sampler":
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        return self

    def _loop(self) -> None:
        import psutil

        root = psutil.Process(self.proc.pid)
        while not self._stop.wait(self.interval):
            # 树里一个进程都没剩 = 应用真的死了，这才算失败；启动壳先退、子进程还活着不算
            procs = [root] + root.children(recursive=True)
            live = []
            for p in procs:
                try:
                    p.memory_info()
                    live.append(p)
                except (psutil.NoSuchProcess, OSError):
                    continue
            if not live:
                self.errors.append(f"NoSuchProcess: pid {self.proc.pid} 及其子进程都不在了")
                return
            row = {"t": round(time.monotonic(), 1),
                   "rss_mib": round(sum(p.memory_info().rss for p in live) / 1048576.0, 1),
                   "cpu": round(sum(p.cpu_percent() for p in live), 1),
                   "threads": sum(p.num_threads() for p in live),
                   "pids": len(live)}
            if hasattr(root, "num_handles"):          # 只有 Windows 有这一项
                row["handles"] = sum(p.num_handles() for p in live)
            self.samples.append(row)

    def stop(self) -> list[dict[str, float]]:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=self.interval * 3)
        return self.samples


def _median(values: list[float]) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    n = len(s)
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2.0


def _split(samples: list[dict[str, float]], key: str) -> tuple[list[float], list[float]]:
    """取同一段读数的首段与末段（各 1/3），中位数对比才抗单点毛刺。"""
    vals = [float(s[key]) for s in samples if key in s]
    third = max(1, len(vals) // 3)
    return vals[:third], vals[-third:]


# ───────────────────────────── 判据（每条一个纯函数，注入时直接喂坏读数）─────────────────────────────

def v_alive(rc: int | None, samples: list[dict[str, float]], expected_seconds: float,
             early_errors: list[str]) -> Row:
    gate = "S1 进程在整个 soak 期间活着，且按 --exit-after 自己干净退出"
    if rc is None:
        return Row(gate, False, f"进程没等到退出，soak {expected_seconds:.0f}s 仍在跑")
    med = _median([s["rss_mib"] for s in samples])
    return Row(gate, rc == 0 and len(samples) >= expected_seconds / SAMPLE_SECONDS * 0.7,
               f"退出码 {rc}｜采样 {len(samples)} 点（预期约 {expected_seconds / SAMPLE_SECONDS:.0f} 点）"
               f"｜采样间隔内 RSS 中位 {med:.1f}MiB"
               + ("" if not early_errors else " ── 采样中断：" + early_errors[0]))


def v_no_crash(crash_bytes: int, traceback_count: int, log_tail: str) -> Row:
    gate = "S2 全程无未捕获异常（crash.log 为空 / app.log 无 Traceback）"
    return Row(gate, crash_bytes == 0 and traceback_count == 0,
               f"crash.log {crash_bytes} 字节｜app.log*（含轮转份数）里 Traceback {traceback_count} 处"
               + ("" if crash_bytes == 0 else f" ── 进程输出尾部：{log_tail[-240:]}"))


def v_threads(samples: list[dict[str, float]]) -> Row:
    gate = f"S3 线程不泄漏（末段中位 − 首段中位 ≤ {THREAD_LEAK_MAX}）"
    if not samples or "threads" not in samples[0]:
        return Row(gate, False, "没有线程数读数")
    head, tail = _split(samples, "threads")
    delta = _median(tail) - _median(head)
    worst = max(float(s["threads"]) for s in samples)
    return Row(gate, delta <= THREAD_LEAK_MAX,
               f"首段中位 {_median(head):.0f} → 末段中位 {_median(tail):.0f}（差 {delta:+.0f}）"
               f"｜全程峰值 {worst:.0f}")


def v_handles(samples: list[dict[str, float]]) -> Row:
    gate = f"S4 句柄不泄漏（末段中位 − 首段中位 ≤ {HANDLE_LEAK_MAX}）"
    if not samples or "handles" not in samples[0]:
        return Row(gate, False, "本机 psutil 没有 num_handles 读数（非 Windows）")
    head, tail = _split(samples, "handles")
    delta = _median(tail) - _median(head)
    return Row(gate, delta <= HANDLE_LEAK_MAX,
               f"首段中位 {_median(head):.0f} → 末段中位 {_median(tail):.0f}（差 {delta:+.0f}）"
               f"｜全程峰值 {max(float(s['handles']) for s in samples):.0f}")


def v_memory(samples: list[dict[str, float]]) -> Row:
    gate = f"S5 内存增长有界（末段中位 − 首段中位 ≤ {RSS_GROWTH_MAX_MIB}MiB，且不越 G8 {G8_LIMIT_MIB:.0f}MiB [约定]）"
    if not samples:
        return Row(gate, False, "没有内存读数")
    head, tail = _split(samples, "rss_mib")
    growth = _median(tail) - _median(head)
    peak = max(float(s["rss_mib"]) for s in samples)
    trough = min(float(s["rss_mib"]) for s in samples)
    return Row(gate, growth <= RSS_GROWTH_MAX_MIB and peak <= G8_LIMIT_MIB,
               f"首段中位 {_median(head):.1f} → 末段中位 {_median(tail):.1f}MiB（增长 {growth:+.1f}）"
               f"｜全程 {trough:.1f}–{peak:.1f}MiB"
               f"｜G8 余量 {G8_LIMIT_MIB - peak:.1f}MiB（单位取 1,200MiB 一档，见 I16）")


def v_backlog(drained: bool, lag: float, states: dict[str, int]) -> Row:
    gate = f"S6 停止投放后积压能排空（≤ {BACKLOG_DRAIN_MAX:.0f}s）"
    states = dict(states)
    sensor_error = str(states.pop("_读库失败", ""))
    shown = {k: v for k, v in states.items() if not k.startswith("_")}
    tail = ""
    if not drained:
        # 排空用时一样是 46 秒，"还有 41 条 queued"和"根本没读到队列"是两种完全不同的红，
        # 读数必须一眼分得开 —— 上一版把后者印成了前者，白跑一轮 soak。
        tail = (f"｜读库原文：{sensor_error}" if sensor_error else
                (f" ── 超过 {BACKLOG_DRAIN_MAX:.0f}s 仍非空，说明有活没人领" if shown else
                 f" ── 到点时读不到队列（{'、'.join(OPEN_STATES)} 都没看见），这条没有被验证"))
    return Row(gate, drained,
               f"排空用时 {lag:.1f}s｜结束时队列状态 {shown or '无任务行'}{tail}")


def v_docs_match(data_root: Path, pdf_now: int) -> Row:
    gate = "S7 长跑之后盘上文件数与库里未标缺失的主记录数相等（双向对账的单点版）"
    try:
        present = query(data_root, "SELECT count(*) FROM documents WHERE missing_since IS NULL")[0][0]
        missing = query(data_root, "SELECT count(*) FROM documents WHERE missing_since IS NOT NULL")[0][0]
    except sqlite3.Error as exc:
        return Row(gate, False, f"读不动库：{type(exc).__name__}: {exc}")
    return Row(gate, present == pdf_now,
               f"盘上 PDF {pdf_now}｜库里未标缺失 {present}｜已标缺失 {missing}"
               "（口径：churn 删掉的那些**留在库里**只打缺失戳，A 档文件不删记录）")


def v_logs(logs_dir: Path, keep_files: int, lines: int) -> Row:
    gate = f"S8 日志受轮转约束（轮转份数 ≤ {keep_files + LOG_ROTATION_SLACK}）"
    files = sorted(logs_dir.glob("app.log*"))
    total = sum(f.stat().st_size for f in files)
    return Row(gate, len(files) <= keep_files + LOG_ROTATION_SLACK,
               f"app.log 相关文件 {len(files)} 份｜合计 {round(total / 1024)}KiB｜当前那份 {lines} 行")


def v_consistency(rc: int | None, tail: str) -> Row:
    gate = "S9 长跑现场通过 p12 一致性核查（13 条全绿 0 未验）"
    return Row(gate, rc == 0 and "未验 0 条" in tail and "ALL GREEN" in tail,
               tail.replace("\n", " ") or "p12 没有输出")


# ───────────────────────────── 反向注入自检 ─────────────────────────────

def inject() -> int:
    """每条判据喂一份**真实存在的坏法**，要求它变红。不会变红的断言直接删（AGENTS.md）。

    坏法不是凭空写的假数：每一类的来源都在注释里（哪一种真实故障会产出这样的读数）。
    """
    good_samples = [{"t": i * SAMPLE_SECONDS, "rss_mib": 300.0 + (i % 3),
                     "cpu": 1.0, "threads": 5, "handles": 700} for i in range(60)]
    bad: list[tuple[Row, str]] = []

    # 坏法 1：进程被 --exit-after 之外的原因杀掉（退出码非 0）→ S1 必须红
    bad.append((v_alive(2, good_samples, 120.0, []),
                "启动失败退出码 2 —— 真实成因：装配抛异常（bootstrap 返回 EXIT_BOOTSTRAP_FAILED）"))
    # 坏法 2：crash.log 有内容 → S2 必须红（真实成因：worker 线程里没接住的异常）
    bad.append((v_no_crash(1024, 3, "Traceback (most recent call last): ..."),
                "crash.log 1024 字节 + 3 处 Traceback"))
    # 坏法 3：线程数从 5 涨到 12 → S3 必须红（真实成因：watchdog observer 每次重建没拆旧的，I5/I19）
    leak_threads = [dict(s, threads=5 + min(7, int(s["t"] / 20))) for s in good_samples]
    bad.append((v_threads(leak_threads), "线程数随时间线性增长到 12"))
    # 坏法 4：句柄从 700 涨到 1400 → S4 必须红（真实成因：每页出图新开连接不关）
    leak_handles = [dict(s, handles=700 + int(s["t"] * 6)) for s in good_samples]
    bad.append((v_handles(leak_handles), "句柄数一路上涨到 1400"))
    # 坏法 5：RSS 一路上涨 400MiB → S5 必须红（真实成因：I21 提到的推理资源不回收）
    leak_rss = [dict(s, rss_mib=300.0 + s["t"] * 3.4) for s in good_samples]
    bad.append((v_memory(leak_rss), "RSS 一路上涨约 400MiB"))
    # 坏法 6：内存峰值越过 G8 红线 → S5 必须红（真实成因：I16 的 OCR 峰值 806–1,131MiB 再叠 UI）
    fat = [dict(s, rss_mib=min(1250.0, 300.0 + s["t"] * 8)) for s in good_samples]
    bad.append((v_memory(fat), "RSS 峰值 1,250MiB 越过 G8 1,200MiB"))
    # 坏法 7：队列一直有 queued → S6 必须红（真实成因：处理器缺 dispatch，observer 线程死掉，I19）
    bad.append((v_backlog(False, 95.0, {"queued": 41}), "120 条里 41 条始终 queued"))
    # 坏法 7b：传感器瞎了 → S6 必须红，而且读数要说"读不到"，不能只说"没排空"。
    #          这条不是纸面上的坏法 —— 2026-10-15 第一轮真 soak 就是这么红的：
    #          backlog() 抄错表名（`jobs`，真表 `processing_jobs`），46 秒里每次读库都抛异常被吞掉。
    bad.append((v_backlog(False, 46.1,
                          {"_读库失败": "OperationalError: no such table: jobs"}),
                "表名抄错，S6 全程一次都没读到队列"))
    # 坏法 8：盘上 30 份库里只有 12 份 → S7 必须红（真实成因：事件丢了且周期校验还没到，I5/I6）
    #         坏法 9：轮转份数超过 keep+1 → S8 必须红（真实成因：handler 没装 rotation）
    #         这两条要真的连库、真的建文件，所以下面现场造。
    # 坏法 10：p12 输出里有"未验"→ S9 必须红（真实成因：跑的时候应用还开着，或快照目录口径错，I27）
    bad.append((v_consistency(1, "未验 C11 —— backups/ 里一份快照都没有"),
                "p12 判未验（I27 的真实坏法）"))

    caught = 0
    for row, why in bad:
        mark = "红" if not row.ok else "绿（← 这条断言没有牙）"
        log(f"  {mark}  {row.gate}\n        坏法：{why}\n        读数：{row.measured}")
        if not row.ok:
            caught += 1

    # 坏法 8/9 需要真文件系统与真库，这里现场造，确保不是"纸面上的坏法"；
    # 同时每条判据都配一份**好读数**，证明判据不是"恒红"—— 恒红的探针和恒红的断言一样没用。
    with tempfile.TemporaryDirectory(prefix="p13_inject_") as td:
        root = Path(td)
        (root / "data").mkdir(parents=True)
        conn = sqlite3.connect(root / "data" / "catalog.db")
        conn.execute("CREATE TABLE documents (path TEXT, missing_since INTEGER)")
        conn.executemany("INSERT INTO documents VALUES (?, NULL)", [("p",)] * 12)
        conn.commit()
        conn.close()
        extra = [(v_docs_match(root, 30), "盘上 30 份库里只有 12 份（I5/I6 的真实后果）"),
                 (v_logs(_mk_logs(root, "leaky", 9), 5, 5000), "轮转份数 9 > keep+1（handler 没装轮转）")]
        good = [v_docs_match(root, 12),
                v_logs(_mk_logs(root, "neat", 6), 5, 5000),
                v_backlog(True, 12.0, {"done": 68, "failed": 3})]
        for row, why in extra:
            log(f"  {'红' if not row.ok else '绿（← 这条判据没有牙）'}  {row.gate}\n"
                f"        坏法：{why}\n        读数：{row.measured}")
            if not row.ok:
                caught += 1
        for row in good:
            log(f"  {'绿（好读数正确放行）' if row.ok else '红（← 判据恒红，不能用）'}  {row.gate}\n"
                f"        读数：{row.measured}")

    total = len(bad) + len(extra)
    good_passed = sum(1 for r in good if r.ok)
    log(f"注入自检：抓到 {caught}/{total} 条坏法｜好读数放行 {good_passed}/{len(good)}")
    if caught != total or good_passed != len(good):
        log("VERDICT: RED（有坏法骗过判据）")
        return 1
    log("VERDICT: ALL GREEN")
    return 0


def _mk_logs(root: Path, name: str, how_many: int) -> Path:
    """在独立子目录里造出 `how_many` 份 app.log 轮转文件（每份都要独占目录，
    否则"好读数"那次会看见上一次留下的文件，判据恒红 —— 注入自检第一跑就踩了这个）。"""
    logs = root / name
    logs.mkdir(parents=True, exist_ok=True)
    for i in range(how_many):
        (logs / ("app.log" if i == 0 else f"app.log.{i}")).write_text("x" * 1024, encoding="utf-8")
    return logs


# ───────────────────────────── 主流程 ─────────────────────────────

def run(minutes: float, keep: bool) -> int:
    soak = minutes * 60.0
    work = Path(tempfile.mkdtemp(prefix="p13_soak_"))
    data_root, corpus = work / "data_root", work / "corpus"
    log(f"现场：{work}｜soak {soak:.0f}s｜采样 {SAMPLE_SECONDS}s｜投放每 {CHURN_EVERY:.0f}s")
    rows: list[Row] = []
    proc: subprocess.Popen[str] | None = None
    try:
        made = build_corpus(corpus)
        # 先把库装配出来（迁移、默认分类、登记监测根、排一条全量扫描），再起真应用进程
        from pdfarchiver.services.bootstrap import bootstrap
        warm = bootstrap(data_root)
        warm.shutdown()
        seed_library(data_root, corpus)

        env = {**os.environ, "QT_QPA_PLATFORM": "offscreen", "PYTHONIOENCODING": "utf-8",
               "PYTHONPATH": str(REPO / "src")}
        # 子进程输出写文件而不是 PIPE：本探针在 soak 结束前不读管道，
        # 用 PIPE 一旦 Qt 警告把 64KB 缓冲写满就会把被测进程卡住 —— 那就不再是"验它稳不稳"了
        stdout_file = work / "app_stdout.log"
        fh = stdout_file.open("w", encoding="utf-8", errors="replace")
        # --exit-after 比 soak 多给 45s：投放完还要等积压排空，那段时间进程必须还活着
        proc = subprocess.Popen([sys.executable, "-m", "pdfarchiver.app",
                                 "--data-dir", str(data_root),
                                 "--exit-after", str(int(soak + 45))],
                                cwd=str(work), env=env,
                                stdout=fh, stderr=subprocess.STDOUT, text=True)
        sampler = Sampler(proc).start()
        t0 = time.monotonic()
        churned = 0
        while time.monotonic() - t0 < soak:
            if proc.poll() is not None:
                break
            time.sleep(max(0.0, CHURN_EVERY - (time.monotonic() - t0) % CHURN_EVERY))
            churned += _churn(corpus, int(time.monotonic() - t0))
        samples = sampler.stop()
        churn_seconds = time.monotonic() - t0
        log(f"投放结束：{churned} 轮变更，用时 {churn_seconds:.1f}s｜采样 {len(samples)} 点")

        # S6：停止投放后等积压排空（进程还在跑，worker 还在领活）
        drained, lag, states = _wait_drain(data_root, proc)
        log(f"排空：{drained}｜用时 {lag:.1f}s｜状态 {states}")

        rc = proc.wait(timeout=180)
        fh.close()
        out = stdout_file.read_text(encoding="utf-8", errors="replace") if stdout_file.exists() else ""
        logs_dir = data_root / "logs"
        crash = logs_dir / "crash.log"
        crash_bytes = crash.stat().st_size if crash.exists() else 0
        # Traceback 要跨轮转份数一起数：只查当前那份 app.log 会漏掉刚轮转走的崩溃
        text = "".join(f.read_text(encoding="utf-8", errors="replace")
                       for f in sorted(logs_dir.glob("app.log*")))
        lines_now = _line_count(logs_dir / "app.log")
        rows.append(v_alive(rc, samples, soak, sampler.errors))
        rows.append(v_no_crash(crash_bytes, text.count("Traceback"), out))
        rows.append(v_threads(samples))
        rows.append(v_handles(samples))
        rows.append(v_memory(samples))
        rows.append(v_backlog(drained, lag, states))
        rows.append(v_docs_match(data_root, len(list(corpus.rglob("*.pdf")))))
        rows.append(v_logs(logs_dir, _keep_files(data_root), lines_now))
        p12 = subprocess.run([sys.executable, P12, "--data-root", str(data_root)],
                             cwd=str(REPO), env={**os.environ, "PYTHONPATH": str(REPO / "src"),
                                                 "QT_QPA_PLATFORM": "offscreen",
                                                 "PYTHONIOENCODING": "utf-8"},
                             capture_output=True, text=True, encoding="utf-8", errors="replace",
                             timeout=600)
        rows.append(v_consistency(p12.returncode, (p12.stdout or "")[-400:]))

        RESULT.parent.mkdir(exist_ok=True)
        RESULT.write_text(json.dumps({"soak_seconds": soak, "samples": samples,
                                      "rows": [asdict(r) for r in rows],
                                      "churn_rounds": churned, "exit_code": rc},
                                     ensure_ascii=False, indent=2), encoding="utf-8")
        log(f"读数已写：{RESULT}")
    finally:
        if proc and proc.poll() is None:
            proc.kill()
        if keep:
            log(f"--keep：现场留着 {work}")
        else:
            shutil.rmtree(work, ignore_errors=True)

    red = 0
    for r in rows:
        log(f"  {'绿' if r.ok else '红'}  {r.gate}\n        {r.measured}")
        red += 0 if r.ok else 1
    log(f"  合计 {len(rows)} 条｜红 {red} 条")
    log("VERDICT: ALL GREEN" if not red else f"VERDICT: RED（{red} 条）")
    return 0 if not red else 1


def _churn(corpus: Path, stamp: int) -> int:
    """投放变更：新增 / 覆盖 / 删除各若干 —— 三条代码路都要在长跑里反复被走。"""
    from conftest import _make_pdf

    churn = corpus / "churn"
    churn.mkdir(exist_ok=True)
    for i in range(CHURN_ADD):
        _make_pdf(churn / f"soak_add_{stamp}_{i}.pdf", pages=1,
                  lines=[f"soak 投放第 {stamp} 轮第 {i} 号样本正文"])
    victim = sorted(churn.glob("soak_add_*.pdf"))
    if victim:
        _make_pdf(victim[0], pages=2, lines=[f"soak 投放第 {stamp} 轮被覆盖的那份正文"])
        victim[-1].unlink()
    return 1


def _wait_drain(data_root: Path, proc: subprocess.Popen[str]) -> tuple[bool, float, dict[str, int]]:
    """等队列里"还没办完的活"清零。未完成态只有三种 —— `LEGAL_TRANSITIONS` 里没有 `retry`，
    把它列进来等于对着一个永不出现的状态做断言，所以按真状态列写。

    读库报错不中断等待（应用正在写时短暂读不到是真事），但**第一条原文要留着**：
    上一版把它吞了，于是 46 秒的等待全程瞎着，读数里只剩一个空字典，看不出是"队列没排空"
    还是"根本没读到队列" —— 这两种红的修法完全不同。
    """
    t0 = time.perf_counter()
    states: dict[str, int] = {}
    first_error = ""
    while time.perf_counter() - t0 < BACKLOG_DRAIN_MAX and proc.poll() is None:
        try:
            states = backlog(data_root)
        except sqlite3.Error as exc:
            first_error = first_error or f"{type(exc).__name__}: {exc}"
            time.sleep(1.0)
            continue
        if not any(k in states for k in OPEN_STATES):
            return True, time.perf_counter() - t0, states
        time.sleep(1.0)
    try:
        states = backlog(data_root)
    except sqlite3.Error as exc:
        states = {"读库失败": 1}
        first_error = first_error or f"{type(exc).__name__}: {exc}"
    if first_error:
        states["_读库失败"] = first_error  # type: ignore[assignment]
    return False, time.perf_counter() - t0, states


def _line_count(path: Path) -> int:
    if not path.exists():
        return 0
    with path.open("rb") as f:
        return sum(1 for _ in f)


def _keep_files(data_root: Path) -> int:
    from pdfarchiver.config.settings import DEFAULTS

    return int(DEFAULTS["log_keep_files"])


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="长时间运行稳定性采样（详见模块文档的三条诚实边界）")
    ap.add_argument("--minutes", type=float, default=4.0, help="soak 时长，默认 4 分钟")
    ap.add_argument("--keep", action="store_true", help="跑完保留现场目录")
    ap.add_argument("--inject", action="store_true", help="反向注入自检：每条判据真注入一次坏法")
    args = ap.parse_args(argv)
    if args.inject:
        return inject()
    return run(args.minutes, args.keep)


if __name__ == "__main__":
    raise SystemExit(main())
