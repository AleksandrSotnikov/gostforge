"""Тесты WYSIWYG-режима для параграфа (Quill ↔ runs).

Roadmap Q2/2026: «Inline-WYSIWYG для параграфа (требует
streamlit-quill)». Конвертеры HTML ↔ run-dict тестируем чистой
логикой (без Streamlit); UI-смок — через AppTest.
"""

from __future__ import annotations

import pytest


def test_runs_to_html_plain_text() -> None:
    """Один text-run без форматирования → `<p>текст</p>`."""
    from gostforge.web.builder_editor import _runs_to_html

    assert _runs_to_html([{"kind": "text", "text": "Привет"}]) == "<p>Привет</p>"


def test_runs_to_html_with_formatting() -> None:
    """Bold / italic / underline сериализуются в strong / em / u."""
    from gostforge.web.builder_editor import _runs_to_html

    out = _runs_to_html(
        [
            {"kind": "text", "text": "жирный", "bold": True},
            {"kind": "text", "text": " "},
            {"kind": "text", "text": "курсив", "italic": True},
            {"kind": "text", "text": " "},
            {"kind": "text", "text": "подчёркнутый", "underline": True},
        ]
    )
    assert "<strong>жирный</strong>" in out
    assert "<em>курсив</em>" in out
    assert "<u>подчёркнутый</u>" in out


def test_runs_to_html_escapes_html_entities() -> None:
    """HTML-сущности экранируются (защита от инъекции через текст)."""
    from gostforge.web.builder_editor import _runs_to_html

    out = _runs_to_html([{"kind": "text", "text": "<script>alert(1)</script>"}])
    assert "<script>" not in out
    assert "&lt;script&gt;" in out


def test_runs_to_html_newline_becomes_br() -> None:
    """`\\n` внутри текста превращается в `<br>` (Quill это понимает)."""
    from gostforge.web.builder_editor import _runs_to_html

    out = _runs_to_html([{"kind": "text", "text": "первая\nвторая"}])
    assert "<br>" in out
    assert "первая" in out and "вторая" in out


def test_runs_to_html_skips_non_text_runs() -> None:
    """Формулы / xref / citation в WYSIWYG-режим не попадают."""
    from gostforge.web.builder_editor import _runs_to_html

    out = _runs_to_html(
        [
            {"kind": "text", "text": "до"},
            {"kind": "formula", "latex": "x^2"},
            {"kind": "text", "text": "после"},
        ]
    )
    assert "до" in out and "после" in out
    assert "x^2" not in out


def test_html_to_runs_plain_text() -> None:
    """`<p>текст</p>` → один text-run без форматирования."""
    from gostforge.web.builder_editor import _html_to_runs

    runs = _html_to_runs("<p>Привет</p>")
    assert runs == [{"kind": "text", "text": "Привет"}]


def test_html_to_runs_extracts_bold_italic_underline() -> None:
    """strong / em / u восстанавливают bold / italic / underline."""
    from gostforge.web.builder_editor import _html_to_runs

    runs = _html_to_runs("<p><strong>жирный</strong> <em>курсив</em> <u>подчёркнутый</u></p>")
    # 5 run-ов: bold, space, italic, space, underline — но смежные с
    # одинаковым форматом склеиваются. Здесь пять run-ов с разным
    # форматом, поэтому склейки не будет.
    assert any(r.get("bold") and r["text"] == "жирный" for r in runs)
    assert any(r.get("italic") and r["text"] == "курсив" for r in runs)
    assert any(r.get("underline") and r["text"] == "подчёркнутый" for r in runs)


def test_html_to_runs_merges_adjacent_same_format() -> None:
    """Смежные run-ы с идентичным форматом склеиваются."""
    from gostforge.web.builder_editor import _html_to_runs

    runs = _html_to_runs("<p><strong>а</strong><strong>б</strong></p>")
    assert len(runs) == 1
    assert runs[0]["text"] == "аб"
    assert runs[0].get("bold") is True


def test_html_to_runs_handles_br_as_newline() -> None:
    """`<br>` → `\\n` в текущем text-run."""
    from gostforge.web.builder_editor import _html_to_runs

    runs = _html_to_runs("<p>первая<br>вторая</p>")
    text = "".join(r["text"] for r in runs)
    assert text == "первая\nвторая"


def test_html_to_runs_handles_multiple_paragraphs() -> None:
    """Несколько `<p>` → один run с `\\n` между ними."""
    from gostforge.web.builder_editor import _html_to_runs

    runs = _html_to_runs("<p>один</p><p>два</p>")
    text = "".join(r["text"] for r in runs)
    assert text == "один\nдва"


def test_html_to_runs_strips_trailing_quill_newline() -> None:
    """Хвостовой `\\n` (типичный артефакт Quill) убирается."""
    from gostforge.web.builder_editor import _html_to_runs

    runs = _html_to_runs("<p>текст</p><p><br></p>")
    text = "".join(r["text"] for r in runs)
    assert text == "текст"


def test_roundtrip_runs_html_runs() -> None:
    """Round-trip: runs → html → runs восстанавливает форматирование."""
    from gostforge.web.builder_editor import _html_to_runs, _runs_to_html

    original = [
        {"kind": "text", "text": "Обычный "},
        {"kind": "text", "text": "жирный", "bold": True},
        {"kind": "text", "text": " и "},
        {"kind": "text", "text": "курсив", "italic": True},
        {"kind": "text", "text": "."},
    ]
    restored = _html_to_runs(_runs_to_html(original))
    # Финальные тексты совпадают (атрибутики могут немного отличаться по
    # склейке смежных, но содержание и форматирование должно жить).
    assert "Обычный " in restored[0]["text"]
    bolds = [r for r in restored if r.get("bold")]
    italics = [r for r in restored if r.get("italic")]
    assert bolds and bolds[0]["text"] == "жирный"
    assert italics and italics[0]["text"] == "курсив"


def test_paragraph_inline_editor_has_wysiwyg_toggle() -> None:
    """UI-смок: на параграфе виден toggle «WYSIWYG-режим (β)».

    Регресс на случай, если кто-то откатит WYSIWYG-фичу или
    переименует toggle.
    """
    try:
        from streamlit.testing.v1 import AppTest
    except ImportError:
        pytest.skip("AppTest недоступен")

    at = AppTest.from_string("from gostforge.web.pages.builder.content import page\npage()\n")
    at.session_state["builder_state"] = {
        "title": "Тест",
        "year": 2026,
        "profile_id": "gost-7.32-2017",
        "sections": [
            {
                "id": "s1",
                "heading": "Глава",
                "blocks": [{"kind": "paragraph", "text": "Текст"}],
                "subsections": [],
            }
        ],
        "active_section_index": 0,
    }
    at.run(timeout=60)
    assert not at.exception, [str(e) for e in at.exception]
    toggle_labels = [t.label for t in at.toggle]
    assert any("WYSIWYG" in lbl for lbl in toggle_labels), (
        f"Toggle «WYSIWYG-режим» не найден; toggles: {toggle_labels}"
    )
