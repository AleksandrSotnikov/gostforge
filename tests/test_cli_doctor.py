"""Тесты команды `gostforge doctor` — диагностика окружения."""

from __future__ import annotations

import json

import pytest
from click.testing import CliRunner

from gostforge.cli import _collect_doctor_report, _doctor_status, main


def test_doctor_report_structure() -> None:
    """`_collect_doctor_report` возвращает ожидаемые разделы."""
    report = _collect_doctor_report()
    required_sections = {
        "python",
        "gostforge",
        "dependencies",
        "libreoffice",
        "profiles",
        "registry",
        "database",
        "plugins",
    }
    assert required_sections <= set(report.keys()), (
        f"Не хватает разделов: {required_sections - set(report.keys())}"
    )


def test_doctor_report_dependencies_include_core_and_optional() -> None:
    """Список зависимостей содержит и обязательные, и опциональные."""
    deps = _collect_doctor_report()["dependencies"]
    # Обязательные.
    for core in ("python-docx", "lxml", "pydantic", "click", "openpyxl"):
        assert core in deps, f"Нет {core}"
        assert deps[core].get("optional", False) is False
    # Опциональные (могут быть установлены или нет).
    for opt in ("streamlit", "fastapi", "uvicorn", "pdfplumber", "PIL"):
        assert opt in deps, f"Нет {opt}"
        assert deps[opt].get("optional", False) is True


def test_doctor_registry_has_checks() -> None:
    """В реестре должны быть проверки (минимум 115 по текущему статусу)."""
    reg = _collect_doctor_report()["registry"]
    assert reg["checks_count"] >= 100, f"Слишком мало проверок: {reg['checks_count']}"
    assert reg["fixers_count"] >= 20, f"Слишком мало фиксеров: {reg['fixers_count']}"


def test_doctor_status_ok_when_core_deps_present() -> None:
    """Если все core-deps + профили — статус ok."""
    report = _collect_doctor_report()
    ok, _warnings = _doctor_status(report)
    # В тестовом окружении дефолтный профиль есть, core-deps стоят.
    assert ok is True


def test_doctor_status_not_ok_when_no_profiles(monkeypatch: pytest.MonkeyPatch) -> None:
    """Если в окружении нет профилей — статус не ok."""
    report = _collect_doctor_report()
    report["profiles"] = {"count": 0, "ids": [], "ok": False}
    ok, warnings = _doctor_status(report)
    assert ok is False
    assert any("профил" in w.lower() for w in warnings), (
        f"Нет предупреждения о профилях: {warnings}"
    )


def test_doctor_status_warns_about_missing_libreoffice() -> None:
    """Отсутствие LibreOffice → warning, но не критично."""
    report = _collect_doctor_report()
    report["libreoffice"] = {"installed": False, "path": None}
    ok, warnings = _doctor_status(report)
    # LibreOffice не критичен — ok остаётся True (если другие компоненты в порядке).
    if report["profiles"].get("ok") and all(
        d["installed"] or d.get("optional") for d in report["dependencies"].values()
    ):
        assert ok is True
    assert any("LibreOffice" in w for w in warnings)


def test_doctor_status_warns_about_missing_optional_deps() -> None:
    """Отсутствие опциональной зависимости → warning, но не критично."""
    report = _collect_doctor_report()
    # Симулируем отсутствие streamlit.
    report["dependencies"]["streamlit"] = {"installed": False, "optional": True}
    ok, warnings = _doctor_status(report)
    assert any("streamlit" in w for w in warnings)
    # Опциональная — статус остаётся ok если всё остальное хорошо.
    if report["profiles"].get("ok") and report["registry"].get("checks_count", 0) > 0:
        # Core-deps в test_env стоят.
        assert ok is True


def test_doctor_status_critical_when_core_missing() -> None:
    """Отсутствие core-зависимости → ok=False."""
    report = _collect_doctor_report()
    report["dependencies"]["lxml"] = {"installed": False, "optional": False}
    ok, warnings = _doctor_status(report)
    assert ok is False
    assert any("lxml" in w and "обязательно" in w.lower() for w in warnings)


# --- CLI integration ---


def test_doctor_cli_human_readable_runs_and_exits_0() -> None:
    """`gostforge doctor` без флагов запускается и возвращает 0 в нормальном окружении."""
    runner = CliRunner()
    result = runner.invoke(main, ["doctor"])
    assert result.exit_code == 0, f"Exit code {result.exit_code}; output:\n{result.output}"
    # Видны разделы.
    assert "Python" in result.output
    assert "Зависимости" in result.output
    assert "Профили" in result.output


def test_doctor_cli_json_outputs_valid_json() -> None:
    """`gostforge doctor --json` выдаёт валидный JSON."""
    runner = CliRunner()
    result = runner.invoke(main, ["doctor", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert "ok" in payload
    assert "report" in payload
    assert "warnings" in payload
    assert "registry" in payload["report"]


def test_doctor_cli_json_reports_check_and_fixer_counts() -> None:
    """JSON-отчёт содержит актуальные счётчики из реестра."""
    runner = CliRunner()
    result = runner.invoke(main, ["doctor", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    reg = payload["report"]["registry"]
    assert reg["checks_count"] >= 100
    assert reg["fixers_count"] >= 20
