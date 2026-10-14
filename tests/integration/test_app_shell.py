"""阶段 1 验收 1、2 + 阶段 2 第 10 项的界面接线：应用真的能起来、能关掉、能再起；
界面显示的是库里的真数据，包括扫描与索引任务的进度 / 错误 / 重试。

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

import pytest
from PySide6 import QtCore, QtWidgets

from pdfarchiver import __version__
from pdfarchiver.services.bootstrap import bootstrap
from pdfarchiver.ui.nav import NAV_ITEMS, PAGE_STATUS
from pdfarchiver.ui.pages.pending_page import PendingPage
from pdfarchiver.ui.pages.status_page import StatusPage

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def window(qapp, ctx):  # qapp 必须先于 ctx 之外存在：没有 QApplication 就构造 QWidget 是直接 abort 进程
    from pdfarchiver.ui.main_window import MainWindow

    w = MainWindow(ctx, cold_start_seconds=0.42)
    w.show()
    yield w
    w.close()
    ctx.shutdown()


def test_窗口真实显示并列出全部导航项(window) -> None:
    assert window.isVisible()
    assert window.centralWidget() is not None
    assert window.nav.count() == len(NAV_ITEMS)
    assert __version__ in window.windowTitle(), "标题里的版本必须来自 __version__，不许另写一份"


def test_首屏显示的是库里的真数字不是写死的文案(window, ctx) -> None:
    page = window.stack.currentWidget()
    assert isinstance(page, StatusPage)
    text = page.view.toPlainText()
    assert f"结构版本 schema_version = {ctx.schema_version}" in text
    assert "分类 = 14" in text, "默认模板 14 个分类要真的读出来"
    assert "文档主记录 = 0" in text, "空库就显示 0，不许显示成看起来有数据的样子"
    assert str(ctx.paths.root) in text
    assert "[默认]" in text and "integrity_check = ok" in text


def test_设置项三列口径在界面上打全(window, ctx) -> None:
    from pdfarchiver.config.settings import DEFAULTS

    text = window.stack.currentWidget().view.toPlainText()
    for key in DEFAULTS:
        assert f"{key}=" in text, f"启动时漏打印了设置项 {key}"


def test_点导航切页并把选择落库(window, ctx, qtbot) -> None:
    rect = window.nav.visualItemRect(window.nav.item(3))
    qtbot.mouseClick(window.nav.viewport(), QtCore.Qt.MouseButton.LeftButton, pos=rect.center())
    assert window.current_item().page_id == "reader"
    assert isinstance(window.stack.currentWidget(), PendingPage)
    assert ctx.app_settings.get("ui.last_nav_page") == "reader", "选择要立刻落库，不是等关窗"


def test_未实现页不放任何假控件(window) -> None:
    window.nav.setCurrentRow(4)
    page = window.stack.currentWidget()
    assert isinstance(page, PendingPage)
    assert page.findChildren(QtWidgets.QTableWidget) == []
    assert page.findChildren(QtWidgets.QProgressBar) == []
    assert page.findChildren(QtWidgets.QPushButton) == []
    assert "Q7" in page.findChild(QtWidgets.QLabel).text(), "要写清卡在哪个决定上"


def test_刷新按钮重查数据库(window, ctx, qtbot) -> None:
    page = window.stack.currentWidget()
    assert "标签 = 0" in page.view.toPlainText()
    ctx.catalog.add_tag("刷新后才出现的标签")
    qtbot.mouseClick(page.refresh, QtCore.Qt.MouseButton.LeftButton)
    assert "标签 = 1" in page.view.toPlainText(), "刷新必须是重新查库，不是重排一遍旧文本"


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

    first = bootstrap(data_root)
    w1 = MainWindow(first)
    w1.nav.setCurrentRow(6)  # monitor 是第 7 项
    assert first.session.last_nav_page() == "monitor"
    w1.close()
    first.shutdown()

    second = bootstrap(data_root)
    w2 = MainWindow(second)
    try:
        assert w2.current_item().page_id == "monitor"
        assert isinstance(w2.stack.currentWidget(), PendingPage)
    finally:
        w2.close()
        second.shutdown()


def test_导航注册表里至少有一屏是真的() -> None:
    """外壳不能只是个空壳：至少一页 implemented=True，否则"真实运行的 UI"不成立。"""
    assert any(i.implemented for i in NAV_ITEMS)
    assert PAGE_STATUS == NAV_ITEMS[0].page_id


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


# —— 阶段 2 第 10 项：进度 / 错误 / 重试真的显示出来 ————————————————————

def test_状态页显示扫描与索引任务的读数(window, ctx, root, make_pdf) -> None:
    """界面不许只显示"一切正常"：这一屏要把队列的真条数打出来。

    `后台未启动` 那半句同样是指令的一部分 —— 阶段 2 的装配刻意不起线程，
    所以界面必须说"没在跑"，不能让人以为任务卡住了。
    """
    r = root("界面读数")
    make_pdf("界面读数/己.pdf", page_lines=["己文档的正文内容字符"])
    ctx.scan.scan_root(r)
    page = window.stack.currentWidget()
    page.reload()
    text = page.view.toPlainText()
    assert "== 扫描与索引任务：进度 / 错误 / 重试 ==" in text
    assert "后台未启动" in text, "没起 worker 就要说没起，不许显示成正在跑"
    assert "任务条数  index：queued=1" in text, text
    assert "还欠一次索引 1" in text
    assert r.root_path in text


def test_刷新按钮同样重查任务读数(window, ctx, root, make_pdf, qtbot) -> None:
    """进度块缓存一下就等于在界面上展示一个已经过去的时刻 —— 刷新必须连它一起重查。"""
    r = root("刷新读数")
    make_pdf("刷新读数/辛.pdf", page_lines=["辛文档的正文内容字符"])
    ctx.scan.scan_root(r)
    page = window.stack.currentWidget()
    qtbot.mouseClick(page.refresh, QtCore.Qt.MouseButton.LeftButton)
    assert "queued=1" in page.view.toPlainText()

    make_pdf("刷新读数/丑.pdf", page_lines=["丑文档的正文内容字符"])
    ctx.scan.scan_root(r)
    qtbot.mouseClick(page.refresh, QtCore.Qt.MouseButton.LeftButton)
    assert "任务条数  index：queued=2" in page.view.toPlainText()


def test_巡检一轮就把脏根排成一条扫描任务(window, ctx, root) -> None:
    """`patrol_tick` 必须真的调 `patrol.poll()`：定时器空转的话，事件永远没人处理，
    而界面上的"上次扫描"会停在启动那一刻，看起来像还在跑。"""
    r = root("巡检")
    ctx.events.push_directory(r.root_key)
    assert ctx.jobs.count("queued") == 0

    window.patrol_tick()
    live = ctx.jobs.list()
    assert [j.kind for j in live] == ["scan"], live
    assert "巡检：" in window.statusBar().currentMessage()

    window.patrol_tick()
    assert ctx.jobs.count("queued") == 1, "脏根已经取走，第二轮不该再排一场重复的重扫"


def test_巡检定时器与巡检器同一个间隔口径(window, ctx) -> None:
    """间隔只许有一个出处。测试先把巡检器的间隔改成 7.5 秒再起定时器：
    界面里写死 5000（`scan_poll_seconds` 的默认值）当场露馅 —— 用默认值当默认值的断言等于没断言。"""
    ctx.patrol.poll_seconds = 7.5
    window.start_patrol()
    timer = window._patrol_timer
    assert timer is not None and timer.isActive()
    assert timer.interval() == 7500, f"定时器间隔没跟巡检器取同一个数：{timer.interval()}ms"
    timer.stop()


def test_巡检抛异常时定时器不许停并且状态栏留下原文(window, ctx, monkeypatch) -> None:
    """一轮失败如果把定时器打死，此后所有文件事件都没人管，而界面看起来一切正常 ——
    这正是 SPEC 4.3「故障要能被知道」禁止的那种静默。"""
    def boom():
        raise OSError("移动盘被拔掉了")

    window.start_patrol()
    monkeypatch.setattr(ctx.patrol, "poll", boom)
    window.patrol_tick()
    message = window.statusBar().currentMessage()
    assert "巡检出错：OSError: 移动盘被拔掉了" in message, message
    assert window._patrol_timer.isActive(), "异常之后定时器必须还活着"
