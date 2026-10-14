"""watchdog 接线 —— 事件是提示，但"提示能到达缓冲区"这件事本身必须有测试。

这一层以前只有 `tests/probes/p4_watchdog.py` 覆盖过，而探针用的是**它自己写的**处理器类。
产品里的 `WatchManager` 另接了一个没继承 `FileSystemEventHandler` 的类，结果 observer 线程
在第一条事件上就 `AttributeError` 死掉：文件监听静默失灵，界面照样显示"后台在跑"。
探针绿了，产品是坏的 —— 所以这里验的是**产品自己那条接线**，用真 watchdog、真事件对象、真目录。

`tests/e2e/test_stage2_acceptance.py` 里还有一条端到端的监听用例，那条走完整链路（慢、
定位粗）；本文件这几条快而窄，坏了能直接指到 `fs/watcher.py`。
"""
from __future__ import annotations

import time
from pathlib import Path

import pytest
from watchdog.events import (DirCreatedEvent, FileClosedNoWriteEvent, FileCreatedEvent,
                            FileDeletedEvent, FileModifiedEvent, FileMovedEvent,
                            FileSystemEventHandler)

from pdfarchiver.fs.watcher import CREATED, DELETED, MODIFIED, MOVED, EventBuffer, WatchManager

ROOT_KEY = "root-key"
PDF = "C:/样本/人工智能产业年度报告.pdf"
OTHER = "C:/样本/说明.txt"


@pytest.fixture
def buffer() -> EventBuffer:
    return EventBuffer()


def _pending(buffer: EventBuffer):
    """取出缓冲区里唯一那条文件事件；空列表直接判失败，不让断言在 [] 上悄悄通过。"""
    events = buffer.drain()
    assert len(events) == 1, f"缓冲区里应该有且只有一条事件，实际 {events}"
    return events[0]


def _handler(buffer: EventBuffer) -> FileSystemEventHandler:
    from pdfarchiver.fs.watcher import _BufferHandler

    return _BufferHandler(ROOT_KEY, buffer)


# —— 回调契约 ——————————————————————————————————————————————

def test_处理器满足watchdog要求的回调形状(buffer) -> None:
    """`BaseObserver.dispatch_events` 调的是 `handler.dispatch(event)`，不是 `on_xxx`。

    这一句看着像废话，但缺了 `dispatch` 的上一版实现让整条监听静默失灵过，
    而且失效方式不是报错、是"什么都不发生"，所以把它写成一条独立断言。
    """
    handler = _handler(buffer)

    assert isinstance(handler, FileSystemEventHandler), "没继承基类就没有 dispatch，observer 线程会当场死掉"
    assert callable(getattr(handler, "dispatch", None))


def test_四种文件事件各自进缓冲区并带上根(buffer) -> None:
    handler = _handler(buffer)

    handler.dispatch(FileCreatedEvent(PDF))
    assert _pending(buffer).kind == CREATED
    handler.dispatch(FileModifiedEvent(PDF))
    assert _pending(buffer).kind == MODIFIED
    handler.dispatch(FileMovedEvent(PDF, "C:/样本/改名后的报告.pdf"))
    moved = _pending(buffer)
    assert (moved.kind, moved.dest_path) == (MOVED, "C:/样本/改名后的报告.pdf")
    handler.dispatch(FileDeletedEvent(PDF))
    assert _pending(buffer).kind == DELETED


def test_事件路径统一成内部口径并标脏对应的根(buffer) -> None:
    handler = _handler(buffer)
    handler.dispatch(FileCreatedEvent("C:\\样本\\人工智能产业年度报告.pdf"))

    event = _pending(buffer)
    assert event.path == PDF.replace("\\", "/"), "反斜杠留在路径里，后面所有前缀比对都会错"
    assert event.root_key == ROOT_KEY
    assert buffer.take_dirty_roots() == {ROOT_KEY}, "文件事件也必须把根标脏，周期校验才接得住"


def test_非PDF文件不产生事件但目录事件只标脏根(buffer) -> None:
    handler = _handler(buffer)
    handler.dispatch(FileCreatedEvent(OTHER))
    assert buffer.drain() == [], "非 PDF 不该产生文件级事件，否则每条都要去库里找一个不存在的主记录"

    handler.dispatch(DirCreatedEvent("C:/样本/子目录"))
    assert buffer.drain() == []
    assert buffer.take_dirty_roots() == {ROOT_KEY}, "目录事件必须让根变脏，重扫才能发现里面的变化"


def test_watchdog新增的事件类型不许把处理器打死(buffer) -> None:
    """基类的 `getattr(self, "on_" + event_type)` 对没实现过的类型直接 AttributeError，
    而这个异常会终止整个 observer 线程 —— 此后所有事件都收不到，且没有任何地方会再报。"""
    handler = _handler(buffer)

    handler.dispatch(FileClosedNoWriteEvent(PDF))     # watchdog 6 才有的类型
    assert buffer.drain() == []
    assert buffer.total_seen == 0                     # 忽略了就该什么都不记

    handler.dispatch(FileCreatedEvent(PDF))           # 忽略一条之后，正常事件仍然进得来
    assert _pending(buffer).kind == CREATED


def test_缓冲区写入失败时异常不逃出dispatch(buffer, monkeypatch) -> None:
    """`push` 抛出去 = observer 线程死 = 这个根以后所有事件都没人收。

    比"丢一条事件"严重得多：丢一条由周期校验兜底，线程死了连校验的触发信号都没了。
    """
    def explode(_event) -> None:
        raise OSError("缓冲区被塞满了")

    monkeypatch.setattr(buffer, "push", explode)
    _handler(buffer).dispatch(FileCreatedEvent(PDF))   # 不抛，就是这条断言

    assert buffer.total_seen == 0


# —— 真 observer 端到端 ————————————————————————————————————

def test_真监听能把新建的PDF交进缓冲区(tmp_path: Path) -> None:
    """起真 `Observer` 听真目录，落一个真 PDF，看它有没有变成缓冲区里的一条事件。

    这条是本文件存在的理由：前面几条就算全绿，`WatchManager.watch()` 接错了对象也一样收不到。
    断言的是"有一条指着这个文件的事件"，不锁死事件类型：Windows 的 emitter 会把
    "新建 + 写入"合并成一条 `modified`（实测两种都出现过），而 `scan_service` 对
    created/modified 走的是同一条对账路，锁类型等于验一个产品没承诺过的东西。
    """
    watched = tmp_path / "语料"
    watched.mkdir()
    manager = WatchManager()
    try:
        assert manager.watch(str(watched), ROOT_KEY)
        manager.start()
        (watched / "人工智能产业年度报告.pdf").write_bytes(b"%PDF-1.7\n")

        deadline = time.monotonic() + 20.0
        seen: list[tuple[str, str]] = []
        while time.monotonic() < deadline:
            batch = [(e.kind, e.path) for e in manager.events.drain()]
            seen += batch
            if any("人工智能产业年度报告" in path for _, path in seen):
                break
            time.sleep(0.05)
        assert any("人工智能产业年度报告" in path for _, path in seen), \
            f"20 秒内真监听没交来一条指着这个文件的事件；实际收到 {seen}"
        assert manager.events.total_seen > 0
        assert manager.is_alive(), "observer 线程已经死了，此后不会再有任何事件"
    finally:
        manager.stop()


def test_真监听能把删除与改名交进缓冲区(tmp_path: Path) -> None:
    watched = tmp_path / "语料"
    watched.mkdir()
    target = watched / "人工智能产业年度报告.pdf"
    target.write_bytes(b"%PDF-1.7\n")
    manager = WatchManager()
    try:
        manager.watch(str(watched), ROOT_KEY)
        manager.start()
        target.rename(watched / "改名后的报告.pdf")
        (watched / "改名后的报告.pdf").unlink()

        seen: set[str] = set()
        deadline = time.monotonic() + 20.0
        while time.monotonic() < deadline and not {MOVED, DELETED} <= seen:
            seen |= {e.kind for e in manager.events.drain()}
            time.sleep(0.05)
        assert {MOVED, DELETED} <= seen, f"改名/删除没被监听到，实际收到 {sorted(seen)}"
    finally:
        manager.stop()


# —— 监听线程的生死 ————————————————————————————————————————

def test_没起与起好的监听线程读出来不一样(tmp_path: Path) -> None:
    """`is_alive()` 是状态页唯一的依据：线程死了没有任何异常会留在表面上，
    根还列着、队列还跑着，只有"事件不再进来"这一件事坏了。"""
    watched = tmp_path / "语料"
    watched.mkdir()
    manager = WatchManager()

    assert manager.is_alive() is False, "还没 start 就说活着，状态页会显示一个不存在的监听"
    try:
        manager.watch(str(watched), ROOT_KEY)
        manager.start()
        assert manager.is_alive() is True
    finally:
        manager.stop()
    assert manager.is_alive() is False


def test_取消监听之后那个根不再交来事件(tmp_path: Path) -> None:
    """先证明"在听的时候收得到"，再证明"退订之后收不到" —— 只测后半句的话，
    一个从来没接通过的实现也能骗过它（这正是 `dispatch` 那次踩坑的形状）。"""
    watched = tmp_path / "语料"
    watched.mkdir()
    manager = WatchManager()
    try:
        manager.watch(str(watched), ROOT_KEY)
        manager.start()

        first = watched / "第一份报告.pdf"
        first.write_bytes(b"%PDF-1.7\n")
        assert _wait_for(manager, lambda e: "第一份报告" in e.path), "在听的时候都没收到，后半句就没法验"

        assert manager.unwatch(ROOT_KEY) is True
        assert manager.observed_roots == ()

        second = watched / "第二份报告.pdf"
        second.write_bytes(b"%PDF-1.7\n")
        time.sleep(1.0)
        assert not any("第二份报告" in e.path for e in manager.events.drain()), \
            "退订只删了字典里的 handler，emitter 还在往它身上灌事件"
    finally:
        manager.stop()


def _wait_for(manager: WatchManager, predicate, *, seconds: float = 20.0) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if any(predicate(e) for e in manager.events.drain()):
            return True
        time.sleep(0.05)
    return False
