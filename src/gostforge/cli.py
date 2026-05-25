"""CLI-интерфейс gostforge."""

from __future__ import annotations

import subprocess
import sys
import time
from collections import defaultdict
from pathlib import Path

import click

from gostforge import __version__
from gostforge.exporter import export_docx
from gostforge.fixer import FixApplied
from gostforge.fixer import fix as run_fix
from gostforge.parser import parse_docx
from gostforge.profile import list_profiles, load_profile
from gostforge.validator import Violation, validate
from gostforge.validator.engine import registered_checks

# Цветовая палитра по серьёзности нарушения. Click автоматически отключает
# цвет, если stdout не терминал, так что отдельно проверять не нужно.
_SEVERITY_STYLE = {
    "error": ("ошибок", {"fg": "red", "bold": True}, "ERROR"),
    "warning": ("предупр.", {"fg": "yellow", "bold": True}, "WARN "),
    "info": ("инфо", {"fg": "cyan"}, "INFO "),
}


def _print_violations(target: Path, violations: list[Violation], quiet: bool) -> None:
    """Сгруппировать и красиво вывести violations для одного документа."""
    click.secho(f"\n>>> {target.name}", bold=True)

    if not violations:
        click.echo("  " + click.style("[OK]", fg="green", bold=True) + "  Нарушений не найдено")
        return

    by_severity: dict[str, list[Violation]] = defaultdict(list)
    for v in violations:
        by_severity[v.severity].append(v)

    counts = {sev: len(items) for sev, items in by_severity.items()}
    summary = ", ".join(
        f"{counts.get(sev, 0)} {label}"
        for sev, (label, _style, _short) in _SEVERITY_STYLE.items()
        if counts.get(sev, 0) > 0
    )
    click.echo(
        "  " + click.style("[FAIL]", fg="red", bold=True) + f"  Найдено нарушений: {len(violations)} ({summary})"
    )

    if quiet:
        codes = sorted({v.check_code for v in violations})
        click.echo("  Коды: " + ", ".join(codes))
        return

    for severity in ("error", "warning", "info"):
        items = by_severity.get(severity, [])
        if not items:
            continue
        _, style, short = _SEVERITY_STYLE[severity]
        for v in items:
            tag = click.style(f"[{short}]", **style)
            code = click.style(f"{v.check_code}", bold=True)
            click.echo(f"  {tag} {code}  {v.message}")
            if v.location:
                click.echo("       " + click.style(v.location, fg="bright_black"))
            if v.suggestion:
                click.echo("       " + click.style("-> " + v.suggestion, fg="green"))


def _write_markdown_report(
    results: dict[str, list[Violation]], output: Path, profile_id: str
) -> None:
    """Сохранить отчёт в Markdown с группировкой по файлам и категориям проверок."""
    lines: list[str] = []
    lines.append(f"# Отчёт нормоконтроля — профиль `{profile_id}`")
    lines.append("")

    total = sum(len(v) for v in results.values())
    files_with_violations = sum(1 for v in results.values() if v)
    lines.append(
        f"Проверено файлов: **{len(results)}**, с нарушениями: **{files_with_violations}**, "
        f"всего нарушений: **{total}**"
    )
    lines.append("")

    for file_path, violations in results.items():
        name = Path(file_path).name
        lines.append(f"## {name}")
        lines.append("")
        if not violations:
            lines.append("Нарушений не найдено.")
            lines.append("")
            continue

        # Группируем по префиксу кода (категория)
        by_category: dict[str, list[Violation]] = defaultdict(list)
        for v in violations:
            category = v.check_code.split(".")[0]
            by_category[category].append(v)

        for category in sorted(by_category):
            lines.append(f"### Категория {category}")
            lines.append("")
            lines.append("| Код | Серьёзность | Сообщение | Что исправить |")
            lines.append("| --- | --- | --- | --- |")
            for v in by_category[category]:
                msg = v.message.replace("|", "\\|")
                sug = v.suggestion.replace("|", "\\|") if v.suggestion else ""
                lines.append(f"| {v.check_code} | {v.severity} | {msg} | {sug} |")
            lines.append("")

    output.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_xlsx_report(
    results: dict[str, list[Violation]], output: Path, profile_id: str
) -> None:
    """Сохранить отчёт в Excel: один лист «Сводка» + по листу на каждый файл."""
    # openpyxl уже в зависимостях; импорт локально, чтобы CLI грузился без него
    # при использовании только Markdown-отчётов.
    from openpyxl import Workbook  # type: ignore[import-not-found]
    from openpyxl.styles import Alignment, Font, PatternFill  # type: ignore[import-not-found]

    wb = Workbook()
    summary = wb.active
    summary.title = "Сводка"

    bold = Font(bold=True)
    header_fill = PatternFill(start_color="DDDDDD", end_color="DDDDDD", fill_type="solid")
    wrap = Alignment(wrap_text=True, vertical="top")

    summary.append([f"Отчёт нормоконтроля — профиль {profile_id}"])
    summary["A1"].font = Font(bold=True, size=14)
    summary.append([])
    summary.append(["Файл", "Нарушений", "Ошибок", "Предупр.", "Инфо"])
    for cell in summary[3]:
        cell.font = bold
        cell.fill = header_fill

    for file_path, violations in results.items():
        name = Path(file_path).name
        total = len(violations)
        errs = sum(1 for v in violations if v.severity == "error")
        warns = sum(1 for v in violations if v.severity == "warning")
        infos = sum(1 for v in violations if v.severity == "info")
        summary.append([name, total, errs, warns, infos])

    for col_letter, width in zip("ABCDE", (40, 12, 10, 12, 8), strict=True):
        summary.column_dimensions[col_letter].width = width

    for file_path, violations in results.items():
        # Имя листа — обрезаем до 31 символа (ограничение Excel) и удаляем спецсимволы
        sheet_name = Path(file_path).stem[:28] + "…" if len(Path(file_path).stem) > 28 else Path(file_path).stem
        sheet_name = "".join(c for c in sheet_name if c not in "[]:*?/\\") or "файл"
        # Уникализация на случай совпадения имён
        base = sheet_name
        suffix = 1
        while sheet_name in wb.sheetnames:
            suffix += 1
            sheet_name = f"{base}_{suffix}"[:31]

        ws = wb.create_sheet(sheet_name)
        ws.append(["Код", "Серьёзность", "Сообщение", "Расположение", "Что исправить"])
        for cell in ws[1]:
            cell.font = bold
            cell.fill = header_fill

        for v in violations:
            ws.append([v.check_code, v.severity, v.message, v.location, v.suggestion])

        for col_letter, width in zip("ABCDE", (10, 14, 60, 40, 60), strict=True):
            ws.column_dimensions[col_letter].width = width
        for row in ws.iter_rows(min_row=2):
            for cell in row:
                cell.alignment = wrap

    wb.save(str(output))


def _write_report(
    results: dict[str, list[Violation]], output: Path, profile_id: str
) -> str:
    """Выбрать формат отчёта по расширению файла. Возвращает подпись формата."""
    suffix = output.suffix.lower()
    if suffix == ".xlsx":
        _write_xlsx_report(results, output, profile_id)
        return "Excel"
    if suffix in {".md", ".markdown", ""}:
        _write_markdown_report(results, output, profile_id)
        return "Markdown"
    # Неизвестное расширение — fallback на Markdown
    _write_markdown_report(results, output, profile_id)
    return "Markdown"


@click.group()
@click.version_option(__version__, prog_name="gostforge")
def main() -> None:
    """gostforge — конструктор и нормоконтролёр документов по ГОСТу."""


@main.command()
@click.argument("path", type=click.Path(exists=True, path_type=Path))
@click.option("--profile", "-p", default="gost-7.32-2017", help="ID профиля для проверки")
@click.option(
    "--report",
    "-r",
    type=click.Path(path_type=Path),
    help="Путь к отчёту. Формат определяется по расширению: .xlsx → Excel, .md → Markdown",
)
@click.option("--quiet", "-q", is_flag=True, help="Показать только сводку и список кодов")
def check(path: Path, profile: str, report: Path | None, quiet: bool) -> None:
    """Проверить документ или папку документов на соответствие профилю."""
    try:
        prof = load_profile(profile)
    except FileNotFoundError as e:
        click.echo(f"Ошибка: {e}", err=True)
        sys.exit(2)

    targets = [path] if path.is_file() else sorted(path.glob("*.docx"))
    if not targets:
        click.echo(f"Не найдено .docx файлов в {path}", err=True)
        sys.exit(1)

    # Сводка по проверкам: сколько включено в профиле, сколько реально есть в реестре
    enabled_codes = {c for c, cfg in prof.checks.items() if cfg.enabled}
    available = set(registered_checks())
    runnable = enabled_codes & available
    skipped = enabled_codes - available

    click.echo(
        click.style("Профиль: ", bold=True) + profile + f" (v{prof.version})"
    )
    click.echo(
        f"Будет запущено проверок: {len(runnable)} из {len(enabled_codes)} включённых"
    )
    if skipped:
        click.echo(
            click.style("  Не реализованы: ", fg="yellow")
            + ", ".join(sorted(skipped))
        )

    results: dict[str, list[Violation]] = {}
    total_errors = 0
    start = time.perf_counter()

    for target in targets:
        document = parse_docx(target)
        violations = validate(document, prof)
        results[str(target)] = violations
        total_errors += sum(1 for v in violations if v.severity == "error")
        _print_violations(target, violations, quiet)

    elapsed = time.perf_counter() - start
    click.echo(
        "\n"
        + click.style("Итого: ", bold=True)
        + f"{len(targets)} файл(ов), {sum(len(v) for v in results.values())} нарушений "
        + f"за {elapsed:.2f} с"
    )

    if report:
        fmt = _write_report(results, report, profile)
        click.echo(click.style(f"{fmt}-отчёт сохранён: {report}", fg="green"))

    if total_errors > 0:
        sys.exit(1)


def _print_fixes(applied: list[FixApplied]) -> None:
    """Вывести таблицу применённых автоправок."""
    if not applied:
        click.echo("  " + click.style("[OK]", fg="green", bold=True) + "  Ничего исправлять не пришлось")
        return

    click.echo(
        "  "
        + click.style("[FIX]", fg="cyan", bold=True)
        + f"  Применено правок: {len(applied)}"
    )
    for record in applied:
        code = click.style(record.fixer_code, bold=True)
        click.echo(f"    {code}  {record.description}")
        if record.location:
            click.echo("       " + click.style(record.location, fg="bright_black"))


@main.command("fix")
@click.argument("path", type=click.Path(exists=True, path_type=Path))
@click.option(
    "-o",
    "--output",
    type=click.Path(path_type=Path),
    required=True,
    help="Куда сохранить исправленный .docx.",
)
@click.option("--profile", "-p", default="gost-7.32-2017")
@click.option(
    "--only",
    multiple=True,
    help="Применить только указанные коды (можно указать несколько раз).",
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="Не записывать файл, только показать какие правки были бы применены.",  # noqa: RUF001
)
def fix_cmd(
    path: Path, output: Path, profile: str, only: tuple[str, ...], dry_run: bool
) -> None:
    """Применить безопасные автоисправления к .docx и записать результат в OUTPUT."""
    try:
        prof = load_profile(profile)
    except FileNotFoundError as e:
        click.echo(f"Ошибка: {e}", err=True)
        sys.exit(2)

    document = parse_docx(path)
    codes = list(only) if only else None
    applied = run_fix(document, prof, codes=codes)

    click.secho(f"\n>>> {path.name}", bold=True)
    _print_fixes(applied)

    if dry_run:
        click.echo(click.style("\n--dry-run: файл не записан.", fg="yellow"))
        return

    export_docx(document, prof, output)
    click.echo(click.style(f"\nИсправленный документ сохранён: {output}", fg="green"))  # noqa: RUF001


@main.group()
def profiles() -> None:
    """Управление профилями."""


@profiles.command("list")
def profiles_list() -> None:
    """Показать доступные профили."""
    for profile_id in list_profiles():
        click.echo(profile_id)


@profiles.command("show")
@click.argument("profile_id")
def profiles_show(profile_id: str) -> None:
    """Показать содержимое профиля."""
    try:
        prof = load_profile(profile_id)
    except FileNotFoundError as e:
        click.echo(f"Ошибка: {e}", err=True)
        sys.exit(2)
    click.echo(prof.model_dump_json(indent=2))


@profiles.command("validate")
@click.argument("path", type=click.Path(exists=True, path_type=Path))
def profiles_validate(path: Path) -> None:
    """Проверить YAML-файл профиля на корректность.

    Выводит сводку: число включённых проверок, сколько из них
    реализовано в текущем gostforge, нет ли ссылок на отсутствующие коды.
    """
    import yaml
    from gostforge.profile.schema import Profile

    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        click.echo(f"Ошибка парсинга YAML: {e}", err=True)
        sys.exit(2)

    try:
        prof = Profile(**data)
    except Exception as e:  # noqa: BLE001 — отображаем pydantic-ошибку как есть
        click.echo(f"Профиль не прошёл валидацию схемы:", err=True)
        click.echo(str(e), err=True)
        sys.exit(2)

    enabled_codes = {c for c, cfg in prof.checks.items() if cfg.enabled}
    available = set(registered_checks())
    runnable = enabled_codes & available
    skipped = enabled_codes - available

    click.echo(click.style(f"Профиль: {prof.id} v{prof.version}", bold=True))
    click.echo(f"  Включено проверок: {len(enabled_codes)}")
    click.echo(f"  Будет запущено: {len(runnable)}")
    if skipped:
        click.echo(
            click.style(f"  Не реализованы ({len(skipped)}): ", fg="yellow")
            + ", ".join(sorted(skipped))
        )
    if prof.extends:
        click.echo(f"  Наследует от: {prof.extends}")
    click.echo(click.style("[OK]", fg="green", bold=True) + " Файл валиден")


@profiles.command("diff")
@click.argument("profile_a")
@click.argument("profile_b")
def profiles_diff(profile_a: str, profile_b: str) -> None:
    """Сравнить два профиля по списку проверок и стилям.

    Выводит:
    - какие проверки включены только в A, только в B;
    - различия в параметрах общих проверок;
    - различия в основных полях styles.page/body.
    """
    try:
        a = load_profile(profile_a)
        b = load_profile(profile_b)
    except FileNotFoundError as e:
        click.echo(f"Ошибка: {e}", err=True)
        sys.exit(2)

    a_enabled = {c for c, cfg in a.checks.items() if cfg.enabled}
    b_enabled = {c for c, cfg in b.checks.items() if cfg.enabled}

    only_a = sorted(a_enabled - b_enabled)
    only_b = sorted(b_enabled - a_enabled)
    common = sorted(a_enabled & b_enabled)

    click.echo(click.style(f"=== {profile_a} vs {profile_b} ===", bold=True))

    if only_a:
        click.echo(click.style(f"\nТолько в {profile_a} ({len(only_a)}):", fg="cyan"))
        click.echo("  " + ", ".join(only_a))
    if only_b:
        click.echo(click.style(f"\nТолько в {profile_b} ({len(only_b)}):", fg="cyan"))
        click.echo("  " + ", ".join(only_b))

    # Отличия в параметрах общих проверок
    param_diffs = []
    for code in common:
        pa = a.checks[code].params
        pb = b.checks[code].params
        if pa != pb:
            param_diffs.append((code, pa, pb))
    if param_diffs:
        click.echo(click.style(f"\nРазные параметры ({len(param_diffs)}):", fg="yellow"))
        for code, pa, pb in param_diffs:
            click.echo(f"  {code}:")
            click.echo(f"    {profile_a}: {pa}")
            click.echo(f"    {profile_b}: {pb}")

    # Стили
    style_diffs = []
    if a.styles.page.margins_mm != b.styles.page.margins_mm:
        style_diffs.append(("margins_mm", a.styles.page.margins_mm, b.styles.page.margins_mm))
    for attr in ("font", "size_pt", "line_spacing", "first_line_indent_cm", "alignment"):
        va = getattr(a.styles.body, attr)
        vb = getattr(b.styles.body, attr)
        if va != vb:
            style_diffs.append((f"body.{attr}", va, vb))
    if style_diffs:
        click.echo(click.style(f"\nРазные стили ({len(style_diffs)}):", fg="yellow"))
        for name, va, vb in style_diffs:
            click.echo(f"  {name}: {profile_a}={va}, {profile_b}={vb}")

    if not only_a and not only_b and not param_diffs and not style_diffs:
        click.echo(click.style("\n[OK] Профили идентичны", fg="green"))


@main.command("checks")
def checks_list() -> None:
    """Показать список зарегистрированных проверок."""
    for code in registered_checks():
        click.echo(code)


@main.group()
def plugins() -> None:
    """Управление пользовательскими плагинами проверок."""


@plugins.command("list")
def plugins_list() -> None:
    """Показать загруженные плагины и предоставленные ими проверки."""
    from gostforge.plugins import (
        discover_plugin_files,
        load_plugins,
        plugins_dir,
    )
    from gostforge.validator.engine import _registry

    directory = plugins_dir()
    click.echo(f"Директория плагинов: {directory}")
    if not directory.exists():
        click.echo("  (не существует — создайте директорию для добавления плагинов)")
        return

    # Снимем снапшот текущего реестра, чтобы понять, какие проверки
    # добавились именно сейчас при загрузке плагинов.
    before = set(_registry)
    files = discover_plugin_files()
    load_plugins()
    after = set(_registry)
    added_codes = sorted(after - before)

    if not files:
        click.echo("  (плагинов не найдено)")
        return

    click.echo(f"\nНайдено файлов: {len(files)}")
    for f in files:
        click.echo(f"  - {f.name}")

    if added_codes:
        click.echo(f"\nДобавлены проверки: {', '.join(added_codes)}")


@plugins.command("dir")
def plugins_dir_cmd() -> None:
    """Показать путь к директории плагинов (или создать её)."""
    from gostforge.plugins import plugins_dir

    d = plugins_dir()
    if not d.exists():
        d.mkdir(parents=True, exist_ok=True)
        click.echo(f"Создана: {d}")
    else:
        click.echo(f"{d}")


@main.command()
@click.option("--port", default=8501, help="Порт (по умолчанию 8501).")
@click.option("--host", default="localhost", help="Адрес для bind (по умолчанию localhost).")
def ui(host: str, port: int) -> None:
    """Запустить веб-интерфейс на Streamlit."""
    try:
        import streamlit  # noqa: F401
    except ImportError:
        click.echo(
            "Streamlit не установлен. Установите gostforge[ui]:\n"
            "  pip install -e \".[ui]\"",
            err=True,
        )
        sys.exit(2)

    # Импортируем модуль приложения, чтобы получить путь до его файла.
    # Импорт обёрнут в try/except: в нём, помимо streamlit, могут быть
    # ошибки конфигурации, которые имеет смысл показать.
    import gostforge.web.app as app_module

    app_path = app_module.__file__
    cmd = [
        "streamlit",
        "run",
        str(app_path),
        "--server.address",
        host,
        "--server.port",
        str(port),
    ]
    subprocess.run(cmd, check=False)


@main.command()
@click.argument("path", type=click.Path(exists=True, path_type=Path))
def stats(path: Path) -> None:
    """Показать структурную статистику документа.

    Считает число разделов, параграфов, таблиц, рисунков, источников
    и слов. Не зависит от профиля и не выполняет проверки.
    """
    from gostforge.stats import compute_stats

    targets = [path] if path.is_file() else sorted(path.glob("*.docx"))
    if not targets:
        click.echo(f"Не найдено .docx файлов в {path}", err=True)
        sys.exit(1)

    for target in targets:
        document = parse_docx(target)
        s = compute_stats(document)
        click.secho(f"\n>>> {target.name}", bold=True)
        rows = [
            ("Секций вёрстки (PageSection)", s.page_sections),
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
        for label, value in rows:
            click.echo(f"  {label:<32} {value}")


@main.command()
@click.argument("path", type=click.Path(exists=True, path_type=Path))
@click.option(
    "-o",
    "--output",
    type=click.Path(path_type=Path),
    required=True,
    help="Куда сохранить .docx с inline-пометками.",
)
@click.option("--profile", "-p", default="gost-7.32-2017", help="ID профиля.")
@click.option(
    "--style",
    type=click.Choice(["inline", "comments"]),
    default="comments",
    show_default=True,
    help=(
        "Стиль аннотации: настоящие комментарии Word (comments) или "
        "inline-маркеры в тексте (inline)."
    ),
)
def annotate(path: Path, output: Path, profile: str, style: str) -> None:
    """Создать .docx с пометками о нарушениях.

    По умолчанию (``--style comments``) вставляются настоящие OOXML-комментарии
    Word: в документе создаётся часть ``word/comments.xml`` и в проблемных
    параграфах ставятся ``<w:commentRangeStart/End>`` + reference-run.
    Word и LibreOffice отображают это как боковые выноски.

    При ``--style inline`` используется старый режим: в начало проблемного
    параграфа вставляется маркер вида ``[F.01: <текст ошибки>]`` курсивом,
    красным цветом. Пометки уровня документа уходят в первый параграф.
    """
    from gostforge.annotator import annotate_docx
    try:
        prof = load_profile(profile)
    except FileNotFoundError as e:
        click.echo(f"Ошибка: {e}", err=True)
        sys.exit(2)
    n = annotate_docx(path, output, prof, style=style)  # type: ignore[arg-type]
    click.echo(f"Создано пометок: {n}")
    click.echo(f"Аннотированный документ сохранён: {output}")


@main.command()
@click.argument("path", type=click.Path(exists=True, path_type=Path))
@click.option(
    "-o",
    "--output",
    type=click.Path(path_type=Path),
    required=True,
    help="Куда сохранить .pdf.",
)
@click.option(
    "--timeout",
    type=float,
    default=60.0,
    help="Таймаут конвертации в секундах.",
)
def pdf(path: Path, output: Path, timeout: float) -> None:
    """Конвертировать .docx → .pdf через LibreOffice headless.

    Требует установленного LibreOffice. Полезно для генерации
    PDF-версии работы после применения автофиксов.
    """
    from gostforge.pdf_exporter import LibreOfficeNotFoundError, convert_to_pdf

    try:
        result = convert_to_pdf(path, output, timeout=timeout)
    except LibreOfficeNotFoundError as e:
        click.echo(f"Ошибка: {e}", err=True)
        sys.exit(3)
    except subprocess.TimeoutExpired:
        click.echo(
            f"Конвертация прервана по таймауту ({timeout}s)", err=True
        )
        sys.exit(4)
    except subprocess.CalledProcessError as e:
        click.echo(
            f"LibreOffice вернул ошибку (код {e.returncode}):", err=True
        )
        stderr = e.stderr or b""
        click.echo(stderr.decode("utf-8", errors="replace"), err=True)
        sys.exit(5)
    click.echo(f"PDF сохранён: {result}")


@main.command()
@click.argument("output", type=click.Path(path_type=Path))
@click.option(
    "--template",
    "-t",
    type=click.Choice(["coursework", "bachelor_thesis", "research_report"]),
    default="coursework",
    help="Шаблон работы.",
)
@click.option("--title", required=True, help="Название работы.")
@click.option("--author", default="", help="Автор.")
@click.option("--supervisor", default="", help="Руководитель.")
@click.option("--organization", default="", help="Организация.")
@click.option("--year", type=int, default=None, help="Год.")
@click.option("--profile", "-p", default="gost-7.32-2017", help="Профиль ГОСТа.")
def new(
    output: Path,
    template: str,
    title: str,
    author: str,
    supervisor: str,
    organization: str,
    year: int | None,
    profile: str,
) -> None:
    """Создать новую работу из шаблона.

    Пример: gostforge new my-coursework.docx --template coursework
        --title "Курсовая по нормоконтролю" --author "Иванов И. И." --year 2026
    """
    from gostforge.builder.templates import (
        bachelor_thesis_template,
        coursework_template,
        research_report_template,
    )

    if template == "coursework":
        builder = coursework_template(
            title=title,
            author=author,
            supervisor=supervisor,
            organization=organization,
            year=year,
        )
    elif template == "bachelor_thesis":
        builder = bachelor_thesis_template(
            title=title,
            author=author,
            supervisor=supervisor,
            organization=organization,
            year=year,
        )
    else:  # research_report
        builder = research_report_template(
            title=title,
            year=year,
            organization=organization,
        )

    try:
        builder.save(output, profile=profile)
    except FileNotFoundError as e:
        click.echo(f"Профиль не найден: {e}", err=True)
        sys.exit(2)
    except ValueError as e:
        click.echo(f"Документ не прошёл валидацию: {e}", err=True)
        sys.exit(3)

    click.echo(f"Создан файл: {output}")
    click.echo("Откройте его в Word / LibreOffice и заполните плейсхолдеры.")


if __name__ == "__main__":
    main()
