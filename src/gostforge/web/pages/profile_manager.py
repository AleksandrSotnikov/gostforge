"""Страница «Управление профилями» — список / удаление / загрузка YAML.

Отдельно от «Редактора профиля» (`pages/profile_editor.py`): редактор
правит параметры одного профиля и сохраняет результат, а здесь —
управление каталогом установленных пользовательских профилей и быстрая
заливка готового YAML с диска (например, кафедрального профиля,
который кто-то прислал коллеге).
"""

from __future__ import annotations

import streamlit as st

from gostforge.web.profile_editor import (
    delete_custom_profile,
    list_installed_custom_profiles,
    save_profile_to_registry,
)


def page() -> None:
    st.title("Управление профилями")
    st.caption(
        "Установленные пользовательские профили живут в локальной БД "
        "(`~/.gostforge/gostforge.db`). Базовые профили (`gost-7.32-2017` и др.) "
        "хранятся в `profiles/` пакета и здесь не показываются."
    )

    # Help-блок: единый стиль с другими страницами веб-UI.
    with st.expander("ℹ️ Что доступно на этой странице", expanded=False):
        st.markdown(
            """
**Эта страница** — реестр **пользовательских** профилей (созданных
в «Редакторе профиля» или загруженных YAML-файлами). Базовые
профили (`gost-7.32-2017`, `gost-r-2.105-2019` и т. д.) сюда не
попадают — они вшиты в пакет.

**Сверху** — таблица установленных профилей: ID, название, версия,
дата установки. Кнопка «Удалить выбранный профиль» убирает запись
из локальной БД (базовые профили не трогает).

**Снизу** — форма «Установить профиль из файла». Загрузите свой
YAML (например, кафедральный профиль, который вам прислали) — он
появится в реестре и в списке выбора в Нормоконтроле / Конструкторе.

**Где хранится:** SQLite в `~/.gostforge/gostforge.db`. Чтобы
перенести профили — скопируйте файл; чтобы откатить — удалите.

> Создание профиля с нуля — на странице «Редактор профиля».
"""
        )

    _render_installed_list()
    st.divider()
    _render_install_from_file()


def _render_installed_list() -> None:
    """Список установленных кафедральных/пользовательских профилей с удалением."""
    customs = list_installed_custom_profiles()
    st.subheader(f"Установленные пользовательские профили ({len(customs)})")
    if not customs:
        st.caption(
            "Пока нет своих профилей. Откройте «Редактор профиля», "
            "настройте параметры и нажмите «Сохранить в реестр». Или "
            "загрузите готовый YAML с диска через форму ниже."
        )
        return
    st.table(
        [
            {
                "ID": c["id"],
                "Название": c["name"],
                "Версия": c["version"],
                "Установлен": c["installed_at"],
            }
            for c in customs
        ]
    )
    options = [c["id"] for c in customs]
    to_delete = st.selectbox(
        "Профиль для удаления",
        options=options,
        key="pm_delete_select",
        help="Удаляется только запись в локальной БД; базовые профили не трогаются.",
    )
    if st.button("Удалить выбранный профиль", key="pm_delete_btn", type="primary"):
        if delete_custom_profile(to_delete):
            st.success(f"Профиль «{to_delete}» удалён из реестра.")
            st.rerun()
        else:
            st.warning(f"Профиль «{to_delete}» не найден в реестре.")


def _render_install_from_file() -> None:
    """Загрузка готового YAML-профиля с диска (drag-and-drop).

    Полезно, когда кафедра прислала готовый профиль файлом — не нужно
    его переписывать вручную в редакторе.
    """
    st.subheader("Загрузить YAML профиля с диска")
    st.caption(
        "Перетащите файл `*.yaml` или выберите вручную. После загрузки "
        "появится превью и кнопка «Установить» — профиль сохранится в "
        "локальный реестр и станет доступен в списках режимов."
    )
    uploaded = st.file_uploader(
        "YAML-профиль",
        type=["yaml", "yml"],
        accept_multiple_files=False,
        key="pm_upload",
    )
    if uploaded is None:
        return
    try:
        yaml_text = uploaded.getvalue().decode("utf-8")
    except UnicodeDecodeError:
        st.error("Не удалось прочитать файл — ожидается UTF-8.")
        return
    st.caption("Превью загруженного YAML:")
    st.code(yaml_text, language="yaml")
    overwrite = st.checkbox(
        "Перезаписать, если профиль с таким ID уже установлен",
        value=False,
        key="pm_install_overwrite",
    )
    if st.button("Установить в реестр", key="pm_install_btn", type="primary"):
        try:
            saved_id = save_profile_to_registry(yaml_text, overwrite=overwrite)
        except ValueError as exc:
            st.error(f"Не удалось установить: {exc}")
            return
        except Exception as exc:
            st.error(f"Ошибка реестра профилей: {exc}")
            return
        st.success(f"Профиль «{saved_id}» установлен. Обновляю список.")
        st.rerun()
