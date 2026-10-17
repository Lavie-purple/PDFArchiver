"""OCR 测试的**替身与样本工厂**，一份，由 `test_ocr_service.py` 与
`test_ocr_progress_and_budget.py` 共用（**ISSUES I58** 丙拆文件时抽出来的，2026-10-17）。

为什么单独成模块而不是各留一份：这两个文件是同一条链的两半（"哪几页该跑 / 跑到一半怎么停"），
`_FakeEngine` 的脚本语义一改就要两边同步，抄两份必漂 —— conftest 里 `settle` 的注释写的
是同一个理由。**不是 pytest 插件**：文件名不以 `test_` 开头，pytest 不收集它。

`_FakeEngine` 只替**推理**，不替库（D-012 禁 mock 数据库）：接口与 `OcrEngine` 一致，
少一样就是替身在骗人，所以这里刻意保留 `version_stamp` / `dpi` / `provider` / `pages_done`。
"""
from __future__ import annotations

from pathlib import Path

from pdfarchiver.fs.identity import identity_key
from pdfarchiver.ocr.engine import OcrPage
from pdfarchiver.parsing.pdf import PageImage


V1 = "fake/1.0+dpi200"
V2 = "fake/2.0+dpi200"


def _doc_id(ctx, path) -> int:
    return int(ctx.documents.facts_by_key(identity_key(str(path))).doc_id)  # type: ignore[arg-type]


def _clear_jobs(ctx) -> None:
    """结掉并清空队列里上一轮留下的行，否则「这次排了几条」只是在数上一轮。"""
    for job in ctx.jobs.list():
        ctx.jobs.succeed(int(job.id))
    ctx.jobs.clear_finished()


def _scanned(ctx, root, make_scanned_pdf, name="扫描件.pdf", *, pages=2) -> int:
    """造一份只有图没有字的真 PDF，扫进库并索引完，返回 doc_id。"""
    r = root("OCR")
    path = Path(make_scanned_pdf(f"OCR/{name}", pages=pages))
    ctx.scan.scan_root(r)
    doc_id = _doc_id(ctx, path)
    ctx.indexer.index_document(doc_id)
    _clear_jobs(ctx)
    return doc_id


def _textual(ctx, root, make_pdf, name="文字版.pdf") -> int:
    r = root("OCR")
    path = Path(make_pdf(f"OCR/{name}", pages=2,
                         lines=["人工智能产业年度报告的总体结论", "第二章讲合同审阅要点与风险"]))
    ctx.scan.scan_root(r)
    doc_id = _doc_id(ctx, path)
    ctx.indexer.index_document(doc_id)
    _clear_jobs(ctx)
    return doc_id


class _FakeEngine:
    """按脚本给出每页结果的引擎替身。接口与 `OcrEngine` 一致：
    `version_stamp` / `dpi` / `provider` / `pages_done` / `recognize` —— 少一样就是替身在骗人。

    `fails` 里的页码返回带 error 的 `OcrPage` —— 替**单页推理抛异常**那条路；
    出图失败（PyMuPDF 那侧）走的是 `_FakeReader`，两条路各验各的。
    `slow_ms` 里的页码按给定的毫秒数返回耗时 —— 替**单页耗时超过反算上限**那条路。
    """

    def __init__(self, *, version: str = V1, texts: dict[int, str] | None = None,
                 fails: tuple[int, ...] = (), provider: str = "DmlExecutionProvider") -> None:
        self.version_stamp = version
        self.dpi = 200
        self.provider = provider
        self.pages_done = 0
        self.texts = dict(texts or {})
        self.fails = set(fails)
        self.slow_ms: dict[int, float] = {}
        self.calls: list[int] = []

    def recognize(self, page_no: int, pixels) -> OcrPage:
        self.calls.append(page_no)
        self.pages_done += 1
        took = self.slow_ms.get(page_no, 1.0)
        if page_no in self.fails:
            return OcrPage(page_no, "", 0, took, f"模拟第 {page_no} 页推理异常")
        return OcrPage(page_no, self.texts.get(page_no, f"第{page_no}页识别文字"), 2, took)


class _FakeReader:
    """假出图层：只用来造「某一页出图失败」和「需要密码」这两种在磁盘上不好稳定复现的条件。"""

    def __init__(self, images: list[PageImage], *, page_count: int, needs_pass: bool = False) -> None:
        self._images = images
        self.info = _FakeInfo(page_count, needs_pass)
        self.produced = 0

    def __call__(self, path: str) -> "_FakeReader":
        return self

    def __enter__(self) -> "_FakeReader":
        return self

    def __exit__(self, *exc_info) -> bool:  # noqa: ANN002
        return False

    def iter_page_images(self, dpi: int = 200):
        for image in self._images:
            self.produced += 1
            yield image


class _FakeInfo:
    def __init__(self, page_count: int, needs_pass: bool) -> None:
        self.page_count = page_count
        self.needs_pass = needs_pass


def _fake_images(page_count: int, *, error_pages: tuple[int, ...] = ()) -> list[PageImage]:
    return [PageImage(n, error=f"模拟第 {n} 页出图失败") if n in error_pages
            else PageImage(n, pixels=bytearray(64)) for n in range(1, page_count + 1)]
