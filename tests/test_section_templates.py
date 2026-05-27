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
