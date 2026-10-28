"""阶段 1 验收 1、2 的外壳部分：应用真起得来、关得掉、起得回；导航切得动且选择落库。

**2026-10-17 按 ISSUES I58 丙 拆开**（800 行那条线现在管所有 `.py`，口径见
**REPO-JOURNAL R-010**）：这一个文件原先 913 行、装着四组互不相干的守卫，名字早已不表达内容。
同轮拆出去的三组：
- `test_status_readout.py` —— 界面显示的是库里的真读数、"缺什么"只许来自两个列表、
  没接上执行器的按钮不许伪装成功；
- `test_patrol_tick.py` —— 巡检定时器干的三件事（排扫描任务 / 状态栏回显 / 逐屏进度刷新）；
- `test_ui_layout.py` —— 地板档几何与定宽列算术。
`window` 夹具四组都要用，搬进 `tests/conftest.py`（同一个理由：抄两份就会漂）。

这一组测试全部 offscreen 跑真 Qt 控件（p3 实测该模式下 QApplication 可用），
不是截图、不是静态稿：每个断言都靠 `qtbot` 点一下、切一下、关一下。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

from PySide6 import QtCore, QtWidgets

from pdfarchiver import __version__
from pdfarchiver.services.bootstrap import bootstrap
from pdfarchiver.ui.main_window import (
    DEFAULT_WINDOW_HEIGHT,
    DEFAULT_WINDOW_WIDTH,
    MIN_WINDOW_HEIGHT,
    MIN_WINDOW_WIDTH,
)
from pdfarchiver.ui.nav import NAV_ITEMS
from pdfarchiver.ui.pages.pending_page import PendingPage
from tests.conftest import settle as _settle

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_窗口真实显示并列出全部导航项(window) -> None:
    assert window.isVisible()
    assert window.centralWidget() is not None
    assert window.nav.count() == len(NAV_ITEMS)
    assert __version__ in window.windowTitle(), "标题里的版本必须来自 __version__，不许另写一份"


def _nav_row(page_id: str) -> int:
    """按 page_id 取导航行号。写死索引的话，注册表一增删这条就静默切到别的一屏。"""
    return [i.page_id for i in NAV_ITEMS].index(page_id)


def test_最小窗宽地板与设计档来自外壳(window) -> None:
    """**D-039** 的两条几何承诺，加上它顺手销掉的 **I52**：

    - 地板 1024×720 必须由窗口自己 `setMinimumSize` 兜住 —— 没有它，用户（或一屏的
      `minimumSizeHint`）能把窗口压到 900px 以下，侧栏被一路榨瘪到 56px；
    - 默认开在 1280×800 —— 线框按这一档画，S1 三栏 236+480+360=1076 只有这一档放得下。

    断言取 `minimumSize()`（显式设的地板）而不是 `minimumSizeHint()`（布局算出来的下限）：
    后者小于地板时 Qt 用前者，界面测试里量 hint 会量到一个跟"用户能压到哪"无关的数。
    """
    assert (window.minimumSize().width(), window.minimumSize().height()) == \
        (MIN_WINDOW_WIDTH, MIN_WINDOW_HEIGHT), \
        f"地板不是 D-039 的 {MIN_WINDOW_WIDTH}×{MIN_WINDOW_HEIGHT}：{window.minimumSize().width()}×{window.minimumSize().height()}"
    assert (window.width(), window.height()) == (DEFAULT_WINDOW_WIDTH, DEFAULT_WINDOW_HEIGHT), \
        f"默认开窗不是设计档 {DEFAULT_WINDOW_WIDTH}×{DEFAULT_WINDOW_HEIGHT}：{window.width()}×{window.height()}"
    assert window.size().width() >= window.minimumSize().width()


def test_点导航切页并把选择落库(window, ctx, qtbot) -> None:
    row = _nav_row("reader")
    assert NAV_ITEMS[row].implemented, "用例前提：这一屏是真的，切过去不该是说明页"
    rect = window.nav.visualItemRect(window.nav.item(row))
    qtbot.mouseClick(window.nav.viewport(), QtCore.Qt.MouseButton.LeftButton, pos=rect.center())
    assert window.current_item().page_id == "reader"
    assert not isinstance(window.stack.currentWidget(), PendingPage), "reader 已实现，不应是 PendingPage"
    assert ctx.app_settings.get("ui.last_nav_page") == "reader", "选择要立刻落库，不是等关窗"


def test_未实现页不放任何假控件(window, qapp) -> None:
    unimplemented = [i for i in NAV_ITEMS if not i.implemented]
    assert unimplemented, "用例前提：注册表里得有未实现项，否则这条测不到东西"
    for item in unimplemented:
        window._select_by_page_id(item.page_id)
        _settle(qapp)
        page = window.stack.currentWidget()
        assert isinstance(page, PendingPage), f"{item.page_id} 未实现却画了真页面"
        assert page.findChildren(QtWidgets.QTableWidget) == []
        assert page.findChildren(QtWidgets.QProgressBar) == []
        assert page.findChildren(QtWidgets.QPushButton) == []
        assert item.page_id in page.findChild(QtWidgets.QLabel).text() or \
            "未实现" in page.findChild(QtWidgets.QLabel).text(), \
            "要写清卡在哪个决定上或标注未实现"


def test_关窗真的关掉连接并留下对账行(qapp, ctx) -> None:
    from pdfarchiver.ui.main_window import MainWindow

    w = MainWindow(ctx)
    w.show()
    assert ctx.engine.thread_connection() is not None
    w.close()
    assert getattr(ctx.engine._local, "conn", None) is None
    assert ctx._closed is True
    lines = (ctx.paths.logs_dir / "state.log").read_text(encoding="utf-8").strip().splitlines()
    assert json.loads(lines[-1])["event"] == "shutdown"


def test_重启后回到上次停的那一屏(qapp, data_root) -> None:
    """验收 1 + 3：关的是进程，不是把状态留在内存里。"""
    from pdfarchiver.ui.main_window import MainWindow
    from pdfarchiver.ui.pages.categories_page import CategoriesPage

    first = bootstrap(data_root)
    w1 = MainWindow(first)
    w1.nav.setCurrentRow(_nav_row("categories"))
    assert first.session.last_nav_page() == "categories"
    w1.close()
    first.shutdown()

    second = bootstrap(data_root)
    w2 = MainWindow(second)
    try:
        assert w2.current_item().page_id == "categories"
        # categories 已实现，不再是 PendingPage
        assert isinstance(w2.stack.currentWidget(), CategoriesPage)
    finally:
        w2.close()
        second.shutdown()


def test_导航注册表里至少有一屏是真的() -> None:
    """外壳不能只是个空壳：至少一页 implemented=True，否则"真实运行的 UI"不成立。"""
    assert any(i.implemented for i in NAV_ITEMS)


def test_状态并入_S7_之后注册表少一项且没有第二处读数() -> None:
    """**D-040** 第三条后果的形状断言，钉住三种坏法：

    1. 注册表还是挂着独立的"运行状态"一项 —— 那就成了第 9 屏之外的第九个入口，
       用户会在两处看到两份读数；
    2. `monitor` 这一项丢了 —— 状态内容直接没了，而 nav 与页面构造各自不会报错；
    3. 把状态页复制一份进 S7 而不是嵌控件 —— 那份副本已经在历史上漂过一次
       （"OCR 后端已交付"那句只存在于原件里）。

    屏数 D-039 定过 **8**（S1–S8），轮三十六线框 §D 丁 确认后新增 S9 → **9 屏**；
    `search` 占位项并入 S1 但仍占一格（implemented=False），所以注册表是
    9 屏 + 1 占位 = **10 项**：状态那项搬进 S7 减一，ask 加一。
    这里断言的是入口数，不是屏数。
    """
    ids = [i.page_id for i in NAV_ITEMS]
    assert "status" not in ids, f"状态还挂在导航上，S7 里就同时有两处入口：{ids}"
    assert len(ids) == 10 and len(set(ids)) == 10, f"注册表应当是 10 项且 id 唯一：{ids}"
    assert "monitor" in ids, "搬进 S7 之后 monitor 这一项是状态读数的唯一宿主"
    assert "ask" in ids, "S9 库内问答在导航上（轮三十六线框 §D 丁）"
    assert NAV_ITEMS[0].page_id == "library", "首屏是文档库（S1），不是某个说明页"


def test_状态栏显示数据目录来源(window, ctx) -> None:
    assert str(ctx.paths.root) in window.statusBar().currentMessage()
    assert "结构版本" in window.statusBar().currentMessage()


def test_进程级冷启动实测符合G1约定(data_root) -> None:
    """真起一个进程跑 `python main.py`，量的是含解释器与依赖 import 的完整冷启动。

    数字由应用自己写进 state.log（`window.ready`），门禁读同一条口径，不外面掐表。
    """
    t0 = time.perf_counter()
    # 收发都显式 utf-8：本机控制台是 GBK，启动失败时子进程回显的是中文报错，解码炸了现场就没了
    proc = subprocess.run(
        [sys.executable, str(REPO_ROOT / "main.py"), "--data-dir", str(data_root),
         "--exit-after", "0.3"],
        cwd=str(REPO_ROOT), env={**os.environ, "QT_QPA_PLATFORM": "offscreen",
                                 "PYTHONIOENCODING": "utf-8"},
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
    wall = time.perf_counter() - t0
    assert proc.returncode == 0, f"启动失败：{proc.stdout}\n{proc.stderr}"

    events = [json.loads(ln) for ln in
              (data_root / "logs" / "state.log").read_text(encoding="utf-8").splitlines()]
    ready = [e for e in events if e["event"] == "window.ready"]
    assert ready, f"没有 window.ready 事件：{events}"
    cold = ready[-1]["cold_start_seconds"]
    assert cold <= 1.5, f"G1 [约定] ≤1.5s，实测 {cold}s"
    assert any(e["event"] == "shutdown" for e in events), "--exit-after 走的是关窗路径，必须有对账行"
    # 后台必须在这个真进程里真的起来 —— 否则"能开界面"掩盖着"没有任何 worker 在领任务"，
    # 阶段 2 的增量扫描与索引就只存在于测试里。
    started = [e for e in events if e["event"] == "background.started"]
    assert started, f"没有 background.started 事件：{[e['event'] for e in events]}"
    from pdfarchiver.config.settings import DEFAULTS

    assert started[-1]["threads"] == int(DEFAULTS["worker_threads"])
    assert started[-1]["watched"] == 0, "空库里没有监测根，起来的事件监听必须是 0 条"
    print(f"\nG1 实测：冷启动 {cold:.3f}s，进程总耗时 {wall:.3f}s")
    print(f"后台起停实测：{started[-1]}")
