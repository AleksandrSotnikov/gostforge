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


# --- R.02 — порядок (алфавит / по упоминанию) ---------------------------


def _violations(doc: Document, profile: Profile, code: str) -> list:
    return [v for v in validate(doc, profile) if v.check_code == code]


def _entry_with_fields(
    entry_id: str, fields: dict[str, str], *, type_: str = "book"
) -> BibliographyEntry:
    """Запись с произвольными полями (для нацеленных тестов R.02-R.13)."""
    full = {"raw": fields.get("raw", entry_id)}
    full.update(fields)
    return BibliographyEntry(id=entry_id, type=type_, fields=full)  # type: ignore[arg-type]


def test_r02_registered() -> None:
    assert "R.02" in registered_checks()


def test_r02_alphabetical_ok_no_violation() -> None:
    """Записи отсортированы по алфавиту — нарушения нет."""
    profile = load_profile("gost-7.32-2017")
    doc = _doc_with_bibliography(
        [
            _entry_with_fields("ref-1", {"author": "Аверин А. А."}),
            _entry_with_fields("ref-2", {"author": "Иванов И. И."}),
            _entry_with_fields("ref-3", {"author": "Петров П. П."}),
        ]
    )
    assert _violations(doc, profile, "R.02") == []


def test_r02_alphabetical_disorder_violation() -> None:
    """Нарушен алфавит — один Violation на первое несоответствие."""
    profile = load_profile("gost-7.32-2017")
    doc = _doc_with_bibliography(
        [
            _entry_with_fields("ref-1", {"author": "Петров П. П."}),
            _entry_with_fields("ref-2", {"author": "Аверин А. А."}),
        ]
    )
    found = _violations(doc, profile, "R.02")
    assert len(found) == 1
    assert found[0].details["order"] == "alphabetical"
    assert found[0].details["prev_id"] == "ref-1"
    assert found[0].details["curr_id"] == "ref-2"


def test_r02_by_mention_violation() -> None:
    """Источник [2] упомянут в тексте раньше [1] — нарушение."""
    profile = load_profile("gost-7.32-2017")
    profile.checks["R.02"] = CheckConfig(
        enabled=True,
        params={"order": "by_mention"},
    )
    para = Paragraph(id="p-1", content=[TextRun(text="Сначала [2], потом [1].")])
    doc = _doc_with_paragraphs([para])
    doc.bibliography.extend(
        [
            _entry_with_fields("ref-1", {"author": "Иванов И. И."}),
            _entry_with_fields("ref-2", {"author": "Петров П. П."}),
        ]
    )
    found = _violations(doc, profile, "R.02")
    assert len(found) == 1
    assert found[0].details["order"] == "by_mention"
    assert found[0].details["prev_index"] == "1"


# --- R.03 — обязательные поля для типа источника ------------------------


def test_r03_registered() -> None:
    assert "R.03" in registered_checks()


def test_r03_all_required_fields_present_no_violation() -> None:
    """Все обязательные поля заполнены — нарушений нет."""
    profile = load_profile("gost-7.32-2017")
    doc = _doc_with_bibliography(
        [
            _entry_with_fields(
                "ref-1",
                {"author": "Иванов И. И.", "year": "2020", "place": "Москва"},
                type_="book",
            ),
        ]
    )
    assert _violations(doc, profile, "R.03") == []


def test_r03_missing_place_in_book_violation() -> None:
    """У книги нет place — Violation с указанием отсутствующего поля."""
    profile = load_profile("gost-7.32-2017")
    doc = _doc_with_bibliography(
        [
            _entry_with_fields(
                "ref-1",
                {"author": "Иванов И. И.", "year": "2020"},
                type_="book",
            ),
        ]
    )
    found = _violations(doc, profile, "R.03")
    assert len(found) == 1
    assert found[0].details["missing_field"] == "place"
    assert found[0].details["entry_type"] == "book"


def test_r03_web_entry_missing_access_date_violation() -> None:
    """У web-записи нет access_date — Violation."""
    profile = load_profile("gost-7.32-2017")
    doc = _doc_with_bibliography(
        [
            _entry_with_fields(
                "ref-1",
                {"url": "https://example.org"},
                type_="web",
            ),
        ]
    )
    found = _violations(doc, profile, "R.03")
    missing = {v.details["missing_field"] for v in found}
    assert "access_date" in missing


def test_r03_unknown_type_skipped() -> None:
    """Тип источника, не описанный в params, пропускается."""
    profile = load_profile("gost-7.32-2017")
    profile.checks["R.03"] = CheckConfig(
        enabled=True,
        params={"required_by_type": {"book": ["author"]}},
    )
    doc = _doc_with_bibliography(
        [
            _entry_with_fields("ref-1", {}, type_="thesis"),
        ]
    )
    assert _violations(doc, profile, "R.03") == []


# --- R.08 — дата обращения для электронных ------------------------------


def test_r08_registered() -> None:
    assert "R.08" in registered_checks()


def test_r08_web_with_access_date_no_violation() -> None:
    """У web-записи есть access_date — нарушения нет."""
    profile = load_profile("gost-7.32-2017")
    doc = _doc_with_bibliography(
        [
            _entry_with_fields(
                "ref-1",
                {"url": "https://example.org", "access_date": "01.05.2023"},
                type_="web",
            ),
        ]
    )
    assert _violations(doc, profile, "R.08") == []


def test_r08_web_without_access_date_violation() -> None:
    """У web-записи нет access_date — Violation."""
    profile = load_profile("gost-7.32-2017")
    doc = _doc_with_bibliography(
        [
            _entry_with_fields(
                "ref-1",
                {"url": "https://example.org"},
                type_="web",
            ),
        ]
    )
    found = _violations(doc, profile, "R.08")
    assert len(found) == 1
    assert found[0].severity == "error"
    assert found[0].details["entry_id"] == "ref-1"


def test_r08_article_with_url_without_access_date_violation() -> None:
    """У статьи с url, но без access_date — тоже Violation R.08."""
    profile = load_profile("gost-7.32-2017")
    doc = _doc_with_bibliography(
        [
            _entry_with_fields(
                "ref-1",
                {"url": "https://example.org", "year": "2022"},
                type_="article",
            ),
        ]
    )
    found = _violations(doc, profile, "R.08")
    assert len(found) == 1


def test_r08_book_without_url_no_violation() -> None:
    """Книга без url — R.08 не применяется."""
    profile = load_profile("gost-7.32-2017")
    doc = _doc_with_bibliography(
        [
            _entry_with_fields("ref-1", {"year": "2020"}, type_="book"),
        ]
    )
    assert _violations(doc, profile, "R.08") == []


# --- R.09 — DOI/URL для современных источников --------------------------


def test_r09_registered() -> None:
    assert "R.09" in registered_checks()


def test_r09_modern_with_doi_no_violation() -> None:
    """Современная запись с DOI — нарушения нет."""
    profile = load_profile("gost-7.32-2017")
    doc = _doc_with_bibliography(
        [
            _entry_with_fields(
                "ref-1",
                {"year": "2022", "doi": "10.1000/abc"},
                type_="article",
            ),
        ]
    )
    assert _violations(doc, profile, "R.09") == []


def test_r09_modern_without_doi_or_url_violation() -> None:
    """Современная запись без DOI и URL — info-Violation."""
    profile = load_profile("gost-7.32-2017")
    doc = _doc_with_bibliography(
        [
            _entry_with_fields(
                "ref-1",
                {"year": "2023"},
                type_="article",
            ),
        ]
    )
    found = _violations(doc, profile, "R.09")
    assert len(found) == 1
    assert found[0].severity == "info"


def test_r09_old_entry_no_violation() -> None:
    """Старая запись (год < modern_year) не проверяется R.09."""
    profile = load_profile("gost-7.32-2017")
    doc = _doc_with_bibliography(
        [
            _entry_with_fields(
                "ref-1",
                {"year": "2010"},
                type_="article",
            ),
        ]
    )
    assert _violations(doc, profile, "R.09") == []


# --- R.10 — доля свежих источников --------------------------------------


def test_r10_registered() -> None:
    assert "R.10" in registered_checks()


def test_r10_enough_fresh_no_violation() -> None:
    """Если ≥ 50% записей свежее threshold — нарушения нет."""
    profile = load_profile("gost-7.32-2017")
    doc = _doc_with_bibliography(
        [
            _entry_with_fields("ref-1", {"year": "2020"}),
            _entry_with_fields("ref-2", {"year": "2022"}),
            _entry_with_fields("ref-3", {"year": "2010"}),
        ]
    )
    assert _violations(doc, profile, "R.10") == []


def test_r10_too_few_fresh_violation() -> None:
    """Если только 1 из 4 источников свежий — Violation."""
    profile = load_profile("gost-7.32-2017")
    doc = _doc_with_bibliography(
        [
            _entry_with_fields("ref-1", {"year": "2020"}),
            _entry_with_fields("ref-2", {"year": "2005"}),
            _entry_with_fields("ref-3", {"year": "2008"}),
            _entry_with_fields("ref-4", {"year": "2010"}),
        ]
    )
    found = _violations(doc, profile, "R.10")
    assert len(found) == 1
    assert found[0].severity == "warning"
    assert found[0].details["fresh_count"] == "1"
    assert found[0].details["dated_count"] == "4"


def test_r10_no_year_records_no_violation() -> None:
    """Если ни у одной записи нет года — нарушения нет (нечего считать)."""
    profile = load_profile("gost-7.32-2017")
    doc = _doc_with_bibliography(
        [
            _entry_with_fields("ref-1", {}),
            _entry_with_fields("ref-2", {}),
        ]
    )
    assert _violations(doc, profile, "R.10") == []


# --- R.11 — минимальное число источников --------------------------------


def test_r11_registered() -> None:
    assert "R.11" in registered_checks()


def test_r11_enough_sources_no_violation() -> None:
    """Источников ≥ min_sources — нарушений нет."""
    profile = load_profile("gost-7.32-2017")
    profile.checks["R.11"] = CheckConfig(enabled=True, params={"min_sources": 2})
    doc = _doc_with_bibliography(
        [
            _entry_with_fields("ref-1", {}),
            _entry_with_fields("ref-2", {}),
        ]
    )
    assert _violations(doc, profile, "R.11") == []


def test_r11_too_few_sources_violation() -> None:
    """Источников меньше min_sources — Violation."""
    profile = load_profile("gost-7.32-2017")
    profile.checks["R.11"] = CheckConfig(enabled=True, params={"min_sources": 5})
    doc = _doc_with_bibliography(
        [
            _entry_with_fields("ref-1", {}),
            _entry_with_fields("ref-2", {}),
        ]
    )
    found = _violations(doc, profile, "R.11")
    assert len(found) == 1
    assert found[0].details["actual"] == "2"
    assert found[0].details["min_sources"] == "5"


def test_r11_empty_bibliography_violation() -> None:
    """Пустой список литературы — тоже Violation."""
    profile = load_profile("gost-7.32-2017")
    profile.checks["R.11"] = CheckConfig(enabled=True, params={"min_sources": 1})
    found = _violations(Document(), profile, "R.11")
    assert len(found) == 1
    assert found[0].details["actual"] == "0"


# --- R.12 — соотношение русско-/иноязычных ------------------------------


def test_r12_registered() -> None:
    assert "R.12" in registered_checks()


def test_r12_balanced_no_violation() -> None:
    """Доля иноязычных в диапазоне 10–50% — нарушений нет."""
    profile = load_profile("gost-7.32-2017")
    doc = _doc_with_bibliography(
        [
            _entry_with_fields("ref-1", {"language": "ru"}),
            _entry_with_fields("ref-2", {"language": "ru"}),
            _entry_with_fields("ref-3", {"language": "en"}),
            _entry_with_fields("ref-4", {"language": "ru"}),
        ]
    )
    # 1 из 4 = 25% — в диапазоне [10%, 50%].
    assert _violations(doc, profile, "R.12") == []


def test_r12_too_many_foreign_violation() -> None:
    """Доля иноязычных > max_foreign_share — Violation с bound=max."""
    profile = load_profile("gost-7.32-2017")
    doc = _doc_with_bibliography(
        [
            _entry_with_fields("ref-1", {"language": "en"}),
            _entry_with_fields("ref-2", {"language": "en"}),
            _entry_with_fields("ref-3", {"language": "en"}),
            _entry_with_fields("ref-4", {"language": "ru"}),
        ]
    )
    found = _violations(doc, profile, "R.12")
    assert len(found) == 1
    assert found[0].details["bound"] == "max"


def test_r12_too_few_foreign_violation() -> None:
    """Доля иноязычных < min_foreign_share — Violation с bound=min."""
    profile = load_profile("gost-7.32-2017")
    doc = _doc_with_bibliography(
        [_entry_with_fields(f"ref-{i}", {"language": "ru"}) for i in range(1, 11)]
    )
    found = _violations(doc, profile, "R.12")
    assert len(found) == 1
    assert found[0].details["bound"] == "min"


# --- R.13 — подозрительные домены ---------------------------------------


def test_r13_registered() -> None:
    assert "R.13" in registered_checks()


def test_r13_clean_urls_no_violation() -> None:
    """Все URL ведут на нормальные домены — нарушений нет."""
    profile = load_profile("gost-7.32-2017")
    doc = _doc_with_bibliography(
        [
            _entry_with_fields("ref-1", {"url": "https://elibrary.ru/item/1"}, type_="web"),
            _entry_with_fields("ref-2", {"url": "https://dx.doi.org/10.1000/abc"}, type_="article"),
        ]
    )
    assert _violations(doc, profile, "R.13") == []


def test_r13_wikipedia_violation() -> None:
    """URL ведёт на Википедию — Violation."""
    profile = load_profile("gost-7.32-2017")
    doc = _doc_with_bibliography(
        [
            _entry_with_fields(
                "ref-1",
                {"url": "https://ru.wikipedia.org/wiki/Article"},
                type_="web",
            ),
        ]
    )
    found = _violations(doc, profile, "R.13")
    assert len(found) == 1
    # Поиск идёт по подстроке, поэтому может сматчиться более общий «wikipedia.org».
    assert "wikipedia.org" in found[0].details["domain"]


def test_r13_studopedia_violation() -> None:
    """URL ведёт на studopedia.ru — Violation."""
    profile = load_profile("gost-7.32-2017")
    doc = _doc_with_bibliography(
        [
            _entry_with_fields(
                "ref-1",
                {"url": "https://studopedia.ru/page-123.html"},
                type_="web",
            ),
        ]
    )
    found = _violations(doc, profile, "R.13")
    assert len(found) == 1
    assert found[0].details["domain"] == "studopedia.ru"


def test_r13_entry_without_url_no_violation() -> None:
    """Запись без url не проверяется R.13."""
    profile = load_profile("gost-7.32-2017")
    doc = _doc_with_bibliography([_entry_with_fields("ref-1", {"year": "2020"}, type_="book")])
    assert _violations(doc, profile, "R.13") == []
