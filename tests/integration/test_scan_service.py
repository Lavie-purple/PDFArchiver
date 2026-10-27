"""扫描与对账（阶段 2 第 1–5 条 + 第 10 条的扫描半边）。

覆盖的不只是"能跑"，而是 SPEC 阶段 2 逐条安全要求：
扫描不许动用户文件、重叠根不许出两条主记录、不许只靠路径判内容变化、
不许把同名文件自动合并、文件删了不许继续当有效结果。

全部跑真目录 + 真文件系统调用，不 mock 数据库（D-012）。
唯一被替换的函数是 `fs.scanner.read_identity`（模拟磁盘故障），那是文件系统边界，不是库。
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from pdfarchiver.db.models import TextPage
from pdfarchiver.fs.identity import identity_key, normalize_path
from pdfarchiver.fs.watcher import CREATED, DELETED, MOVED, FsEvent
from pdfarchiver.jobs.queue import JobCancelled
from pdfarchiver.services.scan_service import (ADOPTED, ADDED, CHANGED, GONE, MISSING, UNCHANGED,
                                               ScanService)


def _mark_done(ctx, doc_id: int, *, fts: str = "done") -> None:
    ctx.documents.mark_index_result(doc_id, sha256=None, page_count=1, parse_status="ok",
                                    text_status="native", text_bearing_rate=1.0,
                                    fts_status=fts, ocr_status="na")


def _finish_all_index_jobs(ctx) -> None:
    """把队列里的任务全部结掉并清空，好让下一句"排了几条"的断言只数这次的。"""
    for job in ctx.jobs.list():
        ctx.jobs.succeed(int(job.id))  # type: ignore[arg-type]
    ctx.jobs.clear_finished()


def _doc_id(ctx, path) -> int:
    return int(ctx.documents.facts_by_key(identity_key(str(path))).doc_id)  # type: ignore[arg-type]


# —— 首次全量扫描 ————————————————————————————————————————

def test_首次扫描把树里每份PDF建成一条主记录(ctx, root, make_pdf) -> None:
    r = root("语料")
    base = Path(r.root_path)
    make_pdf("语料/人工智能产业年度报告.pdf", pages=2)
    make_pdf("语料/子目录/合同审阅要点.pdf")
    (base / "子目录" / "说明.txt").write_text("不是 PDF", encoding="utf-8")

    report = ctx.scan.scan_root(r)

    assert (report.pdfs, report.added, report.other_ext, report.unchanged) == (2, 2, 1, 0), \
        report.summarize()
    assert not report.has_errors
    assert ctx.documents.count() == 2
    assert report.index_enqueued == 2, "新建的文档必须当场排上索引，否则扫完还是搜不到东西"
    assert ctx.jobs.count("queued") == 2


def test_扫描不移动不删除不改写任何用户文件(ctx, root, make_pdf) -> None:
    """SPEC 3.6 / 阶段 2 安全要求：扫描阶段只读。断言靠"扫描前后磁盘逐字节一致"。"""
    r = root("只读检查")
    paths = [Path(make_pdf("只读检查/a.pdf")), Path(make_pdf("只读检查/嵌套/b.pdf"))]
    note = Path(r.root_path) / "嵌套" / "note.md"
    note.write_text("原样", encoding="utf-8")
    paths.append(note)
    before = {p: (p.stat().st_size, p.stat().st_mtime_ns) for p in paths}

    ctx.scan.scan_root(r)
    ctx.scan.scan_root(r)          # 第二遍走"已存在"分支，那一支同样不许碰磁盘

    assert {p: (p.stat().st_size, p.stat().st_mtime_ns) for p in paths} == before
    assert all(p.exists() for p in paths)


def test_再扫一遍全是未变且不重复排索引(ctx, root, make_pdf) -> None:
    """两个判据都要成立：队列里已有未终结任务时去重；任务跑完（索引状态变 done）后也不再排。"""
    r = root("重复扫")
    for i in range(3):
        make_pdf(f"重复扫/f{i}.pdf")

    first = ctx.scan.scan_root(r)
    second = ctx.scan.scan_root(r)
    assert (first.added, second.added, second.unchanged) == (3, 0, 3)
    assert second.index_enqueued == 0, "同一份文档没变还再排一次索引，队列会被扫描刷满"

    _finish_all_index_jobs(ctx)
    for fact in ctx.documents.scan_states_under(r.root_key):
        _mark_done(ctx, fact.doc_id)
    third = ctx.scan.scan_root(r)
    assert (third.unchanged, third.index_enqueued) == (3, 0), \
        "已经索引好的文档，重扫不该再抽一遍正文"


# —— 重叠监测根 ————————————————————————————————————————

def test_重叠根下同一文件只有一条主记录且状态不被冲掉(ctx, root, make_pdf) -> None:
    """SPEC 阶段 2 第 3 条。"状态不被冲掉"是真危险：父根扫到已索引完的文件时，
    如果 upsert 把 fts_status 打回 pending，用户加一个根就等于把全库重抽一遍。"""
    parent = root("文档库")
    child_dir = Path(parent.root_path) / "工作"
    child_dir.mkdir(parents=True, exist_ok=True)
    make_pdf("文档库/工作/季度预算.pdf")
    make_pdf("文档库/收件箱/发票.pdf")
    child = ctx.roots.add(str(child_dir).replace("\\", "/"), identity_key(child_dir), label="子根")

    a = ctx.scan.scan_root(parent)
    b = ctx.scan.scan_root(child)
    assert (a.pdfs, b.pdfs) == (2, 1)
    assert ctx.documents.count() == 2, "重叠根不许把同一份文件扫成两条（p7 实测口径）"
    assert (b.added, b.unchanged) == (0, 1)

    key = identity_key(str(child_dir / "季度预算.pdf"))
    _mark_done(ctx, int(ctx.documents.facts_by_key(key).doc_id))      # type: ignore[arg-type]
    again = ctx.scan.scan_root(parent)
    assert (again.unchanged, again.index_enqueued) == (2, 0)
    assert ctx.documents.facts_by_key(key).fts_status == "done"


# —— 新增 / 修改 / 改名 / 删除 ————————————————————————————

def test_内容变化看大小和时间而不是路径(ctx, root, make_pdf) -> None:
    """SPEC 阶段 2 安全要求「不能仅依赖路径判断文件内容是否变化」。
    同路径、内容换了 → 必须判 changed 并把索引状态打回 stale。"""
    r = root("改动")
    path = Path(make_pdf("改动/a.pdf"))
    ctx.scan.scan_root(r)
    assert ctx.scan.scan_root(r).unchanged == 1
    before = ctx.documents.facts_by_key(identity_key(str(path)))
    assert before.fts_status == "pending"

    make_pdf("改动/a.pdf", pages=3, lines=["换过内容的第二版正文，字符足够长能判出有正文。"])
    report = ctx.scan.scan_root(r)

    assert (report.changed, report.unchanged) == (1, 0), report.summarize()
    after = ctx.documents.facts_by_key(identity_key(str(path)))
    assert after.fts_status == "stale" and after.doc_id == before.doc_id
    assert after.size_bytes != before.size_bytes and after.mtime_ns != before.mtime_ns


def test_改名被认出来并保住主键与索引状态(ctx, root, make_pdf) -> None:
    """SPEC 阶段 2 第 4 条。认出改名靠 (device_id, file_id)，不是靠文件名。"""
    r = root("改名")
    old = Path(make_pdf("改名/原名.pdf"))
    ctx.scan.scan_root(r)
    doc_id = _doc_id(ctx, old)
    _mark_done(ctx, doc_id)

    new = old.with_name("新名.pdf")
    old.rename(new)
    report = ctx.scan.scan_root(r)

    assert (report.adopted, report.added, report.missing) == (1, 0, 0), report.summarize()
    assert ctx.documents.count() == 1
    moved = ctx.documents.get(doc_id)
    assert moved is not None and moved.path_key == identity_key(str(new))
    assert moved.fts_status == "done" and moved.missing_since is None, \
        "改名不改内容，正文没必要重抽"


def test_改名后内容也变了要一并重索引(ctx, root, make_pdf) -> None:
    """改名 + 原地编辑：inode 没变（`os.rename` 保住文件号），大小和 mtime 变了。
    必须同时得到"认出改名"和"重排一次索引"两个结论，缺一个就是要么丢了标注要么搜不到新内容。"""
    r = root("改名又改内容")
    old = Path(make_pdf("改名又改内容/一.pdf"))
    ctx.scan.scan_root(r)
    doc_id = _doc_id(ctx, old)
    _mark_done(ctx, doc_id)
    _finish_all_index_jobs(ctx)      # 队列按 doc_id 去重，不清掉首轮那条就没法证明这次真的重排了

    new = old.with_name("二.pdf")
    old.rename(new)
    with new.open("ab") as handle:            # 原地追加：文件号不变，内容变了
        handle.write(b"%trailing-comment\n")
    report = ctx.scan.scan_root(r)

    assert (report.adopted, report.index_enqueued) == (1, 1), report.summarize()
    assert ctx.documents.count() == 1 and ctx.documents.get(doc_id).fts_status == "stale"


def test_编辑器原子保存会被当成新文件而不是猜成同一个(ctx, root, make_pdf) -> None:
    """有些编辑器保存 = 写临时文件再替换（PyMuPDF 就是这样，实测 file_id 会变）。
    于是"改名后又用这类编辑器存过一次"在磁盘上确实是一个新文件对象：
    认不出来的那一份必须老实建新记录，而旧记录判缺失 —— 不许把两份合成一份。"""
    r = root("原子保存")
    old = Path(make_pdf("原子保存/一.pdf"))
    ctx.scan.scan_root(r)
    old_id = _doc_id(ctx, old)
    _mark_done(ctx, old_id)

    new = old.with_name("二.pdf")
    old.rename(new)
    make_pdf("原子保存/二.pdf", pages=2, lines=["重新保存过整份文件所以文件号也换了。"])
    report = ctx.scan.scan_root(r)

    assert (report.adopted, report.added, report.missing) == (0, 1, 1), report.summarize()
    assert ctx.documents.count() == 2
    assert ctx.documents.get(old_id).missing_since is not None
    assert ctx.documents.get(old_id).fts_status == "done", "旧记录的正文留在库里，找回来自不必重抽"


def _cross_volume_move(src: Path, dst: Path) -> None:
    """模拟 Windows 跨卷搬移：复制内容到新路径、保留 mtime、删源 —— 文件号因此换掉。"""
    st = src.stat()
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(src.read_bytes())
    os.utime(dst, ns=(st.st_atime_ns, st.st_mtime_ns))
    src.unlink()


def _pretend_new_inode(monkeypatch, path: Path, *, bump: int = 10_000_000) -> None:
    """只给 `path` 换一个文件号，模拟「同一份内容、不同 inode」——
    NTFS 上删源后号可能被复用，光靠真文件系统不能确定性地走到兜底分支。"""
    import pdfarchiver.services.scan_service as scan_mod
    from dataclasses import replace

    target = identity_key(str(path))
    real = scan_mod.read_identity

    def _read(raw):
        ident = real(raw)
        if ident.path_key != target:
            return ident
        return replace(ident, file_id=(ident.file_id or 0) + bump)

    monkeypatch.setattr(scan_mod, "read_identity", _read)


def test_跨卷搬移换掉inode后按文件事实认改名(ctx, tmp_path, root, make_pdf, monkeypatch) -> None:
    """**ISSUES I115** 甲：Windows 跨卷搬移 = 复制 + 删源，inode 换了，
    `by_inode` 认不出来。三条文件事实（名字/大小/mtime）全等且旧记录已判缺失时必须认，
    而且**主键不变** —— 用户打的分类、标签、正文索引都跟着这份文档走。"""
    a = root("D盘")
    b = root("H盘")
    src = Path(make_pdf("D盘/这本书能让你睡得好.pdf", pages=2))
    ctx.scan.scan_root(a)
    doc_id = _doc_id(ctx, src)
    _mark_done(ctx, doc_id)

    dst = Path(tmp_path) / "H盘" / src.name
    _cross_volume_move(src, dst)
    vanished = ctx.scan.scan_root(a)
    assert (vanished.missing, vanished.added) == (1, 0), vanished.summarize()
    assert ctx.documents.get(doc_id).missing_since is not None

    _pretend_new_inode(monkeypatch, dst)
    report = ctx.scan.scan_root(b)

    assert (report.adopted, report.added, report.missing) == (1, 0, 0), report.summarize()
    assert ctx.documents.count() == 1, "同一本书不许留下两条主记录"
    moved = ctx.documents.get(doc_id)
    assert moved is not None and moved.path_key == identity_key(str(dst))
    assert moved.missing_since is None and moved.fts_status == "done", \
        "内容没动，正文索引与缺失戳记都要原地跟着主键走"


@pytest.mark.parametrize("破点", ["mtime", "size"])
def test_跨卷搬移差一项文件事实就不认(ctx, tmp_path, root, make_pdf, monkeypatch, 破点) -> None:
    """兜底的判据是三项全等，差一项就不是同一份文件 —— 宁可多一条记录，不许错并。"""
    a = root("D盘")
    b = root("H盘")
    src = Path(make_pdf("D盘/合同.pdf"))
    ctx.scan.scan_root(a)
    _mark_done(ctx, _doc_id(ctx, src))

    dst = Path(tmp_path) / "H盘" / "合同.pdf"
    _cross_volume_move(src, dst)
    ctx.scan.scan_root(a)
    st = dst.stat()
    if 破点 == "mtime":
        os.utime(dst, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000_000))
    else:
        with dst.open("ab") as handle:
            handle.write(b"%changed\n")

    _pretend_new_inode(monkeypatch, dst)
    report = ctx.scan.scan_root(b)

    assert (report.adopted, report.added) == (0, 1), report.summarize()
    assert ctx.documents.count() == 2, "文件名相同不等于同一份文件"


def test_文件事实对上多条缺失记录时不猜改名(ctx, tmp_path, root, make_pdf, monkeypatch) -> None:
    """同名、同大小、同 mtime 的两条缺失记录（用户确实可能有两份一模一样的拷贝）：
    第三份出现时必须老实建新记录 —— 认哪条都是猜，而猜错就是把两份文档合成一份。"""
    a = root("甲盘")
    b = root("乙盘")
    src = Path(make_pdf("甲盘/同名.pdf"))
    payload = src.read_bytes()
    st = src.stat()
    twin = Path(tmp_path) / "乙盘" / "同名.pdf"
    twin.parent.mkdir(parents=True, exist_ok=True)
    twin.write_bytes(payload)
    os.utime(twin, ns=(st.st_atime_ns, st.st_mtime_ns))
    ctx.scan.scan_root(a)
    ctx.scan.scan_root(b)
    assert ctx.documents.count() == 2

    src.unlink()
    twin.unlink()
    ctx.scan.scan_root(a)
    ctx.scan.scan_root(b)
    assert ctx.documents.count_missing() == 2

    c = root("丙盘")
    third = Path(tmp_path) / "丙盘" / "同名.pdf"
    third.parent.mkdir(parents=True, exist_ok=True)
    third.write_bytes(payload)
    os.utime(third, ns=(st.st_atime_ns, st.st_mtime_ns))
    _pretend_new_inode(monkeypatch, third)
    report = ctx.scan.scan_root(c)

    assert (report.adopted, report.added) == (0, 1), report.summarize()
    assert ctx.documents.count() == 3


def test_同inode多候选时不猜改名而是各建一条(ctx, root, make_pdf) -> None:
    """硬链接：两条路径同一个 inode。`by_inode` 给出多条候选时**必须**各建一条记录 ——
    认哪条都是猜，而猜错的代价是把用户的两份文档合成一份（SPEC：禁止自动合并）。"""
    r = root("硬链接")
    src = Path(make_pdf("硬链接/原件.pdf"))
    link = Path(r.root_path) / "链接.pdf"
    try:
        os.link(src, link)
    except OSError as exc:                       # 文件系统不支持硬链接（FAT32 / 跨卷）
        pytest.skip(f"本机文件系统不支持硬链接：{type(exc).__name__}: {exc}")

    report = ctx.scan.scan_root(r)
    assert report.pdfs == 2, "两份都该被走到"
    assert (report.added, report.adopted) == (2, 0), report.summarize()
    assert ctx.documents.count() == 2


def test_不同目录的同名文件各一条记录(ctx, root, make_pdf) -> None:
    """「不能把同名文件自动合并」：身份是路径，不是文件名。"""
    r = root("同名")
    src = Path(make_pdf("同名/原件.pdf"))
    (Path(r.root_path) / "另一处").mkdir()
    (Path(r.root_path) / "另一处" / "原件.pdf").write_bytes(src.read_bytes())

    report = ctx.scan.scan_root(r)
    assert report.added == 2 and ctx.documents.count() == 2
    assert sorted(d.name for d in ctx.documents.list()) == ["原件.pdf", "原件.pdf"]


def test_删除只标缺失不删记录不删正文(ctx, root, make_pdf) -> None:
    r = root("删除")
    path = Path(make_pdf("删除/a.pdf"))
    ctx.scan.scan_root(r)
    doc_id = _doc_id(ctx, path)
    ctx.texts.replace_pages(doc_id, [TextPage(doc_id=doc_id, page_no=1, body="这一页正文要留在库里")])
    _mark_done(ctx, doc_id)

    path.unlink()
    report = ctx.scan.scan_root(r)

    assert report.missing == 1, report.summarize()
    assert ctx.documents.count() == 1 and ctx.documents.count_missing() == 1
    assert ctx.texts.count_pages(doc_id) == 1, "删记录容易，找回正文要重抽整本 —— 阶段 2 只改状态"
    doc = ctx.documents.get(doc_id)
    assert doc.missing_since is not None and doc.fts_status == "done"
    assert ctx.scan.scan_root(r).missing == 0, "已经标过的不许每轮再算一次"


def test_文件回来之后缺失戳记被摘掉(ctx, root, make_pdf) -> None:
    r = root("回来")
    path = Path(make_pdf("回来/a.pdf"))
    ctx.scan.scan_root(r)
    path.unlink()
    assert ctx.scan.scan_root(r).missing == 1

    make_pdf("回来/a.pdf")                     # 同名同路径放回，内容一致
    assert ctx.scan.scan_root(r).missing == 0
    assert ctx.documents.count_missing() == 0
    assert ctx.documents.facts_by_key(identity_key(str(path))).missing_since is None


def test_取消的扫描不判定缺失(ctx, root, make_pdf) -> None:
    """网络盘掉线 / 用户中途停止都会让"没看见"变成"看不见"，
    但只有走完整棵树才有资格说文件没了。"""
    r = root("取消")
    for i in range(4):
        make_pdf(f"取消/f{i}.pdf")
    assert ctx.scan.scan_root(r).added == 4
    (Path(r.root_path) / "f0.pdf").unlink()
    (Path(r.root_path) / "f1.pdf").unlink()

    report = ctx.scan.scan_root(r, should_stop=lambda: True)
    assert report.cancelled and report.missing == 0
    assert ctx.documents.count_missing() == 0, "中途取消就判缺失，等于把用户没删的文件说成删了"


def test_走完了才判缺失(ctx, root, make_pdf) -> None:
    """上一条的对照组：同一批删除，走完扫描就必须判出来 ——
    否则"不判缺失"可能只是因为整条链路根本没跑。"""
    r = root("走完")
    for i in range(2):
        make_pdf(f"走完/f{i}.pdf")
    ctx.scan.scan_root(r)
    (Path(r.root_path) / "f0.pdf").unlink()

    assert ctx.scan.scan_root(r).missing == 1


def test_根目录不存在时不判缺失也不崩(ctx, root) -> None:
    dead = Path(root("掉线").root_path + "_不存在")
    r = ctx.roots.add(str(dead).replace("\\", "/"), identity_key(dead))

    report = ctx.scan.scan_root(r)
    assert (report.pdfs, report.missing) == (0, 0)
    assert report.error_count == 1
    assert ctx.roots.by_key(r.root_key).last_scan_error is not None, \
        "根读不动必须在库里留下原文，否则状态页只会显示一个莫名的 0"


# —— 排除规则与错误条目 ——————————————————————————————————

def test_排除的文件不入库也不被判缺失(ctx, root, make_pdf) -> None:
    base_dir = Path(root("排除").root_path)
    r = ctx.roots.add(str(base_dir).replace("\\", "/"), identity_key(base_dir),
                      exclude_globs=["临时*"])
    (base_dir / "临时稿.pdf").write_bytes(b"%PDF-1.4\n%%EOF\n")
    make_pdf("排除/正式.pdf")

    report = ctx.scan.scan_root(r)
    assert (report.pdfs, report.excluded, report.added) == (1, 1, 1), report.summarize()
    assert ctx.documents.count() == 1
    assert ctx.scan.scan_root(r).missing == 0, \
        "排除=明知存在而不去动它，不能被缺失判定当成删掉了"


def test_排除整棵子树时不下钻(ctx, root, make_pdf) -> None:
    """内置规则 + 用户规则都走 `Exclusions`。整棵目录被排除时连条目都不产生（没进去看），
    所以这里的 pdfs 必须只有正式那一份。"""
    base_dir = Path(root("排除子树").root_path)
    r = ctx.roots.add(str(base_dir).replace("\\", "/"), identity_key(base_dir),
                      exclude_globs=["缓存"])
    (base_dir / "缓存").mkdir()
    (base_dir / "缓存" / "内部.pdf").write_bytes(b"%PDF-1.4\n%%EOF\n")
    make_pdf("排除子树/正式.pdf")

    report = ctx.scan.scan_root(r)
    assert (report.pdfs, report.added) == (1, 1)
    assert ctx.documents.count() == 1


def test_排除规则不是合法JSON时退回内置规则并继续扫(ctx, root, make_pdf) -> None:
    r = root("坏规则")
    make_pdf("坏规则/a.pdf")
    conn = ctx.engine.thread_connection()
    conn.execute("UPDATE monitored_roots SET exclude_globs='不是JSON' WHERE root_key=?", (r.root_key,))
    conn.commit()

    report = ctx.scan.scan_root(ctx.roots.by_key(r.root_key))
    assert (report.pdfs, report.added) == (1, 1), "配置坏了不该让整场扫描停住"


def test_一个读不动的条目不中断整场扫描(ctx, root, make_pdf, monkeypatch) -> None:
    """SPEC 阶段 2 安全要求「不能因文件解析失败而中止全部扫描」。"""
    r = root("坏条目")
    make_pdf("坏条目/a.pdf")
    make_pdf("坏条目/b.pdf")

    import pdfarchiver.fs.scanner as scanner

    original = scanner.read_identity

    def flaky(path):
        if str(path).replace("\\", "/").endswith("b.pdf"):
            raise OSError(13, "拒绝访问")
        return original(path)

    monkeypatch.setattr(scanner, "read_identity", flaky)
    report = ctx.scan.scan_root(r)

    assert (report.error_count, report.pdfs, report.added) == (1, 1, 1), report.summarize()
    assert report.has_errors and "拒绝访问" in report.errors[0], "错误必须留原文，不然没法远程诊断"
    assert ctx.documents.count() == 1
    assert ctx.roots.by_key(r.root_key).last_scan_error is not None


def test_错误原文只留前若干条但计数是全的(ctx, root, make_pdf, monkeypatch) -> None:
    from pdfarchiver.services.scan_service import MAX_ERROR_MESSAGES

    r = root("很多坏条目")
    total = MAX_ERROR_MESSAGES + 5
    for i in range(total):
        make_pdf(f"很多坏条目/f{i}.pdf")

    import pdfarchiver.fs.scanner as scanner

    def always_fail(path):
        raise OSError(22, "参数不对")

    monkeypatch.setattr(scanner, "read_identity", always_fail)
    report = ctx.scan.scan_root(r)

    assert report.error_count == total
    assert len(report.errors) == MAX_ERROR_MESSAGES, "全留下一万条原文没人看得完"
    saved = ctx.roots.by_key(r.root_key).last_scan_error
    assert saved.endswith(f"（另有 {total - 1} 条）"), saved


# —— 任务入口与断点续扫 ——————————————————————————————————

class _StubMonitor:
    """直接调 `handle` 用的假监视器：只记录调用，不碰库。
    队列与进度落库的行为在 `test_job_queue.py` 用真线程真库验过。"""

    def __init__(self, cancelled: bool = False) -> None:
        self.totals: list[int] = []
        self.advances = 0
        self._cancelled = cancelled

    def set_total(self, total: int) -> None:
        self.totals.append(total)

    def advance(self, n: int = 1) -> None:
        self.advances += n

    def cancelled(self) -> bool:
        return self._cancelled

    def flush(self) -> None:
        pass


def test_扫描任务的进度按根计(ctx, root, make_pdf) -> None:
    root("根一")
    root("根二")
    make_pdf("根一/a.pdf")

    monitor = _StubMonitor()
    ctx.scan.handle(ctx.jobs.enqueue("scan"), monitor)

    assert monitor.totals == [2] and monitor.advances == 2
    assert ctx.documents.count() == 1


def test_没有监测根时扫描任务不假装跑了什么(ctx) -> None:
    monitor = _StubMonitor()
    ctx.scan.handle(ctx.jobs.enqueue("scan"), monitor)
    assert monitor.totals == [] and monitor.advances == 0


def test_扫描任务被取消时抛队列认识的异常(ctx, root, make_pdf) -> None:
    """队列只认 `JobCancelled`。抛别的异常会被当成"瞬时故障"重试三次，
    用户点了停止却看到 attempts=3。"""
    root("取消异常")
    for i in range(3):
        make_pdf(f"取消异常/f{i}.pdf")

    with pytest.raises(JobCancelled):
        ctx.scan.handle(ctx.jobs.enqueue("scan"), _StubMonitor(cancelled=True))


def test_断点续扫只排未完成且还在磁盘上的(ctx, root, make_pdf) -> None:
    r = root("续跑")
    keep = Path(make_pdf("续跑/没抽.pdf"))
    done_path = Path(make_pdf("续跑/抽完了.pdf"))
    ctx.scan.scan_root(r)
    _finish_all_index_jobs(ctx)
    _mark_done(ctx, _doc_id(ctx, done_path))

    assert ctx.scan.resume_pending() == 1, "只有还没抽完的那份该回来"
    assert ctx.jobs.count("queued") == 1

    keep_id = _doc_id(ctx, keep)
    _finish_all_index_jobs(ctx)
    ctx.documents.set_fts_status(keep_id, "failed", error="故意留的失败原文")
    assert ctx.scan.resume_pending() == 0, \
        "failed 是「试过且知道为什么不行」，重排只会把同一个坏文件再烧一次重试预算"

    ctx.documents.set_fts_status(keep_id, "pending")
    keep.unlink()
    ctx.scan.scan_root(r)
    _finish_all_index_jobs(ctx)
    assert ctx.scan.resume_pending() == 0, "缺失的文档不该排一条必然失败的索引任务"


# —— 文件事件 ————————————————————————————————————————

def test_事件路径新增与删除各自走同一条对账(ctx, root, make_pdf) -> None:
    root("事件")
    path = Path(make_pdf("事件/新文件.pdf"))

    outcome = ctx.scan.reconcile_event(FsEvent(kind=CREATED, path=normalize_path(path),
                                               root_key="事件"))
    assert (outcome.action, outcome.needs_index) == (ADDED, True)
    assert ctx.documents.count() == 1

    path.unlink()          # 事件说的是"没了"，磁盘上也得真的没了，否则该听磁盘的
    outcome = ctx.scan.reconcile_event(FsEvent(kind=DELETED, path=normalize_path(path),
                                               root_key="事件"))
    assert outcome.action == MISSING
    assert ctx.documents.count_missing() == 1


def test_事件与磁盘现状冲突时听磁盘的(ctx, root, make_pdf) -> None:
    """watchdog 会重复、会乱序（P4 实测）。deleted 事件到达时文件还在，说明事件是过期的。"""
    root("冲突")
    path = Path(make_pdf("冲突/a.pdf"))
    ctx.scan.reconcile_event(FsEvent(kind=CREATED, path=normalize_path(path), root_key="冲突"))

    outcome = ctx.scan.reconcile_event(FsEvent(kind=DELETED, path=normalize_path(path),
                                               root_key="冲突"))
    assert (outcome.action, ctx.documents.count_missing()) == (UNCHANGED, 0)

    outcome = ctx.scan.reconcile_event(FsEvent(kind=MOVED, path=normalize_path(path),
                                               root_key="冲突", dest_path=None))
    assert outcome.action == UNCHANGED, "没有 dest 的移动事件按现状重算"


def test_移动的dest分支认新路径(ctx, root, make_pdf) -> None:
    root("移动")
    src = Path(make_pdf("移动/旧.pdf"))
    assert ctx.scan.reconcile_event(FsEvent(kind=CREATED, path=normalize_path(src),
                                            root_key="移动")).action == ADDED

    dst = src.with_name("新.pdf")
    src.rename(dst)
    outcome = ctx.scan.reconcile_event(FsEvent(kind=MOVED, path=normalize_path(src),
                                               root_key="移动", dest_path=normalize_path(dst)))
    assert outcome.action == ADOPTED, report_line(outcome)
    assert ctx.documents.count() == 1
    assert ctx.documents.facts_by_key(identity_key(str(dst))) is not None


def report_line(outcome) -> str:
    return f"移动事件的 dest 该被认成改名，实际得到 {outcome.action}"


def test_未知事件类型当场拒绝而不是当没事(ctx) -> None:
    with pytest.raises(ValueError, match="未知事件类型"):
        ctx.scan.reconcile_event(FsEvent(kind="watchdog 将来新加的", path="h:/x.pdf", root_key="r"))


def test_取不到身份的路径按消失处理(ctx, root) -> None:
    outcome = ctx.scan.reconcile_path(normalize_path(Path(root("无").root_path) / "没有这个文件.pdf"))
    assert (outcome.action, outcome.doc_id) == (GONE, None)


def test_路径写法不同也认同一个身份(ctx, root, make_pdf) -> None:
    """反斜杠 / 大小写混着来必须认出同一个文件（D-005）。`_vanish` 用的是 `identity_key()`，
    而不是 `str.lower()` —— 后者对非 ASCII 会算出另一个键。"""
    root("身份")
    path = Path(make_pdf("身份/A中文.pdf"))
    ctx.scan.reconcile_event(FsEvent(kind=CREATED, path=normalize_path(path), root_key="身份"))

    for raw in (str(path), str(path).upper()):
        outcome = ctx.scan.reconcile_event(FsEvent(kind=DELETED, path=raw, root_key="身份"))
        assert outcome.action == UNCHANGED, f"文件还在，事件只是带了另一种路径写法：{raw}"
    assert ctx.documents.count() == 1


def test_同一身份重复对账是幂等的(ctx, root, make_pdf) -> None:
    root("幂等")
    path = make_pdf("幂等/a.pdf")
    first = ctx.scan.reconcile_path(normalize_path(path))
    again = ctx.scan.reconcile_path(normalize_path(path))
    assert (first.action, again.action) == (ADDED, UNCHANGED)
    assert ctx.documents.count() == 1


def test_服务实例不持有跨调用状态(ctx, root, make_pdf) -> None:
    """队列 worker 线程与巡检线程共用一个实例，所以两个实例交替调用也不许多建记录。"""
    root("并发")
    path = make_pdf("并发/a.pdf")
    other = ScanService(ctx.documents, ctx.roots, ctx.jobs)
    actions = sorted([ctx.scan.reconcile_path(normalize_path(path)).action,
                      other.reconcile_path(normalize_path(path)).action])
    assert actions == sorted([ADDED, UNCHANGED])
    assert ctx.documents.count() == 1


def test_缺失判定只在同根子树内比较(ctx, root, make_pdf) -> None:
    """重叠根的安全面：甲根扫完不该把乙根独占的文件判缺失。"""
    a, b = root("甲根"), root("乙根")
    make_pdf("甲根/只在甲.pdf")
    make_pdf("乙根/只在乙.pdf")
    ctx.scan.scan_root(a)
    ctx.scan.scan_root(b)
    assert ctx.documents.count() == 2

    (Path(a.root_path) / "只在甲.pdf").unlink()
    assert ctx.scan.scan_root(a).missing == 1
    other = ctx.documents.facts_by_key(identity_key(str(Path(b.root_path) / "只在乙.pdf")))
    assert other.missing_since is None, "乙根的文件不该被甲根的走查判死"


def test_CHANGED与ADOPTED与ADDED是三个不同结论(ctx, root, make_pdf) -> None:
    """常量口径唯一性：界面按这四个词做统计，谁也不许被写成谁。
    断言方式是真的跑出三种结论，不是比字符串不相等。"""
    r = root("三口径")
    a = Path(make_pdf("三口径/a.pdf"))
    b = Path(make_pdf("三口径/b.pdf"))
    assert ctx.scan.reconcile_path(normalize_path(a)).action == ADDED
    assert ctx.scan.reconcile_path(normalize_path(b)).action == ADDED
    make_pdf("三口径/a.pdf", pages=2, lines=["这一版换了内容所以大小和时间都变了。"])
    assert ctx.scan.reconcile_path(normalize_path(a)).action == CHANGED
    b.rename(b.with_name("b2.pdf"))
    assert ctx.scan.reconcile_path(normalize_path(b.with_name("b2.pdf"))).action == ADOPTED
