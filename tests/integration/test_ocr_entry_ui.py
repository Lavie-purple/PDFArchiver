"""「送去识别」—— S1 的 OCR 触发入口（销账 **ISSUES I67** 甲，2026-10-19）。

ISSUES I67 原文记的是：`services/ocr_service.py:176 request_ocr(doc_ids)` 在产品侧**零调用点**，
识别必须由 `gates/stage5.py` 与测试按 `doc_id` 点名，S7 只有 O1/O2/O3 三个读数。
线框 §I67-jia（`docs/wireframes/2026-10-19-round14-i67-i78.html`，2026-10-19 勾「甲先乙后」）
落地的是**单份就地点名**：表格底下那一颗按钮 + 状态条那一句回执。

这一组断言逐条对着 **ISSUES I67** 的三条销账判定写：
① 入口按下之后 `jobs` 里 `kind='ocr'` 的行数 **+N**，且 N 就是屏幕上那句回执里的份数；
② 被跳过的每一类理由都能在屏幕上读到（`SKIP_LABELS` 是唯一出口，界面不重算）；
③ 预算跑满时**在屏幕上看得见**（不是只在读数里多一个数字）。
另两条是这个入口自身的接线：没有当前行就不许点得动；那句回执必须**逐字**是后端 `describe()`。

夹具三条规矩照常（offscreen、独立数据根、真 sqlite3 —— **D-012**）。
样本由 `tests/conftest.py` 现场生成的真 PDF（扫描件 = 整页贴图零文本层，文字版 = 有原生层），
真实语料一条不进测试（**ISSUES I64**）。
"""
from __future__ import annotations

from pathlib import Path

from PySide6 import QtCore

from pdfarchiver.services import ocr_service
from tests.integration.ocr_doubles import _doc_id, _scanned, _textual
from tests.conftest import settle as _settle


def _library(window, qapp):
    """切到 S1 并重查一遍，返回页面对象（与 `test_library_paging_ui` 同一条取法）。"""
    window._select_by_page_id("library")
    _settle(qapp)
    page = window._pages["library"]
    page.reload()
    _settle(qapp)
    return page


def _queued(ctx) -> int:
    return ctx.jobs.counts_by_kind_state().get(("ocr", "queued"), 0)


def _select(page, qapp, doc_id) -> None:
    row = next(r for r in range(page.doc_table.rowCount())
               if page.doc_table.item(r, 0).data(QtCore.Qt.ItemDataRole.UserRole) == doc_id)
    page.doc_table.selectRow(row)
    _settle(qapp)


# ---------------------------------------------------------------------------
# 接线：没有当前行就没有点名的对象
# ---------------------------------------------------------------------------

def test_没有当前行时那颗按钮是禁用的(window, ctx, qapp) -> None:
    """坏法注入实测（`tests/probes/p9_reverse_injection.py` Case 48）：把建按钮那行的
    `setEnabled(False)` 删掉 ⇒ 本条红在"空库里按钮是enabled"。"""
    page = _library(window, qapp)
    assert page.doc_table.rowCount() == 0, "用例前提：这一档库里没有行"

    assert not page.ocr_btn.isEnabled(), "库是空的、没有当前行，那颗按钮却按得动"
    assert page._selected_doc_id is None

    before = _queued(ctx)
    page.ocr_btn.click()
    _settle(qapp)
    assert _queued(ctx) == before, "禁用态的按钮按下去还是排了一条队"


def test_选中一行后按钮变成可点(window, ctx, root, make_scanned_pdf, qapp) -> None:
    """钉的是 `_on_doc_selected` 里那一行：按钮建来是禁用的，只有选中才该活过来。"""
    doc_id = _scanned(ctx, root, make_scanned_pdf)
    page = _library(window, qapp)

    assert not page.ocr_btn.isEnabled()
    _select(page, qapp, doc_id)
    assert page.ocr_btn.isEnabled(), "选中了一行，那颗按钮还是死的（控件在场、链路不在场）"


# ---------------------------------------------------------------------------
# ① 按下之后 +1，而屏幕上那句说的就是 1
# ---------------------------------------------------------------------------

def test_按下扫描件后排一条而状态条说得出这一条(window, ctx, root, make_scanned_pdf, qapp) -> None:
    """**I67 销账判定①**：+N 且 N = 界面显示的该跑份数（两个读数必须同源）。"""
    doc_id = _scanned(ctx, root, make_scanned_pdf)
    page = _library(window, qapp)
    _select(page, qapp, doc_id)
    before = _queued(ctx)

    page.ocr_btn.click()
    _settle(qapp)

    assert _queued(ctx) == before + 1, (
        f"按下之后队列里的 ocr 任务从 {before} 条变成 {_queued(ctx)} 条 —— 入口没接到 request_ocr")
    line = page.status_label.text()
    assert "点名 1 份｜该跑 1 份｜新增任务 1 条" in line, f"那句回执没报出这三个数：{line}"
    assert ctx.ocr.budget.describe() in line, f"那句回执没带上今日预算：{line}"
    assert page.status_label.objectName() != "danger", "排队成功却是红字"


def test_重复点同一份时新增0条而屏幕上看得见0条(window, ctx, root, make_scanned_pdf, qapp) -> None:
    """`queueable` 与 `enqueued` 分开数是服务层的口径（去重不是没排上）；
    屏幕上必须原样报「新增任务 0 条」，否则用户会以为按了没反应。"""
    doc_id = _scanned(ctx, root, make_scanned_pdf)
    page = _library(window, qapp)
    _select(page, qapp, doc_id)

    page.ocr_btn.click()
    _settle(qapp)
    queued = _queued(ctx)

    page.ocr_btn.click()
    _settle(qapp)
    assert _queued(ctx) == queued, "同一份被排了两次 —— 去重在服务层，界面不许绕过它"
    assert "新增任务 0 条" in page.status_label.text(), page.status_label.text()


# ---------------------------------------------------------------------------
# ② 跳过的理由必须在屏幕上，而不只在日志里
# ---------------------------------------------------------------------------

def test_判过不需要识别的那一份按下不排队而理由上屏(window, ctx, root, make_pdf, qapp) -> None:
    """**ISSUES I67** 销账判定②（甲案那一格：一份一份指得到）+ **ISSUES I84** 那条「可见但不许常驻」：
    有理由时红字，理由的措辞取后端 `SKIP_LABELS`，界面不翻译第二遍。"""
    doc_id = _textual(ctx, root, make_pdf)     # 有原生文字层 ⇒ ocr_status='na'
    page = _library(window, qapp)
    _select(page, qapp, doc_id)
    before = _queued(ctx)

    page.ocr_btn.click()
    _settle(qapp)

    assert _queued(ctx) == before, "判定为不需要 OCR 的一份还是被排进队列了"
    line = page.status_label.text()
    assert ocr_service.SKIP_LABELS[ocr_service.SKIP_NOT_NEEDED] in line, f"+0 却没有理由：{line}"
    assert "新增任务 0 条" in line
    assert page.status_label.objectName() == "danger", "没排进队列却是常态色"


def test_还没索引的那一份按下说的是先索引(window, ctx, root, make_pdf, qapp) -> None:
    """另一类理由（`no_verdict`）：入场券是一份可用的正文判定，界面不许把它说成「不需要」。"""
    r = root("未索引")
    path = Path(make_pdf("未索引/没索引.pdf", pages=1, lines=["一句话正文内容测试用"]))
    ctx.scan.scan_root(r)
    doc_id = _doc_id(ctx, path)

    page = _library(window, qapp)
    _select(page, qapp, doc_id)
    before = _queued(ctx)

    page.ocr_btn.click()
    _settle(qapp)

    assert _queued(ctx) == before
    assert ocr_service.SKIP_LABELS[ocr_service.SKIP_NO_VERDICT] in page.status_label.text(), (
        page.status_label.text())


# ---------------------------------------------------------------------------
# ③ 预算跑满时界面可见
# ---------------------------------------------------------------------------

def test_今日预算跑满时按下去说的是预算跑满(window, ctx, root, make_scanned_pdf, qapp) -> None:
    """**I67 销账判定③**：预算是资源闸门，`force` 也不绕它，所以屏幕上必须当场说清
    「今天跑满了」，而不是让人对着一条永远不动的队列猜。"""
    doc_id = _scanned(ctx, root, make_scanned_pdf)
    ctx.ocr.budget.consume(ctx.ocr.budget.pages_per_day)      # 直接把今天的额度用满
    page = _library(window, qapp)
    _select(page, qapp, doc_id)
    before = _queued(ctx)

    page.ocr_btn.click()
    _settle(qapp)

    assert _queued(ctx) == before, "预算已跑满还排进了队列 —— 闸门被界面绕过了"
    line = page.status_label.text()
    assert ocr_service.SKIP_LABELS[ocr_service.SKIP_BUDGET] in line, f"预算跑满却没上屏：{line}"
    assert page.status_label.objectName() == "danger"
    assert "剩 0 页" in line, f"预算那句没报出剩多少：{line}"


# ---------------------------------------------------------------------------
# 回执的形状：屏幕上那句 = 后端那句，界面不重算
# ---------------------------------------------------------------------------

def test_状态条那句逐字就是后端回执(window, ctx, root, make_scanned_pdf, qapp,
                                    monkeypatch) -> None:
    """**ISSUES I60** 那条纪律在 OCR 入口上的版本：格式化只有后端一个出口。
    界面若自己拼一份「已排队 N 份」，就有第二个口径 —— 那份数会与 `OcrRequest` 悄悄漂。"""
    doc_id = _scanned(ctx, root, make_scanned_pdf)
    page = _library(window, qapp)
    _select(page, qapp, doc_id)

    seen: dict = {}
    original = ctx.ocr.request_ocr

    def spy(doc_ids, **kw):
        receipt = original(doc_ids, **kw)
        seen["ids"], seen["receipt"] = list(doc_ids), receipt
        return receipt

    monkeypatch.setattr(ctx.ocr, "request_ocr", spy)
    page.ocr_btn.click()
    _settle(qapp)

    assert seen["ids"] == [doc_id], f"按下去递下去的不是当前行那一份：{seen.get('ids')}"
    assert page.status_label.text() == (
        f"{seen['receipt'].describe()}｜{ctx.ocr.budget.describe()}"), (
        f"那句不是后端回执原样：{page.status_label.text()!r}")


def test_排队失败时屏幕上留的是后端原文(window, ctx, root, make_scanned_pdf, qapp,
                                        monkeypatch) -> None:
    """**ISSUES I84** ③ 的同一口径：服务层抛出来的是原文，不许穿出 Qt 槽让屏幕「什么都不发生」。"""
    doc_id = _scanned(ctx, root, make_scanned_pdf)
    page = _library(window, qapp)
    _select(page, qapp, doc_id)

    def boom(doc_ids, **kw):
        raise RuntimeError("模拟排队时库被锁住")

    monkeypatch.setattr(ctx.ocr, "request_ocr", boom)
    page.ocr_btn.click()
    _settle(qapp)

    line = page.status_label.text()
    assert "模拟排队时库被锁住" in line, f"失败原文没上屏：{line}"
    assert page.status_label.objectName() == "danger"


# ---------------------------------------------------------------------------
# ISSUES I67 那条账的本体：产品里 `request_ocr` 不再是零调用点
# ---------------------------------------------------------------------------

def test_request_ocr在产品侧有调用点了() -> None:
    """**ISSUES I67** 记的就是「调用方全在 `gates/` 与 `tests/`，`src/` 里零调用点」。
    这条把反过来的事实钉住：`src/` 里必须真的**只有 S1 那两处**（甲案那颗按钮 + 乙案面板里的
    「排队」），而不是长成第三个各自算一遍份数的入口。哪天把按钮拆了而没接上别的入口，
    本条就是会红的那一处（坏法见 p9 注入 I49）。"""
    src = Path(__file__).resolve().parents[2] / "src"
    callers = sorted({path.relative_to(src).as_posix()
                      for path in src.rglob("*.py")
                      if ".request_ocr(" in path.read_text(encoding="utf-8")})
    assert callers == ["pdfarchiver/ui/ocr_batch_panel.py",
                       "pdfarchiver/ui/pages/library_page.py"], (
        f"产品里 `request_ocr` 的调用点现在是：{callers}")
