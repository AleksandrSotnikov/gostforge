"""Тесты интерактивного конструктора (gostforge.web.builder_editor).

Стримлит-виджеты через UI-раннер не дёргаем — только чистые функции
сборки, обратного преобразования и шаблонов. Этого достаточно, чтобы
покрыть ядро логики редактора.
"""

from __future__ import annotations

import io
import zipfile

import pytest

pytest.importorskip("streamlit")

from gostforge.builder import work
from gostforge.builder.templates import coursework_template
from gostforge.web.builder_editor import (
    _build_document_from_state,
    _default_state,
    _document_to_state,
    _load_template_to_state,
    render_interactive_builder,
)


def _docx_xml(data: bytes, member: str = "word/document.xml") -> str:
    """Извлечь конкретный XML-член из .docx как строку."""
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        return zf.read(member).decode("utf-8")


# --- Smoke ------------------------------------------------------------------


def test_render_interactive_builder_importable() -> None:
    """Главная функция режима импортируется и вызываема."""
    assert callable(render_interactive_builder)


# --- Сборка из state --------------------------------------------------------


def test_build_document_from_state_minimal() -> None:
    """Минимальный state с одним параграфом → байты .docx."""
    state = {
        "title": "Тест",
        "author": "Иванов",
        "year": 2026,
        "work_type": "coursework",
        "profile_id": "gost-7.32-2017",
        "sections": [
            {
                "id": "intro",
                "heading": "Введение",
                "blocks": [
                    {"kind": "paragraph", "text": "Актуальность темы заключается в..."},
                ],
            },
        ],
    }
    data = _build_document_from_state(state)
    assert isinstance(data, bytes)
    assert data[:2] == b"PK"
    xml = _docx_xml(data)
    assert "Актуальность темы заключается" in xml


def test_build_document_from_state_with_table() -> None:
    """Таблица в state → в .docx есть таблица."""
    state = {
        "title": "T",
        "author": "A",
        "year": 2026,
        "work_type": "coursework",
        "profile_id": "gost-7.32-2017",
        "sections": [
            {
                "id": "intro",
                "heading": "Введение",
                "blocks": [
                    {
                        "kind": "table",
                        "headers": ["A", "B"],
                        "rows": [["1", "2"], ["3", "4"]],
                        "caption": "Результаты",
                    }
                ],
            }
        ],
    }
    data = _build_document_from_state(state)
    xml = _docx_xml(data)
    # python-docx пишет таблицу как <w:tbl> — проверим, что элемент есть.
    assert "<w:tbl>" in xml or "<w:tbl " in xml
    # Подпись содержит «Таблица 1 — ...» — её добавляет builder.
    assert "Результаты" in xml


def test_build_document_from_state_with_list() -> None:
    """Список с 3 элементами → в .docx виден текст элементов."""
    state = {
        "title": "T",
        "author": "A",
        "year": 2026,
        "work_type": "coursework",
        "profile_id": "gost-7.32-2017",
        "sections": [
            {
                "id": "intro",
                "heading": "Введение",
                "blocks": [
                    {
                        "kind": "list",
                        "items": ["раз", "два", "три"],
                        "ordered": True,
                    }
                ],
            }
        ],
    }
    data = _build_document_from_state(state)
    xml = _docx_xml(data)
    for item in ("раз", "два", "три"):
        assert item in xml


def test_build_document_from_state_with_formula() -> None:
    """Формула в state не ломает сборку и попадает в модель.

    Экспортёр в Фазе 1 не пишет OMML, поэтому в самом XML текста может не
    быть; критично, что _build_document_from_state не падает.
    """
    state = {
        "title": "T",
        "author": "A",
        "year": 2026,
        "work_type": "coursework",
        "profile_id": "gost-7.32-2017",
        "sections": [
            {
                "id": "intro",
                "heading": "Введение",
                "blocks": [
                    {"kind": "paragraph", "text": "Формула Эйнштейна:"},
                    {"kind": "formula", "latex": "E=mc^2", "numbered": True},
                ],
            }
        ],
    }
    data = _build_document_from_state(state)
    assert isinstance(data, bytes)
    assert data[:2] == b"PK"


def test_build_document_from_state_with_subsection() -> None:
    """Подраздел внутри раздела → в .docx виден его заголовок."""
    state = {
        "title": "T",
        "author": "A",
        "year": 2026,
        "work_type": "coursework",
        "profile_id": "gost-7.32-2017",
        "sections": [
            {
                "id": "chapter-1",
                "heading": "Глава 1. Анализ",
                "blocks": [
                    {"kind": "paragraph", "text": "Введение в главу."},
                ],
                "subsections": [
                    {
                        "id": "1-1",
                        "heading": "1.1 Подраздел один",
                        "blocks": [
                            {"kind": "paragraph", "text": "Текст подраздела."},
                        ],
                    },
                ],
            }
        ],
    }
    data = _build_document_from_state(state)
    xml = _docx_xml(data)
    assert "Подраздел один" in xml
    assert "Текст подраздела" in xml


def test_build_document_from_state_with_bibliography() -> None:
    """Раздел is_bibliography=True с references → ссылки попадают в .docx."""
    state = {
        "title": "T",
        "author": "A",
        "year": 2026,
        "work_type": "coursework",
        "profile_id": "gost-7.32-2017",
        "sections": [
            {
                "id": "intro",
                "heading": "Введение",
                "blocks": [{"kind": "paragraph", "text": "Текст введения."}],
            },
            {
                "id": "bib",
                "heading": "Список использованных источников",
                "blocks": [],
                "is_bibliography": True,
                "references": [
                    "Иванов И. И. Программирование. — М. : Наука, 2023. — 320 с.",
                ],
            },
        ],
    }
    data = _build_document_from_state(state)
    xml = _docx_xml(data)
    assert "Иванов И. И." in xml


def test_document_to_state_roundtrip() -> None:
    """Document → state → Document даёт корректный .docx."""
    builder = (
        work("Курсовая", author="Иванов", year=2026, work_type="coursework")
        .section("Введение")
        .paragraph("Актуальность темы.")
        .section("Глава 1. Анализ")
        .paragraph("Основной текст.")
        .section("Заключение")
        .paragraph("Выводы.")
        .root
    )
    document = builder.build()
    state = _document_to_state(document)
    assert state["title"] == "Курсовая"
    headings = [s["heading"] for s in state["sections"]]
    assert any("ВВЕДЕНИЕ" in h.upper() for h in headings)
    assert any("ЗАКЛЮЧЕНИЕ" in h.upper() for h in headings)

    # Сборка обратно — без исключений и валидный .docx.
    data = _build_document_from_state(state)
    assert data[:2] == b"PK"


def test_load_template_to_state_coursework() -> None:
    """_load_template_to_state('coursework') возвращает state с обязательными разделами."""
    state = _load_template_to_state(
        "coursework",
        title="Курсовая по нормоконтролю",
        author="Иванов И. И.",
        year=2026,
    )
    assert state["title"] == "Курсовая по нормоконтролю"
    assert state["work_type"] == "coursework"
    assert state["author"] == "Иванов И. И."
    headings = [s["heading"].upper() for s in state["sections"]]
    assert any("ВВЕДЕНИЕ" in h for h in headings)
    assert any("ЗАКЛЮЧЕНИЕ" in h for h in headings)
    assert any("СПИСОК" in h for h in headings)
    # У раздела «Список использованных источников» должен стоять флаг.
    bib = next(s for s in state["sections"] if "СПИСОК" in s["heading"].upper())
    assert bib.get("is_bibliography") is True


def test_load_template_to_state_research_report() -> None:
    """research_report-шаблон даёт is_bibliography флаг и корректный work_type."""
    state = _load_template_to_state(
        "research_report",
        title="Отчёт о НИР",
        year=2026,
        organization="ООО Тест",
    )
    assert state["work_type"] == "research_report"
    assert state["organization"] == "ООО Тест"


# --- Edge cases -------------------------------------------------------------


def test_default_state_is_valid_starting_point() -> None:
    """Дефолтный state — это валидный исходник для редактора."""
    state = _default_state()
    assert "sections" in state
    assert len(state["sections"]) >= 1
    # Активный раздел в допустимых пределах.
    assert 0 <= state["active_section_index"] < len(state["sections"])


def test_build_document_from_empty_sections_does_not_crash() -> None:
    """Пустой sections — сборка добавляет минимальный раздел и не падает."""
    state = {
        "title": "Минимум",
        "author": "",
        "year": 2026,
        "work_type": "coursework",
        "profile_id": "gost-7.32-2017",
        "sections": [],
    }
    data = _build_document_from_state(state)
    assert isinstance(data, bytes)
    assert data[:2] == b"PK"


def test_build_skips_empty_table_and_list() -> None:
    """Таблица без headers/rows и список без items — пропускаются, не ломая сборку."""
    state = {
        "title": "T",
        "author": "",
        "year": 2026,
        "work_type": "coursework",
        "profile_id": "gost-7.32-2017",
        "sections": [
            {
                "id": "intro",
                "heading": "Введение",
                "blocks": [
                    {"kind": "paragraph", "text": "Текст."},
                    {
                        "kind": "table",
                        "headers": [],
                        "rows": [],
                        "caption": "",
                    },
                    {"kind": "list", "items": [], "ordered": False},
                    {"kind": "formula", "latex": "", "numbered": False},
                ],
            }
        ],
    }
    # Не должно поднимать исключение.
    data = _build_document_from_state(state)
    assert data[:2] == b"PK"


def test_state_round_trip_via_json() -> None:
    """state → json.dumps → json.loads → _build_document_from_state не падает.

    Покрывает функциональность «Скачать сохранение / Загрузить
    сохранение» — JSON-сериализация state должна быть обратимой.
    """
    import json

    state = _default_state()
    state["title"] = "Тест round-trip"
    state["sections"][0]["blocks"].append({"kind": "paragraph", "text": "Текст параграфа."})
    blob = json.dumps(state, ensure_ascii=False).encode("utf-8")
    restored = json.loads(blob.decode("utf-8"))
    assert restored == state
    data = _build_document_from_state(restored)
    assert data[:2] == b"PK"


def test_document_to_state_extracts_bibliography_references() -> None:
    """Раздел «Список ...» в Document превращается в references, не blocks."""
    builder = coursework_template(title="К", author="A", year=2026)
    builder.section("Список использованных источников").reference(
        "Иванов И. И. Программирование. — М. : Наука, 2023. — 320 с."
    )
    document = builder.build()
    state = _document_to_state(document)
    # В шаблоне уже есть пустой «Список ...»; вторым шагом мы добавили
    # ещё один с reference(). Берём любой раздел с непустыми references.
    bibs_with_refs = [
        s for s in state["sections"] if s.get("is_bibliography") and s.get("references")
    ]
    assert bibs_with_refs, "Должна быть хотя бы одна bibliography-секция с references"
    assert "Иванов" in bibs_with_refs[0]["references"][0]


# --- основная надпись (штамп ЕСКД) из state ----------------------------------


def _footer_xml(data: bytes) -> str:
    """Склеить все footerN.xml документа (штамп живёт в одном из них)."""
    import re

    parts: list[str] = []
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        for name in zf.namelist():
            if re.match(r"word/footer\d+\.xml$", name):
                parts.append(zf.read(name).decode("utf-8"))
    return "\n".join(parts)


def test_build_document_from_state_with_title_block() -> None:
    """state['title_block'] (enabled) → штамп-таблица в footer с обозначением."""
    state = {
        "title": "Пояснительная записка",
        "author": "Иванов",
        "year": 2026,
        "profile_id": "gost-7.32-2017",
        "title_block": {
            "enabled": True,
            "form": "form1",
            "designation": "АБВГ.001 ПЗ",
            "organization": "Кафедра ИВТ",
            "roles": [{"role": "Разраб.", "name": "Иванов", "date": ""}],
        },
        "sections": [
            {
                "id": "intro",
                "heading": "Введение",
                "blocks": [{"kind": "paragraph", "text": "Текст."}],
            },
        ],
    }
    data = _build_document_from_state(state)
    footer = _footer_xml(data)
    assert "АБВГ.001 ПЗ" in footer
    assert "Кафедра ИВТ" in footer


def test_build_document_from_state_title_block_disabled() -> None:
    """Выключенный штамп не добавляет таблиц в footer."""
    state = {
        "title": "T",
        "profile_id": "gost-7.32-2017",
        "title_block": {"enabled": False},
        "sections": [
            {"id": "intro", "heading": "Введение", "blocks": [{"kind": "paragraph", "text": "X."}]},
        ],
    }
    data = _build_document_from_state(state)
    assert "w:tbl" not in _footer_xml(data)


# --- авто-добавление ГОСТ/ФЗ из state ----------------------------------------


def test_build_state_autofill_refs_adds_gost() -> None:
    """state['autofill_refs'] → упомянутый ГОСТ попадает в список литературы."""
    state = {
        "title": "Работа",
        "profile_id": "gost-7.32-2017",
        "autofill_refs": True,
        "sections": [
            {
                "id": "intro",
                "heading": "Введение",
                "blocks": [{"kind": "paragraph", "text": "Выполнено по ГОСТ 7.32-2017."}],
            },
            {"id": "bib", "heading": "Список использованных источников", "blocks": []},
        ],
    }
    xml = _docx_xml(_build_document_from_state(state))
    assert "ГОСТ 7.32-2017" in xml
    assert "Стандартинформ" in xml


def test_build_state_without_autofill_refs() -> None:
    """Без флага ГОСТ в список литературы не добавляется автоматически."""
    state = {
        "title": "Работа",
        "profile_id": "gost-7.32-2017",
        "sections": [
            {
                "id": "intro",
                "heading": "Введение",
                "blocks": [{"kind": "paragraph", "text": "Выполнено по ГОСТ 7.32-2017."}],
            },
            {"id": "bib", "heading": "Список использованных источников", "blocks": []},
        ],
    }
    xml = _docx_xml(_build_document_from_state(state))
    assert "Стандартинформ" not in xml
