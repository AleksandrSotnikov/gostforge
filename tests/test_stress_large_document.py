"""Стресс-тест: крупный документ проходит build → export → parse → validate.

Проверяет, что пайплайн не деградирует и не падает на большом документе
(сотни разделов / тысячи абзацев — порядка 500+ страниц). Тест помечен
``slow``: запускается в общем прогоне, но при отладке его можно
исключить через ``-m 'not slow'``.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from gostforge.builder import work
from gostforge.exporter import export_docx
from gostforge.model import LogicalSection
from gostforge.parser import parse_docx
from gostforge.profile import load_profile
from gostforge.validator import validate

# ~120 разделов × ~20 абзацев ≈ 2400 абзацев — при ~5 абзацах на страницу
# это уверенно за 500 страниц печатного текста.
_N_SECTIONS = 120
_N_PARAGRAPHS = 20
_PARAGRAPH = (
    "Настоящий абзац содержит достаточный объём текста для имитации "
    "реальной страницы работы и проверки производительности парсера и "
    "экспортёра на большом документе по ГОСТ 7.32-2017. "
)


@pytest.mark.slow
def test_large_document_roundtrip(tmp_path: Path) -> None:
    builder = work("Большой отчёт", author="Иванов И. И.", year=2026)
    for s in range(_N_SECTIONS):
        sec = builder.section(f"Раздел {s + 1}")
        for p in range(_N_PARAGRAPHS):
            sec.paragraph(f"{_PARAGRAPH}(раздел {s + 1}, абзац {p + 1})")

    t0 = time.perf_counter()
    document = builder.build()
    build_time = time.perf_counter() - t0
    # Все разделы на месте.
    top = [c for c in document.page_sections[0].content if isinstance(c, LogicalSection)]
    assert len(top) == _N_SECTIONS

    out = tmp_path / "large.docx"
    t0 = time.perf_counter()
    export_docx(document, load_profile("gost-7.32-2017"), out)
    export_time = time.perf_counter() - t0
    assert out.exists() and out.stat().st_size > 0

    t0 = time.perf_counter()
    reparsed = parse_docx(out)
    parse_time = time.perf_counter() - t0
    reparsed_sections = [
        c for c in reparsed.page_sections[0].content if isinstance(c, LogicalSection)
    ]
    assert len(reparsed_sections) == _N_SECTIONS

    t0 = time.perf_counter()
    violations = validate(reparsed, load_profile("gost-7.32-2017"))
    validate_time = time.perf_counter() - t0
    assert isinstance(violations, list)

    # Грубая защита от катастрофической деградации (не бенчмарк).
    # Пороги щедрые — важно поймать O(n^2)/зависания, а не микросекунды.
    assert build_time < 30, f"build слишком медленный: {build_time:.1f}s"
    assert export_time < 60, f"export слишком медленный: {export_time:.1f}s"
    assert parse_time < 60, f"parse слишком медленный: {parse_time:.1f}s"
    assert validate_time < 60, f"validate слишком медленный: {validate_time:.1f}s"
