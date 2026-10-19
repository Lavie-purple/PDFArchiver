"""分类清单导出（**ISSUES I78** 丙，2026-10-19）：把 S8 右键那一枝名下的文档写成一份能二次处理的文件。

线框 §I78-bing（`docs/wireframes/2026-10-19-round14-i67-i78.html`，2026-10-19 勾「丙」）要求
**先定三条口径再动界面**：列集 · 格式 · 本机绝对路径的默认策略。这三条的出处就是本文件 ——
对话框上每一颗复选框、每一个格式档的标签都从这里取，所以「界面写着有、导出写不出」这种形状
在本层就长不出来（**ISSUES I80** 那一类"界面宣称它会做它不做的事"）。

四条不是偏好而是后果的约定：
- **导出的行集与 S1 浏览、智能集合回放共用同一个 WHERE**（都编成 `DocFilter` 走
  `where_for_filter`）。同一枝分类在三个地方数出三个份数就是两个口径，而线框那条验收判据
  「导出行数 == 那条 `SELECT COUNT(*)`」要的正是"只有一个数"。缺失文档（`missing_since` 非空）
  按 SPEC 3.4 的既有口径**不计入**，导出侧不另开一个"含已消失"的开关。
- **只读**：整条链路只有 `SELECT`，不写库、不改文档、不生成待清理批次 —— 与 S5「只报告不删除」
  是同一条纪律。
- **本机绝对路径默认不出现**，要出现必须带一个显式确认位（`acknowledge_local_path`）。
  AGENTS.md 那条「密钥禁止出现在源码与构建产物」的相邻条是本机路径也是隐私：清单一旦被发到
  群里，用户目录名、盘符与整棵目录结构一起就交出去了。
- **每列的值只有一个口径出处**：大小写**原始字节数**而不是 UI 那个 `1.5 MB` 的显示串 ——
  `ui/format.py` 的 `format_bytes` 是**显示**口径，服务层 import `ui` 会被依赖方向守卫拒
  （**D-054**），把它的字符串抄进本层就是第二个口径、还把精度丢了；修改时间走
  `status_service.format_ts`（全站唯一时间出口），没有 mtime 时留空而不写"从未"，与
  `ui/library_rows.py` 对同一件事的读法逐字一致。

**「已归档」这一列不在本层算口径**（**ISSUES I78** 丙，轮十五 丙 立的那一条）。它曾经"故意不做"，
理由就是没有唯一口径 —— 库里不留 `is_archived` 这类标记（归档改的是路径而不是标记），而撤销
（S4 的反向批次）会在同一张表里再写一批方向取反的行，谁赢取决于怎么排。今天口径立起来了，
本层付出的代价是多带一个跨表读数：`OperationRepository.last_archive_destinations()` 一条 SQL
取回每份文档**最后一笔正向归档**的落点，再由 `archive_service.is_archived()` 与
`documents.path_key` 对一次。撤销之后读「否」、文件被手动挪走之后也读「否」，两句都是那条口径
的直接后果，本层不另作解释、也不自己排台账（自己排一次就是第二个口径，而界面上完全看不出来）。
表头里因此带着口径名：产物里那个「是」不是库里存着的字段，是两行数据对出来的读数。
"""
from __future__ import annotations

import csv
import io
import json
import os
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from pdfarchiver.db.models import Document, Tag, now_ts
from pdfarchiver.db.repositories.catalog import CatalogRepository
from pdfarchiver.db.repositories.documents import (
    MAX_BULK_IDS,
    NS_PER_SECOND,
    DocFilter,
    DocumentRepository,
)
from pdfarchiver.db.repositories.operations import OperationRepository
from pdfarchiver.services.archive_service import is_archived, sanitize_component
from pdfarchiver.services.status_service import format_day, format_ts

#: 一次导出的行数上限。反算依据是真实语料的最大量级：**整个库 10,977 份**（阶段 0 的读数），
#: 所以 50,000 = 全库 ×4.5 —— 今天任何一枝分类都碰不到它。上限存在的全部理由是内存：
#: 一行 `Document` 连字符串约 1 KB 量级，50,000 行是几十 MB，再往上就是拿一次导出换一台机器卡死
#: （AGENTS.md「写死的阈值必须按最大量级反算」）。
EXPORT_MAX_ROWS = 50_000

#: 哈希进产物的位数。S1 右栏详情上是完整 64 位，清单里截到 12 位（约 48 bit）：同一枝分类里
#: 撞上相同的概率远低于人手抄错一位，而整条哈希会把每行撑宽一倍。截了就要说清楚 —— 列名写着「前 12 位」。
SHA256_PREFIX = 12

#: 「已归档」的表头把**口径名一起上屏**（同「SHA256（前 12 位）」那一条理由）：库里根本没有
#: `is_archived` 这一列，裸写「已归档」会让人以为产物里那个「是」是个存着的字段，而它是
#: 「当前位置 ⇄ 最后一笔归档落点」对出来的读数。口径本体在 `archive_service.is_archived`。
ARCHIVED_LABEL = "已归档（按最后一笔归档落点）"

#: 三种格式：`(键, 给人看的名字, 文件后缀)`。界面上那三颗单选钮的标签从这里取，不另抄一遍。
FORMATS: tuple[tuple[str, str, str], ...] = (
    ("csv", "CSV", "csv"),
    ("json", "JSON", "json"),
    ("markdown", "Markdown 表", "md"),
)
_FORMAT_BY_KEY = {key: (label, ext) for key, label, ext in FORMATS}


def _blank_if_none(value: object) -> object:
    """`None` 写成空串：空单元格就是"不知道"，产物里不许出现 `None` 这个字面量。"""
    return "" if value is None else value


@dataclass(frozen=True)
class RowContext:
    """一批文档的**跨表**读数，整批一次取回，逐行只做字典查找。

    为什么不是每行现查：`tags_by_doc_ids` 与 `last_archive_destinations` 都是"一批一条 SQL"，
    50,000 行逐行查就是 10 万条 SQL —— **ISSUES I51** 判过的那类错。
    为什么不是每列各带一个字典：加一列要改的只有这里加一个字段、`_rows()` 里取一次，
    渲染那三个人（CSV/JSON/MD）与 `Column.value` 的签名都不用动。
    """

    tags: dict[int, list[Tag]] = field(default_factory=dict)
    archive_dst: dict[int, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Column:
    """一列：给人看的表头 + 怎么从一份文档取值。

    `value` 的第二个参数是这一批的跨表读数（`RowContext`），只有「标签」与「已归档」两列用得到。
    """

    key: str
    label: str
    value: Callable[[Document, RowContext], object]
    privacy: bool = False


#: 列集的唯一出处。**顺序 = 产物里的列顺序**，对话框里复选框的排列也按它。
EXPORT_COLUMNS: tuple[Column, ...] = (
    Column("name", "文件名", lambda d, _: d.name),
    Column("page_count", "页数", lambda d, _: _blank_if_none(d.page_count)),
    Column("size_bytes", "大小 (字节)", lambda d, _: d.size_bytes),
    Column("sha256_12", f"SHA256（前 {SHA256_PREFIX} 位）",
           lambda d, _: (d.sha256 or "")[:SHA256_PREFIX]),
    Column("mtime", "修改时间",
           lambda d, _: format_ts(d.mtime_ns // NS_PER_SECOND) if d.mtime_ns else ""),
    Column("text_rate", "正文覆盖率",
           lambda d, _: f"{d.text_bearing_rate:.1%}" if d.text_bearing_rate else ""),
    Column("ocr_status", "OCR 状态", lambda d, _: d.ocr_status),
    Column("vector_status", "向量状态", lambda d, _: d.vector_status),
    Column("fts_status", "索引状态", lambda d, _: d.fts_status),
    Column("archived", ARCHIVED_LABEL,
           lambda d, batch: "是" if is_archived(d.path_key, batch.archive_dst.get(d.id)) else "否"),
    Column("tags", "标签", lambda d, batch: ", ".join(t.name for t in batch.tags.get(d.id, []))),
    Column("local_path", "本机绝对路径", lambda d, _: d.path, privacy=True),
)
_COLUMNS_BY_KEY = {c.key: c for c in EXPORT_COLUMNS}

#: 默认勾的那五列 = 线框 §I78-bing 里带 `checked` 的那五项。「本机绝对路径」与「已归档」都不在
#: 默认里，但两条不是同一条理由：前者是隐私口径（勾了要多确认一次），后者是要跨到
#: `operation_items` 取数的一列 —— 默认档应当是一条人人都敢直接导出去的清单，而不是顺便查两张表。
#: 这一条被 `test_默认列集仍是线框勾的那五列` 逐字钉住：把它加进默认档就是改了线框勾过的口径。
DEFAULT_COLUMNS: tuple[str, ...] = ("name", "page_count", "size_bytes", "sha256_12", "mtime")

#: 界面上那颗确认框的问句与服务层拒因共用这一句 —— 两处各写一份就会有一天不一样。
LOCAL_PATH_WARNING = "本操作会把文件在本机的完整路径写进产物"

TAGS_COLUMN_KEY = "tags"
ARCHIVED_COLUMN_KEY = "archived"


@dataclass(frozen=True)
class ExportReceipt:
    """一次导出的读数。屏幕上那句话只有这一个出处（**ISSUES I60**：格式化只有一个出口）。"""

    category_name_path: str
    include_children: bool
    fmt: str
    rows: int
    labels: tuple[str, ...]
    path: Path
    local_path_included: bool

    def describe(self) -> str:
        scope = "含子分类" if self.include_children else "只这一枝"
        return (f"已导出 {self.rows} 行 · 「{self.category_name_path}」（{scope}）· "
                f"{_FORMAT_BY_KEY[self.fmt][0]} · {len(self.labels)} 列 · "
                f"写到 {self.path.parent}｜{self.path.name}")


class ExportService:
    """分类清单导出的口径层：行集、列集、格式、隐私、只读这五件事各只在这里判一次。

    「已归档」的口径**不在**这五件里 —— 它属于"归档"这个概念，在 `archive_service.is_archived`；
    本层只做一件事：把每份文档最后一笔归档落点取回来，交给那一列去对。
    """

    def __init__(self, documents: DocumentRepository, catalog: CatalogRepository,
                 operations: OperationRepository) -> None:
        self.documents = documents
        self.catalog = catalog
        self.ops = operations

    # ---- 口径：行集与份数 ----

    def category_scope(self, category_id: int, *, include_children: bool) -> list[int]:
        """这一枝要导哪几个分类的行（含子时走仓储层那**一条**子树谓词）。

        传的是 **id** 而不是名字：0008 之后同层重名由唯一索引管，但不同层可以同名
        （**ISSUES I77** 甲），按名字取会把「财务/合同」与「技术/合同」并成一坨。
        """
        if not include_children:
            return [category_id]
        return self.catalog.subtree_ids(category_id)

    def filter_for(self, category_id: int, *, include_children: bool) -> DocFilter:
        return DocFilter(category_ids=tuple(self.category_scope(
            category_id, include_children=include_children)))

    def count(self, category_id: int, *, include_children: bool = True) -> int:
        return self.documents.count_matching(
            self.filter_for(category_id, include_children=include_children))

    # ---- 导出 ----

    def export(self, category_id: int, *, dest_dir: Path, fmt: str = "csv",
               columns: Sequence[str] = DEFAULT_COLUMNS, include_children: bool = True,
               acknowledge_local_path: bool = False) -> ExportReceipt:
        """把这一枝名下的清单写进 `dest_dir`，返回一份回执。整条链路不写库（线框硬断言 d）。"""
        specs = self._resolve_columns(columns, acknowledge_local_path=acknowledge_local_path)
        ext = self._resolve_format(fmt)
        category = self.catalog.get_category(category_id)
        total = self.count(category_id, include_children=include_children)
        if total == 0:
            scope = "（含子分类）" if include_children else ""
            raise ValueError(f"「{category.name_path}」{scope}名下没有文档，没有可导出的清单 —— "
                             "空文件不是一份清单，是一份看起来成功的产物")
        if total > EXPORT_MAX_ROWS:
            raise ValueError(f"这一枝有 {total} 行，超过一次导出上限 {EXPORT_MAX_ROWS}；"
                             "先按分类拆细或按条件筛小，再导出")

        docs, batch = self._rows(category_id, include_children=include_children, specs=specs)
        # 数过了才算。`len(docs) != total` 意味着行集与计数用了两条口径，那种产物宁可拒发。
        if len(docs) != total:
            raise ValueError(f"内部不一致：数到 {total} 行、取到 {len(docs)} 行，已拒绝写出")

        target = self._target(dest_dir, category.name_path, ext)
        _write_no_clobber(target, _RENDERERS[fmt](docs, specs, batch))
        return ExportReceipt(category_name_path=category.name_path,
                             include_children=include_children, fmt=fmt, rows=total,
                             labels=tuple(s.label for s in specs), path=target,
                             local_path_included=any(s.privacy for s in specs))

    def _rows(self, category_id: int, *, include_children: bool,
              specs: Sequence[Column]) -> tuple[list[Document], RowContext]:
        """一条 WHERE 取行，外加**按勾了的列决定**的跨表读数，全部整批一次取回。

        不分页：`LIMIT ? OFFSET ?` 分页在 n 行上累计丢弃 n²/2·limit 行，是 AGENTS.md 明令禁止的
        O(n²)；而一次 `SELECT` 本来就要把这些行交给写文件的人，中间没有可以省的那一步。
        只有「标签」与「已归档」两列要出 `documents` 取数，所以**勾了才取**：没勾那一列还去
        扫一张表，在 50,000 行档是白扫，而白扫这种东西最后都会变成"导出怎么这么慢"。
        """
        docs = self.documents.list_sorted(
            self.filter_for(category_id, include_children=include_children),
            sort="name", limit=EXPORT_MAX_ROWS, offset=0)
        ids = [d.id for d in docs]
        batch = RowContext(
            tags=self._tag_map(ids) if any(s.key == TAGS_COLUMN_KEY for s in specs) else {},
            archive_dst=self._move_map(ids)
            if any(s.key == ARCHIVED_COLUMN_KEY for s in specs) else {})
        return docs, batch

    def _tag_map(self, doc_ids: Sequence[int]) -> dict:
        """每 `MAX_BULK_IDS` 个 id 一条查询（同一个数、同一个理由，不另立上限）。"""
        out: dict = {}
        for start in range(0, len(doc_ids), MAX_BULK_IDS):
            out.update(self.catalog.tags_by_doc_ids(list(doc_ids[start:start + MAX_BULK_IDS])))
        return out

    def _move_map(self, doc_ids: Sequence[int]) -> dict[int, str]:
        """同上分批；"最后一笔归档"到底怎么挑，只在仓储层那一句 SQL 里说一遍。

        本层不复述那个挑法，也不在这里 `sorted(items, key=updated_at)` —— 那就是把口径从
        仓储层搬到导出层，而同一条 SQL 已经在 `last_archive_destinations` 里（**ISSUES I78** 丙）。
        """
        out: dict[int, str] = {}
        for start in range(0, len(doc_ids), MAX_BULK_IDS):
            out.update(self.ops.last_archive_destinations(
                list(doc_ids[start:start + MAX_BULK_IDS])))
        return out

    # ---- 校验与落盘 ----

    def _resolve_columns(self, columns: Sequence[str], *,
                         acknowledge_local_path: bool) -> tuple[Column, ...]:
        if not columns:
            raise ValueError("一列都没勾：没有列的清单不是清单")
        unknown = [c for c in columns if c not in _COLUMNS_BY_KEY]
        if unknown:
            raise ValueError(f"未知的导出列 {unknown}；可勾的列有 {[c.key for c in EXPORT_COLUMNS]}")
        specs = tuple(_COLUMNS_BY_KEY[c] for c in dict.fromkeys(columns))
        if any(s.privacy for s in specs) and not acknowledge_local_path:
            raise ValueError(f"勾了「本机绝对路径」—— {LOCAL_PATH_WARNING}，"
                             "这一列要有显式确认才写")
        return specs

    def _resolve_format(self, fmt: str) -> str:
        if fmt not in _FORMAT_BY_KEY:
            raise ValueError(f"未知格式 {fmt!r}；可选 {[k for k, _, _ in FORMATS]}")
        return _FORMAT_BY_KEY[fmt][1]

    def _target(self, dest_dir: Path, name_path: str, ext: str) -> Path:
        if not dest_dir.is_dir():
            raise ValueError(f"目标目录不存在或不是一个目录：{dest_dir}")
        stem = "_".join(sanitize_component(part) for part in name_path.split("/") if part)
        return dest_dir / f"分类清单_{stem}_{format_day(now_ts())}.{ext}"


def _write_no_clobber(target: Path, text: str) -> None:
    """同名产物已存在就拒，不覆盖。

    同一天对同一枝导出两次会得到**同一个文件名**（日期在名字里），第二次如果静默盖掉第一次，
    用户手里那份"上午的清单"就没了 —— 而屏幕上只会说"已导出"。这是不可逆动作，按 S6 备份
    「覆盖前先说」的同一条纪律处理：直接拒绝，让用户改名或删掉旧的。
    写经 `.part` 再 `os.replace`：中途失败留下的是半截的 `.part`，不是一份看起来完整的坏文件。
    """
    if target.exists():
        raise ValueError(f"目标文件已存在，不覆盖：{target.name}")
    part = target.with_name(target.name + ".part")
    try:
        # `newline=""` 是 csv 模块自己要求的（否则它会把 `\r\n` 再翻一遍）；
        # CSV 带 BOM 是给 Excel 的：无 BOM 时 Excel 按本地代码页读，整列中文文件名成乱码（实测）。
        encoding = "utf-8-sig" if target.suffix == ".csv" else "utf-8"
        with part.open("w", encoding=encoding, newline="") as fh:
            fh.write(text)
        os.replace(part, target)
    finally:
        if part.exists():
            part.unlink(missing_ok=True)


def _render_csv(rows: Sequence[Document], specs: Sequence[Column], batch: RowContext) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf)                 # 逗号/引号/换行交给 csv 模块，不自己拼串
    writer.writerow([s.label for s in specs])
    for doc in rows:
        writer.writerow([s.value(doc, batch) for s in specs])
    return buf.getvalue()


def _render_json(rows: Sequence[Document], specs: Sequence[Column], batch: RowContext) -> str:
    payload = [{s.label: s.value(doc, batch) for s in specs} for doc in rows]
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


def _render_markdown(rows: Sequence[Document], specs: Sequence[Column], batch: RowContext) -> str:
    def cell(v: object) -> str:
        return str(v).replace("|", "\\|")   # 表格里漏转义的竖线会把一行切成两列
    lines = ["| " + " | ".join(s.label for s in specs) + " |",
             "| " + " | ".join("---" for _ in specs) + " |"]
    lines += ["| " + " | ".join(cell(s.value(doc, batch)) for s in specs) + " |" for doc in rows]
    return "\n".join(lines) + "\n"


_RENDERERS = {"csv": _render_csv, "json": _render_json, "markdown": _render_markdown}
