"""S1 中栏那张表的"行"与右栏那份"详情"怎么从一份文档摊出来（**ISSUES I78** 甲拆出，2026-10-19）。

为什么单独一个文件：`ui/pages/library_page.py` 已经贴着 D-054 那条 800 行的线（**ISSUES I86** 乙
的临近读数点过它的名），而"一份文档画成哪几格、每格什么措辞"与"三栏怎么摆、什么时候补一批"
是两件事 —— 按主题拆正好是这两件事的分界，不是把一条决定从中间劈开。

两条口径留在这里而不是散回页面：
- **「分类」列截到三个名字**（列宽按 88px 反算，见 `library_page` 的 `set_table_columns`），
  而**详情那一行列全**。同一份文档在两处的个数不同，是"可截断列"与"整段文本"的区分，
  不是两个答案 —— 所以两处都由这一个文件出。
- **修改时间走 `status_service.format_ts`**（全站唯一时间出口）；没有 mtime 时留空而不写"从未"：
  对一份文件的修改时刻，"从未"是错的读法（那是"不知道"）。
"""
from __future__ import annotations

from PySide6 import QtCore, QtWidgets

from pdfarchiver.services.status_service import format_ts
from pdfarchiver.ui.format import format_bytes

#: 「分类」一列最多显示几个名字。用户自定义分类名的长度没有上限（DDL 只对 `(parent_id, name)`
#: 建唯一索引），定宽列装不下无限个，所以按可截断列处理：截断了的必须能悬停读回全文。
CATEGORY_CELL_NAMES = 3

HEADERS = ("文件名", "路径", "大小", "修改时间", "分类")
#: 第一列带 `UserRole`（doc_id），最后一列是「分类」—— 列号只在这里写一次。
DOC_ID_COLUMN = 0
CATEGORY_COLUMN = 4


def mtime_text(doc) -> str:
    return format_ts(doc.mtime_ns // 1_000_000_000) if doc.mtime_ns else ""


def category_cell_text(cats: list) -> str:
    """「分类」列与它的 tooltip 共用同一个串：截断的是显示，不是数据。"""
    return ", ".join(c.name for c in cats[:CATEGORY_CELL_NAMES])


def write_document_rows(table: QtWidgets.QTableWidget, docs: list, start: int, catalog) -> None:
    """把一批文档写进表格的连续几行（从 `start` 那一行起）。

    `catalog` 由宿主页面把 `AppContext.catalog` 递进来：分类那一列**一条查询取回整批**
    （`categories_by_doc_ids`），不逐行取 —— 修前每行调一次 `categories_of`，1,000 行就是
    1,000 条 SQL（**ISSUES I51** 实测 `per_row_categories_queries=1000`）。
    """
    cats_by_doc = catalog.categories_by_doc_ids([doc.id for doc in docs])
    for row, doc in enumerate(docs, start=start):
        # 文件名：doc_id 挂在第一列的 UserRole 上，选中态、跳转、写入后的重画都从这里取
        name_item = QtWidgets.QTableWidgetItem(doc.name)
        name_item.setData(QtCore.Qt.ItemDataRole.UserRole, doc.id)
        name_item.setToolTip(doc.name)
        table.setItem(row, DOC_ID_COLUMN, name_item)

        # 路径：定宽装不下整条绝对路径，靠悬停回读（与 S5 判重表同一口径）
        path_item = QtWidgets.QTableWidgetItem(doc.path)
        path_item.setToolTip(doc.path)
        table.setItem(row, 1, path_item)

        table.setItem(row, 2, QtWidgets.QTableWidgetItem(format_bytes(doc.size_bytes)))
        table.setItem(row, 3, QtWidgets.QTableWidgetItem(mtime_text(doc)))

        cat_text = category_cell_text(cats_by_doc.get(doc.id, []))
        cat_item = QtWidgets.QTableWidgetItem(cat_text)
        cat_item.setToolTip(cat_text)
        table.setItem(row, CATEGORY_COLUMN, cat_item)


def category_cell(cats: list) -> QtWidgets.QTableWidgetItem:
    """单独取这一格的控件：一次关联写入之后只重画被点名的那几行（与上面的措辞同一处）。"""
    text = category_cell_text(cats)
    item = QtWidgets.QTableWidgetItem(text)
    item.setToolTip(text)
    return item


def detail_lines(doc, cats: list, tags: list) -> list[str]:
    """右栏下半部那份详情：一份文档此刻能查到的全部读数，四种状态各一行。"""
    lines = [
        f"文件名：{doc.name}",
        f"扩展名：{doc.ext}",
        f"路径：{doc.path or '(未知)'}",
        f"大小：{format_bytes(doc.size_bytes)}",
        f"修改时间：{mtime_text(doc)}",
        f"SHA256: {doc.sha256 or '(未计算)'}",
        "",
        f"页数：{doc.page_count or '(未知)'}",
        f"正文覆盖率：{doc.text_bearing_rate:.1%}" if doc.text_bearing_rate else "正文覆盖率：(未知)",
        "",
        f"分类：{', '.join(c.name for c in cats) or '(无)'}",
        f"标签：{', '.join(t.name for t in tags) or '(无)'}",
        "",
        f"解析状态：{doc.parse_status}",
        f"正文状态：{doc.text_status}",
        f"OCR 状态：{doc.ocr_status}",
        f"索引状态：{doc.fts_status}",
    ]
    if doc.last_error:
        lines.append(f"最后错误：{doc.last_error}")
    return lines
