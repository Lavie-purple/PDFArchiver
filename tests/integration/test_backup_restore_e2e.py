"""**备份 → 恢复到新目录 → 打开那个库**的端到端断言（阶段 4 SPEC 第一条验收，**ISSUES I81 甲**）。

这条验收原文是「恢复备份后，数据库结构、分类和索引状态符合预期」。在这之前仓库里的状态是：
备份与恢复的三个服务方法在场、S6 界面接线在场、迁移链安全有八条断言，但**没有任何一条测试走完
"备 → 恢 → 开 → 核对"** —— 唯一碰到 `restore_to_new_dir` 的测试（`test_ui_layout.py` 那条
"选中备份文件之后恢复标签页也不许顶宽"）把它 monkeypatch 掉了，验的是标签页宽度，不是恢复结果。
于是「恢复出来的库对不对」这件事从头到尾没有证据，而 S6 上点完按钮界面会显示成功。

三条断言各自钉住一个会坏的地方：

1. **逐键比数**：结构版本 + 六张表的行数 + 倒排花名册 + 正文字符数，备份前后逐个相等 —— 比总数更容易点名，
   坏法注入（在恢复落点偷偷 `DELETE FROM document_tags`）时红的是那一个键，不是一句"内容不一致"。
2. **索引状态跟着回来了**：恢复到新目录之后**直接在那个文件上跑一次 FTS `MATCH`**，
   命中要能落回那一页正文。只数行数的话，一个"表在、FTS 索引空了"的库照样绿 —— 而这恰好是
   用户看得见的坏（库里说有这一页、搜不到）。
3. **不许覆盖当前库**：目标目录里已经有 `catalog.db` 时必须 `FileExistsError`，
   一个都不许写进去（AGENTS.md「不许伪装成功」的反面：不许悄悄覆盖）。

`text_pages` 与 `content_fts_docsize` 都算：前者是"有几页正文"，后者是"这几页进没进倒排"，
两个数不等就是索引状态坏了，而这两件事在产品里是两个口径（见 **ISSUES I33** 那条 FTS 仪表）。

跑法：
    .venv/Scripts/python.exe -m pytest tests/integration/test_backup_restore_e2e.py -q
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from pdfarchiver.db.engine import Engine
from pdfarchiver.db.migrate import current_version
from pdfarchiver.db.models import Document, TextPage
from pdfarchiver.fs.identity import identity_key

COUNTS = {
    "documents": "SELECT count(*) FROM documents",
    "categories": "SELECT count(*) FROM categories",
    "document_categories": "SELECT count(*) FROM document_categories",
    "tags": "SELECT count(*) FROM tags",
    "document_tags": "SELECT count(*) FROM document_tags",
    "text_pages": "SELECT count(*) FROM text_pages",
    # 用影子表 `content_fts_docsize` 而不是 `count(*) FROM content_fts`：后者是**外部内容表**，
    # 2026-10-18 坏法注入实测 —— 恢复后把倒排 `delete-all` 清空，正文表原封不动，
    # `count(*) FROM content_fts` 照样报 2（同库的 `MATCH` 已经搜成 0 条）。
    # 拿它当"进没进索引"的读数等于没读（这与 `repositories/text.py` 里仪表选了 docsize
    # 花名册是同一个原因）。
    "fts_docsize": "SELECT count(*) FROM content_fts_docsize",
}
BODY = "这份样本正文里写着只有它才有的恢复专用句"
# 检索词必须 ≥3 字：`content_fts` 用 trigram 分词，两字查询走 FTS 会得到 0 条（阶段 2 实测，
# 见 `test_search_service.py` 模块 docstring 那条口径）。用两字来断言"索引回来了"会稳定假红。
FTS_QUERY = "恢复专用句"


def _readings(conn: sqlite3.Connection) -> dict[str, int]:
    """一个库的全部读数：结构版本 + 各表行数 + 正文字符总数。

    写成**字典**而不是一个元组：坏法注入时要能点名是哪一个数变了，
    `assert (14, 3, 8) != (14, 0, 8)` 这种红等于没红。
    """
    readings = {"schema_version": current_version(conn)}
    for key, sql in COUNTS.items():
        readings[key] = int(conn.execute(sql).fetchone()[0])
    readings["text_chars"] = int(conn.execute("SELECT coalesce(sum(char_count),0) "
                                              "FROM text_pages").fetchone()[0])
    return readings


@pytest.fixture
def library(ctx):
    """一份真有内容的库：三类标签、两份文档、各一页正文，其中一份挂了两条分类。

    默认种下的 14 个分类模板留着不动 —— 恢复出来的库连"模板有没有多长回来"也要一致，
    那是真实库里最常见的状态（空库反而什么都验不到）。
    """
    for name in ("待归档", "已核对", "临时"):
        ctx.catalog.add_tag(name)
    tags = ctx.catalog.list_tags()
    # 第一份不挂标签、第二份挂两条 —— 让 document_tags 有非零且不满的行数，
    # 恢复时漏挂/多挂才数得出来（全挂或全不挂都让这一列变成常数）。
    for n, (body, link) in enumerate(((BODY, ()), ("另一份样本写着另一句", tags[:2]))):
        path = f"D:\\恢复样本\\样本{n}.pdf"
        doc = ctx.documents.upsert(Document(
            path=path, path_key=identity_key(path), name=f"样本{n}.pdf",
            size_bytes=4096, mtime_ns=1_760_000_000_000_000_000 + n, sha256=f"{n:064x}",
            text_status="done", fts_status="done"))
        doc_id = int(doc.id)
        ctx.texts.replace_pages(doc_id, [TextPage(doc_id=doc_id, page_no=1, body=body,
                                                  char_count=len(body))])
        for tag in link:
            ctx.catalog.link_tag(doc_id, int(tag.id))
    return ctx


def test_恢复到新目录之后逐键读数与备份前相等(library, tmp_path) -> None:  # noqa: ANN001
    """阶段 4 验收「数据库结构、分类…符合预期」的可断言形式：**一个数一个数比**。"""
    before = _readings(library.engine.thread_connection())
    assert before["documents"] == 2 and before["text_pages"] == 2 \
        and before["document_tags"] == 2 and before["fts_docsize"] == 2, \
        f"夹具自己没把库建起来（含 FTS 触发器有没有把两页写进倒排），这条断言就成空指：{before}"

    backup_path = library.backup.create_backup()
    restored = library.backup.restore_to_new_dir(backup_path, tmp_path / "restored")

    assert restored == tmp_path / "restored" / "catalog.db"
    assert restored != library.engine.path, "恢复到新目录的结果不许就是当前库那一份"
    engine = Engine(restored)
    try:
        # 用 thread_connection 而不是 connect()：后者新建的连接不在 `_local.conn` 上，
        # finally 里的 close_thread_connection() 关不到它 —— 等于在 Windows 上留一个
        # 还持着文件句柄的库（tmp_path 删不掉，且这条测试自己不知道）。
        after = _readings(engine.thread_connection())
    finally:
        engine.close_thread_connection()

    diff = {k: (before[k], after[k]) for k in before if before[k] != after.get(k)}
    assert not diff, f"恢复出来的库与备份前不平：{diff}（键=读数名，前=备份前，后=恢复后）"


def test_恢复出来的库当场搜得到那一页(library, tmp_path) -> None:  # noqa: ANN001
    """「索引状态符合预期」不能只数行数：表在而 FTS 索引空了，用户看到的就是"库里说有、搜不到"。"""
    library.backup.create_backup()
    restored = library.backup.restore_to_new_dir(
        library.backup.list_backups()[0]["path"], tmp_path / "restored2")

    conn = sqlite3.connect(str(restored))
    try:
        hit = conn.execute("SELECT rowid, body FROM content_fts WHERE content_fts MATCH ?",
                           (FTS_QUERY,)).fetchall()
    finally:
        conn.close()
    assert len(hit) == 1, f"恢复库里那句独有正文搜成 {len(hit)} 条（应为 1）：{hit}"
    assert BODY in str(hit[0][1]), f"命中的不是那句话：{hit[0][1]!r}"


def test_目标目录已有库时拒绝恢复且一个字节都不写(library, tmp_path) -> None:  # noqa: ANN001
    """恢复必须写到**新目录**：目标已经有 `catalog.db` 就报错，不能把人现在的库顶掉。"""
    backup_path = library.backup.create_backup()
    target = tmp_path / "已有库"
    target.mkdir()
    (target / "catalog.db").write_bytes(b"NOT-A-DB")

    with pytest.raises(FileExistsError):
        library.backup.restore_to_new_dir(backup_path, target)
    assert (target / "catalog.db").read_bytes() == b"NOT-A-DB", "拒绝之前已经把目标库覆盖了"
    assert not (target / "catalog.db-wal").exists(), "留下 WAL 残尸就是半个库"
