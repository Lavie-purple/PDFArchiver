"""pytest 根配置：把 `src/` 挂进 sys.path，测试与 `python main.py` 用同一份源码。

不建 pyproject 的打包段：本项目按 p8 的结论用 PyInstaller 从源码直接冻结，不装包。
"""
from __future__ import annotations

import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
