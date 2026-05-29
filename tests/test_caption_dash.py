"""Тесты I.11 / B.12 — мягкая валидация разделителя подписи (caption.format)."""

from __future__ import annotations

from gostforge.model import (
    Document,
    Figure,
    PageSection,
    Table,
    TextRun,
)
from gostforge.profile import load_profile
from gostforge.validator import validate
from gostforge.validator.checks.figures import expected_caption_dash
from gostforge.validator.engine import registered_checks


def _doc(items: list[object]) -> Document:
    doc = Document()
    doc.page_sections.append(
        PageSection(id="main", name="m", type="main", content=list(items))  # type: ignore[arg-type]
    )
    return doc


def test_checks_registered() -> None:
    assert {"I.11", "B.12"}.issubset(registered_checks())


def test_expected_dash_extraction() -> None:
    assert expected_caption_dash("Рисунок {num} — {title}") == "—"
    assert expected_caption_dash("Таблица {num} - {title}") == "-"
    assert expected_caption_dash("Рисунок {num}. {title}") is None  # без тире


def test_i11_silent_for_em_dash() -> None:
    """Подпись с длинным тире совпадает с профилем (default «—») — тихо."""
    fig = Figure(id="f1", image_path="", caption=[TextRun(text="Рисунок 1 — Схема")])
    profile = load_profile("gost-7.32-2017")
    assert [v for v in validate(_doc([fig]), profile) if v.check_code == "I.11"] == []


def test_i11_warns_for_hyphen() -> None:
    """Дефис вместо предписанного «—» → info-предупреждение I.11."""
    fig = Figure(id="f1", image_path="", caption=[TextRun(text="Рисунок 1 - Схема")])
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(_doc([fig]), profile) if v.check_code == "I.11"]
    assert len(found) == 1
    assert found[0].severity == "info"


def test_i11_silent_for_dot_format() -> None:
    """Точечный формат подписи не матчится разделителем — I.11 молчит (это I.03)."""
    fig = Figure(id="f1", image_path="", caption=[TextRun(text="Рисунок 1. Схема")])
    profile = load_profile("gost-7.32-2017")
    assert [v for v in validate(_doc([fig]), profile) if v.check_code == "I.11"] == []


def test_b12_warns_for_hyphen() -> None:
    """Дефис в подписи таблицы → info-предупреждение B.12."""
    table = Table(id="t1", rows=[["a"]], caption=[TextRun(text="Таблица 1 - Данные")])
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(_doc([table]), profile) if v.check_code == "B.12"]
    assert len(found) == 1
    assert found[0].severity == "info"


def test_b12_silent_for_em_dash() -> None:
    """Длинное тире в подписи таблицы совпадает с профилем — тихо."""
    table = Table(id="t1", rows=[["a"]], caption=[TextRun(text="Таблица 1 — Данные")])
    profile = load_profile("gost-7.32-2017")
    assert [v for v in validate(_doc([table]), profile) if v.check_code == "B.12"] == []
