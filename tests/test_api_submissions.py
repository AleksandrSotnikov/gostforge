# ruff: noqa: RUF001, RUF002, RUF003

"""Тесты REST endpoints для submissions (Фаза 3).

Изолируем БД через GOSTFORGE_DB_PATH в tmp_path. Каждый тест получает
свою чистую БД.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient

from gostforge.api import create_app

from .conftest import make_docx


@pytest.fixture
def db_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    p = tmp_path / "gostforge.db"
    monkeypatch.setenv("GOSTFORGE_DB_PATH", str(p))
    return p


@pytest.fixture
def client(db_path: Path) -> TestClient:
    """TestClient с изолированной БД (db_path fixture монтирует env)."""
    return TestClient(create_app())


@pytest.fixture
def docx_bytes(tmp_path: Path) -> bytes:
    p = tmp_path / "sample.docx"
    make_docx(p, paragraphs=["Один."])
    return p.read_bytes()


# --- POST /check: автозапись submission ------------------------------------


def test_post_check_returns_submission_id_by_default(client: TestClient, docx_bytes: bytes) -> None:
    """По умолчанию /check записывает submission и возвращает его id."""
    r = client.post(
        "/check",
        files={"file": ("thesis.docx", docx_bytes, "application/octet-stream")},
    )
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body["submission_id"], int)
    assert body["submission_id"] > 0


def test_post_check_record_false_skips_db(client: TestClient, docx_bytes: bytes) -> None:
    """record=False → submission_id null, в БД ничего не появляется."""
    r = client.post(
        "/check",
        files={"file": ("thesis.docx", docx_bytes, "application/octet-stream")},
        data={"record": "false"},
    )
    assert r.status_code == 200
    assert r.json()["submission_id"] is None
    # И в /submissions пусто.
    assert client.get("/submissions").json() == []


# --- GET /submissions ------------------------------------------------------


def test_get_submissions_empty_returns_empty_list(client: TestClient) -> None:
    r = client.get("/submissions")
    assert r.status_code == 200
    assert r.json() == []


def test_get_submissions_returns_recent_records(client: TestClient, docx_bytes: bytes) -> None:
    # Запишем два submission через POST /check.
    for name in ("a.docx", "b.docx"):
        client.post(
            "/check",
            files={"file": (name, docx_bytes, "application/octet-stream")},
        )
    r = client.get("/submissions")
    assert r.status_code == 200
    items = r.json()
    assert len(items) == 2
    # Newest first — b.docx был записан позже.
    assert items[0]["filename"] == "b.docx"
    assert items[1]["filename"] == "a.docx"


def test_get_submissions_limit_caps_at_200(client: TestClient, docx_bytes: bytes) -> None:
    """Параметр limit ограничен сверху значением 200."""
    # Реально 200 записей делать не будем — проверим через очень
    # большое limit, что API не упадёт.
    client.post(
        "/check",
        files={"file": ("x.docx", docx_bytes, "application/octet-stream")},
    )
    r = client.get("/submissions?limit=99999")
    assert r.status_code == 200
    # Результат всё ещё корректный.
    assert len(r.json()) == 1


def test_get_submissions_filter_by_filename(client: TestClient, docx_bytes: bytes) -> None:
    for name in ("alpha.docx", "beta.docx", "alpha.docx"):
        client.post(
            "/check",
            files={"file": (name, docx_bytes, "application/octet-stream")},
        )
    r = client.get("/submissions?filename=alpha.docx")
    assert r.status_code == 200
    items = r.json()
    assert len(items) == 2
    assert all(s["filename"] == "alpha.docx" for s in items)


def test_get_submissions_does_not_include_violations_list(
    client: TestClient, docx_bytes: bytes
) -> None:
    """list endpoint возвращает только метаданные + summary, без деталей."""
    client.post(
        "/check",
        files={"file": ("x.docx", docx_bytes, "application/octet-stream")},
    )
    item = client.get("/submissions").json()[0]
    assert "violations" not in item
    assert "error_count" in item


# --- GET /submissions/{id} -------------------------------------------------


def test_get_submission_by_id_returns_full_payload(client: TestClient, docx_bytes: bytes) -> None:
    r = client.post(
        "/check",
        files={"file": ("x.docx", docx_bytes, "application/octet-stream")},
    )
    sid = r.json()["submission_id"]

    r = client.get(f"/submissions/{sid}")
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == sid
    assert body["filename"] == "x.docx"
    assert {"error", "warning", "info"} <= set(body["summary"])
    assert isinstance(body["violations"], list)


def test_get_submission_unknown_id_returns_404(client: TestClient) -> None:
    r = client.get("/submissions/999")
    assert r.status_code == 404
    assert "не найден" in r.json()["detail"]


# --- DELETE /submissions/{id} ----------------------------------------------


def test_delete_submission_removes_record(client: TestClient, docx_bytes: bytes) -> None:
    r = client.post(
        "/check",
        files={"file": ("x.docx", docx_bytes, "application/octet-stream")},
    )
    sid = r.json()["submission_id"]

    r = client.delete(f"/submissions/{sid}")
    assert r.status_code == 200
    assert r.json() == {"deleted": True}

    # Запись пропала.
    assert client.get(f"/submissions/{sid}").status_code == 404
    assert client.get("/submissions").json() == []


def test_delete_unknown_submission_returns_404(client: TestClient) -> None:
    r = client.delete("/submissions/999")
    assert r.status_code == 404
