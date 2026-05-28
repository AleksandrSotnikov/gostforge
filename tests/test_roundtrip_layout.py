"""Сквозной тест вёрстки: builder → export → parse → validate.

Проверяет, что сгенерированный конструктором документ при обратной
парсовке не получает нарушений категории «вёрстки» от собственного
нормоконтроля системы:

* F.01 — поля страницы,
* F.02 — размер бумаги (A4),
* F.03 — ориентация (portrait),
* T.01..T.05 — шрифт, кегль, межстрочный, отступ, выравнивание,
* H.01, H.02 — формат заголовков 1-2 уровней (font, size, bold,
  uppercase, color — благодаря style-cascade в парсере),
* H.07 — отступы между заголовками.

После усиления парсера style-cascade-логикой (см. _style_color_hex,
_style_bold, _style_italic в docx_parser.py) и добавления color-
проверки в H.01/H.02 этот тест ловит регрессии в _apply_heading_styles
и _sync_linked_char_style: если их отключить — H.01 находит цвет
#365F91 и шрифт Cambria, который наследуется от дефолтного шаблона
Word. См. tests/test_style_cascade.py для прямого guard-а на
этот сценарий.

Параметризуется по ВСЕМ профилям в profiles/ — добавление нового
профиля автоматически попадает в guard.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path

import pytest

from gostforge.builder import work
from gostforge.exporter import export_docx
from gostforge.parser import parse_docx
from gostforge.profile import list_profiles, load_profile
from gostforge.validator import validate

# Коды проверок, целиком зависящих от вёрстки (а не от контента).
# Любое нарушение из этого набора на сгенерированном документе =
# регрессия экспортёра.
LAYOUT_CHECK_CODES = frozenset(
    {
        "F.01",  # поля страницы
        "F.02",  # размер бумаги (A4)
        "F.03",  # ориентация (portrait)
        "F.04",  # позиция номера страницы (bottom_center)
        "F.05",  # формат нумерации (arabic)
        "F.06",  # стартовое значение нумерации (из профиля)
        "T.01",  # шрифт (Times New Roman)
        "T.02",  # кегль (14)
        "T.03",  # межстрочный интервал (1.5)
        "T.04",  # отступ первой строки (1.25 см)
        "T.05",  # выравнивание (justify)
        "H.01",  # формат заголовка 1 (жирный, центр, TNR, ВЕРХ. регистр, цвет)
        "H.02",  # формат заголовка 2 (жирный, слева, цвет)
        "H.07",  # отступы между заголовками (spacing_before/after)
    }
)


def _make_full_document_builder():  # type: ignore[no-untyped-def]
    """Собрать максимально полный документ — со всеми обязательными
    разделами по ГОСТ 7.32 и ЕСКД. Контент минимальный, чтобы не
    срабатывали content-проверки сверх того, что мы хотим проверить.

    Если профилю не хватает раздела (например, ЕСКД хочет «Содержание»
    вместо «Реферата») — это покрывается обоими: добавляем оба.
    """
    return (
        work("Анализ алгоритмов сортировки", author="Иванов И. И.", year=2026)
        .section("Реферат")
        .paragraph(
            "Работа объёмом 25 страниц содержит 3 рисунка, 2 таблицы, "
            "15 источников. Ключевые слова: алгоритмы, сортировка."
        )
        .section("Содержание")
        .paragraph("Введение ... 3")
        .paragraph("1 Анализ ... 5")
        .paragraph("Заключение ... 20")
        .section("Введение")
        .paragraph(
            "Актуальность темы исследования заключается в широком "
            "применении алгоритмов сортировки в программных системах."
        )
        .paragraph("Цель работы — сравнить эффективность алгоритмов.")
        .section("1 Анализ алгоритмов")
        .paragraph("В данной главе рассматриваются классические алгоритмы сортировки.")
        .table(
            headers=["Алгоритм", "Сложность"],
            rows=[["Быстрая сортировка", "O(n log n)"]],
            caption="Сложность алгоритмов",
        )
        .section("Заключение")
        .paragraph(
            "В ходе работы достигнуты все поставленные задачи. "
            "Получены количественные оценки эффективности алгоритмов."
        )
        .section("Список использованных источников")
        .reference("Кнут Д. Э. Искусство программирования. — М. : Вильямс, 2007. — 832 с.")
    )


@pytest.mark.parametrize("profile_id", list_profiles())
def test_generated_document_has_no_layout_violations(tmp_path: Path, profile_id: str) -> None:
    """Сгенерированный документ не нарушает ни одну вёрсточную проверку.

    Стратегия: builder собирает документ → export_docx пишет .docx →
    parse_docx читает его обратно в Document → validate прогоняет
    все проверки → отфильтровываем по LAYOUT_CHECK_CODES → ожидаем 0.
    """
    document = _make_full_document_builder().build()
    profile = load_profile(profile_id)

    out_path = tmp_path / f"generated-{profile_id}.docx"
    export_docx(document, profile, out_path)

    parsed = parse_docx(out_path)
    parsed.profile_id = profile_id
    violations = validate(parsed, profile)

    layout_violations = [v for v in violations if v.check_code in LAYOUT_CHECK_CODES]
    if layout_violations:
        # Подробная диагностика для удобства fail-message.
        by_code = Counter(v.check_code for v in layout_violations)
        messages = "\n".join(
            f"  {v.check_code} @ {v.location}: {v.message}" for v in layout_violations
        )
        pytest.fail(
            f"Профиль {profile_id}: найдено {len(layout_violations)} "
            f"вёрсточных нарушений ({dict(by_code)}):\n{messages}"
        )


@pytest.mark.parametrize("profile_id", list_profiles())
def test_generated_document_is_parseable(tmp_path: Path, profile_id: str) -> None:
    """Сгенерированный документ корректно парсится обратно.

    Тривиальный smoke — без него test_generated_document_has_no_layout_violations
    скрывал бы parse-ошибки за raise внутри validate.
    """
    document = _make_full_document_builder().build()
    profile = load_profile(profile_id)
    out_path = tmp_path / f"parseable-{profile_id}.docx"
    export_docx(document, profile, out_path)

    parsed = parse_docx(out_path)
    # Хотя бы одна логическая секция должна быть распознана.
    assert parsed.page_sections, "Парсер не нашёл page_sections"


def test_layout_check_codes_are_real() -> None:
    """LAYOUT_CHECK_CODES — коды реально существующих проверок.

    Если в реестре переименуется проверка (например, T.01 → T.21),
    тест должен это поймать — иначе guard молча перестанет работать.
    """
    from gostforge.validator.engine import _registry

    registered = set(_registry.keys())
    missing = LAYOUT_CHECK_CODES - registered
    assert not missing, (
        f"LAYOUT_CHECK_CODES содержит коды, не зарегистрированные в engine: {sorted(missing)}"
    )
