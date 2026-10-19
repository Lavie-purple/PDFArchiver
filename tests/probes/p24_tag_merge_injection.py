"""p24 · 轮十五 甲（`merge_tags` 的界面入口）的坏法注入证伪。

AGENTS.md 的规矩：「每写完一条断言，先用能骗过它的坏法真注入一次；不会变红的断言直接删」。
本文件覆盖 `tests/integration/test_tag_merge_ui.py` 的**全部 16 个测试函数**，一条不落 ——
每个坏法都是一个"等价但错"的生产代码改动，要求它**必然**把自己该杀的那条打红。

16 条断言配了 **17** 个坏法：`test_删除作用在选中的那一个标签而它的关联一起走` 有两条，
理由写在 a5 上面那段注释里（只撤仓储层那条 `DELETE` 实测**不会红** —— 表结构在兜）。

跑法：
    .venv/Scripts/python.exe tests/probes/p24_tag_merge_injection.py            # 全跑
    .venv/Scripts/python.exe tests/probes/p24_tag_merge_injection.py a1 c3      # 只跑指定 id

三件事先说清，免得结论被误读：
1. **不碰工作区**。复制式 runner 复用 `p9_reverse_injection` 的那一套（把 `src` + `tests`
   + 入口文件抄进系统临时目录再改）。本轮工作区是脏的（未提交的仓储层 + 弹层 + 测试），
   所以**不能用 p15 那种原地改源码再还原的 runner** —— 它会先要求工作区干净。
2. **复制的是工作区当前内容**，不是 git 里的版本 —— 注入的对象就是这一轮刚写的那批代码。
3. 先跑一遍**未注入**的基线。没有这一步，"注入后变红"可能只是复制环境跑不起来，那不算证据。

编号用断言自己的字母（模块 docstring 的四组：a=数据 / b=拒 / c=入口 / d=同源，外加 w=接线），
不用连续序号 —— 序号会和 ISSUES 的 `I<n>` 撞名，那是 **ISSUES I35** 清掉过的那类歧义。

两处刻意的设计约束，写在这里免得下一轮误改：
- **坏法不许依赖"槽函数里抛异常"**。`merge_tag` 是 Qt 槽，由 C++ 侧调用，里面冒出来的异常
  可能被吞掉而只打一句 stderr —— 那注入后测试照样绿，结论就成了假绿。所以 c2 的坏法是
  "读不到对象时返回一个假的 id"而不是"让它 `None.data()` 炸"。
- **d1 的坏法不能用 `len(list_tags())`**。那条测试的库里刻意摆成"三个标签、两份文档"，
  合并后剩两个标签 —— `len()` 数出来正好也是 2，坏法能被断言满足就不是坏法。
  用 `tag_list.count()`（重查之前 = 3）才是那条断言唯一量得出的错。

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

CRIT = "tests/integration/test_tag_merge_ui.py::"
REPO = "src/pdfarchiver/db/repositories/catalog.py"
PAGE = "src/pdfarchiver/ui/pages/categories_page.py"

CASES: list[Case] = [
    # —— (a) 数据：并过去的是关联，不是把源删掉了事 ——————————————
    Case("a1", "两条语句顺序反了：先删源关联再改指目标（两边都有的那份关联被删没）",
         CRIT + "test_源名下的关联改指目标而源标签整行消失",
         [Edit(REPO, '            conn.execute("UPDATE OR IGNORE document_tags SET tag_id=? WHERE tag_id=?",\n'
                    '                         (target_id, source_id))\n'
                    '            conn.execute("DELETE FROM document_tags WHERE tag_id=?", (source_id,))',
               '            conn.execute("DELETE FROM document_tags WHERE tag_id=?", (source_id,))\n'
               '            conn.execute("UPDATE OR IGNORE document_tags SET tag_id=? WHERE tag_id=?",\n'
               '                         (target_id, source_id))')]),
    Case("a2", "行上挂的是第几行而不是它自己那个标签的 id（行号当句柄）",
         CRIT + "test_每一行挂的是它自己那个标签的id",
         [Edit(PAGE, "            item.setData(QtCore.Qt.ItemDataRole.UserRole, tag.id)",
               "            item.setData(QtCore.Qt.ItemDataRole.UserRole, self.tag_list.count())"
               "   # 注入：行号当句柄")]),
    Case("a3", "改名写死列表第一条（改的是**别的**标签）",
         CRIT + "test_改名作用在选中的那一个标签上",
         [Edit(PAGE, "        tag_id, _ = picked",
               "        tag_id, _ = self.ctx.catalog.list_tags()[0].id, \"\"   # 注入：写死第一条")]),
    Case("a4", "删除读的是列表第一条而不是选中的那一个（删错标签 = 不可逆的写）",
         CRIT + "test_删除作用在选中的那一个标签而它的关联一起走",
         [Edit(PAGE, "        tag_id, tag_name = picked",
               "        tag_id, tag_name = self.ctx.catalog.list_tags()[0].id, \"\""
               "   # 注入：删第一条，不是选中的那个")]),
    # 单独撤掉仓储层那条 `DELETE FROM document_tags` **不会红**：`document_tags.tag_id` 上写着
    # `ON DELETE CASCADE`（0001_initial.py:101），是表结构在兜这一半。所以 a5 两处一起撤 ——
    # 那条断言钉的是"关联一定被带走"这个**行为**，不是某一条语句由谁实现。
    Case("a5", "仓储层不删关联 + 表结构也不再级联（标签没了，文档还挂着它）",
         CRIT + "test_删除作用在选中的那一个标签而它的关联一起走",
         [Edit(REPO, '            conn.execute("DELETE FROM document_tags WHERE tag_id=?", (tag_id,))\n'
                    '            conn.execute("DELETE FROM tags WHERE id=?", (tag_id,))',
               '            conn.execute("DELETE FROM tags WHERE id=?", (tag_id,))'
               '   # 注入：关联不带走'),
          Edit("src/pdfarchiver/db/migrations/0001_initial.py",
               "  tag_id     INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,",
               "  tag_id     INTEGER NOT NULL REFERENCES tags(id),")]),

    # —— (b) 拒：三条前置检查 + 拒的原文上屏 ——————————————————
    Case("b1", "把「并进自己」那条拒撤掉（就是修前那个真 bug：全部关联连同标签一起没）",
         CRIT + "test_并进自己当场被拒而关联一条都没少",
         [Edit(REPO, '        if source_id == target_id:\n'
                    '            raise DatabaseError(f"不能把「{source[\'name\']}」并进它自己", ValueError("自我合并前置检查"))',
               '        if source_id == target_id:\n'
               '            pass   # 注入：这条拒撤掉')]),
    Case("b2", "源不存在时不拒，继续往下写（屏幕上那句「已并过去」照样说）",
         CRIT + "test_源或目标不存在都被拒而不是一句已并过去",
         [Edit(REPO, '        if source is None:\n'
                    '            raise DatabaseError(f"源标签不存在：{source_id}", ValueError("外键前置检查"))',
               '        if source is None:\n'
               '            pass   # 注入：源不存在也照样往下走')]),
    Case("b3", "份数不数了，直接回 0（那句「移动 N 份」从此与库无关）",
         CRIT + "test_返回的份数就是源名下实际的文档数",
         [Edit(REPO, '            conn.execute("DELETE FROM tags WHERE id=?", (source_id,))\n'
                    '        return moved',
               '            conn.execute("DELETE FROM tags WHERE id=?", (source_id,))\n'
               '        return 0   # 注入：不数源名下有几份')]),
    Case("b4", "界面上把异常原文换成一句「操作失败」（拒了但没话可抄）",
         CRIT + "test_仓储层拒了而屏幕上留的是原文",
         [Edit(PAGE, '            QtWidgets.QMessageBox.critical(self, "合并标签失败", str(exc))',
               '            QtWidgets.QMessageBox.critical(self, "合并标签失败", "操作失败")'
               '   # 注入：原文咽掉')]),

    # —— (c) 入口：按钮在不在、没有对象时动不动手 ——————————————
    Case("c1", "造了按钮忘了摆上这一排（名字文案全对，屏幕上没有这颗）",
         CRIT + "test_中栏那排是四颗按钮而并入是第三颗",
         [Edit(PAGE, "        tag_btns.addWidget(self.merge_tag_btn)",
               "        pass   # 注入：忘了 addWidget")]),
    Case("c2", "读不到选中项也照样往下走（拿 0 当 id 去问候选）",
         CRIT + "test_没有选中标签时点并入只有一句提示",
         [Edit(PAGE, "        item = self.tag_list.currentItem()\n"
                    "        if item is None:\n"
                    '            QtWidgets.QMessageBox.information(self, action, f"请先选择一个标签再{action}")\n'
                    "            return None",
               "        item = self.tag_list.currentItem()\n"
               "        if item is None:\n"
               '            return 0, ""   # 注入：读不到对象也往下走')]),
    Case("c3", "候选把自己也摆上（「并进它自己」这一项真的可选得到）",
         CRIT + "test_候选清单里没有自己",
         [Edit(PAGE, "        choices = [(t.id, t.name) for t in self.ctx.catalog.list_tags()"
                    " if t.id != exclude_id]",
               "        choices = [(t.id, t.name) for t in self.ctx.catalog.list_tags()]"
               "   # 注入：自己也上候选")]),
    Case("c4", "取消候选对话框当成「也挑了第一个」（按了取消还是写了库）",
         CRIT + "test_取消候选对话框一行都不写",
         [Edit(PAGE, "        name, ok = QtWidgets.QInputDialog.getItem(self, title, prompt, names, 0, False)\n"
                    "        if not ok:\n"
                    "            return None",
               "        name, ok = QtWidgets.QInputDialog.getItem(self, title, prompt, names, 0, False)\n"
               "        if not ok:\n"
               "            return choices[0]   # 注入：取消也替人挑了第一个")]),
    Case("c5", "没有可并入的对象时静默返回（点了没反应，**ISSUES I63** 戊 同族）",
         CRIT + "test_只有一个标签时说明没有可并入的对象",
         [Edit(PAGE, '        if not choices:\n'
                    '            QtWidgets.QMessageBox.information(self, title, "没有可并入的标签")\n'
                    "            return None",
               "        if not choices:\n"
               "            return None   # 注入：一句都不说")]),
    Case("c6", "同一句前置提示在 `delete_tag` 里再抄一遍（口径开始散）",
         CRIT + "test_前置提示在页面代码里只写一处",
         [Edit(PAGE, '        picked = self._current_tag("删除")\n'
                    "        if picked is None:\n"
                    "            return",
               '        picked = self._current_tag("删除")\n'
               "        if picked is None:\n"
               '            QtWidgets.QMessageBox.information(self, "删除", "请先选择一个标签再删除")'
               "   # 注入：第二处\n"
               "            return")]),

    # —— (d) 同源：屏幕上那个数字来自仓储层 ————————————————
    Case("d1", "回执里那个份数由界面自己数列表条数（`merge_tags` 的返回值没人看）",
         CRIT + "test_收尾那句里的份数是仓储层数的而不是界面数的",
         [Edit(PAGE, "            moved = self.ctx.catalog.merge_tags(source_id, target_id)",
               "            self.ctx.catalog.merge_tags(source_id, target_id)\n"
               "            moved = self.tag_list.count()   # 注入：界面自己数")]),

    # —— 接线 ——————————————————————————————————————————————
    Case("w1", "调用点拆掉（`merge_tags` 的调用方退回只剩 `tests/`，**ISSUES I78** 那格复发）",
         CRIT + "test_merge_tags在产品侧有调用点了",
         [Edit(PAGE, "            moved = self.ctx.catalog.merge_tags(source_id, target_id)",
               "            moved = 0   # 注入：这一环没接上")]),
]


def _label(case: Case) -> str:
    return f"p24 注入 {case.inject}｜{case.坏法}"


def main() -> int:
    wanted = [a for a in sys.argv[1:] if not a.startswith("-")]
    cases = [c for c in CASES if not wanted or c.inject in wanted]
    if not cases:
        print(f"没有这些编号：{wanted}（可选：{[c.inject for c in CASES]}）")
        return 2

    ws = Path(tempfile.mkdtemp(prefix="p24_baseline_"))
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
        one = Path(tempfile.mkdtemp(prefix="p24_case_"))
        try:
            _copy_repo(one)
            _apply(one, case)
            rc, out = _run(one, case.node.split())
            failed, errored, passed = _verdicts(out)
            caught = rc != 0 and failed >= 1 and errored == 0
            tail = [ln for ln in out.splitlines() if ln.strip()]
            detail = (f"failed={failed} error={errored} passed={passed}" if caught
                      else " / ".join(tail[-3:]) if tail else "没有输出")
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
