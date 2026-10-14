"""检索层（阶段 2 第 8、9 条：文件名 / 路径 / 元数据 / 正文四类字段 + 片段与页码）。

四类字段必须**各自验**：只验"能搜到东西"的话，路径通道整条写错也照样绿。

正文通道额外验两件事：
1. 口径标注（trigram 还是慢速 LIKE）。p1 实测：两字查询硬走 FTS 会得到 0 条，
   用户看到 0 会以为程序坏了，所以结果里必须写明走了哪条。
2. 命中位置由 Python 侧算（FTS5 没有 `offsets()`，I7）。定位不到时不许编一个偏移出来。

样本是真 PDF、库是真 sqlite3。查询词全部取自样本里写死的那句话。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from pdfarchiver.fs.identity import identity_key
from pdfarchiver.indexing.fts import VIA_FTS, VIA_LIKE, match_expression
from pdfarchiver.search.service import (CHANNEL_LIMIT, FIELD_BODY, FIELD_BROWSE, FIELD_FILENAME,
                                        FIELD_METADATA, FIELD_PATH, Criteria, SearchService)

TITLE_A = "人工智能产业年度报告"
TITLE_B = "合同审阅要点汇编"
BODY_A = "报告里讨论了三条产业扶持政策的落地效果与预算安排"
BODY_B = "审阅要点集中在违约责任的举证条款与解除条件"
KEYWORDS_A = "产业政策,年度总结"


@pytest.fixture
def corpus(ctx, root, make_pdf):
    """两份可搜的活文档 + 一份索引后被删掉的文档。

    命名是刻意分开的：`人工智能产业年度报告.pdf` 让文件名通道有独有的词，
    B 放进 `子目录/` 让路径通道有独有的词（文件名里没有"子目录"三个字），
    两份的元数据与正文各写各的句子 —— 四条通道任何一条串线都会立刻变红。
    """
    r = root("语料")
    a = Path(make_pdf("语料/人工智能产业年度报告.pdf", page_lines=[[BODY_A]],
                      meta={"title": TITLE_A, "author": "政策研究室", "keywords": KEYWORDS_A}))
    b = Path(make_pdf("语料/子目录/合同审阅要点汇编.pdf",
                      page_lines=[["本页是扉页与致谢，没有任何检索要点"],
                                  [BODY_B]],
                      meta={"title": TITLE_B}))
    gone = Path(make_pdf("语料/待删除的合同副本.pdf", page_lines=["这一页写着将被删除的文档正文内容字符"]))
    ctx.scan.scan_root(r)
    for job in ctx.jobs.list():
        if job.kind == "index" and job.doc_id:
            ctx.indexer.index_document(int(job.doc_id))
    ctx.jobs.clear_finished()
    gone.unlink()
    ctx.scan.scan_root(r)          # 第二轮扫描把它打成缺失；正文照旧留在库里
    return {"ctx": ctx, "root": r, "a": a, "b": b, "gone": gone,
            "search": SearchService(ctx.documents, ctx.metadata, ctx.texts)}


# —— 四条通道各自验一次 ——————————————————————————————————

def test_文件名通道按名字命中并标明命中字段(corpus) -> None:
    result = corpus["search"].search(Criteria(text="人工智能", in_fields=(FIELD_FILENAME,)))

    assert [h.doc.name for h in result.hits] == ["人工智能产业年度报告.pdf"]
    hit = result.hits[0]
    assert hit.field == FIELD_FILENAME and hit.field_label == "文件名"
    assert hit.page_no is None, "文件名命中没有页码，编一个出来就是假信息"
    assert result.channel == "", "没勾正文时不许谎称走了 trigram"
    assert result.counts_by_field == {FIELD_FILENAME: 1}


def test_路径通道命中目录名而文件名通道不能(corpus) -> None:
    """"子目录"只存在于路径里。文件名通道必须 0 条、路径通道必须命中 ——
    两条通道共用一条 SQL 的话，这个断言会立刻指出它们没分开。"""
    search = corpus["search"]

    by_name = search.search(Criteria(text="子目录", in_fields=(FIELD_FILENAME,)))
    by_path = search.search(Criteria(text="子目录", in_fields=(FIELD_PATH,)))

    assert by_name.hits == []
    assert [h.doc.name for h in by_path.hits] == ["合同审阅要点汇编.pdf"]
    assert "子目录" in by_path.hits[0].doc.path
    assert by_path.hits[0].snippet.line().count("子目录") == 1


def test_元数据通道命中并说明命中的是哪一列(corpus) -> None:
    """只回 doc_id 等于把口径丢了：用户不知道是标题里有这个词还是作者里有。"""
    search = corpus["search"]

    title = search.search(Criteria(text=TITLE_A, in_fields=(FIELD_METADATA,)))
    author = search.search(Criteria(text="政策研究室", in_fields=(FIELD_METADATA,)))
    keywords = search.search(Criteria(text="年度总结", in_fields=(FIELD_METADATA,)))

    assert [(h.doc.name, h.field_detail) for h in title.hits] == \
        [("人工智能产业年度报告.pdf", "title")]
    assert [(h.doc.name, h.field_detail) for h in author.hits] == \
        [("人工智能产业年度报告.pdf", "author")]
    assert [(h.doc.name, h.field_detail) for h in keywords.hits] == \
        [("人工智能产业年度报告.pdf", "keywords")]
    assert title.hits[0].field_label == "元数据"
    assert title.hits[0].page_no is None


def test_正文通道给出页码与可高亮片段(corpus) -> None:
    """查询词只在**第 2 页**。写死 `page_no=1` 的实现骗不过这句断言 ——
    页码是用户点进阅读器后要落到的那一页，报错页等于没报。"""
    result = corpus["search"].search(Criteria(text="违约责任的举证", in_fields=(FIELD_BODY,)))

    assert len(result.hits) == 1, result.rows()
    hit = result.hits[0]
    assert hit.doc.name == "合同审阅要点汇编.pdf" and hit.page_no == 2
    assert hit.field == FIELD_BODY and hit.field_label == "正文"
    assert "违约责任的举证" in hit.snippet.line()
    start, end = hit.highlight()
    assert hit.snippet.text[start:end] == "违约责任的举证", "高亮区间必须正好框住查询词"

    front = corpus["search"].search(Criteria(text="扉页", in_fields=(FIELD_BODY,)))
    assert [h.page_no for h in front.hits] == [1], "同一文档的另一页要落在另一页上，不是同一个数"


# —— 正文口径：trigram / LIKE / 转义 ———————————————————————

def test_三字以上走trigram并在结果里标注口径(corpus) -> None:
    result = corpus["search"].search(Criteria(text="审阅要点", in_fields=(FIELD_BODY,)))
    assert result.channel == VIA_FTS
    assert "trigram" in result.channel_label, result.channel_label


def test_两字查询退回LIKE并写明慢速匹配(corpus) -> None:
    """trigram 组不出 2 字 gram（p1 实测 0 命中）。硬走索引会得到"没有这份文档"，
    而真相是"查询词太短"，所以退回全文扫描 + 口径标注。"""
    result = corpus["search"].search(Criteria(text="产业", in_fields=(FIELD_BODY,)))

    assert result.channel == VIA_LIKE
    assert "慢速" in result.channel_label, result.channel_label
    assert [h.doc.name for h in result.hits] == ["人工智能产业年度报告.pdf"]
    assert result.hits[0].score == 0.0, "LIKE 没有相关性得分，不许伪造一个"


def test_查询词里的FTS运算符被当成普通字符(corpus) -> None:
    """不转义就会被 FTS5 当语法：`3 AND 5` 变成布尔表达式，`a(` 直接语法报错。
    用户看到的应该是"没有这份文件"，不是"程序崩了"。"""
    for tricky in ['违约 AND 举证', '审阅要点(括号)', '报告"引号"', "产业*通配", "违约_举证"]:
        result = corpus["search"].search(Criteria(text=tricky, in_fields=(FIELD_BODY,)))
        assert isinstance(result.hits, list)
    assert match_expression('a"b') == '"a""b"'
    assert corpus["search"].search(Criteria(text="违约 AND 举证")).channel == VIA_FTS


def test_大小写不同的英文查询仍能定位到片段(corpus, make_pdf) -> None:
    """trigram 折叠大小写，Python 侧用 `lower()` 找回位置。一致时高亮必须落在原文那一段，
    不一致时宁可不高亮 —— 报错位置比不高亮更糟。"""
    r = corpus["root"]
    path = Path(make_pdf(f"{r.label}/大小写对照.pdf",
                         page_lines=["Quarterly REPORT 的正文里夹着一段英文标题"]))
    corpus["search"]  # 语料夹具已经建好库，这里只补一份样本
    ctx_scan_and_index(corpus, path)
    search = corpus["search"]

    result = search.search(Criteria(text="QUARTERLY REPORT", in_fields=(FIELD_BODY,)))

    assert len(result.hits) == 1, result.rows()
    hit = result.hits[0]
    if hit.snippet.matched:
        start, end = hit.highlight()
        assert hit.snippet.text[start:end].lower() == "quarterly report"
    else:
        assert hit.highlight() is None, "matched=False 时不许给出偏移"


def ctx_scan_and_index(corpus, path) -> None:
    """把新加的样本走一遍「扫描 → 索引」，用队列里真实排上的任务驱动，不手搓 doc_id。"""
    ctx = corpus["ctx"]
    ctx.scan.scan_root(corpus["root"])
    for job in ctx.jobs.list():
        if job.kind == "index" and job.doc_id:
            try:
                ctx.indexer.index_document(int(job.doc_id))
            except Exception:
                pass
    ctx.jobs.clear_finished()


# —— 缺失、筛选、分页与截断 ——————————————————————————————

def test_缺失文档默认不进结果但可以显式包含(corpus) -> None:
    """正文其实还在库里（删文件不删正文），但它已不在磁盘上：
    继续搜出来就是 SPEC 禁止的虚假有效结果。开关要能翻回来，用于"我明明删了它怎么还有记录"。"""
    search = corpus["search"]

    default = search.search(Criteria(text="将被删除的文档", in_fields=(FIELD_BODY,)))
    with_missing = search.search(Criteria(text="将被删除的文档", in_fields=(FIELD_BODY,),
                                          include_missing=True))

    assert default.hits == []
    assert [h.doc.name for h in with_missing.hits] == ["待删除的合同副本.pdf"]
    assert with_missing.channel == VIA_FTS


def test_只看缺失时活文档一条都不出(corpus) -> None:
    result = corpus["search"].search(Criteria(text="", missing_only=True))
    assert [h.doc.name for h in result.hits] == ["待删除的合同副本.pdf"]
    assert result.matching_documents == 1


def test_空查询是浏览模式不装成检索(corpus) -> None:
    result = corpus["search"].search(Criteria(text="", limit=10))

    assert result.channel == "" and "浏览模式" in result.channel_label
    assert result.counts_by_field == {FIELD_BROWSE: 2}, "活文档两份，缺失那份不该被浏览出来"
    assert result.hits[0].snippet is None, "浏览没有查询词，没有片段可高亮"


def test_同名命中时文件名排在正文之前(corpus) -> None:
    """相关性口径写死在 `FIELD_WEIGHT`：工具的主用途是"找回那份文件"，
    名字里带词的文档几乎就是用户要找的那份，正文命中再多也不该把它挤下去。"""
    result = corpus["search"].search(Criteria(text="审阅要点"))

    assert result.hits[0].field == FIELD_FILENAME
    assert set(result.counts_by_field) >= {FIELD_FILENAME, FIELD_BODY, FIELD_METADATA}


def test_分页按offset切片而不是全量返回(corpus) -> None:
    search = corpus["search"]

    first = search.search(Criteria(text="语料", in_fields=(FIELD_PATH,), limit=1))
    second = search.search(Criteria(text="语料", in_fields=(FIELD_PATH,), limit=1, offset=1))

    assert len(first.hits) == 1 and len(second.hits) == 1
    assert first.hits[0].doc.name != second.hits[0].doc.name, "翻页翻出同一份就是分页没生效"
    assert first.counts_by_field[FIELD_PATH] == 2, "取回的行数在分页前统计，与本页行数不是一个口径"


def test_超过通道上限时只截断不假装取完(ctx, corpus) -> None:
    """G6 禁止全量物化：一次检索最多 4×CHANNEL_LIMIT 行。
    上限值不是摆设 —— 不实现它，八千份文档的一次浏览会把界面拖死。

    这里同时钉住三个数各是什么口径：`matching_documents` 是 SQL 数出来的**文档**数（203 份），
    `counts_by_field` 是通道在分页前取回的**行**数（被 CHANNEL_LIMIT 卡住），
    `len(hits)` 是本页行数（被 `limit` 卡住）。三个数谁也不能替谁。"""
    base = Path(corpus["root"].root_path)
    for i in range(CHANNEL_LIMIT + 1):
        (base / f"批量{i}.pdf").write_bytes(b"%PDF-1.7\nnot really a pdf\n")
    ctx.scan.scan_root(corpus["root"])
    search = corpus["search"]

    page = search.search(Criteria(text="批量", in_fields=(FIELD_FILENAME,)))
    wide = search.search(Criteria(text="批量", in_fields=(FIELD_FILENAME,), limit=CHANNEL_LIMIT))

    assert page.matching_documents == CHANNEL_LIMIT + 3, "库里有 203 份的名字带「批量」"
    assert page.counts_by_field[FIELD_FILENAME] == CHANNEL_LIMIT
    assert len(page.hits) == 50, "本页 50 行是分页给的，不是通道取回的数"
    assert len(wide.hits) == CHANNEL_LIMIT
    assert page.truncated_fields == (FIELD_FILENAME,), page.truncated_fields
    assert "截断" in page.lines()[0], page.lines()[0]


def test_筛选条件对四条通道同时生效(corpus, root) -> None:
    """筛选口径只有一份（`where_for_filter`）。这里用"按监测根筛"当探针：
    换成一个没有文档的根，四条通道必须同时变空，而不是某条继续返回。"""
    other = root("另一个根")
    search = corpus["search"]

    scoped = search.search(Criteria(text="审阅要点", root_key=other.root_key))
    unscoped = search.search(Criteria(text="审阅要点"))

    assert scoped.matching_documents == 0 and scoped.hits == []
    assert scoped.counts_by_field == {}, "筛选没传进通道，界面就会显示一批点开就找不到文件的结果"
    assert unscoped.hits, "对照组：查询词本身是有命中的"


def test_分类与标签筛选圈出不同文档(corpus, ctx) -> None:
    category = ctx.catalog.add_category("产业政策研究")
    tag = ctx.catalog.add_tag("待复核")
    a_id = int(ctx.documents.facts_by_key(identity_key(str(corpus["a"]))).doc_id)  # type: ignore[arg-type]
    b_id = int(ctx.documents.facts_by_key(identity_key(str(corpus["b"]))).doc_id)  # type: ignore[arg-type]
    ctx.catalog.link_category(a_id, int(category.id))
    ctx.catalog.link_tag(b_id, int(tag.id))
    search = corpus["search"]

    by_category = search.search(Criteria(text="合同", in_fields=(FIELD_FILENAME,),
                                         category_ids=(a_id,)))
    by_tag = search.search(Criteria(text="合同", in_fields=(FIELD_FILENAME,), tag_ids=(int(tag.id),)))

    assert by_category.hits == [], "A 的名字里没有「合同」两个字，按分类筛完就该是空"
    assert [h.doc.name for h in by_tag.hits] == ["合同审阅要点汇编.pdf"]


def test_索引状态与页数筛选(corpus) -> None:
    """`fts_status` / `min_pages` 是「待办清单」的入口：状态页要能列出还没索引好的那些。
    两个口径（索引状态、缺失状态）在同一份筛选下必须各自数得清，不许互相盖掉。"""
    search = corpus["search"]

    done = search.search(Criteria(text="", fts_status="done"))
    done_including_missing = search.search(Criteria(text="", fts_status="done", include_missing=True))
    pending = search.search(Criteria(text="", fts_status="pending"))
    thick = search.search(Criteria(text="", min_pages=5))

    assert done.matching_documents == 2, "默认口径不含缺失那份；它索引过但已经不在磁盘上"
    assert done_including_missing.matching_documents == 3, "翻开关就该把那条找回来"
    assert pending.matching_documents == 0
    assert thick.hits == [], "样本都是一页的，页数筛选得按 page_count 而不是按正文行数"


def test_装配好的应用上下文带着检索入口(ctx, root, make_pdf) -> None:
    """架构守卫禁止 `ui` import `pdfarchiver.search`，所以界面只能通过 `ctx.search` 搜。
    这条测试替界面把那条路走一遍：装配 → 扫描 → 索引 → 搜得到。"""
    r = root("装配")
    make_pdf("装配/装配样本.pdf", page_lines=["装配完成后应当直接搜得到的正文内容"])
    ctx.scan.scan_root(r)
    for job in ctx.jobs.list():
        if job.kind == "index" and job.doc_id:
            ctx.indexer.index_document(int(job.doc_id))

    result = ctx.search.search(Criteria(text="直接搜得到", in_fields=(FIELD_BODY,)))

    assert len(result.hits) == 1, result.rows()
    assert result.hits[0].doc.name == "装配样本.pdf"
    print("\n".join(result.lines() + result.rows()))


def test_非法查询条件当场拒绝而不是返回空结果(corpus) -> None:
    """空字段列表 / 未知字段 / 未知排序 / 越界分页都是调用方的 bug。
    返回 0 条会让它看起来像「真的没有结果」，那是最难发现的一类错。"""
    search = corpus["search"]
    cases = [Criteria(in_fields=()), Criteria(in_fields=("nonsense",)),
             Criteria(in_fields=(FIELD_BODY, FIELD_BODY)), Criteria(sort="随机排序"),
             Criteria(limit=0), Criteria(limit=5000), Criteria(offset=-1),
             Criteria(missing_only=True, include_missing=True)]

    for bad in cases:
        with pytest.raises(ValueError):
            search.search(bad)


def test_把浏览字段当检索通道时要抛而不是静默返回零条(corpus) -> None:
    """`browse` 是「没打字」时的结果标记，不是一条可实现的通道。
    新增字段忘了实现时，`_channel` 必须当场说，而不是让界面显示「0 条命中」。"""
    with pytest.raises(ValueError, match="未实现的检索通道"):
        corpus["search"].search(Criteria(text="审阅要点", in_fields=(FIELD_BROWSE,)))
