"""Second pass: fix double prefixes and range patterns left by first pass."""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

DOUBLE_RE = re.compile(r'ISSUES\s+ISSUES\s+')
RANGE_RE = re.compile(r'(?<!ISSUES\s)(?<![A-Za-z0-9])I(\d{1,2})(?![A-Za-z0-9])')

def fix_double(content: str) -> str:
    return DOUBLE_RE.sub('ISSUES ', content)

def fix_ranges(content: str) -> str:
    def replacer(m: re.Match) -> str:
        start = m.start()
        prefix = content[max(0, start-30):start]
        if 'ISSUES ' in prefix[-10:] or '注入 I' in prefix[-10:]:
            return m.group(0)
        return f'ISSUES I{m.group(1)}'
    return RANGE_RE.sub(replacer, content)

def main() -> None:
    docs_dir = ROOT / 'docs'
    files = sorted(docs_dir.rglob('*.md')) + [ROOT / 'README.md']
    changed = 0
    for f in files:
        if not f.exists():
            continue
        content = f.read_text(encoding='utf-8')
        new_content = fix_double(content)
        new_content = fix_ranges(new_content)
        if new_content != content:
            f.write_text(new_content, encoding='utf-8')
            changed += 1
    print(f"Fixed {changed} files")

if __name__ == '__main__':
    main()
