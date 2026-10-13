"""P8 打包冒烟：把"最小但真实的依赖组合"冻成 exe 并运行一次。

目的不是交付安装包（那是阶段 7），而是提前证伪：如果 PySide6 6.8.3 + PyMuPDF + onnxruntime-directml
在 PyInstaller 下根本打不出能跑的东西，阶段 7 才发现就太晚了（SPEC 阶段 0 明确要求验证打包方案兼容性）。

做法：造一个真调用这三个库的入口脚本 -> PyInstaller --onedir -> 直接运行生成的 exe -> 断言 stdout 出现真实版本号。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time

ENTRY = ".probe_work/p8_app/entry.py"
SPEC_DIR = ".probe_work/p8_app"
APP_NAME = "p8smoke"
ENTRY_SRC = '''
import sys

def main() -> int:
    out = {}
    try:
        import pymupdf
        out["pymupdf"] = pymupdf.__version__
        d = pymupdf.open()
        d.new_page().insert_text((72, 100), "frozen ok 中文")
        out["pdf_pages"] = d.page_count
        d.close()
    except Exception as e:
        out["pymupdf_error"] = f"{type(e).__name__}: {e}"
    try:
        import onnxruntime as ot
        out["onnxruntime"] = ot.__version__
        out["providers"] = ",".join(ot.get_available_providers())
    except Exception as e:
        out["ort_error"] = f"{type(e).__name__}: {e}"
    try:
        import sqlite3
        c = sqlite3.connect(":memory:")
        c.execute("CREATE VIRTUAL TABLE t USING fts5(body, tokenize='trigram')")
        c.execute("INSERT INTO t(body) VALUES ('人工智能产业报告')")
        cur = c.execute("SELECT count(*) FROM t WHERE t MATCH ?", ('"人工智能"',))
        out["fts5_trigram_hits"] = cur.fetchone()[0]
        out["sqlite"] = sqlite3.sqlite_version
    except Exception as e:
        out["sqlite_error"] = f"{type(e).__name__}: {e}"
    try:
        from PySide6 import QtCore, QtWidgets
        out["qt"] = QtCore.qVersion()
        app = QtWidgets.QApplication(sys.argv[:1])
        w = QtWidgets.QLabel("冻结后的中文界面")
        w.show()
        app.processEvents()
        out["widget_created"] = True
    except Exception as e:
        out["qt_error"] = f"{type(e).__name__}: {e}"
    print("SMOKE_JSON " + __import__("json").dumps(out, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
'''


def run(cmd: list[str], env: dict | None = None, timeout: int = 1800) -> tuple[int, str]:
    e = dict(os.environ)
    if env:
        e.update(env)
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=e, encoding="utf-8", errors="replace")
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except subprocess.TimeoutExpired:
        return 124, "TIMEOUT"
    except Exception as exc:  # noqa: BLE001
        return 125, f"{type(exc).__name__}: {exc}"


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    os.makedirs(os.path.dirname(ENTRY), exist_ok=True)
    open(ENTRY, "w", encoding="utf-8").write(ENTRY_SRC)
    rep: dict = {"entry": ENTRY, "pyinstaller": run([sys.executable, "-m", "PyInstaller", "--version"])[1].strip()}

    t0 = time.perf_counter()
    code, log = run([
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onedir",
        "--name", APP_NAME, "--distpath", f"{SPEC_DIR}/dist", "--workpath", f"{SPEC_DIR}/build",
        "--specpath", SPEC_DIR, "--hidden-import", "PySide6.QtPdf", ENTRY,
    ])
    rep["build_exit"] = code
    rep["build_seconds"] = round(time.perf_counter() - t0, 1)
    rep["build_errors"] = [ln for ln in log.splitlines() if "ERROR" in ln][:12]
    rep["build_tail"] = log.strip().splitlines()[-3:] if log.strip() else []

    exe = os.path.join(SPEC_DIR, "dist", APP_NAME, f"{APP_NAME}.exe")
    rep["exe_exists"] = os.path.exists(exe)
    if rep["exe_exists"]:
        d = os.path.dirname(exe)
        rep["dist_dir_mb"] = round(sum(
            os.path.getsize(os.path.join(dp, fn)) for dp, _, fs in os.walk(d) for fn in fs
        ) / 1048576, 1)
        t1 = time.perf_counter()
        c2, out2 = run([exe], env={"QT_QPA_PLATFORM": "offscreen"}, timeout=180)
        rep["run_exit"] = c2
        rep["run_seconds"] = round(time.perf_counter() - t1, 2)
        rep["run_stdout"] = out2.strip().splitlines()[-6:]
        payload = None
        for ln in out2.splitlines():
            if ln.startswith("SMOKE_JSON "):
                try:
                    payload = json.loads(ln[len("SMOKE_JSON "):])
                except json.JSONDecodeError:
                    pass
        rep["smoke"] = payload
    with open(".probe_work/p8_packaging_result.json", "w", encoding="utf-8") as fh:
        json.dump(rep, fh, ensure_ascii=False, indent=2)

    sm = rep.get("smoke") or {}
    checks = [
        ("PyInstaller 能装并能跑完一次冻结", rep["build_exit"] == 0),
        ("产物 exe 存在", rep["exe_exists"]),
        ("冻结后的 exe 能启动并打出真实版本（不是开发机才能跑）", rep.get("run_exit") == 0 and bool(sm)),
        ("冻结后 PyMuPDF 仍能建 PDF", sm.get("pdf_pages") == 1),
        ("冻结后 FTS5 trigram 仍能建索引并命中中文", sm.get("fts5_trigram_hits") == 1),
        ("冻结后 onnxruntime 仍列出 providers（OCR/嵌入没被打包打断）", bool(sm.get("providers"))),
        ("冻结后 PySide6 仍能建窗口", sm.get("widget_created") is True),
        ("没有 ERROR 级别的打包日志", not rep["build_errors"]),
    ]
    for label, ok in checks:
        print(f"  {'PASS' if ok else 'FAIL'}  {label}")
    print("  INFO pyinstaller: " + rep["pyinstaller"])
    print("  INFO build: exit=%s seconds=%s distMB=%s" % (rep["build_exit"], rep["build_seconds"], rep.get("dist_dir_mb")))
    if rep["build_errors"]:
        print("  INFO build_errors: " + json.dumps(rep["build_errors"], ensure_ascii=False)[:600])
    print("  INFO smoke: " + json.dumps(sm, ensure_ascii=False))
    print("VERDICT: " + ("ALL GREEN" if all(ok for _, ok in checks) else "RED"))
    return 0 if all(ok for _, ok in checks) else 1


if __name__ == "__main__":
    sys.exit(main())
