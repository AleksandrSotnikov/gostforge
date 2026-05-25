"""Тесты K.* — проверок колонтитулов и нумерации на уровне PageSection-ов."""

from __future__ import annotations

from gostforge.model import (
    ContentTemplate,
    Document,
    HeaderConfig,
    PageNumberingConfig,
    PageSection,
    TextRun,
)
from gostforge.profile import Profile, load_profile
from gostforge.validator import validate
from gostforge.validator.engine import registered_checks


def _profile() -> Profile:
    return load_profile("gost-7.32-2017")


# --- K.02 ---------------------------------------------------------------------


def test_k02_registered() -> None:
    assert "K.02" in registered_checks()


def test_k02_title_without_number_ok() -> None:
    doc = Document()
    doc.page_sections.append(
        PageSection(
            id="title",
            name="Титульный лист",
            type="title",
            page_numbering=PageNumberingConfig(visible=False),
        )
    )
    profile = _profile()
    violations = [v for v in validate(doc, profile) if v.check_code == "K.02"]
    assert violations == []


def test_k02_title_with_number_violation() -> None:
    doc = Document()
    doc.page_sections.append(
        PageSection(
            id="title",
            name="Титульный лист",
            type="title",
            page_numbering=PageNumberingConfig(visible=True),
        )
    )
    profile = _profile()
    violations = [v for v in validate(doc, profile) if v.check_code == "K.02"]
    assert len(violations) == 1
    assert violations[0].severity == "error"
    assert "title" in violations[0].location


def test_k02_non_title_sections_ignored() -> None:
    doc = Document()
    doc.page_sections.append(
        PageSection(
            id="main",
            name="Основная часть",
            type="main",
            page_numbering=PageNumberingConfig(visible=True),
        )
    )
    profile = _profile()
    violations = [v for v in validate(doc, profile) if v.check_code == "K.02"]
    assert violations == []


# --- K.03 ---------------------------------------------------------------------


def test_k03_registered() -> None:
    assert "K.03" in registered_checks()


def test_k03_correct_start_value() -> None:
    doc = Document()
    doc.page_sections.append(
        PageSection(
            id="title",
            name="Титульный лист",
            type="title",
            page_numbering=PageNumberingConfig(visible=False),
        )
    )
    doc.page_sections.append(
        PageSection(
            id="main",
            name="Основная часть",
            type="main",
            page_numbering=PageNumberingConfig(
                visible=True, start_mode="start_at", start_value=3
            ),
        )
    )
    profile = _profile()
    violations = [v for v in validate(doc, profile) if v.check_code == "K.03"]
    assert violations == []


def test_k03_wrong_start_value_violation() -> None:
    doc = Document()
    doc.page_sections.append(
        PageSection(
            id="main",
            name="Основная часть",
            type="main",
            page_numbering=PageNumberingConfig(
                visible=True, start_mode="start_at", start_value=1
            ),
        )
    )
    profile = _profile()
    violations = [v for v in validate(doc, profile) if v.check_code == "K.03"]
    assert len(violations) == 1
    assert "start_value" in violations[0].location


def test_k03_missing_start_at_violation() -> None:
    doc = Document()
    doc.page_sections.append(
        PageSection(
            id="main",
            name="Основная часть",
            type="main",
            page_numbering=PageNumberingConfig(
                visible=True, start_mode="continue"
            ),
        )
    )
    profile = _profile()
    violations = [v for v in validate(doc, profile) if v.check_code == "K.03"]
    assert len(violations) == 1
    assert violations[0].severity == "error"


def test_k03_no_main_section_no_violation() -> None:
    """Если в документе нет ни одной не-title секции — проверке нечего сказать."""
    doc = Document()
    doc.page_sections.append(
        PageSection(
            id="title",
            name="Титульный лист",
            type="title",
            page_numbering=PageNumberingConfig(visible=False),
        )
    )
    profile = _profile()
    violations = [v for v in validate(doc, profile) if v.check_code == "K.03"]
    assert violations == []


# --- K.04 ---------------------------------------------------------------------


def test_k04_registered() -> None:
    assert "K.04" in registered_checks()


def test_k04_continuous_numbering_ok() -> None:
    doc = Document()
    doc.page_sections.append(
        PageSection(
            id="title",
            name="Титульный лист",
            type="title",
            page_numbering=PageNumberingConfig(visible=False),
        )
    )
    doc.page_sections.append(
        PageSection(
            id="main",
            name="Основная часть",
            type="main",
            page_numbering=PageNumberingConfig(
                visible=True, start_mode="continue"
            ),
        )
    )
    doc.page_sections.append(
        PageSection(
            id="app",
            name="Приложения",
            type="appendix",
            page_numbering=PageNumberingConfig(
                visible=True, start_mode="continue"
            ),
        )
    )
    profile = _profile()
    violations = [v for v in validate(doc, profile) if v.check_code == "K.04"]
    assert violations == []


def test_k04_restart_in_middle_violation() -> None:
    doc = Document()
    doc.page_sections.append(
        PageSection(
            id="title",
            name="Титульный лист",
            type="title",
            page_numbering=PageNumberingConfig(visible=False),
        )
    )
    doc.page_sections.append(
        PageSection(
            id="main",
            name="Основная часть",
            type="main",
            page_numbering=PageNumberingConfig(
                visible=True, start_mode="restart"
            ),
        )
    )
    profile = _profile()
    violations = [v for v in validate(doc, profile) if v.check_code == "K.04"]
    assert len(violations) == 1
    assert violations[0].severity == "error"


def test_k04_first_section_restart_ignored() -> None:
    """Первая секция задаёт нумерацию — её start_mode проверка K.04 не трогает."""
    doc = Document()
    doc.page_sections.append(
        PageSection(
            id="main",
            name="Основная часть",
            type="main",
            page_numbering=PageNumberingConfig(
                visible=True, start_mode="restart"
            ),
        )
    )
    profile = _profile()
    violations = [v for v in validate(doc, profile) if v.check_code == "K.04"]
    assert violations == []


def test_k04_allow_restart_in_appendix_when_enabled() -> None:
    """Если allow_restart_in_appendix=True — рестарт в приложениях разрешён."""
    doc = Document()
    doc.page_sections.append(
        PageSection(
            id="main",
            name="Основная часть",
            type="main",
            page_numbering=PageNumberingConfig(
                visible=True, start_mode="start_at", start_value=3
            ),
        )
    )
    doc.page_sections.append(
        PageSection(
            id="app",
            name="Приложения",
            type="appendix",
            page_numbering=PageNumberingConfig(
                visible=True, start_mode="restart"
            ),
        )
    )
    profile = _profile()
    # Меняем параметр прямо в загруженном профиле.
    profile.checks["K.04"].params["allow_restart_in_appendix"] = True
    violations = [v for v in validate(doc, profile) if v.check_code == "K.04"]
    assert violations == []


# --- K.05 ---------------------------------------------------------------------


def test_k05_registered() -> None:
    assert "K.05" in registered_checks()


def test_k05_appendix_with_proper_header_ok() -> None:
    doc = Document()
    doc.page_sections.append(
        PageSection(
            id="app",
            name="Приложения",
            type="appendix",
            header=HeaderConfig(
                default=ContentTemplate(
                    center=[TextRun(text="ПРИЛОЖЕНИЕ {appendix_letter}")]
                )
            ),
        )
    )
    profile = _profile()
    violations = [v for v in validate(doc, profile) if v.check_code == "K.05"]
    assert violations == []


def test_k05_appendix_without_header_violation() -> None:
    doc = Document()
    doc.page_sections.append(
        PageSection(
            id="app",
            name="Приложения",
            type="appendix",
            header=None,
        )
    )
    profile = _profile()
    violations = [v for v in validate(doc, profile) if v.check_code == "K.05"]
    assert len(violations) == 1
    assert violations[0].severity == "warning"


def test_k05_appendix_header_without_keyword_violation() -> None:
    doc = Document()
    doc.page_sections.append(
        PageSection(
            id="app",
            name="Приложения",
            type="appendix",
            header=HeaderConfig(
                default=ContentTemplate(center=[TextRun(text="Какой-то текст")])
            ),
        )
    )
    profile = _profile()
    violations = [v for v in validate(doc, profile) if v.check_code == "K.05"]
    assert len(violations) == 1
    assert violations[0].severity == "warning"


def test_k05_non_appendix_ignored() -> None:
    doc = Document()
    doc.page_sections.append(
        PageSection(
            id="main",
            name="Основная часть",
            type="main",
            header=None,
        )
    )
    profile = _profile()
    violations = [v for v in validate(doc, profile) if v.check_code == "K.05"]
    assert violations == []


# --- K.01 ---------------------------------------------------------------------


def test_k01_registered() -> None:
    assert "K.01" in registered_checks()


def test_k01_all_expected_sections_ok() -> None:
    doc = Document()
    for sid, name, stype in [
        ("title", "Титульный лист", "title"),
        ("fm1", "Реферат", "frontmatter"),
        ("fm2", "Содержание", "frontmatter"),
        ("main", "Основная часть", "main"),
        ("app", "Приложения", "appendix"),
    ]:
        doc.page_sections.append(
            PageSection(
                id=sid,
                name=name,
                type=stype,  # type: ignore[arg-type]
                page_numbering=PageNumberingConfig(visible=False)
                if stype == "title"
                else PageNumberingConfig(
                    visible=True, start_mode="start_at", start_value=3
                )
                if stype == "main"
                else PageNumberingConfig(visible=True, start_mode="continue"),
            )
        )
    profile = _profile()
    violations = [v for v in validate(doc, profile) if v.check_code == "K.01"]
    assert violations == []


def test_k01_missing_sections_violation() -> None:
    """В документе только main — отсутствуют title/frontmatter/appendix."""
    doc = Document()
    doc.page_sections.append(
        PageSection(
            id="main",
            name="Основная часть",
            type="main",
            page_numbering=PageNumberingConfig(
                visible=True, start_mode="start_at", start_value=3
            ),
        )
    )
    profile = _profile()
    violations = [v for v in validate(doc, profile) if v.check_code == "K.01"]
    # В шаблоне: title + frontmatter + frontmatter + main + appendix.
    # Отсутствуют 4 типа (title, frontmatter×2, appendix).
    assert len(violations) >= 3
    assert all(v.severity == "error" for v in violations)


def test_k01_wrong_order_violation() -> None:
    """Приложение раньше основной части — порядок нарушен."""
    doc = Document()
    doc.page_sections.append(
        PageSection(
            id="title",
            name="Титульный лист",
            type="title",
        )
    )
    doc.page_sections.append(
        PageSection(
            id="app",
            name="Приложения",
            type="appendix",
        )
    )
    doc.page_sections.append(
        PageSection(
            id="main",
            name="Основная часть",
            type="main",
        )
    )
    profile = _profile()
    violations = [v for v in validate(doc, profile) if v.check_code == "K.01"]
    # Должно быть хотя бы одно сообщение про порядок или отсутствие.
    assert len(violations) >= 1


def test_k01_empty_document_violation() -> None:
    doc = Document()
    profile = _profile()
    violations = [v for v in validate(doc, profile) if v.check_code == "K.01"]
    # Все главные типы из шаблона: title, frontmatter, frontmatter, main, appendix.
    assert len(violations) >= 4


def test_k01_empty_template_no_violation() -> None:
    """Если профиль не задаёт sections_template — проверке нечего делать."""
    profile = _profile()
    profile.sections_template = []
    doc = Document()
    violations = [v for v in validate(doc, profile) if v.check_code == "K.01"]
    assert violations == []
