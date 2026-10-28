"""导航注册表 —— 阶段 1 外壳唯一的"界面知识"。

**这里刻意不做任何布局决策。** SPEC 的功能项都要有一行，是因为没有这一行的话，
"应用能启动但看不见还剩什么没做"就变成要靠文档脑补；有这一行，界面就是一个诚实的进度表。
屏数与职责：**D-039** 定的是 8 屏 S1–S8；轮三十七（2026-10-28，线框 §0 + §E 第 7 问 甲）
新增 **S9 库内问答**，屏数升为 **9**，清单见 `docs/UI-SCREENS.md` 第六节。
仍按 `implemented` 标志诚实标注每屏状态：**`implemented=False` 的项一律只给一张"未实现"说明页，
不画任何控件布局**（现仅 `search` 一项为 False，且它不是缺失 —— 检索功能已并入
`library`（S1），见该项 `blocked_by` 说明）。

条目仍按 **SPEC 条款号**命名，不用 S1/S9 编号 —— S 编号是**屏**的编号，一个屏可能挂多个导航入口
（如 S1 同时是"文档库"和"检索"），两套编号混在这里就会变成第二个口径。
S9 不是 SPEC 条款，是轮三十六用户勾选的四项功能之一，它的 `spec` 记线框出处。

**这里没有"运行状态与自检"这一项**（**D-040** 第三条后果）：那一屏并入 **S7 的上半区**，
由 `monitor` 这一项承载，内容一字未改。所以注册表是 **10 项**（D-039 的 8 屏 + S9 的 1 屏，
`search` 是并入 S1 的占位项）—— 屏清单唯一口径在 `docs/UI-SCREENS.md`。
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class NavItem:
    page_id: str
    title: str
    spec: str  # 对应的 SPEC 条款，用于说明"这一屏为什么在清单上"
    implemented: bool
    blocked_by: str = ""  # 未实现时，写清卡在哪个决定上


NAV_ITEMS: list[NavItem] = [
    NavItem("library", "文档库", "3.2 / 3.3", True),
    NavItem("search", "检索", "3.4", False, "S1 已包含检索功能，此项可合并"),
    NavItem("ask", "库内问答", "轮三十六线框 §D · 丁（2026-10-28）", True),
    NavItem("reader", "PDF 阅读", "3.5", True),
    NavItem("archive", "归档预览与确认", "3.6", True),
    NavItem("operations", "操作日志", "3.6", True),
    NavItem("duplicates", "重复检测", "3.7", True),
    NavItem("monitor", "设置与状态", "3.1 / 3.2 + 阶段 1 验收 1–4", True),
    NavItem("categories", "分类与标签", "3.3", True),
    NavItem("backup", "备份与恢复", "3.8", True),
]

NAV_BY_ID: dict[str, NavItem] = {i.page_id: i for i in NAV_ITEMS}


def find(page_id: str) -> NavItem | None:
    return NAV_BY_ID.get(page_id)
