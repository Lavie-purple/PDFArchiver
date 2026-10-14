"""全文索引层：口径（走 FTS 还是 LIKE）、空白归一、命中片段（阶段 2）。

这一层不写 SQL，也不 import `pdfarchiver.db` —— 架构守卫只允许仓储层出现 SQL。
"""
