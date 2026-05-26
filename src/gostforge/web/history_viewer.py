"""Streamlit-страница «История и обсуждение».

Четвёртый режим веб-приложения (поверх Нормоконтроля, Конструктора и
Документации): просмотр submission-ов из локальной БД + лента
комментариев руководитель ↔ студент.

Структура:

* Sidebar — фильтры (filename, скрыть resolved, ввод автора + роли
  по умолчанию).
* Главная область — список submission-ов с цветным summary и
  бейджем «N незакрытых». Клик по записи раскрывает детали:
  список violations + лента комментариев + форма добавления нового.

Идёт напрямую через ``gostforge.db.*`` без HTTP-вызовов (UI и БД
в одном процессе). Это даёт мгновенный отклик и не зависит от
наличия REST API.
"""

from __future__ import annotations

from typing import Any

try:
    import streamlit as st
except ImportError as exc:  # pragma: no cover
    raise ImportError(
        'Установите gostforge[ui] для веб-интерфейса: pip install -e ".[ui]"'
    ) from exc


_ROLE_OPTIONS = ("anonymous", "student", "supervisor")
_ROLE_LABELS: dict[str, str] = {
    "supervisor": "Руководитель",
    "student": "Студент",
    "anonymous": "Аноним",
}
_ROLE_COLORS: dict[str, str] = {
    "supervisor": "#d946ef",  # magenta-pink
    "student": "#3b82f6",  # blue
    "anonymous": "#6b7280",  # gray
}


# --- State -----------------------------------------------------------------


def _ensure_state() -> None:
    """Положить дефолтное состояние истории в session_state, если нет."""
    ss = st.session_state
    if "history_filename_filter" not in ss:
        ss["history_filename_filter"] = ""
    if "history_only_unresolved" not in ss:
        ss["history_only_unresolved"] = False
    if "history_default_author" not in ss:
        import os

        ss["history_default_author"] = os.environ.get("GOSTFORGE_DEFAULT_AUTHOR", "")
    if "history_default_role" not in ss:
        ss["history_default_role"] = "anonymous"
    if "history_selected_id" not in ss:
        ss["history_selected_id"] = None


# --- DB-helpers (тонкие обёртки для UI с graceful fallback) ----------------


def _try_list_submissions(*, filename: str | None, limit: int = 100) -> list[Any]:
    """Безопасный list_submissions. На ошибках возвращает []."""
    try:
        from gostforge.db import get_connection, list_submissions

        with get_connection() as conn:
            return list_submissions(conn, limit=limit, filename=filename)
    except Exception:  # pragma: no cover
        return []


def _try_get_submission(submission_id: int) -> Any | None:
    """Безопасный get_submission."""
    try:
        from gostforge.db import get_connection, get_submission

        with get_connection() as conn:
            return get_submission(conn, submission_id)
    except Exception:  # pragma: no cover
        return None


def _try_list_comments(submission_id: int, *, include_resolved: bool = True) -> list[Any]:
    """Безопасный list_comments."""
    try:
        from gostforge.db import get_connection, list_comments

        with get_connection() as conn:
            return list_comments(
                conn,
                submission_id=submission_id,
                include_resolved=include_resolved,
            )
    except Exception:  # pragma: no cover
        return []


def _try_unresolved_count(submission_id: int) -> int:
    """Безопасный count_unresolved."""
    try:
        from gostforge.db import count_unresolved_comments, get_connection

        with get_connection() as conn:
            return count_unresolved_comments(conn, submission_id)
    except Exception:  # pragma: no cover
        return 0


# --- Действия (мутации БД) -------------------------------------------------


def _add_comment_action(
    *, submission_id: int, body: str, author: str, role: str
) -> tuple[bool, str]:
    """Добавить комментарий. Вернуть (ok, message)."""
    if not body or not body.strip():
        return False, "Текст комментария не может быть пустым."
    try:
        from gostforge.db import add_comment, get_connection

        with get_connection() as conn:
            add_comment(
                conn,
                submission_id=submission_id,
                body=body,
                author=author,
                role=role,
            )
    except ValueError as exc:
        return False, str(exc)
    except Exception as exc:  # pragma: no cover
        return False, f"Ошибка БД: {exc}"
    return True, "Комментарий добавлен."


def _resolve_comment_action(comment_id: int, *, resolved: bool) -> bool:
    try:
        from gostforge.db import get_connection, resolve_comment

        with get_connection() as conn:
            return resolve_comment(conn, comment_id, resolved=resolved)
    except Exception:  # pragma: no cover
        return False


def _delete_comment_action(comment_id: int) -> bool:
    try:
        from gostforge.db import delete_comment, get_connection

        with get_connection() as conn:
            return delete_comment(conn, comment_id)
    except Exception:  # pragma: no cover
        return False


# --- UI --------------------------------------------------------------------


def _render_sidebar() -> None:
    """Фильтры и identity (автор/роль по умолчанию) в sidebar."""
    st.sidebar.subheader("Фильтры истории")
    st.session_state["history_filename_filter"] = st.sidebar.text_input(
        "Имя файла (точное совпадение)",
        value=st.session_state["history_filename_filter"],
        help="Оставьте пустым, чтобы показать все submission-ы.",
    )
    st.session_state["history_only_unresolved"] = st.sidebar.checkbox(
        "Только с открытыми вопросами",
        value=st.session_state["history_only_unresolved"],
    )

    st.sidebar.subheader("Я — автор комментариев")
    st.session_state["history_default_author"] = st.sidebar.text_input(
        "Имя/email",
        value=st.session_state["history_default_author"],
        help=(
            "Используется как автор новых комментариев. Можно также "
            "задать env GOSTFORGE_DEFAULT_AUTHOR — оно подставляется "
            "по умолчанию."
        ),
    )
    role_index = list(_ROLE_OPTIONS).index(st.session_state["history_default_role"])
    st.session_state["history_default_role"] = st.sidebar.selectbox(
        "Роль",
        options=list(_ROLE_OPTIONS),
        index=role_index,
        format_func=lambda r: _ROLE_LABELS[r],
    )


def _render_submissions_list() -> None:
    """Главный список submission-ов с кнопками-открывалками."""
    filename = st.session_state["history_filename_filter"].strip() or None
    items = _try_list_submissions(filename=filename)

    if st.session_state["history_only_unresolved"]:
        items = [s for s in items if _try_unresolved_count(s.id) > 0]

    if not items:
        st.info(
            "История пуста. Запустите проверку в режиме «Нормоконтроль» "
            "или через `gostforge check ...` — submission появится здесь."
        )
        return

    st.markdown(f"**Найдено submission-ов:** {len(items)}")

    for sub in items:
        unresolved = _try_unresolved_count(sub.id)
        badge = f"  :red-background[{unresolved} открытых]" if unresolved > 0 else ""
        title = (
            f"#{sub.id}  ·  {sub.filename}  ·  "
            f":red[{sub.error_count}e] / "
            f":orange[{sub.warning_count}w] / "
            f":blue[{sub.info_count}i]"
            f"  ·  _{sub.created_at}_{badge}"
        )
        with st.expander(title, expanded=False):
            _render_submission_panel(sub)


def _render_submission_panel(sub: Any) -> None:
    """Подробности одного submission: violations + обсуждение."""
    st.caption(f"Профиль: `{sub.profile_id}`")

    tab_v, tab_c = st.tabs(["Нарушения", f"Обсуждение ({_try_unresolved_count(sub.id)} открыто)"])
    with tab_v:
        _render_violations(sub.id)
    with tab_c:
        _render_comments_thread(sub.id)


def _render_violations(submission_id: int) -> None:
    """Список нарушений (read-only)."""
    sub = _try_get_submission(submission_id)
    if sub is None or not sub.violations:
        st.success("Нарушений нет — работа соответствует профилю.")
        return
    severity_color = {"error": "red", "warning": "orange", "info": "blue"}
    for v in sub.violations:
        color = severity_color.get(v.severity, "gray")
        st.markdown(f":{color}[**{v.severity.upper()}**]  `{v.code}`  —  {v.message}")
        if v.location:
            st.caption(v.location)
        if v.suggestion:
            st.markdown(f"→ _{v.suggestion}_")
        st.divider()


def _render_comments_thread(submission_id: int) -> None:
    """Лента комментариев + форма ответа."""
    comments = _try_list_comments(submission_id, include_resolved=True)
    if not comments:
        st.caption("Комментариев ещё нет. Будьте первым.")
    else:
        for c in comments:
            _render_comment_row(c)
    st.markdown("---")
    _render_add_comment_form(submission_id)


def _render_comment_row(comment: Any) -> None:
    """Одна запись в ленте обсуждения + кнопки управления."""
    role = comment.role
    color = _ROLE_COLORS.get(role, "#6b7280")
    label = _ROLE_LABELS.get(role, role)
    status = "✓" if comment.resolved else "●"
    status_color = "#10b981" if comment.resolved else "#eab308"
    author = comment.author or "—"

    st.markdown(
        f"<div style='padding: 8px 12px; border-left: 3px solid {color}; "
        f"margin-bottom: 8px; background-color: rgba(0,0,0,0.02);'>"
        f"<span style='color: {color}; font-weight: 600;'>{label}</span>"
        f" · <code>{author}</code> · "
        f"<span style='color: {status_color};'>{status}</span> · "
        f"<small><code>{comment.created_at}</code> #{comment.id}</small>"
        f"<br><br>{_escape_html(comment.body)}"
        f"</div>",
        unsafe_allow_html=True,
    )
    cols = st.columns([1, 1, 1, 6])
    if comment.resolved:
        if cols[0].button("Переоткрыть", key=f"reopen_{comment.id}"):
            _resolve_comment_action(comment.id, resolved=False)
            st.rerun()
    else:
        if cols[0].button("Закрыть", key=f"resolve_{comment.id}"):
            _resolve_comment_action(comment.id, resolved=True)
            st.rerun()
    if cols[1].button("Удалить", key=f"del_{comment.id}"):
        _delete_comment_action(comment.id)
        st.rerun()


def _render_add_comment_form(submission_id: int) -> None:
    """Форма «добавить комментарий»."""
    with st.form(key=f"add_comment_{submission_id}", clear_on_submit=True):
        body = st.text_area(
            "Новый комментарий",
            placeholder="Опишите проблему или ответьте на замечание...",
            height=100,
        )
        cols = st.columns([3, 2])
        author = cols[0].text_input(
            "Автор",
            value=st.session_state["history_default_author"],
        )
        role_idx = list(_ROLE_OPTIONS).index(st.session_state["history_default_role"])
        role = cols[1].selectbox(
            "Роль",
            options=list(_ROLE_OPTIONS),
            index=role_idx,
            format_func=lambda r: _ROLE_LABELS[r],
        )
        submitted = st.form_submit_button("Отправить")
        if submitted:
            ok, msg = _add_comment_action(
                submission_id=submission_id,
                body=body,
                author=author,
                role=role,
            )
            if ok:
                st.success(msg)
                st.rerun()
            else:
                st.error(msg)


def _escape_html(text: str) -> str:
    """Минимальный HTML-escape для безопасной вставки в st.markdown(html=True).

    Защищает от случайной (или намеренной) разметки внутри текста
    комментария — мы используем unsafe_allow_html для своей рамки,
    но содержимое комментария должно идти как plain text.
    """
    return (
        text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\n", "<br>")
    )


# --- Главная функция режима ------------------------------------------------


def render_history_viewer() -> None:
    """Главная функция режима «История и обсуждение»."""
    _ensure_state()

    st.title("История проверок и обсуждение")
    st.caption(
        "Все submission-ы из локальной БД с цветным summary и лентой "
        "комментариев руководитель ↔ студент. Хранится в "
        "`~/.gostforge/gostforge.db` (или путь из env GOSTFORGE_DB_PATH)."
    )

    _render_sidebar()
    _render_submissions_list()


__all__ = ["render_history_viewer"]
