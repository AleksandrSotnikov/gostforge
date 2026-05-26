"""M.* — проверки формул."""

from __future__ import annotations

import re
from collections.abc import Sequence

from gostforge.model import (
    Block,
    Document,
    Formula,
    LogicalSection,
    PageSection,
    Paragraph,
    TextRun,
)
from gostforge.profile import Profile

from ..engine import Severity, Violation, register


def _iter_formulas(items: Sequence[LogicalSection | Block]) -> list[Formula]:
    """Рекурсивно собрать все Formula из content (через LogicalSection.children)."""
    result: list[Formula] = []
    for item in items:
        if isinstance(item, Formula):
            result.append(item)
        elif isinstance(item, LogicalSection):
            result.extend(_iter_formulas(item.children))
    return result


def _all_formulas(document: Document) -> list[tuple[PageSection, Formula]]:
    """Все Formula документа — со ссылкой на PageSection (для location)."""
    result: list[tuple[PageSection, Formula]] = []
    for ps in document.page_sections:
        for formula in _iter_formulas(ps.content):
            result.append((ps, formula))
    return result


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


@register("M.01")
def check_formula_has_number(document: Document, profile: Profile) -> list[Violation]:
    """Нумерация формулы оформлена номером в круглых скобках справа.

    Параметры:
    - `required` (bool, default False): если True, формула без номера
      считается ошибкой (severity=error). По умолчанию — soft проверка
      с severity=warning, что соответствует ситуации, когда нумерация
      может отсутствовать или быть нераспознанной парсером.

    Формулы с непустым latex и пустым number трактуются как «нумерация
    не распознана / отсутствует». Формулы с пустым latex пропускаются —
    это вырожденный случай, который не должен порождать дубль-нарушений.
    """
    violations: list[Violation] = []
    config = profile.checks.get("M.01")
    required = False
    if config and config.params.get("required") is not None:
        required = bool(config.params["required"])
    severity: Severity = "error" if required else "warning"

    for page_section, formula in _all_formulas(document):
        if not formula.latex or not formula.latex.strip():
            continue
        if formula.number is not None:
            continue
        violations.append(
            Violation(
                check_code="M.01",
                severity=severity,
                message=(f"У формулы «{formula.id}» отсутствует номер в круглых скобках"),
                location=f"page_sections.{page_section.id}.formula[{formula.id}]",
                suggestion=("Указать номер формулы в круглых скобках справа: «(1)»"),
                details={"formula_id": formula.id},
            )
        )
    return violations


@register("M.03")
def check_formula_numbering_continuous(document: Document, profile: Profile) -> list[Violation]:
    """Сквозная нумерация формул: номера должны идти 1, 2, 3, ...

    Формулы без номера (`number is None`) пропускаются — это случай M.01.

    Возможные нарушения:
    - пропуск: после формулы N ожидается N+1, найдена M (M > N+1);
    - дубликат: один и тот же номер встречается у двух формул.
    """
    violations: list[Violation] = []
    numbered: list[tuple[Formula, int]] = [
        (formula, formula.number)
        for _ps, formula in _all_formulas(document)
        if formula.number is not None
    ]
    if not numbered:
        return violations

    seen: dict[int, Formula] = {}
    expected = 1
    for formula, num in numbered:
        if num in seen:
            previous = seen[num]
            violations.append(
                Violation(
                    check_code="M.03",
                    severity="error",
                    message=(
                        f"Номер {num} встречается у двух формул: «{previous.id}» и «{formula.id}»"
                    ),
                    location=f"formula[{formula.id}]",
                    suggestion=(
                        "Перенумеровать формулы так, чтобы каждая имела уникальный сквозной номер"
                    ),
                    details={
                        "formula_id": formula.id,
                        "duplicate_of": previous.id,
                        "number": str(num),
                    },
                )
            )
            continue
        seen[num] = formula
        if num != expected:
            violations.append(
                Violation(
                    check_code="M.03",
                    severity="error",
                    message=(
                        f"После формулы {expected - 1} ожидается формула {expected}, найдено {num}"
                    ),
                    location=f"formula[{formula.id}]",
                    suggestion=(f"Перенумеровать формулу: «({expected})» вместо «({num})»"),
                    details={
                        "formula_id": formula.id,
                        "expected": str(expected),
                        "found": str(num),
                    },
                )
            )
            expected = num + 1
        else:
            expected += 1

    return violations


# Регэкспы для поиска ссылок на формулу N в тексте. Все case-insensitive.
def _formula_reference_patterns(num: int) -> list[re.Pattern[str]]:
    """Сформировать regex'ы вида «(N)», «формула N», «формуле N» для номера N."""
    return [
        # «(N)» — строго в круглых скобках, чтобы не реагировать на любые
        # вхождения числа N в тексте.
        re.compile(rf"\(\s*{num}\s*\)"),
        re.compile(rf"формула\s+{num}\b", re.IGNORECASE),
        re.compile(rf"формуле\s+{num}\b", re.IGNORECASE),
        re.compile(rf"формулу\s+{num}\b", re.IGNORECASE),
        re.compile(rf"формулы\s+{num}\b", re.IGNORECASE),
    ]


@register("M.04")
def check_formula_referenced_in_text(document: Document, profile: Profile) -> list[Violation]:
    """На каждую нумерованную формулу должна быть ссылка в тексте.

    Для каждой Formula с непустым `number` ищем в склеенном тексте всех
    Paragraph документа упоминание вида `(N)`, «формула N», «формуле N»
    (case-insensitive для слов «формула...»). Если ни одной ссылки не
    найдено — Violation (severity=warning).

    Ненумерованные формулы пропускаются — на них ссылки не обязательны.
    """
    violations: list[Violation] = []

    # Один раз склеиваем весь текст документа из параграфов.
    all_text = "\n".join(_paragraph_text(p) for p in _all_paragraphs(document))

    for page_section, formula in _all_formulas(document):
        if formula.number is None:
            continue
        num = formula.number
        if any(p.search(all_text) for p in _formula_reference_patterns(num)):
            continue
        violations.append(
            Violation(
                check_code="M.04",
                severity="warning",
                message=(f"В тексте отсутствует ссылка на формулу {num} «{formula.id}»"),
                location=f"page_sections.{page_section.id}.formula[{formula.id}]",
                suggestion=(
                    f"Добавить в текст ссылку вида «по формуле ({num})» или «в формуле {num}»"
                ),
                details={"formula_id": formula.id, "number": str(num)},
            )
        )
    return violations


# M.02: распознаём «где: ...» или «здесь: ...» в начале параграфа.
# Поддерживаем варианты с двоеточием/запятой/тире/пробелом следом.
_VARIABLES_EXPLAIN_RE = re.compile(r"^\s*(где|здесь)\b", re.IGNORECASE)


def _flatten_blocks(items: Sequence[LogicalSection | Block]) -> list[Block]:
    """Собрать линейный список Block-ов из вложенных LogicalSection.

    Используется M.02: после каждой Formula нужно проверить «соседей»
    в линейном порядке документа — формула в LogicalSection и параграф
    с пояснениями переменных должны идти один за другим в линейной
    последовательности блоков.
    """
    result: list[Block] = []
    for item in items:
        if isinstance(item, Block):
            result.append(item)
        elif isinstance(item, LogicalSection):
            result.extend(_flatten_blocks(item.children))
    return result


def _all_blocks_linear(document: Document) -> list[Block]:
    """Все Block-и документа, в линейном порядке обхода PageSection.content."""
    blocks: list[Block] = []
    for ps in document.page_sections:
        blocks.extend(_flatten_blocks(ps.content))
    return blocks


@register("M.02")
def check_formula_variables_explained(document: Document, profile: Profile) -> list[Violation]:
    """После нумерованной формулы должны идти пояснения переменных.

    Эвристика Фазы 1: для каждой Formula с `number is not None` смотрим
    следующие 3 блока в линейной последовательности документа. Если
    среди них нет Paragraph, начинающегося со слова «где» или «здесь»
    (case-insensitive) — Violation (severity=warning). Ненумерованные
    формулы пропускаем — обычно у них нет переменных, требующих
    пояснения.
    """
    _ = profile  # параметров пока нет, но сигнатура единая для всех проверок
    violations: list[Violation] = []
    blocks = _all_blocks_linear(document)
    # Для location нам нужно знать PageSection — построим карту.
    formula_to_ps: dict[str, PageSection] = {}
    for ps, formula in _all_formulas(document):
        formula_to_ps[formula.id] = ps

    look_ahead = 3
    for idx, block in enumerate(blocks):
        if not isinstance(block, Formula):
            continue
        if block.number is None:
            continue
        following = blocks[idx + 1 : idx + 1 + look_ahead]
        explained = False
        for nb in following:
            if not isinstance(nb, Paragraph):
                continue
            text = _paragraph_text(nb).lstrip()
            if _VARIABLES_EXPLAIN_RE.match(text):
                explained = True
                break
        if explained:
            continue
        owning_ps = formula_to_ps.get(block.id)
        location = (
            f"page_sections.{owning_ps.id}.formula[{block.id}]"
            if owning_ps is not None
            else f"formula[{block.id}]"
        )
        violations.append(
            Violation(
                check_code="M.02",
                severity="warning",
                message=(
                    f"После формулы «{block.id}» (номер {block.number}) "
                    "не найдено пояснение переменных «где: ...»"
                ),
                location=location,
                suggestion=(
                    "Добавить после формулы абзац с пояснением переменных, "
                    "начинающийся словом «где» (или «здесь»)"
                ),
                details={
                    "formula_id": block.id,
                    "number": str(block.number),
                },
            )
        )
    return violations


@register("M.05")
def check_formula_centered(document: Document, profile: Profile) -> list[Violation]:
    """Формула должна быть выровнена по центру.

    На Фазе 1 у Formula нет поля alignment в модели — проверка
    зарегистрирована «вхолостую», чтобы быть в реестре и в YAML-профиле.
    Реальная логика появится на Фазе 2, когда в модели Formula появится
    выравнивание (или когда мы будем знать выравнивание родительского
    параграфа в OOXML).

    # TODO Phase 2: добавить alignment в модель Formula
    """
    _ = (document, profile)  # no-op
    return []


__all__ = [
    "check_formula_centered",
    "check_formula_has_number",
    "check_formula_numbering_continuous",
    "check_formula_referenced_in_text",
    "check_formula_variables_explained",
]
