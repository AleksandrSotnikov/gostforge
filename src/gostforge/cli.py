"""CLI-интерфейс gostforge."""

from __future__ import annotations

import sys
import time
from collections import defaultdict
from pathlib import Path

import click

from gostforge import __version__
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


@main.command("checks")
def checks_list() -> None:
    """Показать список зарегистрированных проверок."""
    for code in registered_checks():
        click.echo(code)


if __name__ == "__main__":
    main()
