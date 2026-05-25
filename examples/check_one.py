"""Программная проверка одного .docx — пример использования gostforge как библиотеки.

Запуск:

    python examples/check_one.py path/to/work.docx [profile-id]
"""
from __future__ import annotations

import sys
from pathlib import Path

from gostforge.parser import parse_docx
from gostforge.profile import load_profile
from gostforge.validator import validate


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: python check_one.py <path.docx> [profile-id]", file=sys.stderr)
        return 2
    path = Path(sys.argv[1])
    profile_id = sys.argv[2] if len(sys.argv) > 2 else "gost-7.32-2017"

    profile = load_profile(profile_id)
    document = parse_docx(path)
    violations = validate(document, profile)

    errors = sum(1 for v in violations if v.severity == "error")
    warnings = sum(1 for v in violations if v.severity == "warning")
    print(f"{path.name}: всего {len(violations)} нарушений ({errors} errors, {warnings} warnings)")
    for v in violations:
        print(f"  [{v.severity.upper():7}] {v.check_code}  {v.message}")
        if v.suggestion:
            print(f"           → {v.suggestion}")
    return 1 if errors > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
