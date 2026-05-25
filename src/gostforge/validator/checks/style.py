"""X.* — проверки стиля и лингвистики."""

from __future__ import annotations

import re
from typing import Any

from gostforge.model import (
    Block,
    CrossRef,
    Document,
    InlineElement,
    LogicalSection,
    Paragraph,
    TextRun,
)
from gostforge.profile import Profile

from ..engine import Violation, register

# Регулярное выражение для местоимений 1-го лица единственного числа:
# «я», «меня», «мне», «мной» (и устар. «мною»), «мой/моя/моё/моего/моему/моим/моей/моих/моими».
_FIRST_PERSON_PATTERN = re.compile(
    r"\bя\b|\bменя\b|\bмне\b|\bмной\b|\bмною\b|"
    r"\bмой\b|\bмоего\b|\bмоему\b|\bмоим\b|"
    r"\bмоё\b|\bмоя\b|\bмоей\b|\bмоих\b|\bмоими\b",
    re.IGNORECASE,
)


def _params(profile: Profile, code: str) -> dict[str, Any]:
    cfg = profile.checks.get(code)
    if cfg is None:
        return {}
    return dict(cfg.params)


def _inline_text(elements: list[InlineElement]) -> str:
    """Склейка inline-элементов в строку."""
    parts: list[str] = []
    for el in elements:
        if isinstance(el, TextRun):
            parts.append(el.text)
        elif isinstance(el, CrossRef):
            parts.append(el.display_template)
    return "".join(parts)


def _iter_paragraphs(document: Document) -> list[Paragraph]:
    """Все Paragraph документа (включая вложенные в LogicalSection)."""
    result: list[Paragraph] = []

    def walk(items: list[LogicalSection | Block]) -> None:
        for it in items:
            if isinstance(it, LogicalSection):
                walk(it.children)
            elif isinstance(it, Paragraph):
                result.append(it)

    for page_section in document.page_sections:
        walk(page_section.content)
    return result


@register("X.02")
def check_no_first_person_singular(document: Document, profile: Profile) -> list[Violation]:
    """X.02 — нет местоимений 1-го лица единственного числа.

    В научном тексте принято обезличенное изложение. Регулярное выражение
    ищет «я», «мне», «меня», «мной»/«мною» и местоимения «мой/моя/моё»
    во всех падежах. Один Violation на параграф (по первому найденному
    местоимению). Исключения (цитаты в кавычках) на Фазе 1 не учитываются.
    """
    _ = profile  # параметры не используются на Фазе 1
    violations: list[Violation] = []
    for paragraph in _iter_paragraphs(document):
        text = _inline_text(paragraph.content)
        match = _FIRST_PERSON_PATTERN.search(text)
        if match is None:
            continue
        found = match.group(0)
        violations.append(
            Violation(
                check_code="X.02",
                severity="warning",
                message=(
                    f"В тексте обнаружено местоимение 1-го лица «{found}». "
                    "В научной работе используйте безличные обороты."
                ),
                location=f"paragraphs.{paragraph.id}",
                suggestion=(
                    "Замените «я» на безличные конструкции «было выполнено», "
                    "«рассмотрено», «в работе предлагается» и т. п."
                ),
                details={"found": found},
            )
        )
    return violations


@register("X.03")
def check_no_colloquial_phrases(document: Document, profile: Profile) -> list[Violation]:
    """X.03 — нет разговорных оборотов.

    Берёт список запрещённых оборотов из профиля (параметр banned_phrases)
    и ищет каждый из них в тексте каждого параграфа (case-insensitive,
    re.escape). Один Violation на каждый найденный оборот в параграфе.
    severity = info: список оборотов условный, false-positive вероятны.
    """
    params = _params(profile, "X.03")
    default_phrases = [
        "короче",
        "ну в общем",
        "то есть так сказать",
        "как бы",
        "типа того",
    ]
    raw_phrases = params.get("banned_phrases", default_phrases)
    if not isinstance(raw_phrases, list):
        raw_phrases = default_phrases
    phrases: list[str] = [str(p) for p in raw_phrases if str(p).strip()]

    violations: list[Violation] = []
    for paragraph in _iter_paragraphs(document):
        text = _inline_text(paragraph.content)
        if not text.strip():
            continue
        for phrase in phrases:
            if re.search(re.escape(phrase), text, re.IGNORECASE):
                violations.append(
                    Violation(
                        check_code="X.03",
                        severity="info",
                        message=(
                            f"Обнаружен разговорный оборот «{phrase}» — "
                            "следует переформулировать научным языком."
                        ),
                        location=f"paragraphs.{paragraph.id}",
                        suggestion=f"Удалить или заменить оборот «{phrase}»",
                        details={"phrase": phrase},
                    )
                )
    return violations


@register("X.01")
def check_spelling(document: Document, profile: Profile) -> list[Violation]:
    """X.01 — орфография (заглушка, severity=warning).

    На Фазе 1 не реализована: для полноценной орфографии требуется
    внешний языковой spell-checker (pyspellchecker, hunspell или
    облачный API), что выходит за рамки минимального ядра.
    TODO Phase 2.
    """
    _ = document
    _ = profile
    return []
