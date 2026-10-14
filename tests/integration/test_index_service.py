"""正文索引（阶段 2 第 6–9 条 + 第 10 条的索引半边）。

样本全是 PyMuPDF 现场生成的真 PDF，库是真 sqlite3（D-012：不许 mock 数据库）。
被替换的只有 `index_service.PdfReader` 一处 —— 用来造"某一页读不出来"这种
在磁盘上无法稳定复现的条件；那是解析层边界，不是库。

每条断言都对着 SPEC 阶段 2 的一句原话写：
「不能仅依赖路径判断内容是否变化」→ 改名后短路、追加后重抽；
「不能因文件解析失败而中止全部扫描」→ 单份失败只落自己的状态；
「不许继续显示虚假的有效结果」→ 失败与缺失的文档不得从正文里搜出来。

测试里 `scan_root` 一律在 `_doc_id` 之前：主记录是扫描建出来的，反过来的顺序
读到的是 None，而不是任何被测行为。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from pdfarchiver.db.models import TextPage
from pdfarchiver.fs.identity import identity_key
from pdfarchiver.indexing.normalize import normalize_page_text
from pdfarchiver.jobs.queue import JobCancelled, PermanentFailure, PROGRESS_STEP_PAGES
from pdfarchiver.parsing.pdf import PageText, PdfInfo, PdfReader
from pdfarchiver.search.service import FIELD_BODY, Criteria, SearchService
from pdfarchiver.services import index_service
from pdfarchiver.services.index_service import IndexOutcome


def _doc_id(ctx, path) -> int:
    return int(ctx.documents.facts_by_key(identity_key(str(path))).doc_id)  # type: ignore[arg-type]


def _clear_jobs(ctx) -> None:
    """结掉并清空队列。`enqueue` 按 (kind, doc_id) 去重，
    不清掉上一轮的待办，下一句「这次排了几条索引」就只是在数上一轮。"""
    for job in ctx.jobs.list():
        ctx.jobs.succeed(int(job.id))
    ctx.jobs.clear_finished()


def _index_all(ctx) -> list[int]:
    """把队列里的 index 任务同步跑完（不起线程），返回跑过的 doc_id。"""
    ids = [int(job.doc_id) for job in ctx.jobs.list() if job.kind == "index" and job.doc_id]
    for doc_id in ids:
        ctx.indexer.index_document(doc_id)
    _clear_jobs(ctx)
    return ids


def _search(ctx) -> SearchService:
    return SearchService(ctx.documents, ctx.metadata, ctx.texts)


class _Monitor:
    """页级进度与取消位。`cancel_after` 让它跑到第 N 页时开始要求停止。"""

    def __init__(self, *, cancel_after: int | None = None) -> None:
        self.totals: list[int] = []
        self.advances = 0
        self._cancel_after = cancel_after

    def set_total(self, total: int) -> None:
        self.totals.append(total)

    def advance(self, n: int = 1) -> None:
        self.advances += n

    def cancelled(self) -> bool:
        return self._cancel_after is not None and self.advances >= self._cancel_after


class _FakeReader:
    """假 PdfReader：页面由脚本给定。只用来造坏页，正文/哈希/库全是真的。"""

    def __init__(self, pages: list[PageText], info: PdfInfo) -> None:
        self._pages = pages
        self.info = info

    def __call__(self, path: str) -> "_FakeReader":
        return self

    def __enter__(self) -> "_FakeReader":
        return self

    def __exit__(self, *exc_info) -> bool:  # noqa: ANN002
        return False

    def iter_text_pages(self):
        yield from self._pages


def _fake_pages(monkeypatch, pages: list[PageText], *, page_count: int | None = None) -> None:
    monkeypatch.setattr(index_service, "PdfReader", _FakeReader(
        pages, PdfInfo(page_count=page_count if page_count is not None else len(pages))))


# —— 正常路径 ————————————————————————————————————————————

def test_原生文本PDF索引出正文页数与状态(ctx, root, make_pdf) -> None:
    """阶段 2 第 6、7 条：元数据、页数、正文都要落到库里。"""
    r = root("原生")
    path = Path(make_pdf("原生/年度报告.pdf", pages=3,
                         lines=["人工智能产业年度报告的总体结论", "第二章讲合同审阅要点与风险"]))
    ctx.scan.scan_root(r)
    doc_id = _doc_id(ctx, path)

    outcome = ctx.indexer.index_document(doc_id)

    assert (outcome.page_count, outcome.stored_pages) == (3, 3), outcome.describe()
    assert outcome.text_status == "native" and outcome.parse_status == "ok"
    assert outcome.fts_status == "done" and outcome.searchable
    doc = ctx.documents.get(doc_id)
    assert doc.text_bearing_rate == 1.0 and doc.last_error is None
    assert doc.last_indexed_at is not None, "状态页要回答「这份是什么时候索引好的」"
    assert len(doc.sha256 or "") == 64, "内容指纹是「有没有变」的唯一凭据，缺了它每次扫描都得重抽"
    assert ctx.texts.count_pages(doc_id) == 3


def test_索引只读不改动用户文件(ctx, root, make_pdf) -> None:
    """扫描与索引两条链路都不许碰磁盘（SPEC 3.6）。索引比扫描更危险：它真的在读整本内容。"""
    r = root("只读")
    path = Path(make_pdf("只读/合同.pdf", pages=2, lines=["合同审阅要点的第三条注意事项"]))
    before = (path.stat().st_size, path.stat().st_mtime_ns, path.read_bytes())

    ctx.scan.scan_root(r)
    ctx.indexer.index_document(_doc_id(ctx, path))

    after = path.stat()
    assert (after.st_size, after.st_mtime_ns) == (before[0], before[1])
    assert path.read_bytes() == before[2]


def test_PDF文档信息落进元数据表(ctx, root, make_pdf) -> None:
    """第 6 条的「元数据」半边：写进去的信息必须读得出来，否则元数据检索是空的。"""
    meta = {"title": "合同审阅要点汇编", "author": "法务内训组", "subject": "审阅规程",
            "keywords": "合同, 审阅, 风险"}
    r = root("元数据")
    path = Path(make_pdf("元数据/说明书.pdf", lines=["产品说明书正文的第一段落内容"], meta=meta))
    ctx.scan.scan_root(r)

    ctx.indexer.index_document(_doc_id(ctx, path))

    row = ctx.metadata.get(_doc_id(ctx, path))
    assert (row["title"], row["author"], row["subject"], row["keywords"]) == \
        ("合同审阅要点汇编", "法务内训组", "审阅规程", "合同, 审阅, 风险"), row
    assert {"producer", "creator_tool", "pdf_created_at"} <= set(row)


def test_索引进度按页推进(ctx, root, make_pdf) -> None:
    """第 10 条：进度是真的页数，不是模拟出来的百分比（AGENTS.md 禁止模拟进度）。"""
    r = root("进度")
    path = Path(make_pdf("进度/多页.pdf", pages=5, lines=["每一页都写满可判定的正文内容字符"]))
    ctx.scan.scan_root(r)
    monitor = _Monitor()

    ctx.indexer.index_document(_doc_id(ctx, path), monitor)

    assert monitor.totals == [5] and monitor.advances == 5


# —— 四类「读不出正文」的文件，处置各不相同 —————————————————

def test_纯扫描件判为无正文并挂上OCR待办(ctx, root, make_scanned_pdf) -> None:
    """p2 实测 37.5% 的语料是这种。它索引「成功」了（fts done）但没有正文可搜，
    `ocr_status='pending'` 是阶段 3 唯一认得的入口。"""
    r = root("扫描件")
    path = Path(make_scanned_pdf("扫描件/合同盖章页.pdf", pages=2))
    ctx.scan.scan_root(r)

    outcome = ctx.indexer.index_document(_doc_id(ctx, path))

    assert (outcome.text_status, outcome.ocr_status) == ("none", "pending"), outcome.describe()
    assert outcome.fts_status == "done" and outcome.page_count == 2
    assert not outcome.searchable, "没有文本层的文件不该从正文里搜出东西"
    assert ctx.texts.count_pages(int(outcome.doc_id)) == 0


def test_损坏PDF索引失败并留下原文(ctx, root, make_broken_pdf) -> None:
    """损坏件的处置是「这一份失败」，不是「这一批中止」（阶段 2 安全要求第 2 条）。"""
    r = root("损坏")
    path = Path(make_broken_pdf("损坏/截断的文件.pdf"))
    ctx.scan.scan_root(r)
    doc_id = _doc_id(ctx, path)

    with pytest.raises(PermanentFailure) as excinfo:
        ctx.indexer.index_document(doc_id)

    doc = ctx.documents.get(doc_id)
    assert (doc.parse_status, doc.text_status, doc.fts_status) == ("failed", "failed", "failed")
    assert doc.last_error, f"失败必须留原文，否则状态页只能说「这份搜不到」而给不出原因：{excinfo.value}"
    assert doc.text_bearing_rate is None, "没读过的比率不能填 0：0 是「一页都没字」，None 才是「不知道」"
    assert doc.page_count is None, "打不开就是不知道页数，拿上一次的数冒充这次的结论是假的"


def test_加密PDF标成需要密码而不是当成可读(ctx, root, make_encrypted_pdf) -> None:
    """阶段 2 不弹密码框（D-006 的边界）。但 `needs_pass=1` 必须落库，
    否则用户面对「搜不到」没有任何线索可循。"""
    r = root("加密")
    path = Path(make_encrypted_pdf("加密/机密合同.pdf"))
    ctx.scan.scan_root(r)
    doc_id = _doc_id(ctx, path)

    with pytest.raises(PermanentFailure, match="密码"):
        ctx.indexer.index_document(doc_id)

    doc = ctx.documents.get(doc_id)
    assert doc.needs_pass == 1 and doc.fts_status == "failed"
    assert "加密" in (doc.last_error or ""), doc.last_error
    assert doc.page_count == 1, "加密文件读得出目录、读不出正文，页数是真的，不该跟着丢"


def test_打开成功但一页都没读出来算失败而不是已索引(ctx, root, make_pdf, monkeypatch) -> None:
    """两个字段不许对同一件事各说一套：正文 0 行 + text_status=failed，
    而 fts_status=done 会让状态页显示「这份已索引」—— 那是 SPEC 禁止的虚假有效结果。"""
    r = root("空壳")
    path = Path(make_pdf("空壳/正常文件.pdf", pages=2, lines=["这里的内容被假读取器换成坏页了"]))
    ctx.scan.scan_root(r)
    doc_id = _doc_id(ctx, path)
    _fake_pages(monkeypatch, [PageText(1, error="页面对象损坏"), PageText(2, error="页面对象损坏")])

    with pytest.raises(PermanentFailure, match="整本读不出"):
        ctx.indexer.index_document(doc_id)

    doc = ctx.documents.get(doc_id)
    assert doc.fts_status == "failed" and doc.page_count == 2
    assert ctx.texts.count_pages(doc_id) == 0


def test_坏页不入库其余页照写(ctx, root, make_pdf, monkeypatch) -> None:
    """阶段 2 安全要求第 2 条的细粒度版本：一页坏 ≠ 整本坏。"""
    r = root("坏页")
    path = Path(make_pdf("坏页/混合.pdf", pages=3, lines=["正常页面的正文内容字符都在这里"]))
    ctx.scan.scan_root(r)
    doc_id = _doc_id(ctx, path)
    _fake_pages(monkeypatch, [
        PageText(1, text="第一页的正常正文内容字符都在这里了谢谢"),
        PageText(2, error="第 2 页交叉引用指向了非法对象"),
        PageText(3, text="第三页也照样能读出一整段正文内容"),
    ], page_count=3)

    outcome = ctx.indexer.index_document(doc_id)

    assert (outcome.page_count, outcome.stored_pages) == (3, 2), outcome.describe()
    assert outcome.parse_status == "degraded" and outcome.fts_status == "done"
    bodies = {p.page_no: p.body for p in ctx.texts.pages_of(doc_id)}
    assert set(bodies) == {1, 3}, f"坏页不许占一行空正文：{sorted(bodies)}"
    assert (ctx.documents.get(doc_id).last_error or "").startswith("第 2 页"), "第一条原文要留住给人查"


# —— 「内容有没有变」的口径 ————————————————————————————————

def test_哈希未变时不重抽正文(ctx, root, make_pdf) -> None:
    """短路必须真的短路：用哨兵行证明第二次没有覆盖库里内容。"""
    r = root("短路")
    path = Path(make_pdf("短路/同一份.pdf", pages=2, lines=["首次索引写入的正文内容字符"]))
    ctx.scan.scan_root(r)
    doc_id = _doc_id(ctx, path)
    ctx.indexer.index_document(doc_id)
    ctx.texts.replace_pages(doc_id, [TextPage(doc_id=doc_id, page_no=1, body="哨兵正文")])

    outcome = ctx.indexer.index_document(doc_id)

    assert outcome.skipped_unchanged and outcome.stored_pages == 1, outcome.describe()
    assert [p.body for p in ctx.texts.pages_of(doc_id)] == ["哨兵正文"], "短路却没短路，哨兵会被真正文覆盖"


def test_哈希相同但正文不在库里时必须重抽(ctx, root, make_pdf) -> None:
    """短路有两个条件，少一个都不许短：哈希没变**且**正文还在库里。
    清过库（或删过档）之后哈希照样对得上，此时短路等于宣布「这份能搜」而它一个字都搜不出来。"""
    r = root("正文没了")
    path = Path(make_pdf("正文没了/清过库.pdf", pages=2, lines=["清库之前索引进去的正文内容字符"]))
    ctx.scan.scan_root(r)
    doc_id = _doc_id(ctx, path)
    ctx.indexer.index_document(doc_id)
    assert ctx.texts.count_pages(doc_id) == 2

    ctx.texts.delete_for_doc(doc_id)
    ctx.documents.set_fts_status(doc_id, "stale")
    outcome = ctx.indexer.index_document(doc_id)

    assert not outcome.skipped_unchanged, "只看哈希的短路会把「库里没正文」盖成「已经索引好了」"
    assert ctx.texts.count_pages(doc_id) == 2
    assert outcome.stored_pages == 2 and outcome.fts_status == "done"


def test_改名不算内容变化所以不重抽(ctx, root, make_pdf) -> None:
    """SPEC 原话「不能仅依赖路径判断文件内容是否变化」。
    改名（同 inode、同字节）走完扫描 + 索引，得到的结论必须是「内容没变，跳过」。"""
    r = root("改名短路")
    path = Path(make_pdf("改名短路/原名.pdf", pages=2, lines=["改名之前的整页正文内容字符"]))
    ctx.scan.scan_root(r)
    doc_id = _doc_id(ctx, path)
    ctx.indexer.index_document(doc_id)

    renamed = path.with_name("新名.pdf")
    path.rename(renamed)
    report = ctx.scan.scan_root(r)
    outcome = ctx.indexer.index_document(doc_id)

    assert report.adopted == 1, report.summarize()
    assert outcome.skipped_unchanged, "改了名字就重抽，等于把 120.6GB 语料在重哈希之外再重读一遍"
    assert ctx.documents.get(doc_id).path_key == identity_key(str(renamed))


def test_内容变了必须重抽且旧正文不残留(ctx, root, make_pdf) -> None:
    """重抽是**整本替换**：新旧正文同时在场会让检索返回已经不存在的句子。"""
    r = root("改动")
    path = Path(make_pdf("改动/版本一.pdf", page_lines=[["第一版里独有的老措辞内容字符一二三四五"]]))
    ctx.scan.scan_root(r)
    doc_id = _doc_id(ctx, path)
    ctx.indexer.index_document(doc_id)
    old_hash = ctx.documents.get(doc_id).sha256
    _clear_jobs(ctx)

    make_pdf("改动/版本一.pdf", page_lines=[["第二版里独有的新措辞内容字符一二三四五"],
                                            ["第二版的另一页正文内容字符也在这里"]])
    report = ctx.scan.scan_root(r)
    assert (report.changed, report.index_enqueued) == (1, 1), report.summarize()
    assert ctx.documents.get(doc_id).fts_status == "stale"

    outcome = ctx.indexer.index_document(doc_id)

    assert not outcome.skipped_unchanged and outcome.page_count == 2
    assert ctx.documents.get(doc_id).sha256 != old_hash
    assert ctx.texts.count_pages(doc_id) == 2
    bodies = " ".join(p.body for p in ctx.texts.pages_of(doc_id))
    assert "新措辞" in bodies and "老措辞" not in bodies, bodies
    assert ctx.texts.check_fts_consistency().aligned, "外部内容表与正文表两张皮（漏索引或花名册残留）"


def test_入库正文只压空白其余一字不改(ctx, root, make_pdf) -> None:
    """第 6 条「可读取正文文本」的口径：库里存的必须就是提取出来的东西（只做空白归一）。
    任何「整理」（截断、去标点、改大小写）都会让用户搜不到他亲眼看见的词。"""
    r = root("原样")
    path = Path(make_pdf("原样/正文.pdf", pages=2, lines=["第七章  附则   与补充说明的内容"]))
    ctx.scan.scan_root(r)
    doc_id = _doc_id(ctx, path)
    ctx.indexer.index_document(doc_id)

    with PdfReader(str(path)) as reader:
        raw = [p.text for p in reader.iter_text_pages()]
    stored = {p.page_no: p.body for p in ctx.texts.pages_of(doc_id)}
    assert stored == {i + 1: normalize_page_text(t) for i, t in enumerate(raw)}
    assert "附则" in stored[1] and "补充说明" in stored[1], str(stored)[:120]


# —— 取消、缺失与用法错误 ————————————————————————————————

def test_取消发生在写库之前旧正文与状态都不动(ctx, root, make_pdf) -> None:
    """半途写进去的正文会让「这份索引好了」和「这份没索引好」看不出区别。
    页级取消检查每 `PROGRESS_STEP_PAGES` 页一次，所以样本必须比它长，否则测不到那一支。"""
    pages = PROGRESS_STEP_PAGES + 1
    r = root("取消")
    path = Path(make_pdf("取消/长文件.pdf", pages=pages, lines=["第一版里可被搜到的正文内容字符"]))
    ctx.scan.scan_root(r)
    doc_id = _doc_id(ctx, path)
    ctx.indexer.index_document(doc_id)
    _clear_jobs(ctx)
    before = ctx.documents.get(doc_id)

    with path.open("ab") as handle:            # 原地追加：内容变了、文件号没变
        handle.write(b"% appended trailing comment\n")
    ctx.scan.scan_root(r)
    assert ctx.documents.get(doc_id).fts_status == "stale"

    with pytest.raises(JobCancelled):
        ctx.indexer.index_document(doc_id, _Monitor(cancel_after=PROGRESS_STEP_PAGES))

    after = ctx.documents.get(doc_id)
    assert after.fts_status == "stale", "取消不是失败：写成 failed 会吃掉重试预算，写成 done 是假完成"
    assert (after.sha256, after.last_indexed_at, after.page_count) == \
        (before.sha256, before.last_indexed_at, before.page_count)
    assert ctx.texts.count_pages(doc_id) == pages, "旧正文得整本留着，直到新版一次写完"


def test_文件已不在磁盘上时补缺失戳记并判死(ctx, root, make_pdf) -> None:
    """索引任务排在前面、文件随后被删：这一份必须既被标缺失又被判永久失败，
    缺一条就是「搜索里继续出现一份已经不存在的文档」。"""
    r = root("索引时没了")
    path = Path(make_pdf("索引时没了/会被删掉.pdf", lines=["删掉之前还没索引过的内容字符"]))
    ctx.scan.scan_root(r)
    doc_id = _doc_id(ctx, path)
    path.unlink()

    with pytest.raises(PermanentFailure, match="已不在磁盘"):
        ctx.indexer.index_document(doc_id)

    assert ctx.documents.get(doc_id).missing_since is not None, "只抛异常不补戳记，库里那条还是「有效」"


def test_主记录不存在时判永久失败(ctx) -> None:
    """库里的行没了（删档、清库）而任务还在队列里。重试不会凭空变出一条记录。"""
    with pytest.raises(PermanentFailure, match="不存在"):
        ctx.indexer.index_document(4242)


def test_任务没有doc_id时拒绝而不是扫全库(ctx) -> None:
    """全量扫描是 `scan` 任务的活。让它共用索引入口，就会有一条没人审计的「顺手重抽整盘」路径。"""
    job = ctx.jobs.enqueue("index")
    assert job is not None and job.doc_id is None

    with pytest.raises(PermanentFailure, match="doc_id"):
        ctx.indexer.handle(job, _Monitor())


def test_经handler跑完的索引与直接调用同结果(ctx, root, make_pdf) -> None:
    """`handle` 是队列唯一的入口，它和 `index_document` 之间不许有第二种行为。"""
    r = root("入口")
    path = Path(make_pdf("入口/任务入口.pdf", pages=2, lines=["经由任务队列索引出来的正文内容"]))
    ctx.scan.scan_root(r)
    doc_id = _doc_id(ctx, path)
    _clear_jobs(ctx)                      # 扫描已经排过一条，这条要自己排，才能拿到 job 对象
    job = ctx.jobs.enqueue("index", doc_id, dedupe=False)

    ctx.indexer.handle(job, _Monitor())

    doc = ctx.documents.get(doc_id)
    assert doc.fts_status == "done" and doc.text_status == "native"
    assert doc.sha256 and doc.page_count == 2


# —— 索引完之后要真的搜得到（第 8、9 条的最低闭环） —————————

def test_索引完能从正文搜出命中页码与片段(ctx, root, make_pdf) -> None:
    """阶段 2 验收原话「必须展示真实搜索结果」，交的就是这几行。
    两页写不同内容（`page_lines`），否则页码归属永远只会验到第 1 页。"""
    r = root("检索")
    make_pdf("检索/第一本.pdf", page_lines=[
        ["合同审阅要点集中在第三条风险条款"],
        ["另一页讲的是付款节点与验收标准"],
    ])
    make_pdf("检索/第二本.pdf", lines=["人工智能产业年度报告的总体结论与展望"])
    ctx.scan.scan_root(r)
    assert _index_all(ctx) == [1, 2], "扫描排上的两条索引任务都得跑完，否则后面搜不到东西"

    result = _search(ctx).search(Criteria(text="合同审阅要点", in_fields=(FIELD_BODY,)))

    assert result.channel == "fts", result.channel_label
    assert len(result.hits) == 1, [h.doc.name for h in result.hits]
    hit = result.hits[0]
    assert hit.doc.name == "第一本.pdf" and hit.page_no == 1, "页码口径与阅读器一致：从 1 开始"
    assert "合同审阅要点" in hit.snippet.line(), hit.snippet.line()
    assert hit.highlight() is not None

    other = _search(ctx).search(Criteria(text="付款节点", in_fields=(FIELD_BODY,)))
    assert [(h.doc.name, h.page_no) for h in other.hits] == [("第一本.pdf", 2)], other.rows()
    print("\n".join(result.lines() + other.rows()))


def test_索引失败的文档不从正文里搜出来(ctx, root, make_broken_pdf, make_pdf) -> None:
    """坏文件不能因为「扫到了就有条目」而出现在检索里（虚假有效结果）。"""
    r = root("失败不可搜")
    good = Path(make_pdf("失败不可搜/好的.pdf", lines=["可搜索的正常正文内容字符都在这里"]))
    Path(make_broken_pdf("失败不可搜/坏的.pdf"))
    ctx.scan.scan_root(r)
    for job in ctx.jobs.list():
        if job.kind == "index" and job.doc_id:
            try:
                ctx.indexer.index_document(int(job.doc_id))
            except PermanentFailure:
                pass
    _clear_jobs(ctx)

    hits = _search(ctx).search(Criteria(text="正文内容", in_fields=(FIELD_BODY,))).hits

    assert [h.doc.name for h in hits] == ["好的.pdf"], [h.doc.name for h in hits]
    assert ctx.documents.get(_doc_id(ctx, good)).fts_status == "done"


def test_检索摘要里文档数与命中行数各算各的(ctx, root, make_pdf) -> None:
    """AGENTS.md「禁止核心概念有多个口径」：`matching_documents` 与命中行数不是同一个数。"""
    r = root("计数")
    for i in range(3):
        make_pdf(f"计数/第{i}本.pdf", lines=[f"同一句话出现在三本文档里的内容{i}"])
    ctx.scan.scan_root(r)
    assert len(_index_all(ctx)) == 3

    result = _search(ctx).search(Criteria(text="同一句话", in_fields=(FIELD_BODY,)))

    assert result.matching_documents == 3, "符合筛选的文档数与命中它的行数各算各的"
    assert len(result.hits) == 3 and result.counts_by_field == {FIELD_BODY: 3}
    assert result.truncated_fields == ()


def test_短路索引给出的结论写在describe里(ctx, root, make_pdf) -> None:
    """状态页要能说「这份没重抽」。短路是个真实结论，不是省略。"""
    r = root("结论")
    path = Path(make_pdf("结论/样本.pdf", pages=20, lines=["用来观察短路结论的正文内容字符"]))
    ctx.scan.scan_root(r)
    doc_id = _doc_id(ctx, path)
    ctx.indexer.index_document(doc_id)
    _clear_jobs(ctx)

    second = ctx.indexer.index_document(doc_id)

    assert isinstance(second, IndexOutcome) and second.skipped_unchanged
    assert second.describe().endswith("跳过重抽"), second.describe()
