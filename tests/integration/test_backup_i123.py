"""备份包的形状（**ISSUES I123**）：向量库文件必须在场，清单必须对得上，恢复落点必须是数据根。

改造前的事实（2026-10-31 探代码确认，逐条见台账 I123）：

- `create_backup()` 只往备份包里放 `catalog.db` 与 `settings.json`，**`vectors.npy` 从来没进过包**。
  后果不是"少备一样东西"：恢复出来的数据根里库说有 196.9 万条向量、文件却不在，
  `VectorStore.search()` 走 `mapped is None` 分支当场 `raise VectorFileMismatch` ——
  **恢复之后语义搜索整条功能是坏的**，而界面上写的是"恢复成功"。
- `restore_to_new_dir()` 把库写成 `target/catalog.db`、把设置写成 `target/config/settings.json`，
  而应用读的是 `target/data/catalog.db` —— 一半对一半错，照 `docs/BACKUP-RESTORE.md` 教的
  `--data-dir <那个新目录>` 指过去**开不到库**。

十一条断言各自钉住一处：

1. 包里三样都在场，清单逐成员记名字与字节数；向量库落盘的文件名按写死的口径 `data/vectors.npy`。
2. 恢复到新数据根之后**当场搜得到**那一条向量，命中分数与备份前一致（这是本轮的验收主句）。
3. 有人从包里单独点 `catalog.db`（界面的文件对话框只能选文件）⇒ 按整包恢复，不许只回半个库。
4. 清单在册的 `vectors.npy` 被人从包里删掉 ⇒ 拒绝恢复，且不在目标根留半个库。
5. `vectors.npy` 被截断 ⇒ 同样拒绝（字节数对不上就是不对得上，不猜"少一半还能用"）。
6. 没建过向量库的库照样能备份，清单只列在场成员（不许把"还没建"当成错误）。
7. 备份中途失败 ⇒ 备份目录不留下（半成品看着像备份，是最坏的一种残留）。
8. 恢复出来的那个根直接 `bootstrap()` 得起，文档数与库里一致。
9. 旧格式（单个 `.db`）仍然可读，但落点跟着数据根口径走。
10. 没有清单的老目录包：有什么恢复什么，向量在场就跟着回来。
11. 快照枚举的唯一口径 `snapshot_paths()` 两种形状都认（顶层裸 `.db` + 包里的 `catalog.db`），
    报告里的名字带包名前缀 —— 只 glob 顶层会把新备份静默漏给 C11 与 p12。
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import numpy as np
import pytest

from pdfarchiver.db.models import Document
from pdfarchiver.fs.identity import identity_key
from pdfarchiver.semantic.vector_store import VectorStore
from pdfarchiver.services import backup_service

DIM = VectorStore.DIM


def _doc(ctx, tmp_path: Path, name: str) -> int:
    file = tmp_path / name
    file.write_bytes(b"%PDF-1.7 fake")
    doc = ctx.documents.upsert(Document(
        path=str(file), path_key=identity_key(str(file)), name=name,
        size_bytes=12, mtime_ns=1_760_000_000_000_000_000, sha256=f"{name!r:0<64}"[:64],
        text_status="done", fts_status="done"))
    return int(doc.id)


@pytest.fixture
def seeded(ctx, tmp_path):
    """两份文档、三条向量（d1 两页 + d2 一页），向量文件真落在 `data/vectors.npy`。

    查询向量取 `d2` 那一页本尊：它与自己那条的点积最高，命中的 `(doc_id, page_no)`
    就是唯一确定的读数 —— 换成随机查询，命中谁取决于运气而不是代码。
    """
    d1 = _doc(ctx, tmp_path, "向量一.pdf")
    d2 = _doc(ctx, tmp_path, "向量二.pdf")
    rng = np.random.default_rng(20261031)
    vectors = {(doc_id, page): _unit(rng)
               for doc_id, page in ((d1, 1), (d1, 2), (d2, 1))}
    store = VectorStore(ctx.paths.root)
    store.add_batch([(doc_id, page, vec) for (doc_id, page), vec in vectors.items()])
    assert store.count() == 3, "夹具自己没把向量建起来，下面几条就都是空指"
    return {"d1": d1, "d2": d2, "vectors": vectors, "store": store}


def _unit(rng) -> np.ndarray:
    v = rng.standard_normal(DIM).astype(np.float32)
    return v / np.linalg.norm(v)


def _manifest(backup_dir: Path) -> dict:
    return json.loads((backup_dir / "manifest.json").read_text(encoding="utf-8"))


def test_备份包里有向量库文件与清单(seeded, ctx, tmp_path) -> None:  # noqa: ANN001
    """`vectors.npy` 与 `manifest.json` 都要在场，清单逐成员的字节数要和包里的真身对上。"""
    backup_dir = ctx.backup.create_backup()

    assert (ctx.paths.data_dir / "vectors.npy").exists(), \
        "向量库落盘的文件名是写死的口径（文档里的数据根布局与清单成员名都按它），不是「paths 当下指到哪个名字」"
    assert (backup_dir / "catalog.db").exists()
    assert (backup_dir / "vectors.npy").exists(), "向量库文件没进备份包 —— 恢复出来语义搜索就是坏的"
    payload = _manifest(backup_dir)
    assert {m["name"] for m in payload["members"]} == {"catalog.db", "vectors.npy"}
    assert payload["schema_version"] == ctx.schema_version
    for member in payload["members"]:
        assert (backup_dir / member["name"]).stat().st_size == member["bytes"], \
            f"清单里的 {member['name']} 字节数与包内实际不平：{member}"

    declared = next(m for m in payload["members"] if m["name"] == "vectors.npy")
    assert declared["bytes"] == ctx.paths.vectors_file.stat().st_size


def test_恢复到新数据根之后语义搜索当场可用(seeded, ctx, tmp_path) -> None:  # noqa: ANN001
    """本轮的验收主句：恢复出来的**数据根**直接能开，向量文件跟着库一起回来。"""
    backup_dir = ctx.backup.create_backup()
    target = tmp_path / "新数据根"

    restored = ctx.backup.restore_to_new_dir(backup_dir, target)

    assert restored == target / "data" / "catalog.db", \
        f"恢复落点不是 `AppPaths` 的库路径（应用读的是 <root>/data/catalog.db）：{restored}"
    assert (target / "data" / "vectors.npy").exists(), "恢复出来的数据根里没有向量文件"

    query = seeded["vectors"][(seeded["d2"], 1)]
    before = seeded["store"].search(query, top_k=3)
    hits = VectorStore(target).search(query, top_k=3)

    assert hits and hits[0][:2] == (seeded["d2"], 1), \
        f"恢复库里那条向量搜不到自己：{hits}"
    assert [h[:2] for h in hits] == [h[:2] for h in before], \
        f"恢复库里命中的那几页与备份前不平：前={before} 后={hits}"
    # 分数逐个相等才算"搬回来的是同一份文件"：向量存的是 int8（`round(v*127)`），
    # 自己查自己的命中分数实测 0.928 而不是 1.0 —— 那是量化的固有损失，不是恢复坏了，
    # 所以这里比的是**同一个查询在备份前后各打几分**，而不是去够一个理论上的 1。
    assert hits[0][2] == pytest.approx(before[0][2]), \
        f"命中分数变了（备份前 {before[0][2]} → 恢复后 {hits[0][2]}）：向量文件不是那一份"
    assert 0.9 <= hits[0][2] <= 1.0, f"命中分数不在 int8 量化后的区间内：命中分数={hits[0][2]:.4f}"
    assert len(hits) == 3, f"三条向量只搜回 {len(hits)} 条：{hits}"


def test_从包里单独选中catalog_db文件也按整包恢复(seeded, ctx, tmp_path) -> None:  # noqa: ANN001
    """界面的文件对话框只能选文件：有人会把包里的 `catalog.db` 单独点进来。

    这时必须按**整包**走 —— 只回半个库（向量文件还留在包里）是数据丢失级别的坑，
    而恢复出来的那个根看着一切正常，直到有人点语义搜索。
    """
    backup_dir = ctx.backup.create_backup()
    target = tmp_path / "按整包恢复"

    restored = ctx.backup.restore_to_new_dir(backup_dir / "catalog.db", target)

    assert restored == target / "data" / "catalog.db"
    assert (target / "data" / "vectors.npy").exists(), \
        "从包里单独点库 ⇒ 只恢复了库，向量文件还躺在包里 —— 这个根一搜语义就是坏的"
    hits = VectorStore(target).search(seeded["vectors"][(seeded["d2"], 1)], top_k=3)
    assert hits and hits[0][:2] == (seeded["d2"], 1), f"整包恢复后那条向量搜不到自己：{hits}"
    assert 0.9 <= hits[0][2] <= 1.0, f"命中分数不在 int8 量化后的区间内：命中分数={hits[0][2]:.4f}"


def test_清单在册的向量文件被删掉时拒绝恢复(seeded, ctx, tmp_path) -> None:  # noqa: ANN001
    """包里的 `vectors.npy` 不见了（清单还写着它）⇒ 当场拒绝，不许"少了就当没有"。"""
    backup_dir = ctx.backup.create_backup()
    (backup_dir / "vectors.npy").unlink()
    target = tmp_path / "残缺恢复"

    with pytest.raises(ValueError, match="vectors.npy"):
        ctx.backup.restore_to_new_dir(backup_dir, target)

    assert not (target / "data" / "catalog.db").exists(), \
        "拒绝之后目标根里还留着库 —— 半个库会被人当成恢复成功"


def test_向量文件被截断时拒绝恢复并删净残留(seeded, ctx, tmp_path) -> None:  # noqa: ANN001
    """字节数对不上就是不对得上：截一半的向量文件恢复出来一搜就炸，必须在门口拦下。"""
    backup_dir = ctx.backup.create_backup()
    vectors = backup_dir / "vectors.npy"
    head = vectors.read_bytes()[: vectors.stat().st_size // 2]
    vectors.write_bytes(head)
    target = tmp_path / "截断恢复"

    with pytest.raises(ValueError, match="不完整"):
        ctx.backup.restore_to_new_dir(backup_dir, target)

    assert not (target / "data" / "vectors.npy").exists()
    assert not (target / "data" / "catalog.db").exists()


def test_没建过向量库的库照样能备份(ctx, tmp_path) -> None:  # noqa: ANN001
    """"还没建语义索引"是正常状态，不是错误：清单只列在场成员，恢复照走。"""
    _doc(ctx, tmp_path, "只有主记录.pdf")
    assert not ctx.paths.vectors_file.exists()

    backup_dir = ctx.backup.create_backup()
    payload = _manifest(backup_dir)
    assert [m["name"] for m in payload["members"]] == ["catalog.db"]

    target = tmp_path / "无向量恢复"
    restored = ctx.backup.restore_to_new_dir(backup_dir, target)
    assert restored == target / "data" / "catalog.db"
    assert not (target / "data" / "vectors.npy").exists()


def test_备份中途失败不留下看着像备份的目录(seeded, ctx, tmp_path, monkeypatch) -> None:  # noqa: ANN001
    """拷成员的中途坏掉（磁盘满 / 源文件读不动）⇒ 整个备份目录撤掉，不进列表。"""
    def boom(*args, **kwargs):
        raise OSError("模拟：拷到一半磁盘满了")

    monkeypatch.setattr(backup_service, "_copy_member", boom)
    before = {b["path"] for b in ctx.backup.list_backups()}

    with pytest.raises(OSError, match="模拟"):
        ctx.backup.create_backup()

    assert {b["path"] for b in ctx.backup.list_backups()} == before, "半成品进了备份列表"
    leftovers = [p.name for p in Path(ctx.paths.backups_dir).iterdir()
                 if p.name.startswith("backup-")]
    assert not leftovers, f"备份目录留下了半成品：{leftovers}"


def test_恢复出来的数据根能直接启动(seeded, ctx, tmp_path) -> None:  # noqa: ANN001
    """落点口径的终局证明：`--data-dir <那个新目录>` 指过去，应用真开得起来、文档还在。

    这条不是冗余 —— 以前库落在 `target/catalog.db`，指过去是一个空的新库（还会自己跑迁移），
    用户看到的是「恢复成功」而数据像丢了；任何"路径字符串相等"的断言都抓不到那种形状。
    """
    backup_dir = ctx.backup.create_backup()
    target = tmp_path / "可直接启动的根"
    restored = ctx.backup.restore_to_new_dir(backup_dir, target)

    from pdfarchiver.services.bootstrap import bootstrap
    fresh = bootstrap(target)
    try:
        assert fresh.paths.catalog_db == restored
        assert fresh.schema_version == ctx.schema_version
        assert fresh.documents.count() == 2, \
            f"新根里读到的主记录数不是 2 —— 指过去开的是别的那个库：{fresh.documents.count()}"
        hits = VectorStore(target).search(seeded["vectors"][(seeded["d2"], 1)], top_k=1)
        assert hits and hits[0][0] == seeded["d2"]
    finally:
        fresh.shutdown()


def test_旧格式单个db文件恢复落到数据根布局(ctx, tmp_path) -> None:  # noqa: ANN001
    """向后兼容：旧格式（单个 `.db`）仍然可读，但落点跟着新口径走，不再摆在根目录顶层。"""
    old_db = tmp_path / "catalog-20261016-120000-v8.db"
    src = sqlite3.connect(str(ctx.engine.path))
    try:
        dst = sqlite3.connect(str(old_db))
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()

    target = tmp_path / "旧格式恢复"
    restored = ctx.backup.restore_to_new_dir(old_db, target)
    assert restored == target / "data" / "catalog.db"
    assert restored.exists()
    assert not (target / "catalog.db").exists(), "还在按老布局往根目录顶层摆"


def test_没有清单的老备份目录恢复向量文件在场那一档(seeded, ctx, tmp_path) -> None:  # noqa: ANN001
    """改造前产出的目录包没有 `manifest.json`：认它有什么就恢复什么，不许因为没清单就拒绝。"""
    backup_dir = ctx.backup.create_backup()
    (backup_dir / "manifest.json").unlink()
    target = tmp_path / "无清单恢复"

    restored = ctx.backup.restore_to_new_dir(backup_dir, target)

    assert restored == target / "data" / "catalog.db"
    assert (target / "data" / "vectors.npy").exists()
    assert (target / "data" / "vectors.npy").stat().st_size == ctx.paths.vectors_file.stat().st_size


def test_快照枚举口径两种形状都认(ctx) -> None:  # noqa: ANN001
    """包里的 `catalog.db` 与顶层裸 `.db` 都得算快照 —— 这是 C11（S7 体检）与 p12 探针共用的
    唯一枚举口径，漏一种形状 = 那份产物从来没被体检过，而读数照绿。

    坏法注入（真跑过，`.probe_work/u49_inject_backup.py` 的 B13）：删掉 `snapshot_paths`
    里遍历 `backup-*` 那三行 → 本条在「包里的库没进口径」上红。
    """
    ctx.paths.backups_dir.mkdir(parents=True, exist_ok=True)
    bare = ctx.paths.backups_dir / "pre-migration-0009-20261031-010101.db"
    bare.write_bytes(b"")
    pkg = ctx.backup.create_backup()

    snaps = backup_service.snapshot_paths(ctx.paths.backups_dir)
    assert bare in snaps, f"顶层裸 .db 没算进快照口径：{snaps}"
    assert pkg / "catalog.db" in snaps, f"包里的 catalog.db 没算进快照口径：{snaps}"

    assert backup_service.snapshot_label(bare, ctx.paths.backups_dir) == bare.name
    assert backup_service.snapshot_label(pkg / "catalog.db", ctx.paths.backups_dir) \
        == f"{pkg.name}/catalog.db", \
        "包里的库印成 `catalog.db` ⇒ 几个包在报告里是同一个名字，看不出体检的是哪一份"

    missing = ctx.paths.backups_dir.parent / "没有这个目录"
    assert backup_service.snapshot_paths(missing) == []
