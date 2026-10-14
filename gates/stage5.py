"""阶段 5 验收门禁：在阶段 1 与阶段 2 的闸门之上，加三条只有本地 OCR 阶段才有的实测。

跑法：
    python gates/stage5.py                  # 全跑（含真引擎推理 + 两个反向注入探针，约 15–20 分钟）
    python gates/stage5.py --no-injection   # 跳过 p9 + p10 注入（约 10 分钟）
    python gates/stage5.py --quick          # 只跑阶段 5 自己的三条实测（不跑回归与注入）

红线与阶段 1、2 一样：任何一条 RED 就打印 `VERDICT: RED（n 条）` 并非 0 退出。

**这条门禁不许出现任何写死的性能数字**（阶段 5 需求原文：「不要编造性能数据」）：
毫秒、内存、显存、逐字命中率全部取自本次运行现场 —— P11 探针当次写出的 JSON、
真引擎自己数出来的 `pages_done`、以及 `state.log`。读不到就判 RED，不拿上一次的结果充数。

三条只在这里跑的：

1. **G5 产品路径端到端实测** —— 用装配好的真后台队列 + 真引擎跑真语料抽出来的扫描件，
   把「耗时 / 内存 / 显卡 / 识别质量 / 追溯 / 幂等 / 控制组」七组读数打印出来。
   测试绿了不等于跑得动：真推理的量级只能在真语料上量。
2. **G5 每日页预算真停机** —— 预算在这里给死 2 页（生产默认 6,000 页/日，一次门禁跑不到），
   用真引擎证明"跑满即停"确实发生：任务落 `cancelled`、主记录 `partial`、
   已跑的页留在库里、没跑的页自动回到待办。这条验的是限量的**行为**，
   限量的**出处**由 `tests/unit/test_ocr_limits.py` 钉住。
3. **G5 真引擎测试不许退化成 skip** —— 可选层没装时 `test_ocr_real_engine.py` 会跳过，
   而跳过的测试一条也没验。门禁机器上装了就必须真跑；没装就 RED 并原样打印装法
   （AGENTS.md：禁止能力不足时伪装成功）。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
import time
from pathlib import Path
from shutil import rmtree

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from stage1 import (PYTEST_ERROR_RE, PYTEST_FAILED_RE, PYTEST_PASSED_RE,  # noqa: E402
                    PYTEST_SKIPPED_RE, REPO, Row, _last_line, _num, _run)

P11 = "tests/probes/p11_ocr_shipped.py"
P10 = "tests/probes/p10_reverse_injection_ocr.py"
REAL_SUITE = "tests/integration/test_ocr_real_engine.py"

G_SHIPPED = "G5 产品路径端到端实测（真语料扫描件 / 真队列 / 真引擎）"
G_BUDGET = "G5 每日页预算真停机（真引擎跑到用满即停）"
G_REAL = "G5 真引擎测试套件（不许用 skip 冒充验过）"
G_INJECT = "G5 OCR 反向注入探针（阶段 5 的断言有没有约束力）"

CAUGHT_RE = re.compile(r"抓到 (\d+)/(\d+) 条坏法")


def _ms(values: list[float]) -> str:
    """min / 均值 / max，一个数都不编。"""
    if not values:
        return "本次没有任何推理发生"
    return (f"{min(values):.1f} / {sum(values) / len(values):.1f} / {max(values):.1f} ms"
            f"（{len(values)} 页）")


def _show(key: str, value: str) -> None:
    print(f"        {key}：{value}")


def gate_shipped_measurement() -> Row:
    """跑 P11 探针，把它**本次**写出的 JSON 读数搬进门禁输出。"""
    work = Path(tempfile.mkdtemp(prefix="stage5_p11_"))
    try:
        out_file = work / "p11_ocr_shipped_result.json"
        p = _run([sys.executable, P11, "--out", str(out_file)])
        text = p.stdout + p.stderr
        if p.returncode != 0 or "VERDICT: ALL GREEN" not in text or not out_file.is_file():
            return Row(G_SHIPPED, False, _last_line(p), text[-1800:])
        r = json.loads(out_file.read_text(encoding="utf-8"))

        sample, run, mem = r["sample"], r["run"], r["memory"]
        store, idem = r["store"], r["idempotency"]
        synth, ctrl = r["quality_synthetic"], r["control_hidden_text_layer"]
        per_page = run["per_page_ms"]
        wall_per_page = run["wall_seconds"] * 1000 / max(1, len(per_page))
        printable = [c for c in r["traceability"] if c["expected_page"]]

        _show("样本", f"《{sample['corpus_pdf']}》第 {sample['extracted_from_page']} 页起 "
                      f"{sample['pages']} 页｜原生文本层 {sample['text_layer_chars']} 字｜"
                      f"索引后 text_status={sample['text_status_after_index']}")
        _show("引擎", f"provider={run['provider']}｜初始化 {run['engine_init_seconds']}s｜"
                      f"onnxruntime {r['onnxruntime_version']}")
        _show("耗时", f"单页推理 {_ms(per_page)}｜整本墙钟 {run['wall_seconds']}s"
                      f"（含出图与落库 {wall_per_page:.1f}ms/页）｜队列收尾 {run['queue_stop_seconds']}s")
        _show("内存", f"启动态 {mem['rss_before_engine_mb']}MiB → 跑完 {mem['rss_after_run_mb']}MiB"
                      f"｜峰值 {mem['peak_mb']}MiB（比启动态 +{mem['peak_minus_startup_mb']}MiB）")
        for label, gpu in (("显卡·跑之前", r["gpu"]["before"]), ("显卡·跑之后", r["gpu"]["after"])):
            _show(label, str(gpu["rows_name_free_mb_used_mb_util_pct"]) if gpu.get("measurable")
                  else f"不可测：{gpu.get('caveat', '')}")
        _show("识别质量（真实页，无人工转写）",
              f"每页字数 {run['per_page_chars']}｜每页行数 {run['per_page_lines']}")
        _show("识别质量（合成页，有标准答案）",
              f"逐字命中 {synth['verbatim_hits']}/{synth['lines_expected']}"
              f"（{synth['verbatim_rate']}）｜行均相似度 {synth['mean_line_similarity']}｜"
              f"单页 {synth['took_ms']}ms")
        _show("追溯", f"{len(printable)} 个取自识别正文的词，命中页均含预期页"
                      f"｜出处标签 {sorted({c['source_label'] for c in printable})}")
        _show("幂等", f"{idem['second_receipt']}｜第二次点名新增推理 "
                      f"{idem['inferences_second_request']} 次")
        _show("控制组（整页图 + 隐形字层）",
              f"{ctrl['source']}｜新增推理 {ctrl['inferences_added']} 次｜{ctrl['meaning']}")

        bad = [name for name, ok in r["verdicts"].items() if not ok]
        # 门禁自己再核四件：探针哪天不再断言这些，这里得先红，而不是跟着一起绿。
        cross = []
        if store["ghost_rows"] != 0:
            cross.append(f"外部内容表有 {store['ghost_rows']} 条游离行")
        if idem["inferences_second_request"] != 0:
            cross.append(f"重复点名仍在推理 {idem['inferences_second_request']} 次")
        if ctrl["inferences_added"] != 0:
            cross.append(f"控制组被白烧 {ctrl['inferences_added']} 次推理")
        if run["job_state"] != "done":
            cross.append(f"队列里的 ocr 任务落在 {run['job_state']}")
        ok = not bad and not cross
        note = "" if ok else "；".join(
            [f"探针判红 {len(bad)} 项：{', '.join(bad)}"] if bad else []) + " " + "；".join(cross)
        return Row(G_SHIPPED, ok,
                   f"队列任务 {run['job_state']} 进度 {run['job_progress']}｜"
                   f"落库 {store['ocr_rows']} 页｜探针 {len(r['verdicts'])} 项判定，未过 {len(bad)} 项",
                   note.strip())
    finally:
        rmtree(work, ignore_errors=True)


def gate_real_engine_suite() -> Row:
    """真引擎那套测试必须**真跑**。跳过等于没验，门禁上不许出现"绿但一条也没跑"。"""
    p = _run([sys.executable, "-m", "pytest", REAL_SUITE, "-q", "--no-header"])
    out = p.stdout + p.stderr
    failed, errored = _num(PYTEST_FAILED_RE, out), _num(PYTEST_ERROR_RE, out)
    passed, skipped = _num(PYTEST_PASSED_RE, out), _num(PYTEST_SKIPPED_RE, out)
    counts = f"{passed} passed / {failed} failed / {errored} error / {skipped} skipped"
    if skipped and not passed:
        return Row(G_REAL, False, f"全部 {skipped} 条被跳过：可选 OCR 层没装",
                   "装法：pip install -r requirements/ocr.txt（门禁不代装，见 docs/ISSUES）")
    return Row(G_REAL, p.returncode == 0 and failed == 0 and errored == 0 and skipped == 0,
               counts, "" if p.returncode == 0 and not skipped else out[-1200:])


def _scanned_sample(path: Path, pages: int) -> Path:
    """整页贴图、零文本层的扫描件 —— 与 `tests/conftest.py` 同一个做法（产品口径的"缺字页"）。
    门禁自己画一份，为的是这条实测不依赖测试目录里的内部函数。"""
    import pymupdf

    doc = pymupdf.open()
    draft = doc.new_page(width=400, height=300)
    shape = draft.new_shape()
    shape.draw_rect(pymupdf.Rect(20, 20, 380, 280))
    shape.finish(color=(0.1, 0.1, 0.1), fill=(0.85, 0.85, 0.85))
    shape.commit()
    stream = draft.get_pixmap().tobytes("png")
    for _ in range(pages):
        page = doc.new_page(width=400, height=300)
        page.insert_image(page.rect, stream=stream)
    doc.delete_page(0)
    doc.save(str(path))
    doc.close()
    return path


def gate_budget_stop() -> Row:
    """资源限量的行为验证：真引擎、真队列、真库。预算给死 2 页，才能在一次门禁里真跑到用满。"""
    from pdfarchiver.db.repositories.jobs import TERMINAL_STATES
    from pdfarchiver.fs.identity import identity_key
    from pdfarchiver.ocr.budget import OcrBudget
    from pdfarchiver.ocr.engine import OcrEngine, OcrUnavailable
    from pdfarchiver.services.bootstrap import bootstrap
    from pdfarchiver.services.ocr_service import pages_needing_ocr

    work = Path(tempfile.mkdtemp(prefix="stage5_budget_"))
    try:
        try:
            engine = OcrEngine()
            version = engine.version_stamp
        except OcrUnavailable as exc:
            return Row(G_BUDGET, False, "可选 OCR 层没装，跑不了真停机", str(exc))

        watch = work / "扫描件"
        watch.mkdir(parents=True, exist_ok=True)
        sample = _scanned_sample(watch / "四页扫描件.pdf", 4)
        ctx = bootstrap(work / "appdata")
        try:
            root = ctx.roots.add(str(watch).replace("\\", "/"), identity_key(watch), label="门禁")
            ctx.scan.scan_root(root)
            doc_id = int(ctx.documents.facts_by_key(identity_key(sample)).doc_id)  # type: ignore[arg-type]
            ctx.indexer.index_document(doc_id)
            for row in ctx.jobs.list():
                ctx.jobs.succeed(int(row.id))
            ctx.jobs.clear_finished()

            ctx.ocr.engine = engine
            ctx.ocr.budget = OcrBudget(ctx.app_settings, pages_per_day=2)
            receipt = ctx.ocr.request_ocr([doc_id])
            started = time.perf_counter()
            queue = ctx.start_background()
            idle = queue.wait_until_idle(timeout=600.0)
            wall = time.perf_counter() - started
            # 读数必须在 shutdown 之前取：连接一关就不是产品运行时的那个口径了
            doc = ctx.documents.get(doc_id)
            jobs = [j for j in ctx.jobs.list(TERMINAL_STATES) if j.kind == "ocr"]
            todo, reused = pages_needing_ocr(ctx.texts.native_page_chars(doc_id),
                                             ctx.texts.ocr_versions_of(doc_id), 4, version)
            stored = ctx.texts.count_ocr_pages(doc_id)
        finally:
            ctx.shutdown()

        if not jobs:
            return Row(G_BUDGET, False, f"点名回执「{receipt.describe()}」里没有 ocr 任务",
                       "4 页扫描件 / 预算 2 页，应当排进一条任务并跑到用满即停")
        job = jobs[-1]
        _show("预算", "这里给死 2 页；生产默认 6,000 页/日（一次门禁跑不到那个量），同一条码路")
        _show("推理", f"真引擎实际推理 {engine.pages_done} 页｜墙钟 {wall:.2f}s"
                      f"（{wall * 1000 / max(1, engine.pages_done):.0f}ms/页）")
        _show("任务", f"点名回执「{receipt.describe()}」→ state={job.state}｜"
                      f"done/total={job.done}/{job.total}｜attempts={job.attempts}")
        _show("停机原因", str(job.last_error)[:240])
        _show("文档", f"ocr_status={doc.ocr_status}｜库里 OCR 行 {stored} 页｜"
                      f"主记录记 {doc.ocr_pages_done} 页｜待办剩 {todo}｜复用 {reused} 页")

        problems = []
        if not idle:
            problems.append("停机后队列等不到空闲（停被当成了还在跑）")
        if engine.pages_done != 2:
            problems.append(f"推理页数 {engine.pages_done} ≠ 预算 2 页")
        if job.state != "cancelled":
            problems.append(f"任务落 {job.state}，判停必须是终态")
        if "页预算用满" not in (job.last_error or ""):
            problems.append("任务行上没留下停机原因")
        if job.attempts != 1:
            problems.append(f"判停被重试了 {job.attempts} 次，预算会被同一份文档反复吃掉")
        if doc.ocr_status != "partial" or stored != 2:
            problems.append(f"主记录 {doc.ocr_status} / OCR 行 {stored} 页，与真实进度不符")
        if todo != [3, 4]:
            problems.append(f"没跑的页没有回到待办：{todo}")
        return Row(G_BUDGET, not problems,
                   f"预算 2 页 → 真推理 {engine.pages_done} 页后停在第 3 页，"
                   f"任务 {job.state}、文档 {doc.ocr_status}、待办剩 {todo}",
                   "；".join(problems))
    finally:
        rmtree(work, ignore_errors=True)


def gate_ocr_injection() -> Row:
    p = _run([sys.executable, P10])
    text = p.stdout + p.stderr
    caught = CAUGHT_RE.search(text)
    measured = (f"{caught.group(1)}/{caught.group(2)} 条坏法被抓到" if caught
                else _last_line(p))
    return Row(G_INJECT, p.returncode == 0 and "VERDICT: ALL GREEN" in text, measured,
               "" if p.returncode == 0 else text[-1500:])


def _machine_load() -> str:
    """起跑时的机器负载，只打印、不参与判定。

    G1/G2 的冷启动阈值是 `[约定]`，而它是**负载绑定**的读数：同一份代码在空载与满载的机器上
    能差好几倍（实测区间记在 `docs/TESTING.md` / `docs/VERIFICATION.md`，不写进这里）。
    把成因跟读数放在一起，免得下一次 RED 又要靠猜 —— 也不许靠放宽阈值来"修"它。
    """
    import psutil  # noqa: PLC0415 - base 依赖，但这一行只是给读数加上下文，坏了不该拖垮门禁
    try:
        cpu = psutil.cpu_percent(interval=1.0)
        avail = round(psutil.virtual_memory().available / 2 ** 20)
        top = max(psutil.process_iter(["name", "memory_info"]),
                  key=lambda p: p.info["memory_info"].rss if p.info["memory_info"] else 0)
        name = (top.info["name"] or "?")[:30]
        rss = round(top.info["memory_info"].rss / 2 ** 20)
        return f"起跑负载：CPU {cpu}%｜可用内存 {avail}MiB｜最吃内存进程 {name} {rss}MiB"
    except Exception as exc:  # noqa: BLE001 - 读数加不上就少加，绝不因此改变判定
        return f"起跑负载：取不到（{type(exc).__name__}: {exc}）"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="gates/stage5.py", description="阶段 5 验收门禁")
    ap.add_argument("--no-injection", action="store_true",
                    help="跳过 p9 + p10 两个反向注入探针（慢，约 8 分钟）")
    ap.add_argument("--quick", action="store_true",
                    help="只跑阶段 5 自己的三条实测，不跑阶段 1/2 的闸门与回归")
    args = ap.parse_args(argv)

    from stage1 import (gate_architecture, gate_cold_start,  # noqa: PLC0415
                        gate_dependency, gate_injection, gate_regression)
    from stage2 import gate_background_lifecycle, gate_e2e_acceptance  # noqa: PLC0415

    stage5 = [gate_shipped_measurement(), gate_budget_stop(), gate_real_engine_suite()]
    if args.quick:
        checks = stage5
    else:
        checks = [gate_dependency(), gate_architecture(), gate_cold_start(),
                  gate_background_lifecycle(), gate_e2e_acceptance()] + stage5 + [gate_regression()]
        if not args.no_injection:
            checks += [gate_injection(), gate_ocr_injection()]
        else:
            checks.append(Row("反向注入探针（p9 + p10）", True, "本次 --no-injection 跳过",
                              "注意：跳过注入时，「断言有约束力」这条没有被验证"))

    print(f"门禁运行于 {REPO}｜python {sys.version.split()[0]}")
    print(f"        {_machine_load()}")
    for row in checks:
        print(f"  {'PASS' if row.ok else 'RED '}  {row.gate}")
        print(f"        实测：{row.measured}")
        if row.note:
            print(f"        现场：{row.note[:600]}")
    bad = [r for r in checks if not r.ok]
    print("VERDICT: " + ("ALL GREEN" if not bad else f"RED（{len(bad)} 条未过）"))
    return 0 if not bad else 1


if __name__ == "__main__":
    raise SystemExit(main())
