"""本地 OCR 引擎适配 —— 阶段 5 唯一认识 RapidOCR/onnxruntime 的地方。

**为什么单独一层**：`services/ocr_service.py` 只管"什么时候跑、跑哪几页、结果写到哪"，
它不该知道 RapidOCR 的 kwargs 是扁平命名（`det_use_dml` / `cls_use_dml` / `rec_use_dml`）、
也不该知道 onnxruntime 的 provider 列表怎么读。这些全是 p5 探针实测出来的细节，
写在一个地方才能被一处改完。

三条硬口径：

1. **只在真要用时才 import 引擎**（`ensure()`）。OCR 是可选层（`requirements/ocr.txt`），
   base 装的机器上没有 rapidocr；模块级 import 会让"只扫描+全文检索"的部署连启动都起不来。
   没装就抛 `OcrUnavailable`，消息里写清缺哪个包 —— 不许退化成"看起来跑成功了但什么都没做"。
2. **默认不联网**：识别全在本机 ONNX 模型里（PP-OCRv4 det 4.5 + rec 10.4 + cls 0.6 MiB，
   随包发布，阶段 5 实测确认无需下载）。这一层不 import 任何网络库，
   `tests/guards/test_architecture.py` 的依赖方向检查会盯着它。
3. **GPU 串行**（D-008）：`self._lock` 保证同一时刻只有一个线程在推理。worker 线程可以有多个，
   但 OCR 这一段排队是故意的 —— p5 实测空闲显存 1,369MB、一次推理吃掉 701MB，
   两个并发就直接超；显存溢出后 ONNX 的行为是回退 CPU 或崩，两种都比慢更难查。
"""
from __future__ import annotations

import importlib.metadata
import logging
import threading
import time
from dataclasses import dataclass

from pdfarchiver.parsing.pdf import OCR_DPI

log = logging.getLogger("pdfarchiver.ocr")

ENGINE_NAME = "rapidocr-onnxruntime"
SUPPORTED_PROVIDERS = ("DmlExecutionProvider", "CPUExecutionProvider")


class OcrUnavailable(RuntimeError):
    """可选 OCR 层没装，或装了但引擎起不来。消息必须带缺什么、怎么装。"""


@dataclass(frozen=True)
class OcrPage:
    """一页的识别结果。`text` 是各行按出图顺序用换行拼起来的：
    换行在这里只是"行与行的分界"，`lines` 数的是识别出几行，顺序就是模型给出的顺序。

    **它不会原样进库**：`services/ocr_service.py` 落库前过 `indexing.normalize.normalize_page_text`，
    与原生正文同一个口径（连续空白压成一个空格）。两边不同口径的话，同一句话在两个来源里
    一个搜得到一个搜不到，那种 bug 没人查得出来。
    """

    page_no: int
    text: str
    lines: int
    took_ms: float
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None

    @property
    def stripped_chars(self) -> int:
        return len(self.text.replace(" ", "").replace("\n", ""))


def version_stamp(*, dpi: int = OCR_DPI) -> str:
    """OCR 结果的**出处指纹**，存进 `text_pages.ocr_version`，幂等跳过就比这个串。

    里面只有三样东西：引擎版本、运行时版本、出图分辨率。**刻意不含 provider** ——
    p5 实测同一批扫描页 CPU 与 DirectML 的识别文本 `text_identical=true`，
    把 provider 写进指纹就等于"显卡驱动更新/临时退回 CPU"都会让整库判定过期，
    而一次整库重跑是 1,144 GPU 小时（p5 外推）。
    """
    return (f"{ENGINE_NAME}/{_dist(ENGINE_NAME)}+onnxruntime/{_dist('onnxruntime-directml')}"
            f"+dpi{dpi}")


def _dist(name: str) -> str:
    """读已发布版本号；读不到就说读不到，不编一个 "unknown" 充数（那会让指纹看起来有效）。"""
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError as exc:
        raise OcrUnavailable(
            f"可选 OCR 层没装：缺发行包 {name}。装法见 requirements/ocr.txt（必须按文件里的顺序装，"
            "先装 onnxruntime-directml 再装 rapidocr）") from exc


class OcrEngine:
    """一份进程内共享的推理引擎。惰性创建，线程安全，串行推理。"""

    def __init__(self, *, prefer_gpu: bool = True, dpi: int = OCR_DPI) -> None:
        self.prefer_gpu = prefer_gpu
        self.dpi = dpi
        self._ocr = None
        self._lock = threading.Lock()
        self.provider: str | None = None
        self.init_seconds: float | None = None
        self.pages_done = 0
        self.total_ms = 0.0

    @property
    def version_stamp(self) -> str:
        return version_stamp(dpi=self.dpi)

    # ---- 生命周期 ----
    def ensure(self) -> None:
        """创建引擎（首次 1.86–3.3s，p5 两次实测；阶段 5 复测 2.20s）。已创建就立即返回。"""
        with self._lock:
            if self._ocr is not None:
                return
            t0 = time.perf_counter()
            provider = self._pick_provider()
            try:
                # p5 实测过这组 kwargs：RapidOCR 1.4.4 是扁平命名，det_/cls_/rec_ 前缀进各自子配置。
                from rapidocr_onnxruntime import RapidOCR  # noqa: PLC0415 - 可选层，见模块说明第 1 条
            except ImportError as exc:
                raise OcrUnavailable(
                    f"可选 OCR 层没装：import rapidocr_onnxruntime 失败（{exc}）。"
                    "装法见 requirements/ocr.txt") from exc
            try:
                self._ocr = RapidOCR(log_level="error", use_cuda=False,
                                     det_use_dml=(provider == "DmlExecutionProvider"),
                                     cls_use_dml=(provider == "DmlExecutionProvider"),
                                     rec_use_dml=(provider == "DmlExecutionProvider"))
            except Exception as exc:  # noqa: BLE001 - 引擎起不来的原因很多，原样留住才能远程诊断
                raise OcrUnavailable(f"OCR 引擎初始化失败（provider={provider}）："
                                     f"{type(exc).__name__}: {exc}") from exc
            self.provider = provider
            self.init_seconds = round(time.perf_counter() - t0, 3)
            log.info("OCR 引擎就绪 provider=%s 耗时 %.2fs 版本 %s",
                     provider, self.init_seconds, self.version_stamp)

    def _pick_provider(self) -> str:
        """有 DirectML 就用，没有就退回 CPU —— 两条路都能独立跑完同一批 OCR 是阶段 5 的验收项，
        而 p5 已验过两者结果逐字一致，所以退回 CPU 不是降级成交不了差。"""
        try:
            import onnxruntime as ort  # noqa: PLC0415
        except ImportError as exc:
            raise OcrUnavailable(
                "可选 OCR 层没装：import onnxruntime 失败（%s）。装法见 requirements/ocr.txt"
                % exc) from exc
        available = [p for p in SUPPORTED_PROVIDERS if p in ort.get_available_providers()]
        if not available:
            raise OcrUnavailable(
                f"onnxruntime 没有可用 provider，现有 {ort.get_available_providers()}")
        if "DmlExecutionProvider" in available and self.prefer_gpu:
            return "DmlExecutionProvider"
        return "CPUExecutionProvider"

    # ---- 推理 ----
    def recognize(self, page_no: int, pixels: object) -> OcrPage:
        """识别一页。单页失败产 `OcrPage(error=原文)` 并继续 —— 调用方永远拿到一个对象而不是异常，
        「失败不阻塞其他文件」就是从这一句开始的。

        页数与耗时两个累计数**也在锁里更新**：它们在锁外面就是两个无同步的 `+=`，
        多线程下会丢更新，而门禁与状态页拿它们算的正是「平均每页多少毫秒」。
        """
        self.ensure()
        t0 = time.perf_counter()
        with self._lock:
            try:
                result, _elapse = self._ocr(pixels)  # noqa: SLF001 - RapidOCR 的 __call__ 就是接口
            except Exception as exc:  # noqa: BLE001 - 出图内容千奇百怪，任何一页都不许拖垮整本
                took = (time.perf_counter() - t0) * 1000
                log.warning("OCR 第 %d 页失败：%s: %s", page_no, type(exc).__name__, exc)
                return OcrPage(page_no, "", 0, round(took, 1), f"{type(exc).__name__}: {exc}")
            rows = result or []
            text = "\n".join(str(r[1]) for r in rows)
            took = (time.perf_counter() - t0) * 1000
            self.pages_done += 1
            self.total_ms += took
        return OcrPage(page_no, text, len(rows), round(took, 1))

    def describe(self) -> str:
        """给状态页与门禁读的自报数字。没跑过就说没跑过，不报 0ms 均值糊弄。"""
        if self._ocr is None:
            return f"OCR 引擎未加载｜版本 {self.version_stamp}"
        avg = self.total_ms / self.pages_done if self.pages_done else 0.0
        return (f"OCR provider={self.provider} 初始化 {self.init_seconds}s｜"
                f"已识别 {self.pages_done} 页｜均值 {avg:.0f}ms/页｜版本 {self.version_stamp}")
