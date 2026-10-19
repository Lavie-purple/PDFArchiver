"""批量点名面板那份账的**读数形状**（**ISSUES I67** 乙，2026-10-19 勾「甲先乙后」）。

放 unit 的理由与 `test_ocr_idempotency.py` 同一条：`OcrPlan` / `SkippedReason` 这几句话是纯数据
拼装，不碰库、不碰 Qt，而界面只是它们的投影 —— **投影接错线**在
`tests/integration/test_ocr_batch_panel_ui.py` 抓，**源头说错话**在这里抓。
**ISSUES I67** 的销账判定②（"每一类跳过理由都指得到是哪几份"）与③（"预算不够不许静默"）
的判据全部落在本文件覆盖的三处：`SkippedReason.label/name_preview`、
`OcrPlan.describe/cost_line`、`OcrPlan.budget_note`。

每条断言都有登记的坏法，见 `tests/probes/p23_ocr_batch_injection.py` 的 U1–U5。
"""
from __future__ import annotations

from pdfarchiver.ocr.budget import PAGE_MS_RANGE
from pdfarchiver.services.ocr_service import (NAME_PREVIEW_LIMIT, SKIP_BUDGET, SKIP_CURRENT,
                                             SKIP_LABELS, SKIP_NO_VERDICT, SKIP_NOT_NEEDED,
                                             OcrPlan, SkippedDoc, SkippedReason)


def _docs(*names: str) -> tuple[SkippedDoc, ...]:
    return tuple(SkippedDoc(i + 1, name) for i, name in enumerate(names))


def test_点名的份数拆成该跑与不跑而两者相加就是点名() -> None:
    """`named = queueable + skipped` 是面板那三个数的恒等式：少一份多一份都是把用户的名单改了。

    逐字整句比对而不是 `in`：`describe()` 是屏幕上那句的**唯一出口**（**ISSUES I60**），
    它少了哪一段、顺序换了，界面跟着一起错，而 `in` 看不见。
    """
    plan = OcrPlan(named=5, queueable=(1, 2),
                   skipped=(SkippedReason(SKIP_NOT_NEEDED, _docs("甲.pdf")),
                            SkippedReason(SKIP_NO_VERDICT, _docs("乙.pdf", "丙.pdf"))),
                   pages_queueable=8, budget_remaining=6000)

    assert plan.skipped_count == 3
    assert len(plan.queueable) + plan.skipped_count == plan.named
    assert plan.describe() == (
        f"点名 5 份｜该跑 2 份｜不跑 3 份｜"
        f"{SKIP_LABELS[SKIP_NOT_NEEDED]} 1 份｜{SKIP_LABELS[SKIP_NO_VERDICT]} 2 份")


def test_每一类理由那一行报的是后端措辞加这一类的份数() -> None:
    """**销账判定②**的标题那半：措辞取自 `SKIP_LABELS`（界面不翻译第二遍），份数取自这一类自己。"""
    item = SkippedReason(SKIP_BUDGET, _docs("a.pdf", "b.pdf", "c.pdf"))

    assert item.label() == f"{SKIP_LABELS[SKIP_BUDGET]}（3 份）"
    plan = OcrPlan(named=3, queueable=(), skipped=(item,), pages_queueable=0, budget_remaining=0)
    assert f"{SKIP_LABELS[SKIP_BUDGET]} 3 份" in plan.describe()
    assert plan.skipped_count == 3


def test_展开清单只列到上限而剩下的说得出还有几份() -> None:
    """清单上限的存在理由：**指得到是哪几份**，不是把屏幕变成文件管理器。

    两头都要钉：越过上限就不算"预览"（一行塞满几百个文件名，谁都读不完），
    而正好等于上限时多出一句「还有 0 份没列出」是谎报 —— 屏幕上有 0 这句话就等于
    在说"后面还有"，与 **ISSUES I84** ② 那一类"文案指向一个不存在的动作"同一族。
    """
    many = _docs(*[f"第{i}份.pdf" for i in range(1, NAME_PREVIEW_LIMIT + 3)])
    shown = SkippedReason(SKIP_CURRENT, many).name_preview()

    assert shown.split("、")[0] == "第1份.pdf"
    assert f"第{NAME_PREVIEW_LIMIT}份.pdf" in shown
    assert f"第{NAME_PREVIEW_LIMIT + 1}份.pdf" not in shown
    assert shown.endswith("（还有 2 份没列出）")
    assert SkippedReason(SKIP_CURRENT, _docs("x.pdf", "y.pdf")).name_preview(limit=2) == "x.pdf、y.pdf"


def test_代价那句给的是主记录页数与实测区间两端() -> None:
    """区间两端都必须上屏（**ISSUES I1** 那三次实测就是两端）：只报一个数是伪装成准确。

    页数口径必须自带「按主记录页数算」这句 —— 它是上限而不是承诺（已有原生文字层的页不推理），
    少这一句屏幕就在承诺一个它算不出来的数。
    """
    lo, hi = PAGE_MS_RANGE
    line = OcrPlan(named=1, queueable=(7,), skipped=(), pages_queueable=40,
                   budget_remaining=6000).cost_line()

    assert "共 40 页" in line
    assert f"单页实测 {lo:,}–{hi:,}ms" in line
    assert "按主记录页数算，待推理的页可能更少" in line
    assert f"预计 {40 * lo / 60_000:.1f}–{40 * hi / 60_000:.1f} 分钟" in line
    assert OcrPlan(named=1, queueable=(), skipped=(SkippedReason(SKIP_NOT_NEEDED, _docs("a.pdf")),),
                   pages_queueable=0, budget_remaining=6000).cost_line() == "这一批没有该跑的份，不烧页"


def test_预算那三档说的是此刻够不够跑完这一批() -> None:
    """**销账判定③**：预算是资源闸门，不许静默。三档各有各的措辞，一档都不许缺。

    `pages == remaining` 那一条钉的是差一错（`>` 写成 `>=` 就把"正好够"说成"不够"，
    而用户看到的是一句劝退的话 —— 屏幕上那句与真跑得到底会不会停是两件事）。
    """
    def note(pages: int, remaining: int) -> str:
        return OcrPlan(named=1, queueable=(1,), skipped=(), pages_queueable=pages,
                       budget_remaining=remaining).budget_note()

    assert note(10, 0) == "今天的页预算已经用满：按下「排队」一条也不会进队列，明日自动恢复"
    assert note(10, 1) == ("今日预算不够跑完这一批：跑满即停，剩下的明天自动回到待办"
                          "（预算是资源闸门，强制也不绕）")
    assert note(10, 10) == "今日预算够跑完这一批", "正好够的时候不许说不够（差一错）"
    assert note(10, 11) == "今日预算够跑完这一批"
    assert len({note(10, 0), note(10, 1), note(10, 10)}) == 3, "三档说成了同一句 = 有一档没算"
