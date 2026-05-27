"""K.* — проверки колонтитулов и нумерации на уровне PageSection-ов.

Эти проверки работают с :class:`PageSection`-ами (секциями вёрстки):
их колонтитулами (``header``/``footer``) и настройками нумерации
(``page_numbering``). Они отличаются от F.* тем, что F.* рассматривает
параметры страницы (геометрию, формат), а K.* — контекст внутри секции.

Контракт каждой проверки: ``check(model, profile) -> list[Violation]``.
"""

from __future__ import annotations

from collections.abc import Sequence

from gostforge.model import (
    ContentTemplate,
    CrossRef,
    Document,
    InlineElement,
    LogicalSection,
    PageSection,
    TextRun,
)
from gostforge.profile import Profile

from ..engine import Violation, register

# --- Утилиты ------------------------------------------------------------------


def _inline_to_text(inline: list[InlineElement] | None) -> str:
    """Склеить inline-контент в plain-текст для эвристических проверок."""
    if not inline:
        return ""
    parts: list[str] = []
    for el in inline:
        if isinstance(el, TextRun):
            parts.append(el.text)
        elif isinstance(el, CrossRef):
            parts.append(el.display_template)
    return "".join(parts)


def _content_template_text(template: ContentTemplate | None) -> str:
    """Склеить весь контент шаблона колонтитула (left+center+right)."""
    if template is None:
        return ""
    return " ".join(
        filter(
            None,
            (
                _inline_to_text(template.left),
                _inline_to_text(template.center),
                _inline_to_text(template.right),
            ),
        )
    )


# --- K.02 — на титульном листе нет номера ------------------------------------


@register("K.02")
def check_title_has_no_page_number(document: Document, profile: Profile) -> list[Violation]:
    """На титульном листе (``type == "title"``) номер страницы не печатается.

    ГОСТ 7.32-2017 п. 6.1.1: на титульном листе номер не проставляется,
    хотя страница учитывается при сквозной нумерации.
    """
    violations: list[Violation] = []
    for section in document.page_sections:
        if section.type != "title":
            continue
        if section.page_numbering.visible:
            violations.append(
                Violation(
                    check_code="K.02",
                    severity="error",
                    message=(
                        f"На титульном листе (секция «{section.name}») включена нумерация страницы"
                    ),
                    location=(f"page_sections.{section.id}.page_numbering.visible"),
                    suggestion="Отключить отображение номера на титульном листе",
                    details={"expected": "False", "actual": "True"},
                )
            )
    return violations


# --- K.03 — нумерация начинается с правильной страницы -----------------------


def _first_main_section(document: Document) -> PageSection | None:
    """Вернуть первую секцию типа "main"; если её нет — первую не-title секцию."""
    for section in document.page_sections:
        if section.type == "main":
            return section
    for section in document.page_sections:
        if section.type != "title":
            return section
    return None


@register("K.03")
def check_main_section_start_value(document: Document, profile: Profile) -> list[Violation]:
    """Нумерация в основной части стартует с фиксированной страницы.

    На уровне секций (дубликат F.06 в более локальном контексте).
    Параметр ``expected_start_value`` — по умолчанию ``3``.
    """
    config = profile.checks.get("K.03")
    expected_start = 3
    if config is not None:
        raw = config.params.get("expected_start_value", 3)
        try:
            expected_start = int(raw)
        except (TypeError, ValueError):
            expected_start = 3

    section = _first_main_section(document)
    if section is None:
        return []

    numbering = section.page_numbering
    violations: list[Violation] = []
    if numbering.start_mode != "start_at":
        violations.append(
            Violation(
                check_code="K.03",
                severity="error",
                message=(
                    f"Секция «{section.name}» должна явно задавать стартовую "
                    f"страницу (start_mode=start_at), а имеет "
                    f"start_mode={numbering.start_mode}"
                ),
                location=f"page_sections.{section.id}.page_numbering.start_mode",
                suggestion="Установить start_mode=start_at и start_value=3",
                details={"expected": "start_at", "actual": numbering.start_mode},
            )
        )
    elif numbering.start_value != expected_start:
        violations.append(
            Violation(
                check_code="K.03",
                severity="error",
                message=(
                    f"Секция «{section.name}» стартует с "
                    f"{numbering.start_value}, ожидается {expected_start}"
                ),
                location=f"page_sections.{section.id}.page_numbering.start_value",
                suggestion=f"Установить start_value={expected_start}",
                details={
                    "expected": str(expected_start),
                    "actual": str(numbering.start_value),
                },
            )
        )
    return violations


# --- K.04 — нумерация продолжается без сбросов -------------------------------


@register("K.04")
def check_no_numbering_restarts(document: Document, profile: Profile) -> list[Violation]:
    """Нумерация в работе сквозная: после первой секции рестартов быть не должно.

    Параметр ``allow_restart_in_appendix`` (bool, default False): если True,
    рестарт в секциях типа "appendix" допустим (некоторые кафедральные
    методички разрешают «Приложение А, страница 1»).
    """
    config = profile.checks.get("K.04")
    allow_restart_in_appendix = False
    if config is not None:
        allow_restart_in_appendix = bool(config.params.get("allow_restart_in_appendix", False))

    violations: list[Violation] = []
    sections = document.page_sections
    for index, section in enumerate(sections):
        if index == 0:
            continue  # первая секция задаёт начало нумерации
        if section.page_numbering.start_mode != "restart":
            continue
        if allow_restart_in_appendix and section.type == "appendix":
            continue
        violations.append(
            Violation(
                check_code="K.04",
                severity="error",
                message=(
                    f"Нумерация в секции «{section.name}» сбрасывается "
                    f"(start_mode=restart). По ГОСТ нумерация должна быть сквозной"
                ),
                location=f"page_sections.{section.id}.page_numbering.start_mode",
                suggestion="Установить start_mode=continue",
                details={"expected": "continue", "actual": "restart"},
            )
        )
    return violations


# --- K.05 — верхний колонтитул в приложениях ---------------------------------


def _header_mentions_appendix(template: ContentTemplate | None) -> bool:
    """Проверить, упоминает ли шаблон «Приложение» или плейсхолдер."""
    text = _content_template_text(template)
    lower = text.lower()
    if "приложение" in lower:
        return True
    return "{appendix_letter}" in text


@register("K.05")
def check_appendix_header(document: Document, profile: Profile) -> list[Violation]:
    """В верхнем колонтитуле приложения должно быть «Приложение …».

    Soft-проверка (warning). Допускаются варианты:
    - текст «ПРИЛОЖЕНИЕ А» в любой из трёх позиций (left/center/right);
    - шаблонный плейсхолдер ``{appendix_letter}``.
    """
    violations: list[Violation] = []
    for section in document.page_sections:
        if section.type != "appendix":
            continue
        header = section.header
        if header is None:
            violations.append(
                Violation(
                    check_code="K.05",
                    severity="warning",
                    message=(
                        f"В секции «{section.name}» отсутствует верхний "
                        f"колонтитул с заголовком приложения"
                    ),
                    location=f"page_sections.{section.id}.header",
                    suggestion=("Добавить верхний колонтитул вида «ПРИЛОЖЕНИЕ {appendix_letter}»"),
                )
            )
            continue

        templates_to_check: list[ContentTemplate | None] = [
            header.default,
            header.first_page,
            header.even_page,
        ]
        if not any(_header_mentions_appendix(t) for t in templates_to_check):
            violations.append(
                Violation(
                    check_code="K.05",
                    severity="warning",
                    message=(
                        f"Верхний колонтитул секции «{section.name}» "
                        f"не содержит слова «Приложение» или плейсхолдера "
                        f"{{appendix_letter}}"
                    ),
                    location=f"page_sections.{section.id}.header",
                    suggestion=("В колонтитул вставить «ПРИЛОЖЕНИЕ {appendix_letter}»"),
                )
            )
    return violations


# --- K.01 — структура секций соответствует шаблону ---------------------------

# Главные типы, по которым строится последовательность шаблона.
_MAJOR_TYPES: frozenset[str] = frozenset({"title", "frontmatter", "main", "appendix"})

# Заголовки структурных элементов «предисловной части» (frontmatter).
_FRONTMATTER_HEADINGS: frozenset[str] = frozenset(
    {
        "реферат",
        "содержание",
        "перечень сокращений",
        "перечень сокращений и обозначений",
        "обозначения и сокращения",
        "нормативные ссылки",
        "термины и определения",
        "определения",
    }
)


def _level1_headings(document: Document) -> list[str]:
    """Тексты заголовков всех LogicalSection 1-го уровня документа."""
    out: list[str] = []

    def walk(items: Sequence[object]) -> None:
        for item in items:
            if isinstance(item, LogicalSection):
                if item.level == 1:
                    out.append(_inline_to_text(item.heading))
                walk(item.children)

    for ps in document.page_sections:
        walk(ps.content)
    return out


def _detect_types_from_headings(document: Document) -> set[str]:
    """Определить присутствующие главные типы по логическим заголовкам.

    Парсер на Фазе 1 кладёт весь документ в одну PageSection(type="main"),
    поэтому типы title/frontmatter/appendix не видны на уровне вёрстки.
    Чтобы K.01 не штрафовал каждый документ ложно, распознаём структурные
    элементы по заголовкам разделов 1-го уровня (титульный лист,
    приложения, реферат/содержание и т. п.).
    """
    types: set[str] = set()
    for heading in _level1_headings(document):
        norm = " ".join(heading.lower().split()).rstrip(".")
        if not norm:
            continue
        if norm == "титульный лист":
            types.add("title")
        elif norm.startswith("приложение"):
            types.add("appendix")
        elif norm in _FRONTMATTER_HEADINGS or norm.startswith("задание"):
            types.add("frontmatter")
        else:
            types.add("main")
    return types


def _lis_length(seq_a: Sequence[str], seq_b: Sequence[str]) -> list[int]:
    """Найти индексы elements seq_a, образующих самую длинную общую подпоследовательность с seq_b.

    Возвращает список индексов в seq_a, которые «попали» в LCS-выравнивание.
    Используется, чтобы определить, какие ожидаемые секции реально найдены
    в документе и в правильном относительном порядке.
    """
    n, m = len(seq_a), len(seq_b)
    if n == 0 or m == 0:
        return []
    # Матрица длин LCS.
    dp = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n):
        for j in range(m):
            if seq_a[i] == seq_b[j]:
                dp[i + 1][j + 1] = dp[i][j] + 1
            else:
                dp[i + 1][j + 1] = max(dp[i + 1][j], dp[i][j + 1])
    # Восстановление индексов seq_a.
    i, j = n, m
    indices: list[int] = []
    while i > 0 and j > 0:
        if seq_a[i - 1] == seq_b[j - 1]:
            indices.append(i - 1)
            i -= 1
            j -= 1
        elif dp[i - 1][j] >= dp[i][j - 1]:
            i -= 1
        else:
            j -= 1
    indices.reverse()
    return indices


# --- K.06 — колонтитулы отвязаны от предыдущей секции -----------------------


@register("K.06")
def check_headers_not_linked_to_previous(document: Document, profile: Profile) -> list[Violation]:
    """Колонтитулы PageSection-ов (кроме первой) должны быть отвязаны.

    По ГОСТ титульный лист, фронтматтер и основная часть имеют разные
    колонтитулы (на титуле — пусто, в основной части — номера страниц).
    Word-флаг ``link_to_previous=True`` означает, что секция наследует
    колонтитул от предыдущей, что нарушает это требование.

    Параметры (`checks.K.06.params`):
    - `exclude_types`: список типов PageSection, для которых проверка
      не применяется (по умолчанию пустой список).
    """
    config = profile.checks.get("K.06")
    exclude_types: set[str] = set()
    if config is not None:
        raw_exclude = config.params.get("exclude_types") or []
        if isinstance(raw_exclude, (list, tuple)):
            exclude_types = {str(t) for t in raw_exclude}

    violations: list[Violation] = []
    for index, section in enumerate(document.page_sections):
        if index == 0:
            # Первая секция не имеет «предыдущей», флаг не имеет смысла.
            continue
        if section.type in exclude_types:
            continue
        if not section.link_to_previous:
            continue
        violations.append(
            Violation(
                check_code="K.06",
                severity="warning",
                message=(
                    f"Секция «{section.name}» (тип {section.type}) связана "
                    f"с колонтитулом предыдущей секции (link_to_previous=True)"
                ),
                location=f"page_sections.{section.id}.link_to_previous",
                suggestion=(
                    "Отвязать колонтитул от предыдущей секции "
                    "(в Word: «Как в предыдущем разделе» — выключить)"
                ),
                details={"section_id": section.id, "type": section.type},
            )
        )
    return violations


@register("K.01")
def check_sections_match_template(document: Document, profile: Profile) -> list[Violation]:
    """Структура PageSection-ов соответствует ``sections_template`` профиля.

    Сравниваем последовательность типов секций (только главные:
    title/frontmatter/main/appendix). Документ должен содержать те же
    типы и в том же относительном порядке. Лишние секции допустимы.

    Используется LCS: «выпавшие» из ожидаемой последовательности типы
    превращаются в Violation. Если документ полностью пуст или не содержит
    ни одного ожидаемого типа — Violation на каждый ожидаемый тип.

    Парсер на Фазе 1 кладёт весь документ в одну PageSection(type="main"),
    поэтому типы title/frontmatter/appendix не видны на уровне вёрстки.
    Чтобы не штрафовать каждый документ ложно, наличие типов определяется
    по объединению: типы PageSection-ов ∪ распознанные по заголовкам
    разделов (титульный лист, приложения, реферат/содержание …). Проверка
    порядка выполняется только при реальной разметке (≥2 типов секций).
    """
    template_major = [t for t in profile.sections_template if t.type in _MAJOR_TYPES]
    if not template_major:
        return []

    page_types_seq = [ps.type for ps in document.page_sections if ps.type in _MAJOR_TYPES]
    available = set(page_types_seq) | _detect_types_from_headings(document)

    violations: list[Violation] = []

    # 1. Присутствие требуемых типов (по объединению вёрстки и заголовков).
    for tpl in template_major:
        if tpl.type not in available:
            violations.append(
                Violation(
                    check_code="K.01",
                    severity="error",
                    message=f"Отсутствует секция «{tpl.name}» (тип {tpl.type})",
                    location="page_sections",
                    suggestion=f"Добавить секцию типа «{tpl.type}»",
                    details={"expected_type": tpl.type},
                )
            )

    # 2. Порядок — только при реальной разметке PageSection-ов (≥2 разных
    #    главных типа). На плоском документе (один main) порядок не определён.
    distinct_page_types = list(dict.fromkeys(page_types_seq))
    if len(distinct_page_types) >= 2:
        expected_types = [t.type for t in template_major]
        matched_indices = set(_lis_length(expected_types, page_types_seq))
        for idx, tpl in enumerate(template_major):
            # Отсутствие уже учтено в блоке присутствия выше — здесь только
            # «тип есть, но не на своём месте».
            if idx in matched_indices or tpl.type not in page_types_seq:
                continue
            violations.append(
                Violation(
                    check_code="K.01",
                    severity="error",
                    message=(
                        f"Секция типа «{tpl.type}» («{tpl.name}») присутствует, "
                        f"но нарушает ожидаемый порядок"
                    ),
                    location="page_sections",
                    suggestion="Переставить секции в порядке шаблона",
                    details={"expected_type": tpl.type},
                )
            )
    return violations
