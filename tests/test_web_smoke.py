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
    """По умолчанию (режим «Главная») приложение рисует дашборд без ошибок."""
    pytest.importorskip("streamlit")
    try:
        from streamlit.testing.v1 import AppTest
    except ImportError:
        pytest.skip("AppTest недоступен")

    at = AppTest.from_string("from gostforge.web.app import render\nrender()\n")
    at.run(timeout=90)
    assert not at.exception, [str(e) for e in at.exception]
    # Дашборд — режим по умолчанию: есть заголовок и переключатель режимов.
    assert at.title
    assert any("Режим" in r.label for r in at.radio)


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


def test_build_annotated_docx_bytes(tmp_path: Any) -> None:
    """Хелпер аннотации возвращает валидный .docx (комментарии Word)."""
    pytest.importorskip("streamlit")
    import io

    from gostforge.builder import work
    from gostforge.exporter import export_docx
    from gostforge.profile import load_profile
    from gostforge.web.app import _build_annotated_docx_bytes

    profile = load_profile("gost-7.32-2017")
    doc = work("Тест").section("Введение").paragraph("Короткий текст.").build()
    src = tmp_path / "src.docx"
    export_docx(doc, profile, src)

    uploaded = io.BytesIO(src.read_bytes())  # getvalue() как у Streamlit UploadedFile
    data, n = _build_annotated_docx_bytes(uploaded, profile, "comments")
    assert data[:2] == b"PK"  # zip-сигнатура .docx
    assert isinstance(n, int)


def test_ensure_docx_bytes_passthrough(tmp_path: Any) -> None:
    """`_ensure_docx_bytes` для .docx возвращает исходный объект без конвертации."""
    pytest.importorskip("streamlit")
    import io

    from gostforge.web.app import _ensure_docx_bytes

    uf = io.BytesIO(b"PKfake")
    uf.name = "work.docx"
    assert _ensure_docx_bytes(uf) is uf


def test_state_versions_list_and_load(tmp_path: Any, monkeypatch: Any) -> None:
    """_save/_list/_load версий state делают round-trip."""
    pytest.importorskip("streamlit")
    from gostforge.web import builder_editor as be

    monkeypatch.setattr(be.Path, "home", staticmethod(lambda: tmp_path))
    state = {"title": "Тест-версия", "profile_id": "gost-7.32-2017", "sections": [{"heading": "X"}]}
    saved = be._save_state_version(state)
    assert saved.exists()
    versions = be._list_state_versions()
    assert saved in versions
    loaded = be._load_state_version(saved)
    assert loaded is not None
    assert loaded["title"] == "Тест-версия"


def test_compare_violations_fixed_and_introduced() -> None:
    """_compare_violations разбивает на исчезнувшие/появившиеся по отпечатку."""
    pytest.importorskip("streamlit")
    from gostforge.validator import Violation
    from gostforge.web.app import _compare_violations

    common = Violation(check_code="T.01", severity="error", message="m", location="loc")
    only_a = Violation(check_code="F.01", severity="error", message="a", location="la")
    only_b = Violation(check_code="H.01", severity="warning", message="b", location="lb")
    cmp = _compare_violations([common, only_a], [common, only_b])
    fixed_codes = {v.check_code for v in cmp["fixed"]}
    intro_codes = {v.check_code for v in cmp["introduced"]}
    assert fixed_codes == {"F.01"}
    assert intro_codes == {"H.01"}
    assert cmp["total_a"] == 2
    assert cmp["total_b"] == 2
    assert cmp["errors_a"] == 2
    assert cmp["errors_b"] == 1


def test_compare_violations_identical_no_diff() -> None:
    pytest.importorskip("streamlit")
    from gostforge.validator import Violation
    from gostforge.web.app import _compare_violations

    v = Violation(check_code="T.01", severity="error", message="m", location="loc")
    cmp = _compare_violations([v], [v])
    assert cmp["fixed"] == []
    assert cmp["introduced"] == []
