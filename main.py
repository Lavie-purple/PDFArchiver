"""开发运行入口：`python main.py`。

`_T0` 在 import 应用包之前取值，这样 G1「冷启动」量的才是**进程起来到窗口就绪**，
而不是只量装配那一段 —— 依赖 import 的时间（PySide6 在 p3 实测是主要开销）必须算进去。
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

_T0 = time.perf_counter()

_SRC = Path(__file__).resolve().parent / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:  # 打包成 exe 后包已在包内，这里不该再加路径
    sys.path.insert(0, str(_SRC))

from pdfarchiver.app import run  # noqa: E402 - 必须先装好 sys.path

if __name__ == "__main__":
    raise SystemExit(run(process_started_at=_T0))
