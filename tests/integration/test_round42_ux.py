"""轮四十二走查修复批的行为守卫（别扭点清单 ①②③⑤⑥⑦⑨⑩⑪⑬⑯ + 标题行乙）。

分工：⑭ 右栏浮层化的**几何**守卫在 `test_ui_tier.py`（同一控件两档形状归那一档量），
④ 后缀措辞与 ⑤ 状态栏方向钉在 `test_hit_explain.py` / `test_search_service.py`（后端口径归
服务层测试），这里钉的是**这一轮改出来的界面行为**：默认收起的区（⑬⑯）、空态指路（⑨⑩⑪）、
跳转兜底（①）、详情占位（②）、上次读到措辞（③）、tooltip 口径（⑤ 界面半边）、
忙碌光标（⑥）、空分类指路（⑦）。

所有断言都在 offscreen 下走真实接线（点真的按、选真的选），不读控件默认值——
"按钮存在"不等于"接上了"，这一条是本项目反复被抓的老坑。
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6 import QtCore, QtWidgets

from pdfarchiver.db.models import Document
from pdfarchiver.fs.identity import identity_key
from pdfarchiver.services.bootstrap import AppContext
from pdfarchiver.ui.main_window import DEFAULT_WINDOW_HEIGHT, DEFAULT_WINDOW_WIDTH, MIN_WINDOW_HEIGHT
from tests.conftest import settle as _settle


def _page_at(window, qapp, page_id: str):
    """切到某一屏、重查一遍（与 test_ui_tier 同一条纪律：隐藏页量出的全是 0）。

    `reload()` 不是每屏都有（ArchivePage 没有它，⑪ 的提示收放自己挂在 textChanged 上），
    有就调、没有就跳 —— 不能让助手函数替某一屏发明接口。
    """
    window._select_by_page_id(page_id)
    _settle(qapp)
    page = window._pages[page_id]
    if hasattr(page, "reload"):
        page.reload()
    _settle(qapp)
    assert page.isVisible(), f"用例前提：{page_id} 得是当前可见页"
    return page


def _seed_docs(ctx: AppContext, count: int = 2) -> list[int]:
    ids = []
    for n in range(count):
        path = f"D:\\用户资料\\轮四十二样本{n}.pdf"
        doc = ctx.documents.upsert(Document(
            path=path, path_key=identity_key(path), name=f"轮四十二样本{n}.pdf",
            size_bytes=1024, mtime_ns=1_760_000_000_000_000_000,
            sha256=f"{n:064x}", text_status="done", fts_status="done"))
        ids.append(int(doc.id))
    return ids


# —— ⑯ 动作行：点名才出现 ——————————————————————————————————————————

def test_动作行默认藏_点名出现_清空收起(window, qapp) -> None:
    """⑯：没点名时「送去识别 + 三颗写入按钮」整排不占屏；点名 ≥1 份才出现。

    坏法注入实测（2026-10-30）：把 `library_page.py` 的 `self.action_row.setVisible(named > 0)`
    改回 `setVisible(True)` ⇒ 本条红在「清空选中就该整排收起」（点名前的默认态没被碰到：
    处理器没跑过，收着的就是收着的 —— 三段里只有"清空"这一段真正过了处理器）。
    """
    page = _page_at(window, qapp, "library")
    _seed_docs(page.ctx)
    page.reload()
    assert not page.action_row.isVisible(), "没点名任何一份，动作行默认就该收起"

    page.doc_table.selectRow(0)
    _settle(qapp)
    assert page.action_row.isVisible(), "点名之后动作行该出现（灰按钮挂着是堆积，点不到是别的 bug）"

    page.doc_table.clearSelection()
    _settle(qapp)
    assert not page.action_row.isVisible(), "清空选中就该整排收起，不能留一排灰按钮"


# —— ⑬ 筛选区：默认收起，有条件自动展开 ——————————————————————————————

def test_筛选区默认收起_加条件自动展开_手动收放有效(window, qapp) -> None:
    """⑬：一条条件都没有时筛选条 + 「按当前筛选送识别」收进「▸ 筛选与集合」后面。

    坏法注入实测（2026-10-30）：把 `_update_filter_area` 里 `visible = …` 硬改成 True
    ⇒ 本条红在「默认收起」。
    """
    page = _page_at(window, qapp, "library")
    assert not page.filter_area.isVisible(), "没加条件时筛选区默认收起"
    assert page.filter_toggle.text().startswith("▸"), "收起态的开关该是 ▸"

    page.filter_bar.set_field("category_ids", [1])
    _settle(qapp)
    assert page.filter_area.isVisible(), "有条件时筛选区自动展开（自动规则：有条件=开）"
    assert page.filter_toggle.text().startswith("▾"), "展开态的开关该是 ▾"

    # 手动收起：意愿生效，条件本身还在（收起≠清空）
    page.filter_toggle.click()
    _settle(qapp)
    assert not page.filter_area.isVisible()
    assert page._query.get("category_ids"), "收起只是收，不许把用户筛好的条件一起清掉"


# —— 标题行乙：浮层标题行整行删除 ——————————————————————————————————————————

def test_浮层没有标题行_关闭键是角标(window) -> None:
    """标题行乙：`FloatablePanel` 不再有那条从没 setText 的 `sectionTitle` 行，
    出口收成右上角一颗「✕」角标（浮层形状下才可见）。

    判据只认**空文本**的 sectionTitle：正文里的「文档详情」等小节标题也用同一个
    objectName，但它们有字 —— 删掉的是那条从不 setText 的头部空行。
    """
    panel = window._pages["library"].right_panel
    empty = [w for w in panel.findChildren(QtWidgets.QLabel)
             if w.objectName() == "sectionTitle" and not w.text().strip()]
    assert empty == [], "浮层里不该再有没字的标题行 —— 留一条空行就是留一条空带"
    assert panel.close_button.text() == "✕"
    # docked=False 的面板是**永久浮层形状**：✕ 角标常挂（`_apply_overlay_style(True)`），
    # `isVisibleTo(panel)` 只回答"面板可见时它可不可见"——答案必须是"是"，整条链在
    # `open_overlay()` 时才真正上屏（Qt 的 isVisible 要逐级 parent 都在显示才为真）。
    assert panel.close_button.isVisibleTo(panel), "浮层形状下 ✕ 该随面板可见（isVisibleTo 只看形状）"


# —— ①② 跳转兜底 + 详情占位 ————————————————————————————————————————————

def test_没搜过时跳转按钮退到打开选中的文档(window, qapp) -> None:
    """①：命中列表没有可用选中时，「跳到该页」退成「打开文档」按中栏选中的那份开。

    修前这条链是死的：没搜过 → `hit_list` 空 → `_on_jump_clicked` 直接 return，
    用户点中栏一行再按跳转，按钮灰着（禁用）或点了没反应。
    坏法注入实测（2026-10-30）：把 `_on_doc_selected` 里那句 `self._set_jump_fallback()`
    删掉 ⇒ 本条红在「按钮没退到可点」。
    """
    page = _page_at(window, qapp, "library")
    ids = _seed_docs(page.ctx)
    page.reload()
    assert not page.jump_btn.isEnabled(), "没选没搜，跳转按钮必须灰着"

    page.doc_table.selectRow(0)
    _settle(qapp)
    assert page.jump_btn.isEnabled(), "选中一份文档后跳转按钮该亮（兜底：打开这份）"
    assert page.jump_btn.text() == "打开文档 → S2", \
        f"没命中列表就没有'那一页'可跳，措辞不该是跳到该页：{page.jump_btn.text()}"

    # ② 详情占位：右栏被唤出而详情空着的那块白底要说清"这里会出什么、去哪选中"
    assert page.detail_view.placeholderText(), "详情区该有占位文字（空白与'坏了'长得一样）"

    payload: list[tuple[int, int | None]] = []
    # 先摘掉外壳的阅读器槽再发信号：样本是假路径，真开阅读器会弹模态
    # 「打开 PDF 失败」把测试进程卡死（实测）。这里只验"发了什么载荷"。
    page.open_in_reader.disconnect(window._open_in_reader)
    page.open_in_reader.connect(lambda p: payload.append(tuple(p)))
    try:
        page._on_jump_clicked()
    finally:
        page.open_in_reader.disconnect()  # 摘掉记录用 lambda
        page.open_in_reader.connect(window._open_in_reader)
    assert payload == [(ids[0], None)], f"兜底跳转该按选中那份整份打开：{payload}"

    # 清空选中 → 兜底无处可去，按钮回到灰
    page.doc_table.clearSelection()
    _settle(qapp)
    assert not page.jump_btn.isEnabled()


# —— ③ 上次读到措辞 ——————————————————————————————————————————————————

def test_上次读到措辞按进度分档(window, qapp, tmp_path: Path) -> None:
    """③：读到第 1 页是"刚翻开"，不是"读到了第 1 页" —— 两个分支要说出不同的动作。"""
    page = _page_at(window, qapp, "library")
    real = tmp_path / "样本.pdf"
    real.write_bytes(b"%PDF-1.4\n")
    doc = page.ctx.documents.upsert(Document(
        path=str(real), path_key=identity_key(str(real)), name="样本.pdf",
        size_bytes=real.stat().st_size, mtime_ns=1_760_000_000_000_000_000,
        text_status="done"))
    page.ctx.documents.update_reading_progressress(int(doc.id), 1)
    page.update_last_read_hint()
    assert "上次打开过" in page.last_read_hint.text(), \
        f"第 1 页不算'读到哪'：{page.last_read_hint.text()}"

    page.ctx.documents.update_reading_progressress(int(doc.id), 3)
    page.update_last_read_hint()
    text = page.last_read_hint.text()
    assert "上次读到" in text and "第 3 页" in text, text


# —— ⑤ 状态栏短口径 + tooltip ————————————————————————————————————————————

def test_状态栏栏里是短口径_技术全称在悬停里(window, qapp) -> None:
    """⑤ 界面半边：栏里不许出现 trigram / bm25 行话；技术全称挪进 tooltip。

    坏法注入实测（2026-10-30）：把 `_do_keyword_search` 里那句 `setToolTip(result.status_detail())`
    删掉 ⇒ 本条红在 tooltip 为空。
    """
    page = _page_at(window, qapp, "library")
    _seed_docs(page.ctx)
    page.reload()
    page.search_input.setText("轮四十二")
    page._do_search()
    _settle(qapp)
    text = page.status_label.text()
    assert "trigram" not in text and "bm25" not in text and "LIKE" not in text, \
        f"状态栏里不该有实现名行话：{text}"
    tip = page.status_label.toolTip()
    assert tip, "短口径把技术全称挪进了悬停，tooltip 不该是空的"
    assert tip != text, "悬停里该是完整口径，不能与栏里那句一字不差"

    # 浏览态清掉：tooltip 是关键词检索的口径，浏览态留着就是过期读数
    page.search_input.clear()
    page._do_search()
    _settle(qapp)
    assert page.status_label.toolTip() == "", "回到浏览态，关键词那条 tooltip 该清掉"


# —— ⑥ 忙碌光标 ————————————————————————————————————————————————————

def test_检索期间挂等待光标_结束归还(window, qapp, monkeypatch) -> None:
    """⑥：真库一次检索 2–4s，没反馈会被当成"点了没反应"。坏法是删 try 外那两行
    setOverride/restore —— 实测注入后 `seen` 里 overrideCursor() 为 None，当场红。"""
    page = _page_at(window, qapp, "library")
    seen: list[object] = []
    orig = page._do_keyword_search

    def spy(query: str) -> None:
        seen.append(QtWidgets.QApplication.overrideCursor())
        orig(query)

    monkeypatch.setattr(page, "_do_keyword_search", spy)
    page.search_input.setText("轮四十二")
    page._do_search()
    assert seen and seen[0] is not None, "检索期间该挂着等待光标"
    assert QtWidgets.QApplication.overrideCursor() is None, "结束后必须归还光标，不许永久锁 Busy"


# —— ⑦ 空分类指路 ————————————————————————————————————————————————————

def test_空分类在状态栏指真实的写入口(window, qapp) -> None:
    """⑦：筛选是"分类 = X"且一页都没取到 → 只报「共 0 份文档」会让人以为程序坏了；
    出路指真实的写入口（「归入分类…」，catalog_links 那排按钮里真实存在的一颗）。

    坏法注入实测（2026-10-30）：把 `_load_more` 那个 if 恒置 False ⇒ 本条红在「指路缺席」。
    """
    page = _page_at(window, qapp, "library")
    cat = page.ctx.catalog.add_category("空分类测试")
    page.filter_bar.set_field("category_ids", [int(cat.id)])
    _settle(qapp)
    text = page.status_label.text()
    assert "还没有文档归入" in text and "归入分类" in text, \
        f"空分类该指路而不是只报 0：{text}"


# —— ⑨⑩⑪ 其它屏空态指路 ————————————————————————————————————————————————

def test_S9_空态提示在场且区分向量未建(window, qapp) -> None:
    """⑨：答案区空着时给一句"怎么用"；向量没建时多说半句"等索引完成会自动建"
    —— 指路只能指真实存在的入口（向量没有手动建的按钮，是队列自动跑的）。"""
    page = _page_at(window, qapp, "ask")
    assert page.empty_hint.isVisible() and page.empty_hint.text(), "空态提示该在场"
    assert "提问" in page.empty_hint.text()
    # 新库没有向量：那句"未建"的半句必须在
    assert "未建" in page.empty_hint.text(), \
        f"没向量时不该只给通用话术：{page.empty_hint.text()}"


def test_S8_两栏空态提示跟列表有无自动收放(window, qapp) -> None:
    """⑩：标签/智能集合两个空列表各配一句"去哪造出第一个"；有内容就整句收起。"""
    page = _page_at(window, qapp, "categories")
    assert page.tag_hint.isVisible(), "空标签列表该有指路"
    assert page.coll_hint.isVisible(), "空集合列表该有指路"

    page.ctx.catalog.add_tag("守卫标签")
    page.reload()
    _settle(qapp)
    assert not page.tag_hint.isVisible(), "有标签之后提示该收起（留着就是堆积）"
    assert page.coll_hint.isVisible(), "集合还是空的，那句该留着"


def test_S3_目标根提示跟输入有无自动收放(window, qapp) -> None:
    """⑪：没填目标根目录时说清"执行归档会把文件搬到哪"；填了就收起。"""
    page = _page_at(window, qapp, "archive")
    assert page.root_hint.isVisible(), "目标根为空时提示该在场"
    page.target_root_input.setText("H:/守卫临时根")
    _settle(qapp)
    assert not page.root_hint.isVisible(), "填了目标根就该收起"
