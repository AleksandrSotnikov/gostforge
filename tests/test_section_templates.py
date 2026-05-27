"""Тесты структурных шаблонов разделов конструктора.

Покрывают добавленные элементы: место под титульный лист (ручная
вставка), приложения с авто-нумерацией букв по ГОСТ и наличие
содержания.
"""

from __future__ import annotations

import pytest

pytest.importorskip("streamlit")

from gostforge.web.builder_editor import (
    _APPENDIX_LETTERS,
    _FRONT_TEMPLATES,
    _GOST_SKELETON_ORDER,
    _SECTION_TEMPLATES,
    _next_appendix_letter,
)


def test_title_template_is_manual_placeholder() -> None:
    assert "title" in _SECTION_TEMPLATES
    label, factory = _SECTION_TEMPLATES["title"]
    assert "итул" in label  # «Титульный лист …»
    section = factory()
    assert section["heading"] == "Титульный лист"
    # Титульник не проверяется нормоконтролем.
    assert section.get("disabled_checks") == ["*"]
    assert section["blocks"], "должен быть параграф-подсказка"


def test_title_inserts_at_front() -> None:
    assert "title" in _FRONT_TEMPLATES


def test_toc_template_present() -> None:
    """Содержание доступно как шаблон и содержит TOC-блок."""
    assert "toc" in _SECTION_TEMPLATES
    section = _SECTION_TEMPLATES["toc"][1]()
    kinds = [b.get("kind") for b in section["blocks"]]
    assert "toc" in kinds


def test_appendix_template_present() -> None:
    assert "appendix" in _SECTION_TEMPLATES
    section = _SECTION_TEMPLATES["appendix"][1]()
    assert section["heading"].startswith("Приложение")


def test_next_appendix_letter_sequence() -> None:
    assert _next_appendix_letter([]) == "А"
    assert _next_appendix_letter([{"heading": "Приложение А"}]) == "Б"
    # Регистр и пробелы не мешают подсчёту.
    assert (
        _next_appendix_letter([{"heading": " приложение А "}, {"heading": "Приложение Б"}]) == "В"
    )
    # Не-приложения не считаются.
    assert _next_appendix_letter([{"heading": "Введение"}]) == "А"


def test_appendix_letters_exclude_gost_forbidden() -> None:
    """ГОСТ 7.32: исключены Ё, З, Й, О, Ч, Ь, Ы, Ъ."""
    for forbidden in "ЁЗЙОЧЬЫЪ":
        assert forbidden not in _APPENDIX_LETTERS
    assert _APPENDIX_LETTERS[0] == "А"


def test_next_appendix_letter_overflow_falls_back_to_number() -> None:
    many = [{"heading": f"Приложение {c}"} for c in _APPENDIX_LETTERS]
    assert _next_appendix_letter(many) == str(len(_APPENDIX_LETTERS) + 1)


def test_gost_skeleton_order_keys_resolve() -> None:
    """Все ключи каркаса по ГОСТ существуют как шаблоны и собираются."""
    assert _GOST_SKELETON_ORDER[0] == "title"  # титульный лист — первым
    for key in _GOST_SKELETON_ORDER:
        assert key in _SECTION_TEMPLATES, key
        section = _SECTION_TEMPLATES[key][1]()
        assert section.get("heading")


def test_gost_skeleton_builds_compliant_structure() -> None:
    """Каркас, собранный из шаблонов, проходит K.01 (структурные элементы
    распознаются) — собираем .docx и проверяем нормоконтролем."""
    import tempfile
    from pathlib import Path

    from gostforge.parser import parse_docx
    from gostforge.profile import load_profile
    from gostforge.validator import validate
    from gostforge.web.builder_editor import _build_document_from_state

    state = {
        "title": "Тест",
        "author": "Иванов И.И.",
        "year": 2026,
        "profile_id": "gost-7.32-2017",
        "sections": [_SECTION_TEMPLATES[k][1]() for k in _GOST_SKELETON_ORDER],
    }
    out = Path(tempfile.mktemp(suffix=".docx"))
    out.write_bytes(_build_document_from_state(state))
    doc = parse_docx(out)
    k01 = [v for v in validate(doc, load_profile("gost-7.32-2017")) if v.check_code == "K.01"]
    assert k01 == [], [v.message for v in k01]
