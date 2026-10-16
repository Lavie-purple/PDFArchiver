"""文档表格的列宽口径 —— 五张表共用。

原先五张表都只写了一句 `setStretchLastSection(True)`：Qt 于是把除最后一列以外的所有列
留在默认 100px，把全部剩余宽度给最后一列。实测结果是文档库的「文件名」和「路径」各挤在
100px 里，而「分类」拿到 225px；归档页「文件名」100px、「分类」888px；操作日志批次表
把 688px 给了「失败」这一列**计数**。

这里改成显式指定：内容最长、也是用户真正要读的那几列各拿定宽。
剩下那点宽度给谁 —— **只给"其余定宽列合计远小于视口"的那种表**。
定宽列已经把视口吃掉时，Stretch 那一列会被压成一条缝（`minimumSectionSize` 是 16px，
实测文档库「分类」在设计宽度下 38px、归档页把吸收列错放在「文件名」上时压到窗口最低是
25px），而且**永远是这一条缝**：横向滚动条是好的（Qt 的滚动范围按"档"不按像素，
`maximum()==2` 也能滚完整段超出量），滚过去看到的仍是个窄条。所以这种情况下这里选
「全定宽 + 横向滚动」，让每一列都保住自己的宽度、靠滚动取齐。

**不用 `QHeaderView.ResizeToContents`** —— 它把列宽交给"当前这批数据里最长的那条"，
换个筛选条件同一列的宽度就跳，且窗口每变一次尺寸都按行重量一遍（O(行×列)）。
2026-10-17 在判重表的 500 组档复测过两种口径的耗时：`ResizeToContents` 填表 61.5/73.6ms、
连续改宽 10 次 102.3/114.9ms，定宽 65.5ms/120.5ms —— 差值全落在 ±20% 抖区内，
**所以 500 行档上性能不是理由**（这里原先写的「定宽 19ms / 29ms」复现不出来，已更正）。
不用它的真理由是列宽不可控 + ×10 档 8 万行时那次重排没人量过，而 AGENTS.md 要求
写死的阈值按最大量级反算 —— 量不到的那一档不许当作已经安全。
"""
from __future__ import annotations

from PySide6 import QtWidgets

# 单元格文字两侧的内边距，实测值：`sizeHintForColumn(c) − 该列最长文本的 advance` 在
# 五张表的五个列上都等于 23（127−104 / 231−208 / 309−286 / 36−13 / 283−260）。
#
# 这条常量的存在理由是**它之前没人算**：I48 那轮"按 13px 字体实测反算"反的是**文本宽**
# （修改时间 110px、大小 41px），然后给了 118/62 = 文本 + 8，于是每一列都恰好短掉那 23px，
# 用户读到的是 `2026-1…` 和 `1…`。**定宽 = 内容宽 + CELL_PADDING_WIDTH**，只按内容宽定
# 列必截断。守卫见 `tests/integration/test_app_shell.py`。
CELL_PADDING_WIDTH = 23

# 允许截断的列：内容天生没有上限（绝对路径 / 用户自定义分类名 / 第三方报错原文），
# 所以它们不承诺"装得下"，改承诺"截断后悬停能读全文" —— 后半句由守卫钉住。
# 反过来说，凡是不在这个集合里的列（时间、大小、状态、计数）都必须按词表上限定宽。
ELIDABLE_COLUMNS = frozenset({
    "文件名", "路径", "源路径", "目标路径", "路径（悬停看全长）", "分类", "错误",
})


def set_table_columns(table: QtWidgets.QTableWidget, widths: dict[int, int],
                      stretch_col: int | None = None) -> None:
    """`widths` 是「列号 → 定宽 px」，**含** `CELL_PADDING_WIDTH`。

    `stretch_col` 只在**其余列的定宽合计远小于视口**时才给：那一列吸收剩余宽度。
    传 `None` 就全部定宽，视口装不下时表格横向滚动。
    """
    header = table.horizontalHeader()
    header.setStretchLastSection(False)
    for col, width in widths.items():
        header.setSectionResizeMode(col, QtWidgets.QHeaderView.ResizeMode.Interactive)
        table.setColumnWidth(col, width)
    if stretch_col is not None:
        header.setSectionResizeMode(stretch_col, QtWidgets.QHeaderView.ResizeMode.Stretch)

