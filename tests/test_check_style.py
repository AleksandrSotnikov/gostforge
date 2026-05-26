"""Тесты проверок X.* — стиль и лингвистика."""

from __future__ import annotations

from gostforge.model import (
    BlockType,
    Document,
    PageSection,
    Paragraph,
    TextRun,
)
from gostforge.profile import load_profile
from gostforge.validator import validate
from gostforge.validator.engine import registered_checks


def _make_paragraph(idx: int, text: str) -> Paragraph:
    return Paragraph(id=f"p{idx}", type=BlockType.PARAGRAPH, content=[TextRun(text=text)])


def _doc_with_paragraphs(*texts: str) -> Document:
    doc = Document()
    page = PageSection(id="main", name="Основная часть", type="main")
    for i, text in enumerate(texts):
        page.content.append(_make_paragraph(i, text))
    doc.page_sections.append(page)
    return doc


# ----- X.02 --------------------------------------------------------------------


def test_x_02_registered() -> None:
    assert "X.02" in registered_checks()


def test_x_02_neutral_text_no_violation() -> None:
    doc = _doc_with_paragraphs(
        "В работе рассмотрено применение методов машинного обучения.",
        "Было получено приближённое решение задачи.",
    )
    profile = load_profile("gost-7.32-2017")
    violations = [v for v in validate(doc, profile) if v.check_code == "X.02"]
    assert violations == []


def test_x_02_finds_ya() -> None:
    doc = _doc_with_paragraphs("Я считаю это правильным подходом.")
    profile = load_profile("gost-7.32-2017")
    violations = [v for v in validate(doc, profile) if v.check_code == "X.02"]
    assert len(violations) == 1
    assert violations[0].severity == "warning"
    assert violations[0].details["found"].lower() == "я"


def test_x_02_finds_mne_menya_moi_various_cases() -> None:
    doc = _doc_with_paragraphs(
        "Мне довелось участвовать в исследовании.",
        "У меня возникла гипотеза.",
        "Мой подход отличается простотой.",
        "Моя задача состояла в анализе данных.",
    )
    profile = load_profile("gost-7.32-2017")
    violations = [v for v in validate(doc, profile) if v.check_code == "X.02"]
    assert len(violations) == 4
    found_words = {v.details["found"].lower() for v in violations}
    assert "мне" in found_words
    assert "меня" in found_words
    assert "мой" in found_words
    assert "моя" in found_words


def test_x_02_one_violation_per_paragraph() -> None:
    """Несколько местоимений в одном параграфе — один Violation."""
    doc = _doc_with_paragraphs("Я думаю, что мне это удалось, и моя работа закончена.")
    profile = load_profile("gost-7.32-2017")
    violations = [v for v in validate(doc, profile) if v.check_code == "X.02"]
    assert len(violations) == 1


def test_x_02_word_boundary_does_not_match_substrings() -> None:
    """«яблоко», «мнение», «менять» не должны попадать как совпадение."""
    doc = _doc_with_paragraphs(
        "Яблоко падает быстро.",
        "Это мнение учёных широко распространено.",
        "Необходимо менять подход.",
        "Семья из четырёх человек.",
    )
    profile = load_profile("gost-7.32-2017")
    violations = [v for v in validate(doc, profile) if v.check_code == "X.02"]
    assert violations == []


# ----- X.03 --------------------------------------------------------------------


def test_x_03_registered() -> None:
    assert "X.03" in registered_checks()


def test_x_03_neutral_text_no_violation() -> None:
    doc = _doc_with_paragraphs(
        "В работе рассмотрено применение методов машинного обучения.",
        "Полученные результаты позволяют сделать вывод о применимости подхода.",
    )
    profile = load_profile("gost-7.32-2017")
    violations = [v for v in validate(doc, profile) if v.check_code == "X.03"]
    assert violations == []


def test_x_03_finds_default_phrases() -> None:
    doc = _doc_with_paragraphs(
        "Короче, основной идеей является.",  # «короче»
        "Это, как бы, противоречит ожиданиям.",  # «как бы»
        "Получили типа того результата, который ожидался.",  # «типа того»
    )
    profile = load_profile("gost-7.32-2017")
    violations = [v for v in validate(doc, profile) if v.check_code == "X.03"]
    assert len(violations) == 3
    phrases = {v.details["phrase"].lower() for v in violations}
    assert "короче" in phrases
    assert "как бы" in phrases
    assert "типа того" in phrases


def test_x_03_severity_is_info() -> None:
    doc = _doc_with_paragraphs("Короче, это не работает.")
    profile = load_profile("gost-7.32-2017")
    violations = [v for v in validate(doc, profile) if v.check_code == "X.03"]
    assert len(violations) == 1
    assert violations[0].severity == "info"


def test_x_03_case_insensitive() -> None:
    doc = _doc_with_paragraphs("КОРОЧЕ, это нужно переформулировать.")
    profile = load_profile("gost-7.32-2017")
    violations = [v for v in validate(doc, profile) if v.check_code == "X.03"]
    assert len(violations) == 1


# ----- X.01 (заглушка) ---------------------------------------------------------


def test_x_01_registered() -> None:
    """X.01 пока — заглушка, регистрация обязана быть, нарушений нет."""
    assert "X.01" in registered_checks()


def test_x_01_stub_returns_no_violations() -> None:
    doc = _doc_with_paragraphs(
        "Текст с заведомыми ошибкаммии — заглушка не должна их находить.",
    )
    profile = load_profile("gost-7.32-2017")
    violations = [v for v in validate(doc, profile) if v.check_code == "X.01"]
    assert violations == []


# ----- X.04 (заглушка) ---------------------------------------------------------


def test_x_04_registered() -> None:
    """X.04 пока — заглушка, регистрация обязана быть."""
    assert "X.04" in registered_checks()


def test_x_04_stub_returns_no_violations() -> None:
    doc = _doc_with_paragraphs(
        "Эксперимент длился 2 секунд и 5 секунда — реализация заглушки.",
    )
    profile = load_profile("gost-7.32-2017")
    violations = [v for v in validate(doc, profile) if v.check_code == "X.04"]
    assert violations == []


# ----- X.05 (заглушка) ---------------------------------------------------------


def test_x_05_registered() -> None:
    """X.05 пока — заглушка, регистрация обязана быть."""
    assert "X.05" in registered_checks()


def test_x_05_stub_returns_no_violations() -> None:
    doc = _doc_with_paragraphs(
        "База данных и БД — заглушка не должна сравнивать термины.",
    )
    profile = load_profile("gost-7.32-2017")
    violations = [v for v in validate(doc, profile) if v.check_code == "X.05"]
    assert violations == []
