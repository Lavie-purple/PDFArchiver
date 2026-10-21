"""G17 / G18 / G19 磁盘安全行为测试（仅用专用临时文件，不碰真实语料）。

三条门禁各自盯一件"做错了就回不去"的事：

- **G17 · 崩溃恢复的依据**：journal 的写入顺序与内容必须能从磁盘侧读出每一条真的动过的项；
  被计划阶段跳过的项**不进 journal**（**D-048**），它只在台账里留原因文本。
- **G18 · 撤销正确性**（本轮 A4 之后可测）：撤销跑完必须四条同时对上 —— 源位置有文件、
  字节与原文件一致、sha256 一致、归档目标位置的文件消失。少任何一条都不算"撤回"。
- **G19 · 跨盘绝不先删源**：目标 sha256 验证通过之前源文件必须还在。注入故障（copy 完立刻
  篡改目标）→ 报错 + 源仍在。

再加两条这条链独有的：
- **plan 是纯计算**（`docs/DATABASE.md` §5.1）：预览前后整个目录树的 mtime 集合完全不变，
  不产生任何 journal 文件，也不写批次行 —— 这是 ROADMAP 阶段 4 门禁点名的判据。
- **预览与执行同源**（**ISSUES I55** 甲 / A3）：界面拿到的 `plan()` 结果与批次里落成
  `operation_items` 的那一批必须逐条相等。

跑法：
    QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe -m pytest \
        tests/integration/test_archive_disk_safety.py -q
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from pdfarchiver.db.engine import Engine
from pdfarchiver.db.migrate import migrate
from pdfarchiver.db.models import Document
from pdfarchiver.db.repositories.catalog import CatalogRepository
from pdfarchiver.db.repositories.documents import DocumentRepository
from pdfarchiver.db.repositories.jobs import JobRepository
from pdfarchiver.db.repositories.operations import OperationRepository
from pdfarchiver.fs.identity import read_identity
from pdfarchiver.jobs.queue import JobCancelled, ProgressMonitor
from pdfarchiver.services.archive_service import (MAX_SAFE_PATH_LENGTH, ArchiveService,
                                                  PlannedMove)

DEFAULT_TEMPLATE = "{category}/{year}/{name}.pdf"
BODY = b"archive disk safety payload"
# 2023-12-31T16:30Z：本机（UTC+8）的本地时间已经是 2024-01-01 00:30。
# 拿它当 mtime 是为了让"年份按哪个时区算"这件事**能被断言** —— 按本地时间算就会渲染成 `2024`，
# 而口径是 UTC（**ISSUES D-022** 那一族：裸本地时间却标 `Z` 注入过一条坏法）。
YEAR_EDGE_TS = int(datetime(2023, 12, 31, 16, 30, tzinfo=timezone.utc).timestamp())


@pytest.fixture()
def env(tmp_path):
    """最小真环境：真 sqlite + 真磁盘目录，无 mock（**D-012**）。"""
    src_dir, dst_dir, journal_dir = (tmp_path / n for n in ("src", "dst", "journals"))
    for d in (src_dir, dst_dir, journal_dir):
        d.mkdir()

    engine = Engine(tmp_path / "test.db")
    migrate(engine, backup_dir=tmp_path / "backups")

    # `AppPaths` 在这里只被用来取 journal 目录，给个只有那一个属性的替身。
    # （**D-012** 禁的是 mock 数据库，库里的一切都是真的。）
    paths = SimpleNamespace(journal_dir=journal_dir)
    ops, docs, catalog, jobs = (OperationRepository(engine), DocumentRepository(engine),
                                CatalogRepository(engine), JobRepository(engine))

    yield {
        "engine": engine, "ops": ops, "docs": docs, "catalog": catalog, "jobs": jobs,
        "svc": ArchiveService(ops, docs, paths, catalog, jobs),
        "src_dir": src_dir, "dst_dir": dst_dir, "journal_dir": journal_dir,
    }
    engine.close_thread_connection()


def _seed(env, name: str, *, category: str | None = None, device_id: int | None = None,
          body: bytes = BODY, mtime_ts: int | None = YEAR_EDGE_TS,
          zero_mtime: bool = False, in_subdir: str = "") -> int:
    """写一个真文件 + 一条真主记录，返回 doc_id。"""
    path = env["src_dir"] / in_subdir / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)
    if mtime_ts is not None:
        os.utime(path, ns=(mtime_ts * 10**9, mtime_ts * 10**9))
    identity = read_identity(path)
    doc = env["docs"].upsert(Document(
        path=identity.path, path_key=identity.path_key, name=identity.name, ext=identity.ext,
        size_bytes=identity.size_bytes, mtime_ns=0 if zero_mtime else identity.mtime_ns,
        ctime_ns=identity.ctime_ns, file_id=identity.file_id,
        device_id=identity.device if device_id is None else device_id,
        parse_status="ok", text_status="native", fts_status="done"))
    if category:
        top, _, child = category.partition("/")
        cat = env["catalog"].add_category(top)
        if child:
            cat = env["catalog"].add_category(child, parent_id=cat.id)
        env["catalog"].link_category(int(doc.id), int(cat.id))
    return int(doc.id)


def _run(env, op_id: int) -> None:
    """按队列的调用形状跑一次处理函数：`handler(job, monitor)`（**ISSUES I68** 的由来）。"""
    job = env["jobs"].latest_of_kind("archive")
    assert job is not None, "提交批次必须同时排出一条后台任务"
    env["svc"].handle(job, ProgressMonitor(env["jobs"], int(job.id), threading.Event()))
    return env["ops"].get_operation(op_id)


def _journal_events(env, op_id: int) -> list[dict]:
    lines = (env["journal_dir"] / f"op_{op_id}.jsonl").read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines]


def _tree_facts(root: Path) -> dict[str, int]:
    """整棵树的 {路径: mtime_ns}。plan 纯计算那条判据就靠它前后对账。"""
    return {str(p): p.stat().st_mtime_ns for p in root.rglob("*") if p.is_file()}


class TestPlanIsPure:
    """`docs/DATABASE.md` §5.1：plan 阶段绝不打开、绝不写、绝不 rename。"""

    def test_预览前后磁盘与台账一处都没变(self, env):
        doc_id = _seed(env, "报销A.pdf", category="财务/报销")
        before = _tree_facts(env["src_dir"])
        dst_before = list(env["dst_dir"].rglob("*"))

        moves = env["svc"].plan([doc_id], str(env["dst_dir"]), DEFAULT_TEMPLATE)

        assert len(moves) == 1 and moves[0].will_move, "计划本身要成立，否则后面全是空对空"
        assert _tree_facts(env["src_dir"]) == before, "预览动了源目录的 mtime"
        assert list(env["dst_dir"].rglob("*")) == dst_before, "预览在目标目录里造了目录或文件"
        assert list(env["journal_dir"].rglob("*")) == [], "预览写了 journal"
        assert env["ops"].list_operations() == [], "预览落了操作批次"

    def test_目标根不存在是当场报错而不是默默跳过(self, env):
        doc_id = _seed(env, "a.pdf")
        with pytest.raises(ValueError, match="目标根目录不存在"):
            env["svc"].plan([doc_id], str(env["dst_dir"] / "没有这个目录"), DEFAULT_TEMPLATE)

    def test_模板写错是整批错误而不是逐项跳过(self, env):
        # 整批一条都跑不了，逐项跳过的话界面会显示 N 条"原因"，人得读完才知道是模板打错了
        doc_id = _seed(env, "a.pdf")
        with pytest.raises(ValueError, match="不认识的变量"):
            env["svc"].plan([doc_id], str(env["dst_dir"]), "{category}/{zuozhe}/{name}.pdf")


class TestPlanRendering:
    """A3：命名模板渲染器，预览与执行同源。"""

    def test_渲染出分类目录加年份目录加原名(self, env):
        doc_id = _seed(env, "报销A.pdf", category="财务/报销")
        moves = env["svc"].plan([doc_id], str(env["dst_dir"]), DEFAULT_TEMPLATE)
        dst = Path(moves[0].dst_path)
        assert (dst.parent.name, dst.parent.parent.name, dst.parent.parent.parent.name) == \
            ("2023", "报销", "财务")
        assert dst.parent.parent.parent.parent == env["dst_dir"]
        assert dst.name == "报销A.pdf"

    def test_年份按UTC算(self, env):
        doc_id = _seed(env, "跨年.pdf")
        dst = Path(env["svc"].plan([doc_id], str(env["dst_dir"]), DEFAULT_TEMPLATE)[0].dst_path)
        assert dst.parent.name == "2023", f"UTC 口径下这是 2023 年，渲染出 {dst.parent.name} 就是按本地时间算的"

    def test_没有分类的文件落到明确的兜底目录(self, env):
        doc_id = _seed(env, "无主.pdf")
        dst = Path(env["svc"].plan([doc_id], str(env["dst_dir"]), DEFAULT_TEMPLATE)[0].dst_path)
        assert dst.parent.parent.name == "_未分类"

    def test_没有修改时间的文件不许冒充某一年(self, env):
        doc_id = _seed(env, "零时间.pdf", zero_mtime=True)
        dst = Path(env["svc"].plan([doc_id], str(env["dst_dir"]), DEFAULT_TEMPLATE)[0].dst_path)
        assert dst.parent.name == "_无年份"

    def test_同盘判move跨盘判copy只看device_id(self, env):
        same = _seed(env, "同盘.pdf")
        other = _seed(env, "跨盘.pdf", device_id=os.stat(env["dst_dir"]).st_dev + 7)
        kinds = {m.doc_id: m.kind for m in
                 env["svc"].plan([same, other], str(env["dst_dir"]), DEFAULT_TEMPLATE)}
        assert kinds[same] == "move" and kinds[other] == "copy"

    def test_目标已存在默认跳过并给出原因(self, env):
        doc_id = _seed(env, "重复.pdf", category="财务")
        clash = env["dst_dir"] / "财务" / "2023" / "重复.pdf"
        clash.parent.mkdir(parents=True, exist_ok=True)
        clash.write_bytes(b"someone else")
        move = env["svc"].plan([doc_id], str(env["dst_dir"]), DEFAULT_TEMPLATE)[0]
        assert not move.will_move
        assert "目标位置已经有同名文件" in (move.skip_reason or "")
        assert clash.read_bytes() == b"someone else", "预览不能碰冲突那份的内容"

    def test_同一批里落到同一个位置只有第一条能走(self, env):
        a = _seed(env, "同名.pdf", in_subdir="甲")
        b = _seed(env, "同名.pdf", in_subdir="乙")
        moves = env["svc"].plan([a, b], str(env["dst_dir"]), "{category}/{name}.pdf")
        assert moves[0].will_move and not moves[1].will_move
        assert "第 1 项" in (moves[1].skip_reason or "")

    def test_源已经不在磁盘上的项跳过(self, env):
        doc_id = _seed(env, "已删.pdf")
        (env["src_dir"] / "已删.pdf").unlink()
        move = env["svc"].plan([doc_id], str(env["dst_dir"]), DEFAULT_TEMPLATE)[0]
        assert "源文件已经不在磁盘上" in (move.skip_reason or "")

    def test_主记录已经不在了的项跳过(self, env):
        move = env["svc"].plan([4242], str(env["dst_dir"]), DEFAULT_TEMPLATE)[0]
        assert "文档主记录已经不在了" in (move.skip_reason or "") and not move.will_move

    def test_超长目标路径跳过并带字符数(self, env):
        # 超长用**模板里的长目录**造，不去建一个 400 字符名的文件：要证的是渲染结果的长度自检，
        # 而源文件能不能落盘取决于本机 LongPathsEnabled，跟这条判据无关（ISSUES I10）。
        doc_id = _seed(env, "a.pdf")
        long_dir = "目录" * 120
        move = env["svc"].plan([doc_id], str(env["dst_dir"]), f"{long_dir}/{{name}}.pdf")[0]
        assert not move.will_move
        assert "目标路径过长" in (move.skip_reason or "")
        assert len(move.dst_path) > MAX_SAFE_PATH_LENGTH

    def test_文件名里的非法字符被清洗而不是整批失败(self, env):
        # Windows 不允许文件名带 `:`，但分类名里可以有 —— 清洗成下划线，且预览里看到的就是落地的
        odd = _seed(env, "合同.pdf", category="年度:2023")
        root = str(env["dst_dir"])
        move = env["svc"].plan([odd], root, "{category}/{name}.pdf")[0]
        assert move.will_move and move.doc_id == odd
        assert "年度_2023" in move.dst_path
        assert ":" not in move.dst_path[len(root):], "冒号留在路径里 Windows 直接写失败"


class TestPreviewMatchesExecution:
    """「预览与实际执行的文件集合逐条一致」（docs/ROADMAP.md 阶段 4 门禁）。"""

    def test_批次里的条目与plan逐条相等(self, env):
        ids = [_seed(env, "甲.pdf", category="财务"), _seed(env, "乙.pdf", category="法律")]
        root = str(env["dst_dir"])
        expected = env["svc"].plan(ids, root, DEFAULT_TEMPLATE)
        op = env["svc"].submit(ids, root, DEFAULT_TEMPLATE)

        items = env["ops"].list_items(op.id)
        assert len(items) == len(expected), "预览 N 条、执行 N+1 条就是两个口径"
        for item, move in zip(items, expected):
            assert (item.src_path, item.dst_path or "", item.kind) == \
                (move.src_path, move.dst_path, move.kind)
            assert item.state == ("pending" if move.will_move else "skipped")

    def test_提交时跳过的项直接落skipped且不可逆(self, env):
        good = _seed(env, "能搬.pdf", category="财务")
        ghost = _seed(env, "会消失.pdf", category="财务")
        (env["src_dir"] / "会消失.pdf").unlink()
        op = env["svc"].submit([good, ghost], str(env["dst_dir"]), DEFAULT_TEMPLATE)
        by_src = {i.src_path: i for i in env["ops"].list_items(op.id)}
        ghost_item = next(i for i in by_src.values() if "会消失" in i.src_path)
        assert ghost_item.state == "skipped" and ghost_item.reversible == 0
        assert ghost_item.error and "源文件已经不在" in ghost_item.error
        assert by_src[next(k for k in by_src if "能搬" in k)].state == "pending"


class TestIrreversibleSingleSource:
    """**ISSUES I69** 丙：「不可逆」全站只许有一个算法。

    归一之前是三处各写各的：S3 界面自己 `os.path.exists(dst)` 数一遍、`reversible` 字段按
    `1 if will_move else 0` 写、S4 数 `reversible == 0`。分级确认控件切的就是这一条数
    （**D-042** 丙），三处不同一条就意味着同一批文件可能在 S3 要输确认词、在 S4 只要勾一下。
    """

    @staticmethod
    def _moves(env) -> list[PlannedMove]:
        doc_id = _seed(env, "甲.pdf", category="财务")
        src = str(env["src_dir"] / "甲.pdf")
        taken = env["dst_dir"] / "已被占位.pdf"
        taken.write_bytes(BODY)   # 目标位上那份是"别人的文件"，这次不搬它
        return [PlannedMove(doc_id, src, str(taken), "move"),
                PlannedMove(doc_id, src, str(env["dst_dir"] / "空位.pdf"), "move"),
                PlannedMove(doc_id, src, "", "move", "源文件已经不在磁盘上")]

    def test_目标位已有文件才算不可逆(self, env):
        hit, free, skipped = self._moves(env)
        assert hit.irreversible is True
        assert free.irreversible is False, "目标位是空的，搬过去盖不掉任何东西"
        assert skipped.irreversible is False, "根本不搬的项不许占这条数"

    def test_界面那条数取的是服务的口径(self, env):
        from pdfarchiver.ui.pages.archive_page import ArchivePage  # 只借静态方法，不起窗口
        moves = self._moves(env)
        assert ArchivePage._counts(moves)["irreversible"] == 1, \
            "界面数出来的与 `PlannedMove.irreversible` 不同一条，就是两个口径又长回来了"

    def test_落库的可逆标记与界面同一条数(self, env):
        from pdfarchiver.ui.pages.archive_page import ArchivePage
        moves = self._moves(env)
        with patch.object(ArchiveService, "plan", return_value=moves):
            op = env["svc"].submit([int(moves[0].doc_id or 0)],
                                   str(env["dst_dir"]), DEFAULT_TEMPLATE)
        pending = [i for i in env["ops"].list_items(op.id) if i.state == "pending"]
        assert sum(1 for i in pending if i.reversible == 0) == \
            ArchivePage._counts(moves)["irreversible"] == 1, \
            "批次里的 `reversible` 与界面上的「不可逆」不同源，撤销那一屏就会给出另一个档"


class TestG19CrossDiskNeverDeletesSourceFirst:
    def test_跨盘copy验证失败时源文件仍在(self, env):
        doc_id = _seed(env, "test.pdf", category="财务",
                       device_id=os.stat(env["dst_dir"]).st_dev + 7)
        src_file = env["src_dir"] / "test.pdf"
        moves = env["svc"].plan([doc_id], str(env["dst_dir"]), DEFAULT_TEMPLATE)
        op = env["svc"].submit([doc_id], str(env["dst_dir"]), DEFAULT_TEMPLATE)
        assert moves[0].kind == "copy"

        original_copy2 = shutil.copy2

        def tampering_copy2(s, d):
            original_copy2(s, d)
            Path(d).write_bytes(b"tampered")

        with patch("shutil.copy2", side_effect=tampering_copy2):
            final = _run(env, op.id)

        assert final.status == "failed"
        assert src_file.exists(), "G19 违反：验证失败后源文件被删了"
        landed = next(p for p in env["dst_dir"].rglob("test.pdf"))
        assert landed.read_bytes() == b"tampered", \
            "两边都在且对不上时不许自动删任何一边（DATABASE §5.2 的 orphan_dst）"

    def test_跨盘copy成功后源文件才消失(self, env):
        doc_id = _seed(env, "report.pdf", category="财务",
                       device_id=os.stat(env["dst_dir"]).st_dev + 7)
        src_file = env["src_dir"] / "report.pdf"
        op = env["svc"].submit([doc_id], str(env["dst_dir"]), DEFAULT_TEMPLATE)
        final = _run(env, op.id)
        assert final.status == "done"
        assert not src_file.exists()
        landed = next(p for p in env["dst_dir"].rglob("report.pdf"))
        assert landed.read_bytes() == BODY

    def test_一项坏带走不了整批(self, env):
        """第二项的源在 plan 之后、执行之前被人删掉：批次只能标 partially_done，第一项照搬。"""
        good = _seed(env, "好.pdf", category="财务")
        bad = _seed(env, "坏.pdf", category="财务")
        op = env["svc"].submit([good, bad], str(env["dst_dir"]), DEFAULT_TEMPLATE)
        (env["src_dir"] / "坏.pdf").unlink()

        final = _run(env, op.id)
        assert final.status == "partially_done"
        states = {i.src_path: i.state for i in env["ops"].list_items(op.id)}
        assert "done" in states.values() and "failed" in states.values()
        assert next(i.error for i in env["ops"].list_items(op.id) if i.state == "failed")

    def test_批次终态只有词表里那几个值(self, env):
        """执行器写状态必须走 `models.OP_STATUSES`：早先它写过 `"partial"`，台账里留下一句没人认识的话。"""
        from pdfarchiver.db.models import ITEM_STATES, OP_STATUSES
        doc_id = _seed(env, "a.pdf", category="财务")
        op = env["svc"].submit([doc_id], str(env["dst_dir"]), DEFAULT_TEMPLATE)
        assert op.status in OP_STATUSES
        assert all(i.state in ITEM_STATES for i in env["ops"].list_items(op.id))
        with pytest.raises(ValueError, match="未知批次状态"):
            env["ops"].finish_operation(op.id, "partial")
        with pytest.raises(ValueError, match="未知操作项状态"):
            env["ops"].update_item_state(env["ops"].list_items(op.id)[0].id, "copying")


class TestG17Journal:
    def test_journal按顺序记下真动过的每一项(self, env):
        ids = [_seed(env, "doc.pdf", category="财务"), _seed(env, "ghost.pdf", category="财务")]
        op = env["svc"].submit(ids, str(env["dst_dir"]), DEFAULT_TEMPLATE)
        (env["src_dir"] / "ghost.pdf").unlink()
        _run(env, op.id)

        events = _journal_events(env, op.id)
        types = [e["event"] for e in events]
        assert types[0] == "start" and types[-1] == "finish"
        assert events[0]["items"] == 2, "start 记的工作量必须是这一批真要领的 pending 项数"
        assert "item_start" in types and "item_done" in types
        assert types.index("item_done") < types.index("finish")
        assert sum(1 for e in events if e["event"] == "item_failed") == 1

    def test_同盘move不写dst_verified(self, env):
        doc_id = _seed(env, "move.pdf", category="财务")
        op = env["svc"].submit([doc_id], str(env["dst_dir"]), DEFAULT_TEMPLATE)
        _run(env, op.id)
        types = [e["event"] for e in _journal_events(env, op.id)]
        assert "dst_verified" not in types and "src_removed" not in types

    def test_跨盘copy先写dst_verified再写src_removed(self, env):
        doc_id = _seed(env, "copy.pdf", category="财务",
                       device_id=os.stat(env["dst_dir"]).st_dev + 7)
        op = env["svc"].submit([doc_id], str(env["dst_dir"]), DEFAULT_TEMPLATE)
        _run(env, op.id)
        types = [e["event"] for e in _journal_events(env, op.id)]
        assert types.index("dst_verified") < types.index("src_removed") < types.index("item_done")

    def test_计划阶段跳过的项不进journal(self, env):
        """**D-048**：journal 只记真动过的；跳过项的原因在 `operation_items.error` 里。"""
        doc_id = _seed(env, "跳.pdf", category="财务")
        (env["src_dir"] / "跳.pdf").unlink()
        op = env["svc"].submit([doc_id], str(env["dst_dir"]), DEFAULT_TEMPLATE)
        _run(env, op.id)
        assert [e["event"] for e in _journal_events(env, op.id)] == ["start", "finish"]
        assert env["ops"].list_items(op.id)[0].error

    def test_journal路径落在journal_dir且按批次号命名(self, env):
        doc_id = _seed(env, "a.pdf", category="财务")
        op = env["svc"].submit([doc_id], str(env["dst_dir"]), DEFAULT_TEMPLATE)
        assert Path(op.journal_path) == env["journal_dir"] / f"op_{op.id}.jsonl"


class TestLibraryStaysConsistent:
    """搬完之后库里的路径必须跟上：主记录跟不上路径，下一次扫描只会把它标成 missing。"""

    def test_搬运后id不变路径变分类还在(self, env):
        doc_id = _seed(env, "判决C.pdf", category="法律/判决")
        op = env["svc"].submit([doc_id], str(env["dst_dir"]), DEFAULT_TEMPLATE)
        _run(env, op.id)

        item = env["ops"].list_items(op.id)[0]
        doc = env["docs"].get(doc_id)
        assert doc is not None and doc.id == doc_id, "换了路径就不该换新主记录"
        assert Path(doc.path) == Path(item.dst_path)
        assert [c.name_path for c in env["catalog"].categories_of(doc_id)] == ["法律/判决"]
        assert env["docs"].get_by_path_key(read_identity(item.dst_path).path_key) is not None

    def test_台账记下两侧哈希(self, env):
        doc_id = _seed(env, "a.pdf", category="财务")
        op = env["svc"].submit([doc_id], str(env["dst_dir"]), DEFAULT_TEMPLATE)
        _run(env, op.id)
        item = env["ops"].list_items(op.id)[0]
        assert item.src_sha256 and item.src_sha256 == item.dst_sha256

    def test_取消停在项与项之间且不谎报完成(self, env):
        ids = [_seed(env, f"第{i}.pdf", category="财务") for i in (1, 2, 3)]
        op = env["svc"].submit(ids, str(env["dst_dir"]), DEFAULT_TEMPLATE)
        job = env["jobs"].latest_of_kind("archive")
        stop = threading.Event()
        monitor = ProgressMonitor(env["jobs"], int(job.id), stop)
        original_move = shutil.move

        def cancelling_move(s, d):
            stop.set()
            return original_move(s, d)

        with patch("shutil.move", side_effect=cancelling_move):
            with pytest.raises(JobCancelled, match="被取消"):
                env["svc"].handle(job, monitor)

        items = env["ops"].list_items(op.id)
        assert [i.state for i in items].count("done") == 1
        assert "pending" in [i.state for i in items], "取消后剩下的项必须还看得见、还能重跑"
        final = env["ops"].get_operation(op.id)
        assert final.status == "partially_done", "取消停在 1/3 项却写成 done 就是谎报"
        assert final.items_done == 1


class TestG18Undo:
    """A4 · 撤销：另开一条 `kind='undo'`、`undo_of=原批次` 的反向批次（**D-043** 甲）。"""

    def _archived(self, env, name="报销A.pdf", category="财务"):
        doc_id = _seed(env, name, category=category)
        op = env["svc"].submit([doc_id], str(env["dst_dir"]), DEFAULT_TEMPLATE)
        _run(env, op.id)
        return doc_id, op.id

    def test_排除的条数与逐条原因一起交回(self, env):
        """**D-043** 甲：撤销只收可逆项，而**被排除的条数与原因必须交给调用方显示**，不许只是一个数。"""
        good = _seed(env, "能撤.pdf", category="财务")
        bad = _seed(env, "撤不了.pdf", category="财务")
        op = env["svc"].submit([good, bad], str(env["dst_dir"]), DEFAULT_TEMPLATE)
        _run(env, op.id)
        gone = next(i for i in env["ops"].list_items(op.id) if "撤不了" in i.dst_path)
        Path(gone.dst_path).unlink()

        undo, excluded, reasons = env["svc"].submit_undo(op.id)
        assert excluded == 1 and len(reasons) == 1
        assert "不凭空造源文件" in reasons[0]
        assert len(env["ops"].list_items(undo.id)) == 1, "被排除的那项不该混进反向批次"

    def test_撤销四项同时对上(self, env):
        doc_id, op_id = self._archived(env)
        item = env["ops"].list_items(op_id)[0]
        original_bytes = Path(item.dst_path).read_bytes()
        src_expected = Path(item.src_path)

        undo, excluded, reasons = env["svc"].submit_undo(op_id)
        assert excluded == 0 and reasons == []
        final = _run(env, undo.id)
        assert final.kind == "undo" and final.status == "done"
        assert final.undo_of == op_id, "反向批次必须能从台账反查到它撤的是哪一批"

        assert src_expected.exists(), "G18①：撤销后源位置要有文件"
        assert src_expected.read_bytes() == original_bytes, "G18②：字节要与原文件一致"
        undo_item = env["ops"].list_items(undo.id)[0]
        assert undo_item.src_sha256 == undo_item.dst_sha256, "G18③：sha256 一致"
        assert not Path(item.dst_path).exists(), "G18④：归档目标位置的文件要消失"
        assert Path(env["docs"].get(doc_id).path) == src_expected, "撤销后库里也要跟着回到原位"

    def test_撤销的反向项src与dst正好对调(self, env):
        _, op_id = self._archived(env)
        forward = env["ops"].list_items(op_id)[0]
        undo, _, _ = env["svc"].submit_undo(op_id)
        back = env["ops"].list_items(undo.id)[0]
        assert (back.src_path, back.dst_path) == (forward.dst_path, forward.src_path)

    def test_没搬成的项不进撤销并逐条给原因(self, env):
        other = _seed(env, "坏的.pdf", category="财务")
        bad_op = env["svc"].submit([other], str(env["dst_dir"]), DEFAULT_TEMPLATE)
        (env["src_dir"] / "坏的.pdf").unlink()
        _run(env, bad_op.id)
        assert env["ops"].list_items(bad_op.id)[0].state == "failed"

        # 全项都被排除时不许开一条空批次：那会在台账里留一条"撤销过 0 项"的记录，
        # 而用户看到的是按钮按下去了。
        with pytest.raises(ValueError, match="没有可撤销的项"):
            env["svc"].submit_undo(bad_op.id)

    def test_目标已经被人挪走时不凭空造文件(self, env):
        _, op_id = self._archived(env, name="被挪走.pdf")
        item = env["ops"].list_items(op_id)[0]
        Path(item.dst_path).unlink()
        with pytest.raises(ValueError, match="已经不在了"):
            env["svc"].submit_undo(op_id)

    def test_原位置已经有新文件时拒绝撤销(self, env):
        _, op_id = self._archived(env, name="原位有新文件.pdf")
        item = env["ops"].list_items(op_id)[0]
        Path(item.src_path).write_bytes(b"a new file at home")
        with pytest.raises(ValueError, match="原位置已经有新文件"):
            env["svc"].submit_undo(op_id)

    def test_撤销撤销批次被拒绝(self, env):
        _, op_id = self._archived(env, name="套娃.pdf")
        undo, _, _ = env["svc"].submit_undo(op_id)
        with pytest.raises(ValueError, match="撤销撤销批次"):
            env["svc"].submit_undo(undo.id)

    def test_整批撤完原批次才记为undone(self, env):
        """撤销另开一条批次、绝不改写原批次的账，但**要把它的态标成 `undone`** ——
        否则台账上那批永远显示 `done`，看不出磁盘上早就回到原位了（`docs/DATABASE.md` §二 词表）。
        """
        _, op_id = self._archived(env, name="两条批次.pdf")
        before = env["ops"].get_operation(op_id)
        undo, _, _ = env["svc"].submit_undo(op_id)
        _run(env, undo.id)
        assert {o.kind for o in env["ops"].list_operations()} == {"archive", "undo"}

        original = env["ops"].get_operation(op_id)
        assert (original.items_total, original.items_done) == \
               (before.items_total, before.items_done), "只改态，不改原批次记下的账"
        assert original.status == "undone"

    def test_部分撤销不许把原批次写成undone(self, env):
        """还剩几项在对面就写"已撤销"，是 AGENTS.md「禁止能力不足时伪装成功」在台账上的形状。"""
        a = _seed(env, "甲.pdf", category="财务")
        b = _seed(env, "乙.pdf", category="法律")
        op = env["svc"].submit([a, b], str(env["dst_dir"]), DEFAULT_TEMPLATE)
        _run(env, op.id)
        undo, _, _ = env["svc"].submit_undo(op.id)
        doomed = next(i for i in env["ops"].list_items(op.id) if "甲" in i.dst_path)
        Path(doomed.dst_path).unlink()      # 归档位置被挪走一项，反向批次只能跑成部分
        assert _run(env, undo.id).status == "partially_done"
        assert env["ops"].get_operation(op.id).status == "done", \
            "undone 只能由整批撤销写出来"


class TestBatchTaskLinkage:
    """**ISSUES I43** / D-043 后果 2：批次 ⇄ 任务的反查口径就是 `file_operations.job_id`。"""

    def test_领批次那一刻写下job_id(self, env):
        doc_id = _seed(env, "a.pdf", category="财务")
        op = env["svc"].submit([doc_id], str(env["dst_dir"]), DEFAULT_TEMPLATE)
        assert op.job_id is None, "提交时不该猜任务号"
        job = env["jobs"].latest_of_kind("archive")
        _run(env, op.id)
        assert env["ops"].get_operation(op.id).job_id == job.id

    def test_没确认的批次worker领不走(self, env):
        """只有 `previewed` 能被领，而把它写成 `previewed` 的唯一入口是 `submit()`（= 确认之后）。"""
        doc_id = _seed(env, "a.pdf", category="财务")
        op = env["ops"].create_operation(kind="archive", plan={"doc_ids": [doc_id]})
        env["jobs"].enqueue("archive", priority=3)
        job = env["jobs"].latest_of_kind("archive")
        env["svc"].handle(job, ProgressMonitor(env["jobs"], int(job.id), threading.Event()))
        assert env["ops"].get_operation(op.id).status == "planned"
        assert (env["src_dir"] / "a.pdf").exists()

    def test_一条任务能把排队的几批都跑完(self, env):
        a = _seed(env, "甲.pdf", category="财务")
        b = _seed(env, "乙.pdf", category="法律")
        first = env["svc"].submit([a], str(env["dst_dir"]), DEFAULT_TEMPLATE)
        second = env["svc"].submit([b], str(env["dst_dir"]), DEFAULT_TEMPLATE)
        _run(env, first.id)
        assert env["ops"].get_operation(second.id).status == "done", \
            "同一条任务领完第一条后第二条还停在 previewed，等于点了没反应"

    def test_空队列上跑处理函数不报错(self, env):
        env["jobs"].enqueue("archive", priority=3)
        job = env["jobs"].latest_of_kind("archive")
        env["svc"].handle(job, ProgressMonitor(env["jobs"], int(job.id), threading.Event()))


@contextmanager
def _opened_without_delete_share(path: Path):
    """以「别人能读、但不能改名/删除」的方式占住文件。

    这正是 PDF 阅读器（PyMuPDF）打开文件时 Windows 给的共享模式：`shutil.move` 的
    rename 会失败，回退成 copy2 + unlink 后 unlink 再失败 —— **ISSUES I104** 的现场。
    """
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateFileW.restype = wintypes.HANDLE
    kernel32.CreateFileW.argtypes = [
        wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
        wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    generic_read, open_existing = 0x80000000, 3
    share_read_write = 0x00000001 | 0x00000002
    handle = kernel32.CreateFileW(str(path), generic_read, share_read_write,
                                  None, open_existing, 0, None)
    if handle in (None, wintypes.HANDLE(-1).value):
        raise OSError(ctypes.get_last_error(), f"CreateFileW 失败：{path}")
    try:
        yield
    finally:
        kernel32.CloseHandle(handle)


@pytest.mark.skipif(sys.platform != "win32", reason="共享模式导致的删源失败只在 Windows 上成立")
class TestI104RollbackWhenSourceLocked:
    """**ISSUES I104**：搬运失败后不许把同一份文件留成两份。

    轮十九真机截图 S4 逮到 `partially_done 3/2/1`：阅读器开着 HB-001 时执行归档，
    `shutil.move` 的 rename 被占用 → copy2 成功 → unlink 源抛 WinError 32，目标目录里
    留下一份一模一样的副本，台账只写"那一项失败了"。源还在 ⇒ 撤掉刚造的目标副本，
    失败项才真的等于"什么都没发生"。
    """

    def test_同盘move删源被占用时撤回目标副本(self, env):
        doc_id = _seed(env, "被阅读器打开.pdf", category="财务")
        op = env["svc"].submit([doc_id], str(env["dst_dir"]), DEFAULT_TEMPLATE)
        item = env["ops"].list_items(op.id)[0]
        src, dst = Path(item.src_path), Path(item.dst_path)

        with _opened_without_delete_share(src):
            final = _run(env, op.id)

        assert final.status == "failed"
        assert src.exists(), "源被别的进程占着，本来就不该删掉"
        assert not dst.exists(), "源还在、目标也留着一份 = 同一份文件变两份（I104 的现场）"
        events = [e["event"] for e in _journal_events(env, op.id)]
        assert "item_rollback" in events, f"回滚没留下痕迹：{events}"
        assert events.index("item_rollback") < events.index("item_failed")

    def test_跨盘copy删源被占用时撤回目标副本(self, env):
        doc_id = _seed(env, "跨盘被打开.pdf", category="财务",
                       device_id=os.stat(env["dst_dir"]).st_dev + 7)
        op = env["svc"].submit([doc_id], str(env["dst_dir"]), DEFAULT_TEMPLATE)
        item = env["ops"].list_items(op.id)[0]
        assert item.kind == "copy", "用例前提：跨盘项走 copy + 验完再删源那条链"
        src, dst = Path(item.src_path), Path(item.dst_path)

        with _opened_without_delete_share(src):
            final = _run(env, op.id)

        assert final.status == "failed"
        assert src.exists()
        assert not dst.exists(), "copy 验证完但删源失败时同样要把目标副本撤回"
        events = [e["event"] for e in _journal_events(env, op.id)]
        assert "dst_verified" in events and "src_removed" not in events, \
            f"删源失败却写了 src_removed，journal 与磁盘对不上：{events}"
        assert "item_rollback" in events, f"回滚没留下痕迹：{events}"
