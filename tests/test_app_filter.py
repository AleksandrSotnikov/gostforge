"""Тесты для чистого helper'а фильтрации нарушений в веб-интерфейсе."""

from __future__ import annotations

import pytest

pytest.importorskip("streamlit")

from gostforge.validator.engine import Violation
from gostforge.web.app import _filter_violations


def _make_violations() -> list[Violation]:
    """Набор нарушений разных категорий и серьёзностей для тестов."""
    return [
        Violation(check_code="F.01", severity="error", message="поля"),
        Violation(check_code="T.14", severity="warning", message="двойной пробел"),
        Violation(check_code="T.08", severity="info", message="кавычки"),
        Violation(check_code="S.03", severity="error", message="заголовок"),
    ]


def test_filter_by_severity_keeps_only_error() -> None:
    """severities={'error'} оставляет только нарушения с severity == error."""
    violations = _make_violations()
    result = _filter_violations(violations, {"error"}, set())
    assert {v.check_code for v in result} == {"F.01", "S.03"}
    assert all(v.severity == "error" for v in result)


def test_filter_by_category_keeps_only_t() -> None:
    """categories={'T'} оставляет только коды T.*."""
    violations = _make_violations()
    result = _filter_violations(violations, set(), {"T"})
    assert {v.check_code for v in result} == {"T.14", "T.08"}


def test_empty_sets_return_all() -> None:
    """Пустые множества → возвращается исходный список целиком."""
    violations = _make_violations()
    result = _filter_violations(violations, set(), set())
    assert result == violations


def test_combination_severity_and_category() -> None:
    """Комбинация severity + category отбирает по обоим измерениям."""
    violations = _make_violations()
    # error И категория T: T.14 (warning) и T.08 (info) не проходят по severity,
    # F.01/S.03 — error, но не категории T → итог пуст.
    assert _filter_violations(violations, {"error"}, {"T"}) == []
    # error И категория F → только F.01.
    result = _filter_violations(violations, {"error"}, {"F"})
    assert [v.check_code for v in result] == ["F.01"]
