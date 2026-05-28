"""R.* — проверки списка литературы (ГОСТ Р 7.0.100-2018)."""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any

from gostforge.model import (
    BibliographyEntry,
    Block,
    Document,
    LogicalSection,
    Paragraph,
    TextRun,
)
from gostforge.profile import Profile

from ..engine import Violation, register

# Регэксп для четырёхзначного года издания (1900-2099 — практический диапазон).
_YEAR_RE = re.compile(r"\b(?:19|20)\d{2}\b")

# Символы-разделители ГОСТ Р 7.0.100-2018, ожидаемые внутри библиографической
# записи: длинное и короткое тире, слэш, двоеточие.
_SEPARATORS: tuple[str, ...] = ("—", "–", "/", ":")

# Маркеры доступа для веб-ресурсов («URL:», «(дата обращения:»).
_WEB_URL_MARKERS: tuple[str, ...] = ("URL:", "(дата обращения:")


def _preview(raw: str, *, max_len: int = 60) -> str:
    """Усечённая выдержка для сообщений о нарушениях."""
    if len(raw) <= max_len:
        return raw
    return raw[:max_len].rstrip() + "…"


def _params(profile: Profile) -> dict[str, Any]:
    """Прочитать `checks.R.04.params` из профиля; вернуть пустой dict, если нет."""
    config = profile.checks.get("R.04")
    if config is None:
        return {}
    return dict(config.params)


def _check_params(profile: Profile, code: str) -> dict[str, Any]:
    """Прочитать `checks.<code>.params` из профиля; вернуть пустой dict, если нет."""
    config = profile.checks.get(code)
    if config is None:
        return {}
    return dict(config.params)


def _str_param(params: dict[str, Any], key: str, default: str) -> str:
    """Достать строковый параметр из профиля с дефолтом."""
    value = params.get(key, default)
    if isinstance(value, str):
        return value
    return default


def _float_param(params: dict[str, Any], key: str, default: float) -> float:
    """Достать float-параметр из профиля с дефолтом."""
    value = params.get(key, default)
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _list_str_param(params: dict[str, Any], key: str, default: list[str]) -> list[str]:
    """Достать список строк из профиля; невалидные элементы пропускаются."""
    value = params.get(key)
    if value is None:
        return list(default)
    if isinstance(value, list):
        return [str(item) for item in value if isinstance(item, str)]
    return list(default)


def _bool_param(params: dict[str, Any], key: str, default: bool) -> bool:
    """Достать булев параметр из профиля с дефолтом."""
    value = params.get(key, default)
    if isinstance(value, bool):
        return value
    return default


def _int_param(params: dict[str, Any], key: str, default: int) -> int:
    """Достать целочисленный параметр из профиля с дефолтом."""
    value = params.get(key, default)
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _violation(entry: BibliographyEntry, aspect: str, message: str, suggestion: str) -> Violation:
    """Сконструировать Violation R.04 со стандартизованным location/details."""
    return Violation(
        check_code="R.04",
        severity="error",
        message=message,
        location=f"bibliography[{entry.id}]",
        suggestion=suggestion,
        details={"aspect": aspect, "entry_id": entry.id},
    )


@register("R.04")
def check_bibliography_format(document: Document, profile: Profile) -> list[Violation]:
    """Минимальные признаки формата библиографической записи по ГОСТ Р 7.0.100-2018.

    Проверяет каждую запись `Document.bibliography` на:
      - минимальную длину (`min_length`, по умолчанию 15);
      - наличие четырёхзначного года (1900-2099) — `require_year`;
      - точку в конце записи — `require_final_dot`;
      - хотя бы один структурный разделитель (— – / :) — `require_separator`;
      - для type="web" — маркер «URL:» или «(дата обращения:» —
        `require_url_marker_for_web`.

    Одна запись может породить несколько Violation, по одному на каждый
    нарушенный аспект.
    """
    violations: list[Violation] = []
    params = _params(profile)
    min_length = _int_param(params, "min_length", 15)
    require_year = _bool_param(params, "require_year", True)
    require_final_dot = _bool_param(params, "require_final_dot", True)
    require_separator = _bool_param(params, "require_separator", True)
    require_url_marker_for_web = _bool_param(params, "require_url_marker_for_web", True)

    for entry in document.bibliography:
        raw = entry.fields.get("raw", "").strip()
        preview = _preview(raw if raw else "<пусто>")

        # Минимальная длина (включает пустую строку).
        if len(raw) < min_length:
            violations.append(
                _violation(
                    entry,
                    "length",
                    f"Запись «{preview}» слишком короткая "
                    f"({len(raw)} симв., ожидается ≥ {min_length})",
                    "Расширить запись до полного библиографического описания "
                    "(автор, заглавие, место, издательство, год, страницы)",
                )
            )
            # При слишком короткой записи остальные проверки бессмысленны.
            continue

        if require_year and not _YEAR_RE.search(raw):
            violations.append(
                _violation(
                    entry,
                    "year",
                    f"Запись «{preview}» не содержит года издания",
                    "Указать год издания (четыре цифры, например «2020»)",
                )
            )

        if require_final_dot and not raw.endswith("."):
            violations.append(
                _violation(
                    entry,
                    "final_dot",
                    f"Запись «{preview}» не оканчивается точкой",
                    "Завершить запись точкой",
                )
            )

        if require_separator and not any(sep in raw for sep in _SEPARATORS):
            violations.append(
                _violation(
                    entry,
                    "separator",
                    f"Запись «{preview}» не содержит структурных разделителей "
                    "(тире, слэш или двоеточие)",
                    "Разделить элементы описания по ГОСТ Р 7.0.100-2018: "
                    "автор / заглавие. — Место : Издательство, год. — страницы",
                )
            )

        if (
            require_url_marker_for_web
            and entry.type == "web"
            and not any(marker in raw for marker in _WEB_URL_MARKERS)
        ):
            violations.append(
                _violation(
                    entry,
                    "web_url",
                    f"Запись «{preview}» (электронный ресурс) не содержит "
                    "маркера доступа «URL:» или «(дата обращения:»",
                    "Указать ссылку в формате «URL: <адрес> (дата обращения: ДД.ММ.ГГГГ)»",
                )
            )

    return violations


# --- Утилиты для работы с текстом параграфов ----------------------------


def _iter_paragraphs(items: Sequence[LogicalSection | Block]) -> list[Paragraph]:
    """Рекурсивно собрать все Paragraph (через LogicalSection.children)."""
    result: list[Paragraph] = []
    for item in items:
        if isinstance(item, Paragraph):
            result.append(item)
        elif isinstance(item, LogicalSection):
            result.extend(_iter_paragraphs(item.children))
    return result


def _all_paragraphs(document: Document) -> list[Paragraph]:
    """Все Paragraph документа (плоско, со всех PageSection)."""
    paragraphs: list[Paragraph] = []
    for ps in document.page_sections:
        paragraphs.extend(_iter_paragraphs(ps.content))
    return paragraphs


def _paragraph_text(paragraph: Paragraph) -> str:
    """Склеить весь текст параграфа из TextRun-ов."""
    return "".join(el.text for el in paragraph.content if isinstance(el, TextRun))


def _document_text(document: Document) -> str:
    """Склеить весь текст всех параграфов документа."""
    return "\n".join(_paragraph_text(p) for p in _all_paragraphs(document))


# --- R.01 — стиль ссылок [N] по профилю ---------------------------------

# Паттерн American style: «(Иванов, 2024)» — фамилия с заглавной буквы +
# запятая + год из 4 цифр в круглых скобках.
_AUTHOR_YEAR_RE = re.compile(r"\([А-ЯЁ][а-яё]+,\s*\d{4}\)")

# Паттерн «Иванов 2024» в квадратных скобках — без номера: «[Иванов 2024]».
_AUTHOR_YEAR_BRACKETS_RE = re.compile(r"\[[А-ЯЁ][а-яё]+\s+\d{4}\]")


@register("R.01")
def check_reference_style_numeric(
    document: Document,
    profile: Profile,
) -> list[Violation]:
    """Все библиографические ссылки в тексте должны быть в формате [N] / [N, M] / [N-M].

    Запрещены:
    - American style «(Иванов, 2024)» — фамилия + год в круглых скобках;
    - «author-year» в квадратных скобках «[Иванов 2024]».

    Каждый найденный паттерн порождает отдельный Violation.
    """
    violations: list[Violation] = []

    for paragraph in _all_paragraphs(document):
        text = _paragraph_text(paragraph)
        if not text:
            continue

        for match in _AUTHOR_YEAR_RE.finditer(text):
            violations.append(
                Violation(
                    check_code="R.01",
                    severity="error",
                    message=(
                        f"Ссылка «{match.group(0)}» в стиле «(Автор, год)» — "
                        "по ГОСТ Р 7.0.100-2018 нужен стиль [N]"
                    ),
                    location=f"paragraph[{paragraph.id}]",
                    suggestion=(
                        "Заменить ссылку на формат [N] с номером записи из списка литературы"
                    ),
                    details={
                        "paragraph_id": paragraph.id,
                        "found": match.group(0),
                        "style": "author_year_parens",
                    },
                )
            )

        for match in _AUTHOR_YEAR_BRACKETS_RE.finditer(text):
            violations.append(
                Violation(
                    check_code="R.01",
                    severity="error",
                    message=(
                        f"Ссылка «{match.group(0)}» в стиле «[Автор год]» — "
                        "по ГОСТ Р 7.0.100-2018 нужен стиль [N]"
                    ),
                    location=f"paragraph[{paragraph.id}]",
                    suggestion=(
                        "Заменить ссылку на формат [N] с номером записи из списка литературы"
                    ),
                    details={
                        "paragraph_id": paragraph.id,
                        "found": match.group(0),
                        "style": "author_year_brackets",
                    },
                )
            )

    return violations


# --- R.05 — каждый источник упомянут в тексте ---------------------------

# Поиск ссылки на номер N в любом из форматов: [N], [N,, [N-, [N:.
_ENTRY_REF_RE_TEMPLATE = r"\[\s*{n}\s*(?:[,\-–\]:])"


def _entry_referenced(text: str, num: int) -> bool:
    """True, если в тексте встречается ссылка на источник с номером N."""
    pattern = re.compile(_ENTRY_REF_RE_TEMPLATE.format(n=num))
    return bool(pattern.search(text))


@register("R.05")
def check_each_entry_referenced(
    document: Document,
    profile: Profile,
) -> list[Violation]:
    """Каждая запись bibliography должна быть упомянута в тексте.

    Для каждой записи с index N (1-based порядок в bibliography) ищем в
    тексте всех параграфов конструкции вида `[N]`, `[N,`, `[N-`, `[N:`.
    Если ни одного — Violation severity=warning.
    """
    violations: list[Violation] = []
    if not document.bibliography:
        return violations

    text = _document_text(document)

    for index, entry in enumerate(document.bibliography, start=1):
        if _entry_referenced(text, index):
            continue
        violations.append(
            Violation(
                check_code="R.05",
                severity="warning",
                message=f"Источник [{index}] «{entry.id}» не упомянут в тексте",
                location=f"bibliography[{entry.id}]",
                suggestion=(
                    f"Добавить в текст ссылку вида [{index}] или удалить "
                    f"источник из списка литературы, если он не используется"
                ),
                details={
                    "entry_id": entry.id,
                    "index": str(index),
                },
            )
        )

    return violations


# --- R.06 — каждая ссылка разрешается в источник (alias C.04) ---------


@register("R.06")
def check_references_resolve_alias(
    document: Document,
    profile: Profile,
) -> list[Violation]:
    """Каждая ссылка [N] в тексте должна разрешаться в запись bibliography.

    Дублирует C.04, оставлен для совместимости с каталогом кодов
    (R.06 — «зеркальная» проверка из подсистемы R). Логика полностью
    идентична C.04; чтобы не порождать дубликат Violation, эта проверка
    возвращает пустой список — фактический контроль выполняет C.04.
    """
    # дублирует C.04, оставлен для совместимости
    return []


# --- R.07 — указаны страницы для цитат (заглушка Фазы 2) ----------------


@register("R.07")
def check_citations_have_pages(
    document: Document,
    profile: Profile,
) -> list[Violation]:
    """Прямые цитаты должны сопровождаться указанием страниц (заглушка Фазы 2).

    Эвристика: ссылка вида `[N]` рядом с конструкциями «по мнению»,
    «как указывает», «согласно» — это цитата без страниц; правильный
    формат — `[N, с. M]` или `[N: M]`.

    Полноценная реализация требует синтаксического анализа предложения
    (определить, является ли ссылка прямой цитатой). На Фазе 2 — заглушка.
    """
    return []


# --- R.02 — порядок (алфавит / по упоминанию) ---------------------------


@register("R.02")
def check_bibliography_order(document: Document, profile: Profile) -> list[Violation]:
    """Записи bibliography должны идти в заданном порядке (алфавит / по упоминанию).

    Параметр `checks.R.02.params.order`:
      - "alphabetical" (по умолчанию) — соседние записи сравниваются
        по `fields["author"]` без учёта регистра (русский алфавит).
        Если у записи нет author — пара пропускается.
      - "by_mention" — для каждой пары соседних номеров N и N+1
        проверяется, что N упоминается в тексте раньше N+1.

    При первом несоответствии возвращается единственный Violation.
    """
    if not document.bibliography:
        return []

    params = _check_params(profile, "R.02")
    order = _str_param(params, "order", "alphabetical")

    if order == "alphabetical":
        for prev, curr in zip(document.bibliography, document.bibliography[1:], strict=False):
            prev_author = prev.fields.get("author")
            curr_author = curr.fields.get("author")
            if not prev_author or not curr_author:
                continue
            if prev_author.lower() > curr_author.lower():
                return [
                    Violation(
                        check_code="R.02",
                        severity="warning",
                        message=(
                            f"Нарушен алфавитный порядок: запись «{prev.id}» "
                            f"({prev_author}) идёт раньше «{curr.id}» ({curr_author})"
                        ),
                        location=f"bibliography[{curr.id}]",
                        suggestion=("Расположить записи по алфавиту фамилий первых авторов"),
                        details={
                            "order": "alphabetical",
                            "prev_id": prev.id,
                            "curr_id": curr.id,
                            "prev_author": prev_author,
                            "curr_author": curr_author,
                        },
                    )
                ]
        return []

    if order == "by_mention":
        text = _document_text(document)
        # Карта: индекс источника (1-based) → позиция первого упоминания в тексте.
        positions: dict[int, int] = {}
        for index in range(1, len(document.bibliography) + 1):
            pattern = re.compile(_ENTRY_REF_RE_TEMPLATE.format(n=index))
            match = pattern.search(text)
            if match is not None:
                positions[index] = match.start()
        # Перебираем пары соседних номеров N и N+1, у которых обе позиции
        # известны: первое упоминание N должно предшествовать N+1.
        for index in range(1, len(document.bibliography)):
            pos_prev = positions.get(index)
            pos_next = positions.get(index + 1)
            if pos_prev is None or pos_next is None:
                continue
            if pos_prev > pos_next:
                prev = document.bibliography[index - 1]
                curr = document.bibliography[index]
                return [
                    Violation(
                        check_code="R.02",
                        severity="warning",
                        message=(
                            f"Источник [{index}] упомянут в тексте позже, чем "
                            f"[{index + 1}] — нарушен порядок «по упоминанию»"
                        ),
                        location=f"bibliography[{curr.id}]",
                        suggestion=(
                            "Перенумеровать записи bibliography в порядке "
                            "первого упоминания в тексте"
                        ),
                        details={
                            "order": "by_mention",
                            "prev_id": prev.id,
                            "curr_id": curr.id,
                            "prev_index": str(index),
                            "curr_index": str(index + 1),
                        },
                    )
                ]
        return []

    # Неизвестное значение параметра order — мягкая деградация, без падения.
    return []


# --- R.03 — обязательные поля для типа источника ------------------------


@register("R.03")
def check_required_fields_by_type(document: Document, profile: Profile) -> list[Violation]:
    """Для каждого type должны быть заполнены обязательные поля.

    Параметр `checks.R.03.params.required_by_type: dict[str, list[str]]`
    задаёт для каждого типа источника список обязательных полей. Например::

        {"book": ["author", "year", "place"],
         "article": ["author", "year"],
         "web": ["url", "access_date"]}

    Если type записи не описан в params — запись пропускается.
    Каждое отсутствующее поле даёт отдельный Violation.
    """
    violations: list[Violation] = []
    params = _check_params(profile, "R.03")
    raw_required = params.get("required_by_type")
    if not isinstance(raw_required, dict):
        return []
    # Приведём dict к ожидаемой структуре: {str: list[str]}.
    required_by_type: dict[str, list[str]] = {}
    for type_name, fields in raw_required.items():
        if not isinstance(type_name, str) or not isinstance(fields, list):
            continue
        required_by_type[type_name] = [f for f in fields if isinstance(f, str)]

    for entry in document.bibliography:
        required = required_by_type.get(entry.type)
        if required is None:
            continue
        for field_name in required:
            value = entry.fields.get(field_name)
            if value:
                continue
            violations.append(
                Violation(
                    check_code="R.03",
                    severity="error",
                    message=(
                        f"Запись {entry.id} (тип {entry.type}): отсутствует поле `{field_name}`"
                    ),
                    location=f"bibliography[{entry.id}]",
                    suggestion=(
                        f"Дополнить запись данными по полю `{field_name}` "
                        f"в соответствии с ГОСТ Р 7.0.100-2018"
                    ),
                    details={
                        "entry_id": entry.id,
                        "entry_type": entry.type,
                        "missing_field": field_name,
                    },
                )
            )
    return violations


# --- R.08 — дата обращения для электронных ------------------------------


@register("R.08")
def check_access_date_for_web(
    document: Document,
    profile: Profile,
) -> list[Violation]:
    """Электронные ресурсы должны содержать дату обращения.

    Запись считается электронной, если её type == "web" или в полях есть
    url (например, у статьи с DOI и онлайн-версией). Отсутствие
    `access_date` — error.
    """
    violations: list[Violation] = []
    for entry in document.bibliography:
        is_web = entry.type == "web" or "url" in entry.fields
        if not is_web:
            continue
        if entry.fields.get("access_date"):
            continue
        violations.append(
            Violation(
                check_code="R.08",
                severity="error",
                message=(f"Запись {entry.id} (электронный ресурс) не содержит даты обращения"),
                location=f"bibliography[{entry.id}]",
                suggestion=(
                    "Добавить «(дата обращения: ДД.ММ.ГГГГ)» после URL по ГОСТ Р 7.0.100-2018"
                ),
                details={
                    "entry_id": entry.id,
                    "entry_type": entry.type,
                },
            )
        )
    return violations


# --- R.09 — DOI/URL для современных источников --------------------------


@register("R.09")
def check_doi_or_url_for_modern(document: Document, profile: Profile) -> list[Violation]:
    """У современных источников (год ≥ modern_year) ожидается DOI или URL.

    Параметр `checks.R.09.params.modern_year` (по умолчанию 2020).
    Severity = info — это рекомендация, не жёсткое требование.
    """
    violations: list[Violation] = []
    params = _check_params(profile, "R.09")
    modern_year = _int_param(params, "modern_year", 2020)

    for entry in document.bibliography:
        year_str = entry.fields.get("year")
        if not year_str:
            continue
        try:
            year = int(year_str)
        except ValueError:
            continue
        if year < modern_year:
            continue
        if entry.fields.get("doi") or entry.fields.get("url"):
            continue
        violations.append(
            Violation(
                check_code="R.09",
                severity="info",
                message=(
                    f"Запись {entry.id} ({year}) не содержит DOI или URL — "
                    "для современных источников желательно указывать ссылку"
                ),
                location=f"bibliography[{entry.id}]",
                suggestion=(
                    "Добавить DOI (формат «10.NNNN/...») или URL к электронной версии источника"
                ),
                details={
                    "entry_id": entry.id,
                    "year": year_str,
                    "modern_year": str(modern_year),
                },
            )
        )
    return violations


# --- R.10 — доля свежих источников ≥ N% ---------------------------------


@register("R.10")
def check_fresh_sources_share(document: Document, profile: Profile) -> list[Violation]:
    """Не менее заданной доли источников должны быть «свежими».

    Параметры:
      - `fresh_year_threshold` (по умолчанию текущий_год − 10)
      - `min_fresh_share` (по умолчанию 0.5 — половина)

    Источники без года не учитываются ни в числителе, ни в знаменателе
    (мы знаем только про датируемые записи). Если bibliography пустая или
    нет ни одной записи с годом — нарушения нет.
    """
    if not document.bibliography:
        return []

    params = _check_params(profile, "R.10")
    # По умолчанию используем границу «10 лет назад» от условной точки
    # 2025 (актуальная дата проекта); параметр fresh_year_threshold
    # должен задаваться явно в профиле.
    fresh_year_threshold = _int_param(params, "fresh_year_threshold", 2015)
    min_fresh_share = _float_param(params, "min_fresh_share", 0.5)

    dated: list[int] = []
    fresh = 0
    for entry in document.bibliography:
        year_str = entry.fields.get("year")
        if not year_str:
            continue
        try:
            year = int(year_str)
        except ValueError:
            continue
        dated.append(year)
        if year >= fresh_year_threshold:
            fresh += 1

    if not dated:
        return []

    share = fresh / len(dated)
    if share >= min_fresh_share:
        return []

    return [
        Violation(
            check_code="R.10",
            severity="warning",
            message=(
                f"Только {share * 100:.0f}% источников от {fresh_year_threshold} "
                f"года и новее, ожидается ≥ {min_fresh_share * 100:.0f}%"
            ),
            location="bibliography",
            suggestion=("Добавить более свежие источники (научные публикации за последние годы)"),
            details={
                "fresh_count": str(fresh),
                "dated_count": str(len(dated)),
                "share": f"{share:.3f}",
                "min_fresh_share": f"{min_fresh_share:.3f}",
                "fresh_year_threshold": str(fresh_year_threshold),
            },
        )
    ]


# --- R.11 — минимальное число источников --------------------------------


@register("R.11")
def check_min_sources(document: Document, profile: Profile) -> list[Violation]:
    """В bibliography должно быть не менее `min_sources` записей.

    Параметр `checks.R.11.params.min_sources` (по умолчанию 20).
    """
    params = _check_params(profile, "R.11")
    min_sources = _int_param(params, "min_sources", 20)
    actual = len(document.bibliography)
    if actual >= min_sources:
        return []
    return [
        Violation(
            check_code="R.11",
            severity="warning",
            message=(f"В списке литературы {actual} источников, ожидается не менее {min_sources}"),
            location="bibliography",
            suggestion=(f"Дополнить список литературы до {min_sources} источников"),
            details={
                "actual": str(actual),
                "min_sources": str(min_sources),
            },
        )
    ]


# --- R.12 — соотношение русско-/иноязычных источников -------------------


@register("R.12")
def check_language_ratio(document: Document, profile: Profile) -> list[Violation]:
    """Доля иноязычных источников должна лежать в допустимом диапазоне.

    Параметры:
      - `max_foreign_share` (по умолчанию 0.5) — верхняя граница доли «en».
      - `min_foreign_share` (по умолчанию 0.1) — нижняя граница доли «en»
        (для научных работ; для гуманитарных можно ставить 0).

    Записи без поля language не учитываются.
    """
    if not document.bibliography:
        return []

    params = _check_params(profile, "R.12")
    max_foreign_share = _float_param(params, "max_foreign_share", 0.5)
    min_foreign_share = _float_param(params, "min_foreign_share", 0.1)

    languages = [entry.fields.get("language") for entry in document.bibliography]
    typed = [lang for lang in languages if lang in {"ru", "en"}]
    if not typed:
        return []
    foreign = sum(1 for lang in typed if lang == "en")
    share = foreign / len(typed)

    if share > max_foreign_share:
        return [
            Violation(
                check_code="R.12",
                severity="info",
                message=(
                    f"Доля иноязычных источников {share * 100:.0f}% превышает "
                    f"допустимые {max_foreign_share * 100:.0f}%"
                ),
                location="bibliography",
                suggestion=(
                    "Увеличить долю русскоязычных источников или скорректировать "
                    "профиль (`max_foreign_share`)"
                ),
                details={
                    "foreign": str(foreign),
                    "total": str(len(typed)),
                    "share": f"{share:.3f}",
                    "max_foreign_share": f"{max_foreign_share:.3f}",
                    "bound": "max",
                },
            )
        ]
    if share < min_foreign_share:
        return [
            Violation(
                check_code="R.12",
                severity="info",
                message=(
                    f"Доля иноязычных источников {share * 100:.0f}% ниже "
                    f"ожидаемых {min_foreign_share * 100:.0f}%"
                ),
                location="bibliography",
                suggestion=(
                    "Добавить иностранные источники по теме исследования (монографии, статьи)"
                ),
                details={
                    "foreign": str(foreign),
                    "total": str(len(typed)),
                    "share": f"{share:.3f}",
                    "min_foreign_share": f"{min_foreign_share:.3f}",
                    "bound": "min",
                },
            )
        ]
    return []


# --- R.13 — нет источников с подозрительных доменов ---------------------


_DEFAULT_SUSPICIOUS_DOMAINS: list[str] = [
    "wikipedia.org",
    "ru.wikipedia.org",
    "answers.com",
    "otvet.mail.ru",
    "studopedia.ru",
    "studwood.net",
    "studfile.net",
]


@register("R.13")
def check_suspicious_domains(document: Document, profile: Profile) -> list[Violation]:
    """В источниках не должно быть ссылок на низкокачественные домены.

    Параметр `checks.R.13.params.suspicious_domains: list[str]` —
    список доменов, на которые ссылаться не следует (Википедия,
    студенческие шпаргалки и т.п.).
    """
    violations: list[Violation] = []
    params = _check_params(profile, "R.13")
    suspicious = _list_str_param(params, "suspicious_domains", _DEFAULT_SUSPICIOUS_DOMAINS)
    if not suspicious:
        return []

    for entry in document.bibliography:
        url = entry.fields.get("url")
        if not url:
            continue
        url_lower = url.lower()
        matched: str | None = None
        for domain in suspicious:
            if domain.lower() in url_lower:
                matched = domain
                break
        if matched is None:
            continue
        violations.append(
            Violation(
                check_code="R.13",
                severity="warning",
                message=(
                    f"Запись {entry.id} ссылается на подозрительный домен "
                    f"«{matched}» — не подходит для научной работы"
                ),
                location=f"bibliography[{entry.id}]",
                suggestion=(
                    "Заменить источник на рецензируемую публикацию: "
                    "монографию, статью в журнале или сборнике конференции"
                ),
                details={
                    "entry_id": entry.id,
                    "domain": matched,
                    "url": url,
                },
            )
        )
    return violations


# Регексы валидации формата DOI/URL.
# DOI: '10.NNNN/...' (стандарт https://www.doi.org/doi_handbook/2_Numbering.html).
_DOI_FORMAT_RE = re.compile(r"^10\.\d{4,9}/\S+$")
# URL: http(s):// + домен.
_URL_FORMAT_RE = re.compile(r"^https?://[^\s/$.?#].\S*$", re.IGNORECASE)
# DOI, обёрнутый в URL ("https://doi.org/10.NNNN/..." или
# "doi.org/10.NNNN/...") — частая ошибка: в поле DOI кладут ссылку.
_DOI_AS_URL_RE = re.compile(
    r"^(?:https?://)?(?:dx\.)?doi\.org/(10\.\d{4,9}/\S+)$",
    re.IGNORECASE,
)
# Типичные опечатки в URL (схема без двоеточия / двоеточие без слешей и пр.).
_URL_TYPO_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(r"^https?//", re.IGNORECASE),
        "пропущено двоеточие в схеме: `https//` вместо `https://`",
    ),
    (
        re.compile(r"^https?:/[^/]", re.IGNORECASE),
        "пропущен слэш в схеме: `https:/x` вместо `https://x`",
    ),
    (re.compile(r"^https?;//", re.IGNORECASE), "точка с запятой вместо двоеточия в схеме"),
    # Специфичные опечатки в схеме. Порядок важен: более длинный
    # паттерн `htps://` (без второй `t` в `https`) должен матчиться
    # раньше, чем `htp://`, иначе `htps://...` подцепится как `htp` +
    # «лишний `s`».
    (re.compile(r"^htps://", re.IGNORECASE), "опечатка в схеме: `htps` вместо `https`"),
    (re.compile(r"^htp://", re.IGNORECASE), "опечатка в схеме: `htp` вместо `http`"),
)


def _diagnose_doi_format(doi: str) -> str | None:
    """Найти конкретную ошибку в формате DOI или None если всё ок.

    Различает: пробелы в начале/конце, обёрнутый в URL DOI («https://doi.org/...»),
    отсутствие префикса 10.NNNN/, общий «не тот формат».
    """
    if not doi:
        return None
    if doi != doi.strip():
        return "лишние пробелы в начале или конце"
    if " " in doi or "\t" in doi:
        return "пробелы или табы внутри значения"
    if _DOI_AS_URL_RE.match(doi):
        # «https://doi.org/10.1234/abc» — частая ошибка, в поле DOI должен
        # быть «голый» идентификатор без https://.
        return "DOI обёрнут в URL — оставьте только идентификатор после `doi.org/`"
    if _DOI_FORMAT_RE.match(doi):
        return None
    if not doi.startswith("10."):
        return "DOI должен начинаться с «10.» (например, «10.1234/abc»)"
    if "/" not in doi:
        return "после префикса «10.NNNN» должен быть `/` и идентификатор"
    return "не соответствует стандарту «10.NNNN/...»"


def _diagnose_url_format(url: str) -> str | None:
    """Найти конкретную ошибку в формате URL или None если всё ок.

    Ловит типичные опечатки (https//, http;//, htp://) и даёт явное
    сообщение вместо общего «не тот формат».
    """
    if not url:
        return None
    if url != url.strip():
        return "лишние пробелы в начале или конце"
    if " " in url or "\t" in url:
        return "пробелы или табы внутри URL"
    for pattern, msg in _URL_TYPO_PATTERNS:
        if pattern.match(url):
            return msg
    if _URL_FORMAT_RE.match(url):
        return None
    if not url.lower().startswith(("http://", "https://")):
        return "URL должен начинаться с `http://` или `https://`"
    return "не соответствует формату `https://domain/path`"


@register("R.14")
def check_doi_url_format(document: Document, profile: Profile) -> list[Violation]:
    """Валидация формата DOI и URL в записях библиографии.

    Сообщение нарушения содержит **конкретную** диагностику ошибки:
    лишние пробелы, DOI обёрнут в URL, типовая опечатка в схеме
    (`https//` без двоеточия, `htp://`, `http;//`), отсутствие
    префикса `10.` и т. п. — пользователь сразу видит, что чинить,
    без необходимости знать формат DOI наизусть.

    Severity = warning — это не критическая ошибка, но почти всегда
    указывает на опечатку при копировании из PDF/Word.

    Параметров профиля нет.
    """
    _ = profile
    violations: list[Violation] = []
    for idx, entry in enumerate(document.bibliography, start=1):
        doi = entry.fields.get("doi")
        if doi:
            problem = _diagnose_doi_format(doi)
            if problem:
                violations.append(
                    Violation(
                        check_code="R.14",
                        severity="warning",
                        message=f"Источник {idx}: DOI «{doi}» — {problem}",
                        location=f"bibliography[{entry.id}].doi",
                        suggestion=(
                            "DOI должен быть «голым» идентификатором вида "
                            "«10.NNNN/suffix» без https://doi.org/ и без пробелов "
                            "(подробнее: https://www.doi.org)"
                        ),
                        details={"entry_id": entry.id, "doi": doi, "problem": problem},
                    )
                )
        url = entry.fields.get("url")
        if url:
            problem = _diagnose_url_format(url)
            if problem:
                violations.append(
                    Violation(
                        check_code="R.14",
                        severity="warning",
                        message=f"Источник {idx}: URL «{url}» — {problem}",
                        location=f"bibliography[{entry.id}].url",
                        suggestion=(
                            "URL должен быть полным: `https://domain/path` "
                            "(или `http://...`), без пробелов и опечаток в схеме"
                        ),
                        details={"entry_id": entry.id, "url": url, "problem": problem},
                    )
                )
    return violations


__all__ = [
    "check_access_date_for_web",
    "check_bibliography_format",
    "check_bibliography_order",
    "check_citations_have_pages",
    "check_doi_or_url_for_modern",
    "check_doi_url_format",
    "check_each_entry_referenced",
    "check_fresh_sources_share",
    "check_language_ratio",
    "check_min_sources",
    "check_reference_style_numeric",
    "check_references_resolve_alias",
    "check_required_fields_by_type",
    "check_suspicious_domains",
]
