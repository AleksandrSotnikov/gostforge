"""Тесты: изображения переживают сохранение/новую сессию.

Раньше state хранил абсолютные пути к временным файлам картинок —
они «протухали» при сохранении в JSON, новой сессии или эфемерном
контейнере, и при генерации .docx изображения пропадали. Теперь
картинка вшивается в state как data-URI (``image_data``).
"""

from __future__ import annotations

import base64
import json
import zipfile
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("streamlit")

from gostforge.web.builder_editor import (
    _build_document_from_state,
    _data_uri_to_temp_file,
    _image_file_to_data_uri,
    embed_images_as_data_uri_in_state,
)

# Минимальный валидный 1x1 PNG.
_PNG_1x1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


def _media_in_docx(data: bytes) -> list[str]:
    import io

    with zipfile.ZipFile(io.BytesIO(data)) as z:
        return [n for n in z.namelist() if "media" in n]


def _state_with_figure(image_path: str = "", image_data: str = "") -> dict[str, Any]:
    return {
        "title": "X",
        "year": 2026,
        "profile_id": "gost-7.32-2017",
        "sections": [
            {
                "heading": "Введение",
                "blocks": [
                    {
                        "kind": "figure",
                        "image_path": image_path,
                        "image_data": image_data,
                        "caption": "Рисунок 1 — Тест",
                    }
                ],
            }
        ],
    }


def test_data_uri_roundtrip(tmp_path: Path) -> None:
    src = tmp_path / "img.png"
    src.write_bytes(_PNG_1x1)
    uri = _image_file_to_data_uri(src)
    assert uri is not None
    assert uri.startswith("data:image/png;base64,")
    out = _data_uri_to_temp_file(uri)
    assert out is not None
    assert Path(out).read_bytes() == _PNG_1x1


def test_data_uri_to_temp_file_rejects_garbage() -> None:
    assert _data_uri_to_temp_file("/not/a/data/uri.png") is None
    assert _data_uri_to_temp_file("data:image/png,nope") is None


def test_embed_inlines_and_survives_file_deletion(tmp_path: Path) -> None:
    """embed_images_as_data_uri_in_state вшивает картинку; после удаления
    исходного файла данные остаются в state."""
    img = tmp_path / "rId5.png"
    img.write_bytes(_PNG_1x1)
    state = _state_with_figure(image_path="embedded:rId5")
    embed_images_as_data_uri_in_state(state, {"rId5": img})
    block = state["sections"][0]["blocks"][0]
    assert block["image_data"].startswith("data:image/png;base64,")

    img.unlink()  # имитируем новую сессию / эфемерный контейнер
    state = json.loads(json.dumps(state))  # сохранение → загрузка JSON
    data = _build_document_from_state(state)
    assert _media_in_docx(data), "изображение должно сохраниться через data_uri"


def test_generate_embeds_image_from_data_uri() -> None:
    uri = "data:image/png;base64," + base64.b64encode(_PNG_1x1).decode("ascii")
    state = _state_with_figure(image_data=uri)
    data = _build_document_from_state(state)
    assert _media_in_docx(data)


def test_generate_skips_stale_path_without_data_uri() -> None:
    """Протухший image_path без image_data не должен ронять генерацию."""
    state = _state_with_figure(image_path="/nonexistent/gone.png")
    data = _build_document_from_state(state)  # не должно бросить
    assert _media_in_docx(data) == []
