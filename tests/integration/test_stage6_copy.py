"""阶段 6 那两处入口的文案与容错，钉到与后端同源（销账 **ISSUES I84** 甲）。

三处症状同一条根：**界面替后端说了后端没说过的话**（**ISSUES I31** / **I87** 的第三个实例）：

① `ai_classify_btn` 的 tooltip 原先写「基于**文档内容**与分类语义中心的相似度推荐分类」，而
   `semantic/classify_service.py:131-136` 送进 embedding 的文本是「上级目录名 + 文件名」，
   一个字的文档内容都没读 —— 用户看到"乱推荐"时按那句话去找模型问题，找不到；
② 空态那句「暂无向量数据，**请先执行语义索引**」指向一个产品里**不存在**的动作
   （`VectorStore.add*` 零产品调用方、`vector` 从不入队 —— **ISSUES I63** 丙/丁）；
③ `_do_semantic_search` 原先没有 `except`，模型缺失时服务层抛 `FileNotFoundError`
   （2026-10-18 真机原文逐字：`语义模型不存在：<数据根>\\models\\bge-small-zh-v1.5\\onnx\\model_int8.onnx`
   换行 `请先下载 bge-small-zh-v1.5 到 <数据根>\\models`），异常穿出 Qt 槽 ⇒ **屏幕上什么都不发生**
   （表格停在上一状态），原文只进 `crash.log`。勾了「语义搜索」、点了、没反应，还没有一句话
   告诉他为什么 —— 而本机真根的 `models/` 今天就不存在，这是常态不是边角。

四条文案/容错断言各钉一处，第五条钉的是 ③ 落地时**新引入**的风险：状态栏一旦能被染红，
就必须保证下一次成功把红收回去（否则"可见的失败"变成"常驻的失败"）。
状态栏那句去掉「或模型不可用」也算一条：③ 之后模型缺失是**抛错**，不再是"无结果"的一种原因。

夹具三条规矩照常（offscreen、独立数据根、真 sqlite3 —— **D-012**）；
库里的文档全是现造的假名字，真实语料一条不进测试（**ISSUES I64**）。
"""
from __future__ import annotations

from pathlib import Path

from pdfarchiver.db.models import Document
from pdfarchiver.fs.identity import identity_key
from pdfarchiver.services.bootstrap import AppContext
from tests.conftest import settle as _settle

_SRC = Path(__file__).resolve().parents[1] / "src" / "pdfarchiver"
# 假原文（不写本机路径字面量：`tests/guards/test_architecture.py` 拦的就是源码常量里的盘符）
_MODEL_MISSING = "语义模型不存在：（本场假路径）bge-small-zh-v1.5/onnx/model_int8.onnx"
_QUERY = "测试查询词至少三个字"   # trigram 口径下两字查询恒 0 条，夹具里的词不许短（阶段 2 实测）


def _library(window, qapp):
    window._select_by_page_id("library")
    _settle(qapp)
    page = window._pages["library"]
    page.reload()
    _settle(qapp)
    return page


def _seed_doc(ctx: AppContext, name: str = "合同000001号.pdf") -> int:
    path = f"D:\\用户资料\\2026 年度合同与结算凭证归档\\{name}"
    row = ctx.documents.upsert(Document(
        path=path, path_key=identity_key(path), name=name, size_bytes=1024,
        mtime_ns=1_760_000_000_000_000_000, sha256="a" * 64,
        text_status="done", fts_status="done"))
    return int(row.id)


def _raise_missing(query: str, top_k: int = 50):
    raise FileNotFoundError(_MODEL_MISSING)


def test_AI推荐分类的tooltip只说后端真读的那两样(window, qapp) -> None:
    """①：tooltip 的名词必须与 `classify_service` 的取数处一一对读，不是措辞偏好。"""
    page = _library(window, qapp)
    tip = page.ai_classify_btn.toolTip()
    assert "文件名" in tip and "目录" in tip, f"tooltip 要写后端实际读的两样（名字与上级目录名）：{tip!r}"
    assert "文档内容" not in tip, f"后端一个字的正文都没读，tooltip 不许承诺它：{tip!r}"


def test_空态文案不许指向产品里不存在的动作(window, qapp, ctx, monkeypatch) -> None:
    """②：界面上任何一句「请先做 X」，X 必须在产品里真有一个入口 —— 全站一次扫，不是只改这一屏。"""
    _seed_doc(ctx)
    page = _library(window, qapp)
    page.doc_table.selectRow(0)
    _settle(qapp)
    assert page._selected_doc_id is not None, "没选中行就点按钮，等于没走过那条分支"
    monkeypatch.setattr(ctx.ai_classify, "suggest_for_doc", lambda doc_id: [])
    page.ai_classify_btn.click()
    text = page.ai_result_label.text()
    assert "暂无向量数据" in text, f"空态要当场说清是空态：{text!r}"
    assert "请先执行语义索引" not in text, f"这句把人引向一个不存在的按钮：{text!r}"
    # 规则而不是补丁：src 下任何一处再写这句都算违规（同 I88 那条「判据打在真东西上」）
    hits = [str(p.relative_to(_SRC.parent.parent)) for p in _SRC.rglob("*.py")
            if "请先执行语义索引" in p.read_text(encoding="utf-8")]
    assert not hits, f"产品里还留着指向不存在动作的文案：{hits}"


def test_模型缺失时语义搜索把后端原文染红上屏(window, qapp, ctx, monkeypatch) -> None:
    """③：失败必须**可见**，且可见的是后端原文，不是界面重述的一句猜测。"""
    page = _library(window, qapp)
    _seed_doc(ctx)
    monkeypatch.setattr(ctx.semantic_search, "search", _raise_missing)
    page._do_semantic_search(_QUERY)
    assert _MODEL_MISSING in page.status_label.text(), \
        f"报错原文必须逐字上屏，而不是只进 crash.log：{page.status_label.text()!r}"
    assert page.status_label.objectName() == "danger", \
        f"失败态要与常态可区分（与 AI 分类那条同一口径）：{page.status_label.objectName()!r}"
    assert page.doc_table.rowCount() == 0, "状态栏是「表里这些行是什么」的唯一口径，失败后不许留着上一批行"
    assert page.hit_list.count() == 0, "右栏命中面板同理：失败之后不许还挂着上一批命中"


def test_一次失败之后紧接着的成功不许留着红(window, qapp, ctx, monkeypatch) -> None:
    """③ 的副作用：状态栏从此可被染红 ⇒ 成功路径必须把它收回去（这条预期为绿，是负对照）。"""
    page = _library(window, qapp)
    doc_id = _seed_doc(ctx)
    monkeypatch.setattr(ctx.semantic_search, "search", _raise_missing)
    page._do_semantic_search(_QUERY)
    assert page.status_label.objectName() == "danger"
    monkeypatch.setattr(ctx.semantic_search, "search",
                        lambda query, top_k=50: [(doc_id, 1, 0.87)])
    page._do_semantic_search(_QUERY)
    assert page.status_label.objectName() != "danger", \
        "红是失败态专用的；成功后还挂着红等于把一次失败变成常驻"
    assert "命中 1 份" in page.status_label.text(), page.status_label.text()


def test_无结果那句不再提模型(window, qapp, ctx, monkeypatch) -> None:
    """③ 之后「模型不可用」是**抛错**，不再是"无结果"的一种原因；那句话留着就是第二句假话。"""
    page = _library(window, qapp)
    monkeypatch.setattr(ctx.semantic_search, "search", lambda query, top_k=50: [])
    page._do_semantic_search(_QUERY)
    text = page.status_label.text()
    assert "模型" not in text, f"无结果的原因只剩向量库为空，那句里的「模型」已经不该在场：{text!r}"
    assert "向量" in text, f"要说清空的是哪一个库：{text!r}"
    assert page.status_label.objectName() != "danger", "空结果不是失败，不许染红"
