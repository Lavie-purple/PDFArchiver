"""P10 反向注入探针：证明阶段 5（本地 OCR）的每条硬断言真的能变红。

规矩与 P9 同一条（AGENTS.md）：「每写完一条断言，先用能骗过它的坏法真注入一次；
不会变红的断言直接删」。跑法 `python tests/probes/p10_reverse_injection_ocr.py`，
末行 `VERDICT: ALL GREEN` 表示下面这些坏法**每一条**都被抓住了。

harness（复制到临时目录、逐条注入、只跑目标节点、先跑基线）直接复用 `p9_reverse_injection`
里那一套 —— 两个探针必须同一套规矩，否则"注入失效"的判定标准会变成两份。
**不碰工作区**：每次注入都在系统临时目录的副本里进行，产品代码从不被改写。

阶段 5 的断言集中在三类最容易静默失灵的地方，所以坏法也按这三类列：
- 幂等判据（少一个条件 = 整库重跑 1,144 GPU 小时，或者永远不再重跑）；
- 失败处置（失败页写空行 / 部分成功写 done / 单页异常连坐整本）；
- 出处与读数（把识别文字标成原生正文、把没排上说成排了、把页数写死成 0）；
- 资源限量（G13 重定后的两件：页预算闸门失效、单页上限失效，以及"停在半路"被记成"跑完了"）；
- 反算出处（上限表与实测脱钩、预算拍成够不着的大数、配置默认值与代码默认值分家）。
"""
from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from p9_reverse_injection import Case, Edit, _apply, _copy_repo, _run, _verdicts  # noqa: E402

IDEM = "tests/unit/test_ocr_idempotency.py"
UNIT = "tests/unit/test_ocr_engine.py"
LIM = "tests/unit/test_ocr_limits.py"
SVC = "tests/integration/test_ocr_service.py"
SVCB = "tests/integration/test_ocr_progress_and_budget.py"    # I58 丙 拆出来的另一半
BUD = "tests/integration/test_ocr_budget.py"
JOBQ = "tests/integration/test_job_queue.py"
REAL = "tests/integration/test_ocr_real_engine.py"
GUARD = "tests/guards/test_architecture.py::test_架构守卫全绿"

OCR_SERVICE = "src/pdfarchiver/services/ocr_service.py"
OCR_ENGINE = "src/pdfarchiver/ocr/engine.py"
OCR_BUDGET = "src/pdfarchiver/ocr/budget.py"
QUEUE = "src/pdfarchiver/jobs/queue.py"
SETTINGS = "src/pdfarchiver/config/settings.py"
CLASSIFY = "src/pdfarchiver/parsing/classify.py"

# 版本串尾部单独成常量：这两串以 `)` 结尾，直接写进 `Edit(...)` 里会让括号配对着迷。
DPI_TAIL = '            f"+dpi{dpi}")'
DPI_TAIL_WITH_PROVIDER = '            f"+dpi{dpi}+DmlExecutionProvider")'

CASES: list[Case] = [
    # —— 幂等判据：少一条就等于整库重跑或永远不再重跑 ——————————————————
    Case("1", "版本比对形同虚设，每次都全量重跑", f"{SVC}::test_跑完再一次都不重跑",
         [Edit(OCR_SERVICE, "        if done_versions.get(page_no) == version_now:", "        if False:")]),
    Case("2", "缺字阈值改成 0，任何一页都被当成已经有正文",
         f"{IDEM}::test_从没跑过的页进待办 "
         f"{SVC}::test_识别结果按页落库并带上页码与版本",
         [Edit(OCR_SERVICE, "        if native.get(page_no, 0) >= MIN_CHARS_PER_BEARING_PAGE:",
               "        if native.get(page_no, 0) >= 0:")]),
    Case("3", "ocr_is_current 不看页数，跑了一半也判「当前」", f"{IDEM}::test_缺任何一项就判不当前",
         [Edit(CLASSIFY, "    return ocr_pages_done >= pages_expected", "    return True")]),
    Case("4", "ocr_is_current 不看版本，升引擎后整库永不重跑", f"{IDEM}::test_缺任何一项就判不当前",
         [Edit(CLASSIFY, "    if stored_version is None or stored_version != version_now:", "    if False:")]),
    Case("5", "入场券不要了：没正文判定的文档也直接开 OCR",
         f"{IDEM}::test_没有正文判定的不发入场券 "
         f"{SVC}::test_还没索引的文档不许直接OCR",
         [Edit(CLASSIFY, "    return text_status in (TEXT_NATIVE, TEXT_MIXED, TEXT_NONE)", "    return True")]),
    Case("6", "整本级短路去掉：明明不用跑也要把文件打开走一遍", f"{SVC}::test_跑完再一次都不重跑",
         [Edit(OCR_SERVICE, "        if not force and expected and not todo and ocr_is_current(",
               "        if False and expected and not todo and ocr_is_current(")]),
    Case("7", "页行不记版本指纹，下次谁也不知道该不该重跑",
         f"{SVC}::test_识别结果按页落库并带上页码与版本 {REAL}::test_真引擎跑完第二次一页都不再推理",
         [Edit(OCR_SERVICE, '            char_count=len(body), ocr_version=version_now)])',
               '            char_count=len(body), ocr_version=None)])')]),

    # —— 失败处置 ————————————————————————————————————————
    Case("8", "给失败页写一行空文本，瞬时故障被记成永久结论", f"{SVC}::test_失败页不写行下次只补它",
         [Edit(OCR_SERVICE,
               '                    outcome.pages_failed += 1\n'
               '                    consecutive_timeouts = 0  # 推理错误不算超时，重置计数\n'
               '                    first_error = first_error or f"第 {page.page_no} 页识别｜{page.error}"\n',
               '                    self._record_page(doc_id, page.page_no, "", version_now)\n'
               '                    outcome.pages_failed += 1\n'
               '                    consecutive_timeouts = 0  # 推理错误不算超时，重置计数\n'
               '                    first_error = first_error or f"第 {page.page_no} 页识别｜{page.error}"\n')]),
    Case("9", "部分成功写成 done，界面宣布「这本书搜得全」",
         f"{SVC}::test_失败页不写行下次只补它 {SVC}::test_单页出图失败不拖垮整本",
         [Edit(OCR_SERVICE,
               "    if outcome.stopped_on_budget or outcome.stopped_on_timeout or outcome.pages_failed:\n"
               "        return OCR_PARTIAL",
               "    if outcome.stopped_on_budget or outcome.stopped_on_timeout or outcome.pages_failed:\n"
               "        return OCR_DONE")]),
    Case("10", "单页出图失败直接抛，946 页的书停在第 2 页", f"{SVC}::test_单页出图失败不拖垮整本",
         [Edit(OCR_SERVICE,
               '                first_error = first_error or f"第 {image.page_no} 页出图｜{image.error}"',
               "                raise RuntimeError(image.error)")]),
    Case("11", "加密件当普通失败去烧重试预算，且不断链", f"{SVC}::test_加密需要密码的PDF判永久失败并留下原因",
         [Edit(OCR_SERVICE, "        if reader.info.needs_pass:", "        if False:")]),
    Case("12", "doc_id 为空当成「整库都跑」，误点一下就是 143 个工作日",
         f"{SVCB}::test_doc_id为空的OCR任务判永久失败不扫全库",
         [Edit(OCR_SERVICE,
               '            raise PermanentFailure("OCR 任务必须指向一份具体文档；全库自动 OCR 按 D-006 不存在")',
               "            return")]),
    Case("13", "一页都没成功也不写 failed", f"{SVC}::test_全部页失败才判failed部分成功绝不判done",
         [Edit(OCR_SERVICE,
               "    if outcome.pages_recognized == 0 and not reused and outcome.pages_failed:", "    if False:")]),

    # —— 排队回执与进度 ————————————————————————————————————
    Case("14", "回执不记跳过理由，「我勾了 40 份」与「队列里 3 份」没人解释",
         f"{SVC}::test_点名的份数进队列且回执指得出为什么没进",
         [Edit(OCR_SERVICE, "                skipped.setdefault(reason, []).append(doc_id)", "                pass")]),
    Case("15", "把去重命中的也说成自己排进去的", f"{SVC}::test_重复点名同一份不重复排队",
         [Edit(OCR_SERVICE, "        enqueued = self.jobs.enqueue_many(\"ocr\", queueable)",
               "        self.jobs.enqueue_many(\"ocr\", queueable)\n        enqueued = len(queueable)")]),
    Case("16", "不设总页数，界面上的进度条永远是 0/N", f"{SVCB}::test_OCR任务经真队列跑完并留下进度",
         [Edit(OCR_SERVICE, "            monitor.set_total(len(todo))", "            pass")]),

    # —— 出处标签与读数 ————————————————————————————————————
    Case("17", "把识别文字标成「原生正文」（SPEC 五明文禁止）",
         f"{SVC}::test_OCR文本进全文索引且标明出处 {REAL}::test_真引擎把图像里的中文识别进全文索引并标明出处",
         [Edit("src/pdfarchiver/search/service.py", '    "ocr": "OCR 识别（可能有错字）",', '    "ocr": "原生正文",')]),
    Case("18", "OCR 文本冒充原生文本落库", f"{REAL}::test_真引擎把图像里的中文识别进全文索引并标明出处",
         [Edit(OCR_SERVICE, '            doc_id=doc_id, page_no=page_no, body=body, source_kind="ocr",',
               '            doc_id=doc_id, page_no=page_no, body=body, source_kind="native",')]),
    Case("19", "已入库 OCR 页数写死成 0", f"{SVCB}::test_状态读数给出OCR份数与已入库页数",
         [Edit("src/pdfarchiver/services/status_service.py",
               "            ocr_pages=self.texts.count_ocr_pages_all() if with_ocr_pages else None,",
               "            ocr_pages=0 if with_ocr_pages else None,")]),
    Case("20", "OCR 份数不分组，四种状态混成一种", f"{SVCB}::test_状态读数给出OCR份数与已入库页数",
         [Edit("src/pdfarchiver/db/repositories/documents.py",
               '        rows = conn.execute("SELECT ocr_status, count(*) AS n FROM documents GROUP BY ocr_status").fetchall()',
               '        rows = conn.execute("SELECT \'na\' AS ocr_status, count(*) AS n FROM documents").fetchall()')]),

    # —— 引擎层 ————————————————————————————————————————
    Case("21", "把 provider 写进版本串：换个显卡驱动就整库过期",
         f"{UNIT}::test_版本指纹里没有provider_换显卡不该让整库重跑",
         [Edit(OCR_ENGINE, DPI_TAIL, DPI_TAIL_WITH_PROVIDER)]),
    Case("22", "读不到版本号就编一个 unknown 充数",
         f"{UNIT}::test_读不到版本号时报错点名缺哪个包以及怎么装",
         [Edit(OCR_ENGINE, "    except importlib.metadata.PackageNotFoundError as exc:",
               "    except ZeroDivisionError as exc:")]),
    Case("23", "推理不串行，两个 worker 一起把显存吃穿",
         f"{UNIT}::test_多线程推理同一时刻只有一个在跑",
         [Edit(OCR_ENGINE, "        with self._lock:\n            try:\n"
                           "                result, _elapse = self._ocr(pixels)",
               "        if True:\n            try:\n                result, _elapse = self._ocr(pixels)")]),
    Case("24", "单页推理异常往上抛，拖死整本也拖死 worker",
         f"{UNIT}::test_单页推理炸了只回错误对象不往上抛",
         [Edit(OCR_ENGINE, "            except Exception as exc:  # noqa: BLE001 - 出图内容千奇百怪，任何一页都不许拖垮整本",
               "            except ZeroDivisionError as exc:  # noqa: BLE001")]),
    Case("25", "GPU 探测失灵时谎称可用", f"{UNIT}::test_有DirectML时默认用GPU且三个子配置都打开",
         [Edit(OCR_ENGINE, '        if "DmlExecutionProvider" in available and self.prefer_gpu:', "        if False:")]),

    # —— 装配与数据层 ————————————————————————————————————
    Case("26", "OCR 层没接进队列：点名的任务永远没人领",
         f"{SVCB}::test_应用自己的队列把ocr任务领给OCR服务",
         [Edit("src/pdfarchiver/services/bootstrap.py",
               '                                "ocr": self.ocr.handle, "vector": self.vector.handle,',
               '                                "ocr": lambda job, monitor: None, "vector": self.vector.handle,')]),
    Case("27", "读页时不取版本列：交出一个永远为 None 的字段",
         f"{SVC}::test_识别结果按页落库并带上页码与版本",
         [Edit("src/pdfarchiver/db/repositories/text.py",
               '            "SELECT doc_id, page_no, source_kind, char_count, body, ocr_version FROM text_pages"',
               '            "SELECT doc_id, page_no, source_kind, char_count, body, NULL AS ocr_version FROM text_pages"')]),
    Case("28", "ocr 任务接错了处理器，跑完的是索引不是识别",
         f"{SVCB}::test_应用自己的队列把ocr任务领给OCR服务",
         [Edit("src/pdfarchiver/services/bootstrap.py",
               '                                "ocr": self.ocr.handle, "vector": self.vector.handle,',
               '                                "ocr": self.indexer.handle, "vector": self.vector.handle,')]),
    Case("29", "识别完成时刻不写，状态页答不了「这份什么时候跑完的」",
         f"{SVC}::test_识别结果按页落库并带上页码与版本",
         [Edit("src/pdfarchiver/db/repositories/documents.py",
               "                (ocr_status, ocr_pages_done, ts, last_error, ts, doc_id))",
               "                (ocr_status, ocr_pages_done, None, last_error, ts, doc_id))")]),
    Case("30", "出图分辨率悄悄换档：版本串跟着变，没人重做实测",
         f"{UNIT}::test_出图分辨率钉在实测那一档",
         [Edit("src/pdfarchiver/parsing/pdf.py", "OCR_DPI = 200", "OCR_DPI = 150")]),
    Case("31", "OCR 服务 import ui，界面反过来被服务层拖着", GUARD,
         [Edit(OCR_SERVICE, "", "\nfrom pdfarchiver.ui import nav as _probe_nav  # 注入：反向依赖\n", append=True)]),

    # —— 每日页预算与单页超时（G13 作废重定的两件）——————————————————
    Case("32", "排队那道预算闸门去掉：用满了照样往里排",
         f"{SVCB}::test_预算用满后点名一条都不排且回执说清原因",
         # 轮十四 E 把这段判据抽成了 `OcrService._split(..., budget_remaining=…)`（预览与排队共用一条），
         # 锚点跟着搬进 `_split`；轮三十六 甲 再把闸门从布尔改成余量（只排预算内的），锚点同步。
         [Edit(OCR_SERVICE,
               '        if budget_remaining <= 0:\n'
               '            # 预算是资源闸门，不是幂等短路，所以 `force` 也不绕它：能绕开限额的限额等于没有限额。',
               '        if False:\n'
               '            # 预算是资源闸门，不是幂等短路，所以 `force` 也不绕它：能绕开限额的限额等于没有限额。')]),
    Case("33", "跑到一半不看预算：限额只在排队时生效一次",
         f"{SVCB}::test_跑到一半预算用满剩下的页留在待办 {SVCB}::test_一页都来不及跑时状态写回pending不前进",
         [Edit(OCR_SERVICE,
               "            if self.budget.exhausted():\n                self._stop_here(doc_id, outcome, reused,",
               "            if False:\n                self._stop_here(doc_id, outcome, reused,")]),
    Case("34", "只给成功的页记账：失败页的 GPU 时间凭空消失",
         f"{SVCB}::test_跑到一半预算用满剩下的页留在待办 {SVCB}::test_单页耗时超过反算上限时那页不入库整份停下",
         [Edit(OCR_SERVICE,
               '                page: OcrPage = self.engine.recognize(image.page_no, image.pixels)\n'
               '                self.budget.consume()      # 烧掉的 GPU 时间不论成败都已发生，失败页同样计入预算',
               '                page: OcrPage = self.engine.recognize(image.page_no, image.pixels)')]),
    Case("35", "单页耗时上限不判：病态文件一直跑到天荒地老",
         f"{SVCB}::test_单页耗时超过反算上限时那页不入库整份停下",
         [Edit(OCR_SERVICE, "                if page.error is None and page.took_ms > limit:", "                if False:")]),
    Case("36", "上限不分 provider，一律按 DML 那档掐：CPU 降级被全数误杀",
         f"{SVCB}::test_CPU降级按CPU的实测上限不误杀慢而正常的页",
         [Edit(OCR_SERVICE, "                limit = page_timeout_ms(self.engine.provider)", "                limit = 30_000")]),
    Case("37", "判停的任务记成跑完：done 被补成 total",
         f"{SVCB}::test_预算停在半路的任务不许记成跑完 {JOBQ}::test_处理函数自己判停时落cancelled并留下原因",
         [Edit(QUEUE, "        elif outcome == \"cancelled\":\n            self._finish_cancelled(job, stop_reason)",
               "        elif outcome == \"cancelled\":\n            self._finish_success(job)")]),
    Case("38", "退出打断与判停混成一种：每次关应用都留下一堆「已取消」",
         f"{JOBQ}::test_退出闸门已拉下时处理函数判停仍按打断处理",
         [Edit(QUEUE,
               '        if self._stop.is_set():\n'
               '            log.info("任务 %s(%s) 被退出打断，留在 running 等下次回收", job.id, job.kind)',
               '        if False:\n'
               '            log.info("任务 %s(%s) 被退出打断，留在 running 等下次回收", job.id, job.kind)')]),
    Case("39", "记账不看日期：换了 UTC 日还是满的，预算变成一次性用品",
         f"{BUD}::test_换了UTC日自动归零不需要任何定时任务",
         [Edit(OCR_BUDGET, "        if not isinstance(stored, dict) or stored.get(\"date\") != self._today():",
               "        if not isinstance(stored, dict):")]),
    Case("40", "剩余页数不夹零：界面读出「剩 -3 页」",
         f"{BUD}::test_记账超出上限也不许出现负数剩余",
         [Edit(OCR_BUDGET, "        return max(0, self.pages_per_day - self.used_today())",
               "        return self.pages_per_day - self.used_today()")]),
    Case("41", "攒到整本再记账：被断电的那一半工作量凭空抹掉",
         f"{BUD}::test_一页写一次进程被杀后计数不倒退 {BUD}::test_用满一页少一页用满即停",
         [Edit(OCR_BUDGET, "        if pages <= 0:\n            return", "        if pages >= 0:\n            return")]),
    Case("42", "单页上限松到实测最大值的四倍以上：这条限量什么都不拦",
         f"{LIM}::test_单页上限是实测最大值乘二",
         [Edit(OCR_BUDGET,
               'PAGE_TIMEOUT_MS = {"DmlExecutionProvider": 30_000, "CPUExecutionProvider": 165_000}',
               'PAGE_TIMEOUT_MS = {"DmlExecutionProvider": 60_000, "CPUExecutionProvider": 165_000}')]),
    Case("43", "没测过的 provider 拿最窄的一档：新显卡一插上就被掐死",
         f"{LIM}::test_没测过的provider用最宽的一档",
         [Edit(OCR_BUDGET,
               '    return PAGE_TIMEOUT_MS.get(provider or "", max(PAGE_TIMEOUT_MS.values()))',
               '    return PAGE_TIMEOUT_MS.get(provider or "", min(PAGE_TIMEOUT_MS.values()))')]),
    Case("44", "预算拍成一个够不着的大数：一天就能「跑完」143 个工作日的量",
         f"{LIM}::test_每日预算是最慢档八小时跑不满的那个数 {LIM}::test_预算的配置默认值与代码默认值同源",
         [Edit(OCR_BUDGET, "DEFAULT_DAILY_PAGE_BUDGET = 6000", "DEFAULT_DAILY_PAGE_BUDGET = 20000")]),
    Case("45", "配置默认值与代码默认值分家：两处各写一个数，迟早对不上",
         f"{LIM}::test_预算的配置默认值与代码默认值同源",
         [Edit(SETTINGS, '    "ocr_daily_page_budget": 6000,  #', '    "ocr_daily_page_budget": 8000,  #')]),
]


def main() -> int:
    ws = Path(tempfile.mkdtemp(prefix="p10_reverse_injection_"))
    try:
        _copy_repo(ws)
        targets = sorted({t for c in CASES for t in c.node.split()})
        rc, out = _run(ws, targets)
        failed, errored, passed = _verdicts(out)
        print(f"基线（未注入）：{passed} 条通过 / {failed} 失败 / {errored} 错误，exit={rc}")
        if rc != 0:
            print(out[-4000:])
            print("VERDICT: RED（基线就没过，后面的注入结论全部不作数）")
            return 1

        results = []
        for case in CASES:
            one = Path(tempfile.mkdtemp(prefix="p10_case_"))
            try:
                _copy_repo(one)
                _apply(one, case)
                rc, out = _run(one, case.node.split())
                failed, errored, passed = _verdicts(out)
                caught = rc != 0 and failed >= 1 and errored == 0
                first = next((ln for ln in out.splitlines()
                              if ln.startswith("E   ") or "AssertionError" in ln
                              or "ArchitectureError" in ln or "PytestUnknownMark" in ln), "")
                results.append((case, caught, failed, errored, passed, first.strip()[:110]))
                print(f"  {'RED  ' if caught else 'GREEN'}  p10 #{case.inject} {case.坏法}")
                print("         -> " + " + ".join(t.split("::")[-1] for t in case.node.split())
                      + f"｜failed={failed} error={errored} passed={passed}")
                if first:
                    print(f"         原文：{first.strip()[:110]}")
            finally:
                shutil.rmtree(one, ignore_errors=True)

        missed = [r for r in results if not r[1]]
        print(f"\n抓到 {len(results) - len(missed)}/{len(results)} 条坏法")
        for case, _, _, _, _, _ in missed:
            print(f"  未抓到：p10 #{case.inject} {case.坏法} —— 对应断言是摆设，按 AGENTS.md 必须删或重写")
        print("VERDICT: " + ("ALL GREEN" if not missed else "RED"))
        return 0 if not missed else 1
    finally:
        shutil.rmtree(ws, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
