"""OCR 的两条纯判据：哪几页要跑、什么时候可以不跑（阶段 5 第 1、8 条）。

放 unit 是因为这两条判据没有库、没有 PDF 也能穷举，而它们错了的话真引擎跑一万四千小时也是白跑：
「避免重复处理未变化的文件」和「普通文字 PDF 不应无意义地反复执行 OCR」这两条验收
**全部**落在这两个函数上，界面上的数字只是它们的投影。

`ocr_ready` 是第三条：有没有资格被问这两个函数。它的判据是"正文判定存不存在"，
不是"ocr_status 是什么"，混起来就会出现"对一份从没索引过的文字版 PDF 把每页都识别一遍"。
"""
from __future__ import annotations

import pytest

from pdfarchiver.parsing.classify import (MIN_CHARS_PER_BEARING_PAGE, OCR_DONE, OCR_FAILED,
                                          OCR_NA, OCR_PARTIAL, OCR_PENDING, ocr_is_current,
                                          ocr_ready)
from pdfarchiver.services.ocr_service import pages_needing_ocr

V1 = "rapidocr-onnxruntime/1.4.4+onnxruntime/1.20.1+dpi200"
V2 = "rapidocr-onnxruntime/1.5.0+onnxruntime/1.20.1+dpi200"
ENOUGH = MIN_CHARS_PER_BEARING_PAGE


def test_原生字数够的页永远不进待办也不进复用() -> None:
    """它有字，本来就不用 OCR —— 既不该推理，也不该被算成"OCR 已经完成的一页"。"""
    todo, reused = pages_needing_ocr({1: ENOUGH, 2: ENOUGH * 3}, {}, 2, V1)
    assert (todo, reused) == ([], 0), "文字版 PDF 被拖进了 OCR 待办，这一条就是「无意义反复执行」"


def test_从没跑过的页进待办() -> None:
    todo, reused = pages_needing_ocr({}, {}, 3, V1)
    assert todo == [1, 2, 3] and reused == 0


def test_版本没变的页算复用不重新推理() -> None:
    todo, reused = pages_needing_ocr({}, {1: V1, 2: V1, 3: V1}, 3, V1)
    assert todo == [] and reused == 3, "引擎没变还要重跑，就是 1,144 小时那个量级"


def test_旧版本的页重新进待办() -> None:
    """引擎升版 = 这一页的结果不再可信，必须重跑（阶段 5 决策 4 加 `ocr_version` 列的全部理由）。"""
    todo, reused = pages_needing_ocr({}, {1: V1, 2: V1}, 2, V2)
    assert todo == [1, 2] and reused == 0


def test_失败页没有版本记录所以一定回到待办() -> None:
    """识别失败的页什么都不写（模块说明第 3 条），于是"重试"不需要额外的状态位。"""
    todo, reused = pages_needing_ocr({}, {1: V1}, 3, V1)
    assert todo == [2, 3] and reused == 1


def test_空白页识别成功过就算跑完不再重试() -> None:
    """"这一页本来就没字"与"这一页失败了"是两件事：前者有版本记录，后者没有。"""
    todo, reused = pages_needing_ocr({}, {1: V1, 2: V1, 3: V1}, 3, V1)
    assert (todo, reused) == ([], 3)
    assert pages_needing_ocr({}, {1: V1, 2: None, 3: V1}, 3, V1)[0] == [2], \
        "版本列被写成 None 的页必须重跑，否则一次部分失败就永远补不回来"


def test_混合文档只把缺字的页排进待办() -> None:
    """946 页的书只有 3 页是贴图，重跑只该跑那 3 页 —— 按页幂等的全部意义。"""
    native = {n: ENOUGH for n in range(1, 8)}          # 前 7 页有字
    todo, reused = pages_needing_ocr({**native, 9: ENOUGH - 1}, {8: V1}, 10, V1)
    assert todo == [9, 10], "待办页算错，混合文档要么白跑要么漏跑"
    assert reused == 1
    assert len(todo) + reused <= 10, "待办 + 复用不得超过总页数，否则页数口径有两个"


def test_页数为零时不产出任何待办() -> None:
    assert pages_needing_ocr({}, {}, 0, V1) == ([], 0)


# —— ocr_is_current：整本级短路的判据 ——————————————————————

def _current(**overrides) -> bool:
    base = {"ocr_status": OCR_DONE, "ocr_pages_done": 4, "stored_version": V1,
            "version_now": V1, "pages_expected": 4}
    base.update(overrides)
    return ocr_is_current(**base)


def test_五项都满足才算当前() -> None:
    assert _current() is True


@pytest.mark.parametrize("overrides,why", [
    ({"ocr_status": OCR_PENDING}, "从没跑完过"),
    ({"ocr_status": OCR_FAILED}, "整体失败过"),
    ({"ocr_status": OCR_NA}, "判过不需要 OCR"),
    ({"pages_expected": 0}, "页数为 0 的文档不许被当成「当前且完整」"),
    ({"stored_version": V2}, "引擎版本变了"),
    ({"stored_version": None}, "版本列是空的（老库升级上来的行）"),
    ({"ocr_pages_done": 3}, "还有一页没进库"),
])
def test_缺任何一项就判不当前(overrides, why) -> None:
    assert _current(**overrides) is False, why


def test_partial跑满一半时不算当前跑满了才算() -> None:
    """`partial` 必须在"跑满"时也能短路，否则每次重启都把混合文档重跑一遍。"""
    assert _current(ocr_status=OCR_PARTIAL, ocr_pages_done=3, pages_expected=4) is False
    assert _current(ocr_status=OCR_PARTIAL, ocr_pages_done=4, pages_expected=4) is True


# —— ocr_ready：入场券 ——————————————————————————————————

@pytest.mark.parametrize("text_status", ["native", "mixed", "none"])
def test_有正文判定的才发入场券(text_status) -> None:
    assert ocr_ready(text_status) is True


@pytest.mark.parametrize("text_status,why", [
    ("pending", "还没索引，一页的原生字数都不知道"),
    ("failed", "整本读不出来，那是 parse_status 的事"),
])
def test_没有正文判定的不发入场券(text_status, why) -> None:
    assert ocr_ready(text_status) is False, why
