"""Тесты REST endpoints для установки/удаления custom-профилей."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient

from gostforge.api import create_app

_VALID_YAML = 'id: kafedra-api-2026\nname: Кафедра API\nversion: "1.0"\nextends: gost-7.32-2017\n'


@pytest.fixture
def db_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    p = tmp_path / "gostforge.db"
    monkeypatch.setenv("GOSTFORGE_DB_PATH", str(p))
    return p


@pytest.fixture
def client(db_path: Path) -> TestClient:
    return TestClient(create_app())


# --- POST /profiles --------------------------------------------------------


def test_install_returns_record(client: TestClient) -> None:
    r = client.post(
        "/profiles",
        files={"file": ("kafedra.yaml", _VALID_YAML.encode(), "application/x-yaml")},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["profile_id"] == "kafedra-api-2026"
    assert body["name"] == "Кафедра API"
    assert "installed_at" in body


def test_install_then_visible_in_list(client: TestClient) -> None:
    client.post(
        "/profiles",
        files={"file": ("kafedra.yaml", _VALID_YAML.encode(), "application/x-yaml")},
    )
    items = client.get("/profiles").json()
    ids = [p["id"] for p in items]
    assert "kafedra-api-2026" in ids
    # is_custom правильно проставлен.
    kaf = next(p for p in items if p["id"] == "kafedra-api-2026")
    builtin = next(p for p in items if p["id"] == "gost-7.32-2017")
    assert kaf["is_custom"] is True
    assert builtin["is_custom"] is False


def test_install_invalid_yaml_returns_400(client: TestClient) -> None:
    r = client.post(
        "/profiles",
        files={"file": ("bad.yaml", b"description: only this\n", "application/x-yaml")},
    )
    assert r.status_code == 400
    assert "валидацию" in r.json()["detail"]


def test_install_non_yaml_extension_returns_400(client: TestClient) -> None:
    r = client.post(
        "/profiles",
        files={"file": ("bad.txt", _VALID_YAML.encode(), "text/plain")},
    )
    assert r.status_code == 400
    assert "yaml" in r.json()["detail"].lower()


def test_install_non_utf8_returns_400(client: TestClient) -> None:
    """Битый UTF-8 → 400."""
    r = client.post(
        "/profiles",
        files={"file": ("x.yaml", b"\xff\xfe\xfd", "application/x-yaml")},
    )
    assert r.status_code == 400


def test_install_duplicate_returns_409(client: TestClient) -> None:
    files = {"file": ("kafedra.yaml", _VALID_YAML.encode(), "application/x-yaml")}
    client.post("/profiles", files=files)
    files2 = {"file": ("kafedra.yaml", _VALID_YAML.encode(), "application/x-yaml")}
    r = client.post("/profiles", files=files2)
    assert r.status_code == 409


def test_install_overwrite_succeeds(client: TestClient) -> None:
    files = {"file": ("kafedra.yaml", _VALID_YAML.encode(), "application/x-yaml")}
    client.post("/profiles", files=files)
    files2 = {"file": ("kafedra.yaml", _VALID_YAML.encode(), "application/x-yaml")}
    r = client.post("/profiles", files=files2, data={"overwrite": "true"})
    assert r.status_code == 200


# --- DELETE /profiles/{id} -------------------------------------------------


def test_delete_existing_custom_profile(client: TestClient) -> None:
    client.post(
        "/profiles",
        files={"file": ("k.yaml", _VALID_YAML.encode(), "application/x-yaml")},
    )
    r = client.delete("/profiles/kafedra-api-2026")
    assert r.status_code == 200
    assert r.json() == {"deleted": True}
    # И в list его больше нет.
    items = client.get("/profiles").json()
    assert "kafedra-api-2026" not in [p["id"] for p in items]


def test_delete_unknown_profile_returns_404(client: TestClient) -> None:
    r = client.delete("/profiles/does-not-exist")
    assert r.status_code == 404


def test_delete_builtin_profile_returns_404(client: TestClient) -> None:
    """Builtin-профили (в каталоге пакета, не в БД) удалить нельзя."""
    r = client.delete("/profiles/gost-7.32-2017")
    assert r.status_code == 404
    assert "builtin" in r.json()["detail"].lower()


# --- end-to-end: POST /check с custom-профилем -----------------------------


def test_check_works_with_installed_custom_profile(client: TestClient, tmp_path: Path) -> None:
    """Установили профиль → можно сразу прогнать /check с ним."""
    from .conftest import make_docx

    client.post(
        "/profiles",
        files={"file": ("k.yaml", _VALID_YAML.encode(), "application/x-yaml")},
    )

    docx = tmp_path / "sample.docx"
    make_docx(docx, paragraphs=["Текст."])
    r = client.post(
        "/check",
        files={"file": ("sample.docx", docx.read_bytes(), "application/octet-stream")},
        data={"profile_id": "kafedra-api-2026"},
    )
    assert r.status_code == 200
    assert r.json()["profile_id"] == "kafedra-api-2026"
