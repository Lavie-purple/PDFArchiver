"""备份与恢复服务 —— S6 的后端。

备份口径唯一：`sqlite3.Connection.backup()`（WAL 模式禁止文件拷贝）。
备份包是一个**目录**（`backup-YYYYMMDD-HHMMSS-v版本/`），内含：
- `catalog.db`（Backup API 一致性快照）
- `vectors.npy`（语义向量库，**建过就必须在场** —— 它不在库里，漏了就等于把语义搜索备丢了）
- `settings.json`（如果存在）
- `manifest.json`（逐成员的名字与字节数，最后一步才写）

旧格式（单个 `.db` 文件、没有 manifest 的目录）仍然可读，恢复时自动识别。

恢复落点口径唯一 = **数据根目录**：产物按 `AppPaths` 摆成应用启动时读的那套布局
（`root/data/catalog.db` + `root/data/vectors.npy` + `root/config/settings.json`），
所以「恢复到新目录」之后把 `--data-dir` 指到那个目录就直接能开。以前 `catalog.db` 落在
`root` 顶层而 `settings.json` 落在 `root/config/`，两者一半对一半错 —— 指过去开不到库
（**ISSUES I123** ②）。
恢复绝不覆盖当前库；恢复后跑 `PRAGMA integrity_check`，坏库当场拒绝并删掉残留。
"""
from __future__ import annotations

import gc
import json
import logging
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path

from pdfarchiver.config.paths import AppPaths
from pdfarchiver.db.engine import Engine
from pdfarchiver.db.migrate import current_version, discover

log = logging.getLogger("pdfarchiver.backup")

MANIFEST_NAME = "manifest.json"
MANIFEST_VERSION = 1
DB_MEMBER = "catalog.db"
VECTORS_MEMBER = "vectors.npy"
SETTINGS_MEMBER = "settings.json"

# 一个包里"算备份内容"的那几样，顺序就是恢复时摆放的顺序。
# 边文件（`catalog.db-wal` / `-shm`）不在这里：它们不是备份内容，恢复也不搬它们 ——
# 而 2026-10-31 现读，真库里那个没有清单的老包里就躺着这两只（32,768 B / 0 B）。
RESTORABLE_MEMBERS = (DB_MEMBER, VECTORS_MEMBER, SETTINGS_MEMBER)


def _refuse_occupied(plan: list[tuple[str, Path, int | None]]) -> None:
    """落点已被占着就整包拒绝（**ISSUES I126** 甲）。

    `restore_to_new_dir()` 是产品里唯一往「不是自己创建的路径」写东西的地方，而恢复出来的
    那份是**没有第二份可取**的。2026-11-01 实测两条：目标根里别人那份 `vectors.npy` 被
    `shutil.copy2` 无声盖掉（界面上报「恢复成功」）；`settings.json` 落点是个同名目录时，
    `copy2` 把成员写进那个目录、字节比对拿到 0、清理「残留」再 `rmtree` 连目录带里面的
    文件一起删。所以判据只有一条：**落点存在（含符号链接）就一个字节也不写**。

    目录单独说一句 —— 那不是「同名文件」，是别人整个目录被我们当成落点。
    """
    for name, dst, _want in plan:
        if not (dst.exists() or dst.is_symlink()):
            continue
        kind = "目录" if dst.is_dir() else "文件"
        raise FileExistsError(
            f"目标根里已经有 {name}（{kind}）：{dst}\n"
            f"恢复不会覆盖它 —— 请换一个空目录，或先把这份挪走。")


def snapshot_paths(backups_dir: Path) -> list[Path]:
    """哪些文件算「库快照」的唯一口径 —— S7 体检的 C11 与 p12 探针都读这一个函数。

    两种形状都要认：`backups/` 顶层的裸 `.db`（迁移落的 `pre-migration-*`、以及 2026-10-31
    之前 S6 产的单文件备份），和目录包里的 `catalog.db`。只 glob 顶层 `*.db` 会把 ①甲 之后的
    新备份**静默漏掉**：C11 那句「整库体检只跑最新一份」体检的还是迁移时的旧快照，而真包从没
    被打开过 —— 读数照绿，什么也没验。
    """
    if not backups_dir.is_dir():
        return []
    snaps = sorted(p for p in backups_dir.glob("*.db") if p.is_file())
    for pkg in sorted(p for p in backups_dir.glob("backup-*") if p.is_dir()):
        member = pkg / DB_MEMBER
        if member.is_file():
            snaps.append(member)
    return snaps


def snapshot_label(snap: Path, backups_dir: Path) -> str:
    """快照在报告里的名字：包里的库必须带出包名，否则每个包都印成同一个 `catalog.db`。"""
    if snap.parent != backups_dir:
        return f"{snap.parent.name}/{snap.name}"
    return snap.name


class BackupService:
    """备份与恢复：sqlite3.Connection.backup() 是唯一合法路径。"""

    def __init__(self, paths: AppPaths, engine: Engine) -> None:
        self.paths = paths
        self.engine = engine

    def create_backup(self, target_dir: str | Path | None = None) -> Path:
        """备份当前库 + 向量库 + 设置到指定目录（默认 backups_dir）。返回备份**目录**。

        目录名格式：`backup-YYYYMMDD-HHMMSS-v版本/`。清单**最后一步**才写，所以任一步失败
        或被中途打断，留下的目录都不是一个「看着像备份」的成品；失败路径统一 `_discard` 掉。

        拷贝顺序有讲究：**先库后向量文件**。反过来若先拷向量、再快照库，中间新增的向量下标
        可能超出已拷文件的容量，备出来的那对文件一搜就报 `VectorFileMismatch`；
        按现在这个顺序，向量文件的行数只可能**不少于**库里报到的下标。
        """
        if target_dir is None:
            target_dir = self.paths.backups_dir
        target_dir = Path(target_dir)
        target_dir.mkdir(parents=True, exist_ok=True)

        conn = self.engine.thread_connection()
        version = current_version(conn)

        now = datetime.now(timezone.utc)
        backup_dir = target_dir / f"backup-{now.strftime('%Y%m%d-%H%M%S')}-v{version}"
        backup_dir.mkdir()

        try:
            self.engine.snapshot_to(backup_dir / DB_MEMBER)
            members = [{"name": DB_MEMBER,
                        "bytes": (backup_dir / DB_MEMBER).stat().st_size}]
            for name, src in ((VECTORS_MEMBER, self.paths.vectors_file),
                              (SETTINGS_MEMBER, self.paths.settings_file)):
                if src.exists():
                    members.append(_copy_member(backup_dir, src, name))
            _write_manifest(backup_dir, now, version, members)
        except BaseException:
            # 这个目录是上面刚 `mkdir` 出来的半成品，不是别人的东西 —— 允许整棵删。
            self._discard(backup_dir, allow_tree=True)
            raise

        log.info("备份完成：%s（%d 个成员）", backup_dir, len(members))
        return backup_dir

    def list_backups(self, backup_dir: str | Path | None = None) -> list[dict]:
        """列出指定目录下的全部备份。返回 [{"path": Path, "version": int, "mtime": int,
        "kind": "dir"|"file"}, ...]。

        同时识别新格式（目录）与旧格式（单个 `.db` 文件）。
        """
        if backup_dir is None:
            backup_dir = self.paths.backups_dir
        backup_dir = Path(backup_dir)
        if not backup_dir.exists():
            return []

        backups = []

        for d in backup_dir.glob("backup-*"):
            if d.is_dir():
                version = _parse_version_from_stem(d.name)
                if version is not None:
                    backups.append({
                        "path": d,
                        "version": version,
                        "mtime": int(d.stat().st_mtime),
                        "kind": "dir",
                    })

        for p in backup_dir.glob("catalog-*.db"):
            version = _parse_version_from_stem(p.stem)
            if version is not None:
                backups.append({
                    "path": p,
                    "version": version,
                    "mtime": int(p.stat().st_mtime),
                    "kind": "file",
                })

        backups.sort(key=lambda b: b["mtime"], reverse=True)
        return backups

    @staticmethod
    def describe_backup(backup_path: str | Path) -> dict:
        """把一个备份"里面到底有什么、各多少字节"摊开给界面看 —— 只读清单与 `stat`，**绝不开库**。

        返回 `{"kind": "dir"|"file", "has_manifest": bool,
        "members": [{"name": str, "bytes": int}], "total_bytes": int}`。

        成员集合与 `_plan_members()` 要往目标根里放的那几样**同一条口径**（清单为准，
        无清单的旧包认 `RESTORABLE_MEMBERS` 里在场的那几样）。这条不是洁癖：本轮冒的坑
        （**ISSUES I123** ①）正是"备份缺一半而界面写着成功"，如果展示读一套、恢复读另一套，
        就等于把同一个毛病从产出侧搬到了消费侧。

        体积取的是**成员自己的字节数之和**，不是包目录的表观占用：包里那两只边文件不算成员，
        而 `manifest.json` 本身几百字节 —— 报"包多大"会把不该准备的空间算进去。
        """
        path = as_package(Path(backup_path))
        if not path.is_dir():
            size = path.stat().st_size
            return {"kind": "file", "has_manifest": False,
                    "members": [{"name": DB_MEMBER, "bytes": size}], "total_bytes": size}

        manifest = _read_manifest(path)
        members: list[dict] = []
        if manifest is None:
            # 没有清单：有什么算什么（与 `_plan_members` 的无清单分支同一句判据）
            for name in RESTORABLE_MEMBERS:
                member = path / name
                if member.is_file():
                    members.append({"name": name, "bytes": member.stat().st_size})
        else:
            recorded = {item.get("name"): item.get("bytes") for item in manifest["members"]
                        if isinstance(item, dict)}
            for name in RESTORABLE_MEMBERS:
                if name not in recorded:
                    # 盘上多出来的东西不算成员：清单没写它，恢复就不搬它 ——
                    # "界面上看得见、恢复回来却没有"正是本轮要消灭的那一类不可见。
                    continue
                member = path / name
                want = recorded[name]
                if not isinstance(want, int):
                    want = member.stat().st_size if member.is_file() else 0
                members.append({"name": name, "bytes": want})
        return {"kind": "dir", "has_manifest": manifest is not None, "members": members,
                "total_bytes": sum(m["bytes"] for m in members)}

    def restore_to_new_dir(self, backup_path: str | Path,
                           target_root: str | Path) -> Path:
        """把一个备份恢复到**新的数据根目录**（不覆盖当前库）。返回恢复出来的 `catalog.db`。

        传进来的 `target_root` 就是恢复之后要填给 `--data-dir` 的那个目录，落点由 `AppPaths`
        算（不再自己拼路径）。自动识别三种包：
        - 带 `manifest.json` 的目录：按清单逐个恢复，逐个核对字节数
        - 不带清单的目录：认 `catalog.db`，`vectors.npy` / `settings.json` 在场才恢复
        - 旧格式（单个 `.db` 文件）：只恢复库 —— 但**如果它旁边就有 `manifest.json`**，
          说明它是被人从包里单独点进来的，按整包走上面第一档
          （同一条归一化在 `as_package`，`describe_backup()` 也走它 ——
          展示与恢复不许对"这算哪个包"有两种答案）

        任一步失败都要把已经写进目标根的东西删干净 —— 半个库比没有库更坏。
        """
        backup_path = as_package(Path(backup_path))
        paths = AppPaths.resolve(target_root)
        new_db = paths.catalog_db

        plan = self._plan_members(backup_path, paths)
        if not any(name == DB_MEMBER for name, _dst, _want in plan):
            raise FileNotFoundError(f"备份里没有 catalog.db：{backup_path}")

        # 目标根是别人的目录：三个落点只要被不是本次恢复的东西占着，就整包拒绝。
        # 这里是产品里唯一往「不是自己创建的路径」写的地方 —— 覆盖掉的那份没有第二份可取。
        _refuse_occupied(plan)

        written: list[Path] = []
        try:
            for name, dst, want_bytes in plan:
                src = self._member_source(backup_path, name)
                dst.parent.mkdir(parents=True, exist_ok=True)
                _refuse_occupied([(name, dst, want_bytes)])   # 预检到落盘之间也可能被人占了
                shutil.copy2(str(src), str(dst))
                written.append(dst)      # 先记账再判定：不然下面这条拒绝就把自己刚写的文件漏在外面
                got = dst.stat().st_size
                if want_bytes is not None and got != want_bytes:
                    raise ValueError(
                        f"{name} 恢复出来是 {got} 字节，清单里写的是 {want_bytes} 字节 —— "
                        f"这份备份不完整，拒绝使用")
            check = self._verify(new_db)
            if check != "ok":
                raise ValueError(f"完整性检查失败：{check}")
        except Exception as exc:
            for dst in written:
                self._discard(dst)
            raise ValueError(f"恢复失败：{exc}。已删除本次恢复写入的文件。") from exc

        log.info("恢复到新数据根：%s", new_db)
        return new_db

    @staticmethod
    def member_destinations(paths: AppPaths) -> dict[str, Path]:
        """成员名 → 恢复之后它落在目标根的哪个路径。

        界面上那行「落点：<目标根>\\data\\catalog.db ＋ …」与 `_plan_members()` 共用这一份：
        界面上写一套、恢复时摆另一套，就是本轮 **ISSUES I123** ② 那个"一半对一半错"的复刻。
        """
        return {DB_MEMBER: paths.catalog_db,
                VECTORS_MEMBER: paths.vectors_file,
                SETTINGS_MEMBER: paths.settings_file}

    @staticmethod
    def _plan_members(backup_path: Path, paths: AppPaths) -> list[tuple[str, Path, int | None]]:
        """这个备份包该往目标根里放哪几样，各自落在哪个路径（清单在场就以清单为准）。"""
        destinations = BackupService.member_destinations(paths)
        if not backup_path.is_dir():
            return [(DB_MEMBER, destinations[DB_MEMBER], None)]

        manifest = _read_manifest(backup_path)
        if manifest is None:
            # 没有清单的老备份包：有什么恢复什么，但库必须在场
            return [(name, destinations[name], None)
                    for name in RESTORABLE_MEMBERS
                    if (backup_path / name).exists()]

        entries = {item.get("name"): item.get("bytes") for item in manifest["members"]
                   if isinstance(item, dict) and item.get("name") in destinations}
        return [(name, destinations[name], entries.get(name)) for name in
                RESTORABLE_MEMBERS if name in entries]

    @staticmethod
    def _member_source(backup_path: Path, name: str) -> Path:
        return backup_path / name if backup_path.is_dir() else backup_path

    @staticmethod
    def _verify(new_db: Path) -> str:
        """`PRAGMA integrity_check`。开库会建 WAL 边文件，检查完必须关掉那只连接。"""
        engine = Engine(new_db)
        try:
            return engine.integrity_check()
        finally:
            engine.close_thread_connection()
            del engine
            gc.collect()

    @staticmethod
    def _discard(target: Path, *, allow_tree: bool = False) -> None:
        """删掉一个可能还被人开着句柄的产物（库 + 它的 WAL 边文件）。

        默认**只删文件**：`restore_to_new_dir()` 的清理只该动本次恢复自己写出来的东西，
        目标根里同名目录连同里面的文件不是我们创建的（**ISSUES I126** 乙 —— 原来这里
        `is_dir()` 就 `rmtree`，把人的目录整个删了）。备份侧那半成品目录是自己刚 `mkdir`
        的，调用时显式传 `allow_tree=True`。

        Windows 上 `Engine` 关连接不等于句柄立刻释放，所以先 `gc` 再重试 5×0.2s；
        实在删不掉只报 warning —— 把原始失败盖住是更坏的结果。
        """
        if target.is_dir():
            if not allow_tree:
                log.warning("不删目录（不是本次恢复创建的）：%s", target)
                return
            shutil.rmtree(str(target), ignore_errors=False)
            return
        gc.collect()
        for _ in range(5):
            try:
                target.unlink(missing_ok=True)
                for suffix in ("-wal", "-shm"):
                    target.with_name(target.name + suffix).unlink(missing_ok=True)
                return
            except PermissionError:
                time.sleep(0.2)
        log.warning("残留没删掉，请手工检查：%s", target)

    def list_migrations(self) -> list[dict]:
        """列出已应用的迁移。从 db/migrations/ 文件名派生（无持久化表）。

        返回 [{"order": int, "name": str, "applied": bool}, ...]。
        """
        migrations_dir = self.paths.root.parent / "src" / "pdfarchiver" / "db" / "migrations"
        if not migrations_dir.exists():
            import pdfarchiver.db.migrations as m
            migrations_dir = Path(m.__file__).parent

        all_migrations = discover(migrations_dir)
        conn = self.engine.thread_connection()
        current = current_version(conn)

        result = []
        for m in all_migrations:
            result.append({
                "order": m.order,
                "name": m.label,
                "applied": m.order <= current,
            })
        return result


def as_package(backup_path: Path) -> Path:
    """人从包里单独点进来的那颗 `catalog.db` ⇒ 归一化成它所属的**包**。

    恢复必须按整包走，不许只回半个库（向量文件还在包里躺着）—— 这是 **ISSUES I123** ①
    那类"看着成功、缺一半"的最后一条路。展示体积的那条路（`describe_backup()`）与
    界面那边的「浏览其他位置…」（点包里的 `manifest.json` 也算选中了那个包）走的是
    **同一个函数**：如果各写一遍，界面报"只有 catalog.db 11.2 GB"而恢复搬回来两样，
    差别就落在没人能从屏幕上看出来的地方。
    """
    if backup_path.is_file() and (backup_path.parent / MANIFEST_NAME).exists():
        return backup_path.parent
    return backup_path


def _copy_member(backup_dir: Path, src: Path, name: str) -> dict:
    """把一样成员拷进备份包，当场核对字节数 —— 拷漏了要在这里炸，不许带进包里。"""
    dst = backup_dir / name
    shutil.copy2(str(src), str(dst))
    got, want = dst.stat().st_size, src.stat().st_size
    if got != want:
        raise ValueError(f"{name} 只拷进备份包 {got} 字节，源文件是 {want} 字节")
    return {"name": name, "bytes": got}


def _write_manifest(backup_dir: Path, created_at: datetime,
                    schema_version: int, members: list[dict]) -> None:
    payload = {"manifest_version": MANIFEST_VERSION,
               "created_at": created_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
               "schema_version": schema_version,
               "members": members}
    (backup_dir / MANIFEST_NAME).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _read_manifest(backup_path: Path) -> dict | None:
    raw = backup_path / MANIFEST_NAME
    if not raw.exists():
        return None
    try:
        payload = json.loads(raw.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise ValueError(f"备份清单读不出来（{raw}）：{exc}") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("members"), list):
        raise ValueError(f"备份清单形状不对（{raw}）：没有 members 列表")
    return payload


def _parse_version_from_stem(stem: str) -> int | None:
    """从 `backup-YYYYMMDD-HHMMSS-v版本` 或 `catalog-YYYYMMDD-HHMMSS-v版本` 里提取版本号。"""
    for part in stem.split("-"):
        if part.startswith("v") and part[1:].isdigit():
            return int(part[1:])
    return None
