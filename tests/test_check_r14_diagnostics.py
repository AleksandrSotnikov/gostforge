"""Тесты диагностических хелперов R.14: конкретные сообщения об ошибках в DOI/URL.

Раньше R.14 говорила общее «не соответствует формату». Теперь
указывает: лишние пробелы, DOI обёрнут в URL, опечатка в схеме,
отсутствие префикса `10.` и т. п.
"""

from __future__ import annotations

import pytest

from gostforge.model import BibliographyEntry, Document
from gostforge.profile.schema import load_profile
from gostforge.validator import validate
from gostforge.validator.checks.references import (
    _diagnose_doi_format,
    _diagnose_url_format,
)

# --- DOI diagnostics ---


@pytest.mark.parametrize(
    "doi",
    [
        "10.1234/abc",
        "10.12345/longer-suffix-123",
        "10.1000/xyz",
    ],
)
def test_doi_valid(doi: str) -> None:
    """Валидный DOI → None (нет проблемы)."""
    assert _diagnose_doi_format(doi) is None


def test_doi_leading_trailing_whitespace() -> None:
    assert "пробелы" in (_diagnose_doi_format(" 10.1234/abc") or "")
    assert "пробелы" in (_diagnose_doi_format("10.1234/abc ") or "")


def test_doi_internal_whitespace() -> None:
    assert "табы" in (_diagnose_doi_format("10.1234/ab c") or "")


@pytest.mark.parametrize(
    "doi",
    [
        "https://doi.org/10.1234/abc",
        "http://doi.org/10.1234/abc",
        "https://dx.doi.org/10.1234/abc",
        "doi.org/10.1234/abc",
    ],
)
def test_doi_wrapped_in_url(doi: str) -> None:
    """DOI скопирован как URL — указываем явно."""
    msg = _diagnose_doi_format(doi)
    assert msg is not None
    assert "обёрнут" in msg or "URL" in msg


def test_doi_missing_prefix() -> None:
    assert "10." in (_diagnose_doi_format("1234/abc") or "")


def test_doi_no_suffix_slash() -> None:
    assert "/" in (_diagnose_doi_format("10.1234abc") or "")


# --- URL diagnostics ---


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com",
        "http://example.com/path",
        "https://example.com/long/path?query=1",
        "HTTPS://EXAMPLE.COM",
    ],
)
def test_url_valid(url: str) -> None:
    assert _diagnose_url_format(url) is None


def test_url_whitespace_diagnostics() -> None:
    assert "пробелы" in (_diagnose_url_format(" https://x.com") or "")
    assert "табы" in (_diagnose_url_format("https://x.\tcom") or "")


@pytest.mark.parametrize(
    "url,expected_word",
    [
        ("https//example.com", "двоеточие"),
        ("https:/example.com", "слэш"),
        ("https;//example.com", "точка"),
        ("htp://example.com", "htp"),
        ("htps://example.com", "htps"),
    ],
)
def test_url_specific_typo_diagnosed(url: str, expected_word: str) -> None:
    """Конкретная опечатка — конкретное сообщение."""
    msg = _diagnose_url_format(url)
    assert msg is not None
    assert expected_word in msg, f"Сообщение «{msg}» не содержит «{expected_word}»"


def test_url_missing_scheme() -> None:
    msg = _diagnose_url_format("www.example.com")
    assert msg is not None
    assert "http" in msg


# --- Integration: R.14 через validate ---


def _doc_with_bib(*, doi: str | None = None, url: str | None = None) -> Document:
    fields: dict[str, str] = {"raw": "Source"}
    if doi is not None:
        fields["doi"] = doi
    if url is not None:
        fields["url"] = url
    entry = BibliographyEntry(id="ref:1", type="article", fields=fields)
    doc = Document()
    doc.bibliography.append(entry)
    return doc


def test_r14_violation_contains_concrete_diagnostic() -> None:
    """R.14 violation.message содержит конкретную причину, не общее «не соответствует»."""
    profile = load_profile("gost-7.32-2017")
    doc = _doc_with_bib(doi="https://doi.org/10.1234/abc")
    violations = [v for v in validate(doc, profile) if v.check_code == "R.14"]
    assert violations, "R.14 должна сработать"
    assert "обёрнут" in violations[0].message
    # details содержат problem-поле.
    assert "problem" in violations[0].details


def test_r14_valid_doi_no_violations() -> None:
    profile = load_profile("gost-7.32-2017")
    doc = _doc_with_bib(doi="10.1234/abc", url="https://example.com")
    violations = [v for v in validate(doc, profile) if v.check_code == "R.14"]
    assert violations == []


def test_r14_typo_in_url_diagnosed() -> None:
    profile = load_profile("gost-7.32-2017")
    doc = _doc_with_bib(url="https//example.com")
    violations = [v for v in validate(doc, profile) if v.check_code == "R.14"]
    assert violations, "должна сработать"
    assert "двоеточие" in violations[0].message
