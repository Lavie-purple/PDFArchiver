"""主题配色的对比度守卫 —— 凡承载文字的颜色对，两主题都必须过 WCAG AA 4.5:1。

这条为什么值得存在（都是量出来的，不是"看着还行"）：界面审核轮揪出四条承载文字的 accent 用色
不达标 —— blue-500 `#3b82f6` 压白字 **3.68:1**、当小字压在 `btn_hover` 上 **3.31:1**、
暗色下压 `#475569` **2.06:1**、`#dc3545` 危险色压暗色卡片 **2.54:1**，另有十处页面里
写死的 `setStyleSheet("color: #…")` 落在 2.55–4.13:1。修完之后复测，浅色主题状态栏
`#6c757d` 压在白底上是 4.69:1（过），压在**状态栏自己的底** `#f8f9fa` 上只剩 **4.45:1**（不过）——
同一个灰在两个底上结论相反，所以这里的配对**逐个写明它真正落在哪块底上**，不写"文字色 vs 背景色"。

两道守卫各管一类，缺一类就漏一段：
- `test_承载文字的颜色对全部过AA` 管**令牌级**搭配（文字色来自一条规则、底来自另一条，
  如 `QLabel#muted` 压在卡片/隔行底上）。
- `test_换底的状态规则必须带上过AA的字色` 管**渲染后的 QSS**：`:hover` / `:selected` 这类
  规则把底换掉之后，字色是按级联继承下来的，令牌级清单看不见这块新底。`QTabBar::tab:hover`
  就是这一类 —— 它换到 `table_row_hover`，继承的 `text_secondary` 在浅/暗两主题分别是
  **4.34:1 / 4.04:1**，两边都掉出 AA，而 `live_pairs` 里一条都不涉及 hover 态。
"""
from __future__ import annotations

import re

import pytest

from pdfarchiver.ui.theme import DARK_THEME, LIGHT_THEME, ThemeColors, ThemeManager

AA_FLOOR = 4.5

# 会把**底**换掉的状态词：换了底，继承来的字色就得重新量一遍。
BG_STATE_WORDS = ("hover", "pressed", "selected", "checked", "focus", "disabled")
# 这些子控件自己不画文字（滚动条滑块、复选框方框、分隔线、面板框），量字色对它们没有意义。
# 注意 `::chunk` 不在这里：进度条的百分比文字是横着压在进度块上的，那条归判重进度（ISSUES 台账）。
TEXT_FREE_SUBCONTROLS = frozenset({
    "handle", "indicator", "separator", "pane", "add-line", "sub-line",
    "add-page", "sub-page", "down-arrow", "up-arrow", "left-arrow", "right-arrow",
    "drop-down", "close-button", "increment", "decrement",
})

_BLOCK_RE = re.compile(r"([^{}]+)\{([^{}]*)\}")
_PROP_RE = re.compile(r"([A-Za-z-]+)\s*:\s*([^;\n]+)")


def _lum(hex_color: str) -> float:
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    f = lambda c: c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4  # noqa: E731
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)


def _ratio(fg: str, bg: str) -> float:
    la, lb = _lum(fg), _lum(bg)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


def _hex(value: str | None) -> str | None:
    return value if value and value.startswith("#") else None


def qss_rules(theme_name: str) -> dict[str, dict[str, str]]:
    """渲染后的 QSS → {选择器: {属性: 值}}，注释先剥掉（注释里带 `:`，会把属性解析带歪）。"""
    manager = ThemeManager()
    manager.set_theme(theme_name)
    stripped = re.sub(r"/\*.*?\*/", "", manager.generate_qss(), flags=re.S)
    rules: dict[str, dict[str, str]] = {}
    for selector, body in _BLOCK_RE.findall(stripped):
        props = {}
        for key, value in _PROP_RE.findall(body):
            props.setdefault(key.strip().lower(), value.strip())
        rules.setdefault(" ".join(selector.split()), props)
    return rules


def _cascade_chain(selector: str) -> list[str]:
    """QSS 里这条规则的**继承顺序**：自身 → 逐个去掉尾部状态词 → 去掉子控件 → 全局。

    尾部状态词从右往左剥（`:item:hover` 先回到 `:item`），且只剥 `BG_STATE_WORDS` 里的那些，
    不能对 `::item` 用 `:xxx` 的通配 —— 那会把子控件名当状态词吃掉，级联直接接错宿主。
    """
    chain = [selector]
    current = selector
    while True:
        head, sep, tail = current.rpartition(":")
        if not sep or tail not in BG_STATE_WORDS:
            break
        current = head
        chain.append(current)
    if "::" in current:
        chain.append(current.split("::", 1)[0])
    chain.append("QWidget")
    return chain


def effective_text_color(selector: str, rules: dict[str, dict[str, str]]) -> str | None:
    """最终落到这条规则上的文字色（自身声明优先，否则按 QSS 继承顺序往上找）。"""
    for candidate in _cascade_chain(selector):
        if "::" in candidate:
            part = candidate.split("::", 1)[1].split(":")[0]
            if part in TEXT_FREE_SUBCONTROLS:
                return None
        color = _hex(rules.get(candidate, {}).get("color"))
        if color:
            return color
    return None


def state_rules_that_repaint(rules: dict[str, dict[str, str]]) -> list[tuple[str, str, str]]:
    """(选择器, 字色, 新底) —— 带状态词、且把底换成实色的规则。"""
    out = []
    for selector, props in rules.items():
        tail = selector.rpartition(":")[2]
        if tail not in BG_STATE_WORDS:
            continue
        bg = _hex(props.get("background-color"))
        if not bg:
            continue
        fg = _hex(props.get("color")) or effective_text_color(selector, rules)
        if fg:
            out.append((selector, fg, bg))
    return out


def live_pairs(c: ThemeColors) -> list[tuple[str, str, str]]:
    """(前景, 背景, 说明) —— 只列**真的会上屏**的搭配。

    占位符这一条是**例外**：它不在 QSS 里（`QLineEdit::placeholder` 是死选择器，填纯红
    渲染出 0 个红像素，**ISSUES I49**），Qt 取的是 `QPalette.PlaceholderText`，由
    `ThemeManager.apply_palette()` 逐控件设成 `text_secondary`（**ISSUES I50** 乙）。
    不设时代码里查不到 —— 那是 Qt 自己拿正文字色按 50% alpha 混出来的第三种颜色，
    实测浅色 `#909294`=3.12:1、暗色 `#808895`=4.09:1，两主题都不过 AA。
    """
    return [
        ("#ffffff", c.btn_primary_bg, "主按钮白字 / 主按钮填充"),
        (c.accent_text, c.card_bg, "accent 当文字色 / 卡片底"),
        (c.accent_text, c.content_bg, "accent 当文字色 / 正文底"),
        (c.accent_text, c.accent_light, "accent 当文字色 / 选中行底"),
        (c.text_secondary, c.card_bg, "次要文字 / 卡片底"),
        (c.text_secondary, c.content_bg, "次要文字 / 正文底"),
        (c.text_secondary, c.table_row_alt, "次要文字 / 隔行底"),
        (c.text_secondary, c.input_bg, "占位符 / 输入框底"),
        (c.danger, c.card_bg, "危险色 / 卡片底"),
        (c.danger, c.content_bg, "危险色 / 正文底"),
        (c.table_header_text, c.table_header_bg, "表头字 / 表头底"),
        (c.sidebar_active_text, c.sidebar_active_bg, "侧栏选中字 / 侧栏选中底"),
        (c.sidebar_text, c.sidebar_bg, "侧栏字 / 侧栏底"),
        (c.btn_text, c.btn_bg, "按钮字 / 按钮底"),
        (c.btn_text, c.btn_hover, "按钮字 / 按钮悬停底"),
        (c.status_text, c.status_bg, "状态栏字 / 状态栏底"),
        (c.text_primary, c.card_bg, "正文 / 卡片底"),
        (c.text_primary, c.content_bg, "正文 / 正文底"),
    ]


@pytest.mark.parametrize("theme_name,theme", [("浅色", LIGHT_THEME), ("暗色", DARK_THEME)])
def test_承载文字的颜色对全部过AA(theme_name: str, theme: ThemeColors) -> None:
    failures = []
    for fg, bg, desc in live_pairs(theme):
        ratio = _ratio(fg, bg)
        if ratio < AA_FLOOR:
            failures.append(f"{desc}: {fg} on {bg} = {ratio:.2f}:1")
    assert not failures, (
        f"{theme_name}主题有 {len(failures)} 对承载文字的颜色不过 AA（要求 ≥{AA_FLOOR}:1）：\n  "
        + "\n  ".join(failures))


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_换底的状态规则必须带上过AA的字色(theme: str) -> None:
    """`:hover` / `:selected` 换掉底之后，字色是继承来的 —— 必须按继承顺序求出那一个字色。

    只量「同一条规则里同时写了 color 和 background-color」是**可以被绕过的**：把
    `QTabBar::tab:hover` 里那行 `color` 删掉，块内配对守卫就不再看这条规则，而屏上仍然是
    继承来的 `text_secondary` 压在 `table_row_hover` 上（浅色 4.34:1）。所以这里量的是
    「这块底 + 最终落到它上面的那个字色」，不是「块内声明的那一对」。
    """
    checked = state_rules_that_repaint(qss_rules(theme))
    # 解析器一旦接错（选择器认不出来、色值前缀变了），checked 会退化成空表然后稳定假绿
    assert len(checked) >= 10, f"{theme}主题只认出 {len(checked)} 条换底的状态规则，守卫已失效"
    failures = [f"{sel}: {fg} on {bg} = {_ratio(fg, bg):.2f}:1"
                for sel, fg, bg in checked if _ratio(fg, bg) < AA_FLOOR]
    assert not failures, (
        f"{theme}主题有 {len(failures)} 条换底的状态规则承载文字不过 AA：\n  "
        + "\n  ".join(failures))


def test_主按钮填充与accent文字色是两套值() -> None:
    """装饰性 accent 与承载文字的 accent 必须是两个令牌。

    合成一个就会两头都输：`accent` 要够亮才压得住暗色卡片上的选中左边条，
    但要当文字色就得够暗（blue-500 压白字只有 3.68:1）。
    """
    assert LIGHT_THEME.accent != LIGHT_THEME.accent_text
    assert DARK_THEME.accent != DARK_THEME.accent_text
    assert _ratio("#ffffff", LIGHT_THEME.btn_primary_bg) >= AA_FLOOR, (
        "主按钮上的白字是直接印在填充色上的，填充色不许为了『好看』调亮")
