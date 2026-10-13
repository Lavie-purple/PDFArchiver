"""路径身份单测（D-005）。规则来自 p7 的 15 条实测，不是字符串风格偏好。"""
from __future__ import annotations

import ctypes
import os
from pathlib import Path

import pytest

from pdfarchiver.fs.identity import identity_key, normalize_path, read_identity


@pytest.fixture
def real_file(tmp_path: Path) -> Path:
    p = tmp_path / "报告 A.pdf"
    p.write_bytes(b"%PDF-1.7\n")
    return p


def test_分隔符统一成正斜杠(real_file) -> None:
    norm = normalize_path(real_file)
    assert "/" in norm and "\\" not in norm
    assert norm.lower().endswith("报告 a.pdf")


def test_输出是绝对路径(tmp_path) -> None:
    norm = normalize_path(Path("相对/目录/文件.pdf"))
    assert os.path.isabs(norm.replace("/", os.sep))
    assert ".." not in norm.split("/")


def test_同一个文件的不同写法得到同一个身份(real_file) -> None:
    direct = identity_key(real_file)
    variants = [
        str(real_file).replace(os.sep, "/"),
        str(real_file.parent) + os.sep + "." + os.sep + real_file.name,
        str(real_file.with_name(real_file.name.upper())) if os.name == "nt" else str(real_file),
    ]
    for v in variants:
        assert identity_key(v) == direct, f"{v} 应当与 {real_file} 同身份"


def test_重叠目录的相对写法同身份(real_file, monkeypatch) -> None:
    monkeypatch.chdir(real_file.parent)
    assert identity_key(real_file.name) == identity_key(real_file)


@pytest.mark.skipif(os.name != "nt", reason="8.3 短名是 Windows 特性")
def test_短名与长名同身份(real_file) -> None:
    """p7 实测：8.3 短名会把空格直接吃掉（`报告 A.pdf` → `报告A~1.PDF`），
    所以身份必须走 realpath，纯字符串归一对不出来。"""
    buf = ctypes.create_unicode_buffer(1024)
    n = ctypes.windll.kernel32.GetShortPathNameW(str(real_file), buf, 1024)
    assert n > 0, "GetShortPathNameW 调用失败，本测试没测到东西"
    short = buf[:n]
    if short.lower() == str(real_file).lower():
        pytest.skip("本机所在卷未启用 8.3 短名生成，这条断言在此环境下无从区分")
    assert identity_key(short) == identity_key(real_file)


def test_身份键全小写(real_file) -> None:
    assert identity_key(real_file) == identity_key(real_file).casefold()


def test_读身份拿到文件事实(real_file) -> None:
    ident = read_identity(real_file)
    assert ident.name == real_file.name
    assert ident.ext == "pdf"
    assert ident.size_bytes == real_file.stat().st_size
    assert ident.mtime_ns == real_file.stat().st_mtime_ns
    assert ident.path_key == identity_key(real_file)
    assert ident.path == normalize_path(real_file)


def test_文件不存在时read_identity抛OSError(tmp_path) -> None:
    with pytest.raises(OSError):
        read_identity(tmp_path / "根本没有这个文件.pdf")


def test_身份字段全部来自一次stat(real_file) -> None:
    """`read_identity` 不许自己造值：每个字段都要能和 `os.stat` 的实际结果对上。"""
    st = os.stat(real_file)
    ident = read_identity(real_file)
    assert (ident.size_bytes, ident.mtime_ns, ident.ctime_ns, ident.file_id) == (
        st.st_size, st.st_mtime_ns, st.st_ctime_ns, st.st_ino)
    assert not hasattr(ident, "page_count"), "页数属于解析层，身份层出现它只能是猜的"
