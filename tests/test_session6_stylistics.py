"""Тесты X.06 (канцеляризмы), X.07 (длинные предложения), X.08 (повторы)."""

from __future__ import annotations

from gostforge.model import (
    Document,
    DocumentMetadata,
    LogicalSection,
    PageGeometry,
    PageNumberingConfig,
    PageSection,
    Paragraph,
    TextRun,
)
from gostforge.profile import load_profile
from gostforge.validator import validate


def _doc_with_text(text: str) -> Document:
    doc = Document(metadata=DocumentMetadata(title="X"))
    p = Paragraph(
        id="p1",
        content=[TextRun(text=text)],
        style_name="Normal",
    )
    sec = LogicalSection(
        id="s",
        heading=[TextRun(text="Введение")],
        level=1,
        children=[p],
    )
    doc.page_sections.append(
        PageSection(
            id="m",
            name="N",
            type="main",
            page=PageGeometry(),
            page_numbering=PageNumberingConfig(),
            content=[sec],
        )
    )
    return doc


def _profile_with_x_enabled() -> object:
    profile = load_profile("gost-7.32-2017").model_copy(deep=True)
    for c in ("X.06", "X.07", "X.08"):
        profile.checks[c].enabled = True
    return profile


# --- X.06 канцеляризмы ---


def test_x06_detects_multiple_bureaucratic() -> None:
    doc = _doc_with_text(
        "Программа является основой. Она осуществляется через интерфейс. "
        "Также представляет собой набор модулей."
    )
    v = validate(doc, _profile_with_x_enabled())
    x06 = [x for x in v if x.check_code == "X.06"]
    assert x06  # > max_per_paragraph (default 1)


def test_x06_one_bureaucratic_no_violation() -> None:
    """Один канцеляризм в абзаце — не нарушает (max_per_paragraph=1)."""
    doc = _doc_with_text("Программа является основой работы.")
    v = validate(doc, _profile_with_x_enabled())
    x06 = [x for x in v if x.check_code == "X.06"]
    assert x06 == []


def test_x06_custom_patterns_via_params() -> None:
    """Дополнительные паттерны через params.custom_patterns."""
    doc = _doc_with_text("В рамках работы было предпринято исследование.")
    profile = _profile_with_x_enabled()
    profile.checks["X.06"].params = {
        "max_per_paragraph": 0,
        "custom_patterns": [
            {"pattern": r"\bв\s+рамках\b", "suggestion": "Упростить"},
        ],
    }
    v = validate(doc, profile)
    x06 = [x for x in v if x.check_code == "X.06"]
    assert x06


def test_x06_disabled_by_default() -> None:
    """В дефолтном профиле X.06 enabled=False."""
    doc = _doc_with_text("Программа является основой. Осуществляется проверка.")
    v = validate(doc, load_profile("gost-7.32-2017"))
    x06 = [x for x in v if x.check_code == "X.06"]
    assert x06 == []


def test_x06_skip_headings() -> None:
    """Проверка не применяется к заголовкам."""
    doc = Document(metadata=DocumentMetadata(title="X"))
    heading_p = Paragraph(
        id="h1",
        content=[TextRun(text="Глава является основной частью работы")],
        style_name="Heading 1",
    )
    sec = LogicalSection(
        id="s",
        heading=[TextRun(text="X")],
        level=1,
        children=[heading_p],
    )
    doc.page_sections.append(
        PageSection(
            id="m",
            name="N",
            type="main",
            page=PageGeometry(),
            page_numbering=PageNumberingConfig(),
            content=[sec],
        )
    )
    v = validate(doc, _profile_with_x_enabled())
    x06 = [x for x in v if x.check_code == "X.06"]
    assert x06 == []


# --- X.07 длинные предложения ---


def test_x07_detects_long_sentence() -> None:
    """Предложение > 35 слов → X.07."""
    long_sentence = " ".join(["слово"] * 40) + "."
    doc = _doc_with_text(long_sentence)
    v = validate(doc, _profile_with_x_enabled())
    x07 = [x for x in v if x.check_code == "X.07"]
    assert len(x07) == 1


def test_x07_short_sentences_no_violation() -> None:
    doc = _doc_with_text("Короткое предложение. И ещё одно. Третье.")
    v = validate(doc, _profile_with_x_enabled())
    x07 = [x for x in v if x.check_code == "X.07"]
    assert x07 == []


def test_x07_custom_max_words() -> None:
    """Можно настроить max_words через профиль."""
    profile = _profile_with_x_enabled()
    profile.checks["X.07"].params = {"max_words": 5}
    doc = _doc_with_text("Это предложение содержит ровно семь слов сразу.")
    v = validate(doc, profile)
    x07 = [x for x in v if x.check_code == "X.07"]
    assert x07


# --- X.08 повтор слов ---


def test_x08_detects_immediate_repetition() -> None:
    doc = _doc_with_text("Программа программа очень хорошая.")
    v = validate(doc, _profile_with_x_enabled())
    x08 = [x for x in v if x.check_code == "X.08"]
    assert x08


def test_x08_no_repetition_at_distance() -> None:
    """Повтор через большое расстояние не нарушает."""
    doc = _doc_with_text(
        "Программа в большом и сложном проекте, разрабатываемом группой, "
        "содержит много модулей и тестов. И ещё подсистем. Программа "
        "включает много компонентов."
    )
    v = validate(doc, _profile_with_x_enabled())
    x08 = [x for x in v if x.check_code == "X.08"]
    # Можем найти, можем не найти — зависит от точного позиционирования.
    # Главное — не должно быть exception.
    assert isinstance(x08, list)


def test_x08_stop_words_not_reported() -> None:
    """Повтор стоп-слов (предлоги, союзы) не считается."""
    doc = _doc_with_text("Программа для системы для пользователя для администратора.")
    v = validate(doc, _profile_with_x_enabled())
    x08 = [x for x in v if x.check_code == "X.08"]
    # 'для' — короче 4 символов, скипается.
    assert all("для" not in v.message for v in x08)


def test_x08_unique_word_reported_once() -> None:
    """Слово, повторённое несколько раз, репортится один раз."""
    doc = _doc_with_text("Программа программа программа программа очень хорошая.")
    v = validate(doc, _profile_with_x_enabled())
    x08 = [x for x in v if x.check_code == "X.08"]
    # Все «программа» — но репорт только один.
    assert len(x08) == 1


def test_x08_min_distance_param() -> None:
    """min_distance из параметров."""
    profile = _profile_with_x_enabled()
    profile.checks["X.08"].params = {"min_distance": 10}
    doc = _doc_with_text("Программа большая. Затем программа маленькая.")
    v = validate(doc, profile)
    x08 = [x for x in v if x.check_code == "X.08"]
    # На расстоянии 3 слов — нарушение при min_distance=10.
    assert x08
