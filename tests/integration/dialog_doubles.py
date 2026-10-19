"""界面测试的**对话框替身**，一份（轮十五 甲，2026-10-20）。

为什么单独成模块：offscreen 下真 `QMessageBox.exec()` 会把主线程堵死 —— 漏装替身的测试
**不会红，只会永远不结束**（`test_archive_execute_ui.py` 的 docstring 记过那次实测卡死）。
同一条需求从 **ISSUES I78** 那批起散在四个测试文件里，其中两份逐字相同；各抄一份迟早会漂，
理由与 `tests/conftest.py` 里 `settle` 的那一段一样，做法沿 `tests/integration/ocr_doubles.py`
（**ISSUES I58** 丙 定下的"共享夹具/替身搬进一个非 `test_` 前缀的 helpers 模块"）。

**刻意没并进来的两份**：`test_archive_execute_ui.py`（只截 information/warning，`question`
回 `Ok`）与 `test_category_export_ui.py`（`question` 的答复由它自己那份 `answers` 决定，
要演"按 No 就不写"）。它们要回的按钮本来就不同，并成一个带开关的替身只会把"这一句到底
按了什么"读得更含糊 —— 并进来的两份是**逐字相同**的那两份，不是"差不多"的那两份。

`stub_message_boxes` 里 `question` 一律回 `Yes`：这一份只服务"确认了就写"的主路，
需要演"人按了取消 / 按了 No"的测试自己接管那一句。
"""
from __future__ import annotations

from PySide6 import QtWidgets


def stub_message_boxes(monkeypatch) -> list[tuple[str, str, str]]:
    """截住四句模态提示，把 `(kind, title, text)` 记进返回的清单 —— 这批测试的读数全在文案里。"""
    shown: list[tuple[str, str, str]] = []

    def _capture(kind: str, reply=None):
        def _fn(parent, title, text, *a, **k):
            shown.append((kind, title, str(text)))
            return reply
        return staticmethod(_fn)

    monkeypatch.setattr(QtWidgets.QMessageBox, "information", _capture("information"))
    monkeypatch.setattr(QtWidgets.QMessageBox, "warning", _capture("warning"))
    monkeypatch.setattr(QtWidgets.QMessageBox, "critical", _capture("critical"))
    monkeypatch.setattr(QtWidgets.QMessageBox, "question",
                        _capture("question", QtWidgets.QMessageBox.StandardButton.Yes))
    return shown


def stub_item_chooser(monkeypatch) -> dict[str, object]:
    """把 `QInputDialog.getItem`（改父类 / 合并分类 / 标签并入 挑目标那一格）换成"按下指定的名字"。

    返回的是一个可写的 dict：`ctl["name"]` 是要选的那一项，`ctl["items"]` 记下界面**实际**
    摆出来的清单 —— 「自己不出现在候选里」这条就靠后者断言，不靠读代码。
    名字不在清单里时 `ok=False`，等于人按了取消。
    """
    ctl: dict[str, object] = {"name": "", "items": []}

    def _getItem(parent, title, prompt, items, *a, **k):
        ctl["items"] = list(items)
        wanted = str(ctl["name"])
        return wanted, wanted in items

    monkeypatch.setattr(QtWidgets.QInputDialog, "getItem", staticmethod(_getItem))
    return ctl


def stub_text_prompt(monkeypatch) -> dict[str, object]:
    """把 `QInputDialog.getText` 换成"依次吐出这几句"（标签名、集合名、新名字都走它）。

    队列吐完就返回 `("", False)` = 人按了取消，所以"多问了一次"不会被静默喂一个默认值。
    """
    ctl: dict[str, object] = {"queue": [], "asked": []}

    def _getText(parent, title, prompt, *a, **k):
        ctl["asked"].append((str(title), str(prompt)))
        if not ctl["queue"]:
            return "", False
        return str(ctl["queue"].pop(0)), True

    monkeypatch.setattr(QtWidgets.QInputDialog, "getText", staticmethod(_getText))
    return ctl
