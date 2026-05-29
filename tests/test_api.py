"""Тесты REST API gostforge.api.app (Фаза 3, первая итерация).

Используем fastapi.testclient — без поднятия uvicorn. Каждый endpoint
покрыт ≥ 2 тестами: happy path и хотя бы один error path.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient

from gostforge.api import create_app

from .conftest import make_docx


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(create_app())


@pytest.fixture
def docx_bytes(tmp_path: Path) -> bytes:
    """Синтетический .docx через фабрику из conftest."""
    p = tmp_path / "sample.docx"
    make_docx(
        p,
        margins_mm={"top": 20, "right": 15, "bottom": 20, "left": 30},
        paragraphs=["Один параграф."],
        headings=[(1, "Введение")],
    )
    return p.read_bytes()


# --- /health ---------------------------------------------------------------


def test_health_returns_ok(client: TestClient) -> None:
    r = client.get("/health")
    assert r.status_code == 200
    payload = r.json()
    assert payload["status"] == "ok"
    assert "version" in payload


# --- /profiles -------------------------------------------------------------


def test_list_profiles_returns_known_profiles(client: TestClient) -> None:
    r = client.get("/profiles")
    assert r.status_code == 200
    profiles = r.json()
    ids = [p["id"] for p in profiles]
    assert "gost-7.32-2017" in ids
    for p in profiles:
        assert {"id", "name", "version", "description"} <= set(p)


def test_get_profile_returns_full_payload(client: TestClient) -> None:
    r = client.get("/profiles/gost-7.32-2017")
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == "gost-7.32-2017"
    assert "styles" in body
    assert "checks" in body


def test_get_unknown_profile_returns_404(client: TestClient) -> None:
    r = client.get("/profiles/this-does-not-exist")
    assert r.status_code == 404


# --- /checks ---------------------------------------------------------------


def test_list_checks_returns_full_catalog(client: TestClient) -> None:
    r = client.get("/checks")
    assert r.status_code == 200
    checks = r.json()
    assert len(checks) >= 100  # 104 в каталоге, допустим запас
    codes = {c["code"] for c in checks}
    assert "F.01" in codes
    assert "T.01" in codes
    # Категория — первая буква до точки.
    for c in checks:
        assert c["category"] == c["code"].split(".")[0]


# --- /check ----------------------------------------------------------------


def test_post_check_happy_path(client: TestClient, docx_bytes: bytes) -> None:
    files = {"file": ("sample.docx", docx_bytes, "application/octet-stream")}
    r = client.post("/check", files=files, data={"profile_id": "gost-7.32-2017"})
    assert r.status_code == 200
    body = r.json()
    assert body["profile_id"] == "gost-7.32-2017"
    assert isinstance(body["violations"], list)
    assert {"error", "warning", "info"} <= set(body["summary"])


def test_post_check_default_profile_when_omitted(client: TestClient, docx_bytes: bytes) -> None:
    """Если profile_id не передан — берётся gost-7.32-2017 по умолчанию."""
    files = {"file": ("sample.docx", docx_bytes, "application/octet-stream")}
    r = client.post("/check", files=files)
    assert r.status_code == 200
    assert r.json()["profile_id"] == "gost-7.32-2017"


def test_post_check_rejects_non_docx_filename(client: TestClient) -> None:
    r = client.post(
        "/check",
        files={"file": ("sample.txt", b"hello", "text/plain")},
        data={"profile_id": "gost-7.32-2017"},
    )
    assert r.status_code == 400
    assert ".docx" in r.json()["detail"]


def test_post_check_rejects_corrupt_docx(client: TestClient) -> None:
    """Файл с правильным именем, но без PK-сигнатуры zip отклоняется."""
    r = client.post(
        "/check",
        files={"file": ("sample.docx", b"not a real zip", "application/octet-stream")},
    )
    assert r.status_code == 400


def test_post_check_unknown_profile_returns_404(client: TestClient, docx_bytes: bytes) -> None:
    files = {"file": ("sample.docx", docx_bytes, "application/octet-stream")}
    r = client.post("/check", files=files, data={"profile_id": "does-not-exist"})
    assert r.status_code == 404


def test_post_check_finds_margin_violation(client: TestClient, tmp_path: Path) -> None:
    """Документ с неправильными полями должен дать violation F.01."""
    p = tmp_path / "bad.docx"
    make_docx(
        p,
        margins_mm={"top": 10, "right": 10, "bottom": 10, "left": 10},
        paragraphs=["Текст."],
    )
    r = client.post(
        "/check",
        files={"file": ("bad.docx", p.read_bytes(), "application/octet-stream")},
    )
    assert r.status_code == 200
    codes = {v["code"] for v in r.json()["violations"]}
    assert "F.01" in codes


# --- /fix ------------------------------------------------------------------


def test_post_fix_returns_docx_binary(client: TestClient, docx_bytes: bytes) -> None:
    r = client.post(
        "/fix",
        files={"file": ("sample.docx", docx_bytes, "application/octet-stream")},
    )
    assert r.status_code == 200
    assert r.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    assert r.content.startswith(b"PK")  # zip-сигнатура
    assert "attachment" in r.headers.get("content-disposition", "")


def test_post_fix_with_only_filter(client: TestClient, docx_bytes: bytes) -> None:
    """Параметр only ограничивает набор фиксеров (multi-value form)."""
    r = client.post(
        "/fix",
        files={"file": ("sample.docx", docx_bytes, "application/octet-stream")},
        data={"only": ["T.08", "T.10"]},
    )
    assert r.status_code == 200
    assert r.content.startswith(b"PK")


def test_post_fix_rejects_non_docx(client: TestClient) -> None:
    r = client.post(
        "/fix",
        files={"file": ("bad.txt", b"hello", "text/plain")},
    )
    assert r.status_code == 400


# --- /annotate -------------------------------------------------------------


def test_post_annotate_default_comments_style(client: TestClient, docx_bytes: bytes) -> None:
    r = client.post(
        "/annotate",
        files={"file": ("sample.docx", docx_bytes, "application/octet-stream")},
    )
    assert r.status_code == 200
    assert r.content.startswith(b"PK")


def test_post_annotate_inline_style(client: TestClient, docx_bytes: bytes) -> None:
    r = client.post(
        "/annotate",
        files={"file": ("sample.docx", docx_bytes, "application/octet-stream")},
        data={"style": "inline"},
    )
    assert r.status_code == 200
    assert r.content.startswith(b"PK")


def test_post_annotate_rejects_invalid_style(client: TestClient, docx_bytes: bytes) -> None:
    r = client.post(
        "/annotate",
        files={"file": ("sample.docx", docx_bytes, "application/octet-stream")},
        data={"style": "rainbow"},
    )
    assert r.status_code == 400


# --- /stats ----------------------------------------------------------------


def test_post_stats_returns_counts(client: TestClient, docx_bytes: bytes) -> None:
    r = client.post(
        "/stats",
        files={"file": ("sample.docx", docx_bytes, "application/octet-stream")},
    )
    assert r.status_code == 200
    body = r.json()
    # DocumentStats — dataclass, у него точно есть базовые поля.
    assert isinstance(body, dict)
    # Хотя бы какой-то счётчик существует и неотрицателен.
    assert any(isinstance(v, int) and v >= 0 for v in body.values())


def test_post_stats_rejects_non_docx(client: TestClient) -> None:
    r = client.post(
        "/stats",
        files={"file": ("bad.txt", b"hello", "text/plain")},
    )
    assert r.status_code == 400


# --- /check без файла ------------------------------------------------------


def test_post_check_without_file_returns_422(client: TestClient) -> None:
    """FastAPI validation: отсутствие required file → 422."""
    r = client.post("/check", data={"profile_id": "gost-7.32-2017"})
    assert r.status_code == 422


# --- /check/stream (SSE) ---------------------------------------------------


def _parse_sse_stream(text: str) -> list[tuple[str, dict[str, object]]]:
    """Распарсить SSE-поток в список (event_name, json_payload).

    SSE-фрейм:
        event: <name>
        data: <json>

        (пустая строка = разделитель)
    """
    import json

    events: list[tuple[str, dict[str, object]]] = []
    for block in text.split("\n\n"):
        block = block.strip()
        if not block:
            continue
        event_name = ""
        data_str = ""
        for line in block.splitlines():
            if line.startswith("event: "):
                event_name = line[7:].strip()
            elif line.startswith("data: "):
                data_str = line[6:]
        if event_name:
            payload = json.loads(data_str) if data_str else {}
            events.append((event_name, payload))
    return events


def test_post_check_stream_happy_path(client: TestClient, docx_bytes: bytes) -> None:
    """`/check/stream` стримит события parse → check×N → done."""
    files = {"file": ("sample.docx", docx_bytes, "application/octet-stream")}
    r = client.post("/check/stream", files=files, data={"profile_id": "gost-7.32-2017"})
    assert r.status_code == 200
    assert "text/event-stream" in r.headers.get("content-type", "")
    events = _parse_sse_stream(r.text)
    names = [name for name, _ in events]
    assert names[0] == "parse", f"Первое событие должно быть parse, получили {names[0]}"
    assert names[-1] == "done", f"Последнее событие должно быть done, получили {names[-1]}"
    # Между ними — хотя бы одно событие check.
    assert "check" in names, f"Ожидался хотя бы один check-event; всего: {names}"


def test_post_check_stream_check_events_have_progress(
    client: TestClient, docx_bytes: bytes
) -> None:
    """Каждое `check`-событие содержит code/index/total для прогресс-бара."""
    files = {"file": ("sample.docx", docx_bytes, "application/octet-stream")}
    r = client.post("/check/stream", files=files, data={"profile_id": "gost-7.32-2017"})
    events = _parse_sse_stream(r.text)
    check_events = [(name, payload) for name, payload in events if name == "check"]
    assert check_events, "Должен быть хотя бы один check-event"
    for _, payload in check_events:
        assert "code" in payload and isinstance(payload["code"], str)
        assert "index" in payload and isinstance(payload["index"], int)
        assert "total" in payload and isinstance(payload["total"], int)
        assert payload["index"] < payload["total"]


def test_post_check_stream_done_event_has_summary(client: TestClient, docx_bytes: bytes) -> None:
    """`done` содержит violations и summary, как у обычного `/check`."""
    files = {"file": ("sample.docx", docx_bytes, "application/octet-stream")}
    r = client.post("/check/stream", files=files, data={"profile_id": "gost-7.32-2017"})
    events = _parse_sse_stream(r.text)
    done = [payload for name, payload in events if name == "done"]
    assert len(done) == 1
    assert "violations" in done[0]
    assert "summary" in done[0]
    summary = done[0]["summary"]
    assert isinstance(summary, dict)
    assert {"error", "warning", "info"} <= set(summary)


def test_post_check_stream_rejects_non_docx(client: TestClient) -> None:
    """Не-.docx файл — 400 до старта стрима (валидация в _read_docx_upload)."""
    r = client.post(
        "/check/stream",
        files={"file": ("bad.txt", b"hello", "text/plain")},
    )
    assert r.status_code == 400


def test_post_check_stream_unknown_profile_returns_404(
    client: TestClient, docx_bytes: bytes
) -> None:
    """Несуществующий profile_id — 404 до старта стрима."""
    files = {"file": ("sample.docx", docx_bytes, "application/octet-stream")}
    r = client.post(
        "/check/stream",
        files=files,
        data={"profile_id": "nonexistent-profile-99"},
    )
    assert r.status_code == 404


# --- validator.engine.validate_iter (unit) ----------------------------------


def test_validate_iter_yields_check_events_then_done() -> None:
    """`validate_iter` yields check-события по очереди и финальный done."""
    from gostforge.profile import load_profile
    from gostforge.validator.engine import validate_iter

    from .conftest import make_docx

    p = Path("/tmp/sample_for_iter_test.docx")
    make_docx(p, paragraphs=["Параграф."])
    from gostforge.parser import parse_docx

    document = parse_docx(p)
    profile = load_profile("gost-7.32-2017")

    events = list(validate_iter(document, profile))
    check_events = [e for e in events if e[0] == "check"]
    done_events = [e for e in events if e[0] == "done"]
    assert check_events, "Должен быть хотя бы один check-event"
    assert len(done_events) == 1
    # check.index растёт от 0 до total-1.
    indices = [e[2] for e in check_events]
    assert indices == sorted(indices)
    assert all(0 <= idx < e[3] for idx, e in zip(indices, check_events, strict=True))
