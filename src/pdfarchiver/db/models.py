"""行数据类与状态常量。

SPEC 3.2 明确「缺失的元数据应保留为空，不得凭空编造」，所以这些 dataclass 里
可空字段一律 `None` 默认，**没有任何"看起来合理"的兜底值**。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone


def now_ts() -> int:
    """全项目只有一个时间口径：UTC unix 秒。数据库与日志都用它。"""
    return int(datetime.now(timezone.utc).timestamp())


@dataclass
class Document:
    id: int | None = None
    path: str = ""
    path_key: str = ""
    name: str = ""
    ext: str = "pdf"
    size_bytes: int = 0
    mtime_ns: int = 0
    ctime_ns: int | None = None
    file_id: int | None = None
    device_id: int | None = None
    sha256: str | None = None
    page_count: int | None = None
    text_bearing_rate: float | None = None
    is_pdf: int = 1
    needs_pass: int = 0
    is_repaired: int = 0
    parse_status: str = "pending"
    text_status: str = "pending"
    ocr_status: str = "na"
    ocr_pages_done: int = 0
    last_ocr_at: int | None = None
    fts_status: str = "pending"
    vector_status: str = "na"
    category_confirmed: int = 0
    last_scanned_at: int | None = None
    last_indexed_at: int | None = None
    last_read_page: int | None = None
    last_read_at: int | None = None
    last_error: str | None = None
    missing_since: int | None = None
    created_at: int = 0
    updated_at: int = 0


@dataclass
class Category:
    id: int | None = None
    name: str = ""
    parent_id: int | None = None
    name_path: str = ""
    note: str | None = None
    created_at: int = 0
    updated_at: int = 0


@dataclass
class Tag:
    id: int | None = None
    name: str = ""
    color: str | None = None
    note: str | None = None
    created_at: int = 0


@dataclass
class MonitoredRoot:
    id: int | None = None
    root_path: str = ""
    root_key: str = ""
    label: str | None = None
    enabled: int = 1
    exclude_globs: str = "[]"
    last_full_scan_at: int | None = None
    last_scan_error: str | None = None
    created_at: int = 0
    updated_at: int = 0


@dataclass
class Job:
    """后台任务的一行。`state` 的合法取值只有 docs/DATABASE 二·2.2 那一套，
    流转规则由 `jobs/queue.py` 负责，见那里的 `LEGAL_TRANSITIONS`。"""

    id: int | None = None
    kind: str = "scan"
    doc_id: int | None = None
    state: str = "queued"
    priority: int = 5
    attempts: int = 0
    progress: float = 0.0
    total: int | None = None
    done: int = 0
    last_error: str | None = None
    created_at: int = 0
    started_at: int | None = None
    finished_at: int | None = None


@dataclass
class TextPage:
    """一页正文。`page_no` 一律从 1 开始 —— SPEC 3.4 要求搜索结果能跳到"相关页码"，
    而用户在看阅读器时看到的页码也是 1 基的，两处不许各算各的。"""

    doc_id: int
    page_no: int
    body: str
    source_kind: str = "native"
    char_count: int = 0
    ocr_version: str | None = None

    def __post_init__(self) -> None:
        if self.page_no < 1:
            raise ValueError(f"页码必须从 1 开始，收到 {self.page_no}")
        if not self.char_count:
            self.char_count = len(self.body)
