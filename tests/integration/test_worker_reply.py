"""后台线程回主线程那一发：接收方已经没了，就不许把异常抛在线程外（**ISSUES I131 追** / 轮五十八 ③ 甲 追补 甲）。

三处 worker（`library-search` / `status-reload` / `db-check-quick`）都以一行 `emit` 收尾。
「线程还没跑完，界面已经没了」这一刻 Qt 抛的是
`RuntimeError: Internal C++ object (LibraryPage) already deleted`，穿不出线程、由
`threading.excepthook` 记进 crash.log —— 用户那边对应的动作是**关窗退出时那一趟还在跑**，
日志里看着像崩了一次。三处都走 `ui/thread_reply.py::emit_if_alive` 这一份口径。

两条判据各自的坏法（都真注入过，见 `.probe_work/r59_badway.log`）：

- 下面那组按站点参数化的行为断言：把 `emit_if_alive` 里的 `try/except` 摘掉 → 三条全红，
  红的原文就是 `Internal C++ object (…) already deleted`。
- `tests/guards/test_worker_emit_sites.py`：在某个 worker 里改回裸 `signal.emit(...)` → 红，
  并且点名是哪个文件。

为什么这里必须自己把接收方**销毁**而不是只 `close()`：offscreen 实测（`.probe_work/r59_alive_probe.log`）
`close()` 只隐藏窗口，C++ 侧还活着，此时裸 `emit` 照样成功 —— 用 `close()` 写的断言摘掉守卫也绿，
等于摆设。真正弄没 C++ 侧的是 `deleteLater()` + `sendPostedEvents(DeferredDelete)`，
量出来 `shiboken6.isValid(page) = False`，裸 `emit` 当场抛那句原文。
"""
from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import pytest
from PySide6 import QtCore

from pdfarchiver.services.bootstrap import AppContext
from pdfarchiver.services.db_check import QUICK
from pdfarchiver.ui.pages.health_panel import HealthPanel
from pdfarchiver.ui.pages.library_page import LibraryPage
from pdfarchiver.ui.pages.status_page import StatusPage
from tests.conftest import settle as _settle  # noqa: TID251 - 与全站界面用例同一个「跑稳」口径


def _join(thread_name: str, timeout: float = 10.0) -> None:
    """等那一趟后台真的跑到最后一行。

    不等就直接断言 = 断言了个空（worker 还在 `gate.wait` 里，守卫那条路根本没走到）。
    """
    deadline = time.monotonic() + timeout
    while any(t.name == thread_name and t.is_alive() for t in threading.enumerate()):
        if time.monotonic() > deadline:
            raise AssertionError(f"{thread_name} 线程 {timeout:.0f}s 还没跑完")
        time.sleep(0.02)


@pytest.fixture
def escaped() -> list[BaseException]:
    """接住「穿出线程的异常」——产品里正是这条路把它记进 crash.log 的。"""
    seen: list[BaseException] = []

    def hook(args: threading.ExceptHookArgs) -> None:
        seen.append(args.exc_value)

    original = threading.excepthook
    threading.excepthook = hook
    try:
        yield seen
    finally:
        threading.excepthook = original


class _Gate:
    """把后台那一趟按住，直到界面已经没了才放行 —— 按站点不同，按住的是它各自的服务。"""

    def __init__(self) -> None:
        self.released = threading.Event()

    def hold(self, seconds: float = 5.0) -> None:
        if not self.released.wait(seconds):
            raise AssertionError("后台那趟没被放行（测试自己漏了 set()）")

    def release(self) -> None:
        self.released.set()


def _destroy(qapp, page) -> None:
    page.deleteLater()
    qapp.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)
    _settle(qapp)


def _blocked(gate: _Gate, original: Callable[..., Any]) -> Callable[..., Any]:
    """worker 线程里 → 按住直到放行再交空结果；主线程里 → 原样走、不碰闸门。

    「主线程里原样走」不是保险起见：`ctx.status.read` 在建窗与切屏路径上也被主线程调，
    把它一起按住就是测试自己锁死，5 秒后红的是「没被放行」而不是要验的那件事（实测踩过）。
    """
    def runner(*args: object, **kwargs: object) -> Any:
        if threading.current_thread() is threading.main_thread():
            return original(*args, **kwargs)
        gate.hold()
        return []
    return runner


@dataclass(frozen=True)
class _Site:
    """一站点的四件事：怎么建、怎么点、认哪一格「还在跑」、那条线程叫什么。"""

    id: str
    build: Callable[[AppContext], Any]
    start: Callable[[Any], None]
    busy: Callable[[Any], bool]
    thread: str


_SITES = [
    _Site("S1 检索 library-search", LibraryPage,
          lambda p: (p.search_input.setText("请示"), p.search_btn.click())[1],
          lambda p: p.searching, "library-search"),
    _Site("S7 状态重读 status-reload", StatusPage,
          lambda p: p.refresh.click(), lambda p: p.reloading, "status-reload"),
    _Site("S7 库体检 db-check-quick", HealthPanel,
          lambda p: p.quick_btn.click(), lambda p: p.running, f"db-check-{QUICK}"),
]


@pytest.mark.parametrize("site", _SITES, ids=[s.id for s in _SITES])
def test_界面没了之后回主线程那一发不许抛到线程外(qapp, ctx: AppContext, site: _Site,
                                                  escaped, monkeypatch) -> None:
    """起那一趟 → 把界面销毁 → 放行 → 等线程跑完：一行异常都不许漏出去。"""
    import shiboken6

    gate = _Gate()
    for owner, attr in ((ctx.search, "search_in"), (ctx.status, "read"),
                        (ctx.db_check, "run")):
        monkeypatch.setattr(owner, attr, _blocked(gate, getattr(owner, attr)))

    page = site.build(ctx)
    page.show()
    _settle(qapp)
    site.start(page)
    assert site.busy(page), f"前提：点完 {site.id} 那颗按钮，那一趟得真的在跑"
    _destroy(qapp, page)
    assert not shiboken6.isValid(page), "前提：接收方的 C++ 侧得真的没了，否则这条断言是摆设"
    gate.release()
    _join(site.thread)
    assert escaped == [], "回主线程那一发漏出了线程：" + " / ".join(
        f"{type(e).__name__}: {e}" for e in escaped)
