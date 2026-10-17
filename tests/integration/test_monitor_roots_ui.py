"""S7 监测根登记的界面接线（销账 **ISSUES I66**）。

这条链原先的形状是：两颗按钮都 `clicked.connect` 且未禁用，按下去只弹一句
「当前监测目录只能通过配置文件修改」—— 而那句本身是假的（监测根在库表 `monitored_roots` 里，
`settings.json` 根本没有这个键）。界面写的"能做什么"和实际做什么是两回事时，用户按按钮的那一秒
就站在一条死路上，所以这里的断言全部钉**点下去之后库里、监听名单里和列表里多出来的东西**，
不钉文案。

`conftest.py` 的三条规矩照常适用：offscreen、独立数据根、真 sqlite3（D-012）。
"""
from __future__ import annotations

from pathlib import Path

from PySide6 import QtCore, QtWidgets

from pdfarchiver.db.models import Document
from pdfarchiver.services.bootstrap import AppContext

UI_DIR = Path(__file__).resolve().parents[2] / "src" / "pdfarchiver" / "ui"


def _page(window):
    """切到 S7 并返回那个页面（页面是惰性建的，不切过去就没有这个对象）。"""
    window._select_by_page_id("monitor")
    return window._pages["monitor"]


def _seed_doc(ctx: AppContext, path: str, name: str) -> None:
    ctx.documents.upsert(Document(
        path=path, path_key=path.casefold(), name=name, size_bytes=2048,
        mtime_ns=1_760_000_000_000_000_000, sha256=f"{7:064x}",
        text_status="done", fts_status="done"))


def test_点添加目录之后库里多一行且是启用态(window, ctx, qapp, tmp_path, monkeypatch) -> None:
    """销账判定 ①：行数 **+1** 且 `enabled=1` —— 光把按钮接上不弹框不算接上。"""
    picked = tmp_path / "选中的目录"
    picked.mkdir()
    monkeypatch.setattr(QtWidgets.QFileDialog, "getExistingDirectory",
                        staticmethod(lambda *a, **k: str(picked)))

    page = _page(window)
    before = ctx.roots.count()

    page.add_root_btn.click()
    qapp.processEvents()

    assert ctx.roots.count() == before + 1, "点了「添加目录」，监测根一行都没多"
    added = ctx.roots.list()[-1]
    assert added.enabled == 1, f"新登记的根必须是启用态，实际 {added.enabled}"
    assert added.root_path.endswith("选中的目录"), added.root_path
    assert page.roots_list.count() == before + 1, "库里有了、列表没刷新 —— 用户看不到自己登记成功"


def test_取消选择不动任何东西(window, ctx, qapp, monkeypatch) -> None:
    """选择器被取消（返回空串）是正常路径，不许写成一行空根。"""
    monkeypatch.setattr(QtWidgets.QFileDialog, "getExistingDirectory",
                        staticmethod(lambda *a, **k: ""))
    page = _page(window)
    before = ctx.roots.count()

    page.add_root_btn.click()
    qapp.processEvents()

    assert ctx.roots.count() == before
    assert page.roots_list.count() == before


def test_重复登记同一个目录是重新启用而不是多一行(window, ctx, qapp, tmp_path, monkeypatch) -> None:
    """`RootRepository.add` 的 `ON CONFLICT ... DO UPDATE` 口径：幂等 + 重开 `enabled=1`。

    这一条同时钉住"界面不许把重复登记变成第二行"和"被停用的根重新添加会回来"。
    """
    picked = tmp_path / "同一个目录"
    picked.mkdir()
    monkeypatch.setattr(QtWidgets.QFileDialog, "getExistingDirectory",
                        staticmethod(lambda *a, **k: str(picked)))
    page = _page(window)

    page.add_root_btn.click()
    qapp.processEvents()
    assert ctx.roots.count() == 1, page.roots_list.count()
    key = ctx.roots.list()[-1].root_key

    ctx.roots.set_enabled(key, False)          # 周期校验/命令行把这条根停掉
    page.reload_settings()
    assert " [已禁用]" in page.roots_list.item(0).text(), page.roots_list.item(0).text()

    page.add_root_btn.click()                   # 再点一次同一个目录
    qapp.processEvents()

    assert ctx.roots.count() == 1, "重复登记多出一行，同一个根会被扫两遍"
    assert ctx.roots.by_key(key).enabled == 1, "重新添加必须把它带回启用态"
    assert " [已禁用]" not in page.roots_list.item(0).text()


def test_移除只撤监测不删文档记录也不碰磁盘(window, ctx, qapp, tmp_path, monkeypatch) -> None:
    """销账判定 ②，也是 `RootRepository.remove` 模块文档那条承诺的界面版：
    **移除监测根只删配置** —— 用户把一根从列表里拿掉，不等于他要丢掉这上面的记录和分类标注。
    """
    watched = tmp_path / "要移除的根"
    watched.mkdir()
    _seed_doc(ctx, str(tmp_path / "留在库里的.pdf"), "留在库里的.pdf")
    ctx.register_root(str(watched))
    page = _page(window)
    docs_before = len(ctx.documents.list(limit=1000))
    assert docs_before == 1, "测试前提坏了：库里一份文档都没有，「移除不删记录」就没被验到"

    monkeypatch.setattr(QtWidgets.QMessageBox, "question",
                        staticmethod(lambda *a, **k: QtWidgets.QMessageBox.StandardButton.Yes))
    page.roots_list.setCurrentRow(0)
    removed_key = page.roots_list.currentItem().data(QtCore.Qt.ItemDataRole.UserRole)
    page.remove_root_btn.click()
    qapp.processEvents()

    assert ctx.roots.by_key(removed_key) is None, "确认移除之后那条根还在库里"
    assert len(ctx.documents.list(limit=1000)) == docs_before, "移除监测根删掉了文档主记录"
    assert watched.exists(), "移除监测根把用户磁盘上的目录删了"
    assert page.roots_list.count() == 0, "库里撤了、列表还挂着那一条"


def test_确认框答否就不撤(window, ctx, qapp, tmp_path, monkeypatch) -> None:
    """这是一次会改库的操作，默认答案必须是"要用户明确说好"。"""
    watched = tmp_path / "留着"
    watched.mkdir()
    ctx.register_root(str(watched))
    page = _page(window)
    before = ctx.roots.count()

    monkeypatch.setattr(QtWidgets.QMessageBox, "question",
                        staticmethod(lambda *a, **k: QtWidgets.QMessageBox.StandardButton.No))
    page.roots_list.setCurrentRow(0)
    page.remove_root_btn.click()
    qapp.processEvents()

    assert ctx.roots.count() == before


def test_没选中任何一行时移除不生效(window, ctx, qapp, tmp_path, monkeypatch) -> None:
    """"移除选中"而什么都没选中：只能提示，不许拿列表第一行开刀。"""
    for name in ("甲目录", "乙目录"):
        (tmp_path / name).mkdir()
        ctx.register_root(str(tmp_path / name))
    page = _page(window)
    before = ctx.roots.count()

    asked: list[str] = []
    monkeypatch.setattr(QtWidgets.QMessageBox, "information",
                        staticmethod(lambda parent, title, text, *a, **k: asked.append(text)))
    monkeypatch.setattr(QtWidgets.QMessageBox, "question",
                        staticmethod(lambda *a, **k: (_ for _ in ()).throw(
                            AssertionError("没选中就不该弹确认框"))))
    page.remove_root_btn.click()
    qapp.processEvents()

    assert ctx.roots.count() == before, "没选中也删掉了一条监测根"
    assert asked == ["先在列表里选中一个目录。"], asked


def test_界面登记会挂上监听移除也会松开(window, ctx, qapp, tmp_path, monkeypatch) -> None:
    """同族坏法的正面版（**ISSUES I5** 那一族："看着进了库、其实没接"）。

    登记只做 `roots.add` 也能让上面几条全绿，而新根**只有周期校验在管、实时事件一条收不到**，
    界面上完全看不出来。所以这条真起后台，量 `watched_roots`。
    """
    picked = tmp_path / "在听的目录"
    picked.mkdir()
    monkeypatch.setattr(QtWidgets.QFileDialog, "getExistingDirectory",
                        staticmethod(lambda *a, **k: str(picked)))
    ctx.start_background()
    page = _page(window)
    before = ctx.background_state().watched_roots

    page.add_root_btn.click()
    qapp.processEvents()
    assert ctx.background_state().watched_roots == before + 1, (
        "登记进了库，监听名单里却没有它 —— 这个根的新文件只能等下一轮周期校验")

    key = ctx.roots.list()[-1].root_key
    monkeypatch.setattr(QtWidgets.QMessageBox, "question",
                        staticmethod(lambda *a, **k: QtWidgets.QMessageBox.StandardButton.Yes))
    page.roots_list.setCurrentRow(0)
    page.remove_root_btn.click()
    qapp.processEvents()

    assert ctx.roots.by_key(key) is None
    assert ctx.background_state().watched_roots == before, (
        "撤了登记还继续听，事件会灌进一个没人认领的根")


def test_界面里不许再出现只能通过配置文件修改这句话() -> None:
    """那句假文案的钉子（反面守卫）：监测根从来不在 `settings.json` 里，
    而界面任何一处再写这句话都会把人支去翻一个不存在的键。
    """
    offenders = [str(p.relative_to(UI_DIR)) for p in UI_DIR.rglob("*.py")
                 if "只能通过配置文件" in p.read_text(encoding="utf-8")]
    assert offenders == [], f"界面仍在把用户支去翻一个不存在的键：{offenders}"


# —— 用户文档的能力表 ⇄ 代码里的未接线清单 ————————————————————————————
# 这两份说的是同一件事（"界面上到底做得到做不到"），漂了的代价是用户按文档办事撞死路：
# **ISSUES I57** 抓到的是四份文档整整一轮停在"界面只有一屏"，本轮销 I66 时又抓到第二例 ——
# `README.md` 把离线 OCR 写成「✅ 能用」，而 `request_ocr()` 在产品侧**零调用点**（**ISSUES I67**）。
# 所以这条守卫盯**形状**不盯那两句错字：未接线清单点名的动作，能力表那一行的状态列不许打 ✅。
UNWIRED_TOPIC_WORDS = {
    "S3 执行归档": ("归档", "移动", "改名"),
    "S3 命名模板": ("命名模板", "改名"),
    "S4 整批撤销": ("撤销",),
    "OCR": ("OCR", "识别"),
}
CAPABILITY_TABLES = ("README.md", "docs/USAGE.md")


def test_用户文档不许把未接线的动作写成界面能做的事() -> None:
    from pdfarchiver.ui.pages.status_page import UNWIRED_ACTIONS

    repo = Path(__file__).resolve().parents[2]
    # 未接线清单加了新条目、映射表却没跟着加 ⇒ 守卫会安静地漏掉它，所以先钉映射的完备性。
    unmapped = sorted({e.split("：")[0] for e in UNWIRED_ACTIONS} - UNWIRED_TOPIC_WORDS.keys())
    assert unmapped == [], (
        f"UNWIRED_ACTIONS 新增了 {unmapped}，能力表守卫不认识它 = 从此不盯这类假 ✅；"
        "给它补一组话题词再来")

    offenders: list[str] = []
    for rel in CAPABILITY_TABLES:
        for line in (repo / rel).read_text(encoding="utf-8").splitlines():
            if not line.startswith("|"):
                continue
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if len(cells) < 2:
                continue
            for entry in UNWIRED_ACTIONS:
                head = entry.split("：")[0]
                if not any(w in cells[0] for w in UNWIRED_TOPIC_WORDS[head]):
                    continue
                if "✅" in cells[1]:
                    offenders.append(f"{rel}｜{cells[0]} → {cells[1]}（未接线：{head}）")
                    break
    assert offenders == [], (
        "能力表在未接线的动作上打了 ✅：\n  " + "\n  ".join(offenders) +
        "\n状态页那张贴纸（`status_page.UNWIRED_ACTIONS`）才是"
        "「屏在、动作没接到后端」的唯一口径")


def test_文档不许宣称OCR会自动排队() -> None:
    """**D-028 / ISSUES I1** 的红线：OCR **绝不自动触发**，只处理显式点名的页。
    "界面上设置好参数就会自动排队"这句话把这整条产品形态说反了（本轮从 `USAGE.md` §一 删掉的就是它）。

    判据是"这个短语是被承诺还是被否认"，而且**否定必须贴在那四个字前面**：坏法注入 ⑭
    （把"不会自动排队"改成"会自动排队"）实测被行级否定词判据放过去了 —— 同一行前半句还写着
    「界面上**没有**触发入口」，于是整行被当成老实话，守卫假绿（2026-10-17 现测）。
    """
    negated_before = ("不会", "不曾", "无法", "未能", "绝不", "没有", "并非", "也不")
    repo = Path(__file__).resolve().parents[2]
    offenders: list[str] = []
    for rel in (*CAPABILITY_TABLES, "docs/INSTALL.md", "docs/TROUBLESHOOTING.md",
                "docs/BACKUP-RESTORE.md"):
        for number, line in enumerate((repo / rel).read_text(encoding="utf-8").splitlines(), 1):
            for at in [i for i in range(len(line)) if line.startswith("自动排队", i)]:
                if line[max(0, at - 2):at] in negated_before or line[at - 1:at] == "不":
                    continue
                offenders.append(f"{rel}:{number}｜{line.strip()}")
                break
    assert offenders == [], f"文档在宣称有个不会自动跑的东西会自己跑：{offenders}"
