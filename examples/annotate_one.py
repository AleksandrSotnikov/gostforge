"""Генерация аннотированного .docx с пометками о нарушениях.

Запуск:

    python examples/annotate_one.py work.docx annotated.docx
"""
from __future__ import annotations

import sys
from pathlib import Path

from gostforge.annotator import annotate_docx
from gostforge.profile import load_profile


def main() -> int:
    if len(sys.argv) < 3:
        print("Usage: python annotate_one.py <input.docx> <output.docx>", file=sys.stderr)
        return 2
    src = Path(sys.argv[1])
    dst = Path(sys.argv[2])
    profile_id = sys.argv[3] if len(sys.argv) > 3 else "gost-7.32-2017"

    profile = load_profile(profile_id)
    n = annotate_docx(src, dst, profile)
    print(f"Создано {n} пометок в {dst}")
    print("Откройте файл в Word — пометки выделены красным курсивом.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
