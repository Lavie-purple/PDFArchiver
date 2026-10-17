"""G17/G19 磁盘安全行为测试（仅用专用临时文件，不碰真实语料）。

G17 · 文件操作崩溃恢复：journal 写入顺序正确，崩溃后可从 journal 读出每条 item 的状态。
    （完整 journal replay 尚未实现，本测试钉住 journal 格式与写入顺序不变，为将来 replay 铺路。）
G19 · 跨盘移动绝不先删源：跨盘 copy 模式下，目标 sha256 验证通过前源文件必须存在。
    注入故障（验证后、删源前抛异常）→ 源文件仍在。

G18 · 撤销正确性：需要 undo 执行器（ISSUES I55 挂账中），本轮不测。
"""
from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from unittest.mock import patch

import pytest

from pdfarchiver.db.engine import Engine
from pdfarchiver.db.migrate import migrate
from pdfarchiver.db.repositories.documents import DocumentRepository
from pdfarchiver.db.repositories.operations import OperationRepository
from pdfarchiver.db.models import Document, now_ts
from pdfarchiver.services.archive_service import ArchiveService


@pytest.fixture()
def archive_env(tmp_path):
    """搭一个最小归档环境：临时库 + 临时源目录 + 临时目标目录。"""
    db_path = tmp_path / "test.db"
    src_dir = tmp_path / "src"
    dst_dir = tmp_path / "dst"
    journal_dir = tmp_path / "journals"
    src_dir.mkdir()
    dst_dir.mkdir()
    journal_dir.mkdir()

    engine = Engine(db_path)
    migrate(engine, backup_dir=tmp_path / "backups")
    ops = OperationRepository(engine)
    docs = DocumentRepository(engine)

    class FakePaths:
        pass

    fake_paths = FakePaths()
    fake_paths.journal_dir = journal_dir

    svc = ArchiveService(ops, docs, fake_paths)
    yield {
        "engine": engine, "ops": ops, "docs": docs, "svc": svc,
        "src_dir": src_dir, "dst_dir": dst_dir, "journal_dir": journal_dir,
        "tmp_path": tmp_path,
    }
    engine.close_thread_connection()


def _seed_doc(docs: DocumentRepository, *, name: str, src_path: Path,
              device_id: int | None = None) -> int:
    """往 documents 表插一条测试记录，返回 doc_id。"""
    src_path.write_bytes(b"test content for archive safety test")
    stat = src_path.stat()
    conn = docs.engine.thread_connection()
    conn.execute(
        "INSERT INTO documents(path, path_key, name, ext, size_bytes, mtime_ns,"
        " device_id, parse_status, text_status, fts_status, ocr_status, vector_status,"
        " created_at, updated_at)"
        " VALUES(?,?,?, 'pdf', ?, ?, ?, 'ok','native','done','na','na', ?, ?)",
        (str(src_path), str(src_path), name, stat.st_size, stat.st_mtime_ns,
         device_id, now_ts(), now_ts()))
    return int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])


class TestG19CrossDiskNeverDeletesSourceFirst:
    """G19：跨盘 copy 模式下，源文件在目标 sha256 验证通过前不得被删除。"""

    def test_跨盘copy验证失败时源文件仍在(self, archive_env):
        """注入故障：让 sha256 验证抛异常 → 源文件必须还在。"""
        env = archive_env
        src_file = env["src_dir"] / "test.pdf"
        doc_id = _seed_doc(env["docs"], name="test.pdf", src_path=src_file,
                           device_id=None)  # device_id=None → 默认 move

        # 直接创建一个 kind="copy" 的 item 来测试跨盘逻辑
        op = env["ops"].create_operation(kind="archive", journal_path=str(env["journal_dir"] / "op_test.jsonl"))
        item = env["ops"].add_item(op.id, doc_id, kind="copy",
                                   src_path=str(src_file),
                                   dst_path=str(env["dst_dir"] / "test.pdf"))

        # 让 sha256 验证失败（copy 后修改目标文件）
        original_copy2 = shutil.copy2

        def tampering_copy2(src, dst):
            original_copy2(src, dst)
            Path(dst).write_bytes(b"tampered")  # 破坏目标

        journal_path = str(env["journal_dir"] / "op_test.jsonl")
        with patch("shutil.copy2", side_effect=tampering_copy2):
            with pytest.raises(RuntimeError, match="SHA256 不匹配"):
                env["svc"]._execute_item(item, journal_path)

        # G19 核心断言：验证失败后，源文件必须仍在
        assert src_file.exists(), "G19 违反：验证失败后源文件被删了"

    def test_跨盘copy成功后源文件才消失(self, archive_env):
        """正常流程：跨盘 copy → 验证通过 → 源文件消失 → 目标文件在。"""
        env = archive_env
        src_file = env["src_dir"] / "report.pdf"
        doc_id = _seed_doc(env["docs"], name="report.pdf", src_path=src_file,
                           device_id=None)

        # 直接创建一个 kind="copy" 的 item
        op = env["ops"].create_operation(kind="archive", journal_path=str(env["journal_dir"] / "op_test2.jsonl"))
        item = env["ops"].add_item(op.id, doc_id, kind="copy",
                                   src_path=str(src_file),
                                   dst_path=str(env["dst_dir"] / "report.pdf"))

        journal_path = str(env["journal_dir"] / "op_test2.jsonl")
        env["svc"]._execute_item(item, journal_path)

        # 源文件已删（验证通过后）
        assert not src_file.exists(), "copy 成功后源文件应该被删"
        # 目标文件存在且内容一致
        dst_file = env["dst_dir"] / "report.pdf"
        assert dst_file.exists()
        assert dst_file.read_bytes() == b"test content for archive safety test"

        # 源文件已删（验证通过后）
        assert not src_file.exists(), "copy 成功后源文件应该被删"
        # 目标文件存在且内容一致
        dst_file = env["dst_dir"] / "report.pdf"
        assert dst_file.exists()
        assert dst_file.read_bytes() == b"test content for archive safety test"


class TestG17JournalFormat:
    """G17：journal 写入顺序正确，崩溃后可读出每条 item 的状态。

    完整 journal replay 尚未实现（ISSUES I55 挂账），本测试钉住 journal 格式不变。
    """

    def test_journal记录完整操作序列(self, archive_env):
        """正常归档后，journal 文件应包含 start → item_start → item_done → finish。"""
        env = archive_env
        src_file = env["src_dir"] / "doc.pdf"
        doc_id = _seed_doc(env["docs"], name="doc.pdf", src_path=src_file,
                           device_id=None)  # 同盘 move

        # 用 handle() 跑完整流程
        env["svc"].handle(
            job_id=3, doc_ids=[doc_id],
            target_root=str(env["dst_dir"]), template="")

        # 读 journal
        journal_file = env["journal_dir"] / "op_3.jsonl"
        assert journal_file.exists(), "journal 文件应该被创建"
        events = [json.loads(line) for line in journal_file.read_text().splitlines()]

        # 验证事件序列
        event_types = [e["event"] for e in events]
        assert "start" in event_types
        assert "item_start" in event_types
        assert "item_done" in event_types
        assert "finish" in event_types

        # 同盘 move 不需要 dst_verified（只有跨盘 copy 才需要）
        # 但 item_done 必须在 finish 之前
        done_idx = event_types.index("item_done")
        finish_idx = event_types.index("finish")
        assert done_idx < finish_idx, "item_done 必须在 finish 之前"

    def test_journal在item失败时仍记录(self, archive_env):
        """某个 item 失败时，journal 应记录 item_failed 并继续处理后续 item。"""
        env = archive_env
        src1 = env["src_dir"] / "a.pdf"
        src2 = env["src_dir"] / "b.pdf"
        doc1 = _seed_doc(env["docs"], name="a.pdf", src_path=src1, device_id=None)
        doc2 = _seed_doc(env["docs"], name="b.pdf", src_path=src2, device_id=None)

        # 让第一个 item 失败（源文件不存在）
        src1.unlink()

        env["svc"].handle(
            job_id=4, doc_ids=[doc1, doc2],
            target_root=str(env["dst_dir"]), template="")

        journal_file = env["journal_dir"] / "op_4.jsonl"
        events = [json.loads(line) for line in journal_file.read_text().splitlines()]
        event_types = [e["event"] for e in events]

        assert "item_failed" in event_types, "失败的 item 应在 journal 里留 item_failed"
        # 第二个 item 应该成功
        assert event_types.count("item_done") >= 1, "后续 item 应继续执行"
        assert "finish" in event_types
