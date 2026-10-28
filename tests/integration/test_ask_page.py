"""S9 · 库内问答（轮三十七 丁）：答案句 / 证据卡 / 范围读数 / 双击跳页 / 历史提问。

这一屏钉的每一条都是「界面不许自己编」的具体形状：

1. **答案句与卡头的唯一 owner 是 `QaService`**（**ISSUES I60** 族）。界面上那条
   「共找到 N 段…」与每张卡的「文件名｜第 N 页｜相似度 0.63」必须逐字等于后端
   `Answer.summary` / `Evidence.header()` 的返回值 —— 界面里再拼一遍就是第二个口径，
   N 或相似度一变两处必然漂。
2. **证据卡双击 → S2** 复用 S1 的 `open_in_reader` 载荷口径 `(doc_id, page_no)`；
   页码丢了用户就会被送到第 1 页，那比不跳更糟。
3. **范围与向量读数**来自 `VectorStore.stats()` 的同一次扫描 —— 顶栏「范围：全库（N 份）」
   与底栏「向量 已建/未建」必须是同一时刻的同一份事实。
4. **D-040 的 S9 版**：页宽 < 两栏下限（1024 地板档）时左栏「历史提问」收起。

界面测试的语义通道一律注入 `FakeSemantic` —— 真 `SemanticSearchService` 要 ONNX
模型与 1.9 GB 向量文件，那不是单元/集成测试该背的成本；`QaService` 以下全走真仓储与真库。
六条守卫的坏法注入（本轮真跑并当场变红，随后还原）：见各条 docstring 的「坏法」注记。
"""
from __future__ import annotations

import re

import numpy as np
import pytest

from pdfarchiver.db.models import Document, TextPage
from pdfarchiver.fs.identity import identity_key
from pdfarchiver.semantic.qa_service import EXCERPT_CHARS, QaService
from pdfarchiver.semantic.vector_store import VectorStore
from pdfarchiver.ui.pages.ask_page import EXCERPT_NOTE, TWO_COLUMN_MIN_WIDTH, AskPage
from tests.conftest import settle as _settle
from tests.integration.dialog_doubles import stub_message_boxes

NAMED = "归档范围与保留期限的请示.pdf"
DOC_PATH = "D:/用户资料/归档/请示.pdf"
BODY_2 = "归档范围与保留期限的请示正文第三段，保留期限按五年执行"
OCR_NAME = "授权书（扫描件）.pdf"
OCR_BODY = "本授权书由归档处盖章生效，保留期限另议"


class FakeSemantic:
    """假语义通道：返回预置的 (doc_id, page_no, score)，并记下每次查询词。"""

    def __init__(self, results, *, vectors: int, docs: int) -> None:
        self._results = list(results)
        self._vectors = vectors
        self._docs = docs
        self.queries: list[str] = []

    def search(self, query: str, top_k: int = 10) -> list[tuple[int, int, float]]:
        self.queries.append(query)
        return list(self._results[:top_k])

    def stats(self) -> tuple[int, int]:
        return (self._vectors, self._docs)


def _seed_doc(ctx) -> int:
    """一份两页文档（第 1 页短句 / 第 2 页带查询词），返回 doc_id。"""
    doc = ctx.documents.upsert(Document(
        path=DOC_PATH, path_key=identity_key(DOC_PATH),
        name=NAMED, size_bytes=20480, mtime_ns=1_760_000_000_000_000_000,
        page_count=2, text_status="done", fts_status="done"))
    ctx.texts.replace_pages(int(doc.id), [
        TextPage(doc_id=int(doc.id), page_no=1, body="本件为内部流转稿"),
        TextPage(doc_id=int(doc.id), page_no=2, body=BODY_2)])
    return int(doc.id)


@pytest.fixture
def corpus(ctx):
    """两份文档、三种出处（原生第 2 页 / OCR 第 1 页）。"""
    doc_id = _seed_doc(ctx)
    ocr_path = "D:/用户资料/扫描件/授权书.pdf"
    ocr = ctx.documents.upsert(Document(
        path=ocr_path, path_key=identity_key(ocr_path),
        name=OCR_NAME, size_bytes=4096, mtime_ns=1_760_000_000_000_000_000,
        page_count=1, text_status="done", fts_status="done", ocr_status="done"))
    ctx.texts.replace_pages(int(ocr.id), [
        TextPage(doc_id=int(ocr.id), page_no=1, body=OCR_BODY,
                 source_kind="ocr", ocr_version="probe-1")])
    return ctx, doc_id


# —— 服务层：答案句与证据卡都是后端的事实 ——————————————————————

def test_答案句两数来自真检索且卡头由后端管(corpus) -> None:
    """三段命中、覆盖两份 —— summary 的 N 与 M 必须数得出来；卡头措辞只有一个 owner。"""
    ctx, doc_id = corpus
    fake = FakeSemantic([(doc_id, 2, 0.63), (doc_id + 1, 1, 0.58), (doc_id, 1, 0.41)],
                        vectors=3, docs=2)
    answer = QaService(fake, ctx.documents, ctx.texts).ask("保留期限")

    assert answer.summary == "共找到 3 段相关正文，覆盖 2 份文档。", answer.summary
    assert answer.note == ""
    assert [e.header() for e in answer.evidences] == [
        f"{NAMED}｜第 2 页｜相似度 0.63",
        f"{OCR_NAME}｜第 1 页｜相似度 0.58",
        f"{NAMED}｜第 1 页｜相似度 0.41",
    ]
    assert answer.evidences[0].excerpt == BODY_2  # 短摘录 = 页面原文逐字
    assert answer.elapsed_ms >= 0


def test_长摘录按常量截断带省略号不重排(corpus) -> None:
    """截断是确定性的：`EXCERPT_CHARS` + 「……」。卡片的定位靠卡头，摘录只管能读。"""
    ctx, doc_id = corpus
    long_body = "保留期限条款：" + "这一段是凑长度的原文，" * 30
    ctx.texts.replace_pages(doc_id, [
        TextPage(doc_id=doc_id, page_no=1, body="本件为内部流转稿"),
        TextPage(doc_id=doc_id, page_no=2, body=long_body)])
    answer = QaService(FakeSemantic([(doc_id, 2, 0.63)], vectors=1, docs=1),
                       ctx.documents, ctx.texts).ask("保留期限")

    ev = answer.evidences[0]
    assert ev.excerpt.endswith("……")
    assert len(ev.excerpt) == EXCERPT_CHARS + 2, \
        f"摘录 {len(ev.excerpt)} 字 —— 应为 {EXCERPT_CHARS} 字正文 + 省略号"
    assert ev.excerpt[:EXCERPT_CHARS] == " ".join(long_body.split())[:EXCERPT_CHARS]


def test_向量库为空时答案句讲明原因不许装作搜过(corpus) -> None:
    """0 向量时「没有找到相关正文」不是全部事实 —— 用户得知道是库里还没建向量。"""
    ctx, _ = corpus
    answer = QaService(FakeSemantic([], vectors=0, docs=0),
                       ctx.documents, ctx.texts).ask("保留期限")

    assert answer.summary == "没有找到相关正文。"
    assert "向量库还没有向量" in answer.note


def test_stats一次扫描出两个读数(ctx) -> None:
    """`VectorStore.stats()` 是 S9 两个读数的唯一出处 —— 真库上验一次 SQL 本身。

    外键已开（I111 D）：vector_meta 的 doc_id 必须指向真实文档，所以先 upsert 一份。
    """
    path = "D:/用户资料/stats.pdf"
    doc = ctx.documents.upsert(Document(
        path=path, path_key=identity_key(path),
        name="stats.pdf", size_bytes=10, mtime_ns=1))
    store = VectorStore(ctx.paths.root)
    rng = np.random.default_rng(7)
    vecs = [rng.random(512).astype(np.float32) for _ in range(3)]
    store.add_batch([(int(doc.id), 1, vecs[0]), (int(doc.id), 2, vecs[1]),
                     (int(doc.id), 3, vecs[2])])
    assert store.stats() == (3, 1)


# —— 界面：屏在清单上、读数上屏、信号与降级 ——————————————————————

def _goto_ask(window, qapp) -> AskPage:
    window._select_by_page_id("ask")
    _settle(qapp)
    page = window._pages["ask"]
    assert isinstance(page, AskPage) and page.isVisible()
    return page


def test_S9_在导航与清单上部件齐全读数诚实(window, ctx, qapp) -> None:
    """空向量库（测试库没建过向量）：范围 0 份 + 向量未建 —— 两个读数不许编。"""
    page = _goto_ask(window, qapp)
    assert page.ask_btn.text() == "提问"
    assert page.note_label.text() == EXCERPT_NOTE
    assert page.scope_hint.text() == "范围：全库（0 份）", \
        f"空库的范围读数不许编：{page.scope_hint.text()!r}"
    assert page.vector_label.text() == "向量 未建"


def test_提问后答案句与证据卡逐字来自后端(window, ctx, qapp, monkeypatch) -> None:
    """坏法 ①②（真跑变红）：把 summary / 卡头的拼接搬进界面，本条各红在一处断言上。"""
    doc_id = _seed_doc(ctx)
    fake = FakeSemantic([(doc_id, 2, 0.63)], vectors=1, docs=1)
    monkeypatch.setattr(ctx, "qa", QaService(fake, ctx.documents, ctx.texts))

    page = _goto_ask(window, qapp)
    expected = ctx.qa.ask("保留期限")
    page.ask_input.setText("保留期限")
    page._ask()
    _settle(qapp)

    assert page.answer_label.text() == expected.summary, \
        f"答案句不是后端那一句：{page.answer_label.text()!r}"
    assert page.note_label.text() == EXCERPT_NOTE
    assert len(page._cards) == len(expected.evidences)
    for card, ev in zip(page._cards, expected.evidences):
        head = card.findChildren(type(page.answer_label))[0].text()
        assert ev.header() in head, f"卡头不是后端那句：{head!r}"


def test_证据卡双击把整份页码载荷发给外壳(window, ctx, qapp, monkeypatch) -> None:
    """坏法 ③（真跑变红）：payload 只发 doc_id 不发页码 —— 用户会被送到第 1 页。

    对话框替身**必装**（轮十五 甲那次的实测）：种入的文档路径是假的，双击走进 S2 的
    `open_document` 后 `fitz.open` 抛异常 → `QMessageBox.critical` —— offscreen 下真模态
    `exec()` 不红、只永不结束。截住它还能顺手断言「真的走完了 S2 的开门动作」。
    """
    shown = stub_message_boxes(monkeypatch)
    doc_id = _seed_doc(ctx)
    fake = FakeSemantic([(doc_id, 2, 0.63)], vectors=1, docs=1)
    monkeypatch.setattr(ctx, "qa", QaService(fake, ctx.documents, ctx.texts))

    page = _goto_ask(window, qapp)
    page.ask_input.setText("保留期限")
    page._ask()
    _settle(qapp)

    got: list[object] = []
    page.open_in_reader.connect(got.append)
    page._cards[0].mouseDoubleClickEvent(None)  # 处理器不读事件对象；发的是我们自定义的信号
    _settle(qapp)
    assert got == [(doc_id, 2)], \
        f"双击载荷不是 (doc_id, page_no)：{got} —— 页码丢了就是把人送到第 1 页"
    reader = window._pages["reader"]
    assert reader.isVisible(), "双击后没有切到 S2 阅读器"
    assert any(kind == "critical" and "打开 PDF 失败" in title for kind, title, _ in shown), \
        f"种入路径是假的，S2 该如实报打不开：{shown!r}"


def test_历史提问去重置顶且点击重问(window, ctx, qapp, monkeypatch) -> None:
    """坏法 ④（真跑变红）：把 `_remember_history` 改成 append（不置顶不去重）—— 本条红。"""
    fake = FakeSemantic([], vectors=0, docs=0)
    monkeypatch.setattr(ctx, "qa", QaService(fake, ctx.documents, ctx.texts))
    page = _goto_ask(window, qapp)

    for q in ("问题一", "问题二", "问题一"):
        page.ask_input.setText(q)
        page._ask()
        _settle(qapp)
    assert [page.history_list.item(i).text() for i in range(page.history_list.count())] \
        == ["问题一", "问题二"], "历史提问没有去重置顶"

    page.history_list.itemClicked.emit(page.history_list.item(1))
    _settle(qapp)
    assert page.ask_input.text() == "问题二"
    assert fake.queries.count("问题二") == 2, "点历史条目没有真的重问一遍"


def test_1024档左栏收起宽档回来(window, ctx, qapp) -> None:
    """坏法 ⑤（真跑变红）：删掉 resizeEvent 里那一行 setVisible —— 本条红。"""
    page = _goto_ask(window, qapp)
    window.resize(1024, 720)
    _settle(qapp)
    assert not page._history_pane.isVisible(), \
        f"页宽 {page.width()}px < {TWO_COLUMN_MIN_WIDTH}px，历史提问还挂着 —— 1024 档没收"
    window.resize(1280, 800)
    _settle(qapp)
    assert page._history_pane.isVisible(), "回到 1280 档历史提问没回来"


def test_检索失败红字带原文不留旧证据(window, ctx, qapp, monkeypatch) -> None:
    """**ISSUES I84** ③ 的 S9 版：异常穿出 Qt 槽 = 屏幕上什么都不发生。接住，红字 + 原文。"""
    class Boom(FakeSemantic):
        def search(self, query: str, top_k: int = 10):
            raise FileNotFoundError("模型目录不存在：data/models/embedding")

    monkeypatch.setattr(ctx, "qa", QaService(Boom([], vectors=0, docs=0),
                                             ctx.documents, ctx.texts))
    page = _goto_ask(window, qapp)
    page.ask_input.setText("保留期限")
    page._ask()
    _settle(qapp)

    assert "模型目录不存在" in page.answer_label.text(), \
        f"失败原因原文没上屏：{page.answer_label.text()!r}"
    assert page.answer_label.objectName() == "danger", "失败读数没有走红字"
    assert page._cards == [], "失败后还挂着上一问的证据卡"


def test_耗时与向量读数在提问后上屏(window, ctx, qapp, monkeypatch) -> None:
    doc_id = _seed_doc(ctx)
    fake = FakeSemantic([(doc_id, 2, 0.63)], vectors=1, docs=1)
    monkeypatch.setattr(ctx, "qa", QaService(fake, ctx.documents, ctx.texts))

    page = _goto_ask(window, qapp)
    page.ask_input.setText("保留期限")
    page._ask()
    _settle(qapp)

    assert re.fullmatch(r"检索耗时 [\d,]+ ms", page.time_label.text()), \
        f"耗时读数口径不对：{page.time_label.text()!r}"
    assert page.vector_label.text() == "向量 已建"
