# Примеры использования gostforge

В этой директории — готовые примеры кода для основных сценариев.
Все скрипты можно запустить напрямую после `pip install -e ".[dev]"`.

## Файлы

- `check_one.py` — программная проверка одного `.docx` против профиля
- `fix_one.py` — программное применение автофиксов к `.docx`
- `build_coursework.py` — построение курсовой работы через `WorkBuilder`
- `build_with_figures.py` — конструктор с реальными изображениями и
  списками
- `annotate_one.py` — генерация аннотированного `.docx`
- `batch_check.py` — пакетная проверка папки и сводный отчёт

## Запуск

```bash
python examples/check_one.py path/to/work.docx
python examples/build_coursework.py
# и т.п.
```
