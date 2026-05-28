"""Тесты проверок V.* — объём и метрики."""

from __future__ import annotations

from gostforge.model import (
    BlockType,
    Document,
    Figure,
    LogicalSection,
    PageSection,
    Paragraph,
    Table,
    TextRun,
)
from gostforge.profile import load_profile
from gostforge.validator import validate
from gostforge.validator.engine import registered_checks


def _make_paragraph(idx: int, text: str) -> Paragraph:
    return Paragraph(id=f"p{idx}", type=BlockType.PARAGRAPH, content=[TextRun(text=text)])


def _make_section_with_words(num_paragraphs: int, words_per_paragraph: int) -> PageSection:
    """Создать PageSection с указанным количеством параграфов и слов в каждом."""
    section = PageSection(id="main", name="Основная часть", type="main")
    for i in range(num_paragraphs):
        words = " ".join(f"слово{i}_{j}" for j in range(words_per_paragraph))
        section.content.append(_make_paragraph(i, words))
    return section


# ----- V.01 --------------------------------------------------------------------


def test_v_01_registered() -> None:
    assert "V.01" in registered_checks()


def test_v_01_volume_within_range_no_violation() -> None:
    """30 страниц по 250 слов = 7500 слов — в диапазоне [25, 50]."""
    doc = Document()
    # 30 параграфов по 250 слов = 7500 слов ≈ 30 страниц
    doc.page_sections.append(_make_section_with_words(30, 250))
    profile = load_profile("gost-7.32-2017")
    violations = [v for v in validate(doc, profile) if v.check_code == "V.01"]
    assert violations == []


def test_v_01_too_few_pages_warning() -> None:
    """500 слов = ~2 страницы — намного меньше 25 минимальных."""
    doc = Document()
    doc.page_sections.append(_make_section_with_words(5, 100))  # 500 слов
    profile = load_profile("gost-7.32-2017")
    violations = [v for v in validate(doc, profile) if v.check_code == "V.01"]
    assert len(violations) == 1
    assert violations[0].severity == "warning"
    assert "минимум" in violations[0].message.lower() or "минимум" in violations[0].message


def test_v_01_too_many_pages_warning() -> None:
    """100 параграфов по 250 слов = 25000 слов ≈ 100 страниц — больше 50."""
    doc = Document()
    doc.page_sections.append(_make_section_with_words(100, 250))
    profile = load_profile("gost-7.32-2017")
    violations = [v for v in validate(doc, profile) if v.check_code == "V.01"]
    assert len(violations) == 1
    assert violations[0].severity == "warning"
    assert "максимум" in violations[0].message.lower()


def test_v_01_empty_document_triggers_min_warning() -> None:
    """Пустой документ — 0 слов, должно быть нарушение по минимуму."""
    doc = Document()
    doc.page_sections.append(PageSection(id="main", name="Основная часть", type="main"))
    profile = load_profile("gost-7.32-2017")
    violations = [v for v in validate(doc, profile) if v.check_code == "V.01"]
    assert len(violations) == 1
    assert violations[0].severity == "warning"


# ----- V.02 --------------------------------------------------------------------


def _section_with_text(section_id: str, heading_text: str, paragraph_text: str) -> LogicalSection:
    """Создать LogicalSection с одним заголовком и одним параграфом-телом."""
    section = LogicalSection(
        id=section_id,
        heading=[TextRun(text=heading_text)],
        level=1,
    )
    if paragraph_text:
        section.children.append(_make_paragraph(0, paragraph_text))
    return section


def _doc_with_intro_conclusion(intro_words: int, conclusion_words: int) -> Document:
    doc = Document()
    page = PageSection(id="main", name="Основная часть", type="main")
    intro_text = " ".join(f"intro{i}" for i in range(intro_words))
    concl_text = " ".join(f"concl{i}" for i in range(conclusion_words))
    page.content.append(_section_with_text("intro", "Введение", intro_text))
    page.content.append(_section_with_text("concl", "Заключение", concl_text))
    doc.page_sections.append(page)
    return doc


def test_v_02_registered() -> None:
    assert "V.02" in registered_checks()


def test_v_02_intro_and_conclusion_within_range_no_violation() -> None:
    """1000 слов во введении и 700 — в заключении — норма."""
    doc = _doc_with_intro_conclusion(1000, 700)
    profile = load_profile("gost-7.32-2017")
    violations = [v for v in validate(doc, profile) if v.check_code == "V.02"]
    assert violations == []


def test_v_02_intro_too_short_warning() -> None:
    """100 слов во введении — намного меньше 800."""
    doc = _doc_with_intro_conclusion(100, 700)
    profile = load_profile("gost-7.32-2017")
    violations = [v for v in validate(doc, profile) if v.check_code == "V.02"]
    assert len(violations) == 1
    assert violations[0].severity == "warning"
    assert "Введение" in violations[0].message


def test_v_02_conclusion_too_long_warning() -> None:
    """2000 слов в заключении — больше 1200."""
    doc = _doc_with_intro_conclusion(1000, 2000)
    profile = load_profile("gost-7.32-2017")
    violations = [v for v in validate(doc, profile) if v.check_code == "V.02"]
    assert len(violations) == 1
    assert violations[0].severity == "warning"
    assert "Заключение" in violations[0].message


def test_v_02_no_intro_section_no_violation() -> None:
    """Если введения нет — V.02 молчит (это зона ответственности S.* проверок)."""
    doc = Document()
    page = PageSection(id="main", name="Основная часть", type="main")
    page.content.append(_section_with_text("concl", "Заключение", "слово " * 700))
    doc.page_sections.append(page)
    profile = load_profile("gost-7.32-2017")
    violations = [v for v in validate(doc, profile) if v.check_code == "V.02"]
    assert violations == []


def test_v_02_case_insensitive_heading() -> None:
    """Заголовок «ВВЕДЕНИЕ» в верхнем регистре должен распознаваться."""
    doc = Document()
    page = PageSection(id="main", name="Основная часть", type="main")
    text = " ".join(f"w{i}" for i in range(100))  # мало слов — должно дать violation
    page.content.append(_section_with_text("intro", "ВВЕДЕНИЕ", text))
    doc.page_sections.append(page)
    profile = load_profile("gost-7.32-2017")
    violations = [v for v in validate(doc, profile) if v.check_code == "V.02"]
    assert len(violations) == 1


# ----- V.04 --------------------------------------------------------------------


def test_v_04_registered() -> None:
    assert "V.04" in registered_checks()


def test_v_04_enough_figures_and_tables_no_violation() -> None:
    """30 страниц = 3 блока по 10. Должно быть >= 3 рисунка и 3 таблицы."""
    doc = Document()
    page = _make_section_with_words(30, 250)  # ~30 страниц
    for i in range(3):
        page.content.append(Figure(id=f"fig{i}", type=BlockType.FIGURE, image_path=f"img{i}.png"))
        page.content.append(Table(id=f"tbl{i}", type=BlockType.TABLE))
    doc.page_sections.append(page)
    profile = load_profile("gost-7.32-2017")
    violations = [v for v in validate(doc, profile) if v.check_code == "V.04"]
    assert violations == []


def test_v_04_no_figures_yields_violation() -> None:
    """30 страниц, 0 рисунков, 3 таблицы — violation по рисункам."""
    doc = Document()
    page = _make_section_with_words(30, 250)
    for i in range(3):
        page.content.append(Table(id=f"tbl{i}", type=BlockType.TABLE))
    doc.page_sections.append(page)
    profile = load_profile("gost-7.32-2017")
    violations = [v for v in validate(doc, profile) if v.check_code == "V.04"]
    assert len(violations) == 1
    assert violations[0].severity == "info"
    assert "Рисунков" in violations[0].message


def test_v_04_no_tables_yields_violation() -> None:
    """30 страниц, 3 рисунка, 0 таблиц — violation по таблицам."""
    doc = Document()
    page = _make_section_with_words(30, 250)
    for i in range(3):
        page.content.append(Figure(id=f"fig{i}", type=BlockType.FIGURE, image_path=f"img{i}.png"))
    doc.page_sections.append(page)
    profile = load_profile("gost-7.32-2017")
    violations = [v for v in validate(doc, profile) if v.check_code == "V.04"]
    assert len(violations) == 1
    assert violations[0].severity == "info"
    assert "Таблиц" in violations[0].message


def test_v_04_no_figures_and_no_tables_yields_two_violations() -> None:
    """30 страниц, 0 рисунков, 0 таблиц — 2 violation."""
    doc = Document()
    page = _make_section_with_words(30, 250)
    doc.page_sections.append(page)
    profile = load_profile("gost-7.32-2017")
    violations = [v for v in validate(doc, profile) if v.check_code == "V.04"]
    assert len(violations) == 2


# ----- V.03 (заглушка) ---------------------------------------------------------


def test_v_03_registered() -> None:
    """V.03 пока — заглушка, регистрация обязана быть, нарушений нет."""
    assert "V.03" in registered_checks()


def test_v_03_stub_returns_no_violations() -> None:
    doc = Document()
    doc.page_sections.append(_make_section_with_words(30, 250))
    profile = load_profile("gost-7.32-2017")
    violations = [v for v in validate(doc, profile) if v.check_code == "V.03"]
    assert violations == []
