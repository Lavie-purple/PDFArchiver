"""数据目录解析 —— 阶段 1 验收第 6 条：不许依赖开发机上的固定绝对路径。

优先级（高→低）：显式参数 > 环境变量 ``PDFARCHIVER_DATA_DIR`` > 系统本地应用数据目录。
第三条让装到任何一台 Windows 上都落在 ``%LOCALAPPDATA%\\PdfArchiver``，
非 Windows（CI / 测试）落到 ``~/.local/share/PdfArchiver``，两者都不是写死的盘符。
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

ENV_DATA_DIR = "PDFARCHIVER_DATA_DIR"
APP_DIR_NAME = "PdfArchiver"


def _system_app_data_dir() -> Path:
    """系统给"应用本地数据"的目录。取不到就退到用户主目录，绝不写死路径。"""
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
        if base:
            return Path(base)
        return Path.home() / "AppData" / "Local"
    xdg = os.environ.get("XDG_DATA_HOME")
    if xdg:
        return Path(xdg)
    return Path.home() / ".local" / "share"


def resolve_data_root(explicit: str | os.PathLike[str] | None = None,
                      env: os._Environ[str] | dict[str, str] | None = None) -> Path:
    """只要目录本身，不要来源信息时用这个；需要溯源一律用 ``AppPaths.resolve``。"""
    return AppPaths.resolve(explicit, env).root


@dataclass(frozen=True)
class AppPaths:
    """一次解析、全场共用。目录由此处统一创建，别的模块不许自己拼路径。"""

    root: Path
    source: str = "系统默认"

    @classmethod
    def resolve(cls, explicit: str | os.PathLike[str] | None = None,
                env: os._Environ[str] | dict[str, str] | None = None) -> AppPaths:
        environ = os.environ if env is None else env
        if explicit:
            return cls(root=Path(explicit).expanduser(), source="显式参数")
        from_env = environ.get(ENV_DATA_DIR)
        if from_env:
            return cls(root=Path(from_env).expanduser(), source=f"环境变量 {ENV_DATA_DIR}")
        return cls(root=_system_app_data_dir() / APP_DIR_NAME, source="系统本地应用数据目录")

    @property
    def data_dir(self) -> Path:
        return self.root / "data"

    @property
    def catalog_db(self) -> Path:
        return self.data_dir / "catalog.db"

    @property
    def backups_dir(self) -> Path:
        return self.data_dir / "backups"

    @property
    def cache_dir(self) -> Path:
        return self.data_dir / "cache"

    @property
    def config_dir(self) -> Path:
        return self.root / "config"

    @property
    def settings_file(self) -> Path:
        return self.config_dir / "settings.json"

    @property
    def logs_dir(self) -> Path:
        return self.root / "logs"

    @property
    def models_dir(self) -> Path:
        return self.root / "models"

    @property
    def journal_dir(self) -> Path:
        """归档/去重/备份等批次执行的 journal 目录（ISSUES I41 定死唯一口径）。"""
        return self.data_dir / "journal"

    def mkdirs(self) -> None:
        """幂等：已存在不报错。建运行时真要写的目录，**不建 `models`**（模型是阶段 6 按需下载，
        提前建出来只会让人以为里面有东西）。"""
        for d in (self.data_dir, self.backups_dir, self.cache_dir, self.config_dir,
                  self.logs_dir, self.journal_dir):
            d.mkdir(parents=True, exist_ok=True)

    def describe(self) -> str:
        """给人看的一行：根目录在哪、为什么选它。诊断时要出现在日志与状态栏里。"""
        return f"数据根目录={self.root} (来源={self.source})"
