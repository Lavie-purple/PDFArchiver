"""阶段 1 验收 1、2 + 阶段 2 第 10 项的界面接线：应用真的能起来、能关掉、能再起；
界面显示的是库里的真数据，包括扫描与索引任务的进度 / 错误 / 重试。

这一组测试全部 offscreen 跑真 Qt 控件（p3 实测该模式下 QApplication 可用），
不是截图、不是静态稿：每个断言都靠 `qtbot` 点一下、切一下、关一下。

**2026-10-17 起这一组里所有"状态读数"的断言都走 S7 上半区**（**D-040**）：
状态不再是注册表里独立的一项，内容一字未改，只是换了取它的路线 —— `_status_block()`。
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import pytest
from PySide6 import QtCore, QtWidgets

from pdfarchiver import __version__
from pdfarchiver.services.bootstrap import bootstrap
from pdfarchiver.ui.main_window import (
    DEFAULT_WINDOW_HEIGHT,
    DEFAULT_WINDOW_WIDTH,
    MIN_WINDOW_HEIGHT,
    MIN_WINDOW_WIDTH,
    NAV_WIDTH,
)
from pdfarchiver.ui.nav import NAV_ITEMS
from pdfarchiver.ui.pages.pending_page import PendingPage
from pdfarchiver.ui.pages.settings_page import SettingsPage
from pdfarchiver.ui.pages.status_page import StatusPage, UNWIRED_ACTIONS
from pdfarchiver.ui.table_layout import CELL_PADDING_WIDTH, ELIDABLE_COLUMNS
from tests.conftest import settle as _settle

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


def _nav_row(page_id: str) -> int:
    """按 page_id 取导航行号。写死索引的话，注册表一增删这条就静默切到别的一屏。"""
    return [i.page_id for i in NAV_ITEMS].index(page_id)


def _status_block(window, qapp) -> StatusPage:
    """切到 S7 并取出它上半区那张状态页（**D-040**：状态不再是独立的一屏）。

    必须真的切过去：`QStackedWidget` 里隐藏页不重排，`isVisible()` 恒为 False，
    下面的 `view.toPlainText()` 就会读到一个从没刷过的控件还照样绿。
    """
    window._select_by_page_id("monitor")
    _settle(qapp)
    page = window._pages["monitor"]
    assert isinstance(page, SettingsPage), "S7 下半区是设置、上半区是状态，两半在同一屏里"
    block = page.status_page
    assert isinstance(block, StatusPage) and block.isVisible(), \
        "这一组断言全部依赖状态那一块真的可见"
    return block


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


def test_首屏显示的是库里的真数字不是写死的文案(window, ctx, qapp) -> None:
    page = _status_block(window, qapp)
    text = page.view.toPlainText()
    assert f"结构版本 schema_version = {ctx.schema_version}" in text
    assert "分类 = 14" in text, "默认模板 14 个分类要真的读出来"
    assert "文档主记录 = 0" in text, "空库就显示 0，不许显示成看起来有数据的样子"
    assert str(ctx.paths.root) in text
    assert "[默认]" in text and "库文件 =" in text
    # 状态页**不跑任何同步库检查**（2026-10-16 判死：quick_check 在 6.1GB 真库上也要 452s+），
    # 所以这行也不该再出现——出现就说明有人把检查塞回了 UI，那会把大库状态页冻住。
    assert "integrity_check" not in text and "quick_check" not in text


def test_设置项三列口径在界面上打全(window, ctx, qapp) -> None:
    from pdfarchiver.config.settings import DEFAULTS

    text = _status_block(window, qapp).view.toPlainText()
    for key in DEFAULTS:
        assert f"{key}=" in text, f"启动时漏打印了设置项 {key}"


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


def test_刷新按钮重查数据库(window, ctx, qapp, qtbot) -> None:
    page = _status_block(window, qapp)
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

    屏数仍是 **8**（D-039 的 S1–S8），注册表 10→9 只是把状态那一项搬进 S7，
    不新增一屏，所以这里断言的是入口数，不是屏数。
    """
    ids = [i.page_id for i in NAV_ITEMS]
    assert "status" not in ids, f"状态还挂在导航上，S7 里就同时有两处入口：{ids}"
    assert len(ids) == 9 and len(set(ids)) == 9, f"注册表应当是 9 项且 id 唯一：{ids}"
    assert "monitor" in ids, "搬进 S7 之后 monitor 这一项是状态读数的唯一宿主"
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


# —— 阶段 2 第 10 项：进度 / 错误 / 重试真的显示出来 ————————————————————

def test_状态页显示扫描与索引任务的读数(window, ctx, qapp, root, make_pdf) -> None:
    """界面不许只显示"一切正常"：S7 上半区要把队列的真条数打出来。

    `后台未启动` 那半句同样是指令的一部分 —— 阶段 2 的装配刻意不起线程，
    所以界面必须说"没在跑"，不能让人以为任务卡住了。
    """
    r = root("界面读数")
    make_pdf("界面读数/己.pdf", page_lines=["己文档的正文内容字符"])
    ctx.scan.scan_root(r)
    page = _status_block(window, qapp)
    page.reload()
    text = page.view.toPlainText()
    assert "== 扫描与索引任务：进度 / 错误 / 重试 ==" in text
    assert "后台未启动" in text, "没起 worker 就要说没起，不许显示成正在跑"
    assert "任务条数  index：queued=1" in text, text
    assert "还欠一次索引 1" in text
    assert r.root_path in text


def test_刷新按钮同样重查任务读数(window, ctx, qapp, root, make_pdf, qtbot) -> None:
    """进度块缓存一下就等于在界面上展示一个已经过去的时刻 —— 刷新必须连它一起重查。"""
    r = root("刷新读数")
    make_pdf("刷新读数/辛.pdf", page_lines=["辛文档的正文内容字符"])
    ctx.scan.scan_root(r)
    page = _status_block(window, qapp)
    qtbot.mouseClick(page.refresh, QtCore.Qt.MouseButton.LeftButton)
    assert "queued=1" in page.view.toPlainText()

    make_pdf("刷新读数/丑.pdf", page_lines=["丑文档的正文内容字符"])
    ctx.scan.scan_root(r)
    qtbot.mouseClick(page.refresh, QtCore.Qt.MouseButton.LeftButton)
    assert "任务条数  index：queued=2" in page.view.toPlainText()


def test_状态读数只有这一处拼装(window, ctx, qapp) -> None:
    """D-040 的选择是**嵌控件**而不是抄一份渲染代码，所以全站只该有一个 `StatusPage`。

    一旦有人图省事在 `SettingsPage` 里另写一段 `parts += ...`，两份读数就会各自漂：
    上一轮已经真的漂过一次——"OCR 后端已交付但没有界面入口"那句只在原件里，
    副本里没有，而两边都长得像"状态页"，没人看得出哪份是权威的。
    """
    window._select_by_page_id("monitor")
    _settle(qapp)
    page = window._pages["monitor"]
    assert page.findChildren(StatusPage) == [page.status_page], \
        "S7 里出现了第二个状态读数控件，等于回到两份口径"
    text = page.status_page.view.toPlainText()
    assert text.count("== 扫描与索引任务：进度 / 错误 / 重试 ==") == 1, \
        "同一个标题出现两次 = 两处在拼同一份读数"


# 缺什么只许从两个列表里出来：nav 注册表（整屏没做）与 `status_page.UNWIRED_ACTIONS`
# （屏在、动作没接到后端）。散文式的「某某还没实现」会过期 —— 上一轮那句
# 「语义搜索（阶段 6）与文件归档、备份恢复的界面（阶段 4）后端和界面都还没实现」
# 就是三条一起漂（语义搜索早已接进 S1 的复选框，归档与备份两屏都建出来了）。
MISSING_CLAIM_RE = re.compile(r"还没实现|未实现|都没有|没做")
SECTION_RE = re.compile(r"^== .+ ==$")


def test_状态读数里的缺什么只许来自两个列表(window, ctx, qapp) -> None:
    window._select_by_page_id("monitor")
    _settle(qapp)
    text = window._pages["monitor"].status_page.view.toPlainText()

    sanctioned = ({f"  · {a}" for a in UNWIRED_ACTIONS}
                  | {f"  · {i.title} —— 未实现：{i.blocked_by}"
                     for i in NAV_ITEMS if not i.implemented})
    for line in text.splitlines():
        if not MISSING_CLAIM_RE.search(line):
            continue
        assert SECTION_RE.match(line) or line in sanctioned, (
            f"状态读数在用散文宣称「没实现」：{line!r}\n"
            "缺什么只许从 nav 注册表或 status_page.UNWIRED_ACTIONS 里出来 —— "
            "散文没有来源，代码一改它就悄悄变成假话")

    assert text.count("移动、改名或删除") == 1, (
        "磁盘口径出现了不止一份。SPEC 阶段 4 之后这一句是真会变的（归档一接线就得改），"
        "两处就有了第二个口径（AGENTS.md「禁止核心概念有多个口径」）")


# 这两个按钮的共同点：按下之后**本该动磁盘**。现在执行器没接上，所以它们必须只报
# 「什么都没变」；报「已提交 / 撤销成功」就是把没做的事说成做完了
# （AGENTS.md「禁止能力不足时伪装成功」）。
FAKE_OUTCOME_CLAIMS = ("已提交", "提交到归档队列", "已开始", "已创建", "将创建",
                       "已撤销", "撤销成功", "已移动", "已搬")


def test_没接上执行器的按钮不许伪装成功(window, ctx, qapp, monkeypatch, tmp_path) -> None:
    from PySide6.QtWidgets import QMessageBox

    from pdfarchiver.db.models import Document

    shown: list[str] = []
    monkeypatch.setattr(QMessageBox, "information",
                        staticmethod(lambda parent, title, text, *a, **k: shown.append(text)))
    monkeypatch.setattr(QMessageBox, "warning",
                        staticmethod(lambda parent, title, text, *a, **k: shown.append(text)))

    # 撤销要有批次可选，而这条批次必须在**取基线之前**建好 —— 它是对照的起点，
    # 不是被测动作的产物；建晚了就只能拿"+1"当预期，测的就不是"没动盘"了。
    ctx.operations.create_operation("archive")
    ops_before = len(ctx.operations.list_operations(limit=200))
    jobs_before = ctx.jobs.count()

    # S3 执行归档：灌一份文档、勾上、给目标根，然后真的点按钮
    path = str(tmp_path / "待归档.pdf")
    ctx.documents.upsert(Document(
        path=path, path_key=path.casefold(), name="待归档.pdf", size_bytes=1024,
        mtime_ns=1_760_000_000_000_000_000, sha256=f"{1:064x}",
        text_status="done", fts_status="done"))
    window._select_by_page_id("archive")
    _settle(qapp)
    page = window._pages["archive"]
    page._load_documents()
    page.doc_table.item(0, 0).setCheckState(QtCore.Qt.CheckState.Checked)
    page.target_root_input.setText(str(tmp_path / "归档库"))
    page.execute_btn.click()

    # S4 整批撤销：选中上面那条批次，点撤销
    window._select_by_page_id("operations")
    _settle(qapp)
    ops_page = window._pages["operations"]
    ops_page.reload()
    assert ops_page.op_table.rowCount() >= 1, "撤销那屏列不出批次，测试前提坏了"
    ops_page.op_table.setCurrentCell(0, 0)
    ops_page.undo_btn.click()

    assert len(shown) == 2, f"两个按钮各该报一次，实际报了 {len(shown)} 次：{shown}"
    for text in shown:
        assert not any(w in text for w in FAKE_OUTCOME_CLAIMS), f"文案谎报了后果：{text!r}"
        assert "磁盘" in text, f"没接上执行器的按钮必须明说磁盘上没动过：{text!r}"
    assert len(ctx.operations.list_operations(limit=200)) == ops_before, (
        "点过「执行归档」和「撤销」之后台账里多出了批次 —— 界面在背地里建批次了")
    assert ctx.jobs.count() == jobs_before, (
        "点过之后队列里冒出了任务，可文案说的是「还没接上」 —— 读数与行为对不上")


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


# —— S5 判重进度（线框 §S5「进度」那一行）———————————————————————————


def _show_dedup(window, qapp):
    """切到重复检测屏并让它真的可见。

    不切的话 `QStackedWidget` 里它是隐藏页，`isVisible()` 恒为 False，
    `patrol_tick` 那一支分支根本不会走 —— 上一轮就是被这个假绿骗过一次。
    """
    from pdfarchiver.ui.pages.dedup_page import DedupPage

    window._select_by_page_id("duplicates")
    _settle(qapp)
    page = window._pages["duplicates"]
    assert isinstance(page, DedupPage) and page.isVisible(), "这一组断言全部依赖这一屏真的可见"
    return page


def test_判重进度块显示的是那一行的真份数不是假数(window, ctx, qapp) -> None:
    """这两个控件原来是**建完就 setVisible(False)、全站零引用**的死控件。

    线框 §S5「进度」的硬条件：读数只认 `JobRepository.set_progress` 写进去的 `done`/`total`，
    而且**不许**出现"整库判重总进度百分比"这种合并假数 —— 所以这里量份数，不量百分号。
    """
    page = _show_dedup(window, qapp)
    assert not page.progress_bar.isVisible() and not page.lbl_progress.isVisible(), \
        "库里一条判重任务都没有，进度块就该整个收起，不许显示一个 0% 的空条"

    job = ctx.jobs.enqueue("dedup", doc_id=None, priority=5)
    ctx.jobs.claim(("dedup",))
    ctx.jobs.set_progress(job.id, 120, 4000)
    page.reload_progress()

    assert page.progress_bar.isVisible() and page.lbl_progress.isVisible()
    assert (page.progress_bar.minimum(), page.progress_bar.maximum(),
            page.progress_bar.value()) == (0, 4000, 120)
    text = page.lbl_progress.text()
    assert "判重进行中" in text and "第 120/4,000 份" in text, text
    assert "%" not in text, f"§S5 明令禁止合并百分比读数，界面上却印出来了：{text}"
    # 进度条自带的那行百分比是横着压在进度块（accent 填充）上的：浅色 4.19:1、暗色 2.98:1，
    # 两套主题都不过 AA。关掉文字、读数交给旁边的标签，是唯一两边都过线的形状。
    assert not page.progress_bar.isTextVisible(), "百分比文字压在 accent 进度块上，两主题都不过 AA"


def test_判重任务行没了以后进度块必须整个收起(window, ctx, qapp) -> None:
    """进度块只认 `latest_of_kind` 那一行，所以**那一行没了它就得跟着没**。

    这条不是理论上的洁癖：`JobRepository.clear_finished` 会删掉全部终结行（门禁 stage5 就在用）。
    删完之后如果界面还挂着"判重完成：第 X/Y 份"，那句话指的是一个库里已经不存在的任务 ——
    和 **ISSUES I31** 同族：读数说不清自己指的是什么，用户就当成还在跑。
    """
    page = _show_dedup(window, qapp)
    job = ctx.jobs.enqueue("dedup", doc_id=None, priority=5)
    ctx.jobs.claim(("dedup",))
    ctx.jobs.set_progress(job.id, 3, 3)
    ctx.jobs.succeed(job.id)
    page.reload_progress()
    assert page.progress_bar.isVisible() and page.lbl_progress.isVisible()

    assert ctx.jobs.clear_finished() == 1, "用例前提：终结行确实被清掉了"
    page.reload_progress()
    assert not page.progress_bar.isVisible() and not page.lbl_progress.isVisible(), \
        "任务行已经不在了，界面上还留着一条指向它的读数"


def test_判重跑着的时候进度跟着定时器走且发起按钮不许再亮(window, ctx, qapp, root, make_pdf) -> None:
    """接线断在中间有两种坏法，这一条同时抓住：定时器压根不刷这一屏（进度永远停在发起那一刻），
    以及刷了但「发起」又被①段那个计数重新点亮（按下去只弹一句「判重已在进行」）。"""
    r = root("判重进度")
    make_pdf("判重进度/寅.pdf", page_lines=["寅文档的正文内容字符"])
    ctx.scan.scan_root(r)

    page = _show_dedup(window, qapp)
    page.reload()
    assert page.btn_start.isEnabled(), "有 1 份还没算过哈希、又没在跑，按钮就该是亮的"

    job = ctx.jobs.enqueue("dedup", doc_id=None, priority=5)
    ctx.jobs.claim(("dedup",))
    window.patrol_tick()
    assert page.progress_bar.isVisible(), "patrol_tick 没把这一屏的进度刷进去，接线断了"
    assert "判重进行中" in page.lbl_progress.text(), page.lbl_progress.text()
    # 这一会儿 `set_total` 还没跑过（`total` 是 NULL）：区间必须是 0..0（Qt 的忙碌条 = "在干，
    # 总量还不知道"）。写成 0..100 + value 0 会画出一根空满量程条，看着像卡死在 0%。
    assert (page.progress_bar.minimum(), page.progress_bar.maximum()) == (0, 0), \
        f"还没数出待算份数却给了满量程空条：min={page.progress_bar.minimum()} max={page.progress_bar.maximum()}"
    assert "待算份数还没数出来" in page.lbl_progress.text(), page.lbl_progress.text()
    assert not page.btn_start.isEnabled(), "任务活着的时候按钮还亮着，点下去只会弹一句「已在进行」"

    ctx.jobs.set_progress(job.id, 1, 1)
    ctx.jobs.succeed(job.id)
    window.patrol_tick()
    assert "判重完成" in page.lbl_progress.text(), page.lbl_progress.text()
    assert (page.progress_bar.minimum(), page.progress_bar.value()) == (0, 1), \
        "`succeed` 会把 done 补齐成 total：跑完的那一次要显示成满格，不是停在 0"


def test_判重进度的状态词表对齐仓储的状态口径() -> None:
    """六个合法状态漏一个，那一行就显示成空串（ KeyError 之前先炸的是界面），
    而 `latest_of_kind` 会如实把那条捞回来 —— 所以只有拿仓储的 `STATES` 来对才能发现。"""
    from pdfarchiver.db.repositories.jobs import LIVE_STATES, STATES
    from pdfarchiver.ui.pages.dedup_page import _LIVE_STATES, _STATE_READING

    assert frozenset(_STATE_READING) == frozenset(STATES), (
        f"词表缺 {set(STATES) - set(_STATE_READING)}，多出 {set(_STATE_READING) - set(STATES)}")
    assert _LIVE_STATES == LIVE_STATES, "「已经排过了」的判定与仓储的未终结集合不是同一组状态"


# —— 布局守卫：任何一屏都不许把侧栏榨瘪 ——————————————————————————————
# 出处是界面审核发现 1（单行不折行的长文字）。可用宽度按 **D-039 的地板档 1024** 算，
# 不按 1280 的设计档算：地板是用户能压到的最窄处，在设计档上量等于把守卫放松 256px。
# 两个数都取自外壳本身（MIN_WINDOW_WIDTH / NAV_WIDTH），不在这里另立口径。

AVAILABLE_WIDTH = MIN_WINDOW_WIDTH - NAV_WIDTH - 1

# 环境里的临时路径太短，顶不出这个坏法；自己钉一条 247 字符的（现测 len(str(...)) = 247）。
# 尾段是一整串无空格 ASCII（Qt 把 CJK 逐字当可断点，全中文的长路径自己就能折断），
# 结尾留一个独特文件名，用来区分"中段省略"和"尾段截断"。
# 用户名位写成 local 而不是真用户名：这条只是形状夹具，规则见 docs/REPO-JOURNAL.md R-003
# （commit 前 `git grep` 本机用户名与私人目录名，命中即改；同类事故已出过一次，提交 0e808d0）。
LONG_DB_PATH = (Path("C:/Users/local/AppData/Local/PdfArchiver/profiles")
                / ("log" * 60) / "catalog-final.db")


@pytest.mark.parametrize("page_id", [i.page_id for i in NAV_ITEMS if i.implemented])
def test_每屏在地板宽度下都装得下且不吃侧栏(window, ctx, page_id, qapp, monkeypatch) -> None:
    """一条不可折行的长文字（典型是 Windows 绝对路径）会把该页 minimumSizeHint 顶到
    比窗口还宽，QSplitter 于是把侧栏压到它的 minimumSizeHint —— 实测 backup 页一条
    103 字符的路径让侧栏从 200px 掉到 **56px**，而且 splitter 尺寸是被撑大的那一份，
    切回别的屏也不恢复。D-040 只授权在宽度不足时牺牲命中面板，侧栏不在授权范围内。

    先把库路径钉成一条 243 字符的长 ASCII 路径再逐屏量：环境里的临时路径太短，
    不钉的话这个坏法能骗过断言（实测同一段代码，短路径下本页最低宽度 510px、
    长路径下 2935px，只有后者会红）。

    三条断言对应三种坏法，缺一漏一半：
    - 页面最低宽度 > 地板档侧栏之外的可用宽度 → 侧栏被榨瘪；
    - 窗口自身布局算出的最低宽度 > D-039 的地板 → `setMinimumSize` 是假的，
      用户连"把窗口缩到 1024"都做不到（Qt 实际用的最低宽是两者的较大值）；
    - 真把窗口压到地板再量侧栏 → 抓的是"声明了地板但页面仍然顶宽"这一类，
      前两条都只比 hint，不量 splitter 实际分到的宽度。
    """
    monkeypatch.setattr(ctx.engine, "path", LONG_DB_PATH)
    window._select_by_page_id(page_id)
    window._refresh_current()
    qapp.processEvents()

    page = window._pages[page_id]
    budget = AVAILABLE_WIDTH
    # QTabWidget 只把**当前**标签页的尺寸算进 minimumSizeHint；隐藏标签页里的长文字
    # 要到切过去的那一刻才顶宽（实测把恢复标签页的一条裸路径留在里面，这条断言照样绿）。
    # 所以逐屏量之前要把每屏的每个标签页都轮一遍。
    for tabs in page.findChildren(QtWidgets.QTabWidget):
        for i in range(tabs.count()):
            tabs.setCurrentIndex(i)
            qapp.processEvents()
            assert tabs.minimumSizeHint().width() <= budget, (
                f"{page_id} 第 {i + 1} 个标签页（{tabs.tabText(i)}）最低宽度 "
                f"{tabs.minimumSizeHint().width()}px，超过侧栏之外的可用 {budget}px")

    assert page.minimumSizeHint().width() <= budget, (
        f"{page_id} 的最低宽度 {page.minimumSizeHint().width()}px 超过地板档下侧栏之外"
        f"的可用 {budget}px —— 侧栏会被榨瘪（实测掉到 56px 且切屏不恢复）")
    assert window.minimumSizeHint().width() <= MIN_WINDOW_WIDTH, (
        f"{page_id} 让窗口自身布局的最低宽度到了 {window.minimumSizeHint().width()}px，"
        f"超过 D-039 的地板 {MIN_WINDOW_WIDTH}px —— setMinimumSize 挡不住它，"
        f"Qt 取两者较大值，用户压不到 1024")

    window.resize(MIN_WINDOW_WIDTH, MIN_WINDOW_HEIGHT)
    _settle(qapp)
    assert window.nav.width() >= NAV_WIDTH, (
        f"{page_id} 在地板档 {MIN_WINDOW_WIDTH}px 下把侧栏压到了 {window.nav.width()}px"
        f"（应当还是 {NAV_WIDTH}px）—— I52 的坏法重现")


def test_选中备份文件之后恢复标签页也不许顶宽(window, ctx, qapp, monkeypatch) -> None:
    """上一条逐标签页量的是**静态**内容；`QTabWidget` 只把当前标签页算进
    minimumSizeHint，所以"点了按钮之后才填进去的长路径"它看不见（实测把
    `lbl_selected` 换成裸路径，上一条照样绿）。这条走真的那条路：选一个深路径的备份。
    """
    from PySide6.QtWidgets import QFileDialog, QMessageBox

    # 成功/失败都会弹模态框，测试里不拦下来就直接卡住
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a, **k: None))
    monkeypatch.setattr(QMessageBox, "critical", staticmethod(lambda *a, **k: None))

    deep = str(LONG_DB_PATH)
    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: (deep, "")))
    window._select_by_page_id("backup")
    page = window._pages["backup"]
    tabs = page.findChildren(QtWidgets.QTabWidget)[0]
    tabs.setCurrentIndex(1)
    qapp.processEvents()

    page._select_backup()
    qapp.processEvents()

    budget = AVAILABLE_WIDTH
    assert tabs.minimumSizeHint().width() <= budget, (
        f"填进真实路径后，恢复标签页最低宽度 {tabs.minimumSizeHint().width()}px，"
        f"超过侧栏之外的可用 {budget}px")
    assert "…" in page.lbl_selected.text(), f"路径没中段省略：{page.lbl_selected.text()!r}"
    assert page.lbl_selected.toolTip() == deep, "完整路径要能在悬停里回读"

    # 同一标签页上还有第三条会填路径的标签（恢复结果），坏法一模一样，顺手一起钉住
    monkeypatch.setattr(QFileDialog, "getExistingDirectory",
                        staticmethod(lambda *a, **k: deep))
    monkeypatch.setattr(ctx.backup, "restore_to_new_dir", lambda *a, **k: Path(deep))
    page._restore_to_new_dir()
    qapp.processEvents()
    assert tabs.minimumSizeHint().width() <= budget, (
        f"填进恢复结果路径后，恢复标签页最低宽度 {tabs.minimumSizeHint().width()}px，"
        f"超过侧栏之外的可用 {budget}px")
    assert "…" in page.lbl_restore_result.text(), "恢复结果里的新库路径同样要中段省略"


def test_截掉的路径必须能在悬停里回读(window, ctx, qapp, monkeypatch) -> None:
    """上一条管"不许顶宽"，这一条管"顶不宽了也不能把信息弄丢"。

    中段省略是 S5 判重表已经定下的口径（表头直接写着"路径（悬停看全长）"）：
    盘符和文件名两端都要看得见，完整值靠 tooltip 回读。
    """
    monkeypatch.setattr(ctx.engine, "path", LONG_DB_PATH)
    window._select_by_page_id("backup")
    page = window._pages["backup"]
    page._reload_current_info()
    qapp.processEvents()

    assert "…" in page.lbl_current.text(), "够长却没省略 = 截断没生效（或干脆没截）"
    assert str(LONG_DB_PATH) in page.lbl_current.toolTip(), "截掉的完整路径必须能在 tooltip 里回读"
    assert page.lbl_current.text().startswith("当前库：C:"), "开头（盘符）要留着才能认出是哪台盘"
    assert "catalog-final.db" in page.lbl_current.text(), \
        "结尾（文件名）也要留着 —— 变成尾段截断就看不出是哪个库了"




# 用户真正要读、且**长度不固定**的那几列，在各页的表头文案。
# 判重表的「SHA256（前8位）」不在这里：它是定长 8 个十六进制字符（约 55px），
# 100px 的默认宽都截不断它，给它设 200px 底线只是把阈值调到一个坏法根本骗不过它的数字上。
# 与 `table_layout.ELIDABLE_COLUMNS` 的分工：本集合是"可以截断、但必须还能看出目录层次"
# 的那几条路径列；后者是它的超集（多「分类」「错误」），装得下/回读得上的守卫用后者 ——
# 两套列名不许各说各话，末尾单独一条断言钉住子集关系。
CONTENT_COLUMNS = {"文件名", "路径", "源路径", "目标路径", "路径（悬停看全长）"}
# 200px：13px 字体下约 15 个汉字，是一条绝对路径能不能看出目录层次的底线。
# 40px：证明没有任何一列被 Stretch 压成缝（实测压瘪后是 38px／25px，见下面两条测试）。
MIN_CONTENT_WIDTH = 200
MIN_ANY_WIDTH = 40


@pytest.mark.parametrize("page_id", [i.page_id for i in NAV_ITEMS if i.implemented])
def test_表格不许把内容列压成一条缝(window, ctx, page_id, qapp) -> None:
    """钉住两种坏法。

    ① 八张表原先都只写一句 `setStretchLastSection(True)`：除最后一列以外全留在 Qt 默认的
    100px，剩余宽度一律给最后一列 —— 实测文档库「文件名」100px 而「分类」225px，
    操作日志把 688px 给了「失败」这一列**计数**。
    ② 改成显式定宽后又踩到第二个坑：定宽列已经把视口吃掉时，Stretch 那一列被压成几十像素的
    缝（文档库「分类」实测 38px、归档「文件名」压到窗口最低时实测 25px），而且**永远是这一条缝** ——
    横向滚动条本身是好的（Qt 的滚动范围按"档"不按像素，maximum()==2 也能滚完整段超出量），
    滚过去看见的仍是个窄条。
    """
    window._select_by_page_id(page_id)
    _settle(qapp)
    for table in window._pages[page_id].findChildren(QtWidgets.QTableWidget):
        header = table.horizontalHeader()
        widths = [header.sectionSize(c) for c in range(table.columnCount())]
        for col, name in enumerate(
                [table.horizontalHeaderItem(c).text() if table.horizontalHeaderItem(c) else "?"
                 for c in range(table.columnCount())]):
            floor = MIN_CONTENT_WIDTH if name in CONTENT_COLUMNS else MIN_ANY_WIDTH
            assert widths[col] >= floor, (
                f"{page_id} 的「{name}」列只有 {widths[col]}px，低于底线 {floor}px"
                f"（该表列宽 {widths}，视口 {table.viewport().width()}px）")


def test_表格定宽列放不下时必须还能滚到(window, ctx, qapp) -> None:
    """全定宽这条修法的前提是"滚得过去"，所以把前提本身钉住，而不是只钉列宽。

    文档库中栏视口实测 463px（空库读数；灌进行之后是 425px，少掉的是 Qt 自己长出来的行号列，
    见 **ISSUES I54**），五列定宽合计 752px —— 装不下是设计内的（D-040：1024px 下
    宁可牺牲命中面板也不动侧栏）。装不下时剩下的列**必须仍然可达**：横向滚动条可用，
    且把滚动值拧到底之后最后一列会进视口。
    """
    window._select_by_page_id("library")
    _settle(qapp)
    table = window._pages["library"].doc_table
    last = table.columnCount() - 1
    bar = table.horizontalScrollBar()
    assert table.viewport().width() < sum(
        table.horizontalHeader().sectionSize(c) for c in range(table.columnCount())), (
        "前提没了：五列已经能全部装进视口，那这条测试该改成量别的")
    assert bar.maximum() >= 1 and bar.isVisible(), (
        f"列宽超出视口却没有可用的横向滚动条（maximum={bar.maximum()}，"
        f"可见={bar.isVisible()}）—— 超出部分等于被裁掉")
    bar.setValue(bar.maximum())
    _settle(qapp)
    assert table.columnViewportPosition(last) < table.viewport().width(), (
        "滚到底也到不了最后一列 —— 定宽列超出视口时被裁掉了，等于那列永远看不见")


def test_压到地板宽度时归档表仍保住文件名与路径(window, ctx, qapp) -> None:
    """吸收列放在哪一列，决定窗口压窄时**谁**被牺牲，所以这条单独钉住那一列。

    归档页的定宽三列（选择 56 + 文件名 280 + 路径 240）合计 576px。**D-039 立了 1024px 地板
    之后**，侧栏之外的可用宽度只剩 823px，这一档实测视口 805px（空库；有行时少掉行号列那 38px，
    见 **ISSUES I54**）—— 576px 装得下，剩余宽度由「分类」这条吸收列吃掉（实测 229px）。
    **地板之前**窗口能压到 356px、视口 281px，那时必然装不下，而被压瘪的正是内容列
    （那是 **ISSUES I52** 的坏法，现在压不到了）—— 所以这条守卫今天钉的是"地板真的挡住了它"。
    原先把吸收列放在「文件名」上，压窄时牺牲的恰好是用户唯一要读的那一列；现在放在「分类」上
    （左栏分类树里本来就有），文件名/路径按定宽保住。
    """
    window._select_by_page_id("archive")
    _settle(qapp)
    # 一级一级压到底，不能一次跳过去：实测从 1000 直接 resize 到 356 时 QHeaderView
    # **不重排 Stretch 列**，读数还留着 1000px 时的 375px —— 守卫会因此假绿
    # （注入坏法验证时被抓到一次）。步进才等效于用户拖窗口。
    for width in range(DEFAULT_WINDOW_WIDTH, MIN_WINDOW_WIDTH - 1, -50):
        window.resize(width, MIN_WINDOW_HEIGHT)
        _settle(qapp, rounds=4)
    window.resize(MIN_WINDOW_WIDTH, MIN_WINDOW_HEIGHT)
    _settle(qapp)
    assert window.width() == MIN_WINDOW_WIDTH, (
        f"窗口压不到 D-039 的地板：停在 {window.width()}px —— 地板被页面顶宽了")

    header = window._pages["archive"].doc_table.horizontalHeader()
    widths = {
        window._pages["archive"].doc_table.horizontalHeaderItem(c).text(): header.sectionSize(c)
        for c in range(window._pages["archive"].doc_table.columnCount())}
    assert widths["文件名"] >= MIN_CONTENT_WIDTH, (
        f"窗口压到地板 {MIN_WINDOW_WIDTH}px 时「文件名」只剩 {widths['文件名']}px，"
        f"说明吸收列又落回了内容列上：{widths}")
    assert widths["路径"] >= MIN_CONTENT_WIDTH, f"「路径」同样被压瘪：{widths}"


# ---------------------------------------------------------------------------
# 定宽列必须装得下它那一列**格式能产出的最宽读数**
# ---------------------------------------------------------------------------
# 上面三条量的是"底线"（内容列 ≥200px / 任何列 ≥40px），它们管的是列被压成缝，
# 管不到"列看着挺宽、值却带省略号"。实测漏网的就是这一类：I48 那轮反算的是**文本宽**
# （修改时间 110px、大小 41px）然后给了 +8，而 Qt 单元格的内边距实测 23px
# （`sizeHintForColumn − 最长文本 advance`，五张表五个列都得 23）——
# 于是「大小」显示成 `1…`、「修改时间」显示成 `2026-1…`、批次「状态」显示成 `parti…`，
# 三屏四列全都恰好差那一截。
#
# 宽度模型用字符类别而不是运行时字体：离屏平台上这里**一个 UI 字体都没有**
# （Microsoft YaHei UI / Microsoft YaHei / Segoe UI 全部缺席），`horizontalAdvance`
# 把数字位量成 13px，比真机宽近一倍 —— 直接拿它当"需要宽"会把阈值抬到一个
# 好版本也过不了、只有把列宽翻倍才能过的数字上。13px UI 字体的现实量级：
# ASCII ≈7px（`2026-10-15 12:34` 16 字符 = 112px，与 I48 实测的 110px 对得上），
# 汉字与全角标点 ≈13px（1 em，这条离屏也量得准）。
ASCII_CHAR_WIDTH = 7
WIDE_CHAR_WIDTH = 13


def _estimated_text_width(text: str) -> int:
    return sum(WIDE_CHAR_WIDTH if ord(ch) > 127 else ASCII_CHAR_WIDTH for ch in text)


def _need_for(column_name: str, cells: list[str]) -> int:
    """该列必须容下的宽度：列头与最坏读数取最宽，再加单元格内边距。"""
    return max([_estimated_text_width(column_name)]
               + [_estimated_text_width(t) for t in cells]) + CELL_PADDING_WIDTH


def _seed_worst_readings(window, ctx, page_id: str) -> None:
    """把每列**格式能产出的最宽读数**灌进去，别让守卫只看列头。

    空表量不到值 —— 上一轮就是这么假绿的：文档库和备份页在测试库里都是 0 行，
    「大小」「修改时间」窄到只显示一个 `1` 也没人报警。
    """
    from datetime import datetime, timezone

    from pdfarchiver.db.models import Document

    if page_id == "library":
        # 大小档位在 1024 进位，最宽读数因此是 `1023.9 MB`（9 字符）
        widest_mb = int(1023.9 * 1024 * 1024)
        stamp = datetime(2026, 10, 16, 16, 8, 30, tzinfo=timezone.utc).timestamp()
        for name in ("归档范围与保留期限的请示（复函稿）.pdf", "Introduction-to-Statistical-Learning.pdf"):
            path = f"D:\\用户资料\\2026 年度合同与结算凭证归档\\{name}"
            ctx.documents.upsert(Document(
                path=path, path_key=path.casefold(), name=name,
                size_bytes=widest_mb, mtime_ns=int(stamp * 1_000_000_000),
                sha256=f"{hash(name):064x}", text_status="done", fts_status="done"))
    elif page_id == "operations":
        op = ctx.operations.create_operation("archive")
        ctx.operations.add_item(op.id, None, "move", "D:\\a.pdf", "D:\\b.pdf")
        ctx.operations.finish_operation(op.id, status="partially_done")
    elif page_id == "backup":
        ctx.backup.create_backup()


@pytest.mark.parametrize("page_id", [i.page_id for i in NAV_ITEMS if i.implemented])
def test_定宽列必须装得下最宽读数(window, ctx, page_id, qapp) -> None:
    """两条承诺按列分工：**不许截断的列**必须装得下，**允许截断的列**必须能悬停回读。

    判重表整体落在守卫外面：它四列是 `ResizeToContents`（不是 Interactive），
    列宽由当前这批数据决定 —— 那是 **ISSUES I48** 里写明"量了故意没改"的一条豁免，
    不是漏网。
    """
    _seed_worst_readings(window, ctx, page_id)
    window._select_by_page_id(page_id)
    _settle(qapp)

    for table in window._pages[page_id].findChildren(QtWidgets.QTableWidget):
        header = table.horizontalHeader()
        for col in range(table.columnCount()):
            head_item = table.horizontalHeaderItem(col)
            name = head_item.text() if head_item else "?"
            if header.sectionResizeMode(col) != QtWidgets.QHeaderView.ResizeMode.Interactive:
                continue                      # Stretch / ResizeToContents 由另两条守卫管
            cells = [table.item(r, col).text() for r in range(table.rowCount())
                     if table.item(r, col) is not None and table.item(r, col).text()]
            actual = header.sectionSize(col)
            if name in ELIDABLE_COLUMNS:
                # 内容天生无上限（绝对路径 / 用户自定义分类名 / 第三方报错原文），
                # 所以不承诺装得下，改承诺"每一格都能悬停读回全文"。
                for r, text in enumerate(cells):
                    assert table.item(r, col).toolTip() == text, (
                        f"{page_id} 的「{name}」列第 {r} 行截断了却没有 tooltip 回读全文："
                        f"{text[:40]!r}")
                continue
            need = _need_for(name, cells)
            assert actual >= need, (
                f"{page_id} 的「{name}」列给 {actual}px，最宽读数要 {need}px"
                f"（最长值 {max(cells, key=_estimated_text_width)[:24]!r} + 内边距 "
                f"{CELL_PADDING_WIDTH}px）—— 该列会显示成省略号")


def test_内容列集合必须还是可截断列集合的子集() -> None:
    """两套列名各说各话，早晚会有一列"既没人承诺装得下、也没人承诺能回读"。"""
    assert CONTENT_COLUMNS <= ELIDABLE_COLUMNS, (
        f"只在 CONTENT_COLUMNS 里的列：{sorted(CONTENT_COLUMNS - ELIDABLE_COLUMNS)}")
