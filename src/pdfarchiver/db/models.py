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
    sha256: str | None = None
    page_count: int | None = None
    is_pdf: int = 1
    needs_pass: int = 0
    is_repaired: int = 0
    parse_status: str = "pending"
    text_status: str = "pending"
    ocr_status: str = "na"
    fts_status: str = "pending"
    vector_status: str = "na"
    category_confirmed: int = 0
    last_scanned_at: int | None = None
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
    created_at: int = 0
    updated_at: int = 0


@dataclass
class Job:
    id: int | None = None
    kind: str = "scan"
    doc_id: int | None = None
    state: str = "queued"
    priority: int = 5
    attempts: int = 0
    progress: float = 0.0
    last_error: str | None = None
    created_at: int = 0
