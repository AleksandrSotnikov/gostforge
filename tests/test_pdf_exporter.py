# ruff: noqa: RUF002

"""Тесты для ``gostforge.pdf_exporter``.

Все тесты НЕ вызывают реальный LibreOffice — внешние процессы замоканы.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from gostforge.pdf_exporter import (
    LibreOfficeNotFoundError,
    _find_soffice,
    convert_to_pdf,
)


def test_find_soffice_raises_when_not_in_path() -> None:
    """Если ни soffice, ни libreoffice не найдены — поднимается LibreOfficeNotFoundError."""
    with (
        patch("gostforge.pdf_exporter.shutil.which", return_value=None),
        pytest.raises(LibreOfficeNotFoundError) as exc_info,
    ):
        _find_soffice()
    # Сообщение должно содержать подсказку по установке.
    assert "LibreOffice" in str(exc_info.value)
    assert "apt install" in str(exc_info.value) or "brew" in str(exc_info.value)


def test_find_soffice_returns_soffice_path() -> None:
    """Когда soffice найден — возвращается путь, libreoffice не запрашивается."""

    def which_stub(name: str) -> str | None:
        return "/usr/bin/soffice" if name == "soffice" else None

    with patch("gostforge.pdf_exporter.shutil.which", side_effect=which_stub):
        assert _find_soffice() == "/usr/bin/soffice"


def test_find_soffice_falls_back_to_libreoffice() -> None:
    """Если soffice не найден, но libreoffice есть — возвращается путь до libreoffice."""

    def which_stub(name: str) -> str | None:
        return "/usr/bin/libreoffice" if name == "libreoffice" else None

    with patch("gostforge.pdf_exporter.shutil.which", side_effect=which_stub):
        assert _find_soffice() == "/usr/bin/libreoffice"


def test_convert_raises_on_missing_input(tmp_path: Path) -> None:
    """Несуществующий input_path → FileNotFoundError ещё до запуска LibreOffice."""
    missing = tmp_path / "does-not-exist.docx"
    output = tmp_path / "out.pdf"
    with pytest.raises(FileNotFoundError):
        convert_to_pdf(missing, output)


def test_convert_calls_subprocess_with_correct_args(tmp_path: Path) -> None:
    """convert_to_pdf вызывает soffice с правильными аргументами и переносит результат."""
    input_path = tmp_path / "work.docx"
    input_path.write_bytes(b"fake docx content")
    output_path = tmp_path / "out" / "result.pdf"

    captured: dict[str, Any] = {}

    def fake_run(
        cmd: list[str],
        *,
        check: bool,
        timeout: float,
        capture_output: bool,
    ) -> subprocess.CompletedProcess[bytes]:
        captured["cmd"] = cmd
        captured["check"] = check
        captured["timeout"] = timeout
        captured["capture_output"] = capture_output
        # Эмулируем поведение LibreOffice: положить work.pdf в outdir.
        outdir_idx = cmd.index("--outdir") + 1
        outdir = Path(cmd[outdir_idx])
        (outdir / "work.pdf").write_bytes(b"%PDF-1.5 fake pdf")
        return subprocess.CompletedProcess(cmd, returncode=0, stdout=b"", stderr=b"")

    with (
        patch("gostforge.pdf_exporter._find_soffice", return_value="/usr/bin/soffice"),
        patch("gostforge.pdf_exporter.subprocess.run", side_effect=fake_run),
    ):
        result = convert_to_pdf(input_path, output_path, timeout=42.5)

    # Результат перенесён в указанный путь и содержит «pdf»-байты.
    assert result == output_path.resolve()
    assert output_path.is_file()
    assert output_path.read_bytes().startswith(b"%PDF")

    # Команда содержит обязательные флаги и таймаут передан.
    cmd = captured["cmd"]
    assert cmd[0] == "/usr/bin/soffice"
    assert "--headless" in cmd
    assert "--convert-to" in cmd
    assert cmd[cmd.index("--convert-to") + 1] == "pdf"
    assert "--outdir" in cmd
    assert str(input_path.resolve()) in cmd
    assert captured["check"] is True
    assert captured["timeout"] == 42.5
    assert captured["capture_output"] is True


def test_convert_creates_parent_directory(tmp_path: Path) -> None:
    """Если родительская папка output_path не существует — она создаётся."""
    input_path = tmp_path / "work.docx"
    input_path.write_bytes(b"fake docx")
    # Глубоко вложенный путь — родителей нет.
    output_path = tmp_path / "deeply" / "nested" / "result.pdf"

    def fake_run(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        outdir = Path(cmd[cmd.index("--outdir") + 1])
        (outdir / "work.pdf").write_bytes(b"%PDF-1.5")
        return subprocess.CompletedProcess(cmd, returncode=0, stdout=b"", stderr=b"")

    with (
        patch("gostforge.pdf_exporter._find_soffice", return_value="/usr/bin/soffice"),
        patch("gostforge.pdf_exporter.subprocess.run", side_effect=fake_run),
    ):
        convert_to_pdf(input_path, output_path)

    assert output_path.is_file()


def test_convert_raises_when_libreoffice_does_not_produce_pdf(tmp_path: Path) -> None:
    """subprocess.run отработал успешно, но PDF не появился — RuntimeError."""
    input_path = tmp_path / "work.docx"
    input_path.write_bytes(b"fake docx")
    output_path = tmp_path / "out.pdf"

    def fake_run(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        # Ничего не пишем в outdir — эмулируем «успешный» запуск без результата.
        return subprocess.CompletedProcess(cmd, returncode=0, stdout=b"", stderr=b"")

    with (
        patch("gostforge.pdf_exporter._find_soffice", return_value="/usr/bin/soffice"),
        patch("gostforge.pdf_exporter.subprocess.run", side_effect=fake_run),
        pytest.raises(RuntimeError) as exc_info,
    ):
        convert_to_pdf(input_path, output_path)
    assert "PDF" in str(exc_info.value)


def test_convert_propagates_called_process_error(tmp_path: Path) -> None:
    """Если LibreOffice падает (non-zero exit) — CalledProcessError пробрасывается."""
    input_path = tmp_path / "work.docx"
    input_path.write_bytes(b"fake docx")
    output_path = tmp_path / "out.pdf"

    def fake_run(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        raise subprocess.CalledProcessError(returncode=1, cmd=cmd, stderr=b"boom")

    with (
        patch("gostforge.pdf_exporter._find_soffice", return_value="/usr/bin/soffice"),
        patch("gostforge.pdf_exporter.subprocess.run", side_effect=fake_run),
        pytest.raises(subprocess.CalledProcessError),
    ):
        convert_to_pdf(input_path, output_path)


def test_convert_propagates_timeout(tmp_path: Path) -> None:
    """Таймаут пробрасывается как TimeoutExpired."""
    input_path = tmp_path / "work.docx"
    input_path.write_bytes(b"fake docx")
    output_path = tmp_path / "out.pdf"

    def fake_run(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        raise subprocess.TimeoutExpired(cmd=cmd, timeout=kwargs.get("timeout", 0))

    with (
        patch("gostforge.pdf_exporter._find_soffice", return_value="/usr/bin/soffice"),
        patch("gostforge.pdf_exporter.subprocess.run", side_effect=fake_run),
        pytest.raises(subprocess.TimeoutExpired),
    ):
        convert_to_pdf(input_path, output_path, timeout=0.5)
