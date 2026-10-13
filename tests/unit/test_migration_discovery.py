"""迁移发现规则单测（docs/DATABASE 四）。

这些规则不是洁癖：迁移文件名一乱，"哪个版本已经跑过"就没有唯一答案，
而 `schema_version` 一旦和目录内容对不上，轻则重复建表报错，重则跳过迁移留下半套结构。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from pdfarchiver.db.migrations import discover

_BODY = 'VERSION = {version}\n\n\ndef apply(conn):\n    conn.execute("CREATE TABLE t{n}(x INTEGER)")\n'


def _mig(dir_: Path, filename: str, version: int) -> Path:
    p = dir_ / filename
    p.write_text(_BODY.format(version=version, n=version), encoding="utf-8")
    return p


@pytest.fixture
def mdir(tmp_path: Path) -> Path:
    d = tmp_path / "migrations"
    d.mkdir()
    return d


def test_按序号升序返回(mdir) -> None:
    _mig(mdir, "0002_second.py", 2)
    _mig(mdir, "0001_first.py", 1)
    found = discover(mdir)
    assert [m.order for m in found] == [1, 2]
    assert [m.label for m in found] == ["0001_first", "0002_second"]
    assert found[0].version == 1


def test_下划线开头的辅助文件被跳过(mdir) -> None:
    _mig(mdir, "0001_first.py", 1)
    _mig(mdir, "_shared_helpers.py", 99)
    assert [m.order for m in discover(mdir)] == [1]


def test_文件名不合规则直接拒绝(mdir) -> None:
    _mig(mdir, "initial.py", 1)
    with pytest.raises(ValueError, match="NNNN_slug"):
        discover(mdir)


def test_四位数以下的序号不被接受(mdir) -> None:
    _mig(mdir, "001_first.py", 1)
    with pytest.raises(ValueError, match="NNNN_slug"):
        discover(mdir)


def test_缺VERSION的迁移被拒绝(mdir) -> None:
    (mdir / "0001_no_version.py").write_text("def apply(conn):\n    pass\n", encoding="utf-8")
    with pytest.raises(ValueError, match="VERSION"):
        discover(mdir)


def test_缺apply的迁移被拒绝(mdir) -> None:
    (mdir / "0001_no_apply.py").write_text("VERSION = 1\n", encoding="utf-8")
    with pytest.raises(ValueError, match="apply"):
        discover(mdir)


def test_VERSION与文件名不一致时拒绝(mdir) -> None:
    """这是最阴的一种：水位表会记住文件名的序号，实际结构却由 VERSION 决定 —— 两边必须钉死。"""
    _mig(mdir, "0003_wrong.py", 1)
    with pytest.raises(ValueError, match="与文件名序号不一致"):
        discover(mdir)


def test_序号重复时拒绝(mdir) -> None:
    _mig(mdir, "0001_first.py", 1)
    _mig(mdir, "0001_second.py", 1)
    with pytest.raises(ValueError, match="重复"):
        discover(mdir)


def test_空目录返回空列表(mdir) -> None:
    assert discover(mdir) == []


def test_真实迁移目录里的文件全部合规则() -> None:
    """本项目的真迁移文件必须满足上面全部规则；阶段 2 加 0002 时这条会跟着一起验。"""
    real = Path(__file__).resolve().parents[2] / "src" / "pdfarchiver" / "db" / "migrations"
    found = discover(real)
    assert found, "迁移目录里一个迁移都没有，应用永远建不出表"
    orders = [m.order for m in found]
    assert orders == sorted(orders) and orders[0] == 1, "首版迁移必须是 0001，序号不许断档"
    assert len(set(orders)) == len(orders)
