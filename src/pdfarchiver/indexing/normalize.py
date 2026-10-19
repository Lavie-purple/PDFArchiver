"""正文入库前的空白归一 —— 索引与片段共用这一个口径，别在别处再做第二次。

为什么要归一（不是美观问题，是命中问题）：PyMuPDF 按 PDF 里的文本块/行吐字，同一句话
在源文件里常被拆成两行。不归一的话 `content_fts` 里存的是 `"hello\nworld"`，用户搜
`hello world` 时 trigram 组不出这个 gram，**明明在正文里却搜不到**；中文同理，
`人工智能` 被排版断成 `人工\n智能` 后 4 字查询直接 0 命中。

归一只做两件事：① 剥掉 C0 控制字符里不是空白的那些（**U+0000 等不可打印字符**）；
② 连续空白（\n、\r、\t、\v、\f、NBSP、全角空格……按 `str.isspace()` 的判定）压成一个空格，
首尾去掉。①是 **ISSUES I90**：真语料里 1,310 页正文夹着 U+0000，SQLite 的 `length()`/`substr()`
把正文当 C 串**遇到 NUL 即截断**（`length(body)` 读成 1 而真实字数上千），FTS 片段与界面预览
也可能拿到被截断的半句。控制字符对检索一个字的信息都没有，却会连累 SQL 侧一切函数 ——
所以入库前剥掉它，而不是让它留在库里等下游到处出岔子。
不做的事：不改大小写（折叠是检索层的事）、不删标点、不改字序 —— 正文一个字都不许"整理"，
否则片段展示和 PDF 原文对不上，用户照着页码翻回原文件会找不到那句话。
"""
from __future__ import annotations


def _drop_control(text: str) -> str:
    """剥掉不可打印的 C0 控制字符（U+0000–U+001F）与 DEL（U+007F），但**保留空白控制符**
    （\t \n \v \f \r —— 它们 `isspace()` 为真，交给下面的空白归一并压成空格，语义不变）。
    用 `str.isprintable()` 判不了：它对空格返回 False，会把普通空格也删掉。"""
    if not any(ch < "\x20" or ch == "\x7f" for ch in text):
        return text  # 绝大多数页正文一个控制字符都没有，先快速跳过
    return "".join(ch for ch in text if (ch >= "\x20" and ch != "\x7f") or ch.isspace())


def normalize_page_text(raw: str) -> str:
    """先剥控制字符，再把连续空白压成一个空格。`str.split()` 无参调用就是按 `isspace()`
    分并丢掉首尾空白，C 层一遍扫完，不必自己写循环，也不必维护一张空白字符表。"""
    return " ".join(_drop_control(raw).split())
