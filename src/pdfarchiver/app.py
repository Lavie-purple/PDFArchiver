"""组合根：建容器、接线、启动/退出。不含业务规则（docs/ARCHITECTURE 一）。

失败路径是这一层唯一有"逻辑"的地方，因为装配本身失败时界面还不存在：
必须把原文写进 crash.log 并以非 0 退出码结束，而不是弹一句"启动失败"就把堆栈丢掉。
"""
from __future__ import annotations

import argparse
import ctypes
import logging
import os
import sys
import time
import traceback
from pathlib import Path

from PySide6 import QtCore, QtGui, QtWidgets

from pdfarchiver import APP_NAME, __version__
from pdfarchiver.config.paths import AppPaths
from pdfarchiver.config.settings import SettingsError
from pdfarchiver.db.engine import DatabaseError
from pdfarchiver.diagnostics.logs import append_crash, state_event
from pdfarchiver.services.bootstrap import AppContext, bootstrap
from pdfarchiver.ui.main_window import MainWindow

log = logging.getLogger("pdfarchiver.app")

EXIT_OK = 0
EXIT_BOOTSTRAP_FAILED = 2


def _apply_app_identity(app: QtWidgets.QApplication) -> None:
    """窗口/任务栏的应用身份（轮四十用户勾选 ③）：图标 + Windows 任务栏分组 ID。

    AppUserModelID 必须在**第一个窗口显示之前**设置，否则 Windows 把进程归进
    默认分组，任务栏悬停与固定显示的是 python/exe 的裸名；设置失败（非 Windows
    或 API 不可用）不致命，只少分组。图标取包内 assets/app.ico（多尺寸，
    冻结产物由 spec 的 datas 一起收进去），失败则留系统默认 —— 身份缺失不挡启动。
    """
    app.setWindowIcon(QtGui.QIcon(str(Path(__file__).parent / "assets" / "app.ico")))
    if sys.platform != "win32":
        return
    try:
        bool(ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            f"PdfArchiver.{APP_NAME}"))
    except OSError:
        log.warning("AppUserModelID 设置失败，任务栏将不按应用分组")


def _parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog=APP_NAME, description=f"本地 PDF 归档与检索工具 {__version__}")
    ap.add_argument("--data-dir", default=None,
                    help="覆盖数据根目录；不传则按环境变量 PDFARCHIVER_DATA_DIR，再否则系统本地应用数据目录")
    ap.add_argument("--exit-after", type=float, default=0.0, metavar="秒",
                    help="窗口就绪后自动退出。启动门禁和打包后的冒烟验证要用它证明"
                         "「真的能起来、也真能关掉」；0 = 不自动退出")
    ap.add_argument("--version", action="version", version=f"{APP_NAME} {__version__}")
    return ap


def run(argv: list[str] | None = None, process_started_at: float | None = None) -> int:
    t_entry = time.perf_counter()
    args = _parser().parse_args(sys.argv[1:] if argv is None else argv)
    paths = AppPaths.resolve(args.data_dir)

    # ISSUES I18：QApplication 必须在 bootstrap 之前创建，否则装配失败时无法弹 GUI 错误对话框。
    # 复用已存在的单例（`instance() or ...`）：同一进程里第二次进 run() 时（测试会这样），
    # 直接 new 一个会抛 "destroy the QApplication"，产品单次启动则永远走新建那一支。
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv[:1])
    app.setApplicationName(APP_NAME)
    _apply_app_identity(app)

    try:
        ctx = bootstrap(args.data_dir)
    except (SettingsError, DatabaseError, OSError) as exc:
        dest = append_crash(f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}", paths.logs_dir)
        msg = f"启动失败：{exc}\n完整堆栈已写入 {dest}"
        print(msg, file=sys.stderr)
        log.error("启动失败：%s（堆栈已写入 %s）", exc, dest)
        _show_startup_error(f"启动失败：{exc}", dest)
        return EXIT_BOOTSTRAP_FAILED

    t_assembled = time.perf_counter()
    window = MainWindow(ctx)
    window.show()
    t_shown = time.perf_counter()
    if process_started_at is not None:
        cold = t_shown - process_started_at
        window.set_cold_start_seconds(cold)
        # G1 的数由应用自己报：门禁脚本从 state.log 读这一条，不靠外部掐表（外部量不到窗口就绪的时刻）
        log.info("冷启动 %.3fs（进程起来→窗口就绪）门禁 G1 [约定] ≤1.5s", cold)
        # 分段耗时（轮十八 ⑦，欠账 I102）：超线那次要能看出时间花在哪段 —— 解释器与依赖 import /
        # 装配 / 建窗。同一个出口：读法就是 state.log 里这一条事件的 phases 字段。
        state_event(ctx.paths.logs_dir, "window.ready", cold_start_seconds=round(cold, 3),
                    phases={"import_to_run_s": round(t_entry - process_started_at, 3),
                            "assemble_s": round(t_assembled - t_entry, 3),
                            "window_s": round(t_shown - t_assembled, 3)})
    if args.exit_after > 0:
        QtCore.QTimer.singleShot(int(args.exit_after * 1000), window.close)
    if not _start_background(ctx, window):
        ctx.shutdown()
        return EXIT_BOOTSTRAP_FAILED
    code = app.exec()
    ctx.shutdown()  # 幂等：closeEvent 里已经调过一次，这里兜住不用窗口关闭路径退出的情况
    return code


def _show_startup_error(message: str, crash_log: Path) -> None:
    """ISSUES I18：装配失败时弹 GUI 错误对话框，让双击启动的用户能看到错误而不是"闪退"。

    offscreen 平台（测试环境）跳过对话框，避免阻塞自动化。
    日志落点只能用调用方传进来的**真路径**：在这里写一个"典型路径"字面量，
    就是在教用户去翻一个可能根本不存在的位置（架构守卫禁止 `src/` 里出现盘符路径）。
    """
    if os.environ.get("QT_QPA_PLATFORM") == "offscreen":
        return  # 测试环境不弹窗

    from PySide6 import QtWidgets
    box = QtWidgets.QMessageBox()
    box.setIcon(QtWidgets.QMessageBox.Icon.Critical)
    box.setWindowTitle("启动失败")
    box.setText(message)
    box.setDetailedText(
        f"完整错误堆栈在这一份日志里：\n{crash_log}\n\n"
        f"同一目录（{crash_log.parent}）下还有两份：\n"
        "  app.log   —— 全部运行日志\n"
        "  state.log —— 生命周期事件，一行一条 JSON")
    box.exec()


def _start_background(ctx: AppContext, window: MainWindow) -> bool:
    """起 worker 线程 + 文件监听 + 巡检定时器。

    放在窗口起来之后，是为了让 G1 的冷启动只量"进程起来到窗口就绪"，不把开线程的耗时算进
    一个和界面无关的指标里。后台起不来就是启动失败：留下原文、以非 0 退出，
    不许带着一个没人领任务的队列继续跑 —— 那正是"界面看着正常、其实什么都没发生"。
    """
    try:
        queue = ctx.start_background()
    except (DatabaseError, OSError) as exc:
        dest = append_crash(f"后台启动失败 {type(exc).__name__}: {exc}\n{traceback.format_exc()}",
                            ctx.paths.logs_dir)
        msg = f"后台启动失败：{exc}\n完整堆栈已写入 {dest}"
        print(msg, file=sys.stderr)
        log.error("后台启动失败：%s（堆栈已写入 %s）", exc, dest)
        _show_startup_error(f"后台启动失败：{exc}", dest)
        return False
    window.start_patrol()
    log.info("后台与巡检已就绪：worker %d，回收中断后队列状态 %s",
             queue.thread_count, ctx.jobs.counts_by_state())
    return True


if __name__ == "__main__":  # 允许 `python -m pdfarchiver.app` 直接跑
    raise SystemExit(run())
