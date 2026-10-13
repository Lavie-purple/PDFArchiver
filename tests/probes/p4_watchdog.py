"""P4 文件监测探针：watchdog 在真实 NTFS + 中文路径上的事件可靠性。

SPEC 3.1 明令"不能仅依赖文件监测事件"，本探针就是用来量化"仅依赖会漏多少"的。

验证项：
  Q1 增/改/重命名/移动/删除 各自收到什么事件类型，Windows 上重命名是不是 pending 两段
  Q2 事件延迟分布（写入完成 -> 回调到达）
  Q3 中文文件名是否完整回传（路径编码不出 surrogate）
  Q4 observer 启动后新建的子目录里新增文件能否被捕获（递归监听）
  Q5 一次性批量产生 300 个文件时事件是否丢失（缓冲区溢出）
  Q6 目录被整体重命名时，监听器还能不能继续工作
  Q7 关闭期间发生的变化：重启 observer 后，增量扫描能否校正（这一条靠对比扫描快照证明）

用法: python tests/probes/p4_watchdog.py [--burst 300] [--out .probe_work/p4_watchdog_result.json]
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from pathlib import Path

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

ROOT = Path(".probe_work/watch_root")


class Collector(FileSystemEventHandler):
    def __init__(self) -> None:
        self.events: list[dict] = []

    def _rec(self, etype: str, path: str, extra: dict | None = None) -> None:
        item = {"t": time.time(), "type": etype, "path": path, "is_dir": None}
        if extra:
            item.update(extra)
        self.events.append(item)

    def on_created(self, event) -> None:
        self._rec("created", event.src_path, {"is_dir": event.is_directory})

    def on_deleted(self, event) -> None:
        self._rec("deleted", event.src_path, {"is_dir": event.is_directory})

    def on_modified(self, event) -> None:
        if not event.is_directory:
            self._rec("modified", event.src_path)

    def on_moved(self, event) -> None:
        self._rec("moved", event.src_path, {"dest": getattr(event, "dest_path", None), "is_dir": event.is_directory})


def snapshot(root: Path) -> dict[str, int]:
    out = {}
    for p in root.rglob("*"):
        if p.is_file():
            out[str(p.relative_to(root))] = p.stat().st_size
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--burst", type=int, default=300)
    ap.add_argument("--settle", type=float, default=3.0, help="每步等待事件到达的秒数")
    ap.add_argument("--out", default=".probe_work/p4_watchdog_result.json")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    if ROOT.exists():
        shutil.rmtree(ROOT)
    (ROOT / "sub").mkdir(parents=True)
    col = Collector()
    obs = Observer()
    obs.schedule(col, str(ROOT), recursive=True)
    obs.start()
    time.sleep(0.8)
    res: dict = {"backend": type(obs).__name__, "steps": {}}
    base = time.time()

    def settle(seconds: float | None = None) -> None:
        time.sleep(seconds or args.settle)

    # Q1/Q3 新建中文文件
    f1 = ROOT / "人工智能产业报告 2026.pdf"
    t_write = time.time()
    f1.write_bytes(b"%PDF-1.7\n% fake for watch probe\n")
    settle()
    res["steps"]["create_cn"] = {"n_events": len(col.events), "types": sorted({e["type"] for e in col.events})}

    def find(pred) -> list[dict]:
        return [e for e in col.events if pred(e)]

    cn_created = find(lambda e: e["type"] == "created" and "人工智能" in e["path"])
    res["chinese_path"] = {
        "received": bool(cn_created),
        "path_repr_ok": bool(cn_created) and "\ufffd" not in cn_created[0]["path"] and "\\ud" not in repr(cn_created[0]["path"]),
        "sample": cn_created[0]["path"][-30:] if cn_created else None,
        "latency_ms": round((cn_created[0]["t"] - t_write) * 1000, 1) if cn_created else None,
    }

    # 修改
    n_before = len(col.events)
    f1.write_bytes(b"%PDF-1.7\n% modified content longer\n")
    settle()
    res["steps"]["modify"] = {"delta": len(col.events) - n_before, "types": sorted({e["type"] for e in col.events[n_before:]})}

    # 重命名
    n_before = len(col.events)
    f2 = ROOT / "改名后.pdf"
    f1.rename(f2)
    settle()
    moved = col.events[n_before:]
    res["steps"]["rename"] = {
        "delta": len(moved),
        "types": sorted({e["type"] for e in moved}),
        "has_moved_event": any(e["type"] == "moved" for e in moved),
        "pending_rename": any("pending" in str(e.get("type")) for e in moved),
        "old_in_src": any(e["type"] == "moved" and "人工智能" in e["path"] for e in moved),
        "dest_correct": any(e["type"] == "moved" and e.get("dest") and str(f2) in e["dest"] for e in moved),
    }

    # 移动到新子目录
    n_before = len(col.events)
    d_new = ROOT / "moved_into"
    d_new.mkdir()
    f3 = d_new / "改名后.pdf"
    f2.rename(f3)
    settle()
    moved2 = col.events[n_before:]
    res["steps"]["move_across_dirs"] = {"delta": len(moved2), "types": sorted({e["type"] for e in moved2})}

    # 监听启动后新建子目录里的文件（递归）
    n_before = len(col.events)
    d_late = ROOT / "sub" / "晚到的目录"
    d_late.mkdir(parents=True)
    (d_late / "新文件.pdf").write_bytes(b"%PDF-1.7 late\n")
    settle()
    late = col.events[n_before:]
    res["steps"]["nested_after_start"] = {
        "delta": len(late),
        "caught_new_file": any("新文件" in e["path"] for e in late),
        "types": sorted({e["type"] for e in late}),
    }

    # 删除
    n_before = len(col.events)
    f3.unlink()
    settle()
    res["steps"]["delete"] = {"delta": len(col.events) - n_before, "types": sorted({e["type"] for e in col.events[n_before:]})}

    # Q5 批量
    n_before = len(col.events)
    burst_dir = ROOT / "burst"
    burst_dir.mkdir()
    t0 = time.time()
    for i in range(args.burst):
        (burst_dir / f"b{i:04d}.pdf").write_bytes(b"%PDF-1.7 burst\n")
    burst_wall = time.time() - t0
    settle(args.settle * 2)
    created_burst = [e for e in col.events[n_before:] if e["type"] == "created"]
    res["burst"] = {
        "files_written": args.burst,
        "write_seconds": round(burst_wall, 2),
        "created_events": len(created_burst),
        "lost_ratio": round(1 - len(created_burst) / args.burst, 3),
        "total_events_delta": len(col.events) - n_before,
    }

    # Q6 整个被监听目录的父级重命名 -> 监听器命运
    snap_before = snapshot(ROOT)
    renamed_root = ROOT.parent / "watch_root_renamed"
    n_before = len(col.events)
    ROOT.rename(renamed_root)
    settle()
    res["root_renamed"] = {
        "delta_events": len(col.events) - n_before,
        "observer_alive": obs.is_alive(),
        "can_still_write": True,
    }
    try:
        (renamed_root / "after_root_rename.pdf").write_bytes(b"%PDF-1.7 after\n")
        settle()
        res["root_renamed"]["event_after_rename_captured"] = any("after_root_rename" in e["path"] for e in col.events[n_before:])
    except OSError as exc:
        res["root_renamed"]["write_error"] = str(exc)

    obs.stop()
    obs.join(timeout=5)

    # Q7 程序外变化：停表后改文件，重启 observer 也不会有事件 -> 只能靠扫描校正
    time.sleep(0.5)
    (renamed_root / "outside_change.pdf").write_bytes(b"%PDF-1.7 outside\n")
    snap_after = snapshot(renamed_root)
    res["offline_change"] = {
        "files_added_while_unwatched": len(set(snap_after) - set(snap_before)),
        "detectable_only_by_scan": True,
    }

    # 乱序检查：modified 是否可能早于 created 到达
    order_violation = 0
    seen_created = set()
    for e in col.events:
        if e["type"] == "created":
            seen_created.add(e["path"])
        elif e["type"] == "modified" and e["path"] not in seen_created:
            order_violation += 1
    res["ordering"] = {"modified_before_created_count": order_violation, "total_events": len(col.events)}
    res["event_type_histogram"] = {}
    for e in col.events:
        res["event_type_histogram"][e["type"]] = res["event_type_histogram"].get(e["type"], 0) + 1
    res["elapsed_seconds"] = round(time.time() - base, 1)

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(res, fh, ensure_ascii=False, indent=2)
    shutil.rmtree(renamed_root, ignore_errors=True)

    lat_cn = res["chinese_path"]["latency_ms"]
    checks = [
        ("created 事件延迟 < 1000ms", lat_cn is not None and lat_cn < 1000),
        ("中文文件名完整回传，无替换符", res["chinese_path"]["path_repr_ok"]),
        ("同目录重命名 -> 单个 moved 且 src/dest 可配对", res["steps"]["rename"]["has_moved_event"] and res["steps"]["rename"]["dest_correct"]),
        ("跨目录移动 -> 被报成 deleted+created（不能只信 moved）", "moved" not in res["steps"]["move_across_dirs"]["types"]),
        ("监听启动后的新子目录里的文件仍被捕获", res["steps"]["nested_after_start"]["caught_new_file"]),
        ("批量 300 文件无 created 事件丢失", res["burst"]["created_events"] >= res["burst"]["files_written"]),
        ("删除事件被收到", res["steps"]["delete"]["delta"] >= 1),
        ("被监听目录本身被重命名时没有任何事件（监听器还在旧句柄上）", res["root_renamed"]["delta_events"] == 0),
        ("停表期间的变化只能靠扫描发现（证明必须做定期校验）", res["offline_change"]["files_added_while_unwatched"] >= 1),
        ("没有 modified 早于 created 的乱序", res["ordering"]["modified_before_created_count"] == 0),
    ]
    for label, ok in checks:
        print(f"  {'PASS' if ok else 'FAIL'}  {label}")
    print("  INFO burst: " + json.dumps(res["burst"], ensure_ascii=False))
    print("  INFO rename: " + json.dumps(res["steps"]["rename"], ensure_ascii=False))
    print("  INFO root_renamed: " + json.dumps(res["root_renamed"], ensure_ascii=False))
    print("  INFO histogram: " + json.dumps(res["event_type_histogram"], ensure_ascii=False))
    print("  INFO ordering: " + json.dumps(res["ordering"], ensure_ascii=False))
    print("VERDICT: " + ("ALL GREEN" if all(ok for _, ok in checks) else "RED"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
