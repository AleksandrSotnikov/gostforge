"""CLI-интерфейс gostforge."""

from __future__ import annotations

import sys
from pathlib import Path

import click

from gostforge import __version__
from gostforge.parser import parse_docx
from gostforge.profile import list_profiles, load_profile
from gostforge.validator import validate


@click.group()
@click.version_option(__version__, prog_name="gostforge")
def main() -> None:
    """gostforge — конструктор и нормоконтролёр документов по ГОСТу."""


@main.command()
@click.argument("path", type=click.Path(exists=True, path_type=Path))
@click.option("--profile", "-p", default="gost-7.32-2017", help="ID профиля для проверки")
@click.option("--report", "-r", type=click.Path(path_type=Path), help="Путь к файлу отчёта (.xlsx или .md)")
def check(path: Path, profile: str, report: Path | None) -> None:
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

    all_violations: dict[str, list] = {}
    for target in targets:
        click.echo(f"\n→ {target.name}")
        document = parse_docx(target)
        violations = validate(document, prof)
        all_violations[str(target)] = violations
        if not violations:
            click.echo("  ✓ нарушений не найдено")
            continue
        for v in violations:
            marker = {"error": "✗", "warning": "!", "info": "·"}.get(v.severity, "?")
            click.echo(f"  {marker} [{v.check_code}] {v.message}")

    if report:
        # TODO: записать отчёт в xlsx или markdown
        click.echo(f"\nОтчёт: {report} (не реализовано в фазе 0)")


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


if __name__ == "__main__":
    main()
