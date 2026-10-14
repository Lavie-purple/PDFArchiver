"""排除规则（SPEC 3.1 第 7 条：支持配置排除目录和排除规则）。

这一层不碰数据库、不碰磁盘，只做字符串判断 —— 排除决定"哪些用户的文件会被打开读一遍"，
所以它的行为必须能被单测穷举，而不是藏在某条 SQL 或某个 walk 循环里。

**唯一口径**：规则匹配的是 `fs.identity.normalize_path()` 之后的路径（正斜杠、绝对路径）。
调用方传进来的若是别的写法（反斜杠、短名、相对路径），先归一再比 —— 否则同一条规则
对 `D:/a/temp/x.pdf` 和 `D:/a/temp\\/x.pdf` 会给出不一样的是/否，那才是真的排除不住。

规则的两种写法（不引入 glob 的 `**` 语义，避免用户猜）：
- **不含 `/`**：当作"名字规则"，路径里**任意一段**命中即排除。`temp` 排掉 `a/temp/b.pdf`，
  `~$*` 排掉所有 Office 临时文件，不管它在第几层。
- **含 `/`**：当作"路径规则"，对整条归一化路径做匹配，`*` 可以跨越 `/`。
  `*/网盘/*` 排掉某个盘下的整棵树。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache

# 内置排除：这些不是"用户可选"的，是**读了也没用**的东西。
# .split() 的每一条都是"名字规则"（不含 /）。
DEFAULT_EXCLUDES: tuple[str, ...] = (
    "~$*",       # Office 锁文件/自动恢复文件，不是文档
    "*.tmp",
    "thumbs.db",
    "desktop.ini",
    ".ds_store",
)


def _glob_to_regex(glob: str) -> re.Pattern[str]:
    """把一条 fnmatch 风格规则编译成正则。`*` → 任意（含 /），`?` → 单字符，`[...]` 原样保留。

    不用 `fnmatch.translate` 是因为它对 `/` 的处理与 `*` 的组合依赖平台（Windows 上不区分大小写），
    而我们要的是"对已归一化的路径、固定不区分大小写"这一个行为。
    """
    out: list[str] = []
    i = 0
    while i < len(glob):
        ch = glob[i]
        if ch == "*":
            out.append(".*")
        elif ch == "?":
            out.append(".")
        elif ch == "[":
            j = glob.find("]", i + 1)
            if j < 0:
                out.append(re.escape(ch))
            else:
                out.append(glob[i:j + 1])
                i = j
        else:
            out.append(re.escape(ch))
        i += 1
    return re.compile("^" + "".join(out) + "$", re.IGNORECASE)


@lru_cache(maxsize=512)
def _compiled(glob: str) -> re.Pattern[str]:
    return _glob_to_regex(glob)


@dataclass(frozen=True)
class Exclusions:
    """一组规则。空规则 = 什么都不排（但内置项照排，见 `DEFAULT_EXCLUDES`）。"""

    globs: tuple[str, ...] = DEFAULT_EXCLUDES

    @classmethod
    def of(cls, extra: list[str] | tuple[str, ...] | None = None,
           *, include_defaults: bool = True) -> Exclusions:
        extra = tuple((extra or ()))
        base = DEFAULT_EXCLUDES if include_defaults else ()
        merged: list[str] = []
        for g in (*base, *extra):
            cleaned = str(g).strip().replace("\\", "/")
            if cleaned and cleaned not in merged:
                merged.append(cleaned)
        return cls(tuple(merged))

    def is_excluded(self, normalized_path: str) -> bool:
        """`normalized_path` 必须是 `normalize_path()` 的产物（正斜杠、绝对路径）。
        传原始路径进来不会被拒绝，但结果不作保证 —— 归一是调用方的责任，
        因为"同一个文件"的判定只有 `identity` 一处口径。"""
        path = normalized_path.replace("\\", "/")
        segments = [s for s in path.split("/") if s]
        for glob in self.globs:
            regex = _compiled(glob)
            if "/" in glob:
                if regex.match(path):
                    return True
            elif any(regex.match(seg) for seg in segments):
                return True
        return False

    def describe(self) -> str:
        if not self.globs:
            return "无排除规则"
        return f"{len(self.globs)} 条规则：" + ", ".join(self.globs)
