# ruff: noqa: RUF001, RUF002, RUF003

"""Тесты движка автоисправлений и фиксеров T.08/T.09/T.10/T.11/T.12/T.13/H.03/H.08."""

from __future__ import annotations

from pathlib import Path

from gostforge.exporter import export_docx
from gostforge.fixer import FixApplied, fix, registered_fixers
from gostforge.model import (
    Document,
    LogicalSection,
    PageGeometry,
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
