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
    help="Путь к Markdown-отчёту (рекомендуется .md)",
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
        _write_markdown_report(results, report, profile)
        click.echo(click.style(f"Отчёт сохранён: {report}", fg="green"))

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
