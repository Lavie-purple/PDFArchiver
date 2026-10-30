"""首启引导向导（轮四十三 甲）的界面接线。

钉的全是**点下去之后库里多出来的东西**，不钉文案：
「看过引导」这个状态只有 `app_settings["ui.wizard.done"]` 一个口径，向导里那三屏
只是把它写进去的其中一条路；另一条（S7「首次引导…」重开）必须能在键已写的情况下
仍然把窗拉起来。第三步「选择目录…」走的是 `ctx.register_root` —— 与 S7 同一入口，
所以这里断言的是 `monitored_roots` 真的多了一行且 `enabled=1`，不是那句回显。

**测试里一律不调 `wizard.exec()`**：模态阻塞会让 offscreen 下的 `settle()` 永远不返回
（`dialog_doubles.py` 记过 QMessageBox 那一次卡死）。要验"弹了"就把 `exec` 换成记录器。

`conftest.py` 的三条规矩照常适用：offscreen、独立数据根、真 sqlite3（D-012）。
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from PySide6 import QtWidgets

from pdfarchiver.services.bootstrap import AppContext, bootstrap
from pdfarchiver.ui.onboarding_wizard import (
    ONBOARDING_KEY,
    STEP2_NOTE,
    OnboardingWizard,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


def _wizard(window, ctx: AppContext) -> OnboardingWizard:
    """建一页向导但不进事件循环（不 `exec`），按钮照样能 `click()`。"""
    return OnboardingWizard(ctx, window)


def _to_step2(wizard: OnboardingWizard) -> None:
    wizard.next_btn.click()
    assert wizard.steps.currentIndex() == 1, "第一步点「下一步」没到第二步"


# ---- 判据本身 ----


def test_干净数据根首启判定为要弹(window, ctx) -> None:
    """首启 = 库里没有 `ONBOARDING_KEY`。写死在别处（settings.json / 环境变量）就是第二个口径。"""
    assert window._should_show_onboarding() is True
    ctx.app_settings.set(ONBOARDING_KEY, True)
    assert window._should_show_onboarding() is False, "写过「看过」还判要弹 = 每次启动都拦一道"


def test_走完三步点完成会记下看过(window, ctx) -> None:
    """主路：下一步 → 下一步 → 完成。三步都得真的能走到底，且最后落在同一屏才叫「完成」。"""
    wizard = _wizard(window, ctx)
    # 向导从未 show，用 isVisibleTo/isHidden 才读得到 `setVisible` 的结果（isVisible 恒 False）
    assert not wizard.skip_btn.isHidden() and wizard.prev_btn.isHidden(), \
        "第一屏该有「跳过」没有「上一步」"

    _to_step2(wizard)
    wizard.next_btn.click()
    assert wizard.steps.currentIndex() == 2
    assert wizard.next_btn.text() == "完成", "最后一屏的按钮还写着「下一步」= 按下去走不出去"
    assert wizard.skip_btn.isHidden(), "最后一屏不该再有「跳过」"
    wizard.next_btn.click()

    assert ctx.app_settings.get(ONBOARDING_KEY, False) is True
    assert window._should_show_onboarding() is False


def test_跳过也算看过(window, ctx) -> None:
    """「跳过」= 用户明确不想被引导，不写键的话下次启动又弹一遍。"""
    wizard = _wizard(window, ctx)
    wizard.skip_btn.click()
    assert ctx.app_settings.get(ONBOARDING_KEY, False) is True


def test_上一步能退回去(window, ctx) -> None:
    """三步窗不许只能往前走：第二步挑错了目录要能回第一步，且第一屏的按钮排要跟着换回来。"""
    wizard = _wizard(window, ctx)
    _to_step2(wizard)
    wizard.prev_btn.click()
    assert wizard.steps.currentIndex() == 0, "第二步点「上一步」没退回第一屏"
    assert not wizard.skip_btn.isHidden(), "退回第一屏却没把「跳过」摆回来"


# ---- ✕ 关窗的两种命运 ----


def test_直接关窗且没勾选下次还弹(window, ctx) -> None:
    wizard = _wizard(window, ctx)
    wizard.close()
    assert ctx.app_settings.get(ONBOARDING_KEY, None) is None, "没表态就当没看过"
    assert window._should_show_onboarding() is True


def test_勾选以后不再显示后关窗才算看过(window, ctx) -> None:
    wizard = _wizard(window, ctx)
    wizard.not_ask_check.setChecked(True)
    wizard.close()
    assert ctx.app_settings.get(ONBOARDING_KEY, False) is True
    assert window._should_show_onboarding() is False


# ---- 第二步：登记监测根 ----


def test_向导里选的目录真的进了监测根(window, ctx, qapp, tmp_path, monkeypatch) -> None:
    """与 S7 同一条 `register_root`：光把按钮接上不写库不算接上。"""
    picked = tmp_path / "向导选的目录"
    picked.mkdir()
    monkeypatch.setattr(QtWidgets.QFileDialog, "getExistingDirectory",
                        staticmethod(lambda *a, **k: str(picked)))

    wizard = _wizard(window, ctx)
    before = ctx.roots.count()
    _to_step2(wizard)
    wizard.pick_btn.click()
    qapp.processEvents()

    assert ctx.roots.count() == before + 1, "点了「选择目录」，监测根一行都没多"
    added = ctx.roots.list()[-1]
    assert added.enabled == 1, f"向导里登记的根必须是启用态，实际 {added.enabled}"
    assert added.root_path.replace("\\", "/").endswith("向导选的目录"), added.root_path
    assert str(picked) in wizard.root_note.text(), "库里有了、屏幕上不吭声 = 用户不知道登记成功"


def test_取消选择不动监测根(window, ctx, qapp, monkeypatch) -> None:
    """选择器返回空串是正常路径，不许写一行空根。"""
    monkeypatch.setattr(QtWidgets.QFileDialog, "getExistingDirectory",
                        staticmethod(lambda *a, **k: ""))
    wizard = _wizard(window, ctx)
    before = ctx.roots.count()
    _to_step2(wizard)
    wizard.pick_btn.click()
    qapp.processEvents()

    assert ctx.roots.count() == before
    assert wizard.root_note.text() == STEP2_NOTE, "没选也要把回显改成就绪文案 = 骗用户已经登记了"


# ---- S7 重开 ----


def _page(window):
    window._select_by_page_id("monitor")
    return window._pages["monitor"]


def test_设置页按钮能把已看过的向导再拉起来(window, ctx, monkeypatch) -> None:
    """键已写 → 自动路径不再弹；S7 那颗按钮必须绕过判据（force）仍然弹窗。"""
    ctx.app_settings.set(ONBOARDING_KEY, True)
    opened: list[OnboardingWizard] = []
    monkeypatch.setattr(OnboardingWizard, "exec",
                        lambda self, *a: (opened.append(self), 1)[1])

    page = _page(window)
    assert hasattr(page, "replay_onboarding_btn"), "S7 上没有重开引导的入口"
    assert window._should_show_onboarding() is False
    window.maybe_show_onboarding()          # 非 force：已经看过，不该弹
    assert opened == []

    page.replay_onboarding_btn.click()

    assert len(opened) == 1, "点了「首次引导…」没弹窗（或被判据挡住了）"
    assert opened[0].steps.count() == 3
    assert window._onboarding is None, "exec 返回后要把引用清掉，否则关窗路径上留着一个已死对象"


def test_重开入口在设置页且全站只这一颗(window, ctx) -> None:
    """一个动作只有一个入口（AGENTS.md「每加一个新入口先全站搜」）：S7 之外不许再摆一颗。"""
    page = _page(window)
    assert page.replay_onboarding_btn.text() == "首次引导…"
    # 光把控件建出来不算上屏：没进布局就没有父控件，用户在 S7 上看不到它
    assert page.replay_onboarding_btn.isVisibleTo(page), "按钮建了没摆进 S7 = 死控件"
    texts = [b.text() for b in window.findChildren(QtWidgets.QPushButton)]
    assert texts.count("首次引导…") == 1, "同颗按钮出现在两屏 = 两个口径"


# ---- 关窗不被向导卡住（G20 --exit-after 首启那一场就靠这条路） ----


def test_外壳关窗先合上在场的向导(window, ctx) -> None:
    class _Recorder:
        def __init__(self) -> None:
            self.closed = 0

        def close(self) -> None:
            self.closed += 1

    fake = _Recorder()
    window._onboarding = fake
    window.close()
    assert fake.closed == 1, "关主窗不合模态向导 = 首启那一次根本退不出去"

    window._onboarding = None  # 夹具收尾还要 close()，别让第二次调用打到已回收的替身


def test_没有向导时关窗不报错(window, ctx) -> None:
    window.close()
    assert not window.isVisible()


@pytest.mark.parametrize("clicked", ["skip", "next"])
def test_两条收尾路径只写这一个键(window, ctx, clicked) -> None:
    """「完成」和「跳过」是两句话、一个状态：冒出第二个向导键就是两个口径。"""
    wizard = _wizard(window, ctx)
    if clicked == "next":
        _to_step2(wizard)
        wizard.next_btn.click()
        wizard.next_btn.click()
    else:
        wizard.skip_btn.click()
    keys = [k for k in ctx.app_settings.all_keys() if "wizard" in k]
    assert keys == [ONBOARDING_KEY], f"看过引导只能有一个存放键，实际 {keys}"


# ---- 组合根那一条 singleShot 不是死码（真进程） ----


def test_真进程首启弹出向导且关窗退得掉(tmp_path: Path) -> None:
    """干净数据根 = 首启，真起一个进程三件事一次验完：

    ① `app.run()` 里那条 `QTimer.singleShot` 真的把向导弹了出来（app.log 里有这一行）；
    ② `--exit-after` 收得住进程 —— 模态窗在场时靠外壳 `closeEvent` 先合上它，退出码必须 0；
    ③ ✕ 关掉且没勾「以后不再显示」→ 键不写，下次启动还弹（这条只在真进程里读得到，
       因为写不写是由 Qt 的关窗事件决定的）。
    """
    data_root = tmp_path / "appdata"
    proc = subprocess.run(
        [sys.executable, str(REPO_ROOT / "main.py"), "--data-dir", str(data_root),
         "--exit-after", "1.0"],
        cwd=str(REPO_ROOT), env={**os.environ, "QT_QPA_PLATFORM": "offscreen",
                                 "PYTHONIOENCODING": "utf-8"},
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
    assert proc.returncode == 0, f"首启进程退不出去：{proc.stdout}\n{proc.stderr}"

    text = (data_root / "logs" / "app.log").read_text(encoding="utf-8")
    assert "首启引导已弹出" in text, "组合根的触发线断了：向导一次都没弹过"

    ctx = bootstrap(data_root)
    try:
        assert ctx.app_settings.get(ONBOARDING_KEY, None) is None, \
            "没勾「以后不再显示」就被程序自己关掉也不该写键"
    finally:
        ctx.shutdown()
