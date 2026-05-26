"""Тесты CLI-команды `gostforge serve` (Фаза 3).

uvicorn.run помокаем — реально слушать порт в тестах не нужно.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest
from click.testing import CliRunner

from gostforge.cli import main


def test_serve_invokes_uvicorn_with_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = MagicMock()
    # Подменяем uvicorn.run в импортированном внутри команды модуле.
    monkeypatch.setattr("uvicorn.run", fake)

    runner = CliRunner()
    result = runner.invoke(main, ["serve"])
    assert result.exit_code == 0, result.output
    fake.assert_called_once()
    kwargs = fake.call_args.kwargs
    assert kwargs["host"] == "127.0.0.1"
    assert kwargs["port"] == 8000
    assert kwargs["reload"] is False
    assert fake.call_args.args[0] == "gostforge.api.app:app"


def test_serve_passes_host_port_reload(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = MagicMock()
    monkeypatch.setattr("uvicorn.run", fake)

    runner = CliRunner()
    result = runner.invoke(main, ["serve", "--host", "0.0.0.0", "--port", "9000", "--reload"])
    assert result.exit_code == 0, result.output
    kwargs = fake.call_args.kwargs
    assert kwargs["host"] == "0.0.0.0"
    assert kwargs["port"] == 9000
    assert kwargs["reload"] is True


def test_serve_reports_missing_extra(monkeypatch: pytest.MonkeyPatch) -> None:
    """Если uvicorn не установлен — выходим с кодом 2 и подсказкой."""
    import builtins

    real_import = builtins.__import__

    def _no_uvicorn(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "uvicorn":
            raise ImportError("no uvicorn here")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _no_uvicorn)

    runner = CliRunner()
    result = runner.invoke(main, ["serve"])
    assert result.exit_code == 2
    assert "gostforge[api]" in result.output
