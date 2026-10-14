"""PyMuPDF 封装：元数据、页数、逐页正文。

p2 探针在这条路上量过的数字决定了实现方式：**147.9 页/s**（抽取）、
最大单文件 946 页 / 1.1GB、单文件处理 RSS 增量最大 68.2MB。
所以"打开一次、逐页取、取完就关"是唯一可行的形态。

三条不许违反的做法：

1. **绝不整本读进内存**（SPEC 五·8）。只用 `pymupdf.open(path)`，页面文本按需取；
   不调 `read_bytes()`、不 `convert_to_pdf()`、不把所有页拼成一个大字符串再切。
2. **单页取不出来不是整本失败**。`iter_text_pages()` 对每一页单独 try，
   坏页产出 `PageText(error=...)` 并继续 —— 一份 900 页的文档不该因为第 400 页崩掉而整体没有索引。
3. **元数据缺就缺**。`metadata` 里读不到的键一律给 `None`；`is_repaired` 为真时
   `parse_status='degraded'`，**不算成功**（P2 实测要求，SPEC 3.2 不许凭空编造）。

`PdfReader` 是个上下文管理器：`with` 结束就 `close()`，句柄不会泄漏到下一次扫描。
"""
from __future__ import annotations

import datetime
import logging
import os
import re
from dataclasses import dataclass, field
from typing import Iterator

import pymupdf

log = logging.getLogger("pdfarchiver.parsing")

# PDF 的 Info 字典字段名 → 我们的 document_metadata 列名。只这一份映射表，别处不许再抄一遍。
META_FIELDS: dict[str, str] = {
    "title": "title",
    "author": "author",
    "subject": "subject",
    "creator": "creator_tool",
    "producer": "producer",
    "creationDate": "pdf_created_at",
    "ModDate": "pdf_modified_at",
    "keywords": "keywords",
}

_PDF_DATE_RE = re.compile(
    r"^D:(?P<Y>\d{4})(?P<m>\d{2})(?P<d>\d{2})(?P<H>\d{2})(?P<M>\d{2})(?P<S>\d{2})?"
    r"(?P<tz>[Z+-])?(?P<oh>\d{2})'?(?P<om>\d{2})?'?")


class PdfOpenError(RuntimeError):
    """整本打不开。消息里带文件路径和 PyMuPDF 原文 —— 只说"打开失败"没法远程诊断。"""

    def __init__(self, path: str, exc: BaseException) -> None:
        super().__init__(f"{path}｜{type(exc).__name__}: {exc}")
        self.path = path
        self.cause = exc


@dataclass
class PageText:
    """一页的抽取结果。`page_no` 从 1 开始（与 `text_pages.page_no` 同口径，与用户看到的页码一致）。"""

    page_no: int
    text: str = ""
    error: str | None = None

    @property
    def stripped_chars(self) -> int:
        return len(self.text.strip())


@dataclass
class PdfInfo:
    page_count: int = 0
    is_pdf: bool = True
    is_encrypted: bool = False
    needs_pass: bool = False
    is_repaired: bool = False
    pdf_version: str | None = None
    metadata: dict[str, str | None] = field(default_factory=dict)

    def as_metadata_row(self) -> dict[str, str | None]:
        """映射成 `document_metadata` 的列名字典。没读到的键留 None，不填"未知""佚名"之类的假值。"""
        out = {col: None for col in META_FIELDS.values()}
        for src, col in META_FIELDS.items():
            value = self.metadata.get(src)
            if value is not None and str(value).strip():
                out[col] = str(value).strip()
        return out


class PdfReader:
    """一份 PDF 一个实例，用完即关。不缓存文档对象，也不跨线程传它。"""

    def __init__(self, path: str | os.PathLike[str]) -> None:
        self.path = os.fspath(path)
        try:
            self._doc = pymupdf.open(self.path)
        except Exception as exc:  # noqa: BLE001 - PyMuPDF 对损坏文件抛的类型不止一种，必须原样留住
            raise PdfOpenError(self.path, exc) from exc
        self.info = self._read_info()

    # ---- 生命周期 ----
    def close(self) -> None:
        try:
            self._doc.close()
        except Exception as exc:  # noqa: BLE001 - 关闭失败要记但不能盖掉调用方真正的异常
            log.warning("关闭 PDF 句柄失败 %s：%s", self.path, exc)

    def __enter__(self) -> PdfReader:
        return self

    def __exit__(self, *exc_info) -> bool:  # noqa: ANN002
        self.close()
        return False

    # ---- 读取 ----
    def _read_info(self) -> PdfInfo:
        doc = self._doc
        meta = doc.metadata or {}
        return PdfInfo(
            page_count=int(doc.page_count),
            is_pdf=bool(doc.is_pdf),
            is_encrypted=bool(doc.is_encrypted),
            needs_pass=bool(doc.needs_pass),
            is_repaired=bool(getattr(doc, "is_repaired", False)),
            pdf_version=str(meta.get("format") or "") or None,
            metadata={k: meta.get(k) for k in META_FIELDS},
        )

    def iter_text_pages(self) -> Iterator[PageText]:
        """逐页取文本。加密且需要密码的文档在这里**不抛**，产出一条 error 后结束 ——
        它不是解析失败，是权限不足，状态得由调用方按 `info.needs_pass` 判定。"""
        if self.info.needs_pass:
            yield PageText(1, error="PDF 已加密且需要密码，无法读取正文")
            return
        for index in range(self.info.page_count):
            try:
                text = self._doc[index].get_text("text") or ""
            except Exception as exc:  # noqa: BLE001 - 坏页留下原文继续走，见模块说明第 2 条
                log.warning("第 %d 页抽取失败 %s：%s", index + 1, self.path, exc)
                yield PageText(index + 1, error=f"{type(exc).__name__}: {exc}")
                continue
            yield PageText(index + 1, text=text)


def parse_pdf_date(raw: str | None) -> int | None:
    """`D:YYYYMMDDHHmmSS...` → UTC unix 秒；解析不出来返回 None。

    **库里存的仍然是原始串**（`document_metadata.pdf_created_at`），这个函数只给
    "要按时间排序/筛选"的人用。理由：PDF 的日期字段坏得千奇百怪（缺秒、缺时区、乱码），
    存解析结果就等于把"我猜的是哪个时区"这件事写进了数据里，而原始串至少是可以复算的。
    """
    if not raw:
        return None
    m = _PDF_DATE_RE.match(str(raw).strip())
    if not m:
        return None
    g = m.groupdict()
    try:
        naive = datetime.datetime(int(g["Y"]), int(g["m"]), int(g["d"]),
                                  int(g["H"]), int(g["M"]), int(g["S"] or 0))
    except ValueError:
        return None
    tz = g["tz"]
    if tz in ("+", "-"):
        offset = datetime.timedelta(hours=int(g["oh"] or 0), minutes=int(g["om"] or 0))
        aware = naive.replace(tzinfo=(datetime.timezone(offset) if tz == "+"
                                      else datetime.timezone(-offset)))
    else:
        # 没有时区信息时**当 UTC**，并且不假装知道本地时区：
        # 猜成本机会让同一份 PDF 在两台机器上显示两个创建时间，那才是多口径。
        aware = naive.replace(tzinfo=datetime.timezone.utc)
    return int(aware.timestamp())
