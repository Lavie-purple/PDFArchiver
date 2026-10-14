"""「这份 PDF 有没有正文」的判定 —— 唯一口径。

**为什么需要一个单独的模块**：这件事在三个地方被问到，各自都容易顺手算一遍：
扫描器（要不要建全文索引）、状态页（为什么搜不到内容）、阶段 5（要不要送去 OCR）。
如果三处各有一个阈值，就会出现"状态页说可搜索、搜索说没有结果"这种事。
所以阈值、算法、结论字符串都只写在本文件里，别处只许调用。

阈值与 **p2 探针完全一致**（那 37.5% 纯扫描件的统计就是按这两个数出来的），
改动这里等于改动阶段 0 的全部实测结论 —— 要改就重跑 `tests/probes/p2_pdf_extract.py`。

| 判定 | 条件 | 结论 |
| --- | --- | --- |
| 有原生正文 | `text_bearing_rate >= 0.5` | `text_status='native'` |
| 部分有 | `0.1 < rate < 0.5` | `text_status='mixed'` |
| 基本没有 | `rate <= 0.1` | `text_status='none'`（多半是扫描件） |
| 一页都没读出来 | 全部页面报错 | `text_status='failed'` |

`text_bearing_rate` = "去空格后 ≥40 字符的页" 占 "实际读到的页" 的比例。
p2 是按最多 30 页抽样算的；本阶段索引时逐页都读了，所以这里是**全量页**上的同一个数 —— 
分母变大只会更准，不是第二个口径。

阶段 2 不区分"扫描件"与"空/读不出"：两者的处置一样（都不建正文索引、都标 OCR 待处理），
而区分它需要逐页 `get_images()`，p2 没量过那一步的耗时，不为了分类引入未验证的开销。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from pdfarchiver.parsing.pdf import PageText

MIN_CHARS_PER_BEARING_PAGE = 40  # p2 口径
NATIVE_RATE_MIN = 0.5            # p2 口径
SCANNED_RATE_MAX = 0.1           # p2 口径

TEXT_NATIVE = "native"
TEXT_MIXED = "mixed"
TEXT_NONE = "none"
TEXT_FAILED = "failed"
TEXT_STATUSES = (TEXT_NATIVE, TEXT_MIXED, TEXT_NONE, TEXT_FAILED)


@dataclass(frozen=True)
class Verdict:
    text_status: str
    text_bearing_rate: float
    bearing_pages: int
    read_pages: int
    error_pages: int

    @property
    def needs_ocr(self) -> bool:
        """需要 OCR ≠ 会跑 OCR。阶段 2 只做标记：OCR 已按 D-006 移出自动索引流程
        （p5 实测全量 1,144 小时），到这里只是把"哪些文件等着"数清楚。"""
        return self.text_status in (TEXT_MIXED, TEXT_NONE)

    def describe(self) -> str:
        return (f"text_status={self.text_status}，bearing_rate={self.text_bearing_rate:.3f}，"
                f"{self.bearing_pages}/{self.read_pages} 页有正文，{self.error_pages} 页读失败")


def ocr_status_for(verdict: Verdict) -> str:
    """`ocr_status` 的唯一映射。

    'pending' 的意思是"识别出这份需要 OCR，但按 D-006 没有排任务"。
    原生文本给 'na'（不需要），整本读不出来的也给 'na' —— 连文件都打不开，OCR 也无从下手，
    那种情况该由 `parse_status='failed'` + `last_error` 说话，而不是让 OCR 队列背一个打不开的文件。
    """
    if verdict.text_status == TEXT_FAILED:
        return "na"
    return "pending" if verdict.needs_ocr else "na"


OCR_NA = "na"
OCR_PENDING = "pending"
OCR_DONE = "done"
OCR_PARTIAL = "partial"
OCR_FAILED = "failed"
# 取值只有这五个，`documents.ocr_status` 的写入唯一入口是 `mark_ocr_result`，判定唯一出处是
# `services/ocr_service._status_for` / `_status_when_nothing_to_do`。
# **没有** `running` —— 与 `fts_status` 同一条规矩（D-025）：进行中由队列的 `job.state` 表达，
# 文档行只记结论，否则关窗时会留下一堆没人认领的 'running'。
# 也**没有**状态机转移表：这一列每次都由"这次跑了几页、库里几页是当前版本"重新算出来，
# 不是从上一步累加过去的，所以不存在"哪条边合法"的问题；写它的唯一后果是漏一条边把自己挡死。
OCR_STATUSES = (OCR_NA, OCR_PENDING, OCR_DONE, OCR_PARTIAL, OCR_FAILED)


def ocr_ready(text_status: str) -> bool:
    """这份文档**有没有可用的正文判定**，也就是能不能算出"哪几页缺字"。

    OCR 的待办页判据是原生字数表（`text_pages` 里 `source_kind='native'` 那些行），
    而那张表只在索引成功之后才存在。所以这里问的不是 `ocr_status`，而是"判定存不存在"：
    - `pending` = 还没索引，一页的原生字数都不知道，跑 OCR 会把文字版 PDF 的每一页都识别一遍；
    - `failed` = 整本读不出内容，那是 `parse_status` + `last_error` 该说的事，不该排进 OCR 队列。
    排队（`services/ocr_service.request_ocr`）与执行（`ocr_document`）都只问这一个问题。
    """
    return text_status in (TEXT_NATIVE, TEXT_MIXED, TEXT_NONE)


def ocr_is_current(*, ocr_status: str, ocr_pages_done: int, stored_version: str | None,
                   version_now: str, pages_expected: int) -> bool:
    """「这份文档的 OCR 还是当前的吗」—— 唯一判定，幂等跳过与"按需重识别"都只问它。

    四个条件缺一个就会出事故，各自对应一条实测：
    - `ocr_status` 不是 done/partial：从没跑过或整体失败，当然要跑。
    - `stored_version == version_now`：引擎或模型或出图分辨率变了就必须重跑（阶段 5 决策 4 加这一列
      的全部理由）。版本串里**不含 provider**：p5 实测 CPU 与 DirectML `text_identical=true`，
      把 provider 写进版本会让"显卡驱动换了/临时退回 CPU"这种小事引发整库重跑 = 1,144 小时。
    - `ocr_pages_done == pages_expected`：混合文档上次只成功了 8/10 页时，`ocr_status` 是 partial，
      重跑要能只补那 2 页（按页存版本正是为此）。
    - `pages_expected > 0`：页数为 0 的文档（读不出来）不该被当成"当前且完整"。
    """
    if ocr_status not in (OCR_DONE, OCR_PARTIAL):
        return False
    if not pages_expected:
        return False
    if stored_version is None or stored_version != version_now:
        return False
    return ocr_pages_done >= pages_expected


def judge(pages: Sequence[PageText]) -> Verdict:
    """对一份文档的全部页面判定。空列表 = 一页都没有，按 `failed` 处理（没有正文可索引）。

    逐页流式抽取时用 `PageTally`，不必把整本的 `PageText` 攒在内存里再交给这个函数 ——
    两条路走的是同一个 `PageTally`，所以判定只有一份实现。
    """
    tally = PageTally()
    for page in pages:
        tally.add(page)
    return tally.verdict()


class PageTally:
    """边抽边算的累加器。阈值与 `judge` 同源（本模块唯一的那两个数）。

    存在理由不是省代码，是省内存：最大单文件 946 页（p2），如果索引层为了"最后判一次"
    把每一页的原始文本连同一个归一化副本一起留在内存里，峰值就是双份整本。
    判定只依赖三个计数，所以流式数完就够了。
    """

    def __init__(self) -> None:
        self.read_pages = 0
        self.bearing_pages = 0
        self.error_pages = 0

    def add(self, page: PageText) -> None:
        if page.error is not None:
            self.error_pages += 1
            return
        self.read_pages += 1
        if page.stripped_chars >= MIN_CHARS_PER_BEARING_PAGE:
            self.bearing_pages += 1

    def verdict(self) -> Verdict:
        if not self.read_pages:
            return Verdict(TEXT_FAILED, 0.0, 0, 0, self.error_pages)
        rate = self.bearing_pages / self.read_pages
        if rate >= NATIVE_RATE_MIN:
            status = TEXT_NATIVE
        elif rate <= SCANNED_RATE_MAX:
            status = TEXT_NONE
        else:
            status = TEXT_MIXED
        return Verdict(status, rate, self.bearing_pages, self.read_pages, self.error_pages)
