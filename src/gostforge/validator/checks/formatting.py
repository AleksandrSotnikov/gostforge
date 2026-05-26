"""F.* — проверки параметров страницы."""

from __future__ import annotations

from gostforge.model import ContentTemplate, Document, TextRun
from gostforge.profile import Profile

from ..engine import Violation, register


# Плейсхолдер, который парсер ставит в footer/header, когда находит
# поле PAGE в OOXML (instrText="PAGE" или fldSimple).
_PAGE_PLACEHOLDER = "{page}"


def _template_has_placeholder(template: ContentTemplate | None, placeholder: str) -> bool:
    """Есть ли заданный плейсхолдер в каком-либо из слотов шаблона (left/center/right)."""
    if template is None:
        return False
    for slot in (template.left, template.center, template.right):
        if slot is None:
            continue
        for el in slot:
            if isinstance(el, TextRun) and placeholder in el.text:
                return True
    return False


def _placeholder_at(template: ContentTemplate | None, slot: str, placeholder: str) -> bool:
    """Лежит ли плейсхолдер именно в указанном слоте."""
    if template is None:
        return False
    content = getattr(template, slot, None)
    if content is None:
        return False
    for el in content:
        if isinstance(el, TextRun) and placeholder in el.text:
            return True
    return False


@register("F.01")
def check_margins(document: Document, profile: Profile) -> list[Violation]:
    """Проверка полей страницы.

    Эталонные поля берутся из профиля (по умолчанию 30/20/20/15 мм для ГОСТ 7.32).
    Допустимое отклонение — 0.5 мм.
    """
    violations: list[Violation] = []
    expected = profile.styles.page.margins_mm
    tolerance = 0.5

    for section in document.page_sections:
        actual = section.page.margins_mm
        for side in ("top", "right", "bottom", "left"):
            exp = expected.get(side)
            act = actual.get(side)
            if exp is None or act is None:
                continue
            if abs(exp - act) > tolerance:
                violations.append(
                    Violation(
                        check_code="F.01",
                        severity="error",
                        message=(
                            f"Поле «{side}» в секции «{section.name}» = {act} мм, "
                            f"ожидается {exp} мм"
                        ),
                        location=f"page_sections.{section.id}.page.margins_mm.{side}",
                        suggestion=f"Установить поле {side} = {exp} мм",
                        details={"expected": str(exp), "actual": str(act)},
                    )
                )
    return violations


@register("F.04")
def check_page_number_position(document: Document, profile: Profile) -> list[Violation]:
    """Проверка положения номера страницы.

    Параметр профиля `checks.F.04.params.position`: одно из значений
    `bottom_center` (по умолчанию), `bottom_right`, `bottom_left`,
    `top_center`, `top_right`, `top_left`.

    Парсер кладёт плейсхолдер `{page}` в соответствующий слот footer/header
    при обнаружении поля PAGE в OOXML.
    """
    violations: list[Violation] = []
    config = profile.checks.get("F.04")
    position = "bottom_center"
    if config and config.params.get("position"):
        position = str(config.params["position"])

    try:
        vertical, slot = position.split("_", 1)
    except ValueError:
        # Конфигурация профиля невалидна — это ошибка не документа, а профиля.
        # Тихо выходим, чтобы не валить весь прогон. Будет покрыто валидацией
        # профиля отдельно.
        return violations

    if vertical not in {"top", "bottom"} or slot not in {"left", "center", "right"}:
        return violations

    for section in document.page_sections:
        if not section.page_numbering.visible:
            continue

        target = section.footer if vertical == "bottom" else section.header

        if not _template_has_placeholder(target.default if target else None, _PAGE_PLACEHOLDER):
            violations.append(
                Violation(
                    check_code="F.04",
                    severity="error",
                    message=(
                        f"В секции «{section.name}» включена нумерация страниц, "
                        f"но поле PAGE в {vertical}-колонтитуле не найдено"
                    ),
                    location=f"page_sections.{section.id}.{vertical}.default",
                    suggestion=(
                        f"Добавить поле PAGE в {slot}-слот нижнего колонтитула"
                        if vertical == "bottom"
                        else f"Добавить поле PAGE в {slot}-слот верхнего колонтитула"
                    ),
                    details={"expected_position": position},
                )
            )
            continue

        # Поле есть, но проверим, в правильном ли слоте
        if not _placeholder_at(target.default if target else None, slot, _PAGE_PLACEHOLDER):
            violations.append(
                Violation(
                    check_code="F.04",
                    severity="error",
                    message=(
                        f"Номер страницы в секции «{section.name}» расположен не в "
                        f"ожидаемом положении ({position})"
                    ),
                    location=f"page_sections.{section.id}.{vertical}.default.{slot}",
                    suggestion=f"Переместить поле PAGE в {slot}-слот {vertical}-колонтитула",
                    details={"expected_position": position},
                )
            )

    return violations


@register("F.06")
def check_page_numbering_start(document: Document, profile: Profile) -> list[Violation]:
    """Проверка стартового значения нумерации страниц.

    Параметр профиля `checks.F.06.params.start_value` задаёт ожидаемое
    значение `<w:pgNumType w:start="N"/>` в первой секции (например, 3 —
    нумерация продолжается с титула, но видна только начиная с третьей
    страницы).

    Семантика «мягкая»: проверяем только те PageSection, где
    `page_numbering.visible=True` и `start_mode="start_at"`. Если в
    секции `start_mode="continue"` — считаем, что нумерация продолжается
    с предыдущей секции и явное значение не требуется. Если параметр
    профиля не задан — проверка пропускается.
    """
    violations: list[Violation] = []
    config = profile.checks.get("F.06")
    expected_raw = config.params.get("start_value") if config else None
    if expected_raw is None:
        return violations
    try:
        expected = int(expected_raw)
    except (TypeError, ValueError):
        # Невалидное значение в профиле — лучше не сыпать ложными нарушениями.
        return violations

    for section in document.page_sections:
        numbering = section.page_numbering
        if not numbering.visible:
            continue
        if numbering.start_mode != "start_at":
            # Мягкая семантика Фазы 1: continue/restart — пропускаем.
            continue
        actual = numbering.start_value
        if actual is None or actual == expected:
            continue
        violations.append(
            Violation(
                check_code="F.06",
                severity="error",
                message=(
                    f"В секции «{section.name}» нумерация начинается со страницы "
                    f"{actual}, ожидается {expected}"
                ),
                location=f"page_sections.{section.id}.page_numbering.start_value",
                suggestion=f"Установить стартовое значение нумерации = {expected}",
                details={"expected": str(expected), "actual": str(actual)},
            )
        )
    return violations


@register("F.05")
def check_page_number_format(document: Document, profile: Profile) -> list[Violation]:
    """Проверка формата нумерации страниц.

    По ГОСТ 7.32-2017 — арабские цифры. Параметр `checks.F.05.params.format`
    может переопределить ожидание: `arabic` (по умолчанию), `roman`,
    `uppercase_letter`. Проверка применяется только к секциям, где
    `page_numbering.visible = True`.
    """
    violations: list[Violation] = []
    config = profile.checks.get("F.05")
    expected = "arabic"
    if config and config.params.get("format"):
        expected = str(config.params["format"])

    for section in document.page_sections:
        numbering = section.page_numbering
        if not numbering.visible:
            continue
        if numbering.format == expected:
            continue
        violations.append(
            Violation(
                check_code="F.05",
                severity="error",
                message=(
                    f"В секции «{section.name}» нумерация в формате "
                    f"«{numbering.format}», ожидается «{expected}»"
                ),
                location=f"page_sections.{section.id}.page_numbering.format",
                suggestion=f"Установить формат нумерации «{expected}» (арабские цифры)",
                details={"expected": expected, "actual": numbering.format},
            )
        )
    return violations


@register("F.02")
def check_paper_size(document: Document, profile: Profile) -> list[Violation]:
    """Проверка формата бумаги (по умолчанию A4).

    Параметр `checks.F.02.params.paper`: ожидаемый формат (по умолчанию из
    `profile.styles.page.size` или «A4»).
    """
    violations: list[Violation] = []
    config = profile.checks.get("F.02")
    expected = profile.styles.page.size or "A4"
    if config and config.params.get("paper"):
        expected = str(config.params["paper"])

    for section in document.page_sections:
        actual = section.page.paper
        if actual == expected:
            continue
        violations.append(
            Violation(
                check_code="F.02",
                severity="error",
                message=(
                    f"Формат бумаги в секции «{section.name}» — «{actual}», ожидается «{expected}»"
                ),
                location=f"page_sections.{section.id}.page.paper",
                suggestion=f"Установить формат бумаги «{expected}»",
                details={"expected": expected, "actual": actual},
            )
        )
    return violations


@register("F.03")
def check_orientation(document: Document, profile: Profile) -> list[Violation]:
    """Проверка ориентации страницы (по умолчанию portrait).

    Параметр `checks.F.03.params.orientation`: portrait | landscape.
    Секции типа `appendix` пропускаются — у приложений по ГОСТ может быть
    альбомная ориентация.
    """
    violations: list[Violation] = []
    config = profile.checks.get("F.03")
    expected = "portrait"
    if config and config.params.get("orientation"):
        expected = str(config.params["orientation"])

    for section in document.page_sections:
        if section.type == "appendix":
            continue
        if section.page.orientation == expected:
            continue
        violations.append(
            Violation(
                check_code="F.03",
                severity="warning",
                message=(
                    f"Ориентация секции «{section.name}» — «{section.page.orientation}», "
                    f"ожидается «{expected}»"
                ),
                location=f"page_sections.{section.id}.page.orientation",
                suggestion=f"Установить ориентацию «{expected}»",
                details={"expected": expected, "actual": section.page.orientation},
            )
        )
    return violations
