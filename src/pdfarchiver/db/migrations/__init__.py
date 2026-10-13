"""顺序迁移。文件名 `0001_initial.py` 这种形态按 docs/DATABASE 四 的规定，
用 importlib 按路径加载（模块名以数字开头不能正常 import，所以不靠 import 语句发现迁移）。
"""
from __future__ import annotations

import importlib.util
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

MIGRATION_FILE_RE = re.compile(r"^(?P<order>\d{4})_(?P<slug>[a-z0-9_]+)\.py$")


@dataclass(frozen=True)
class Migration:
    order: int
    slug: str
    filename: str
    apply: Callable[[object], None]

    @property
    def version(self) -> int:
        return self.order

    @property
    def label(self) -> str:
        return f"{self.order:04d}_{self.slug}"


def discover(migrations_dir: Path) -> list[Migration]:
    """按文件名升序加载全部迁移。缺号不补、乱序不猜 —— 目录里有什么就是什么。"""
    found: list[Migration] = []
    for path in sorted(migrations_dir.glob("*.py")):
        if path.name.startswith("_"):
            continue
        m = MIGRATION_FILE_RE.match(path.name)
        if not m:
            raise ValueError(f"迁移文件名不符合 NNNN_slug.py 规则：{path.name}")
        spec = importlib.util.spec_from_file_location(f"pdfarchiver_migration_{m.group('order')}", path)
        if spec is None or spec.loader is None:
            raise ValueError(f"无法加载迁移脚本：{path}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        for attr in ("VERSION", "apply"):
            if not hasattr(module, attr):
                raise ValueError(f"迁移 {path.name} 缺少 {attr}")
        if module.VERSION != int(m.group("order")):
            raise ValueError(f"迁移 {path.name} 的 VERSION={module.VERSION} 与文件名序号不一致")
        found.append(Migration(int(m.group("order")), m.group("slug"), path.name, module.apply))
    orders = [f.order for f in found]
    if len(set(orders)) != len(orders):
        raise ValueError(f"迁移序号重复：{orders}")
    return sorted(found, key=lambda f: f.order)
