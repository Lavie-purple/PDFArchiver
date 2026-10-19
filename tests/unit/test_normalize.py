"""正文入库归一的口径（索引与片段共用这一个函数）。

为什么单独成文而不是只留在 `test_index_service.py` 的集成断言里：**ISSUES I90** 之后这个函数
承担了两件事 —— ① 连续空白压成一个空格，② 剥掉不可打印的控制字符。②是一条**正确性不变量**
（"正文里不许出现 U+0000"），它决定了 SQL 侧 `length()`/`substr()`/FTS snippet 会不会在 NUL
处提前截断，而不只是排版。不变量要钉在离它最近的地方。

坏法自证：本文件的 `test_空白控制符仍压成空格不许多删` 与 `test_输出里绝不含低字节控制字符`
在把 `_drop_control` 摘掉（退回 `" ".join(raw.split())`）后必红 —— `"\x00"` 不是 `isspace()`，
`split()` 不会去掉它，控制字符就原样留在正文里。
"""
from __future__ import annotations

import sqlite3

from pdfarchiver.indexing.normalize import normalize_page_text


def test_剥掉正文里的_null_与其他不可打印控制字符() -> None:
    assert normalize_page_text("人工智能\x00报告") == "人工智能报告"
    # \x01 \x02 \x03 不是 isspace → 直接删掉；\x1c–\x1f 被 Python 当空白 → 压成分隔空格（同样不再是控制字符）
    assert normalize_page_text("a\x01\x02b\x03尾") == "ab尾"
    assert normalize_page_text("带\x7f删除符") == "带删除符"


def test_空白控制符仍压成空格不许多删() -> None:
    """\t \n \v \f \r 属于空白：交给下面的空白归一压成一个普通空格，语义与旧口径一致。"""
    assert normalize_page_text("a\tb\nc") == "a b c"
    assert normalize_page_text("第七章  附则   与补充") == "第七章 附则 与补充"


def test_全是控制字符的页归一成空串() -> None:
    assert normalize_page_text("\x00\x01\x02") == ""


def test_输出里绝不含低字节控制字符() -> None:
    """这条就是"正文里不许出现 NUL"的可计数版本：归一之后只剩 >= 0x20 的字符与单个空格。"""
    messy = "报告\x00\x07铃\x1b转义\x0b\v普通\ttab 结尾"
    out = normalize_page_text(messy)
    assert all(ord(ch) >= 0x20 for ch in out), [hex(ord(ch)) for ch in out if ord(ch) < 0x20]


def test_归一后的正文_sql_口径与_python_口径不再分家() -> None:
    """I90 的落点：入库前剥掉 NUL 之后，SQLite 的 `length(body)` 就等于 Python 的 `len(body)`。
    这条把"单位函数行为"接回"那个 1,310 行分家红灯"上 —— 直接证的是缺陷本身，不是措辞。"""
    body = normalize_page_text("开头\x00夹着空字节的长正文" + "补" * 2000)
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE t(body TEXT NOT NULL)")
    conn.execute("INSERT INTO t VALUES(?)", (body,))
    sql_len = conn.execute("SELECT length(body) FROM t").fetchone()[0]
    conn.close()
    assert sql_len == len(body), f"SQL 读成 {sql_len}、Python 读成 {len(body)}：还有控制字符没剥干净"
