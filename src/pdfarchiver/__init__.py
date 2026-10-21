"""Windows 本地 PDF 归档与检索工具。"""

# 口径见 docs/CHANGELOG.md 头部与 docs/REPO-JOURNAL.md「版本号口径 = 已完成的最大阶段号」：
# 阶段 0–7 全部走完且发布门禁 2026-10-21 全绿，所以升 1.0.0（轮十七）。
# CHANGELOG 与本常量必须同值，改一处就要改另一处。
__version__ = "1.0.0"

# 数据库结构版本口径只在这里定义一次；UI 与日志都引用它，不许各写一份。
APP_NAME = "PdfArchiver"
