"""仓储层 —— 全项目只有这里的字符串会进 SQLite（docs/ARCHITECTURE 二）。

每个仓储持有一个 `Engine`，**每次调用取本线程的连接**：连接不属于仓储，属于线程
（p1/P3 实测：`check_same_thread` 下共享连接会直接抛，worker 必须自己开一条）。
"""
from __future__ import annotations
