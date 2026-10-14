"""watchdog 封装：**只产事件，不改库**（docs/ARCHITECTURE 一）。

P4 探针在真实 NTFS + 中文路径上量过这个东西的可靠性，结论决定了本文件的形态：

| 现象 | 实测 | 设计后果 |
| --- | --- | --- |
| 300 个文件一次性落盘 | 302 条 created，**0 丢失** | 事件够密，可以用它做"快速通道" |
| 被监听的目录自身被重命名 | **0 事件** | 事件流完全看不见根消失，必须有外部校验（D-009） |
| 跨目录移动 | created + deleted 两条，不是一条 moved | 不能把"移动"当成原子事件处理 |
| 事件顺序 | 可乱序、可重复 | 队列里做合并，最终一律以"再扫一次"的结果为准 |

所以这里的态度是：**事件是提示，不是事实**。
`WatchManager` 只负责把事件收进一个合并过的缓冲区，并标记"哪个根脏了"；
真正决定数据库怎么变的，是 `services/scan_service.py` 的重新扫描。
"""
from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Iterable

from watchdog.events import FileSystemEventHandler

from pdfarchiver.fs.identity import normalize_path
from pdfarchiver.fs.scanner import PDF_EXT

log = logging.getLogger("pdfarchiver.fs")

CREATED = "created"
DELETED = "deleted"
MODIFIED = "modified"
MOVED = "moved"
EVENT_KINDS = (CREATED, DELETED, MODIFIED, MOVED)

# watchdog 的事件类型名（`FileCreatedEvent.event_type` 的值就是 "created"）与上面四个口径
# 恰好同名，但把两个词表绑在字面相等上不安全 —— 上游改名我们就静默收不到事件。
# 这里显式列一遍；未列出的类型（`opened` / `closed` / `closed_no_write`）一律忽略。
_WATCHDOG_KINDS = {kind: kind for kind in EVENT_KINDS}


@dataclass(frozen=True)
class FsEvent:
    kind: str
    path: str            # 已 normalize_path()
    root_key: str
    dest_path: str | None = None
    at: float = 0.0


@dataclass
class EventBuffer:
    """线程安全的合并缓冲区。

    合并键是 `(root_key, path)`：同一个文件在 5 毫秒里被写 20 次，只需要重索引一次。
    `dirty_roots` 是给校验器看的 —— 根里出现过任何事件（含目录事件）就标脏，
    至于脏在哪个文件，交给重新扫描去发现。
    """

    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    _pending: dict[tuple[str, str], FsEvent] = field(default_factory=dict, repr=False)
    dirty_roots: set[str] = field(default_factory=set)
    total_seen: int = 0
    directory_events: int = 0

    def push(self, event: FsEvent) -> None:
        with self._lock:
            self.total_seen += 1
            self.dirty_roots.add(event.root_key)
            self._pending[(event.root_key, event.path)] = event

    def push_directory(self, root_key: str) -> None:
        """目录事件：不产生可定位的文件级动作，只让对应根变脏。"""
        with self._lock:
            self.total_seen += 1
            self.directory_events += 1
            self.dirty_roots.add(root_key)

    def drain(self) -> list[FsEvent]:
        with self._lock:
            out = list(self._pending.values())
            self._pending.clear()
            return out

    def snapshot(self) -> dict[str, int]:
        with self._lock:
            return {"pending": len(self._pending), "dirty_roots": len(self.dirty_roots),
                    "total_seen": self.total_seen, "directory_events": self.directory_events}

    def take_dirty_roots(self) -> set[str]:
        """取走并清空脏根集合。必须有"取走"这个动作：脏根是"该再校验一次"的凭据，
        读完不清就等于下一条事件永远只能触发同一批已经处理过的校验。"""
        with self._lock:
            out, self.dirty_roots = self.dirty_roots, set()
            return out

    def clear_root(self, root_key: str) -> None:
        with self._lock:
            self.dirty_roots.discard(root_key)
            for key in [k for k in self._pending if k[0] == root_key]:
                self._pending.pop(key, None)


class _BufferHandler(FileSystemEventHandler):
    """watchdog 的回调侧。

    **必须继承 `FileSystemEventHandler`**：observer 线程拿到事件后调的是
    `handler.dispatch(event)`（`watchdog/observers/api.py` 的 `dispatch_events`），不是我们的
    某个方法。少了这个基类，`handler` 上根本没有 `dispatch`，observer 线程在**第一条事件**上
    就 `AttributeError` 死掉 —— 而线程死了没有 anywhere 会再看它：文件监听静默失灵，
    界面上依旧显示"后台在跑"。（实测踩过：见 tests/e2e/test_stage2_acceptance.py 的监听用例，
    当时的现象是 crash.log 里一行 `_BufferHandler object has no attribute dispatch`。）

    异常同样绝不许抛出 `dispatch`：一个异常 = 整个 observer 线程 = 此后所有事件都没人收。
    所以每条事件单独包住，异常进日志后继续下一条。
    """

    def __init__(self, root_key: str, buffer: EventBuffer) -> None:
        super().__init__()
        self.root_key = root_key
        self.buffer = buffer

    def _emit(self, kind: str, event) -> None:  # noqa: ANN001 - watchdog FileSystemEvent
        try:
            if event.is_directory:
                self.buffer.push_directory(self.root_key)
                return
            path = str(event.src_path)
            if not path.lower().endswith("." + PDF_EXT):
                return
            dest = getattr(event, "dest_path", None)
            self.buffer.push(FsEvent(
                kind=kind, path=normalize_path(path), root_key=self.root_key,
                dest_path=normalize_path(str(dest)) if dest else None, at=time.time()))
        except Exception as exc:  # noqa: BLE001 - 抛出就等于打死 observer 线程，此后事件全丢
            log.exception("处理文件事件失败（kind=%s path=%s）：%s", kind, event.src_path, exc)

    def dispatch(self, event) -> None:  # noqa: ANN001 - watchdog FileSystemEvent
        """只把四种事件交给缓冲区，其余当场忽略。

        不沿用基类的 `getattr(self, "on_" + event.event_type)` 分派：watchdog 6 还会交来
        `opened` / `closed` / `closed_no_write`，未定义的方法名就是 AttributeError，
        而这个异常照样会带走整个 observer 线程。忽略多余事件是安全的 ——
        created/modified 已经覆盖"文件内容变了"，`services` 那边一律以重扫为准。
        """
        kind = _WATCHDOG_KINDS.get(event.event_type)
        if kind is not None:
            self._emit(kind, event)


class WatchManager:
    """每个监测根一个 observer 任务。start/stop 都幂等。

    注意 watchdog 的 `Observer` 在 Windows 上就是 `WindowsApiObserver`（P4 用的同一个类），
    不自己挑实现，免得上层行为跟着变。
    """

    def __init__(self, buffer: EventBuffer | None = None) -> None:
        from watchdog.observers import Observer

        self.buffer = buffer or EventBuffer()
        self._observer = Observer()
        self._handlers: dict[str, _BufferHandler] = {}
        self._watches: dict[str, object] = {}      # watchdog 的 ObservedWatch，取消监听要用它
        self._started = False

    @property
    def events(self) -> EventBuffer:
        return self.buffer

    def is_alive(self) -> bool:
        """observer 线程此刻还活着吗。没 `start()` 过是 False。

        必须有这个读数：observer 线程一旦被异常打死，事件流就**静默断掉**，
        而 `observed_roots` 照样列出所有根、任务队列照样在跑，界面上看不出任何区别
        （阶段 2 实测踩过：处理器缺 `dispatch` 时 crash.log 只留了一行 AttributeError，
        界面上一切正常）。状态页把它读成一行字，断流就不是没人知道的事。
        """
        return self._observer.is_alive()

    def watch(self, root_path: str, root_key: str) -> bool:
        """开始监听一个根。根目录不存在时返回 False（**不抛**）——
        P4 实测：根没了事件流是静默的，这里再抛一次只会把"根没了"这件事藏得更深。
        真正发现根消失的是 `services` 的周期校验。"""
        if root_key in self._handlers:
            return True
        if not os.path.isdir(root_path):
            log.warning("监测根不存在，不启用事件监听：%s", root_path)
            return False
        handler = _BufferHandler(root_key, self.buffer)
        try:
            self._watches[root_key] = self._observer.schedule(handler, root_path, recursive=True)
        except OSError as exc:
            log.error("启用事件监听失败 %s：%s", root_path, exc)
            return False
        self._handlers[root_key] = handler
        if self._started:
            log.info("已追加监听 %s（运行中）", root_path)
        return True

    def unwatch(self, root_key: str) -> bool:
        """停止监听一个根。必须真的向 watchdog 退订：只把 handler 从字典里摘掉的话，
        emitter 还在往那个已经没人认领的 handler 里灌事件，`buffer.total_seen` 会一直涨，
        而界面上这个根已经不见了 —— 又多一个说不出来的数。"""
        handler = self._handlers.pop(root_key, None)
        if handler is None:
            return False
        watch = self._watches.pop(root_key, None)
        if watch is not None:
            try:
                self._observer.unschedule(watch)   # type: ignore[arg-type]
            except (KeyError, OSError) as exc:
                log.warning("取消监听 %s 失败：%s: %s", root_key, type(exc).__name__, exc)
        self.buffer.clear_root(root_key)
        return True

    def start(self) -> None:
        if self._started:
            return
        self._observer.start()
        self._started = True
        log.info("事件监听已启动，覆盖 %d 个根", len(self._handlers))

    def stop(self) -> None:
        if not self._started:
            return
        self._observer.stop()
        self._observer.join(timeout=5.0)
        self._started = False
        log.info("事件监听已停止")

    @property
    def observed_roots(self) -> tuple[str, ...]:
        return tuple(sorted(self._handlers))

    def drain(self) -> Iterable[FsEvent]:
        return self.buffer.drain()
