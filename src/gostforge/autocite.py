"""Авто-наполнение списка литературы упомянутыми ГОСТами и ФЗ.

Сканирует текст документа, находит упоминания стандартов
(«ГОСТ 7.32-2017», «ГОСТ Р 2.105-2019», …) и федеральных законов
(«Федеральный закон … № 152-ФЗ»), и добавляет недостающие в
`Document.bibliography` и в раздел «Список использованных источников».

Идемпотентно: повторный запуск (в т.ч. при пересборке того же файла,
импортированного с уже добавленными записями) не создаёт дубликатов —
дедупликация по нормализованному обозначению ГОСТа / номеру ФЗ против
существующих записей библиографии.
"""

from __future__ import annotations

import re

from gostforge.model import (
    BibliographyEntry,
    Block,
    Document,
    LogicalSection,
    Paragraph,
    TextRun,
)

# Алиасы заголовка раздела со списком литературы (как в builder/parser).
_BIBLIOGRAPHY_HEADINGS: frozenset[str] = frozenset(
    {
        "список использованных источников",
        "список литературы",
        "литература",
        "список источников",
        "библиографический список",
    }
)

# «ГОСТ 7.32-2017», «ГОСТ Р 2.105-2019», «ГОСТ Р 7.0.100-2018», «ГОСТ 2.104-2006».
_GOST_RE = re.compile(r"ГОСТ(?:\s+Р)?\s+\d+(?:\.\d+)*\s*[-–—]\s*\d{4}")
# ФЗ с датой: «… от 27.07.2006 № 152-ФЗ».
_FZ_DATED_RE = re.compile(
    r"от\s+(\d{1,2}\.\d{1,2}\.(\d{4}))\s*(?:г\.?)?\s*№\s*(\d{1,4})\s*[-–—]\s*ФЗ",
    re.IGNORECASE,
)
# ФЗ без даты: «№ 149-ФЗ», «149-ФЗ».
_FZ_BARE_RE = re.compile(r"(?:№\s*)?(\d{1,4})\s*[-–—]\s*ФЗ", re.IGNORECASE)


def _normalize_gost(text: str) -> str:
    """Каноническая форма обозначения ГОСТа для сравнения и вывода."""
    t = re.sub(r"[–—]", "-", text)  # тире → дефис
    t = re.sub(r"\s*-\s*", "-", t)  # убрать пробелы вокруг дефиса
    t = re.sub(r"\s+", " ", t).strip()
    return t


def _paragraph_text(para: Paragraph) -> str:
    return "".join(el.text for el in para.content if isinstance(el, TextRun))


def _iter_paragraphs(items: list[LogicalSection | Block]) -> list[Paragraph]:
    """Рекурсивно собрать все Paragraph (включая вложенные подразделы)."""
    result: list[Paragraph] = []
    for item in items:
        if isinstance(item, Paragraph):
            result.append(item)
        elif isinstance(item, LogicalSection):
            result.extend(_iter_paragraphs(item.children))
    return result


def _find_bibliography_section(document: Document) -> LogicalSection | None:
    """Найти логический раздел со списком литературы (по алиасам заголовка)."""
    for ps in document.page_sections:
        for child in ps.content:
            if isinstance(child, LogicalSection):
                heading = (
                    "".join(el.text for el in child.heading if isinstance(el, TextRun))
                    .strip()
                    .lower()
                )
                if heading in _BIBLIOGRAPHY_HEADINGS:
                    return child
    return None


def _existing_keys(document: Document) -> set[str]:
    """Множество ключей (ГОСТ/ФЗ), уже представленных в библиографии.

    Ключи извлекаются из raw-текста записей, поэтому дедупликация
    устойчива к различиям форматирования (тире/дефис, пробелы).
    """
    keys: set[str] = set()
    for entry in document.bibliography:
        raw = entry.fields.get("raw", "")
        for m in _GOST_RE.finditer(raw):
            keys.add(_normalize_gost(m.group(0)))
        for m in _FZ_DATED_RE.finditer(raw):
            keys.add(f"№{m.group(3)}-ФЗ")
        for m in _FZ_BARE_RE.finditer(raw):
            keys.add(f"№{m.group(1)}-ФЗ")
    return keys


def _body_text(document: Document, bib_section: LogicalSection | None) -> str:
    """Весь текст документа, кроме самого раздела библиографии."""
    parts: list[str] = []
    for ps in document.page_sections:
        for child in ps.content:
            if child is bib_section:
                continue
            if isinstance(child, Paragraph):
                parts.append(_paragraph_text(child))
            elif isinstance(child, LogicalSection):
                parts.extend(_paragraph_text(p) for p in _iter_paragraphs([child]))
    return "\n".join(parts)


def _unique_id(base: str, used: set[str]) -> str:
    """Сгенерировать уникальный id записи на основе base."""
    candidate = base
    i = 2
    while candidate in used:
        candidate = f"{base}-{i}"
        i += 1
    used.add(candidate)
    return candidate


def autofill_references(document: Document) -> list[BibliographyEntry]:
    """Добавить упомянутые в тексте ГОСТ/ФЗ в список литературы.

    Возвращает список добавленных записей (пустой, если новых нет).
    Идемпотентна: повторный вызов на том же документе ничего не добавит.
    Если раздела библиографии нет — записи всё равно добавляются в
    `document.bibliography` (для нормоконтроля), но без видимого абзаца.
    """
    bib_section = _find_bibliography_section(document)
    body = _body_text(document, bib_section)

    seen = _existing_keys(document)
    used_ids = {e.id for e in document.bibliography}
    added: list[BibliographyEntry] = []

    def _add(key: str, entry_type: str, raw: str, fields_extra: dict[str, str]) -> None:
        if key in seen:
            return
        seen.add(key)
        slug = re.sub(r"[^0-9A-Za-zА-Яа-я]+", "-", key).strip("-").lower()
        entry_id = _unique_id(f"autoref-{entry_type}-{slug}", used_ids)
        fields = {"raw": raw, "designation": key, **fields_extra}
        entry = BibliographyEntry(id=entry_id, type=entry_type, fields=fields)  # type: ignore[arg-type]
        document.bibliography.append(entry)
        if bib_section is not None:
            bib_section.children.append(Paragraph(id=entry_id, content=[TextRun(text=raw)]))
        added.append(entry)

    # --- ГОСТы ---------------------------------------------------------------
    for m in _GOST_RE.finditer(body):
        designation = _normalize_gost(m.group(0))
        year = designation[-4:]
        raw = f"{designation}. — Москва : Стандартинформ, {year}."
        _add(designation, "standard", raw, {"year": year})

    # --- ФЗ с датой (приоритетно, чтобы захватить год) -----------------------
    dated_numbers: set[str] = set()
    for m in _FZ_DATED_RE.finditer(body):
        date, year, num = m.group(1), m.group(2), m.group(3)
        dated_numbers.add(num)
        key = f"№{num}-ФЗ"
        raw = f"Федеральный закон от {date} № {num}-ФЗ. — Текст : непосредственный."
        _add(key, "law", raw, {"year": year})

    # --- ФЗ без даты (если номер ещё не встречался с датой) ------------------
    for m in _FZ_BARE_RE.finditer(body):
        num = m.group(1)
        if num in dated_numbers:
            continue
        key = f"№{num}-ФЗ"
        raw = f"Федеральный закон № {num}-ФЗ. — Текст : непосредственный."
        _add(key, "law", raw, {})

    return added
