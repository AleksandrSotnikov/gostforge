"""Тесты движка автоисправлений и фиксеров T.08/T.09/T.10/T.11/T.12/T.13/H.03/H.08."""

from __future__ import annotations

from pathlib import Path

from gostforge.exporter import export_docx
from gostforge.fixer import FixApplied, fix, registered_fixers
from gostforge.model import (
    Document,
    LogicalSection,
    PageGeometry,
    PageNumberingConfig,
    PageSection,
    Paragraph,
    TextRun,
)
from gostforge.parser import parse_docx
from gostforge.profile import load_profile
from gostforge.validator import validate


def _doc_with_paragraph(paragraph: Paragraph) -> Document:
    """Утилита: документ с одной страничной секцией и одним абзацем."""
    doc = Document()
    doc.page_sections.append(
        PageSection(
            id="main",
            name="Основная часть",
            type="main",
            page=PageGeometry(),
            content=[paragraph],
        )
    )
    return doc


def _doc_with_section(section: LogicalSection) -> Document:
    """Утилита: документ с одной страничной секцией и одним LogicalSection."""
    doc = Document()
    doc.page_sections.append(
        PageSection(
            id="main",
            name="Основная часть",
            type="main",
            page=PageGeometry(),
            content=[section],
        )
    )
    return doc


# --- регистрация фиксеров ----------------------------------------------------


def test_fix_registry_has_codes() -> None:
    """Все ожидаемые коды зарегистрированы."""
    codes = set(registered_fixers())
    assert {"T.08", "T.09", "T.10", "T.11", "T.12", "T.13", "H.03", "H.08"}.issubset(codes)


# --- T.08: двойные пробелы --------------------------------------------------


def test_t08_collapses_double_spaces() -> None:
    """Множественные пробелы внутри run-а схлопываются в один."""
    paragraph = Paragraph(
        id="p1",
        content=[TextRun(text="hello  world")],
        style_name="Normal",
    )
    doc = _doc_with_paragraph(paragraph)
    profile = load_profile("gost-7.32-2017")
    applied = fix(doc, profile, codes=["T.08"])
    assert len(applied) == 1
    assert applied[0].fixer_code == "T.08"
    assert isinstance(applied[0], FixApplied)
    text_runs = [el for el in paragraph.content if isinstance(el, TextRun)]
    assert text_runs[0].text == "hello world"


def test_t08_no_change_when_clean() -> None:
    """Если двойных пробелов нет — FixApplied пустой."""
    paragraph = Paragraph(
        id="p1",
        content=[TextRun(text="hello world")],
        style_name="Normal",
    )
    doc = _doc_with_paragraph(paragraph)
    profile = load_profile("gost-7.32-2017")
    applied = fix(doc, profile, codes=["T.08"])
    assert applied == []


# --- T.09: хвостовые пробелы -------------------------------------------------


def test_t09_strips_trailing_whitespace() -> None:
    """Хвостовой пробел в последнем run-е убирается."""
    paragraph = Paragraph(
        id="p1",
        content=[TextRun(text="text   ")],
        style_name="Normal",
    )
    doc = _doc_with_paragraph(paragraph)
    profile = load_profile("gost-7.32-2017")
    applied = fix(doc, profile, codes=["T.09"])
    assert len(applied) == 1
    assert applied[0].fixer_code == "T.09"
    text_runs = [el for el in paragraph.content if isinstance(el, TextRun)]
    assert text_runs[0].text == "text"


def test_t09_trailing_in_middle_run_not_touched() -> None:
    """Пробел в конце run-а, который не последний в параграфе, сохраняется."""
    paragraph = Paragraph(
        id="p1",
        content=[TextRun(text="a "), TextRun(text="b")],
        style_name="Normal",
    )
    doc = _doc_with_paragraph(paragraph)
    profile = load_profile("gost-7.32-2017")
    applied = fix(doc, profile, codes=["T.09"])
    assert applied == []
    text_runs = [el for el in paragraph.content if isinstance(el, TextRun)]
    assert text_runs[0].text == "a "
    assert text_runs[1].text == "b"


# --- T.10: прямые кавычки → «ёлочки» ----------------------------------------


def test_t10_replaces_paired_quotes_single_run() -> None:
    """Пара прямых кавычек в одном run-е заменяется на «ёлочки»."""
    paragraph = Paragraph(
        id="p1",
        content=[TextRun(text='"привет"')],
        style_name="Normal",
    )
    doc = _doc_with_paragraph(paragraph)
    profile = load_profile("gost-7.32-2017")
    applied = fix(doc, profile, codes=["T.10"])
    assert len(applied) == 1
    assert applied[0].fixer_code == "T.10"
    text_runs = [el for el in paragraph.content if isinstance(el, TextRun)]
    assert text_runs[0].text == "«привет»"


def test_t10_skips_unpaired_quote() -> None:
    """Нечётное число кавычек — фиксер не трогает (нет уверенной пары)."""
    paragraph = Paragraph(
        id="p1",
        content=[TextRun(text='hello "world')],
        style_name="Normal",
    )
    doc = _doc_with_paragraph(paragraph)
    profile = load_profile("gost-7.32-2017")
    applied = fix(doc, profile, codes=["T.10"])
    assert applied == []
    text_runs = [el for el in paragraph.content if isinstance(el, TextRun)]
    assert text_runs[0].text == 'hello "world'


def test_t10_skips_multi_run_paragraph() -> None:
    """Параграф из нескольких непустых TextRun-ов не трогаем (форматирование)."""
    paragraph = Paragraph(
        id="p1",
        content=[TextRun(text='"привет'), TextRun(text=' мир"')],
        style_name="Normal",
    )
    doc = _doc_with_paragraph(paragraph)
    profile = load_profile("gost-7.32-2017")
    applied = fix(doc, profile, codes=["T.10"])
    assert applied == []
    text_runs = [el for el in paragraph.content if isinstance(el, TextRun)]
    assert text_runs[0].text == '"привет'
    assert text_runs[1].text == ' мир"'


# --- T.11: дефис → длинное тире ---------------------------------------------


def test_t11_hyphen_to_em_dash() -> None:
    """« - » → « — » в одном TextRun-е."""
    paragraph = Paragraph(
        id="p1",
        content=[TextRun(text="a - b")],
        style_name="Normal",
    )
    doc = _doc_with_paragraph(paragraph)
    profile = load_profile("gost-7.32-2017")
    applied = fix(doc, profile, codes=["T.11"])
    assert len(applied) == 1
    text_runs = [el for el in paragraph.content if isinstance(el, TextRun)]
    assert text_runs[0].text == "a — b"


def test_t11_in_word_hyphen_kept() -> None:
    """Дефис без пробелов вокруг (внутри слова) не трогаем."""
    paragraph = Paragraph(
        id="p1",
        content=[TextRun(text="веб-сервис")],
        style_name="Normal",
    )
    doc = _doc_with_paragraph(paragraph)
    profile = load_profile("gost-7.32-2017")
    applied = fix(doc, profile, codes=["T.11"])
    assert applied == []
    text_runs = [el for el in paragraph.content if isinstance(el, TextRun)]
    assert text_runs[0].text == "веб-сервис"


# --- T.12: NBSP между числом и единицей -------------------------------------


def test_t12_registered() -> None:
    """Фиксер T.12 присутствует в реестре."""
    assert "T.12" in registered_fixers()


def test_t12_inserts_nbsp_between_number_and_unit() -> None:
    """«5 кг» → «5<NBSP>кг»."""
    paragraph = Paragraph(
        id="p1",
        content=[TextRun(text="вес 5 кг и длина 10 м")],
        style_name="Normal",
    )
    doc = _doc_with_paragraph(paragraph)
    profile = load_profile("gost-7.32-2017")
    applied = fix(doc, profile, codes=["T.12"])
    assert len(applied) == 1
    assert applied[0].fixer_code == "T.12"
    assert isinstance(applied[0], FixApplied)
    text_runs = [el for el in paragraph.content if isinstance(el, TextRun)]
    # Между числом и единицей должен стоять U+00A0, остальные пробелы — обычные.
    assert text_runs[0].text == "вес 5 кг и длина 10 м"


def test_t12_no_change_when_already_nbsp() -> None:
    """Если уже стоит NBSP — фиксер ничего не делает."""
    paragraph = Paragraph(
        id="p1",
        content=[TextRun(text="вес 5 кг")],
        style_name="Normal",
    )
    doc = _doc_with_paragraph(paragraph)
    profile = load_profile("gost-7.32-2017")
    applied = fix(doc, profile, codes=["T.12"])
    assert applied == []
    text_runs = [el for el in paragraph.content if isinstance(el, TextRun)]
    assert text_runs[0].text == "вес 5 кг"


def test_t12_no_change_when_no_units() -> None:
    """В тексте без единиц измерения — никаких правок."""
    paragraph = Paragraph(
        id="p1",
        content=[TextRun(text="просто текст без чисел")],
        style_name="Normal",
    )
    doc = _doc_with_paragraph(paragraph)
    profile = load_profile("gost-7.32-2017")
    applied = fix(doc, profile, codes=["T.12"])
    assert applied == []


# --- T.13: NBSP между инициалами и фамилией ---------------------------------


def test_t13_registered() -> None:
    """Фиксер T.13 присутствует в реестре."""
    assert "T.13" in registered_fixers()


def test_t13_inserts_nbsp_between_initials_and_surname() -> None:
    """«И. И. Иванов» → «И.<NBSP>И.<NBSP>Иванов»."""
    paragraph = Paragraph(
        id="p1",
        content=[TextRun(text="автор: И. И. Иванов и А. Б. Петров")],
        style_name="Normal",
    )
    doc = _doc_with_paragraph(paragraph)
    profile = load_profile("gost-7.32-2017")
    applied = fix(doc, profile, codes=["T.13"])
    assert len(applied) == 1
    assert applied[0].fixer_code == "T.13"
    assert isinstance(applied[0], FixApplied)
    text_runs = [el for el in paragraph.content if isinstance(el, TextRun)]
    assert text_runs[0].text == "автор: И. И. Иванов и А. Б. Петров"


def test_t13_no_change_when_already_nbsp() -> None:
    """Если NBSP уже стоит — фиксер ничего не делает."""
    paragraph = Paragraph(
        id="p1",
        content=[TextRun(text="И. И. Иванов")],
        style_name="Normal",
    )
    doc = _doc_with_paragraph(paragraph)
    profile = load_profile("gost-7.32-2017")
    applied = fix(doc, profile, codes=["T.13"])
    assert applied == []
    text_runs = [el for el in paragraph.content if isinstance(el, TextRun)]
    assert text_runs[0].text == "И. И. Иванов"


def test_t13_no_change_without_pattern() -> None:
    """В тексте без шаблона «И. И. Фамилия» — никаких правок."""
    paragraph = Paragraph(
        id="p1",
        content=[TextRun(text="просто текст без инициалов")],
        style_name="Normal",
    )
    doc = _doc_with_paragraph(paragraph)
    profile = load_profile("gost-7.32-2017")
    applied = fix(doc, profile, codes=["T.13"])
    assert applied == []


# --- H.03: точка после номера заголовка --------------------------------------


def test_h03_removes_dot_after_number() -> None:
    """«1. Введение» → «1 Введение»."""
    section = LogicalSection(
        id="s1",
        heading=[TextRun(text="1. Введение")],
        level=1,
    )
    doc = _doc_with_section(section)
    profile = load_profile("gost-7.32-2017")
    applied = fix(doc, profile, codes=["H.03"])
    assert len(applied) == 1
    assert applied[0].fixer_code == "H.03"
    runs = [el for el in section.heading if isinstance(el, TextRun)]
    assert runs[0].text == "1 Введение"


# --- H.08: точка в конце заголовка -------------------------------------------


def test_h08_removes_trailing_dot() -> None:
    """«Введение.» → «Введение»."""
    section = LogicalSection(
        id="s1",
        heading=[TextRun(text="Введение.")],
        level=1,
    )
    doc = _doc_with_section(section)
    profile = load_profile("gost-7.32-2017")
    applied = fix(doc, profile, codes=["H.08"])
    assert len(applied) == 1
    runs = [el for el in section.heading if isinstance(el, TextRun)]
    assert runs[0].text == "Введение"


def test_h08_preserves_question_mark() -> None:
    """Знак вопроса в конце заголовка — допустим, не трогаем."""
    section = LogicalSection(
        id="s1",
        heading=[TextRun(text="Что такое?")],
        level=1,
    )
    doc = _doc_with_section(section)
    profile = load_profile("gost-7.32-2017")
    applied = fix(doc, profile, codes=["H.08"])
    assert applied == []
    runs = [el for el in section.heading if isinstance(el, TextRun)]
    assert runs[0].text == "Что такое?"


# --- H.01/H.02: формат заголовков (шрифт/кегль/жирность/цвет) ----------------


def test_h01_h02_fix_registered() -> None:
    """Фиксеры формата заголовков зарегистрированы."""
    codes = set(registered_fixers())
    assert {"H.01", "H.02"}.issubset(codes)


def test_h01_fixes_blue_cambria_heading() -> None:
    """«Синий Cambria» заголовок 1 уровня приводится к профилю."""
    section = LogicalSection(
        id="s1",
        heading=[
            TextRun(
                text="ВВЕДЕНИЕ",
                font="Cambria",
                size_pt=16.0,
                bold=False,
                color_hex="365F91",
            )
        ],
        level=1,
    )
    doc = _doc_with_section(section)
    profile = load_profile("gost-7.32-2017")

    pre = [v for v in validate(doc, profile) if v.check_code == "H.01"]
    assert pre, "тест должен начинаться с нарушениями H.01"

    applied = fix(doc, profile, codes=["H.01"])
    assert len(applied) == 1
    assert applied[0].fixer_code == "H.01"

    runs = [el for el in section.heading if isinstance(el, TextRun)]
    run = runs[0]
    assert run.font == "Times New Roman"
    assert run.size_pt == 14.0
    assert run.bold is True
    assert run.color_hex is None

    post = [v for v in validate(doc, profile) if v.check_code == "H.01"]
    assert post == []


def test_h01_leaves_inherited_runs_untouched() -> None:
    """Run с наследуемыми (None) атрибутами фиксер не трогает."""
    section = LogicalSection(
        id="s1",
        heading=[TextRun(text="ГЛАВА 1", font=None, size_pt=None, bold=None, color_hex=None)],
        level=1,
    )
    doc = _doc_with_section(section)
    profile = load_profile("gost-7.32-2017")

    applied = fix(doc, profile, codes=["H.01"])
    assert applied == []

    runs = [el for el in section.heading if isinstance(el, TextRun)]
    run = runs[0]
    assert run.font is None
    assert run.size_pt is None
    assert run.bold is None
    assert run.color_hex is None


def test_h01_does_not_change_uppercase() -> None:
    """Регистр заголовка фиксер не меняет — это правка текста, не формата."""
    section = LogicalSection(
        id="s1",
        heading=[TextRun(text="введение", font="Times New Roman", size_pt=14.0, bold=True)],
        level=1,
    )
    doc = _doc_with_section(section)
    profile = load_profile("gost-7.32-2017")

    fix(doc, profile, codes=["H.01"])
    runs = [el for el in section.heading if isinstance(el, TextRun)]
    assert runs[0].text == "введение"


def test_h02_fixes_heading_level_2_only() -> None:
    """H.02 правит заголовки 2 уровня, не трогая 1 уровень."""
    h1 = LogicalSection(
        id="s1",
        heading=[TextRun(text="ГЛАВА", font="Cambria", size_pt=16.0, bold=False)],
        level=1,
    )
    h2 = LogicalSection(
        id="s2",
        heading=[TextRun(text="Подраздел", font="Cambria", size_pt=16.0, bold=False)],
        level=2,
    )
    h1.children.append(h2)
    doc = _doc_with_section(h1)
    profile = load_profile("gost-7.32-2017")

    applied = fix(doc, profile, codes=["H.02"])
    assert len(applied) == 1
    assert applied[0].fixer_code == "H.02"

    # Заголовок 1 уровня не тронут фиксером H.02.
    runs1 = [el for el in h1.heading if isinstance(el, TextRun)]
    assert runs1[0].font == "Cambria"
    # Заголовок 2 уровня приведён к профилю.
    runs2 = [el for el in h2.heading if isinstance(el, TextRun)]
    assert runs2[0].font == "Times New Roman"


# --- F.01/F.02/F.03: геометрия страницы --------------------------------------


def _doc_with_page(page: PageGeometry, *, section_type: str = "main") -> Document:
    """Документ с одной PageSection заданной геометрии."""
    doc = Document()
    doc.page_sections.append(
        PageSection(
            id="main",
            name="Основная часть",
            type=section_type,
            page=page,
            content=[],
        )
    )
    return doc


def test_f01_f02_f03_fix_registered() -> None:
    """Фиксеры геометрии страницы зарегистрированы."""
    codes = set(registered_fixers())
    assert {"F.01", "F.02", "F.03"}.issubset(codes)


def test_f01_fixes_wrong_margins() -> None:
    """Поля 25/25/25/25 приводятся к профилю ГОСТ (20/15/20/30)."""
    doc = _doc_with_page(
        PageGeometry(margins_mm={"top": 25, "right": 25, "bottom": 25, "left": 25})
    )
    profile = load_profile("gost-7.32-2017")

    pre = [v for v in validate(doc, profile) if v.check_code == "F.01"]
    assert pre, "тест должен начинаться с нарушениями F.01"

    applied = fix(doc, profile, codes=["F.01"])
    assert len(applied) == 1
    assert applied[0].fixer_code == "F.01"

    margins = doc.page_sections[0].page.margins_mm
    assert margins == profile.styles.page.margins_mm
    post = [v for v in validate(doc, profile) if v.check_code == "F.01"]
    assert post == []


def test_f01_no_change_when_within_tolerance() -> None:
    """Отклонение ≤ 0.5 мм не считается нарушением — фиксер молчит."""
    base = dict(load_profile("gost-7.32-2017").styles.page.margins_mm)
    base["top"] = base["top"] + 0.3  # в пределах допуска
    doc = _doc_with_page(PageGeometry(margins_mm=base))
    profile = load_profile("gost-7.32-2017")
    assert fix(doc, profile, codes=["F.01"]) == []


def test_f02_fixes_paper_size() -> None:
    """A5 → A4."""
    doc = _doc_with_page(PageGeometry(paper="A5"))
    profile = load_profile("gost-7.32-2017")
    applied = fix(doc, profile, codes=["F.02"])
    assert len(applied) == 1
    assert doc.page_sections[0].page.paper == "A4"


def test_f03_fixes_orientation() -> None:
    """landscape → portrait для обычной секции."""
    doc = _doc_with_page(PageGeometry(orientation="landscape"))
    profile = load_profile("gost-7.32-2017")
    applied = fix(doc, profile, codes=["F.03"])
    assert len(applied) == 1
    assert doc.page_sections[0].page.orientation == "portrait"


def test_f03_skips_appendix() -> None:
    """Приложение может быть альбомным — фиксер F.03 его не трогает."""
    doc = _doc_with_page(PageGeometry(orientation="landscape"), section_type="appendix")
    profile = load_profile("gost-7.32-2017")
    applied = fix(doc, profile, codes=["F.03"])
    assert applied == []
    assert doc.page_sections[0].page.orientation == "landscape"


# --- F.05: формат нумерации страниц ------------------------------------------


def test_f05_fixer_registered() -> None:
    """Фиксер F.05 присутствует в реестре."""
    assert "F.05" in registered_fixers()


def test_f05_fixes_roman_to_arabic() -> None:
    """Римская нумерация видимой секции → арабская (профиль ГОСТ)."""
    doc = _doc_with_page(PageGeometry())
    doc.page_sections[0].page_numbering = PageNumberingConfig(visible=True, format="roman")
    profile = load_profile("gost-7.32-2017")

    pre = [v for v in validate(doc, profile) if v.check_code == "F.05"]
    assert pre, "тест должен начинаться с нарушением F.05"

    applied = fix(doc, profile, codes=["F.05"])
    assert len(applied) == 1
    assert applied[0].fixer_code == "F.05"
    assert doc.page_sections[0].page_numbering.format == "arabic"
    post = [v for v in validate(doc, profile) if v.check_code == "F.05"]
    assert post == []


def test_f05_no_change_when_already_arabic() -> None:
    """Арабская нумерация — фиксер молчит."""
    doc = _doc_with_page(PageGeometry())
    doc.page_sections[0].page_numbering = PageNumberingConfig(visible=True, format="arabic")
    profile = load_profile("gost-7.32-2017")
    assert fix(doc, profile, codes=["F.05"]) == []


def test_f05_skips_invisible_numbering() -> None:
    """Если нумерация не отображается — формат не важен, фиксер не трогает."""
    doc = _doc_with_page(PageGeometry())
    doc.page_sections[0].page_numbering = PageNumberingConfig(visible=False, format="roman")
    profile = load_profile("gost-7.32-2017")
    applied = fix(doc, profile, codes=["F.05"])
    assert applied == []
    assert doc.page_sections[0].page_numbering.format == "roman"


# --- K.02 / K.03 / K.04: нумерация и колонтитулы секций ----------------------


def _doc_with_sections(*sections: PageSection) -> Document:
    """Документ из произвольного набора PageSection-ов."""
    doc = Document()
    doc.page_sections.extend(sections)
    return doc


def test_k_fixers_registered() -> None:
    """Фиксеры K.02/K.03/K.04/K.06 присутствуют в реестре."""
    assert {"K.02", "K.03", "K.04", "K.06"}.issubset(registered_fixers())


def test_k02_disables_title_page_number() -> None:
    """K.02: на титульном листе номер страницы отключается."""
    title = PageSection(
        id="title",
        name="Титульный лист",
        type="title",
        page=PageGeometry(),
        page_numbering=PageNumberingConfig(visible=True),
        content=[],
    )
    doc = _doc_with_sections(title)
    profile = load_profile("gost-7.32-2017")

    pre = [v for v in validate(doc, profile) if v.check_code == "K.02"]
    assert pre, "тест должен начинаться с нарушением K.02"

    applied = fix(doc, profile, codes=["K.02"])
    assert len(applied) == 1
    assert applied[0].fixer_code == "K.02"
    assert doc.page_sections[0].page_numbering.visible is False
    assert [v for v in validate(doc, profile) if v.check_code == "K.02"] == []


def test_k02_skips_non_title() -> None:
    """K.02 не трогает нумерацию обычных секций."""
    main = PageSection(
        id="main",
        name="Основная часть",
        type="main",
        page=PageGeometry(),
        page_numbering=PageNumberingConfig(visible=True),
        content=[],
    )
    doc = _doc_with_sections(main)
    profile = load_profile("gost-7.32-2017")
    assert fix(doc, profile, codes=["K.02"]) == []
    assert doc.page_sections[0].page_numbering.visible is True


def test_k03_sets_start_at_and_value() -> None:
    """K.03: основная часть получает start_mode=start_at и start_value=3."""
    title = PageSection(
        id="title",
        name="Титул",
        type="title",
        page=PageGeometry(),
        page_numbering=PageNumberingConfig(visible=False),
        content=[],
    )
    main = PageSection(
        id="main",
        name="Основная часть",
        type="main",
        page=PageGeometry(),
        page_numbering=PageNumberingConfig(visible=True, start_mode="continue"),
        content=[],
    )
    doc = _doc_with_sections(title, main)
    profile = load_profile("gost-7.32-2017")

    pre = [v for v in validate(doc, profile) if v.check_code == "K.03"]
    assert pre, "тест должен начинаться с нарушением K.03"

    applied = fix(doc, profile, codes=["K.03"])
    assert len(applied) == 1
    assert main.page_numbering.start_mode == "start_at"
    assert main.page_numbering.start_value == 3
    assert [v for v in validate(doc, profile) if v.check_code == "K.03"] == []


def test_k03_no_change_when_already_correct() -> None:
    """K.03 молчит, если стартовая страница уже задана верно."""
    main = PageSection(
        id="main",
        name="Основная часть",
        type="main",
        page=PageGeometry(),
        page_numbering=PageNumberingConfig(visible=True, start_mode="start_at", start_value=3),
        content=[],
    )
    doc = _doc_with_sections(main)
    profile = load_profile("gost-7.32-2017")
    assert fix(doc, profile, codes=["K.03"]) == []


def test_k04_converts_restart_to_continue() -> None:
    """K.04: сброс нумерации во второй секции → continue."""
    first = PageSection(
        id="main",
        name="Основная часть",
        type="main",
        page=PageGeometry(),
        page_numbering=PageNumberingConfig(start_mode="start_at", start_value=3),
        content=[],
    )
    second = PageSection(
        id="ch2",
        name="Глава 2",
        type="main",
        page=PageGeometry(),
        page_numbering=PageNumberingConfig(start_mode="restart"),
        content=[],
    )
    doc = _doc_with_sections(first, second)
    profile = load_profile("gost-7.32-2017")

    pre = [v for v in validate(doc, profile) if v.check_code == "K.04"]
    assert pre, "тест должен начинаться с нарушением K.04"

    applied = fix(doc, profile, codes=["K.04"])
    assert len(applied) == 1
    assert second.page_numbering.start_mode == "continue"
    assert [v for v in validate(doc, profile) if v.check_code == "K.04"] == []


def test_k04_skips_first_section() -> None:
    """K.04 не трогает первую секцию — она задаёт начало нумерации."""
    first = PageSection(
        id="main",
        name="Основная часть",
        type="main",
        page=PageGeometry(),
        page_numbering=PageNumberingConfig(start_mode="restart"),
        content=[],
    )
    doc = _doc_with_sections(first)
    profile = load_profile("gost-7.32-2017")
    assert fix(doc, profile, codes=["K.04"]) == []
    assert first.page_numbering.start_mode == "restart"


def test_k06_unlinks_header_from_previous() -> None:
    """K.06: вторая секция со связанным колонтитулом отвязывается."""
    first = PageSection(id="title", name="Титул", type="title", page=PageGeometry(), content=[])
    second = PageSection(
        id="main",
        name="Основная часть",
        type="main",
        page=PageGeometry(),
        link_to_previous=True,
        content=[],
    )
    doc = _doc_with_sections(first, second)
    profile = load_profile("gost-7.32-2017")

    pre = [v for v in validate(doc, profile) if v.check_code == "K.06"]
    assert pre, "тест должен начинаться с нарушением K.06"

    applied = fix(doc, profile, codes=["K.06"])
    assert len(applied) == 1
    assert applied[0].fixer_code == "K.06"
    assert second.link_to_previous is False
    assert [v for v in validate(doc, profile) if v.check_code == "K.06"] == []


def test_k06_skips_first_section() -> None:
    """K.06 не трогает первую секцию — у неё нет «предыдущей»."""
    first = PageSection(
        id="title",
        name="Титул",
        type="title",
        page=PageGeometry(),
        link_to_previous=True,
        content=[],
    )
    doc = _doc_with_sections(first)
    profile = load_profile("gost-7.32-2017")
    assert fix(doc, profile, codes=["K.06"]) == []
    assert first.link_to_previous is True


# --- end-to-end: export → parse → fix → export → parse → validate -----------


def test_fix_round_trip_through_export(tmp_path: Path) -> None:
    """После fix + export + parse в документе нет T.08-нарушений."""
    paragraph = Paragraph(
        id="p1",
        content=[TextRun(text="hello  world", font="Times New Roman", size_pt=14)],
        style_name="Normal",
    )
    doc = _doc_with_paragraph(paragraph)
    profile = load_profile("gost-7.32-2017")

    # До фикса — есть нарушение T.08.
    pre = [v for v in validate(doc, profile) if v.check_code == "T.08"]
    assert pre, "тест должен начинаться с нарушением T.08"

    fix(doc, profile, codes=["T.08"])

    out = tmp_path / "fixed.docx"
    export_docx(doc, profile, out)
    reparsed = parse_docx(out)
    post = [v for v in validate(reparsed, profile) if v.check_code == "T.08"]
    assert post == []


# --- фильтрация по кодам -----------------------------------------------------


def test_fix_with_codes_filter() -> None:
    """`codes=["T.08"]` применяет только T.08, остальные пропускает."""
    # В параграфе и двойной пробел (T.08), и парные кавычки (T.10).
    paragraph = Paragraph(
        id="p1",
        content=[TextRun(text='"a  b"')],
        style_name="Normal",
    )
    doc = _doc_with_paragraph(paragraph)
    profile = load_profile("gost-7.32-2017")

    applied = fix(doc, profile, codes=["T.08"])
    codes = {a.fixer_code for a in applied}
    assert codes == {"T.08"}
    text_runs = [el for el in paragraph.content if isinstance(el, TextRun)]
    # T.08 сработал: двойной пробел схлопнулся; T.10 не запускался — кавычки на месте.
    assert text_runs[0].text == '"a b"'


# --- T.07 fix_consecutive_empty_paragraphs ---------------------------------


def test_t07_fix_registered() -> None:
    """T.07 фиксер зарегистрирован в реестре."""
    from gostforge.fixer.engine import registered_fixers

    assert "T.07" in registered_fixers()


def test_t07_removes_extra_empty_paragraphs() -> None:
    """3 пустых абзаца подряд → останется только 1 (max_consecutive_empty=1)."""
    from gostforge.fixer import fix as run_fix
    from gostforge.model import Document, PageSection, Paragraph, TextRun
    from gostforge.profile import load_profile

    doc = Document()
    doc.page_sections.append(
        PageSection(
            id="main",
            name="m",
            type="main",
            content=[
                Paragraph(id="p1", content=[TextRun(text="Раздел 1")]),
                Paragraph(id="p2", content=[]),
                Paragraph(id="p3", content=[TextRun(text="")]),
                Paragraph(id="p4", content=[TextRun(text="   ")]),
                Paragraph(id="p5", content=[TextRun(text="Раздел 2")]),
            ],
        )
    )
    profile = load_profile("gost-7.32-2017")
    fixes = run_fix(doc, profile, codes=["T.07"])
    assert len(fixes) == 2  # удалены 2 лишних пустых
    assert all(f.fixer_code == "T.07" for f in fixes)
    # В content остался 1 пустой + 2 непустых = 3 параграфа
    assert len(doc.page_sections[0].content) == 3


def test_t07_keeps_single_empty_paragraph() -> None:
    """1 пустой абзац подряд при max=1 — не удаляется."""
    from gostforge.fixer import fix as run_fix
    from gostforge.model import Document, PageSection, Paragraph, TextRun
    from gostforge.profile import load_profile

    doc = Document()
    doc.page_sections.append(
        PageSection(
            id="main",
            name="m",
            type="main",
            content=[
                Paragraph(id="p1", content=[TextRun(text="A")]),
                Paragraph(id="p2", content=[]),
                Paragraph(id="p3", content=[TextRun(text="B")]),
            ],
        )
    )
    profile = load_profile("gost-7.32-2017")
    fixes = run_fix(doc, profile, codes=["T.07"])
    assert fixes == []


# --- T.06 fix_disable_auto_hyphenation -------------------------------------


def test_t06_fix_registered() -> None:
    from gostforge.fixer.engine import registered_fixers

    assert "T.06" in registered_fixers()


def test_t06_disables_auto_hyphenation() -> None:
    """auto_hyphenation=True → False после фиксера."""
    from gostforge.fixer import fix as run_fix
    from gostforge.model import Document
    from gostforge.profile import load_profile

    doc = Document(auto_hyphenation=True)
    profile = load_profile("gost-7.32-2017")
    applied = run_fix(doc, profile, codes=["T.06"])
    assert len(applied) == 1
    assert applied[0].fixer_code == "T.06"
    assert doc.auto_hyphenation is False


def test_t06_noop_when_already_disabled() -> None:
    from gostforge.fixer import fix as run_fix
    from gostforge.model import Document
    from gostforge.profile import load_profile

    doc = Document(auto_hyphenation=False)
    profile = load_profile("gost-7.32-2017")
    assert run_fix(doc, profile, codes=["T.06"]) == []


def test_t06_noop_when_unset() -> None:
    """None означает «не определено», фиксер не трогает."""
    from gostforge.fixer import fix as run_fix
    from gostforge.model import Document
    from gostforge.profile import load_profile

    doc = Document(auto_hyphenation=None)
    profile = load_profile("gost-7.32-2017")
    assert run_fix(doc, profile, codes=["T.06"]) == []


def test_export_writes_auto_hyphenation_setting(tmp_path: Path) -> None:
    """Round-trip: auto_hyphenation=True сохраняется через экспорт."""
    from gostforge.exporter import export_docx
    from gostforge.model import Document, PageSection
    from gostforge.parser import parse_docx
    from gostforge.profile import load_profile

    doc = Document(auto_hyphenation=True)
    doc.page_sections.append(PageSection(id="main", name="m", type="main"))
    profile = load_profile("gost-7.32-2017")
    out = tmp_path / "out.docx"
    export_docx(doc, profile, out)
    reparsed = parse_docx(out)
    assert reparsed.auto_hyphenation is True


# --- T.03 / T.04 / T.05 — выравнивание/интервал/отступ -----------------------


def test_t03_fix_registered() -> None:
    from gostforge.fixer.engine import registered_fixers

    assert "T.03" in registered_fixers()


def test_t03_corrects_line_spacing_to_profile_default() -> None:
    from gostforge.fixer import fix as run_fix
    from gostforge.model import Document, PageSection, Paragraph, TextRun
    from gostforge.profile import load_profile

    p = Paragraph(id="p1", content=[TextRun(text="Текст")], style_name="Normal", line_spacing=1.0)
    doc = Document()
    doc.page_sections.append(PageSection(id="main", name="m", type="main", content=[p]))
    profile = load_profile("gost-7.32-2017")
    applied = run_fix(doc, profile, codes=["T.03"])
    assert len(applied) == 1
    assert p.line_spacing == 1.5


def test_t03_skips_heading() -> None:
    from gostforge.fixer import fix as run_fix
    from gostforge.model import Document, PageSection, Paragraph, TextRun
    from gostforge.profile import load_profile

    p = Paragraph(
        id="p1", content=[TextRun(text="Заголовок")], style_name="Heading 1", line_spacing=1.0
    )
    doc = Document()
    doc.page_sections.append(PageSection(id="main", name="m", type="main", content=[p]))
    profile = load_profile("gost-7.32-2017")
    assert run_fix(doc, profile, codes=["T.03"]) == []


def test_t04_corrects_first_line_indent() -> None:
    from gostforge.fixer import fix as run_fix
    from gostforge.model import Document, PageSection, Paragraph, TextRun
    from gostforge.profile import load_profile

    p = Paragraph(
        id="p1", content=[TextRun(text="x")], style_name="Normal", first_line_indent_cm=0.0
    )
    doc = Document()
    doc.page_sections.append(PageSection(id="main", name="m", type="main", content=[p]))
    profile = load_profile("gost-7.32-2017")
    applied = run_fix(doc, profile, codes=["T.04"])
    assert len(applied) == 1
    assert p.first_line_indent_cm == 1.25


def test_t05_corrects_alignment_to_justify() -> None:
    from gostforge.fixer import fix as run_fix
    from gostforge.model import Document, PageSection, Paragraph, TextRun
    from gostforge.profile import load_profile

    p = Paragraph(id="p1", content=[TextRun(text="x")], style_name="Normal", alignment="left")
    doc = Document()
    doc.page_sections.append(PageSection(id="main", name="m", type="main", content=[p]))
    profile = load_profile("gost-7.32-2017")
    applied = run_fix(doc, profile, codes=["T.05"])
    assert len(applied) == 1
    assert p.alignment == "justify"


def test_t04_noop_when_already_correct() -> None:
    from gostforge.fixer import fix as run_fix
    from gostforge.model import Document, PageSection, Paragraph, TextRun
    from gostforge.profile import load_profile

    p = Paragraph(
        id="p1", content=[TextRun(text="x")], style_name="Normal", first_line_indent_cm=1.25
    )
    doc = Document()
    doc.page_sections.append(PageSection(id="main", name="m", type="main", content=[p]))
    profile = load_profile("gost-7.32-2017")
    assert run_fix(doc, profile, codes=["T.04"]) == []


# --- U.01: NBSP между числом и единицей СИ ----------------------------------


def test_u01_fixer_registered() -> None:
    """Фиксер U.01 присутствует в реестре."""
    assert "U.01" in registered_fixers()


def test_u01_inserts_nbsp_between_number_and_si_unit() -> None:
    """U.01-фиксер: обычный пробел между числом и единицей СИ → NBSP."""
    paragraph = Paragraph(
        id="p1",
        content=[TextRun(text="масса 10 кг")],
        style_name="Normal",
    )
    doc = _doc_with_paragraph(paragraph)
    profile = load_profile("gost-7.32-2017")
    applied = fix(doc, profile, codes=["U.01"])
    assert len(applied) == 1
    assert applied[0].fixer_code == "U.01"
    assert isinstance(applied[0], FixApplied)
    runs = [el for el in paragraph.content if isinstance(el, TextRun)]
    assert "10 кг" in runs[0].text
    assert "10 кг" not in runs[0].text  # обычного пробела больше нет


def test_u01_fixer_no_change_when_already_nbsp() -> None:
    """Если уже стоит NBSP — фиксер ничего не делает."""
    paragraph = Paragraph(
        id="p1",
        content=[TextRun(text="ток 5 А")],
        style_name="Normal",
    )
    doc = _doc_with_paragraph(paragraph)
    profile = load_profile("gost-7.32-2017")
    applied = fix(doc, profile, codes=["U.01"])
    assert applied == []


# --- U.02: знак препинания между числом и единицей ---------------------------


def test_u02_fixer_registered() -> None:
    """Фиксер U.02 присутствует в реестре."""
    assert "U.02" in registered_fixers()


def test_u02_replaces_punct_with_nbsp() -> None:
    """U.02-фиксер: «10.кг» → «10 кг» (с неразрывным пробелом)."""
    paragraph = Paragraph(
        id="p1",
        content=[TextRun(text="масса 10.кг и 50,%")],
        style_name="Normal",
    )
    doc = _doc_with_paragraph(paragraph)
    profile = load_profile("gost-7.32-2017")
    applied = fix(doc, profile, codes=["U.02"])
    assert len(applied) == 1
    assert applied[0].fixer_code == "U.02"
    run = next(el for el in paragraph.content if isinstance(el, TextRun))
    assert "10 кг" in run.text
    assert "50 %" in run.text
    assert "10.кг" not in run.text
    assert "50,%" not in run.text


def test_u02_resolves_validator_violation() -> None:
    """После U.02-фикса проверка U.02 не находит нарушений."""
    paragraph = Paragraph(
        id="p1",
        content=[TextRun(text="ускорение 9.м составило")],
        style_name="Normal",
    )
    doc = _doc_with_paragraph(paragraph)
    profile = load_profile("gost-7.32-2017")
    fix(doc, profile, codes=["U.02"])
    assert not [v for v in validate(doc, profile) if v.check_code == "U.02"]


def test_u02_no_change_when_correct() -> None:
    """Корректная запись «10 кг» (с пробелом) фиксер не трогает."""
    paragraph = Paragraph(
        id="p1",
        content=[TextRun(text="масса 10 кг")],
        style_name="Normal",
    )
    doc = _doc_with_paragraph(paragraph)
    profile = load_profile("gost-7.32-2017")
    applied = fix(doc, profile, codes=["U.02"])
    assert applied == []


# --- U.03: точка после единицы измерения -------------------------------------


def test_u03_fixer_registered() -> None:
    """Фиксер U.03 присутствует в реестре."""
    assert "U.03" in registered_fixers()


def test_u03_drops_trailing_dot() -> None:
    """U.03-фиксер: «10 кг.» → «10 кг»."""
    paragraph = Paragraph(
        id="p1",
        content=[TextRun(text="масса 10 кг. в сумме")],
        style_name="Normal",
    )
    doc = _doc_with_paragraph(paragraph)
    profile = load_profile("gost-7.32-2017")
    applied = fix(doc, profile, codes=["U.03"])
    assert len(applied) == 1
    assert applied[0].fixer_code == "U.03"
    run = next(el for el in paragraph.content if isinstance(el, TextRun))
    assert "10 кг в сумме" in run.text
    assert "кг." not in run.text


def test_u03_resolves_validator_violation() -> None:
    """После U.03-фикса проверка U.03 не находит нарушений."""
    paragraph = Paragraph(
        id="p1",
        content=[TextRun(text="ток 5 А.")],
        style_name="Normal",
    )
    doc = _doc_with_paragraph(paragraph)
    profile = load_profile("gost-7.32-2017")
    fix(doc, profile, codes=["U.03"])
    assert not [v for v in validate(doc, profile) if v.check_code == "U.03"]


def test_u03_keeps_year_abbreviation() -> None:
    """«1990 г.» — это год, а не граммы; фиксер его не трогает (зеркало U.03)."""
    paragraph = Paragraph(
        id="p1",
        content=[TextRun(text="издано в 1990 г. в Москве")],
        style_name="Normal",
    )
    doc = _doc_with_paragraph(paragraph)
    profile = load_profile("gost-7.32-2017")
    applied = fix(doc, profile, codes=["U.03"])
    assert applied == []
    run = next(el for el in paragraph.content if isinstance(el, TextRun))
    assert "1990 г." in run.text


def test_u03_keeps_page_abbreviation() -> None:
    """«с.» (страница) всегда пропускается — слишком много ложных срабатываний."""
    paragraph = Paragraph(
        id="p1",
        content=[TextRun(text="см. 12 с. источника")],
        style_name="Normal",
    )
    doc = _doc_with_paragraph(paragraph)
    profile = load_profile("gost-7.32-2017")
    applied = fix(doc, profile, codes=["U.03"])
    assert applied == []


# --- T.01 / T.02: шрифт и кегль основного текста -----------------------------


def test_t01_t02_fixers_registered() -> None:
    assert {"T.01", "T.02"}.issubset(registered_fixers())


def test_t01_fixer_sets_expected_font_keeps_inherited() -> None:
    """T.01: явный неверный шрифт → Times New Roman; наследуемый (None) не трогаем."""
    paragraph = Paragraph(
        id="p1",
        style_name="Normal",
        content=[
            TextRun(text="плохой шрифт", font="Arial"),
            TextRun(text=" наследуемый", font=None),
        ],
    )
    doc = _doc_with_paragraph(paragraph)
    profile = load_profile("gost-7.32-2017")
    applied = fix(doc, profile, codes=["T.01"])
    assert len(applied) == 1 and applied[0].fixer_code == "T.01"
    runs = [el for el in paragraph.content if isinstance(el, TextRun)]
    assert runs[0].font == "Times New Roman"
    assert runs[1].font is None  # наследуемый не тронут


def test_t02_fixer_sets_expected_body_size() -> None:
    """T.02: явный неверный кегль тела → 14 pt; наследуемый (None) не трогаем."""
    paragraph = Paragraph(
        id="p1",
        style_name="Normal",
        content=[
            TextRun(text="мелкий", size_pt=10.0),
            TextRun(text=" наследуемый", size_pt=None),
        ],
    )
    doc = _doc_with_paragraph(paragraph)
    profile = load_profile("gost-7.32-2017")
    applied = fix(doc, profile, codes=["T.02"])
    assert len(applied) == 1 and applied[0].fixer_code == "T.02"
    runs = [el for el in paragraph.content if isinstance(el, TextRun)]
    assert runs[0].size_pt == 14.0
    assert runs[1].size_pt is None


def test_t02_fixer_respects_caption_size() -> None:
    """Для подписи (стиль Caption) ожидаемый кегль — 12 pt, не 14."""
    paragraph = Paragraph(
        id="cap1",
        style_name="Caption",
        content=[TextRun(text="Рисунок 1 — Схема", size_pt=10.0)],
    )
    doc = _doc_with_paragraph(paragraph)
    profile = load_profile("gost-7.32-2017")
    fix(doc, profile, codes=["T.02"])
    runs = [el for el in paragraph.content if isinstance(el, TextRun)]
    assert runs[0].size_pt == 12.0


def test_u02_fix_registered() -> None:
    """Фиксер U.02 присутствует в реестре."""
    assert "U.02" in registered_fixers()


def test_u02_replaces_punct_with_nbsp_exact() -> None:
    """«10.кг» → «10<NBSP>кг»: точка между числом и единицей заменяется на NBSP."""
    paragraph = Paragraph(
        id="p1",
        content=[TextRun(text="значение 10.кг")],
        style_name="Normal",
    )
    doc = _doc_with_paragraph(paragraph)
    profile = load_profile("gost-7.32-2017")
    applied = fix(doc, profile, codes=["U.02"])
    assert len(applied) == 1
    assert applied[0].fixer_code == "U.02"
    assert isinstance(applied[0], FixApplied)
    text_runs = [el for el in paragraph.content if isinstance(el, TextRun)]
    # В тексте должен появиться неразрывный пробел (U+00A0).
    assert " " in text_runs[0].text
    assert text_runs[0].text == "значение 10 кг"


def test_u02_no_change_when_clean() -> None:
    """Если между числом и единицей уже стоит обычный пробел — U.02 не трогает."""
    paragraph = Paragraph(
        id="p1",
        content=[TextRun(text="10 кг")],
        style_name="Normal",
    )
    doc = _doc_with_paragraph(paragraph)
    profile = load_profile("gost-7.32-2017")
    applied = fix(doc, profile, codes=["U.02"])
    assert applied == []
    text_runs = [el for el in paragraph.content if isinstance(el, TextRun)]
    assert text_runs[0].text == "10 кг"


# --- U.03: точка после единицы -----------------------------------------------


def test_u03_fix_registered() -> None:
    """Фиксер U.03 присутствует в реестре."""
    assert "U.03" in registered_fixers()


def test_u03_strips_trailing_dot() -> None:
    """«10 кг.» → «10 кг»: точка после единицы измерения убирается."""
    paragraph = Paragraph(
        id="p1",
        content=[TextRun(text="вес 10 кг.")],
        style_name="Normal",
    )
    doc = _doc_with_paragraph(paragraph)
    profile = load_profile("gost-7.32-2017")
    applied = fix(doc, profile, codes=["U.03"])
    assert len(applied) == 1
    assert applied[0].fixer_code == "U.03"
    text_runs = [el for el in paragraph.content if isinstance(el, TextRun)]
    assert text_runs[0].text == "вес 10 кг"


def test_u03_preserves_year_g() -> None:
    """«1990 г.» — это «год», а не «грамм». Фиксер должен пропустить."""
    paragraph = Paragraph(
        id="p1",
        content=[TextRun(text="в 1990 г. произошло событие")],
        style_name="Normal",
    )
    doc = _doc_with_paragraph(paragraph)
    profile = load_profile("gost-7.32-2017")
    applied = fix(doc, profile, codes=["U.03"])
    assert applied == []
    text_runs = [el for el in paragraph.content if isinstance(el, TextRun)]
    assert text_runs[0].text == "в 1990 г. произошло событие"


def test_u03_preserves_page_s() -> None:
    """«5 с.» — это «страница» в библиографии, фиксер пропускает «с.»."""
    paragraph = Paragraph(
        id="p1",
        content=[TextRun(text="см. 5 с.")],
        style_name="Normal",
    )
    doc = _doc_with_paragraph(paragraph)
    profile = load_profile("gost-7.32-2017")
    applied = fix(doc, profile, codes=["U.03"])
    assert applied == []
    text_runs = [el for el in paragraph.content if isinstance(el, TextRun)]
    assert text_runs[0].text == "см. 5 с."
