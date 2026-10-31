"""`describe_backup()` 三档形状 —— 恢复页「体积」列与「选中内容」行读的就是它（轮五十 甲案）。

口径只有一条：**成员集合与 `_plan_members()` 往目标根里放的那几样是同一份**。展示读一套、
恢复搬另一套，等于把「备份缺一半而界面写着成功」（**ISSUES I123** ①）从产出侧搬到消费侧 ——
人在按之前看到的体积，必须就是恢复时要准备的那份空间。

五条断言各自钉住一处：

1. 有清单的包按清单逐成员报字节数，`manifest.json` 自身与边文件（`catalog.db-wal`/`-shm`）不算成员。
2. 裸 `.db` 只有库一项，`kind == "file"`。
3. 没有清单的老目录包：盘上有什么算什么，不许因为没清单就报空。
4. 从包里单独点 `catalog.db` 与点整包报**同一份内容**（`as_package()` 归一化）；
   两种答案会让界面报"只有库"而恢复搬回来两样。
5. 展示不打开库：跑一遍 `describe_backup()` 不在包里新增任何文件（开库会建 WAL 边文件）。
"""
from __future__ import annotations

import shutil

import pytest

from pdfarchiver.services import backup_service

describe = backup_service.BackupService.describe_backup


@pytest.fixture
def vectors_file(ctx):  # noqa: ANN001, ANN201
    """给数据根放一份向量文件（备份只做文件拷贝，不解析它）⇒ 包里就有两样成员。"""
    ctx.paths.data_dir.mkdir(parents=True, exist_ok=True)
    ctx.paths.vectors_file.write_bytes(b"\x93NUMPY" + b"\x00" * 4096)
    return ctx.paths.vectors_file


def test_有清单的包按清单逐成员报字节数(ctx, vectors_file) -> None:  # noqa: ANN001
    pkg = ctx.backup.create_backup()
    # 老包里躺着的那两只边文件（2026-10-25 现读那只包就有）与清单本身都不算成员：
    # 报"包多大"会把不该准备的空间算进去。
    (pkg / "catalog.db-wal").write_bytes(b"\x00" * 32768)
    (pkg / "catalog.db-shm").write_bytes(b"")

    info = describe(pkg)

    assert info["kind"] == "dir"
    assert info["has_manifest"] is True
    assert [m["name"] for m in info["members"]] == ["catalog.db", "vectors.npy"]
    for member in info["members"]:
        assert member["bytes"] == (pkg / member["name"]).stat().st_size, \
            f"清单里的字节数与包内真身不平：{member}"
    assert info["total_bytes"] == sum(m["bytes"] for m in info["members"])
    assert info["total_bytes"] < sum(p.stat().st_size for p in pkg.iterdir()), \
        "总量把清单自身或边文件算进去了 —— 界面会让人多准备一份空间"


def test_裸库只有库一项(ctx) -> None:  # noqa: ANN001
    bare = ctx.paths.backups_dir / "catalog-20261016-120000-v8.db"
    bare.parent.mkdir(parents=True, exist_ok=True)
    bare.write_bytes(b"x" * 5000)

    info = describe(bare)

    assert info == {"kind": "file", "has_manifest": False,
                    "members": [{"name": "catalog.db", "bytes": 5000}],
                    "total_bytes": 5000}, info


def test_没有清单的老包盘上有什么算什么(ctx, vectors_file) -> None:  # noqa: ANN001
    pkg = ctx.backup.create_backup()
    (pkg / "manifest.json").unlink()

    info = describe(pkg)

    assert info["kind"] == "dir"
    assert info["has_manifest"] is False
    assert [m["name"] for m in info["members"]] == ["catalog.db", "vectors.npy"], \
        "没有清单就报空 ⇒ 老备份在这个界面上看着像「没东西可恢复」"
    assert info["total_bytes"] == sum(m["bytes"] for m in info["members"])

    (pkg / "vectors.npy").unlink()
    info = describe(pkg)
    assert [m["name"] for m in info["members"]] == ["catalog.db"], \
        "盘上没有的成员不许凭空出现在清单里"


def test_从包里点库与点整包报同一份内容(ctx, vectors_file) -> None:  # noqa: ANN001
    pkg = ctx.backup.create_backup()

    assert describe(pkg / "catalog.db") == describe(pkg), \
        "从包里单独点库报的是半份内容 ⇒ 界面说「只有库」，而恢复会搬回来两样"

    copy = ctx.paths.backups_dir.parent / "被拷出来的库.db"
    shutil.copy2(pkg / "catalog.db", copy)
    info = describe(copy)
    assert info["kind"] == "file" and info["total_bytes"] == copy.stat().st_size, \
        "旁边没有清单的裸库仍然是裸库，不许被当成整包"


def test_展示体积不打开库(ctx, vectors_file) -> None:  # noqa: ANN001
    """刷新列表时每一行都要报体积 —— 一次刷新开 N 个 12 GB 的库是不可接受的；
    而库坏掉的包也该照常列表（拒绝它的是恢复那一步，不是列表）。

    这里把 `catalog.db` 换成不是数据库的字节：任何"顺手打开库看一眼"的实现都会当场抛
    （`sqlite3.DatabaseError`），展示这一侧则只读清单与 `stat`，照样报得出成员与体积。
    """
    pkg = ctx.backup.create_backup()
    (pkg / "catalog.db").write_bytes(b"not a database" * 64)

    info = describe(pkg)

    assert [m["name"] for m in info["members"]] == ["catalog.db", "vectors.npy"]
    assert info["total_bytes"] == sum(m["bytes"] for m in info["members"])
