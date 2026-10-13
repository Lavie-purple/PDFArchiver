"""设置读写 —— 唯一口径：设置项名字 + 默认值 + 校验（docs/ARCHITECTURE 一）。

AGENTS.md 禁止「应用运行时悄悄改配置」，所以这里同时记录三件事并可打印：
当前生效值 / 它是不是用户覆盖的 / 来自哪个文件。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# 阶段 1 只有这几项是真被代码使用的；不加"将来可能用"的配置项。
DEFAULTS: dict[str, Any] = {
    "worker_threads": 2,          # docs/ARCHITECTURE 三：默认 2
    "gpu_tasks_concurrent": 1,    # D-008：同一时刻最多一个 GPU 任务（p5 显存实测逼出来的）
    "busy_timeout_ms": 5000,      # 与 db/engine.py 的连接工厂同源
    "log_keep_files": 5,          # diagnostics/logs.py 的轮转份数
    "archive_default_template": "{category}/{year}/{name}.pdf",  # 阶段 4 才执行，先占口径
}

SETTINGS_VERSION = 1


class SettingsError(ValueError):
    """设置文件坏了。消息里必须带文件路径，否则无法远程诊断。"""


@dataclass(frozen=True)
class Settings:
    values: dict[str, Any]
    overridden: frozenset[str]
    source: str
    file: Path | None = None
    # 未知键原样带着走，保存时写回去 —— 不静默删用户文件里的内容
    unknown: dict[str, Any] = field(default_factory=dict)

    def __getitem__(self, key: str) -> Any:
        return self.values[key]

    def replaced(self, **kwargs: Any) -> Settings:
        """返回改了若干键的新实例（frozen dataclass，不原地改）。"""
        merged = {**self.values, **kwargs}
        return Settings(
            values=merged,
            overridden=frozenset(self.overridden | kwargs.keys()),
            source=self.source,
            file=self.file,
            unknown=dict(self.unknown),
        )

    def describe(self) -> str:
        """启动时必须打印一次。三列口径：生效值 / 是否被覆盖 / 来源文件。"""
        lines = [f"设置来源：{self.source}"]
        for key in sorted(DEFAULTS):
            tag = "用户覆盖" if key in self.overridden else "默认"
            lines.append(f"  {key}={self.values[key]!r} [{tag}]")
        return "\n".join(lines)


def _validate(body: dict[str, Any], src: Path | str) -> tuple[dict[str, Any], dict[str, Any]]:
    known, unknown = {}, {}
    for key, val in body.items():
        if key not in DEFAULTS:
            unknown[key] = val
            continue
        want = type(DEFAULTS[key])
        if want is int and isinstance(val, bool):
            # Python 里 True 就是 1，不拦的话 `worker_threads: true` 会静默变成 2 个线程以外的怪值
            raise SettingsError(f"{src}: 设置项 {key} 期望整数，实际是布尔 {val!r}")
        if not isinstance(val, want):
            raise SettingsError(f"{src}: 设置项 {key} 期望 {want.__name__}，实际 {type(val).__name__}={val!r}")
        if want is int and val <= 0:
            raise SettingsError(f"{src}: 设置项 {key} 必须为正整数，实际 {val}")
        known[key] = val
    return {**DEFAULTS, **known}, unknown


def load(settings_file: Path) -> Settings:
    """读 settings.json。文件不存在是正常首启状态，返回内置默认值。"""
    label = str(settings_file)
    if not settings_file.exists():
        return Settings(dict(DEFAULTS), frozenset(), f"内置默认值（{label} 尚不存在）", None)
    try:
        raw = json.loads(settings_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SettingsError(f"{label} 不是合法 JSON：{exc}") from exc
    if not isinstance(raw, dict):
        raise SettingsError(f"{label} 顶层必须是对象，实际 {type(raw).__name__}")
    body = raw.get("values") if isinstance(raw.get("values"), dict) else raw
    values, unknown = _validate(body, label)
    overridden = frozenset(k for k in body if k in DEFAULTS)
    return Settings(values, overridden, label, settings_file, unknown)


def save(settings: Settings, settings_file: Path) -> Path:
    """原子写：先写 .tmp 再 replace，避免半截 JSON 把下次启动顶死。"""
    settings_file.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "settings_version": SETTINGS_VERSION,
        "values": {**{k: settings.values[k] for k in sorted(DEFAULTS)}, **settings.unknown},
    }
    tmp = settings_file.with_name(settings_file.name + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(settings_file)
    return settings_file
