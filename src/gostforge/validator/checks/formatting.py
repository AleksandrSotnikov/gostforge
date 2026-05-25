"""F.* — проверки параметров страницы."""

from __future__ import annotations

from gostforge.model import Document
from gostforge.profile import Profile

from ..engine import Violation, register


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


# TODO: F.02 — формат бумаги
# TODO: F.03 — ориентация
# TODO: F.04 — положение номера страницы
# TODO: F.05 — формат номера
# TODO: F.06 — стартовая страница нумерации
