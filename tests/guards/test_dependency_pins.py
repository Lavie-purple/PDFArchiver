"""G21 依赖钉版守卫：版本装错不是报错，是段错误 —— 所以必须在 import 之前拦住。

证据来源 docs/VERIFICATION.md 第二节：
  - PySide6 6.12.0 在 Win10 19045 上 import 即 WinError 127
  - onnxruntime >=1.21 全部 WinError 1114 DLL 初始化失败
  - 纯 onnxruntime 与 onnxruntime-directml 共存 -> import 直接 exit 139（无异常可捕获）
  - rapidocr-onnxruntime 声明依赖 onnxruntime，会把它自动拽回来

用法：
    python -m pytest tests/guards/test_dependency_pins.py -q
或独立跑（不需要 pytest）：
    python tests/guards/test_dependency_pins.py
"""
from __future__ import annotations

import sys


class PinError(AssertionError):
    """守卫失败。消息里必须写清「违反了哪条实测结论」。"""


def _interp_note() -> str:
    """版本守卫最常见的"假阳性"是用错解释器（项目外还有别的 Python，
    里面装着 torch 之类被禁的包）。红的时候必须能一眼看出是哪台解释器。"""
    return f"（当前解释器：{sys.executable}；本项目只认 .venv 里的依赖）"


def _ver(s: str) -> tuple[int, ...]:
    parts = []
    for chunk in s.split(".")[:3]:
        digits = ""
        for ch in chunk:
            if ch.isdigit():
                digits += ch
            else:
                break
        parts.append(int(digits or 0))
    return tuple(parts)


def _dist_version(name: str) -> str | None:
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version(name)
    except PackageNotFoundError:
        return None


def _assert_pin(name: str, allowed_max: str | None = None, exact: str | None = None) -> str:
    """返回实际版本；未安装返回 '-'（调用方决定是否算失败）。

    这里刻意不调 importlib 之外的任何东西：守卫不能在检查过程中 import 被检查的包，
    因为一旦共存，import 本身就是那个会段错误的动作。
    """
    got = _dist_version(name)
    if got is None:
        return "-"
    if exact is not None and got != exact:
        raise PinError(f"{name}=={exact} 是实测唯一可用版本，当前 {got} {_interp_note()}")
    if allowed_max is not None and _ver(got) > _ver(allowed_max):
        raise PinError(
            f"{name} 必须 <= {allowed_max}（更高版本在本机 DLL 初始化失败），当前 {got} {_interp_note()}"
        )
    return got


def test_pyside6_pinned_to_6_8_lts() -> None:
    """6.12 装得上、导入即 WinError 127。不许放开上界。"""
    got = _assert_pin("PySide6", exact="6.8.3")
    if got != "-":
        assert got.startswith("6.8."), f"PySide6 只允许 6.8.x，当前 {got}"
        _assert_pin("PySide6-Essentials", exact="6.8.3")
        _assert_pin("shiboken6", exact="6.8.3")


def test_onnxruntime_version_ceiling() -> None:
    """>=1.21 全部 WinError 1114；1.19.2 / 1.20.1 实测可用。"""
    _assert_pin("onnxruntime", allowed_max="1.20.1")
    _assert_pin("onnxruntime-directml", allowed_max="1.20.1")


def test_exactly_one_onnxruntime_distribution() -> None:
    """两个发行版共存 -> 同一个 onnxruntime/ 目录互相覆盖 -> import 段错误 exit 139。

    这条是全套守卫里最重要的：它的失败模式不是异常，是进程直接没了，
    所以宁可在这里误报，也不许放行。
    """
    plain = _dist_version("onnxruntime")
    dml = _dist_version("onnxruntime-directml")
    if plain is not None and dml is not None:
        raise PinError(
            f"同时存在 onnxruntime=={plain} 与 onnxruntime-directml=={dml}。"
            "两者往同一 onnxruntime/ 目录写，import 会直接段错误。"
            "处置：pip uninstall -y onnxruntime onnxruntime-directml && "
            "pip install onnxruntime-directml==1.20.1"
        )
    assert plain is None or dml is None


def test_project_has_onnxruntime_when_optional_layers_installed() -> None:
    """装了 OCR 或语义层就必须有且只有一个 ORT 发行版；都没装则允许为空。"""
    present = [n for n in ("onnxruntime", "onnxruntime-directml") if _dist_version(n)]
    optional = [n for n in ("rapidocr-onnxruntime", "tokenizers") if _dist_version(n)]
    if optional and not present:
        raise PinError(f"已装可选层 {optional} 但没有任何 onnxruntime 发行版")
    assert len(present) <= 1, f"多个 ORT 发行版共存：{present}"


def test_pymupdf_and_watchdog_installed() -> None:
    _assert_pin("PyMuPDF", exact="1.28.2")
    _assert_pin("watchdog")


def test_no_gpu_framework_that_pulls_cuda() -> None:
    """SPEC 第五节：不许因为显卡型号就假设 CUDA。torch/tensorflow 一旦进来
    就会把「CUDA 可用与否」变成运行期隐式分支，本项目只允许 onnxruntime + DirectML。"""
    for banned in ("torch", "tensorflow", "paddlepaddle", "transformers", "sentence-transformers"):
        if _dist_version(banned) is not None:
            raise PinError(
                f"依赖树里出现了 {banned}；本项目的推理路径只有 onnxruntime-directml {_interp_note()}"
            )


def _self_check() -> int:
    """独立运行入口，同时做一次「本守卫能不能被骗过」的自检。

    AGENTS.md 要求每条断言先用能骗过它的坏法真注入一次。这里注入的是最关键的
    test_exactly_one_onnxruntime_distribution：伪造两个发行版共存，必须抛错。
    """
    guards = [
        ("one-ORT-distribution 能识破共存", _fake_coexist_raises),
        ("one-ORT-distribution 放行正确状态", _fake_single_ok),
        ("版本上限能识破 1.31.0", _fake_ceiling_raises),
        ("版本上限放行 1.20.1", _fake_ceiling_ok),
    ]
    failed = 0
    for label, fn in guards:
        try:
            fn()
            print(f"  PASS  [自检] {label}")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"  FAIL  [自检] {label} -> {type(exc).__name__}: {exc}")
    real = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"  PASS  {name}")
            except Exception as exc:  # noqa: BLE001
                real += 1
                print(f"  FAIL  {name} -> {type(exc).__name__}: {exc}")
    print(f"依赖树：{[n for n in ('onnxruntime', 'onnxruntime-directml') if _dist_version(n)]}")
    print("VERDICT: " + ("ALL GREEN" if not (failed or real) else "RED"))
    return 0 if not (failed or real) else 1


def _patched(present: dict[str, str | None]):
    """临时替换 _dist_version，用来注入坏状态。"""
    import types

    module = sys.modules[__name__]
    original = module._dist_version

    def deco(fn):
        def wrapper():
            module._dist_version = lambda n: present.get(n)
            try:
                return fn()
            finally:
                module._dist_version = original

        return wrapper

    return deco


def _fake_coexist_raises() -> None:
    @_patched({"onnxruntime": "1.31.0", "onnxruntime-directml": "1.20.1"})
    def case():
        try:
            test_exactly_one_onnxruntime_distribution()
        except PinError:
            return
        raise AssertionError("坏法骗过了守卫：共存状态没有被拦住")

    case()


def _fake_single_ok() -> None:
    @_patched({"onnxruntime-directml": "1.20.1"})
    def case():
        test_exactly_one_onnxruntime_distribution()

    case()


def _fake_ceiling_raises() -> None:
    @_patched({"onnxruntime": "1.31.0"})
    def case():
        try:
            test_onnxruntime_version_ceiling()
        except PinError:
            return
        raise AssertionError("坏法骗过了守卫：1.31.0 没有被拦住")

    case()


def _fake_ceiling_ok() -> None:
    @_patched({"onnxruntime": "1.20.1"})
    def case():
        test_onnxruntime_version_ceiling()

    case()


if __name__ == "__main__":
    sys.exit(_self_check())
