"""设置层单测 —— 对应 AGENTS.md「禁止在应用运行时改配置文件：启动必须打印当前默认值 /
用户覆盖值 / 来源文件」，以及 SPEC 3.8「应用配置与原始 PDF 分离存放」。"""
from __future__ import annotations

import json

import pytest

from pdfarchiver.config.settings import (DEFAULTS, SETTINGS_VERSION, SettingsError, load, save)


def _write(path, body) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(body, ensure_ascii=False), encoding="utf-8")


def test_文件不存在是正常首启状态不是错误(tmp_path) -> None:
    s = load(tmp_path / "config" / "settings.json")
    assert s.values == DEFAULTS
    assert s.overridden == frozenset()
    assert s.file is None
    assert "尚不存在" in s.source


def test_默认值一项都不缺(tmp_path) -> None:
    s = load(tmp_path / "none.json")
    for key in DEFAULTS:
        assert key in s.values


def test_用户只覆盖一项其余仍标默认(tmp_path) -> None:
    f = tmp_path / "config" / "settings.json"
    _write(f, {"worker_threads": 4})
    s = load(f)
    assert s["worker_threads"] == 4
    assert s.overridden == frozenset({"worker_threads"})
    desc = s.describe()
    assert "[用户覆盖]" in desc and "[默认]" in desc
    assert s.source == str(f)


def test_描述里每个设置项都只出现一次(tmp_path) -> None:
    desc = load(tmp_path / "none.json").describe()
    for key in DEFAULTS:
        assert desc.count(f"{key}=") == 1, "同一个设置项打两遍就是两个口径"


def test_嵌套values写法同样接受(tmp_path) -> None:
    f = tmp_path / "settings.json"
    _write(f, {"settings_version": SETTINGS_VERSION, "values": {"busy_timeout_ms": 8000}})
    s = load(f)
    assert s["busy_timeout_ms"] == 8000
    assert "busy_timeout_ms" in s.overridden


def test_类型不对时报错带文件路径(tmp_path) -> None:
    f = tmp_path / "settings.json"
    _write(f, {"worker_threads": "很多"})
    with pytest.raises(SettingsError) as e:
        load(f)
    assert str(f) in str(e.value)
    assert "worker_threads" in str(e.value)


def test_非正整数被拒绝(tmp_path) -> None:
    f = tmp_path / "settings.json"
    _write(f, {"busy_timeout_ms": 0})
    with pytest.raises(SettingsError):
        load(f)


def test_布尔值不被当成整数(tmp_path) -> None:
    """Python 里 True 是 int 的实例，`isinstance(True, int)` 为真 —— 不加这条守卫
    `worker_threads: true` 会静默变成 2 个线程。"""
    f = tmp_path / "settings.json"
    _write(f, {"worker_threads": True})
    with pytest.raises(SettingsError):
        load(f)


def test_坏JSON的报错能定位到文件(tmp_path) -> None:
    f = tmp_path / "settings.json"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("{ 这不是 JSON", encoding="utf-8")
    with pytest.raises(SettingsError) as e:
        load(f)
    assert str(f) in str(e.value)


def test_顶层不是对象时报错(tmp_path) -> None:
    f = tmp_path / "settings.json"
    _write(f, [1, 2, 3])
    with pytest.raises(SettingsError) as e:
        load(f)
    assert "顶层必须是对象" in str(e.value)


def test_未知键保存时原样带回(tmp_path) -> None:
    """用户文件里的键不认识的也不能删 —— 删掉就是覆盖用户数据。"""
    f = tmp_path / "settings.json"
    _write(f, {"worker_threads": 3, "将来的设置": 7})
    s = load(f)
    assert s.unknown == {"将来的设置": 7}
    save(s, f)
    assert json.loads(f.read_text(encoding="utf-8"))["values"]["将来的设置"] == 7


def test_保存写出全部已知项与版本号(tmp_path) -> None:
    f = tmp_path / "settings.json"
    s = load(tmp_path / "不存在.json").replaced(worker_threads=6)
    save(s, f)
    body = json.loads(f.read_text(encoding="utf-8"))
    assert body["settings_version"] == SETTINGS_VERSION
    assert set(DEFAULTS) <= set(body["values"])
    assert body["values"]["worker_threads"] == 6
    assert not f.with_name("settings.json.tmp").exists(), "原子写的临时文件必须被 replace 掉"


def test_replaced不改原对象(tmp_path) -> None:
    s = load(tmp_path / "none.json")
    s2 = s.replaced(worker_threads=9)
    assert s["worker_threads"] == DEFAULTS["worker_threads"]
    assert s2["worker_threads"] == 9
    assert "worker_threads" in s2.overridden
