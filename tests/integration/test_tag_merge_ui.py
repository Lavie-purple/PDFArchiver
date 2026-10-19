"""S8 中栏「并入…」—— `merge_tags` 在产品里的入口（轮十五 甲，2026-10-20）。

**这一条补的是什么账**：**ISSUES I78** 甲（2026-10-19）把「归入分类 / 加标签 / 移除标签 /
改父类 / 合并分类」五条写路径接上了界面，同一天记下的尾巴是「仍零调用方的是 `merge_tags`」
（写在 `gates/stage3.py` 与本页旧 docstring 里）。修前标签能建能改能删，**唯独不能并把两个**
—— 而库里真有「报销」与「报销单」这种近义标签各挂一批文档时，界面上唯一的出路是逐个文档
重打标签，那件事在几千份的库里等于没有出路。

补这颗按钮时先在仓储层挖出一处**真 bug**（不是"少个功能"）：修前 `merge_tags(a, a)` 先让
`UPDATE OR IGNORE` 把 `tag_id` 改成它自己（空转），紧接着 `DELETE FROM document_tags
WHERE tag_id=a` —— 那个标签的**全部文档关联连同 `tags` 行一起没了**。按下去是"删标签"，
而屏幕上没有一句话说明关联被抹掉了。`test_并进自己当场被拒而关联一条都没少` 钉的就是这一步，
它的坏法是把那三条前置检查撤掉（撤完真的少东西，不是恒真）。

断言对着四组事写：
(a) **数据**：并过去之后源名下的文档全部挂目标、源标签行与源关联行归零、两边都有的那份
    不出现第二行（`UPDATE OR IGNORE` + `DELETE` 那条顺序，同 `merge_categories`）；
(b) **拒**：并进自己 / 源不存在 / 目标不存在 三条都拒在仓储层且**一条关联都不动**，
    拒的原文上了屏幕（AGENTS.md「不许伪装成功」在写路径上的版本）；
(c) **入口**：没有点名就没有动作、取消候选不写库、只有一个标签时说明没有可并入的对象，
    而这句前置提示全站只写一处（**ISSUES I78** 同一条"不许逐个打补丁"）；
(d) **同源**：屏幕上"移动了几份"那个数字是仓储层数出来的返回值，不是界面自己 `len()` 出来的
    （**ISSUES I60** 那条纪律在合并动作上的版本）。

夹具与读数辅助全走 `dialog_doubles.py`（offscreen 下漏装 `QMessageBox` 替身的测试不会红，
只会永远不结束）；库是**真 sqlite3**（**D-012**），`document_tags` 的直接 SELECT 只出现在
本文件的读数函数里，产品代码一条 SQL 都不写 —— 那是架构守卫钉的方向。
文档全是现造的假名字，真实语料一条不进测试（**ISSUES I64**）。

16 条断言配了 **17** 个坏法，全部真注入过（2026-10-20 抓到 17/17，基线 16 条全绿）：
`tests/probes/p24_tag_merge_injection.py`。多出来的那一条在「删除作用在选中的那一个标签」上 ——
**只撤仓储层那句 `DELETE FROM document_tags` 实测不会红**：`document_tags.tag_id` 上写着
`ON DELETE CASCADE`（`0001_initial.py:101`），是表结构在兜这一半。所以那条坏法把两处一起撤，
钉的是"关联一定被带走"这个**行为**，而不是某一条语句由哪一层实现。
"""
from __future__ import annotations

from pathlib import Path

import pytest
from PySide6 import QtCore

from pdfarchiver.db.engine import DatabaseError
from pdfarchiver.db.models import Document
from pdfarchiver.fs.identity import identity_key
from tests.integration.dialog_doubles import (stub_item_chooser, stub_message_boxes,
                                              stub_text_prompt)
from tests.conftest import settle as _settle


# ---------------------------------------------------------------------------
# 夹具与读数辅助
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def dialogs(monkeypatch) -> list[tuple[str, str, str]]:
    """截住四句模态提示，返回 `(kind, title, text)` 清单 —— 这批断言的读数大半在文案里。"""
    return stub_message_boxes(monkeypatch)


@pytest.fixture
def pick(monkeypatch):
    """`QInputDialog.getItem`（挑"并进哪一个"那一格）换成"按下指定名字"，并记下实际候选。"""
    return stub_item_chooser(monkeypatch)


@pytest.fixture
def names(monkeypatch):
    """`QInputDialog.getText`（新建 / 改名 那两格）换成"依次吐出这几句"。"""
    return stub_text_prompt(monkeypatch)


def _categories(window, qapp):
    window._select_by_page_id("categories")
    _settle(qapp)
    page = window._pages["categories"]
    page.reload()
    _settle(qapp)
    return page


def _seed_docs(ctx, count: int) -> list[int]:
    """灌 count 份**只有名字**的文档（不碰磁盘），返回 id 列表。"""
    ids: list[int] = []
    for n in range(count):
        name = f"并入测试{n}号.pdf"
        path = f"D:\\用户资料\\{name}"
        ids.append(ctx.documents.upsert(Document(
            path=path, path_key=identity_key(path), name=name,
            size_bytes=2048 + n, mtime_ns=1_760_000_000_000_000_000,
            sha256=f"e{n:063x}", text_status="done", fts_status="done")).id)
    return ids


def _rows(ctx, tag_id: int) -> list[int]:
    """数`document_tags` 里挂在某个标签名下的 doc_id —— 只有直连真库数得准。"""
    conn = ctx.engine.thread_connection()
    return [r[0] for r in conn.execute(
        "SELECT doc_id FROM document_tags WHERE tag_id=? ORDER BY doc_id", (tag_id,)).fetchall()]


def _tag_ids(ctx) -> set[int]:
    return {t.id for t in ctx.catalog.list_tags()}


def _displayed(page) -> list[str]:
    return [page.tag_list.item(i).text() for i in range(page.tag_list.count())]


def _select_tag(page, name: str) -> None:
    row = next(i for i in range(page.tag_list.count()) if page.tag_list.item(i).text() == name)
    page.tag_list.setCurrentRow(row)


def _asked(dialogs, kind: str = "information") -> list[str]:
    return [text for k, _, text in dialogs if k == kind]


# ---------------------------------------------------------------------------
# (a) 数据：并过去的是关联，不是把源删掉了事
# ---------------------------------------------------------------------------

def test_源名下的关联改指目标而源标签整行消失(window, ctx, qapp, pick, dialogs) -> None:
    """三份文档：`甲` 挂 1、2 两份，`乙` 只挂 2 那份。把 `甲` 并进 `乙` ——
    并完之后 `乙` 名下正好是 {1,2}，`甲` 一行关联都不剩、`tags` 表也少一行。

    「两边都有的那份不出现第二行」是这条的第二半：`UPDATE OR IGNORE` 撞主键时那行**留在原处**，
    靠紧跟的 `DELETE` 清掉 —— 顺序反了就是把 2 号那份的关联删没了（`merge_categories` 同一形状）。
    """
    ids = _seed_docs(ctx, 3)
    src = ctx.catalog.add_tag("并入甲")
    dst = ctx.catalog.add_tag("并入乙")
    ctx.catalog.link_tags([ids[0], ids[1]], src.id)
    ctx.catalog.link_tags([ids[1]], dst.id)   # 第三份两个标签都不挂，不该被这次合并牵进来

    page = _categories(window, qapp)
    _select_tag(page, "并入甲")
    pick["name"] = "并入乙"
    page.merge_tag_btn.click()
    _settle(qapp)

    assert _rows(ctx, dst.id) == [ids[0], ids[1]]
    assert _rows(ctx, src.id) == []
    assert _tag_ids(ctx) == {dst.id}
    assert _displayed(page) == ["并入乙"]


def test_每一行挂的是它自己那个标签的id(window, ctx, qapp) -> None:
    """句柄是 id 不是行号（**ISSUES I78** 乙 在集合那一栏记下过同一条纪律）。

    修前三颗按钮各抄一遍 `list_tags()[currentRow()]` —— 那份"第几行 == 第几条"的临时前提
    只在列表没重排过时成立。这一条钉的是"挂在行上的那个 id 就是这一行显示的标签"，
    顺序按 `list_tags()` 现取（`name COLLATE NOCASE`，中文按字节序），不假设插入序。
    """
    for name in ("并入丙", "并入甲", "并入乙"):
        ctx.catalog.add_tag(name)
    page = _categories(window, qapp)
    listed = ctx.catalog.list_tags()

    assert _displayed(page) == [t.name for t in listed]
    assert [page.tag_list.item(i).data(QtCore.Qt.ItemDataRole.UserRole)
            for i in range(page.tag_list.count())] == [t.id for t in listed]


def test_改名作用在选中的那一个标签上(window, ctx, qapp, names, pick) -> None:
    """三个标签、点名中间那一个改名 —— 另两个的名字一个字都不动，而库里正好少一个旧名多一个新名。

    坏法是把当前行读错（写死第一个 / 反着数），那样改的会是**别的**标签。
    """
    ctx.catalog.add_tag("并入甲")
    middle = ctx.catalog.add_tag("并入乙")
    ctx.catalog.add_tag("并入丙")
    page = _categories(window, qapp)
    _select_tag(page, "并入乙")
    names["queue"] = ["并入乙改"]

    page.rename_tag_btn.click()
    _settle(qapp)

    by_id = {t.id: t.name for t in ctx.catalog.list_tags()}
    assert by_id[middle.id] == "并入乙改"
    assert {t.name for t in ctx.catalog.list_tags()} == {"并入甲", "并入丙", "并入乙改"}
    assert "并入乙改" in _displayed(page) and "并入乙" not in _displayed(page)


def test_删除作用在选中的那一个标签而它的关联一起走(window, ctx, qapp, pick) -> None:
    """三颗按钮里"没被并进去的那两颗"也要读对行：删错一个标签是不可逆的写。

    后半句（关联一起走）钉的是**行为**不是语句：只撤仓储层那句 `DELETE FROM document_tags`
    实测不会红 —— `document_tags.tag_id` 上有 `ON DELETE CASCADE`，表结构在兜；p24 注入 a5
    把两处一起撤才打得红这一条。
    """
    ids = _seed_docs(ctx, 2)
    gone = ctx.catalog.add_tag("并入甲")
    left = ctx.catalog.add_tag("并入乙")
    ctx.catalog.link_tags([ids[0]], gone.id)
    ctx.catalog.link_tags([ids[1]], left.id)
    page = _categories(window, qapp)
    _select_tag(page, "并入甲")

    page.delete_tag_btn.click()
    _settle(qapp)

    assert _tag_ids(ctx) == {left.id}
    assert _rows(ctx, gone.id) == [] and _rows(ctx, left.id) == [ids[1]]


# ---------------------------------------------------------------------------
# (b) 拒：三条前置检查都在仓储层，且拒了不写任何东西
# ---------------------------------------------------------------------------

def test_并进自己当场被拒而关联一条都没少(ctx) -> None:
    """**这一条钉的是修前那个真 bug**：`merge_tags(a, a)` 在旧实现里会把 `a` 的**全部关联**
    连同 `tags` 行一起删掉（`UPDATE OR IGNORE` 空转，紧跟的 `DELETE` 落到同一个 id 上）。

    现在拒在检查里，一条都不动。坏法（把三条前置检查撤掉）在这条上是真的少东西 ——
    撤完关联归零，红。
    """
    ids = _seed_docs(ctx, 3)
    tag = ctx.catalog.add_tag("并入甲")
    ctx.catalog.link_tags(ids, tag.id)

    with pytest.raises(DatabaseError, match="不能把"):
        ctx.catalog.merge_tags(tag.id, tag.id)

    assert _rows(ctx, tag.id) == sorted(ids)
    assert tag.id in _tag_ids(ctx)


def test_源或目标不存在都被拒而不是一句已并过去(ctx) -> None:
    """修前这两条**根本没有**：`DELETE` 打在不存在的 id 上就是静默无操作，
    而界面上那句"已并过去"照样说给用户听 —— 与 **ISSUES I36**「未跑却算 PASS」同一类谎。
    """
    ids = _seed_docs(ctx, 2)
    left = ctx.catalog.add_tag("并入乙")
    ctx.catalog.link_tags(ids, left.id)

    with pytest.raises(DatabaseError, match="源标签不存在"):
        ctx.catalog.merge_tags(9_999, left.id)
    with pytest.raises(DatabaseError, match="目标标签不存在"):
        ctx.catalog.merge_tags(left.id, 9_999)

    assert _rows(ctx, left.id) == sorted(ids) and left.id in _tag_ids(ctx)


def test_返回的份数就是源名下实际的文档数(ctx) -> None:
    """`merge_tags` 的返回值是**源名下的文档份数**（与 `merge_categories` 同一口径），
    屏幕上那句"移动 N 份"只有这一个出处。返回 `None` 的旧签名在这里会当场红。
    """
    ids = _seed_docs(ctx, 3)
    src = ctx.catalog.add_tag("并入甲")
    dst = ctx.catalog.add_tag("并入乙")
    ctx.catalog.link_tags([ids[0], ids[1], ids[2]], src.id)
    ctx.catalog.link_tags([ids[2]], dst.id)

    assert ctx.catalog.merge_tags(src.id, dst.id) == 3
    assert _rows(ctx, dst.id) == sorted(ids)


def test_仓储层拒了而屏幕上留的是原文(window, ctx, qapp, monkeypatch, dialogs) -> None:
    """**ISSUES I78** 甲那批的同一形状：拒必须看得见原文，不许界面咽下去只留一句"失败了"。

    这里绕过候选对话框直接递一个不存在的目标 id（界面上挑不出这一条，但真被别的入口递进来时
    屏幕上得有东西可抄）。
    """
    ids = _seed_docs(ctx, 1)
    src = ctx.catalog.add_tag("并入甲")
    ctx.catalog.add_tag("并入乙")
    ctx.catalog.link_tags(ids, src.id)
    page = _categories(window, qapp)
    _select_tag(page, "并入甲")
    monkeypatch.setattr(page, "_pick_tag",
                        lambda *a, **k: (max(_tag_ids(ctx) - {src.id}) + 500, "不存在的目标"))

    page.merge_tag_btn.click()
    _settle(qapp)

    assert _asked(dialogs, "critical") and "目标标签不存在" in _asked(dialogs, "critical")[0]
    assert _asked(dialogs) == []          # 拒了就不许再说一句"已并过去"
    assert _rows(ctx, src.id) == sorted(ids)


# ---------------------------------------------------------------------------
# (c) 入口：没有点名 / 取消 / 只有一个候选
# ---------------------------------------------------------------------------

def test_中栏那排是四颗按钮而并入是第三颗(window, ctx, qapp) -> None:
    """按钮在不在、叫什么、摆没摆在这一排 —— 是这一条唯一能守住"入口存在"的读数
    （写没写库由上面那几条守）。

    排在改名与删除之间：并入是"改这个标签的去处"，与删除同一族，所以放在按下去会少一个标签的
    那颗**之前**。`x()` 递增那一句钉的是"真的挂在这一排的布局里"—— 只 `QPushButton("并入…")`
    而忘了 `tag_btns.addWidget(...)`，文案与名字全对，而屏幕上没有这颗。
    """
    page = _categories(window, qapp)
    four = (page.add_tag_btn, page.rename_tag_btn, page.merge_tag_btn, page.delete_tag_btn)

    assert [b.text() for b in four] == ["新建", "改名", "并入…", "删除"]
    assert all(b.isEnabled() for b in four)
    xs = [b.geometry().x() for b in four]
    assert xs == sorted(xs) and len(set(xs)) == 4, f"四颗按钮没有并排在同一排：{xs}"


def test_没有选中标签时点并入只有一句提示(window, ctx, qapp, pick, dialogs) -> None:
    """前置检查读不到对象就是**什么都不写**：候选对话框一次都不该弹（`pick["items"]` 空）。"""
    ids = _seed_docs(ctx, 1)
    tag = ctx.catalog.add_tag("并入甲")
    other = ctx.catalog.add_tag("并入乙")
    ctx.catalog.link_tags(ids, tag.id)
    page = _categories(window, qapp)
    page.tag_list.clearSelection()
    page.tag_list.setCurrentItem(None)

    page.merge_tag_btn.click()
    _settle(qapp)

    assert pick["items"] == []
    assert _asked(dialogs) == ["请先选择一个标签再并入"]
    assert _tag_ids(ctx) == {tag.id, other.id}
    assert _rows(ctx, tag.id) == sorted(ids) and _rows(ctx, other.id) == []


def test_候选清单里没有自己(window, ctx, qapp, pick) -> None:
    """自我合并在仓储层拒（唯一口径），但**不摆上候选**才是给人用的拒 ——
    那句 `不能把「并入甲」并进它自己` 是给开发看的话术。
    """
    src = ctx.catalog.add_tag("并入甲")
    ctx.catalog.add_tag("并入乙")
    ctx.catalog.add_tag("并入丙")
    page = _categories(window, qapp)
    _select_tag(page, "并入甲")
    pick["name"] = "并入乙"

    page.merge_tag_btn.click()
    _settle(qapp)

    assert sorted(pick["items"]) == ["并入丙", "并入乙"]
    assert "并入甲" not in pick["items"]
    assert src.id not in _tag_ids(ctx)


def test_取消候选对话框一行都不写(window, ctx, qapp, pick, dialogs) -> None:
    """`ok=False` 就是人按了取消：既不写库，也不该收尾那句"已并过去"。"""
    ids = _seed_docs(ctx, 2)
    src = ctx.catalog.add_tag("并入甲")
    dst = ctx.catalog.add_tag("并入乙")
    ctx.catalog.link_tags(ids, src.id)
    page = _categories(window, qapp)
    _select_tag(page, "并入甲")
    pick["name"] = "不存在的候选名"

    page.merge_tag_btn.click()
    _settle(qapp)

    assert _rows(ctx, src.id) == sorted(ids) and src.id in _tag_ids(ctx)
    assert _rows(ctx, dst.id) == []
    assert _asked(dialogs) == []


def test_只有一个标签时说明没有可并入的对象(window, ctx, qapp, pick, dialogs) -> None:
    """候选为空时**先说一句再返回**，而不是弹一个空下拉框（空下拉 = 点了没反应，**ISSUES I63** 戊 同族）。"""
    ids = _seed_docs(ctx, 1)
    only = ctx.catalog.add_tag("并入甲")
    ctx.catalog.link_tags(ids, only.id)
    page = _categories(window, qapp)
    _select_tag(page, "并入甲")

    page.merge_tag_btn.click()
    _settle(qapp)

    assert _asked(dialogs) == ["没有可并入的标签"]
    assert pick["items"] == []
    assert _rows(ctx, only.id) == sorted(ids) and only.id in _tag_ids(ctx)


# ---------------------------------------------------------------------------
# (d) 同源：屏幕上那个数字来自仓储层
# ---------------------------------------------------------------------------

def test_收尾那句里的份数是仓储层数的而不是界面数的(window, ctx, qapp, pick, dialogs) -> None:
    """`已并入「并入乙」· 移动 2 份文档的标签关联` —— 那个 2 是 `merge_tags` 的返回值。

    库里刻意摆成"三个标签、两份文档"：界面要是自己 `len(list_tags())` 会数出 3（重查之前），
    `len(tag_list)` 也一样是 3 —— 只有源名下实际关联是 2。坏法见 p24 注入甲-b。
    """
    ids = _seed_docs(ctx, 2)
    ctx.catalog.add_tag("并入丙")
    src = ctx.catalog.add_tag("并入甲")
    dst = ctx.catalog.add_tag("并入乙")
    ctx.catalog.link_tags(ids, src.id)
    page = _categories(window, qapp)
    _select_tag(page, "并入甲")
    pick["name"] = "并入乙"

    page.merge_tag_btn.click()
    _settle(qapp)

    assert _asked(dialogs) == ["已并入「并入乙」· 移动 2 份文档的标签关联"]


def test_前置提示在页面代码里只写一处() -> None:
    """「请先选择一个标签」这句在 `categories_page.py` 的**代码行**里只出现一次 ——
    修前它在改名与删除里各抄了一遍，补第三颗按钮时很容易抄成三遍（AGENTS.md
    「禁止同类问题逐个打补丁」：一次声明规则，不逐个补）。

    只数带 `QMessageBox` 的那几行：docstring 里引用这句作说明是允许的（注释不是第二个口径）。
    """
    text = (Path(__file__).resolve().parents[2] / "src" / "pdfarchiver"
            / "ui" / "pages" / "categories_page.py").read_text(encoding="utf-8")
    hits = [ln.strip() for ln in text.splitlines()
            if "请先选择一个标签" in ln and "QMessageBox" in ln]
    assert len(hits) == 1, f"这句前置提示有 {len(hits)} 处代码在写：{hits}"


def test_merge_tags在产品侧有调用点了() -> None:
    """**ISSUES I78** 那条账的最后一格：修前 `merge_tags` 的调用方全在 `tests/`，`src/` 里零。

    与 `test_六条写方法在产品侧各有调用点了` 同一形状（那条的名单里没有 `merge_tags`，
    因为**当时确实没有** —— 这一条把补上的那一颗钉死，并写死调用方文件：哪天按钮被拆到
    只剩 `gates/` 在用，本条红）。
    """
    src = Path(__file__).resolve().parents[2] / "src"
    files = {p.relative_to(src).as_posix(): p.read_text(encoding="utf-8") for p in src.rglob("*.py")}
    found = sorted(pos for pos, text in files.items()
                   if ".merge_tags" in text and not pos.endswith("db/repositories/catalog.py"))
    assert found == ["pdfarchiver/ui/pages/categories_page.py"], \
        f"`merge_tags` 的调用方现在是：{found}"


if __name__ == "__main__":
    import sys

    sys.exit(pytest.main([__file__, "-q", "-p", "no:randomly"]))
