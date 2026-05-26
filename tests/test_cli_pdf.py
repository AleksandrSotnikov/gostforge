"""Тесты CLI-команды `gostforge pdf`.

LibreOffice реально не вызывается — все внешние процессы замоканы.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import patch

from click.testing import CliRunner

from gostforge.cli import main
from gostforge.pdf_exporter import LibreOfficeNotFoundError


def _make_fake_docx(path: Path) -> Path:
    """Положить любой файл с расширением .docx — содержимое не важно (LO замокан)."""
    path.write_bytes(b"fake docx bytes")
    return path


def test_pdf_command_libreoffice_not_found_exits_3(tmp_path: Path) -> None:
    """Если LibreOffice не найден — exit code 3 и сообщение об ошибке."""
    src = _make_fake_docx(tmp_path / "in.docx")
    out = tmp_path / "out.pdf"

    runner = CliRunner()
    with patch(
        "gostforge.pdf_exporter._find_soffice",
        side_effect=LibreOfficeNotFoundError("LibreOffice не найден. ..."),
    ):
        result = runner.invoke(
            main,
            ["pdf", str(src), "-o", str(out)],
            catch_exceptions=False,
        )

    assert result.exit_code == 3, result.output
    assert "LibreOffice не найден" in result.output


def test_pdf_command_success(tmp_path: Path) -> None:
    """Happy path: subprocess замокан, PDF появляется, exit 0."""
    src = _make_fake_docx(tmp_path / "work.docx")
    out = tmp_path / "out.pdf"

    def fake_run(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        outdir = Path(cmd[cmd.index("--outdir") + 1])
        (outdir / "work.pdf").write_bytes(b"%PDF-1.5 fake")
        return subprocess.CompletedProcess(cmd, returncode=0, stdout=b"", stderr=b"")

    runner = CliRunner()
    with (
        patch("gostforge.pdf_exporter._find_soffice", return_value="/usr/bin/soffice"),
        patch("gostforge.pdf_exporter.subprocess.run", side_effect=fake_run),
    ):
        result = runner.invoke(
            main,
            ["pdf", str(src), "-o", str(out)],
            catch_exceptions=False,
        )

    assert result.exit_code == 0, result.output
    assert out.is_file()
    assert "PDF сохранён" in result.output


def test_pdf_command_timeout_exits_4(tmp_path: Path) -> None:
    """TimeoutExpired → exit code 4 и метка таймаута в stderr."""
    src = _make_fake_docx(tmp_path / "in.docx")
    out = tmp_path / "out.pdf"

    def fake_run(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        raise subprocess.TimeoutExpired(cmd=cmd, timeout=kwargs.get("timeout", 0))

    runner = CliRunner()
    with (
        patch("gostforge.pdf_exporter._find_soffice", return_value="/usr/bin/soffice"),
        patch("gostforge.pdf_exporter.subprocess.run", side_effect=fake_run),
    ):
        result = runner.invoke(
            main,
            ["pdf", str(src), "-o", str(out), "--timeout", "0.5"],
            catch_exceptions=False,
        )

    assert result.exit_code == 4, result.output
    assert "таймаут" in result.output.lower()


def test_pdf_command_libreoffice_error_exits_5(tmp_path: Path) -> None:
    """LibreOffice вернул не-нулевой код → exit 5 и stderr выводится."""
    src = _make_fake_docx(tmp_path / "in.docx")
    out = tmp_path / "out.pdf"

    def fake_run(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        raise subprocess.CalledProcessError(returncode=77, cmd=cmd, stderr=b"libreoffice boom")

    runner = CliRunner()
    with (
        patch("gostforge.pdf_exporter._find_soffice", return_value="/usr/bin/soffice"),
        patch("gostforge.pdf_exporter.subprocess.run", side_effect=fake_run),
    ):
        result = runner.invoke(
            main,
            ["pdf", str(src), "-o", str(out)],
            catch_exceptions=False,
        )

    assert result.exit_code == 5, result.output
    assert "77" in result.output
    assert "libreoffice boom" in result.output
