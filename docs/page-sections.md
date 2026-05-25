# Колонтитулы и секции

Самая сложная часть генерации `.docx`. Этот документ описывает модель PageSection в `gostforge` и её отображение в OOXML.

## Принципиальное разделение

В OOXML «секция» (`<w:sectPr>`) — это блок страничной вёрстки с собственными полями, ориентацией и колонтитулами. Студенты обычно называют «разделом» главу работы (1, 2, 3) — это **другое**. Чтобы не путаться, в `gostforge`:

- **`PageSection`** — секция вёрстки. У неё свои поля, колонтитулы, правила нумерации страниц.
- **`Section` (LogicalSection)** — раздел работы по содержанию (введение, глава 1, заключение). Это контент.

Один PageSection может содержать много LogicalSection. Одно приложение — отдельный PageSection.

## Типовая структура для дипломной работы

| № | PageSection | Колонтитул | Номер страницы |
|---|---|---|---|
| 1 | Титульный лист | пусто | не показан, в счёт |
| 2 | Задание, реферат | пусто | не показан, в счёт |
| 3 | Содержание, список сокращений | арабская | показан с 3-й страницы |
| 4 | Основная часть (введение + главы + заключение + литература) | арабская | продолжает |
| 5 | Приложение А | «ПРИЛОЖЕНИЕ А» вверху | продолжает |
| 6 | Приложение Б | «ПРИЛОЖЕНИЕ Б» вверху | продолжает |

Эта структура задаётся профилем в `sections_template`. Конструктор использует её как стартовый шаблон нового проекта.

## Модель PageSection

```python
@dataclass
class PageSection:
    id: str
    name: str
    type: Literal["title", "frontmatter", "main", "appendix", "custom"]
    page: PageGeometry  # размер бумаги, поля, ориентация
    header: HeaderConfig | None
    footer: HeaderConfig | None
    page_numbering: PageNumberingConfig
    link_to_previous: bool = False  # ВСЕГДА явно
    different_first_page: bool = False
    different_odd_even: bool = False
    logical_sections: list[LogicalSection] = field(default_factory=list)


@dataclass
class HeaderConfig:
    default: ContentTemplate
    first_page: ContentTemplate | None = None
    even_page: ContentTemplate | None = None


@dataclass
class ContentTemplate:
    left: InlineContent | None = None
    center: InlineContent | None = None
    right: InlineContent | None = None


@dataclass
class PageNumberingConfig:
    visible: bool = True
    format: Literal["arabic", "roman", "uppercase_letter"] = "arabic"
    start_mode: Literal["continue", "restart", "start_at"] = "continue"
    start_value: int | None = None
```

## Плейсхолдеры в шаблонах колонтитулов

`ContentTemplate` поддерживает плейсхолдеры, которые на экспорте превращаются в OOXML-поля:

| Плейсхолдер | OOXML-поле | Что показывает |
|---|---|---|
| `{page}` | `PAGE` | Номер текущей страницы |
| `{numpages}` | `NUMPAGES` | Общее число страниц |
| `{appendix_letter}` | `STYLEREF "Appendix"` | Буква текущего приложения |
| `{section_title}` | `STYLEREF "Heading 1"` | Название текущего раздела |
| `{chapter_title}` | `STYLEREF "Heading 2"` | Название текущей главы |
| `{date}` | `DATE` | Дата (генерируется при открытии) |
| `{author}` | static | Из метаданных проекта |
| `{short_title}` | static | Короткое название работы |

## Реализация в OOXML

### sectPr с правильными ссылками

```xml
<w:sectPr>
  <w:headerReference w:type="default" r:id="rIdH3"/>
  <w:headerReference w:type="first" r:id="rIdH3f"/>
  <w:footerReference w:type="default" r:id="rIdF3"/>
  <w:pgSz w:w="11906" w:h="16838"/>
  <w:pgMar w:top="1134" w:right="850" w:bottom="1134" w:left="1701"
           w:header="708" w:footer="708" w:gutter="0"/>
  <w:pgNumType w:start="3" w:fmt="decimal"/>
  <w:titlePg/>  <!-- если different_first_page -->
</w:sectPr>
```

### Отдельные header/footer-part для каждой секции

`word/header1.xml`, `word/header2.xml`, ... — по одному файлу на каждую уникальную конфигурацию колонтитула. Регистрируются в `[Content_Types].xml` и в `word/_rels/document.xml.rels`.

### Разрыв link-to-previous

По умолчанию Word наследует колонтитулы предыдущей секции. У `gostforge` каждая `PageSection` имеет собственный набор header/footer-part, и ссылки указывают именно на них.

В `python-docx` это `section.header.is_linked_to_previous = False`, но операция нестабильна — надёжнее работать с `sectPr` через lxml напрямую.

### Поле PAGE

```xml
<w:p>
  <w:pPr><w:jc w:val="center"/></w:pPr>
  <w:r><w:fldChar w:fldCharType="begin"/></w:r>
  <w:r><w:instrText xml:space="preserve">PAGE \* MERGEFORMAT</w:instrText></w:r>
  <w:r><w:fldChar w:fldCharType="separate"/></w:r>
  <w:r><w:t>1</w:t></w:r>
  <w:r><w:fldChar w:fldCharType="end"/></w:r>
</w:p>
```

### Поле STYLEREF для названия приложения

В нижнем колонтитуле приложения «ПРИЛОЖЕНИЕ А» обновляется автоматически:

```xml
<w:r><w:fldChar w:fldCharType="begin"/></w:r>
<w:r><w:instrText xml:space="preserve">STYLEREF "Appendix Title" \* MERGEFORMAT</w:instrText></w:r>
<w:r><w:fldChar w:fldCharType="separate"/></w:r>
<w:r><w:t>А</w:t></w:r>
<w:r><w:fldChar w:fldCharType="end"/></w:r>
```

Для этого нужен стиль `Appendix Title`, применённый к заголовкам приложений.

## Валидация колонтитулов (K-проверки)

В режиме нормоконтроля парсер извлекает структуру PageSection из чужого `.docx`, валидатор сверяет:

- `K.01` — Число и типы PageSection совпадают с шаблоном профиля.
- `K.02` — На титульном листе нет видимого номера страницы.
- `K.03` — Номер на первой странице с нумерацией = ожидаемое значение.
- `K.04` — Между основной частью и литературой нумерация не сбрасывается.
- `K.05` — В приложении присутствует верхний колонтитул с буквой.
- `K.06` — Ссылки на header/footer в каждой секции не указывают на чужие part-файлы (link-to-previous разорван корректно).

## Известные подводные камни

1. **`python-docx` теряет колонтитулы при `add_section()`** — приходится копировать `sectPr` руками.
2. **`titlePg` без сопровождающего header-part первой страницы** — Word всё равно показывает default header.
3. **`STYLEREF` к стилю, которого нет** — Word показывает ошибку поля при открытии.
4. **`pgNumType w:start="0"`** — нестандартно, многие парсеры падают; используем минимум 1.
5. **Чётные/нечётные колонтитулы (`evenAndOddHeaders`)** — настройка живёт в `settings.xml`, не в секции; легко забыть.
