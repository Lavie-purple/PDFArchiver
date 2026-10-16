"""一次性清理裸 I<n> 引用：给每个裸写加上命名空间。

规则：
- ISSUES.md 行头 `| I5 |` 是定义，不改；文内交叉引用改 `ISSUES I<n>`
- TESTING.md p9 注入表行头 `| I1 |` 改 `p9 注入 I1`；其余台账引用改 `ISSUES I<n>`
- 其它文件：裸 I<n> 一律改 `ISSUES I<n>`
- 已有命名空间的（ISSUES I / 注入 I / p9 注入 / p10 注入 #）跳过
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BARE_RE = re.compile(r'(?<![A-Za-z0-9\u4e00-\u9fff])I(\d{1,2})(?![A-Za-z0-9])')
NS_RE = re.compile(r'(?:ISSUES\s+I|注入\s+I|p9\s+注入\s+I|p10\s+注入\s+#)')

def fix_line(line: str, is_issues_row_header: bool = False, is_p9_row_header: bool = False) -> str:
    if is_issues_row_header:
        return line
    if is_p9_row_header:
        return BARE_RE.sub(r'p9 注入 I\1', line, count=1)

    def replacer(m: re.Match) -> str:
        start = m.start()
        prefix = line[:start]
        if NS_RE.search(prefix[-30:]):
            return m.group(0)
        return f'ISSUES I{m.group(1)}'

    return BARE_RE.sub(replacer, line)


def process_issues_md(content: str) -> str:
    lines = content.split('\n')
    out = []
    for line in lines:
        if re.match(r'^\|\s*I\d{1,2}\s*\|', line):
            out.append(line)
        else:
            out.append(fix_line(line, is_issues_row_header=False))
    return '\n'.join(out)


def process_testing_md(content: str) -> str:
    lines = content.split('\n')
    out = []
    in_p9_table = False
    for line in lines:
        if 'p9' in line.lower() and '反向注入' in line:
            in_p9_table = True
        if in_p9_table and re.match(r'^\|\s*I\d{1,2}\s*\|', line):
            out.append(fix_line(line, is_p9_row_header=True))
        elif in_p9_table and line.strip() == '':
            in_p9_table = False
            out.append(line)
        elif re.match(r'^#{1,3}\s', line):
            in_p9_table = False
            out.append(line)
        else:
            out.append(fix_line(line))
    return '\n'.join(out)


def process_generic(content: str) -> str:
    lines = content.split('\n')
    return '\n'.join(fix_line(line) for line in lines)


def main() -> None:
    docs_dir = ROOT / 'docs'
    files = sorted(docs_dir.rglob('*.md')) + [ROOT / 'README.md']

    total_before = 0
    total_after = 0
    changed_files = 0

    for f in files:
        if not f.exists():
            continue
        content = f.read_text(encoding='utf-8')
        before = len(BARE_RE.findall(content))
        ns_count = len(NS_RE.findall(content))
        bare_before = before - ns_count

        if f.name == 'ISSUES.md':
            new_content = process_issues_md(content)
        elif f.name == 'TESTING.md':
            new_content = process_testing_md(content)
        else:
            new_content = process_generic(content)

        after_all = len(BARE_RE.findall(new_content))
        after_ns = len(NS_RE.findall(new_content))
        bare_after = after_all - after_ns

        if bare_after < bare_before:
            f.write_text(new_content, encoding='utf-8')
            changed_files += 1

        total_before += bare_before
        total_after += bare_after

    print(f"处理前裸写：{total_before}")
    print(f"处理后裸写：{total_after}")
    print(f"修改文件数：{changed_files}")
    print(f"消除裸写：{total_before - total_after}")


if __name__ == '__main__':
    main()
