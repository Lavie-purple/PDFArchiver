"""迁移执行器：水位表 + 迁移前快照 + 单事务可回退。

三条硬规矩都来自 docs/DATABASE 四 与阶段 1 门禁：
1. 跑任何迁移**之前**必须用 Backup API 落一份 `pre-migration-<版本>-<时间戳>.db`；
2. 一个迁移 = 一个事务。中途失败要回到原样，靠的是手动 `BEGIN`，不是 sqlite3 的隐式事务
   （默认隔离级别下 DDL 何时提交不可控，所以这里显式接管）；
3. 禁止"改结构就让用户删库重来"，因此水位只增不减，迁移只往前不往后。
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from pdfarchiver.db.engine import DatabaseError, Engine
from pdfarchiver.db.migrations import Migration, discover
from pdfarchiver.db.models import now_ts

SCHEMA_TABLE = "schema_version"


class MigrationError(DatabaseError):
    """迁移失败。带着快照路径抛出，恢复时能直接指给人看。"""

    def __init__(self, msg: str, exc: BaseException, *, snapshot: Path | None = None,
                 db: str = "") -> None:
        super().__init__(msg, exc, db=db)
        self.snapshot = snapshot


@dataclass
class MigrationReport:
    from_version: int
    to_version: int
    applied: list[str] = field(default_factory=list)
    snapshots: list[Path] = field(default_factory=list)

    @property
    def did_anything(self) -> bool:
        return bool(self.applied)


def ensure_schema_table(conn: sqlite3.Connection) -> None:
    conn.execute(f"CREATE TABLE IF NOT EXISTS {SCHEMA_TABLE}(version INTEGER NOT NULL, applied_at INTEGER NOT NULL)")


def current_version(conn: sqlite3.Connection) -> int:
    ensure_schema_table(conn)
    row = conn.execute(f"SELECT max(version) FROM {SCHEMA_TABLE}").fetchone()
    return int(row[0]) if row and row[0] is not None else 0


def migrate(engine: Engine, *, backup_dir: Path | None = None,
            migrations_dir: Path | None = None) -> MigrationReport:
    """把库升到 migrations 目录里的最新版本。已是最新则什么都不做（幂等）。"""
    migrations_dir = Path(migrations_dir) if migrations_dir else Path(__file__).parent / "migrations"
    pending_all = discover(migrations_dir)
    if not pending_all:
        # 空发现必须炸在这里，而不是让应用走到后面某张表不存在时才崩 —— 那是阶段 5 冻结产物
        # 双击没起来的真实原因：打包时漏收 migrations/*.py，discover() 静默返回 []，
        # 于是"迁移成功、零条"，表一张也没建，报错落在离根因八丈远的 seed_default_categories。
        # 反向注入实测：把这段变成永假分支后，全套 340 条测试只有守卫那 1 条变红 ——
        # 也就是说没有这条守卫，整个测试套件都会放行"零迁移静默成功"。
        raise MigrationError(
            f"迁移目录里一个迁移也没有：{migrations_dir}（拒绝在零迁移下启动 —— 表不会建）",
            FileNotFoundError(str(migrations_dir)), db=str(engine.path))
    conn = engine.connect()
    try:
        conn.isolation_level = None  # 手动 BEGIN/COMMIT，见模块文档第 2 条
        before = current_version(conn)
        report = MigrationReport(from_version=before, to_version=before)
        todo = [m for m in pending_all if m.order > before]
        if not todo:
            return report
        if backup_dir is None:
            raise MigrationError("迁移前必须有快照目录（backup_dir 未提供）",
                                 ValueError("拒绝在无备份条件下改结构"), db=str(engine.path))
        for mig in todo:
            snap = _snapshot_before(engine, backup_dir, mig)
            report.snapshots.append(snap)
            try:
                _run_one(conn, mig, report, db=str(engine.path))
            except MigrationError as exc:
                exc.snapshot = snap  # 失败时把"回到原样之前的一份完整副本"指给人看
                raise
        report.to_version = current_version(conn)
        return report
    finally:
        conn.close()


def _snapshot_before(engine: Engine, backup_dir: Path, mig: Migration) -> Path:
    stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    dest = backup_dir / f"pre-migration-{mig.order:04d}-{stamp}.db"
    engine.snapshot_to(dest)
    return dest


def _run_one(conn: sqlite3.Connection, mig: Migration, report: MigrationReport, *, db: str) -> None:
    conn.execute("BEGIN IMMEDIATE")
    try:
        mig.apply(conn)
    except BaseException as exc:
        conn.rollback()
        raise MigrationError(f"迁移 {mig.label} 失败，已回滚，库回到原样", exc, db=db) from exc
    conn.execute(f"DELETE FROM {SCHEMA_TABLE}")
    conn.execute(f"INSERT INTO {SCHEMA_TABLE}(version, applied_at) VALUES(?,?)", (mig.order, now_ts()))
    conn.commit()
    report.applied.append(mig.label)
