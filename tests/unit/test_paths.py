"""数据目录解析的单测 —— 对应阶段 1 验收第 6 条：不许依赖开发机上的固定绝对路径。

断言全部按"结构"写，不写 `C:\\Users\\lavie\\...`：一旦测试里出现某个人的用户名，
它就只能在开发机上通过，等于把硬编码写进了测试。
"""
from __future__ import annotations

import pytest

from pdfarchiver.config.paths import APP_DIR_NAME, ENV_DATA_DIR, AppPaths, resolve_data_root


def test_无显式参数时落在系统本地应用数据目录() -> None:
    paths = AppPaths.resolve(None, env={})
    assert paths.root.name == APP_DIR_NAME
    assert paths.source == "系统本地应用数据目录"
    assert paths.root.is_absolute()


def test_环境变量优先于系统默认(tmp_path) -> None:
    paths = AppPaths.resolve(None, env={ENV_DATA_DIR: str(tmp_path / "fromEnv")})
    assert paths.root == tmp_path / "fromEnv"
    assert "环境变量" in paths.source


def test_显式参数优先于环境变量(tmp_path) -> None:
    env = {ENV_DATA_DIR: str(tmp_path / "ignored")}
    paths = AppPaths.resolve(tmp_path / "explicit", env)
    assert paths.root == tmp_path / "explicit"
    assert paths.source == "显式参数"


def test_波浪号被展开(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    paths = AppPaths.resolve("~/tilde", env={})
    assert "~" not in str(paths.root)
    assert paths.root.name == "tilde"


def test_各子目录都在根目录之下() -> None:
    paths = AppPaths.resolve(None, env={})
    for p in (paths.data_dir, paths.catalog_db, paths.backups_dir, paths.cache_dir,
              paths.config_dir, paths.settings_file, paths.logs_dir, paths.models_dir):
        assert paths.root in p.parents, f"{p} 不在 {paths.root} 之下"
    assert paths.catalog_db.parent == paths.data_dir
    assert paths.settings_file.parent == paths.config_dir


def test_mkdirs建齐运行目录但不建模型目录(tmp_path) -> None:
    paths = AppPaths.resolve(tmp_path, env={})
    paths.mkdirs()
    for d in (paths.data_dir, paths.backups_dir, paths.cache_dir, paths.config_dir, paths.logs_dir):
        assert d.is_dir()
    assert not paths.models_dir.exists(), "模型目录属于阶段 6 的按需下载，启动时不该凭空建出来"
    paths.mkdirs()  # 幂等


def test_resolve_data_root与AppPaths同源(tmp_path) -> None:
    assert resolve_data_root(tmp_path, {}) == AppPaths.resolve(tmp_path, {}).root


def test_describe带来源(tmp_path) -> None:
    text = AppPaths.resolve(tmp_path, env={}).describe()
    assert str(tmp_path) in text and "来源=" in text


@pytest.mark.parametrize("bad", ["", None])
def test_空显式参数回落到下一级(bad, tmp_path) -> None:
    paths = AppPaths.resolve(bad, env={})
    assert paths.root.name == APP_DIR_NAME
