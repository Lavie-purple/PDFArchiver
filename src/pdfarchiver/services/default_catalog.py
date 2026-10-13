"""默认分类模板 —— 以**数据**形式落库，不写进任何判断逻辑。

SPEC 3.3：「不得把分类逻辑写死在程序代码中」+「提供合理的默认分类模板，均为初始建议，
不是不可修改的固定分类」。所以这里的结构第一次启动时被种进 `categories` 表，
之后用户改名、挪层级、删除都可以，代码里没有任何地方拿这些名字做过条件判断
（`tests/guards/test_architecture.py` 不查这条，人查：全站搜「人工智能」应只出现在本文件）。

标签一个都不预置：SPEC 没有给默认标签清单，凭空造一批就是假数据。
"""
from __future__ import annotations

from dataclasses import dataclass

from pdfarchiver.db.repositories.catalog import CatalogRepository
from pdfarchiver.db.repositories.settings import SettingsRepository

# {顶层分类名: [子分类名, ...]}。子分类是 SPEC 3.3 原文列举的示例，未增删。
DEFAULT_CATEGORY_TEMPLATE: dict[str, list[str]] = {
    "行业／领域": ["人工智能", "游戏", "金融", "商业", "设计"],
    "文档类型": ["课件", "论文", "行业报告", "技术文档", "产品手册", "白皮书", "标准规范"],
}

NOTE = "初始模板（SPEC 3.3），可改名、可删除"
_SEEDED_KEY = "catalog.default_seeded"


@dataclass
class SeedResult:
    categories_created: int
    tags_created: int
    skipped: bool  # 已经种过一遍（或用户已有自己的树）时为 True —— 用户的树不许被启动流程覆盖

    def describe(self) -> str:
        if self.skipped:
            return "未写入模板（已种过或用户已有分类）"
        return f"种下默认分类 {self.categories_created} 个"


def seed_default_categories(catalog: CatalogRepository, app_settings: SettingsRepository) -> SeedResult:
    """只在**从没种过**的时候种一次。

    判据不是"分类表为空"：用户把模板全删了以后表也是空的，下次启动又给他长回来，
    等于启动流程覆盖了用户的删除动作。所以种过没种过记在 `app_settings` 里。
    """
    if app_settings.get(_SEEDED_KEY) is True:
        return SeedResult(0, 0, True)
    if catalog.count_categories() > 0:
        return SeedResult(0, 0, True)
    created = 0
    for top_name, children in DEFAULT_CATEGORY_TEMPLATE.items():
        top = catalog.add_category(top_name, note=NOTE)
        created += 1
        for child in children:
            catalog.add_category(child, parent_id=top.id, note=NOTE)
            created += 1
    app_settings.set(_SEEDED_KEY, True)
    return SeedResult(created, 0, False)
