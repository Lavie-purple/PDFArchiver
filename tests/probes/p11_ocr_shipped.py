"""P11 探针：真实语料扫描件上量**产品真正发出去的那条 OCR 路**。

p5 量的是引擎裸调用（`ocr(arr)` 直接喂 numpy），阶段 5 复测量的是识别正确率。两者都回答不了
验收要的那句话：**用户点下「重新识别」以后，产品这条路在真实扫描页上花多少时间、吃多少内存、
识别出来的字进没进索引、落没落在正确的页上**。所以这里全程不手调引擎：

    真扫描件 → PdfReader 出图 → OcrEngine 推理 → OcrService 落库 → 真后台队列 → FTS5 → 检索

样本从真实语料里抽连续几页（`insert_pdf` 整页搬运，不重采样、不合成），要过两道门槛，
**两道都不是我发明的数**：

  1. 文本层为 0 —— 产品口径下这几页真的缺字。这一步不是形式主义：p5 一直当扫描件用的
     那本（**C1**，真实文件名只落 gitignored 的 `.probe_work/`，不入库）实测带 6 页 2,833 字的
     **隐藏 OCR 文本层**（2026-10-15 本探针跑出），产品口径下它一页都不该推理。
     拿它当"扫描件样本"等于把整条待办逻辑偷换成空气。
  2. 首页识别出的字数 ≥ `classify.MIN_CHARS_PER_BEARING_PAGE`(40) —— 同一条"有字的页"口径。
     少了这道就会挑中图多字少的样本（实测第一份候选抽的 6 页只有 7–86 字），
     检测框数量远低于正文页，用它算单页耗时会让吞吐外推系统性偏低。

于是这份探针同时出三组数：

  A 真无字、且是正文页的扫描件 → 走完整条 OCR 路：耗时 / 内存 / GPU / 质量 / 追溯 / 幂等
  B 合成扫描件（有标准答案）   → 逐字命中率与行均相似度，这是「识别质量」唯一能给百分比的地方
  C 控制组：带隐藏字层的那种"扫描件" → 发不出入场券，0 次推理
    （阶段 5「普通文字 PDF 不应无意义地反复执行 OCR」在真实语料上的直接证据）

三条规矩先说清，免得数字被误读：

1. **耗时/内存/GPU 只记录、不在探针里断言**。同一批页在独显与核显上差 5 倍是正常现象，
   把机器相关的数字写进判定条件只会得到 flaky；红线在 `gates/stage5.py`，阈值按实测反算。
2. **真实语料没有人工转写**，所以 A 组只报两项可计算的量：结构统计（每页字数/CJK 占比
   —— 乱码的典型特征是占比极低）与可检索性（识别出的词真能搜到且落在正确的页上）。
   不给真实页编一个"准确率 95%"。
3. **GPU 显存按实际能问到的说**。本机 `nvidia-smi` 可问（实测返回一张 NVIDIA 卡的空闲/占用/利用率），
   但 DirectML 落在哪个适配器上没有公开查询接口 —— 报原文数字 + 写明这条归属限制，不假装知道。

候选扫描件的名字取自 `.probe_work/p2_pdf_result.json` 里 `kind == "scanned_image"` 那 15 份，
目录取自 `.probe_work/p0_corpus_census.json`，两处都是实测产物，所以本探针里没有任何写死的本机路径。
只读用户文件、只往临时目录写，跑完删掉。

用法：
  python tests/probes/p11_ocr_shipped.py [--pages 6] [--control <pdf>] [--out .probe_work/p11_result.json]

末行 `VERDICT: ALL GREEN` = 结构性结论（跑通了、落库了、页对、幂等成立、文本能搜到、控制组零推理）全部成立。
"""
from __future__ import annotations

import argparse
import difflib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

import psutil  # noqa: E402
import pymupdf  # noqa: E402

from pdfarchiver.db.repositories.jobs import TERMINAL_STATES  # noqa: E402
from pdfarchiver.fs.identity import identity_key  # noqa: E402
from pdfarchiver.ocr.engine import OcrEngine, OcrUnavailable  # noqa: E402
from pdfarchiver.parsing.classify import MIN_CHARS_PER_BEARING_PAGE  # noqa: E402
from pdfarchiver.parsing.pdf import PdfReader  # noqa: E402
from pdfarchiver.search.service import FIELD_BODY, Criteria, SearchService  # noqa: E402
from pdfarchiver.services.bootstrap import bootstrap  # noqa: E402

WORK = REPO / ".probe_work"
CJK_RE = re.compile(r"[一-鿿]")
DEFAULT_PAGES = 6
MAX_CANDIDATES = 12         # 逐份确认「零字层 + 正文页」，最多试这么多份，就要么找到要么明说没找到
MIN_VERBATIM_HITS = 10      # 合成页逐字命中下限：实测 12/12，留 2 行给不同显卡与驱动
QUERY_PHRASE_CHARS = 6      # trigram 最少 3 字；取 6 个连着的中文字，检索才不至于撞上一堆页
SYNTHETIC_LINES = [
    "这部著作讨论的是阶层固化的社会学机制",
    "中间阶层的不安感来自收入与支出的双向挤压",
    "非接触欲望的年轻群体主动退出了消费竞争",
    "章节讨论就业形态与终身雇佣制的松动",
    "数据表明独居比例在都市圈持续攀升",
    "作者把这种倾向称为低欲望化的社会症候",
    "出版社版本说明与译者后记附在全书末尾",
    "目录列出了六章内容与三个附录条目",
    "参考文献区分日文原始资料与英文研究",
    "图表呈现了各年龄段收入分布的差异",
    "结语部分提出重新分配闲暇时间的主张",
    "版权页记载了首次印刷与版次信息",
]


class Instrumented(OcrEngine):
    """产品引擎本身，只在 `recognize` 外面加一圈记录。

    记录的是**同一条路**产出的 `OcrPage`（含耗时、行数、错误原文），所以这里的数字
    就是界面与状态页拿到的数字；换成自己调 `self._ocr` 就变成在量另一条没发布的路。
    """

    def __init__(self) -> None:
        super().__init__()
        self.samples: list[dict] = []

    def recognize(self, page_no: int, pixels: object):
        page = super().recognize(page_no, pixels)
        self.samples.append({"page_no": page_no, "took_ms": page.took_ms, "lines": page.lines,
                             "chars": page.stripped_chars, "error": page.error})
        return page


class RssSampler(threading.Thread):
    """后台采 RSS 峰值。只在跑完之后读一次等于没测：一页一事务的路径上峰值出现在中途。"""

    def __init__(self, proc: psutil.Process) -> None:
        super().__init__(daemon=True)
        self._proc = proc
        self._stop = threading.Event()
        self.peak_mb = proc.memory_info().rss / 1048576.0

    def run(self) -> None:
        while not self._stop.is_set():
            try:
                self.peak_mb = max(self.peak_mb, self._proc.memory_info().rss / 1048576.0)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                return
            time.sleep(0.05)

    def stop(self) -> None:
        self._stop.set()


def rss_mb() -> float:
    return psutil.Process(os.getpid()).memory_info().rss / 1048576.0


def gpu_state() -> dict:
    """能问到就报原文，问不到就报「这台机器问不到」+ 原因。绝不返回一个猜的数。"""
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.free,memory.used,utilization.gpu",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5, encoding="utf-8", errors="replace")
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired) as exc:
        return {"measurable": False, "reason": f"nvidia-smi 调用失败：{type(exc).__name__}: {exc}"}
    if out.returncode != 0:
        return {"measurable": False,
                "reason": (out.stderr or out.stdout).strip()[:200] or "nvidia-smi 返回非 0"}
    return {"measurable": True,
            "rows_name_free_mb_used_mb_util_pct": [ln.strip() for ln in out.stdout.splitlines() if ln.strip()],
            "caveat": "这是 nvidia-smi 问到的那张卡；DirectML 落在哪个适配器没有公开查询接口，"
                      "所以只报原文数字，不声称这增量就是本次推理的显存占用"}


def scanned_candidates() -> list[str]:
    """真实语料里 p2 判过「纯图像扫描件」的那些份，按现在还能不能找到过滤。

    名字取自 p2 结果，目录取自 p0 普查的「按 PDF 数量排名前 20 的目录」—— 两处都是实测产物，
    所以这里没有任何写死的本机路径。
    """
    p2, census = WORK / "p2_pdf_result.json", WORK / "p0_corpus_census.json"
    if not (p2.is_file() and census.is_file()):
        return []
    tails = [f["path_tail"] for f in json.loads(p2.read_text(encoding="utf-8")).get("files", [])
             if f.get("kind") == "scanned_image"]
    dirs = [d["dir"] for d in json.loads(census.read_text(encoding="utf-8"))
            .get("top20_directories_by_pdf_count", [])]
    found: list[str] = []
    for directory in dirs:
        root = Path(directory)
        if not root.is_dir():
            continue
        entries = [p for p in root.iterdir() if p.is_file() and p.suffix.lower() == ".pdf"]
        for tail in tails:
            # 用 startswith 而不是 glob：p2 记的 path_tail 是被截断过的前缀，
            # 而书名里的方括号会让 glob 把它当模式读，找到的就不是同一份文件。
            found.extend(str(p) for p in entries if p.name.startswith(tail))
        if found:
            break
    return found[:MAX_CANDIDATES]


def control_pdf(cli_path: str) -> str:
    """控制组样本：优先用 p5 那本「被当作扫描件的隐藏字层 PDF」，它正是口径要挡住的类型。
    返回空串表示真语料这本读不到，由 `measure_control` 退化成自己合成 —— 不是跳过。"""
    if cli_path and os.path.exists(cli_path):
        return cli_path
    hint = WORK / "p5_scanned_path.txt"
    if hint.is_file():
        path = hint.read_text(encoding="utf-8").strip()
        if path and os.path.exists(path):
            return path
    return ""


def extract_pages(src_pdf: str, dest: Path, *, pages: int) -> dict:
    """从真书里抽连续几页另存。页面图像原样搬运，文本层也原样保留（控制组靠它）。"""
    src = pymupdf.open(src_pdf)
    total = src.page_count
    begin = min(int(total * 0.34), max(0, total - 1))     # 跳过封面与版权页，取正文中段
    take = min(pages, total - begin)
    dest.parent.mkdir(parents=True, exist_ok=True)
    out = pymupdf.open()
    for offset in range(take):
        out.insert_pdf(src, from_page=begin + offset, to_page=begin + offset)
    out.save(str(dest))
    meta = {"corpus_pdf": os.path.basename(src_pdf), "corpus_total_pages": total,
            "extracted_from_page": begin + 1, "extracted_pages": take,
            "sample_bytes": dest.stat().st_size}
    src.close()
    out.close()
    return meta


def text_layer_chars(pdf: Path) -> tuple[int, int]:
    """用产品自己的读取器确认这份样本有没有字。返回 (文本层字符数, 页数)。"""
    with PdfReader(str(pdf)) as reader:
        return sum(p.stripped_chars for p in reader.iter_text_pages()), int(reader.info.page_count)


def first_page_recognized_chars(engine: OcrEngine, pdf: Path) -> int:
    """只识别第 1 页拿它的字数 —— 一次推理换「这份能不能当吞吐样本」的判据，值得。"""
    with PdfReader(str(pdf)) as reader:
        image = next(reader.iter_page_images(dpi=engine.dpi))
    if image.error is not None:
        raise RuntimeError(f"第 1 页出图失败：{image.error}")
    page = engine.recognize(image.page_no, image.pixels)
    if page.error is not None:
        raise RuntimeError(f"第 1 页识别失败：{page.error}")
    return page.stripped_chars


def choose_sample(dest_dir: Path, engine: OcrEngine, *, pages: int) -> tuple[Path | None, dict, list[dict]]:
    """返回 (可用样本, 元数据, 逐份淘汰记录)。没有一份合格就交回 None，由 main 明说而不是将就。"""
    tried: list[dict] = []
    for candidate in scanned_candidates():
        dest = dest_dir / "库" / "真实零字扫描件.pdf"
        record: dict = {"path_tail": os.path.basename(candidate)}
        try:
            meta = extract_pages(candidate, dest, pages=pages)
            chars, page_count = text_layer_chars(dest)
            record.update({"text_layer_chars": chars, "pages": page_count})
            if chars == 0 and page_count == meta["extracted_pages"]:
                record["first_page_recognized_chars"] = first_page_recognized_chars(engine, dest)
        except Exception as exc:  # noqa: BLE001 - 语料里的坏文件不是产品失败，原因如实记下再继续
            record["error"] = f"{type(exc).__name__}: {exc}"[:180]
            tried.append(record)
            dest.unlink(missing_ok=True)
            continue
        record["accepted"] = record.get("first_page_recognized_chars", 0) >= MIN_CHARS_PER_BEARING_PAGE
        tried.append(record)
        if record["accepted"]:
            meta.update({"source_abs": candidate, "text_layer_chars": 0, "pages": page_count})
            return dest, meta, tried
        dest.unlink(missing_ok=True)
    return None, {}, tried


def cjk_ratio(text: str) -> float:
    return round(len(CJK_RE.findall(text)) / len(text), 3) if text else 0.0


def build_synthetic_scan(dest: Path, lines: list[str], *, dpi: int) -> None:
    """排字 → 渲染成位图 → 贴回新页。产物是零文本层的图，字只存在于像素里。"""
    draft = pymupdf.open()
    page = draft.new_page(width=595, height=842)
    y = 70
    for line in lines:
        page.insert_text((48, y), line, fontsize=22, fontname="china-s")
        y += 60
    stream = page.get_pixmap(matrix=pymupdf.Matrix(dpi / 72, dpi / 72)).tobytes("png")
    draft.close()
    out = pymupdf.open()
    sheet = out.new_page(width=595, height=842)
    sheet.insert_image(sheet.rect, stream=stream)
    dest.parent.mkdir(parents=True, exist_ok=True)
    out.save(str(dest))
    out.close()


def build_synthetic_control(dest: Path, lines: list[str], *, dpi: int) -> None:
    """贴图之后在同一行位上再压一层 `render_mode=3` 的隐形字 —— 别人已经 OCR 过的扫描件就这样：
    屏幕上是图，抽取器读得到字。控制组要拦的正是这一种。"""
    build_synthetic_scan(dest, lines, dpi=dpi)
    out = pymupdf.open(str(dest))
    sheet = out[0]
    y = 70
    for line in lines:
        sheet.insert_text((48, y), line, fontsize=22, fontname="china-s", render_mode=3)
        y += 60
    scratch = dest.with_name(dest.stem + ".隐形层.pdf")
    out.save(str(scratch), garbage=3, deflate=True)
    out.close()
    scratch.replace(dest)


def measure_synthetic_quality(engine: OcrEngine, synthetic: Path) -> dict:
    """合成页逐字命中率 —— 唯一有标准答案的那个数，所以它是「识别质量」的百分比来源。"""
    with PdfReader(str(synthetic)) as reader:
        image = next(reader.iter_page_images(dpi=engine.dpi))
    if image.error is not None:
        return {"error": f"合成样本出图失败：{image.error}"}
    page = engine.recognize(image.page_no, image.pixels)
    if page.error is not None:
        return {"error": f"合成样本识别失败：{page.error}"}
    body = page.text
    hits = sum(1 for line in SYNTHETIC_LINES if line in body)
    sims = [round(difflib.SequenceMatcher(None, line, best_match(line, body)).ratio(), 3)
            for line in SYNTHETIC_LINES]
    return {"lines_expected": len(SYNTHETIC_LINES), "verbatim_hits": hits,
            "verbatim_rate": round(hits / len(SYNTHETIC_LINES), 3),
            "mean_line_similarity": round(sum(sims) / len(sims), 3),
            "recognized_chars": page.stripped_chars, "recognized_lines": page.lines,
            "took_ms": page.took_ms, "dpi": engine.dpi, "provider": engine.provider,
            "recognized_text": body}


def best_match(line: str, body: str) -> str:
    """从识别文本里挑与标准答案最像的一行，用于算「错成什么样」而不是「丢没丢」。"""
    rows = [row for row in body.split("\n") if row.strip()] or [body]
    return max(rows, key=lambda row: difflib.SequenceMatcher(None, line, row).ratio())


def traceability(ctx, doc_id: int, bodies: dict[int, str]) -> list[dict]:
    """从每一页真识别出来的字里取一段，回查能不能搜到、页对不对、出处标没标 OCR。"""
    service = SearchService(ctx.documents, ctx.metadata, ctx.texts)
    checks = []
    for page_no in sorted(bodies):
        phrase = next_phrase(bodies[page_no])
        if phrase is None:
            checks.append({"page_no": page_no, "skipped":
                           f"这一页识别出来的连续中文字不足 {QUERY_PHRASE_CHARS} 个，取不出可查词"})
            continue
        hits = [h for h in service.search(Criteria(text=phrase, in_fields=(FIELD_BODY,))).hits
                if int(h.doc.id) == doc_id]
        checks.append({"phrase": phrase, "expected_page": page_no,
                       "hit_pages": [h.page_no for h in hits],
                       "hit_on_expected_page": any(h.page_no == page_no for h in hits),
                       "body_source": hits[0].body_source if hits else None,
                       "source_label": hits[0].source_label if hits else None})
    return checks


def next_phrase(body: str) -> str | None:
    """找第一段连续 ≥6 个中文字。取不到就不硬凑 —— 拿标点空格拼出来的查询串验不到 trigram。"""
    for match in re.finditer(r"[一-鿿]{6,}", body):
        return match.group(0)[:QUERY_PHRASE_CHARS]
    return None


def clear_job_rows(ctx) -> None:
    """结掉扫描/索引排下的残行，否则「这次队列跑了几条」在数上一轮。"""
    for job in ctx.jobs.list():
        ctx.jobs.succeed(int(job.id))
    ctx.jobs.clear_finished()


def ingest(ctx, directory: Path, sample: Path) -> int:
    """样本目录登记成监测根 → 扫 → 索引，全程走产品自己的服务，返回 doc_id。"""
    root = ctx.roots.add(str(directory).replace("\\", "/"), identity_key(directory),
                         label="阶段5实测样本")
    ctx.scan.scan_root(root)
    facts = ctx.documents.facts_by_key(identity_key(str(sample)))
    if facts is None:
        raise RuntimeError(f"扫描没有把样本收进库：{sample}")
    doc_id = int(facts.doc_id)
    ctx.indexer.index_document(doc_id)
    clear_job_rows(ctx)
    return doc_id


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pages", type=int, default=DEFAULT_PAGES)
    ap.add_argument("--control", default="", help="控制组 PDF（默认取 p5 那本带隐藏字层的，没有就合成）")
    ap.add_argument("--timeout", type=float, default=900.0)
    ap.add_argument("--out", default=".probe_work/p11_ocr_shipped_result.json")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    import onnxruntime as ort

    report: dict = {
        "probe": "p11_ocr_shipped",
        "os": f"Windows {platform.release()} {platform.version()}",
        "python": platform.python_version(),
        "onnxruntime_version": ort.__version__,
        "providers_available": ort.get_available_providers(),
        "sample_gate": {"zero_text_layer": True, "min_first_page_chars": MIN_CHARS_PER_BEARING_PAGE},
    }

    work = Path(tempfile.mkdtemp(prefix="p11_ocr_shipped_"))
    ctx = None
    try:
        ctx = bootstrap(work / "appdata")
        proc = psutil.Process(os.getpid())
        rss_before = rss_mb()                      # 引擎还没建，这才是应用启动态的基线
        gpu_before = gpu_state()

        engine = Instrumented()
        try:
            engine.version_stamp                  # 可选层没装在这里就说清楚，别拖到跑一半
        except OcrUnavailable as exc:
            print(f"VERDICT: RED（可选 OCR 层没装：{exc}）")
            return 1
        ctx.ocr.engine = engine

        sample, meta, tried = choose_sample(work, engine, pages=args.pages)
        report["candidates_tried"] = tried
        if sample is None:
            print(f"VERDICT: RED（真实语料里没找到「零文本层 + 首页 ≥{MIN_CHARS_PER_BEARING_PAGE} 字」"
                  f"的样本，试了 {len(tried)} 份，逐份记录见 JSON）")
            return 1
        selection_samples = len(engine.samples)    # 筛选那几次推理不算进吞吐数字
        report["sample"] = meta

        doc_id = ingest(ctx, sample.parent, sample)
        doc = ctx.documents.get(doc_id)
        report["sample"]["text_status_after_index"] = doc.text_status
        if doc.text_status != "none":
            print("VERDICT: RED（零文本层的样本索引后却不判 none，入场券这条口径自己就不自洽）")
            return 1

        receipt = ctx.ocr.request_ocr([doc_id])
        report["queue"] = {"receipt": receipt.describe(), "named": receipt.named,
                           "queueable": receipt.queueable, "enqueued": receipt.enqueued}
        if receipt.enqueued != 1:
            print(f"VERDICT: RED（点名一份只排进 {receipt.enqueued} 条：{receipt.describe()}）")
            return 1

        sampler = RssSampler(proc)
        sampler.start()
        t0 = time.perf_counter()
        queue = ctx.start_background()             # 产品自己的注册表，不自搭 WorkQueue
        finished = queue.wait_until_idle(timeout=args.timeout)
        wall_s = round(time.perf_counter() - t0, 2)
        sampler.stop()
        stop_seconds = round(_stop_queue(queue), 3)
        job = next((j for j in ctx.jobs.list(TERMINAL_STATES) if j.kind == "ocr"), None)
        run_samples = engine.samples[selection_samples:]
        report["run"] = {
            "waited_idle": finished, "wall_seconds": wall_s, "queue_stop_seconds": stop_seconds,
            "engine_init_seconds": engine.init_seconds, "provider": engine.provider,
            "engine_describe": engine.describe(),
            "per_page_ms": [s["took_ms"] for s in run_samples],
            "per_page_lines": [s["lines"] for s in run_samples],
            "per_page_chars": [s["chars"] for s in run_samples],
            "inferences_this_run": len(run_samples),
            "pages_failed": sum(1 for s in run_samples if s["error"]),
            "job_state": job.state if job else None,
            "job_progress": [job.done, job.total] if job else None,
            "job_last_error": job.last_error if job else None,
        }
        report["memory"] = {
            "rss_before_engine_mb": round(rss_before, 1), "rss_after_run_mb": round(rss_mb(), 1),
            "delta_mb": round(rss_mb() - rss_before, 1), "peak_mb": round(sampler.peak_mb, 1),
            "peak_minus_startup_mb": round(sampler.peak_mb - rss_before, 1),
            "note": "基线取在引擎创建前（≈应用启动态）；峰值由 0.05s 采样的后台线程采集 —— "
                    "一页一事务的路径上峰值出现在中途，跑完再读一次等于没测"}
        report["gpu"] = {"before": gpu_before, "after": gpu_state()}

        pages = ctx.texts.pages_of(doc_id)
        bodies = {p.page_no: p.body for p in pages}
        doc = ctx.documents.get(doc_id)
        report["store"] = {
            "ocr_rows": len(pages),
            "all_pages_have_current_version": all(p.ocr_version == engine.version_stamp for p in pages),
            "distinct_versions": sorted({str(p.ocr_version) for p in pages}),
            "per_page": [{"page_no": p.page_no, "char_count": p.char_count,
                          "source_kind": p.source_kind, "cjk_ratio": cjk_ratio(p.body)}
                         for p in pages],
            "doc_ocr_status": doc.ocr_status, "doc_ocr_pages_done": doc.ocr_pages_done,
            "last_ocr_at": doc.last_ocr_at, "fts": ctx.texts.check_fts_consistency().as_dict(),
            "sample_text_first_page": (bodies[min(bodies)][:240] if bodies else ""),
            "per_page_lines_from_engine": report["run"]["per_page_lines"],
            "line_count_note": "库里 body 已过 normalize（连续空白压成一个空格），落库后数不出行，"
                               "所以行数以引擎识别时记录的 per_page_lines 为准",
        }

        pages_before_second = engine.pages_done
        second = ctx.ocr.request_ocr([doc_id])
        again = ctx.ocr.ocr_document(doc_id)
        report["idempotency"] = {
            "second_receipt": second.describe(), "second_enqueued": second.enqueued,
            "skipped_current": again.skipped_current,
            "pages_recognized_second_time": again.pages_recognized,
            "inferences_second_request": engine.pages_done - pages_before_second,
        }
        report["traceability"] = traceability(ctx, doc_id, bodies)

        synthetic = work / "合成扫描件.pdf"
        build_synthetic_scan(synthetic, SYNTHETIC_LINES, dpi=engine.dpi)
        report["quality_synthetic"] = measure_synthetic_quality(engine, synthetic)
        report["quality_synthetic"]["note"] = (
            "这一项有标准答案，所以能算逐字命中率；真实语料那几页没有人工转写，"
            "只报结构统计与可检索性，不编百分比")

        report["control_hidden_text_layer"] = measure_control(ctx, engine, work, control_pdf(args.control))
        report["verdicts"] = judge(report)

        out = REPO / args.out
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        _print(report, str(out))
        bad = [name for name, ok in report["verdicts"].items() if not ok]
        print("VERDICT: " + ("ALL GREEN" if not bad else f"RED（{len(bad)} 项未过：{', '.join(bad)}）"))
        return 0 if not bad else 1
    finally:
        if ctx is not None:
            ctx.shutdown()
        shutil.rmtree(work, ignore_errors=True)


def measure_control(ctx, engine: OcrEngine, work: Path, pdf: str) -> dict:
    """控制组：整页图 + 隐形字层的「已经 OCR 过的扫描件」，一页都不许推理。

    优先用真语料那一本（`--control` 或 p5 留下的路径提示）；读不到就自己合成同样一批字 ——
    这一条验的是「有字层的普通文字 PDF 不许被反复烧 GPU 小时」，与字来自哪本书无关，
    所以它不许因为语料盘没插而变成 skipped（探针的临时文件是会被清掉的）。
    """
    directory = work / "控制组"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "带隐藏字层的扫描件.pdf"
    if pdf:
        source = f"真语料《{os.path.basename(pdf)}》"
        extract_pages(pdf, path, pages=DEFAULT_PAGES)
    else:
        source = f"合成（{len(SYNTHETIC_LINES)} 行同一批字，整页贴图 + render_mode=3 隐形层）"
        build_synthetic_control(path, SYNTHETIC_LINES, dpi=engine.dpi)
    chars, page_count = text_layer_chars(path)
    doc_id = ingest(ctx, directory, path)
    status = ctx.documents.get(doc_id).text_status
    before = engine.pages_done
    outcome = ctx.ocr.ocr_document(doc_id)
    receipt = ctx.ocr.request_ocr([doc_id])
    return {"source": source, "text_layer_chars": chars, "pages": page_count,
            "text_status_after_index": status, "ocr_status": outcome.ocr_status,
            "pages_expected": outcome.pages_expected, "pages_recognized": outcome.pages_recognized,
            "inferences_added": engine.pages_done - before, "receipt": receipt.describe(),
            "meaning": f"字层已经在正文索引里（{chars} 字 / {page_count} 页），再跑一遍 OCR 就是"
                       f"白烧 GPU 小时；实际新增推理 {engine.pages_done - before} 次"}


def _stop_queue(queue) -> float:
    t0 = time.perf_counter()
    queue.stop()
    return time.perf_counter() - t0


def judge(report: dict) -> dict[str, bool]:
    """结构性结论 —— 全是可计算的，不含任何机器相关的耗时数字。"""
    run, store, sample = report["run"], report["store"], report["sample"]
    traced = [c for c in report["traceability"] if "phrase" in c]
    synth = report["quality_synthetic"]
    control = report["control_hidden_text_layer"]
    verdicts = {
        "队列跑完且进度对得上页数": bool(run["waited_idle"]) and run["job_state"] == "done"
        and run["job_progress"] == [sample["pages"], sample["pages"]],
        "每一页都真推理过且没有失败页": run["inferences_this_run"] == sample["pages"]
        and run["pages_failed"] == 0 and len(run["per_page_ms"]) == sample["pages"],
        "落库页数与版本指纹一致": store["ocr_rows"] == sample["pages"]
        and store["all_pages_have_current_version"],
        "主记录状态、页数与完成时刻都写了": store["doc_ocr_status"] == "done"
        and store["doc_ocr_pages_done"] == sample["pages"] and store["last_ocr_at"] is not None,
        "OCR 正文与全文索引花名册对得齐（漏索引/残留都为 0）": store["fts"]["unindexed"] == 0
        and store["fts"]["stale_docsize"] == 0 and store["fts"]["pages"] == store["fts"]["indexed"],
        "第二次点名不再推理": report["idempotency"]["second_enqueued"] == 0
        and report["idempotency"]["skipped_current"] is True
        and report["idempotency"]["pages_recognized_second_time"] == 0
        and report["idempotency"]["inferences_second_request"] == 0,
        "识别出的词能搜回原页并带出处": bool(traced) and all(
            c["hit_on_expected_page"] and c["body_source"] == "ocr"
            and c["source_label"] == "OCR 识别（可能有错字）" for c in traced),
        "合成页逐字命中达标": synth.get("verbatim_hits", -1) >= MIN_VERBATIM_HITS,
        "控制组带隐藏字层的扫描件零推理": control["inferences_added"] == 0
        and control["pages_recognized"] == 0,
    }
    return verdicts


def _print(report: dict, out_path: str) -> None:
    run, mem, sample = report["run"], report["memory"], report["sample"]
    print(f"样本：{sample['corpus_pdf']} 第 {sample['extracted_from_page']} 页起 {sample['pages']} 页"
          f"｜{sample['sample_bytes'] / 1048576:.1f}MB｜索引判定 text_status={sample['text_status_after_index']}")
    print(f"候选：试了 {len(report['candidates_tried'])} 份真语料才找到「零字层 + 首页 ≥"
          f"{MIN_CHARS_PER_BEARING_PAGE} 字」的那份")
    print(f"引擎：provider={run['provider']} 初始化 {run['engine_init_seconds']}s｜{run['engine_describe']}")
    print(f"耗时：单页 {run['per_page_ms']} ms｜整本墙钟 {run['wall_seconds']}s｜"
          f"队列收尾 {run['queue_stop_seconds']}s")
    print(f"内存：启动态 {mem['rss_before_engine_mb']}MiB → 跑完 {mem['rss_after_run_mb']}MiB"
          f"（增量 {mem['delta_mb']}MiB｜峰值 {mem['peak_mb']}MiB）")
    for label, key in (("GPU 跑前", "before"), ("GPU 跑后", "after")):
        gpu = report["gpu"][key]
        print(f"{label}：" + (str(gpu["rows_name_free_mb_used_mb_util_pct"]) if gpu.get("measurable")
                             else f"不可测｜{gpu.get('reason', '')}"))
    print(f"质量（真实页，无人工转写）：每页 {report['store']['per_page']}")
    print(f"                      识别行数 {run['per_page_lines']}｜识别字数 {run['per_page_chars']}")
    synth = report["quality_synthetic"]
    print(f"质量（合成页，有标准答案）：逐字命中 {synth.get('verbatim_hits')}/"
          f"{synth.get('lines_expected')}｜行均相似度 {synth.get('mean_line_similarity')}"
          f"｜{synth.get('took_ms')}ms/页")
    printable = [c for c in report["traceability"] if "phrase" in c]
    print(f"追溯：取到可查词的页 {[c['expected_page'] for c in printable]} → 命中页 "
          f"{[c['hit_pages'] for c in printable]}")
    idem = report["idempotency"]
    print(f"幂等：{idem['second_receipt']}｜第二次点名新增推理 {idem['inferences_second_request']} 次")
    control = report["control_hidden_text_layer"]
    print(f"控制组：{control['source']} 文本层 {control['text_layer_chars']} 字/"
          f"{control['pages']} 页 → text_status={control['text_status_after_index']} "
          f"ocr_status={control['ocr_status']} 应识别 {control['pages_expected']} 页 "
          f"新增推理 {control['inferences_added']} 次")
    print(f"样例识别文本：{report['store']['sample_text_first_page'][:180]}")
    for name, ok in report["verdicts"].items():
        print(f"  {'PASS' if ok else 'RED '}  {name}")
    print(f"结果已写入 {out_path}")


if __name__ == "__main__":
    raise SystemExit(main())
