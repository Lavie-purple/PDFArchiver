"""目录遍历：把一棵树里的条目逐个交出去，**不返回大列表**。

这一层不碰数据库、不碰索引、不改任何东西（docs/ARCHITECTURE 二：`fs` 不许 import `db`）。
它只回答一个问题：**"这棵子树现在有什么"**，并把过程中遇到的每一个读不动的目录
原样带出来，交给 `services/scan_service.py` 去决定"这条记成错误、其余继续"。

四条实测逼出来的做法：

1. **迭代而不是递归**。用显式栈，不用 `rglob` / 递归函数 —— 递归实现要么爆栈，
   要么在超长中文路径上被绊倒（P7 的 533 字符路径要靠 LongPathsEnabled 才走得通，不该依赖）。
2. **目录 realpath 去重**。NTFS junction 与符号链接可以构成环，`os.walk(followlinks=False)`
   对 junction 不生效。成环时不挡就会无限增长队列 —— 这不是慢，是永远扫不完。
3. **单个目录打不开不是结束**。权限不足、正被独占、网络盘掉线都很常见，
   必须产出一条 `error` 条目然后继续走下一个目录（SPEC 阶段 2 验收：解析失败不中断整体扫描）。
4. **排除、非 PDF、错误都用同一种条目类型带出来**，靠 `kind` 区分。
   把它们都塞进 `ScanError` 会让"排除"看起来像故障，而它明明是用户配置生效的证据。
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator

from pdfarchiver.fs.exclude import Exclusions
from pdfarchiver.fs.identity import FileIdentity, normalize_path, read_identity

log = logging.getLogger("pdfarchiver.fs")

PDF_EXT = "pdf"
KIND_PDF = "pdf"
KIND_EXCLUDED = "excluded"
KIND_OTHER = "other_ext"
KIND_ERROR = "error"
KINDS = (KIND_PDF, KIND_EXCLUDED, KIND_OTHER, KIND_ERROR)


@dataclass(frozen=True)
class ScanItem:
    """遍历产出的一个条目。

    - `kind=pdf` 时 `identity` 一定可用，`detail` 为空；
    - `kind=excluded` / `other_ext` 时 `identity` 也可用（已 stat 过，不用白不用），
      但它**不会**被写进数据库；
    - `kind=error` 时只有 `path` 与 `detail`（原文错误），`identity` 为 None —— 打不开就是打不开，
      不猜它是什么。
    """

    kind: str
    path: str
    identity: FileIdentity | None = None
    detail: str = ""

    @property
    def is_pdf(self) -> bool:
        return self.kind == KIND_PDF


def iter_tree(root_path: str | os.PathLike[str], exclusions: Exclusions,
              *, should_stop: Callable[[], bool] | None = None) -> Iterator[ScanItem]:
    """深度优先走完一棵树。`should_stop` 是协作式取消位，每进入一个目录检查一次
    （目录粒度 = 一次 `os.scandir`，最长几十毫秒，足够让"停止扫描"点下去就有反应）。"""
    root = Path(os.fspath(root_path))
    stack: list[Path] = [root]
    seen_dirs: set[str] = set()

    while stack:
        if should_stop is not None and should_stop():
            log.info("扫描被取消，剩余 %d 个目录未走", len(stack))
            return
        current = stack.pop()
        try:
            real = normalize_path(current)
        except OSError as exc:
            yield ScanItem(KIND_ERROR, str(current), detail=f"{type(exc).__name__}: {exc}")
            continue
        if real in seen_dirs:
            continue  # junction / 符号链接成环：走过就跳过
        seen_dirs.add(real)

        if exclusions.is_excluded(real):
            continue  # 整棵子树被排除：不下钻。排除了多少文件不计数 —— 没进去看，就不知道

        try:
            with os.scandir(current) as it:
                entries = list(it)
        except OSError as exc:
            yield ScanItem(KIND_ERROR, str(current), detail=f"{type(exc).__name__}: {exc}")
            continue

        for entry in entries:
            try:
                is_dir = entry.is_dir(follow_symlinks=False)
            except OSError as exc:
                yield ScanItem(KIND_ERROR, entry.path, detail=f"{type(exc).__name__}: {exc}")
                continue
            if is_dir:
                stack.append(Path(entry.path))
                continue
            try:
                identity = read_identity(entry.path)
            except OSError as exc:
                yield ScanItem(KIND_ERROR, entry.path, detail=f"{type(exc).__name__}: {exc}")
                continue
            if exclusions.is_excluded(identity.path):
                yield ScanItem(KIND_EXCLUDED, identity.path, identity, detail="命中排除规则")
                continue
            if identity.ext != PDF_EXT:
                yield ScanItem(KIND_OTHER, identity.path, identity, detail=f"不是 PDF（.{identity.ext}）")
                continue
            yield ScanItem(KIND_PDF, identity.path, identity)


def collect_pdfs(root_path: str | os.PathLike[str], exclusions: Exclusions,
                 *, should_stop: Callable[[], bool] | None = None
                 ) -> tuple[list[FileIdentity], list[ScanItem]]:
    """走完一棵树，返回 (PDF 身份列表, 非-PDF 之外的全部条目计数用原始条目)。

    只在**全量扫描**用。第二项是 `kind != pdf` 的全部条目（含 excluded / other / error），
    由调用方分类计数 —— 计数口径只有一份：这里交出的条目数就是各 kind 的条数。
    """
    pdfs: list[FileIdentity] = []
    others: list[ScanItem] = []
    for item in iter_tree(root_path, exclusions, should_stop=should_stop):
        if item.is_pdf and item.identity is not None:
            pdfs.append(item.identity)
        else:
            others.append(item)
    return pdfs, others
