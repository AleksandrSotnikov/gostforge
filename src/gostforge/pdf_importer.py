# ruff: noqa: RUF001, RUF002, RUF003

"""Импорт PDF в state-конструктора.

Извлекает структуру (заголовки + параграфы) из PDF через pdfplumber.
Форматирование (шрифты, цвета) не сохраняется — только текстовая
структура, которую студент дальше довёрстывает по ГОСТу в
конструкторе.

Требует опциональной зависимости::

    pip install gostforge[import-formats]

Эвристика заголовков: строка считается заголовком, если она короткая
(< 80 символов), без точки в конце, и либо ВЕРХНИМ регистром, либо
начинается с номера раздела («1 Анализ», «1.1 Подраздел»).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any


class PdfImportError(RuntimeError):
    """Ошибка импорта PDF (нет pdfplumber, битый файл и т. п.)."""


# Эвристики распознавания заголовков.
_HEADING_NUMBER_RE = re.compile(r"^\d+(\.\d+){0,3}\.?\s+\S")
_STRUCTURAL_HEADINGS = {
    "введение",
    "заключение",
    "содержание",
    "реферат",
    "список использованных источников",
    "список литературы",
    "литература",
    "приложение",
}


def _looks_like_heading(line: str) -> tuple[bool, int]:
    """Определить, является ли строка заголовком, и его уровень.

    Возвращает (is_heading, level). level: 1 для глав/структурных,
    2/3 для подразделов по числу точек в номере.
    """
    s = line.strip()
    if not s or len(s) > 80:
        return False, 0
    # Структурный раздел.
    low = s.lower().rstrip(".")
    if low in _STRUCTURAL_HEADINGS or low.startswith("приложение"):
        return True, 1
    # Номерованный заголовок: «1 X», «1.1 X», «1.1.1 X».
    m = _HEADING_NUMBER_RE.match(s)
    if m:
        number_part = s.split()[0].rstrip(".")
        level = number_part.count(".") + 1
        return True, min(level, 3)
    # ВЕРХНИЙ регистр без точки в конце — вероятно заголовок.
    if s == s.upper() and not s.endswith(".") and len(s.split()) <= 12:
        return True, 1
    return False, 0


def import_pdf_to_state(
    pdf_path: str | Path,
    *,
    profile_id: str = "gost-7.32-2017",
    title: str | None = None,
) -> dict[str, Any]:
    """Извлечь структуру PDF в state-словарь конструктора.

    Параметры
    ---------
    pdf_path:
        Путь к .pdf-файлу.
    profile_id:
        Профиль для итогового state.
    title:
        Название работы. Если None — берётся из первой непустой строки
        или имени файла.

    Возвращает state-dict (как у конструктора): title/profile_id/
    sections[] с blocks[].

    Исключения
    ----------
    PdfImportError
        pdfplumber не установлен или PDF не читается.
    FileNotFoundError
        Файл не существует.
    """
    pdf_path = Path(pdf_path)
    if not pdf_path.is_file():
        raise FileNotFoundError(f"Файл не найден: {pdf_path}")

    try:
        import pdfplumber  # type: ignore[import-not-found]
    except ImportError as exc:
        raise PdfImportError(
            "Для импорта PDF нужна зависимость pdfplumber. Установите: "
            'pip install "gostforge[import-formats]"'
        ) from exc

    lines: list[str] = []
    try:
        with pdfplumber.open(str(pdf_path)) as pdf:
            for page in pdf.pages:
                text = page.extract_text() or ""
                for raw_line in text.split("\n"):
                    line = raw_line.strip()
                    if line:
                        lines.append(line)
    except Exception as exc:
        raise PdfImportError(f"Не удалось прочитать PDF: {exc}") from exc

    state: dict[str, Any] = {
        "title": title or "",
        "year": 2026,
        "profile_id": profile_id,
        "sections": [],
    }

    # Если title не задан — первая строка-заголовок или имя файла.
    if not state["title"]:
        state["title"] = pdf_path.stem

    sections: list[dict[str, Any]] = state["sections"]
    current_section: dict[str, Any] | None = None
    para_buffer: list[str] = []

    def flush_paragraph() -> None:
        nonlocal para_buffer
        if para_buffer and current_section is not None:
            text = " ".join(para_buffer).strip()
            if text:
                current_section.setdefault("blocks", []).append({"kind": "paragraph", "text": text})
        para_buffer = []

    for line in lines:
        is_heading, _level = _looks_like_heading(line)
        in_bib = current_section is not None and current_section.get("is_bibliography")
        # Внутри библиографии нумерованные строки («1. Иванов…») — это
        # записи источников, а не заголовки. Заголовком, обрывающим
        # список, считаем только структурный раздел или ВЕРХНИЙ регистр
        # (например, «Приложение А»).
        if in_bib and is_heading:
            stripped = line.strip()
            low = stripped.lower().rstrip(".")
            is_structural = low in _STRUCTURAL_HEADINGS or low.startswith("приложение")
            is_upper = stripped == stripped.upper() and not stripped.endswith(".")
            if not (is_structural or is_upper):
                is_heading = False
        if is_heading:
            flush_paragraph()
            is_bib = line.strip().lower().rstrip(".") in {
                "список использованных источников",
                "список литературы",
                "литература",
            }
            current_section = {
                "heading": line.strip(),
                "blocks": [],
            }
            if is_bib:
                current_section["is_bibliography"] = True
                current_section["references"] = []
            sections.append(current_section)
        else:
            if current_section is None:
                # Текст до первого заголовка — создаём «Введение».
                current_section = {"heading": "Введение", "blocks": []}
                sections.append(current_section)
            if current_section.get("is_bibliography"):
                # В bib-разделе каждая строка — отдельная ссылка.
                current_section.setdefault("references", []).append(line.strip())
            else:
                para_buffer.append(line)

    flush_paragraph()
    return state
