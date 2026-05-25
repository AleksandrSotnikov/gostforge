"""Пакетная проверка папки с .docx-файлами и сводный отчёт.

Запуск:

    python examples/batch_check.py path/to/folder/ [profile-id]

Выводит таблицу: имя файла | число нарушений | топ-5 кодов.
"""
from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

from gostforge.parser import parse_docx
from gostforge.profile import load_profile
from gostforge.validator import validate


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: python batch_check.py <folder> [profile-id]", file=sys.stderr)
        return 2
    folder = Path(sys.argv[1])
    profile_id = sys.argv[2] if len(sys.argv) > 2 else "gost-7.32-2017"

    if not folder.is_dir():
        print(f"Не папка: {folder}", file=sys.stderr)
        return 2

    profile = load_profile(profile_id)

    docs = sorted(folder.glob("*.docx"))
    if not docs:
        print(f"Нет .docx в {folder}")
        return 0

    print(f"{'Файл':<40} {'Ошибки':>7} {'Предупр.':>9}  Топ-5 кодов")
    print("-" * 80)
    total_errors = 0
    for path in docs:
        try:
            document = parse_docx(path)
            violations = validate(document, profile)
        except Exception as e:  # noqa: BLE001
            print(f"{path.name:<40} ERROR: {e}")
            continue
        errs = sum(1 for v in violations if v.severity == "error")
        warns = sum(1 for v in violations if v.severity == "warning")
        top_codes = Counter(v.check_code for v in violations).most_common(5)
        codes_str = ", ".join(f"{c}×{n}" for c, n in top_codes)
        print(f"{path.name[:39]:<40} {errs:>7} {warns:>9}  {codes_str}")
        total_errors += errs

    print(f"\nИтого: {len(docs)} файлов, {total_errors} ошибок суммарно")
    return 1 if total_errors > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
