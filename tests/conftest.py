"""测试公用夹具。

放在这里而不是各测试文件里，是因为三条规矩必须全站统一：
1. Qt 一律 offscreen —— 不许在用户桌面上弹出窗口（阶段 0 的 P3 探针同样这么做）。
2. 每个测试一个独立数据目录 —— 数据库、日志、备份都不许跨测试串味。
3. **绝不用 mock 数据库**（D-012）：所有库相关测试都跑真 sqlite3 文件，
   否则 WAL、唯一索引、触发器这些真实行为一个都验不到。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from pdfarchiver.services.bootstrap import AppContext, bootstrap  # noqa: E402


@pytest.fixture
def data_root(tmp_path: Path) -> Path:
    """一个干净的数据根目录（还不存在，由 bootstrap 自己建）。"""
    return tmp_path / "appdata"


def settle(qapp, rounds: int = 6) -> None:
    """让 Qt 真的走完一轮重排。

    一次 `processEvents()` 之后 `sectionSize()` 会留着**改尺寸之前**的读数：注入坏法时
    窗口已经从 1000px 压到 356px，列宽却仍报 375px，守卫就这么假绿的（实测）。

    放在 conftest 而不是某个测试文件里：界面几何的断言分布在四个模块
    （`test_app_shell.py` / `test_status_readout.py` / `test_patrol_tick.py` /
    `test_ui_layout.py`，加上 `test_ui_tier.py`），"要跑几轮才算稳"这条抄两份就会漂。
    """
    for _ in range(rounds):
        qapp.processEvents()


def resize_stepped(window, qapp, width: int, height: int) -> None:
    """一级一级把窗口拉到目标宽（±50px），不要一次跳过去。

    实测从 1000 直接 resize 到 356 时 `QHeaderView` **不重排 Stretch 列**，`sectionSize()`
    留着改尺寸之前的 375px —— 守卫就这么假绿的（注入坏法时被抓到一次，见
    `test_ui_layout.py` 里那条教训）。用户是拖着窗口变的，步进才等效。
    和 `settle` 一样只许有一份：几何断言分布在五个模块里，抄两份就会漂。
    """
    step = 50 if width > window.width() else -50
    while (width - window.width()) * step > 0:
        nxt = min(window.width() + step, width) if step > 0 \
            else max(window.width() + step, width)
        window.resize(nxt, height)
        settle(qapp, rounds=4)


def page_at(window, qapp, page_id: str, width: int, height: int):
    """切到某一屏、重查一遍、压到指定窗口宽，返回页面对象。

    搬进 conftest（轮四十五 拆 `test_ui_tier.py` 时）：`test_ui_tier.py` 与
    `test_ui_hits.py` 两组都要它。**必须真的切过去**再 resize：`QStackedWidget` 里隐藏的页
    不重排，没看过的页面量出来是一串 0（离屏 Qt 的既有陷阱）。
    还要显式 `reload()`：已经在当前页时 `setCurrentRow` 不发信号，外壳的刷新链一次都不走，
    测试中途灌进库的行就读不到（实测文档表停在 0 行）。
    """
    window._select_by_page_id(page_id)
    settle(qapp)
    page = window._pages[page_id]
    page.reload()
    window.resize(width, height)
    settle(qapp)
    assert page.isVisible(), f"用例前提：{page_id} 这一屏得是当前可见页，否则量到的都是 0"
    return page


@pytest.fixture
def window(qapp, ctx):  # qapp 必须先于 ctx 之外存在：没有 QApplication 就构造 QWidget 是直接 abort 进程
    """起真外壳、关窗、并把上下文收干净。

    同样搬进 conftest（**ISSUES I58** 丙，2026-10-17）：`test_app_shell.py` 拆成四份之后
    四组都要这一份夹具，留在其中任何一个文件里就等于让另外三个去 import 别的服务模块。
    `test_placeholder_palette.py` 自己那一份**不是**同一个夹具（它要逐屏切一遍才能遍历到
    惰性建的页面），所以它保留本地定义、按 pytest 的规则覆盖这一个。
    """
    from pdfarchiver.ui.main_window import MainWindow

    w = MainWindow(ctx, cold_start_seconds=0.42)
    w.show()
    yield w
    w.close()
    ctx.shutdown()


@pytest.fixture
def ctx(data_root: Path):
    context = bootstrap(data_root)
    try:
        yield context
    finally:
        context.shutdown()


@pytest.fixture
def reopen(ctx: AppContext):
    """同一个数据目录再启动一次，返回新上下文。用于验"重启后东西还在"。"""
    def _reopen() -> AppContext:
        return bootstrap(ctx.paths.root)
    return _reopen


@pytest.fixture
def bare_ctx(ctx: AppContext) -> AppContext:
    """仓储层测试用：把默认分类模板和内部状态清空，断言才敢写绝对条数。

    清空只在测试的临时目录里发生，产品代码的"首启种一次"行为由
    `test_默认模板种过就不再长回来` 单独验。
    """
    conn = ctx.engine.thread_connection()
    conn.execute("DELETE FROM categories")
    conn.execute("DELETE FROM app_settings")
    conn.commit()
    return ctx


# —— 阶段 2：真实 PDF 样本 ————————————————————————————————
# 验收要求"创建真实的 PDF 样本"，所以这里用 PyMuPDF 生成合法文件，不塞假字节。
# 纯扫描件用「整页贴图、零文本层」造出来（p2 实测 37.5% 的语料是这种），
# 损坏件用「合法文件头 + 无交叉引用」造出来 —— 这两种在索引层的处置完全不同，
# 用同一种"坏文件"去测，等于只测了一半。

LINES_PER_PAGE = 12   # 12 行 × 每行 ≥4 字 = 一页去空格后必然 ≥ MIN_CHARS_PER_BEARING_PAGE(40)


def _fill_text_page(page, lines: list[str]) -> None:
    """逐行画字。`fontname="china-s"` 是 PyMuPDF 内置的简体中文字体：用 `helv` 中文会画成
    一串 `··`，提取出来的正文就不是那几个字，中文检索的断言等于什么都没验（实测）。"""
    y = 40
    for line in lines:
        page.insert_text((36, y), line, fontsize=11, fontname="china-s")
        y += 16


def _make_pdf(path, *, pages: int = 1, lines: list[str] | None = None,
              page_lines: list[list[str]] | None = None,
              meta: dict[str, str] | None = None, encrypted: bool = False) -> str:
    """生成一份有原生文本层的真 PDF，返回落盘路径。

    每页固定铺满 12 行：一页的去空格字符数因此必然 ≥40，`classify.judge` 才判得出 `native`。

    - `page_lines`：**每页写不同的内容**（页数 = 列表长度）。页码归属的断言非它不可 ——
      `lines` 是给每一页铺同一批句子，用它验"命中在第几页"永远只会验到第 1 页。
      每页可以写一整行字符串（`["这一页的全部正文"]`），也可以写多行
      （`[["第一行", "第二行"]]`）。这里接受裸字符串是因为不接受的失败方式太安静：
      `"句子"[i]` 取到的是**单个字符**，样本会"生成成功"而正文只剩 12 个字，
      于是所有关于页码和片段的断言都在验一份根本没有正文的文件（实测踩过）。
    - `meta`：写进 PDF 文档信息字典。PyMuPDF 现生成的文件**连 producer 都是空的**（实测），
      所以元数据通道必须自己种值，否则断言是在验"读不到"。
    """
    import pymupdf

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)   # 样本可以写到还没建的子目录里，模拟嵌套目录
    body = lines or [" "]
    pages = len(page_lines) if page_lines else pages
    doc = pymupdf.open()
    for index in range(pages):
        page = doc.new_page(width=595, height=842)
        source = page_lines[index] if page_lines else body
        if isinstance(source, str):
            source = [source]
        _fill_text_page(page, [source[i % len(source)] for i in range(LINES_PER_PAGE)])
    if meta:
        doc.set_metadata(meta)
    if encrypted:
        doc.save(str(path), encryption=pymupdf.PDF_ENCRYPT_AES_256,
                 owner_pw="o", user_pw="secret")
    else:
        doc.save(str(path))
    doc.close()
    return str(path)


@pytest.fixture
def make_pdf(tmp_path: Path):
    """真实 PDF 工厂：`make_pdf(name, pages=…, lines=…, page_lines=…, meta=…)` → 路径字符串。"""
    def _factory(name: str, *, pages: int = 1, lines: list[str] | None = None,
                 page_lines: list[list[str]] | None = None,
                 meta: dict[str, str] | None = None) -> str:
        return _make_pdf(tmp_path / name, pages=pages, lines=lines,
                         page_lines=page_lines, meta=meta)
    return _factory


def _make_scanned_pdf(path, *, pages: int = 2) -> str:
    """纯扫描件：整页贴一张渲染出来的图，**没有任何文本层**。
    p2 实测语料里 37.5% 是这种，端到端验收必须有它，所以写成模块级函数（`_make_pdf` 同理），
    让 `tests/e2e/` 那种"自己拼一棵样本树"的调用方也能用，而不是只有一条 fixture 路。

    先用一页画矩形、渲染成 PNG 再贴进各页，最后删掉那张用来渲染的草稿页 ——
    留着它，页数就比测试以为的多一页，页数断言会莫名其妙地差一。"""
    import pymupdf

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = pymupdf.open()
    draft = doc.new_page(width=400, height=300)
    shape = draft.new_shape()
    shape.draw_rect(pymupdf.Rect(20, 20, 380, 280))
    shape.finish(color=(0.1, 0.1, 0.1), fill=(0.85, 0.85, 0.85))
    shape.commit()
    stream = draft.get_pixmap().tobytes("png")
    for _ in range(pages):
        page = doc.new_page(width=400, height=300)
        page.insert_image(page.rect, stream=stream)
    doc.delete_page(0)
    doc.save(str(path))
    doc.close()
    return str(path)


@pytest.fixture
def make_scanned_pdf(tmp_path: Path):
    def _factory(name: str, *, pages: int = 2) -> str:
        return _make_scanned_pdf(tmp_path / name, pages=pages)
    return _factory


@pytest.fixture
def make_broken_pdf(tmp_path: Path):
    """有 `%PDF` 头但没有交叉引用表的文件 —— PyMuPDF 打得开壳、读不出一页。"""
    def _factory(name: str) -> str:
        path = tmp_path / name
        path.write_bytes(b"%PDF-1.7\n" + b"\x00" * 4096)
        return str(path)
    return _factory


@pytest.fixture
def make_encrypted_pdf(tmp_path: Path):
    """有原生文本但加了密且要密码。阶段 2 不弹密码框，必须老实标 failed。"""
    def _factory(name: str, *, text: str = "机密合同正文字符内容") -> str:
        return _make_pdf(tmp_path / name, pages=1, lines=[text], encrypted=True)
    return _factory


@pytest.fixture
def root(ctx: AppContext, tmp_path: Path):
    """把一个真实存在的目录登记成监测根，返回 `MonitoredRoot`。

    `root_key` 用 `identity_key()` 而不是路径原文：缺失判定靠 `path_key LIKE root_key%`
    的前缀匹配，两个口径必须同一个函数算出来。
    """
    from pdfarchiver.fs.identity import identity_key

    def _factory(name: str = "监测目录", **kw):
        directory = tmp_path / name
        directory.mkdir(parents=True, exist_ok=True)
        path = str(directory).replace("\\", "/")
        return ctx.roots.add(path, identity_key(directory), label=name, **kw)

    return _factory
