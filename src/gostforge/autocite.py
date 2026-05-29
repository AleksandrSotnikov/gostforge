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

# Каталог распространённых стандартов: нормализованное обозначение → название
# (по официальному наименованию ГОСТа). Для записей из каталога формируется
# полное библиографическое описание по ГОСТ Р 7.0.100-2018; для остальных —
# корректный минимальный скелет (обозначение + издатель + год).
_GOST_CATALOG: dict[str, str] = {
    "ГОСТ 7.32-2017": (
        "Система стандартов по информации, библиотечному и издательскому делу. "
        "Отчёт о научно-исследовательской работе. Структура и правила оформления"
    ),
    "ГОСТ Р 7.0.100-2018": (
        "Система стандартов по информации, библиотечному и издательскому делу. "
        "Библиографическая запись. Библиографическое описание. "
        "Общие требования и правила составления"
    ),
    "ГОСТ Р 7.0.5-2008": (
        "Система стандартов по информации, библиотечному и издательскому делу. "
        "Библиографическая ссылка. Общие требования и правила составления"
    ),
    "ГОСТ 7.1-2003": (
        "Система стандартов по информации, библиотечному и издательскому делу. "
        "Библиографическая запись. Библиографическое описание. "
        "Общие требования и правила составления"
    ),
    "ГОСТ Р 2.105-2019": (
        "Единая система конструкторской документации. Общие требования к текстовым документам"
    ),
    "ГОСТ 2.104-2006": "Единая система конструкторской документации. Основные надписи",
    "ГОСТ Р 8.000-2015": (
        "Государственная система обеспечения единства измерений. Основные положения"
    ),
    "ГОСТ 8.417-2002": ("Государственная система обеспечения единства измерений. Единицы величин"),
}

# Каталог распространённых федеральных законов: номер → (название, дата принятия
# в формате ДД.ММ.ГГГГ). Используется для полного описания и определения года.
_FZ_CATALOG: dict[str, tuple[str, str]] = {
    "152": ("О персональных данных", "27.07.2006"),
    "149": ("Об информации, информационных технологиях и о защите информации", "27.07.2006"),
    "273": ("Об образовании в Российской Федерации", "29.12.2012"),
    "63": ("Об электронной подписи", "06.04.2011"),
    "162": ("О стандартизации в Российской Федерации", "29.06.2015"),
    "44": (
        "О контрактной системе в сфере закупок товаров, работ, услуг "
        "для обеспечения государственных и муниципальных нужд",
        "05.04.2013",
    ),
}

# Сведения о виде содержания и средстве доступа (ГОСТ Р 7.0.100-2018, обяз.).
_MEDIA_NOTE = "Текст : непосредственный."


def _gost_raw(designation: str, year: str) -> str:
    """Сформировать библиографическое описание ГОСТа по ГОСТ Р 7.0.100-2018."""
    title = _GOST_CATALOG.get(designation)
    if title:
        return f"{designation}. {title}. — Москва : Стандартинформ, {year}. — {_MEDIA_NOTE}"
    return f"{designation}. — Москва : Стандартинформ, {year}. — {_MEDIA_NOTE}"


def _fz_raw(num: str, text_date: str | None) -> tuple[str, str | None]:
    """Сформировать описание ФЗ по ГОСТ Р 7.0.100-2018. Возвращает (raw, year).

    Название и дата берутся из каталога (если ФЗ известен); дата из текста
    приоритетна. Если год из текста расходится с каталожным — название не
    подставляется (во избежание ошибочной атрибуции одинаковых номеров).
    """
    catalog = _FZ_CATALOG.get(num)
    title: str | None = None
    catalog_date: str | None = None
    if catalog is not None:
        title, catalog_date = catalog
    if title and text_date and catalog_date and text_date[-4:] != catalog_date[-4:]:
        title = None  # номер совпал, а год — нет: это другой закон
    use_date = text_date or catalog_date
    prefix = f"{title} : " if title else ""
    if use_date:
        raw = f"{prefix}Федеральный закон от {use_date} № {num}-ФЗ. — {_MEDIA_NOTE}"
        return raw, use_date[-4:]
    return f"{prefix}Федеральный закон № {num}-ФЗ. — {_MEDIA_NOTE}", None


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

    # --- ГОСТы (все упомянутые) ---------------------------------------------
    for m in _GOST_RE.finditer(body):
        designation = _normalize_gost(m.group(0))
        year = designation[-4:]
        _add(designation, "standard", _gost_raw(designation, year), {"year": year})

    # --- ФЗ: собираем номера с датой (приоритет) и без --------------------
    fz_dates: dict[str, str | None] = {}
    for m in _FZ_DATED_RE.finditer(body):
        fz_dates.setdefault(m.group(3), m.group(1))
    for m in _FZ_BARE_RE.finditer(body):
        fz_dates.setdefault(m.group(1), None)
    for num, text_date in fz_dates.items():
        fz_raw, fz_year = _fz_raw(num, text_date)
        _add(f"№{num}-ФЗ", "law", fz_raw, {"year": fz_year} if fz_year else {})

    return added
