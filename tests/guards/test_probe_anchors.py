"""注入锚点的**在场性**守卫 —— 把「坏法今天还落得进去」提前到秒级确认。

反向注入探针的判据是「红且点名」，而锚点失配时代码根本没被改过：p9/p10 直接
`RuntimeError`，p15/p16/p17/p18 记一条 SKIP 并让 `VERDICT` 变 RED —— 两种都算红，
但要等 **680.5s**（段 injection，2026-10-19 六份探针同段实测；同段不含 p21 时 2026-10-18
空载 **332s**。p22 于 2026-10-19 入段，单跑 73s，段总时长待空载复跑后更新这一行）
+ **70s**（段 ui-inject）才告诉你坏了，
而且坏因是三周前改 OCR 熔断器时往锚点中间插了一行。
2026-10-18 的门禁就是这么红的（p10 的 #8、#26、#28 三条同时失配）。

这条守卫只做一件事：**不跑 pytest**，把八份探针表里每条锚点拿来在目标文件里数一遍。
口径与探针自己一致，不另立第二份：
- `count(anchor) == 1`，按通用换行读入（p9/p10 的 `_apply` 就是这个式子）；
- 目标文件不存在同样算失配。

第二条断言钉的是行尾：p15/p16/p17/p18 注入时按**字节**换行匹配，与本条的文本口径只在
「同一个文件混用行尾」时分叉。`tests/probes/p10_reverse_injection_ocr.py` 自己就中过 ——
289 行的文件写成 `\r\r\n`，被 `tests/guards/test_file_size.py` 的 `splitlines()` 数成 577 行。

坏法注入（要求「红且点名」，2026-10-18 三条都真注入过一次）：
1. 把 `tests/probes/p18_...py` 里 `PROP` 的 `.exists()` 改成 `.exist()` → 第一条红并点名 `p18 #S3`；
2. 把某个注入目标文件的某行行尾写成 `\r\r\n` → 第二条红并点名那个文件；
3. 把本文件 `anchors()` 里 `"p17"` 那一行的表换成 `[]` → 第三条红并点名 `p17=0`
   （这条防的是「探针改名/表清空 → 前两条静默变永真」）。
没红过的守卫不算守卫（AGENTS.md）。

跑法：
    .venv/Scripts/python.exe -m pytest tests/guards/test_probe_anchors.py -q
    .venv/Scripts/python.exe tests/guards/test_probe_anchors.py    # 独立跑，末行 VERDICT
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "probes"))

import p9_reverse_injection as p9  # noqa: E402
import p10_reverse_injection_ocr as p10  # noqa: E402
import p15_archive_ui_injection as p15  # noqa: E402
import p16_doc_pointers_injection as p16  # noqa: E402
import p17_handler_shape_injection as p17  # noqa: E402
import p18_irreversible_source_injection as p18  # noqa: E402
import p21_saved_search_injection as p21  # noqa: E402
import p22_category_export_injection as p22  # noqa: E402

REPO = Path(__file__).resolve().parents[2]


def _from_case_edits(probe: str, cases) -> list[tuple[str, str, Path, str]]:
    rows = []
    for case in cases:
        for edit in case.edits:
            if edit.append:      # 追加型坏法没有锚点，只往文件尾巴加行
                continue
            rows.append((probe, f"#{case.inject}", REPO / edit.path, edit.anchor))
    return rows


def _from_tuples(probe: str, mutations, path_at: int | None, anchor_at: int,
                 fixed_path: Path | None = None,
                 relative: bool = False) -> list[tuple[str, str, Path, str]]:
    """p15/p16/p17/p18 各自的坏法表：字段顺序不同，但都有一条「锚点」和一处「落点」。"""
    rows = []
    for row in mutations:
        if fixed_path is not None:
            path = fixed_path
        elif relative:
            path = REPO / row[path_at]
        else:
            path = row[path_at]
        rows.append((probe, f"#{row[0]}", path, row[anchor_at]))
    return rows


def anchors() -> list[tuple[str, str, Path, str]]:
    """八份探针的全部坏法锚点：(探针, 编号, 目标文件, 锚点)。"""
    return [
        *_from_case_edits("p9", p9.CASES),
        *_from_case_edits("p10", p10.CASES),
        *_from_tuples("p15", p15.MUTATIONS, 2, 3, relative=True),
        *_from_tuples("p16", p16.MUTATIONS, 2, 3, relative=True),
        *_from_tuples("p17", p17.MUTATIONS, None, 2, fixed_path=p17.SRC),
        *_from_tuples("p18", p18.MUTATIONS, 2, 3),
        *_from_case_edits("p21", p21.CASES),
        *_from_case_edits("p22", p22.CASES),
    ]


def _hits(path: Path, anchor: str) -> int:
    return path.read_text(encoding="utf-8").count(anchor)


def test_每条注入锚点在目标文件里恰好命中一次() -> None:
    bad: list[str] = []
    rows = anchors()
    for probe, cid, path, anchor in rows:
        if not path.exists():
            bad.append(f"{probe} {cid} 目标文件不在场：{path.relative_to(REPO)}")
            continue
        n = _hits(path, anchor)
        if n != 1:
            first = anchor.splitlines()[0].strip()[:60]
            bad.append(f"{probe} {cid} 命中 {n} 次（要求 1 次）"
                       f"｜{path.relative_to(REPO)}｜{first}")
    assert not bad, f"{len(rows)} 条锚点里 {len(bad)} 条失配：\n" + "\n".join(bad)


def test_探针与其注入目标不许混用行尾() -> None:
    paths = sorted({p for _, _, p, _ in anchors()} | {
        Path(__file__).resolve(),
        *(REPO / "tests" / "probes" / f"{name}.py" for name in
          ("p9_reverse_injection", "p10_reverse_injection_ocr",
           "p15_archive_ui_injection", "p16_doc_pointers_injection",
           "p17_handler_shape_injection", "p18_irreversible_source_injection",
           "p21_saved_search_injection", "p22_category_export_injection")),
    })
    mixed = [str(p.relative_to(REPO)) for p in paths if b"\r\r\n" in p.read_bytes()]
    assert not mixed, "这些文件里有 \\r\\r\\n（会被按通用换行数成两倍行数）：" + " ".join(mixed)


def test_注入锚点表不许空转() -> None:
    """八份探针都真在表里 —— 探针改名或表清空时，上面两条会静默变成永真。"""
    counts = {probe: sum(1 for row in anchors() if row[0] == probe)
              for probe in ("p9", "p10", "p15", "p16", "p17", "p18", "p21", "p22")}
    empty = [f"{k}={v}" for k, v in counts.items() if v == 0]
    assert not empty, f"这些探针一条锚点都没收集到：{' '.join(empty)}｜全表 {counts}"


if __name__ == "__main__":
    fails: list[str] = []
    for fn in (test_每条注入锚点在目标文件里恰好命中一次,
               test_探针与其注入目标不许混用行尾,
               test_注入锚点表不许空转):
        try:
            fn()
        except AssertionError as exc:
            fails.append(f"{fn.__name__}：{exc}")
    rows = anchors()
    files = {p for _, _, p, _ in rows}
    print(f"核了 {len(rows)} 条锚点，落在 {len(files)} 个文件上")
    for line in fails:
        print("RED  " + line[:900])
    print("VERDICT: " + ("ALL GREEN" if not fails else "RED"))
    sys.exit(0 if not fails else 2)
