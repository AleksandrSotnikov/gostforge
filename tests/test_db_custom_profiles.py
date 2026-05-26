# ruff: noqa: RUF001, RUF002, RUF003

"""Тесты локального реестра пользовательских профилей (миграция v2)."""

from __future__ import annotations

from pathlib import Path

import pytest

from gostforge.db import (
    CustomProfileRecord,
    get_connection,
    get_custom_profile,
    install_profile,
    list_custom_profiles,
    uninstall_profile,
)
from gostforge.db.migrations import current_schema_version
from gostforge.profile import is_custom_profile, list_profiles, load_profile


@pytest.fixture
def db_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    p = tmp_path / "gostforge.db"
    monkeypatch.setenv("GOSTFORGE_DB_PATH", str(p))
    return p


_VALID_YAML = '''
id: kafedra-prog-2026
name: Программирование 2026 (моя кафедра)
version: "1.0"
extends: gost-7.32-2017
description: Кафедральные требования.
checks:
  T.02:
    enabled: true
    severity: error
    params:
      body_size: 12
'''


_MINIMAL_YAML = '''
id: minimal-test
name: Минимальный
version: "1.0"
'''


# --- Миграция --------------------------------------------------------------


def test_migration_v2_creates_custom_profiles_table(db_path: Path) -> None:
    with get_connection() as conn:
        assert current_schema_version(conn) >= 2
        tables = {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert "custom_profiles" in tables


# --- install_profile -------------------------------------------------------


def test_install_returns_record(db_path: Path) -> None:
    with get_connection() as conn:
        rec = install_profile(conn, yaml_content=_VALID_YAML, source="manual")
    assert isinstance(rec, CustomProfileRecord)
    assert rec.profile_id == "kafedra-prog-2026"
    assert rec.name == "Программирование 2026 (моя кафедра)"
    assert rec.source == "manual"
    assert rec.installed_at  # ISO-метка времени


def test_install_rejects_invalid_yaml(db_path: Path) -> None:
    with get_connection() as conn:
        with pytest.raises(ValueError, match="Невалидный YAML"):
            install_profile(conn, yaml_content="!!! битый ::: yaml :::")


def test_install_rejects_yaml_without_required_fields(db_path: Path) -> None:
    """YAML без id/name → ValueError, не молчаливая запись."""
    with get_connection() as conn:
        with pytest.raises(ValueError, match="валидацию"):
            install_profile(
                conn,
                yaml_content='description: только описание\n',
            )


def test_install_rejects_non_mapping_yaml(db_path: Path) -> None:
    """YAML-список или строка вместо словаря отклоняется."""
    with get_connection() as conn:
        with pytest.raises(ValueError, match="должен быть YAML-объектом"):
            install_profile(conn, yaml_content="- a\n- b\n")


def test_install_duplicate_without_overwrite_raises(db_path: Path) -> None:
    with get_connection() as conn:
        install_profile(conn, yaml_content=_VALID_YAML)
        with pytest.raises(ValueError, match="уже установлен"):
            install_profile(conn, yaml_content=_VALID_YAML)


def test_install_overwrite_updates_existing(db_path: Path) -> None:
    with get_connection() as conn:
        rec1 = install_profile(conn, yaml_content=_VALID_YAML, source="manual")
        updated_yaml = _VALID_YAML.replace(
            'name: Программирование 2026 (моя кафедра)',
            'name: Обновлённое имя',
        )
        rec2 = install_profile(
            conn, yaml_content=updated_yaml, source="github.com/...", overwrite=True
        )
    # ID записи остался прежним (UPDATE, не INSERT).
    assert rec1.id == rec2.id
    assert rec2.name == "Обновлённое имя"
    assert rec2.source == "github.com/..."


# --- get / list / uninstall ------------------------------------------------


def test_get_custom_profile_returns_record(db_path: Path) -> None:
    with get_connection() as conn:
        install_profile(conn, yaml_content=_VALID_YAML)
        rec = get_custom_profile(conn, "kafedra-prog-2026")
    assert rec is not None
    assert rec.profile_id == "kafedra-prog-2026"
    assert "kafedra-prog-2026" in rec.yaml_content


def test_get_unknown_returns_none(db_path: Path) -> None:
    with get_connection() as conn:
        assert get_custom_profile(conn, "does-not-exist") is None


def test_list_custom_profiles_alphabetical(db_path: Path) -> None:
    with get_connection() as conn:
        install_profile(conn, yaml_content=_VALID_YAML)
        install_profile(conn, yaml_content=_MINIMAL_YAML)
        items = list_custom_profiles(conn)
    assert [r.profile_id for r in items] == ["kafedra-prog-2026", "minimal-test"]


def test_uninstall_removes_record(db_path: Path) -> None:
    with get_connection() as conn:
        install_profile(conn, yaml_content=_VALID_YAML)
        assert uninstall_profile(conn, "kafedra-prog-2026") is True
        assert get_custom_profile(conn, "kafedra-prog-2026") is None
        # Повторный uninstall — False.
        assert uninstall_profile(conn, "kafedra-prog-2026") is False


# --- Интеграция с load_profile ---------------------------------------------


def test_load_profile_finds_custom_in_db(db_path: Path) -> None:
    with get_connection() as conn:
        install_profile(conn, yaml_content=_VALID_YAML)
    p = load_profile("kafedra-prog-2026")
    assert p.id == "kafedra-prog-2026"


def test_load_profile_custom_inherits_from_builtin(db_path: Path) -> None:
    """extends: gost-7.32-2017 должен слиться с builtin-профилем."""
    with get_connection() as conn:
        install_profile(conn, yaml_content=_VALID_YAML)
    p = load_profile("kafedra-prog-2026")
    # body_size переопределён в кастомном профиле.
    assert p.checks["T.02"].params["body_size"] == 12
    # Но F.01 (поля страницы) унаследован от gost-7.32-2017 — параметры есть.
    assert "F.01" in p.checks


def test_load_profile_builtin_still_works(db_path: Path) -> None:
    """Установка custom не ломает доступ к builtin профилям."""
    with get_connection() as conn:
        install_profile(conn, yaml_content=_VALID_YAML)
    p = load_profile("gost-7.32-2017")
    assert p.id == "gost-7.32-2017"


def test_list_profiles_includes_custom(db_path: Path) -> None:
    with get_connection() as conn:
        install_profile(conn, yaml_content=_VALID_YAML)
    ids = list_profiles()
    assert "kafedra-prog-2026" in ids
    # Builtin тоже на месте.
    assert "gost-7.32-2017" in ids


def test_list_profiles_sorted(db_path: Path) -> None:
    with get_connection() as conn:
        install_profile(conn, yaml_content=_VALID_YAML)
        install_profile(conn, yaml_content=_MINIMAL_YAML)
    ids = list_profiles()
    assert ids == sorted(ids)


def test_is_custom_profile_returns_correct_flag(db_path: Path) -> None:
    with get_connection() as conn:
        install_profile(conn, yaml_content=_VALID_YAML)
    assert is_custom_profile("kafedra-prog-2026") is True
    assert is_custom_profile("gost-7.32-2017") is False
    assert is_custom_profile("does-not-exist") is False


def test_custom_profile_overrides_builtin_with_same_id(db_path: Path) -> None:
    """Если custom-профиль имеет id builtin — приоритет custom."""
    # Создаём YAML с id одноимённым builtin, но другим именем.
    override = _VALID_YAML.replace(
        "id: kafedra-prog-2026", "id: gost-7.32-2017"
    ).replace("extends: gost-7.32-2017\n", "")
    with get_connection() as conn:
        install_profile(conn, yaml_content=override)
    p = load_profile("gost-7.32-2017")
    # name стало кафедральным (custom перекрыл).
    assert "кафедра" in p.name.lower()


def test_load_profile_without_db_falls_back_to_builtin(
    db_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Если БД недоступна — load_profile молча идёт в файлы."""
    # Используем недостижимый путь к БД, чтобы _load_from_db вернул None.
    monkeypatch.setenv("GOSTFORGE_DB_PATH", "/nonexistent/path/db.sqlite")
    # У нас всё равно нет прав на /nonexistent — _load_from_db поглотит
    # ошибку и вернёт None. Главное — load_profile не упадёт.
    p = load_profile("gost-7.32-2017")
    assert p.id == "gost-7.32-2017"
