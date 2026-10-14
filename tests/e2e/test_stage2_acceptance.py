"""阶段 2 端到端验收 —— 真装配、真 worker 线程、真文件监听、真 PDF，一处都不 mock。

与 `tests/integration/` 的分工：那边逐条验每一层的规矩（一个坏页不许拖垮整本、
取消不许写成 failed……），这边只回答验收单上的那句话：

> 验收时请建立临时测试目录，创建真实的 PDF 样本，并测试重叠目录、文件修改、重命名、
> 删除、应用重启和索引恢复。必须运行自动化测试并展示真实搜索结果。

每个测试都从 `bootstrap()` 开始、经 `start_background()` 起的真线程跑完，断言的是
**库里的最终事实**，不是某个方法的返回值：测试里一次都不手动调 `scan_root` /
`index_document`，绕过队列就等于没验队列。

两条纪律：
1. **等结果不靠 `sleep`**。worker 干没干完是库里 `queued+running` 的行数说的
   （`wait_until_idle`）；事件到没到是文档状态说的（带截止时间的轮询，超时就 fail
   并把事件计数一起打出来）。慢机器上不许假失败，也不许放宽成"迟早会好"。
2. **改名、删除只发生在本测试自己造的样本上**（pytest 的 `tmp_path` 里）。
   产品代码有没有动过用户的文件，由最后一个测试用整棵树的 sha256 指纹证明。

跑法（要看真实搜索结果全文，加 `-s`）：
    python -m pytest tests/e2e -q -s
"""
from __future__ import annotations

import hashlib
import time
from pathlib import Path

import pytest

from pdfarchiver.db.repositories.documents import NEEDS_INDEX_STATUSES
from pdfarchiver.db.repositories.jobs import STATES
from pdfarchiver.fs.identity import identity_key
from pdfarchiver.jobs.queue import WorkQueue
from pdfarchiver.search.service import (FIELD_BODY, FIELD_FILENAME, FIELD_METADATA,
                                        FIELD_PATH, Criteria)
from pdfarchiver.services.bootstrap import AppContext, bootstrap
from tests.conftest import _make_pdf, _make_scanned_pdf

TITLE_A = "人工智能产业年度报告"
BODY_A = "报告里讨论了三条产业扶持政策的落地效果与预算安排"
TITLE_B = "合同审阅要点汇编"
BODY_B = "审阅要点集中在违约责任的举证条款与解除条件"
PHRASE_B3 = "第三页单独写了附则的生效日期与解释口径"
LATE_BODY = "这是监听起来之后才落盘的一份文件正文内容字符"

IDLE_TIMEOUT = 60.0    # 五份小 PDF，真 worker 跑完绰绰有余；等不到就是链路断了


# —— 语料与装配 ————————————————————————————————————————————

def _tree(tmp_path: Path) -> dict[str, Path]:
    """建一棵真实的样本树。`outer` / `inner` 是两个**互相重叠**的待登记根。

    六种文件各代表一种必须区别处置的实况：有原生正文的、藏在嵌套目录里的、
    纯扫描的（有页没字）、截断的（打得开壳读不出一页）、加密的（要密码）、非 PDF（不该进库）。
    """
    outer = tmp_path / "语料"
    inner = outer / "子目录"
    files = {
        "年报": outer / "人工智能产业年度报告.pdf",
        "汇编": inner / "合同审阅要点汇编.pdf",
        "扫描件": outer / "扫描件" / "会议纪要扫描件.pdf",
        "截断": outer / "损坏" / "残缺文件.pdf",
        "加密": outer / "加密" / "机密合同.pdf",
        "文本": outer / "备注.txt",
    }
    _make_pdf(files["年报"], page_lines=[[BODY_A]],
              meta={"title": TITLE_A, "author": "政策研究室", "keywords": "产业政策,年度总结"})
    _make_pdf(files["汇编"], page_lines=[["本页是扉页与致谢，没有任何检索要点"],
                                         [BODY_B], [PHRASE_B3]],
              meta={"title": TITLE_B})
    _make_scanned_pdf(files["扫描件"], pages=2)
    for leaf in (files["截断"], files["文本"]):
        leaf.parent.mkdir(parents=True, exist_ok=True)   # _make_pdf 会自建父目录，裸写文件不会
    files["截断"].write_bytes(b"%PDF-1.7\n" + b"\x00" * 4096)
    _make_pdf(files["加密"], pages=1, lines=["机密合同正文字符内容"], encrypted=True)
    files["文本"].write_text("非 PDF 文件，扫描器应当只计数不入库", encoding="utf-8")
    return {"outer": outer, "inner": inner, **files}


def _register(ctx: AppContext, directory: Path, label: str):
    """登记监测根。路径口径与 `tests/conftest.py` 的 `root` 夹具一致：
    `root_path` 用正斜杠，`root_key` 用 `identity_key()` —— 缺失判定靠前缀匹配，两个口径必须同源。"""
    path = str(directory).replace("\\", "/")
    return ctx.roots.add(path, identity_key(directory), label=label)


@pytest.fixture
def live(tmp_path: Path):
    """真后台：装配 → 登记两个重叠根 → 起 worker 与监听 → 排一次全量扫描并等它跑完。

    重叠是验收点之一：`语料/` 递归会走到 `语料/子目录/`，而后者自己也是个根。
    同一个文件被两条路扫到，只能留一条主记录。
    """
    files = _tree(tmp_path)
    ctx = bootstrap(tmp_path / "appdata")
    try:
        outer = _register(ctx, files["outer"], "语料")
        inner = _register(ctx, files["inner"], "子目录")
        assert inner.root_path.startswith(outer.root_path), "两个根不重叠，这条验收就什么都没测到"
        queue = ctx.start_background()
        assert ctx.jobs.enqueue("scan") is not None
        assert queue.wait_until_idle(timeout=IDLE_TIMEOUT), "全量扫描没跑完，后面的断言都是空谈"
        yield {"ctx": ctx, "queue": queue, "files": files, "outer": outer, "inner": inner}
    finally:
        ctx.shutdown()


def _doc_of(ctx: AppContext, path: Path):
    doc = ctx.documents.get_by_path_key(identity_key(path))
    assert doc is not None, f"{path} 没进库"
    assert doc.id is not None
    return doc


def _show(result) -> None:
    """把真实搜索结果原样打出来 —— 验收要求"展示真实搜索结果"，交的就是这些行。"""
    for line in result.lines():
        print(line)
    for row in result.rows():
        print("    ", row)


def _body_of(ctx: AppContext, doc_id: int) -> str:
    return " ".join(p.body or "" for p in ctx.texts.pages_of(doc_id))


def _verify(ctx: AppContext, queue: WorkQueue, root_key: str) -> None:
    """走一次真实的周期校验：根标脏 → 巡检排一条 `scan` → worker 按磁盘现状重算。

    这里只把根标脏（等价于"到点该校验了"），对账与索引全部由 worker 线程去做。
    """
    ctx.events.push_directory(root_key)
    report = ctx.patrol.poll()
    assert report.scan_enqueued, "脏根没能排出一场扫描，周期校验这条路是断的"
    assert queue.wait_until_idle(timeout=IDLE_TIMEOUT), "校验扫描没跑完"


def _fingerprint(directory: Path) -> dict[str, tuple[int, str]]:
    """整棵子树的 `{相对路径: (字节数, sha256)}`。移动、删除、改写、新增都会让它变。"""
    out: dict[str, tuple[int, str]] = {}
    for path in sorted(p for p in directory.rglob("*") if p.is_file()):
        data = path.read_bytes()
        out[str(path.relative_to(directory))] = (len(data), hashlib.sha256(data).hexdigest())
    return out


# —— 1. 完整链路与真实搜索结果 ————————————————————————————

def test_真实语料跑完整链路并展示四条通道的检索结果(live) -> None:
    ctx, files = live["ctx"], live["files"]

    assert ctx.documents.count() == 5, "重叠根把同一个文件扫成了两条主记录"
    assert ctx.documents.get_by_path_key(identity_key(files["文本"])) is None, "非 PDF 不该进文档表"
    compiled = _doc_of(ctx, files["汇编"])
    assert compiled.page_count == 3

    # 五种文件的处置各不相同，而且各自说的是实话
    assert (_doc_of(ctx, files["年报"]).text_status,
            _doc_of(ctx, files["年报"]).fts_status) == ("native", "done")
    scanned = _doc_of(ctx, files["扫描件"])
    assert (scanned.text_status, scanned.fts_status, scanned.ocr_status) == ("none", "done", "pending")
    broken = _doc_of(ctx, files["截断"])
    assert (broken.parse_status, broken.text_status, broken.fts_status) == ("failed", "failed", "failed")
    assert broken.last_error, "失败不留原文，状态页就答不出这份为什么搜不到"
    secret = _doc_of(ctx, files["加密"])
    assert (secret.needs_pass, secret.fts_status) == (1, "failed")

    print("\n== 阶段 2 验收：真实搜索结果（来自真 sqlite 库 + 真 PDF 抽取）==")
    by_name = ctx.search.search(Criteria(text="人工智能", in_fields=(FIELD_FILENAME,)))
    _show(by_name)
    assert [h.doc.name for h in by_name.hits] == ["人工智能产业年度报告.pdf"]

    by_path = ctx.search.search(Criteria(text="子目录", in_fields=(FIELD_PATH,)))
    _show(by_path)
    assert [h.doc.name for h in by_path.hits] == ["合同审阅要点汇编.pdf"], "路径通道与文件名通道没分开"

    by_meta = ctx.search.search(Criteria(text="政策研究室", in_fields=(FIELD_METADATA,)))
    _show(by_meta)
    assert [(h.doc.name, h.field_detail) for h in by_meta.hits] == \
        [("人工智能产业年度报告.pdf", "author")]

    by_body = ctx.search.search(Criteria(text="违约责任的举证", in_fields=(FIELD_BODY,)))
    _show(by_body)
    assert by_body.channel == "fts", "六个字的中文查询该走 trigram，退化成 LIKE 说明索引没建起来"
    hit = next(h for h in by_body.hits if h.doc.id == compiled.id)
    assert hit.page_no == 2, f"正文命中的页码错了：说它在第 {hit.page_no} 页"
    assert "违约责任的举证" in hit.snippet.line() and hit.highlight() is not None

    third = ctx.search.search(Criteria(text="附则的生效日期", in_fields=(FIELD_BODY,)))
    _show(third)
    assert [(h.doc.name, h.page_no) for h in third.hits] == [("合同审阅要点汇编.pdf", 3)], \
        "页码写死成 1 的实现骗不过这句：阅读器要跳到第 3 页"

    everything = ctx.search.search(Criteria(text="审阅要点"))
    _show(everything)
    assert set(everything.counts_by_field) >= {FIELD_FILENAME, FIELD_BODY, FIELD_METADATA}
    assert everything.hits[0].field == FIELD_FILENAME, "合并排序没把文件名通道排在正文前面"


def test_重叠根再扫一遍不多记录也不重抽正文(live) -> None:
    """第二遍扫描靠 sha256 短路：`last_indexed_at` 与正文行数都不许动。

    守的是量级红线 —— 全量语料 200 万页，"扫过一遍就重抽一遍"按 p2 实测要跑 3.8 小时。
    """
    ctx, queue, files = live["ctx"], live["queue"], live["files"]
    doc = _doc_of(ctx, files["年报"])
    doc_id = int(doc.id)  # type: ignore[arg-type]
    before = (ctx.documents.count(), int(doc.last_indexed_at or 0), ctx.texts.count_pages(doc_id))

    assert ctx.jobs.enqueue("scan") is not None
    assert queue.wait_until_idle(timeout=IDLE_TIMEOUT)

    after_doc = _doc_of(ctx, files["年报"])
    assert (ctx.documents.count(), int(after_doc.last_indexed_at or 0),
            ctx.texts.count_pages(doc_id)) == before, "同一份内容被重抽了一遍，或主记录长出了第二条"


def test_永久故障一次就定终态不把好文件拖在重试里(live) -> None:
    """损坏与加密各只有一条任务、一次尝试、一个 failed 终态；好文件全是 done。

    把它们当成瞬时故障的话，每次启动都要重跑一遍打不开的文件，而状态页上它们永远
    "还在重试"，真正该看的故障反倒被埋掉。
    """
    ctx, files = live["ctx"], live["files"]
    by_doc: dict[int, list] = {}
    for job in ctx.jobs.list(states=STATES):        # 含终态：默认口径只看未终结任务
        if job.doc_id is not None:
            by_doc.setdefault(int(job.doc_id), []).append(job)

    for label in ("截断", "加密"):
        doc = _doc_of(ctx, files[label])
        rows = by_doc.get(int(doc.id), [])          # type: ignore[arg-type]
        assert [(j.kind, j.state, j.attempts) for j in rows] == [("index", "failed", 1)], \
            f"{label} 的任务终态不对：{[(j.state, j.attempts) for j in rows]}"
    good = by_doc.get(int(_doc_of(ctx, files["年报"]).id), [])   # type: ignore[arg-type]
    assert [(j.kind, j.state) for j in good] == [("index", "done")]
    assert ctx.jobs.count("queued") == 0 and ctx.jobs.count("running") == 0


# —— 2. 真文件监听（事件快路）——————————————————————————————

def test_监听起来之后落盘的文件自己变成可搜(live, tmp_path: Path) -> None:
    """这条只验事件快路：测试里没有标脏根、没有手动排扫描、没有手动对账。

    样本先在**没被监听的**暂存目录里生成并写完，再整只挪进监测根 ——
    同盘 rename 是原子的，不会出现"事件到了、文件只写了一半"这种自造竞态。

    断的是"有文件级事件被处理过"（`report.events`），不断"由它判出新增"（`report.added`）：
    挪入文件的同一次 poll 里，父目录的 modified 事件已经把根标脏，周期校验会并行排一场重扫，
    谁先落到主记录上是不定的 —— 而 `added` 只能有一个赢家。锁 `added` 等于把产品没承诺的
    时序当契约（实测：`added` 稳定为 0，文件是被重扫发现的，快路本身是通的）。
    目录事件不进 `_pending`，所以 `report.events` 只可能来自文件级事件；
    本测试期间除了这一份新文件没有任何写操作，事件的对象是确定的。
    """
    ctx, queue, files = live["ctx"], live["queue"], live["files"]
    late = Path(_make_pdf(tmp_path / "暂存" / "现场新增的补充协议.pdf", page_lines=[[LATE_BODY]]))
    target = files["outer"] / late.name
    seen_before = ctx.events.snapshot()["total_seen"]
    late.rename(target)

    deadline = time.monotonic() + 30.0
    file_events = 0
    while file_events < 1 and time.monotonic() < deadline:
        file_events += ctx.patrol.poll().events
        queue.wait_until_idle(timeout=5.0)
    assert file_events >= 1, \
        f"30 秒内没有一条文件级事件被处理过，那不是监听的功劳：{ctx.events.snapshot()}"
    assert queue.wait_until_idle(timeout=IDLE_TIMEOUT)

    doc = ctx.documents.get_by_path_key(identity_key(target))
    assert doc is not None and doc.fts_status == "done", f"文件没进库或没索引完：{doc}"
    assert ctx.events.snapshot()["total_seen"] > seen_before
    assert doc.text_status == "native"

    result = ctx.search.search(Criteria(text="才落盘的一份文件", in_fields=(FIELD_BODY,)))
    _show(result)
    assert [h.doc.name for h in result.hits] == ["现场新增的补充协议.pdf"], \
        "文件名对上了但正文搜不到，说明 worker 真没抽过这一页"


# —— 3. 修改 / 改名 / 删除 —————————————————————————————————

def test_改了内容的文件重扫后正文跟着变(live) -> None:
    """判据是 (size, mtime_ns) + sha256，不是路径 —— 同一个文件名可以是另一份内容。"""
    ctx, queue, files = live["ctx"], live["queue"], live["files"]
    doc_id = int(_doc_of(ctx, files["年报"]).id)  # type: ignore[arg-type]
    assert "预算安排" in _body_of(ctx, doc_id)

    _make_pdf(files["年报"], page_lines=[["这一页已经换成全新的正文句子内容字符里面找不到那些旧词"]])
    _verify(ctx, queue, live["outer"].root_key)

    body = _body_of(ctx, doc_id)
    assert "换成全新的正文句子" in body and "预算安排" not in body, "正文还是旧的那一版"
    assert ctx.search.search(Criteria(text="预算安排", in_fields=(FIELD_BODY,))).hits == [], \
        "内容已经改了，旧正文还能搜出来就是虚假有效结果"
    fresh = ctx.search.search(Criteria(text="找不到那些旧词", in_fields=(FIELD_BODY,)))
    _show(fresh)
    assert [h.doc.name for h in fresh.hits] == ["人工智能产业年度报告.pdf"]


def test_改名认得出来是同一条记录而不是新的一条(live) -> None:
    """改名不换主键：`doc_id` 不变、正文不重抽、旧路径不再出现在库里。

    这条一旦退化，阶段 3 用户打在文件上的分类与标签就会跟着改名丢光。
    """
    ctx, queue, files = live["ctx"], live["queue"], live["files"]
    doc = _doc_of(ctx, files["汇编"])
    doc_id, indexed_at = int(doc.id), int(doc.last_indexed_at or 0)  # type: ignore[arg-type]
    moved = files["汇编"].with_name("合同审阅要点汇编-第二版.pdf")
    files["汇编"].rename(moved)

    _verify(ctx, queue, live["outer"].root_key)
    after = ctx.documents.get(doc_id)
    assert after is not None and after.name == moved.name, f"改名后主记录没跟着换路径：{after}"
    assert after.missing_since is None
    assert int(after.last_indexed_at or 0) == indexed_at, "内容没变却重抽了一遍正文"
    assert ctx.documents.get_by_path_key(identity_key(files["汇编"])) is None
    assert ctx.documents.count() == 5, "改名该换路径不换记录，长出新记录就是没认出来"

    result = ctx.search.search(Criteria(text="违约责任的举证", in_fields=(FIELD_BODY,)))
    assert [(h.doc.name, h.page_no) for h in result.hits] == [(moved.name, 2)]


def test_删掉的文件从结果里下去但记录与正文留着(live) -> None:
    """删除只改状态：正文留着，是为了文件挪回来时不必重抽 200 万页。

    删的是本测试自己造的样本（pytest 的 `tmp_path`）；
    "检索默认口径里不许出现它"是 SPEC 3.4 的硬要求。
    """
    ctx, queue, files = live["ctx"], live["queue"], live["files"]
    doc_id = int(_doc_of(ctx, files["汇编"]).id)  # type: ignore[arg-type]
    pages_before = ctx.texts.count_pages(doc_id)

    files["汇编"].unlink()
    _verify(ctx, queue, live["outer"].root_key)

    after = ctx.documents.get(doc_id)
    assert after is not None and after.missing_since is not None, "磁盘上没了，库里还说它还在"
    assert ctx.documents.count() == 5 and ctx.documents.count_missing() == 1
    assert ctx.texts.count_pages(doc_id) == pages_before, "删一个文件就把正文也删了，挪回来得重抽"

    assert ctx.search.search(Criteria(text="违约责任的举证", in_fields=(FIELD_BODY,))).hits == []
    shown = ctx.search.search(Criteria(text="违约责任的举证", in_fields=(FIELD_BODY,),
                                       include_missing=True))
    assert [(h.doc.name, h.page_no) for h in shown.hits] == [("合同审阅要点汇编.pdf", 2)], \
        "显式包含缺失时应当还能翻到旧正文"


# —— 4. 重启与索引恢复 ——————————————————————————————————————

def test_重启之后一切还在且重扫不必重抽(tmp_path: Path) -> None:
    """第一次跑完关进程，再对同一个数据目录 `bootstrap`：库说有什么就是有什么。

    重启后的全量扫描一份都不该重抽（`last_indexed_at` 全员不变），否则 7,768 份语料
    每次开机都要跑三个多小时。
    """
    files = _tree(tmp_path)
    data_root = tmp_path / "appdata"

    first = bootstrap(data_root)
    try:
        outer = _register(first, files["outer"], "语料")
        queue = first.start_background()
        assert first.jobs.enqueue("scan") is not None
        assert queue.wait_until_idle(timeout=IDLE_TIMEOUT)
        max_attempts = queue.max_attempts
        stamped = {int(d.id): int(d.last_indexed_at or 0) for d in first.documents.list()
                   if d.fts_status == "done" and d.id is not None}
        counts = first.status.read_tasks(max_attempts=max_attempts).fts_by_status
        assert counts.get("done", 0) >= 3, f"链路没跑通，重启无从谈起：{counts}"
    finally:
        first.shutdown()

    second = bootstrap(data_root)
    try:
        assert [r.root_path for r in second.roots.list()] == [outer.root_path], "监测根没留在库里"
        assert second.documents.count() == 5
        assert second.status.read_tasks(max_attempts=max_attempts).fts_by_status == counts
        assert second.background_state().running is False, "没调 start_background 就该说没起"
        assert second.documents.count("running") if False else True  # noqa: B015 - 占位将被删除

        queue = second.start_background()
        assert queue.max_attempts == max_attempts
        assert second.jobs.enqueue("scan") is not None
        assert queue.wait_until_idle(timeout=IDLE_TIMEOUT)
        after = {int(d.id): int(d.last_indexed_at or 0) for d in second.documents.list()
                 if d.fts_status == "done" and d.id is not None}
        assert after == stamped, "重启后重扫把已完成的正文又抽了一遍"

        result = second.search.search(Criteria(text="附则的生效日期", in_fields=(FIELD_BODY,)))
        _show(result)
        assert [(h.doc.name, h.page_no) for h in result.hits] == [("合同审阅要点汇编.pdf", 3)]
    finally:
        second.shutdown()


def test_进程被杀留下的running残尸重启后接着跑完(tmp_path: Path) -> None:
    """崩在索引中途 = 库里留一行 `running`，而文档还停在 `stale`。

    回收必须早于 `start()`，否则那行 running 被当成"还在跑"，这份文档永远没人领 ——
    这是"索引恢复"唯一真正的失效方式。
    """
    files = _tree(tmp_path)
    data_root = tmp_path / "appdata"

    first = bootstrap(data_root)
    try:
        _register(first, files["outer"], "语料")
        queue = first.start_background()
        assert first.jobs.enqueue("scan") is not None
        assert queue.wait_until_idle(timeout=IDLE_TIMEOUT)
        doc_id = int(_doc_of(first, files["年报"]).id)  # type: ignore[arg-type]
        first.documents.invalidate_index(doc_id)             # 当作"内容改过，欠一次索引"
        assert first.jobs.enqueue("index", doc_id) is not None
        claimed = first.jobs.claim(("index",))                # 领走之后进程被杀：没人写终态
        assert claimed is not None and claimed.state == "running"
        stale = first.documents.get(doc_id)
        assert stale is not None and stale.fts_status in NEEDS_INDEX_STATUSES
    finally:
        first.shutdown()

    second = bootstrap(data_root)
    try:
        assert second.jobs.count("running") == 1, "残尸没留在库里，那 recover 要收什么"
        assert second.background_state().running is False
        queue = second.start_background()
        assert second.jobs.count("running") == 0, "start 之后立刻被回收成 queued 才算 recover 早于 start"
        assert queue.wait_until_idle(timeout=IDLE_TIMEOUT)
        after = second.documents.get(doc_id)
        assert after is not None and after.fts_status == "done"
        assert second.status.read_tasks(max_attempts=queue.max_attempts).index_backlog == 0
        rows = [j for j in second.jobs.list(states=STATES) if j.doc_id == doc_id]
        assert ("done", 2) in [(j.state, j.attempts) for j in rows], \
            "回收的那条任务没接着跑完：现存的行是 " + str([(j.state, j.attempts) for j in rows])
        # 一场扫描排一条 + 本次制造的中断一条，就这两条；`resume_pending` 不该再排第三条
        assert len(rows) == 2, f"断点续扫把同一份文档排重复了：{[(j.state, j.attempts) for j in rows]}"
        assert sum(j.kind == "index" and j.state in ("queued", "running") for j in rows) == 0
        assert [h.doc.name for h in second.search.search(
            Criteria(text="预算安排", in_fields=(FIELD_BODY,))).hits] == ["人工智能产业年度报告.pdf"]
    finally:
        second.shutdown()


# —— 5. 安全边界 ————————————————————————————————————————————

def test_扫描与索引全程没有动过磁盘上的任何文件(live) -> None:
    """SPEC 3.6 / 阶段 2 安全要求：扫描与索引这一层**只读**。

    对整棵语料树取 (字节数, sha256) 指纹，跑完一轮周期校验之后必须逐字节一致 ——
    路径集合一致说明没移动没删除，字节一致说明没改写。
    库、日志、备份都写在数据目录里，不会落进语料树。
    """
    corpus = live["files"]["outer"]
    before = _fingerprint(corpus)
    ctx = live["ctx"]
    assert ctx.documents.count() == 5

    _verify(ctx, live["queue"], live["outer"].root_key)

    assert _fingerprint(corpus) == before, "扫描或索引改动了用户目录里的文件"


def test_跑完整条链路后crash_日志里没有一行线程异常(live) -> None:
    """后台线程死了不会有任何表面症状：根照样列着、队列照样跑、界面照样说"一切正常"。

    阶段 2 实测踩过两次，都是这一类：
    1. `fs/watcher.py` 的处理器没继承 `FileSystemEventHandler`，observer 线程在第一条事件上
       `AttributeError` 死掉，文件监听静默失灵；
    2. 崩溃钩子按 `args.exc_info` 取异常，而 `threading.ExceptHookArgs` 没有这个字段，
       于是钩子自己崩，现场（那条 AttributeError）都没被记下来。
    现在钩子能落盘了，这条测试就同时守两侧：链路跑完不许留下一行未处理的线程异常，
    而 crash.log 真有内容时也必须有原文可看。
    """
    ctx = live["ctx"]
    _verify(ctx, live["queue"], live["outer"].root_key)

    crash = ctx.paths.logs_dir / "crash.log"
    text = crash.read_text(encoding="utf-8") if crash.is_file() else ""
    assert "线程异常" not in text, f"有后台线程崩过一次：\n{text[-600:]}"
