"""路径规范化与文件身份。

规则来自 p7 的 15 条实测断言（docs/VERIFICATION 4.8），不是风格选择：

    norm(path)      = os.path.realpath(path) → normpath → 反斜杠转 /
    identity_key    = norm(path).casefold()

**必须 realpath，不能只 normpath**：Windows 的 8.3 短名会把空格直接吃掉
（``报告 A.pdf`` → ``报告A~1.PDF``），纯字符串归一对不出同一文件。
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def normalize_path(raw: str | os.PathLike[str]) -> str:
    """统一到 ``, 分隔 → 正斜杠、解析短名与符号链接后的绝对路径。"""
    real = os.path.realpath(os.fspath(raw))
    return os.path.normpath(real).replace(os.sep, "/")


def identity_key(raw: str | os.PathLike[str]) -> str:
    """主记录唯一性用的键。库里配套 `COLLATE NOCASE` 唯一索引（D-005）——
    两边都做大小写不敏感是有意的冗余：索引防住绕过本函数写入的路径。"""
    return normalize_path(raw).casefold()


@dataclass(frozen=True)
class FileIdentity:
    """写 documents 表必需的文件事实。取不到的字段留 None，不许猜。"""

    path: str
    path_key: str
    name: str
    ext: str
    size_bytes: int
    mtime_ns: int
    ctime_ns: int | None
    device: int | None
    file_id: int | None


def read_identity(raw: str | os.PathLike[str]) -> FileIdentity:
    """stat 一次拿全。文件不在时抛 OSError，由调用方决定记成 missing 还是失败。"""
    st = os.stat(raw)
    p = Path(os.fspath(raw))
    return FileIdentity(
        path=normalize_path(p),
        path_key=identity_key(p),
        name=p.name,
        ext=p.suffix.lstrip(".").lower(),
        size_bytes=st.st_size,
        mtime_ns=st.st_mtime_ns,
        ctime_ns=getattr(st, "st_ctime_ns", None),
        device=getattr(st, "st_dev", None),
        file_id=getattr(st, "st_ino", None),  # NTFS 上实测可用（p7）
    )
