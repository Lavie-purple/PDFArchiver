"""表格的列宽与取数口径 —— 九张表共用。

列宽见 `set_table_columns`；取数见 `loaded_line`（**ISSUES I76**：靠 `limit=` 封顶的表，
屏上必须同时报「总数」与「已取回数」，两个数都取自后端字段）。

原先八张表都只写了一句 `setStretchLastSection(True)`：Qt 于是把除最后一列以外的所有列
留在默认 100px，把全部剩余宽度给最后一列。实测结果是文档库的「文件名」和「路径」各挤在
100px 里，而「分类」拿到 225px；归档页「文件名」100px、「分类」888px；操作日志批次表
把 688px 给了「失败」这一列**计数**。

这里改成显式指定：内容最长、也是用户真正要读的那几列各拿定宽。
剩下那点宽度给谁 —— **按当时的视口宽运行时算**（**ISSUES I121 ①甲**，轮四十七）：
只有当「其余定宽列 + 吸收列自己的下限」真的装得进视口时，才给那一列 Stretch。
判据原先写死在调用点（那句「远小于视口」从来没人按视口算过），于是三张表在任何窗口宽下
都全定宽：宽屏右侧空一大片（@2560 实测死宽 +1514／+1453／+1377px），而文件名、路径永远挤在
220／200px 里 —— 用户点的「右侧空了一块」和「文件名被截断」是同一件事。

反过来，定宽列已经把视口吃掉时**不许**给 Stretch：那一列会被压成一条缝（`minimumSectionSize`
是 16px，实测文档库「分类」在设计宽度下 38px、归档页把吸收列错放在「文件名」上时压到窗口最低是
25px），而且**永远是这一条缝**：横向滚动条是好的（Qt 的滚动范围按"档"不按像素，
`maximum()==2` 也能滚完整段超出量），滚过去看到的仍是个窄条。所以这一档选
「全定宽 + 横向滚动」，让每一列都保住自己的宽度、靠滚动取齐 —— 那正是 **D-040**
写明的 1024 地板档既定降级（③甲：维持并钉成断言）。

**不用 `QHeaderView.ResizeToContents`** —— 它把列宽交给"当前这批数据里最长的那条"，
换个筛选条件同一列的宽度就跳，且窗口每变一次尺寸都按行重量一遍（O(行×列)）。
2026-10-17 在判重表的 500 组档复测过两种口径的耗时：`ResizeToContents` 填表 61.5/73.6ms、
连续改宽 10 次 102.3/114.9ms，定宽 65.5ms/120.5ms —— 差值全落在 ±20% 抖区内，
**所以 500 行档上性能不是理由**（这里原先写的「定宽 19ms / 29ms」复现不出来，已更正）。
不用它的真理由是列宽不可控 + ×10 档 8 万行时那次重排没人量过，而 AGENTS.md 要求
写死的阈值按最大量级反算 —— 量不到的那一档不许当作已经安全。

**ISSUES I61 选甲（2026-10-17）**：判重页并进本口径，全站 8 张表统一。判重页的列宽
按 500 组档上限反算（浪费量 103 / SHA 93 / 份数 63 / 状态 103），路径列作 stretch_col。
"""
from __future__ import annotations

from PySide6 import QtCore, QtWidgets

# 单元格文字两侧的内边距，实测值：`sizeHintForColumn(c) − 该列最长文本的 advance` 在
# 五张表的五个列上都等于 23（127−104 / 231−208 / 309−286 / 36−13 / 283−260）。
#
# 这条常量的存在理由是**它之前没人算**：I48 那轮"按 13px 字体实测反算"反的是**文本宽**
# （修改时间 110px、大小 41px），然后给了 118/62 = 文本 + 8，于是每一列都恰好短掉那 23px，
# 用户读到的是 `2026-1…` 和 `1…`。**定宽 = 内容宽 + CELL_PADDING_WIDTH**，只按内容宽定
# 列必截断。守卫见 `tests/integration/test_ui_layout.py`。
CELL_PADDING_WIDTH = 23

# 允许截断的列：内容天生没有上限（绝对路径 / 用户自定义分类名 / 第三方报错原文），
# 所以它们不承诺"装得下"，改承诺"截断后悬停能读全文" —— 后半句由守卫钉住。
# 反过来说，凡是不在这个集合里的列（时间、大小、状态、计数）都必须按词表上限定宽。
ELIDABLE_COLUMNS = frozenset({
    "文件名", "路径", "源路径", "目标路径", "路径（悬停看全长）", "分类", "错误", "标记",
})

# 吸收列自己的下限：视口不够时就退到这一档，再不够整张表改全定宽 + 横向滚动。
# 140px = 9 个全角字（9×13=117）+ 内边距 23，比"还能读出一个词形"的最低线，
# 也远高于被 Stretch 压瘪时的实测读数 38px／25px。
# **这个值不受守卫**（坏法注入实测：改成 16px 后 `test_ui_layout.py` 32 条全绿）。原因量过：
# 它只在调用点**没**给吸收列声明宽度时当兜底，而全站走这一条的四张表（S3 待归档文档表／S7 体检表／
# S6 两张）在地板档都是 Stretch（实测 231／497／438／526px），从不退到 Interactive ⇒ 这 140 没上过屏。
# 不给它编断言（AGENTS.md：不会变红的断言直接删），留字当 `.get()` 的缺省，改之前先复跑那张表。
STRETCH_MIN_WIDTH = 140


class _ViewportStretchPolicy(QtCore.QObject):
    """吸收列到底吸不吸，按**当时的视口宽**算。

    判据是 `其余定宽列合计 + 吸收列下限 ≤ 视口`。装得下就给 Stretch（那一列吃掉剩余宽度，
    表内右侧不留空）；装不下就把它降回 Interactive + `STRETCH_MIN_WIDTH`，全表横向滚动 ——
    也就是 **D-040** 的 1024 地板档既定降级。

    装不下还硬给 Stretch，被压成缝的正是这一列（`minimumSectionSize` 只有 16px），
    而滚动条滚过去看见的还是那条缝 —— 见模块开头那段。
    """

    def __init__(self, table: QtWidgets.QTableWidget, widths: dict[int, int],
                 stretch_col: int) -> None:
        super().__init__(table)
        self._table = table
        self._viewport = table.viewport()
        self._stretch_col = stretch_col
        self._others = sum(w for col, w in widths.items() if col != stretch_col)
        self._floor = widths.get(stretch_col, STRETCH_MIN_WIDTH)
        self._applying = False

    def attach(self) -> None:
        """盯住视口的宽变化。对象 parent 在表上，随表一起销毁。"""
        self._viewport.installEventFilter(self)

    def eventFilter(self, watched: QtCore.QObject, event: QtCore.QEvent) -> bool:
        # 只看 Resize，不另接 Show：隐藏的页切过来那一刻，Qt 会把攒下的那次改尺寸**补发**成
        # Resize —— `test_ui_layout.py` 地板档那一半走的就是"先压到 1024 再头一回进这一屏"，
        # 把 Show 分支删掉它照样绿，所以接两条等于把同一件事判两遍。
        # 两条判据都比的是 Python 包装对象、且不回摸 `self._table`：拆窗口时表的 C++ 侧比
        # 视口的收尾事件先没，摸了就抛 "Internal C++ object already deleted" 刷屏。
        if event.type() != QtCore.QEvent.Type.Resize or watched is not self._viewport:
            return False
        self._apply()
        return False

    def _apply(self) -> None:
        if self._applying:
            return
        viewport = self._viewport.width()
        if viewport <= 0:
            return                       # 还没进过布局，此刻的读数不是视口
        self._applying = True
        try:
            fits = self._others + self._floor <= viewport
            self._table.horizontalHeader().setSectionResizeMode(
                self._stretch_col,
                QtWidgets.QHeaderView.ResizeMode.Stretch if fits
                else QtWidgets.QHeaderView.ResizeMode.Interactive)
            if not fits:
                # Stretch 期间这一列的"用户宽度"被 Qt 改成了拉伸值，降回来时必须显式钉回下限。
                self._table.setColumnWidth(self._stretch_col, self._floor)
        finally:
            self._applying = False


def set_table_columns(table: QtWidgets.QTableWidget, widths: dict[int, int],
                      stretch_col: int | None = None) -> None:
    """`widths` 是「列号 → 定宽 px」，**含** `CELL_PADDING_WIDTH`。

    `stretch_col` 是**这一列愿意吸收剩余宽度**的声明：能不能真的吸，由
    `_ViewportStretchPolicy` 按当时的视口宽运行时算（**ISSUES I121 ①甲**）。传 `None`
    就全部定宽，视口装不下时表格横向滚动。

    全站 9 张表都经这里（ISSUES I61 选甲：判重页并进；#198 加 S7 库体检表）：archive 2 / backup 2 /
    library 1 / operations 2 / dedup 1 / monitor 1。行号列统一 `hide()`，守卫
    `test_ui_tier.py` 逐屏扫全部 9 张。
    """
    header = table.horizontalHeader()
    header.setStretchLastSection(False)
    # 单行行高 + `ElideRight` 的组合下，Qt 对「反斜杠 + CJK 混排的整段不可断词」会把
    # 260px 的单元格画成 `C…`（**ISSUES I107**：S3 计划表三行目标路径全中，实测
    # `C:\Users\lavie\AppData\Local\Temp…` 只剩一个字符；同一单元格换成正斜杠串就正常，
    # 关掉自动换行也恢复正常）。全站 9 张表都是单行行高，没有一张用得上换行 ——
    # 一律关掉，别等下一张带反斜杠路径的表再踩一次。
    table.setWordWrap(False)
    # 行号列没人要过，但 Qt 会自动长出来，而且**宽度随行号位数变**（2026-10-17 现测：
    # 空表 0 / 2 行 38 / 40 行 51）—— 于是同一张表"可用视口"不是一个数，I48 那套列宽
    # 反算的分母里根本没有它。判重页自 I61 起也走这里（它原先自己配表头），所以一处
    # `hide()` 覆盖全站 8 张；守卫 `tests/integration/test_ui_tier.py` 逐屏扫全部 8 张，
    # 第 9 张漏掉会红（ISSUES I54）。
    table.verticalHeader().hide()
    for col, width in widths.items():
        header.setSectionResizeMode(col, QtWidgets.QHeaderView.ResizeMode.Interactive)
        table.setColumnWidth(col, width)
    if stretch_col is not None:
        header.setSectionResizeMode(stretch_col, QtWidgets.QHeaderView.ResizeMode.Stretch)
        _ViewportStretchPolicy(table, widths, stretch_col).attach()


def loaded_line(total: int, loaded: int, unit: str) -> str:
    """`limit=` 封顶的表格共用那一行两个数，口径与 **ISSUES I51** 同源（**ISSUES I76**）。

    为什么必须有这一处：S3 / S5 / S4 三张表各写了一句陈述句标题（「可归档的文档」「重复文件组」
    「操作记录」），取数却都带着仓储层的 `limit` —— 10,977 份的真库里第 501 份之后的文档在界面
    上**不存在**，而屏上没有任何一处说这件事。这和 **ISSUES I51** 修前那句「共 1000 份文档」
    （8,000 份的库）是同一个错觉，只是换了屏。

    两个数都只许来自后端字段：`total` 是仓储层数出来的（`count()` / `dedup_summary()`），
    `loaded` 是这一批真的取回来的行数（也就是表格刚写进去的行数）。界面自己算的任何数都不算。
    """
    if loaded >= total:
        return f"共 {total} {unit}｜表格里 {loaded} {unit}"
    return (f"共 {total} {unit}｜表格里已有 {loaded} {unit}"
            f"，还有 {total - loaded} {unit}没在这里")
