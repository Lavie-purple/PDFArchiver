"""后台线程把结果交回主线程那一发的口径 —— 接收方可能已经先没了。

`threading.Thread` + `Signal` 是本产品回主线程的唯一形状，一共三处，每处的 worker 都以
一行 `emit` 收尾：

- `ui/pages/library_page.py` 的 `library-search`（轮五十八 ③ 甲，S1 检索）
- `ui/pages/status_page.py` 的 `status-reload`（**ISSUES I109** ①，全库 OCR 计数）
- `ui/pages/health_panel.py` 的 `db-check-<档>`（**ISSUES I110**，库体检）

问题出在"线程还没跑完，界面已经没了"这一刻：界面的 Python 包装对象一释放，它那棵 C++ 子树
（页面、表格、信号）跟着销毁，而 worker 手里还攥着引用。等它跑到最后一行去 `emit`，
抛的是 `RuntimeError: Internal C++ object (LibraryPage) already deleted`；异常穿不出线程，
由 `diagnostics/logs.py` 的 `threading.excepthook` 记进 crash.log。这一发是 2026-11-03 轮五十八
③ 甲 自己引出来的（检索搬进后台线程之后才有的这条路）。摘掉本文件的 `try/except` 之后三处各自红
在 `Internal C++ object (LibraryPage/StatusPage/HealthPanel) already deleted`，实录见
`.probe_work/r59_badway.log` 的 A1，判据在 `tests/integration/test_worker_reply.py`。
产品里对应的动作是**关窗退出时那一趟还没回来** —— 用户看到的是日志里一条看着像崩了的记录。

这里判 `RuntimeError` 就够，不需要摸 `shiboken6.isValid`：跨线程连接是**队列投递**，
`emit` 只把事件排进主线程的队列、不执行槽函数，所以槽里抛什么都到不了这一行；
这一行能抛出的 `RuntimeError` 只有"接收方的 C++ 侧已经没了"一种。

丢掉这一发不算"界面伪装成功"（**ISSUES I84** 那一类）：屏幕上已经没有这块界面了，
没有东西可骗。三处都从这里过，"怎么办"只许有一份。
"""
from __future__ import annotations

from PySide6 import QtCore


def emit_if_alive(signal: QtCore.SignalInstance, *args: object) -> bool:
    """界面还在就把结果交回主线程；那一页已经没了就安静地丢。

    返回是否投递成功 —— 现在三个调用点都不看它（无处可看），留着是为了下一处不用改写规则。
    """
    try:
        signal.emit(*args)
    except RuntimeError:      # Internal C++ object (...) already deleted
        return False
    return True
