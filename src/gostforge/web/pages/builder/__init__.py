"""Подстраницы Конструктора.

Конструктор разнесён по четырём страницам — каждая фокусируется на
своём шаге workflow:

* **structure** — дерево разделов: добавить / удалить / переместить;
* **content** — редактор содержимого активного раздела;
* **validation** — live-нормоконтроль с кликом «→ К разделу»;
* **export** — экспорт во все форматы + автофиксы.

У всех страниц общий sidebar (метаданные работы + save/load state +
автосейв) и общий ``_ensure_state()`` / snapshot.

Реализации UI-блоков не дублируются — каждая страница импортирует
существующие render-helpers из ``web.builder_editor``. Это минимально
инвазивный рефакторинг.
"""

from __future__ import annotations


def _common_setup() -> None:
    """Общая инициализация для всех страниц Конструктора.

    Все 4 страницы независимо рендерятся Streamlit-ом, поэтому каждой
    нужно: убедиться, что state есть; снять snapshot для undo/redo;
    запустить периодический autosave.
    """
    from gostforge.web.builder_editor import (
        _auto_snapshot_if_changed,
        _autosave_now,
        _ensure_state,
    )

    _ensure_state()
    _auto_snapshot_if_changed()
    _autosave_now()


def _common_sidebar() -> None:
    """Общий sidebar Конструктора: метаданные, save/load, автосейв.

    Виден на всех 4 подстраницах — переключение страницы не теряет
    контекст «над какой работой я работаю».
    """
    from gostforge.web.builder_editor import (
        _get_state,
        _render_autosave_banner,
        _render_sidebar_metadata,
        _render_state_persistence_sidebar,
    )

    _render_sidebar_metadata()
    _render_state_persistence_sidebar(_get_state())
    _render_autosave_banner()
