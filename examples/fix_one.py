"""Программное применение автофиксов к .docx.

Запуск:

    python examples/fix_one.py work.docx fixed.docx
"""
from __future__ import annotations

import sys
from pathlib import Path

from gostforge.exporter import export_docx
from gostforge.fixer import fix as run_fix
from gostforge.parser import parse_docx
from gostforge.profile import load_profile


def main() -> int:
    if len(sys.argv) < 3:
        print("Usage: python fix_one.py <input.docx> <output.docx> [profile-id]", file=sys.stderr)
        return 2
    src = Path(sys.argv[1])
    dst = Path(sys.argv[2])
    profile_id = sys.argv[3] if len(sys.argv) > 3 else "gost-7.32-2017"

    profile = load_profile(profile_id)
    document = parse_docx(src)
    fixes = run_fix(document, profile)
    export_docx(document, profile, dst)

    print(f"Применено правок: {len(fixes)}")
    for f in fixes:
        print(f"  {f.fixer_code}  {f.description}")
    print(f"Сохранено: {dst}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
