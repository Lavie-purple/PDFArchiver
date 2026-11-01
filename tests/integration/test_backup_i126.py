"""恢复不许静默覆盖别人的东西（**ISSUES I126** 甲）。

轮五十一实测的两条（证据 `.probe_work/u51_restore_overwrite_proof.log`，2026-11-01）：

- 目标根里先有人一份 `data/vectors.npy`（160 B，内容写着 IMPORTANT-NOT-OURS）⇒ 恢复照旧返回、
  无异常，事后回读已经不是原来那份 —— 被包内那份 `shutil.copy2` 盖掉了，而界面上写着「恢复成功」。
- 目标根的 `config/settings.json` 是个**目录**、里面放着一份人的文件 ⇒ `copy2` 把成员写进那个
  目录，字节比对拿到 0，失败清理走 `_discard()` 的 `shutil.rmtree` —— 连目录带里面那份一起删。

两条的共同形状：往**不是本次恢复创建的路径**上写，写之前不判存在。判据因此也只有一条：
**落点已被占着（含符号链接）⇒ 一个字节也不写，整包拒绝，并把撞上的成员与路径点出来。**

外加一条反向守卫：目标根**存在但为空**时必须照常恢复 —— 否则「一律拒绝」也能让上面两条变绿。
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from pdfarchiver.db.models import Document
from pdfarchiver.fs.identity import identity_key
from pdfarchiver.semantic.vector_store import VectorStore
from pdfarchiver.services.backup_service import BackupService

OURS_VECTORS = b"IMPORTANT-NOT-OURS" + b"\x00" * 143          # 160 B：不是 .npy，也不该被读
HUMAN_FILE = "我的账密.txt"


def _seed_vectors(ctx, tmp_path: Path) -> None:  # noqa: ANN001
    """造一份真向量（备份包里有 `vectors.npy` 才谈得上「目标根那份被盖掉」）。"""
    file = tmp_path / "向量文档.pdf"
    file.write_bytes(b"%PDF-1.7 fake")
    doc = ctx.documents.upsert(Document(
        path=str(file), path_key=identity_key(str(file)), name=file.name,
        size_bytes=12, mtime_ns=1_760_000_000_000_000_000, sha256="a" * 64,
        text_status="done", fts_status="done"))
    vec = np.zeros(VectorStore.DIM, dtype=np.float32)
    vec[0] = 1.0
    store = VectorStore(ctx.paths.root)
    store.add_batch([(int(doc.id), 1, vec)])
    assert ctx.paths.vectors_file.exists(), "夹具自己没把向量建起来，这条就成空指"


@pytest.fixture
def seeded_settings_and_vectors(ctx, tmp_path):  # noqa: ANN001
    """一个三类成员都在场的包：向量库 + 设置（没有设置的包只有两个成员，撞不上甲-2）。"""
    _seed_vectors(ctx, tmp_path)
    ctx.paths.settings_file.write_text(json.dumps({"worker_threads": 3}), encoding="utf-8")
    return ctx


def test_目标根里别人那份向量文件不被覆盖(seeded_settings_and_vectors, ctx, tmp_path) -> None:  # noqa: ANN001
    """甲-1：恢复前目标根已有 `data/vectors.npy` ⇒ 拒整包，那份 160 B 原样还在。"""
    backup_dir = ctx.backup.create_backup()
    target = tmp_path / "别人的根"
    (target / "data").mkdir(parents=True)
    stranger = target / "data" / "vectors.npy"
    stranger.write_bytes(OURS_VECTORS)

    with pytest.raises(FileExistsError, match="vectors.npy"):
        ctx.backup.restore_to_new_dir(backup_dir, target)

    assert stranger.read_bytes() == OURS_VECTORS, "别人那份向量文件被包里的盖掉了"
    assert not (target / "data" / "catalog.db").exists(), \
        "拒绝之前已经把库写进目标根了 —— 拒绝要拒绝在动笔之前"
    assert not (target / "config" / "settings.json").exists(), "库还没谈拢就先把设置写进去了"


def test_settings落点是同名目录时连目录带文件都不动(seeded_settings_and_vectors, ctx, tmp_path) -> None:  # noqa: ANN001
    """甲-2：`config/settings.json` 是个目录、里面有人的文件 ⇒ 拒绝，且**不再 rmtree 它**。"""
    backup_dir = ctx.backup.create_backup()
    target = tmp_path / "同名目录的根"
    occupied = target / "config" / "settings.json"
    occupied.mkdir(parents=True)
    human = occupied / HUMAN_FILE
    human.write_text("别删我", encoding="utf-8")

    with pytest.raises(FileExistsError, match="settings.json"):
        ctx.backup.restore_to_new_dir(backup_dir, target)

    assert occupied.is_dir(), "那个同名目录被人当成落点删掉了"
    assert human.read_text(encoding="utf-8") == "别删我", "目录里那份人的文件被连带删掉了"
    assert not (target / "data" / "catalog.db").exists()


def test_目标根存在但为空时照常恢复(seeded_settings_and_vectors, ctx, tmp_path) -> None:  # noqa: ANN001
    """反向守卫：「目标根存在」本身不是拒绝理由 —— 空的既有目录与不存在的目录应当同一条路。"""
    backup_dir = ctx.backup.create_backup()
    target = tmp_path / "空的既有根"
    target.mkdir()

    restored = ctx.backup.restore_to_new_dir(backup_dir, target)

    assert restored == target / "data" / "catalog.db"
    assert restored.exists()
    assert (target / "data" / "vectors.npy").exists(), "空根里向量文件没跟着回来"
    assert json.loads((target / "config" / "settings.json").read_text(encoding="utf-8")) \
        == {"worker_threads": 3}


def test__discard默认不删目录只删文件(tmp_path: Path) -> None:
    """守卫单测：`_discard()` 默认只删文件；只有显式 `allow_tree=True`（备份侧半成品）才删树。"""
    stranger = tmp_path / "别人的目录"
    stranger.mkdir()
    inside = stranger / HUMAN_FILE
    inside.write_text("别删我", encoding="utf-8")

    BackupService._discard(stranger)
    assert inside.exists(), "默认路径把不是本次创建的同名目录整个删了"

    BackupService._discard(stranger, allow_tree=True)
    assert not stranger.exists(), "显式 allow_tree=True 时备份侧半成品目录没被删掉"
