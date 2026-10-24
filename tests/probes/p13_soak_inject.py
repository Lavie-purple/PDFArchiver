"""p13 的反向注入自检 —— 从 `p13_soak.py` 拆出的注入段（拆分时那份已 794 行，距 800 红线 6 行）。

入口仍在 p13：`python tests/probes/p13_soak.py --inject`，`main()` 里延迟导入本模块。
每条坏法都是"能骗过对应判据的写法"，逐条喂给判据函数看它会不会红 —— 红 = 断言有约束力，
不红 = 这条判据是摆设，按 AGENTS.md 直接删或改写。

为什么 `from p13_soak import …` 不成环：p13 顶层从不反向 import 本模块，只在 `main()` 里延迟
导入；本模块运行时 p13 已经定义完。p13 作为 `__main__` 跑时这里会把同一份代码再导入一次
（模块名 `p13_soak`），两边没有可变状态，用的是同一套判据函数。
"""
from __future__ import annotations

import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from p13_soak import (  # noqa: E402
    SAMPLE_SECONDS,
    Row,
    log,
    v_alive,
    v_backlog,
    v_consistency,
    v_docs_match,
    v_handles,
    v_logs,
    v_memory,
    v_no_crash,
    v_threads,
)


def inject() -> int:
    """每条判据喂一份**真实存在的坏法**，要求它变红。不会变红的断言直接删（AGENTS.md）。

    坏法不是凭空写的假数：每一类的来源都在注释里（哪一种真实故障会产出这样的读数）。
    """
    good_samples = [{"t": i * SAMPLE_SECONDS, "rss_mib": 300.0 + (i % 3),
                     "cpu": 1.0, "threads": 5, "handles": 700} for i in range(60)]
    bad: list[tuple[Row, str]] = []

    # 坏法 1：进程被 --exit-after 之外的原因杀掉（退出码非 0）→ S1 必须红
    bad.append((v_alive(2, good_samples, 120.0, []),
                "启动失败退出码 2 —— 真实成因：装配抛异常（bootstrap 返回 EXIT_BOOTSTRAP_FAILED）"))
    # 坏法 1b：采样点数达标，但中间睡了 60 秒 → S1 必须红（真实成因：2026-10-22 那场 2 小时
    #           soak，本机休眠 36.2 + 13.7 分钟，采样却只剩空洞两侧的点，差点被当成连续观测）
    holey = [{"t": i * SAMPLE_SECONDS, "rss_mib": 300.0, "cpu": 1.0,
              "threads": 5, "handles": 700}
             for i in range(350) if not 120 <= i < 150]
    bad.append((v_alive(0, holey, 700.0, []),
                "本机休眠 60s：采样 320 点仍过数量线，但中间有 62s 空洞"))
    # 坏法 2：crash.log 有内容 → S2 必须红（真实成因：worker 线程里没接住的异常）
    bad.append((v_no_crash(1024, 3, "Traceback (most recent call last): ..."),
                "crash.log 1024 字节 + 3 处 Traceback"))
    # 坏法 3：线程数从 5 涨到 12 → S3 必须红（真实成因：watchdog observer 每次重建没拆旧的，I5/I19）
    leak_threads = [dict(s, threads=5 + min(7, int(s["t"] / 20))) for s in good_samples]
    bad.append((v_threads(leak_threads), "线程数随时间线性增长到 12"))
    # 坏法 4：句柄从 700 涨到 1400 → S4 必须红（真实成因：每页出图新开连接不关）
    leak_handles = [dict(s, handles=700 + int(s["t"] * 6)) for s in good_samples]
    bad.append((v_handles(leak_handles), "句柄数一路上涨到 1400"))
    # 坏法 5：RSS 一路上涨 400MiB → S5 必须红（真实成因：I21 提到的推理资源不回收）
    leak_rss = [dict(s, rss_mib=300.0 + s["t"] * 3.4) for s in good_samples]
    bad.append((v_memory(leak_rss), "RSS 一路上涨约 400MiB"))
    # 坏法 6：内存峰值越过 G8 红线 → S5 必须红（真实成因：I16 的 OCR 峰值 806–1,131MiB 再叠 UI）
    fat = [dict(s, rss_mib=min(1250.0, 300.0 + s["t"] * 8)) for s in good_samples]
    bad.append((v_memory(fat), "RSS 峰值 1,250MiB 越过 G8 1,200MiB"))
    # 坏法 7：队列一直有 queued → S6 必须红（真实成因：处理器缺 dispatch，observer 线程死掉，I19）
    bad.append((v_backlog(False, 95.0, {"queued": 41}, peak_open=41), "120 条里 41 条始终 queued"))
    # 坏法 7b：传感器瞎了 → S6 必须红，而且读数要说"读不到"，不能只说"没排空"。
    #          这条不是纸面上的坏法 —— 2026-10-15 第一轮真 soak 就是这么红的：
    #          backlog() 抄错表名（`jobs`，真表 `processing_jobs`），46 秒里每次读库都抛异常被吞掉。
    bad.append((v_backlog(False, 46.1,
                          {"_读库失败": "OperationalError: no such table: jobs"}),
                "表名抄错，S6 全程一次都没读到队列"))
    # 坏法 7c：从未观测到积压却"秒排空" → S6 必须红（未验）。
    #          真实形状：2026-10-21 轮十七 r17c，`0.0s {'done': 88}` —— 停投放时队列本来就是空的，
    #          排空逻辑一次都没被走到。种入积压前的旧版就是这么绿的。
    bad.append((v_backlog(True, 0.0, {"done": 88}, peak_open=0),
                "队列全程非终态为空，0.0s 的排空是空转（轮十七真实读数）"))
    # 坏法 8：盘上 30 份库里只有 12 份 → S7 必须红（真实成因：事件丢了且周期校验还没到，I5/I6）
    #         坏法 9：轮转份数超过 keep+1 → S8 必须红（真实成因：handler 没装 rotation）
    #         这两条要真的连库、真的建文件，所以下面现场造。
    # 坏法 10：p12 输出里有"未验"→ S9 必须红（真实成因：跑的时候应用还开着，或快照目录口径错，I27）
    bad.append((v_consistency(1, "未验 C11 —— backups/ 里一份快照都没有"),
                "p12 判未验（I27 的真实坏法）"))

    caught = 0
    for row, why in bad:
        mark = "红" if not row.ok else "绿（← 这条断言没有牙）"
        log(f"  {mark}  {row.gate}\n        坏法：{why}\n        读数：{row.measured}")
        if not row.ok:
            caught += 1

    # 坏法 8/9 需要真文件系统与真库，这里现场造，确保不是"纸面上的坏法"；
    # 同时每条判据都配一份**好读数**，证明判据不是"恒红"—— 恒红的探针和恒红的断言一样没用。
    with tempfile.TemporaryDirectory(prefix="p13_inject_") as td:
        root = Path(td)
        (root / "data").mkdir(parents=True)
        conn = sqlite3.connect(root / "data" / "catalog.db")
        conn.execute("CREATE TABLE documents (path TEXT, missing_since INTEGER)")
        conn.executemany("INSERT INTO documents VALUES (?, NULL)", [("p",)] * 12)
        conn.commit()
        conn.close()
        extra = [(v_docs_match(root, 30), "盘上 30 份库里只有 12 份（I5/I6 的真实后果）"),
                 (v_logs(_mk_logs(root, "leaky", 9), 5, 5000), "轮转份数 9 > keep+1（handler 没装轮转）")]
        good = [v_docs_match(root, 12),
                v_logs(_mk_logs(root, "neat", 6), 5, 5000),
                v_backlog(True, 12.0, {"done": 68, "failed": 3}, peak_open=41),
                v_alive(0, good_samples, 120.0, [])]
        for row, why in extra:
            log(f"  {'红' if not row.ok else '绿（← 这条判据没有牙）'}  {row.gate}\n"
                f"        坏法：{why}\n        读数：{row.measured}")
            if not row.ok:
                caught += 1
        for row in good:
            log(f"  {'绿（好读数正确放行）' if row.ok else '红（← 判据恒红，不能用）'}  {row.gate}\n"
                f"        读数：{row.measured}")

    total = len(bad) + len(extra)
    good_passed = sum(1 for r in good if r.ok)
    log(f"注入自检：抓到 {caught}/{total} 条坏法｜好读数放行 {good_passed}/{len(good)}")
    if caught != total or good_passed != len(good):
        log("VERDICT: RED（有坏法骗过判据）")
        return 1
    log("VERDICT: ALL GREEN")
    return 0


def _mk_logs(root: Path, name: str, how_many: int) -> Path:
    """在独立子目录里造出 `how_many` 份 app.log 轮转文件（每份都要独占目录，
    否则"好读数"那次会看见上一次留下的文件，判据恒红 —— 注入自检第一跑就踩了这个）。"""
    logs = root / name
    logs.mkdir(parents=True, exist_ok=True)
    for i in range(how_many):
        (logs / ("app.log" if i == 0 else f"app.log.{i}")).write_text("x" * 1024, encoding="utf-8")
    return logs


# ───────────────────────────── 主流程 ─────────────────────────────
