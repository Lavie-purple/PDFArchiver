"""文档里的**证据指针存在性**守卫 —— 把台账规则「文档里的引用也是断言」变成机器断言。

这条规则以前只是写在 `docs/ISSUES.md` 末尾那张规则表里，没人断言，所以同一个毛病在两周内
复发了三次（都是本轮改账时现读的）：

- **ISSUES I51** 的处置格写「**D-017** 已定『行号↔坐标 O(1)』的口径」，而 D-017 是
  「阅读器渲染以 PyMuPDF 为主」—— 编号存在、但说的不是这件事；
- **ISSUES I66** 的处置格写「`TROUBLESHOOTING.md` **§十四** 问题表」，而那份文档最大的节号
  当时是 §十一 —— 指针直接空指；
- **ISSUES I34** 整条就是「交付文档引用不存在的测试名」。

守卫查六类指针（口径都取自被引用文件自己的定义处，不另立第二份）：

1. `D-\\d{3}` → 必须在 `docs/DECISIONS*.md`（活册 + 2026-10-18 切出的 `DECISIONS-ARCHIVE.md`）
   有 `## D-0xx` 标题（这两份合起来是定义处，不反过来查自己）；
2. `ISSUES I\\d+` → 必须在 `docs/ISSUES.md` 有 `| ISSUES Ixx ` 行（同上）；
3. `某某.md §<中文节号>` → 那份文件里必须有对应编号的 `## ` 标题（`## 一、` 与 `## 一 ·` 两种写法都认）；
4. 反引号里的 `test_\\w+` → 必须在 `tests/` 里真的 `def` 出来，**或**是同名的测试模块文件
   （`test_app_shell` 指的是那份被 **ISSUES I58** 拆掉的文件，不是函数）。
   **这一档对台账类文档不生效**（`LEDGER_DOCS` 与 `docs/stage-reports/`）：那里写的是
   「那一轮当时由哪条断言钉住」，把历史条目改成今天的样子就是销毁证据；
   今天已经不在场的名字由 `ledger_stale_test_names()` 逐条数出来（不判红），
   当场记在 **ISSUES I70**。
5. 反引号里的 `*.py` 文件名 → 必须在 `src/`／`gates/`／`tests/`／`packaging/`／`scripts/`
   或仓库根顶层真有一个同名文件（2026-10-18 加，**ISSUES I82** 乙：`docs/ARCHITECTURE.md`
   的模块树里有 9 条这样的文件线，而 `src/` 下从来没有过这些文件）。
   模板占位符（`NNNN_slug.py`、`stageN.py`）与 `.probe_work/` 走白名单，理由写在两个常量的注释里；
   台账类文档同样**只数不判红**（`ledger_stale_py_names()` → `PY_STALE_CAP`），
   因为「I82 这一行」本身就是靠列出九个不存在的名字存在的。
6. 「本机不存在 / 未安装 / 没建过」这类**现在时的本机状态**句子 → 同一行必须带
   `YYYY-MM-DD` 读数日期（2026-10-18 加，**ISSUES I87** 丙：阶段 0 那句「默认数据根在本机不存在」
   在真语料首扫之后就成了假话，而它同时躺在门禁打印、TESTING、ROADMAP、VERIFICATION 与交付报告里）。

**这条守卫查不出什么**（**ISSUES I35** 自己就记过这个局限，写在这里免得下轮把它当全能守卫）：
「存在但指错」—— 编号在场、说的却是另一件事。它能拦住的是**空指**，也就是最不可能被读出来
的那一类。第 3 项也只认「文件名 + §」挨在一起的写法，句子里承前省略文件名的裸 `§N` 不在范围内。
第 5 档另有两处**故意留的松**，都在注释里：裸名（`engine.py`）只认「有同名文件」，不认它在哪个层 ——
要卡层就得写全路径，而模块树天生写裸名；带 `/` 的写法按**段后缀**匹配，所以
`ui/pages/library_page.py` 算在场（它就是 `src/pdfarchiver/ui/pages/library_page.py`）。

坏法注入（要求"红且点名"）见 `tests/probes/p16_doc_pointers_injection.py`：六档各造一处空指
（编造 D 编号 / 编造 ISSUES 编号 / 编造节号 / 引用一个不存在的测试名 / 引用一个不存在的 `*.py` /
写一句不带日期的本机状态），逐条要求红在**对应那一条**断言上，且台账旧名与旧文件名那两条计数
不许跟着红（证明豁免不是把守卫放空）。

跑法：
    .venv/Scripts/python.exe -m pytest tests/guards/test_doc_pointers.py -q
    .venv/Scripts/python.exe tests/guards/test_doc_pointers.py      # 独立跑，末行 VERDICT
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

CN_DIGITS = "〇一二三四五六七八九十"

#: 台账与决策集自己就是编号的定义处，不反过来查自己。
#: `DECISIONS-ARCHIVE.md` 是 2026-10-18 切册（**D-059**）搬出来的 D-001 … D-038 逐字原文，
#: 它**也是**定义处：那些编号的正文在这里，所以它跟活册一样不反过来查（切册前它的引用根本不被扫，
#: 切完突然开始扫会把一批历史写法判成空指 —— 那是切册造成的假红，不是新问题）。
SELF_DEFINING = ("DECISIONS.md", "DECISIONS-ARCHIVE.md", "ISSUES.md")

#: **带日期的记录**：它们写的是「那一轮当时由哪条断言钉住」，其中的测试名允许已经改名或作废，
#: 因为把历史条目改成今天的样子等于销毁证据（AGENTS.md「不许伪装成功」的反面就是不许重写记录）。
#: 这批文档**仍然**受编号 / 节号两条检查约束 —— 编号是稳定的，改名不改变它指哪一条。
#: 现存的失效测试名指针逐条记在 **ISSUES I70**，不是没人看过。
LEDGER_DOCS = ("docs/CHANGELOG.md", "docs/CHANGELOG-ARCHIVE.md",
               "docs/DECISIONS.md", "docs/DECISIONS-ARCHIVE.md",
               "docs/ISSUES.md", "docs/VERIFICATION.md",
               "docs/VERIFICATION-RUNLOGS.md", "docs/REPO-JOURNAL.md")
LEDGER_DIR = "docs/stage-reports/"

#: 台账类文档里「今天已经不存在的测试名」允许的条数上限（**ISSUES I70** 丙）。
#: 6 = 2026-10-18 现数（`python tests/guards/test_doc_pointers.py` 倒数第二行），逐条记在 I70，
#: 每一条都当场追注了继任者。这条线不是审美：台账里的旧名字会无声累积，等到没人愿意逐条追注
#: 那一刻，「台账引用不存在的断言」就退回 **ISSUES I34** 之前的人肉状态。
#: 要抬高它，必须同时做两件事：给新出现的那条追注继任者，并在 I70 那一行写下为什么会多。
LEDGER_STALE_CAP = 6

# ───────────────────────────── 第 5 档：反引号里的 `*.py` 也是断言（**ISSUES I82** 乙）─────────────────────────────

#: `.py` 文件名的定义处 = 这四个代码目录 + `scripts/` + **仓库根本身的顶层 `.py`**
#: （`main.py` 是入口，`docs/INSTALL.md` 教人跑它；把它算成空指就等于让守卫教人改一个对的文件）。
#: 文档里的模块树、门禁说明、修复步骤
#: 凡是写「某某.py」的，断言的都是这些目录里有一个真文件；指向别处（如 `docs/` 下的示例）
#: 的句子不在本档范围，那种引用由第 3 档（节号）或直接由人核。
PY_DIRS = ("src", "gates", "tests", "packaging", "scripts")

#: 白名单前缀：`.probe_work/` 里的一次性探针**不归这一档管**。
#: 理由不是"放过它们"，而是**分工不同**：本档问的是"这个名字在不在产品的代码树里"，
#: 而"交付文档的证据不许指向收尾会删的临时文件"是另一条规则（**ISSUES I33 / I34**），
#: 那批 2026-10-18 已经逐条改指常驻探针 `tests/probes/p14_fts_instrument.py` 与台账行。
#: 台账里的 `.probe_work/` 引用（现数 19 个名字，16 个还在盘上）走"只数不判红"，见
#: `ledger_stale_py_names()`。
PY_EXEMPT_PREFIX = (".probe_work/",)

#: 模板占位符不是"某个文件在场"的断言，是"某个文件长这样"的说明（迁移与门禁的命名规则）。
PY_TEMPLATES = ("NNNN_slug.py", "stageN.py")

#: 台账类文档里「今天已经不存在的 `.py` 名字」允许的条数（同 `LEDGER_STALE_CAP` 的形状）。
#: 28 = 2026-10-18 现数（本文件末行打印的那一条；+1 来自 I77 甲的 `i77_badway.py`）。
#: 这个数看着大，大头是三类**本来就该留着的**：
#: `docs/ISSUES.md:95` 一条就占了 12 处 —— 那是 **ISSUES I82** 自己在逐条点名「哪 9 个文件名不存在」，
#: 把这些名字改成今天的样子等于把这条台账的物证删掉；其余是随轮次删掉的一次性探针
#: （`index_write_probe.py`、`ocr_accuracy.py` 等）与被改名的测试文件。
#: 抬高它同样必须逐条写明为什么（哪一轮把哪个文件改名/删掉了，继任者是谁）。
#: 35 = 2026-10-20 现数：轮十六 把 791 行的 `tests/integration/test_category_export_ui.py`
#: 按主题拆成 `tests/integration/category_export/` 三份测试（`test_ui.py` / `test_output.py` /
#: `test_archive.py`，加共享的 `_helpers.py` 与 `conftest.py`）。台账里 7 处旧文件名按
#: 「不改历史」留着原样（CHANGELOG ×2、ISSUES I78 ×1、RUNLOGS ×3、阶段3交付报告 ×1），
#: 逐条追注见 **ISSUES I82** 2026-10-20 那一段。
PY_STALE_CAP = 35

#: 第 6 档：现在时的**机器状态**断言必须带读数日期（**ISSUES I87** 丙）。
#: 「本机不存在 / 未安装 / 没建过」这类句子说的是**这台机器今天什么样**，不是产品逻辑；
#: 阶段 0 那句「默认数据根在本机不存在」在真语料首扫之后就成了假话，而它同时躺在门禁打印、
#: TESTING、ROADMAP、VERIFICATION 与交付报告里（五个落点，见 I87）。
#: 只认「本机」+ 现在时否定的**紧挨**形状，避免把产品行为描述（"配置文件不存在时…"）误判进来。
MACHINE_STATE = re.compile(r"本机[^。；\n]{0,28}?(不存在|不在场|未安装|没装|没建过)")
DATED = re.compile(r"\d{4}-\d{2}-\d{2}")


def _cn_to_int(text: str) -> int | None:
    """中文节号转数字，只覆盖本仓用到的 `〇`–`九十九`；不认识的写法返回 None（不猜）。"""
    if text == "〇":
        return 0
    if "十" not in text:
        return CN_DIGITS.index(text) if text in CN_DIGITS else None
    before, _, after = text.partition("十")
    tens = CN_DIGITS.index(before) if before else 1
    ones = CN_DIGITS.index(after) if after else 0
    if tens > 9 or ones > 9:
        return None
    return tens * 10 + ones


def _doc_files() -> list[Path]:
    files = [ROOT / "README.md"]
    files.extend(sorted((ROOT / "docs").rglob("*.md")))
    return [f for f in files if f.is_file()]


def _headings(path: Path) -> set[int]:
    """该文件里 `## <中文数字>` 形式的顶级节号集合。"""
    found = set()
    for m in re.finditer(r"^## ([〇一二三四五六七八九十]+)[ 、·]",
                         path.read_text(encoding="utf-8", errors="replace"), re.M):
        value = _cn_to_int(m.group(1))
        if value is not None:
            found.add(value)
    return found


def _decision_files() -> list[Path]:
    """决策编号的定义处 = 活册 + 分册。2026-10-18 切册（**D-059**）把 D-001 … D-038 逐字搬进
    `DECISIONS-ARCHIVE.md`，如果这里还只读活册，**全仓几百处引用早期编号的活文档会一起假红** ——
    这条 glob 就是切册唯一一次被迫改到的判据（坏法见 `test_分册里的编号仍然算在场`）。"""
    return sorted((ROOT / "docs").glob("DECISIONS*.md"))


def _decision_numbers() -> set[int]:
    found: set[int] = set()
    for path in _decision_files():
        found.update(int(m) for m in re.findall(r"^## D-(\d+)",
                                                path.read_text(encoding="utf-8", errors="replace"),
                                                re.M))
    return found


def _issue_numbers() -> set[int]:
    text = (ROOT / "docs" / "ISSUES.md").read_text(encoding="utf-8", errors="replace")
    return {int(m) for m in re.findall(r"^\| ISSUES I(\d+) ", text, re.M)}


def _test_functions() -> set[str]:
    names: set[str] = set()
    for path in (ROOT / "tests").rglob("*.py"):
        names.update(re.findall(r"\bdef (test_\w+)", path.read_text(encoding="utf-8",
                                                                     errors="replace")))
    return names


def _test_modules() -> set[str]:
    """`tests/` 下的模块名。文档里反引号包住的 `test_xxx` 有一半指的是**文件**而不是函数
    （例如 `test_app_shell` 是阶段 1 那份 913 行的文件，**ISSUES I58** 把它拆成了四份），
    两种写法都要能被认下来。"""
    return {p.stem for p in (ROOT / "tests").rglob("test_*.py")}


def _is_ledger(rel: str) -> bool:
    return rel in LEDGER_DOCS or rel.startswith(LEDGER_DIR)


def _py_inventory() -> tuple[set[str], set[str]]:
    """`PY_DIRS` 里所有 `.py` 的两种口径：仓内相对路径（posix）与裸文件名。

    两种都要，因为文档里两种写法都有：模块树写裸名（`queue.py`），修复步骤写全路径
    （`tests/guards/test_migrations.py`），而讲 `src/` 内部时写的是**包根以下的半路径**
    （`ui/pages/library_page.py` = `src/pdfarchiver/ui/pages/library_page.py`）。
    半路径靠**按段后缀**匹配（见 `check_pointers` 第 5 档），不靠裸名 —— 否则 `db/engine.py`
    会被 `ocr/engine.py` 这种同裸名不同层的路径蒙过去。
    `__pycache__` 必须排掉 —— 它里面有
    `0001_initial.cpython-311.py` 这类**同名不同物**的东西，混进来会让"名字在场"这条判据变松。
    """
    paths: set[str] = set()
    names: set[str] = set()
    tops = [ROOT / top for top in PY_DIRS] + [ROOT]      # 顶层只取 ROOT/*.py，不递归
    for base in tops:
        if not base.is_dir():
            continue
        pattern = "*.py" if base == ROOT else "**/*.py"
        for path in base.glob(pattern):
            if "__pycache__" in path.parts or ".venv" in path.parts:
                continue
            paths.add(path.relative_to(ROOT).as_posix())
            names.add(path.name)
    return paths, names


def _py_present(quoted: str, py_paths: set[str], py_names: set[str]) -> bool:
    """`quoted` 这个写法在代码树里有没有对应的真文件（第 5 档的判据本体）。"""
    if quoted in py_paths:
        return True
    if "/" in quoted:
        return any(p.endswith("/" + quoted) for p in py_paths)
    return quoted in py_names


def _quoted_py(line: str) -> list[str]:
    """这一行里被反引号整体包住、且**整段就是一个 py 路径**的引用。

    整段 fullmatch 而不是 search：模块树里那句 `` `fileops/{plan,journal,execute,undo}.py` ``
    是一条"这几个名字都不存在"的说明，把它拆开逐段判会误伤，而它本来也不该被当断言。
    """
    found = []
    for span in re.findall(r"`([^`]*)`", line):
        text = span.strip()
        if text.startswith("./"):
            text = text[2:]              # 只去相对前缀；lstrip("./") 会把 `.probe_work/` 的点也吃掉
        text = text.replace("\\", "/")
        if not re.fullmatch(r"[\w.\u4e00-\u9fff/-]+\.py", text):
            continue
        if text.split("/")[-1] in PY_TEMPLATES:      # 按裸名滤：`gates/stageN.py` 也是模板写法
            continue
        found.append(text)
    return found


def _resolve_md(name: str) -> Path | None:
    """按文件名在仓里找那份 md（引用只写文件名，不写目录，所以这里必须支持递归找）。"""
    candidates = [p for p in ROOT.rglob(name) if p.is_file()]
    if not candidates:
        return None
    in_docs = [p for p in candidates if "docs" in p.parts]
    return (in_docs or candidates)[0]


def check_pointers() -> list[str]:
    decisions = _decision_numbers()
    issues = _issue_numbers()
    functions = _test_functions()
    modules = _test_modules()
    heading_cache: dict[str, set[int]] = {}
    py_paths, py_names = _py_inventory()
    problems: list[str] = []

    for path in _doc_files():
        rel = path.relative_to(ROOT).as_posix()
        text = path.read_text(encoding="utf-8", errors="replace")
        for line_no, line in enumerate(text.splitlines(), 1):
            if path.name not in SELF_DEFINING:
                for number in {int(x) for x in re.findall(r"(?<![\w-])D-(\d{3})(?![\w-])", line)}:
                    if number not in decisions:
                        problems.append(f"{rel}:{line_no} 引用 D-{number:03d}，"
                                        f"而 `docs/DECISIONS*.md`（活册 + 分册）里没有这条编号")
                for number in {int(x) for x in re.findall(r"ISSUES I(\d+)", line)}:
                    if number not in issues:
                        problems.append(f"{rel}:{line_no} 引用 ISSUES I{number}，"
                                        f"而 `docs/ISSUES.md` 里没有这一行")
            for match in re.finditer(r"`?([\w.\u4e00-\u9fff-]+\.md)`?\s*§([〇一二三四五六七八九十]+)",
                                     line):
                name, raw = match.group(1), match.group(2)
                target = _resolve_md(name)
                if target is None:
                    problems.append(f"{rel}:{line_no} 引用 {name} §{raw}，仓库里没有这份文件")
                    continue
                key = str(target)
                if key not in heading_cache:
                    heading_cache[key] = _headings(target)
                want = _cn_to_int(raw)
                if want is None or want not in heading_cache[key]:
                    problems.append(
                        f"{rel}:{line_no} 引用 {name} §{raw}，而该文件现有节号 "
                        f"{sorted(heading_cache[key])}")
            if _is_ledger(rel):
                continue          # 第 4、5、6 档对带日期的记录不生效，理由见 `LEDGER_DOCS` 的注释
            for quoted in re.findall(r"`(test_[\w]+)`", line):
                if quoted not in functions and quoted not in modules:
                    problems.append(f"{rel}:{line_no} 引用 `{quoted}`，而 `tests/` 里既没有这个 "
                                    f"`def test_` 名字也没有同名模块文件")
            for quoted in _quoted_py(line):
                if any(quoted.startswith(p) for p in PY_EXEMPT_PREFIX):
                    continue
                if _py_present(quoted, py_paths, py_names):
                    continue
                problems.append(f"{rel}:{line_no} 引用 `{quoted}`，而 "
                                f"{'/'.join(PY_DIRS)} 这四个代码目录与仓库根顶层"
                                f"没有任何同名文件"
                                f"（**ISSUES I82**：文档里的 `*.py` 文件名也是断言）")
            if MACHINE_STATE.search(line) and not DATED.search(line):
                problems.append(f"{rel}:{line_no} 「{MACHINE_STATE.search(line).group(0)}」是一句"
                                f"**现在时**的本机状态断言，却没带读数日期（**ISSUES I87** 丙："
                                f"这类句子会随这台机器变样，必须写明哪天量的）")
    return problems


def ledger_stale_test_names() -> list[str]:
    """台账类文档里「今天已经不存在」的测试名，逐条数出来给 **ISSUES I70** 对账用。

    它们**不算红**（销毁证据比留一个旧名字更糟），但**必须可见** —— 没有这一条，
    「台账里引用不存在的测试」就又回到只有人肉读才发现的老路（**ISSUES I34**）。
    """
    functions = _test_functions()
    modules = _test_modules()
    found: list[str] = []
    for path in _doc_files():
        rel = path.relative_to(ROOT).as_posix()
        if not _is_ledger(rel):
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for line_no, line in enumerate(text.splitlines(), 1):
            for quoted in set(re.findall(r"`(test_[\w]+)`", line)):
                if quoted not in functions and quoted not in modules:
                    found.append(f"{rel}:{line_no} {quoted}")
    return sorted(set(found))


def ledger_stale_py_names() -> list[str]:
    """台账类文档里「今天已经不存在」的 `.py` 名字，逐条数出来给 **ISSUES I82** 对账用。

    与 `ledger_stale_test_names()` 同一条理由：那些行写的是「那一轮当时动过哪个文件」，
    而台账里最典型的一条就是 I82 自己 —— 它存在的意义就是列出九个不存在的名字。
    所以这里**只数不判红**，但数字必须上屏（**ISSUES I34**：没人数的账等于没账）。
    """
    py_paths, py_names = _py_inventory()
    found: list[str] = []
    for path in _doc_files():
        rel = path.relative_to(ROOT).as_posix()
        if not _is_ledger(rel):
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for line_no, line in enumerate(text.splitlines(), 1):
            for quoted in set(_quoted_py(line)):
                if any(quoted.startswith(p) for p in PY_EXEMPT_PREFIX):
                    continue
                if _py_present(quoted, py_paths, py_names):
                    continue
                found.append(f"{rel}:{line_no} {quoted}")
    return sorted(set(found))


def _problems_containing(*needles: str) -> list[str]:
    """按**报错句子里的固定短语**分派，不按被引用的编号形状分派 —— 第一版按 `"D-0"` 筛，
    于是注入一条 `D-999` 就漏过去了（编号形状不同，而同一条断言本该抓住它）。"""
    return [p for p in check_pointers() if any(n in p for n in needles)]


def test_文档里的决策编号都真实存在() -> None:
    assert _decision_numbers(), "docs/DECISIONS.md 一条编号都没解析出来，守卫自己坏了"
    if bad := _problems_containing("里没有这条编号"):
        raise AssertionError("\n".join(bad))


def test_分册里的编号仍然算在场() -> None:
    """切册不许把编号切成不存在（**ISSUES I86** 乙 的前置）。

    坏法 2026-10-18 真注入过：把 `_decision_files()` 收回只读 `docs/DECISIONS.md` 一份 →
    本条立刻红在「分册里的 38 条不被认」上，同时 `test_文档里的决策编号都真实存在` 也跟着红
    （活文档里有几百处引用 D-0xx 早期编号）；改回 glob 两条一起绿。
    """
    files = _decision_files()
    assert len(files) >= 2, (
        f"决策定义处只有 {len(files)} 份（{[f.name for f in files]}）—— 分册被挪走或改名了，"
        "早期编号会从定义处消失")
    archived = {int(m) for m in re.findall(
        r"^## D-(\d+)", (ROOT / "docs" / "DECISIONS-ARCHIVE.md")
        .read_text(encoding="utf-8", errors="replace"), re.M)}
    live = set()
    for path in files:
        if path.name == "DECISIONS-ARCHIVE.md":
            continue
        live.update(int(m) for m in re.findall(
            r"^## D-(\d+)", path.read_text(encoding="utf-8", errors="replace"), re.M))
    assert archived, "分册里一条 D 编号都没有 —— 那 `_decision_files` 的 glob 就是在空转"
    missing = archived - _decision_numbers()
    assert not missing, f"分册里的 {sorted(missing)} 不被认，活文档引用它们会假红"
    assert not (archived & live), f"同一个编号出现在两册里（{sorted(archived & live)}）—— 切册切重了"


def test_文档里的台账编号都真实存在() -> None:
    assert _issue_numbers(), "docs/ISSUES.md 一条编号都没解析出来，守卫自己坏了"
    if bad := _problems_containing("里没有这一行"):
        raise AssertionError("\n".join(bad))


def test_文档里的节号指针都落得下去() -> None:
    if bad := _problems_containing("而该文件现有节号", "仓库里没有这份文件"):
        raise AssertionError("\n".join(bad))


def test_活文档里引用的测试名都还在场() -> None:
    if bad := _problems_containing("`test_"):
        raise AssertionError("\n".join(bad))


def test_活文档里引用的文件名都还在场() -> None:
    """第 5 档（**ISSUES I82** 乙）：反引号里的 `*.py` 也是断言，不是排版。"""
    if bad := _problems_containing("没有任何同名文件"):
        raise AssertionError("\n".join(bad))


def test_本机状态断言带读数日期() -> None:
    """第 6 档（**ISSUES I87** 丙）：「本机不存在 / 未安装」这类现在时句子必须带日期。

    这条只管活文档：台账里同一句话是**那一轮的读数**，本身就在带日期的格子里，
    把它改成今天的样子就是 I87 要防的那种「抄成常量」。
    """
    if bad := _problems_containing("本机状态断言"):
        raise AssertionError("\n".join(bad))


def test_台账旧名不超过上限() -> None:
    """台账里的过期名字**可以存在**（改历史记录就是销毁证据），但**不许无声增长**。

    判红的方式只有一条路能走：新一轮改了代码里的测试名、却没给台账那一处追注继任者。
    那时正确做法是补追注，不是抬这条线（抬线要在 I70 写明理由，见 `LEDGER_STALE_CAP` 的注释）。
    """
    stale = ledger_stale_test_names()
    assert len(stale) <= LEDGER_STALE_CAP, (
        f"台账旧名 {len(stale)} 处 > 上限 {LEDGER_STALE_CAP} 处。多出来的是这些：\n"
        + "\n".join(stale))


def test_台账旧文件名不超过上限() -> None:
    """第 5 档的台账半边（**ISSUES I82** 乙）：豁免 ≠ 没人看。

    上限 = 现数 27，其中 12 处是 `docs/ISSUES.md:95` 那条 **I82 自己在逐条点名**「哪 9 个文件名
    不存在」—— 把那行改成今天的样子就是销毁证据。所以这条判红的唯一路径是：**新一轮又让一个
    文档里的文件名失去了对应物**，而没在 I82 那一行写下它去哪了。
    """
    stale = ledger_stale_py_names()
    assert len(stale) <= PY_STALE_CAP, (
        f"台账旧文件名 {len(stale)} 处 > 上限 {PY_STALE_CAP} 处。多出来的是这些：\n"
        + "\n".join(stale))


if __name__ == "__main__":
    found = check_pointers()
    stale = ledger_stale_test_names()
    stale_py = ledger_stale_py_names()
    if len(stale) > LEDGER_STALE_CAP:
        found.append(f"台账旧名 {len(stale)} 处 > 上限 {LEDGER_STALE_CAP} 处"
                     f"（**ISSUES I70** 丙）：新多出来的是这些 → {'；'.join(stale)}")
    if len(stale_py) > PY_STALE_CAP:
        found.append(f"台账旧文件名 {len(stale_py)} 处 > 上限 {PY_STALE_CAP} 处"
                     f"（**ISSUES I82** 乙）：新多出来的是这些 → {'；'.join(stale_py)}")
    for item in found:
        print("  RED  " + item)
    for item in stale:
        print("  台账旧名  " + item)
    print(f"扫了 {len(_doc_files())} 份 md、{len(_decision_numbers())} 条决策编号、"
          f"{len(_issue_numbers())} 条台账编号、{len(_test_functions())} 个测试函数、"
          f"{len(_py_inventory()[0])} 个真实 .py")
    print(f"台账类文档里今天已不存在的测试名（不判红，逐条记在 **ISSUES I70**）：{len(stale)} 处")
    print(f"台账类文档里今天已不存在的 .py 名字（不判红，逐条记在 **ISSUES I82**）：{len(stale_py)} 处")
    print("VERDICT: " + ("ALL GREEN" if not found else f"RED（{len(found)} 处空指）"))
    sys.exit(0 if not found else 1)
