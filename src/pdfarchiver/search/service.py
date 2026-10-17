"""检索层：把一条查询变成四类字段的命中结果（SPEC 3.4 / 阶段 2 第 8、9 条）。

四条通道各跑各的 SQL，最后在这里合并排序：
  文件名 `documents.name`、路径 `documents.path`、元数据 `document_metadata.*`、正文 `content_fts`/`text_pages`。

四条不能含糊的规矩：

1. **筛选口径只有一份**。四条通道都用 `documents.where_for_filter` 编译出来的同一个
   `DocFilter`。"按分类筛完搜正文"和"按分类筛完看文件名"如果各拼一次 WHERE，
   两边就会在某个角落分家（漏掉 `missing_since IS NULL` 是最好犯的一种）。
2. **结果里标口径**。正文通道要写明走的是 trigram 还是慢速 LIKE（`indexing/fts.py`），
   每条命中要写明命中在哪个字段。用户搜"人工"看到 0 条会以为程序坏了，
   看到"慢速匹配 3 条"才知道是查询词太短。
3. **每条通道限量**。`CHANNEL_LIMIT` 是硬上限（G6 禁止全量渲染）：一次检索最多物化
   4×200 行，超出部分只报"该通道被截断"，不假装"一共 12,000 条都取回来了"。
4. **四个计数各说各的事**，不许混用一个"总数"：`matching_documents` 是符合筛选条件的
   **文档**数（SQL 数出来的，与查询词无关）；`counts_by_field` 是各通道**取回的行数**
   （分页前、受 `CHANNEL_LIMIT` 限制）；`len(hits)` 是本页行数。
5. **浅扫要自报没扫完**。1–2 字的 LIKE 通道有行预算（`LIKE_SCAN_ROWS`）：到点就停，
   停了就必须把"只看了库里靠前的一段、结果可能不全"写进结果（`body_scan_incomplete`），
   并让界面把它显示出来。**D-051** —— 这是改语义，不是改性能参数。
"""
from __future__ import annotations

import time
from dataclasses import dataclass

from pdfarchiver.db.models import Document
from pdfarchiver.db.repositories.documents import DocFilter, DocumentRepository, SORTS
from pdfarchiver.db.repositories.metadata import MetadataRepository
from pdfarchiver.db.repositories.text import TextRepository
from pdfarchiver.indexing.fts import VIA_FTS, channel_for, describe_channel, match_expression
from pdfarchiver.indexing.snippets import Snippet, snippet_for

# 每条通道的行数上限：4 条通道 ×200 行的片段计算与物化，留足首屏 500ms 门禁（G2）。
# 2026-10-17 更正依据：原先这里写着"按 p1 实测 LIKE 499ms/次 反算"，**那条依据已被证伪**
# （**ISSUES I59**：LIKE 的耗时由"为凑满 200 条要往表里走多深"决定，与表大小只是间接关系 ——
# 真库现测 `发票` 走 334,924 行 2,676ms、`北京` 走 11,903 行 104ms，同一条 SQL 同一张表）。
# 上限本身不动：它是 G6「禁止全量物化」的口径，不是性能参数。
CHANNEL_LIMIT = 200
# LIKE 通道的**深度预算**（**D-051**）：往 `text_pages` 里最多走 N 行就停。
# 反算按最大量级（真库 1,972,578 行、2026-10-17 实测）：无预算时最慢的两字查询 `发票`
# 要为凑满 200 条走 334,924 行（全表 17.0%）= 端到端 2,994ms，即约 **112 行/ms**；
# 要压在 G2 的 500ms 红线内 ⇒ 理论上限 500×112≈5.6 万行，但实测预算段本身更快
# （边界扫描不含正文抽取，60,000 行端到端 329ms ⇒ 约 182 行/ms），
# 所以取 **60,000 行**：实测端到端 **P95 328ms / max 332ms**，距红线余 34%
# （`.probe_work/g2_after_budget_B.log`）。
# 代价如实写着：这只覆盖全表 3.0%，2 字查询的正文召回从"最多 200 行（全库里）"变成
# "最多 200 行（库里靠前的 6 万页里）"，且**偏向 doc_id 靠前的那批文档**（`发票` 实测
# 200 行 → 169 行），所以必须自报未扫完。窗口按 doc_id 取整到份，最多越出预算一份
# （库里最大的那份 946 页 = 预算的 1.6%）。
LIKE_SCAN_ROWS = 60_000
DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 200

FIELD_FILENAME = "filename"
FIELD_PATH = "path"
FIELD_METADATA = "metadata"
FIELD_BODY = "body"
FIELD_BROWSE = "browse"

FIELD_LABELS = {
    FIELD_FILENAME: "文件名",
    FIELD_PATH: "路径",
    FIELD_METADATA: "元数据",
    FIELD_BODY: "正文",
    FIELD_BROWSE: "浏览",
}
# 相关性权重：文件名 > 元数据 > 路径 > 正文。归档工具的主用途是"找回那份文件"，
# 名字里带词的文档几乎就是用户要找的那份；正文命中一万次也不该把它挤下去。
FIELD_WEIGHT = {FIELD_FILENAME: 0, FIELD_METADATA: 1, FIELD_PATH: 2, FIELD_BODY: 3}

# 正文有两个来源，而且必须一直分开说（SPEC 五：不得把未经验证的识别文字伪装成准确的原始文本）。
# 这一段文字会出现在每条正文命中上 —— 用户照着页码翻回原文件时，得先知道那句"正文"是谁给的。
BODY_SOURCE_LABELS = {
    "native": "原生正文",
    "ocr": "OCR 识别（可能有错字）",
}


@dataclass(frozen=True)
class Criteria:
    """一次检索的完整输入。字段类型全是内置值 —— UI 层不许 import `db`，
    所以这里不收 `DocFilter`，由 `doc_filter()` 换算。"""

    text: str = ""
    in_fields: tuple[str, ...] = (FIELD_FILENAME, FIELD_METADATA, FIELD_PATH, FIELD_BODY)
    root_key: str | None = None
    category_ids: tuple[int, ...] = ()
    tag_ids: tuple[int, ...] = ()
    tag_match_all: bool = False
    modified_from: int | None = None      # UTC unix 秒，比的是文件修改时间（口径见 DocFilter）
    modified_to: int | None = None
    fts_status: str | None = None
    min_pages: int | None = None
    min_size_bytes: int | None = None
    include_missing: bool = False         # True=磁盘上已经不存在的文档也参与
    missing_only: bool = False
    sort: str = "relevance"
    limit: int = DEFAULT_PAGE_SIZE
    offset: int = 0

    def doc_filter(self) -> DocFilter:
        return DocFilter(
            root_key=self.root_key, category_ids=self.category_ids, tag_ids=self.tag_ids,
            tag_match_all=self.tag_match_all, modified_from=self.modified_from,
            modified_to=self.modified_to, fts_status=self.fts_status,
            min_pages=self.min_pages, min_size_bytes=self.min_size_bytes,
            include_missing=self.include_missing, missing_only=self.missing_only)

    def validate(self) -> None:
        unknown = [f for f in self.in_fields if f not in FIELD_LABELS]
        if unknown:
            raise ValueError(f"未知检索字段 {unknown}；可选 {sorted(FIELD_LABELS)}")
        if not self.in_fields:
            raise ValueError("至少要选一个检索字段，一个都不选等于声明\"什么都不搜\"")
        if len(set(self.in_fields)) != len(self.in_fields):
            raise ValueError(f"检索字段重复：{list(self.in_fields)}")
        if self.sort != "relevance" and self.sort not in SORTS:
            raise ValueError(f"未知排序 {self.sort!r}；可选 relevance + {sorted(SORTS)}")
        if not 1 <= self.limit <= MAX_PAGE_SIZE:
            raise ValueError(f"单页条数要在 1–{MAX_PAGE_SIZE} 之间，收到 {self.limit}")
        if self.offset < 0:
            raise ValueError(f"偏移不能为负，收到 {self.offset}")
        if self.missing_only and self.include_missing:
            raise ValueError("missing_only（只看缺失）与 include_missing（包含缺失）含义相反，不能同时要")


@dataclass(frozen=True)
class Hit:
    doc: Document
    field: str            # FIELD_* 之一：这条命中是从哪类字段找到的
    snippet: Snippet | None
    page_no: int | None   # 正文命中的页码（1 基，与阅读器显示的一致）；其他通道为 None
    score: float          # 正文 trigram 通道的 bm25（越小越相关）；其他通道恒 0.0
    field_detail: str | None = None   # 元数据命中时的具体列名，如 author / title
    body_source: str = "native"       # 正文命中的来源：native=文件里本来就有的字，ocr=识别出来的

    @property
    def field_label(self) -> str:
        return FIELD_LABELS[self.field]

    @property
    def source_label(self) -> str:
        """正文命中的出处标签。非正文通道返回空串 —— 只有正文有两个来源可说。"""
        return BODY_SOURCE_LABELS.get(self.body_source, "") if self.field == FIELD_BODY else ""

    def highlight(self) -> tuple[int, int] | None:
        """片段内的高亮区间（界面据此把片段切成 前文/命中/后文 三段）。
        定位不到时返回 None —— 不高亮，不编一个位置出来。"""
        if self.snippet is None or not self.snippet.matched:
            return None
        return self.snippet.query_start - self.snippet.start, self.snippet.query_end - self.snippet.start


@dataclass(frozen=True)
class SearchResult:
    criteria: Criteria
    hits: list[Hit]
    channel: str                       # fts / like_fallback / ""（没勾正文或没打字）
    matching_documents: int            # 符合筛选条件的文档数（与查询词无关）
    counts_by_field: dict[str, int]    # 各通道取回的行数（分页前）
    truncated_fields: tuple[str, ...]  # 取满 CHANNEL_LIMIT 的通道，后面还有但没取
    took_ms: int
    body_scan_incomplete: bool = False  # 正文 LIKE 通道被 `LIKE_SCAN_ROWS` 截停（**D-051**）

    @property
    def channel_label(self) -> str:
        if not self.criteria.text.strip():
            return f"浏览模式（未输入查询词，排序 {self.criteria.sort}）"
        if not self.channel:
            return "只检索文件名 / 路径 / 元数据（本次没有搜正文）"
        return describe_channel(self.channel, self.criteria.text)

    @property
    def _counts_text(self) -> str:
        return "、".join(f"{FIELD_LABELS[name]} {n} 行"
                         for name, n in sorted(self.counts_by_field.items(),
                                               key=lambda kv: FIELD_WEIGHT[kv[0]])) or "0 行"

    @property
    def _truncation_text(self) -> str:
        return f"｜截断通道：{'、'.join(FIELD_LABELS[n] for n in self.truncated_fields)}" \
            if self.truncated_fields else ""

    @property
    def _scan_text(self) -> str:
        """浅扫自报（**D-051**）：预算截停时必须说"没扫完"，而且要连**偏向哪一段**一起说 ——
        只写"结果可能不全"是不够的，用户会以为缺的是随机一些，实际缺的是库里靠后的那些文档。"""
        return f"｜正文按 {LIKE_SCAN_ROWS:,} 页预算浅扫，未扫完（缺的是库里靠后的页）" \
            if self.body_scan_incomplete else ""

    def lines(self) -> list[str]:
        """给人读的结果摘要。阶段 2 验收要"展示真实搜索结果"，交的就是这个，不是截图里的假表格。"""
        return [f"查询「{self.criteria.text or '（空）'}」｜口径：{self.channel_label}"
                f"｜符合筛选的文档 {self.matching_documents} 份｜取回 {self._counts_text}"
                f"｜本页 {len(self.hits)} 行｜耗时 {self.took_ms}ms"
                f"{self._truncation_text}{self._scan_text}"]

    def status_line(self) -> str:
        """状态栏那一行的口径（**ISSUES I60**）。与 `lines()` 同源同字段，只降措辞密度：
        `lines()` 是给报告和终端读的整句（实测 1056px），而 S1 中栏在最宽的那档（窗口 1280）
        只有 463px 可用（`test_ui_layout` 现测），整句要塞进三行才放得下。这里去掉"查询「…」"
        （查询词就在输入框里，重复一遍不增加信息）和"口径："前缀，线框点名的三样一条不少：
        通道口径、各通道取回的行数、截断 —— 且**没有任何界面自己算出来的数**。
        浅扫自报（**D-051**）也在这一行里：预算截停是真 happened，藏在报告里等于没说。
        """
        return (f"{self.channel_label}｜符合筛选 {self.matching_documents} 份｜{self._counts_text}"
                f"｜本页 {len(self.hits)} 行｜{self.took_ms}ms"
                f"{self._truncation_text}{self._scan_text}")

    def rows(self) -> list[str]:
        out: list[str] = []
        for hit in self.hits:
            where = f"第 {hit.page_no} 页" if hit.page_no else \
                f"{hit.field_label}" + (f"·{hit.field_detail}" if hit.field_detail else "")
            # 正文命中必须带上出处：同一句"命中"可能是 PDF 里的字，也可能是识别出来的字，
            # 后者会有错字，用户照抄进报告之前有权知道（SPEC 五·不许伪装成准确的原始文本）。
            source = f"｜{hit.source_label}" if hit.source_label else ""
            out.append(f"[{where}]{source} {hit.doc.name}｜"
                       f"{hit.snippet.line() if hit.snippet else hit.doc.path}")
        return out


class SearchService:
    def __init__(self, documents: DocumentRepository, metadata: MetadataRepository,
                 text: TextRepository) -> None:
        self.documents = documents
        self.metadata = metadata
        self.text = text

    def search(self, criteria: Criteria) -> SearchResult:
        criteria.validate()
        t0 = time.perf_counter()
        filters = criteria.doc_filter()
        needle = criteria.text.strip()
        matching = self.documents.count_matching(filters)

        if not needle:
            hits = self._browse(filters, criteria)
            return SearchResult(criteria=criteria, hits=hits, channel="", matching_documents=matching,
                                counts_by_field={FIELD_BROWSE: len(hits)}, truncated_fields=(),
                                took_ms=self._ms(t0))

        groups: dict[str, tuple[list[Hit], bool]] = {}
        shallow_scan = False
        for name in criteria.in_fields:
            rows, truncated, incomplete = self._channel(name, needle, filters)
            # 浅扫自报**不以"这一条有没有命中"为前提**：0 行时更需要说，否则用户读到的是
            # 「库里没有」，而真相是「库里靠前的 6 万页没有」。
            shallow_scan = shallow_scan or incomplete
            if rows:
                groups[name] = (rows, truncated)

        merged = self._order(groups, criteria)
        return SearchResult(
            criteria=criteria, hits=merged[criteria.offset:criteria.offset + criteria.limit],
            channel=channel_for(needle) if FIELD_BODY in criteria.in_fields else "",
            matching_documents=matching,
            counts_by_field={name: len(rows) for name, (rows, _) in groups.items()},
            truncated_fields=tuple(sorted(name for name, (_, cut) in groups.items() if cut)),
            took_ms=self._ms(t0), body_scan_incomplete=shallow_scan)

    # —— 各通道 ——————————————————————————————————————————————

    def _channel(self, name: str, needle: str,
                 filters: DocFilter) -> tuple[list[Hit], bool, bool]:
        """返回 (命中, 被 `CHANNEL_LIMIT` 截断, 被 `LIKE_SCAN_ROWS` 浅扫)。

        第三条只有正文的 LIKE 通道可能为真：另外三条扫的是 `documents`（现库 10,980 行）与
        `document_metadata`，量级比正文小两个数量级，给它们设预算是凭空砍召回（**D-051** 只改正文）。
        """
        if name == FIELD_FILENAME:
            return (*self._from_docs(self.documents.field_hits(
                needle, column="name", filters=filters, limit=CHANNEL_LIMIT + 1),
                FIELD_FILENAME, needle, lambda d: d.name), False)
        if name == FIELD_PATH:
            return (*self._from_docs(self.documents.field_hits(
                needle, column="path", filters=filters, limit=CHANNEL_LIMIT + 1),
                FIELD_PATH, needle, lambda d: d.path), False)
        if name == FIELD_METADATA:
            rows = self.metadata.field_hits(needle, filters=filters, limit=CHANNEL_LIMIT + 1)
            docs = self.documents.by_ids([r.doc_id for r in rows])
            return (*self._truncate([
                Hit(doc=docs[r.doc_id], field=FIELD_METADATA, snippet=snippet_for(r.value, needle),
                    page_no=None, score=0.0, field_detail=r.field) for r in rows if r.doc_id in docs]),
                False)
        if name == FIELD_BODY:
            return self._body(needle, filters)
        raise ValueError(f"未实现的检索通道 {name}")

    def _body(self, needle: str, filters: DocFilter) -> tuple[list[Hit], bool, bool]:
        incomplete = False
        if channel_for(needle) == VIA_FTS:
            rows = self.text.search_fts(match_expression(needle), filters, limit=CHANNEL_LIMIT + 1)
        else:
            rows, incomplete = self.text.search_like(
                needle, filters, limit=CHANNEL_LIMIT + 1, scan_budget=LIKE_SCAN_ROWS)
        docs = self.documents.by_ids([r.doc_id for r in rows])
        return (*self._truncate([
            Hit(doc=docs[r.doc_id], field=FIELD_BODY, snippet=snippet_for(r.body, needle),
                page_no=r.page_no, score=r.score, body_source=r.source_kind)
            for r in rows if r.doc_id in docs]), incomplete)

    def _from_docs(self, docs: list[Document], name: str, needle: str,
                   source) -> tuple[list[Hit], bool]:  # noqa: ANN001 - source 是 str→str 的小函数
        return self._truncate([Hit(doc=d, field=name, snippet=snippet_for(source(d), needle),
                                   page_no=None, score=0.0) for d in docs])

    def search_text(self, query: str, limit: int = 100) -> SearchResult:
        """便捷入口：UI 不需要自己构造 Criteria。"""
        return self.search(Criteria(text=query, limit=limit))

    def _browse(self, filters: DocFilter, criteria: Criteria) -> list[Hit]:
        sort = "name" if criteria.sort == "relevance" else criteria.sort
        docs = self.documents.list_sorted(filters, sort=sort, limit=criteria.limit, offset=criteria.offset)
        return [Hit(doc=d, field=FIELD_BROWSE, snippet=None, page_no=None, score=0.0) for d in docs]

    @staticmethod
    def _truncate(hits: list[Hit]) -> tuple[list[Hit], bool]:
        """多取一行只为判断"到底有没有被截断"，那一行不参与结果。"""
        return hits[:CHANNEL_LIMIT], len(hits) > CHANNEL_LIMIT

    # —— 合并排序 ————————————————————————————————————————————

    def _order(self, groups: dict[str, tuple[list[Hit], bool]], criteria: Criteria) -> list[Hit]:
        """行级结果，一条命中一行 —— 同一份文档正文命中 3 页就是 3 行，四种排序下都是。
        （分页单位若是"文档"，`counts_by_field` 和页码就没法自洽。）

        `relevance`：先字段权重，正文组内按 bm25（越小越相关），其他组内按文件名字序。
        其余排序：整表按文档属性重排，同文档的多行保持相邻。结果集已被 `CHANNEL_LIMIT`
        限住，这几百行在 Python 里排是 O(n log n)，不必给 SQL 加第二种排序口径。"""
        rows: list[Hit] = []
        for name, (hits, _) in groups.items():
            rows += sorted(hits, key=lambda h: (h.doc.name.casefold(), h.doc.id or 0, h.page_no or 0)) \
                if name != FIELD_BODY or criteria.sort != "relevance" else hits
        if criteria.sort == "relevance":
            return sorted(rows, key=lambda h: (FIELD_WEIGHT[h.field],
                                               h.score if h.field == FIELD_BODY else 0.0,
                                               h.doc.id or 0, h.page_no or 0))
        key_of = {
            "name": lambda h: (h.doc.name.casefold(), h.doc.id or 0, h.page_no or 0),
            "path": lambda h: (h.doc.path.casefold(), h.doc.id or 0, h.page_no or 0),
            "mtime": lambda h: (-h.doc.mtime_ns, h.doc.id or 0, h.page_no or 0),
            "size": lambda h: (-h.doc.size_bytes, h.doc.id or 0, h.page_no or 0),
            "pages": lambda h: (-(h.doc.page_count or 0), h.doc.id or 0, h.page_no or 0),
            "indexed": lambda h: (-(h.doc.last_indexed_at or 0), h.doc.id or 0, h.page_no or 0),
        }[criteria.sort]
        return sorted(rows, key=key_of)

    @staticmethod
    def _ms(t0: float) -> int:
        return int((time.perf_counter() - t0) * 1000)
