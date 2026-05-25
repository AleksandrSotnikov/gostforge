"""R.* — проверки списка литературы (ГОСТ Р 7.0.100-2018)."""

# ruff: noqa: RUF001, RUF002, RUF003

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
    document: Document, profile: Profile  # noqa: ARG001
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
                        "Заменить ссылку на формат [N] с номером записи "
                        "из списка литературы"
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
                        "Заменить ссылку на формат [N] с номером записи "
                        "из списка литературы"
                    ),
                    details={
                        "paragraph_id": paragraph.id,
                        "found": match.group(0),
                        "style": "author_year_brackets",
                    },
                )
            )

    return violations


__all__ = [
    "check_bibliography_format",
    "check_reference_style_numeric",
]
