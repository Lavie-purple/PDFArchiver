r"""真实语料首扫 —— Priority 2 的主导交付物。

把 p0 普查过的 6 个盘符根注册为监测根，跑一场全量扫描，记录：
- 每阶段耗时（目录遍历 / 主记录 upsert / 正文抽取 / 全文索引）
- 峰值 RSS
- 任务队列排空时间
- 错误计数与原文

输出落在 `<数据根>\logs\first_scan_report.json`，同时打印关键数字到 stdout。
这场扫描的预期量级：7,768 份 / 120.6GB / ~200 万页。
按 p2 的 302.5 页/s 抽取速度，纯抽取约 110 分钟；加索引与哈希，总耗时预期 2–3 小时。

用法：
    python scripts/real_corpus_first_scan.py
    python scripts/real_corpus_first_scan.py --data-dir D:\\pdfdata
    python scripts/real_corpus_first_scan.py --roots C:/Users/xxx D:/ E:/   # 只扫指定根
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import sys
import time
import traceback
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Sequence

# 把 src/ 挂进 sys.path（与 conftest.py 同一套）
_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent / "src"))

import psutil  # noqa: E402

from pdfarchiver.app import bootstrap  # noqa: E402
from pdfarchiver.config.paths import AppPaths  # noqa: E402
from pdfarchiver.db.repositories.documents import DocumentRepository  # noqa: E402
from pdfarchiver.db.repositories.jobs import JobRepository  # noqa: E402
from pdfarchiver.db.repositories.roots import RootRepository  # noqa: E402
from pdfarchiver.db.repositories.text import TextRepository  # noqa: E402
from pdfarchiver.db.repositories.metadata import MetadataRepository  # noqa: E402
from pdfarchiver.fs.identity import identity_key  # noqa: E402
from pdfarchiver.services.scan_service import ScanService  # noqa: E402
from pdfarchiver.services.index_service import IndexService  # noqa: E402

# p0 普查用过的 6 个根（VERIFICATION.md 4.1）
DEFAULT_ROOTS = [
    Path(os.path.expanduser("~")),  # C:/Users/<当前用户>
    Path("D:/"),
    Path("E:/"),
    Path("F:/"),
    Path("G:/"),
    Path("H:/"),
]


@dataclass
class PhaseTiming:
    phase: str
    started_at: float
    ended_at: float
    took_s: float
    note: str = ""


@dataclass
class FirstScanReport:
    started_at: str
    data_root: str
    roots_registered: list[str]
    phases: list[PhaseTiming] = field(default_factory=list)
    total_pdf_found: int = 0
    total_added: int = 0
    total_changed: int = 0
    total_errors: int = 0
    error_messages: list[str] = field(default_factory=list)
    peak_rss_mb: float = 0.0
    queue_drained_at: float = 0.0
    final_schema_version: int = 0
    verdict: str = "UNKNOWN"

    def to_dict(self) -> dict:
        d = asdict(self)
        d["phases"] = [asdict(p) for p in self.phases]
        return d


def _get_rss_mb() -> float:
    return psutil.Process().memory_info().rss / 1024 / 1024


def _phase(report: FirstScanReport, phase_name: str, note: str = ""):
    """上下文管理器风格的阶段计时。用法：with _phase(report, 'xxx'): ..."""
    class _Ctx:
        def __enter__(self_inner):
            self_inner.t0 = time.time()
            return self_inner
        def __exit__(self_inner, exc_type, exc_val, exc_tb):
            t1 = time.time()
            report.phases.append(PhaseTiming(
                phase=phase_name,
                started_at=self_inner.t0,
                ended_at=t1,
                took_s=round(t1 - self_inner.t0, 3),
                note=note,
            ))
            rss = _get_rss_mb()
            if rss > report.peak_rss_mb:
                report.peak_rss_mb = round(rss, 1)
            print(f"  [{phase_name}] {report.phases[-1].took_s:.1f}s  (RSS {rss:.0f}MB)")
            return False
    return _Ctx()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data-dir", type=Path, default=None,
                    help="数据根目录（默认 %LOCALAPPDATA%/PdfArchiver）")
    ap.add_argument("--roots", nargs="+", type=Path, default=None,
                    help="只扫指定的根（覆盖 DEFAULT_ROOTS）")
    ap.add_argument("--dry-run", action="store_true",
                    help="只注册根、不真跑扫描（验证配置）")
    args = ap.parse_args()

    roots_to_scan: Sequence[Path] = args.roots or DEFAULT_ROOTS
    print(f"=== 真实语料首扫 ===")
    print(f"Python {sys.version.split()[0]} | {platform.system()} {platform.release()}")
    print(f"CPU 逻辑核: {os.cpu_count()}")
    print(f"内存: {psutil.virtual_memory().total / 1024**3:.1f}GB 可用 {psutil.virtual_memory().available / 1024**3:.1f}GB")
    print(f"待扫根: {len(roots_to_scan)} 个")
    for r in roots_to_scan:
        exists = "[OK]" if r.exists() else "[MISSING]"
        print(f"  - {r}  {exists}")
    print()

    report = FirstScanReport(
        started_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        data_root="",
        roots_registered=[str(r) for r in roots_to_scan],
    )

    # Phase 0: bootstrap
    with _phase(report, "bootstrap"):
        ctx = bootstrap(args.data_dir)
        report.data_root = str(ctx.paths.root)
        print(f"数据根: {ctx.paths.root}")
        print(f"库文件: {ctx.paths.catalog_db}")
        print(f"日志目录: {ctx.paths.logs_dir}")

    try:
        # Phase 1: register roots
        with _phase(report, "register_roots"):
            root_repo = RootRepository(ctx.engine)
            for root_path in roots_to_scan:
                if not root_path.exists():
                    print(f"  跳过不存在的根: {root_path}")
                    continue
                # ISSUES I89 甲：原先写 `str(root_path)`（`C:\Users\lavie`），绕开了
                # `bootstrap.register_root()`，登记的根键与全库子树查询用的 identity_key 口径
                # （`c:/users/lavie`）分家，导致真库六个根"下面有哪些文档"恒返回 0 条。
                root_key = identity_key(str(root_path))
                existing = root_repo.by_key(root_key)
                if existing is None:
                    root_repo.add(root_path=str(root_path), root_key=root_key)
                    print(f"  [NEW] {root_key}")
                else:
                    print(f"  [EXISTS] {root_key} (enabled={existing.enabled})")

        if args.dry_run:
            print("\n--dry-run 模式，不执行扫描。")
            report.verdict = "DRY_RUN"
            _write_report(ctx.paths, report)
            return 0

        # Phase 1.5: start background workers
        with _phase(report, "start_workers", note="启动 worker 线程 + 事件监听 + 断点续扫"):
            queue = ctx.start_background()
            print(f"  Worker 线程已启动")

        # Phase 2: full scan
        with _phase(report, "full_scan", note="目录遍历 + 主记录 upsert"):
            doc_repo = DocumentRepository(ctx.engine)
            root_repo = RootRepository(ctx.engine)
            job_repo = JobRepository(ctx.engine)
            scan_svc = ScanService(doc_repo, root_repo, job_repo)
            scan_results = []
            enabled_roots = root_repo.list_enabled()
            print(f"启用的监测根: {len(enabled_roots)} 个")
            for monitored_root in enabled_roots:
                root_path = Path(monitored_root.root_path)
                if not root_path.exists():
                    print(f"\n跳过不存在的根: {monitored_root.root_key}")
                    continue
                print(f"\n扫描根: {monitored_root.root_key}")
                result = scan_svc.scan_root(monitored_root)
                scan_results.append(result)
                print(f"  PDF 发现: {result.pdfs}")
                print(f"  新增: {result.added}  变更: {result.changed}  未变: {result.unchanged}")
                print(f"  错误: {result.error_count}")
                if result.errors:
                    for err in result.errors[:5]:
                        print(f"    - {err}")
                    if len(result.errors) > 5:
                        print(f"    ... 还有 {len(result.errors) - 5} 条")

            report.total_pdf_found = sum(r.pdfs for r in scan_results)
            report.total_added = sum(r.added for r in scan_results)
            report.total_changed = sum(r.changed for r in scan_results)
            report.total_errors = sum(r.error_count for r in scan_results)
            report.error_messages = []
            for r in scan_results:
                report.error_messages.extend(r.errors[:10])  # 每根最多留 10 条

        # Phase 3: wait for index queue to drain
        with _phase(report, "index_drain", note="等待正文抽取 + FTS 索引队列排空"):
            text_repo = TextRepository(ctx.engine)
            meta_repo = MetadataRepository(ctx.engine)
            index_svc = IndexService(doc_repo, text_repo, meta_repo)
            max_wait_s = 3600  # 最多等 1 小时
            poll_interval_s = 5
            waited_s = 0
            while waited_s < max_wait_s:
                # Count documents that still need indexing
                conn = ctx.engine.thread_connection()
                pending_row = conn.execute(
                    "SELECT COUNT(*) FROM documents WHERE missing_since IS NULL AND fts_status IN ('pending', 'stale')"
                ).fetchone()
                pending = pending_row[0] if pending_row else 0
                if pending == 0:
                    print(f"  队列已排空（等了 {waited_s:.0f}s）")
                    report.queue_drained_at = waited_s
                    break
                if waited_s % 60 == 0 and waited_s > 0:
                    print(f"  待索引: {pending}  已等 {waited_s:.0f}s  RSS {_get_rss_mb():.0f}MB")
                time.sleep(poll_interval_s)
                waited_s += poll_interval_s
            else:
                print(f"  超时：{max_wait_s}s 后仍有 {pending} 条未索引")
                report.verdict = "TIMEOUT"

        # Phase 4: final stats
        with _phase(report, "final_stats"):
            conn = ctx.engine.thread_connection()
            doc_count = conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
            indexed_count = conn.execute(
                "SELECT COUNT(*) FROM documents WHERE fts_status = 'done'"
            ).fetchone()[0]
            schema_ver = conn.execute(
                "SELECT version FROM schema_version"
            ).fetchone()[0]
            report.final_schema_version = schema_ver
            print(f"\n=== 最终统计 ===")
            print(f"文档主记录: {doc_count}")
            print(f"已索引正文: {indexed_count}")
            print(f"结构版本: {schema_ver}")
            print(f"峰值 RSS: {report.peak_rss_mb:.0f}MB")

        if report.verdict != "TIMEOUT":
            report.verdict = "ALL_GREEN" if report.total_errors == 0 else "WITH_ERRORS"

        _write_report(ctx.paths, report)
        print(f"\n报告已写入: {ctx.paths.logs_dir / 'first_scan_report.json'}")
        print(f"VERDICT: {report.verdict}")

        ctx.shutdown()
        return 0 if report.verdict in ("ALL_GREEN", "WITH_ERRORS") else 1

    except Exception:
        traceback.print_exc()
        report.verdict = "CRASHED"
        if "ctx" in locals():
            _write_report(ctx.paths, report)
            ctx.shutdown()
        return 2


def _write_report(paths: AppPaths, report: FirstScanReport) -> None:
    out = paths.logs_dir / "first_scan_report.json"
    out.write_text(json.dumps(report.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
