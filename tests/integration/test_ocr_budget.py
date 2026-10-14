"""每日页预算的记账（G13 作废重定的第一件，推导见 `ocr/budget.py` 与 docs/DECISIONS.md D-028）。

库是真的（D-012 不许 mock 数据库）：这一层唯一要验的就是**计数在跨天、坏值和进程被杀之后
还说不说得清**。预算停在什么状态上、单页超时怎么拦，那是编排层的事，在 `test_ocr_service.py`。

`app_settings` 里放的是"今天已经跑了多少页"（应用内部状态），`settings.json` 里放的是
"上限是多少"（用户配置）—— 同一个概念不许有两个存放处，所以两边各测各的。
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from pdfarchiver.ocr.budget import OcrBudget
from pdfarchiver.services.bootstrap import bootstrap


def _budget(ctx, pages_per_day: int) -> OcrBudget:
    """走真库的记账本。上限这里给死值，测的是记账不是配置。"""
    return OcrBudget(ctx.app_settings, pages_per_day=pages_per_day)


def _today(offset_days: int = 0) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=offset_days)).strftime("%Y-%m-%d")


def test_上限读的是settings_json里的覆盖值(data_root) -> None:
    """装配那一步把配置接到预算上（阶段 5「完成后更新 OCR 配置」的落点）。
    写死 6,000 也能让别的测试全绿，所以这条必须从文件一路走到 `ctx.ocr.budget`。"""
    f = data_root / "config" / "settings.json"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps({"ocr_daily_page_budget": 7}), encoding="utf-8")
    ctx = bootstrap(data_root)
    try:
        assert ctx.settings["ocr_daily_page_budget"] == 7
        assert ctx.ocr.budget.pages_per_day == 7, "配置没接到预算上，用户改的就是个装饰"
        assert ctx.ocr.budget.remaining() == 7
    finally:
        ctx.shutdown()


def test_用满一页少一页用满即停(ctx) -> None:
    b = _budget(ctx, 3)
    assert (b.used_today(), b.remaining(), b.exhausted()) == (0, 3, False), "首启就该是满的"
    b.consume()
    assert (b.used_today(), b.remaining(), b.exhausted()) == (1, 2, False)
    b.consume(2)
    assert (b.used_today(), b.remaining(), b.exhausted()) == (3, 0, True)


def test_记账超出上限也不许出现负数剩余(ctx) -> None:
    """并发 worker 可能在同一瞬间各消费一页；读数负数会直接把界面写成"剩 -1 页"。"""
    b = _budget(ctx, 2)
    b.consume(5)
    assert b.used_today() == 5 and b.remaining() == 0 and b.exhausted() is True


def test_一页写一次进程被杀后计数不倒退(ctx) -> None:
    """攒到整本再写等于把"跑到一半被断电"的那一半工作量凭空抹掉，预算就形同虚设。"""
    b = _budget(ctx, 10)
    b.consume()
    assert ctx.app_settings.get(OcrBudget.KEY)["pages"] == 1, "第一页就得落库"
    b.consume()
    stored = ctx.app_settings.get(OcrBudget.KEY)
    assert stored["pages"] == 2 and stored["date"] == _today() and stored["budget"] == 10


def test_计数落库重启之后今天已经跑了多少页还在(ctx, reopen) -> None:
    """重启把预算清零 = 每次崩溃都能重新烧掉一整天，这条限制就不存在了。"""
    ctx.ocr.budget.consume(4)
    assert ctx.ocr.budget.used_today() == 4
    second = reopen()
    try:
        assert second.ocr.budget.used_today() == 4
        assert second.ocr.budget.remaining() == second.ocr.budget.pages_per_day - 4
    finally:
        second.shutdown()


def test_换了UTC日自动归零不需要任何定时任务(ctx) -> None:
    """记账里带日期，日期一变读数就是 0 —— 没有后台线程去"清计数器"，就没有清失败这条路。"""
    b = _budget(ctx, 2)
    b.consume(2)
    assert b.exhausted()
    ctx.app_settings.set(OcrBudget.KEY, {"date": _today(-1), "pages": 2, "budget": 2}, kind="state")
    assert (b.used_today(), b.remaining(), b.exhausted()) == (0, 2, False)


def test_记账内容是坏值时按零处理而不是把预算炸掉(ctx) -> None:
    """手工改库、别的版本写下的格式，都会让读数变成不可比的东西。
    这时宁可放行（当作今天没跑），也不能让 worker 抛异常把任务烧掉三次重试预算。
    两类都要真给：日期不是今天的（读不到今天的账），以及日期对但页数不是数的（`int()` 会抛）。
    """
    b = _budget(ctx, 4)
    wrong_shape = ["今天跑了不少页", 7, None]
    right_date_bad_pages = [{"date": _today(), "pages": "许多"}, {"date": _today(), "pages": None}]
    for broken in wrong_shape + right_date_bad_pages:
        ctx.app_settings.set(OcrBudget.KEY, broken, kind="state")
        assert b.used_today() == 0, f"坏值 {broken!r} 没被按零处理"
        assert b.remaining() == 4 and b.exhausted() is False


def test_读数说得出已用上限与是哪一天(ctx) -> None:
    """界面与门禁只能转述这一句；缺任何一个数，"为什么停了"就没人答得出。"""
    b = _budget(ctx, 6000)
    b.consume(120)
    text = b.describe()
    assert "已用 120 页" in text and "预算 6000 页" in text and "剩 5880 页" in text, text
    assert _today() in text, "不说清这是哪一天的账，跨天读数就没法核对"
