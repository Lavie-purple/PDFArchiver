"""阅读器行为断言（**ISSUES I79** 乙 + 轮四十七 ② 甲）。

这些断言钉的都是 SPEC 阶段 3 验收里"阅读器不崩、进度不丢"那一条，之前只有"手动点过没坏"的层次：

1. 缩放档 —— `_zoom_in` / `_zoom_out` 的上下限（4.0 / 0.3）与倍率（1.2×）必须逐次生效，
   不超界、不跳步。
2. 损坏 / 失效文件不崩且回显原文 —— `pymupdf.open()` 抛异常时必须走 `QMessageBox.critical`，
   标题是「打开 PDF 失败」，正文是异常原文（不是"未知错误"之类的遮罩）。
3. 阅读进度跨重启恢复 —— 翻到第 N 页后 `last_read_page` 必须写进库；用同一个 `Engine`
   重新打开同一份文档，阅读器必须停在那一页（1-based 口径，与 `text_pages.page_no` 一致）。
4. 「适应宽度」那一态（**Q1 甲-1 / Q2 甲+乙**）—— 倍率 = 现视口宽 ÷ 当页 1.0 倍渲染宽，
   按下的那一次同步铺满、拖窗只停手铺一次、手动一动就弹起、且**不受手动上限卡**。
   出厂默认开（2026-10-31 用户点名；甲-1 原判默认关）⇒ 可按下钮的 `click()` 在出厂态上是
   弹起，「按下」这条路一律走「弹起 → 再按下」。
   这一组全部是量出来的（`.tmp_probe_fit` 一次性探针，已删）：1024/1280/1600/2560 四档
   铺满之后 渲染宽 − 视口宽 = 0、横向滚动 `maximum()` 恒为 0。

第 4 组里"铺满"这一条必须写成 `±2px` 而不是"接近"：双扣竖滚条那一种坏法（第一版真写过，
`viewport().width()` 已经把滚条扣掉了再减一条）量出来正好差 8px，屏幕上就是右侧一条缝 ——
那正是用户报的「宽的时候右侧空了一块」的病根之一，容差松到 10px 就骗过去了。
"""
from __future__ import annotations

import re
from pathlib import Path
from unittest.mock import patch

import pymupdf
import pytest
from PySide6 import QtTest, QtWidgets

from pdfarchiver.db.models import Document
from pdfarchiver.ui.pages.reader_page import (
    _FIT_PIXEL_BUDGET, _REFIT_DEBOUNCE_MS, _ZOOM_MAX, ReaderPage)
from pdfarchiver.ui.theme import ThemeManager


def _insert_doc(ctx, *, path: str, page_count: int = 3) -> int:
    conn = ctx.engine.thread_connection()
    conn.execute(
        "INSERT INTO documents(path, path_key, name, ext, size_bytes, mtime_ns,"
        " page_count, created_at, updated_at)"
        " VALUES(?,?,?,?,?,?,?,1,1)",
        (path, path.lower(), path.rsplit("/", 1)[-1], "pdf", 1024, 1, page_count))
    conn.commit()
    return int(conn.execute(
        f"SELECT id FROM documents WHERE path_key='{path.lower()}'").fetchone()[0])


def _navigate_to_reader(window, qapp) -> ReaderPage:
    """拿到阅读页并切到它。轮四十一（2026-10-29）起 S2 不占导航格，
    阅读页由外壳按需创建直接切栈 —— 这里走的就是外壳同一条路。"""
    from tests.conftest import settle as _settle
    page = window._ensure_reader_page()
    window.nav.setCurrentRow(-1)
    window.stack.setCurrentWidget(page)
    _settle(qapp)
    return page


def _open_sized_pdf(ctx, window, qapp, tmp_path: Path, sizes, name: str = "fit.pdf") -> ReaderPage:
    """按给定的页面尺寸（pt）造一份真 PDF 并在阅读器里打开它。

    尺寸必须能随用例改：适应宽度的病全在**宽窄不等的页**上（横版、票据条、A4 混排），
    而 `tests/conftest.py::_make_pdf` 把每页写死成 595×842，用它只能验出"方页恰好对"。
    """
    from tests.conftest import settle as _settle
    path = tmp_path / name
    doc = pymupdf.open()
    for width, height in sizes:
        doc.new_page(width=width, height=height)
    doc.save(str(path))
    doc.close()

    doc_id = _insert_doc(ctx, path=str(path).replace("\\", "/"), page_count=len(sizes))
    reader = _navigate_to_reader(window, qapp)
    reader.open_document(doc_id)
    _settle(qapp)
    return reader


def _await_refit(qapp) -> None:
    """让**拖窗那一路**的防抖真的到期。

    `settle()` 只跑 `processEvents()`，而 QTimer 的到期要等墙上时间走过 120ms ——
    光 processEvents 会让防抖永远不触发，断言就此变成"什么都没发生也算过"（实测）。
    """
    QtTest.QTest.qWait(_REFIT_DEBOUNCE_MS + 120)
    from tests.conftest import settle as _settle
    _settle(qapp, rounds=4)


def _filled(reader: ReaderPage) -> tuple[int, int]:
    """(渲染宽, 视口宽) —— 铺满 = 这两个数相等。"""
    return reader.pdf_label.pixmap().width(), reader.pdf_view.viewport().width()


def _qss_bg(body: str) -> str | None:
    """QSS 块体里那条 `background-color` 的实色值（认不出就回 None，让断言自己报"解析失败"）。"""
    found = re.search(r"background-color:\s*(#[0-9a-fA-F]{3,8})", body)
    return found.group(1).lower() if found else None


@pytest.mark.parametrize("width", [1024, 1280, 2560])
def test_适应宽度按下即按现视口铺满(ctx, window, qapp, tmp_path: Path, width: int) -> None:
    """**Q1 甲-1**：按下那颗之后立刻铺满、不留横向滚动，只等一次重排、**不等防抖**。

    三档窗口里 2560 是用户报的那一档（右侧空一块）。这里给的 `settle` 只是 `processEvents`：
    刚冒出来的竖滚条要一轮重排才从 `viewport().width()` 里扣掉，而防抖（QTimer 到期要走过
    120ms 墙上时间）刻意不给 —— 按下之后还得"等一下才铺满"就是另一版病。
    """
    from tests.conftest import resize_stepped, settle
    reader = _open_sized_pdf(ctx, window, qapp, tmp_path, [(595, 842)] * 2)
    resize_stepped(window, qapp, width, 720)

    # 出厂已是按下态（2026-10-31 用户点名默认开）：可按下按钮的 `click()` 在按下态上是**弹起**，
    # 所以「按下那颗」这条路 = 先弹起再按下；第二下的重铺是同步的，不等防抖（settle 一样只给重排）。
    reader.fit_btn.click()
    assert not reader.fit_btn.isChecked(), "出厂是按下态，第一下点击应当弹起"
    reader.fit_btn.click()
    settle(qapp)

    assert reader.fit_btn.isChecked(), "按下之后必须是按下态，否则这一态在屏幕上没有可见出口"
    rendered, avail = _filled(reader)
    assert abs(rendered - avail) <= 2, (
        f"{width} 档没铺满：渲染 {rendered}px / 视口 {avail}px（差 {rendered - avail}px）")
    assert reader.pdf_view.horizontalScrollBar().maximum() == 0, (
        f"{width} 档铺出了横向滚动，说明倍率算到了可视宽之外")


@pytest.mark.parametrize("width", [1024, 2560])
def test_适应宽度默认开_不点按钮首开即铺满(ctx, window, qapp, tmp_path: Path, width: int) -> None:
    """**2026-10-31 用户点名「改成默认开」**：不碰任何按钮，开文档这一下就该铺满。

    甲-1 原判默认关（宽屏首帧右侧空、每启动一次要按一次）。默认开之后这条钉住**出厂态**：
    坏法 = 摘掉构造里那句 `setChecked(True)` ⇒ 两条都红（isChecked 与渲染宽差一条视口）。
    先改窗再开文档：用户真实动线就是窗开着、点开一份 PDF。
    """
    from tests.conftest import resize_stepped, settle
    path = tmp_path / "fitdefault.pdf"
    doc = pymupdf.open()
    doc.new_page(width=595, height=842)
    doc.save(str(path))
    doc.close()

    doc_id = _insert_doc(ctx, path=str(path).replace("\\", "/"))
    reader = _navigate_to_reader(window, qapp)
    resize_stepped(window, qapp, width, 720)
    reader.open_document(doc_id)
    settle(qapp)

    assert reader.fit_btn.isChecked(), (
        "出厂就该是按下态（默认开）；一红说明构造里那句 setChecked(True) 被摘了")
    rendered, avail = _filled(reader)
    assert abs(rendered - avail) <= 2, (
        f"{width} 档首开没铺满：渲染 {rendered}px / 视口 {avail}px（差 {rendered - avail}px）")
    assert reader.pdf_view.horizontalScrollBar().maximum() == 0


def test_适应宽度不受手动上限卡(ctx, window, qapp, tmp_path: Path) -> None:
    """**Q2 甲**：这一态的倍率不许被 `_ZOOM_MAX` 截 —— 截了就永远占不满宽档。

    100×200 的窄页在 2560 档要 23.35×（渲染 2335×4670 = 10.90M 像素，仍在预算内）才铺得满；
    手动上限 4.0 一卡就只剩 400px 宽，右侧空 1900 多 px。

    这一份样本还额外走了一条别的路：1.0 倍时它只有 200px 高。出厂已按下（默认开），
    开档即铺；这里照旧走一遍「弹起 → 再按下」把用户路径过全 —— 再按下之后竖条才冒出来，
    所以视口宽必须等一次重排才作数。
    """
    from tests.conftest import resize_stepped, settle
    reader = _open_sized_pdf(ctx, window, qapp, tmp_path, [(100, 200)])
    resize_stepped(window, qapp, 2560, 720)

    reader.fit_btn.click()   # 出厂按下 ⇒ 这一下弹起
    reader.fit_btn.click()   # 再按下 → 立刻铺满
    settle(qapp)

    assert reader._zoom_level > _ZOOM_MAX, (
        f"这一态被手动上限卡住了：{_ZOOM_MAX} 装不满 2560 档，实际倍率 {reader._zoom_level}")
    rendered, avail = _filled(reader)
    assert abs(rendered - avail) <= 2, f"窄页没铺满：渲染 {rendered} / 视口 {avail}"
    assert reader.pdf_view.horizontalScrollBar().maximum() == 0


def test_超预算的窄长页按预算夹住(ctx, window, qapp, tmp_path: Path) -> None:
    """50×3000 那一档：按宽铺满要 16M 像素，必须夹到预算，且**不许**因此滚出横向条。

    夹完是 448×26833 = 12.02M —— 比预算多出的那 0.2% 是 PyMuPDF 把每条边**向上取整**
    （8.9443×50 = 447.2 → 448）来的，所以容差按 1% 写，不是把预算写松。
    横向留一条空是这一档**设计内**的（断言反过来钉它），但竖向照旧、横向滚动照旧为 0。
    出厂已按下（默认开）：开档那次渲染就是这条路的现值，不再补按。
    """
    reader = _open_sized_pdf(ctx, window, qapp, tmp_path, [(50, 3000)])

    pix = reader.pdf_label.pixmap()
    assert pix.width() * pix.height() <= _FIT_PIXEL_BUDGET * 1.01, (
        f"超预算：{pix.width()}×{pix.height()} = {pix.width() * pix.height():,} 像素")
    assert pix.width() < reader.pdf_view.viewport().width(), (
        "预算夹住之后横向本应有空，这条一红说明夹算没生效")
    assert reader.pdf_view.horizontalScrollBar().maximum() == 0, (
        "夹了预算还滚得动横向，说明夹的是显示而不是渲染")


def test_手动缩放弹起适应宽度并不再跟窗走(ctx, window, qapp, tmp_path: Path) -> None:
    """点「放大」必须把这一态弹起、只铺一遍整页，且弹起之后拖窗**不许**改倍率。

    不弹起就没法表达"现在到底听谁的"（**Q1 甲-1** 的判据）；弹起之后若还在跟窗重铺，
    就变成"用户已经手动选了倍率，窗口一抖又给改回去"。
    中间那句计数钉的是「这颗按钮的状态由用户决定，不由程序决定」：接 `toggled` 之后
    `setChecked(False)` 自己就会再铺一遍（一次 8M 像素的白活）。
    """
    from tests.conftest import resize_stepped, settle
    reader = _open_sized_pdf(ctx, window, qapp, tmp_path, [(595, 842)] * 3)
    resize_stepped(window, qapp, 1024, 720)
    _await_refit(qapp)   # 出厂已按下（默认开）：先把改窗触发的重铺等完，再开始数数

    renders: list[int] = []
    real = reader._render_page
    reader._render_page = lambda: (renders.append(1), real())[0]   # type: ignore[method-assign]

    reader.zoom_in_btn.click()
    assert not reader.fit_btn.isChecked(), "手动一动这一态就该弹起"
    assert len(renders) == 1, f"点一次「放大」铺了 {len(renders)} 遍整页"
    zoom = reader._zoom_level

    resize_stepped(window, qapp, 1600, 720)
    settle(qapp)
    _await_refit(qapp)
    assert reader._zoom_level == pytest.approx(zoom), (
        f"弹起之后还在跟窗重算：{zoom} → {reader._zoom_level}")


def test_适应宽度按下与松开画得不一样() -> None:
    """这一态得**看得见**：`:checked` 必须有自己的底色，且与松开态（`QPushButton` 那条）不同。

    甲-1 的全部意义就是"看得出现在听谁的"，而这一条几何探针量不出来 —— 那颗按钮按下与松开
    一直是同一个尺寸。所以量渲染后的 QSS：删掉 `QPushButton#fitWidthBtn:checked` 整条，
    或把它的底色改成与松开态同一个值，这里都要红。
    对比度不在这里量（那是 `test_theme_contrast.py` 的活），这里只问"两态是不是同一个颜色"。
    """
    manager = ThemeManager()
    for theme in ("light", "dark"):
        manager.set_theme(theme)
        qss = re.sub(r"/\*.*?\*/", "", manager.generate_qss(), flags=re.S)
        checked = re.search(r"QPushButton#fitWidthBtn:checked\s*\{([^}]*)\}", qss)
        assert checked, (f"{theme} 主题里没有 QPushButton#fitWidthBtn:checked —— "
                         "按下与松开逐格相同，这一态在屏幕上没有出口")
        rest = re.search(r"\nQPushButton\s*\{([^}]*)\}", qss)
        assert rest, f"{theme} 主题里认不出 QPushButton 的松开态底色，比较无意义"

        checked_bg, rest_bg = _qss_bg(checked.group(1)), _qss_bg(rest.group(1))
        assert checked_bg and rest_bg, f"{theme} 两态之一没有实色底色（fg/bg 解析失败）"
        assert checked_bg != rest_bg, (
            f"{theme} 按下态底色与松开态同为 {checked_bg}，两态在屏幕上分不出来")


def test_拖窗只在停手之后铺一次(ctx, window, qapp, tmp_path: Path) -> None:
    """连着改三次窗宽：拖的过程中 0 次重铺，停手之后 1 次，且**不跳页**。

    计数器是包在 `_render_page` 外面的，因此"没铺"是真的没渲染（不是渲染了没看见）。
    拖窗那一路每变 1px 就重铺一整页会把最贵的一档拖成幻灯片；但停手那一次必须铺，
    而且铺完之后仍然铺满 —— 只数次数不看结果，一条"永远不重铺"的坏法也能过。
    """
    from tests.conftest import resize_stepped, settle
    reader = _open_sized_pdf(ctx, window, qapp, tmp_path, [(595, 842)] * 3)
    resize_stepped(window, qapp, 1024, 720)
    _await_refit(qapp)   # 出厂已按下（默认开）：先把改窗触发的重铺等完，下面从零数
    reader._next_page()

    renders: list[int] = []
    real = reader._render_page
    reader._render_page = lambda: (renders.append(1), real())[0]   # type: ignore[method-assign]

    for width in (1150, 1300, 1450):
        window.resize(width, 720)
        settle(qapp)
    assert len(renders) == 0, f"拖窗过程中重铺了 {len(renders)} 次，防抖没接上"

    _await_refit(qapp)
    assert len(renders) == 1, f"停手之后应只铺一次，实际 {len(renders)} 次"
    assert reader._current_page == 1, "重铺不许把阅读位置带走（0-based = 1 即第 2 页）"
    assert reader.page_label.text() == "2 / 3", f"页码显示跟着跳了：{reader.page_label.text()}"
    rendered, avail = _filled(reader)
    assert abs(rendered - avail) <= 2, f"停手那一次没铺满：渲染 {rendered} / 视口 {avail}"


def test_翻页按当页宽窄逐页重算(ctx, window, qapp, tmp_path: Path) -> None:
    """竖版翻到横版：倍率按**这一页**的宽重算，装得下就不留缝、也不出滚条。

    这一页是整组里唯一需要等防抖才收敛的：1024 档横版页第一次同步铺的时候竖滚条还挂着
    （按 799 算），铺完它消失了、可视宽变 807，于是停手那一次再铺成 807（实测
    0.9489 → 0.9584）。所以这里断言写在 `_await_refit` 之后，量的是收敛完的那一次。
    出厂已按下（默认开）：改窗排进防抖的那一次先等完，再翻页 —— 翻页那次同步铺。
    """
    from tests.conftest import resize_stepped
    reader = _open_sized_pdf(ctx, window, qapp, tmp_path, [(595, 842), (842, 595)])
    resize_stepped(window, qapp, 1024, 720)
    _await_refit(qapp)

    reader._next_page()
    _await_refit(qapp)

    rendered, avail = _filled(reader)
    assert abs(rendered - avail) <= 2, (
        f"横版页没按自己的宽重算：渲染 {rendered} / 视口 {avail}")
    pix = reader.pdf_label.pixmap()
    assert pix.height() <= reader.pdf_view.viewport().height(), (
        f"横版页整页应当装得下，实际高 {pix.height()} 超出视口高")
    assert reader.pdf_view.horizontalScrollBar().maximum() == 0


def test_缩放档上下限与倍率(ctx, window, qapp, tmp_path: Path) -> None:
    """`_zoom_in` 上限 4.0、`_zoom_out` 下限 0.3、每次 1.2×。

    上限在轮四十七从 3.0 抬到 4.0（**Q2 乙**）：2560 档要看清一处局部需要 3.92，3.0 恰好卡在
    那一步够不着的地方；抬到 4.0 单页 2382×3368 = 8.02M 像素，仍在「适应宽度」那一条的预算内。

    出厂已按下（默认开，2026-10-31 用户点名）：开档倍率由适应宽度现算，不再是写死的 1.0 ——
    先把这一态弹起，梯子从**现值**起量：`base` → zoom_in → 1.2× → zoom_out 回 `base` → …
    上下限两条不变。
    """
    pdf_path = tmp_path / "zoom.pdf"
    doc = pymupdf.open()
    for i in range(3):
        page = doc.new_page()
        page.insert_text((36, 40 + i * 30), f"第 {i+1} 页", fontsize=11, fontname="china-s")
    doc.save(pdf_path)
    doc.close()

    doc_id = _insert_doc(ctx, path=str(pdf_path).replace("\\", "/"))
    reader = _navigate_to_reader(window, qapp)
    reader.open_document(doc_id)

    reader.fit_btn.click()   # 出厂按下 ⇒ 这一下弹起，倍率就地变成手动轴的现值
    base = reader._zoom_level
    assert base > 0, "弹起之后手动轴必须有一个现值可接"

    reader._zoom_in()
    assert abs(reader._zoom_level - base * 1.2) < 0.01 * base, (
        f"第一次放大应是 {base}×1.2，实际 {reader._zoom_level}")

    reader._zoom_out()
    assert abs(reader._zoom_level - base) < 0.01 * base, (
        f"放大后缩小应回到 {base}，实际 {reader._zoom_level}")

    for _ in range(20):
        reader._zoom_in()
    assert reader._zoom_level <= _ZOOM_MAX, f"缩放上限 {_ZOOM_MAX} 被突破：{reader._zoom_level}"
    assert reader._zoom_level == _ZOOM_MAX, f"连续放大必须停在 {_ZOOM_MAX}，实际 {reader._zoom_level}"

    for _ in range(30):
        reader._zoom_out()
    assert reader._zoom_level >= 0.3, f"缩放下限 0.3 被突破：{reader._zoom_level}"
    assert reader._zoom_level == 0.3, f"连续缩小必须停在 0.3，实际 {reader._zoom_level}"


def test_损坏PDF不崩且回显原文(ctx, window, qapp, tmp_path: Path) -> None:
    """`pymupdf.open()` 抛异常时必须走 `QMessageBox.critical`，标题是「打开 PDF 失败」，
    正文是异常原文。

    用一份「合法文件头 + 垃圾字节」造出损坏件，`pymupdf.open()` 会抛 `RuntimeError`。
    阅读器必须弹框而不是崩溃，且框里的文字是 PyMuPDF 的原文（不是"未知错误"）。
    """
    bad_path = tmp_path / "corrupt.pdf"
    bad_path.write_bytes(b"%PDF-1.4\n" + b"\x00" * 100)

    doc_id = _insert_doc(ctx, path=str(bad_path).replace("\\", "/"))
    reader = _navigate_to_reader(window, qapp)

    with patch.object(QtWidgets.QMessageBox, "critical") as mock_msg:
        reader.open_document(doc_id)
        mock_msg.assert_called_once()
        args = mock_msg.call_args
        title = args[0][1] if len(args[0]) > 1 else args[1].get("title", "")
        body = args[0][2] if len(args[0]) > 2 else args[1].get("text", "")
        assert title == "打开 PDF 失败", f"弹框标题必须是「打开 PDF 失败」，实际「{title}」"
        assert len(body) > 0, "弹框正文不能是空的"
        assert "未知错误" not in body, "弹框正文必须是异常原文，不许遮罩成「未知错误」"


def test_阅读进度跨重启恢复(ctx, window, qapp, tmp_path: Path) -> None:
    """翻到第 N 页后 `last_read_page` 必须写进库；重新打开同一份文档，阅读器停在那一页。

    1-based 口径（与 `text_pages.page_no` 一致）。初始打开 → 翻到第 3 页 → 断言 DB 里
    `last_read_page=3` → 再次调用 `open_document` → 断言阅读器停在第 3 页（0-based = 2）。
    这证明恢复逻辑从 DB 读值而不是从内存缓存。
    """
    pdf_path = tmp_path / "progress.pdf"
    doc = pymupdf.open()
    for i in range(5):
        page = doc.new_page()
        page.insert_text((36, 40), f"第 {i+1} 页", fontsize=11, fontname="china-s")
    doc.save(pdf_path)
    doc.close()

    doc_id = _insert_doc(ctx, path=str(pdf_path).replace("\\", "/"), page_count=5)
    reader = _navigate_to_reader(window, qapp)
    reader.open_document(doc_id)
    assert reader._current_page == 0, "初始应停在第 1 页（0-based = 0）"

    reader._next_page()
    reader._next_page()
    assert reader._current_page == 2, "翻两页后应停在第 3 页（0-based = 2）"

    conn = ctx.engine.thread_connection()
    row = conn.execute("SELECT last_read_page, last_read_at FROM documents WHERE id=?",
                       (doc_id,)).fetchone()
    assert row["last_read_page"] == 3, f"阅读进度必须是 3（1-based），实际 {row['last_read_page']}"
    assert row["last_read_at"] is not None, "last_read_at 必须被写入"

    reader._current_page = 0
    reader.open_document(doc_id)
    assert reader._current_page == 2, (
        f"重新打开同一文档应从 DB 恢复到最后读的那页（0-based = 2），"
        f"实际 {reader._current_page}")
