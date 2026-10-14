"""组合根：建容器、接线、启动/退出。不含业务规则（docs/ARCHITECTURE 一）。

失败路径是这一层唯一有"逻辑"的地方，因为装配本身失败时界面还不存在：
必须把原文写进 crash.log 并以非 0 退出码结束，而不是弹一句"启动失败"就把堆栈丢掉。
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
import traceback

from PySide6 import QtCore, QtWidgets

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
    args = _parser().parse_args(sys.argv[1:] if argv is None else argv)
    paths = AppPaths.resolve(args.data_dir)
    try:
        ctx = bootstrap(args.data_dir)
    except (SettingsError, DatabaseError, OSError) as exc:
        dest = append_crash(f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}", paths.logs_dir)
        print(f"启动失败：{exc}\n完整堆栈已写入 {dest}", file=sys.stderr)
        return EXIT_BOOTSTRAP_FAILED

    app = QtWidgets.QApplication(sys.argv[:1])
    app.setApplicationName(APP_NAME)
    window = MainWindow(ctx)
    window.show()
    if process_started_at is not None:
        cold = time.perf_counter() - process_started_at
        window.set_cold_start_seconds(cold)
        # G1 的数由应用自己报：门禁脚本从 state.log 读这一条，不靠外部掐表（外部量不到窗口就绪的时刻）
        log.info("冷启动 %.3fs（进程起来→窗口就绪）门禁 G1 [约定] ≤1.5s", cold)
        state_event(ctx.paths.logs_dir, "window.ready", cold_start_seconds=round(cold, 3))
    if args.exit_after > 0:
        QtCore.QTimer.singleShot(int(args.exit_after * 1000), window.close)
    if not _start_background(ctx, window):
        ctx.shutdown()
        return EXIT_BOOTSTRAP_FAILED
    code = app.exec()
    ctx.shutdown()  # 幂等：closeEvent 里已经调过一次，这里兜住不用窗口关闭路径退出的情况
    return code


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
        print(f"后台启动失败：{exc}\n完整堆栈已写入 {dest}", file=sys.stderr)
        return False
    window.start_patrol()
    log.info("后台与巡检已就绪：worker %d，回收中断后队列状态 %s",
             queue.thread_count, ctx.jobs.counts_by_state())
    return True


if __name__ == "__main__":  # 允许 `python -m pdfarchiver.app` 直接跑
    raise SystemExit(run())
