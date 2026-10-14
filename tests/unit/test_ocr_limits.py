"""G13 作废重定之后那两条限量的**出处**（docs/DECISIONS.md D-028）。

放 unit 不是因为它们简单，而是因为**这两个数错了，集成测试发现不了**：
上限松了不会有人失败，紧了会在门禁机器上偶尔红一次 —— 两种都只能靠"数是怎么来的"来断言。
所以这里比的不是字面值，是它们与实测数据的推导关系：AGENTS.md「写死的阈值必须按最大量级反算」。

实测原始数据：`.probe_work/p5_ocr_result.json`（同一台机器、同两批页，DML 与 CPU 各 14 页）
与 `.probe_work/p11_ocr_shipped_result.json`（产品路径端到端 6 页）。数字不许手改。
"""
from __future__ import annotations

from pdfarchiver.config.settings import DEFAULTS
from pdfarchiver.ocr.budget import (DEFAULT_DAILY_PAGE_BUDGET, PAGE_TIMEOUT_MS, page_timeout_ms)

# p5 实测单页最大耗时（毫秒）。DML 那一档是在**别的进程正占用独显**时测到的，
# 所以它是"合法波动"的上界而不是故障值 —— 上限必须容得下它。
P5_MEASURED_MAX_MS = {"DmlExecutionProvider": 14_072.0, "CPUExecutionProvider": 80_291.0}

# 每日预算按"最慢的可持续吞吐"反算：p5 DML 均值（显卡被占用时）+ P11 在产品路径上
# 实测的出图与落库开销（墙钟 13.72s/6 页 = 2,286.7ms，减去推理均值 2,155.3ms）。
P5_SLOWEST_MEAN_MS = 4_061.8
P11_OVERHEAD_MS = 131.4
UNATTENDED_HOURS = 8


def test_每个已知provider都有实测依据() -> None:
    """加一档 provider 就得先有实测，否则这里的数是无根据拍的（阶段 5「不要编造性能数据」）。"""
    assert set(PAGE_TIMEOUT_MS) == set(P5_MEASURED_MAX_MS), \
        "上限表与实测数据不同源：要么是没测就加了档，要么是测过却忘了登记上限"


def test_单页上限是实测最大值乘二() -> None:
    for provider, measured_max in P5_MEASURED_MAX_MS.items():
        limit = page_timeout_ms(provider)
        assert limit >= measured_max * 2, \
            f"{provider} 上限低于实测最大值 ×2：显卡争用时（实测快 1.9 倍差距）会把正常任务打死"
        assert limit < measured_max * 3, \
            f"{provider} 上限放到 ×3 以上就不是拦病态文件，是什么都拦不住"


def test_没测过的provider用最宽的一档() -> None:
    """认不出的 provider（CUDA、未来的 CoreML）拿最宽的那档 —— 没测过它有多快就没资格掐它。"""
    widest = max(PAGE_TIMEOUT_MS.values())
    for provider in ("CUDAExecutionProvider", "CoreMLExecutionProvider", None, ""):
        assert page_timeout_ms(provider) == widest


def test_每日预算是最慢档八小时跑不满的那个数() -> None:
    per_page_ms = P5_SLOWEST_MEAN_MS + P11_OVERHEAD_MS
    affordable = UNATTENDED_HOURS * 3_600_000 / per_page_ms
    assert DEFAULT_DAILY_PAGE_BUDGET <= affordable, \
        f"预算 {DEFAULT_DAILY_PAGE_BUDGET} 页超过最慢档 {UNATTENDED_HOURS} 小时能跑的 {affordable:.0f} 页"
    assert DEFAULT_DAILY_PAGE_BUDGET > affordable - 1_000, \
        "预算比反算值还小一千页以上就是随手改数，不是按量级取的"


def test_预算的配置默认值与代码默认值同源() -> None:
    """两处各写一份 6,000 迟早会分家 —— 配置项是用户改的那份，必须与代码兜底值一致。"""
    assert DEFAULTS["ocr_daily_page_budget"] == DEFAULT_DAILY_PAGE_BUDGET


def test_预算拦的是量级而不是单次慢() -> None:
    """全量待 OCR 是 1,014,112 页（p5 实测外推）。按预算跑要一百多个自然日 ——
    这条限制拦的是"点错一次把机器烧一整天"，它并没有把全量 OCR 变成可达成的承诺，
    界面与文档都不许把它说成"跑完就好"。"""
    total_pending_pages = 1_014_112
    days = total_pending_pages // DEFAULT_DAILY_PAGE_BUDGET
    assert days >= 100, f"只要 {days} 天就能跑完全库，这条预算该整个删掉而不是留着糊弄界面"
