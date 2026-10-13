"""测试公用夹具。

放在这里而不是各测试文件里，是因为三条规矩必须全站统一：
1. Qt 一律 offscreen —— 不许在用户桌面上弹出窗口（阶段 0 的 P3 探针同样这么做）。
2. 每个测试一个独立数据目录 —— 数据库、日志、备份都不许跨测试串味。
3. **绝不用 mock 数据库**（D-012）：所有库相关测试都跑真 sqlite3 文件，
   否则 WAL、唯一索引、触发器这些真实行为一个都验不到。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from pdfarchiver.services.bootstrap import AppContext, bootstrap  # noqa: E402


@pytest.fixture
def data_root(tmp_path: Path) -> Path:
    """一个干净的数据根目录（还不存在，由 bootstrap 自己建）。"""
    return tmp_path / "appdata"


@pytest.fixture
def ctx(data_root: Path):
    context = bootstrap(data_root)
    try:
        yield context
    finally:
        context.shutdown()


@pytest.fixture
def reopen(ctx: AppContext):
    """同一个数据目录再启动一次，返回新上下文。用于验"重启后东西还在"。"""
    def _reopen() -> AppContext:
        return bootstrap(ctx.paths.root)
    return _reopen


@pytest.fixture
def bare_ctx(ctx: AppContext) -> AppContext:
    """仓储层测试用：把默认分类模板和内部状态清空，断言才敢写绝对条数。

    清空只在测试的临时目录里发生，产品代码的"首启种一次"行为由
    `test_默认模板种过就不再长回来` 单独验。
    """
    conn = ctx.engine.thread_connection()
    conn.execute("DELETE FROM categories")
    conn.execute("DELETE FROM app_settings")
    conn.commit()
    return ctx
