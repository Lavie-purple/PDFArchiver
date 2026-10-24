"""库体检服务 —— S7「库体检」面板的唯一取数与判定口（1甲 2甲 3甲 4甲，2026-10-24 定案）。

四件事只在这里定：

- **两档**：`quick` 只读小表与索引、不发 PRAGMA、不扫正文，真库实测十几秒；`full` 在它之上再跑
  正文页扫描、花名册双向对账、`integrity_check / foreign_key_check` 与最新快照整库体检。
  真库（11GB / 正文 1,975,611 行）同口径两场实测的四个慢项：C1 1,037,900→1,200,867ms、
  C5 1,241,146→1,541,084ms、C11 961,441→1,036,524ms、C4 218,742→259,539ms，
  合计 **57 → 67 分钟**（`docs/VERIFICATION-RUNLOGS.md` §4.33 与 §4.35；差额是机器负载，不是库变大）。
- **只报证据**：不自动重跑索引、不修库、不动文件；红行只说明查到什么、原文是什么。
- **只存上次时间与计数**：`app_settings["db_check.last"]` 里是
  `{ts, mode, total, red, readings, elapsed_s}`，明细不落盘（4甲）。
- **口径与 p12 同源**：C0/C2/C4/C5/C6/C7/C8/C9/C10/C12/C13 的判据逐条对齐
  `tests/probes/p12_consistency.py`；C9 在应用运行中只当**读数**（不是判定）——
  p12 那条「无进程时不许有 running 残留」的前提是应用已停。

界面只调 `run(mode)` 并把 `DbCheckReport.rows` 原样铺进表里，不自己算任何数。
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from pathlib import Path

from pdfarchiver.db.engine import Engine
from pdfarchiver.db.models import now_ts
from pdfarchiver.db.repositories.health import (
    OPERATION_DOMAINS,
    VECTOR_LEGAL,
    HealthRepository,
)
from pdfarchiver.db.repositories.settings import SettingsRepository
from pdfarchiver.fs.identity import identity_key
from pdfarchiver.services.default_catalog import DEFAULT_CATEGORY_TEMPLATE

log = logging.getLogger("pdfarchiver.services.db_check")

QUICK = "quick"
FULL = "full"
MODE_LABELS = {QUICK: "快速体检", FULL: "全库体检"}
LAST_KEY = "db_check.last"

QUICK_COST = ("快速体检：结构版本、路径键、正文行数、四组状态取值域、页码、分类树、根键。"
              "不发 PRAGMA、不读正文；11GB 真库实测约 12 秒。")
FULL_COST = ("全库体检 = 快速体检 + 正文页扫描（字数/NUL/来源）+ 索引花名册双向对账 + "
             "integrity_check / foreign_key_check + 最新快照整库体检。"
             "11GB 真库同口径两次实测：约 57 分钟与约 67 分钟（慢的四项 C1 约 17–20 分、"
             "C5 约 21–26 分、C11 约 16–17 分、C4 约 4 分），运行期间不可中断。")


def format_duration(seconds: float) -> str:
    """秒 → 给人读的时长。不用 `format_ts`：这不是时刻，是长度。"""
    total = max(0, int(round(seconds)))
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours} 时 {minutes} 分 {secs} 秒"
    if minutes:
        return f"{minutes} 分 {secs} 秒"
    return f"{secs} 秒"


@dataclass(frozen=True)
class CheckRow:
    """一行体检结论。`ok=None` = 读数（应用运行中语义不成立，或环境里没有可对的东西）。"""

    code: str
    label: str
    ok: bool | None
    measured: str
    seconds: float = 0.0

    @property
    def verdict(self) -> str:
        if self.ok is None:
            return "读数"
        return "通过" if self.ok else "未通过"


@dataclass(frozen=True)
class DbCheckReport:
    mode: str
    rows: tuple[CheckRow, ...]
    started_at: int
    elapsed_s: float

    @property
    def total(self) -> int:
        return len(self.rows)

    @property
    def red(self) -> int:
        return sum(1 for r in self.rows if r.ok is False)

    @property
    def readings(self) -> int:
        return sum(1 for r in self.rows if r.ok is None)

    @property
    def passed(self) -> int:
        return sum(1 for r in self.rows if r.ok is True)

    def summary(self) -> str:
        return (f"{MODE_LABELS.get(self.mode, self.mode)} {self.total} 项｜"
                f"通过 {self.passed}｜未通过 {self.red}｜读数 {self.readings}｜"
                f"用时 {format_duration(self.elapsed_s)}")

    def failed_rows(self) -> list[CheckRow]:
        return [r for r in self.rows if r.ok is False]


def _brief(items, limit: int = 3) -> str:
    values = list(items)
    extra = f" …（共 {len(values)} 条）" if len(values) > limit else ""
    return " ｜ ".join(str(x) for x in values[:limit]) + extra


class DbCheckService:
    def __init__(self, engine: Engine, app_settings: SettingsRepository, backups_dir: Path,
                 expected_version: int) -> None:
        self.engine = engine
        self.app_settings = app_settings
        self.backups_dir = Path(backups_dir)
        self.expected_version = int(expected_version)
        self.repo = HealthRepository(engine)

    # ---- 入口 ----

    def run(self, mode: str) -> DbCheckReport:
        if mode not in MODE_LABELS:
            raise ValueError(f"未知体检档位 {mode!r}；可选 {sorted(MODE_LABELS)}")
        started = now_ts()
        t0 = time.perf_counter()
        try:
            specs = self._specs(mode)
            rows = tuple(self._one(code, label, fn) for code, label, fn in specs)
            report = DbCheckReport(mode=mode, rows=rows, started_at=started,
                                   elapsed_s=time.perf_counter() - t0)
            self._remember(report)
            log.info("库体检（%s）完成：%s", mode, report.summary())
            return report
        finally:
            # 体检跑在独立线程里，连接由这条线程自己持有；结束时必须还回去，
            # 否则每点一次就多一条到进程退出才释放的连接。
            self.engine.close_thread_connection()

    @staticmethod
    def failure_report(mode: str, exc: BaseException) -> DbCheckReport:
        """体检没跑起来（不是某条红，而是压根没开始）。原文照给，不折成"失败了"。"""
        row = CheckRow("—", "体检没跑起来", False, f"{type(exc).__name__}: {exc}")
        return DbCheckReport(mode=mode, rows=(row,), started_at=now_ts(), elapsed_s=0.0)

    def _specs(self, mode: str):
        specs = [
            ("C0", "结构版本", self._c0),
            ("C2", "主记录路径唯一", self._c2),
            ("C4", "正文与索引花名册" + ("双向对账" if mode == FULL else "行数"),
             self._c4_full if mode == FULL else self._c4_quick),
            ("C6", "状态字段取值", self._c6),
            ("C7", "向量状态取值", self._c7),
            ("C8", "文件操作状态", self._c8),
            ("C9", "队列状态（读数）", self._c9),
            ("C10", "分类树自洽", self._c10),
            ("C12", "正文页码", self._c12),
            ("C13", "监测根根键", self._c13),
        ]
        if mode == FULL:
            # C0–C13 的编号顺序与 p12 一致，只把最慢的 C11 挪到最后：
            # 它是唯一给别的库文件发 integrity_check 的一条（真库实测约 16 分钟），
            # 放在末尾才好让前十二条先出结论。
            specs.insert(1, ("C1", "库自身健康", self._c1))
            specs.insert(4, ("C5", "正文页自洽", self._c5))
            specs.append(("C11", "快照体检", self._c11))
        return specs

    def _one(self, code: str, label: str, fn):
        t0 = time.perf_counter()
        try:
            ok, measured = fn()
        except Exception as exc:  # noqa: BLE001 - 一条查不动不许带走整场体检，原文必须上屏
            ok, measured = False, f"{type(exc).__name__}: {exc}"
        return CheckRow(code, label, ok, measured, round(time.perf_counter() - t0, 3))

    def _remember(self, report: DbCheckReport) -> None:
        payload = {"ts": report.started_at, "mode": report.mode, "total": report.total,
                   "red": report.red, "readings": report.readings,
                   "elapsed_s": round(report.elapsed_s, 1)}
        try:
            self.app_settings.set(LAST_KEY, payload, kind="ui")
        except Exception as exc:  # noqa: BLE001 - 写不进上次读数不该抹掉刚跑出来的结论
            log.warning("库体检结果已得到，但上次读数没写进 app_settings：%s", exc)

    # ---- 十四条（与 p12 同口径） ----

    def _c0(self) -> tuple[bool, str]:
        at = self.repo.schema_version()
        return at == self.expected_version, \
            f"库里 v{at}｜迁移目录最新 v{self.expected_version}"

    def _c1(self) -> tuple[bool, str]:
        return self.repo.integrity()

    def _c2(self) -> tuple[bool, str]:
        rows = self.repo.document_path_keys()
        total = len(rows)
        distinct = len({key for _, key in rows})
        mismatched = [path for path, key in rows if identity_key(path) != key]
        problems = []
        if distinct != total:
            problems.append(f"{total} 行只有 {distinct} 个不同 path_key —— 唯一性被绕过过")
        if mismatched:
            problems.append(f"{len(mismatched)} 行的 path_key 不等于 identity_key(path)"
                            f"，例：{_brief(mismatched)}")
        return not problems, f"主记录 {total:,} 条｜" + \
            ("；".join(problems) if problems else "唯一性与口径两项全部一致")

    def _c4_quick(self) -> tuple[bool, str]:
        pages = self.repo.text_page_count()
        indexed = self.repo.fts_roster_count()
        ok = pages == indexed
        return ok, (f"正文 {pages:,} 行｜花名册 {indexed:,} 行｜"
                    + ("行数一致" if ok else
                       f"差 {abs(pages - indexed):,} 行 —— 索引与正文两张皮（逐行对账看全库体检）"))

    def _c4_full(self) -> tuple[bool, str]:
        pages = self.repo.text_page_count()
        indexed = self.repo.fts_roster_count()
        unindexed, stale = self.repo.fts_gaps()
        ok = pages == indexed and unindexed == 0 and stale == 0
        return ok, (f"正文 {pages:,} 行｜花名册 {indexed:,} 行｜漏索引 {unindexed}｜"
                    f"花名册残留 {stale}"
                    + ("" if ok else " —— 索引与正文两张皮，跑一次全文索引重建再对账")
                    + "｜本口径测不到倒排幽灵（免词口径全瞎，由带词的 G10 守着）")

    def _c5(self) -> tuple[bool, str]:
        total, ocr_rows = self.repo.text_page_totals()
        structure = self.repo.text_page_structure()
        char_bad = nul_bad = 0
        examples: list[str] = []
        for r in self.repo.text_page_char_candidates():
            body = r["body"]
            if "\x00" in body:
                nul_bad += 1
            if r["char_count"] != len(body):
                char_bad += 1
                examples.append(f"doc{r['doc_id']}p{r['page_no']} 记 {r['char_count']} 实际 {len(body)}")
        problems = []
        if char_bad:
            problems.append(f"{char_bad} 行的 char_count 与 Python len(body) 分家（状态页的字数是假的），"
                            f"例：{_brief(examples)}")
        if nul_bad:
            problems.append(f"{nul_bad} 行正文夹着 U+0000（SQL 侧 length/substr 会遇 NUL 即截断，"
                            f"入库前该剥掉 —— 见 ISSUES I90 乙）")
        if structure["kind_bad"]:
            problems.append(f"{structure['kind_bad']} 行的 source_kind 不在 native/ocr 之内")
        if structure["ocr_no_version"]:
            problems.append(f"{structure['ocr_no_version']} 行 OCR 正文没有 ocr_version —— "
                            f"幂等判据看不见它，下次会把同一页再烧一遍")
        if structure["native_with_version"]:
            problems.append(f"{structure['native_with_version']} 行原生正文带着 ocr_version（来源口径混了）")
        if structure["empty_body"]:
            problems.append(f"{structure['empty_body']} 行正文是空串（索引里养着零信息行）")
        return not problems, (f"正文 {total:,} 页（其中 ocr {ocr_rows:,}）｜"
                              + ("；".join(problems) if problems else "六项全部自洽"))

    def _c6(self) -> tuple[bool, str]:
        bad = self.repo.status_domain_violations()
        total = self.repo.document_count()
        problems = [f"{table}.{column} 有 {n} 行落在口径外（出现值 {values}）"
                    for table, column, n, values in bad]
        return not problems, (f"主记录 {total:,} 条｜"
                              + ("；".join(problems) if problems else
                                 "主记录四个状态列 + 队列两列全部合法"))

    def _c7(self) -> tuple[bool, str]:
        n, values = self.repo.vector_domain_violations()
        dist = self.repo.vector_status_distribution()
        non_na = sum(count for value, count in dist.items() if value != "na")
        bad = (f"documents.vector_status 有 {n} 行落在口径外（出现值 {values}｜"
               f"允许值 {sorted(VECTOR_LEGAL)}）")
        return not n, (f"非 na 的行 {non_na:,} 条｜分布 {dist or '空'}｜"
                       + (bad if n else "全部合法（产品里没人写它，所以恒为 na 或测试夹具值）"))

    def _c8(self) -> tuple[bool, str]:
        ops, items = self.repo.operation_distributions()
        bad: list[str] = []
        for table, column, legal in OPERATION_DOMAINS:
            dist = ops if table == "file_operations" else items
            for value in dist:
                if value not in legal:
                    bad.append(f"{table}.{column}='{value}' 不在口径 {sorted(legal)}")
        return not bad, (f"file_operations 分布 {ops or '空'}｜operation_items 分布 {items or '空'}｜"
                         + ("；".join(bad) if bad else "全部合法"))

    def _c9(self) -> tuple[bool | None, str]:
        dist = self.repo.job_state_distribution()
        running = dist.get("running", 0)
        return None, (f"running {running}｜各状态分布 {dist or '队列是空的'}｜"
                      + ("应用正在运行：running>0 不代表残留，本行只报读数；"
                         "停机口径由 p12 C9 判定" if running else "干净"))

    def _c10(self) -> tuple[bool, str]:
        nodes = {row["id"]: row for row in self.repo.category_rows()}
        problems: list[str] = []
        orphans = [n["name_path"] for n in nodes.values()
                   if n["parent_id"] is not None and n["parent_id"] not in nodes]
        if orphans:
            problems.append(f"{len(orphans)} 个节点的父节点不存在，例：{_brief(orphans)}")
        cycles: list[str] = []
        for node in nodes.values():
            seen = {node["id"]}
            cur = node
            while cur["parent_id"] is not None:
                parent = nodes.get(cur["parent_id"])
                if parent is None:
                    break
                if parent["id"] in seen:
                    cycles.append(node["name_path"])
                    break
                seen.add(parent["id"])
                cur = parent
        if cycles:
            problems.append(f"{len(cycles)} 个节点的父链成环（侧栏永远走不出来），例：{_brief(cycles)}")
        stale = [f"{n['name_path']} 应为 {p}/{n['name']}"
                 for n in nodes.values()
                 for p in [(nodes[n["parent_id"]]["name_path"] if n["parent_id"] in nodes else "")]
                 if n["name_path"] != (f"{p}/{n['name']}" if p else n["name"])]
        if stale:
            problems.append(f"{len(stale)} 个节点的 name_path 与父链不一致，例：{_brief(stale)}")
        dangling = self.repo.dangling_document_categories()
        if dangling:
            problems.append(f"document_categories 里 {dangling} 行指向已不存在的文档")
        template = sum(1 + len(children) for children in DEFAULT_CATEGORY_TEMPLATE.values())
        return not problems, (f"分类 {len(nodes)} 个（默认模板算出来是 {template} 个）｜"
                              + ("；".join(problems) if problems else "四项全部自洽"))

    def _c11(self) -> tuple[bool | None, str]:
        snaps = sorted(self.backups_dir.glob("*.db")) if self.backups_dir.is_dir() else []
        if not snaps:
            return None, ("backups/ 里一份快照都没有 —— 从没跑过迁移就不会有；"
                          "这一条在应用里没有可体检的对象，不是通过")
        newest = max(snaps, key=lambda p: (p.stat().st_mtime_ns, p.name))
        bad: list[str] = []
        detail: list[str] = []
        checked: list[str] = []
        for snap in snaps:
            size = snap.stat().st_size
            if size == 0:
                bad.append(f"{snap.name} 是 0 字节")
                continue
            try:
                version = self.repo.snapshot_version(snap)
            except Exception as exc:  # noqa: BLE001 - 单份打不开只判这一份，其余照跑
                bad.append(f"{snap.name} 打不开：{type(exc).__name__}: {exc}")
                continue
            detail.append(f"{snap.name} {round(size / 1024)}KiB@v{version}")
            if snap == newest:
                t0 = time.perf_counter()
                ok, measured = self.repo.snapshot_health(snap)
                checked.append(f"{snap.name} {round((time.perf_counter() - t0) * 1000)}ms")
                if not ok:
                    bad.append(f"{snap.name}：{measured}")
        scope = (f"整库体检只跑最新一份，其余 {len(snaps) - 1} 份仅开库读版本"
                 f"（旧快照内部损坏不在本口径内，ISSUES I98）")
        return not bad, (f"快照 {len(snaps)} 份｜{_brief(detail, 4)}｜整库体检 1 份：{_brief(checked, 4)}"
                         f"｜{scope}" + ("" if not bad else " ── " + "；".join(bad)))

    def _c12(self) -> tuple[bool, str]:
        over, below, dup = self.repo.page_range_counts()
        return over == 0 and below == 0 and dup == 0, \
            (f"超页 {over}｜页码 <1 {below}｜同页重复 {dup}"
             f"（page_count 的口径来自解析器；页码越界=正文与文件对不上）")

    def _c13(self) -> tuple[bool, str]:
        rows = self.repo.root_rows()
        bad = [row["root_key"] for row in rows if identity_key(row["root_key"]) != row["root_key"]]
        return not bad, (f"监测根 {len(rows)} 个｜"
                         + (f"{len(bad)} 行的 root_key 不等于 identity_key(root_key)，例：{_brief(bad)}"
                            if bad else "每行 root_key 都等于 identity_key(root_key)"))
