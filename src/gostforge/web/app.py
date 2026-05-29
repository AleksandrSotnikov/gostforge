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
        'Установите gostforge[ui] для веб-интерфейса: pip install -e ".[ui]"'
    ) from exc

from gostforge import __version__
from gostforge.builder.templates import (
    bachelor_thesis_template,
    coursework_template,
    research_report_template,
)
from gostforge.cli import _write_markdown_report, _write_xlsx_report
from gostforge.exporter import export_docx
from gostforge.fixer import FixApplied
from gostforge.fixer import fix as run_fix
from gostforge.fixer.engine import registered_fixers
from gostforge.parser import parse_docx
from gostforge.pdf_exporter import LibreOfficeNotFoundError, convert_to_pdf
from gostforge.profile import list_profiles, load_profile
from gostforge.stats import compute_stats
from gostforge.validator import Violation, validate
from gostforge.validator.engine import registered_checks

if TYPE_CHECKING:
    from gostforge.model import Document
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


def _filter_violations(
    violations: list[Violation],
    severities: set[str],
    categories: set[str],
) -> list[Violation]:
    """Отфильтровать нарушения по серьёзности и категории.

    Категория — буква до точки в коде проверки (``"F.01"`` → ``"F"``).
    Пустое множество означает «не фильтровать по этому измерению»: при
    обоих пустых множествах возвращается исходный список без изменений.
    """
    return [
        v
        for v in violations
        if (not severities or v.severity in severities)
        and (not categories or v.check_code.split(".", 1)[0] in categories)
    ]


def _ensure_docx_bytes(uploaded_file: Any) -> Any:
    """Привести загрузку к .docx-байтам (конвертируя .doc/.odt/.rtf).

    Возвращает file-like объект с методами ``getvalue()``/``name`` —
    либо исходный (если уже .docx), либо ``io.BytesIO`` с
    конвертированными байтами. Конвертация — через LibreOffice
    (``convert_document``); может поднять LibreOfficeNotFoundError.
    """
    import io

    name = getattr(uploaded_file, "name", "document.docx")
    suffix = Path(name).suffix.lower()
    if suffix == ".docx":
        return uploaded_file

    from gostforge.pdf_exporter import convert_document

    with tempfile.NamedTemporaryFile(suffix=suffix or ".doc", delete=False) as tmp_in:
        tmp_in.write(uploaded_file.getvalue())
        in_path = Path(tmp_in.name)
    out_path = in_path.with_suffix(".docx")
    convert_document(in_path, out_path, target_format="docx")
    buf = io.BytesIO(out_path.read_bytes())
    buf.name = f"{Path(name).stem}.docx"
    return buf


def _process_file(uploaded_file: Any, profile: Profile) -> tuple[Document, list[Violation]]:
    """Сохранить загруженный файл во временный путь, распарсить и проверить.

    Возвращает кортеж (Document, violations) — модель нужна для вкладки
    «Статистика», violations — для вкладки «Проверка».
    """
    with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as tmp:
        tmp.write(uploaded_file.getvalue())
        tmp_path = Path(tmp.name)
    document = parse_docx(tmp_path)
    return document, validate(document, profile)


def _build_annotated_docx_bytes(
    uploaded_file: Any, profile: Profile, style: str
) -> tuple[bytes, int]:
    """Сохранить загрузку во временный файл и вернуть аннотированный .docx.

    ``style``: «comments» — настоящие OOXML-комментарии Word; «inline» —
    inline-маркеры `[CODE: message]`. Возвращает (bytes, число пометок).
    """
    from gostforge.annotator import annotate_docx

    with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as tmp_in:
        tmp_in.write(uploaded_file.getvalue())
        in_path = Path(tmp_in.name)
    with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as tmp_out:
        out_path = Path(tmp_out.name)
    n = annotate_docx(in_path, out_path, profile, style=style)  # type: ignore[arg-type]
    return out_path.read_bytes(), n


def _build_fixed_docx_bytes(document: Document, profile: Profile) -> tuple[bytes, list[FixApplied]]:
    """Применить автофиксы к документу и вернуть байты исправленного .docx.

    Возвращает (bytes, fixes_applied). fixes_applied — список записей
    о правках (код, location, описание) в порядке вызова фиксеров.
    Если ничего не исправлено — список пуст.
    """
    fixes_applied = run_fix(document, profile)
    with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as tmp:
        out_path = Path(tmp.name)
    export_docx(document, profile, out_path)
    data = out_path.read_bytes()
    return data, fixes_applied


def _group_fixes(fixes: list[FixApplied]) -> list[tuple[str, int, list[str]]]:
    """Сгруппировать применённые правки по коду фиксера.

    Возвращает список (код, количество, описания) с сортировкой по коду.
    Порядок описаний внутри группы сохраняется (как применялись).
    """
    grouped: dict[str, list[str]] = {}
    for fa in fixes:
        grouped.setdefault(fa.fixer_code, []).append(fa.description)
    return [(code, len(descs), descs) for code, descs in sorted(grouped.items())]


def _build_pdf_bytes(uploaded_file: Any) -> bytes:
    """Сконвертировать загруженный .docx → .pdf и вернуть байты результата.

    Сохраняем загруженный файл во временный путь (LibreOffice читает с
    диска, а не из памяти) и вызываем :func:`convert_to_pdf`. Может
    поднять :class:`LibreOfficeNotFoundError`, ``subprocess.CalledProcessError``,
    ``subprocess.TimeoutExpired`` — обрабатываем вызывающим кодом.
    """
    with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as tmp:
        tmp.write(uploaded_file.getvalue())
        docx_path = Path(tmp.name)
    pdf_path = docx_path.with_suffix(".pdf")
    convert_to_pdf(docx_path, pdf_path)
    return pdf_path.read_bytes()


def _render_stats_table(name: str, document: Document) -> None:
    """Вкладка «Статистика» — числовые метрики структуры документа."""
    st.subheader(name)
    s = compute_stats(document)
    rows = [
        ("Секций вёрстки", s.page_sections),
        ("Разделов 1 уровня", s.logical_sections_level_1),
        ("Разделов всего", s.logical_sections_total),
        ("Параграфов всего", s.paragraphs),
        ("  …непустых", s.paragraphs_non_empty),
        ("Таблиц", s.tables),
        ("Рисунков", s.figures),
        ("Источников", s.bibliography_entries),
        ("Слов", s.words),
        ("Символов", s.characters),
    ]
    try:
        import pandas as pd  # type: ignore[import-untyped]

        df: Any = pd.DataFrame(rows, columns=["Показатель", "Значение"])
    except ImportError:  # pragma: no cover
        df = [{"Показатель": k, "Значение": v} for k, v in rows]
    st.dataframe(df, use_container_width=True, hide_index=True)


def _build_report_bytes(results: dict[str, list[Violation]], profile_id: str, fmt: str) -> bytes:
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
        st.sidebar.warning("Не реализованы: " + ", ".join(sorted(skipped)))

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

    # Фильтры по серьёзности и категории. Метрики выше остаются на полном
    # списке — фильтр влияет только на таблицу и детали ниже.
    severity_internal = {"Ошибка": "error", "Предупреждение": "warning", "Инфо": "info"}
    col_sev, col_cat = st.columns(2)
    with col_sev:
        sev_labels = st.multiselect(
            "Серьёзность",
            ["Ошибка", "Предупреждение", "Инфо"],
            key=f"sev_{name}",
        )
    with col_cat:
        cat_options = sorted({v.check_code.split(".", 1)[0] for v in violations})
        cat_selected = st.multiselect(
            "Категория",
            options=cat_options,
            key=f"cat_{name}",
        )
    selected_severities = {severity_internal[label] for label in sev_labels}
    selected_categories = set(cat_selected)
    filtered = _filter_violations(violations, selected_severities, selected_categories)

    if not filtered:
        st.caption("Под фильтр ничего не подходит.")
        return

    rows = _violations_to_rows(filtered)
    # pandas обычно идёт в зависимостях streamlit; используем её, если доступна,
    # иначе передаём список словарей — st.dataframe умеет и так.
    try:
        import pandas as pd

        df: Any = pd.DataFrame(rows)
    except ImportError:  # pragma: no cover - pandas есть в зависимостях streamlit
        df = rows
    st.dataframe(df, use_container_width=True, hide_index=True)

    with st.expander("Детали (location)"):
        for v in filtered:
            loc = v.location or "(не указано)"
            st.markdown(f"- **{v.check_code}** — `{loc}`")


def _render_pdf_tab(uploads: dict[str, Any]) -> None:
    """Вкладка «PDF» — конвертация загруженных .docx → .pdf через LibreOffice.

    Для каждого файла предлагается кнопка «Сгенерировать PDF». Сама
    конвертация запускается только по клику (LibreOffice стартует
    ~2 секунды — лениво экономим время загрузки страницы). При успехе
    показываем download_button с байтами .pdf. Если LibreOffice не
    установлен — выводим единичный warning сверху и не показываем кнопки.
    """
    # Проверяем доступность LibreOffice один раз — если его нет, нет
    # смысла рисовать кнопки конвертации.
    try:
        from gostforge.pdf_exporter import _find_soffice

        _find_soffice()
    except LibreOfficeNotFoundError:
        st.warning(
            "LibreOffice не установлен, PDF недоступен. "
            "Установите libreoffice (Ubuntu/Debian: sudo apt install libreoffice; "
            "macOS: brew install --cask libreoffice) и перезапустите gostforge."
        )
        return

    st.caption(
        "Конвертация выполняется через LibreOffice headless. "
        "Полезно для генерации финальной PDF-версии работы после автофиксов."
    )

    for name, uf in uploads.items():
        st.subheader(name)
        stem = Path(name).stem or "document"
        if st.button(f"Сгенерировать PDF «{name}»", key=f"gen_pdf_{name}"):
            try:
                pdf_bytes = _build_pdf_bytes(uf)
            except Exception as e:
                st.error(f"Не удалось сконвертировать «{name}» в PDF: {e}")
                continue
            st.success("PDF готов — нажмите «Скачать».")
            st.download_button(
                f"Скачать PDF «{name}»",
                data=pdf_bytes,
                file_name=f"{stem}.pdf",
                mime="application/pdf",
                key=f"download_pdf_{name}",
            )
        st.divider()


def _render_main(profile_id: str) -> None:
    """Главная область — загрузка файлов и результаты."""
    st.title("gostforge — нормоконтроль .docx по ГОСТ")
    st.caption(
        "Загрузите курсовую, дипломную или отчёт НИР — получите список нарушений "
        "и отчёт по выбранному профилю."
    )

    uploaded = st.file_uploader(
        "Перетащите .docx / .doc / .odt / .rtf или нажмите для выбора",
        type=["docx", "doc", "odt", "rtf"],
        accept_multiple_files=True,
    )

    if not uploaded:
        st.info(
            "Загрузите один или несколько файлов выше. Основной формат — "
            ".docx; .doc/.odt/.rtf автоматически конвертируются через "
            "LibreOffice. Поддерживаются курсовые, дипломные работы и "
            "отчёты НИР по ГОСТ 7.32-2017."
        )
        return

    prof = load_profile(profile_id)
    documents: dict[str, Document] = {}
    results: dict[str, list[Violation]] = {}
    uploads: dict[str, Any] = {}

    for uf in uploaded:
        try:
            # .doc/.odt/.rtf → .docx (один раз), чтобы все вкладки работали.
            norm = _ensure_docx_bytes(uf)
            document, violations = _process_file(norm, prof)
        except Exception as e:
            st.error(f"Не удалось обработать «{uf.name}»: {e}")
            continue
        documents[uf.name] = document
        results[uf.name] = violations
        uploads[uf.name] = norm

    if not results:
        return

    tab_check, tab_stats, tab_fix, tab_annot, tab_pdf = st.tabs(
        ["Проверка", "Статистика", "Автоисправление", "Аннотация", "PDF"]
    )

    with tab_check:
        for name, violations in results.items():
            _render_file_result(name, violations)
            st.divider()

    with tab_stats:
        for name, document in documents.items():
            _render_stats_table(name, document)
            st.divider()

    with tab_fix:
        st.markdown(
            f"Доступно **{len(registered_fixers())}** безопасных автофиксеров — "
            "они исправляют форматирование, не меняя смысл текста: поля и "
            "ориентация страницы, шрифт/кегль/цвет текста и заголовков, "
            "пробелы и кавычки, точки в заголовках, единицы измерения."
        )
        st.caption(f"Полный список: `{', '.join(sorted(registered_fixers()))}`.")
        for name, document in documents.items():
            st.subheader(name)
            try:
                fixed_bytes, applied = _build_fixed_docx_bytes(document, prof)
            except Exception as e:
                st.error(f"Не удалось сгенерировать исправленный .docx: {e}")
                continue
            if applied:
                groups = _group_fixes(applied)
                summary = ", ".join(f"{code} ×{count}" for code, count, _ in groups)
                st.success(f"Применено правок: {len(applied)} ({summary})")
                with st.expander("Что именно исправлено"):
                    for code, count, descs in groups:
                        st.markdown(f"**{code}** — {count} шт.")
                        for desc in descs:
                            st.markdown(f"- {desc}")
            else:
                st.info("Нечего исправлять — документ уже без авто-исправимых нарушений.")
            stem = Path(name).stem or "document"
            st.download_button(
                f"Скачать исправленный «{name}»",
                data=fixed_bytes,
                file_name=f"{stem}_fixed.docx",
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                key=f"download_fixed_{name}",
            )
            st.divider()

    with tab_annot:
        st.markdown(
            "Аннотированный `.docx` — копия документа с пометками нарушений "
            "прямо в проблемных местах. Откройте в Word/LibreOffice."
        )
        style_label = st.radio(
            "Вид пометок",
            options=["comments", "inline"],
            format_func=lambda v: {
                "comments": "Комментарии Word (боковые выноски)",
                "inline": "Inline-маркеры [CODE: …] в тексте",
            }[v],
            horizontal=True,
            key="annot_style",
        )
        for name, uf in uploads.items():
            st.subheader(name)
            try:
                annotated_bytes, n = _build_annotated_docx_bytes(uf, prof, style_label)
            except Exception as e:
                st.error(f"Не удалось создать аннотированный .docx: {e}")
                continue
            if n:
                st.success(f"Вставлено пометок: {n}")
            else:
                st.info("Нарушений не найдено — пометок нет.")
            stem = Path(name).stem or "document"
            st.download_button(
                f"Скачать аннотированный «{name}»",
                data=annotated_bytes,
                file_name=f"{stem}_annotated.docx",
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                key=f"download_annotated_{name}",
            )
            st.divider()

    with tab_pdf:
        _render_pdf_tab(uploads)

    total = sum(len(v) for v in results.values())
    st.markdown(f"**Итого:** проверено файлов {len(results)}, всего нарушений {total}.")

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


# Карта шаблонов для режима «Конструктор». Ключ — id шаблона (внутренний),
# значение — кортеж (человекочитаемое имя, фабричная функция). Сами шаблоны
# различаются сигнатурой: `research_report_template` не принимает author и
# supervisor, поэтому в _render_builder_mode() мы вызываем их через
# именованные аргументы, фильтруя ненужные.
_TEMPLATE_LABELS: dict[str, str] = {
    "coursework": "Курсовая работа",
    "bachelor_thesis": "Бакалаврская ВКР",
    "research_report": "Отчёт о НИР",
}


def _build_template_docx_bytes(
    template_id: str,
    *,
    title: str,
    author: str,
    supervisor: str,
    organization: str,
    year: int | None,
) -> bytes:
    """Собрать болванку по шаблону и вернуть байты .docx."""
    with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as tmp:
        out_path = Path(tmp.name)

    if template_id == "coursework":
        builder = coursework_template(
            title=title,
            author=author,
            supervisor=supervisor,
            organization=organization,
            year=year,
        )
    elif template_id == "bachelor_thesis":
        builder = bachelor_thesis_template(
            title=title,
            author=author,
            supervisor=supervisor,
            organization=organization,
            year=year,
        )
    elif template_id == "research_report":
        # research_report_template не принимает author/supervisor — это
        # обезличенный отчёт о НИР по ГОСТ 7.32-2017.
        builder = research_report_template(
            title=title,
            organization=organization,
            year=year,
        )
    else:  # pragma: no cover - селект ограничен ключами _TEMPLATE_LABELS
        raise ValueError(f"Неизвестный шаблон: {template_id}")

    builder.save(out_path)
    return out_path.read_bytes()


def _render_builder_mode() -> None:
    """Режим «Конструктор»: собрать болванку работы по шаблону.

    Sidebar содержит селект шаблона и поля для метаданных (title, author,
    supervisor, organization, year). Главная область — кнопка генерации и
    download_button с готовым .docx. Если title пустой — выводим warning
    и не показываем кнопку скачивания.
    """
    st.sidebar.title("Параметры работы")
    st.sidebar.caption(f"gostforge v{__version__}")

    template_id = st.sidebar.selectbox(
        "Шаблон",
        options=list(_TEMPLATE_LABELS.keys()),
        format_func=lambda key: _TEMPLATE_LABELS[key],
        help=("Скелет работы: какие разделы будут предзаполнены плейсхолдерами."),
    )

    title = st.sidebar.text_input(
        "Название работы",
        value="",
        help="Обязательное поле. Используется на титульном листе.",
    )
    author = st.sidebar.text_input(
        "Автор",
        value="",
        help="ФИО автора. Для отчёта о НИР игнорируется.",
    )
    supervisor = st.sidebar.text_input(
        "Научный руководитель",
        value="",
        help="ФИО руководителя. Для отчёта о НИР игнорируется.",
    )
    organization = st.sidebar.text_input(
        "Организация",
        value="",
        help="Название вуза или организации.",
    )
    year = st.sidebar.number_input(
        "Год",
        min_value=1900,
        max_value=2100,
        value=2026,
        step=1,
        help="Год выпуска работы.",
    )

    st.title("gostforge — конструктор работ по ГОСТу")
    st.caption(
        "Соберите валидный по структуре .docx-скелет с разделами и "
        "подсказками-плейсхолдерами. Дальше — заполните разделы своим текстом."
    )

    st.markdown(
        f"**Шаблон:** {_TEMPLATE_LABELS[template_id]}\n\n**Название:** {title or '_(не указано)_'}"
    )

    if not title.strip():
        st.warning("Укажите название работы")
        return

    if st.button("Создать болванку"):
        try:
            data = _build_template_docx_bytes(
                template_id,
                title=title.strip(),
                author=author.strip(),
                supervisor=supervisor.strip(),
                organization=organization.strip(),
                year=int(year),
            )
        except Exception as exc:
            st.error(f"Не удалось сгенерировать .docx: {exc}")
            return
        st.success("Болванка готова — нажмите «Скачать».")
        st.download_button(
            "Скачать болванку",
            data=data,
            file_name=f"{template_id}.docx",
            mime=("application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
            key=f"download_builder_{template_id}",
        )


def render() -> None:
    """Главная функция рендера — точка входа streamlit-приложения."""
    st.set_page_config(
        page_title="gostforge — нормоконтроль и конструктор по ГОСТу",
        page_icon="📄",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    profiles = list_profiles()
    if not profiles:
        st.error("Не найдено ни одного профиля. Проверьте директорию profiles/.")
        return

    mode = st.radio(
        "Режим",
        options=[
            "Главная",
            "Нормоконтроль",
            "Конструктор",
            "Редактор профиля",
            "История",
            "Документация",
        ],
        horizontal=True,
        help=(
            "Главная — обзор возможностей и быстрый старт. "
            "Нормоконтроль — проверка существующего .docx по ГОСТ. "
            "Конструктор — сборка работы по ГОСТу с нуля или из .docx. "
            "Редактор профиля — настройка всех параметров оформления и "
            "сохранение своего профиля. "
            "История — все прошлые проверки + обсуждение руководитель↔студент. "
            "Документация — встроенный просмотр руководства."
        ),
    )

    if mode == "Главная":
        from gostforge.web.dashboard import render_dashboard

        render_dashboard()
        return

    if mode == "Документация":
        from gostforge.web.docs_viewer import render_docs_viewer

        render_docs_viewer()
        return

    if mode == "Редактор профиля":
        from gostforge.web.profile_editor import render_profile_editor

        render_profile_editor()
        return

    if mode == "История":
        from gostforge.web.history_viewer import render_history_viewer

        render_history_viewer()
        return

    if mode == "Конструктор":
        # Новый интерактивный редактор (Фаза 2). Старый _render_builder_mode
        # с генерацией болванки по шаблону сохранён в этом модуле для
        # обратной совместимости и доступен напрямую через
        # ``_render_builder_mode()`` — кнопка «Загрузить шаблон» внутри
        # интерактивного редактора покрывает тот же сценарий.
        from gostforge.web.builder_editor import render_interactive_builder

        render_interactive_builder()
    else:
        profile_id = _render_sidebar(profiles)
        _render_main(profile_id)


# Streamlit запускает файл как ``__main__``. При обычном ``import`` модуля
# (например, из тестов или CLI) мы не должны вызывать render() — там нет
# контекста streamlit-сессии.
if __name__ == "__main__":
    render()
