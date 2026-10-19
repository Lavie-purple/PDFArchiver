"""p21 · 轮十四 C（**ISSUES I78** 乙 · 智能集合保存筛选）的坏法注入证伪。

AGENTS.md 的规矩：「每写完一条断言，先用能骗过它的坏法真注入一次；不会变红的断言直接删」。
本文件覆盖 `tests/integration/test_saved_search_ui.py` 的**全部 23 个测试函数**（收集 26 条，
参数化那条占两个宽度档）与 `tests/guards/test_insert_covers_notnull.py` 那一条，共 24 个坏法 ——
每个坏法都是一个"等价但错"的生产代码改动，要求它**必然**把自己该杀的那条打红。

跑法：
    .venv/Scripts/python.exe tests/probes/p21_saved_search_injection.py            # 全跑
    .venv/Scripts/python.exe tests/probes/p21_saved_search_injection.py b1 c1 h1    # 只跑指定 id

三件事先说清，免得结论被误读：
1. **不碰工作区**。复制式 runner 直接复用 `p9_reverse_injection` 的那一套（把 `src` + `tests`
   + 入口文件抄进系统临时目录再改），产品代码一次都没被改写过 —— 本轮工作区是脏的（未提交的
   实现 + 测试），所以**不能用 p15 那种原地改源码再还原的 runner**，它会先要求工作区干净。
2. **复制的是工作区当前内容**，不是 git 里的版本 —— 注入的对象就是这一轮刚写的那批代码。
3. 先跑一遍**未注入**的基线。没有这一步，"注入后变红"可能只是复制环境跑不起来，那不算证据。

编号用的是断言自己的字母（线框 §I78-yi 的硬断言 (a)–(e) / k=chips 接线 / s=S8 那栏 /
p=两张表的漂移 / g=分档算术 / h=库结构守卫），不用连续序号 —— 序号会和 ISSUES 的 `I<n>` 撞名，
那正是 **ISSUES I35** 清掉过的那类歧义。

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

CRIT = "tests/integration/test_saved_search_ui.py::"
GUARD = "tests/guards/test_insert_covers_notnull.py::test_INSERT写全必填列"

SERVICE = "src/pdfarchiver/search/service.py"
COLLSVC = "src/pdfarchiver/services/collection_service.py"
REPO = "src/pdfarchiver/db/repositories/collections.py"
BAR = "src/pdfarchiver/ui/collection_bar.py"
LIB = "src/pdfarchiver/ui/pages/library_page.py"
CATS = "src/pdfarchiver/ui/pages/categories_page.py"
SHELL = "src/pdfarchiver/ui/main_window.py"

CASES: list[Case] = [
    # —— 硬断言 (b)：一份条件只有一种表示法，往返必须 `==` ——————————————————
    Case("b1", "`from_query` 不把 id 串还原成 tuple（存进去 list、读回来还是 list）",
         CRIT + "test_条件经过query_json往返还是同一条",
         [Edit(SERVICE, "                fields[name] = tuple(int(item) for item in value)",
               "                fields[name] = value              # injected")]),
    Case("b2", "`from_query` 咽下不认识的键（屏幕上写着筛过，库里一条 WHERE 都没加）",
         CRIT + "test_认不出的键当场拒",
         [Edit(SERVICE, "        unknown = sorted(set(query) - set(QUERY_FIELDS))",
               "        unknown = []                          # injected")]),
    Case("b3", "`to_query` 顺手把「这次怎么看」也存进集合",
         CRIT + "test_集合只存筛选条件不存这次怎么看",
         [Edit(SERVICE, "        query: dict[str, object] = {}\n        for name in QUERY_FIELDS:",
               '        query: dict[str, object] = {}\n        for name in (*QUERY_FIELDS, "sort"):')]),

    # —— 硬断言 (a)：存 → 关 → 开，条件与结果还是同一份 ————————————————
    Case("a1", "回放时灌的是屏幕上现成那份，不是那条集合存的那份",
         CRIT + "test_存一条集合_关开一次_条件与结果仍是同一份",
         [Edit(LIB, "        self.filter_bar.apply_query(entry.query, saved=entry)",
               "        self.filter_bar.apply_query(self._query, saved=entry)    # injected")]),
    Case("n1", "存的是屏幕上那份稀疏 dict（不规范化）",
         CRIT + "test_存集合存的是规范化那一份而不是屏幕上的写法",
         [Edit(COLLSVC, "        return Criteria.from_query(query).to_query()",
               "        return dict(query)                    # injected")]),

    # —— 硬断言 (d)：集合上那个数 = 回放后表格的行数 ————————————————
    Case("d1", "命中数改成数全库（与回放那条 WHERE 脱钩）",
         CRIT + "test_集合那一行的命中数等于回放后表格的行数",
         [Edit(COLLSVC,
               "                hits=self.documents.count_matching(criteria.browse_page().doc_filter()),",
               "                hits=self.documents.count(),      # injected")]),

    # —— 硬断言 (c)：删一条集合不许动文档（SPEC 3.3.5） ——————————————————
    Case("c1", "删集合顺手把归入关联一起清了（集合被当成物化视图）",
         CRIT + "test_删除集合只删那一行查询不动文档",
         [Edit(REPO, '            conn.execute("DELETE FROM collections WHERE id=?", (collection_id,))',
               '            conn.execute("DELETE FROM collections WHERE id=?", (collection_id,))\n'
               '            conn.execute("DELETE FROM document_categories")          # injected')]),

    # —— 硬断言 (e)：`update_query` 在产品里有调用点 ————————————————
    Case("e1", "「覆盖此集合」做成另存一条（`update_query` 回到零调用点）",
         CRIT + "test_update_query在产品里有调用点且调用方写死 "
         + CRIT + "test_覆盖此集合改写存着的那份而不新增一行",
         [Edit(COLLSVC,
               "        return self.collections.update_query(collection_id, self._normalized(query))",
               "        return self.collections.add(str(collection_id), self._normalized(query))")]),
    Case("e2", "就地改一枚 chip 就把集合身份清掉（本轮现测：覆盖按钮永远点不亮）",
         CRIT + "test_覆盖此集合改写存着的那份而不新增一行",
         [Edit(BAR, "        if saved is not None:\n            self._saved = saved",
               "        self._saved = saved                   # injected")]),

    # —— chips 的接线 ——————————————————————————————————————————————
    Case("k1", "点 × 但那条条件没走（摘不掉）",
         CRIT + "test_去掉一枚chip是去掉那个键而不是置成默认值",
         [Edit(BAR, "        else:\n            self._without(query, cond.field)\n"
                    "        self.apply_query(query)",
               "        else:\n            pass                                    # injected\n"
               "        self.apply_query(query)")]),
    Case("k2", "没有标签也让「标签要全部命中」上屏（宣称它会做它不做的事）",
         CRIT + "test_标签没了全部命中那条也跟着走",
         [Edit(BAR, '            if cond.field == "tag_match_all" and not self._query.get("tag_ids"):\n'
                    "                continue     # 没有标签时它不改任何一行 SQL，见模块 docstring",
                    "            if False:                                        # injected\n"
                    "                continue")]),
    Case("k3", "一条条件都没有也允许存",
         CRIT + "test_没有条件时存不动界面也说为什么",
         [Edit(BAR, "        self.save_btn.setEnabled(bool(chips))",
               "        self.save_btn.setEnabled(True)        # injected")]),
    Case("k4", "旧版那种空条件集合上屏假装自己筛过什么",
         CRIT + "test_旧版那种空条件集合上屏写着它筛过什么",
         [Edit(COLLSVC, "        if not self.usable:", "        if False:               # injected")]),
    Case("k5", "关键词搜索不看屏幕上那排 chips（走全库）",
         CRIT + "test_关键词搜索就在当前那排chips里搜",
         [Edit(LIB, "        result = self.ctx.search.search_in(self._query, query, limit=100)",
               "        result = self.ctx.search.search_in({}, query, limit=100)   # injected")]),
    Case("k6", "语义通道不说自己不看那排条件",
         CRIT + "test_语义搜索明说自己不看这排条件",
         [Edit(LIB,
               '        note = ("｜⚠ 语义通道不看上面那排筛选条件" if self._query else "")',
               '        note = ""                             # injected')]),

    # —— S8 那一栏 ————————————————————————————————————————————————
    Case("s1", "双击一行只灌条件、不切屏（看着像过去了其实没过去）",
         CRIT + "test_双击一行S8把外壳切到S1并灌回条件",
         [Edit(SHELL, '        self._select_by_page_id("library")\n'
                      '        self._pages["library"].apply_saved(entry)',
                      '        pass                                            # injected\n'
                      '        self._pages["library"].apply_saved(entry)')]),
    Case("s2", "S8 那一行只写上集合名，命中数不上屏",
         CRIT + "test_S8那一行读的是行上那条集合而不是第几行",
         [Edit(CATS, "            item = QtWidgets.QListWidgetItem(entry.label())",
               "            item = QtWidgets.QListWidgetItem(entry.name)   # injected")]),
    Case("s3", "「复制为新」只复制名字不复制条件",
         CRIT + "test_改名与复制为新走的是服务层",
         [Edit(CATS, "            self.ctx.collection.copy_as_new(entry.id, new_name.strip())",
               "            self.ctx.collection.save(new_name.strip(), {})  # injected")]),
    Case("s4", "「添加条件」菜单在构造时填一次（此后条件表变了也不重取）",
         CRIT + "test_添加条件菜单每展开一次才重取条件表",
         [Edit(BAR, "        menu.aboutToShow.connect(lambda: _fill(menu))",
               "        _fill(menu)                           # injected")]),

    # —— 两张表与后端口径不许漂（界面无从 import，只能钉读数） ——————————————
    Case("p1", "条件表少一枚（后端还能存，界面加不出来）",
         CRIT + "test_筛选条这张表与集合能存的字段同一批",
         [Edit(BAR, '    Condition("min_size_bytes", "大小至少…", "大小", "≥", "size"),\n', "")]),
    Case("p2", "索引状态的说法少一个（库里可搜的状态有一个没人认）",
         CRIT + "test_索引状态那几句说法与库里可搜的状态同一批",
         [Edit(BAR, '    "stale": "要重索引",\n', "")]),
    Case("p3", "有一枚条件的取值方式没人认（`_ask` 落到别分支，问出来的是别的东西）",
         CRIT + "test_条件表每一枚都上得了屏也问得出值",
         [Edit(BAR, '    Condition("min_pages", "页数至少…", "页数", "≥", "pages"),',
               '    Condition("min_pages", "页数至少…", "页数", "≥", "pagez"),   # injected')]),

    # —— 分档算术（为什么 chips 与那四颗按钮是两行而不是一行） ——————————————
    Case("g1", "把「添加条件」撑成固定宽（并回一行时 chips 被挤没的形状）",
         CRIT + "test_筛选条拆两行的算术在两个宽度档都成立",
         [Edit(BAR, "        self.add_btn.setMenu(self._condition_menu())",
               "        self.add_btn.setMenu(self._condition_menu())\n"
               "        self.add_btn.setMinimumWidth(900)     # injected")]),

    # —— 库结构守卫 ————————————————————————————————————————————————
    Case("h1", "`collections` 的 INSERT 漏写 `updated_at`（本轮现测：这一插每次都失败）",
         GUARD,
         [Edit(REPO,
               '                "INSERT INTO collections(name, query_json, note, created_at, updated_at)"\n'
               '                " VALUES(?,?,?,?,?)",\n'
               "                (name, query_json, note, ts, ts))",
               '                "INSERT INTO collections(name, query_json, note, created_at)"\n'
               '                " VALUES(?,?,?,?)",\n'
               "                (name, query_json, note, ts))")]),
]


def _label(case: Case) -> str:
    return f"p21 注入 {case.inject}｜{case.坏法}"


def main() -> int:
    wanted = [a for a in sys.argv[1:] if not a.startswith("-")]
    cases = [c for c in CASES if not wanted or c.inject in wanted]
    if not cases:
        print(f"没有这些编号：{wanted}（可选：{[c.inject for c in CASES]}）")
        return 2

    ws = Path(tempfile.mkdtemp(prefix="p21_injection_"))
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
        one = Path(tempfile.mkdtemp(prefix="p21_case_"))
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
            print(f"         -> {' + '.join(t.split('::')[-1] for t in case.node.split())}｜{detail}")
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
