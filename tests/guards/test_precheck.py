"""收尾预检脚本的接线守卫 —— 它自己坏了，整链就会重新变成第一道筛子。

背景（2026-10-24 轮二十三）：轮二十二整链 35 条判定里 3 条红全是自伤（裸探针名 ×2、
`--data-root` 传深一层 ×1），花整链量级的时间才发现。处置是把它们固化成
`scripts/precheck.py` 的两步。这里钉三件事：

1. 两步**都在**，且第一步是守卫全量、第二步是门禁的 `docs-inject` + `guards` 两段；
2. 任一步红 ⇒ 末行 `VERDICT: RED`、退出码 1、**不再往下跑**；
3. 只有两步全绿才 `ALL GREEN`、退出码 0。

坏法注入就是测试里的 `runner`：第 2 条喂一个恒红的假 runner（它替掉真实子进程，
所以这一步不跑门禁，2 秒内出结果），第 3 条喂恒绿的假 runner。真实 runner 的接线由
第 1 条按 argv 逐字断言 —— 只喂假 runner 会让「脚本根本没跑那两步」也变绿。
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def _load():
    path = REPO / "scripts" / "precheck.py"
    spec = importlib.util.spec_from_file_location("precheck_under_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_预检两步覆盖守卫全量与门禁两段() -> None:
    steps = _load().STEPS
    assert len(steps) == 2, f"预检步数变了：{[n for n, _ in steps]}"
    first, second = (" ".join(cmd) for _, cmd in steps)
    assert "pytest tests/guards" in first, first
    assert "--only docs-inject" in second and "--only guards" in second, second


def test_预检任一步红就判红并停住(capsys) -> None:
    mod = _load()
    calls: list[list[str]] = []

    def fake_red(cmd: list[str]) -> tuple[bool, str]:
        calls.append(cmd)
        return False, "假红：失效 .py 名字 46 > 上限 37"

    assert mod.main([], runner=fake_red) == 1
    out = capsys.readouterr().out
    assert "VERDICT: RED" in out, out
    assert "46 > 上限 37" in out, "红的现场必须上屏，否则修不了"
    assert len(calls) == 1, f"红了还继续跑：{len(calls)} 步"


def test_预检两步全绿才报全绿(capsys) -> None:
    mod = _load()
    assert mod.main([], runner=lambda cmd: (True, "ok")) == 0
    out = capsys.readouterr().out
    assert "VERDICT: ALL GREEN" in out, out
    assert "PASS  1/2" in out and "PASS  2/2" in out, out
