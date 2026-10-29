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
from collections.abc import Mapping
from dataclasses import dataclass, replace

from pdfarchiver.db.models import Document
from pdfarchiver.db.repositories.documents import DocFilter, DocumentRepository, SORTS
from pdfarchiver.db.repositories.metadata import MetadataRepository
from pdfarchiver.db.repositories.text import TextRepository
from pdfarchiver.indexing.fts import (VIA_FTS, channel_for, describe_channel, format_bm25,
                                      match_expression)
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


#: 智能集合要存的那批筛选字段 —— 逐条沿用 `docs/UI-WIREFRAMES.md` §S1 乙 那张表
#: （线框 `docs/wireframes/2026-10-19-round14-i67-i78.html` §I78-yi 点名「字段沿用」）。
#: `text` / `in_fields` / `sort` / `limit` / `offset` **故意不在内**：集合存的是"筛选条件"，
#: 检索词与分页排序是"这一次怎么看"，把后者存进集合等于把一次查询的偶然状态固化成永久条件
#: —— 回放时用户会看到自己上次滚到第几页。
#: 这份清单同时就是 `collections.query_json` 的键集合，所以 `ui/collection_bar.py` 里那份
#: 条件文案表（`CONDITIONS`）必须与它同一批字段；漂移由
#: `test_筛选条这张表与集合能存的字段同一批` 钉住（界面无从 import 本模块，只能这样对）。
QUERY_FIELDS: tuple[str, ...] = (
    "category_ids", "tag_ids", "tag_match_all", "root_key",
    "modified_from", "modified_to", "fts_status",
    "min_pages", "min_size_bytes", "missing_only",
)
_TUPLE_FIELDS = frozenset({"category_ids", "tag_ids"})
_BOOL_FIELDS = frozenset({"tag_match_all", "missing_only"})
_TEXT_FIELDS = frozenset({"root_key", "fts_status"})


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

    def to_query(self) -> dict[str, object]:
        """筛选条件 → 可以直接 `json.dumps` 的字典（智能集合的 `query_json` 存的就是这份东西）。

        tuple 落成 list 是 JSON 的形状，读回来由 `from_query` 还原成 tuple，所以往返两端
        看到的仍是同一个 `Criteria`（线框 §I78-yi 硬断言 (b)）。
        """
        query: dict[str, object] = {}
        for name in QUERY_FIELDS:
            value = getattr(self, name)
            query[name] = list(value) if isinstance(value, tuple) else value
        return query

    @classmethod
    def from_query(cls, query: Mapping[str, object]) -> "Criteria":
        """`query_json` 反序列化回 `Criteria` —— 与 `to_query` 共用上面那一份字段表，没有第二种格式。

        认不出的键**当场拒**：这里出现一个不在 `QUERY_FIELDS` 里的键，要么是有人手写过集合，
        要么格式已经变了；咽下去的结果是"存了一条根本不生效的条件"—— 屏幕上那句条件写着
        筛过，库里一条 WHERE 都没有（**ISSUES I11**「界面不许伪装」在数据侧的版本）。
        """
        unknown = sorted(set(query) - set(QUERY_FIELDS))
        if unknown:
            raise ValueError(f"查询条件里有不认识的键 {unknown}；能存的只有 {list(QUERY_FIELDS)}")
        fields: dict[str, object] = {}
        for name in QUERY_FIELDS:
            value = query.get(name)
            if value is None:
                continue          # 缺键与显式 null 都是"这一条不设条件"，落回 dataclass 的默认值
            if name in _TUPLE_FIELDS:
                if not isinstance(value, (list, tuple)):
                    raise ValueError(f"{name} 要是一串分类/标签 id，收到 {value!r}")
                fields[name] = tuple(int(item) for item in value)
            elif name in _BOOL_FIELDS:
                fields[name] = bool(value)
            elif name in _TEXT_FIELDS:
                fields[name] = str(value)
            else:
                fields[name] = int(value)     # 时间秒 / 页数 / 字节数
        return cls(**fields)      # type: ignore[arg-type]

    def browse_page(self, offset: int = 0) -> "Criteria":
        """把一条筛选条件变成"库里那一列"的第 N 批。

        三个强制项都是浏览的形状而不是检索的形状：没有查询词、按名字序（批与批之间不重
        不漏要靠它，见 `browse_documents`）、磁盘上已经不存在的文档也照样是库里的一条记录。
        `missing_only` 与 `include_missing` 含义相反，所以只看缺失时后者必须关（`validate` 钉着）。
        """
        return replace(self, text="", sort="name", offset=offset,
                       include_missing=not self.missing_only)


def doc_filter_from_query(query: Mapping[str, object] | None) -> DocFilter:
    """筛选条那份 dict → `DocFilter`。**dict 只有一种解释**，所以换算也只有这一处。

    `AppContext.ocr.pending_in` 也要"按当前筛选"取名单：它若自己再解一遍这份 dict，
    同一个键迟早有两种读法（**ISSUES I60** 那族）。界面不碰 `DocFilter`（不许 import db），
    只把 `FilterBar` 存的那份 dict 递进来。
    """
    return Criteria.from_query(query or {}).doc_filter()


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

    @property
    def _short_channel(self) -> str:
        """状态栏那一行用的**短通道名**（轮四十二 ⑤）。

        `channel_label` 那句技术口径（trigram 字数 / LIKE 为何退回）整句在中栏里太长
        —— I60 实测它单独一行 708–816px，挤压的是"符合筛选 / 行数 / 耗时"这些每轮都变的数。
        状态栏只放方向：走了索引没、搜没搜正文。「慢速」二字必须保留 ——
        用户搜 1–2 字看到它才明白是查询词太短（fts.py 模块注释里那条规矩），
        `test_search_service` 与 `test_ui_tier` 都拿它当方向判据；完整口径挪进
        `status_detail()`，两个口径同一个 owner。
        """
        if not self.channel:
            return "只搜文件名 / 路径 / 元数据"
        return "全文索引检索" if self.channel == VIA_FTS else "慢速逐页扫描"

    def status_line(self) -> str:
        """状态栏那一行的口径（**ISSUES I60**）。与 `lines()` 同源同字段，只降措辞密度：
        `lines()` 是给报告和终端读的整句（实测 1056px），而 S1 中栏在最宽的那档（窗口 1280）
        只有 463px 可用（`test_ui_layout` 现测），整句要塞进三行才放得下。这里去掉"查询「…」"
        （查询词就在输入框里，重复一遍不增加信息）和"口径："前缀，线框点名的三样一条不少：
        通道口径、各通道取回的行数、截断 —— 且**没有任何界面自己算出来的数**。
        浅扫自报（**D-051**）也在这一行里：预算截停是真 happened，藏在报告里等于没说。
        轮四十二 ⑤ 之后通道名用 `_short_channel`（技术全称挪去 `status_detail()` 悬停）。
        """
        if not self.criteria.text.strip():
            return self._browse_line()
        return (f"{self._short_channel}｜符合筛选 {self.matching_documents} 份｜{self._counts_text}"
                f"｜本页 {len(self.hits)} 行｜{self.took_ms}ms"
                f"{self._truncation_text}{self._scan_text}")

    def status_detail(self) -> str:
        """状态栏悬停（tooltip）里的完整口径（轮四十二 ⑤）：栏里是短话，悬停是全话 ——
        两句都从这一个类出，界面不拼（**ISSUES I60** 同一条纪律）。"""
        if not self.criteria.text.strip():
            return f"浏览模式（未输入查询词，排序 {self.criteria.sort}）"
        return self.channel_label

    def _browse_line(self) -> str:
        """没输入查询词时那一行，**两个数都必须在场**（**ISSUES I51**）。

        `共 N` 是 `count_matching` 数出来的符合筛选的全库数，`M 行` 是这一页为止表格里
        已经取回的行数（`offset + 本页行数`，还是后端那两个字段，界面没算任何东西）。
        修前这一行写的是 `f"共 {len(docs)} 份文档"`，而 `docs` 来自 `list(limit=1000)` ——
        8,000 份的库里那行说「共 1000 份文档」，把"还有 7,000 份没在表格里"这件事报成了
        "库只有 1000 份"（实测 `table_rows=1000 / db_total_documents=8000`）。
        """
        total = self.matching_documents
        shown = self.criteria.offset + len(self.hits)
        if shown >= total:
            return f"共 {total} 份文档｜表格里 {shown} 行"
        return f"共 {total} 份文档｜表格里已有 {shown} 行，滚动到底继续取下一批"

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

    def suffix(self, hit: Hit) -> str:
        """一条命中"为什么被找到"的**行内短后缀**（轮三十七 甲）—— S1 右栏把它接在
        `rows()` 那句的行尾，界面不自己拼（**ISSUES I60** 那族：文案只有后端一个 owner）。

        轮三十六的整段解释带（选中即出、常驻三行）按线框 §A 甲 改成行内后缀：措辞必须
        缩短，所以页码与出处**不再重复**——`rows()` 的行首已经带 `[第 N 页]` 与
        `｜OCR 识别（可能有错字）`，后缀只补行首没有的那两样：通道口径与相关性分数。
        只用本对象与 `Hit` **取回来时本来就带着的**字段：不重跑查询、不新算分数。
        非正文通道（文件名 / 路径 / 元数据）与正文 LIKE 的 `Hit.score` 恒为 0.0
        （`text.search_like` 的 docstring：「LIKE 没有相关性得分」）—— 所以**只在
        trigram 那一支**报 bm25，另几支一个字都不许提，否则行尾会出现一个 0.00 的假相关度。
        """
        if hit.field == FIELD_BROWSE:
            return "未输入查询词，按当前筛选列出，不带命中位置"
        if hit.field != FIELD_BODY:
            where = hit.field_label + (f"·{hit.field_detail}" if hit.field_detail else "")
            return f"{where} 含查询词（字面匹配）"
        n = len(self.criteria.text.strip())
        # 措辞去行话（轮四十二 ④）：「trigram」「bm25」是实现名，用户要的是"走了索引没、
        # 排得靠前靠后"。技术口径仍留在 `describe_channel` / `channel_label`（状态栏悬停），
        # 这里只出人话。LIKE 分支保「慢速」二字 —— 告诉用户是查询词太短才没走索引。
        if self.channel == VIA_FTS:
            head = f"正文·全文索引（{n} 字）·相关度 {format_bm25(hit.score)}"
        else:
            head = f"正文·慢速逐页扫描（{n} 字，未用索引）"
        # 「-0.00」与「没有得分」长得一样的事归 `format_bm25` 一处管（上面只管报不报）。
        return head + ("｜浅扫未扫完（缺的是库里靠后的页）" if self.body_scan_incomplete else "")


class SearchService:
    def __init__(self, documents: DocumentRepository, metadata: MetadataRepository,
                 text: TextRepository) -> None:
        self.documents = documents
        self.metadata = metadata
        self.text = text

    def search(self, criteria: Criteria, *, known_total: int | None = None) -> SearchResult:
        """把一条查询变成命中结果。

        `known_total` 只给分页浏览的第二批及以后用：`matching_documents` 来自
        `count_matching`，那是一句 `SELECT count(*) … WHERE missing_since IS NULL`，
        而 `ix_documents_missing` 是**部分索引**（只收非 NULL 的行），数 NULL 用不上它 ⇒
        每批都重数就是每批扫一遍全表，滚完整库 = O(库行数²)（AGENTS.md「禁止 O(n²)」）。
        传进来的必须是同一次浏览会话第一批从 `count_matching` 拿到的那个数，不是界面算的数。
        """
        criteria.validate()
        t0 = time.perf_counter()
        filters = criteria.doc_filter()
        needle = criteria.text.strip()
        matching = self.documents.count_matching(filters) if known_total is None else known_total

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

        第三条只有正文的 LIKE 通道可能为真：另外三条扫的是 `documents`（**2026-10-20 现读 10,977 行**，
        清掉 **ISSUES I95** 那三条手写演示数据之后；此前 10,980）与 `document_metadata`，
        量级比正文小两个数量级，给它们设预算是凭空砍召回（**D-051** 只改正文）。
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

    def search_in(self, query: Mapping[str, object], text: str,
                  limit: int = 100) -> SearchResult:
        """在**已选定的筛选条件**里搜查询词（**ISSUES I78** 乙 逼出来的这一条）。

        它替掉了原先的 `search_text(query, limit)`：那条造出的 `Criteria` 一条筛选都不带，
        有了 S1 那排 chips 之后就会变成"屏幕上写着「分类 = 合同」、结果里出来别的分类"——
        界面宣称它在筛，其实没筛（**ISSUES I11** 那一类）。`query` 传 `{}` 就是它原来的行为，
        所以这是一次改名加一个参数，不是一条新能力。

        条件与检索词在这里合成**一个** `Criteria`，四条通道于是仍然共用
        `documents.where_for_filter` 编译出的那一份 WHERE（本模块开头第 1 条规矩）。
        """
        return self.search(replace(Criteria.from_query(query), text=text, limit=limit))

    def browse_documents(self, *, query: Mapping[str, object] | None = None,
                         offset: int = 0, total: int | None = None) -> SearchResult:
        """浏览库里那一列（没有查询词）—— 与 `search_text` 并列的便捷入口，同样不让 UI 自己造 Criteria。

        `query` 就是智能集合存的那份筛选条件（**ISSUES I78** 乙）：点分类树筛一类，与
        回放一个集合，走的是同一个 `Criteria.from_query` 与同一条 SQL。原先这里是一个
        `category_id=` 关键字参数 —— 那样"按分类筛"与"按集合存的那组条件筛"会变成两套入口、
        两套 WHERE，而线框 §I78-yi 要的正是"读写同源"（同一份格式，与 I55 ③ 模板同一条做法）。

        分页单位是一批 `DEFAULT_PAGE_SIZE` 行（§S1 甲 线框那句「滚到底再取下一批 50 条」），
        排序走 `SORTS["name"]` 这**一个**口径（`d.name COLLATE NOCASE, d.id`）：批与批之间
        不重不漏要靠它，界面原来那句 Python 里的 `sort(key=name.casefold)` 是第二个口径。
        `include_missing=True` 与修前的 `documents.list()` 同口径 —— 磁盘上已经不存在的文件
        也是库里的一条记录，缺没缺是这一列要如实说的事实，不是"虚假的有效结果"（那一条管的是检索）。
        `total` 是**第一批**返回的那个 `matching_documents`，第二批起带上它就不必每批重数全表
        （见 `search()` 的 `known_total`）；库里在这期间增删了文档，下一次 `reload()` 会重新数。
        """
        return self.search(Criteria.from_query(query or {}).browse_page(offset),
                           known_total=total)

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
