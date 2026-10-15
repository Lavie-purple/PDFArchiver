"""导航注册表 —— 阶段 1 外壳唯一的"界面知识"。

**这里刻意不做任何布局决策。** SPEC 的功能项都要有一行，是因为没有这一行的话，
"应用能启动但看不见还剩什么没做"就变成要靠文档脑补；有这一行，界面就是一个诚实的进度表。
屏数与职责已定案（**D-039**：8 屏 S1–S8，清单见 `docs/UI-SCREENS.md` 第四节），
但**逐屏线框未确认前**（`docs/UI-WIREFRAMES.md`），`implemented=False` 的项一律只给一张"未实现"说明页，
不画任何控件布局。

条目仍按 **SPEC 条款号**命名，不用 S1/S8 编号 —— S 编号是**屏**的编号，一个屏可能挂多个导航入口
（如 S1 同时是"文档库"和"检索"），两套编号混在这里就会变成第二个口径。
"""
from __future__ import annotations

from dataclasses import dataclass

PAGE_STATUS = "status"


@dataclass(frozen=True)
class NavItem:
    page_id: str
    title: str
    spec: str  # 对应的 SPEC 条款，用于说明"这一屏为什么在清单上"
    implemented: bool
    blocked_by: str = ""  # 未实现时，写清卡在哪个决定上


NAV_ITEMS: list[NavItem] = [
    NavItem(PAGE_STATUS, "运行状态与自检", "阶段 1 验收 1–4", True),
    NavItem("library", "文档库", "3.2 / 3.3", False, "Q7 线框未确认（docs/UI-SCREENS.md）"),
    NavItem("search", "检索", "3.4", False, "Q7 线框未确认（后端全文检索阶段 2 已交付）"),
    NavItem("reader", "PDF 阅读", "3.5", False, "Q7 线框未确认；渲染通道已定（D-017），页面渲染后端未实现"),
    NavItem("archive", "归档预览与确认", "3.6", False, "Q7 线框未确认；文件操作属阶段 4，后端与界面都未实现"),
    NavItem("duplicates", "重复检测", "3.7", False, "Q7 线框未确认；重复检测属阶段 4，后端与界面都未实现"),
    NavItem("monitor", "监测与索引设置", "3.1 / 3.2", False, "Q7 线框未确认（后端扫描与索引阶段 2 已交付）"),
    NavItem("backup", "备份与恢复", "3.8", False, "Q7 线框未确认；备份向导属阶段 4，恢复界面未实现"),
]

NAV_BY_ID: dict[str, NavItem] = {i.page_id: i for i in NAV_ITEMS}


def find(page_id: str) -> NavItem | None:
    return NAV_BY_ID.get(page_id)
