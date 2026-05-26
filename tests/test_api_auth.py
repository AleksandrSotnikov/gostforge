# ruff: noqa: RUF001, RUF002, RUF003

"""Тесты API-key middleware (Фаза 3, итерация 2).

env GOSTFORGE_API_KEYS включает обязательную проверку заголовка
X-API-Key для всех путей, кроме /health и /docs/openapi.json.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient

from gostforge.api import create_app

from .conftest import make_docx


@pytest.fixture
def docx_bytes(tmp_path: Path) -> bytes:
    p = tmp_path / "sample.docx"
    make_docx(p, paragraphs=["Один."])
    return p.read_bytes()


def _client_with_keys(monkeypatch: pytest.MonkeyPatch, *keys: str) -> TestClient:
    """Создать TestClient с включенным auth (env-переменная задана)."""
    monkeypatch.setenv("GOSTFORGE_API_KEYS", ",".join(keys))
    return TestClient(create_app())


# --- auth выключен (default) -----------------------------------------------


def test_no_env_means_auth_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """Если GOSTFORGE_API_KEYS пустой/не задан — все запросы анонимны."""
    monkeypatch.delenv("GOSTFORGE_API_KEYS", raising=False)
    client = TestClient(create_app())
    assert client.get("/health").status_code == 200
    assert client.get("/checks").status_code == 200


def test_empty_env_means_auth_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GOSTFORGE_API_KEYS", "")
    client = TestClient(create_app())
    assert client.get("/checks").status_code == 200


def test_short_keys_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ключи короче 8 символов считаются опечаткой и игнорируются."""
    monkeypatch.setenv("GOSTFORGE_API_KEYS", "abc,short,xy")
    client = TestClient(create_app())
    # Никаких валидных ключей → auth выключен.
    assert client.get("/checks").status_code == 200


# --- auth включён ----------------------------------------------------------


def test_health_accessible_without_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """liveness-проверка должна работать для мониторинга без секретов."""
    client = _client_with_keys(monkeypatch, "super-secret-1234")
    assert client.get("/health").status_code == 200


def test_openapi_docs_accessible_without_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """OpenAPI-схема должна быть доступна — для интеграторов и Swagger UI."""
    client = _client_with_keys(monkeypatch, "super-secret-1234")
    assert client.get("/openapi.json").status_code == 200
    assert client.get("/docs").status_code == 200


def test_protected_endpoint_without_key_returns_401(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client_with_keys(monkeypatch, "super-secret-1234")
    r = client.get("/checks")
    assert r.status_code == 401
    body = r.json()
    assert body["error"] == "unauthorized"


def test_protected_endpoint_with_wrong_key_returns_401(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client_with_keys(monkeypatch, "super-secret-1234")
    r = client.get("/checks", headers={"X-API-Key": "wrong-key-123"})
    assert r.status_code == 401


def test_protected_endpoint_with_valid_key_passes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client_with_keys(monkeypatch, "super-secret-1234")
    r = client.get("/checks", headers={"X-API-Key": "super-secret-1234"})
    assert r.status_code == 200
    assert len(r.json()) >= 100


def test_multiple_keys_supported(monkeypatch: pytest.MonkeyPatch) -> None:
    """Несколько ключей (для разных потребителей) — comma-separated."""
    client = _client_with_keys(monkeypatch, "key-alpha-001", "key-beta-002")
    assert client.get("/checks", headers={"X-API-Key": "key-alpha-001"}).status_code == 200
    assert client.get("/checks", headers={"X-API-Key": "key-beta-002"}).status_code == 200
    assert client.get("/checks", headers={"X-API-Key": "unknown"}).status_code == 401


def test_post_check_with_auth(monkeypatch: pytest.MonkeyPatch, docx_bytes: bytes) -> None:
    """POST /check тоже требует X-API-Key при включённом auth."""
    client = _client_with_keys(monkeypatch, "super-secret-1234")
    files = {"file": ("s.docx", docx_bytes, "application/octet-stream")}
    r = client.post("/check", files=files)
    assert r.status_code == 401
    r = client.post("/check", files=files, headers={"X-API-Key": "super-secret-1234"})
    assert r.status_code == 200


def test_case_insensitive_header_name(monkeypatch: pytest.MonkeyPatch) -> None:
    """HTTP-заголовки регистронезависимы, middleware не должен спотыкаться."""
    client = _client_with_keys(monkeypatch, "super-secret-1234")
    for variant in ("X-API-Key", "x-api-key", "X-Api-Key"):
        r = client.get("/checks", headers={variant: "super-secret-1234"})
        assert r.status_code == 200, variant
