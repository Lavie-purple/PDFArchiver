"""冻结产物的真机冒烟：在没有 venv 的干净条件下，把「首启 → 扫描 → 索引 → 检索 → OCR → 关闭重启 → 被杀恢复」跑一遍。

跑法：
    python packaging/frozen_smoke.py              # 约 4–6 分钟（先要跑过 python packaging/build.py）
    python packaging/frozen_smoke.py --keep       # 跑完不删临时目录，出问题时进去看
    python packaging/frozen_smoke.py --only first # 只跑某一阶段：first/scan/ocr/restart/kill/paths

和 `tests/e2e/` 那十一条的分工：e2e 验的是**代码逻辑** —— 在 venv 里、`offscreen` 平台上、
数据目录是 pytest 的 tmp_path。这里验的是**产物**，三点都不一样：

1. exe 从仓库里**复制出去**再跑，运行目录、cwd、PATH 里都没有 venv 与仓库路径 ——
   SPEC 阶段 7 验收第 2 条「不依赖开发者机器上的临时文件或绝对路径」只能这样证。
2. **首启那一枪不带 `QT_QPA_PLATFORM=offscreen`**：这是本项目第一次真起桌面窗口（旧账 I17）。
   后面几枪为了不在使用者桌面上挂几分钟窗口，仍然用 offscreen —— 差别只在"窗口给不给人看"，
   跑的是同一个 exe、同一套装配代码。
3. 扫描、索引、OCR 全部发生在**冻结进程内部**，抽出来的正文与识别结果写进它自己建的库，
   然后由本脚本从外面只读打开那份库来对账。

一处必须说清的诚实边界：**产品没有"添加监测根目录"的用户入口**（阶段 3 未实现，Q7 线框未确认）。
所以本脚本用服务层真代码 `RootRepository.add` + `JobRepository.enqueue("scan")` 把活排进去，
再由冻结的 worker 线程执行 —— 被验的是"冻结产物能不能真干活"，
"用户点得到吗"不在这里，写在交付报告的未实现清单里。
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
for _p in (REPO / "src", REPO / "tests"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

BUNDLE_SRC = REPO / "dist" / "PdfArchiver"
BUILD_REPORT = REPO / ".probe_work" / "packaging_build_report.json"
RESULT = REPO / ".probe_work" / "frozen_smoke_result.json"
PHRASE = "冷链物流温度记录仪校准规程"      # 只有真抽取或真识别才得到的一串字
BULK_DOCS = 150                         # 杀进程那一阶段要让队列里真有活：几份 PDF 一秒就排空了


@dataclass
class Row:
    gate: str
    ok: bool
    measured: str


def log(msg: str) -> None:
    print(msg, flush=True)


class Sampler:
    """后台线程采样冻结进程的内存 / 句柄 / 线程数。

    只打印不当断言：这三个数都是负载绑定的读数，跨机器、跨时段不可比（D-033 同一条理由）。
    """

    def __init__(self, proc: subprocess.Popen[str]) -> None:
        self.samples: list[dict[str, float]] = []
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        try:
            import psutil
            self._ps = psutil.Process(proc.pid)
        except Exception:  # noqa: BLE001 - 采样加不上就少加，不改判定
            self._ps = None

    def start(self) -> "Sampler":
        if self._ps is not None:
            self._thread = threading.Thread(target=self._loop, daemon=True)
            self._thread.start()
        return self

    def _loop(self) -> None:
        while not self._stop.is_set() and self._ps.is_running():
            try:
                self.samples.append({
                    "rss_mb": round(self._ps.memory_info().rss / 1048576, 1),
                    "handles": self._ps.num_handles(),
                    "threads": self._ps.num_threads(),
                    "cpu_pct": round(self._ps.cpu_percent(interval=None), 1)})
            except Exception:  # noqa: BLE001 - 进程刚好退出时读不到，不是失败
                break
            time.sleep(0.5)

    def stop(self) -> str:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=3)
        if not self.samples:
            return "无资源读数（psutil 起不来或进程瞬间退出）"
        peak_rss = max(s["rss_mb"] for s in self.samples)
        peak_h = max(int(s["handles"]) for s in self.samples)
        peak_t = max(int(s["threads"]) for s in self.samples)
        return (f"峰值 RSS {peak_rss:.1f}MiB｜峰值句柄 {peak_h}｜峰值线程 {peak_t}｜"
                f"采样 {len(self.samples)} 次")


# ───────────────────────────── 环境与被测进程 ─────────────────────────────

def clean_env(*, offscreen: bool) -> dict[str, str]:
    """把 venv 与仓库从环境里摘干净：产物只能靠自己包内的东西跑起来。"""
    env = dict(os.environ)
    keep = [p for p in (env.get("PATH") or "").split(os.pathsep)
            if p and str(REPO) not in p and ".venv" not in p]
    env["PATH"] = os.pathsep.join(keep)
    for key in ("PYTHONPATH", "PYTHONHOME", "PYTHONSTARTUP", "PDFARCHIVER_DATA_DIR",
                "PYTHONIOENCODING", "VIRTUAL_ENV", "QT_QPA_PLATFORM"):
        env.pop(key, None)
    if offscreen:
        env["QT_QPA_PLATFORM"] = "offscreen"
    return env


def launch(exe: Path, data_dir: Path, cwd: Path, *, offscreen: bool,
           exit_after: float = 0.0) -> subprocess.Popen[str]:
    cmd = [str(exe), "--data-dir", str(data_dir)]
    if exit_after > 0:
        cmd += ["--exit-after", f"{exit_after}"]
    return subprocess.Popen(cmd, cwd=str(cwd), env=clean_env(offscreen=offscreen),
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, encoding="utf-8", errors="replace")


def console_encoding() -> str:
    """控制台工具（taskkill）说的是 OEM 代码页，跟解释器的偏好编码是两件事。

    实测（2026-10-18）：`PYTHONUTF8=1` 下 `locale.getpreferredencoding()` 变成 UTF-8，
    拿它解 taskkill 的 `0xB3 0xC9`（「成」的 GBK 字节）会在读线程里抛
    `UnicodeDecodeError`，整段 `--only package` 判 RED；改成 `errors="replace"` 能不炸，
    但回显变成乱码 —— 门禁原文不可读等于没证据。所以这里按机器真实的 OEM 代码页解。
    """
    if sys.platform != "win32":
        return "utf-8"
    import ctypes
    return f"cp{ctypes.windll.kernel32.GetOEMCP()}"


def close_gracefully(proc: subprocess.Popen[str]) -> tuple[bool, float]:
    """先走 WM_CLOSE（等价于用户点 ×），拿不到优雅退出才强杀。"""
    t0 = time.perf_counter()
    subprocess.run(["taskkill", "/PID", str(proc.pid)], capture_output=True, text=True,
                   encoding=console_encoding(), errors="replace")
    try:
        return proc.wait(timeout=30) == 0, round(time.perf_counter() - t0, 2)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=10)
        return False, round(time.perf_counter() - t0, 2)


def force_kill_tree(proc: subprocess.Popen[str]) -> tuple[bool, str]:
    """真强杀，模拟断电 / 被拔。"""
    out = subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                         capture_output=True, text=True,
                         encoding=console_encoding(), errors="replace")
    return out.returncode == 0, (out.stdout or "").strip()[:160]


# ───────────────────────────── 只读对账侧 ─────────────────────────────

def state_size(data_dir: Path) -> int:
    path = data_dir / "logs" / "state.log"
    return path.stat().st_size if path.is_file() else 0


def state_events(data_dir: Path, since_bytes: int) -> list[dict]:
    path = data_dir / "logs" / "state.log"
    if not path.is_file():
        return []
    out = []
    for line in path.read_bytes()[since_bytes:].decode("utf-8", "replace").splitlines():
        if line.strip():
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                out.append({"event": "UNPARSEABLE", "raw": line[:200]})
    return out


def query(data_dir: Path, sql: str, args: tuple = ()) -> list[tuple]:
    uri = f"file:{(data_dir / 'data' / 'catalog.db').as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=15)
    try:
        return conn.execute(sql, args).fetchall()
    finally:
        conn.close()


def scalar(data_dir: Path, sql: str, args: tuple = ()):
    rows = query(data_dir, sql, args)
    return rows[0][0] if rows and rows[0] else None


def wait_for(data_dir: Path, sql: str, want, *, deadline: float, args: tuple = ()):
    """轮询一个标量查询到条件成立；超时就把最后一次值交出去，不猜。"""
    t0 = time.perf_counter()
    last = None
    while time.perf_counter() - t0 < deadline:
        try:
            last = scalar(data_dir, sql, args)
        except sqlite3.OperationalError as exc:
            last = f"读不到：{exc}"
        if isinstance(last, (int, float)) and want(last):
            return True, last, round(time.perf_counter() - t0, 1)
        time.sleep(0.5)
    return False, last, round(time.perf_counter() - t0, 1)


# ───────────────────────────── 写侧：只用服务层真代码 ─────────────────────────────

def seed_root_and_enqueue_scan(data_dir: Path, corpus: Path) -> str:
    """登记监测根 + 排一条全量扫描，与 `tests/e2e` 完全同一条路：正斜杠路径 + `identity_key`。"""
    from pdfarchiver.db.engine import Engine
    from pdfarchiver.db.repositories.jobs import JobRepository
    from pdfarchiver.db.repositories.roots import RootRepository
    from pdfarchiver.fs.identity import identity_key

    engine = Engine(data_dir / "data" / "catalog.db", busy_timeout_ms=5000)
    try:
        key = identity_key(corpus)
        RootRepository(engine).add(str(corpus).replace("\\", "/"), key, label="冒烟临时语料")
        JobRepository(engine).enqueue("scan")
        return key
    finally:
        engine.close_thread_connection()


def enqueue_ocr(data_dir: Path, doc_id: int) -> int:
    from pdfarchiver.db.engine import Engine
    from pdfarchiver.db.repositories.jobs import JobRepository

    engine = Engine(data_dir / "data" / "catalog.db", busy_timeout_ms=5000)
    try:
        jobs = JobRepository(engine)
        before = jobs.count()
        jobs.enqueue("ocr", doc_id, dedupe=False)
        return jobs.count() - before
    finally:
        engine.close_thread_connection()


# ───────────────────────────── 造真 PDF ─────────────────────────────

def make_scanned_image_pdf(path: Path) -> None:
    """把中文句子**渲染成图片**再贴满整页：没有文本层，只有 OCR 才读得出那几个字。"""
    import pymupdf

    draft = pymupdf.open()
    page = draft.new_page(width=595, height=842)
    y = 80
    for line in (PHRASE, "记录仪每年应校准一次并保留原始曲线", "偏差超过 0.5 摄氏度即判不合格"):
        page.insert_text((60, y), line, fontsize=28, fontname="china-s")
        y += 90
    stream = page.get_pixmap(dpi=200).tobytes("png")
    draft.close()
    doc = pymupdf.open()
    target = doc.new_page(width=595, height=842)
    target.insert_image(target.rect, stream=stream)
    path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(path))
    doc.close()


def make_corpus(corpus: Path) -> dict:
    """用项目自己的造样函数（`tests/conftest.py`）生成真 PDF，两处不各写一份。"""
    from conftest import _make_pdf, _make_scanned_pdf

    corpus.mkdir(parents=True, exist_ok=True)
    text_pdf = _make_pdf(corpus / f"{PHRASE}.pdf",
                         page_lines=[[f"{PHRASE}，第 {i + 1} 条要求"] for i in range(3)])
    make_scanned_image_pdf(corpus / "扫描件_有字无文本层.pdf")
    _make_scanned_pdf(corpus / "扫描件_空白.pdf", pages=1)
    for i in range(BULK_DOCS):
        _make_pdf(corpus / f"批量样本_{i:03d}.pdf", pages=2,
                  lines=[f"批量样本第 {i} 号，含可检索中文字串"])
    return {"text_pdf": text_pdf, "files": len(list(corpus.rglob("*.pdf")))}


def add_bulk(corpus: Path, count: int, tag: str) -> None:
    from conftest import _make_pdf

    for i in range(count):
        _make_pdf(corpus / f"{tag}_{i:03d}.pdf", pages=2, lines=[f"{tag}第 {i} 号样本正文"])


# ───────────────────────────── 各阶段 ─────────────────────────────

def phase_first_launch(exe: Path, data_dir: Path, run_dir: Path) -> list[Row]:
    from pdfarchiver.db.migrate import SCHEMA_TABLE
    from pdfarchiver.db.migrations import discover
    from pdfarchiver.services.default_catalog import DEFAULT_CATEGORY_TEMPLATE

    # 期望的结构版本从产品自己的迁移目录取，不写死字面量：这一条曾经写死成 3，
    # 迁移加到第 7 段之后它把一场本来全绿的冒烟判成 RED —— 硬编码的计数一定会过期。
    migrations = discover(REPO / "src" / "pdfarchiver" / "db" / "migrations")

    expected_cats = len(DEFAULT_CATEGORY_TEMPLATE) + sum(
        len(v) for v in DEFAULT_CATEGORY_TEMPLATE.values())

    rows: list[Row] = []
    marker = state_size(data_dir)
    proc = launch(exe, data_dir, run_dir, offscreen=False)   # 真桌面，关 I17 的一半
    sampler = Sampler(proc).start()
    time.sleep(6.0)
    reading = sampler.stop()
    graceful, close_seconds = close_gracefully(proc)
    events = state_events(data_dir, marker)
    names = [e["event"] for e in events]

    rows.append(Row("G20 冻结产物在真桌面（非 offscreen）起得来、点 × 关得掉",
                    graceful and proc.returncode == 0,
                    f"退出码 {proc.returncode}｜优雅关闭={graceful}（{close_seconds}s）｜{reading}"))

    tree = {"data/catalog.db": (data_dir / "data" / "catalog.db").is_file(),
            "data/backups/": (data_dir / "data" / "backups").is_dir(),
            "data/cache/": (data_dir / "data" / "cache").is_dir(),
            "config/": (data_dir / "config").is_dir(),
            "logs/state.log": (data_dir / "logs" / "state.log").is_file(),
            "logs/app.log": bool(list(data_dir.glob("logs/app.log*")))}
    missing = [k for k, ok in tree.items() if not ok]
    snapshots = list((data_dir / "data" / "backups").glob("*.db"))
    rows.append(Row("首启按约定建出数据目录（库 / 迁移快照 / 缓存 / 配置 / 日志）", not missing,
                    f"缺={missing or '无'}｜迁移前快照 {len(snapshots)} 份"))

    version = scalar(data_dir, f"SELECT max(version) FROM {SCHEMA_TABLE}")
    # `schema_version` 表按产品口径只留最新一条（`_run_one` 是 DELETE + INSERT），所以「七段都跑完」
    # 的证据不是七行版本号，而是**每段迁移前各存了一份快照**。两个条件一起判。
    rows.append(Row(f"结构版本落到 {migrations[-1].order}"
                    f"（{len(migrations)} 段迁移在冻结态全部跑完）",
                    version == migrations[-1].order and len(snapshots) == len(migrations),
                    f"{SCHEMA_TABLE} max(version) = {version}｜期望 {migrations[-1].order}"
                    f"｜迁移前快照 {len(snapshots)} 份（每段一份，共 {len(migrations)} 段）"))

    cats = scalar(data_dir, "SELECT count(*) FROM categories")
    rows.append(Row(f"SPEC 3.3 默认分类种进库（期望 {expected_cats}，数字取自代码里的模板本身）",
                    cats == expected_cats, f"categories 行数 = {cats}"))

    ready = [e for e in events if e["event"] == "window.ready"]
    rows.append(Row("I17 桌面首屏：冻结进程写出 window.ready（本项目第一次不是 offscreen 取的数）",
                    bool(ready) and ready[-1].get("cold_start_seconds") is not None,
                    f"cold_start_seconds={ready[-1].get('cold_start_seconds') if ready else '无'}"))
    crash = data_dir / "logs" / "crash.log"
    rows.append(Row("首启没有未捕获异常（crash.log 不在场）", not crash.is_file(),
                    f"{crash}" if crash.is_file() else "0 个 crash.log"))
    log(f"        首启事件序列：{names}")
    return rows


def phase_scan_and_search(exe: Path, data_dir: Path, run_dir: Path, info: dict,
                          corpus: Path) -> tuple[list[Row], int]:
    rows: list[Row] = []
    seed_root_and_enqueue_scan(data_dir, corpus)
    marker = state_size(data_dir)
    proc = launch(exe, data_dir, run_dir, offscreen=True)
    sampler = Sampler(proc).start()

    expected = info["files"]
    ok_docs, docs, secs = wait_for(data_dir, "SELECT count(*) FROM documents",
                                   lambda v: v >= expected, deadline=200)
    ok_pages, pages, _ = wait_for(data_dir, "SELECT count(*) FROM text_pages",
                                  lambda v: v >= 2 * (expected - 2), deadline=120)
    reading = sampler.stop()
    close_gracefully(proc)
    events = state_events(data_dir, marker)

    rows.append(Row("冻结产物完成首次全量扫描：主记录数 = 磁盘 PDF 数", ok_docs,
                    f"documents {docs} / 磁盘 {expected}｜排队到齐 {secs}s｜{reading}"))
    rows.append(Row("冻结产物抽出正文（真 PyMuPDF 在冻结态跑的，不是夹具喂好的字符串）", ok_pages,
                    f"text_pages {pages} 行"))

    native = scalar(data_dir, "SELECT text_status FROM documents WHERE name LIKE ?", (f"%{PHRASE}%",))
    rows.append(Row("有文本层的 PDF 判为 native（口径来自 parsing/classify.py 的 TEXT_NATIVE）",
                    native == "native", f"text_status = {native}"))

    none_count = scalar(data_dir, "SELECT count(*) FROM documents WHERE text_status='none'")
    failed = scalar(data_dir, "SELECT count(*) FROM documents WHERE parse_status='failed'")
    rows.append(Row("无文本层的两份扫描件判为 none 而不是 failed（不许把好文件拖成失败）",
                    (none_count or 0) >= 2 and failed == 0,
                    f"text_status=none 的有 {none_count} 份｜parse_status=failed 的有 {failed} 份"))

    hits = query(data_dir,
                 "SELECT tp.page_no, tp.doc_id FROM content_fts"
                 " JOIN text_pages tp ON tp.rowid = content_fts.rowid"
                 " WHERE content_fts MATCH ? ORDER BY tp.page_no", (f'"{PHRASE[:6]}"',))
    rows.append(Row("G20 冻结态 FTS5 trigram 命中中文，且带真实页码", bool(hits),
                    f"命中 {len(hits)} 页，页号 {[h[0] for h in hits]}"))

    body = query(data_dir, "SELECT page_no, char_count, body FROM text_pages"
                           " WHERE doc_id=(SELECT id FROM documents WHERE name LIKE ?)"
                           " ORDER BY page_no", (f"%{PHRASE}%",))
    rows.append(Row("抽出的正文含预期句子、逐页内容互不相同（页码归属不是复制出来的）",
                    bool(body) and all(PHRASE in (r[2] or "") for r in body)
                    and len({r[0] for r in body}) == len(body),
                    f"{len(body)} 页｜页号 {[r[0] for r in body]}｜字数 {[r[1] for r in body]}"))

    gap = query(data_dir, "SELECT (SELECT count(*) FROM text_pages)"
                          " - (SELECT count(*) FROM content_fts)")
    rows.append(Row("G10 冻结产物写完的索引不留幽灵行（正文行数 = 索引行数）", gap[0][0] == 0,
                    f"text_pages − content_fts = {gap[0][0]}"))

    stuck = scalar(data_dir, "SELECT count(*) FROM processing_jobs"
                             " WHERE state NOT IN('done','cancelled','failed')")
    rows.append(Row("扫描阶段收尾后队列没有卡住的活", stuck == 0, f"未终结任务 {stuck} 条"))
    log(f"        扫描阶段事件={[e['event'] for e in events]}")

    ocr_id = scalar(data_dir, "SELECT id FROM documents WHERE name LIKE ?", ("%扫描件_有字无文本层%",)) or 0
    return rows, int(ocr_id)


def phase_ocr(exe: Path, data_dir: Path, run_dir: Path, doc_id: int) -> list[Row]:
    if not doc_id:
        return [Row("G20 冻结态 OCR 真推理（DLL 与模型都在包内）", False,
                    "前一条阶段没找到那份『有字无文本层』的扫描件，无法点名")]
    rows: list[Row] = []
    added = enqueue_ocr(data_dir, doc_id)
    marker = state_size(data_dir)
    proc = launch(exe, data_dir, run_dir, offscreen=True)
    sampler = Sampler(proc).start()
    ok, done, secs = wait_for(
        data_dir, "SELECT count(*) FROM text_pages WHERE doc_id=? AND ocr_version IS NOT NULL",
        lambda v: v >= 1, deadline=240, args=(doc_id,))
    reading = sampler.stop()
    close_gracefully(proc)
    events = state_events(data_dir, marker)

    body = query(data_dir, "SELECT page_no, body, ocr_version FROM text_pages"
                           " WHERE doc_id=? AND ocr_version IS NOT NULL ORDER BY page_no", (doc_id,))
    text = "".join(r[1] or "" for r in body)
    provider_line = ""
    for candidate in sorted(data_dir.glob("logs/app.log*")):
        for line in candidate.read_text(encoding="utf-8", errors="replace").splitlines():
            if "OCR 引擎就绪" in line:
                provider_line = line.strip()
    stamp = body[0][2] if body else None
    from pdfarchiver.ocr.engine import OcrEngine

    # OCR 失败必须能被远程诊断：把队列原文、文档原文、app.log 里的 OCR 行和 crash.log 尾巴
    # 一起抄进门禁输出，而不是只留一句"0 页"让人再跑一遍去猜。
    job_errors = [tuple(r) for r in query(data_dir,
                                          "SELECT kind, state, coalesce(last_error, '(空)')"
                                          " FROM processing_jobs WHERE kind='ocr' ORDER BY id DESC LIMIT 3")]
    doc_error = scalar(data_dir, "SELECT coalesce(last_error, '(空)') FROM documents WHERE id=?", (doc_id,))
    ocr_lines = [line.strip() for candidate in sorted(data_dir.glob("logs/app.log*"))
                 for line in candidate.read_text(encoding="utf-8", errors="replace").splitlines()
                 if "ocr" in line.lower()][:8]
    crash_file = data_dir / "logs" / "crash.log"
    crash_tail = (crash_file.read_text(encoding="utf-8", errors="replace")[-700:]
                  if crash_file.is_file() else "")

    rows.append(Row(f"G20 冻结态 OCR 真推理出正文（本次入队 {added} 条）", ok and bool(text.strip()),
                    f"{len(body)} 页｜等 {secs}s｜{reading}\n"
                    f"        队列原文 {job_errors}｜文档 last_error：{doc_error}\n"
                    f"        app.log OCR 行 {len(ocr_lines)} 条："
                    f"{' ｜ '.join(ocr_lines[:3]) if ocr_lines else '（没有）'}\n"
                    f"        crash.log：{crash_tail or '（不在场）'}"))
    rows.append(Row("冻结态识别结果里出现渲染进图片的那句话（不是假数据、不是原生文本层漏进来的）",
                    PHRASE in text, f"识别正文前 120 字：{text[:120]!r}"))
    rows.append(Row("冻结态版本指纹与开发机同一条口径（换显卡不该让整库过期）",
                    stamp == OcrEngine().version_stamp,
                    f"库内 {stamp}｜当次 OcrEngine.version_stamp = {OcrEngine().version_stamp}"))
    rows.append(Row("冻结态 OCR 走到的 provider 在 app.log 里有原文行", bool(provider_line),
                    provider_line or "app.log 里没有『OCR 引擎就绪』行"))
    log(f"        OCR 阶段事件={[e['event'] for e in events]}")
    return rows


def phase_restart(exe: Path, data_dir: Path, run_dir: Path) -> list[Row]:
    sqls = {"documents": "SELECT count(*) FROM documents",
            "categories": "SELECT count(*) FROM categories",
            "text_pages": "SELECT count(*) FROM text_pages",
            "tags": "SELECT count(*) FROM tags",
            "schema_version": "SELECT max(version) FROM schema_version"}
    before = {k: scalar(data_dir, v) for k, v in sqls.items()}
    marker = state_size(data_dir)
    proc = launch(exe, data_dir, run_dir, offscreen=True, exit_after=12.0)
    sampler = Sampler(proc).start()
    try:
        out, _ = proc.communicate(timeout=240)
    except subprocess.TimeoutExpired:
        proc.kill()
        out = "超时强杀"
    reading = sampler.stop()
    events = state_events(data_dir, marker)
    names = [e["event"] for e in events]
    after = {k: scalar(data_dir, v) for k, v in sqls.items()}

    rows = [
        Row("重启不再跑迁移", "migration.applied" not in names and proc.returncode == 0,
            f"本次事件={names}｜退出码 {proc.returncode}｜{reading}"),
        Row("重启后文档 / 分类 / 正文 / 标签 / 结构版本一条不少不多（幂等）", before == after,
            f"重启前 {before} → 重启后 {after}"),
        Row("重启后不重抽正文（内容哈希未变就不该再干活）",
            before["text_pages"] == after["text_pages"],
            f"text_pages {before['text_pages']} → {after['text_pages']}"),
        Row("关闭时留下 shutdown 对账行", "shutdown" in names, f"事件序列 {names}"),
    ]
    if out and out.strip():
        log(f"        stdout（窗口化产物本应为空）：{out.strip()[:200]}")
    return rows


def phase_kill_recovery(exe: Path, data_dir: Path, run_dir: Path, corpus: Path) -> list[Row]:
    rows: list[Row] = []
    add_bulk(corpus, 120, "第二批样本")
    total = len(list(corpus.rglob("*.pdf")))
    seed_root_and_enqueue_scan(data_dir, corpus)

    proc = launch(exe, data_dir, run_dir, offscreen=True)
    ok_running, running, secs = wait_for(
        data_dir, "SELECT count(*) FROM processing_jobs WHERE state='running'",
        lambda v: v >= 1, deadline=120)
    killed, detail = force_kill_tree(proc)
    rows.append(Row("制造真实中断：强杀时队列里确有 running 残尸", ok_running and killed,
                    f"残尸 {running} 条（等 {secs}s）｜taskkill /F：{detail}"))
    if not ok_running:
        return rows + [Row("重启把被杀留下的 running 收回队列", False,
                           "上一条没抓到残尸，后面的恢复无从谈起（把 BULK_DOCS 调大再跑）")]

    marker = state_size(data_dir)
    # 本阶段只判**这次新增**的失败：前一阶段留下的 OCR 失败不属于"被中断的任务续跑"这件事，
    # 混在一起数会让一条 RED 盖住另一条的口径。失败原文照样抄出来。
    failed_before = scalar(data_dir, "SELECT count(*) FROM processing_jobs WHERE state='failed'")
    proc2 = launch(exe, data_dir, run_dir, offscreen=True)
    sampler = Sampler(proc2).start()
    recovered = 0
    t0 = time.perf_counter()
    while time.perf_counter() - t0 < 180:
        started = [e for e in state_events(data_dir, marker) if e["event"] == "background.started"]
        if started:
            recovered = started[0].get("recovered", 0)
            break
        time.sleep(0.5)
    rows.append(Row("重启把上次被杀留下的 running 收回队列（D-030 的 recover 路径）", recovered >= 1,
                    f"background.started.recovered = {recovered}"))

    ok_done, left, secs2 = wait_for(
        data_dir, "SELECT count(*) FROM processing_jobs WHERE state IN('running','pending','queued')",
        lambda v: v == 0, deadline=360)
    reading = sampler.stop()
    close_gracefully(proc2)
    docs = scalar(data_dir, "SELECT count(*) FROM documents")
    failed = scalar(data_dir, "SELECT count(*) FROM processing_jobs WHERE state='failed'")
    fresh_failures = [tuple(r) for r in query(
        data_dir, "SELECT kind, coalesce(last_error,'(空)'), doc_id FROM processing_jobs"
                  " WHERE state='failed' ORDER BY id DESC LIMIT 5")][:]
    rows.append(Row("被中断的任务续跑完毕，队列不再有待办", ok_done and failed == failed_before,
                    f"未完成任务 {left} 条｜失败 {failed} 条（本阶段开始前已 {failed_before} 条，"
                    f"新增 {failed - failed_before} 条）｜等 {secs2}s｜{reading}\n"
                    f"        失败任务原文：{fresh_failures}"))
    rows.append(Row("两批语料全部在册（记录数 = 磁盘 PDF 数）", docs == total,
                    f"documents {docs} / 磁盘 {total}"))
    return rows


def phase_no_dev_paths(bundle: Path, data_dir: Path) -> list[Row]:
    """SPEC 阶段 7 验收第 2 条：产物不依赖开发机上的临时文件或绝对路径。"""
    rows: list[Row] = []
    needles = {"仓库路径": str(REPO), "venv 路径": str(REPO / ".venv")}
    files = [f for f in list((data_dir / "config").rglob("*")) + list((data_dir / "logs").rglob("*"))
             if f.is_file()]
    hits: dict[str, list[str]] = {}
    for f in files:
        text = f.read_text(encoding="utf-8", errors="replace")
        for label, needle in needles.items():
            if needle in text:
                hits.setdefault(label, []).append(f.name)
    rows.append(Row("产出的配置与日志里不含开发机仓库路径 / venv 路径", not hits,
                    f"命中={hits or '无'}（扫了 {len(files)} 个文件）"))
    rows.append(Row("本次运行目录在仓库外（否则『复制出去还能跑』这句没被验过）",
                    not str(bundle).startswith(str(REPO)), str(bundle)))
    return rows


# ───────────────────────────── 编排 ─────────────────────────────

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--keep", action="store_true", help="保留临时目录")
    ap.add_argument("--only", default="", help="first/scan/ocr/restart/kill/paths 之一，调试用")
    args = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    if not (BUNDLE_SRC / "PdfArchiver.exe").is_file():
        log(f"FAIL  找不到 {BUNDLE_SRC / 'PdfArchiver.exe'}，先跑 python packaging/build.py")
        print("VERDICT: RED（1 条未过）")
        return 1

    try:
        import psutil
        log(f"起跑负载：CPU {psutil.cpu_percent(interval=1.0)}%｜"
            f"可用内存 {round(psutil.virtual_memory().available / 1048576)}MiB"
            "（资源读数只在同负载下可比）")
    except Exception as exc:  # noqa: BLE001
        log(f"起跑负载：取不到（{type(exc).__name__}: {exc}）")

    work = Path(os.environ.get("TMP", ".")) / f"frozen_smoke_{time.strftime('%m%d_%H%M%S')}"
    run_dir, bundle = work / "run", work / "PdfArchiver"
    data_dir, corpus = work / "data_root", work / "corpus"
    for d in (run_dir, data_dir, corpus):
        d.mkdir(parents=True, exist_ok=True)

    t0 = time.perf_counter()
    shutil.copytree(BUNDLE_SRC, bundle, dirs_exist_ok=True)
    exe = bundle / "PdfArchiver.exe"
    log(f"产物已复制到仓库外：{exe}（{round(time.perf_counter() - t0, 1)}s）")

    info = make_corpus(corpus)
    log(f"临时真语料 {info['files']} 份 PDF 已生成于 {corpus}")

    rows: list[Row] = []
    ocr_doc_id = 0
    only = args.only
    if only in ("", "first"):
        rows += phase_first_launch(exe, data_dir, run_dir)
    if only in ("", "scan"):
        scan_rows, ocr_doc_id = phase_scan_and_search(exe, data_dir, run_dir, info, corpus)
        rows += scan_rows
    if only in ("", "ocr"):
        if not ocr_doc_id:
            ocr_doc_id = int(scalar(data_dir, "SELECT id FROM documents WHERE name LIKE ?",
                                    ("%扫描件_有字无文本层%",)) or 0)
        rows += phase_ocr(exe, data_dir, run_dir, ocr_doc_id)
    if only in ("", "restart"):
        rows += phase_restart(exe, data_dir, run_dir)
    if only in ("", "kill"):
        rows += phase_kill_recovery(exe, data_dir, run_dir, corpus)
    if only in ("", "paths"):
        rows += phase_no_dev_paths(bundle, data_dir)

    report = json.loads(BUILD_REPORT.read_text(encoding="utf-8")) if BUILD_REPORT.is_file() else {}
    rows.append(Row("体积对账报告在场（整包大小与逐项由构建那次当场写出）", bool(report.get("total_mb")),
                    f"整包 {report.get('total_mb')} MiB｜构建 {report.get('build_seconds')}s｜"
                    f"OCR 层 {report.get('ocr_in_venv')}"))

    bad = [r for r in rows if not r.ok]
    log("")
    for r in rows:
        print(f"  {'PASS' if r.ok else 'FAIL'}  {r.gate}")
        print(f"        {r.measured}")
    elapsed = round(time.perf_counter() - t0, 1)
    RESULT.write_text(json.dumps({"wall_seconds": elapsed, "bundle": str(bundle),
                                  "data_dir": str(data_dir), "build_report": report,
                                  "rows": [r.__dict__ for r in rows]}, ensure_ascii=False, indent=2),
                      encoding="utf-8")
    print(f"  INFO 总耗时 {elapsed}s｜结果写出 {RESULT.relative_to(REPO)}")
    if args.keep:
        print(f"  INFO 临时目录保留在 {work}")
    else:
        shutil.rmtree(work, ignore_errors=True)
        print("  INFO 临时目录已清理（--keep 可保留）")
    print("VERDICT: " + ("ALL GREEN" if not bad else f"RED（{len(bad)} 条未过）"))
    return 0 if not bad else 1


if __name__ == "__main__":
    raise SystemExit(main())
