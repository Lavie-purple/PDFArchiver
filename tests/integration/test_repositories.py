"""仓储层：真 SQLite 上的读写、幂等、约束与跨重启持久化。

对应阶段 1 验收 2、3：数据库能初始化/写入/读取/迁移；分类、标签和设置能持久化。
"""
from __future__ import annotations

import pytest

from pdfarchiver.db.engine import DatabaseError
from pdfarchiver.db.models import Document, now_ts
from pdfarchiver.fs.identity import identity_key, normalize_path
from pdfarchiver.services.bootstrap import bootstrap


def _doc(path, **kw) -> Document:
    return Document(path=normalize_path(path), path_key=identity_key(path),
                    name=path.name, ext=path.suffix.lstrip(".").lower(),
                    size_bytes=kw.pop("size_bytes", 1024), mtime_ns=kw.pop("mtime_ns", 1), **kw)


def test_文档主记录写入后能原样读回(ctx, tmp_path) -> None:
    p = tmp_path / "人工智能产业报告.pdf"
    p.write_bytes(b"x" * 1024)
    saved = ctx.documents.upsert(_doc(p, page_count=88))
    got = ctx.documents.get(saved.id)
    assert got is not None and got.id == saved.id
    assert (got.name, got.ext, got.page_count, got.path_key) == (
        "人工智能产业报告.pdf", "pdf", 88, saved.path_key)
    assert got.created_at > 0 and got.updated_at >= got.created_at
    assert ctx.documents.get_by_path_key(saved.path_key).id == saved.id


def test_同一路径重复写只留一条且只刷新文件事实(ctx, tmp_path) -> None:
    p = tmp_path / "a.pdf"
    p.write_bytes(b"x")
    first = ctx.documents.upsert(_doc(p, size_bytes=10))
    # 故意把状态写成已完成，再看第二次 upsert 会不会把它抹掉
    conn = ctx.engine.thread_connection()
    conn.execute("UPDATE documents SET parse_status='done', fts_status='done' WHERE id=?", (first.id,))
    conn.commit()

    second = ctx.documents.upsert(_doc(p, size_bytes=999))
    assert second.id == first.id, "重叠监测根重复扫到同一文件不许膨胀成两条（p7 实测）"
    assert ctx.documents.count() == 1
    assert second.size_bytes == 999
    assert second.parse_status == "done", "重新扫描不能把索引状态冲掉"
    assert second.fts_status == "done"


def test_标记缺失保留记录且不覆盖首次时间(ctx, tmp_path) -> None:
    p = tmp_path / "gone.pdf"
    p.write_bytes(b"x")
    saved = ctx.documents.upsert(_doc(p))
    assert ctx.documents.mark_missing(saved.path_key) is True
    first = ctx.documents.get(saved.id)
    assert first.missing_since and first.path == saved.path
    assert ctx.documents.count_missing() == 1
    assert ctx.documents.mark_missing(saved.path_key) is False, "第二次标记不该改时间戳"
    ts = ctx.documents.get(saved.id).missing_since
    assert ts == first.missing_since
    # 文件回来了：upsert 要把 missing_since 清空
    p.write_bytes(b"xx")
    assert ctx.documents.upsert(_doc(p, size_bytes=2)).missing_since is None


def test_文档错误信息落库(ctx, tmp_path) -> None:
    p = tmp_path / "broken.pdf"
    p.write_bytes(b"x")
    saved = ctx.documents.upsert(_doc(p))
    ctx.documents.set_error(saved.id, "pymupdf 打不开：需要口令")
    got = ctx.documents.get(saved.id)
    assert got.last_error == "pymupdf 打不开：需要口令"
    assert got.parse_status == "failed"


def test_列表按名字排序且分页(ctx, tmp_path) -> None:
    for name in ("b.pdf", "a.pdf", "c.pdf"):
        p = tmp_path / name
        p.write_bytes(b"x")
        ctx.documents.upsert(_doc(p))
    names = [d.name for d in ctx.documents.list(limit=2, offset=0)]
    assert names == ["a.pdf", "b.pdf"]
    assert [d.name for d in ctx.documents.list(limit=500, offset=2)] == ["c.pdf"]


def test_分类树层级与路径名(bare_ctx) -> None:
    ctx = bare_ctx
    top = ctx.catalog.add_category("研究报告")
    child = ctx.catalog.add_category("人工智能", parent_id=top.id)
    grand = ctx.catalog.add_category("大模型", parent_id=child.id)
    assert (top.name_path, child.name_path, grand.name_path) == (
        "研究报告", "研究报告/人工智能", "研究报告/人工智能/大模型")
    tree = ctx.catalog.category_tree()
    assert [(c.name, lvl) for c, lvl in tree] == [("研究报告", 0), ("人工智能", 1), ("大模型", 2)]


def test_空分类名被拒绝并说明原因(ctx) -> None:
    with pytest.raises(DatabaseError, match="不能为空"):
        ctx.catalog.add_category("   ")


def test_父分类不存在时报错而不是静默建到根上(ctx) -> None:
    with pytest.raises(DatabaseError, match="父分类不存在"):
        ctx.catalog.add_category("孤儿", parent_id=4242)


def test_同层同名分类被唯一索引拒绝(bare_ctx) -> None:
    ctx = bare_ctx
    top = ctx.catalog.add_category("重复")
    ctx.catalog.add_category("子", parent_id=top.id)
    with pytest.raises(DatabaseError) as e:
        ctx.catalog.add_category("子", parent_id=top.id)
    assert "UNIQUE" in str(e.value).upper(), "错误里要留下 sqlite 原文，不然没法判断是谁拦的"
    assert ctx.catalog.count_categories() == 2


def test_不同层可以同名(bare_ctx) -> None:
    ctx = bare_ctx
    a = ctx.catalog.add_category("金融")
    b = ctx.catalog.add_category("报告")
    ctx.catalog.add_category("报告", parent_id=a.id)
    assert ctx.catalog.count_categories() == 3


def test_标签名大小写不敏感重复(ctx) -> None:
    ctx.catalog.add_tag("AI")
    with pytest.raises(DatabaseError):
        ctx.catalog.add_tag("ai")
    assert ctx.catalog.count_tags() == 1


def test_文档挂标签与分类并查得回(ctx, tmp_path) -> None:
    p = tmp_path / "doc.pdf"
    p.write_bytes(b"x")
    doc = ctx.documents.upsert(_doc(p))
    cat = ctx.catalog.add_category("课件")
    tag = ctx.catalog.add_tag("2026")

    assert ctx.catalog.link_category(doc.id, cat.id) is True
    assert ctx.catalog.link_category(doc.id, cat.id) is False, "重复关联要幂等，不许报错也不许两行"
    assert ctx.catalog.link_tag(doc.id, tag.id) is True
    assert ctx.catalog.link_tag(doc.id, tag.id) is False
    assert [c.name for c in ctx.catalog.categories_of(doc.id)] == ["课件"]
    assert [t.name for t in ctx.catalog.tags_of(doc.id)] == ["2026"]
    assert ctx.catalog.unlink_tag(doc.id, tag.id) is True
    assert ctx.catalog.tags_of(doc.id) == []


def test_AI建议默认未确认并且不顶掉人工确认(ctx, tmp_path) -> None:
    """SPEC 3.3：AI 分类建议未经人工确认不得触发文件动作 —— 落库时必须留得下这个区别。"""
    p = tmp_path / "doc.pdf"
    p.write_bytes(b"x")
    doc = ctx.documents.upsert(_doc(p))
    cat = ctx.catalog.add_category("行业报告")
    tag = ctx.catalog.add_tag("待定")
    assert ctx.catalog.link_category(doc.id, cat.id, origin="ai", confirmed=0) is True
    conn = ctx.engine.thread_connection()
    row = conn.execute("SELECT origin, confirmed FROM document_categories"
                       " WHERE doc_id=? AND category_id=?", (doc.id, cat.id)).fetchone()
    assert (row["origin"], row["confirmed"]) == ("ai", 0)


def test_关联不存在的文档时被外键拦住(ctx) -> None:
    cat = ctx.catalog.add_category("存在")
    with pytest.raises(DatabaseError) as e:
        ctx.catalog.link_category(9999, cat.id)
    assert "FOREIGN KEY" in str(e.value).upper(), "要把 sqlite 原文留下，才知道是外键拦的还是索引拦的"


def test_监测根增删改查且不碰磁盘(ctx, tmp_path) -> None:
    root = tmp_path / "文档目录"
    root.mkdir()
    key = identity_key(root)
    added = ctx.roots.add(str(root).replace("\\", "/"), key, label="我的 PDF")
    assert added.enabled == 1 and added.label == "我的 PDF"
    assert ctx.roots.count() == 1

    assert ctx.roots.set_enabled(key, False) is True
    assert ctx.roots.list()[0].enabled == 0
    # 重新添加 = 重新启用，且不许变两条
    again = ctx.roots.add(str(root).replace("\\", "/"), key)
    assert ctx.roots.count() == 1 and again.enabled == 1
    assert ctx.roots.set_enabled("不存在的键", True) is False

    assert ctx.roots.remove(key) is True
    assert ctx.roots.count() == 0
    assert root.is_dir(), "移除监测配置绝不能删用户的目录"


def test_任务入队与按状态读取(ctx, tmp_path) -> None:
    p = tmp_path / "doc.pdf"
    p.write_bytes(b"x")
    doc = ctx.documents.upsert(_doc(p))
    a = ctx.jobs.enqueue("scan", doc.id)
    ctx.jobs.enqueue("index", doc.id, priority=1)
    assert a.state == "queued" and a.progress == 0.0
    assert [j.kind for j in ctx.jobs.list()] == ["index", "scan"], "默认只看在跑的和排队的，按优先级排"
    assert ctx.jobs.count() == 2 and ctx.jobs.count("queued") == 2
    assert ctx.jobs.counts_by_state() == {"queued": 2}
    with pytest.raises(ValueError):
        ctx.jobs.list(states=())


def test_应用内部状态读写跨类型且覆盖生效(bare_ctx) -> None:
    ctx = bare_ctx
    for key, value in (("int", 7), ("str", "中文"), ("dict", {"a": 1}), ("list", [1, 2]),
                       ("bool", False), ("null", None)):
        ctx.app_settings.set(key, value)
    for key, value in (("int", 7), ("str", "中文"), ("dict", {"a": 1}), ("list", [1, 2]),
                       ("bool", False), ("null", None)):
        assert ctx.app_settings.get(key) == value
        assert isinstance(ctx.app_settings.get(key), type(value))
    assert ctx.app_settings.get("没这个键") is None
    assert ctx.app_settings.get("没这个键", "兜底") == "兜底"
    ctx.app_settings.set("int", 8)
    assert ctx.app_settings.get("int") == 8 and ctx.app_settings.count() == 6
    assert ctx.app_settings.all_keys() == ["bool", "dict", "int", "list", "null", "str"]


def test_分类标签和设置跨重启还在(data_root) -> None:
    """阶段 1 验收第 3 条。关连接重开 = 进程重启，内存里什么都没了才算数。"""
    first = bootstrap(data_root)
    cat = first.catalog.add_category("跨重启分类")
    tag = first.catalog.add_tag("跨重启标签")
    first.app_settings.set("窗口几何", {"w": 1200, "h": 800})
    first.roots.add("H:/docs", identity_key("H:/docs"))
    first.jobs.enqueue("scan")
    first.shutdown()

    second = bootstrap(data_root)
    try:
        assert [c.name for c in second.catalog.list_categories() if c.name == "跨重启分类"]
        assert [t.name for t in second.catalog.list_tags() if t.name == "跨重启标签"]
        assert second.app_settings.get("窗口几何") == {"w": 1200, "h": 800}
        assert second.roots.count() == 1
        assert second.jobs.count() == 1
        assert second.status.read().categories == second.catalog.count_categories()
    finally:
        second.shutdown()


def test_默认模板种过就不再长回来(data_root) -> None:
    """SPEC 3.3 说模板是"初始建议，可删"。用户把模板全删掉以后表也是空的，
    启动流程不许把它再变回来 —— 那等于覆盖用户的删除动作。"""
    first = bootstrap(data_root)
    assert first.catalog.count_categories() == 14, "SPEC 3.3 列举的两个顶层 + 各自子项"
    conn = first.engine.thread_connection()
    tops = conn.execute("SELECT count(*) FROM categories WHERE parent_id IS NULL").fetchone()[0]
    assert tops == 2
    conn.execute("DELETE FROM categories")
    conn.commit()
    assert first.catalog.count_categories() == 0
    first.shutdown()

    second = bootstrap(data_root)
    try:
        assert second.seed.skipped is True
        assert second.catalog.count_categories() == 0, "用户删空的分类树被启动流程复活了"
    finally:
        second.shutdown()


def test_时间戳口径只有一个(data_root) -> None:
    """AGENTS.md 禁止核心概念多个口径：库里的时间必须是 UTC unix 秒，且来自 now_ts()。"""
    ctx = bootstrap(data_root)
    tag = ctx.catalog.add_tag("时间戳")
    conn = ctx.engine.thread_connection()
    row = conn.execute("SELECT created_at FROM tags WHERE id=?", (tag.id,)).fetchone()
    assert abs(row["created_at"] - now_ts()) <= 5
    assert isinstance(row["created_at"], int) and row["created_at"] > 1_700_000_000
    ctx.shutdown()
