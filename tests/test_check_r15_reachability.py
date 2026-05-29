"""Тесты R.15 — опциональная HTTP-проверка доступности URL.

Мокаем `_check_url_reachable_http` через monkeypatch, чтобы:
* не делать реальных сетевых запросов в CI;
* проверять разные сценарии (200, 404, timeout, network error);
* убедиться, что R.15 не запускается, если в профиле `enabled=False`
  (поведение по умолчанию).
"""

from __future__ import annotations

import pytest

from gostforge.model import BibliographyEntry, Document
from gostforge.profile import load_profile
from gostforge.validator import validate
from gostforge.validator.checks import references as refs_mod


def _doc_with_urls(*urls: str) -> Document:
    doc = Document()
    for i, url in enumerate(urls, start=1):
        doc.bibliography.append(
            BibliographyEntry(
                id=f"ref:{i}",
                type="article",
                fields={"raw": f"Source {i}", "url": url},
            )
        )
    return doc


def _profile_with_r15(enabled: bool = True, **params: object) -> object:
    """Загрузить дефолтный профиль и переопределить настройки R.15."""
    p = load_profile("gost-7.32-2017")
    cfg = p.checks.get("R.15")
    if cfg is None:
        pytest.skip("R.15 не зарегистрирован в дефолтном профиле")
    cfg.enabled = enabled
    if params:
        cfg.params.update({k: v for k, v in params.items()})
    return p


def test_r15_disabled_by_default_in_default_profile() -> None:
    """R.15 в дефолтном профиле = enabled: false (off-by-default фича)."""
    p = load_profile("gost-7.32-2017")
    cfg = p.checks.get("R.15")
    assert cfg is not None, "R.15 должна быть в профиле как off-by-default"
    assert cfg.enabled is False


def test_r15_skipped_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """Если R.15.enabled=False — HTTP-функция вообще не дёргается."""
    calls: list[str] = []

    def _spy(url: str, timeout: float) -> str | None:
        calls.append(url)
        return None

    monkeypatch.setattr(refs_mod, "_check_url_reachable_http", _spy)

    p = _profile_with_r15(enabled=False)
    doc = _doc_with_urls("https://example.com")
    violations = [v for v in validate(doc, p) if v.check_code == "R.15"]
    assert violations == []
    assert calls == [], "HTTP-функция не должна вызываться при enabled=False"


def test_r15_no_violation_when_url_reachable(monkeypatch: pytest.MonkeyPatch) -> None:
    """Если все URL доступны (None) — нарушений нет."""
    monkeypatch.setattr(refs_mod, "_check_url_reachable_http", lambda url, timeout: None)

    p = _profile_with_r15(enabled=True)
    doc = _doc_with_urls("https://example.com", "https://other.example.com")
    violations = [v for v in validate(doc, p) if v.check_code == "R.15"]
    assert violations == []


def test_r15_violation_for_404(monkeypatch: pytest.MonkeyPatch) -> None:
    """404 → warning с конкретным «HTTP 404»."""
    monkeypatch.setattr(refs_mod, "_check_url_reachable_http", lambda url, timeout: "HTTP 404")

    p = _profile_with_r15(enabled=True)
    doc = _doc_with_urls("https://example.com/dead")
    violations = [v for v in validate(doc, p) if v.check_code == "R.15"]
    assert len(violations) == 1
    v = violations[0]
    assert v.severity == "warning"
    assert "HTTP 404" in v.message
    assert v.details["problem"] == "HTTP 404"


def test_r15_violation_for_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    """Таймаут — отдельное человекочитаемое сообщение."""
    monkeypatch.setattr(
        refs_mod, "_check_url_reachable_http", lambda url, timeout: f"таймаут ({timeout:g} с)"
    )

    p = _profile_with_r15(enabled=True, timeout=2.0)
    doc = _doc_with_urls("https://slow.example.com")
    violations = [v for v in validate(doc, p) if v.check_code == "R.15"]
    assert len(violations) == 1
    assert "таймаут" in violations[0].message


def test_r15_skips_format_broken_url(monkeypatch: pytest.MonkeyPatch) -> None:
    """Форматно-сломанные URL — ответственность R.14, R.15 их пропускает."""
    calls: list[str] = []
    monkeypatch.setattr(
        refs_mod, "_check_url_reachable_http", lambda url, timeout: calls.append(url) or None
    )

    p = _profile_with_r15(enabled=True)
    # «https//example.com» (без двоеточия) — R.14 сработает; R.15 пропускает.
    doc = _doc_with_urls("https//example.com")
    violations = [v for v in validate(doc, p) if v.check_code == "R.15"]
    assert violations == []
    assert calls == [], "HTTP-функция не должна вызываться для невалидного формата"


def test_r15_respects_max_urls_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    """Параметр max_urls ограничивает число HTTP-запросов."""
    calls: list[str] = []
    monkeypatch.setattr(
        refs_mod, "_check_url_reachable_http", lambda url, timeout: calls.append(url) or "HTTP 500"
    )

    p = _profile_with_r15(enabled=True, max_urls=2)
    doc = _doc_with_urls(
        "https://a.example.com",
        "https://b.example.com",
        "https://c.example.com",
        "https://d.example.com",
    )
    violations = [v for v in validate(doc, p) if v.check_code == "R.15"]
    assert len(calls) == 2, f"должно быть ровно 2 запроса, было {len(calls)}"
    assert len(violations) == 2


def test_check_url_reachable_http_handles_404(monkeypatch: pytest.MonkeyPatch) -> None:
    """Реальный HTTPError 404 от urllib → строка «HTTP 404» (через мок urlopen)."""
    import urllib.error
    import urllib.request

    def _boom(req: object, timeout: float = 0) -> object:
        raise urllib.error.HTTPError(
            url="https://example.com/x", code=404, msg="Not Found", hdrs=None, fp=None
        )

    monkeypatch.setattr(urllib.request, "urlopen", _boom)
    result = refs_mod._check_url_reachable_http("https://example.com/x", timeout=2.0)
    assert result == "HTTP 404"


def test_check_url_reachable_http_handles_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    """TimeoutError при urlopen → строка вида «таймаут (Ns)»."""
    import urllib.request

    def _boom(req: object, timeout: float = 0) -> object:
        raise TimeoutError("connection timed out")

    monkeypatch.setattr(urllib.request, "urlopen", _boom)
    result = refs_mod._check_url_reachable_http("https://slow.example.com", timeout=3.0)
    assert result is not None
    assert "таймаут" in result


def test_check_url_reachable_http_handles_urlerror(monkeypatch: pytest.MonkeyPatch) -> None:
    """URLError (DNS / connection refused / etc.) → строка с reason."""
    import urllib.error
    import urllib.request

    def _boom(req: object, timeout: float = 0) -> object:
        raise urllib.error.URLError("Name or service not known")

    monkeypatch.setattr(urllib.request, "urlopen", _boom)
    result = refs_mod._check_url_reachable_http("https://nonexistent.invalid/", timeout=2.0)
    assert result is not None
    assert "сетевая ошибка" in result


def test_check_url_reachable_http_falls_back_to_get_on_405(monkeypatch: pytest.MonkeyPatch) -> None:
    """Если HEAD = 405, делаем GET. Если GET = 200, считаем URL живым."""
    import urllib.error
    import urllib.request

    calls: list[str] = []

    def _urlopen(req: object, timeout: float = 0) -> object:
        method = getattr(req, "get_method", lambda: "GET")()
        calls.append(method)
        if method == "HEAD":
            raise urllib.error.HTTPError(
                url="x", code=405, msg="Method Not Allowed", hdrs=None, fp=None
            )

        class _OK:
            status = 200

            def __enter__(self) -> _OK:
                return self

            def __exit__(self, *args: object) -> None:
                pass

        return _OK()

    monkeypatch.setattr(urllib.request, "urlopen", _urlopen)
    result = refs_mod._check_url_reachable_http("https://example.com/", timeout=2.0)
    assert result is None
    assert calls == ["HEAD", "GET"]
