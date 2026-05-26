# ruff: noqa: RUF002, RUF003

"""REST API для gostforge поверх FastAPI.

Опциональная зависимость (`pip install -e ".[api]"`). Импорт самого
объекта приложения отложен, чтобы основной пакет не требовал FastAPI.

Использование:

    from gostforge.api import create_app
    app = create_app()

Запуск через CLI:

    gostforge serve --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

from .app import create_app

__all__ = ["create_app"]
