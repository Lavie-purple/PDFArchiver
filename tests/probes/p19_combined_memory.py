"""P19 组合内存压测 —— 销账 ISSUES I16（各组件只单点测过，合起来从来没量过）。

跑法：
    python tests/probes/p19_combined_memory.py            # 四个窗口跑完，7 条判定
    python tests/probes/p19_combined_memory.py --inject   # 反向注入自检（每条判据真喂坏读数）
    python tests/probes/p19_combined_memory.py --keep     # 跑完保留现场，进去看日志

**量的是同一台机器上四个窗口的峰值，不是四个绝对值的横比**（读数负载绑定，I25 同源）：

    窗口 A  只有界面            —— offscreen 真窗口进程（取舍与代价见 I17），队列空着
    窗口 B  界面 + 索引         —— 真扫描 + 逐份索引跑完
    窗口 C  界面 + 索引 + OCR   —— OCR 任务在跑，churn 持续排新的 index 任务
    窗口 D  只有 OCR            —— 另起一个干净解释器走服务层，不加载 Qt（由 m5 钉住）

四条必须读清楚的诚实边界：

1. **`worker_threads=1`（I46 甲）意味着窗口 C 的"同时活"不是两条线程在并行**，而是
   "引擎常驻 + 任务交替"：单条 worker 一次只领一个任务，OCR 那一块在第一次 OCR 之后就留在
   进程树里，随后的 index 任务是在"引擎已经占着的内存之上"跑的。**这正是产品默认配置下
   用户会遇到的形态**，窗口 C 量的就是它。手工把 `worker_threads` 调成 2 之后的叠加形态
   没有在这里测（也不是产品会跑出的形态）。
2. **G8 的单位口径没有拍板**（I16 自己记着，等 Q4）。这里不替用户决定：判定取更严的一档
   （1,200MiB），但 1,200 / 1,228.8 两档余量一律同时印出来。
3. **语料是本探针自己画的合成样本**（几十份 / 十几页），不是真实语料的 10,977 份 / 202 万页。
   真实语料一页都没被这里用过（I64：库里 ids 1–3 是用户数据，不当夹具）。
   样本不 import `tests/conftest.py` 而是本地画 —— 窗口 D 要的是一个**干净进程**，
   把 pytest 拖进对照里就没法说"D 只多了 OCR"（`gates/stage5.py` 同源的做法）。
4. **"低可用内存时刻"这里只记读数，不设阈值**（AGENTS.md：阈值只有两种合法来源，
   "多少算低"两者都不是）。m6 判的是"读数必须上屏"，等不等于"低"由人判。

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
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
for _p in (REPO / "src", REPO / "tests" / "probes"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

RESULT = REPO / ".probe_work" / "p19_combined_memory_result.json"

SCANNED_DOCS = 4            # 纯扫描件：整页贴图、零文本层，OCR 的待办页判据只对这种成立
PAGES_PER_SCANNED = 3       # → OCR 窗口共 12 页（峰值主要由引擎载入决定，页数只是让它持续几秒）
NATIVE_DOCS = 30            # 有原生文本层的样本：索引窗口的活
CHURN_DOCS = 12             # 窗口 C 期间每轮投放几份，让索引在 OCR 跑着的时候同时在跑
IDLE_SECONDS = 25.0         # 窗口 A 的长度
CAP_SCAN = 240.0            # 窗口 B 等排空的上限
CAP_OCR = 300.0             # 窗口 C 等「OCR 落库 + 队列排空」的上限
DRAIN_SETTLE = 5.0          # 窗口 C 里 OCR 页够了之后，再多看这么多秒确认队列真排空
SAMPLE_SECONDS = 1.0        # 峰值采样网格：p13 的 2s 是采趋势的，会把几秒高的尖峰整个漏掉
LINES_PER_PAGE = 12         # 与 conftest 同口径：12 行 × 每行 ≥4 字 = 一页 ≥40 字，classify 才判 native

G8_STRICT_MIB = 1200.0      # "1.2GB" 按 1.2×10^9 折 MiB
G8_LOOSE_MIB = 1228.8       # "1.2GiB" 按 1.2×2^30 折 MiB
OPEN_STATES = ("queued", "running", "paused")


@dataclass
class Row:
    gate: str
    ok: bool
    measured: str


def log(msg: str) -> None:
    print(msg, flush=True)


# ───────────────────────────── 造现场（本地画样本，不 import conftest）─────────────────────────────

def _native_pdf(path: Path, *, pages: int, line: str) -> None:
    """有原生文本层的真 PDF。`fontname="china-s"` 是 PyMuPDF 内置简体中文字体 ——
    用 `helv` 中文会画成一串 `··`，提取出来的正文不是那几个字（conftest 同一处实测）。"""
    import pymupdf

    path.parent.mkdir(parents=True, exist_ok=True)
    doc = pymupdf.open()
    for _ in range(pages):
        page = doc.new_page(width=595, height=842)
        y = 40
        for i in range(LINES_PER_PAGE):
            page.insert_text((36, y), f"{line}第{i}行", fontsize=11, fontname="china-s")
            y += 16
    doc.save(str(path))
    doc.close()


def _scanned_pdf(path: Path, *, pages: int) -> None:
    """整页贴图、**零文本层** —— 产品口径的"缺字页"，OCR 唯一该干的活。"""
    import pymupdf

    path.parent.mkdir(parents=True, exist_ok=True)
    doc = pymupdf.open()
    draft = doc.new_page(width=400, height=300)
    shape = draft.new_shape()
    shape.draw_rect(pymupdf.Rect(20, 20, 380, 280))
    shape.finish(color=(0.1, 0.1, 0.1), fill=(0.85, 0.85, 0.85))
    shape.commit()
    stream = draft.get_pixmap().tobytes("png")
    for _ in range(pages):
        page = doc.new_page(width=400, height=300)
        page.insert_image(page.rect, stream=stream)
    doc.delete_page(0)      # 留着草稿页，页数就比预期的多一页，页码断言会莫名差一
    doc.save(str(path))
    doc.close()


def build_corpus(corpus: Path) -> int:
    for i in range(SCANNED_DOCS):
        _scanned_pdf(corpus / "scanned" / f"p19_scan_{i}.pdf", pages=PAGES_PER_SCANNED)
    for i in range(NATIVE_DOCS):
        _native_pdf(corpus / "native" / f"p19_native_{i:02d}.pdf", pages=2,
                    line=f"p19 索引样本第{i}号可检索中文字串")
    (corpus / "churn").mkdir(exist_ok=True)
    return SCANNED_DOCS + NATIVE_DOCS


def churn(corpus: Path, stamp: int) -> int:
    for i in range(CHURN_DOCS):
        _native_pdf(corpus / "churn" / f"p19_churn_{stamp}_{i}.pdf", pages=1,
                    line=f"p19 投放第{stamp}轮第{i}号正文样本")
    return CHURN_DOCS


# ───────────────────────────── 读写库（只读口径与 p13 同源）─────────────────────────────

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


def open_backlog(data_root: Path) -> dict[str, int]:
    """表名 `processing_jobs` 是抄不得的（p13 的 S6 就因为抄成 `jobs` 全程瞎了 46 秒，I29 同族）。"""
    rows = query(data_root, "SELECT state, count(*) FROM processing_jobs GROUP BY state")
    return {k: v for k, v in dict(rows).items() if k in OPEN_STATES}


def register_root(data_root: Path, corpus: Path, label: str) -> None:
    """探针侧登记监测根（与 `p13_soak.seed_library` 同一条仓储路，不装配服务层）。"""
    from pdfarchiver.db.engine import Engine
    from pdfarchiver.db.repositories.roots import RootRepository
    from pdfarchiver.fs.identity import identity_key

    engine = Engine(data_root / "data" / "catalog.db", busy_timeout_ms=5000)
    try:
        RootRepository(engine).add(str(corpus).replace("\\", "/"), identity_key(corpus),
                                   label=label)
    finally:
        engine.close_thread_connection()


def enqueue(data_root: Path, kind: str, doc_ids: list[int]) -> int:
    """排活，返回**真正新增**条数。`enqueue` 去重命中返回 None ——
    把"排了"当成"排进去了"会让 m2 那条"组合真的在跑"变成自证。"""
    from pdfarchiver.db.engine import Engine
    from pdfarchiver.db.repositories.jobs import JobRepository

    engine = Engine(data_root / "data" / "catalog.db", busy_timeout_ms=5000)
    try:
        jobs = JobRepository(engine)
        if kind == "scan":
            return 1 if jobs.enqueue("scan") else 0
        return sum(1 for d in doc_ids if jobs.enqueue("ocr", d))
    finally:
        engine.close_thread_connection()


# ───────────────────────────── 采样 ─────────────────────────────
# 窗口 A/B/C 复用 p13 的 Sampler：**必须采整棵进程树**，本机 venv 的 python.exe 是个启动壳，
# 真跑 Qt 的是它 spawn 的子进程，只盯 launcher 会采出一组漂亮但无意义的读数（I29）。

class SelfSampler:
    """窗口 D 用：那个干净进程自己采自己（含子进程，正常应该只有它自己）。"""

    def __init__(self, interval: float = SAMPLE_SECONDS) -> None:
        self.interval = interval
        self.samples: list[dict[str, float]] = []
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> "SelfSampler":
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        return self

    def _loop(self) -> None:
        import psutil

        me = psutil.Process(os.getpid())
        while not self._stop.wait(self.interval):
            live = [me]
            for child in me.children(recursive=True):
                try:
                    child.memory_info()
                    live.append(child)
                except (psutil.NoSuchProcess, OSError):
                    continue
            self.samples.append({"t": round(time.monotonic(), 1),
                                 "rss_mib": round(sum(p.memory_info().rss for p in live)
                                                 / 1048576.0, 1)})

    def stop(self) -> list[dict[str, float]]:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=self.interval * 3)
        return self.samples


def peak(samples: list[dict[str, float]]) -> float:
    vals = [float(s["rss_mib"]) for s in samples if "rss_mib" in s]
    return max(vals) if vals else 0.0


def available_mib() -> float:
    import psutil

    return psutil.virtual_memory().available / 1048576.0


def qt_modules_loaded() -> list[str]:
    return sorted(m for m in sys.modules
                  if m.startswith("PySide6") or m.startswith("PyQt"))


# ───────────────────────────── 判据（每条一个纯函数，注入时直接喂坏读数）─────────────────────────────

def m1_windows_measured(peaks: dict[str, float], alive_to_end: bool) -> Row:
    missing = [w for w in ("A", "B", "C", "D") if peaks.get(w, 0.0) <= 0.0]
    return Row("m1 四个窗口都真采到数，且应用进程撑到窗口 C 结束",
               not missing and alive_to_end,
               "｜".join(f"{w} {peaks.get(w, 0.0):.1f}MiB" for w in ("A", "B", "C", "D"))
               + ("" if not missing else f" ── 这些窗口一个点都没有：{'、'.join(missing)}")
               + ("" if alive_to_end else " ── 应用进程在窗口 C 结束前就退出了"))


def m2_combination_actually_ran(ocr_delta: int, index_delta: int,
                                churn_seen: int, churn_planted: int) -> Row:
    """整个探针的存在理由。没有它，"组合峰值"可以只是 UI 空转时的那块内存。

    三路增量缺一判红：OCR 页落库、窗口 C 内完成的 index 任务、churn 投放的文件真进了库。
    """
    problems = []
    if ocr_delta <= 0:
        problems.append(f"OCR 页落库增量 {ocr_delta} —— 引擎根本没跑，C 不是「界面+索引+OCR」")
    if index_delta <= 0:
        problems.append(f"窗口 C 内完成的 index 任务 {index_delta} 条 —— 索引没和 OCR 同场")
    if churn_seen <= 0:
        problems.append(f"churn 投放 {churn_planted} 份里 {churn_seen} 份进了库 —— "
                        "监听/巡检那条路没在跑，索引增量来自旧文件，同场是假的")
    return Row("m2 窗口 C 确实是「界面 + 索引 + OCR」同场（三路增量都要在场）",
               not problems,
               f"OCR 页 +{ocr_delta}｜窗口内完成 index +{index_delta}｜"
               f"churn 入库 {churn_seen}/{churn_planted}"
               + ("" if not problems else " ── " + "；".join(problems)))


def m3_peak_within_g8(combined_peak: float) -> Row:
    ok = combined_peak <= G8_STRICT_MIB
    return Row(f"m3 组合峰值不越 G8（判定取更严的 {G8_STRICT_MIB:.0f}MiB 一档 [约定]）",
               ok,
               f"组合峰值 {combined_peak:.1f}MiB｜按 1,200MiB 档余量 "
               f"{G8_STRICT_MIB - combined_peak:+.1f}MiB｜按 1,228.8MiB 档余量 "
               f"{G8_LOOSE_MIB - combined_peak:+.1f}MiB"
               + ("" if ok else " ── 按更严的一档越线（单位口径本身仍等 Q4，本探针不替用户定）"))


def m4_attribution_present(peaks: dict[str, float]) -> Row:
    c, d = peaks.get("C", 0.0), peaks.get("D", 0.0)
    ok = c > 0.0 and d > 0.0
    return Row("m4 分层归因两条腿都在场（组合 − 单点 OCR = 界面与索引叠进来的量）",
               ok,
               f"组合 C {c:.1f}MiB − 单点 D {d:.1f}MiB = {c - d:+.1f}MiB"
               "（同一台机器、同一批页数、同一轮里量的；D 是另起的干净进程，不含本探针驻留）"
               + ("" if ok else " ── 有一侧没量到，差值无意义，不许引用"))


def m5_phase_d_has_no_qt(qt_in_d: list[str]) -> Row:
    return Row("m5 窗口 D 那个进程确实没加载 Qt（否则它不是「只有 OCR」的对照）",
               not qt_in_d,
               f"D 进程结束时的 Qt 模块：{qt_in_d or '无'}"
               + ("" if not qt_in_d else " ── 对照被 UI 污染，m4 的差值不成立"))


def m6_load_reading_present(avail_start: float, avail_end: float) -> Row:
    ok = avail_start > 0.0 and avail_end > 0.0
    return Row("m6 本机可用内存读数上屏（I16 要求低可用内存时刻各跑一次；只记读数不设阈值）",
               ok,
               f"起跑可用 {avail_start:.0f}MiB｜收摊可用 {avail_end:.0f}MiB"
               "（等不等于「低」由人判，本探针不替这个阈值背书）"
               + ("" if ok else " ── 读数没取到，「是不是低可用内存时刻」这句话没有依据"))


def m7_no_crash(crash_bytes: int, traceback_count: int, tail: str) -> Row:
    return Row("m7 全程无未捕获异常（crash.log 为空 / app.log 无 Traceback）",
               crash_bytes == 0 and traceback_count == 0,
               f"crash.log {crash_bytes} 字节｜app.log*（含轮转）里 Traceback {traceback_count} 处"
               + ("" if crash_bytes == 0 else f" ── 进程输出尾部：{tail[-240:]}"))


# ───────────────────────────── 反向注入自检 ─────────────────────────────

def inject() -> int:
    """每条判据喂一份**真实存在的坏法**要求变红，再喂一份好读数要求放行。"""
    good_peaks = {"A": 90.0, "B": 260.0, "C": 980.0, "D": 900.0}
    bad: list[tuple[Row, str]] = []

    # 坏法 1：窗口 D 没跑起来（可选层没装 / OCR 任务没人领）→ m1 必须红
    bad.append((m1_windows_measured(dict(good_peaks, D=0.0), True),
                "窗口 D 一个采样点都没有（引擎起不来）"))
    # 坏法 1b：应用进程半路退出 → m1 必须红
    bad.append((m1_windows_measured(good_peaks, False),
                "应用进程在窗口 C 结束前退出（装配失败 / 被杀）"))
    # 坏法 2：三路增量各缺一条。第一缺是本探针最容易被骗过去的一种绿 ——
    #         OCR 任务排了但一页没落库（text_status=pending 被 PermanentFailure 拒掉），
    #         量了一下午"组合内存"其实是 UI + 索引
    bad.append((m2_combination_actually_ran(0, 12, 12, 12), "OCR 页增量 0：排了任务但一页没落库"))
    bad.append((m2_combination_actually_ran(12, 0, 12, 12), "窗口 C 内完成的 index 任务 0 条：OCR 独跑"))
    bad.append((m2_combination_actually_ran(12, 12, 0, 12),
                "churn 投放的一份没进库：监听断了，索引增量来自旧文件，同场是假的"))
    # 坏法 3：越线。两条 —— 一条两档都越，一条**只有严档越**。
    #         后者正是 G8 单位口径没定死时会被放过去的那一段（1,210MiB 按 1,228.8 算绿）
    bad.append((m3_peak_within_g8(1300.0), "组合峰值 1,300MiB：两档都越"))
    bad.append((m3_peak_within_g8(1210.0),
                "组合峰值 1,210MiB：按 1,228.8MiB 一档绿、按 1,200MiB 一档红（口径没定死的那段）"))
    # 坏法 4：归缺一条腿 → m4 必须红（只报组合不报单点，等于没有差值）
    bad.append((m4_attribution_present(dict(good_peaks, D=0.0)),
                "单点 OCR 那侧没读数，差值是编的"))
    # 坏法 5：窗口 D 里加载了 Qt → m5 必须红
    bad.append((m5_phase_d_has_no_qt(["PySide6.QtWidgets"]),
                "D 进程 import 了 PySide6（服务层对照被 UI 污染）"))
    # 坏法 6：可用内存读数没取到 → m6 必须红
    bad.append((m6_load_reading_present(0.0, 2100.0),
                "psutil 读不到可用内存，「是不是低内存时刻」没有依据"))
    # 坏法 7：worker 线程里没接住的异常 → m7 必须红
    bad.append((m7_no_crash(2048, 3, "Traceback (most recent call last): ... MemoryError"),
                "crash.log 2,048 字节 + 3 处 Traceback"))

    caught = 0
    for row, why in bad:
        mark = "红" if not row.ok else "绿（← 这条断言没有牙）"
        log(f"  {mark}  {row.gate}\n        坏法：{why}\n        读数：{row.measured}")
        caught += 1 if not row.ok else 0

    good = [m1_windows_measured(good_peaks, True),
            m2_combination_actually_ran(12, 9, 12, 12),
            m3_peak_within_g8(good_peaks["C"]),
            m4_attribution_present(good_peaks),
            m5_phase_d_has_no_qt([]),
            m6_load_reading_present(2100.0, 1900.0),
            m7_no_crash(0, 0, "")]
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


# ───────────────────────────── 窗口 D：只有 OCR 的干净进程 ─────────────────────────────

def service_only(work: Path) -> int:
    """另起解释器走服务层：扫描 → 逐份索引 → OCR 同一批页数，全程没有 Qt 窗口。

    与窗口 C 同一批页数，为的是 m4 那个差值是"同机同负荷"下的差值而不是两次实验相减。
    读数写进 `work/p19_service_only.json`，由主流程读回来 —— 不靠 stdout（本环境后台命令的
    stdout 捕获会整块丢，见本轮记录）。
    """
    out_file = work / "p19_service_only.json"
    from pdfarchiver.services.bootstrap import bootstrap

    d_root, d_corpus = work / "data_root_d", work / "corpus_d"
    for i in range(SCANNED_DOCS):
        _scanned_pdf(d_corpus / "scanned" / f"p19_d_{i}.pdf", pages=PAGES_PER_SCANNED)
    sampler = SelfSampler().start()
    started = time.monotonic()
    payload: dict[str, object] = {"error": None}
    try:
        ctx = bootstrap(d_root)
        try:
            root = ctx.roots.add(str(d_corpus / "scanned").replace("\\", "/"),
                                 _key(d_corpus / "scanned"), label="p19 单点 OCR")
            ctx.scan.scan_root(root)
            ids = sorted({d.doc_id for d in
                          (ctx.documents.facts_by_key(_key(p)) for p in
                           sorted((d_corpus / "scanned").glob("*.pdf")))
                          if d is not None})
            for doc_id in ids:
                ctx.indexer.index_document(doc_id)
            for row in ctx.jobs.list():
                ctx.jobs.succeed(int(row.id))
            receipt = ctx.ocr.request_ocr(ids)
            queue = ctx.start_background()
            idle = queue.wait_until_idle(timeout=CAP_OCR)
            payload.update({
                "doc_ids": ids, "receipt": receipt.describe(), "drained": idle,
                "ocr_pages": scalar(d_root, "SELECT count(*) FROM text_pages "
                                           "WHERE source_kind='ocr'"),
            })
        finally:
            ctx.shutdown()
    except Exception as exc:      # noqa: BLE002 - 对照进程的任何异常都要原样带回主流程，不许糊成 0
        payload["error"] = f"{type(exc).__name__}: {exc}"
    samples = sampler.stop()
    payload.update({"peak_mib": peak(samples), "samples": len(samples),
                    "seconds": round(time.monotonic() - started, 1),
                    "qt_modules": qt_modules_loaded(),
                    "avail_mib": round(available_mib(), 1)})
    out_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    log(f"窗口 D：峰值 {payload['peak_mib']:.1f}MiB｜{payload['seconds']}s｜"
        f"OCR 页 {payload.get('ocr_pages')}｜Qt {payload['qt_modules'] or '无'}｜"
        f"error={payload['error']}")
    return 1 if payload["error"] else 0


def _key(path: Path) -> str:
    from pdfarchiver.fs.identity import identity_key

    return identity_key(path)


# ───────────────────────────── 主流程 ─────────────────────────────

def wait_for(data_root: Path, done, cap: float, proc=None) -> tuple[bool, float, str]:
    """轮询只读库直到 `done()` 为真或到点。返回 (成功, 用时, 第一条读库原文)。

    读库异常**留着原文**而不是吞掉：p13 的 S6 就是吞掉之后全程瞎了 46 秒，
    读数只剩一个空字典，分不清"没排空"和"根本没读到"（I29 同族）。
    """
    t0 = time.perf_counter()
    first_error = ""
    while time.perf_counter() - t0 < cap:
        if proc is not None and proc.poll() is not None:
            return False, time.perf_counter() - t0, "应用进程已经退出，不再空等"
        try:
            if done():
                return True, time.perf_counter() - t0, first_error
        except Exception as exc:  # noqa: BLE001 - 应用正在写时短暂读不到是真事，但原文必须留下
            first_error = first_error or f"{type(exc).__name__}: {exc}"
        time.sleep(1.0)
    return False, time.perf_counter() - t0, first_error


def run(keep: bool) -> int:
    import p13_soak

    work = Path(tempfile.mkdtemp(prefix="p19_mem_"))
    data_root, corpus = work / "data_root", work / "corpus"
    avail_start = available_mib()
    log(f"现场：{work}｜起跑可用内存 {avail_start:.0f}MiB")
    log(f"量级：扫描件 {SCANNED_DOCS} 份 ×{PAGES_PER_SCANNED} 页（OCR "
        f"{SCANNED_DOCS * PAGES_PER_SCANNED} 页）｜原生 {NATIVE_DOCS} 份｜"
        f"窗口 C 每轮投放 {CHURN_DOCS} 份｜采样 {SAMPLE_SECONDS}s")
    rows: list[Row] = []
    peaks: dict[str, float] = {}
    proc: subprocess.Popen[str] | None = None
    sampler: p13_soak.Sampler | None = None
    try:
        seeded = build_corpus(corpus)
        warm = bootstrap_warm(data_root)      # 迁移与默认分类先建好，再起一个干净的应用进程
        register_root(data_root, corpus, "p19 合成语料")

        env = {**os.environ, "QT_QPA_PLATFORM": "offscreen", "PYTHONIOENCODING": "utf-8",
               "PYTHONPATH": str(REPO / "src")}
        stdout_file = work / "app_stdout.log"
        fh = stdout_file.open("w", encoding="utf-8", errors="replace")
        proc = subprocess.Popen([sys.executable, "-m", "pdfarchiver.app",
                                 "--data-dir", str(data_root), "--exit-after", "900"],
                                cwd=str(work), env=env,
                                stdout=fh, stderr=subprocess.STDOUT, text=True)
        sampler = p13_soak.Sampler(proc, interval=SAMPLE_SECONDS).start()

        # ── 窗口 A：只有界面，队列空着 ──
        time.sleep(IDLE_SECONDS)
        cut_a = len(sampler.samples)
        peaks["A"] = peak(sampler.samples)
        log(f"窗口 A（只有界面 {IDLE_SECONDS:.0f}s，{cut_a} 个点）峰值 {peaks['A']:.1f}MiB")

        # ── 窗口 B：界面 + 索引 ──
        queued_scan = enqueue(data_root, "scan", [])
        ok_b, waited_b, err_b = wait_for(
            data_root,
            lambda: scalar(data_root, "SELECT count(*) FROM documents") >= seeded
            and not open_backlog(data_root),
            CAP_SCAN, proc)
        cut_b = len(sampler.samples)
        peaks["B"] = peak(sampler.samples[cut_a:])
        docs_b = scalar(data_root, "SELECT count(*) FROM documents")
        log(f"窗口 B（界面+索引）峰值 {peaks['B']:.1f}MiB｜排进 scan {queued_scan} 条｜"
            f"库里主记录 {docs_b}/{seeded}｜等排空 {waited_b:.1f}s 成功={ok_b}"
            + (f"｜读库原文：{err_b}" if err_b else ""))

        # ── 窗口 C：界面 + 索引 + OCR 同场 ──
        scanned_ids = [int(r[0]) for r in
                       query(data_root, "SELECT id FROM documents WHERE path LIKE ?",
                             ("%p19_scan_%",))]
        ocr_before = scalar(data_root, "SELECT count(*) FROM text_pages WHERE source_kind='ocr'")
        index_before = scalar(data_root, "SELECT count(*) FROM processing_jobs "
                                         "WHERE kind='index' AND state='done'")
        queued_ocr = enqueue(data_root, "ocr", scanned_ids)
        ocr_target = ocr_before + SCANNED_DOCS * PAGES_PER_SCANNED
        churn_start = time.monotonic()
        stamps = 0
        last_probe = ""
        while time.monotonic() - churn_start < CAP_OCR and proc.poll() is None:
            stamps += 1
            churn(corpus, stamps)
            ok_c, _, err_c = wait_for(
                data_root,
                lambda: scalar(data_root, "SELECT count(*) FROM text_pages "
                                          "WHERE source_kind='ocr'") >= ocr_target,
                DRAIN_SETTLE)
            last_probe = err_c or ""
            if scalar(data_root, "SELECT count(*) FROM text_pages WHERE source_kind='ocr'") \
                    >= ocr_target and not open_backlog(data_root):
                break
        cut_c = len(sampler.samples)
        peaks["C"] = peak(sampler.samples[cut_b:])
        ocr_after = scalar(data_root, "SELECT count(*) FROM text_pages WHERE source_kind='ocr'")
        index_after = scalar(data_root, "SELECT count(*) FROM processing_jobs "
                                        "WHERE kind='index' AND state='done'")
        churn_seen = scalar(data_root, "SELECT count(*) FROM documents WHERE path LIKE ?",
                            ("%p19_churn_%",))
        alive_to_end = proc.poll() is None
        log(f"窗口 C（同场）峰值 {peaks['C']:.1f}MiB｜排进 ocr {queued_ocr}/{len(scanned_ids)} 条｜"
            f"OCR 页 {ocr_before}→{ocr_after}｜index 完成 {index_before}→{index_after}｜"
            f"投放 {stamps} 轮共 {stamps * CHURN_DOCS} 份、入库 {churn_seen} 份｜"
            f"用时 {time.monotonic() - churn_start:.1f}s"
            + (f"｜读库原文：{last_probe}" if last_probe else ""))

        samples = sampler.stop()
        proc.terminate()
        try:
            proc.wait(timeout=60)
        except subprocess.TimeoutExpired:
            proc.kill()
        fh.close()

        logs_dir = data_root / "logs"
        crash = logs_dir / "crash.log"
        crash_bytes = crash.stat().st_size if crash.exists() else 0
        text = "".join(f.read_text(encoding="utf-8", errors="replace")
                       for f in sorted(logs_dir.glob("app.log*")))
        tail = stdout_file.read_text(encoding="utf-8", errors="replace")[-400:] \
            if stdout_file.exists() else ""

        # ── 窗口 D：另起干净进程，只有 OCR ──
        rc_d = subprocess.run([sys.executable, str(Path(__file__).resolve()),
                               "--service-only", str(work)],
                              cwd=str(REPO), env=env, timeout=CAP_OCR + 120)
        d_json = work / "p19_service_only.json"
        d: dict[str, object] = {}
        if d_json.exists():
            d = json.loads(d_json.read_text(encoding="utf-8"))
        else:
            log(f"窗口 D 没留下读数文件（退出码 {rc_d.returncode}）")
        peaks["D"] = float(d.get("peak_mib", 0.0) or 0.0)
        qt_in_d = list(d.get("qt_modules", ["读数缺失"]) or []) if d else ["读数缺失"]
        if d.get("error"):
            log(f"窗口 D 报错原文：{d['error']}")

        # m1 到这里才构造：它判的是「四个窗口都真采到数」，而 D 的读数要等上面那一段落进
        # `peaks`。原来 m1 排在窗口 D **之前**，于是 D 恒为 0.0MiB、这一条在真实路径上永远红
        # —— 而 `--inject` 自检喂的是手工造的 peaks，从来照不到这个顺序（**ISSUES I92** ②）。
        rows.append(m1_windows_measured(peaks, alive_to_end))
        rows.append(m2_combination_actually_ran(ocr_after - ocr_before,
                                                index_after - index_before,
                                                churn_seen, stamps * CHURN_DOCS))
        rows.append(m3_peak_within_g8(peaks["C"]))
        rows.append(m4_attribution_present(peaks))
        rows.append(m5_phase_d_has_no_qt(qt_in_d))

        rows.append(m6_load_reading_present(avail_start, available_mib()))
        rows.append(m7_no_crash(crash_bytes, text.count("Traceback"), tail))

        RESULT.parent.mkdir(exist_ok=True)
        RESULT.write_text(json.dumps({
            "peaks_mib": peaks, "samples_app": samples, "window_d": d,
            "ocr_pages_before_after": [ocr_before, ocr_after],
            "index_done_before_after": [index_before, index_after],
            "churn_rounds": stamps, "churn_in_library": churn_seen,
            "documents_end": scalar(data_root, "SELECT count(*) FROM documents"),
            "avail_mib_start": round(avail_start, 1),
            "avail_mib_end": round(available_mib(), 1),
            "rows": [asdict(r) for r in rows],
            "g8": {"strict_mib": G8_STRICT_MIB, "loose_mib": G8_LOOSE_MIB,
                   "verdict_uses": "strict", "unit_open": "Q4"},
            "concurrency_note": "worker_threads=1（I46 甲）：C 的并发是引擎常驻 + 任务交替",
        }, ensure_ascii=False, indent=2), encoding="utf-8")
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


def bootstrap_warm(data_root: Path):
    """只为了把库建出来（迁移 + 默认分类），建完就关 —— 应用进程自己再装配一遍。"""
    from pdfarchiver.services.bootstrap import bootstrap

    ctx = bootstrap(data_root)
    ctx.shutdown()
    return data_root


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="组合内存压测（详见模块文档的四条诚实边界）")
    ap.add_argument("--keep", action="store_true", help="跑完保留现场目录")
    ap.add_argument("--inject", action="store_true", help="反向注入自检：每条判据真喂一次坏读数")
    ap.add_argument("--service-only", type=Path, default=None, metavar="现场目录",
                    help="内部用：作为窗口 D 的干净对照进程跑一遍服务层 OCR")
    args = ap.parse_args(argv)
    if args.service_only:
        return service_only(args.service_only)
    if args.inject:
        return inject()
    return run(args.keep)


if __name__ == "__main__":
    raise SystemExit(main())
