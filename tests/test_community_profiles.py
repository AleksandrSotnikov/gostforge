"""Тесты community-реестра кафедральных профилей.

Roadmap Q2/2026: «Публичный реестр кафедральных профилей».
Реализован как локальный каталог `profiles/community/*.yaml` —
пользователь устанавливает выбранный профиль через CLI
`gostforge profiles community install <id>` или UI «Маркетплейс
профилей».
"""

from __future__ import annotations

import pytest


def test_list_community_profiles_returns_examples() -> None:
    """В `profiles/community/` лежат образцы кафедральных профилей."""
    from gostforge.profile import list_community_profiles

    items = list_community_profiles()
    assert items, "Каталог community-профилей пуст; ожидаем хотя бы 1 образец"
    ids = {it["id"] for it in items}
    assert "msu-vmk-coursework" in ids
    assert "spbstu-bachelor-thesis" in ids
    # Поля метаданных присутствуют у каждого.
    for it in items:
        assert "id" in it and isinstance(it["id"], str)
        assert "name" in it and isinstance(it["name"], str)
        assert "version" in it
        assert "description" in it


def test_read_community_profile_yaml_returns_content() -> None:
    """`read_community_profile_yaml` возвращает сырой YAML."""
    from gostforge.profile import read_community_profile_yaml

    yaml_content = read_community_profile_yaml("msu-vmk-coursework")
    assert "id: msu-vmk-coursework" in yaml_content
    assert "extends: gost-7.32-2017" in yaml_content


def test_read_community_profile_yaml_raises_on_unknown_id() -> None:
    """Неизвестный id → FileNotFoundError."""
    from gostforge.profile import read_community_profile_yaml

    with pytest.raises(FileNotFoundError):
        read_community_profile_yaml("nonexistent-profile-id-xxx")


def test_cli_profiles_community_list() -> None:
    """`gostforge profiles community list` показывает доступные образцы."""
    from click.testing import CliRunner

    from gostforge.cli import main

    runner = CliRunner()
    r = runner.invoke(main, ["profiles", "community", "list"])
    assert r.exit_code == 0, r.output
    assert "msu-vmk-coursework" in r.output
    assert "spbstu-bachelor-thesis" in r.output


def test_cli_profiles_community_install_unknown_id_exits_with_error() -> None:
    """`gostforge profiles community install <wrong>` → exit 2 с ошибкой."""
    from click.testing import CliRunner

    from gostforge.cli import main

    runner = CliRunner()
    r = runner.invoke(main, ["profiles", "community", "install", "wrong-id"])
    assert r.exit_code == 2
    assert "не найден" in r.output.lower() or "не найден" in (r.stderr_bytes or b"").decode(
        "utf-8", errors="ignore"
    )


def test_cli_profiles_community_install_writes_to_db(tmp_path, monkeypatch) -> None:
    """Установка community-профиля попадает в локальный реестр БД."""
    from click.testing import CliRunner

    # Изолированная БД на каждый тест.
    monkeypatch.setenv("GOSTFORGE_DB_PATH", str(tmp_path / "test.db"))

    from gostforge.cli import main

    runner = CliRunner()
    r = runner.invoke(
        main, ["profiles", "community", "install", "msu-vmk-coursework", "--overwrite"]
    )
    assert r.exit_code == 0, r.output
    assert "msu-vmk-coursework" in r.output

    # Проверим, что профиль реально появился в БД.
    from gostforge.db import get_connection, list_custom_profiles

    with get_connection() as conn:
        installed = list_custom_profiles(conn)
    ids = {p.profile_id for p in installed}
    assert "msu-vmk-coursework" in ids


def test_profile_manager_page_shows_community_section() -> None:
    """UI: на «Управлении профилями» виден заголовок «Маркетплейс…»."""
    try:
        from streamlit.testing.v1 import AppTest
    except ImportError:
        pytest.skip("AppTest недоступен")
    at = AppTest.from_string("from gostforge.web.pages.profile_manager import page\npage()\n")
    at.run(timeout=60)
    assert not at.exception, [str(e) for e in at.exception]
    subheaders = [s.value for s in at.subheader]
    assert any("Маркетплейс" in s for s in subheaders), (
        f"Subheader «Маркетплейс» не найден; subheaders: {subheaders}"
    )
