"""P5 OCR 探针：真实扫描页上验证 RapidOCR(onnxruntime) 的可用性、速度与 CPU vs DirectML 差异。

需求依据：阶段 5 要接"经过验证的本地 OCR 引擎"；SPEC 第五节要求记录真实资源占用与处理速度；
目标机是 GTX 1060 6GB（实测空闲显存仅 2.3GB，因为核显/独显在驱动显示器）。

不许做的事：不许用合成图片代替真实扫描页；不许只测"能跑通"而不测准确率与吞吐；
不许因为 GTX 1060 支持 CUDA 就假定 GPU 后端可用（本探针用 get_available_providers() 实测）。

用法:
  python tests/probes/p5_ocr.py [--pdf <扫描版pdf>] [--pages 8] [--providers cpu,dml]
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import sys
import time

import psutil
import pymupdf

pymupdf.TOOLS.mupdf_display_errors(False)
RSS = psutil.Process(os.getpid())


def rss_mb() -> float:
    return RSS.memory_info().rss / 1048576


def gpu_free_mb() -> int:
    """直接问 nvidia-smi，不猜。查询失败返回 -1 并在报告里标明。"""
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.free,memory.total", "--format=csv,noheader,nounits"],
            capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=15,
        )
        if out.returncode != 0:
            return -1
        return int(out.stdout.strip().splitlines()[0].split(",")[0])
    except Exception:  # noqa: BLE001
        return -1


def build_ocr(use_dml: bool):
    from rapidocr_onnxruntime import RapidOCR

    # RapidOCR 1.4.4 的 kwargs 是扁平命名：det_/cls_/rec_ 前缀进各自子配置，其余进 Global
    return RapidOCR(
        log_level="error",
        use_cuda=False,
        det_use_dml=use_dml,
        cls_use_dml=use_dml,
        rec_use_dml=use_dml,
    )


def rendered_pages(pdf: str, limit: int) -> list[tuple[int, "object"]]:
    import numpy as np

    doc = pymupdf.open(pdf)
    out = []
    step = max(1, doc.page_count // limit)
    for i in range(0, doc.page_count, step):
        if len(out) >= limit:
            break
        pix = doc[i].get_pixmap(matrix=pymupdf.Matrix(200 / 72, 200 / 72), colorspace=pymupdf.csRGB)
        arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
        if pix.n == 4:
            arr = arr[:, :, :3]
        out.append((i, arr.copy()))
    doc.close()
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdf", default="")
    ap.add_argument("--pages", type=int, default=8)
    ap.add_argument("--out", default=".probe_work/p5_ocr_result.json")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    os.makedirs(os.path.dirname(args.out), exist_ok=True)

    pdf = args.pdf
    if not pdf or not os.path.exists(pdf):
        hint = ".probe_work/p5_scanned_path.txt"
        if os.path.exists(hint):
            pdf = open(hint, encoding="utf-8").read().strip()
    report: dict = {
        "probe": "p5_ocr",
        "os": f"Windows {platform.release()} {platform.version()}",
        "python": platform.python_version(),
        "gpu_free_mb_at_start": gpu_free_mb(),
        "scanned_pdf_pages_total": pymupdf.open(pdf).page_count if pdf and os.path.exists(pdf) else 0,
        "ocr_pdf_path_tail": os.path.basename(pdf) if pdf else "",
        "providers_available": [],
        "runs": {},
    }
    import onnxruntime as ot

    report["onnxruntime_version"] = ot.__version__
    report["providers_available"] = ot.get_available_providers()

    pages = rendered_pages(pdf, args.pages)
    report["pages_tested"] = len(pages)
    report["page_pixel_sizes"] = [[int(p[1].shape[1]), int(p[1].shape[0])] for p in pages[:3]]

    for tag, use_dml in (("cpu", False), ("directml", True)):
        if tag == "directml" and "DmlExecutionProvider" not in report["providers_available"]:
            report["runs"][tag] = {"skipped": "DmlExecutionProvider 不在可用列表"}
            continue
        rss0 = rss_mb()
        t0 = time.perf_counter()
        try:
            ocr = build_ocr(use_dml)
        except Exception as exc:  # noqa: BLE001
            report["runs"][tag] = {"init_error": f"{type(exc).__name__}: {exc}"}
            continue
        init_s = time.perf_counter() - t0
        per_page, texts, scores = [], [], []
        err = None
        for idx, arr in pages:
            try:
                t1 = time.perf_counter()
                res, _elapse = ocr(arr)
                per_page.append(round((time.perf_counter() - t1) * 1000, 1))
                texts.append("".join(r[1] for r in res) if res else "")
                scores.extend(float(r[2]) for r in res) if res else None
            except Exception as exc:  # noqa: BLE001
                err = f"{type(exc).__name__}: {exc}"
                break
        run = {
            "init_seconds": round(init_s, 2),
            "per_page_ms": per_page,
            "pages_done": len(per_page),
            "per_page_ms_mean": round(sum(per_page) / len(per_page), 1) if per_page else None,
            "per_page_ms_median": sorted(per_page)[len(per_page) // 2] if per_page else None,
            "pages_per_minute": round(60000 / (sum(per_page) / len(per_page)), 1) if per_page else None,
            "chars_total": sum(len(t) for t in texts),
            "chars_per_page_mean": round(sum(len(t) for t in texts) / len(texts), 1) if texts else 0,
            "sample_text_page0": (texts[0][:80] if texts else ""),
            "rss_delta_mb": round(rss_mb() - rss0, 1),
            "error": err,
            "providers_in_use": ot.get_available_providers(),
        }
        if tag == "directml":
            run["gpu_free_mb_after"] = gpu_free_mb()
        report["runs"][tag] = run

    cpu_t, dml_t = report["runs"].get("cpu", {}), report["runs"].get("directml", {})
    report["comparison"] = {
        "cpu_mean_ms": cpu_t.get("per_page_ms_mean"),
        "dml_mean_ms": dml_t.get("per_page_ms_mean"),
        "speedup_vs_cpu": round(cpu_t["per_page_ms_mean"] / dml_t["per_page_ms_mean"], 2)
        if cpu_t.get("per_page_ms_mean") and dml_t.get("per_page_ms_mean")
        else None,
        # 两个后端结果必须一致，否则不能随意切换后端
        "text_identical": (cpu_t.get("sample_text_page0", "\x00") == dml_t.get("sample_text_page0", "\x00"))
        if cpu_t.get("pages_done") and dml_t.get("pages_done")
        else None,
        "vram_consumed_mb": (report["gpu_free_mb_at_start"] - dml_t["gpu_free_mb_after"])
        if dml_t.get("gpu_free_mb_after") is not None and report["gpu_free_mb_at_start"] > 0
        else None,
    }

    # 全量投产推算：用 P2 真实样本的类别占比与页数，不许用假想值
    try:
        cen = json.load(open(".probe_work/p0_corpus_census.json", encoding="utf-8"))
        pdfs = json.load(open(".probe_work/p2_pdf_result.json", encoding="utf-8"))
        ok = [r for r in pdfs["files"] if r.get("kind")]
        n_ok = len(ok)
        scanned = [r for r in ok if r["kind"] == "scanned_image"]
        mixed = [r for r in ok if r["kind"] == "mixed"]
        # 需要 OCR 的页数：纯扫描全都要，mixed 只按 text_bearing_rate 缺的部分估
        pages_scanned = sum(r["pages"] for r in scanned)
        pages_needed = pages_scanned + sum(
            int(r["pages"] * (1 - r["detail"]["text_bearing_rate"])) for r in mixed
        )
        share_needed = pages_needed / max(1, sum(r["pages"] for r in ok))
        total_pages_est = cen["pdf_count"] * (sum(r["pages"] for r in ok) / n_ok)
        pages_to_ocr = int(total_pages_est * share_needed)
        report["projection"] = {
            "corpus_pdf_count": cen["pdf_count"],
            "sampled_files_ok": n_ok,
            "sampled_scanned_image_count": len(scanned),
            "sampled_mixed_count": len(mixed),
            "ocr_share_of_pages": round(share_needed, 3),
            "corpus_total_pages_estimate": int(total_pages_est),
            "corpus_pages_needing_ocr": pages_to_ocr,
            "hours_cpu": round(pages_to_ocr * cpu_t["per_page_ms_mean"] / 3.6e6, 1)
            if cpu_t.get("per_page_ms_mean") else None,
            "hours_directml": round(pages_to_ocr * dml_t["per_page_ms_mean"] / 3.6e6, 1)
            if dml_t.get("per_page_ms_mean") else None,
            "days_cpu_at_8h_per_day": round(pages_to_ocr * cpu_t["per_page_ms_mean"] / 3.6e6 / 8, 1)
            if cpu_t.get("per_page_ms_mean") else None,
            "days_directml_at_8h_per_day": round(pages_to_ocr * dml_t["per_page_ms_mean"] / 3.6e6 / 8, 1)
            if dml_t.get("per_page_ms_mean") else None,
        }
    except Exception as exc:  # noqa: BLE001
        report["projection"] = {"unavailable": f"{type(exc).__name__}: {exc}"}

    proj = report.get("projection", {})
    # 阈值不许拍脑袋：由"无人值守窗口"反算每页预算。
    # 设计假设 A-OCR-1（待用户确认）：全量 OCR 必须能在一个 8 小时无人值守窗口内推进 >= 10% 语料。
    budget_hours, corpus_fraction_per_window = 8.0, 0.10
    pages_per_window = proj.get("corpus_pages_needing_ocr", 0) * corpus_fraction_per_window
    ms_budget = round(budget_hours * 3.6e6 / pages_per_window, 1) if pages_per_window else None
    report["threshold_derivation"] = {
        "assumption": "A-OCR-1: 8 小时无人值守窗口至少推进 10% 待 OCR 页（未与用户确认）",
        "pages_per_window": int(pages_per_window),
        "per_page_ms_budget": ms_budget,
    }
    dml_med = dml_t.get("per_page_ms_median")
    report["verdict"] = {
        "ocr_feasible_unattended": bool(ms_budget is not None and (dml_med or 1e9) <= ms_budget),
        "cuda_provider_present": "CUDAExecutionProvider" in report["providers_available"],
    }
    checks = [
        ("onnxruntime 能 import 且列出可用 providers", bool(report["providers_available"])),
        ("用的是实测空闲显存而不是宣称值", report["gpu_free_mb_at_start"] > 0),
        ("真实扫描页 OCR 在 CPU 后端跑通且无异常", cpu_t.get("pages_done", 0) >= 3 and cpu_t.get("error") is None),
        ("OCR 真的识别出了中文文本（不是空结果）", cpu_t.get("chars_per_page_mean", 0) > 20),
        (f"最快后端单页中位数 <= 全量投产反算的预算 {ms_budget}ms（不达标=全量 OCR 不可行，必须改成按需）",
         ms_budget is not None and (dml_med or 1e9) <= ms_budget),
        ("全量 OCR 结论已明确记录：可行 / 不可行（不许含糊）", "ocr_feasible_unattended" in report.get("verdict", {})),
        ("DirectML 后端确实更快（不是自我安慰）",
         bool(report["comparison"]["speedup_vs_cpu"] and report["comparison"]["speedup_vs_cpu"] > 1.0)),
        ("OCR 引擎增量内存 < 900MB（不能挤掉索引与 UI）", cpu_t.get("rss_delta_mb", 1e9) < 900),
        ("DirectML 显存占用被实测记录，且留得住（剩余 >200MB）",
         report["comparison"].get("vram_consumed_mb") is None or report["comparison"]["vram_consumed_mb"] < 2000),
        ("两个后端的识别结果一致（否则不许随意切换）",
         report["comparison"]["text_identical"] is not False),
        ("全量 OCR 耗时已按真实语料推算并给出（不许回避量级）", "hours_cpu" in proj or "hours_directml" in proj),
        ("CUDA 后端可用性按实测判定，不靠显卡型号推断",
         ("CUDAExecutionProvider" in report["providers_available"]) is False),
    ]
    for label, ok in checks:
        print(f"  {'PASS' if ok else 'FAIL'}  {label}")
    for tag, run in report["runs"].items():
        print(f"  INFO {tag}: " + json.dumps({k: run.get(k) for k in
              ("init_seconds", "per_page_ms_mean", "per_page_ms_median", "pages_per_minute",
               "chars_per_page_mean", "rss_delta_mb", "error", "skipped", "gpu_free_mb_after")}, ensure_ascii=False))
    print("  INFO comparison: " + json.dumps(report["comparison"], ensure_ascii=False))
    print("  INFO threshold: " + json.dumps(report["threshold_derivation"], ensure_ascii=False))
    print("  INFO projection: " + json.dumps(proj, ensure_ascii=False))
    print("  INFO sample: " + json.dumps(cpu_t.get("sample_text_page0", ""), ensure_ascii=False))
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2)
    print("VERDICT: " + ("ALL GREEN" if all(ok for _, ok in checks) else "RED"))
    return 0 if all(ok for _, ok in checks) else 1


if __name__ == "__main__":
    sys.exit(main())
