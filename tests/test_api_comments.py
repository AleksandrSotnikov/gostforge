# ruff: noqa: RUF001, RUF002, RUF003

"""Тесты REST endpoints для комментариев (Фаза 3)."""

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
    return TestClient(create_app())


@pytest.fixture
def submission_id(client: TestClient, tmp_path: Path) -> int:
    """Создать submission через POST /check и вернуть его id."""
    p = tmp_path / "thesis.docx"
    make_docx(p, paragraphs=["Текст"])
    r = client.post(
        "/check",
        files={"file": ("thesis.docx", p.read_bytes(), "application/octet-stream")},
    )
    assert r.status_code == 200
    sid = r.json()["submission_id"]
    assert isinstance(sid, int)
    return sid


# --- POST /submissions/{id}/comments ---------------------------------------


def test_add_comment_returns_record(
    client: TestClient, submission_id: int
) -> None:
    r = client.post(
        f"/submissions/{submission_id}/comments",
        json={"body": "Проверь введение", "author": "prof", "role": "supervisor"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["body"] == "Проверь введение"
    assert body["author"] == "prof"
    assert body["role"] == "supervisor"
    assert body["resolved"] is False
    assert isinstance(body["id"], int)


def test_add_comment_default_role_anonymous(
    client: TestClient, submission_id: int
) -> None:
    r = client.post(
        f"/submissions/{submission_id}/comments", json={"body": "x"}
    )
    assert r.status_code == 200
    assert r.json()["role"] == "anonymous"
    assert r.json()["author"] == ""


def test_add_comment_empty_body_returns_400(
    client: TestClient, submission_id: int
) -> None:
    r = client.post(
        f"/submissions/{submission_id}/comments", json={"body": ""}
    )
    assert r.status_code == 400
    r = client.post(
        f"/submissions/{submission_id}/comments", json={"body": "   "}
    )
    assert r.status_code == 400


def test_add_comment_invalid_role_returns_400(
    client: TestClient, submission_id: int
) -> None:
    r = client.post(
        f"/submissions/{submission_id}/comments",
        json={"body": "x", "role": "admin"},
    )
    assert r.status_code == 400


def test_add_comment_unknown_submission_returns_404(client: TestClient) -> None:
    r = client.post("/submissions/999/comments", json={"body": "x"})
    assert r.status_code == 404


def test_add_comment_missing_body_field_returns_400(
    client: TestClient, submission_id: int
) -> None:
    r = client.post(f"/submissions/{submission_id}/comments", json={})
    assert r.status_code == 400


# --- GET /submissions/{id}/comments ----------------------------------------


def test_list_comments_empty(client: TestClient, submission_id: int) -> None:
    r = client.get(f"/submissions/{submission_id}/comments")
    assert r.status_code == 200
    assert r.json() == []


def test_list_comments_chronological(
    client: TestClient, submission_id: int
) -> None:
    client.post(
        f"/submissions/{submission_id}/comments", json={"body": "первый"}
    )
    client.post(
        f"/submissions/{submission_id}/comments", json={"body": "второй"}
    )
    items = client.get(f"/submissions/{submission_id}/comments").json()
    assert [c["body"] for c in items] == ["первый", "второй"]


def test_list_comments_filter_resolved(
    client: TestClient, submission_id: int
) -> None:
    r1 = client.post(
        f"/submissions/{submission_id}/comments", json={"body": "open"}
    )
    r2 = client.post(
        f"/submissions/{submission_id}/comments", json={"body": "closed"}
    )
    client.patch(f"/comments/{r2.json()['id']}/resolve")
    only_open = client.get(
        f"/submissions/{submission_id}/comments?include_resolved=false"
    ).json()
    assert len(only_open) == 1
    assert only_open[0]["id"] == r1.json()["id"]


def test_list_comments_unknown_submission_returns_empty_list(
    client: TestClient,
) -> None:
    """Нет 404 — пустой список, как при пустом submission_id."""
    r = client.get("/submissions/999/comments")
    assert r.status_code == 200
    assert r.json() == []


# --- PATCH /comments/{id}/resolve ------------------------------------------


def test_resolve_comment_default_marks_resolved(
    client: TestClient, submission_id: int
) -> None:
    cid = client.post(
        f"/submissions/{submission_id}/comments", json={"body": "x"}
    ).json()["id"]
    r = client.patch(f"/comments/{cid}/resolve")
    assert r.status_code == 200
    assert r.json()["resolved"] is True


def test_resolve_comment_explicit_false_unmarks(
    client: TestClient, submission_id: int
) -> None:
    cid = client.post(
        f"/submissions/{submission_id}/comments", json={"body": "x"}
    ).json()["id"]
    client.patch(f"/comments/{cid}/resolve")
    r = client.patch(f"/comments/{cid}/resolve", json={"resolved": False})
    assert r.json()["resolved"] is False


def test_resolve_unknown_comment_returns_404(client: TestClient) -> None:
    r = client.patch("/comments/999/resolve")
    assert r.status_code == 404


# --- DELETE /comments/{id} -------------------------------------------------


def test_delete_comment(client: TestClient, submission_id: int) -> None:
    cid = client.post(
        f"/submissions/{submission_id}/comments", json={"body": "x"}
    ).json()["id"]
    r = client.delete(f"/comments/{cid}")
    assert r.status_code == 200
    assert r.json() == {"deleted": True}
    items = client.get(f"/submissions/{submission_id}/comments").json()
    assert items == []


def test_delete_unknown_comment_returns_404(client: TestClient) -> None:
    r = client.delete("/comments/999")
    assert r.status_code == 404


# --- unresolved_comments в GET /submissions/{id} ---------------------------


def test_submission_detail_includes_unresolved_count(
    client: TestClient, submission_id: int
) -> None:
    client.post(
        f"/submissions/{submission_id}/comments", json={"body": "open1"}
    )
    r2 = client.post(
        f"/submissions/{submission_id}/comments", json={"body": "resolved-one"}
    )
    client.patch(f"/comments/{r2.json()['id']}/resolve")
    r = client.get(f"/submissions/{submission_id}")
    assert r.json()["unresolved_comments"] == 1


def test_submission_detail_unresolved_zero_when_no_comments(
    client: TestClient, submission_id: int
) -> None:
    r = client.get(f"/submissions/{submission_id}")
    assert r.json()["unresolved_comments"] == 0


# --- CASCADE ----------------------------------------------------------------


def test_delete_submission_cascades_to_comments(
    client: TestClient, submission_id: int
) -> None:
    """Удаление submission уносит свои комментарии (ON DELETE CASCADE)."""
    cid = client.post(
        f"/submissions/{submission_id}/comments", json={"body": "x"}
    ).json()["id"]
    client.delete(f"/submissions/{submission_id}")
    # Комментарий больше не существует.
    assert client.delete(f"/comments/{cid}").status_code == 404
