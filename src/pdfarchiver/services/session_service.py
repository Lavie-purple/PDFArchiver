"""会话记忆：界面自己要用的一点状态（上次停在哪个导航项）。

存在 `app_settings` 表里而不是 settings.json，是因为它是**本机运行时状态**、不是用户配置：
删掉它应用照样正常，删掉 settings.json 用户设置就没了。两者口径不同，不互相镜像。

这一层存在的另一个原因是依赖方向：`ui` 不许 import `db.repositories`
（docs/ARCHITECTURE 二，由 tests/guards/test_architecture.py 拦住），
界面要持久化一点东西，就必须走服务层。
"""
from __future__ import annotations

from pdfarchiver.db.repositories.settings import SettingsRepository

_LAST_NAV_KEY = "ui.last_nav_page"


class SessionService:
    def __init__(self, app_settings: SettingsRepository) -> None:
        self.app_settings = app_settings

    def last_nav_page(self) -> str | None:
        value = self.app_settings.get(_LAST_NAV_KEY)
        return value if isinstance(value, str) else None

    def remember_nav_page(self, page_id: str) -> None:
        self.app_settings.set(_LAST_NAV_KEY, page_id)
