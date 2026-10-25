"""S7「库体检」（#198 · 1甲 2甲 3甲 4甲）—— 服务口径 + 面板接线。

四条分开验，因为它们会各自坏掉：

1. **服务口径**：快速档 10 行、全库档 13 行；每条判据与 p12 同源。坏法注入：
   把 C13 的比较改成恒真 → 第二条红；删掉 C11 的 0 字节分支 → 第三条红。
2. **4甲 持久化**：`app_settings["db_check.last"]` 里只许有 `ts/mode/total/red/readings/elapsed_s`
   六个键 —— 明细不落盘这件事写成"键集合相等"，多存一个字段就红。
3. **1甲 面板接线**：设置页里翻页（不另开窗口）、点「快速体检」后表格真的铺上 10 行、
   「上次体检」行跟着更新、返回设置页。坏法注入：把 `finished` 接到空 lambda → 这张表停在 0 行。
4. **成本读数（**ISSUES I110** 丙）**：文案里四场读数都在且明说跨度没定位；确认框那一个
   点上的时长回读 `db_check.last.elapsed_s`，且只认 `mode == full` 的记录。
"""
from __future__ import annotations

import time

from pdfarchiver.services.db_check import (
    FULL,
    LAST_KEY,
    QUICK,
    DbCheckService,
    last_full_elapsed,
)


def _row(report, code: str):
    return next(r for r in report.rows if r.code == code)


def test_快速体检十行且零红(ctx) -> None:
    """零数据的干净库上，快速档不该有红行；C9 只能是「读数」（应用运行中 running>0 不算残留）。"""
    report = ctx.db_check.run(QUICK)

    assert report.total == 10, f"快速档该有 10 项：{[r.code for r in report.rows]}"
    assert [r.code for r in report.rows] == [
        "C0", "C2", "C4", "C6", "C7", "C8", "C9", "C10", "C12", "C13"]
    assert report.red == 0, [r.measured for r in report.rows if r.ok is False]
    assert report.readings == 1 and _row(report, "C9").ok is None
    assert report.passed == 9
    assert all(r.seconds >= 0 for r in report.rows)
    assert "快速体检 10 项" in report.summary() and "未通过 0" in report.summary()


def test_坏根键让_C13_点名(ctx, tmp_path) -> None:
    """C13 与 p12 同口径：`root_key` 必须等于 `identity_key(root_key)`。

    坏法注入（真跑过）：把 `_c13` 里的 `identity_key(row["root_key"]) != row["root_key"]`
    换成 `False` → 本条红在「C13 仍是绿」。
    """
    root = ctx.register_root(tmp_path / "监测目录")
    conn = ctx.engine.thread_connection()
    conn.execute("UPDATE monitored_roots SET root_key='不是身份键' WHERE root_key=?",
                 (root.root_key,))
    conn.commit()

    report = ctx.db_check.run(QUICK)
    c13 = _row(report, "C13")
    assert c13.ok is False, c13.measured
    assert "root_key 不等于 identity_key" in c13.measured, c13.measured
    assert "不是身份键" in c13.measured, "红行的例子要带出坏值，否则用户不知道该改哪一行"


def test_全库档把零字节快照判红且只跑最新一份整库体检(ctx) -> None:
    """C11 与 p12 同口径：0 字节快照是"坏"，不是"跳过"。

    坏法注入（真跑过）：把 `_c11` 里 `if size == 0: bad.append(...)` 这段删掉 →
    这份快照会落进 `snapshot_version` 抛 `DatabaseError`，红行文案变成「打不开」而不是
    「是 0 字节」；本条按文案点名，两种红都拦得住。
    """
    ctx.paths.backups_dir.mkdir(parents=True, exist_ok=True)
    broken = ctx.paths.backups_dir / "catalog-坏快照-v0.db"
    broken.write_bytes(b"")

    report = ctx.db_check.run(FULL)
    assert report.total == 13, f"全库档该有 13 项：{[r.code for r in report.rows]}"
    assert [r.code for r in report.rows][-1] == "C11", "最慢的 C11 要收尾，让前十二条先出结论"
    c11 = _row(report, "C11")
    assert c11.ok is False, c11.measured
    assert "是 0 字节" in c11.measured, c11.measured
    assert "只跑最新一份" in c11.measured, c11.measured


def test_上次体检只落盘六个键(ctx) -> None:
    """4甲：明细不落盘。键集合相等 —— 多存一条 measured 也算违约。"""
    ctx.db_check.run(QUICK)
    payload = ctx.app_settings.get(LAST_KEY)
    assert isinstance(payload, dict), payload
    assert set(payload) == {"ts", "mode", "total", "red", "readings", "elapsed_s"}, payload
    assert payload["mode"] == QUICK and payload["total"] == 10 and payload["red"] == 0
    assert abs(int(payload["ts"]) - int(time.time())) < 120, "ts 得是本次起跑的时刻"


def test_体检的异常会变成红行而不是带走整场(ctx, monkeypatch) -> None:
    """一条查不动，其余照跑；原文（类型 + 消息）必须回到那一行。"""
    def boom():
        raise RuntimeError("模拟一条读不动的查询")

    monkeypatch.setattr(ctx.db_check, "_c2", boom)
    report = ctx.db_check.run(QUICK)
    c2 = _row(report, "C2")
    assert c2.ok is False and "RuntimeError" in c2.measured and "模拟" in c2.measured
    assert report.total == 10 and report.red == 1


def test_没跑起来的体检也给原文() -> None:
    """`failure_report` 不是"失败了"三个字：类型与消息都要在读数格上。"""
    report = DbCheckService.failure_report(QUICK, RuntimeError("库被占用"))
    assert report.total == 1 and report.red == 1
    assert "RuntimeError: 库被占用" in report.rows[0].measured


# ---------------------------------------------------------------------------
# 1甲 面板接线（offscreen 真控件）
# ---------------------------------------------------------------------------

def _wait_report(qapp, panel, timeout: float = 60.0) -> None:
    deadline = time.monotonic() + timeout
    while panel.running and time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(0.01)
    qapp.processEvents()
    assert not panel.running, "体检没在超时内结束 —— 后台线程卡住或信号没回主线程"


def test_设置页里翻页跑快速体检并回写上次读数(window, qapp) -> None:
    """完整一条用户路径：设置页 → 库体检 → 快速体检 → 10 行读数 → 上次体检行更新 → 返回。

    坏法注入（真跑过）：把 `health_panel.finished` 的连接删掉 → 「上次体检」行停在
    「还没有跑过」，本条红在那一句；把 `_fill` 的 `setRowCount(len(report.rows))` 注成 0 →
    表格停在 0 行，本条红在行数。
    """
    window._select_by_page_id("monitor")
    for _ in range(6):
        qapp.processEvents()
    page = window._pages["monitor"]
    assert page.isVisible(), "用例前提：S7 得是当前可见页"

    assert page.lower_stack.currentWidget() is page.settings_view
    assert "还没有跑过" in page.health_panel.last_check_label.text(), (
        page.health_panel.last_check_label.text())

    page.health_toggle_btn.click()
    for _ in range(6):
        qapp.processEvents()
    assert page.lower_stack.currentWidget() is page.health_panel, "点「库体检…」没翻页"
    assert page.lower_title.text() == "库体检"
    assert "返回设置" in page.health_toggle_btn.text()
    assert page.health_panel.isVisible(), "翻页后体检面板不可见"

    page.health_panel.quick_btn.click()
    assert not page.health_panel.quick_btn.isEnabled(), "跑起来之后两颗按钮都要禁用"
    _wait_report(qapp, page.health_panel)

    assert page.health_panel.table.rowCount() == 10
    assert page.health_panel.table.item(0, 0).text().startswith("C0 ")
    assert page.health_panel.table.item(0, 2).toolTip(), "读数格必须挂 tooltip（长文本要能回读）"
    assert "快速体检 10 项" in page.health_panel.status_label.text()
    assert page.health_panel.quick_btn.isEnabled() and page.health_panel.full_btn.isEnabled()

    assert "上次体检：" in page.health_panel.last_check_label.text()
    assert "快速体检" in page.health_panel.last_check_label.text(), (
        page.health_panel.last_check_label.text())
    assert "还没有跑过" not in page.health_panel.last_check_label.text(), (
        "完成后面板没把结束信号接回设置页")
    assert _mode_is_quick(window)

    page.health_toggle_btn.click()
    for _ in range(6):
        qapp.processEvents()
    assert page.lower_stack.currentWidget() is page.settings_view
    assert page.lower_title.text() == "监测与索引"


def _mode_is_quick(window) -> bool:
    return window.ctx.app_settings.get(LAST_KEY, {}).get("mode") == QUICK


def test_全库档的确认框先给成本(window) -> None:
    """2甲：全库档是真慢动作，按钮上要写明时长，点下去先问一次。

    钉的是**读数都在**（**ISSUES I110** 丙）：安静档四项（C1 18 分 16 秒 / C5 22 分 23 秒 /
    C11 19 分 16 秒 / C4 3 分 40 秒）与「合计约 64 分钟」，加上界面里那两场（26 分 58 秒 / 56 分 30 秒），
    并明说跨度没定位、点下去按本机上次实测报。
    只留「57–67 分钟」那种准点数就是回到被自家读数打破的老写法 —— 原先这里断言的正是那两个数。
    """
    window._select_by_page_id("monitor")
    page = window._pages["monitor"]
    page.show_health()
    for where in (page.health_panel.cost_label.text(), page.health_panel.full_btn.toolTip()):
        assert "26 分 58 秒" in where and "56 分 30 秒" in where, where
        assert "18 分 16 秒" in where and "22 分 23 秒" in where, where
        assert "19 分 16 秒" in where and "3 分 40 秒" in where, where
        assert "合计约 64 分钟" in where, where
        assert "57 分钟" in where and "67 分钟" in where, where
        assert "跨度没定位" in where, where
        assert "按本机上次实测报" in where, where
        assert "不可中断" in where, where
        assert "**" not in where, where
    assert "约 12 秒" in page.health_panel.quick_btn.toolTip()


def test_确认框的时长回读本机上次实测(window) -> None:
    """I110 丙：点下去那一句里的时长来自 `db_check.last.elapsed_s`，不是文案里的第四个数。

    坏法注入（真跑过）：把 `full_confirm_text` 改成只回 `FULL_COST`（不读记录）→ 本条红在
    「上次在本机本库实测」；把 `last_full_elapsed` 里 `mode != FULL` 那道闸删掉 → 本条红在
    「快速档那 12 秒被当成全库档的时长」。
    """
    window._select_by_page_id("monitor")
    page = window._pages["monitor"]
    page.show_health()

    window.ctx.app_settings.set(LAST_KEY, {"ts": 1, "mode": FULL, "total": 13, "red": 0,
                                           "readings": 1, "elapsed_s": 1618.2}, kind="ui")
    body = page.health_panel.full_confirm_text()
    assert "上次在本机本库实测：26 分 58 秒" in body, body
    assert "本机还没有全库档的实测读数" not in body, body

    window.ctx.app_settings.set(LAST_KEY, {"ts": 1, "mode": QUICK, "total": 10, "red": 0,
                                           "readings": 1, "elapsed_s": 12.3}, kind="ui")
    body = page.health_panel.full_confirm_text()
    assert "本机还没有全库档的实测读数" in body, body
    assert "12 秒" not in body, "快速档的时长不能出现在全库档确认框里冒充实测"


def test_上次实测只认能用的记录(ctx) -> None:
    """`last_full_elapsed` 的闸：没记录 / 档位不对 / 值不是数 / 数是 0，一律回 None 而不是 0。"""
    assert last_full_elapsed(ctx.app_settings) is None, "没跑过时必须是 None，界面才有「没有读数」可说"
    ctx.app_settings.set(LAST_KEY, {"ts": 1, "mode": FULL, "elapsed_s": 1618.2}, kind="ui")
    assert last_full_elapsed(ctx.app_settings) == 1618.2
    for bad in ({"ts": 1, "mode": QUICK, "elapsed_s": 12.3},
                {"ts": 1, "mode": FULL},
                {"ts": 1, "mode": FULL, "elapsed_s": "不是数"},
                {"ts": 1, "mode": FULL, "elapsed_s": 0.0},
                "不是字典"):
        ctx.app_settings.set(LAST_KEY, bad, kind="ui")
        assert last_full_elapsed(ctx.app_settings) is None, bad
