# ruff: noqa: RUF001, RUF002, RUF003

"""S.* — проверки структуры работы (наличие обязательных разделов, их порядок)."""

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
from .headings import iter_logical_sections

# Дефолтный список обязательных разделов для ГОСТ 7.32-2017. Может быть
# переопределён через `checks.S.01.params.required_headings`.
_DEFAULT_REQUIRED_HEADINGS: list[str] = [
    "Введение",
    "Заключение",
    "Список использованных источников",
]

# Альтернативные написания для разделов: одно из них достаточно
# (например, «Список литературы» или «Список использованных источников»).
_HEADING_ALIASES: dict[str, list[str]] = {
    "Список использованных источников": ["Список литературы"],
}

# Дефолтный ожидаемый порядок разделов работы по ГОСТ 7.32-2017.
# Используется в S.02, если в профиле не задан `expected_order`.
_DEFAULT_EXPECTED_ORDER: list[str] = [
    "Реферат",
    "Содержание",
    "Перечень сокращений",
    "Введение",
    "Заключение",
    "Список использованных источников",
    "Приложение",
]


def _heading_text(content: Sequence[InlineElement]) -> str:
    """Склеить inline-содержимое заголовка в чистую строку."""
    return "".join(el.text for el in content if isinstance(el, TextRun)).strip()


def _all_level1_headings(items: Sequence[LogicalSection | Block]) -> list[str]:
    """Собрать тексты всех LogicalSection первого уровня (рекурсивно)."""
    result: list[str] = []
    for item in items:
        if isinstance(item, LogicalSection):
            if item.level == 1:
                result.append(_heading_text(item.heading))
            result.extend(_all_level1_headings(item.children))
    return result


def _all_level1_sections(
    items: Sequence[LogicalSection | Block],
) -> list[LogicalSection]:
    """Собрать сами LogicalSection первого уровня (рекурсивно), в порядке появления."""
    result: list[LogicalSection] = []
    for item in items:
        if isinstance(item, LogicalSection):
            if item.level == 1:
                result.append(item)
            result.extend(_all_level1_sections(item.children))
    return result


def _normalize(s: str) -> str:
    """Нормализация для сравнения: lowercase + collapse whitespace."""
    return " ".join(s.lower().split())


@register("S.01")
def check_required_sections(document: Document, profile: Profile) -> list[Violation]:
    """Проверка наличия обязательных разделов работы.

    Параметры профиля (`checks.S.01.params`):
    - `required_headings`: список ожидаемых заголовков (по умолчанию
      «Введение», «Заключение», «Список использованных источников»).
    """
    violations: list[Violation] = []
    config = profile.checks.get("S.01")
    required: list[str] = list(_DEFAULT_REQUIRED_HEADINGS)
    if config and config.params.get("required_headings"):
        required = list(config.params["required_headings"])

    found_headings: list[str] = []
    for section in document.page_sections:
        found_headings.extend(_all_level1_headings(section.content))

    normalized_found = {_normalize(h) for h in found_headings if h}

    for expected in required:
        candidates = [expected] + _HEADING_ALIASES.get(expected, [])
        if not any(_normalize(c) in normalized_found for c in candidates):
            aliases = _HEADING_ALIASES.get(expected, [])
            aliases_hint = f" (или: {', '.join(aliases)})" if aliases else ""
            violations.append(
                Violation(
                    check_code="S.01",
                    severity="error",
                    message=f"В документе отсутствует обязательный раздел «{expected}»",
                    location="page_sections.*.logical_section[level=1]",
                    suggestion=f"Добавить раздел уровня 1 с заголовком «{expected}»{aliases_hint}",
                    details={"expected": expected, "found_headings": "; ".join(found_headings)},
                )
            )
    return violations


def _first_paragraph(section: LogicalSection) -> Paragraph | None:
    """Найти первый Paragraph среди прямых детей раздела."""
    for child in section.children:
        if isinstance(child, Paragraph):
            return child
    return None


@register("S.06")
def check_section_page_break(document: Document, profile: Profile) -> list[Violation]:
    """Раздел указанного уровня должен начинаться с новой страницы.

    Параметр профиля `checks.S.06.params.required_for_level` (по умолчанию 1)
    задаёт, для каких уровней разделов требуется разрыв страницы.

    Семантика Фазы 1 — «мягкая»: нарушением считается только случай,
    когда у первого Paragraph раздела `page_break_before` явно равен
    False. Если значение None (унаследовано/не задано парсером явно) —
    не считаем нарушением, чтобы не плодить ложные срабатывания
    (разрыв может быть задан через Word-стиль заголовка).

    Самый первый LogicalSection документа пропускается — он по умолчанию
    начинается с первой страницы.
    """
    violations: list[Violation] = []
    config = profile.checks.get("S.06")
    required_level = 1
    if config and config.params.get("required_for_level") is not None:
        try:
            required_level = int(config.params["required_for_level"])
        except (TypeError, ValueError):
            required_level = 1

    sections: list[LogicalSection] = []
    for ps in document.page_sections:
        sections.extend(iter_logical_sections(ps.content))

    level_sections = [s for s in sections if s.level == required_level]
    # Первый раздел нужного уровня — на первой странице, разрыв не нужен.
    for section in level_sections[1:]:
        first_para = _first_paragraph(section)
        if first_para is None:
            continue
        if first_para.page_break_before is False:
            heading = _heading_text(section.heading)
            violations.append(
                Violation(
                    check_code="S.06",
                    severity="error",
                    message=(
                        f"Раздел «{heading}» (уровень {required_level}) не начинается "
                        f"с новой страницы"
                    ),
                    location=f"page_sections.*.logical_section[{section.id}]",
                    suggestion=(
                        "Включить разрыв страницы перед заголовком "
                        "(Word: «Разрыв страницы перед» в свойствах абзаца)"
                    ),
                    details={"section_id": section.id, "level": str(required_level)},
                )
            )

    return violations


def _match_expected_index(
    heading: str,
    expected_normalized: list[str],
    aliases_normalized: dict[str, list[str]],
) -> int | None:
    """Если заголовок совпадает с одним из ожидаемых (с учётом алиасов),
    вернуть его индекс в expected. Иначе — None.

    Сравнение по нормализованному (lowercase, схлопнутые пробелы) тексту;
    допускается префиксное совпадение для «Приложение» (например,
    «Приложение А»).
    """
    norm = _normalize(heading)
    if not norm:
        return None
    for idx, expected in enumerate(expected_normalized):
        candidates = [expected, *aliases_normalized.get(expected, [])]
        for cand in candidates:
            if norm == cand:
                return idx
            # Приложения могут быть с буквой/номером: «Приложение А», «Приложение 1»
            if cand == "приложение" and norm.startswith("приложение"):
                return idx
    return None


def _lis_indices(values: Sequence[int]) -> list[int]:
    """Индексы (в исходном values) элементов длиннейшей строго возрастающей
    подпоследовательности. Простая O(n^2) реализация — для нашей задачи
    (десяток разделов) этого более чем достаточно.
    """
    n = len(values)
    if n == 0:
        return []
    # dp[i] = длина LIS, оканчивающейся в i; prev[i] = индекс предыдущего
    dp = [1] * n
    prev = [-1] * n
    best_end = 0
    for i in range(n):
        for j in range(i):
            if values[j] < values[i] and dp[j] + 1 > dp[i]:
                dp[i] = dp[j] + 1
                prev[i] = j
        if dp[i] > dp[best_end]:
            best_end = i
    chain: list[int] = []
    cur = best_end
    while cur != -1:
        chain.append(cur)
        cur = prev[cur]
    chain.reverse()
    return chain


@register("S.02")
def check_sections_order(document: Document, profile: Profile) -> list[Violation]:
    """Найденные подмножество ожидаемых разделов должно идти в правильном порядке.

    Параметр `checks.S.02.params.expected_order` — список заголовков в
    ожидаемом порядке (по умолчанию см. `_DEFAULT_EXPECTED_ORDER`).

    Семантика:
    - Собираем все LogicalSection level==1 в порядке появления.
    - Оставляем только те, чьи заголовки совпали с одним из expected
      (с учётом алиасов).
    - Считаем LIS по их индексам в expected_order.
    - Каждый раздел, не попавший в LIS — Violation (не на своём месте).
    """
    violations: list[Violation] = []
    config = profile.checks.get("S.02")
    expected: list[str] = list(_DEFAULT_EXPECTED_ORDER)
    if config and config.params.get("expected_order"):
        expected = list(config.params["expected_order"])

    expected_normalized = [_normalize(e) for e in expected]
    aliases_normalized: dict[str, list[str]] = {
        _normalize(k): [_normalize(a) for a in v] for k, v in _HEADING_ALIASES.items()
    }

    sections: list[LogicalSection] = []
    for ps in document.page_sections:
        sections.extend(_all_level1_sections(ps.content))

    # Отфильтровать только те, что входят в expected (с алиасами)
    indexed: list[tuple[LogicalSection, int]] = []
    for section in sections:
        text = _heading_text(section.heading)
        idx = _match_expected_index(text, expected_normalized, aliases_normalized)
        if idx is not None:
            indexed.append((section, idx))

    if len(indexed) <= 1:
        return violations

    indices = [idx for _, idx in indexed]
    lis_positions = set(_lis_indices(indices))

    for pos, (section, _idx) in enumerate(indexed):
        if pos in lis_positions:
            continue
        # Найдём предыдущий раздел из LIS — он же ожидался перед текущим
        prev_expected_name: str | None = None
        for j in range(pos - 1, -1, -1):
            if j in lis_positions:
                prev_expected_name = expected[indexed[j][1]]
                break
        heading = _heading_text(section.heading)
        if prev_expected_name:
            msg = (
                f"Раздел «{heading}» расположен не на своём месте; "
                f"ожидался после «{prev_expected_name}»"
            )
        else:
            msg = f"Раздел «{heading}» расположен не на своём месте"
        violations.append(
            Violation(
                check_code="S.02",
                severity="error",
                message=msg,
                location=f"page_sections.*.logical_section[{section.id}]",
                suggestion=(
                    "Расположите разделы в порядке, предусмотренном ГОСТ: "
                    + " → ".join(expected)
                ),
                details={
                    "section_id": section.id,
                    "heading": heading,
                    "expected_after": prev_expected_name or "",
                },
            )
        )
    return violations


__all__ = [
    "check_required_sections",
    "check_section_page_break",
    "check_sections_order",
]
