"""S1 中栏那一列的**浏览分页**（**ISSUES I51**）：一批一批取，滚到底补下一批。

2026-11-03（轮五十八 ③）从 `ui/pages/library_page.py` 整段搬来，理由与
`ui/library_filter.py`、`ui/library_hits.py` 同一条：那一屏的接线只增不减，而 700 行自线
（**ISSUES I96** 甲）就钉在它身上 —— 本轮要给检索加"搬去后台线程"这一格，先按主题腾地方，
**不许抬那条自线**。

**为什么仍是 mixin 而不是一个独立控件**：这一格的东西全是"页面状态 + 表格控件"的换算，
`tests/integration/test_library_paging_ui.py` 与 `test_round42_ux.py` 认的是
`page._start_browse()` / `page._on_scrolled(0)` / `page._browse_exhausted` 这些页面属性，
换访问路径等于让断言跟着实现改。混入让控件与状态仍然挂在页面对象上，归属只挪了文件。

混入方（`ui/pages/library_page.py` 的 `LibraryPage`）须提供：
`self.ctx`（AppContext）、`self.doc_table`（那张表）、`self.status_label`（tooltip 的落点）、
`self._set_status`（状态栏唯一出口）、`self._write_rows`（每格写什么在 `library_rows.py`）、
`self._query`（当前筛选那份 dict）、`self._current_docs`（已取到的行，与表一一对应）、
`self._browse_active` / `self._browse_exhausted` / `self._browse_total`（这三个数的现场，
构造时由页面初始化 —— 它们与 `_current_docs` 同生同灭，分两处存就会有一天对不上）。

搜索编排与 `_apply_query` 本体**留在页面里**：一次查询要同时写中栏表、状态栏、右栏与筛选区
四处状态，拆开就是两边各拿一半。
"""
from __future__ import annotations

from pdfarchiver.services.bootstrap import AppContext  # noqa: F401 - 文档化混入契约


class LibraryBrowseMixin:
    """浏览态的取数与补批；控件与状态仍归页面（`page.xxx` 访问路径不变）。"""

    # ---- 浏览：一批一批取（**ISSUES I51**）------------------------------------

    def _start_browse(self) -> None:
        """把中栏切成"浏览库里这一列"：只先取第一批，剩下的等滚动。

        修前这里是 `documents.list(limit=1000)` 一次灌满再逐行取分类：8,000 份的库实测
        `table_rows=1000 / 看不见 7,000 份 / 逐行 SQL 1,000 条`，而状态栏那句
        「共 1000 份文档」把"没显示"说成了"不存在"（×10 档 8 万份时看不见 79,000 份）。
        """
        self._browse_active = True
        self._browse_exhausted = False
        self._browse_total = 0
        # 轮四十二 ⑤：浏览态的口径是 `_browse_line()`，关键词那条 tooltip 是过期口径，清掉。
        self.status_label.setToolTip("")
        self._current_docs = []
        self.doc_table.setRowCount(0)
        self._load_more()
        self._fill_viewport()

    def _load_more(self) -> None:
        """取下一批追加到表尾。取完了就是空操作 —— 不许到库尾再绕回头。"""
        if not self._browse_active or self._browse_exhausted:
            return
        # `or None`：第一批还没数过（`_browse_total` 是 0），把 0 当"已知的数"递下去就等于
        # 叫后端跳过 `count_matching`、然后状态栏说「共 0 份文档」。第二批起才带上第一批
        # 那个读数 —— 每批重数一遍全表是 O(行数²)，见 `SearchService.search` 的 `known_total`。
        result = self.ctx.search.browse_documents(
            query=self._query, offset=len(self._current_docs),
            total=self._browse_total or None)
        self._browse_total = result.matching_documents
        docs = [hit.doc for hit in result.hits]
        if not docs:
            self._browse_exhausted = True
        elif len(self._current_docs) + len(docs) >= self._browse_total:
            self._browse_exhausted = True
        self._append_rows(docs)
        # 轮四十二 ⑦：筛选是"分类 = X"、一页都没取到、且表格本来就空 ⇒ 十有八九是这个分类
        # 底下还没有任何文档**归入**（真库实测 `document_categories` 0 行、14 个裸分类）。
        # 只报「共 0 份文档」会让人以为程序坏了；出路指真实的写入口（catalog_links 那排按钮）。
        if not docs and not self._current_docs and self._query.get("category_ids"):
            self._set_status(f"{result.status_line()}｜这个分类还没有文档归入："
                             "在表格里选中文件后，用那排写入按钮里的「归入分类…」建立关联。")
        else:
            self._set_status(result.status_line())

    def _append_rows(self, docs: list) -> None:
        if not docs:
            return
        start = len(self._current_docs)
        self.doc_table.setRowCount(start + len(docs))
        self._write_rows(start, docs)
        self._current_docs += docs

    def _fill_viewport(self) -> None:
        """第一批顶不出滚动条时（视口比一批还高）永远不会有人滚 ⇒ 也就永远不会补，
        所以这里主动补到"能滚"为止。行高统一（**D-040**）⇒ 一次乘法就够，不测每行。"""
        while self._browse_active and not self._browse_exhausted \
                and self._loaded_height() <= self.doc_table.viewport().height():
            self._load_more()

    def _loaded_height(self) -> int:
        if not self._current_docs:
            return 0
        return self.doc_table.rowHeight(0) * len(self._current_docs)

    def _on_scrolled(self, value: int) -> None:
        bar = self.doc_table.verticalScrollBar()
        if bar.maximum() - value <= self.doc_table.viewport().height():
            self._load_more()
