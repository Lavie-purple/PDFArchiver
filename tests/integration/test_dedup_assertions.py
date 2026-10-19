"""判重口径断言（**ISSUES I79** 甲）。

四条断言钉四件事，每件都是"看着对但没写过断言就不算数"的那一类：

1. 同一 sha256 才算一组 —— 两份同哈希的文档必须出现在 `duplicate_groups()` 的同一行里。
2. 不同 sha256 不进同一组 —— 两份不同哈希的文档各自成组（或不成组），绝不混在一起。
3. 缺失文件仍在组里，但可回收排除它 —— `missing_since IS NOT NULL` 的成员不计入 `reclaimable_bytes`。
4. 硬链接组 ≠ 重复组 —— 同 `device_id + file_id` 的多路径算硬链接，`count_hardlink_groups()` 计得出，
   但 `reclaimable_bytes` 排除它们（硬链接不占额外磁盘空间）。

这四条合起来就是 S5 页面上那三行读数的口径来源：`group_count` / `excess_count` / `reclaimable_bytes`。
没有这些断言，"什么算重复"只是页面上的一行说明文字，改错了一天也不会红。
"""
from __future__ import annotations

import pytest

from pdfarchiver.db.models import Document


def _insert_doc(ctx, *, path: str, sha: str | None, size: int = 1024,
                device_id: int | None = None, file_id: int | None = None,
                missing_since: int | None = None) -> int:
    conn = ctx.engine.thread_connection()
    conn.execute(
        "INSERT INTO documents(path, path_key, name, ext, size_bytes, mtime_ns,"
        " sha256, device_id, file_id, missing_since, created_at, updated_at)"
        " VALUES(?,?,?,?,?,?,?,?,?,?,1,1)",
        (path, path.lower(), path.rsplit("/", 1)[-1], "pdf", size, 1,
         sha, device_id, file_id, missing_since))
    conn.commit()
    return int(conn.execute(f"SELECT id FROM documents WHERE path_key='{path.lower()}'").fetchone()[0])


def test_同一sha256才算一组(ctx) -> None:
    """两份同哈希的文档必须出现在 `duplicate_groups()` 的同一行里。"""
    _insert_doc(ctx, path="H:/docs/a.pdf", sha="aa" * 32, size=1000)
    _insert_doc(ctx, path="H:/docs/b.pdf", sha="aa" * 32, size=1000)
    groups = ctx.documents.duplicate_groups()
    assert len(groups) == 1, f"同哈希两份应成一组，实际 {len(groups)} 组"
    assert groups[0]["sha256"] == "aa" * 32
    assert groups[0]["count"] == 2


def test_不同sha256不进同一组(ctx) -> None:
    """两份不同哈希的文档各自不成组（`HAVING count(*) > 1`），绝不混在一起。"""
    _insert_doc(ctx, path="H:/docs/a.pdf", sha="aa" * 32, size=1000)
    _insert_doc(ctx, path="H:/docs/b.pdf", sha="bb" * 32, size=1000)
    groups = ctx.documents.duplicate_groups()
    assert len(groups) == 0, f"不同哈希各一份不应成组，实际 {len(groups)} 组"


def test_缺失文件仍在组里但可回收排除它(ctx) -> None:
    """`missing_since IS NOT NULL` 的成员不计入 `reclaimable_bytes`。

    三份同哈希：一份正常 + 一份正常 + 一份缺失。`group_count=1`、`excess_count=2`，
    但 `reclaimable_bytes` 只算那一份正常副本的 size（缺失的那份不占磁盘，不可回收）。
    """
    _insert_doc(ctx, path="H:/docs/a.pdf", sha="cc" * 32, size=5000)
    _insert_doc(ctx, path="H:/docs/b.pdf", sha="cc" * 32, size=5000)
    _insert_doc(ctx, path="H:/docs/c.pdf", sha="cc" * 32, size=5000, missing_since=100)

    summary = ctx.documents.dedup_summary()
    assert summary["group_count"] == 1
    assert summary["excess_count"] == 2
    assert summary["reclaimable_bytes"] == 5000, (
        f"缺失文件不应计入可回收：三份同哈希（两份在 + 一份缺），可回收应只算一份的 size，"
        f"实际 {summary['reclaimable_bytes']}")

    members = ctx.documents.duplicate_group_members("cc" * 32)
    assert len(members) == 3
    missing_members = [m for m in members if m["missing_since"] is not None]
    assert len(missing_members) == 1


def test_硬链接组不等于重复组(ctx) -> None:
    """同 `device_id + file_id` 的多路径算硬链接。

    三份同哈希：两份是硬链接（同 device_id=1, file_id=100）+ 一份独立副本。
    `count_hardlink_groups()` 必须计得出这 1 组硬链接；
    `reclaimable_bytes` 只算那一份独立副本的 size（硬链接不占额外磁盘空间）。
    """
    _insert_doc(ctx, path="H:/docs/a.pdf", sha="dd" * 32, size=8000,
                device_id=1, file_id=100)
    _insert_doc(ctx, path="H:/docs/b.pdf", sha="dd" * 32, size=8000,
                device_id=1, file_id=100)
    _insert_doc(ctx, path="H:/docs/c.pdf", sha="dd" * 32, size=8000,
                device_id=2, file_id=200)

    assert ctx.documents.count_hardlink_groups() == 1, \
        "同 device_id+file_id 的多路径必须被计为硬链接组"

    summary = ctx.documents.dedup_summary()
    assert summary["group_count"] == 1
    assert summary["reclaimable_bytes"] == 8000, (
        f"硬链接不应计入可回收：三份同哈希（两份硬链接 + 一份独立），可回收应只算独立副本的 size，"
        f"实际 {summary['reclaimable_bytes']}")

    members = ctx.documents.duplicate_group_members("dd" * 32)
    hardlinks = [m for m in members if m["is_hardlink"]]
    assert len(hardlinks) == 1, f"硬链接成员应有 1 个（第二份起算硬链接），实际 {len(hardlinks)}"


def test_sha256为空不进任何组(ctx) -> None:
    """`sha256 IS NULL` 的文档不参与分组。

    两份都没有哈希的文档，即使 size 相同也不应出现在 `duplicate_groups()` 里。
    这是 `WHERE sha256 IS NOT NULL` 那条过滤的直接推论，但没断言过就等于没保证。
    """
    _insert_doc(ctx, path="H:/docs/a.pdf", sha=None, size=1000)
    _insert_doc(ctx, path="H:/docs/b.pdf", sha=None, size=1000)
    groups = ctx.documents.duplicate_groups()
    assert len(groups) == 0, "sha256 为空的文档不应参与分组"
