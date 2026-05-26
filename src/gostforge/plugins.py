"""Загрузчик пользовательских плагинов проверок.

Плагин — это обычный Python-файл (или пакет) с зарегистрированными через
``@register("X.NN")`` функциями. При импорте модуля валидатора мы сканируем
директорию ``~/.gostforge/plugins/`` (Linux/macOS) или
``%APPDATA%\\gostforge\\plugins\\`` (Windows) и импортируем каждый
найденный ``.py``-файл. При импорте срабатывают декораторы
``@register`` — проверки автоматически попадают в общий реестр.

Ошибки импорта одного плагина не должны прерывать загрузку других —
они логируются как warning и проглатываются. Так одна плохая
кафедральная проверка не положит весь нормоконтроль.
"""

from __future__ import annotations

import importlib.util
import logging
import os
import sys
from pathlib import Path

logger = logging.getLogger(__name__)


def plugins_dir() -> Path:
    """Путь к директории плагинов.

    На Windows — ``%APPDATA%\\gostforge\\plugins``, если переменная задана,
    иначе fallback на ``~/.gostforge/plugins`` (как на Linux/macOS).
    """
    if os.name == "nt":
        appdata = os.environ.get("APPDATA")
        if appdata:
            return Path(appdata) / "gostforge" / "plugins"
    return Path.home() / ".gostforge" / "plugins"


def discover_plugin_files(directory: Path | None = None) -> list[Path]:
    """Найти все ``.py``-файлы в директории плагинов (не рекурсивно).

    Файлы, начинающиеся с ``_`` (например, ``__init__.py``, ``_helper.py``),
    игнорируются — они считаются вспомогательными и не должны
    самостоятельно регистрировать проверки.
    """
    directory = directory or plugins_dir()
    if not directory.is_dir():
        return []
    return sorted(
        p
        for p in directory.iterdir()
        if p.is_file() and p.suffix == ".py" and not p.name.startswith("_")
    )


def load_plugins(directory: Path | None = None) -> list[str]:
    """Загрузить все плагины из директории. Возвращает список загруженных имён.

    Каждый плагин импортируется через ``importlib`` с уникальным
    именем модуля ``gostforge_plugin_<stem>``. При импорте срабатывают
    декораторы ``@register``, и проверки добавляются в реестр.

    Ошибки импорта плагина логируются как warning, но не прерывают
    загрузку других плагинов.
    """
    loaded: list[str] = []
    for plugin_file in discover_plugin_files(directory):
        module_name = f"gostforge_plugin_{plugin_file.stem}"
        try:
            spec = importlib.util.spec_from_file_location(module_name, plugin_file)
            if spec is None or spec.loader is None:
                logger.warning("Не удалось создать spec для %s", plugin_file)
                continue
            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            spec.loader.exec_module(module)
            loaded.append(module_name)
            logger.info("Загружен плагин %s из %s", module_name, plugin_file)
        except Exception as exc:  # noqa: BLE001 — изолируем ошибки плагинов
            logger.warning("Ошибка загрузки плагина %s: %s", plugin_file, exc)
            # Удалим возможный битый модуль из sys.modules, чтобы
            # повторная загрузка не схватила полу-импортированный объект.
            sys.modules.pop(module_name, None)
    return loaded
