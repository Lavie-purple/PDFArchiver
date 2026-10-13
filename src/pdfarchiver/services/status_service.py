"""把"现在库到底是什么状态"算给界面看。

阶段 1 的界面外壳只允许显示**能算出来的事实**：条数、版本、路径、完整性。
任何进度百分比、任何"就绪/正常"的笼统结论都不许出现在这里，因为没有东西在跑。
"""
from __future__ import annotations

from dataclasses import dataclass

from pdfarchiver.db.engine import Engine
from pdfarchiver.db.migrate import current_version
from pdfarchiver.db.repositories.catalog import CatalogRepository
from pdfarchiver.db.repositories.documents import DocumentRepository
from pdfarchiver.db.repositories.jobs import JobRepository
from pdfarchiver.db.repositories.roots import RootRepository
from pdfarchiver.db.repositories.settings import SettingsRepository


@dataclass(frozen=True)
class CatalogStatus:
    schema_version: int
    documents: int
    missing_documents: int
    categories: int
    tags: int
    roots: int
    jobs_by_state: dict[str, int]
    app_setting_keys: int
    integrity: str
    db_path: str

    def lines(self) -> list[str]:
        """给人读的固定顺序清单。空库要能一眼看出是空的（0 而不是"无数据"字样）。"""
        jobs = ", ".join(f"{k}={v}" for k, v in sorted(self.jobs_by_state.items())) or "无任务"
        return [
            f"结构版本 schema_version = {self.schema_version}",
            f"文档主记录 = {self.documents}（其中标记缺失 {self.missing_documents}）",
            f"分类 = {self.categories}，标签 = {self.tags}",
            f"监测根目录 = {self.roots}",
            f"任务 = {jobs}",
            f"应用内部状态条数 = {self.app_setting_keys}",
            f"完整性检查 integrity_check = {self.integrity}",
            f"库文件 = {self.db_path}",
        ]


class StatusService:
    """界面与自检页共用的唯一取数口。不做缓存 —— 阶段 1 的量级不值得缓存，缓存只会让"读到旧数"变成 bug。"""

    def __init__(self, engine: Engine, documents: DocumentRepository, catalog: CatalogRepository,
                 roots: RootRepository, jobs: JobRepository, app_settings: SettingsRepository) -> None:
        self.engine = engine
        self.documents = documents
        self.catalog = catalog
        self.roots = roots
        self.jobs = jobs
        self.app_settings = app_settings

    def read(self) -> CatalogStatus:
        conn = self.engine.thread_connection()
        return CatalogStatus(
            schema_version=current_version(conn),
            documents=self.documents.count(),
            missing_documents=self.documents.count_missing(),
            categories=self.catalog.count_categories(),
            tags=self.catalog.count_tags(),
            roots=self.roots.count(),
            jobs_by_state=self.jobs.counts_by_state(),
            app_setting_keys=self.app_settings.count(),
            integrity=self.engine.integrity_check(),
            db_path=str(self.engine.path),
        )
