"""S3「执行归档」与 S4「撤销选中批次」真的接到执行器（A2 / A3 / A4 · **D-042** 丙 / **D-043** 甲）。

这批测试只认一条判据：**按下按钮之后，库里的批次、队列里的任务、磁盘上的文件三者对不对得上**。
以前这两个按钮按下去只报一句「还没接上」，所以那时有反向守卫（不许伪装成功）；
现在接上了，守卫就翻过来钉"接上之后不许偷偷做多余的事"：

- 没看过计划 ⇒ 不许有批次（`previewed` 的唯一入口是 `submit()`，worker 只领 `previewed`）；
- 确认框取消 ⇒ 库里、队列里、磁盘上都不许有变化；
- 旧预览不许授权执行 ⇒ 计划变了必须先作废重看（`_signature` 逐条比对）；
- 预览表里那一行的目标路径 ⇒ 必须就是执行后磁盘上那个文件（阶段 4 门禁「预览与实际执行的
  文件集合逐条一致」的界面版），这也是命名模板真的参与渲染（A3）最硬的证据；
- 目标卷装不下 ⇒ 「执行归档」是**禁用**，不是"再提醒一次"（`docs/DATABASE.md` §5.2 末条）。

`confirm_dangerous()` 换成记录器（真模态框在 offscreen 下会堵主线程），控件本身由
`test_confirm_control.py` 直接驱动 —— 换掉的只是"人点没点确认"这一个布尔，
而"确认后系统做了什么"仍是真代码 + 真库 + 真文件（**D-012**）。
"""
from __future__ import annotations

import threading
from pathlib import Path

import pytest
from PySide6 import QtCore, QtWidgets

from pdfarchiver.db.models import Document
from pdfarchiver.fs.identity import read_identity
from pdfarchiver.jobs.queue import ProgressMonitor
from pdfarchiver.ui.confirm import DangerSummary
from tests.conftest import settle as _settle

DEFAULT_TEMPLATE = "{category}/{year}/{name}.pdf"
BODY = b"%PDF-1.7\narchive-ui-fixture\n" * 8


class _Answers:
    """分级确认控件的记录器：记下页面上摆给人看的那份账，再按 `answer` 回答"确不确定"。"""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, DangerSummary]] = []
        self.answer = True

    def __call__(self, parent, *, title: str, verb: str, summary: DangerSummary) -> bool:
        self.calls.append((title, verb, summary))
        return self.answer


@pytest.fixture
def answers(monkeypatch):
    from pdfarchiver.ui.pages import archive_page, operations_page

    ctl = _Answers()
    monkeypatch.setattr(archive_page, "confirm_dangerous", ctl)
    monkeypatch.setattr(operations_page, "confirm_dangerous", ctl)
    return ctl


@pytest.fixture(autouse=True)
def dialogs(monkeypatch) -> list[tuple[str, str, str]]:
    """截住模态提示，返回 `(kind, title, text)` 清单 —— 文案是这批测试的读数。

    **autouse 是必需的，不是省事**：offscreen 下真 `QMessageBox` 的 `exec()` 会把主线程堵死，
    而按下去的那个按钮（「执行归档」「撤销选中批次」）收尾正有一句回执弹窗。漏装这条夹具的
    测试不会红，只会**永远不结束**（本轮实测卡在这里一次）。
    """
    shown: list[tuple[str, str, str]] = []

    def _capture(kind: str):
        def _fn(parent, title, text, *a, **k):
            shown.append((kind, title, str(text)))
            return QtWidgets.QMessageBox.StandardButton.Ok
        return staticmethod(_fn)

    monkeypatch.setattr(QtWidgets.QMessageBox, "information", _capture("information"))
    monkeypatch.setattr(QtWidgets.QMessageBox, "warning", _capture("warning"))
    return shown


def _archive_page(window, qapp):
    window._select_by_page_id("archive")
    _settle(qapp)
    return window._pages["archive"]


def _ops_page(window, qapp):
    window._select_by_page_id("operations")
    _settle(qapp)
    return window._pages["operations"]


def _seed(ctx, path: Path, *, size_bytes: int | None = None,
          device_id: int | None = None) -> int:
    """真文件 + 真主记录（跨盘那一档靠换 `device_id`，口径同 **ISSUES I40**）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(BODY)
    identity = read_identity(path)
    doc = ctx.documents.upsert(Document(
        path=identity.path, path_key=identity.path_key, name=identity.name, ext=identity.ext,
        size_bytes=identity.size_bytes if size_bytes is None else size_bytes,
        mtime_ns=identity.mtime_ns, ctime_ns=identity.ctime_ns, file_id=identity.file_id,
        device_id=identity.device if device_id is None else device_id,
        parse_status="ok", text_status="native", fts_status="done"))
    return int(doc.id)


def _arm(page, doc_ids: list[int], target_root: str,
         template: str = DEFAULT_TEMPLATE) -> None:
    """把 S3 摆成"勾好了、目标根也给了"的样子（还没生成预览）。"""
    page.target_root_input.setText(target_root)
    page.template_input.setText(template)
    page._load_documents()
    wanted = {str(i) for i in doc_ids}
    for row in range(page.doc_table.rowCount()):
        cell = page.doc_table.item(row, 0)
        if str(cell.data(QtCore.Qt.ItemDataRole.UserRole)) in wanted:
            cell.setCheckState(QtCore.Qt.CheckState.Checked)


def _run_batch(ctx, op_id: int):
    """按队列的调用形状把批次跑掉（生产同一条 `handler(job, monitor)`，**ISSUES I68**）。"""
    job = ctx.jobs.latest_of_kind("archive")
    assert job is not None, "提交批次必须同时排出一条后台任务"
    ctx.archive.handle(job, ProgressMonitor(ctx.jobs, int(job.id), threading.Event()))
    return ctx.operations.get_operation(op_id)


def _row_of(table, op_id: int) -> int:
    for row in range(table.rowCount()):
        if table.item(row, 0).data(QtCore.Qt.ItemDataRole.UserRole) == op_id:
            return row
    raise AssertionError(f"台账里列不出批次 #{op_id}")


def _column(table, col: int) -> list[str]:
    return [table.item(r, col).text() for r in range(table.rowCount())]


# —— S3：预览 → 确认 → 提交 ——————————————————————————————————

def test_没看过计划就不许建批次(window, ctx, qapp, tmp_path, dialogs) -> None:
    (tmp_path / "归档库").mkdir()
    doc_id = _seed(ctx, tmp_path / "候选" / "甲.pdf")
    page = _archive_page(window, qapp)
    _arm(page, [doc_id], str(tmp_path / "归档库"))

    assert not page.execute_btn.isEnabled(), "「执行」在未生成预览前必须按不动（§S3）"
    page._execute_archive()                       # 绕过禁用直接调用：第二道闸也得拦住

    # 「请先点生成预览」和「计划已经变了」两句警告里挑一句当证据不行：两句都含「生成预览」，
    # 把第一道闸删掉照样能骗过这条断言（本轮注入实测）。要点名是哪一道闸拦住的。
    assert "没看过计划" in dialogs[-1][2], dialogs[-1]
    assert ctx.operations.list_operations(limit=50) == []
    assert ctx.jobs.latest_of_kind("archive") is None, "界面在背地里排任务"


def test_预览之后落的是同一份计划加一次后台任务(window, ctx, qapp, tmp_path,
                                                  answers, dialogs) -> None:
    (tmp_path / "归档库").mkdir()
    doc_id = _seed(ctx, tmp_path / "候选" / "乙.pdf")
    page = _archive_page(window, qapp)
    _arm(page, [doc_id], str(tmp_path / "归档库"))
    page.preview_btn.click()

    assert page.preview_table.rowCount() == 1
    assert page.execute_btn.isEnabled()
    assert answers.calls == [], "预览不是确认，不该弹分级控件"

    page.execute_btn.click()

    title, verb, summary = answers.calls[-1]
    assert title.startswith("确认执行归档") and verb == "归档"
    assert (summary.will_run, summary.same_disk, summary.cross_disk, summary.irreversible) \
        == (1, 1, 0, 0), f"确认框摆的账与计划不一致：{summary}"

    ops = ctx.operations.list_operations(limit=50)
    assert len(ops) == 1
    op = ops[0]
    assert (op.kind, op.status, op.items_total) == ("archive", "previewed", 1)
    job = ctx.jobs.latest_of_kind("archive")
    assert job is not None and job.state == "queued"
    assert f"已提交 #{op.id}｜共 1 项" in dialogs[-1][2], dialogs[-1]

    assert page._preview is None and not page.execute_btn.isEnabled(), (
        "提交后旧预览必须作废：不然连点两次就是把同一份计划执行两遍")
    assert page.preview_table.rowCount() == 0


def test_取消确认之后库里队列磁盘都不许变(window, ctx, qapp, tmp_path, answers,
                                          dialogs) -> None:
    dst = tmp_path / "归档库"
    dst.mkdir()
    src = tmp_path / "候选" / "丙.pdf"
    doc_id = _seed(ctx, src)
    page = _archive_page(window, qapp)
    _arm(page, [doc_id], str(dst))
    page.preview_btn.click()

    answers.answer = False                        # 用户在分级控件上点「取消，什么都不做」
    page.execute_btn.click()

    assert len(answers.calls) == 1, "取消也该先让人看过那份账"
    assert ctx.operations.list_operations(limit=50) == []
    assert ctx.jobs.latest_of_kind("archive") is None
    assert src.exists() and not (dst / "_未分类").exists(), "取消之后磁盘上留了痕迹"
    assert dialogs == [], "取消是一次正常处置，不该再弹一个警告吓用户"
    assert page.execute_btn.isEnabled(), "取消不该顺手把人看过的计划清掉"


def test_旧预览不许授权执行(window, ctx, qapp, tmp_path, answers, dialogs) -> None:
    """磁盘上文件动了而界面信号没响 —— 这种漂移只能靠执行前重算、逐条比对拦住。"""
    dst = tmp_path / "归档库"
    dst.mkdir()
    src = tmp_path / "候选" / "丁.pdf"
    doc_id = _seed(ctx, src)
    page = _archive_page(window, qapp)
    _arm(page, [doc_id], str(dst))
    page.preview_btn.click()

    src.unlink()                                  # 用户自己在资源管理器里把它挪走了
    page.execute_btn.click()

    assert "已经不一致" in dialogs[-1][2], dialogs[-1]
    assert len(answers.calls) == 0, (
        "计划都不一致了还弹确认框，就是把旧的那份执行出去")
    assert ctx.operations.list_operations(limit=50) == []
    assert page._preview is None

    page.preview_btn.click()                      # 重看一遍，这一次的原因必须摆出来
    assert page.preview_table.rowCount() == 1
    assert "源文件已经不在磁盘上" in _column(page.preview_table, 4), (
        "跳过没有原因文本即判红（§S3），界面不许自己编一句")


def test_全部跳过时不建批次也不弹确认(window, ctx, qapp, tmp_path, answers, dialogs) -> None:
    (tmp_path / "归档库").mkdir()
    src = tmp_path / "候选" / "戊.pdf"
    doc_id = _seed(ctx, src)
    src.unlink()                                  # 库里有记录，磁盘上已经没有
    page = _archive_page(window, qapp)
    _arm(page, [doc_id], str(tmp_path / "归档库"))
    page.preview_btn.click()
    page.execute_btn.click()

    assert answers.calls == [], "一项都不动的操作不该走危险操作控件"
    assert ctx.operations.list_operations(limit=50) == []
    assert "全部被跳过" in dialogs[-1][2], dialogs[-1]


def test_跨盘装不下时执行键是禁用的(window, ctx, qapp, tmp_path, answers, dialogs) -> None:
    """`docs/DATABASE.md` §5.2 末条：执行前查剩余空间，不足 ⇒ 「执行」**禁用**，不是再提醒一次。"""
    (tmp_path / "归档库").mkdir()
    # 假 device_id ⇒ 计划判成跨盘 copy；size 给 1TB ⇒ 任何现实卷都装不下
    doc_id = _seed(ctx, tmp_path / "候选" / "己.pdf",
                   size_bytes=1024 ** 4, device_id=999_999_999)
    page = _archive_page(window, qapp)
    _arm(page, [doc_id], str(tmp_path / "归档库"))
    page.preview_btn.click()

    assert "空间不足" in page.plan_summary.text() and "已禁用" in page.plan_summary.text()
    assert not page.execute_btn.isEnabled(), "计数条写着禁用而按钮还开着，那句话就是假的"

    page._execute_archive()                       # 第二道闸：绕过禁用也拦得住
    assert answers.calls == [], "空间不足还弹确认框，就是把禁用降级成一次点击"
    assert ctx.operations.list_operations(limit=50) == []
    assert "已拒绝执行" in dialogs[-1][2], dialogs[-1]


# —— A3：模板真的参与渲染 ——————————————————————————————————

def test_改模板之后预览的目标路径跟着变(window, ctx, qapp, tmp_path) -> None:
    (tmp_path / "归档库").mkdir()
    doc_id = _seed(ctx, tmp_path / "候选" / "庚.pdf")
    page = _archive_page(window, qapp)
    _arm(page, [doc_id], str(tmp_path / "归档库"))
    page.preview_btn.click()
    first = page.preview_table.item(0, 1).text()

    page.template_input.setText("{name}_归档.pdf")
    assert page._preview is None and not page.execute_btn.isEnabled(), (
        "模板变了而预览还留着，执行的就是没看过的那份计划")

    page.preview_btn.click()
    second = page.preview_table.item(0, 1).text()
    assert Path(second).name == "庚_归档.pdf"
    assert Path(first).name != Path(second).name


# —— A2 端到端：预览那一行 == 磁盘上那个文件（真后台线程）——————————————

def test_预览里的目标路径就是执行后磁盘上的路径(window, ctx, qapp, tmp_path,
                                                answers) -> None:
    dst = tmp_path / "归档库"
    dst.mkdir()
    src = tmp_path / "候选" / "辛.pdf"
    doc_id = _seed(ctx, src)
    original_bytes = src.read_bytes()
    page = _archive_page(window, qapp)
    _arm(page, [doc_id], str(dst))
    page.preview_btn.click()
    target = Path(page.preview_table.item(0, 1).text())

    queue = ctx.start_background()
    page.execute_btn.click()
    assert queue.wait_until_idle(timeout=60.0), "后台队列没把这一批跑完"

    assert target.exists(), f"预览说落到 {target}，磁盘上却没有它"
    assert target.read_bytes() == original_bytes, "搬过去的字节必须与原文件一致"
    assert not src.exists(), "同盘 rename 之后原位不该还留着"
    assert Path(ctx.documents.get(doc_id).path) == target, \
        "库里也要跟着走，否则下一轮扫描只会把它标成 missing"
    assert ctx.operations.list_operations(limit=50)[0].status == "done"


# —— S4：整批撤销 ————————————————————————————————————————————

def _archived(ctx, tmp_path, names: list[str]) -> int:
    """走服务层建一批真归档并跑完，返回批次 id（S4 的前置状态，不是被测动作）。"""
    dst = tmp_path / "归档库"
    dst.mkdir(exist_ok=True)
    doc_ids = [_seed(ctx, tmp_path / "候选" / name) for name in names]
    op = ctx.archive.submit(doc_ids, str(dst), DEFAULT_TEMPLATE)
    _run_batch(ctx, op.id)
    return op.id


def test_没选中批次时撤销只问一句而不建东西(window, ctx, qapp, answers, dialogs) -> None:
    page = _ops_page(window, qapp)
    assert page.op_table.rowCount() == 0
    page.undo_btn.click()

    assert "请先选择" in dialogs[-1][2]
    assert answers.calls == []
    assert ctx.operations.list_operations(limit=50) == []


def test_撤销确认后另开一条反向批次并排队(window, ctx, qapp, tmp_path, answers,
                                          dialogs) -> None:
    op_id = _archived(ctx, tmp_path, ["壬.pdf"])
    page = _ops_page(window, qapp)
    page.reload()
    page.op_table.setCurrentCell(_row_of(page.op_table, op_id), 0)
    page.undo_btn.click()

    title, verb, summary = answers.calls[-1]
    assert title == f"确认撤销批次 #{op_id}" and verb == "撤销"
    assert (summary.will_run, summary.same_disk, summary.irreversible) == (1, 1, 0)
    assert summary.lines == (), "没有排除项就不许编一条排除原因"

    ops = ctx.operations.list_operations(limit=50)
    undo = next(o for o in ops if o.kind == "undo")
    assert (undo.undo_of, undo.status, undo.items_total) == (op_id, "previewed", 1)
    assert ctx.jobs.latest_of_kind("archive") is not None
    assert f"已提交撤销批次 #{undo.id}（撤销 #{op_id}）" in dialogs[-1][2], dialogs[-1]
    assert ctx.operations.get_operation(op_id).status == "done", (
        "只是提交了反向批次，原批次的态要等它真跑完才许变")


def test_撤销取消确认之后什么都不建(window, ctx, qapp, tmp_path, answers, dialogs) -> None:
    op_id = _archived(ctx, tmp_path, ["癸.pdf"])
    archived = Path(ctx.operations.list_items(op_id)[0].dst_path)
    ops_before = len(ctx.operations.list_operations(limit=50))
    jobs_before = ctx.jobs.count()

    page = _ops_page(window, qapp)
    page.reload()
    page.op_table.setCurrentCell(_row_of(page.op_table, op_id), 0)
    answers.answer = False
    page.undo_btn.click()

    assert len(answers.calls) == 1
    assert len(ctx.operations.list_operations(limit=50)) == ops_before
    assert ctx.jobs.count() == jobs_before, "取消之后队列里多出一条反向批次"
    assert archived.exists(), "取消之后归档位置的文件不该动"
    assert dialogs == []


def test_排除项的条数与逐条原因都摆在确认框里(window, ctx, qapp, tmp_path, answers,
                                              dialogs) -> None:
    """**D-043** 甲 第 2 行：撤销排除的条数与原因必须显示，不许只显示撤销成功。"""
    op_id = _archived(ctx, tmp_path, ["子.pdf", "丑.pdf"])
    gone = next(i for i in ctx.operations.list_items(op_id) if "子" in i.dst_path)
    Path(gone.dst_path).unlink()

    page = _ops_page(window, qapp)
    page.reload()
    page.op_table.setCurrentCell(_row_of(page.op_table, op_id), 0)
    page.undo_btn.click()

    summary = answers.calls[-1][2]
    assert summary.will_run == 1, "被排除的那项不许混进要执行的条数里"
    assert summary.lines[0] == "排除 1 项，原因逐条："
    assert any("已经不在了" in line for line in summary.lines[1:]), summary.lines

    undo = next(o for o in ctx.operations.list_operations(limit=50) if o.kind == "undo")
    assert undo.items_total == 1
    assert "排除 1 项" in dialogs[-1][2], dialogs[-1]


def test_没有可撤项时不开一条空批次(window, ctx, qapp, tmp_path, answers, dialogs) -> None:
    op_id = _archived(ctx, tmp_path, ["寅.pdf"])
    for item in ctx.operations.list_items(op_id):
        Path(item.dst_path).unlink()

    page = _ops_page(window, qapp)
    page.reload()
    page.op_table.setCurrentCell(_row_of(page.op_table, op_id), 0)
    page.undo_btn.click()

    assert answers.calls == [], "没有可撤的项就不该弹危险操作确认框"
    assert "没有可撤销的项" in dialogs[-1][2]
    assert "已经不在了" in dialogs[-1][2], "原因要逐条给，不许只说一句没有可撤的项"
    assert [o for o in ctx.operations.list_operations(limit=50) if o.kind == "undo"] == []


def test_撤销撤销批次被拒绝并显示原因(window, ctx, qapp, tmp_path, answers, dialogs) -> None:
    """台账不许变成一条无限套娃的链（`plan_undo` 里那条拒绝）。"""
    op_id = _archived(ctx, tmp_path, ["卯.pdf"])
    undo_op, _, _ = ctx.archive.submit_undo(op_id)
    _run_batch(ctx, undo_op.id)

    page = _ops_page(window, qapp)
    page.reload()
    page.op_table.setCurrentCell(_row_of(page.op_table, undo_op.id), 0)
    page.undo_btn.click()

    assert answers.calls == []
    assert "撤销撤销批次" in dialogs[-1][2], dialogs[-1]
    assert len([o for o in ctx.operations.list_operations(limit=50) if o.kind == "undo"]) == 1


def test_撤销跑完之后台账上原批次显示已撤销(window, ctx, qapp, tmp_path, answers) -> None:
    """`undone` 是 `docs/DATABASE.md` §二 词表里那一态，而 S4 的批次表就是它的显示出口。"""
    op_id = _archived(ctx, tmp_path, ["辰.pdf"])
    page = _ops_page(window, qapp)
    page.reload()
    page.op_table.setCurrentCell(_row_of(page.op_table, op_id), 0)
    page.undo_btn.click()
    undo_op = next(o for o in ctx.operations.list_operations(limit=50) if o.kind == "undo")
    _run_batch(ctx, undo_op.id)

    page.reload()
    assert _column(page.op_table, 2)[_row_of(page.op_table, op_id)] == "undone"
    assert _column(page.op_table, 2)[_row_of(page.op_table, undo_op.id)] == "done"
