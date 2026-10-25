"""启动装配：目录 → 日志 → 设置 → 连接 → 迁移 → 默认模板 → 自检。

顺序是有意的，两条规矩写在这里：
1. **日志早于任何可能失败的事**。设置文件坏了、库打不开，都得先留下原文（SPEC 4.3、AGENTS.md 排障条）。
2. **迁移早于任何读写**。仓储层假设表存在；表不存在时的报错是"no such table"，对人没有诊断价值，
   而"迁移失败 + 快照路径"才有。

阶段 1 不做的事：不扫描目录、不建全文索引、不起 worker、不连 GPU。
阶段 2 把扫描/索引的服务对象**装配好**了，但仍然不在这里起线程：
`bootstrap()` 只负责"依赖齐不齐"，`AppContext.start_background()` 才决定"跑不跑" ——
界面测试和只看库状态的调用方不该被两个 worker 线程和文件监听拖住。
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
from pdfarchiver.db.models import MonitoredRoot
from pdfarchiver.db.repositories.catalog import CatalogRepository
from pdfarchiver.db.repositories.collections import CollectionRepository
from pdfarchiver.db.repositories.documents import DocumentRepository
from pdfarchiver.db.repositories.jobs import JobRepository
from pdfarchiver.db.repositories.metadata import MetadataRepository
from pdfarchiver.db.repositories.operations import OperationRepository
from pdfarchiver.db.repositories.roots import RootRepository
from pdfarchiver.db.repositories.settings import SettingsRepository
from pdfarchiver.db.repositories.text import TextRepository
from pdfarchiver.diagnostics.logs import install_crash_hooks, setup_logging, state_event
from pdfarchiver.fs.exclude import Exclusions
from pdfarchiver.fs.identity import identity_key, normalize_path
from pdfarchiver.fs.watcher import EventBuffer, WatchManager
from pdfarchiver.jobs.queue import DEFAULT_MAX_ATTEMPTS, WorkQueue
from pdfarchiver.ocr.budget import OcrBudget
from pdfarchiver.ocr.engine import OcrEngine, OcrUnavailable
from pdfarchiver.search.service import SearchService
from pdfarchiver.semantic.search_service import SemanticSearchService
from pdfarchiver.semantic.classify_service import AIClassifyService
from pdfarchiver.semantic.embedding import EmbeddingService
from pdfarchiver.semantic.vector_store import VectorStore
from pdfarchiver.services.archive_service import ArchiveService
from pdfarchiver.services.backup_service import BackupService
from pdfarchiver.services.collection_service import CollectionService
from pdfarchiver.services.default_catalog import SeedResult, seed_default_categories
from pdfarchiver.services.dedup_service import DedupService
from pdfarchiver.services.db_check import DbCheckService
from pdfarchiver.services.export_service import ExportService
from pdfarchiver.services.index_service import IndexService
from pdfarchiver.services.ocr_service import OcrService
from pdfarchiver.services.vector_service import VectorService
from pdfarchiver.services.patrol import Patrol
from pdfarchiver.services.scan_service import ScanService
from pdfarchiver.services.session_service import SessionService
from pdfarchiver.services.status_service import StatusService

log = logging.getLogger("pdfarchiver.bootstrap")


@dataclass(frozen=True)
class BackgroundState:
    """后台此刻的状态读数。没起线程时也要能回答，好让界面把"没启动"说成一句事实而不是留白。

    存在的全部理由：`queue` 与 `watch` 不在界面可用字段清单里（见 `AppContext` 文档），
    而 worker 数、监听根数、事件积压这三样正是阶段 2 第 10 项要显示的内容。
    """

    running: bool
    worker_threads: int
    max_attempts: int
    watched_roots: int
    watcher_alive: bool
    pending_events: int

    def lines(self) -> list[str]:
        if not self.running:
            return ["  后台未启动：没有 worker 线程、没有文件监听，任务行只会被排进队列而没人领"]
        out = [f"  后台：worker 线程 {self.worker_threads}｜监听根 {self.watched_roots}"
               f"｜事件缓冲待处理 {self.pending_events}"]
        if not self.watcher_alive and self.watched_roots:
            # 线程死了不会有任何报错：根还列着、队列还在跑，只有事件不再进来。
            # 不说出来，"改了文件但程序没反应"就只能靠人猜。
            out.append("  ⚠ 文件监听线程已不在：磁盘变化只能等周期校验，最快 "
                       "也要到下一轮全量对账")
        return out


@dataclass
class AppContext:
    """一次启动的全部运行时依赖。UI 只认这个对象，不自己拼路径、不自己开连接。

    界面**只许用** `paths` / `settings` / `status` / `session` / `scan` / `indexer` / `search` /
    `semantic_search` / `ai_classify` / `ocr` / `vector` / `dedup` / `backup` / `collection` /
    `patrol` / `archive` / `export` / `db_check` 这些**服务字段**（`archive` 是阶段 4 的归档与撤销入口，
    `collection` 是 **ISSUES I78** 乙的智能集合入口，`export` 是 **ISSUES I78** 丙 的分类清单导出入口，
    `db_check` 是 S7「库体检」面板的唯一取数口 —— 它自己持有 `HealthRepository` 与
    `app_settings`，界面不再直接写 SQL），
    以及 `background_state()`、
    `register_root()`、`unregister_root()`；`documents` / `catalog` / `collections` / `roots` /
    `jobs` / `texts` / `metadata` / `app_settings` / `operations` 是仓储对象，本该是给服务层和测试用的，
    但今天界面确实在直接取其中几个（S1/S8 读 `ctx.catalog` 的分类标签清单、S7 读 `ctx.roots` 的根表）——
    这一条现状写在这里而不是装作已经收干净，新写的读数一律优先走上面那些服务字段。
    `queue` / `watch` / `events` 是**私有运行时**，
    界面要那三样的数字就走 `background_state()`，不许自己摸线程对象 —— 所以登记/移除监测根走上面
    那两个方法而不是 `ctx.roots` 加 `ctx.watch`：漏掉 `watch()` 的话新登记的根**从此只有周期校验
    在管，实时事件一条收不到**，而界面上完全看不出来。

    `ocr` 是阶段 5 的服务入口，**故意不在上面那份界面可用清单里**：OCR 的入口界面还没经线框确认
    （AGENTS.md），现在只有测试与门禁通过它排队。装配无条件进行、引擎惰性加载，
    没装可选层的应用照旧能扫描与全文检索。

    `watch` / `queue` 在 `start_background()` 之前是 None —— 阶段 1 的界面测试
    和"只看库"的调用方不该被起线程这件事拖住，也不该在没人要扫描时占着两个 worker。
    """

    paths: AppPaths
    settings: Settings
    engine: Engine
    migration: MigrationReport
    seed: SeedResult
    documents: DocumentRepository
    catalog: CatalogRepository
    collections: CollectionRepository
    operations: OperationRepository
    roots: RootRepository
    jobs: JobRepository
    texts: TextRepository
    metadata: MetadataRepository
    app_settings: SettingsRepository
    status: StatusService
    session: SessionService
    scan: ScanService
    indexer: IndexService
    search: SearchService
    semantic_search: SemanticSearchService
    ai_classify: AIClassifyService
    ocr: OcrService
    vector: VectorService
    archive: ArchiveService
    dedup: DedupService
    backup: BackupService
    collection: CollectionService
    export: ExportService
    patrol: Patrol
    db_check: DbCheckService
    events: EventBuffer
    bootstrap_seconds: float
    schema_version: int
    watch: WatchManager | None = None
    queue: WorkQueue | None = None
    _closed: bool = field(default=False, repr=False)

    def start_background(self) -> WorkQueue:
        """起 worker 线程 + 事件监听 + 断点续扫。重复调用返回同一个队列（幂等）。

        顺序是硬的：`recover()` 必须早于 `start()`（否则上次被杀留下的 `running` 行
        会被当成"还在跑"而永远没人领），`watch()` 必须早于首次扫描（否则全量扫描期间
        新落盘的文件没人记事件，只能等下一次周期校验）。
        """
        if self.queue is not None:
            return self.queue
        self.queue = WorkQueue(self.jobs,
                               {"scan": self.scan.handle, "index": self.indexer.handle,
                                "ocr": self.ocr.handle, "vector": self.vector.handle,
                                "archive": self.archive.handle,
                                "dedup": self.dedup.handle},
                               engine=self.engine, threads=int(self.settings["worker_threads"]))
        recovered = self.queue.recover()
        resuming = self.scan.resume_pending()
        self.watch = WatchManager(self.events)
        for root in self.roots.list_enabled():
            self.watch.watch(root.root_path, root.root_key)
        self.watch.start()
        self.queue.start()
        state_event(self.paths.logs_dir, "background.started",
                    threads=int(self.settings["worker_threads"]),
                    recovered=recovered["requeued"], resume_index=resuming,
                    watched=len(self.watch.observed_roots))
        log.info("后台已启动：worker %d，监听根 %d，回收中断 %d，续排索引 %d",
                 self.queue.thread_count, len(self.watch.observed_roots),
                 recovered["requeued"], resuming)
        return self.queue

    def register_root(self, raw_path: str | Path) -> MonitoredRoot:
        """S7「添加目录…」的唯一入口：登记 = 写 `monitored_roots` + 挂上监听。

        `roots.add` 对同一路径幂等并重开 `enabled=1`（`ON CONFLICT ... DO UPDATE`），所以重复
        添加是"重新启用"而不是报错；重复添加也不会多出一行。
        """
        path = normalize_path(raw_path)
        root = self.roots.add(path, identity_key(path), label=Path(path).name)
        if self.watch is not None:
            self.watch.watch(root.root_path, root.root_key)
        log.info("已登记监测根：%s", root.root_path)
        return root

    def unregister_root(self, root_key: str) -> bool:
        """只撤监测：磁盘上的文件不动，库里的文档主记录与分类标注也不删
        （`RootRepository.remove` 的同一口径）。"""
        removed = self.roots.remove(root_key)
        if removed and self.watch is not None:
            self.watch.unwatch(root_key)
        log.info("已移除监测根：%s（%s）", root_key, "移除" if removed else "本就不在列表里")
        return removed

    def background_state(self) -> BackgroundState:
        """后台此刻的只读快照；`start_background()` 之前 `running=False`，其余取零值。"""
        if self.queue is None:
            return BackgroundState(running=False, worker_threads=0, max_attempts=DEFAULT_MAX_ATTEMPTS,
                                   watched_roots=0, watcher_alive=False,
                                   pending_events=self.events.snapshot()["pending"])
        return BackgroundState(running=True, worker_threads=self.queue.thread_count,
                               max_attempts=self.queue.max_attempts,
                               watched_roots=len(self.watch.observed_roots) if self.watch else 0,
                               watcher_alive=bool(self.watch.is_alive()) if self.watch else False,
                               pending_events=self.events.snapshot()["pending"])

    def shutdown(self) -> None:
        """停后台、关连接并留下对账行。重复调用不报错（Qt 的 aboutToQuit 可能和显式关闭都来一次）。"""
        if self._closed:
            return
        self._closed = True
        if self.watch is not None:
            self.watch.stop()
        if self.queue is not None:
            if not self.queue.stop():
                log.warning("有 worker 未按时退出，其任务行留在 running 等下次回收")
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
    collections = CollectionRepository(engine)
    operations = OperationRepository(engine)
    app_settings = SettingsRepository(engine)
    seed = seed_default_categories(catalog, app_settings)
    documents = DocumentRepository(engine)
    roots = RootRepository(engine)
    jobs = JobRepository(engine)
    texts = TextRepository(engine)
    metadata = MetadataRepository(engine)
    status = StatusService(engine, documents, catalog, roots, jobs, app_settings, texts)
    session = SessionService(app_settings)

    events = EventBuffer()
    scan = ScanService(documents, roots, jobs, exclusions=Exclusions.of())
    indexer = IndexService(documents, texts, metadata)
    search = SearchService(documents, metadata, texts)
    embedding = EmbeddingService(paths.root)
    # **ISSUES I111** 甲：全进程只许一只 `VectorStore`。以前这里先建语义搜索（它自己 new 一只）
    # 再另建一只注入写路径，于是写侧落的向量在读侧那只的缓存里永远看不见 —— 刚建完向量当场搜不到，
    # 只有重启才好。由 `bootstrap` 建好再注入，谁读谁写都是同一只。
    # **ISSUES I111** ⑤：`embedding` 同样只养一份。第二份 ONNX session 实测 +36.2 MiB RSS、
    # +9 句柄、约 +200 MiB 显存（DirectML），懒加载 276 ms；两个实例的输出逐位相同。
    vector_store = VectorStore(paths.root)
    semantic_search = SemanticSearchService(paths.root, vector_store, embedding)
    ai_classify = AIClassifyService(catalog, documents, embedding, vector_store)
    ocr_engine = OcrEngine()
    ocr = OcrService(documents, texts, jobs, ocr_engine,
                     OcrBudget(app_settings, int(settings["ocr_daily_page_budget"])))
    # 向量写路径（**ISSUES I63** 丙 + 丁）：构造不加载模型 —— embedding 的 ONNX session 是
    # 首次 embed 才 `_ensure_session`，与 OCR 的"到首次识别才加载"同一条冷启动纪律。
    vector = VectorService(documents, texts, jobs, embedding, vector_store)
    # 只在启动时读一次发行包元数据（微秒级），**不 import onnxruntime** —— 那一下是 1s 量级，
    # 冷启动门禁 G1（≤1.5s）就是被它顶掉的（docs/ISSUES）。真正的加载发生在首次识别的 ensure() 里。
    try:
        log.info("OCR 层可用，版本指纹 %s（引擎与模型要到首次识别才加载）", ocr_engine.version_stamp)
    except OcrUnavailable as exc:  # 消息本身就是"缺哪个包、怎么装"，原样写进日志
        log.warning("OCR 层不可用，扫描与全文检索照旧：%s", exc)
    archive = ArchiveService(operations, documents, paths, catalog, jobs)
    dedup = DedupService(documents, jobs)
    backup = BackupService(paths, engine)
    collection = CollectionService(collections, documents)
    export = ExportService(documents, catalog, operations)
    patrol = Patrol(scan, jobs, events, poll_seconds=int(settings["scan_poll_seconds"]),
                    verify_minutes=int(settings["scan_verify_minutes"]))
    # S7「库体检」（#198）：构造零成本，真正取数在用户点按钮时发生 ——
    # `expected_version` 用迁移目标版本而不是当前版本，这样 C0 才是在问
    # "水位有没有停在本版"，而不是拿自己跟自己比。
    db_check = DbCheckService(engine, app_settings, paths.backups_dir,
                              expected_version=report.to_version)

    # 启动路径**不跑任何同步库检查**（AGENTS.md 禁止启动阻塞）：
    # PRAGMA integrity_check 在 6.1GB 真语料库上实测 19 小时+未完，
    # quick_check 冷/热缓存各实测 452s / 478s —— 都与库同量级，谁都躲不掉。
    # 库健康核查的唯一入口是离线探针 p12（tests/probes/p12_consistency.py，可自行限速）；
    # 真损坏时第一条坏 SQL 会以 error + 原文进日志，不会静默。
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
                      documents=documents, catalog=catalog, collections=collections,
                      operations=operations, roots=roots, jobs=jobs, texts=texts, metadata=metadata,
                      app_settings=app_settings, status=status, session=session,
                      scan=scan, indexer=indexer, search=search,
                      semantic_search=semantic_search, ai_classify=ai_classify,
                      ocr=ocr, vector=vector, archive=archive,
                      dedup=dedup, backup=backup, collection=collection, export=export,
                      patrol=patrol, events=events, db_check=db_check,
                      bootstrap_seconds=elapsed, schema_version=schema_version)
