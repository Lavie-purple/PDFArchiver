"""库内问答的拼装层 —— S9 屏所有文案的唯一出处（轮三十七 丁 · §E 第 6 问 甲）。

答案 = 检索到的 N 段原文 + 文件名 + 页码，按相似度排序，**不做任何生成**：
零成本、零幻觉、离线、无新依赖。乙（本地模型）将来从这里接一个可插钩子，
没装就退化成甲 —— 本轮不装（线框 §D）。

范围口径（线框写「当前筛选」、落成「全库」的理由，**线框措辞跟实现走**）：
`SemanticSearchService.search` 没有带筛选的路径 —— 与 S1 语义通道是同一件事
（**ISSUES I11** 族：界面不许宣称它做不到的事），而 S9 屏上没有筛选控件，
「当前筛选」四个字在屏幕上没有任何东西可指。所以提示句如实写「范围：全库（N 份）」，
N 是向量库覆盖的文档份数（`stats()`）。

**不加新表、不改既有数据模型**（线框不变量 ①）：这里只读 `vector_meta` /
`documents` / `text_pages`，一个字都不写。
"""
from __future__ import annotations

import time
from dataclasses import dataclass

from pdfarchiver.db.repositories.documents import DocumentRepository
from pdfarchiver.db.repositories.text import TextRepository
from pdfarchiver.semantic.search_service import SemanticSearchService

# 一问带几张证据卡。卡片每张两行（卡头 + 摘录），8 张是右栏滚一屏能读完的量。
TOP_SEGMENTS = 8
# 摘录截断长度。证据卡的价值在"卡头定位到页"，不在"把整页搬上屏"。
EXCERPT_CHARS = 120


@dataclass(frozen=True)
class Evidence:
    """一条证据：一段带页码的原文摘录。`header()` 的措辞只许这一处管。"""

    doc_id: int
    page_no: int
    score: float
    doc_name: str
    excerpt: str

    def header(self) -> str:
        """证据卡卡头：「文件名.pdf｜第 12 页｜相似度 0.63」（线框 §D 甲）。"""
        return f"{self.doc_name}｜第 {self.page_no} 页｜相似度 {self.score:.2f}"


@dataclass(frozen=True)
class Answer:
    """一次提问的完整回执。界面只许渲染这里已有的字段，不许自己拼句子（**ISSUES I60** 族）。"""

    query: str
    elapsed_ms: int
    summary: str
    note: str  # 空答案时说明原因（向量库还没建），有答案时为空
    evidences: tuple[Evidence, ...]


class QaService:
    """抽取式问答。线程不安全（底下的仓储与服务都不线程安全）。"""

    def __init__(self, semantic: SemanticSearchService, documents: DocumentRepository,
                 texts: TextRepository) -> None:
        """`semantic` 必须是装配层那一只（**ISSUES I111** ⑤：第二个实例多养一份
        ONNX session，实测 +36.2 MiB RSS / 懒加载 276 ms，没有理由再养一份）。"""
        self._semantic = semantic
        self._documents = documents
        self._texts = texts

    def stats(self) -> tuple[int, int]:
        """（向量条数, 覆盖文档份数）—— S9 顶栏「范围」与「向量 已建/未建」的读数口。"""
        return self._semantic.stats()

    def ask(self, query: str) -> Answer:
        """就全库提一问，返回抽取式答案。检索异常（模型不在场等）原样抛出，
        由界面按 **ISSUES I84** ③ 的口径落成红字 + 原文。"""
        text = query.strip()
        t0 = time.perf_counter()
        results = self._semantic.search(text, top_k=TOP_SEGMENTS)
        elapsed_ms = round((time.perf_counter() - t0) * 1000)

        evidences: list[Evidence] = []
        for doc_id, page_no, score in results:
            doc = self._documents.get(doc_id)
            if doc is None:  # 与 S1 语义通道同一防御：库里已无这份就不再展示
                continue
            body = self._texts.body_of_page(doc_id, page_no)
            if body is None:  # 向量的入场券就是有可搜正文（I116 甲），走到这即正文已被清
                continue
            collapsed = " ".join(body.split())
            if len(collapsed) > EXCERPT_CHARS:
                collapsed = collapsed[:EXCERPT_CHARS] + "……"
            evidences.append(Evidence(doc_id=doc_id, page_no=page_no, score=score,
                                      doc_name=doc.name, excerpt=collapsed))

        if evidences:
            covered = len({e.doc_id for e in evidences})
            summary = f"共找到 {len(evidences)} 段相关正文，覆盖 {covered} 份文档。"
            note = ""
        else:
            summary = "没有找到相关正文。"
            note = "向量库还没有向量，先在 S7 建语义索引。" if self.stats()[0] == 0 else ""
        return Answer(query=text, elapsed_ms=elapsed_ms, summary=summary,
                      note=note, evidences=tuple(evidences))
