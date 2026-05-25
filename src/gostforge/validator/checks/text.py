"""T.* — проверки основного текста (шрифт, кегль, интервалы)."""

from __future__ import annotations

from collections.abc import Iterator, Sequence

from gostforge.model import (
    Block,
    Document,
    InlineElement,
    LogicalSection,
    Paragraph,
    TextRun,
)
from gostforge.profile import Profile

from ..engine import Violation, register


# Стили абзацев, которые не считаются «основным текстом». Для них применяются
# отдельные правила (размер подписи, размер сноски), а не body.
_CAPTION_STYLE_PREFIXES = ("caption", "image caption", "table caption", "figure caption")
_NON_BODY_STYLES = {"footnote text", "header", "footer"}

# Допуск по кеглю (Word хранит размеры с шагом 0.5pt, иногда плавающие значения)
_SIZE_TOLERANCE_PT = 0.1

# Допуск по межстрочному интервалу и отступу красной строки. line_spacing
# в Word может быть округлён до сотых, indent — до миллиметров.
_LINE_SPACING_TOLERANCE = 0.01
_INDENT_TOLERANCE_CM = 0.05


def _iter_paragraphs(items: list[LogicalSection | Block]) -> list[Paragraph]:
    """Рекурсивно собрать все Paragraph из списка вложенных элементов модели."""
    result: list[Paragraph] = []
    for item in items:
        if isinstance(item, Paragraph):
            result.append(item)
        elif isinstance(item, LogicalSection):
            result.extend(_iter_paragraphs(item.children))
    return result


def _all_paragraphs(document: Document) -> list[Paragraph]:
    """Все Paragraph из всех PageSection документа (рекурсивный обход)."""
    paragraphs: list[Paragraph] = []
    for section in document.page_sections:
        paragraphs.extend(_iter_paragraphs(section.content))
    return paragraphs


def _classify_paragraph(paragraph: Paragraph) -> str:
    """Классифицировать абзац: 'body', 'caption', 'footnote', 'header_footer', 'heading'.

    Используется проверками для выбора применимых параметров профиля.
    """
    style = (paragraph.style_name or "").strip().lower()
    if any(style.startswith(p) for p in _CAPTION_STYLE_PREFIXES):
        return "caption"
    if style == "footnote text":
        return "footnote"
    if style in {"header", "footer"}:
        return "header_footer"
    if style.startswith("heading"):
        return "heading"
    return "body"


def _preview(content: Sequence[InlineElement]) -> str:
    """Короткий превью-текст из inline-содержимого для сообщения об ошибке."""
    pieces: list[str] = []
    for el in content:
        if isinstance(el, TextRun) and el.text:
            pieces.append(el.text)
    text = "".join(pieces).strip()
    return text[:50] + ("…" if len(text) > 50 else "")


@register("T.01")
def check_font(document: Document, profile: Profile) -> list[Violation]:
    """Проверка шрифта основного текста.

    Эталон — `profile.styles.body.font`. Параметр в профиле:
    `checks.T.01.params.font` (если задан, перебивает body.font).
    """
    violations: list[Violation] = []
    config = profile.checks.get("T.01")
    expected_font = profile.styles.body.font
    if config and config.params.get("font"):
        expected_font = config.params["font"]

    for paragraph in _all_paragraphs(document):
        category = _classify_paragraph(paragraph)
        if category in {"header_footer"}:
            continue  # колонтитулы — отдельная категория проверок K.*
        for run in paragraph.content:
            if not isinstance(run, TextRun):
                continue
            if not run.text or not run.text.strip():
                continue
            if run.font is None:
                continue  # шрифт наследуется от стиля — не считаем нарушением
            if run.font != expected_font:
                violations.append(
                    Violation(
                        check_code="T.01",
                        severity="error",
                        message=(
                            f"Шрифт «{run.font}» в абзаце «{_preview(paragraph.content)}» "
                            f"не соответствует ожидаемому «{expected_font}»"
                        ),
                        location=f"page_sections.*.paragraph[{paragraph.id}].run",
                        suggestion=f"Использовать шрифт «{expected_font}» для основного текста",
                        details={"expected": expected_font, "actual": run.font},
                    )
                )
    return violations


@register("T.02")
def check_font_size(document: Document, profile: Profile) -> list[Violation]:
    """Проверка кегля основного текста, подписей и сносок.

    Параметры в `checks.T.02.params`:
    - `body_size` (по умолчанию profile.styles.body.size_pt)
    - `caption_size` (по умолчанию styles.extra['caption_size_pt'], 12)
    - `footnote_size` (по умолчанию styles.extra['footnote_size_pt'], 10)
    """
    violations: list[Violation] = []
    config = profile.checks.get("T.02")
    params = config.params if config else {}

    extra = profile.styles.extra
    body_size = float(params.get("body_size", profile.styles.body.size_pt))
    caption_size = float(params.get("caption_size", extra.get("caption_size_pt", 12)))
    footnote_size = float(params.get("footnote_size", extra.get("footnote_size_pt", 10)))

    expected_by_category = {
        "body": body_size,
        "caption": caption_size,
        "footnote": footnote_size,
    }

    for paragraph in _all_paragraphs(document):
        category = _classify_paragraph(paragraph)
        expected = expected_by_category.get(category)
        if expected is None:
            continue  # heading и header/footer проверяются отдельно (H.*, K.*)
        for run in paragraph.content:
            if not isinstance(run, TextRun):
                continue
            if not run.text or not run.text.strip():
                continue
            if run.size_pt is None:
                continue
            if abs(run.size_pt - expected) > _SIZE_TOLERANCE_PT:
                violations.append(
                    Violation(
                        check_code="T.02",
                        severity="error",
                        message=(
                            f"Кегль {run.size_pt} pt в абзаце «{_preview(paragraph.content)}» "
                            f"не соответствует ожидаемому {expected} pt"
                        ),
                        location=f"page_sections.*.paragraph[{paragraph.id}].run",
                        suggestion=f"Использовать кегль {expected} pt для {category}",
                        details={
                            "expected": str(expected),
                            "actual": str(run.size_pt),
                            "category": category,
                        },
                    )
                )
    return violations


@register("T.03")
def check_line_spacing(document: Document, profile: Profile) -> list[Violation]:
    """Проверка межстрочного интервала основного текста (по умолчанию 1.5).

    Параметры `checks.T.03.params`:
    - `line_spacing` (по умолчанию `profile.styles.body.line_spacing`).
    """
    violations: list[Violation] = []
    config = profile.checks.get("T.03")
    expected = float(profile.styles.body.line_spacing)
    if config and config.params.get("line_spacing") is not None:
        expected = float(config.params["line_spacing"])

    for paragraph in _all_paragraphs(document):
        if _classify_paragraph(paragraph) != "body":
            continue
        if paragraph.line_spacing is None:
            continue
        if abs(paragraph.line_spacing - expected) > _LINE_SPACING_TOLERANCE:
            violations.append(
                Violation(
                    check_code="T.03",
                    severity="error",
                    message=(
                        f"Межстрочный интервал {paragraph.line_spacing} в абзаце "
                        f"«{_preview(paragraph.content)}» не соответствует {expected}"
                    ),
                    location=f"page_sections.*.paragraph[{paragraph.id}].line_spacing",
                    suggestion=f"Установить межстрочный интервал {expected} для основного текста",
                    details={"expected": str(expected), "actual": str(paragraph.line_spacing)},
                )
            )
    return violations


@register("T.04")
def check_first_line_indent(document: Document, profile: Profile) -> list[Violation]:
    """Проверка отступа красной строки основного текста (по умолчанию 1.25 см).

    Параметры `checks.T.04.params`:
    - `first_line_indent_cm` (по умолчанию `profile.styles.body.first_line_indent_cm`).
    """
    violations: list[Violation] = []
    config = profile.checks.get("T.04")
    expected = float(profile.styles.body.first_line_indent_cm)
    if config and config.params.get("first_line_indent_cm") is not None:
        expected = float(config.params["first_line_indent_cm"])

    for paragraph in _all_paragraphs(document):
        if _classify_paragraph(paragraph) != "body":
            continue
        if paragraph.first_line_indent_cm is None:
            continue
        if abs(paragraph.first_line_indent_cm - expected) > _INDENT_TOLERANCE_CM:
            violations.append(
                Violation(
                    check_code="T.04",
                    severity="error",
                    message=(
                        f"Отступ красной строки {paragraph.first_line_indent_cm} см "
                        f"в абзаце «{_preview(paragraph.content)}» не соответствует {expected} см"
                    ),
                    location=f"page_sections.*.paragraph[{paragraph.id}].first_line_indent_cm",
                    suggestion=f"Установить отступ первой строки {expected} см",
                    details={
                        "expected": str(expected),
                        "actual": str(paragraph.first_line_indent_cm),
                    },
                )
            )
    return violations


def _iter_container_paragraph_groups(
    document: Document,
) -> Iterator[list[Paragraph]]:
    """Итератор по «контейнерам» документа.

    Контейнер — это последовательность сиблингов на одном уровне (либо
    `content` страничной секции, либо `children` логического раздела).
    Пустые абзацы T.07 считаются только в пределах одного контейнера: между
    логическими разделами счётчик сбрасывается, потому что в OOXML заголовок
    стоит между ними и физически разрывает «цепочку» пустоты.
    """
    for page_section in document.page_sections:
        yield [item for item in page_section.content if isinstance(item, Paragraph)]
        for ls in _walk_logical_sections(page_section.content):
            yield [item for item in ls.children if isinstance(item, Paragraph)]


def _walk_logical_sections(
    items: Sequence[LogicalSection | Block],
) -> Iterator[LogicalSection]:
    """Рекурсивный обход LogicalSection (вложенные включаются)."""
    for item in items:
        if isinstance(item, LogicalSection):
            yield item
            yield from _walk_logical_sections(item.children)


def _paragraph_is_empty(paragraph: Paragraph) -> bool:
    """Пустой абзац: нет ни одного TextRun с непустым text.strip()."""
    for el in paragraph.content:
        if isinstance(el, TextRun) and el.text and el.text.strip():
            return False
    return True


@register("T.05")
def check_alignment(document: Document, profile: Profile) -> list[Violation]:
    """Проверка выравнивания основного текста (по умолчанию по ширине).

    Параметры `checks.T.05.params`:
    - `alignment`: 'left' | 'right' | 'center' | 'justify' (по умолчанию body.alignment).
    """
    violations: list[Violation] = []
    config = profile.checks.get("T.05")
    expected = profile.styles.body.alignment
    if config and config.params.get("alignment"):
        expected = config.params["alignment"]

    for paragraph in _all_paragraphs(document):
        if _classify_paragraph(paragraph) != "body":
            continue
        if paragraph.alignment is None:
            continue
        if paragraph.alignment != expected:
            violations.append(
                Violation(
                    check_code="T.05",
                    severity="error",
                    message=(
                        f"Выравнивание «{paragraph.alignment}» в абзаце "
                        f"«{_preview(paragraph.content)}» не соответствует «{expected}»"
                    ),
                    location=f"page_sections.*.paragraph[{paragraph.id}].alignment",
                    suggestion=f"Установить выравнивание «{expected}» для основного текста",
                    details={"expected": expected, "actual": paragraph.alignment},
                )
            )
    return violations


@register("T.07")
def check_no_consecutive_empty_paragraphs(
    document: Document, profile: Profile
) -> list[Violation]:
    """В тексте не должно быть подряд идущих пустых абзацев.

    Параметр `checks.T.07.params.max_consecutive_empty` (int, по умолчанию 1)
    задаёт, сколько пустых абзацев подряд допустимо. Превышение — нарушение.
    Счёт ведётся в пределах одного контейнера-сиблингов; через границу
    логического раздела цепочка не продолжается (между ними стоит заголовок).

    Один Violation на каждую цепочку, превысившую лимит.
    """
    violations: list[Violation] = []
    config = profile.checks.get("T.07")
    max_empty = 1
    if config and config.params.get("max_consecutive_empty") is not None:
        max_empty = int(config.params["max_consecutive_empty"])

    for paragraphs in _iter_container_paragraph_groups(document):
        run_length = 0
        chain_start_id: str | None = None
        for paragraph in paragraphs:
            if _paragraph_is_empty(paragraph):
                if run_length == 0:
                    chain_start_id = paragraph.id
                run_length += 1
            else:
                if run_length > max_empty:
                    violations.append(
                        _t07_violation(run_length, max_empty, chain_start_id)
                    )
                run_length = 0
                chain_start_id = None
        if run_length > max_empty:
            violations.append(_t07_violation(run_length, max_empty, chain_start_id))
    return violations


def _t07_violation(count: int, allowed: int, location_id: str | None) -> Violation:
    location = (
        f"page_sections.*.paragraph[{location_id}]"
        if location_id
        else "page_sections.*"
    )
    return Violation(
        check_code="T.07",
        severity="warning",
        message=(
            f"Подряд идущих пустых абзацев: {count} (допустимо не более {allowed})"
        ),
        location=location,
        suggestion="Удалить лишние пустые абзацы; для отступа использовать spacing_before/after",
        details={"count": str(count), "allowed": str(allowed)},
    )


__all__ = [
    "check_alignment",
    "check_first_line_indent",
    "check_font",
    "check_font_size",
    "check_line_spacing",
    "check_no_consecutive_empty_paragraphs",
]
