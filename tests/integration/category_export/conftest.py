"""分类清单导出测试的专用夹具（2026-10-20 随 791 行拆分从原测试文件搬来）。

三份测试共用同一棵树与同一套模态替身：`branch` 的"同名两枝 + 父亲自己挂文档"是
硬断言 (a) 与 (e) 的现场，拆文件时不能各造一棵 —— 两棵树一旦漂了，两份断言就各验各的。
里面的关系与原来逐字一致：

- 「导出测试财务/合同」与「导出测试技术/合同」同名不同层：**ISSUES I77** 甲 的 0008 迁移
  只锁同层重名，所以按**名字**取子树会把两枝并成一坨 —— 这棵树就是为了让那种并法露出来（(e)）。
- 「导出测试财务」自己名下有 2 份，子枝另有 3 + 1 份：这样"含子分类"切下去是
  **6 → 2** 而不是 **6 → 0**。关掉之后一个都导不出来那种数，分不清"谓词换了"和"当场拒了"。

`dialogs` 的 autouse 必需性与 `test_catalog_writes_ui.py` 同一条：offscreen 下真 `QMessageBox`
的 `exec()` 会把主线程堵死。
"""
from __future__ import annotations

import pytest
from PySide6 import QtWidgets

from _helpers import _docs


@pytest.fixture(autouse=True)
def need_qapp(qapp):
    """本目录每一条都要构造 `QDialog`：没有 QApplication 就构造 QWidget 是直接 abort 进程。"""
    return qapp


@pytest.fixture
def answers() -> dict:
    """模态回答的旋钮，默认一律"Yes"。

    autouse 的 `dialogs` 是在**每次调用时**读这个 dict 的，所以测试里先把它改成 `No`
    再驱动控件是有效的（而不是把夹具顺序赌上去）。
    """
    return {"question": QtWidgets.QMessageBox.StandardButton.Yes}


@pytest.fixture(autouse=True)
def dialogs(monkeypatch, answers) -> list[tuple[str, str, str]]:
    """截住模态提示，返回 `(kind, title, text)` 清单 —— 这批测试的读数大半在文案里。"""
    shown: list[tuple[str, str, str]] = []

    def _capture(kind: str, reply=None):
        def _fn(parent, title, text, *a, **k):
            shown.append((kind, title, str(text)))
            return answers["question"] if reply is None else reply
        return staticmethod(_fn)

    monkeypatch.setattr(QtWidgets.QMessageBox, "information", _capture("information"))
    monkeypatch.setattr(QtWidgets.QMessageBox, "warning", _capture("warning"))
    monkeypatch.setattr(QtWidgets.QMessageBox, "critical", _capture("critical"))
    monkeypatch.setattr(QtWidgets.QMessageBox, "question", _capture("question"))
    return shown


@pytest.fixture
def chooser(monkeypatch) -> dict:
    """把"选目录"那个系统对话框换成"返回这里指定的目录"。"""
    ctl: dict[str, object] = {"dir": ""}

    def _get_existing(parent, title, start="", *a, **k):
        return str(ctl["dir"])

    monkeypatch.setattr(QtWidgets.QFileDialog, "getExistingDirectory", staticmethod(_get_existing))
    return ctl


@pytest.fixture
def branch(ctx):
    """一棵**故意带同名两枝**的分类树，外加"父亲自己也挂文档"这一档（理由见模块 docstring）。"""
    fin = ctx.catalog.add_category("导出测试财务")
    fin_ht = ctx.catalog.add_category("合同", parent_id=fin.id)
    sub = ctx.catalog.add_category("报销", parent_id=fin.id)
    tech = ctx.catalog.add_category("导出测试技术")
    tech_ht = ctx.catalog.add_category("合同", parent_id=tech.id)
    empty = ctx.catalog.add_category("导出测试空枝")

    own = _docs(ctx, 2, "财务卷")
    kids = _docs(ctx, 3, "合同卷")
    bare = _docs(ctx, 1, "报销卷", bare=True)
    tech_ids = _docs(ctx, 2, "技术卷")
    ctx.catalog.link_categories(own, fin.id)
    ctx.catalog.link_categories(kids, fin_ht.id)
    ctx.catalog.link_categories(bare, sub.id)
    ctx.catalog.link_categories(tech_ids, tech_ht.id)
    tag = ctx.catalog.add_tag("导出测试标签")
    ctx.catalog.link_tags(own, tag.id)
    return {"fin": fin, "fin_ht": fin_ht, "sub": sub, "tech": tech, "tech_ht": tech_ht,
            "empty": empty, "own": own, "kids": kids, "bare": bare, "tech_ids": tech_ids}
