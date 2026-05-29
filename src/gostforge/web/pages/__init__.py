"""Страницы Streamlit multi-page приложения.

Каждый модуль здесь — тонкая обёртка над существующим render-функционалом
(`dashboard.render_dashboard`, `builder_editor.render_interactive_builder`,
и т. д.). Все они регистрируются в `web.app.render()` через `st.Page` +
`st.navigation`, что даёт URL routing и браузерную историю.

Импорты внутри функций (lazy): на первом запуске Streamlit грузит только
активную страницу — это заметно ускоряет старт.
"""
