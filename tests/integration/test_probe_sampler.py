"""P13 采样器的两条守卫：传感器自己失灵时，读数必须说清"是我瞎了"，而不是伪装成产品坏/产品好。

2026-10-21 轮十七的整链真踩过两次，同时发生：

1. `.venv` 的 `python.exe` 启动壳先退，旧 `Sampler._loop` 里的
   `root.children(recursive=True)` 抛 NoSuchProcess，采样线程静默结束 → **0 个采样点**，
   S3/S4/S5 全变成"没有读数"。
2. p13 在探针进程里跑过 `bootstrap()`，它装的应用级 excepthook 没还回去 → 上面那个
   NoSuchProcess 被写进了**被测应用**的 `crash.log`（2,127 字节），S2 假红。

这里用两个真进程把两种坏法钉住：启动壳退出后要能靠现场标记找回真身；探针的钩子与
handler 用过必须原样还回去（否则下一条线程异常又会写进被测进程的证据里）。
"""
from __future__ import annotations

import logging
import subprocess
import sys
import threading
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def _p13():
    sys.path.insert(0, str(REPO / "tests" / "probes"))
    import p13_soak

    return p13_soak


def _kill_by_marker(marker: str) -> None:
    import psutil

    for p in psutil.process_iter(["pid", "cmdline"]):
        try:
            cmdline = p.info.get("cmdline") or []
            if any(marker in str(part) for part in cmdline):
                p.kill()
        except psutil.Error:
            continue


def test_sampler_follows_real_child_after_launcher_exits(tmp_path):
    """启动壳（Popen 的 pid）退出后，采样要从命令行里的现场标记继续采到真子进程。

    坏法：把 `_live_tree` 的 marker 分支删掉 / 只认 Popen pid —— 采样点数变 0，本条红。
    """
    p13_soak = _p13()
    marker = str(tmp_path / "data_root")
    launcher = subprocess.Popen([
        sys.executable, "-c",
        "import subprocess,sys,time\n"
        "subprocess.Popen([sys.executable,'-c','import time; time.sleep(8)',sys.argv[1]])\n"
        "time.sleep(0.2)\n",
        marker,
    ])
    try:
        launcher.wait(timeout=10)
        sampler = p13_soak.Sampler(launcher, interval=0.2, marker=marker).start()
        time.sleep(1.2)
        samples = sampler.stop()
    finally:
        _kill_by_marker(marker)

    assert samples, f"启动壳退出后一个采样点都没拿到：{sampler.errors}"
    assert not sampler.errors, sampler.errors
    assert all(int(s["pids"]) >= 1 for s in samples)
    assert all(float(s["rss_mib"]) > 0 for s in samples)


def test_sampler_reports_missing_process_instead_of_empty_readout(tmp_path):
    """进程整棵都不在时：errors 要留原文，三个空读数要说"没采到点"，不许说成"非 Windows"。

    坏法：把 `_loop` 的顶层 except 去掉（线程静默死）或把 S4 的空读数文案改回
    "本机 psutil 没有 num_handles 读数（非 Windows）" —— 本条红。
    """
    p13_soak = _p13()
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(0.1)"])
    proc.wait(timeout=10)

    sampler = p13_soak.Sampler(proc, interval=0.1, marker=str(tmp_path / "absent")).start()
    deadline = time.monotonic() + 5.0
    while not sampler.errors and time.monotonic() < deadline:
        time.sleep(0.1)
    samples = sampler.stop()

    assert samples == []
    assert sampler.errors and sampler.errors[0].startswith("NoSuchProcess"), sampler.errors
    for row in (p13_soak.v_threads(samples), p13_soak.v_handles(samples), p13_soak.v_memory(samples)):
        assert not row.ok
        assert "采样点" in row.measured, row.measured
    assert "非 Windows" not in p13_soak.v_handles(samples).measured


def test_probe_bootstrap_restores_hooks_and_handlers(tmp_path):
    """探针里 bootstrap 一次之后，excepthook 与日志 handler 都必须回到原样。

    坏法：删掉 `_bootstrap_and_seed` 的 finally 恢复块 —— 钩子身份不相等，本条红；
    同时下一次采样线程异常会再写进被测应用的 crash.log（轮十七的 S2 假红就是它）。
    """
    p13_soak = _p13()
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    data_root = tmp_path / "data_root"
    before = (sys.excepthook, threading.excepthook)

    p13_soak._bootstrap_and_seed(data_root, corpus)

    assert (sys.excepthook, threading.excepthook) == before
    owned = [h for h in logging.getLogger("pdfarchiver").handlers
             if getattr(h, "_pdfarchiver_owned", False)]
    assert not owned, "探针还留着写向被测日志目录的 handler"
    assert not (data_root / "logs" / "crash.log").exists()
