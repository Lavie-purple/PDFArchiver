"""OCR 的两种限量：每日页预算与单页超时（G13 作废重定的产物，推导见 docs/DECISIONS.md D-028）。

原来那条 G13 是「单页耗时预算 284ms」，由 A-OCR-1（8 小时无人值守推进 10% 待 OCR 页）反算而来。
实测 2,155–4,062ms/页（P11 与 p5），那个预算**任何引擎在任何显卡上都达不到**，
所以整条作废，换成两件做得到、也拦得住东西的限制：

1. **每日页预算**：跑满即停，界面上说得出"今天已经跑了多少页 / 上限多少"。
   这一条拦的是"点错一次把机器烧一整天"，不是拦单页慢。
2. **单页超时**：超过上限的那一页判失败、这份停下等下次。这一条拦的是病态文件
   （超大页面、畸形图像），不是拦"今天显卡被别人占着所以慢了两倍"。

两条都不是拍脑袋的数，全部由实测反算，实测数据在 `.probe_work/p5_ocr_result.json`
与 `.probe_work/p11_ocr_shipped_result.json`：

| 限制 | 依据 | 反算 | 取值 |
|---|---|---|---|
| 单页超时（DirectML） | 实测单页最大 14,072ms（p5，GTX 1060 被别的进程占用时） | ×2 = 28,144 → 向上取整到 5s 档 | 30,000ms |
| 单页超时（CPU 降级） | 实测单页最大 80,291ms（p5 同一批页走 CPU） | ×2 = 160,582 → 同上 | 165,000ms |
| 每日页预算 | 实测最慢的**可持续**吞吐 4,193ms/页 = p5 DML 均值 4,061.8ms（显卡被占用时）+ P11 在产品路径上实测的出图与落库开销 131.4ms（墙钟 13.72s/6 页 = 2,286.7ms 减推理均值 2,155.3ms） | 8 小时无人值守 = 28,800s ÷ 4.193s ≈ 6,868 页 → 向下取整到千位 | 6,000 页/日 |

这两条反算关系由 `tests/unit/test_ocr_limits.py` 断言 —— 改这里的数必须同时改实测出处，
不然改的就是口味。预算用均值而不是最大值：它算的是"一天最多烧多少"，
按单页最值算会把预算压到几百页，那条限制就成了摆设。

×2 而不是 ×1.2：p5 那批页是在**别的进程正占用独显**时测的，P11 同一台机器空闲时快 1.9 倍 ——
显卡争用是合法波动的主要来源，上限必须容得下它，否则超时会在最该干活的时候把任务全打死。
预算取最慢档：预算的目的是"一天最多烧多少"，按慢的算才不会低估。

超时的实现口径要写明白：它是**单页返回之后**判定，不是抢占。ONNX 推理挂死时唯一能提前脱身的
办法是把推理丢进线程再放弃它，而被放弃的线程仍持有显存（p5 实测一次推理 701MB），
那是比慢更糟的泄漏。所以这里的选择是"事后判 + 立刻停下这一份"，真挂死要靠重启进程，
这条留在 docs/RISKS.md。
"""
from __future__ import annotations

from datetime import datetime, timezone

# provider → 单页耗时上限（毫秒）。推导见模块表格；改这两个数必须同时改推导。
PAGE_TIMEOUT_MS = {"DmlExecutionProvider": 30_000, "CPUExecutionProvider": 165_000}

# 每日页预算的默认值。用户可在 settings.json 覆盖（`ocr_daily_page_budget`），代码不替用户改。
DEFAULT_DAILY_PAGE_BUDGET = 6000


def page_timeout_ms(provider: str | None) -> int:
    """认不出的 provider 用最宽的那档 —— 没测过它有多快，就没资格掐它。"""
    return PAGE_TIMEOUT_MS.get(provider or "", max(PAGE_TIMEOUT_MS.values()))


class OcrBudget:
    """今天还能识别几页。上限来自配置，已用页数存 `app_settings`（应用内部状态，不是配置）。

    跨天自动归零：存储里带 UTC 日期，日期一变读数就是 0，不需要任何定时任务去清它。
    用 UTC 与全站时间口径一致（`diagnostics/logs.py` 与 `db/models.now_ts` 都是 UTC），
    否则"今天"会有两个定义。
    """

    KEY = "ocr.pages_today"

    def __init__(self, app_settings, pages_per_day: int = DEFAULT_DAILY_PAGE_BUDGET) -> None:
        self.settings = app_settings
        self.pages_per_day = int(pages_per_day)

    def _today(self) -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")

    def used_today(self) -> int:
        stored = self.settings.get(self.KEY) or {}
        if not isinstance(stored, dict) or stored.get("date") != self._today():
            return 0
        try:
            return max(0, int(stored.get("pages", 0)))
        except (TypeError, ValueError):
            return 0

    def remaining(self) -> int:
        return max(0, self.pages_per_day - self.used_today())

    def exhausted(self) -> bool:
        return self.remaining() <= 0

    def consume(self, pages: int = 1) -> None:
        """记下一页的开销。**失败的页同样要记** —— 预算拦的是 GPU 时间，不是识别成果。

        一页写一次：崩溃或杀进程之后计数不会倒退。攒到整本再写等于把"跑到一半被断电"
        的那一半工作量凭空抹掉，预算就形同虚设。
        """
        if pages <= 0:
            return
        self.settings.set(self.KEY, {"date": self._today(),
                                     "pages": self.used_today() + pages,
                                     "budget": self.pages_per_day}, kind="state")

    def describe(self) -> str:
        return (f"今日 OCR 已用 {self.used_today()} 页 / 预算 {self.pages_per_day} 页"
                f"（剩 {self.remaining()} 页，UTC 日 {self._today()}）")
