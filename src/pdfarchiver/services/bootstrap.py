"""启动装配：目录 → 日志 → 设置 → 连接 → 迁移 → 默认模板 → 自检。

顺序是有意的，两条规矩写在这里：
1. **日志早于任何可能失败的事**。设置文件坏了、库打不开，都得先留下原文（SPEC 4.3、AGENTS.md 排障条）。
2. **迁移早于任何读写**。仓储层假设表存在；表不存在时的报错是"no such table"，对人没有诊断价值，
   而"迁移失败 + 快照路径"才有。

阶段 1 不做的事：不扫描目录、不建全文索引、不起 worker、不连 GPU。
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path

from pdfarchiver import __version__
from pdfarchiver.config.paths import AppPaths
from pdfarchiver.config.settings import DEFAULTS, Settings, SettingsError, load
from pdfarchiver.db.engine import Engine
from pdfarchiver.db.migrate import MigrationReport, current_version, migrate
from pdfarchiver.db.repositories.catalog import CatalogRepository
from pdfarchiver.db.repositories.documents import DocumentRepository
from pdfarchiver.db.repositories.jobs import JobRepository
from pdfarchiver.db.repositories.roots import RootRepository
from pdfarchiver.db.repositories.settings import SettingsRepository
from pdfarchiver.diagnostics.logs import install_crash_hooks, setup_logging, state_event
from pdfarchiver.services.default_catalog import SeedResult, seed_default_categories
from pdfarchiver.services.session_service import SessionService
from pdfarchiver.services.status_service import StatusService

log = logging.getLogger("pdfarchiver.bootstrap")


@dataclass
class AppContext:
    """一次启动的全部运行时依赖。UI 只认这个对象，不自己拼路径、不自己开连接。

    界面**只许用** `paths` / `settings` / `status` / `session` 四个字段；
    其余的仓储对象是给服务层和测试用的，界面直取等于绕过依赖方向。
    """

    paths: AppPaths
    settings: Settings
    engine: Engine
    migration: MigrationReport
    seed: SeedResult
    documents: DocumentRepository
    catalog: CatalogRepository
    roots: RootRepository
    jobs: JobRepository
    app_settings: SettingsRepository
    status: StatusService
    session: SessionService
    bootstrap_seconds: float
    schema_version: int
    _closed: bool = field(default=False, repr=False)

    def shutdown(self) -> None:
        """关连接并留下对账行。重复调用不报错（Qt 的 aboutToQuit 可能和显式关闭都来一次）。"""
        if self._closed:
            return
        self._closed = True
        self.engine.close_thread_connection()
        state_event(self.paths.logs_dir, "shutdown", schema_version=self.schema_version)


def bootstrap(explicit_data_dir: str | Path | None = None,
              env: dict[str, str] | None = None,
              migrations_dir: Path | None = None) -> AppContext:
    """装配运行时。失败时抛原异常（DatabaseError / SettingsError），且已经先写过日志。"""
    t0 = time.perf_counter()
    paths = AppPaths.resolve(explicit_data_dir, env)
    paths.mkdirs()

    # 日志必须早于设置读取：settings.json 坏掉时，如果日志还没配好，这条错误就没人记得下来
    logger = setup_logging(paths.logs_dir, keep_files=int(DEFAULTS["log_keep_files"]))
    install_crash_hooks(paths.logs_dir)
    logger.info("PdfArchiver %s 启动中｜%s", __version__, paths.describe())
    state_event(paths.logs_dir, "startup.begin", version=__version__, data_root=str(paths.root))

    try:
        settings = load(paths.settings_file)
    except SettingsError as exc:
        log.exception("设置文件读取失败，拒绝用猜出来的配置继续启动")
        state_event(paths.logs_dir, "startup.settings_failed", error=f"{type(exc).__name__}: {exc}")
        raise
    setup_logging(paths.logs_dir, keep_files=int(settings["log_keep_files"]))
    logger.info("%s", settings.describe().replace("\n", " / "))

    engine = Engine(paths.catalog_db, busy_timeout_ms=int(settings["busy_timeout_ms"]))
    try:
        report = migrate(engine, backup_dir=paths.backups_dir, migrations_dir=migrations_dir)
    except Exception as exc:
        log.exception("迁移失败，拒绝在不确定的结构上继续运行")
        state_event(paths.logs_dir, "startup.migration_failed", error=f"{type(exc).__name__}: {exc}")
        raise

    catalog = CatalogRepository(engine)
    app_settings = SettingsRepository(engine)
    seed = seed_default_categories(catalog, app_settings)
    documents = DocumentRepository(engine)
    roots = RootRepository(engine)
    jobs = JobRepository(engine)
    status = StatusService(engine, documents, catalog, roots, jobs, app_settings)
    session = SessionService(app_settings)

    integrity = engine.integrity_check()
    if integrity != "ok":
        log.error("数据库完整性检查未通过：%s", integrity)
        state_event(paths.logs_dir, "db.integrity_problem", detail=integrity)

    if report.did_anything:
        log.info("迁移完成 %s→%s，应用 %s，快照 %s", report.from_version, report.to_version,
                 report.applied, [str(p.name) for p in report.snapshots])
        state_event(paths.logs_dir, "migration.applied", **{
            "from": report.from_version, "to": report.to_version,
            "applied": report.applied, "snapshots": [str(p) for p in report.snapshots]})
    else:
        log.info("结构版本 %d 已是最新，无迁移发生", report.to_version)

    elapsed = time.perf_counter() - t0
    schema_version = current_version(engine.thread_connection())
    log.info("装配完成，用时 %.3fs；分类 %d 个（%s）",
             elapsed, catalog.count_categories(), seed.describe())
    state_event(paths.logs_dir, "startup.done", seconds=round(elapsed, 3), schema_version=schema_version)

    return AppContext(paths=paths, settings=settings, engine=engine, migration=report, seed=seed,
                      documents=documents, catalog=catalog, roots=roots, jobs=jobs,
                      app_settings=app_settings, status=status, session=session,
                      bootstrap_seconds=elapsed, schema_version=schema_version)
