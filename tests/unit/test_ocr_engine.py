"""OCR 引擎层（阶段 5 第 2 条「接入经过验证的本地 OCR 引擎」）—— 不碰真模型。

这一层的三件事都能在没有 onnxruntime 的情况下验，而且**必须**在没有它的情况下验：
可选层没装的机器上，产品的其余部分照常跑（模块说明第 1 条）。所以这里的"引擎"全部是
`sys.modules` 里塞的替身模块 —— 真推理由 `tests/integration/test_ocr_real_engine.py` 跑，
真性能数字由 `gates/stage5.py` 现测，不在这里编。

四条线各自对着一条会真出事的东西：
- 版本指纹里**没有 provider**：写进去就意味着换张显卡驱动要让全库重跑（p5 外推 1,144 GPU 小时）；
- provider 选择：有 DirectML 用 GPU、没有就退回 CPU，且两头的 `*_use_dml` kwargs 必须跟着变；
- 单页失败产错误对象而不是抛异常：抛出去就是一页坏内容拖死整本（第 4 条「失败不阻塞」）；
- 推理串行：worker 可以有多条线程，同一时刻只能有一个线程在推理（D-008，p5 实测两次并发就超显存）。
"""
from __future__ import annotations

import importlib.metadata
import sys
import threading
import time
import types

import pytest

from pdfarchiver.ocr.engine import (ENGINE_NAME, OcrEngine, OcrPage, OcrUnavailable, version_stamp)
from pdfarchiver.parsing.pdf import OCR_DPI


def _row(text: str):
    """RapidOCR 的一行：`[四点框, 文本, 置信度]`。取的就是下标 1。"""
    return [[[0, 0], [10, 0], [10, 8], [0, 8]], text, 0.95]


class _FakeOrt:
    def __init__(self, providers: list[str]) -> None:
        self._providers = providers

    def get_available_providers(self) -> list[str]:
        return list(self._providers)


class _FakeRapid:
    """替 `rapidocr_onnxruntime.RapidOCR`：记录建了几次、拿到哪些 kwargs。"""

    def __init__(self, **kwargs) -> None:
        type(self).built += 1
        type(self).last_kwargs = kwargs
        self.calls: list[object] = []

    built = 0
    last_kwargs: dict = {}

    def __call__(self, pixels):
        self.calls.append(pixels)
        return [_row("识别出来的一行"), _row("第二行")], None


@pytest.fixture
def fake_engine_modules(monkeypatch):
    """把 onnxruntime 与 rapidocr 两个模块换成替身，返回"声明这台机器有哪些 provider"的函数。

    用 `sys.modules` 而不是 patch 属性，是因为被测代码里是**函数内 import**
    （惰性、可选层的代价）—— 属性 patch 对 `from X import Y` 无效。
    版本号一并钉死：`ensure()` 成功时要打一条含版本指纹的日志，可选层真没装的机器上
    读不到版本号会让这条日志自己抛异常。
    """
    _FakeRapid.built = 0
    _FakeRapid.last_kwargs = {}
    module = types.ModuleType("rapidocr_onnxruntime")
    module.RapidOCR = _FakeRapid  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "rapidocr_onnxruntime", module)
    monkeypatch.setattr(importlib.metadata, "version",
                        lambda name: {"rapidocr-onnxruntime": "1.4.4",
                                      "onnxruntime-directml": "1.20.1"}[name])

    def _use(providers: list[str]) -> None:
        monkeypatch.setitem(sys.modules, "onnxruntime", _FakeOrt(providers))

    return _use


@pytest.fixture
def fixed_versions(monkeypatch):
    """版本号钉死。不钉的话，可选层没装的机器上这些断言会直接报错 —— 而这一层正是为"没装"设计的。"""
    monkeypatch.setattr(importlib.metadata, "version",
                        lambda name: {"rapidocr-onnxruntime": "1.4.4",
                                      "onnxruntime-directml": "1.20.1"}[name])


# —— 版本指纹：幂等跳过的唯一判据 ——————————————————————————

def test_版本指纹由引擎版本运行时版本与分辨率拼成(fixed_versions) -> None:
    assert version_stamp(dpi=200) == "rapidocr-onnxruntime/1.4.4+onnxruntime/1.20.1+dpi200"


def test_版本指纹里没有provider_换显卡不该让整库重跑(fixed_versions) -> None:
    """provider 会随驱动、显存占用甚至临时回退而变，而识别文本不变（p5 实测 text_identical=true）。
    把它写进指纹 = 每次回退 CPU 都判整库过期 = 143 个工作日重烧。"""
    stamp = version_stamp()
    assert "Dml" not in stamp and "CPU" not in stamp and "Provider" not in stamp, stamp
    assert ENGINE_NAME in stamp and f"dpi{OCR_DPI}" in stamp


@pytest.mark.parametrize("missing", [ENGINE_NAME, "onnxruntime-directml"])
def test_读不到版本号时报错点名缺哪个包以及怎么装(monkeypatch, missing: str) -> None:
    """不许编一个 "unknown" 充数：假指纹会让"版本没变所以跳过"看起来成立，
    于是一批永远不会重跑的页挂在一个不存在的版本号上。"""
    def _version(name: str) -> str:
        if name == missing:
            raise importlib.metadata.PackageNotFoundError(name)
        return "1.0.0"

    monkeypatch.setattr(importlib.metadata, "version", _version)

    with pytest.raises(OcrUnavailable, match=missing) as caught:
        version_stamp()
    assert "requirements/ocr.txt" in str(caught.value), "报错必须当场给出装法，不能只说没有"


# —— provider 选择与初始化 ————————————————————————————————

def test_出图分辨率钉在实测那一档(fixed_versions) -> None:
    """200dpi 是 p5 与阶段 5 复测所用的档：识别质量、单页耗时、1,144 小时的外推全由它算出来。

    悄悄改 `parsing.pdf.OCR_DPI` 会让版本串跟着变，而没有任何一处代码提醒"这批文本是另一档跑的"
    —— 要么整库白重跑，要么新旧两档的文本混在一张表里没人知道。所以这一行必须钉住，
    换档时它变红，逼着改动的人同时重做实测并写进文档。
    """
    assert OCR_DPI == 200
    assert OcrEngine().dpi == OCR_DPI
    assert version_stamp().endswith(f"+dpi{OCR_DPI}")


def test_有DirectML时默认用GPU且三个子配置都打开(fake_engine_modules) -> None:
    fake_engine_modules(["DmlExecutionProvider", "CPUExecutionProvider"])
    engine = OcrEngine()

    engine.ensure()

    assert engine.provider == "DmlExecutionProvider"
    assert {k: v for k, v in _FakeRapid.last_kwargs.items() if k.endswith("_use_dml")} == {
        "det_use_dml": True, "cls_use_dml": True, "rec_use_dml": True}


def test_没有DirectML时退回CPU并把GPU开关全关(fake_engine_modules) -> None:
    """两条路都能独立跑完同一批 OCR 是阶段 5 的验收项；退 CPU 不是退成交不了差。"""
    fake_engine_modules(["CPUExecutionProvider"])
    engine = OcrEngine()

    engine.ensure()

    assert engine.provider == "CPUExecutionProvider"
    assert all(v is False for k, v in _FakeRapid.last_kwargs.items() if k.endswith("_use_dml"))


def test_显式要求不用GPU时即使有DirectML也走CPU(fake_engine_modules) -> None:
    fake_engine_modules(["DmlExecutionProvider", "CPUExecutionProvider"])
    engine = OcrEngine(prefer_gpu=False)

    engine.ensure()

    assert engine.provider == "CPUExecutionProvider"


def test_一个进程只建一次引擎(fake_engine_modules) -> None:
    """`ensure()` 会被每条 worker 线程的第一页各调一次；建第二个引擎就是再吃 701MB 显存。"""
    fake_engine_modules(["CPUExecutionProvider"])
    engine = OcrEngine()

    engine.ensure()
    engine.ensure()

    assert _FakeRapid.built == 1


def test_没有任何可用provider时把现有列表说出来(fake_engine_modules) -> None:
    fake_engine_modules(["CUDAExecutionProvider"])

    with pytest.raises(OcrUnavailable, match="CUDAExecutionProvider"):
        OcrEngine().ensure()


def test_引擎建不起来时留住原始异常而不是吞掉(fake_engine_modules, monkeypatch) -> None:
    """AGENTS.md：任何非 2xx 都要能远程诊断 —— 初始化失败只剩一句"OCR 不可用"就查不下去。"""
    fake_engine_modules(["CPUExecutionProvider"])

    def _boom(**kwargs):
        raise RuntimeError("ONNX 模型文件校验失败")

    monkeypatch.setattr(_FakeRapid, "__init__", lambda self, **kw: _boom(**kw))

    with pytest.raises(OcrUnavailable, match="ONNX 模型文件校验失败"):
        OcrEngine().ensure()


def test_没装rapidocr时报错给出装法(fake_engine_modules, monkeypatch) -> None:
    fake_engine_modules(["CPUExecutionProvider"])
    monkeypatch.setitem(sys.modules, "rapidocr_onnxruntime", None)   # import 会抛 ImportError

    with pytest.raises(OcrUnavailable, match="requirements/ocr.txt"):
        OcrEngine().ensure()


def test_没装onnxruntime时报错点名发行包(monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "onnxruntime", None)

    with pytest.raises(OcrUnavailable, match="onnxruntime"):
        OcrEngine().ensure()


# —— 推理结果与失败 ————————————————————————————————————————

def _loaded() -> OcrEngine:
    engine = OcrEngine()
    engine._ocr = lambda pixels: ([_row("第一行"), _row("第二行")], None)
    return engine


def test_一页多行按出图顺序拼成换行文本() -> None:
    """行序与行数由模型给，这一层不重排、不合并、不数错 —— 片段定位与"识别了几行"都读它。"""
    page = _loaded().recognize(3, b"x")

    assert page == OcrPage(3, "第一行\n第二行", 2, page.took_ms)
    assert page.ok and page.error is None
    assert page.stripped_chars == 6


def test_识别结果为空算成功不算失败() -> None:
    """空白页本来就没字。给它记版本，下次才不会再跑 —— 与"这页失败了要重试"是两件事。"""
    engine = OcrEngine()
    engine._ocr = lambda pixels: (None, None)

    page = engine.recognize(1, b"x")

    assert page.ok and page.text == "" and page.lines == 0
    assert engine.pages_done == 1, "空白页也是识别过的一页"


def test_单页推理炸了只回错误对象不往上抛() -> None:
    """抛出去就是 946 页的书停在第 400 页。第 4 条「OCR 失败不能阻塞其他文件」在这句话上。"""
    engine = OcrEngine()

    def _boom(pixels):
        raise RuntimeError("DmlGetFrontendPartitionForNode failed: 显存不足")

    engine._ocr = _boom
    page = engine.recognize(400, b"x")

    assert page.error == "RuntimeError: DmlGetFrontendPartitionForNode failed: 显存不足"
    assert not page.ok and page.text == ""
    assert engine.pages_done == 0, "失败的页不许计入「识别过」，否则它永远不会回到待办"


def test_多线程推理同一时刻只有一个在跑() -> None:
    """D-008：p5 实测空闲显存 1,369MB、单次推理 701MB，两个并发就超；
    溢出后 ONNX 的行为是回退 CPU 或直接崩，两种都比慢更难查。"""
    engine = OcrEngine()
    inside = 0
    peak = 0
    guard = threading.Lock()

    def _slow(pixels):
        nonlocal inside, peak
        with guard:
            inside += 1
            peak = max(peak, inside)
        time.sleep(0.01)
        with guard:
            inside -= 1
        return [_row("字")], None

    engine._ocr = _slow
    threads = [threading.Thread(target=engine.recognize, args=(i, b"x")) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert peak == 1, f"同一时刻有 {peak} 个线程在推理"
    assert engine.pages_done == 8


def test_未加载时自报未加载而不是零页均值(fixed_versions) -> None:
    """状态页与门禁读这行字。报 "均值 0ms/页" 会被读成"识别很快"。"""
    engine = OcrEngine()

    assert "未加载" in engine.describe()

    engine._ocr = lambda pixels: ([_row("字")], None)
    engine.recognize(1, b"x")

    assert "已识别 1 页" in engine.describe()
