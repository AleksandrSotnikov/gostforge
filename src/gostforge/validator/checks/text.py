"""T.* — проверки основного текста (шрифт, кегль, интервалы)."""

from __future__ import annotations

from collections.abc import Sequence

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


__all__ = ["check_font", "check_font_size"]
