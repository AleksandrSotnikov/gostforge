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


@register("X.04")
def check_number_unit_agreement(document: Document, profile: Profile) -> list[Violation]:
    """X.04 — согласование чисел и единиц измерения (заглушка).

    На Фазе 2 — упрощённо: только для «секунда / минута / час / день /
    год / месяц». На текущий момент возвращаем пустой список, чтобы
    проверка была зарегистрирована и видна пользователю.

    TODO Phase 3: полноценная реализация на базе словаря падежных форм
    единиц и правил согласования числительных с существительными.
    """
    _ = document
    _ = profile
    return []


@register("X.05")
def check_term_consistency(document: Document, profile: Profile) -> list[Violation]:
    """X.05 — единообразие терминов.

    По ГОСТу один термин должен использоваться в одном виде во всём
    документе. Студенты часто пишут «база данных» в одном месте и
    «БД» в другом — это создаёт впечатление, что речь о разных вещах.

    Параметры профиля ``checks.X.05.params.terms``: список записей
    ``{canonical, aliases}``.

    Пример::

        X.05:
          enabled: true
          params:
            terms:
              - canonical: "база данных"
                aliases: ["БД", "DB"]
              - canonical: "программное обеспечение"
                aliases: ["ПО"]

    Severity = info.
    """
    config = profile.checks.get("X.05")
    if not config:
        return []
    terms_raw = config.params.get("terms", [])
    if not terms_raw:
        return []

    from gostforge.validator.checks.text import _all_paragraphs as _all_p

    full_text = " ".join(
        "".join(el.text for el in p.content if hasattr(el, "text") and isinstance(el.text, str))
        for p in _all_p(document)
    )
    if not full_text:
        return []
    full_text_lower = full_text.lower()

    violations: list[Violation] = []
    for term_entry in terms_raw:
        if not isinstance(term_entry, dict):
            continue
        canonical = str(term_entry.get("canonical", "")).strip()
        aliases = term_entry.get("aliases") or []
        if not canonical or not aliases:
            continue
        canonical_lower = canonical.lower()
        found_aliases = [
            alias
            for alias in aliases
            if isinstance(alias, str)
            and alias
            and alias.lower() != canonical_lower
            and alias.lower() in full_text_lower
        ]
        if not found_aliases:
            continue
        violations.append(
            Violation(
                check_code="X.05",
                severity="info",
                message=(
                    f"Термин «{canonical}» используется в разных формах: "
                    + ", ".join(f"«{a}»" for a in found_aliases)
                    + (f", а также «{canonical}»" if canonical_lower in full_text_lower else "")
                ),
                location="document",
                suggestion=(f"Привести все упоминания к единому виду «{canonical}»"),
                details={
                    "canonical": canonical,
                    "aliases": ", ".join(found_aliases),
                },
            )
        )
    return violations


# X.06 — канцеляризмы и расхожие плохие обороты в научном тексте.
_BUREAUCRATIC_PATTERNS: list[tuple[str, str]] = [
    (r"\bявляется\b", "Замените «является» на «—» или конкретное действие"),
    (r"\bявляются\b", "Замените «являются» на «—» или конкретное действие"),
    (r"\bосуществляется\b", "Замените «осуществляется» на конкретное действие"),
    (r"\bосуществляются\b", "Замените «осуществляются» на конкретное действие"),
    (r"\bпроизводится\b", "Замените «производится» на конкретное действие"),
    (r"\bпроизводятся\b", "Замените «производятся» на конкретное действие"),
    (r"\bпредставляет\s+собой\b", "Замените «представляет собой» на «—»"),
    (r"\bпредставляют\s+собой\b", "Замените «представляют собой» на «—»"),
    (r"\bв\s+качестве\b", "«В качестве» — избыточно, упростите"),
    (r"\bосуществить\b", "Замените «осуществить» на конкретный глагол"),
]


@register("X.06")
def check_bureaucratic_style(document: Document, profile: Profile) -> list[Violation]:
    """X.06 — канцеляризмы в научном тексте.

    Распознаёт типовые «бюрократические» обороты, которые делают
    текст тяжёлым: «является», «осуществляется», «представляет
    собой», «в качестве». Это рекомендация, не жёсткое нарушение
    ГОСТа — улучшает читаемость работы.

    Параметры ``checks.X.06.params``:
    * ``max_per_paragraph`` (default 1) — допустимо канцеляризмов
      в одном абзаце без warning.
    * ``custom_patterns`` — дополнительные паттерны
      ``[{pattern, suggestion}]``.

    Severity = info.
    """
    config = profile.checks.get("X.06")
    max_per_paragraph = 1
    extra_patterns: list[tuple[str, str]] = []
    if config:
        if config.params.get("max_per_paragraph") is not None:
            max_per_paragraph = int(config.params["max_per_paragraph"])
        for entry in config.params.get("custom_patterns") or []:
            if isinstance(entry, dict):
                pat = str(entry.get("pattern", ""))
                sugg = str(entry.get("suggestion", "Перефразировать"))
                if pat:
                    extra_patterns.append((pat, sugg))

    patterns = _BUREAUCRATIC_PATTERNS + extra_patterns
    compiled = [(re.compile(p, re.IGNORECASE), s) for p, s in patterns]

    from gostforge.validator.checks.text import _all_paragraphs as _all_p

    violations: list[Violation] = []
    for paragraph in _all_p(document):
        style = (paragraph.style_name or "").lower()
        if style.startswith("heading") or style.startswith("caption") or style.startswith("list"):
            continue
        text = "".join(
            el.text for el in paragraph.content if hasattr(el, "text") and isinstance(el.text, str)
        )
        if not text:
            continue
        found: list[tuple[str, str]] = []
        for pattern, suggestion in compiled:
            for match in pattern.finditer(text):
                found.append((match.group(0), suggestion))
        if len(found) > max_per_paragraph:
            preview = text[:60] + ("…" if len(text) > 60 else "")
            phrases = list({f[0] for f in found})
            violations.append(
                Violation(
                    check_code="X.06",
                    severity="info",
                    message=(
                        f"В абзаце «{preview}» {len(found)} канцеляризмов: "
                        + ", ".join(f"«{p}»" for p in phrases[:3])
                        + ("…" if len(phrases) > 3 else "")
                    ),
                    location=f"paragraph[{paragraph.id}]",
                    suggestion=found[0][1],
                    details={
                        "paragraph_id": paragraph.id,
                        "count": str(len(found)),
                    },
                )
            )
    return violations


@register("X.07")
def check_sentence_length(document: Document, profile: Profile) -> list[Violation]:
    """X.07 — слишком длинные предложения.

    Сложные предложения с 35+ словами трудно читать. Срабатывает на
    предложениях с числом слов больше параметра max_words.

    Параметр ``checks.X.07.params.max_words`` (default 35).

    Деление на предложения — по знакам ``.``, ``!``, ``?`` плюс
    пробел или конец строки. Эвристика устойчива к сокращениям
    ('т. е.', 'и т. д.') — после них обычно идёт строчная буква.

    Severity = info.
    """
    config = profile.checks.get("X.07")
    max_words = 35
    if config and config.params.get("max_words") is not None:
        max_words = int(config.params["max_words"])

    from gostforge.validator.checks.text import _all_paragraphs as _all_p

    violations: list[Violation] = []
    for paragraph in _all_p(document):
        style = (paragraph.style_name or "").lower()
        if style.startswith("heading") or style.startswith("caption"):
            continue
        text = "".join(
            el.text for el in paragraph.content if hasattr(el, "text") and isinstance(el.text, str)
        )
        if not text:
            continue
        for sentence in _split_sentences(text):
            words = sentence.split()
            if len(words) <= max_words:
                continue
            preview = sentence[:60] + ("…" if len(sentence) > 60 else "")
            violations.append(
                Violation(
                    check_code="X.07",
                    severity="info",
                    message=(
                        f"Длинное предложение ({len(words)} слов, "
                        f"допустимо {max_words}): «{preview}»"
                    ),
                    location=f"paragraph[{paragraph.id}]",
                    suggestion="Разбейте на 2-3 более коротких предложения",
                    details={
                        "paragraph_id": paragraph.id,
                        "words": str(len(words)),
                    },
                )
            )
    return violations


_SENTENCE_END_RE = re.compile(r"(?<=[.!?])\s+(?=[А-ЯA-Z])")


def _split_sentences(text: str) -> list[str]:
    """Разбить текст на предложения по простой эвристике."""
    if not text:
        return []
    return [s.strip() for s in _SENTENCE_END_RE.split(text) if s.strip()]


@register("X.08")
def check_word_repetition(document: Document, profile: Profile) -> list[Violation]:
    """X.08 — повтор одного слова через короткое расстояние (тавтология).

    «работа работа», «которая которая», «для для» — типичные ошибки
    при копировании текста. X.08 ищет одинаковые значимые слова
    в радиусе менее N слов друг от друга.

    Параметр ``checks.X.08.params.min_distance`` (default 3) — минимум
    слов между двумя одинаковыми значимыми словами.

    Стоп-слова (предлоги, союзы, частицы, местоимения, базовые
    глаголы) пропускаются — их повтор естественен. Слова короче
    4 символов тоже пропускаются.

    Severity = info.
    """
    config = profile.checks.get("X.08")
    min_distance = 3
    if config and config.params.get("min_distance") is not None:
        min_distance = int(config.params["min_distance"])

    from gostforge.validator.checks.text import _all_paragraphs as _all_p

    violations: list[Violation] = []
    for paragraph in _all_p(document):
        style = (paragraph.style_name or "").lower()
        if style.startswith("heading") or style.startswith("caption"):
            continue
        text = "".join(
            el.text for el in paragraph.content if hasattr(el, "text") and isinstance(el.text, str)
        )
        if not text:
            continue
        words_with_pos: list[tuple[int, str]] = []
        for m in re.finditer(r"[А-Яа-яёЁA-Za-z]+", text):
            w = m.group(0).lower()
            if len(w) < 4 or w in _STOP_WORDS_RU:
                continue
            words_with_pos.append((len(words_with_pos), w))
        last_seen: dict[str, int] = {}
        already_reported: set[str] = set()
        for idx, w in words_with_pos:
            if w in last_seen and (idx - last_seen[w]) < min_distance:
                if w in already_reported:
                    last_seen[w] = idx
                    continue
                already_reported.add(w)
                preview = text[:60] + ("…" if len(text) > 60 else "")
                violations.append(
                    Violation(
                        check_code="X.08",
                        severity="info",
                        message=(
                            f"Повтор «{w}» через {idx - last_seen[w]} слова в абзаце «{preview}»"
                        ),
                        location=f"paragraph[{paragraph.id}]",
                        suggestion=("Замените одно из вхождений синонимом или перефразируйте"),
                        details={"paragraph_id": paragraph.id, "word": w},
                    )
                )
            last_seen[w] = idx
    return violations


# Стоп-слова: предлоги, союзы, частицы, местоимения, базовые глаголы.
# Их повтор не считаем стилистической ошибкой.
_STOP_WORDS_RU: frozenset[str] = frozenset(
    {
        "быть",
        "была",
        "было",
        "были",
        "будет",
        "будут",
        "этот",
        "эта",
        "это",
        "эти",
        "того",
        "тому",
        "тем",
        "тех",
        "который",
        "которая",
        "которое",
        "которые",
        "которого",
        "также",
        "более",
        "менее",
        "может",
        "могут",
        "могла",
        "после",
        "перед",
        "между",
        "через",
        "около",
        "если",
        "когда",
        "пока",
        "затем",
        "потом",
        "однако",
        "поэтому",
        "поскольку",
        "часть",
        "часто",
    }
)
