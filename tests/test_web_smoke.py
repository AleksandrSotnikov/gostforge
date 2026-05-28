"""Smoke-тесты для веб-интерфейса (Streamlit).

Полноценный e2e Streamlit-приложения за пределами Фазы 1: фреймворк
требует отдельного раннера и контекста сессии. Здесь мы ограничиваемся
смоук-проверками:

* модуль ``gostforge.web.app`` импортируется при установленном streamlit;
* CLI-команда ``gostforge ui`` корректно падает с exit code 2, если
  streamlit не установлен;
* CLI-команда ``gostforge ui`` собирает корректную команду для
  ``streamlit run`` и передаёт её ``subprocess.run``.
"""

from __future__ import annotations

import sys
from typing import Any

import pytest
from click.testing import CliRunner

from gostforge.cli import main


def test_app_module_importable() -> None:
    """``import gostforge.web.app`` не падает при наличии streamlit."""
    pytest.importorskip("streamlit")
    # Чистый импорт без побочного запуска render() — render() закрыт
    # в ``if __name__ == "__main__":`` блок.
    import gostforge.web.app as app_module

    assert hasattr(app_module, "render"), "В app.py должна быть функция render()"


def test_app_renders_dashboard_by_default() -> None:
    """По умолчанию (страница «Главная») приложение рисует дашборд без ошибок.

    После перехода на ``st.navigation``: вместо ``st.radio('Режим', ...)``
    у нас sidebar-навигация со страницами, а дашборд — `default=True`-страница.
    Проверяем: нет exceptions + есть заголовок дашборда.
    """
    pytest.importorskip("streamlit")
    try:
        from streamlit.testing.v1 import AppTest
    except ImportError:
        pytest.skip("AppTest недоступен")

    at = AppTest.from_string("from gostforge.web.app import render\nrender()\n")
    at.run(timeout=90)
    assert not at.exception, [str(e) for e in at.exception]
    # На главной странице дашборд: есть title.
    assert at.title


def test_ui_command_without_streamlit_exits_2(monkeypatch: pytest.MonkeyPatch) -> None:
    """Если streamlit не установлен, ``gostforge ui`` падает с exit code 2."""
    # Прячем streamlit, чтобы ``import streamlit`` внутри команды упал.
    monkeypatch.setitem(sys.modules, "streamlit", None)

    runner = CliRunner()
    result = runner.invoke(main, ["ui"])
    assert result.exit_code == 2, result.output
    assert "Streamlit не установлен" in result.output
    assert "gostforge[ui]" in result.output


def test_ui_command_invokes_streamlit_run(monkeypatch: pytest.MonkeyPatch) -> None:
    """``gostforge ui --port 9000 --host 0.0.0.0`` запускает streamlit run с этими параметрами."""
    pytest.importorskip("streamlit")

    captured: dict[str, Any] = {}

    def fake_run(cmd: list[str], *args: Any, **kwargs: Any) -> Any:
        captured["cmd"] = cmd
        captured["kwargs"] = kwargs

        class _Result:
            returncode = 0

        return _Result()

    import subprocess

    monkeypatch.setattr(subprocess, "run", fake_run)

    runner = CliRunner()
    result = runner.invoke(main, ["ui", "--port", "9000", "--host", "0.0.0.0"])
    assert result.exit_code == 0, result.output

    cmd = captured["cmd"]
    assert cmd[0] == "streamlit"
    assert cmd[1] == "run"
    # Третий аргумент — путь до app.py
    assert cmd[2].endswith("app.py")
    assert "--server.address" in cmd
    assert cmd[cmd.index("--server.address") + 1] == "0.0.0.0"
    assert "--server.port" in cmd
    assert cmd[cmd.index("--server.port") + 1] == "9000"
    # Флаги темы оформления
    assert "--theme.base" in cmd
    assert cmd[cmd.index("--theme.base") + 1] == "light"
    assert "--theme.primaryColor" in cmd
    assert cmd[cmd.index("--theme.primaryColor") + 1] == "#2F5496"
    assert "--theme.font" in cmd
    assert cmd[cmd.index("--theme.font") + 1] == "serif"


def test_process_file_with_progress_calls_callback(tmp_path: Any) -> None:
    """`_process_file_with_progress` зовёт on_progress(code, idx, total)
    хотя бы раз и возвращает violations идентичные обычному `_process_file`.
    """
    from gostforge.profile import load_profile
    from gostforge.web.app import _process_file, _process_file_with_progress
    from tests.conftest import make_docx

    docx = tmp_path / "x.docx"
    make_docx(docx, paragraphs=["Параграф один."])

    class _Uploaded:
        name = "x.docx"

        def __init__(self, p):
            self._data = p.read_bytes()

        def getvalue(self) -> bytes:
            return self._data

    uploaded = _Uploaded(docx)
    profile = load_profile("gost-7.32-2017")

    calls: list[tuple[str, int, int]] = []

    def cb(code: str, idx: int, total: int) -> None:
        calls.append((code, idx, total))

    _, violations = _process_file_with_progress(uploaded, profile, cb)
    assert calls, "Должен быть хотя бы один вызов on_progress"
    # idx растёт; total одинаковый.
    indices = [c[1] for c in calls]
    assert indices == sorted(indices)
    totals = {c[2] for c in calls}
    assert len(totals) == 1, "total должен быть константой между вызовами"

    # violations такие же, как у синхронного варианта.
    _, violations_sync = _process_file(_Uploaded(docx), profile)
    assert len(violations) == len(violations_sync)
