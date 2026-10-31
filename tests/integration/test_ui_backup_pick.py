"""S6 恢复页「在表里点一行来选包」这一层（轮五十 甲案）。

页面的形状由 `docs/wireframes/2026-10-31-round49-s6-restore-entry.html` §2 甲 定（Q1–Q4 全甲）。
这里管**屏幕上的数答不答得出人按之前该知道的事**，不重复服务层已经钉住的那几条：

- 类型列：包与裸库能恢复回来的东西不一样（裸库只有 `catalog.db`，向量文件回不来）。
- 体积列：给人看的是 `format_bytes` 口径，字节原值挂 tooltip；数字必须与恢复时准备的空间同源。
- 门禁：选中一行 **且** 填了目标根，按钮才亮（只满足一半时按下去只会静默什么都不做）。
- 列表口径 = 本程序认得的产物：迁移前的手工快照没有清单、答不出「里面有什么」，不进表（Q4 甲）。
- 两张表同源（一次 `list_backups()` 读、两处填），刷新按**路径**记选中而不是按行号。
- 外部位置选来的包不在表里，刷新不许把它清掉。
- 落点那一行由 `AppPaths` 唯一算，与恢复时摆放的是同一份映射（**ISSUES I123** ②）。
"""
from __future__ import annotations

import shutil
import time
from pathlib import Path

from PySide6.QtWidgets import QFileDialog, QMessageBox, QTabWidget

from pdfarchiver.services import backup_service
from pdfarchiver.ui.format import format_bytes

describe = backup_service.BackupService.describe_backup


def _restore_page(window, qapp, monkeypatch):  # noqa: ANN001, ANN202
    """切到 S6 的「恢复」标签页。

    QTabWidget 不给隐藏标签页排版（offscreen 实测：视口停在 638 不动），所以先切过去。
    两条模态框路径都在测试里拦下来，否则卡死。
    """
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a, **k: None))
    monkeypatch.setattr(QMessageBox, "critical", staticmethod(lambda *a, **k: None))
    window._select_by_page_id("backup")
    page = window._pages["backup"]
    tabs = page.findChildren(QTabWidget)[0]
    tabs.setCurrentIndex(1)
    qapp.processEvents()
    return page, tabs


def _names(table) -> list[str]:  # noqa: ANN001
    return [table.item(i, 0).text() for i in range(table.rowCount())]


def _row_of(table, name: str) -> int:  # noqa: ANN001
    rows = [i for i, text in enumerate(_names(table)) if text == name]
    assert len(rows) == 1, f"表里没有（或有不止一行）{name}：{_names(table)}"
    return rows[0]


def _write_bare(ctx, name: str = "catalog-20261016-120000-v8.db") -> Path:  # noqa: ANN001
    """旧格式裸库（2026-10-31 之前 S6 的产物，本机备份目录里现在还躺着几只）。"""
    bare = Path(ctx.paths.backups_dir) / name
    bare.parent.mkdir(parents=True, exist_ok=True)
    bare.write_bytes(b"SQLite format 3\x00" + b"\x00" * 1024)
    return bare


def test_类型列分得出包与裸库(window, ctx, qapp, monkeypatch) -> None:  # noqa: ANN001
    """两者能恢复回来的东西不一样，这一格是唯一在按之前说得出来的地方。"""
    page, _tabs = _restore_page(window, qapp, monkeypatch)
    pkg = ctx.backup.create_backup()
    bare = _write_bare(ctx)

    page._reload_backups()

    assert page.restore_table.item(_row_of(page.restore_table, pkg.name), 1).text() == "包"
    assert page.restore_table.item(_row_of(page.restore_table, bare.name), 1).text() == "裸库", \
        "裸库也印成「包」⇒ 人以为向量文件跟着回来了"


def test_体积列是成员字节之和且原值可回读(window, ctx, qapp, monkeypatch) -> None:  # noqa: ANN001
    """给人看的是 `format_bytes`，字节原值挂 tooltip —— 与判重页容量列同一口径。"""
    page, _tabs = _restore_page(window, qapp, monkeypatch)
    pkg = ctx.backup.create_backup()
    bare = _write_bare(ctx)

    page._reload_backups()

    info = describe(pkg)
    pkg_row = _row_of(page.restore_table, pkg.name)
    assert page.restore_table.item(pkg_row, 4).text() == format_bytes(info["total_bytes"]), \
        f"体积列不是成员字节之和：{page.restore_table.item(pkg_row, 4).text()!r} ≠ {info!r}"
    db_bytes = (pkg / "catalog.db").stat().st_size
    assert f"catalog.db {db_bytes:,} B" in page.restore_table.item(pkg_row, 4).toolTip(), \
        "字节原值没挂 tooltip ⇒ 屏幕上只剩一个换算过的读数"

    bare_row = _row_of(page.restore_table, bare.name)
    assert page.restore_table.item(bare_row, 4).text() == format_bytes(bare.stat().st_size)


def test_恢复按钮两个条件都满足才亮(window, ctx, qapp, monkeypatch) -> None:  # noqa: ANN001
    """只满足一半时按下去只会静默 `return`（改前那版就是这样），必须按不动。"""
    page, _tabs = _restore_page(window, qapp, monkeypatch)
    ctx.backup.create_backup()
    page._reload_backups()

    assert not page.btn_restore.isEnabled(), "什么都没选，按钮就亮着"

    page.restore_table.selectRow(0)
    qapp.processEvents()
    assert page._selected is not None
    assert not page.btn_restore.isEnabled(), \
        "选了一行、还没填目标根，按钮就亮了 —— 按下去什么都不发生，界面上也不会说为什么"

    page.ed_target.setText(str(Path(ctx.paths.root) / "新的数据根"))
    qapp.processEvents()
    assert page.btn_restore.isEnabled(), "选中 + 目标根都有了，按钮还是按不动"

    page.ed_target.clear()
    qapp.processEvents()
    assert not page.btn_restore.isEnabled(), "清掉目标根之后按钮还亮着"


def test_非本程序产的快照不进列表(window, ctx, qapp, monkeypatch) -> None:  # noqa: ANN001
    """Q4 甲：列表口径 = 本程序认得的产物，不按「目录里恰好有什么」算。

    本机 `data\\backups\\` 里就躺着一只 `pre-migration-0008-….db`（11.97 GB）：它没有清单，
    选中之后「里面有什么」答不出来 —— 正是甲案要消灭的那类不可见，列出来又答不出更误导。
    """
    page, _tabs = _restore_page(window, qapp, monkeypatch)
    stray = Path(ctx.paths.backups_dir) / "pre-migration-0008-20261020T122144.db"
    stray.parent.mkdir(parents=True, exist_ok=True)
    stray.write_bytes(b"\x00" * 512)
    pkg = ctx.backup.create_backup()

    page._reload_backups()

    for table, label in ((page.restore_table, "恢复"), (page.backup_table, "备份")):
        names = _names(table)
        assert pkg.name in names
        assert stray.name not in names, \
            f"{label}表把迁移前的手工快照列出来了 —— 它没有清单，答不出里面有什么"


def test_两张表同一个来源同一份清单(window, ctx, qapp, monkeypatch) -> None:  # noqa: ANN001
    """两页读的是同一次 `list_backups()`；任何一边自己过滤，都会让两屏的「已有备份」对不上。"""
    page, _tabs = _restore_page(window, qapp, monkeypatch)
    ctx.backup.create_backup()
    time.sleep(1.1)          # 包名只到秒：同一秒内建第二个会撞名（产品侧如实报错，不在本轮改）
    ctx.backup.create_backup()
    _write_bare(ctx)

    page._reload_backups()

    assert page.restore_table.rowCount() == 3
    assert _names(page.restore_table) == _names(page.backup_table), \
        f"两页的清单对不上：恢复={_names(page.restore_table)} 备份={_names(page.backup_table)}"


def test_刷新之后选中的还是同一个包(window, ctx, qapp, monkeypatch) -> None:  # noqa: ANN001
    """选中按**路径**记：新的备份一进来行号就整体下移，按行号记会静默换成别的包。"""
    page, _tabs = _restore_page(window, qapp, monkeypatch)
    old = ctx.backup.create_backup()
    page._reload_backups()
    page.restore_table.selectRow(0)
    assert page._selected == old

    time.sleep(1.1)
    ctx.backup.create_backup()
    page._reload_backups()

    assert page.restore_table.rowCount() == 2
    assert page._selected == old, "刷新把选中项丢了（或换成了别的包）"
    selected = page.restore_table.selectionModel().selectedRows()
    assert len(selected) == 1, f"表上没有唯一一行被选中：{selected}"
    assert page.restore_table.item(selected[0].row(), 0).text() == old.name, \
        "选中的那一行指向了新备份 —— 行号变了，选中没跟着包走"
    assert page.lbl_pick.toolTip() == str(old)


def test_外部位置选来的包刷新后不被表清掉(window, ctx, qapp, monkeypatch) -> None:  # noqa: ANN001
    """移动硬盘 / 另一台机器拷来的包不在 `backups_dir` 里，刷新两次也不许把它丢了。"""
    page, _tabs = _restore_page(window, qapp, monkeypatch)
    pkg = ctx.backup.create_backup()
    outside = Path(ctx.paths.root).parent / "拷到别处" / "backup-20260101-000000-v1"
    outside.mkdir(parents=True)
    for member in (backup_service.DB_MEMBER, backup_service.MANIFEST_NAME):
        shutil.copy2(pkg / member, outside / member)

    # 人点的是包里那颗 catalog.db；服务层归一化成整包
    monkeypatch.setattr(QFileDialog, "getOpenFileName",
                        staticmethod(lambda *a, **k: (str(outside / "catalog.db"), "")))
    page._browse_other()
    assert page._selected == outside

    page._reload_backups()

    assert page._selected == outside, "刷新把外部位置选来的包清掉了"
    assert page.restore_table.selectionModel().selectedRows() == []
    assert page.lbl_pick.toolTip() == str(outside)


def test_选中内容那行说得出包里有什么(window, ctx, qapp, monkeypatch) -> None:  # noqa: ANN001
    """主句：缺的那一半必须在**按之前**看得见（**ISSUES I123** ① 的消费侧）。"""
    page, _tabs = _restore_page(window, qapp, monkeypatch)
    ctx.paths.data_dir.mkdir(parents=True, exist_ok=True)
    ctx.paths.vectors_file.write_bytes(b"\x93NUMPY" + b"\x00" * 4096)
    pkg = ctx.backup.create_backup()
    bare = _write_bare(ctx)

    page._reload_backups()
    page.restore_table.selectRow(_row_of(page.restore_table, pkg.name))
    qapp.processEvents()

    text = page.lbl_contents.text()
    assert "catalog.db" in text and "vectors.npy" in text, f"包里两样东西没摊开：{text!r}"
    assert "清单在场" in text, f"没说明「清单在场 ⇒ 逐个核对字节数」：{text!r}"

    page.restore_table.selectRow(_row_of(page.restore_table, bare.name))
    qapp.processEvents()
    assert "旧格式裸库" in page.lbl_contents.text(), \
        f"裸库没写明「只有库，向量文件回不来」：{page.lbl_contents.text()!r}"


def test_落点那行按AppPaths摆(window, ctx, qapp, monkeypatch) -> None:  # noqa: ANN001
    """落点与恢复时摆放的是同一份映射（`member_destinations`）—— 两边各写一套就是 I123 ②。"""
    page, _tabs = _restore_page(window, qapp, monkeypatch)
    ctx.backup.create_backup()
    page._reload_backups()
    page.restore_table.selectRow(0)
    target = str(Path(ctx.paths.root).parent / "恢复目标根")

    page.ed_target.setText(target)
    qapp.processEvents()

    expected = str(Path(target) / "data" / "catalog.db")
    assert page.lbl_dest.toolTip() == expected, \
        f"落点没按 AppPaths 算：{page.lbl_dest.toolTip()!r} ≠ {expected!r}"
    assert page.lbl_dest.text().startswith("落点：")
    assert "之后显示" not in page.lbl_dest.text(), \
        f"选中与目标根都齐了，落点那行还停在空态：{page.lbl_dest.text()!r}"
