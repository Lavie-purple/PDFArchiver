"""流式哈希 —— "内容变了没有"这个问题的唯一答案。

SPEC 阶段 2 安全要求第 3 条：**不能仅依赖路径来判断文件内容是否变化**。
路径、大小、mtime 三个里任何一个都能"看起来变了但其实没变"（复制一遍就换 mtime），
也能"看起来没变但其实变了"（人为回拨 mtime）。所以判定内容同一性只认 sha256。

分块读，块大小 4MB：p2 实测本机 sha256 中位 **240MB/s**，4MB 的一次调用已经把吞吐压满；
再大就只是在动内存（SPEC 五·8 不允许把整个 PDF 读进内存，120GB 的语料更不行）。
"""
from __future__ import annotations

import hashlib
import os
import time
from dataclasses import dataclass

CHUNK_BYTES = 4 * 1024 * 1024  # 4MB —— 见模块说明，改这里要重新量吞吐


@dataclass(frozen=True)
class Digest:
    sha256: str
    size_bytes: int
    seconds: float

    @property
    def mb_per_second(self) -> float:
        return (self.size_bytes / 1024 / 1024) / self.seconds if self.seconds > 0 else 0.0


def stream_sha256(path: str | os.PathLike[str], *, chunk_bytes: int = CHUNK_BYTES) -> Digest:
    """算文件内容哈希。文件打不开时把 OSError 原样抛出，由调用方记成错误条目。"""
    h = hashlib.sha256()
    size = 0
    started = time.monotonic()
    with open(path, "rb") as fh:
        while True:
            block = fh.read(chunk_bytes)
            if not block:
                break
            size += len(block)
            h.update(block)
    return Digest(sha256=h.hexdigest(), size_bytes=size, seconds=time.monotonic() - started)
