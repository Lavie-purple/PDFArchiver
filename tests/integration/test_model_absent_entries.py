"""轮五十一 · 模型不在场时那三个入口（Q1 乙 / Q3 乙 / Q4 乙）+ 丁-2 的建向量入口（Q2 甲·丁-2）。

起因是 **ISSUES I84** 乙那一条「语义搜索勾选框在模型缺席时该不该置灰」，读码时发现它不是孤例：
一只 `EmbeddingService` 挂着三个入口（S1「语义搜索」、S1「AI 推荐分类」、S9「提问」），三处都
接住了异常、都不崩，但**报错发生在动作之后**，而且那两段原文各带一个绝对路径。勾了、点了、
屏幕上出来一串带盘符的模型文件路径 —— 这条路只有开发机能看懂。

定案的形状是**判定一处、消费三处**：谓词升成 `EmbeddingService.model_ready()`，装配时快照成
`AppContext.semantic_ready` 一个布尔，界面只读它。快照不是偷懒，是 Q1 乙「不做热探测」的实现
形态 —— 界面拿不到第二个口径，也就没法轮询。

夹具的一条硬事实（本轮抓到并写进 `conftest.plant_model_files`）：**测试数据根里永远没有模型**，
所以整套测试默认跑在「不在场」那一档。这既是好事（开发机看不见的状态被默认覆盖），也是陷阱
（断言「入口能用」的用例必须自己换到 `window_ready` / `ctx_ready`）。

十八条判据，坏法逐条对应线框 §3 末那张表：① 谓词在 UI 里重算 ② 只改一处入口
③ 置灰顺手废掉输入框 ④ 置灰了却没写「需重启」⑤ 绝对路径进界面。另加丁-2 的三条：
排队回执与后端同源、没正文那份如实染红、绝不自动发生。
"""
from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import pytest

from pdfarchiver.db.models import Document
from pdfarchiver.fs.identity import identity_key
from pdfarchiver.services.bootstrap import AppContext, bootstrap
from pdfarchiver.semantic.embedding import EmbeddingService
from pdfarchiver.semantic.vector_store import VectorStore
from pdfarchiver.ui.semantic_state import ABSENT_REASON, DISABLE_TIP
from tests.conftest import plant_model_files, run_search as _run_search, settle as _settle

_SRC = Path(__file__).resolve().parents[2] / "src" / "pdfarchiver"
_UI = _SRC / "ui"
# 假原文（带盘符是有意的：判据⑤要能被抓住 —— `MACHINE_LOCAL_PATH_RE` 只扫 src，测试文件里
# 写假路径不违规；但写一条**没有**盘符的假路径会让「不含路径」那条断言恒真、抓不住任何东西）
_FAKE_ROOT = "C:/假数据根"
_MODEL_MISSING = (f"语义模型不存在：{_FAKE_ROOT}/models/{EmbeddingService.MODEL_NAME}"
                  f"/onnx/model_int8.onnx\n请先下载 {EmbeddingService.MODEL_NAME} 到 {_FAKE_ROOT}/models")
_QUERY = "测试查询词至少三个字"


def _raise_missing(*a, **k):
    raise FileNotFoundError(_MODEL_MISSING)


def _library(window, qapp):
    window._select_by_page_id("library")
    _settle(qapp)
    page = window._pages["library"]
    page.reload()
    _settle(qapp)
    return page


def _ask(window, qapp):
    window._select_by_page_id("ask")
    _settle(qapp)
    return window._pages["ask"]


def _seed_doc(ctx: AppContext, name: str = "合同000001号.pdf", *, searchable: bool = True) -> int:
    """「有正文可搜」按产品口径写：`has_searchable_text` 认的是 `text_status ∈ (native, mixed)`。

    夹具最初把它写成 `text_status="done"`（那是 `fts_status` 的词表），于是"点一次恰好排一条"
    那条真红了 —— 红的是夹具不是产品，这种偏要当场改，不然丁-2 的判据永远验不到排队。
    """
    path = f"D:\\用户资料\\2026 年度合同与结算凭证归档\\{name}"
    row = ctx.documents.upsert(Document(
        path=path, path_key=identity_key(path), name=name, size_bytes=1024,
        mtime_ns=1_760_000_000_000_000_000, sha256="a" * 64,
        text_status="native" if searchable else "pending",
        fts_status="done" if searchable else "pending"))
    return int(row.id)


def _select_first_row(page, qapp) -> None:
    page.reload()
    _settle(qapp)
    page.doc_table.selectRow(0)
    _settle(qapp)
    assert page._selected_doc_id is not None, "没选中行，「没有当前行」那一层会盖住要验的那一层"


def _vector_jobs(ctx: AppContext) -> list:
    return [j for j in ctx.jobs.list() if j.kind == "vector"]


def _give_a_category_center(ctx: AppContext, doc_id: int) -> None:
    """让「AI 推荐分类」真的会去碰模型 —— 不给这一步，这一处根本走不到失败那条路。

    `AIClassifyService.suggest()` 先算分类中心：向量库为空 ⇒ 当场返回空列表，**模型一次都不碰**
    （屏上是「暂无向量数据」，不是红字）。所以要验"过期快照也不许吐路径"，必须先给某个已归类的
    文档落一条向量，让 `embed_single` 非被调用不可。
    """
    cat = ctx.catalog.add_category("语义缺席测试")
    ctx.catalog.link_category(doc_id, cat.id)
    vec = np.random.default_rng(11).random(512).astype(np.float32)
    VectorStore(ctx.paths.root).add_batch([(doc_id, 1, vec)])


# —— 谓词本身：与抛错处同一条路径口径 ——

def test_谓词与抛错处同源_两条文件缺一即假(data_root: Path) -> None:
    """`model_ready()` 说「在」而 `embed` 抛「不在」，指路就成了假指路。三档真跑一遍。"""
    model_dir = plant_model_files(data_root)
    service = EmbeddingService(data_root)
    assert service.model_ready() is True, "两条文件都在却说不在"

    (model_dir / EmbeddingService.TOKENIZER_FILE).unlink()
    assert service.model_ready() is False, "分词器不在却仍说能用 —— 勾选框就是骗人的"
    with pytest.raises(FileNotFoundError) as gone:
        service.embed_single("测试")
    assert "分词器不存在" in str(gone.value)

    (model_dir / EmbeddingService.MODEL_FILE).unlink()
    assert service.model_ready() is False, "两条都不在还说在场"
    with pytest.raises(FileNotFoundError) as both:
        service.embed_single("测试")
    assert "语义模型不存在" in str(both.value)


def test_装配快照唯一决定界面读到的那一个布尔(data_root: Path) -> None:
    """`semantic_ready` 是装配时的一次快照：装配前放好文件才为真，装配之后放不算。"""
    without = bootstrap(data_root)
    try:
        assert without.semantic_ready is False, "干净数据根里说模型在场"
    finally:
        without.shutdown()

    ready_root = data_root.parent / "with-model"
    plant_model_files(ready_root)
    with_model = bootstrap(ready_root)
    try:
        assert with_model.semantic_ready is True, "放好了却说不在 —— 三个入口会白灰一片"
    finally:
        with_model.shutdown()


# —— 消费三处：同一个布尔驱动，一条都不漏 ——

def test_不在场时三个入口一起灰由同一个布尔驱动(window, ctx, qapp) -> None:
    """坏法②「只改一处」的红点就在这里：四行同一次判定，漏一处就红。"""
    assert ctx.semantic_ready is False, "夹具前提：测试数据根里没有模型"
    page = _library(window, qapp)
    _seed_doc(ctx)
    _select_first_row(page, qapp)
    for name in ("semantic_toggle", "ai_classify_btn", "vector_btn"):
        assert not getattr(page, name).isEnabled(), f"模型不在场，{name} 还亮着"
    assert not _ask(window, qapp).ask_btn.isEnabled(), "模型不在场，S9「提问」还亮着"


def test_在场时三处行为与改动前逐字同(window_ready, ctx_ready, qapp) -> None:
    """Q1 乙的防回归承诺：在场 = 这一屏什么都没改过（连 tooltip 的措辞都不许漂）。"""
    page = _library(window_ready, qapp)
    assert page.semantic_toggle.isEnabled()
    assert page.semantic_toggle.toolTip() == "使用 AI 向量匹配，而非关键词匹配"
    assert page.search_input.isEnabled() and page.search_input.toolTip() != DISABLE_TIP
    _seed_doc(ctx_ready)
    _select_first_row(page, qapp)
    assert page.ai_classify_btn.isEnabled(), "在场且选中行，推荐分类该可用"
    assert page.ai_classify_btn.toolTip() == "按文件名与所在目录名推荐分类（不读文档正文）"
    assert page.vector_btn.isEnabled(), "丁-2：在场且选中行，建向量该可用"
    ask = _ask(window_ready, qapp)
    assert ask.ask_btn.isEnabled() and ask.ask_btn.toolTip() == "", "在场不该给提问按钮加新话"


def test_指路那句两层都说到_Q4乙(window, qapp) -> None:
    """Q4 乙：只说「现在不能用」是半句实话 —— 放好模型不重启仍然不能用，必须同屏说到。"""
    page = _library(window, qapp)
    tip = page.semantic_toggle.toolTip()
    assert tip == DISABLE_TIP, f"三个入口必须同一句（指路只写一处）：{tip!r}"
    assert "重启" in tip, f"没写重启才生效，置灰本身就成了新的假话：{tip!r}"
    assert "不在本机" in tip or "没有" in tip, f"没说不做不了的原因：{tip!r}"
    assert _ask(window, qapp).ask_btn.toolTip() == DISABLE_TIP


def test_放好模型不重启仍然灰_没有热探测(window, ctx, qapp) -> None:
    """Q1 乙「不做热探测」的可证伪形态：装配之后放文件，界面一条都不动。"""
    page = _library(window, qapp)
    plant_model_files(ctx.paths.root)
    page.reload()
    _settle(qapp)
    assert ctx.semantic_ready is False, "快照被改写了，那就不是「只在建窗时问一次」"
    assert not page.semantic_toggle.isEnabled(), "没重启就变亮，说明有一条探测在跑"


def test_置灰不许顺手废掉关键词通道(window, ctx, qapp) -> None:
    """坏法③「置灰顺手把输入框也废了」：全文搜索与模型无关，一条都不该跟着躺。"""
    page = _library(window, qapp)
    assert page.search_input.isEnabled(), "语义不可用≠搜索不可用"
    assert page.search_btn.isEnabled() and page.clear_btn.isEnabled()
    _seed_doc(ctx, name="保留期限与归档范围的请示.pdf")
    page.reload()
    _settle(qapp)
    page.search_input.setText("保留期限")
    _run_search(page, qapp)
    _settle(qapp)
    assert page.doc_table.rowCount() == 1, f"关键词通道该照常出结果：{page.doc_table.rowCount()} 行"
    assert page.status_label.objectName() != "danger", "正常出了结果却被染红"


def test_界面不自算谓词_ui里不许出现第二个模型路径口径() -> None:
    """坏法①「口径第二份」：模型路径口径只有 `EmbeddingService` 一处，界面只许读那一个布尔。"""
    hits = []
    for py in _UI.rglob("*.py"):
        text = py.read_text(encoding="utf-8")
        for token in ("models_dir", "MODEL_NAME", "EmbeddingService", "model_ready"):
            if token in text:
                hits.append(f"{py.relative_to(_SRC.parent.parent)}:{token}")
    assert not hits, f"界面自己拼了一遍模型路径，就有了第二个口径：{hits}"
    assert "ctx.semantic_ready" in (_UI / "pages" / "library_page.py").read_text(encoding="utf-8"), \
        "S1 没读那一个布尔，说明它的置灰是从别处算出来的"


def test_那句不在本机只覆盖模型缺席_semantic层别处不许抛同类型异常() -> None:
    """Q3 乙那句之所以不是猜测：`semantic/` 里 `raise FileNotFoundError` 只有 embedding 那两条。

    别处（archive / backup）也抛同类型异常，但它们不经过 `absent_or_original` 这个出口；
    若哪天语义层多了一处同类型抛出，屏上那句「不在本机」就开始说假话 —— 这条先红。
    """
    offenders = [py.name for py in (_SRC / "semantic").rglob("*.py")
                 if "raise FileNotFoundError" in py.read_text(encoding="utf-8")
                 and py.name != "embedding.py"]
    assert not offenders, f"语义层多了一处 FileNotFoundError，界面上那句话不再等价：{offenders}"


# —— Q3 乙：一句上屏，原文进日志 ——

def test_语义搜索失败只上一句原文进日志(window, ctx, qapp, monkeypatch, caplog) -> None:
    page = _library(window, qapp)
    monkeypatch.setattr(ctx.semantic_search, "search", _raise_missing)
    with caplog.at_level(logging.WARNING, logger="pdfarchiver"):
        _run_search(page, qapp, _QUERY, semantic=True)
    text = page.status_label.text()
    assert ABSENT_REASON in text, f"没上那一句实话：{text!r}"
    assert _FAKE_ROOT not in text and "model_int8" not in text, f"绝对路径进界面了（坏法⑤）：{text!r}"
    assert page.status_label.objectName() == "danger"
    assert _MODEL_MISSING.splitlines()[0] in caplog.text.replace("\r\n", "\n"), \
        "原文没进日志 —— 隐藏路径不能把诊断价值一起藏掉"
    assert page.doc_table.rowCount() == 0 and page.hit_list.count() == 0, "失败后不许留上一批行"


def test_AI分类失败只上一句原文进日志(window, ctx, qapp, monkeypatch, caplog) -> None:
    page = _library(window, qapp)
    _seed_doc(ctx)
    _select_first_row(page, qapp)
    monkeypatch.setattr(ctx.ai_classify, "suggest_for_doc", _raise_missing)
    with caplog.at_level(logging.WARNING, logger="pdfarchiver"):
        page._on_ai_classify_clicked()
    text = page.ai_result_label.text()
    assert ABSENT_REASON in text and _FAKE_ROOT not in text, f"这一处漏了（坏法②）：{text!r}"
    assert page.ai_result_label.objectName() == "danger"
    assert _FAKE_ROOT in caplog.text, "原文没进日志"


def test_提问检索失败只上一句原文进日志(window, ctx, qapp, monkeypatch, caplog) -> None:
    page = _ask(window, qapp)
    monkeypatch.setattr(ctx.semantic_search, "search", _raise_missing)
    page.ask_input.setText("保留期限")
    with caplog.at_level(logging.WARNING, logger="pdfarchiver"):
        page._ask()
    text = page.answer_label.text()
    assert ABSENT_REASON in text and _FAKE_ROOT not in text, f"S9 这一处漏了：{text!r}"
    assert page.answer_label.objectName() == "danger"
    assert page._cards == [], "失败后不许还挂着上一问的证据卡"
    assert _FAKE_ROOT in caplog.text


def test_建窗之后模型被移走点击仍只上一句(window_ready, ctx_ready, qapp, caplog) -> None:
    """这一档才是用户真能走到的路：在场建窗 → 模型被删走 → 点。快照过期了，界面仍不许吐路径。"""
    page = _library(window_ready, qapp)
    doc_id = _seed_doc(ctx_ready)
    _give_a_category_center(ctx_ready, doc_id)
    _select_first_row(page, qapp)
    model_dir = ctx_ready.paths.models_dir / EmbeddingService.MODEL_NAME
    for relative in (EmbeddingService.MODEL_FILE, EmbeddingService.TOKENIZER_FILE):
        (model_dir / relative).unlink()
    with caplog.at_level(logging.WARNING, logger="pdfarchiver"):
        # 顺序与取数都有讲究：失败的那次语义搜索会把中栏表清空（产品行为：不许留上一批行），
        # 清表连带把当前行与右栏那一行的读数一起抹掉 ⇒ 先点分类、当场把它的文字存下来，
        # 再搜索。反过来写会被「没有当前行」的早退盖住，AI 分类那一处就验不到了。
        page._on_ai_classify_clicked()
        ai_text = page.ai_result_label.text()
        _run_search(page, qapp, _QUERY, semantic=True)
    status_text = page.status_label.text()
    assert ABSENT_REASON in status_text, f"过期快照下把后端原文吐上了屏：{status_text!r}"
    assert ABSENT_REASON in ai_text, f"AI 分类这一处吐了原文：{ai_text!r}"
    assert str(model_dir) not in status_text + ai_text
    assert "model_int8" not in status_text + ai_text
    assert "语义模型不存在" in caplog.text, "藏路径的同时把原文一起藏了，等于没有诊断"


def test_一句之外的失败仍回原文_不吞掉别的FileNotFoundError(window, ctx, qapp, monkeypatch) -> None:
    """「不在本机」这句只许说模型那一条：同类型但不同原因的异常不许被套进同一句里。"""
    page = _library(window, qapp)
    _seed_doc(ctx)
    _select_first_row(page, qapp)
    monkeypatch.setattr(ctx.ai_classify, "suggest_for_doc",
                        lambda *a, **k: (_ for _ in ()).throw(ValueError("向量库文件读不了")))
    page._on_ai_classify_clicked()
    text = page.ai_result_label.text()
    assert "向量库文件读不了" in text, f"后端原文被换成了一句不相干的话：{text!r}"
    assert ABSENT_REASON not in text


# —— 丁-2：用户真能点到的建向量入口 ——

def test_点名建向量走真入队回执与后端同源(window_ready, ctx_ready, qapp) -> None:
    page = _library(window_ready, qapp)
    doc_id = _seed_doc(ctx_ready)
    _select_first_row(page, qapp)
    page.vector_btn.click()
    _settle(qapp)
    jobs = _vector_jobs(ctx_ready)
    assert len(jobs) == 1, f"点一次该恰好排进一条：{[(j.kind, j.doc_id) for j in jobs]}"
    assert int(jobs[0].doc_id) == doc_id
    text = page.status_label.text()
    assert "点名 1 份" in text and "新增任务 1 条" in text, \
        f"回执必须是后端 `describe()` 的原样，不是界面重拼：{text!r}"
    assert page.status_label.objectName() != "danger", "排上了却报失败"


def test_没有可搜正文那份如实染红不假装排队(window_ready, ctx_ready, qapp) -> None:
    page = _library(window_ready, qapp)
    _seed_doc(ctx_ready, name="扫描件未识别.pdf", searchable=False)
    _select_first_row(page, qapp)
    page.vector_btn.click()
    _settle(qapp)
    assert not _vector_jobs(ctx_ready), f"没正文的一份不该排进队列：{_vector_jobs(ctx_ready)}"
    assert page.status_label.objectName() == "danger", "新增 0 条是失败态，不许留常态色"
    assert "没有可搜的正文" in page.status_label.text(), f"要说出是哪一个原因：{page.status_label.text()!r}"


def test_不在场时建向量点不动且建窗后队列一条都没有(window, ctx, qapp) -> None:
    """两条各钉一层：入口灰着（点下去无事），且**绝不自动**排向量。"""
    page = _library(window, qapp)
    _seed_doc(ctx)
    page.reload()
    _settle(qapp)
    assert not _vector_jobs(ctx), "还没点就排了向量 —— 丁-2 的前提是永不自动"
    _select_first_row(page, qapp)
    page.vector_btn.click()
    _settle(qapp)
    assert not page.vector_btn.isEnabled() and not _vector_jobs(ctx), "灰着的按钮仍把任务排了进去"


def test_S9空态那句不再承诺自动建立(window, qapp) -> None:
    """**ISSUES I84** ② 的第四个实例：「索引完成后会自动建立」指向一个产品里不存在的自动行为。"""
    page = _ask(window, qapp)
    hint = page.empty_hint.text()
    assert "自动建立" not in hint, f"向量没人点名就不会出现，这句是第二句假话：{hint!r}"
    assert "点名" in hint and "为当前文档建向量" in hint, f"要指到真存在的按钮：{hint!r}"
    hits = [str(p.relative_to(_SRC.parent.parent)) for p in _SRC.rglob("*.py")
            if "自动建立" in p.read_text(encoding="utf-8")]
    assert not hits, f"产品里还留着承诺自动建立的文案：{hits}"
