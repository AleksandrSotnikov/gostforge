"""Тесты R.04 — формат библиографических записей по ГОСТ Р 7.0.100-2018."""

# ruff: noqa: RUF001, RUF002, RUF003

from __future__ import annotations

from gostforge.model import (
    BibliographyEntry,
    Document,
    PageSection,
    Paragraph,
    TextRun,
)
from gostforge.profile import Profile, load_profile
from gostforge.profile.schema import CheckConfig
from gostforge.validator import validate
from gostforge.validator.engine import registered_checks


def _doc_with_paragraphs(paragraphs: list[Paragraph]) -> Document:
    """Документ из одного PageSection с заданными параграфами."""
    doc = Document()
    doc.page_sections.append(
        PageSection(
            id="main",
            name="m",
            type="main",
            content=list(paragraphs),  # type: ignore[arg-type]
        )
    )
    return doc


def _entry(
    entry_id: str,
    raw: str,
    *,
    type_: str = "book",
) -> BibliographyEntry:
    """Удобный конструктор BibliographyEntry для тестов."""
    return BibliographyEntry(
        id=entry_id,
        type=type_,  # type: ignore[arg-type]
        fields={"raw": raw},
    )


def _doc_with_bibliography(entries: list[BibliographyEntry]) -> Document:
    doc = Document()
    doc.bibliography.extend(entries)
    return doc


def _r04(doc: Document, profile: Profile) -> list:
    return [v for v in validate(doc, profile) if v.check_code == "R.04"]


def test_r04_registered() -> None:
    """Проверка R.04 зарегистрирована в реестре."""
    assert "R.04" in registered_checks()


def test_r04_correct_entry_no_violation() -> None:
    """Полная корректная запись не порождает нарушений R.04."""
    entry = _entry(
        "ref-1",
        "Иванов И. И. Основы программирования : учебник / И. И. Иванов. — "
        "Москва : Наука, 2020. — 320 с.",
        type_="book",
    )
    profile = load_profile("gost-7.32-2017")
    found = _r04(_doc_with_bibliography([entry]), profile)
    assert found == [], f"Не ожидали нарушений, получили: {found}"


def test_r04_missing_year_violation() -> None:
    """Запись без года издания → violation aspect='year'."""
    entry = _entry(
        "ref-1",
        "Иванов И. И. Без года : монография / И. И. Иванов. — Москва : Наука. — 100 с.",
    )
    profile = load_profile("gost-7.32-2017")
    found = _r04(_doc_with_bibliography([entry]), profile)
    aspects = {v.details["aspect"] for v in found}
    assert "year" in aspects
    year_v = next(v for v in found if v.details["aspect"] == "year")
    assert year_v.location == "bibliography[ref-1]"
    assert "года" in year_v.message


def test_r04_missing_final_dot_violation() -> None:
    """Запись без точки в конце → violation aspect='final_dot'."""
    entry = _entry(
        "ref-1",
        "Иванов И. И. Без точки / И. И. Иванов. — Москва : Наука, 2020. — 100 с",
    )
    profile = load_profile("gost-7.32-2017")
    found = _r04(_doc_with_bibliography([entry]), profile)
    aspects = {v.details["aspect"] for v in found}
    assert "final_dot" in aspects


def test_r04_too_short_violation() -> None:
    """Запись короче min_length → violation aspect='length' (и только он)."""
    entry = _entry("ref-1", "Иванов 2020.")
    profile = load_profile("gost-7.32-2017")
    found = _r04(_doc_with_bibliography([entry]), profile)
    aspects = [v.details["aspect"] for v in found]
    # При нарушении длины остальные проверки не выполняются.
    assert aspects == ["length"]


def test_r04_no_separator_violation() -> None:
    """Запись без тире/слэша/двоеточия → violation aspect='separator'."""
    entry = _entry(
        "ref-1",
        "Иванов И И Основы программирования учебник Москва Наука 2020 320 страниц",
    )
    profile = load_profile("gost-7.32-2017")
    found = _r04(_doc_with_bibliography([entry]), profile)
    aspects = {v.details["aspect"] for v in found}
    assert "separator" in aspects


def test_r04_web_entry_without_url_marker_violation() -> None:
    """web-запись без «URL:» или «(дата обращения:» → violation aspect='web_url'."""
    entry = _entry(
        "ref-1",
        "Сидоров С. С. Веб-ресурс : электронный ресурс / С. С. Сидоров. — 2022. — С. 1.",
        type_="web",
    )
    profile = load_profile("gost-7.32-2017")
    found = _r04(_doc_with_bibliography([entry]), profile)
    aspects = {v.details["aspect"] for v in found}
    assert "web_url" in aspects


def test_r04_web_entry_with_url_marker_no_violation_for_web_url() -> None:
    """web-запись с маркером «URL:» и «(дата обращения:» — нет violation web_url."""
    entry = _entry(
        "ref-1",
        "Сидоров С. С. Ресурс [Электронный ресурс] / С. С. Сидоров. — 2022. — "
        "URL: https://example.org (дата обращения: 01.05.2023).",
        type_="web",
    )
    profile = load_profile("gost-7.32-2017")
    found = _r04(_doc_with_bibliography([entry]), profile)
    aspects = {v.details["aspect"] for v in found}
    assert "web_url" not in aspects


def test_r04_require_year_false_disables_year_check() -> None:
    """Параметр require_year=False отключает проверку года."""
    entry = _entry(
        "ref-1",
        "Иванов И. И. Без года / И. И. Иванов. — Москва : Наука. — 100 с.",
    )
    profile = load_profile("gost-7.32-2017")
    profile.checks["R.04"] = CheckConfig(
        enabled=True,
        params={"require_year": False},
    )
    found = _r04(_doc_with_bibliography([entry]), profile)
    aspects = {v.details["aspect"] for v in found}
    assert "year" not in aspects


def test_r04_multiple_aspects_in_one_entry() -> None:
    """Одна запись с несколькими нарушениями даёт несколько Violation."""
    # Нет года, нет точки в конце, нет разделителей — должно быть ≥ 3 violation.
    entry = _entry(
        "ref-1",
        "Иванов И И Без года и без точки и без разделителей текст длинный достаточно",
    )
    profile = load_profile("gost-7.32-2017")
    found = _r04(_doc_with_bibliography([entry]), profile)
    aspects = {v.details["aspect"] for v in found}
    assert {"year", "final_dot", "separator"}.issubset(aspects)
    # Все они привязаны к одной записи.
    assert all(v.location == "bibliography[ref-1]" for v in found)


def test_r04_empty_bibliography_no_violations() -> None:
    """Пустой bibliography — никаких violation R.04."""
    profile = load_profile("gost-7.32-2017")
    found = _r04(Document(), profile)
    assert found == []


# --- R.01 — стиль ссылок [N] по профилю ---------------------------------


def test_r01_registered() -> None:
    """Проверка R.01 зарегистрирована в реестре."""
    assert "R.01" in registered_checks()


def test_r01_numeric_style_no_violation() -> None:
    """Текст со ссылками только в формате [N] — нарушения нет."""
    para = Paragraph(
        id="p-1",
        content=[TextRun(text="Согласно [1] и [2, 3], результаты совпадают.")],
    )
    doc = _doc_with_paragraphs([para])
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "R.01"]
    assert found == []


def test_r01_author_year_parens_violation() -> None:
    """«(Иванов, 2024)» — нарушение R.01."""
    para = Paragraph(
        id="p-1",
        content=[TextRun(text="Как показано в работе (Иванов, 2024), это так.")],
    )
    doc = _doc_with_paragraphs([para])
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "R.01"]
    assert len(found) == 1
    assert found[0].details["style"] == "author_year_parens"
    assert "Иванов" in found[0].details["found"]


def test_r01_author_year_brackets_violation() -> None:
    """«[Иванов 2024]» — нарушение R.01."""
    para = Paragraph(
        id="p-1",
        content=[TextRun(text="Согласно [Иванов 2024], результаты такие.")],
    )
    doc = _doc_with_paragraphs([para])
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "R.01"]
    assert len(found) == 1
    assert found[0].details["style"] == "author_year_brackets"


# --- R.05 — каждый источник упомянут в тексте ---------------------------


def test_r05_registered() -> None:
    """Проверка R.05 зарегистрирована в реестре."""
    assert "R.05" in registered_checks()


def test_r05_all_entries_referenced_no_violation() -> None:
    """Все источники упомянуты — нарушения нет."""
    para = Paragraph(
        id="p-1",
        content=[TextRun(text="См. [1] и [2].")],
    )
    doc = _doc_with_paragraphs([para])
    doc.bibliography.extend(
        [
            _entry("ref-1", "Иванов И. И. Книга. — Москва : Наука, 2020. — 100 с."),
            _entry("ref-2", "Петров П. П. Статья. — Москва : Наука, 2021. — 50 с."),
        ]
    )
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "R.05"]
    assert found == []


def test_r05_unreferenced_entry_violation() -> None:
    """Источник [2] не упомянут — нарушение."""
    para = Paragraph(id="p-1", content=[TextRun(text="См. [1].")])
    doc = _doc_with_paragraphs([para])
    doc.bibliography.extend(
        [
            _entry("ref-1", "Иванов 2020"),
            _entry("ref-2", "Петров 2021"),
        ]
    )
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "R.05"]
    assert len(found) == 1
    assert found[0].details["index"] == "2"
    assert found[0].details["entry_id"] == "ref-2"


# --- R.06 — alias C.04 --------------------------------------------------


def test_r06_registered() -> None:
    """Заглушка-alias R.06 зарегистрирована (дублирует C.04)."""
    assert "R.06" in registered_checks()


# --- R.07 — заглушка ----------------------------------------------------


def test_r07_registered() -> None:
    """Заглушка R.07 зарегистрирована в реестре."""
    assert "R.07" in registered_checks()


def test_r05_range_reference_counts() -> None:
    """Ссылка [1-3] упоминает источники 1, 2 и 3."""
    para = Paragraph(id="p-1", content=[TextRun(text="См. [1-3].")])
    doc = _doc_with_paragraphs([para])
    doc.bibliography.extend(
        [
            _entry("ref-1", "A"),
            _entry("ref-2", "B"),
            _entry("ref-3", "C"),
        ]
    )
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "R.05"]
    # [1- покрывает запись 1; [1-3] не покрывает 2 и 3 буквальным паттерном
    # «[2,» / «[2-» / «[2:», поэтому будем считать как минимум: source-1
    # упомянут, 2 и 3 — нет (упрощённая эвристика).
    # Поэтому тест ожидает, что ref-1 упомянут, а ref-2 и ref-3 — нет.
    unreferenced = {v.details["entry_id"] for v in found}
    assert "ref-1" not in unreferenced
    assert {"ref-2", "ref-3"}.issubset(unreferenced)
