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
import logging
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
SAMPLE_GAP_MAX = 10.0       # 相邻采样点最大允许间隔；超过说明本机睡过/被冻结，读数不再是连续观测
CHURN_EVERY = 15.0          # 每 15 秒投放一批文件变更；短于此会被周期校验（默认 30 分钟）掩盖
CHURN_ADD = 3               # 每轮新增几份、改一份、删一份 —— 三条路都要在长跑里反复走
BULK_SEED = 20              # 起跑前库里先有多少份

THREAD_LEAK_MAX = 2         # 相对首段中位数最多再多几个线程（worker 2 + observer + Qt 内部）
HANDLE_LEAK_MAX = 200       # 相对首段中位数最多再多几个句柄
RSS_GROWTH_MAX_MIB = 80.0   # 末段中位数 - 首段中位数：几分钟内涨这么多就是留着不放
G8_LIMIT_MIB = 1200.0       # 内存红线；[约定] 单位口径按更严的 1,200MiB 一档（I16 说这条没写明）
BACKLOG_DRAIN_MAX = 90.0    # 停止投放后，队列从有活到全空最多允许多少秒
BURST_ADD = 30              # 停投放前种入的收尾积压份数 —— S6 必须有一次真排空，不能空转
BURST_OBSERVE_MAX = 30.0    # 等积压被观测到（队列出现非终态）的上限；观测不到时 S6 判「未验」
BURST_OBSERVE_POLL = 0.25   # 观察期轮询间隔：收尾这批清得快，1s 网格会整个错过
OPEN_STATES = ("queued", "running", "paused")   # `LEGAL_TRANSITIONS` 里全部非终态，一个不多一个不少
LOG_ROTATION_SLACK = 1      # 轮转份数只许比 log_keep_files 多 1（当前那份）


@dataclass
class Row:
    gate: str
    ok: bool
    measured: str


def log(msg: str) -> None:
    try:
        print(msg, flush=True)
    except UnicodeEncodeError:
        # 2026-10-22 的真事故：stdout 重定向到文件时控制台编码是 GBK，S5 读数里的 U+2212
        # 直接把探针打死在打印阶段（库已跑完 2 小时，结果却没打出来）。降级成可编码字符继续打。
        enc = getattr(sys.stdout, "encoding", None) or "ascii"
        sys.stdout.write(msg.encode(enc, "replace").decode(enc) + "\n")
        sys.stdout.flush()


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
                 interval: float = SAMPLE_SECONDS, marker: str = "") -> None:
        self.proc = proc
        # interval 是给「同一棵树要量峰值而不是趋势」的探针（p19）留的口子：2s 采趋势够用，
        # 但一次几秒就完成的内存尖峰会被 2s 网格整个漏掉。默认值不变，p13 的读数口径不变。
        self.interval = interval
        # 启动壳先退时靠它找回真正的应用进程：命令行里带着数据根目录这条现场标记
        self.marker = marker
        self.samples: list[dict[str, float]] = []
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.errors: list[str] = []

    def start(self) -> "Sampler":
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        return self

    def _loop(self) -> None:
        """采样线程一死，S3–S5 就全变成"没有读数"——异常原文必须留在 errors 里。

        2026-10-21 轮十七的真 soak 踩过：`root.children(recursive=True)` 在启动壳退出的瞬间
        抛 NoSuchProcess，线程静默结束、0 个采样点，读数里只剩三句"没有读数"，看不出是产品
        没线程还是传感器先死了（`docs/ISSUES.md` **I100**）。
        """
        import psutil

        try:
            while not self._stop.wait(self.interval):
                live = self._live_tree(psutil)
                if not live:
                    self.errors.append(
                        f"NoSuchProcess: pid {self.proc.pid} 及其子进程都不在了"
                        + (f"（现场标记 {self.marker} 也没找到）" if self.marker else ""))
                    return
                row = {"t": round(time.monotonic(), 1), "rss_mib": 0.0, "cpu": 0.0,
                       "threads": 0, "pids": len(live)}
                handles = 0
                has_handles = False
                for p in live:
                    try:
                        row["rss_mib"] += p.memory_info().rss / 1048576.0
                    except psutil.Error:
                        continue
                    try:
                        row["cpu"] += p.cpu_percent()
                        row["threads"] += p.num_threads()
                    except psutil.Error:
                        pass
                    if hasattr(p, "num_handles"):      # 只有 Windows 有这一项
                        try:
                            handles += p.num_handles()
                            has_handles = True
                        except psutil.Error:
                            pass
                row["rss_mib"] = round(row["rss_mib"], 1)
                row["cpu"] = round(row["cpu"], 1)
                if has_handles:
                    row["handles"] = handles
                self.samples.append(row)
        except Exception as exc:  # noqa: BLE001 - 线程自己炸了也要留下原文，不能静默退出
            self.errors.append(f"{type(exc).__name__}: {exc}")

    def _live_tree(self, psutil) -> list:
        """从 Popen 的 pid 起逐个子进程往下走；启动壳不在了就按现场标记找真身。

        `children(recursive=True)` 是"一次性走完整棵树"，任何一个子进程在遍历途中消失都会
        让整次解析抛异常 —— 所以这里改成逐层 BFS，每个 pid 的读取各自兜住。
        """
        roots = []
        try:
            roots.append(psutil.Process(self.proc.pid))
        except psutil.Error:
            pass
        if not roots and self.marker:
            for p in psutil.process_iter(["pid", "cmdline"]):
                try:
                    cmdline = p.info.get("cmdline") or []
                except psutil.Error:
                    continue
                if any(self.marker in str(part) for part in cmdline):
                    roots.append(p)
        live: list = []
        seen: set[int] = set()
        queue = list(roots)
        while queue:
            p = queue.pop()
            if p.pid in seen:
                continue
            seen.add(p.pid)
            try:
                p.memory_info()
            except psutil.Error:
                continue
            live.append(p)
            try:
                queue.extend(p.children(recursive=False))
            except psutil.Error:
                continue
        return live

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


def _max_gap(samples: list[dict[str, float]]) -> tuple[float, float]:
    """相邻采样点之间最大的时间空洞（秒）与它起点的 t。

    本机休眠 / 进程被冻结时，`Sampler` 的等待计时跟着停，醒来后只会在 `t` 上留下一个大洞。
    采样点数可能仍然达标，但那段空洞里产品完全没被观测 —— 不能当连续长跑读数用。
    """
    gaps = [(b["t"] - a["t"], a["t"]) for a, b in zip(samples, samples[1:])]
    return max(gaps, default=(0.0, 0.0))


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
    gap, gap_at = _max_gap(samples)
    continuous = gap <= SAMPLE_GAP_MAX
    return Row(gate, rc == 0 and len(samples) >= expected_seconds / SAMPLE_SECONDS * 0.7 and continuous,
               f"退出码 {rc}｜采样 {len(samples)} 点（预期约 {expected_seconds / SAMPLE_SECONDS:.0f} 点）"
               f"｜最大采样空洞 {gap:.1f}s｜采样间隔内 RSS 中位 {med:.1f}MiB"
               + ("" if continuous else
                  f" ── 本机休眠/冻结过（{gap_at:.1f}s 处起空 {gap:.1f}s），这段没被观测，读数不作数")
               + ("" if not early_errors else " ── 采样中断：" + early_errors[0]))


def v_no_crash(crash_bytes: int, traceback_count: int, log_tail: str) -> Row:
    gate = "S2 全程无未捕获异常（crash.log 为空 / app.log 无 Traceback）"
    return Row(gate, crash_bytes == 0 and traceback_count == 0,
               f"crash.log {crash_bytes} 字节｜app.log*（含轮转份数）里 Traceback {traceback_count} 处"
               + ("" if crash_bytes == 0 else f" ── 进程输出尾部：{log_tail[-240:]}"))


def v_threads(samples: list[dict[str, float]]) -> Row:
    gate = f"S3 线程不泄漏（末段中位 − 首段中位 ≤ {THREAD_LEAK_MAX}）"
    if not samples:
        return Row(gate, False, "一个采样点都没拿到（采样线程先退出了，原因见 S1 的采样中断说明）")
    if "threads" not in samples[0]:
        return Row(gate, False, "采样里没有 threads 列（传感器缺列，不是产品没线程）")
    head, tail = _split(samples, "threads")
    delta = _median(tail) - _median(head)
    worst = max(float(s["threads"]) for s in samples)
    return Row(gate, delta <= THREAD_LEAK_MAX,
               f"首段中位 {_median(head):.0f} → 末段中位 {_median(tail):.0f}（差 {delta:+.0f}）"
               f"｜全程峰值 {worst:.0f}")


def v_handles(samples: list[dict[str, float]]) -> Row:
    gate = f"S4 句柄不泄漏（末段中位 − 首段中位 ≤ {HANDLE_LEAK_MAX}）"
    if not samples:
        return Row(gate, False, "一个采样点都没拿到（采样线程先退出了，原因见 S1 的采样中断说明）")
    if not any("handles" in s for s in samples):
        return Row(gate, False, "本机 psutil 没有 num_handles 读数（非 Windows）")
    head, tail = _split(samples, "handles")
    delta = _median(tail) - _median(head)
    return Row(gate, delta <= HANDLE_LEAK_MAX,
               f"首段中位 {_median(head):.0f} → 末段中位 {_median(tail):.0f}（差 {delta:+.0f}）"
               f"｜全程峰值 {max(float(s['handles']) for s in samples if 'handles' in s):.0f}")


def v_memory(samples: list[dict[str, float]]) -> Row:
    gate = f"S5 内存增长有界（末段中位 − 首段中位 ≤ {RSS_GROWTH_MAX_MIB}MiB，且不越 G8 {G8_LIMIT_MIB:.0f}MiB [约定]）"
    if not samples:
        return Row(gate, False, "一个采样点都没拿到（采样线程先退出了，原因见 S1 的采样中断说明）")
    head, tail = _split(samples, "rss_mib")
    growth = _median(tail) - _median(head)
    peak = max(float(s["rss_mib"]) for s in samples)
    trough = min(float(s["rss_mib"]) for s in samples)
    return Row(gate, growth <= RSS_GROWTH_MAX_MIB and peak <= G8_LIMIT_MIB,
               f"首段中位 {_median(head):.1f} → 末段中位 {_median(tail):.1f}MiB（增长 {growth:+.1f}）"
               f"｜全程 {trough:.1f}–{peak:.1f}MiB"
               f"｜G8 余量 {G8_LIMIT_MIB - peak:.1f}MiB（单位取 1,200MiB 一档，见 I16）")


def v_backlog(drained: bool, lag: float, states: dict[str, int], peak_open: int = 0) -> Row:
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
    elif peak_open <= 0:
        # 2026-10-21 轮十七的真实形状：churn 边投边办，停投放那一刻队列恰好是空的，
        # `0.0s {'done': 88}` 看着完美，实际排空逻辑一次都没被走到 —— 空转通过不算验证。
        tail = (" ── 种入的积压一次都没被观测到（队列全程非终态为空），"
                "这次排空是空转，这条没有被验证")
    return Row(gate, drained and peak_open > 0,
               f"观察窗峰值积压 {peak_open} 条｜排空用时 {lag:.1f}s｜"
               f"结束时队列状态 {shown or '无任务行'}{tail}")


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
    gate = "S9 长跑现场通过 p12 一致性核查（14 条全绿 0 未验）"
    return Row(gate, rc == 0 and "未验 0 条" in tail and "ALL GREEN" in tail,
               tail.replace("\n", " ") or "p12 没有输出")


# ───────────────────────────── 反向注入自检 ─────────────────────────────

def bootstrap_without_hooks(data_root: Path):
    """在探针进程里装配一次产品运行时，返回 ctx；把 excepthook 与日志 handler 立刻还回去。

    `bootstrap()` 装的是**进程级** excepthook，落点是本次数据根目录的 `crash.log`。探针
    自己要接着跑（采样线程、p12 子进程都在探针进程里），所以装完必须立刻还：2026-10-21
    轮十七的真 soak 里，采样线程的 NoSuchProcess 被写进了**被测应用**的 crash.log
    （S2 假红 2,127 字节），采样线程同时静默退出（S3–S5 全成"没有读数"）。
    日志 handler 也一起摘掉，否则探针后续的 logging 还会往被测进程的 app.log 里写。
    """
    from pdfarchiver.services.bootstrap import bootstrap

    hooks = (sys.excepthook, threading.excepthook)
    try:
        return bootstrap(data_root)
    finally:
        sys.excepthook, threading.excepthook = hooks
        logger = logging.getLogger("pdfarchiver")
        for handler in [h for h in logger.handlers if getattr(h, "_pdfarchiver_owned", False)]:
            logger.removeHandler(handler)
            handler.close()


def _bootstrap_and_seed(data_root: Path, corpus: Path) -> None:
    """先把库装配出来（迁移、默认分类、登记监测根、排一条全量扫描），再起真应用进程。"""
    warm = bootstrap_without_hooks(data_root)
    warm.shutdown()
    seed_library(data_root, corpus)


def _prevent_sleep() -> None:
    """长跑期间向系统要一个「别睡」的请求，避免再次把休眠场错当连续观测。

    2026-10-22 那场 2 小时 soak 就是被本机休眠打断的：睡了约 36.2 + 13.7 分钟，进程被冻结，
    采样出现 2,170s / 822s 两个空洞，收尾的积压种入落空，S6/S7/S9 连带假红。
    请求按线程生效，探针退出即自动失效；非 Windows 上是空操作。
    """
    if sys.platform != "win32":
        return
    import ctypes

    es_continuous, es_system_required = 0x80000000, 0x00000001
    ctypes.windll.kernel32.SetThreadExecutionState(es_continuous | es_system_required)


def _allow_sleep() -> None:
    if sys.platform != "win32":
        return
    import ctypes

    ctypes.windll.kernel32.SetThreadExecutionState(0x80000000)  # ES_CONTINUOUS


def run(minutes: float, keep: bool) -> int:
    soak = minutes * 60.0
    work = Path(tempfile.mkdtemp(prefix="p13_soak_"))
    data_root, corpus = work / "data_root", work / "corpus"
    log(f"现场：{work}｜soak {soak:.0f}s｜采样 {SAMPLE_SECONDS}s｜投放每 {CHURN_EVERY:.0f}s")
    rows: list[Row] = []
    _UNLINK_SKIPS["count"] = 0
    proc: subprocess.Popen[str] | None = None
    _prevent_sleep()
    try:
        made = build_corpus(corpus)
        _bootstrap_and_seed(data_root, corpus)

        env = {**os.environ, "QT_QPA_PLATFORM": "offscreen", "PYTHONIOENCODING": "utf-8",
               "PYTHONPATH": str(REPO / "src")}
        # 子进程输出写文件而不是 PIPE：本探针在 soak 结束前不读管道，
        # 用 PIPE 一旦 Qt 警告把 64KB 缓冲写满就会把被测进程卡住 —— 那就不再是"验它稳不稳"了
        stdout_file = work / "app_stdout.log"
        fh = stdout_file.open("w", encoding="utf-8", errors="replace")
        # --exit-after 比 soak 多给 45s 排空 + 30s 积压观察：投放完还要等一个"确定存在过"的
        # 积压被排空，那段时间进程必须还活着（轮十七之前这里只给 45s，S6 靠空转也能绿）
        proc = subprocess.Popen([sys.executable, "-m", "pdfarchiver.app",
                                 "--data-dir", str(data_root),
                                 "--exit-after", str(int(soak + 45 + BURST_OBSERVE_MAX))],
                                cwd=str(work), env=env,
                                stdout=fh, stderr=subprocess.STDOUT, text=True)
        sampler = Sampler(proc, marker=str(data_root)).start()
        t0 = time.monotonic()
        churned = 0
        while time.monotonic() - t0 < soak:
            if proc.poll() is not None:
                break
            time.sleep(max(0.0, CHURN_EVERY - (time.monotonic() - t0) % CHURN_EVERY))
            churned += _churn(corpus, int(time.monotonic() - t0))
        # S6 的前置：种一批确定能被观测到的积压并等它出现。churn 边投边办，停投放那一刻
        # 队列往往恰好是空的 —— 不种这一批，"排空 0.0s"就是空转通过（轮十七 r17c 的 0.0s）。
        _seed_burst(corpus)
        peak_open, observe_error = _observe_backlog(data_root, proc)
        log(f"积压观测：峰值 {peak_open} 条｜"
            + ("已观测到非终态" if peak_open > 0 else "没有观测到非终态")
            + (f"｜读库原文：{observe_error}" if observe_error else ""))
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
        rows.append(v_backlog(drained, lag, states, peak_open))
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
                                      "rows": [asdict(r) for r in rows], "backlog_peak": peak_open,
                                      "churn_rounds": churned,
                                      "churn_unlink_skipped": _UNLINK_SKIPS["count"],
                                      "exit_code": rc},
                                     ensure_ascii=False, indent=2), encoding="utf-8")
        log(f"读数已写：{RESULT}")
        if _UNLINK_SKIPS["count"]:
            log(f"churn 删除被占用跳过 {_UNLINK_SKIPS['count']} 次（每次最多 5 次重试、共约 1s）")
    finally:
        _allow_sleep()
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


_UNLINK_SKIPS = {"count": 0}


def _unlink_retry(path: Path, attempts: int = 5, delay: float = 0.2) -> bool:
    """应用可能正在读刚投放的样本：Windows 上会 WinError 32。
    短暂重试仍被占用就跳过这一轮删除并计数；曾经没接这一手，探针自己崩掉了一整场 soak。"""
    for i in range(attempts):
        try:
            path.unlink()
            return True
        except PermissionError:
            if i + 1 == attempts:
                _UNLINK_SKIPS["count"] += 1
                return False
            time.sleep(delay)
    return False


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
        _unlink_retry(victim[-1])
    return 1


def _seed_burst(corpus: Path) -> int:
    """停投放前种入一批收尾积压：S6 要排的必须是**确定存在过**的积压。

    2026-10-21 轮十七 r17c 的读数 `0.0s {'done': 88}` 暴露的正是相反形状：churn 每 15s
    投一批、worker 边投边办，停投放那一刻队列恰好是空的 —— 排空判据"绿"了，但它要守的
    那条路（有活 → 领走 → 清空）一次都没被走到。单独目录 `burst/` 不干扰 churn 的增删循环。
    """
    from conftest import _make_pdf

    burst = corpus / "burst"
    burst.mkdir(exist_ok=True)
    for i in range(BURST_ADD):
        _make_pdf(burst / f"soak_burst_{i:03d}.pdf", pages=1,
                  lines=[f"soak 收尾积压第 {i} 号样本正文"])
    return BURST_ADD


def _observe_backlog(data_root: Path, proc: subprocess.Popen[str],
                     timeout: float = BURST_OBSERVE_MAX) -> tuple[int, str]:
    """种入积压后盯着队列，直到出现非终态或超时。返回（观察窗峰值未完成数，读库错误原文）。

    轮询比排空期密一个量级：30 份一页 PDF 在这台机器上一两秒就能办完，1s 网格会整个错过、
    把"清得太快"误判成"从没出现过"。读库报错不中断观察（应用正在写时短暂读不到是真事），
    但第一条原文要带回去 —— 观察不到积压时，"消费太快"和"传感器瞎了"的修法完全不同。
    """
    peak = 0
    first_error = ""
    t0 = time.perf_counter()
    while time.perf_counter() - t0 < timeout and proc.poll() is None:
        try:
            states = backlog(data_root)
        except sqlite3.Error as exc:
            first_error = first_error or f"{type(exc).__name__}: {exc}"
            time.sleep(BURST_OBSERVE_POLL)
            continue
        open_now = sum(v for k, v in states.items() if k in OPEN_STATES)
        peak = max(peak, open_now)
        if open_now > 0:
            return peak, ""
        time.sleep(BURST_OBSERVE_POLL)
    return peak, first_error


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
        from p13_soak_inject import inject  # noqa: PLC0415 注入段独立成 p13_soak_inject.py
        return inject()
    return run(args.minutes, args.keep)


if __name__ == "__main__":
    raise SystemExit(main())
