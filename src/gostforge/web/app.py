# ruff: noqa: RUF001, RUF002

"""Streamlit-приложение gostforge.

Минимальный веб-интерфейс Фазы 1: drag-and-drop загрузка одного или
нескольких ``.docx``, проверка по выбранному профилю, просмотр
нарушений и скачивание отчёта (Markdown/Excel).

Запуск:

    gostforge ui
    # или вручную
    streamlit run src/gostforge/web/app.py
"""

from __future__ import annotations

import json
import tempfile
from collections import Counter
from pathlib import Path
from typing import TYPE_CHECKING, Any

try:
    import streamlit as st
except ImportError as exc:  # pragma: no cover - проверяется при отсутствии пакета
    raise ImportError(
        "Установите gostforge[ui] для веб-интерфейса: pip install -e \".[ui]\""
    ) from exc

from gostforge import __version__
from gostforge.cli import _write_markdown_report, _write_xlsx_report
from gostforge.parser import parse_docx
from gostforge.profile import list_profiles, load_profile
from gostforge.validator import Violation, validate
from gostforge.validator.engine import registered_checks

if TYPE_CHECKING:
    from gostforge.profile import Profile


def _violations_to_rows(violations: list[Violation]) -> list[dict[str, str]]:
    """Преобразовать нарушения в список словарей для st.dataframe."""
    severity_label = {"error": "Ошибка", "warning": "Предупр.", "info": "Инфо"}
    return [
        {
            "Код": v.check_code,
            "Серьёзность": severity_label.get(v.severity, v.severity),
            "Сообщение": v.message,
            "Что исправить": v.suggestion,
        }
        for v in violations
    ]


def _process_file(uploaded_file: Any, profile: Profile) -> list[Violation]:
    """Сохранить загруженный файл во временный путь, распарсить и проверить."""
    with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as tmp:
        tmp.write(uploaded_file.getvalue())
        tmp_path = Path(tmp.name)
    document = parse_docx(tmp_path)
    return validate(document, profile)


def _build_report_bytes(
    results: dict[str, list[Violation]], profile_id: str, fmt: str
) -> bytes:
    """Сгенерировать отчёт во временный файл и вернуть его байты."""
    suffix = ".md" if fmt == "markdown" else ".xlsx"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp_path = Path(tmp.name)
    if fmt == "markdown":
        _write_markdown_report(results, tmp_path, profile_id)
    else:
        _write_xlsx_report(results, tmp_path, profile_id)
    return tmp_path.read_bytes()


def _render_sidebar(profiles: list[str]) -> str:
    """Боковая панель — выбор профиля и сводка по проверкам."""
    st.sidebar.title("Настройки")
    st.sidebar.caption(f"gostforge v{__version__}")

    profile_id = st.sidebar.selectbox(
        "Профиль",
        options=profiles,
        index=profiles.index("gost-7.32-2017") if "gost-7.32-2017" in profiles else 0,
        help="Профиль определяет, какие проверки будут запущены и с какими параметрами.",
    )

    prof = load_profile(profile_id)
    enabled_codes = {c for c, cfg in prof.checks.items() if cfg.enabled}
    available = set(registered_checks())
    runnable = enabled_codes & available
    skipped = enabled_codes - available

    st.sidebar.markdown(
        f"**Профиль:** `{profile_id}` (v{prof.version})\n\n"
        f"**Будет запущено:** {len(runnable)} из {len(enabled_codes)} включённых"
    )
    if skipped:
        st.sidebar.warning(
            "Не реализованы: " + ", ".join(sorted(skipped))
        )

    with st.sidebar.expander("Показать параметры профиля"):
        st.json(json.loads(prof.model_dump_json()))

    return profile_id


def _render_file_result(name: str, violations: list[Violation]) -> None:
    """Отрисовать результат проверки одного файла."""
    st.subheader(name)

    counts = Counter(v.severity for v in violations)
    col_err, col_warn, col_info = st.columns(3)
    col_err.metric("Ошибок", counts.get("error", 0))
    col_warn.metric("Предупр.", counts.get("warning", 0))
    col_info.metric("Инфо", counts.get("info", 0))

    if not violations:
        st.success("Нарушений не найдено")
        return

    rows = _violations_to_rows(violations)
    # pandas обычно идёт в зависимостях streamlit; используем её, если доступна,
    # иначе передаём список словарей — st.dataframe умеет и так.
    try:
        import pandas as pd  # type: ignore[import-untyped]

        df: Any = pd.DataFrame(rows)
    except ImportError:  # pragma: no cover - pandas есть в зависимостях streamlit
        df = rows
    st.dataframe(df, use_container_width=True, hide_index=True)

    with st.expander("Детали (location)"):
        for v in violations:
            loc = v.location or "(не указано)"
            st.markdown(f"- **{v.check_code}** — `{loc}`")


def _render_main(profile_id: str) -> None:
    """Главная область — загрузка файлов и результаты."""
    st.title("gostforge — нормоконтроль .docx по ГОСТ")
    st.caption(
        "Загрузите курсовую, дипломную или отчёт НИР — получите список нарушений "
        "и отчёт по выбранному профилю."
    )

    uploaded = st.file_uploader(
        "Перетащите .docx или нажмите для выбора",
        type=["docx"],
        accept_multiple_files=True,
    )

    if not uploaded:
        st.info(
            "Загрузите один или несколько .docx-файлов выше. Поддерживаются "
            "курсовые, дипломные работы и отчёты НИР, оформленные по ГОСТ 7.32-2017."
        )
        return

    prof = load_profile(profile_id)
    results: dict[str, list[Violation]] = {}

    for uf in uploaded:
        try:
            violations = _process_file(uf, prof)
        except Exception as e:
            st.error(f"Не удалось обработать «{uf.name}»: {e}")
            continue
        results[uf.name] = violations
        _render_file_result(uf.name, violations)
        st.divider()

    if not results:
        return

    total = sum(len(v) for v in results.values())
    st.markdown(
        f"**Итого:** проверено файлов {len(results)}, всего нарушений {total}."
    )

    col_md, col_xlsx = st.columns(2)
    with col_md:
        md_bytes = _build_report_bytes(results, profile_id, "markdown")
        st.download_button(
            "Скачать Markdown-отчёт",
            data=md_bytes,
            file_name="report.md",
            mime="text/markdown",
        )
    with col_xlsx:
        xlsx_bytes = _build_report_bytes(results, profile_id, "xlsx")
        st.download_button(
            "Скачать Excel-отчёт",
            data=xlsx_bytes,
            file_name="report.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )


def render() -> None:
    """Главная функция рендера — точка входа streamlit-приложения."""
    st.set_page_config(
        page_title="gostforge — нормоконтроль .docx",
        layout="wide",
    )
    profiles = list_profiles()
    if not profiles:
        st.error("Не найдено ни одного профиля. Проверьте директорию profiles/.")
        return
    profile_id = _render_sidebar(profiles)
    _render_main(profile_id)


# Streamlit запускает файл как ``__main__``. При обычном ``import`` модуля
# (например, из тестов или CLI) мы не должны вызывать render() — там нет
# контекста streamlit-сессии.
if __name__ == "__main__":
    render()
