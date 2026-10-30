"""五条动作行的「行末那格」—— 只有整句装得下，才把这一屏已有的一句读数搬进行末（**ISSUES I121** ④）。

线框 `docs/wireframes/2026-10-31-round47-fit-width-action-rows.html` §2 乙-1 / §4 Q3 乙-1 ·
Q4 甲 · Q5 甲（2026-10-31「都按你推荐来」）。五条行：S3 归档预览底部 / S4 操作日志 /
S5 ① 段工具行 / S6 备份按钮行 / S7 体检行。

这一族断言盯的是三件会被静默弄坏的事，每件都有一处**实测逮到过**：

1. **装不装得下只许有一份判据**（`ui/viewport_fit.py` 的 `fits_absorbing`）。表格吸收列与
   行末那格必须同一条式子，否则同一屏会出现"列说装得下、句子说装不下"两套说法。
2. **跨宿主搬动会抹掉控件自己的显式显示位**。实测把 S5 的进度条搬进 ① 段行末之后
   `progress_bar.isHidden()` 变 True、`isVisible()` 恒假，三条 `test_patrol_tick` 判重进度
   当场红 —— Qt 在 `insertWidget` 触发的 `setParent` 里清掉了显示位，不在 `_move` 里钉回去
   就是"搬进去的那句从此不显示"。
3. **`wordWrap` 标签的 `sizeHint` 给的是折行后的窄宽**，搬进去之后布局按那个窄宽给它，
   句子会被压成两三行、行高只有 36 ⇒ 上下都看不见。实测 S6 `lbl_current` 整句
   `horizontalAdvance` = 585px 而 `sizeHint` 只报 273×43 —— 所以行末期间要把
   `minimumWidth` 钉成单行整句宽（`_Cell.width_of`），回原位再还原。

另有三族是**结构性**的，量不到像素，只在代码走形时红：判据全站只许有一份（按 AST 扫**调用**，
第一版扫文字被 docstring 里那句 `fits_absorbing` 骗过）、改写那句的地方自己必须 `sync()`
（沿整条调用链找，只看"有没有调用者"删掉页里那一次照样绿）、行末那句不许进宿主的最低宽
（对照行自己那份 `minimumSizeHint()`，拿常量当上限会漏掉整档）。

窗口两档取自外壳本身：`MIN_WINDOW_WIDTH`（D-039 地板 1024）与走查那一档的 2560。
2560 不是随手写的：线框 §2 的实测读数就是这一档空弹簧吃掉 2,038–2,174px。
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest
from PySide6 import QtWidgets

from pdfarchiver.ui.action_row import ActionRow
from pdfarchiver.ui.main_window import MIN_WINDOW_WIDTH
from tests.conftest import resize_stepped as _resize_stepped
from tests.conftest import settle as _settle

SRC = Path(__file__).resolve().parents[2] / "src" / "pdfarchiver"

#: 地板档（D-039 的最小窗宽）与走查用的宽档。
FLOOR = MIN_WINDOW_WIDTH
WIDE = 2560

#: 五条行的登记表：`屏名 / page_id / 句子的取路径 / 那句里必须原样出现的片段`。
#: 最后那一栏钉的是硬口径 1「内容一个字不改」——搬进去的必须是这一屏别处已有的那只
#: QLabel，文案由页面自己算，这一格不产第六个数（**ISSUES I60** 定过的口径）。
ROWS = [
    ("S3 归档预览", "archive", "loaded_note", "还没取数"),
    ("S4 操作日志", "operations", "loaded_note", "条操作批次"),
    ("S5 重复检测", "duplicates", "lbl_progress", "判重进行中"),
    ("S6 备份恢复", "backup", "lbl_current", "当前库"),
    ("S7 库体检", "monitor", "health_panel.last_check_label", "上次体检"),
]


def _show(window, qapp, ctx, page_id):
    """切到那一屏并让它真的可见，返回 `(行, 句子)`。

    两处必须显式翻面：S5 的进度块只在库里真有 `kind=dedup` 的行时才显示（没有句子就搬不动），
    S7 的体检面板在 `lower_stack` 里默认不在场 —— 隐藏着的 widget **从没排过版**，
    几何停在 Qt 默认 640×480，量出来全是假数（这一条本轮真踩过一次）。
    """
    window._select_by_page_id(page_id)
    _settle(qapp)
    page = window._pages[page_id]
    if page_id == "duplicates":
        job = ctx.jobs.enqueue("dedup", doc_id=None, priority=5)
        ctx.jobs.claim(("dedup",))
        ctx.jobs.set_progress(job.id, 120, 4000)
        page.reload_progress()
    if page_id == "monitor":
        page.show_health()
        _settle(qapp)
    row = getattr(page, "action_row", None) or page.health_panel.action_row
    attr = next(spec[2] for spec in ROWS if spec[1] == page_id)
    obj = page
    for part in attr.split("."):
        obj = getattr(obj, part)
    return row, obj


def _at(window, qapp, ctx, spec, width):
    """切到那一屏、压到指定窗宽，返回 `(行, 句子, 这一格)`。"""
    row, cap = _show(window, qapp, ctx, spec[1])
    _resize_stepped(window, qapp, width, 720)
    _settle(qapp)
    return row, cap, row._cells[0]


# —— 宽档：五条行都必须把那句收进行末，且贴右缘、单行、全文 -----------------------


@pytest.mark.parametrize("spec", ROWS, ids=[r[0] for r in ROWS])
def test_宽档那句搬进行末且贴右缘(window, qapp, ctx, spec) -> None:
    """这一条抓的坏法：行末那格根本没接上（句子还画在行的上方/下方），或搬进去之后
    被布局推到左边、右侧照旧空着 —— 那正是走查逮到的 2,038px 空弹簧的形状。"""
    row, cap, cell = _at(window, qapp, ctx, spec, WIDE)

    assert cell.in_row is True, (
        f"{spec[0]} 在 {WIDE} 档该把「{cap.text()[:16]}…」收进行末，实际还留在原位")
    assert cap.parentWidget() is row, "搬进去的必须是这一屏别处那只控件本身，不是它的副本"
    assert cap.geometry().right() == row.width() - 1, (
        f"那句没有贴右缘：右缘 {cap.geometry().right()}，行宽 {row.width()}")
    assert not cap.isHidden(), "跨宿主搬动抹掉了显示位 ⇒ 行末那句永远不出现"


@pytest.mark.parametrize("spec", ROWS, ids=[r[0] for r in ROWS])
def test_搬进去的那句单行显示且一个字不截(window, qapp, ctx, spec) -> None:
    """硬口径 2「只在整句装得下时才搬」的可证伪形式：**给出的宽 ≥ 整句单行宽**。

    这条同时挡住两种坏法：判据放松成"装不下也搬"（句子被折成两三行、行高 36 装不下 ⇒ 看不见），
    以及行末再截一刀（`ElideRight`）把已有的回读弄丢 —— S6 那句本来就按 `_elided` 中段省略过，
    完整路径挂在 tooltip 上，行末截第二刀就变成"截了但回读不到全文"。
    """
    row, cap, cell = _at(window, qapp, ctx, spec, WIDE)
    advance = cap.fontMetrics().horizontalAdvance(cap.text())

    assert spec[3] in cap.text(), f"那句的内容被这一格改写了：{cap.text()!r}"
    assert cap.width() >= advance, (
        f"布局只给 {cap.width()}px 而整句单行要 {advance}px ⇒ 被折行（最低宽没钉住）")
    # 高度按**它真拿到的宽度**要的那一档来量（`heightForWidth(cap.width())`），不是
    # `sizeHint().height()`：后者是 `wordWrap` 在折行宽下算出的多行高（实测 S6 报 43），
    # 而这一格故意把整句钉成单行（只需 13），拿 43 来比会把「做对了」判成「上下被裁」。
    # 坏法仍然是拆掉 `pin_widths()`：宽度掉回 273 ⇒ `heightForWidth(273)=43 > 36` 当场红。
    assert cap.height() >= cap.heightForWidth(cap.width()), (
        f"高度 {cap.height()} 装不下它在 {cap.width()}px 宽下要的 "
        f"{cap.heightForWidth(cap.width())} ⇒ 上下被裁")


# —— 地板档：装不下就整句退回原位（Q5 甲的那一条分支）——————————————————


def test_地板档S6装不下就退回原位且照样看得见(window, qapp, ctx) -> None:
    """S6 的 `lbl_current` 是五条行里唯一在地板档真装不下的（实测需要 585px，地板档行末
    只剩 789−302=487px）。这一条把"装不下"那支钉住：如果判据永远为真，Q5 甲那句
    「退回原位」在产品里就是只能靠人工压窄宿主才能红的死码。

    先压宽档再压地板档：那句得**真的被搬进去过再搬回来**，否则"还原"那一步在这个
    会话里从没执行过，最后一行断言就是恒真的（坏法注入第一轮就是这么漏的）。
    """
    spec = ("", "backup", "lbl_current", "")
    wide_row, wide_cap, wide_cell = _at(window, qapp, ctx, spec, WIDE)
    assert wide_cell.in_row is True and wide_cap.minimumWidth() > 0, \
        "用例前提：宽档先把那句钉进行末，下面的'退回原位'才是一次真的搬回"

    row, cap, cell = _at(window, qapp, ctx, spec, FLOOR)
    assert cell.can_absorb(row._fixed_total(), row.width()) is False, (
        f"地板档该行宽 {row.width()}、按钮占 {row._fixed_total()}、句子要 {cell.width_needed()} "
        "—— 判据居然说装得下，那'装不下退回原位'这一支就是死码")
    assert cell.in_row is False and cap.parentWidget() is not row, "装不下却搬进去了"
    assert not cap.isHidden(), "退回原位之后那句必须照样看得见"
    assert cap.toolTip(), "S6 那句的回读靠 tooltip，空了就等于截断无回读"
    # 行末期间钉的 `minimumWidth` 必须跟着还原：本位上宿主 layout 该能折这一句，留着那份
    # 585px 下限就是把页最低宽顶上去的那条路（**ISSUES I52** 那一族）。坏法：删掉 `_move`
    # 里的 `unpin_widths()`。
    assert cap.minimumWidth() == cell.mins[cap], (
        f"回原位没还原最低宽（现在 {cap.minimumWidth()}，登记时 {cell.mins[cap]}）")


# —— S5 的同伴：句子与进度条同进同出 —————————————————————————


def test_进度句与进度条同进同出(window, qapp, ctx) -> None:
    """把句子挪进行末而把它的进度条留在页底，等于把一句读数劈成两半（线框 §S5 的硬条件）。

    这一条同时是「显式显示位」那处修复的回归钉：坏法是在 `_move` 里不钉回去，
    症状是 `patrol_tick` 刷出来的进度条与句子双双消失（三条 `test_patrol_tick` 当场红）。
    """
    row, cap, cell = _at(window, qapp, ctx, ("", "duplicates", "lbl_progress", ""), WIDE)
    page = window._pages["duplicates"]

    assert cell.in_row is True
    assert cap.parentWidget() is row and page.progress_bar.parentWidget() is row, (
        "进度条没跟着句子走，一句读数被劈成两半")
    assert cap.isVisible() and page.progress_bar.isVisible(), "搬进去之后双双不显示"
    assert "第 120/4,000 份" in cap.text(), cap.text()


# —— 空句与隐藏句：不搬 ——————————————————————————————————


def test_没有判重任务时空句不许搬进行末(window, qapp, ctx) -> None:
    """S5 的 `lbl_progress` 在库里没有 `kind=dedup` 的行时是**隐藏的空标签**。
    搬进去等于把弹簧换成一条缝，而那一格从此占着一个不显示的控件。

    坏法：拆掉 `_Cell.can_absorb` 里"隐藏或空句直接判装不下"那两行守卫。
    """
    window._select_by_page_id("duplicates")
    _settle(qapp)
    page = window._pages["duplicates"]
    _resize_stepped(window, qapp, WIDE, 720)
    _settle(qapp)
    row, cell = page.action_row, page.action_row._cells[0]

    assert ctx.jobs.latest_of_kind("dedup") is None, "用例前提：库里没有判重任务行"
    assert page.lbl_progress.isHidden() and not page.lbl_progress.text()
    assert cell.in_row is False and cell.can_absorb(row._fixed_total(), row.width()) is False
    assert page.lbl_progress.parentWidget() is not row
    assert page.progress_bar.parentWidget() is not row, "隐藏的同伴也不许被搬进去"


# —— 组件级：两个分支都要能红，且能来回 ———————————————————————


def _synthetic(host_width: int):
    """造一个宿主宽可控的 `ActionRow`：两颗按钮 + 一句 40 字的读数 + 一个隐藏的同伴。

    真实页面的行宽被外壳夹在 807–2,343px，五条行在地板档**都**装得下（除 S6），
    所以"装不下"那一支要在产品里点名，只能在这里把宿主压到 400px 才抓得到。
    """
    host = QtWidgets.QWidget()
    host.resize(host_width, 200)
    lay = QtWidgets.QVBoxLayout(host)
    row = ActionRow()
    for text in ("左按钮", "右按钮"):
        row.add_button(QtWidgets.QPushButton(text))
    caption = QtWidgets.QLabel("这一句是行末那格的读数，故意写得长一些，好在窄宿主下装不下。")
    caption.setWordWrap(True)
    lay.addWidget(caption)
    companion = QtWidgets.QProgressBar()
    companion.setVisible(False)
    lay.addWidget(companion)
    row.absorb(lay, caption, companions=(companion,))
    lay.addWidget(row)
    host.show()
    return host, row, caption, companion


def test_窄宿主装不下整句退回原位宽宿主收进行末(qapp) -> None:
    """来回两个方向都要验：单向的断言在"永远搬"或"永远不搬"两种坏法下会有一半漏掉。"""
    host, row, caption, _ = _synthetic(400)
    _settle(qapp)
    cell = row._cells[0]
    # 前提按**与判据无关的两件事**来量（整句单行宽 + 按钮自己的 sizeHint 那份），
    # 不写成 `cell.width_needed()`：那正是 `fits_absorbing` 用的同一个数，
    # 拿它当前提等于问判据"你判对了吗"，坏判据照样点头。
    advance = caption.fontMetrics().horizontalAdvance(caption.text())
    assert advance + row._fixed_total() > row.width(), (
        f"用例前提破了：{host.width()}px 宿主该行宽 {row.width()}，按钮占 "
        f"{row._fixed_total()}、整句要 {advance} —— 明明装得下，这一条就验不到"
        "「装不下退回原位」那一支")
    assert cell.in_row is False, "宿主明显装不下整句，却还是搬进行末了"
    home_index = cell.homes[caption]
    assert cell.home.indexOf(caption) == home_index

    host.resize(1600, 200)
    _settle(qapp)
    assert cell.in_row is True, "拉宽之后没重判（`HostResizeWatcher` 没接上 Resize）"
    assert caption.parentWidget() is row
    assert caption.minimumWidth() >= advance, "搬进去没把单行整句宽钉成最低宽"
    assert cell.home.indexOf(caption) == -1

    host.resize(400, 200)
    _settle(qapp)
    assert cell.in_row is False
    assert caption.minimumWidth() == cell.mins[caption], "回原位没还原最低宽"
    assert cell.home.indexOf(caption) == home_index, "回原位没回到登记的那一格"
    host.close()


def test_搬动不许抹掉控件自己的显式显示位(qapp) -> None:
    """Qt 在跨宿主 `setParent` 里会把控件的显式显示位清掉。

    坏法：删掉 `_move` 末尾那段 `setVisible(not hidden)`。症状：搬进行末的那句与它的同伴
    从此不显示（真页面上是 S5 的进度块整个消失）。隐藏的同伴必须**保持**隐藏 ——
    所以钉的是"自己那一层的 `isHidden()`"，不是连着宿主链的 `isVisible()`。
    """
    host, row, caption, companion = _synthetic(1600)
    _settle(qapp)
    assert row._cells[0].in_row is True
    assert not caption.isHidden(), "搬进去之后显示位被抹掉了"
    assert companion.isHidden(), "同伴本来就藏着，搬动不该把它暴露出来"

    host.resize(400, 200)
    _settle(qapp)
    assert not caption.isHidden() and companion.isHidden(), "退回原位时显示位又被动了一次"
    host.close()


def test_Qt不给文字信号所以改写句子之后必须自己sync(qapp) -> None:
    """`QLabel` 没有 `textChanged`（那是 QLineEdit 的），`setVisible` 也不发任何信号 ——
    所以这一格不会自己发现"同一宽度下句子被重写了"。这条把契约的前提钉住：
    不改宽、只改内容而**不调 `sync()`** 的话，位置是旧的。
    """
    host, row, caption, _ = _synthetic(1600)
    _settle(qapp)
    assert row._cells[0].in_row is True

    # 换成一句**明显超出行宽**的（1600 档行宽约 1,578px，九十章 CJK ≈ 2,500px）：
    # 不调 sync 就该停在行末，调了就该退回原位 —— 两个方向分别是这条的绿与红。
    caption.setText("这一句被改写得很长很长长到这一行明显装不下了所以必须退回原位去。" * 6)
    _settle(qapp)
    assert row._cells[0].in_row is True, "前提破了：Qt 其实会自己重判，那下面的 sync 断言就该删"

    row.sync()
    assert row._cells[0].in_row is False, "sync() 没重判 —— 五个改写点上那一次调用是空转"
    host.close()


def test_改写句子之后行末的最低宽跟着换(qapp) -> None:
    """位置没变（仍在行末）而句子变长了：钉住的 `minimumWidth` 必须跟着上新句子，
    否则布局仍按旧句子的窄宽给，新句子被折行、行高装不下 ⇒ 看不见。

    新句子刻意取**装得下但比旧句子宽**的那一档（≈1,000px < 1,578px 行宽）：
    取"装不下"的话这条只验到 `_move`，验不到 `elif fits: pin_widths()` 那一路。
    """
    host, row, caption, _ = _synthetic(1600)
    _settle(qapp)
    old = caption.fontMetrics().horizontalAdvance(caption.text())
    caption.setText("换了一句比原来宽不少、但这一行仍然装得下的读数，"
                    "为的是专门验最低宽跟着走而不是只跟着位置走。")
    assert caption.fontMetrics().horizontalAdvance(caption.text()) > old, "用例前提：新句子更宽"
    row.sync()
    advance = caption.fontMetrics().horizontalAdvance(caption.text())

    assert row._cells[0].in_row is True
    assert caption.width() >= advance, (
        f"最低宽还停在旧句子：给 {caption.width()}px，新句子要 {advance}px")
    host.close()


# —— 单一判据与最低窗宽 ——————————————————————————————————


def test_全站只有一处装得下判据() -> None:
    """表格吸收列与行末那格共用同一条式子；出现第三个调用方说明有人在别处重写了一遍。

    坏法：把 `fits_absorbing(...)` 就地抄成 `a + b <= c` —— 名字没了，这条要点名文件才抓得到。
    第一版按**文件里有没有出现这个名字**来扫，结果 `action_row.py` 的模块 docstring 就提了
    一句 `fits_absorbing`，把就地抄了一遍那次判成绿（真注入了才发现）。所以扫的是 AST 里的
    **调用**：docstring 里怎么提都不算引用，真用了才算。
    """
    definers, callers = [], []
    for path in sorted(SRC.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        named = {n.name for n in ast.walk(tree)
                 if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                 and n.name == "fits_absorbing"}
        called = any(
            (isinstance(c.func, ast.Name) and c.func.id == "fits_absorbing")
            or (isinstance(c.func, ast.Attribute) and c.func.attr == "fits_absorbing")
            for c in ast.walk(tree) if isinstance(c, ast.Call))
        if named:
            definers.append(path.name)
        elif called:
            callers.append(path.name)

    assert definers == ["viewport_fit.py"], f"判据的定义不止一份：{definers}"
    assert sorted(callers) == ["action_row.py", "table_layout.py"], (
        f"除表格吸收列与行末那格之外还有人自己判装没装下（或这一格根本没走那条判据）：{callers}")


def test_行末那句不许参与宿主的最低宽(qapp) -> None:
    """**ISSUES I52** 那一族的机制：搬进来的句子有自己的最低宽度（S6 省略后仍是 ~420px 的
    不可折断整词），它一旦计入宿主的最低宽，`QSplitter` 就没法把内容列压到地板档 ⇒ 侧栏被榨瘪。

    `ActionRow` 的横向策略是 `Ignored`，所以宿主算最低宽时这一行按 0 计。坏法：把策略改回
    `Preferred` ⇒ 宿主的 `minimumSizeHint().width()` 立刻长成这一行自己要的那个数。
    对照量的是**同一场里这一行自己的 `minimumSizeHint()`**，不是写死的常量。实测（1600 档、
    句子在行末）：行自己报 **532**（按钮 172 + 钉住的整句 360，隐藏的同伴不计），宿主在
    `Ignored` 下只报 **22**。第一版拿 `width_needed()+fixed_total()=649` 当上限，差着一整颗
    隐藏的进度条 ⇒ 改成 `Preferred` 后宿主涨到 532 仍然"小于 649"，这条把换策略真注入了
    才发现它不红 —— 现在比的是这两个数本身。
    真实页面的最低窗宽本身由 `main_window` 写死（D-039 甲案），所以这一条只能在组件级量到。
    """
    host, row, caption, _ = _synthetic(1600)
    _settle(qapp)
    assert row._cells[0].in_row is True, "用例前提：句子在行末，它那份最低宽才算得进来"
    row_min = row.minimumSizeHint().width()
    assert row_min > 300, f"用例前提破了：这一行自己只要 {row_min}px，换个策略也量不出差别"

    host_min = host.minimumSizeHint().width()
    assert host_min < row_min, (
        f"宿主最低宽 {host_min} 已经把行末那句那份 {row_min} 收进来了 ⇒ 内容列压不到地板档")
    host.close()


# —— 五处改写点真的调了 sync ——————————————————————————————

#: page_id → 那句的属性名。改写它的函数必须自己 `sync()`，或它的调用者 `sync()`。
CAPTION_ATTRS = {"archive": "loaded_note", "operations": "loaded_note",
                 "duplicates": "lbl_progress", "backup": "lbl_current",
                 "monitor": "last_check_label"}

_PAGE_FILES = {"archive": "archive_page.py", "operations": "operations_page.py",
               "duplicates": "dedup_page.py", "backup": "backup_page.py",
               "monitor": "health_panel.py"}


def _funcs_rewriting_caption(tree: ast.Module, attr: str):
    """返回所有「体内有 `<self>.<attr>.setText(...)`」的函数节点。"""
    hits = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for call in ast.walk(node):
            fn = call.func if isinstance(call, ast.Call) else None
            if (isinstance(fn, ast.Attribute) and fn.attr == "setText"
                    and isinstance(fn.value, ast.Attribute)
                    and fn.value.attr == attr):
                hits.append(node)
                break
    return hits


def _calls_sync(node: ast.AST) -> bool:
    for call in ast.walk(node):
        if (isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)
                and call.func.attr == "sync"):
            return True
    return False


def _callers(tree: ast.Module) -> dict[str, set[str]]:
    """`被叫的名字 → 谁叫它`。两种接法都算边：`self.foo()` 直接调，
    与 `button.clicked.connect(self.foo)` 交给 Qt 调（后者在界面上是常态）。"""
    reverse: dict[str, set[str]] = {}
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for call in ast.walk(node):
            if not isinstance(call, ast.Call):
                continue
            targets = []
            if isinstance(call.func, ast.Attribute):
                targets.append(call.func.attr)          # self.foo(...)
            for arg in call.args:                       # connect(self.foo)
                if isinstance(arg, ast.Attribute):
                    targets.append(arg.attr)
            for name in targets:
                if name != node.name:
                    reverse.setdefault(name, set()).add(node.name)
    return reverse


@pytest.mark.parametrize("page_id", sorted(CAPTION_ATTRS))
def test_改写那句的地方都重判了一次(page_id) -> None:
    """`sync()` 不是保险丝：Qt 不发"文字变了"的信号，所以**改写点自己**必须重判。

    坏法：删掉某个页面里那一句 `self.action_row.sync()` —— 这一条当场点名是哪个函数。
    S5 走的是调用者那一路（`reload_progress` 用 `finally` 兜住三个提前 return），所以规则
    写成"本函数或它的**某一条**调用链上有一次 `sync()`"。第一版只验"有没有调用者"，
    删掉 `backup_page` 那一句照样绿 —— 调用者存在而调用者不 sync，等于没人重判。
    """
    path = SRC / "ui" / "pages" / _PAGE_FILES[page_id]
    tree = ast.parse(path.read_text(encoding="utf-8"))
    writers = _funcs_rewriting_caption(tree, CAPTION_ATTRS[page_id])
    assert writers, f"{path.name} 里找不到改写 `{CAPTION_ATTRS[page_id]}` 的那一处"
    reverse = _callers(tree)
    syncers = {n.name for n in ast.walk(tree)
               if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and _calls_sync(n)}

    for writer in writers:
        seen = {writer.name}
        frontier, covered = [writer.name], writer.name in syncers
        while frontier and not covered:
            nxt = []
            for name in frontier:
                for caller in reverse.get(name, ()):
                    if caller in seen:
                        continue
                    seen.add(caller)
                    nxt.append(caller)
                    covered = covered or caller in syncers
            frontier = nxt
        assert covered, (
            f"{path.name}::{writer.name}() 改写了那一句，而它自己与它的整条调用链上"
            "都没有一次 `sync()` ⇒ 改写之后没人重判")
