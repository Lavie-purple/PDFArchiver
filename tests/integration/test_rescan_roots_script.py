"""**ISSUES I118** 甲：`scripts/rescan_roots.py` —— 按监测根增量重扫的固定入口。

它写的是用户库，所以这里只钉三件事，每件都能被一种坏法打红：
1. 不带 `--apply` 一个字不写（坏法：把 dry-run 提前返回删掉）；
2. 按根扫描能把「两次扫描之间落进监测根」的文件变成「主记录 + 正文 + fts done」
   （坏法：`rescan_roots` 里不调 `scan_root`）；
3. `--only` 与 `--paths` 都只碰点到的那一部分（坏法：忽略筛选条件、把所有根都扫一遍）。
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

from pdfarchiver.fs.identity import identity_key

REPO = Path(__file__).resolve().parents[2]


def _load_script():
    spec = importlib.util.spec_from_file_location("rescan_roots_script",
                                                  REPO / "scripts" / "rescan_roots.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _state(ctx, path: str):
    return ctx.documents.facts_by_key(identity_key(Path(path)))


def test_按根重扫把新落盘的文件补进库并建好正文(ctx, root, make_pdf) -> None:
    root("监测目录")
    pdf = make_pdf("监测目录/两次扫描之间落下的报告.pdf", pages=2,
                   lines=["这份文件是在上一场链之后才落进监测根的，库里本来没有它。"])

    code = _load_script().main(["--data-root", str(ctx.paths.root), "--apply"])

    assert code == 0
    known = _state(ctx, pdf)
    assert known is not None, "按根重扫之后盘上的文件必须在库里"
    assert known.fts_status == "done", f"正文没建完：fts_status={known.fts_status}"
    assert ctx.texts.count_pages(int(known.doc_id)) == 2


def test_不带_apply_就只读预演一个字不写(ctx, root, make_pdf) -> None:
    root("监测目录")
    pdf = make_pdf("监测目录/只在盘上.pdf")

    code = _load_script().main(["--data-root", str(ctx.paths.root)])

    assert code == 0
    assert ctx.documents.count() == 0, "预演不许写库 —— 这个入口默认是只读的"
    assert _state(ctx, pdf) is None


def test_only_不匹配的根一根都不碰(ctx, root, make_pdf) -> None:
    root("甲根")
    root("乙根")
    picked = make_pdf("甲根/点到的.pdf")
    untouched = make_pdf("乙根/没点到的.pdf")

    code = _load_script().main(["--data-root", str(ctx.paths.root), "--apply",
                                "--only", "甲根"])

    assert code == 0
    assert _state(ctx, picked) is not None
    assert _state(ctx, untouched) is None, "--only 之外的根不许被扫进来"


def test_paths_模式只索引点名的那一份(ctx, root, make_pdf) -> None:
    root("监测目录")
    picked = make_pdf("监测目录/点名的.pdf")
    untouched = make_pdf("监测目录/没点名的.pdf")

    code = _load_script().main(["--data-root", str(ctx.paths.root), "--apply",
                                "--paths", picked])

    assert code == 0
    known = _state(ctx, picked)
    assert known is not None and known.fts_status == "done"
    assert _state(ctx, untouched) is None, "点名模式不许顺手扫整棵子树"
