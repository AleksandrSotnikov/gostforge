"""Стартовая страница «Главная» Streamlit-интерфейса gostforge.

Приветственный дашборд/онбординг: коротко объясняет, что делает
инструмент, перечисляет доступные режимы, предлагает три типовых
сценария «с чего начать» и показывает компактную шпаргалку по
ГОСТ 7.32-2017 (значения по возможности берутся из реального профиля).

Страница не выполняет действий над документами — это навигационная
точка входа. Любой сбой при чтении профиля/реестра проверок не должен
ронять рендер: значения подменяются разумными хардкод-дефолтами.
"""

from __future__ import annotations

try:
    import streamlit as st
except ImportError as exc:  # pragma: no cover - проверяется при отсутствии пакета
    raise ImportError("Для UI нужен streamlit: pip install 'gostforge[ui]'") from exc


# Канонические значения ГОСТ 7.32-2017 на случай, если профиль не
# удастся загрузить. Используются как fallback в _gost_cheatsheet().
_FALLBACK_MARGINS_MM: dict[str, float] = {"top": 20.0, "right": 15.0, "bottom": 20.0, "left": 30.0}
_FALLBACK_FONT: str = "Times New Roman"
_FALLBACK_SIZE_PT: float = 14.0
_FALLBACK_LINE_SPACING: float = 1.5
_FALLBACK_INDENT_CM: float = 1.25


# Категории проверок нормоконтроля: буква кода → краткое название.
# Используется в блоке «Что проверяет нормоконтроль».
_CHECK_CATEGORIES: dict[str, str] = {
    "F": "Поля и геометрия страницы",
    "T": "Текст и типографика",
    "S": "Структура работы",
    "H": "Заголовки",
    "I": "Рисунки",
    "B": "Таблицы",
    "M": "Формулы",
    "L": "Списки",
    "R": "Список литературы",
    "C": "Перекрёстные ссылки",
    "A": "Сокращения",
    "P": "Приложения",
    "K": "Колонтитулы и нумерация",
    "V": "Объём",
    "X": "Стиль изложения",
    "U": "Единицы измерения",
}


def _gost_cheatsheet() -> dict[str, object]:
    """Собрать значения для шпаргалки по ГОСТ 7.32-2017.

    Предпочтительно тянем параметры оформления из профиля
    ``gost-7.32-2017``; при любой ошибке (нет профиля, иная структура
    схемы) откатываемся на канонические хардкод-значения, чтобы
    страница «Главная» всегда отрисовывалась.
    """
    margins = dict(_FALLBACK_MARGINS_MM)
    font = _FALLBACK_FONT
    size_pt = _FALLBACK_SIZE_PT
    line_spacing = _FALLBACK_LINE_SPACING
    indent_cm = _FALLBACK_INDENT_CM
    try:
        from gostforge.profile import load_profile

        p = load_profile("gost-7.32-2017")
        margins = dict(p.styles.page.margins_mm)
        font = p.styles.body.font
        size_pt = p.styles.body.size_pt
        line_spacing = p.styles.body.line_spacing
        indent_cm = p.styles.body.first_line_indent_cm
    except Exception:  # любой сбой откатываем на дефолты
        pass

    return {
        "margins": margins,
        "font": font,
        "size_pt": size_pt,
        "line_spacing": line_spacing,
        "indent_cm": indent_cm,
    }


def _checks_count() -> int | None:
    """Число зарегистрированных проверок или ``None`` при ошибке."""
    try:
        from gostforge.validator.engine import registered_checks

        return len(registered_checks())
    except Exception:  # метрика не критична для рендера
        return None


def _profiles_count() -> int | None:
    """Число доступных профилей или ``None`` при ошибке."""
    try:
        from gostforge.profile import list_profiles

        return len(list_profiles())
    except Exception:  # метрика не критична для рендера
        return None


def _render_modes_overview() -> None:
    """Обзор пяти режимов инструмента (bullet-list)."""
    st.subheader("Режимы")
    st.markdown(
        "- **Нормоконтроль** — проверка готовой `.docx` по ГОСТ.\n"
        "- **Конструктор** — собрать работу с нуля или доработать свою.\n"
        "- **Редактор профиля** — настроить все параметры оформления.\n"
        "- **История** — прошлые проверки и обсуждение руководитель↔студент.\n"
        "- **Документация** — встроенное руководство."
    )
    st.caption("Выберите режим в переключателе вверху.")


def _render_getting_started() -> None:
    """Блок «С чего начать» — три типовых пути использования."""
    st.subheader("С чего начать")
    st.markdown(
        "1. **Проверить готовую работу** — откройте режим **Нормоконтроль** "
        "и загрузите свой `.docx`.\n"
        "2. **Собрать новую работу с нуля** — откройте режим **Конструктор** "
        "и нажмите **«Собрать каркас по ГОСТ»**.\n"
        "3. **Доработать свою `.docx`** — откройте режим **Конструктор** "
        "и нажмите **«Загрузить готовую работу (.docx)»**."
    )


def _render_cheatsheet() -> None:
    """Компактная шпаргалка по ключевым требованиям ГОСТ 7.32-2017."""
    cs = _gost_cheatsheet()
    margins = cs["margins"]
    assert isinstance(margins, dict)
    top = margins.get("top", _FALLBACK_MARGINS_MM["top"])
    right = margins.get("right", _FALLBACK_MARGINS_MM["right"])
    bottom = margins.get("bottom", _FALLBACK_MARGINS_MM["bottom"])
    left = margins.get("left", _FALLBACK_MARGINS_MM["left"])

    st.subheader("Шпаргалка по ГОСТ 7.32")
    st.markdown(
        f"- **Поля:** верх {top:g} мм, низ {bottom:g} мм, "
        f"правое {right:g} мм, левое {left:g} мм.\n"
        f"- **Шрифт:** {cs['font']}, {cs['size_pt']:g} пт.\n"
        f"- **Межстрочный интервал:** {cs['line_spacing']:g}.\n"
        f"- **Абзацный отступ:** {cs['indent_cm']:g} см.\n"
        "- **Выравнивание:** по ширине.\n"
        "- **Нумерация:** разделы основной части нумеруются (1, 1.1); "
        "структурные элементы (Введение, Заключение, Список использованных "
        "источников) — без номера."
    )


def _render_metrics() -> None:
    """Небольшие метрики: число проверок и число профилей."""
    checks = _checks_count()
    profiles = _profiles_count()
    col_checks, col_profiles = st.columns(2)
    col_checks.metric("Проверок", checks if checks is not None else "—")
    col_profiles.metric("Профилей", profiles if profiles is not None else "—")


def _render_check_categories() -> None:
    """Раскрывающийся обзор категорий проверок нормоконтроля.

    Список строится из модульной константы ``_CHECK_CATEGORIES``
    (буква кода → краткое название категории).
    """
    with st.expander("Что проверяет нормоконтроль"):
        lines = "\n".join(
            f"- **{letter}** — {title}" for letter, title in _CHECK_CATEGORIES.items()
        )
        st.markdown(lines)


def _render_profiles() -> None:
    """Раскрывающийся список доступных профилей с описаниями.

    Идентификаторы берём из ``list_profiles``; имя и описание — из
    загруженного профиля. Загрузка каждого профиля обёрнута в
    try/except, чтобы один битый профиль не ронял страницу. Если
    список пуст или ничего не удалось загрузить — выводим подпись.
    """
    with st.expander("Доступные профили"):
        try:
            from gostforge.profile import list_profiles, load_profile

            profile_ids = list_profiles()
        except Exception:  # реестр профилей недоступен — не критично
            profile_ids = []

        lines: list[str] = []
        for profile_id in profile_ids:
            try:
                prof = load_profile(profile_id)
            except Exception:  # один битый профиль не должен ломать страницу
                continue
            if prof.description:
                lines.append(f"- **{prof.name}** (`{profile_id}`) — {prof.description}")
            else:
                lines.append(f"- **{prof.name}** (`{profile_id}`)")

        if lines:
            st.markdown("\n".join(lines))
        else:
            st.caption("Профили не найдены.")


def render_dashboard() -> None:
    """Отрисовать стартовую страницу «Главная» (дашборд/онбординг)."""
    st.title("gostforge — нормоконтроль и конструктор по ГОСТ")
    st.markdown(
        "**gostforge** — двухрежимная система для работы с документами по ГОСТ: "
        "проводит **нормоконтроль** чужих `.docx` (курсовых, дипломных, отчётов "
        "НИР) на соответствие стандарту и помогает **конструировать** работы по "
        "ГОСТу с нуля. Оба режима работают через единую модель документа."
    )

    _render_metrics()
    st.divider()

    _render_modes_overview()
    st.divider()

    _render_getting_started()
    st.divider()

    _render_cheatsheet()
    st.divider()

    _render_check_categories()
    _render_profiles()
