"""Windows 本地 PDF 归档与检索工具。"""

# 口径见 docs/REPO-JOURNAL.md「版本号口径 = 已完成的最大阶段号」：阶段 5 已交付所以是 0.5.0，
# 阶段 3、4 零代码所以不连续。CHANGELOG 与本常量必须同值，改一处就要改另一处。
__version__ = "0.5.0"

# 数据库结构版本口径只在这里定义一次；UI 与日志都引用它，不许各写一份。
APP_NAME = "PdfArchiver"
