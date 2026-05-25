# Конструктор работ

Модуль `gostforge.builder` — высокоуровневый fluent-API над моделью документа.
Студент описывает работу декларативно: разделы, параграфы, таблицы, рисунки,
список литературы. На выходе — `.docx`, который сразу проходит профильные
проверки нормоконтроля.

При сохранении конструктор автоматически:

- ставит правильные поля страницы, шрифт и межстрочный интервал (по профилю);
- проставляет `page_break_before=True` у первого параграфа каждого раздела
  верхнего уровня (кроме самого первого);
- добавляет футер с полем `PAGE` (номер страницы);
- ставит `pgNumType.start = 3`;
- собирает список литературы в `Document.bibliography`.

## 1. Минимальный документ

```python
from gostforge.builder import work

(
    work("Курсовая по нормоконтролю", author="Иванов И. И.", year=2026)
    .section("Введение")
        .paragraph("Актуальность темы заключается в ...")
        .paragraph("Целью работы является ...")
    .section("Глава 1. Анализ предметной области")
        .subsection("1.1 Обзор существующих решений")
            .paragraph("В настоящее время существует множество подходов ...")
        .subsection("1.2 Постановка задачи")
            .paragraph("Сформулируем задачу следующим образом ...")
    .section("Заключение")
        .paragraph("В ходе работы было ...")
    .section("Список использованных источников")
        .reference("Иванов И. И. Программирование. — М. : Наука, 2023. — 320 с.")
    .save("coursework.docx", profile="gost-7.32-2017")
)
```

`save()` сам прогоняет результат через валидатор и поднимает `ValueError`,
если есть error-уровневые нарушения. Если нужна только модель (без записи
файла) — используйте `.build()`:

```python
builder = work("Курсовая").section("Введение").paragraph("Текст")
document = builder.build()   # gostforge.model.Document
```

## 2. Шаблоны

В `gostforge.builder.templates` лежат скелеты с уже добавленными
обязательными разделами и плейсхолдером `<Заполните этот раздел>`:

```python
from gostforge.builder.templates import (
    coursework_template,
    bachelor_thesis_template,
    research_report_template,
)

builder = coursework_template(
    title="Курсовая по нормоконтролю",
    author="Иванов И. И.",
    year=2026,
)
builder.save("coursework.docx", profile="gost-7.32-2017")
```

Шаблоны возвращают `WorkBuilder`, в который можно продолжать добавлять
разделы/параграфы перед `save()`.

## 3. Команда `gostforge new`

CLI-обёртка для шаблонов:

```bash
gostforge new my-coursework.docx \
    --template coursework \
    --title "Курсовая по нормоконтролю" \
    --author "Иванов И. И." \
    --year 2026
```

Доступные значения `--template`: `coursework`, `bachelor_thesis`,
`research_report`. После создания файла откройте его в Word/LibreOffice и
замените плейсхолдеры реальным текстом.
