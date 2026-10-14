"""把产品冻成 exe，并当场做体积对账。

跑法：
    python packaging/build.py            # 干净重建（约 5–12 分钟，看机器闲不闲）
    python packaging/build.py --no-clean # 复用上次的 workpath，快一些

这条脚本只回答两个问题：
1. **打得出来吗** —— PyInstaller 退出 0、日志里没有 ERROR 行、exe 真存在，
   且**该进包的东西真进了包**（OCR 模型 / 推理 DLL / 迁移脚本，三样都是静态分析收不到的）。
2. **体积都花在哪** —— 逐项列出并做**分区求对账**：顶层各项之和必须等于整目录大小，
   `_internal` 明细之和必须等于 `_internal` 本身。对不上的意思是"有一项没被列出来"，
   那才是体积对账真正要防的事；至于"该多大"这种数字，SPEC 没给、p8 也没给结论，
   所以这里不写死阈值充数（AGENTS.md：不许编数据）。

`--windowed` 的产物没有 stdout，所以"跑起来对不对"不在这里验，在 `packaging/frozen_smoke.py`。
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SPEC = REPO / "packaging" / "PdfArchiver.spec"
DIST = REPO / "dist"
WORK = REPO / "build"
APP_DIR = DIST / "PdfArchiver"
EXE = APP_DIR / "PdfArchiver.exe"
INTERNAL = APP_DIR / "_internal"
REPORT = REPO / ".probe_work" / "packaging_build_report.json"
MB = 1024 * 1024


def _dir_size(path: Path) -> int:
    total = 0
    for dp, _, files in os.walk(path):
        for fn in files:
            try:
                total += os.path.getsize(os.path.join(dp, fn))
            except OSError:
                pass
    return total


def _tree_sizes(path: Path) -> list[tuple[str, int]]:
    """目录本身只算它直属的文件，子目录各自成一项 —— 这样各项之和才等于整棵树。"""
    own = sum(f.stat().st_size for f in path.iterdir() if f.is_file())
    out = []
    if own:
        out.append(("(本级文件)", own))
    for d in sorted((c for c in path.iterdir() if c.is_dir()), key=lambda p: p.name.lower()):
        out.append((d.name, _dir_size(d)))
    return out


def _machine_load() -> str:
    """构建耗时是负载绑定的读数，所以读数必须和成因放在一起打印（同 gates/stage5.py 的 D-033）。"""
    try:
        import psutil
        cpu = psutil.cpu_percent(interval=1.0)
        avail = round(psutil.virtual_memory().available / MB)
        return f"起跑负载：CPU {cpu}%｜可用内存 {avail}MiB"
    except Exception as exc:  # noqa: BLE001 - 读数加不上就少加，不改判定
        return f"起跑负载：取不到（{type(exc).__name__}: {exc}）"


def _ocr_expected() -> dict[str, bool]:
    """开发环境里装了可选层，产物就必须带着它 —— 用来把"包里没有 OCR"变成可判定的事。"""
    def installed(name: str) -> bool:
        probe = subprocess.run(
            [sys.executable, "-c", f"import importlib.util,sys;"
                                   f"sys.exit(0 if importlib.util.find_spec({name!r}) else 1)"],
            capture_output=True, text=True)
        return probe.returncode == 0
    return {"rapidocr": installed("rapidocr_onnxruntime"), "onnxruntime": installed("onnxruntime")}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--no-clean", action="store_true", help="不删上次 workpath/dist，加快重跑")
    args = ap.parse_args(argv)
    # 中文输出在 cmd 默认代码页下会变乱码，重跑一次也读不回来；这里直接钉 UTF-8
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    if not SPEC.is_file():
        print(f"FAIL  找不到 spec：{SPEC}")
        print("VERDICT: RED（1 条未过）")
        return 1

    os.makedirs(REPO / ".probe_work", exist_ok=True)
    if not args.no_clean:
        for stale in (APP_DIR, WORK / "PdfArchiver"):
            if stale.is_dir():
                import shutil
                shutil.rmtree(stale, ignore_errors=True)

    print(f"构建目录 {REPO}｜python {sys.version.split()[0]}")
    print(f"        {_machine_load()}")
    expected = _ocr_expected()

    cmd = [sys.executable, "-m", "PyInstaller"]
    if not args.no_clean:
        cmd.append("--clean")
    cmd += ["--noconfirm", "--distpath", str(DIST), "--workpath", str(WORK), str(SPEC)]
    t0 = time.perf_counter()
    proc = subprocess.run(cmd, cwd=str(REPO), capture_output=True, text=True,
                          encoding="utf-8", errors="replace",
                          env={**os.environ, "PYTHONIOENCODING": "utf-8"}, timeout=3600)
    build_seconds = round(time.perf_counter() - t0, 1)
    log_text = (proc.stdout or "") + (proc.stderr or "")
    error_lines = [ln.strip() for ln in log_text.splitlines() if "ERROR:" in ln or "ERROR " in ln]
    if proc.returncode != 0:
        # 失败得很快时（参数错、spec 语法错），不让人再手动重跑一遍才知道为什么
        print("PyInstaller 原文（末尾 20 行）：")
        for ln in [l for l in log_text.splitlines() if l.strip()][-20:]:
            print(f"  {ln}")

    checks: list[tuple[str, bool, str]] = []
    checks.append(("PyInstaller 退出码为 0", proc.returncode == 0,
                   f"exit={proc.returncode}｜用时 {build_seconds}s"))
    checks.append(("构建日志没有 ERROR 行", not error_lines,
                   "; ".join(error_lines[:3]) if error_lines else "0 条"))
    checks.append(("exe 真的存在", EXE.is_file(), str(EXE)))

    parts: list[tuple[str, int]] = []
    internal_detail: list[tuple[str, int]] = []
    total_bytes = 0
    if APP_DIR.is_dir():
        total_bytes = _dir_size(APP_DIR)
        parts = _tree_sizes(APP_DIR)
        if INTERNAL.is_dir():
            internal_bytes = _dir_size(INTERNAL)
            internal_detail = _tree_sizes(INTERNAL)
            detail_sum = sum(size for _, size in internal_detail)
            checks.append(("_internal 明细能对上 _internal 总大小", detail_sum == internal_bytes,
                           f"明细合计 {round(detail_sum / MB, 1)}MiB vs 实际 "
                           f"{round(internal_bytes / MB, 1)}MiB"))
        part_sum = sum(size for _, size in parts)
        checks.append(("顶层各项之和等于整包大小（体积对账）", part_sum == total_bytes,
                       f"各项合计 {round(part_sum / MB, 1)}MiB vs 整包 "
                       f"{round(total_bytes / MB, 1)}MiB"))

    if expected["rapidocr"]:
        models = list((INTERNAL / "rapidocr_onnxruntime" / "models").glob("*.onnx")) \
            if INTERNAL.is_dir() else []
        checks.append((f"开发环境装了 OCR，产物里就必须有识别模型（实测 {len(models)} 个）",
                       len(models) >= 3, ", ".join(m.name for m in models)))
    if expected["onnxruntime"]:
        capi = list((INTERNAL / "onnxruntime" / "capi").glob("*.dll")) \
            if (INTERNAL / "onnxruntime" / "capi").is_dir() else []
        checks.append((f"onnxruntime 的推理 DLL 进了包（实测 {len(capi)} 个）", bool(capi),
                       ", ".join(c.name for c in capi[:4])))

    # 发行包元数据（.dist-info）是第三样"静态分析收不到、缺了又不报错"的东西：
    # ocr/engine.py 的版本指纹走 importlib.metadata.version()，元数据不在包里就抛
    # PackageNotFoundError，而那条异常在产品里被解释成"这台机器没装 OCR"——
    # 于是冻结产物 import 得动模块、OCR 却整批 failed，构建报告那头的 rapidocr: True
    # 又是在 venv 里 import 成功的读数（两边都不算说谎，拼起来是假绿）。
    # 第二版冻结冒烟就是这么红的，原文：`OcrUnavailable: 可选 OCR 层没装：缺发行包 rapidocr-onnxruntime`。
    dist_infos = sorted(p.name for p in INTERNAL.glob("*.dist-info")) if INTERNAL.is_dir() else []
    _want = [d.lower().replace("_", "-") for d, on in
             (("rapidocr-onnxruntime", expected["rapidocr"]),
              ("onnxruntime-directml", expected["onnxruntime"])) if on]
    _have = {d.lower().replace("_", "-") for d in dist_infos}
    _miss = [d for d in _want if not any(h.startswith(d) for h in _have)]
    checks.append((f"OCR 版本指纹要读的 .dist-info 进了包（实测 {len(dist_infos)} 份）",
                   bool(_want) and not _miss,
                   f"包内 {[d for d in dist_infos if 'ocr' in d.lower() or 'onnx' in d.lower()][:4]}"
                   f"｜缺 {_miss or '无'}"))

    # 迁移脚本是**数据文件**，不在 PYZ 里：discover() 靠对目录 glob("*.py")。漏收的后果不是
    # "迁移报错"，而是"零迁移、静默成功"，然后应用在八丈远之外崩 —— 首版冻结产物就是这么起的不来，
    # 所以这里在打包当场就把包内清单和源目录清单对齐，而不是等冻结冒烟去撞。
    src_mig_dir = REPO / "src" / "pdfarchiver" / "db" / "migrations"
    bundled_mig_dir = INTERNAL / "pdfarchiver" / "db" / "migrations"
    src_migrations = sorted(p.name for p in src_mig_dir.glob("*.py") if not p.name.startswith("_"))
    bundled = sorted(p.name for p in bundled_mig_dir.glob("*.py")) if bundled_mig_dir.is_dir() else []
    checks.append(("迁移脚本按 .py 进了包，且与源目录清单一模一样",
                   bool(bundled) and bundled == src_migrations,
                   f"包内 {bundled or '（没有这个目录）'}｜源码 {src_migrations}"))

    report = {
        "build_seconds": build_seconds,
        "pyinstaller": subprocess.run([sys.executable, "-m", "PyInstaller", "--version"],
                                      capture_output=True, text=True).stdout.strip(),
        "exe": str(EXE),
        "total_mb": round(total_bytes / MB, 1),
        "top_level": {name: round(size / MB, 1) for name, size in parts},
        "internal_detail": {name: round(size / MB, 1) for name, size in internal_detail},
        "ocr_in_venv": expected,
        "build_error_lines": error_lines[:12],
        "machine_load": _machine_load(),
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n体积对账（整包 {round(total_bytes / MB, 1)} MiB，用时 {build_seconds}s）：")
    for name, size in parts:
        print(f"  {round(size / MB, 1):>9.1f} MiB  {name}")
    if internal_detail:
        print("  ── _internal 明细 ──")
        for name, size in sorted(internal_detail, key=lambda x: -x[1]):
            print(f"  {round(size / MB, 1):>9.1f} MiB  {name}")

    bad = []
    print()
    for label, ok, measured in checks:
        print(f"  {'PASS' if ok else 'FAIL'}  {label}")
        if not ok:
            bad.append(label)
        print(f"        {measured}")
    print(f"  INFO 报告已写出 {REPORT.relative_to(REPO)}")
    print("VERDICT: " + ("ALL GREEN" if not bad else f"RED（{len(bad)} 条未过）"))
    return 0 if not bad else 1


if __name__ == "__main__":
    raise SystemExit(main())
