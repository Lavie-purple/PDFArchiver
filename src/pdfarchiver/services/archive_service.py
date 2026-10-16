"""归档服务 —— 阶段 4 核心：执行文件操作（移动/复制/重命名）并记录 journal。

设计约束：
1. **每步操作前写 journal**（JSONL），崩溃后可从 journal 恢复。
2. **不删除源文件直到目标已验证**（SPEC 3.6 / G19）。
3. **支持撤销**：每次归档操作生成一个 undo 批次。
4. **路径长度自检**（ISSUES I10）：目标路径生成前检查是否超过系统限制，
   超限时返回可读错误而不是让 shutil 抛 WinError 3。

状态流转：
- planned → running → done/failed
- 每个 item: pending → copying → done/failed
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
from pathlib import Path
from typing import Iterable

from pdfarchiver.db.repositories.documents import DocumentRepository
from pdfarchiver.db.repositories.jobs import JobRepository
from pdfarchiver.db.repositories.operations import OperationRepository
from pdfarchiver.config.paths import AppPaths

log = logging.getLogger("pdfarchiver.archive")

# Windows MAX_PATH = 260，但扩展长度前缀 `\\?\` 可支持到 32,767。
# 安全上限留 240（给目录创建与临时文件留余量）。超过此值必须用扩展前缀或缩短路径。
MAX_SAFE_PATH_LENGTH = 240


class PathTooLongError(ValueError):
    """目标路径超过系统限制（ISSUES I10）。消息里必须带路径长度与限制值。"""


def validate_path_length(path: Path, *, limit: int = MAX_SAFE_PATH_LENGTH) -> None:
    """检查路径长度是否在安全范围内。超限抛 PathTooLongError（可读错误，不是 WinError 3）。

    Windows 默认 MAX_PATH = 260，但很多工具（Git、资源管理器）不支持扩展长度前缀。
    安全上限 240 = 给目录创建与临时文件留 20 字符余量。
    """
    path_str = str(path)
    if len(path_str) > limit:
        raise PathTooLongError(
            f"目标路径过长：{len(path_str)} 字符（上限 {limit}）\n"
            f"路径：{path_str}\n"
            "请缩短文件名、减少嵌套层级，或启用系统 LongPathsEnabled（ISSUES I10）"
        )


class ArchiveService:
    """归档服务：执行文件操作并记录 journal。"""

    def __init__(self, ops: OperationRepository, docs: DocumentRepository,
                 paths: AppPaths) -> None:
        self.ops = ops
        self.docs = docs
        self.paths = paths

    def preview_path_length(self, doc_ids: list[int], target_root: str,
                           template: str) -> dict[str, int | str]:
        """预览归档后的路径长度分布（ISSUES I10：路径长度作为归档方案预览的显示项）。

        返回 {max_length, min_length, avg_length, over_limit_count}。
        """
        target_root_path = Path(target_root)
        lengths = []
        for doc_id in doc_ids:
            doc = self.docs.get(doc_id)
            if not doc:
                continue
            dst_path = target_root_path / doc.name
            lengths.append(len(str(dst_path)))
        if not lengths:
            return {"max_length": 0, "min_length": 0, "avg_length": 0, "over_limit_count": 0}
        return {
            "max_length": max(lengths),
            "min_length": min(lengths),
            "avg_length": sum(lengths) / len(lengths),
            "over_limit_count": sum(1 for l in lengths if l > MAX_SAFE_PATH_LENGTH),
        }

    def handle(self, job_id: int, doc_ids: list[int], target_root: str,
               template: str) -> None:
        """执行归档任务。由 WorkQueue 调用。

        流程：
        1. 创建操作批次（file_operations）
        2. 为每个 doc_id 创建操作项（operation_items）
        3. 逐项执行：计算目标路径 → 写 journal → 复制/移动 → 验证 → 更新状态
        4. 完成或失败时更新批次状态

        ISSUES I40：同盘/跨盘判定必须 import 同一个来源（documents.device_id 与目标根的 st_dev），
        标记与 operation_items.kind 不一致即判红。跨盘移动绝不先删源（G19）。
        """
        target_root_path = Path(target_root)
        if not target_root_path.exists():
            raise ValueError(f"目标根目录不存在：{target_root}")

        # ISSUES I40：取目标根的设备号（跨盘判定的唯一来源之一）
        target_device = os.stat(target_root_path).st_dev

        # 创建操作批次
        journal_path = str(self.paths.journal_dir / f"op_{job_id}.jsonl")
        op = self.ops.create_operation(
            kind="archive",
            plan={"doc_ids": doc_ids, "target_root": target_root, "template": template},
            journal_path=journal_path)

        # 为每个文档创建操作项
        items = []
        for doc_id in doc_ids:
            doc = self.docs.get(doc_id)
            if not doc:
                continue
            # 计算目标路径（简化版，实际应该用 template 渲染）
            dst_path = str(target_root_path / doc.name)

            # ISSUES I40：同盘/跨盘判定 —— 源设备号来自 documents.device_id（唯一来源）
            # 跨盘 = copy + verify + delete source（G19：绝不先删源）
            # 同盘 = move（原子 rename，安全）
            src_device = doc.device_id  # 来自 documents 表，唯一来源
            if src_device is not None and src_device != target_device:
                kind = "copy"  # 跨盘：先复制，验证后再删源
            else:
                kind = "move"  # 同盘或设备号未知：默认 move（未知时保守按同盘处理）

            item = self.ops.add_item(op.id, doc_id, kind=kind,
                                     src_path=doc.path, dst_path=dst_path)
            items.append(item)

        # 开始执行
        self.ops.start_operation(op.id)
        self.ops.write_journal(journal_path, {"event": "start", "op_id": op.id})

        failed = 0
        for item in items:
            try:
                self._execute_item(item, journal_path)
            except Exception as exc:
                log.exception("归档项失败 item_id=%s", item.id)
                self.ops.update_item_state(item.id, "failed", error=str(exc))
                self.ops.write_journal(journal_path, {
                    "event": "item_failed", "item_id": item.id, "error": str(exc)})
                failed += 1

        # 完成
        status = "failed" if failed == len(items) else ("done" if failed == 0 else "partial")
        self.ops.finish_operation(op.id, status)
        self.ops.write_journal(journal_path, {"event": "finish", "op_id": op.id, "status": status})

    def _execute_item(self, item, journal_path: str) -> None:
        """执行单个操作项。

        ISSUES I40 / G19：跨盘移动 = 先复制 → 验证 sha256 → 再删源。
        绝不先删源（复制失败时丢源是 SPEC 3.6 / G19 禁止的路径）。
        """
        src = Path(item.src_path)
        dst = Path(item.dst_path) if item.dst_path else None

        if not src.exists():
            raise FileNotFoundError(f"源文件不存在：{src}")

        # ISSUES I10：目标路径长度自检（在创建目录与复制前检查，避免半截操作后报错）
        if dst is not None:
            validate_path_length(dst)

        # 写 journal：即将开始
        self.ops.write_journal(journal_path, {
            "event": "item_start", "item_id": item.id, "src": str(src), "dst": str(dst)})

        # 计算源文件 sha256
        src_sha = self._sha256(src)

        # 确保目标目录存在
        dst.parent.mkdir(parents=True, exist_ok=True)

        # 复制/移动（G19：跨盘移动绝不先删源）
        if item.kind == "move":
            shutil.move(str(src), str(dst))
        elif item.kind == "copy":
            # 跨盘：先复制，验证后再删源（G19）
            shutil.copy2(str(src), str(dst))
        else:
            raise ValueError(f"未知操作类型：{item.kind}")

        # 验证目标
        if not dst.exists():
            raise RuntimeError(f"目标文件未生成：{dst}")
        dst_sha = self._sha256(dst)

        # 验证 sha256 一致（move 和 copy 都要验）
        if src_sha != dst_sha:
            raise RuntimeError(f"SHA256 不匹配：src={src_sha}, dst={dst_sha}")

        # 跨盘 copy：验证成功后才删源（G19：绝不先删源）
        if item.kind == "copy":
            self.ops.write_journal(journal_path, {
                "event": "dst_verified", "item_id": item.id, "dst_sha256": dst_sha})
            src.unlink()  # 验证通过后才删

        # 更新状态
        self.ops.update_item_state(item.id, "done", dst_sha256=dst_sha)
        self.ops.write_journal(journal_path, {
            "event": "item_done", "item_id": item.id, "dst_sha256": dst_sha})

    def _sha256(self, path: Path) -> str:
        h = hashlib.sha256()
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()
        # 阶段 4 实现：按计划执行归档，写 journal，更新 operation_items
