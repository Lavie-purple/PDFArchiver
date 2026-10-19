"""p22 · 轮十四 D（**ISSUES I78** 丙 · 分类清单导出）的坏法注入证伪。

AGENTS.md 的规矩：「每写完一条断言，先用能骗过它的坏法真注入一次；不会变红的断言直接删」。
本文件覆盖 `tests/integration/test_category_export_ui.py` 的**全部 31 个测试函数**，
一条不落 —— 每个坏法都是一个"等价但错"的生产代码改动，要求它**必然**把自己该杀的那条打红。
轮十五 丙 起「已归档」那一列也在这张网里（k1–k8，其中 k4/k5 分别打 T3 的两半）。

跑法：
    .venv/Scripts/python.exe tests/probes/p22_category_export_injection.py             # 全跑
    .venv/Scripts/python.exe tests/probes/p22_category_export_injection.py c2 d1 w1     # 只跑指定 id

三件事先说清，免得结论被误读：
1. **不碰工作区**。复制式 runner 直接复用 `p9_reverse_injection` 的那一套（把 `src` + `tests`
   + 入口文件抄进系统临时目录再改），产品代码一次都没被改写过 —— 本轮工作区是脏的
   （未提交的服务层 + 弹层 + 测试），所以**不能用 p15 那种原地改源码再还原的 runner**，
   它会先要求工作区干净。
2. **复制的是工作区当前内容**，不是 git 里的版本 —— 注入的对象就是这一轮刚写的那批代码。
3. 先跑一遍**未注入**的基线。没有这一步，"注入后变红"可能只是复制环境跑不起来，那不算证据。

编号用的是断言自己的字母（线框 §I78-bing 的硬断言 (a)–(e) / u=口径来源 / n=落盘纪律 /
r=回执 / f=格式与空值 / g=门 / w=接线 / k=已归档口径），不用连续序号 —— 序号会和
ISSUES 的 `I<n>` 撞名，那正是 **ISSUES I35** 清掉过的那类歧义。

runner 的判定口径与 **ISSUES I55** 一致：`rc≠0 且 failed≥1 且 errored==0`；锚点命中不是恰好一次
判「注入失效」（那种情况下断言根本没被改到，结论不作数）。
"""
from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from p9_reverse_injection import Case, Edit, _apply, _copy_repo, _run, _verdicts   # noqa: E402

CRIT = "tests/integration/test_category_export_ui.py::"

SVC = "src/pdfarchiver/services/export_service.py"
OPS = "src/pdfarchiver/db/repositories/operations.py"
BOX = "src/pdfarchiver/ui/export_dialog.py"
CATS = "src/pdfarchiver/ui/pages/categories_page.py"
BOOT = "src/pdfarchiver/services/bootstrap.py"

CASES: list[Case] = [
    # —— 口径来源：弹层不许抄一份 —— 列标签 / 默认档 / 列顺序 ——————————————
    Case("u1", "界面抄一份格式标签并把 Markdown 那档简写（服务层叫「Markdown 表」）",
         CRIT + "test_弹层上的列与格式逐字来自服务层那张表",
         [Edit(BOX, "            radio = QtWidgets.QRadioButton(label)",
               "            radio = QtWidgets.QRadioButton(label.replace(\"Markdown 表\", \"Markdown\"))")]),
    Case("u2", "界面自己加一档默认勾选（默认列集变成界面说了算）",
         CRIT + "test_默认勾的就是服务层那五列",
         [Edit(BOX, "            box.setChecked(column.key in DEFAULT_COLUMNS)",
               "            box.setChecked(column.key in DEFAULT_COLUMNS or column.key == \"text_rate\")")]),
    Case("u3", "勾选的列按遍历的反方向回（列顺序由鼠标轨迹而不是由那张表定）",
         CRIT + "test_产物列顺序由表定而不是由点击顺序定",
         [Edit(BOX, "        return tuple(c.key for c in EXPORT_COLUMNS if self.column_checks[c.key].isChecked())",
               "        return tuple(c.key for c in reversed(EXPORT_COLUMNS) if self.column_checks[c.key].isChecked())")]),

    # —— 硬断言 (a)：屏幕上那个数 = 产物里的行数 ————————————————————
    Case("a1", "屏幕上那个份数改数全库（与导出那条 WHERE 脱钩）",
         CRIT + "test_屏幕上那个份数就是产物里的行数",
         [Edit(SVC, "        return self.documents.count_matching(\n"
                   "            self.filter_for(category_id, include_children=include_children))",
               "        return self.documents.count()   # 注入：与行集脱钩的第二个数")]),
    Case("a2", "「含子分类」只改标签不改谓词（界面写着只这一枝，产物还是整枝）",
         CRIT + "test_含子分类切下去屏幕上那句与产物一起跟着变",
         [Edit(BOX, "            rows = self.ctx.export.count(self.category_id, include_children=self.include_children())",
               "            rows = self.ctx.export.count(self.category_id, include_children=True)")]),
    Case("a3", "空枝照样落一份只有表头的文件（看起来成功的产物）",
         CRIT + "test_导出被拒时弹的是失败框而目录里什么都没落",
         [Edit(SVC, "        if total == 0:", "        if False:")]),

    # —— 硬断言 (b)：未勾的列不出现 ——————————————————————————————————
    Case("b1", "渲染时按全表出列，未勾的留空（界面写着没勾，产物里占一列）",
         CRIT + "test_未勾的列不出现在表头与json键里",
         [Edit(SVC, "    writer.writerow([s.label for s in specs])\n"
                   "    for doc in rows:\n"
                   "        writer.writerow([s.value(doc, batch) for s in specs])",
               "    writer.writerow([c.label for c in EXPORT_COLUMNS])\n"
               "    for doc in rows:\n"
               "        writer.writerow([c.value(doc, batch) if c in specs else \"\" for c in EXPORT_COLUMNS])")]),

    # —— 硬断言 (c)：本机绝对路径 ——————————————————————————————————
    Case("c1", "「文件名」那一列写的是整条路径（列名与取值不同源，盘符漏进产物）",
         CRIT + "test_默认产物里搜不到盘符",
         [Edit(SVC, "    Column(\"name\", \"文件名\", lambda d, _: d.name),",
               "    Column(\"name\", \"文件名\", lambda d, _: d.path),")]),
    Case("c2", "界面以为自己问过了（确认框永远不弹，隐私列一勾就写）",
         CRIT + "test_勾本机绝对路径要先确认一次而确认后产物里才有路径",
         [Edit(BOX, "        if box.property(\"confirmed\"):\n            return",
               "        if True:                    # 注入：确认位当成已经问过\n            return")]),
    Case("c3", "答「否」只清确认位、复选框留着勾（屏幕上写着勾了）",
         CRIT + "test_确认时答否就回落到未勾而产物里没有那一列",
         [Edit(BOX, "        box.setChecked(False)", "        pass   # 注入：不复位复选框")]),

    # —— 硬断言 (d)：只读 ——————————————————————————————————————————
    Case("d1", "导出时顺手把这一枝的文档标成「这次扫描见过」（只读变成写）",
         CRIT + "test_只读导出前后五张表逐行不变",
         [Edit(SVC, "        target = self._target(dest_dir, category.name_path, ext)",
               "        self.documents.mark_scanned_many(d.id for d in docs)   # 注入：顺手记一笔\n"
               "        target = self._target(dest_dir, category.name_path, ext)")]),

    # —— 硬断言 (e)：同名两枝不并 ——————————————————————————————————
    Case("e1", "产物文件名只用末段分类名（「财务/合同」与「技术/合同」撞成同一份）",
         CRIT + "test_同名两枝各导各的而产物文件名不撞",
         [Edit(SVC, "        stem = \"_\".join(sanitize_component(part) for part in name_path.split(\"/\") if part)",
               "        stem = sanitize_component(name_path.split(\"/\")[-1])   # 注入：丢掉层级")]),

    # —— 落盘纪律：不覆盖、不留半截 ————————————————————————————————
    Case("n1", "同名产物静默盖掉（上午那份清单没了，屏幕上只写「已导出」）",
         CRIT + "test_同名产物第二次导出被拒而第一份原样还在",
         [Edit(SVC, "    if target.exists():", "    if False:")]),
    Case("n2", "写盘中途失败不清 `.part`（下次在同一目录看见半截怪后缀的文件）",
         CRIT + "test_写盘中途失败时不留半截产物",
         [Edit(SVC, "    finally:\n        if part.exists():\n            part.unlink(missing_ok=True)",
               "    finally:\n        pass   # 注入：临时件留在目录里")]),

    # —— 回执：格式化只有一个出口（ISSUES I60）——————————————————————
    Case("r1", "界面上自己拼一句回执（列数与写到哪儿都不说了）",
         CRIT + "test_屏幕上那句逐字就是后端回执",
         [Edit(BOX, "        QtWidgets.QMessageBox.information(self, \"导出完成\", receipt.describe())",
               "        QtWidgets.QMessageBox.information(self, \"导出完成\", f\"已导出 {receipt.rows} 行\")")]),

    # —— 三种格式与空值口径 ————————————————————————————————————————
    Case("f1", "Markdown 档的后缀写成 csv（选一种格式得到另一种文件）",
         CRIT + "test_三种格式各写出对应后缀与内容",
         [Edit(SVC, "    (\"markdown\", \"Markdown 表\", \"md\"),",
               "    (\"markdown\", \"Markdown 表\", \"csv\"),")]),
    Case("f2", "三种格式一律带 BOM（JSON/MD 的读者读到 \\ufeff）",
         CRIT + "test_csv带bom而md与json不带",
         [Edit(SVC, "        encoding = \"utf-8-sig\" if target.suffix == \".csv\" else \"utf-8\"",
               "        encoding = \"utf-8-sig\"   # 注入：一律带 BOM")]),
    Case("f3", "Markdown 不转义竖线（一行被切成更多列，整张表错位）",
         CRIT + "test_md转义竖线而列数不变",
         [Edit(SVC, "        return str(v).replace(\"|\", \"\\\\|\")   # 表格里漏转义的竖线会把一行切成两列",
               "        return str(v)          # 注入：不转义")]),
    Case("f4", "空值写成占位文字「无」（凭空编造一个看起来有内容的值）",
         CRIT + "test_没有页数的文档写成空单元格而不是none字面量",
         [Edit(SVC, "    return \"\" if value is None else value",
               "    return \"无\" if value is None else value   # 注入：占位文字")]),
    Case("f5", "勾了标签列但标签取不回来（界面写着有这一列，产物里整列空）",
         CRIT + "test_勾上标签列之后每行是那几个标签",
         [Edit(SVC, "            out.update(self.catalog.tags_by_doc_ids(list(doc_ids[start:start + MAX_BULK_IDS])))",
               "            pass   # 注入：一批都不取")]),

    # —— 门：没有目录 / 没有列就不许点得动（ISSUES I74 那一族）——————
    Case("g1", "导出按钮不看保存路径（预设一个「看起来对」的目录）",
         CRIT + "test_没选目录时导出是死的而选了才亮起来",
         [Edit(BOX, "        self.export_btn.setEnabled(bool(self.dest_input.text().strip())\n"
                   "                                   and bool(self.selected_columns()))",
               "        self.export_btn.setEnabled(bool(self.selected_columns()))   # 注入：不看目录")]),
    Case("g2", "导出按钮不看勾了几列（一列都没勾也发得出去）",
         CRIT + "test_一列都不勾时导出也是死的",
         [Edit(BOX, "        self.export_btn.setEnabled(bool(self.dest_input.text().strip())\n"
                   "                                   and bool(self.selected_columns()))",
               "        self.export_btn.setEnabled(bool(self.dest_input.text().strip()))   # 注入：不看列")]),
    Case("g3", "「选择…」选了目录但不填回输入框（点了没反应，人以为按钮坏了）",
         CRIT + "test_选择按钮把目录填回输入框",
         [Edit(BOX, "        if chosen:\n            self.dest_input.setText(chosen)",
               "        if chosen:\n            pass   # 注入：不填回")]),

    # —— 接线 ————————————————————————————————————————————————————
    Case("w1", "菜单那一项接了个空函数（未接线的按钮，ISSUES I79 那一类）",
         CRIT + "test_菜单上那一项按下去真的把弹层开起来",
         [Edit(CATS, "            (\"导出此分类清单…\", self.export_category),",
               "            (\"导出此分类清单…\", lambda: None),   # 注入：空动作")]),
    Case("w2", "装配时不接 `export` 服务字段（弹层构造得出，一按就断）",
         CRIT + "test_导出链路每一环在产品侧各有调用点了",
         [Edit(BOOT, "    export = ExportService(documents, catalog, operations)",
               "    export = None   # 注入：这一环没接上")]),

    # —— 已归档唯一口径（ISSUES I78 丙 · 轮十五 丙）——————————————————
    Case("k1", "撤销批次也当正向归档（退回原处的文件读成已归档）",
         CRIT + "test_撤销之后这一列读否而归档落点那行还在台账里",
         [Edit(OPS, "WHERE x.state='done' AND y.kind='archive' AND x.dst_path IS NOT NULL",
               "WHERE x.state='done' AND x.dst_path IS NOT NULL   # 注入：撤销也算")]),
    Case("k2", "只认 move、不认跨盘那一档 copy（跨盘归档过的全报没归档）",
         CRIT + "test_跨盘归档的copy条目也算已归档",
         [Edit(OPS, "WHERE x.state='done' AND y.kind='archive' AND x.dst_path IS NOT NULL",
               "WHERE x.state='done' AND y.kind='archive' AND x.kind='move'"
               " AND x.dst_path IS NOT NULL")]),
    Case("k3", "失败 / 跳过的搬动也算已归档（文件根本没落到 dst_path）",
         CRIT + "test_没跑完的搬动不算已归档",
         [Edit(OPS, "WHERE x.state='done' AND y.kind='archive' AND x.dst_path IS NOT NULL",
               "WHERE x.state IN ('done','failed','skipped') AND y.kind='archive'"
               " AND x.dst_path IS NOT NULL")]),
    Case("k4", "「最后一笔」取成第一笔（换模板重跑之后读的还是旧落点）",
         CRIT + "test_已归档列读的是最后一笔归档落点",
         [Edit(OPS, "  SELECT max(x.id) FROM operation_items AS x",
               "  SELECT min(x.id) FROM operation_items AS x   # 注入：取第一笔")]),
    Case("k5", "导出层根本没去取归档落点（整列恒读否）",
         CRIT + "test_已归档列读的是最后一笔归档落点",
         [Edit(SVC, "        out: dict[int, str] = {}\n"
                   "        for start in range(0, len(doc_ids), MAX_BULK_IDS):\n"
                   "            out.update(self.ops.last_archive_destinations(\n"
                   "                list(doc_ids[start:start + MAX_BULK_IDS])))\n"
                   "        return out",
               "        return {}   # 注入：一批都不取")]),
    Case("k6", "默认列集偷偷多勾「已归档」（默认导出白扫一遍台账）",
         CRIT + "test_默认列集仍是线框勾的那五列",
         [Edit(SVC, "DEFAULT_COLUMNS: tuple[str, ...] = (\"name\", \"page_count\", \"size_bytes\","
                    " \"sha256_12\", \"mtime\")",
               "DEFAULT_COLUMNS: tuple[str, ...] = (\"name\", \"page_count\", \"size_bytes\","
               " \"sha256_12\", \"mtime\", \"archived\")")]),
    Case("k7", "表头只写「已归档」不带口径名（读者以为它是文件属性）",
         CRIT + "test_已归档列的表头带着口径名",
         [Edit(SVC, "ARCHIVED_LABEL = \"已归档（按最后一笔归档落点）\"",
               "ARCHIVED_LABEL = \"已归档\"   # 注入：口径名掉了")]),
    Case("k8", "读台账时顺手收掉一个批次（只读导出写一笔业务表）",
         CRIT + "test_只读导出前后五张表逐行不变",
         [Edit(SVC, "        out: dict[int, str] = {}",
               "        self.ops.finish_operation(1)   # 注入：读的时候写一笔\n"
               "        out: dict[int, str] = {}")]),
]


def _label(case: Case) -> str:
    return f"p22 注入 {case.inject}｜{case.坏法}"


def main() -> int:
    wanted = [a for a in sys.argv[1:] if not a.startswith("-")]
    cases = [c for c in CASES if not wanted or c.inject in wanted]
    if not cases:
        print(f"没有这些编号：{wanted}（可选：{[c.inject for c in CASES]}）")
        return 2

    ws = Path(tempfile.mkdtemp(prefix="p22_injection_"))
    try:
        _copy_repo(ws)
        targets = sorted({t for c in cases for t in c.node.split()})
        rc, out = _run(ws, targets)
        failed, errored, passed = _verdicts(out)
        print(f"基线（未注入）：{passed} 条通过 / {failed} 失败 / {errored} 错误，exit={rc}")
        if rc != 0:
            print(out[-3000:])
            print("VERDICT: RED（基线就没过，后面的注入结论全部不作数）")
            return 1
    finally:
        shutil.rmtree(ws, ignore_errors=True)

    results: list[tuple[Case, bool, str]] = []
    for case in cases:
        one = Path(tempfile.mkdtemp(prefix="p22_case_"))
        try:
            _copy_repo(one)
            _apply(one, case)
            rc, out = _run(one, case.node.split())
            failed, errored, passed = _verdicts(out)
            caught = rc != 0 and failed >= 1 and errored == 0
            detail = (f"failed={failed} error={errored} passed={passed}" if caught
                      else out.splitlines()[-3] if out.strip() else "没有输出")
            results.append((case, caught, detail))
            print(f"  {'RED  ' if caught else 'GREEN'}  {_label(case)}")
            print(f"         -> {case.node.split('::')[-1]}｜{detail}")
        except RuntimeError as exc:                     # 锚点命中次数不对 = 注入失效
            results.append((case, False, str(exc)))
            print(f"  失效    {_label(case)}\n         -> {exc}")
        finally:
            shutil.rmtree(one, ignore_errors=True)

    missed = [r for r in results if not r[1]]
    print(f"\n抓到 {len(results) - len(missed)}/{len(results)} 条坏法")
    for case, _, detail in missed:
        print(f"  未抓到：{_label(case)} —— {detail}\n"
              f"         对应断言是摆设，按 AGENTS.md 必须删或重写")
    print("VERDICT: " + ("ALL GREEN" if not missed else "RED"))
    return 0 if not missed else 1


if __name__ == "__main__":
    raise SystemExit(main())
