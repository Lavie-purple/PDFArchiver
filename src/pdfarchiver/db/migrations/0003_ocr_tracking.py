"""0003 · OCR 结果的可追溯列（阶段 5）。

三条口径写在这里，改结构前先看：

1. **版本按页存，不按文档存**（`text_pages.ocr_version`）。一份 900 页的混合文档里，
   失败的可能只有第 400 页；按文档存版本就只能整本重跑，而"整本重跑"在这条路上
   是秒级/页 × 页数（p5 实测 DirectML 中位 3,281ms/页），代价必须由粒度来摊。
   原生页这一列是 `NULL` —— "没跑过 OCR"和"跑过但结果是空"是两件事，不许用空串混成一谈。
2. **`ocr_pages_done` 是计数不是状态**。状态只有一个口径，就是 `documents.ocr_status`
   （取值见 `parsing/classify.py` 的 `OCR_STATUSES`）；这一列只回答"这本书里有几页是 OCR 出来的"，
   供状态页与"识别质量"抽样用，不参与任何流转判定。
3. **不给 OCR 单独建表**（阶段 5 决策 4 选的是加列）。等真要存"每次跑花了多久、用了哪个 provider"
   的流水时再建 `ocr_runs`，那时这一列仍然留着当"当前状态"的读数，两处不冲突。

刻意**不加**的两样东西：
- 不给 `ocr_status` 建部分索引：待 OCR 的文档数在真实语料上是千级（p0 实测 7,768 份），
  `COUNT(*) WHERE ocr_status='pending'` 全表扫也就几毫秒，为一个几毫秒的读加写放大不值。
- 不加"OCR 置信度"列：p5 的 RapidOCR 只给了行文本，**逐行分数没被验证过能不能横向比较**，
  存一个没验证过的分数进库，就等于把假指标写进事实层（SPEC 五·不许凭空编造）。
"""
from __future__ import annotations

VERSION = 3

DOCUMENTS_COLUMNS = [
    ("ocr_pages_done", "INTEGER NOT NULL DEFAULT 0"),
    # 列名跟着 `last_scanned_at` / `last_indexed_at` 的既有口径走，不起第三个名字。
    ("last_ocr_at", "INTEGER"),
]

TEXT_PAGES_COLUMNS = [
    ("ocr_version", "TEXT"),
]


def apply(conn) -> None:  # noqa: ANN001 - sqlite3.Connection，不 import 类型以免多一层依赖
    """整个函数在调用方的一个事务里执行：中途失败整体回滚，库回到 0002。"""
    for name, sql_type in DOCUMENTS_COLUMNS:
        conn.execute(f"ALTER TABLE documents ADD COLUMN {name} {sql_type}")
    for name, sql_type in TEXT_PAGES_COLUMNS:
        conn.execute(f"ALTER TABLE text_pages ADD COLUMN {name} {sql_type}")
