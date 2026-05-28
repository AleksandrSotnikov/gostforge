"""Тесты схем нумерации рисунков и таблиц (continuous / by_chapter / приложения)."""

from __future__ import annotations

from gostforge.builder.work_builder import WorkBuilder, _parse_appendix_letter
from gostforge.model import Figure, LogicalSection, Table


def _figure_captions(doc: object) -> list[str]:
    captions: list[str] = []
    for ps in doc.page_sections:  # type: ignore[attr-defined]
        for sec in ps.content:
            if isinstance(sec, LogicalSection):
                for c in sec.children:
                    if isinstance(c, Figure):
                        captions.append(c.caption[0].text)
    return captions


def _table_captions(doc: object) -> list[str]:
    captions: list[str] = []
    for ps in doc.page_sections:  # type: ignore[attr-defined]
        for sec in ps.content:
            if isinstance(sec, LogicalSection):
                for c in sec.children:
                    if isinstance(c, Table):
                        captions.append(c.caption[0].text)
    return captions


def test_continuous_numbering_default() -> None:
    """По умолчанию нумерация сквозная: Рисунок 1, 2, 3, ..."""
    doc = (
        WorkBuilder("X")
        .section("Глава 1")
        .figure(image_path="a.png", caption="A")
        .figure(image_path="b.png", caption="B")
        .section("Глава 2")
        .figure(image_path="c.png", caption="C")
        .build()
    )
    assert _figure_captions(doc) == [
        "Рисунок 1 — A",
        "Рисунок 2 — B",
        "Рисунок 3 — C",
    ]


def test_by_chapter_numbering_resets_per_chapter() -> None:
    """В режиме by_chapter счётчик сбрасывается на новой главе."""
    b = WorkBuilder("X")
    b._figure_numbering_mode = "by_chapter"
    doc = (
        b.section("Глава 1")
        .figure(image_path="a.png", caption="A")
        .figure(image_path="b.png", caption="B")
        .section("Глава 2")
        .figure(image_path="c.png", caption="C")
        .build()
    )
    assert _figure_captions(doc) == [
        "Рисунок 1.1 — A",
        "Рисунок 1.2 — B",
        "Рисунок 2.1 — C",
    ]


def test_appendix_letter_numbering_independent_of_mode() -> None:
    """В приложениях нумерация всегда буквенная: А.1, А.2, Б.1, ... ."""
    doc = (
        WorkBuilder("X")
        .section("Введение")
        .figure(image_path="x.png", caption="X")
        .section("Приложение А")
        .figure(image_path="a1.png", caption="A1")
        .figure(image_path="a2.png", caption="A2")
        .section("Приложение Б")
        .figure(image_path="b1.png", caption="B1")
        .build()
    )
    assert _figure_captions(doc) == [
        "Рисунок 1 — X",
        "Рисунок А.1 — A1",
        "Рисунок А.2 — A2",
        "Рисунок Б.1 — B1",
    ]


def test_tables_have_their_own_numbering_mode() -> None:
    """`_table_numbering_mode` не зависит от `_figure_numbering_mode`."""
    b = WorkBuilder("X")
    b._figure_numbering_mode = "continuous"
    b._table_numbering_mode = "by_chapter"
    doc = (
        b.section("Глава 1")
        .figure(image_path="f.png", caption="F")
        .table(headers=["A"], rows=[["x"]], caption="T1")
        .section("Глава 2")
        .table(headers=["A"], rows=[["x"]], caption="T2")
        .build()
    )
    assert _figure_captions(doc) == ["Рисунок 1 — F"]
    assert _table_captions(doc) == ["Таблица 1.1 — T1", "Таблица 2.1 — T2"]


def test_figure_number_field_is_continuous_ordinal() -> None:
    """`Figure.number` хранит сквозной int независимо от схемы (для xref-ов)."""
    b = WorkBuilder("X")
    b._figure_numbering_mode = "by_chapter"
    doc = (
        b.section("Глава 1")
        .figure(image_path="a.png", caption="A")
        .section("Приложение А")
        .figure(image_path="b.png", caption="B")
        .build()
    )
    figs = [
        c
        for ps in doc.page_sections
        for sec in ps.content
        if isinstance(sec, LogicalSection)
        for c in sec.children
        if isinstance(c, Figure)
    ]
    assert [f.number for f in figs] == [1, 2]


def test_custom_caption_format_with_period() -> None:
    """Профильный формат «Рисунок {num}. {title}» (точка) — экспортёр уважает."""
    b = WorkBuilder("X")
    b._figure_caption_format = "Рисунок {num}. {title}"
    doc = b.section("Глава").figure(image_path="a.png", caption="Схема").build()
    assert _figure_captions(doc) == ["Рисунок 1. Схема"]


def test_custom_caption_format_combines_with_chapter_numbering() -> None:
    """Формат + by_chapter работают вместе: «Рисунок 3.1. Title»."""
    b = WorkBuilder("X")
    b._figure_numbering_mode = "by_chapter"
    b._figure_caption_format = "Рисунок {num}. {title}"
    doc = (
        b.section("Глава 1")
        .figure(image_path="a.png", caption="A")
        .section("Глава 2")
        .figure(image_path="b.png", caption="B")
        .figure(image_path="c.png", caption="C")
        .build()
    )
    assert _figure_captions(doc) == [
        "Рисунок 1.1. A",
        "Рисунок 2.1. B",
        "Рисунок 2.2. C",
    ]


def test_table_caption_format_is_independent_from_figure_format() -> None:
    """Формат подписи таблицы независим от формата рисунка."""
    b = WorkBuilder("X")
    b._figure_caption_format = "Fig {num}: {title}"
    b._table_caption_format = "Tbl. {num} – {title}"
    doc = (
        b.section("Глава")
        .figure(image_path="a.png", caption="F")
        .table(headers=["A"], rows=[["x"]], caption="T")
        .build()
    )
    assert _figure_captions(doc) == ["Fig 1: F"]
    assert _table_captions(doc) == ["Tbl. 1 – T"]


def test_parse_appendix_letter() -> None:
    """`_parse_appendix_letter` распознаёт «Приложение X[. ...]» и возвращает X."""
    assert _parse_appendix_letter("Приложение А") == "А"
    assert _parse_appendix_letter("Приложение Б. Дополнительные данные") == "Б"
    assert _parse_appendix_letter("приложение в") == "В"  # регистр игнорируется
    assert _parse_appendix_letter("Глава 1") is None
    assert _parse_appendix_letter("Введение") is None
    # «Приложение» без буквы — не приложение.
    assert _parse_appendix_letter("Приложение") is None


def test_numbering_override_context_manager() -> None:
    """Контекст-менеджер `numbering_override` временно меняет режим нумерации.

    Roadmap Q2/2026: «Per-section override схемы нумерации рисунков/таблиц».
    Документ — глобально continuous; одна глава внутри `with`-блока
    получает by_chapter, после выхода нумерация возвращается к continuous.
    """
    b = WorkBuilder("X")  # default continuous
    b.section("Глава 1").figure(image_path="a.png", caption="A")
    with b.numbering_override(figure="by_chapter"):
        b.section("Глава 2").figure(image_path="b.png", caption="B").figure(
            image_path="c.png", caption="C"
        )
    b.section("Глава 3").figure(image_path="d.png", caption="D")
    doc = b.build()
    # Глава 1 (continuous): «1»; Глава 2 (by_chapter): «2.1», «2.2»;
    # Глава 3 (восстановили continuous): «4» (ordinal не сбрасывается).
    assert _figure_captions(doc) == [
        "Рисунок 1 — A",
        "Рисунок 2.1 — B",
        "Рисунок 2.2 — C",
        "Рисунок 4 — D",
    ]


def test_numbering_override_separately_for_figures_and_tables() -> None:
    """Override-режимы для рисунков и таблиц задаются независимо."""
    b = WorkBuilder("X")
    with b.numbering_override(figure="by_chapter"):
        # table остаётся в default-режиме (continuous).
        b.section("Глава 1").figure(image_path="a.png", caption="A").table(
            headers=["H"], rows=[["v"]], caption="T1"
        )
    assert _figure_captions(b.build()) == ["Рисунок 1.1 — A"]
    # Пересоберём отдельно для таблицы — счётчики у b сбрасываются заново.
    b2 = WorkBuilder("X")
    with b2.numbering_override(table="by_chapter"):
        b2.section("Глава 1").table(headers=["H"], rows=[["v"]], caption="T1").table(
            headers=["H"], rows=[["v"]], caption="T2"
        )
    assert _table_captions(b2.build()) == ["Таблица 1.1 — T1", "Таблица 1.2 — T2"]


def test_numbering_override_restores_previous_mode_on_exit() -> None:
    """После выхода из `with` режим восстанавливается, даже если внутри он менялся."""
    b = WorkBuilder("X")
    b._figure_numbering_mode = "continuous"
    with b.numbering_override(figure="by_chapter"):
        assert b._figure_numbering_mode == "by_chapter"
    assert b._figure_numbering_mode == "continuous"


def test_chapter_label_override_replaces_auto_prefix() -> None:
    """`chapter_label_override` подменяет автоматический счётчик главы.

    Полезно, когда в работе есть «Содержание» / «Введение» как разделы —
    они попадают в счётчик глав. Пользователь задаёт префикс вручную:
    «В.1, В.2» для рисунков во введении или «А.1, А.2» для приложения
    с произвольной буквой.
    """
    b = WorkBuilder("X")
    b._figure_numbering_mode = "by_chapter"
    sec1 = b.section("Введение")  # автоматически получит "1"
    with b.chapter_label_override("В"):
        sec1.figure(image_path="a.png", caption="A")
    sec2 = b.section("Глава 1")  # автоматически получит "2"
    sec2.figure(image_path="b.png", caption="B")
    doc = b.build()
    assert _figure_captions(doc) == [
        "Рисунок В.1 — A",  # override-метка
        "Рисунок 2.1 — B",  # обратно к авто-счётчику
    ]


def test_chapter_label_override_none_is_noop() -> None:
    """`chapter_label_override(None)` не меняет метку — удобно для условного применения."""
    b = WorkBuilder("X")
    b._figure_numbering_mode = "by_chapter"
    sec = b.section("Глава 1")
    with b.chapter_label_override(None):
        sec.figure(image_path="a.png", caption="A")
    assert _figure_captions(b.build()) == ["Рисунок 1.1 — A"]


def test_chapter_label_override_blank_string_is_noop() -> None:
    """Пустая строка / whitespace тоже no-op (UI часто отдаёт ' ')."""
    b = WorkBuilder("X")
    b._figure_numbering_mode = "by_chapter"
    sec = b.section("Глава 1")
    with b.chapter_label_override("   "):
        sec.figure(image_path="a.png", caption="A")
    assert _figure_captions(b.build()) == ["Рисунок 1.1 — A"]


def test_chapter_label_override_restores_on_exit() -> None:
    """Метка восстанавливается после выхода из `with`."""
    b = WorkBuilder("X")
    b._figure_numbering_mode = "by_chapter"
    b.section("Глава 1")  # auto "1"
    saved = b._current_chapter_label
    with b.chapter_label_override("ABC"):
        assert b._current_chapter_label == "ABC"
    assert b._current_chapter_label == saved


def test_chapter_label_override_resets_appendix_flag() -> None:
    """При override метка приложения сбрасывается — иначе by_chapter глюкает."""
    b = WorkBuilder("X")
    b._figure_numbering_mode = "by_chapter"
    b.section("Приложение А")  # автоматически приложение, флаг True
    assert b._is_current_chapter_appendix is True
    with b.chapter_label_override("Z"):
        assert b._is_current_chapter_appendix is False
    # После выхода флаг возвращается.
    assert b._is_current_chapter_appendix is True
