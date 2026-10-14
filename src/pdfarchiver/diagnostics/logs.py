"""诊断层：app.log / crash.log / state.log（docs/ARCHITECTURE 一）。

阶段 1 就要立起来的规矩：**任何异常都必须留下能被远程读到的原文**。
所以这里做的不是"打日志"，是把三条出口一次封好：
  app.log    轮转的运行日志，所有模块共用一个 logger 名
  crash.log  未捕获异常 + 线程内异常，追加，含完整 traceback
  state.log  一行一条 JSON 的生命周期事件（启动/关闭/迁移/失败），用于事后对账
"""
from __future__ import annotations

import json
import logging
import re
import sys
import threading
import traceback
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOGGER_NAME = "pdfarchiver"
ENCODING = "utf-8"  # 日志文件一律 UTF-8：Windows 控制台默认 GBK，绝不能拿控制台编码当文件编码


STAMP_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z")  # 口径的唯一写法，测试按它断言


def log_stamp() -> str:
    """三个日志出口唯一的时间口径：UTC ISO 8601 带 `Z`。

    不给本地时区偏移：远程对账时对方要靠猜我这台机器在哪个时区才能把 app.log 的一行
    和 state.log 的一条 JSON 对上，这正是「错误必须能被远程诊断」不允许的。
    库里存的是 `now_ts()`（UTC unix 秒），这里是同一瞬间的可读写法，不是第二块表。
    """
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class _StampFormatter(logging.Formatter):
    """app.log 的行首时间戳走 `log_stamp()` 同一条路，不用 logging 默认的本地无偏移 asctime。"""

    def formatTime(self, record, datefmt=None):  # noqa: ANN001,N802 - 覆盖标准库签名与命名
        return (datetime.fromtimestamp(record.created, timezone.utc)
                .isoformat(timespec="milliseconds").replace("+00:00", "Z"))


def setup_logging(log_dir: Path, keep_files: int = 5, level: int = logging.INFO) -> logging.Logger:
    """幂等：同一个目录重复调用不叠 handler；换了目录就换 handler。

    换目录这条不是可有可无：数据根目录受 `--data-dir` / 环境变量控制，
    一次进程生命周期里重新解析过一次的，日志不能还往老目录里写。
    """
    log_dir.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(level)
    target = str((log_dir / "app.log").resolve())
    owned = [h for h in logger.handlers if getattr(h, "_pdfarchiver_owned", False)]
    for h in owned:
        if getattr(h, "baseFilename", None) == target:
            if h.backupCount != keep_files:  # 用户改了 log_keep_files，下一次调用就要生效
                h.backupCount = keep_files
            return logger
    for old in owned:
        logger.removeHandler(old)
        old.close()

    handler = RotatingFileHandler(
        log_dir / "app.log", maxBytes=2_000_000, backupCount=keep_files, encoding=ENCODING
    )
    handler.setFormatter(_StampFormatter(
        "%(asctime)s %(levelname)s [%(threadName)s] %(name)s: %(message)s"))
    handler._pdfarchiver_owned = True  # type: ignore[attr-defined]
    logger.addHandler(handler)
    return logger


def crash_log_path(log_dir: Path) -> Path:
    return log_dir / "crash.log"


def append_crash(text: str, log_dir: Path) -> Path:
    """崩了就要留痕。写失败也不许再抛 —— 抛出去会把崩溃现场本身弄丢。"""
    p = crash_log_path(log_dir)
    try:
        with p.open("a", encoding=ENCODING) as fh:
            fh.write(text)
            fh.flush()
    except OSError:
        pass
    return p


def install_crash_hooks(log_dir: Path) -> None:
    """主线程未捕获异常 + threading 内部异常都进 crash.log，并记进 app.log。"""

    def dump(kind: str, exc_text: str) -> None:
        append_crash(f"\n===== {log_stamp()} {kind} =====\n{exc_text}", log_dir)
        logging.getLogger(LOGGER_NAME).error("%s 已记录到 crash.log", kind, exc_info=None)

    def hook(etype, value, tb):  # noqa: ANN001 - 与 sys.excepthook 签名一致
        dump("未捕获异常", "".join(traceback.format_exception(etype, value, tb)))
        sys.__excepthook__(etype, value, tb)

    sys.excepthook = hook

    def thread_hook(args: threading.ExceptHookArgs) -> None:
        # `ExceptHookArgs` 是 structseq，字段是 exc_type/exc_value/exc_traceback —— 没有 `exc_info`。
        # 写成 args.exc_info 的后果不是"日志少一行"，而是钩子自己抛异常、原始现场被
        # "Exception in threading.excepthook" 顶掉，worker 线程里到底炸了什么永远看不到。
        dump(f"线程异常 {args.thread.name if args.thread else '?'}",
             "".join(traceback.format_exception(args.exc_type, args.exc_value, args.exc_traceback)))

    threading.excepthook = thread_hook


def state_event(log_dir: Path, event: str, **fields) -> None:
    """生命周期对账用的一行 JSON。写不上就只进 app.log，不影响主流程。"""
    rec = {"ts": log_stamp(), "event": event, **fields}
    try:
        with (log_dir / "state.log").open("a", encoding=ENCODING) as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except OSError as exc:
        logging.getLogger(LOGGER_NAME).warning("state.log 写入失败：%s", exc)
