"""Smoke-тесты для вкладки «PDF» в Streamlit-UI.

Реальный LibreOffice не вызывается — subprocess замокан, как и в
тестах CLI и pdf_exporter.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest


def test_pdf_helpers_importable() -> None:
    """``_build_pdf_bytes`` и ``_render_pdf_tab`` импортируются из app.py."""
    pytest.importorskip("streamlit")
    from gostforge.web.app import _build_pdf_bytes, _render_pdf_tab

    assert callable(_build_pdf_bytes)
    assert callable(_render_pdf_tab)


def test_build_pdf_bytes_calls_convert(tmp_path: Path) -> None:
    """``_build_pdf_bytes`` сохраняет docx во temp, вызывает convert, возвращает байты."""
    pytest.importorskip("streamlit")
    from gostforge.web.app import _build_pdf_bytes

    class _FakeUploaded:
        def getvalue(self) -> bytes:
            return b"fake docx bytes"

    def fake_run(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        outdir = Path(cmd[cmd.index("--outdir") + 1])
        input_path = Path(cmd[-1])
        (outdir / (input_path.stem + ".pdf")).write_bytes(b"%PDF-1.5 fake")
        return subprocess.CompletedProcess(cmd, returncode=0, stdout=b"", stderr=b"")

    with (
        patch("gostforge.pdf_exporter._find_soffice", return_value="/usr/bin/soffice"),
        patch("gostforge.pdf_exporter.subprocess.run", side_effect=fake_run),
    ):
        data = _build_pdf_bytes(_FakeUploaded())

    assert isinstance(data, bytes)
    assert data.startswith(b"%PDF")
