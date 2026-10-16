"""重复检测服务 —— S5 的后端。

判重口径唯一：`documents.sha256`（字节级同哈希）。不许按文件名/大小分组（S5 定案）。
判重任务走后台队列（KINDS 已加 `dedup`，handler 注册在 bootstrap.py）。

两条硬约束：
1. **不删除任何文件**。清理动作必须走 S3→S4 的归档批次链（可预览、可撤销）。
2. **不凭空编造进度**。进度由 `ProgressMonitor.advance()` 按实际处理文件数回写，
   百分比由仓储 `done/total` 算（AGENTS.md 禁止模拟进度）。
"""
from __future__ import annotations

import logging
from pathlib import Path

from pdfarchiver.db.repositories.documents import DocumentRepository
from pdfarchiver.db.repositories.jobs import JobRepository
from pdfarchiver.fs.digest import stream_sha256
from pdfarchiver.jobs.queue import JobCancelled, ProgressMonitor

log = logging.getLogger("pdfarchiver.dedup")


class DedupService:
    """重复检测：为未算哈希的文件计算 sha256 并写入 documents 表。

    判重本身是一条 SQL 查询（`GROUP BY sha256 HAVING count(*) > 1`），不需要"跑"；
    真正耗时的是给没哈希的文件算哈希 —— 这就是 dedup 任务干的事。
    """

    def __init__(self, docs: DocumentRepository, jobs: JobRepository) -> None:
        self.docs = docs
        self.jobs = jobs

    def handle(self, job, monitor: ProgressMonitor) -> None:
        """后台队列的处理函数。为所有 `sha256 IS NULL` 且磁盘上还在的文件算哈希。

        流程：
        1. 取全部 `sha256 IS NULL AND missing_since IS NULL` 的文档 ID
        2. 逐个算 sha256（走 `fs/digest.stream_sha256`，4MB 分块，实测 240MB/s）
        3. 写回 documents 表
        4. 每处理一份 `monitor.advance(1)`，进度由仓储算百分比
        """
        rows = self.docs.list_unhashed()
        total = len(rows)
        monitor.set_total(total)

        hashed = 0
        errors = 0
        for row in rows:
            if monitor.cancelled():
                raise JobCancelled("判重被取消")
            doc_id = row["id"]
            path = Path(row["path"])
            path_key = row["path_key"]
            try:
                if not path.exists():
                    self.docs.mark_missing(path_key)
                    continue
                digest = stream_sha256(path)
                self.docs.update_sha256(doc_id, digest.sha256)
                hashed += 1
            except Exception as exc:
                log.warning("哈希失败 doc_id=%s path=%s: %s", doc_id, path, exc)
                errors += 1
            monitor.advance(1)

        log.info("判重完成：共 %d 份，成功哈希 %d，失败 %d", total, hashed, errors)
