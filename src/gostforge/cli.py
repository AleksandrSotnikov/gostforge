"""CLI-интерфейс gostforge."""

from __future__ import annotations

import json
import os
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
@click.option(
    "--no-record",
    is_flag=True,
    help="Не записывать результаты проверки в локальную БД истории.",
)
def check(
    path: Path, profile: str, report: Path | None, quiet: bool, no_record: bool
) -> None:
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

    if not no_record:
        _record_check_results(results, profile)

    if report:
        fmt = _write_report(results, report, profile)
        click.echo(click.style(f"{fmt}-отчёт сохранён: {report}", fg="green"))

    if total_errors > 0:
        sys.exit(1)


def _record_check_results(
    results: dict[str, list[Violation]], profile_id: str
) -> None:
    """Сохранить результаты прогона в локальную БД истории.

    Ошибки БД (нет места, нет прав) логируются и проглатываются —
    они не должны ломать основной workflow проверки.
    """
    try:
        from gostforge.db import get_connection, record_submission
    except ImportError:
        return
    try:
        with get_connection() as conn:
            for target, violations in results.items():
                record_submission(
                    conn,
                    filename=Path(target).name,
                    profile_id=profile_id,
                    violations=violations,
                )
    except Exception as exc:  # pragma: no cover — не валим CLI на БД
        click.echo(
            click.style(f"Не удалось записать в БД истории: {exc}", fg="yellow"),
            err=True,
        )


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

    # Передаём source_docx=path, чтобы рисунки из исходного .docx
    # переносились в выходной как реальные изображения (а не placeholder).
    export_docx(document, prof, output, source_docx=path)
    click.echo(click.style(f"\nИсправленный документ сохранён: {output}", fg="green"))  # noqa: RUF001


@main.group()
def profiles() -> None:
    """Управление профилями."""


@profiles.command("list")
def profiles_list() -> None:
    """Показать доступные профили (builtin + установленные локально)."""
    from gostforge.profile import is_custom_profile

    for profile_id in list_profiles():
        if is_custom_profile(profile_id):
            click.echo(f"{profile_id}  " + click.style("[custom]", fg="green"))
        else:
            click.echo(f"{profile_id}  " + click.style("[builtin]", fg="cyan"))


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


@profiles.command("install")
@click.argument("path", type=click.Path(exists=True, path_type=Path))
@click.option(
    "--overwrite",
    is_flag=True,
    help="Перезаписать, если профиль с таким id уже установлен.",
)
def profiles_install(path: Path, overwrite: bool) -> None:
    """Установить YAML-профиль в локальный реестр.

    После установки профиль доступен всем командам по своему id
    (gostforge check ... --profile <id>, REST API и т.д.). YAML
    валидируется до записи в БД — неверная схема отвергается с
    понятной ошибкой.
    """
    try:
        from gostforge.db import get_connection, install_profile
    except ImportError as exc:  # pragma: no cover — db в stdlib
        click.echo(f"Ошибка импорта модуля БД: {exc}", err=True)
        sys.exit(2)

    yaml_content = path.read_text(encoding="utf-8")
    try:
        with get_connection() as conn:
            rec = install_profile(
                conn,
                yaml_content=yaml_content,
                source=str(path.resolve()),
                overwrite=overwrite,
            )
    except ValueError as exc:
        click.echo(click.style(f"Ошибка: {exc}", fg="red"), err=True)
        sys.exit(2)

    click.echo(
        click.style("Профиль установлен:", fg="green", bold=True)
        + f" {rec.profile_id}  ({rec.name}, v{rec.version})"
    )
    click.echo(f"  Источник:    {rec.source}")
    click.echo(f"  Установлен:  {rec.installed_at}")
    click.echo(
        "\nИспользовать: gostforge check FILE.docx --profile "
        + rec.profile_id
    )


@profiles.command("uninstall")
@click.argument("profile_id")
def profiles_uninstall(profile_id: str) -> None:
    """Удалить custom-профиль из локального реестра.

    Builtin-профили (gost-7.32-2017 и т. п.) удалить нельзя — они
    лежат в каталоге пакета, не в БД. Команда даст ошибку, если
    профиль не установлен локально.
    """
    try:
        from gostforge.db import get_connection, uninstall_profile
    except ImportError as exc:  # pragma: no cover
        click.echo(f"Ошибка импорта модуля БД: {exc}", err=True)
        sys.exit(2)

    with get_connection() as conn:
        removed = uninstall_profile(conn, profile_id)
    if removed:
        click.echo(
            click.style(f"Профиль удалён: {profile_id}", fg="green", bold=True)
        )
    else:
        click.echo(
            click.style(
                f"Профиль {profile_id!r} не установлен в локальный реестр.",
                fg="yellow",
            ),
            err=True,
        )
        sys.exit(1)


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
@click.option("--host", default="127.0.0.1", help="Адрес для bind (по умолчанию 127.0.0.1).")
@click.option("--port", default=8000, help="Порт (по умолчанию 8000).")
@click.option(
    "--reload", is_flag=True, help="Включить hot-reload для разработки."
)
def serve(host: str, port: int, reload: bool) -> None:
    """Запустить REST API gostforge на FastAPI/uvicorn.

    Опциональная зависимость: pip install -e ".[api]". Полный список
    endpoints — docs/phase-3-api-spec.md. По умолчанию слушает только
    127.0.0.1 (запуск из публичной сети — за reverse-proxy с auth).
    """
    try:
        import uvicorn  # noqa: F401
    except ImportError:
        click.echo(
            "FastAPI/uvicorn не установлены. Установите gostforge[api]:\n"
            '  pip install -e ".[api]"',
            err=True,
        )
        sys.exit(2)

    import uvicorn

    uvicorn.run(
        "gostforge.api.app:app",
        host=host,
        port=port,
        reload=reload,
    )


@main.command()
@click.option("--limit", "-n", default=20, help="Сколько последних записей показать.")
@click.option(
    "--filename", "-f", default=None, help="Фильтр по имени файла (точное совпадение)."
)
@click.option(
    "--id",
    "submission_id",
    type=int,
    default=None,
    help="Показать детали одного submission по id.",
)
def history(limit: int, filename: str | None, submission_id: int | None) -> None:
    """История проверок из локальной БД.

    Без параметров показывает последние ``--limit`` записей с
    summary по severity. С ``--id`` показывает детали конкретного
    submission со списком всех найденных нарушений.

    БД лежит в ``~/.gostforge/gostforge.db`` (переопределяется env
    ``GOSTFORGE_DB_PATH``) и автоматически создаётся при первом
    ``gostforge check``.
    """
    try:
        from gostforge.db import get_connection, get_submission, list_submissions
    except ImportError as exc:  # pragma: no cover — db в stdlib
        click.echo(f"Не удалось импортировать модуль БД: {exc}", err=True)
        sys.exit(2)

    with get_connection() as conn:
        if submission_id is not None:
            sub = get_submission(conn, submission_id)
            if sub is None:
                click.echo(f"Submission #{submission_id} не найден.", err=True)
                sys.exit(1)
            _print_submission_details(sub)
            return

        items = list_submissions(conn, limit=limit, filename=filename)
        if not items:
            click.echo("История пуста. Запустите 'gostforge check ...' для первой записи.")
            return

        click.echo(click.style(f"Последние {len(items)} проверок:\n", bold=True))
        for s in items:
            severity_str = (
                f"{click.style(str(s.error_count), fg='red')}e/"
                f"{click.style(str(s.warning_count), fg='yellow')}w/"
                f"{click.style(str(s.info_count), fg='cyan')}i"
            )
            click.echo(
                f"  #{s.id:>4}  {s.created_at}  {severity_str}  "
                f"[{s.profile_id}]  {s.filename}"
            )
        click.echo(
            "\nДля деталей: gostforge history --id <N>"
        )


@main.group()
def comment() -> None:
    """Комментарии к submission-ам (совместная работа)."""


def _default_author() -> str:
    """Имя автора по умолчанию — из env или getpass.getuser()."""
    env = os.environ.get("GOSTFORGE_DEFAULT_AUTHOR", "").strip()
    if env:
        return env
    try:
        import getpass

        return getpass.getuser()
    except Exception:  # pragma: no cover - graceful
        return ""


@comment.command("add")
@click.argument("submission_id", type=int)
@click.argument("body")
@click.option(
    "--author",
    default=None,
    help="Имя автора. Если не задано — берётся из env GOSTFORGE_DEFAULT_AUTHOR "
    "или getpass.getuser().",
)
@click.option(
    "--role",
    type=click.Choice(["student", "supervisor", "anonymous"]),
    default="anonymous",
    help="Роль автора (student/supervisor/anonymous).",
)
def comment_add(
    submission_id: int, body: str, author: str | None, role: str
) -> None:
    """Добавить комментарий к submission.

    Пример:

        gostforge comment add 42 "Переделай введение" --role supervisor

    Если submission_id не существует или body пустой — выходим с
    кодом 2 + сообщением.
    """
    from gostforge.db import add_comment, get_connection

    final_author = author if author is not None else _default_author()
    try:
        with get_connection() as conn:
            c = add_comment(
                conn,
                submission_id=submission_id,
                body=body,
                author=final_author,
                role=role,
            )
    except ValueError as exc:
        click.echo(click.style(f"Ошибка: {exc}", fg="red"), err=True)
        sys.exit(2)

    click.echo(
        click.style("Комментарий добавлен:", fg="green", bold=True)
        + f" #{c.id} к submission #{c.submission_id}"
    )
    click.echo(f"  Автор: {c.author or '—'}  [{c.role}]")
    click.echo(f"  Время: {c.created_at}")


@comment.command("list")
@click.argument("submission_id", type=int)
@click.option(
    "--unresolved",
    is_flag=True,
    help="Показать только незакрытые комментарии.",
)
def comment_list(submission_id: int, unresolved: bool) -> None:
    """Показать все комментарии к submission.

    Закрытые помечены ``✓``, открытые — ``●``.
    """
    from gostforge.db import get_connection, list_comments

    with get_connection() as conn:
        items = list_comments(
            conn,
            submission_id=submission_id,
            include_resolved=not unresolved,
        )
    if not items:
        click.echo("Комментариев нет.")
        return
    for c in items:
        role_color = {
            "supervisor": "magenta",
            "student": "blue",
            "anonymous": "bright_black",
        }.get(c.role, "white")
        role_label = click.style(f"[{c.role}]", fg=role_color)
        status = (
            click.style("✓", fg="green") if c.resolved else click.style("●", fg="yellow")
        )
        author = c.author or "—"
        click.echo(
            f"#{c.id} {status} {role_label} {author} "
            + click.style(c.created_at, fg="bright_black")
        )
        for line in c.body.splitlines():
            click.echo(f"    {line}")


@comment.command("resolve")
@click.argument("comment_id", type=int)
@click.option(
    "--reopen",
    is_flag=True,
    help="Снять отметку resolved (вернуть в открытые).",
)
def comment_resolve(comment_id: int, reopen: bool) -> None:
    """Пометить комментарий как resolved (или снять отметку через --reopen)."""
    from gostforge.db import get_connection, resolve_comment

    with get_connection() as conn:
        ok = resolve_comment(conn, comment_id, resolved=not reopen)
    if not ok:
        click.echo(
            click.style(f"Комментарий #{comment_id} не найден.", fg="yellow"),
            err=True,
        )
        sys.exit(1)
    action = "переоткрыт" if reopen else "закрыт"
    click.echo(
        click.style(f"Комментарий #{comment_id} {action}.", fg="green", bold=True)
    )


@comment.command("delete")
@click.argument("comment_id", type=int)
def comment_delete(comment_id: int) -> None:
    """Удалить комментарий."""
    from gostforge.db import delete_comment, get_connection

    with get_connection() as conn:
        ok = delete_comment(conn, comment_id)
    if not ok:
        click.echo(
            click.style(f"Комментарий #{comment_id} не найден.", fg="yellow"),
            err=True,
        )
        sys.exit(1)
    click.echo(
        click.style(f"Комментарий #{comment_id} удалён.", fg="green", bold=True)
    )


def _print_submission_details(sub: object) -> None:
    """Распечатать одну запись со списком violations и комментариев."""
    click.echo(click.style(f"Submission #{sub.id}", bold=True))  # type: ignore[attr-defined]
    click.echo(f"  Файл:      {sub.filename}")  # type: ignore[attr-defined]
    click.echo(f"  Профиль:   {sub.profile_id}")  # type: ignore[attr-defined]
    click.echo(f"  Время:     {sub.created_at}")  # type: ignore[attr-defined]
    click.echo(
        f"  Сводка:    "
        f"{click.style(str(sub.error_count), fg='red')} error / "  # type: ignore[attr-defined]
        f"{click.style(str(sub.warning_count), fg='yellow')} warning / "  # type: ignore[attr-defined]
        f"{click.style(str(sub.info_count), fg='cyan')} info"  # type: ignore[attr-defined]
    )
    if not sub.violations:  # type: ignore[attr-defined]
        click.echo("\n  Нарушений нет.")
    else:
        click.echo("\n  Нарушения:")
        for v in sub.violations:  # type: ignore[attr-defined]
            color = {"error": "red", "warning": "yellow", "info": "cyan"}.get(
                v.severity, "white"
            )
            click.echo(
                f"    {click.style(v.severity.upper(), fg=color)}  "
                f"{v.code:>6}  {v.message}"
            )
            if v.location:
                click.echo(
                    click.style(f"            {v.location}", fg="bright_black")
                )
            if v.suggestion:
                click.echo(click.style(f"          → {v.suggestion}", fg="green"))

    _print_submission_comments(sub.id)  # type: ignore[attr-defined]


def _print_submission_comments(submission_id: int) -> None:
    """Распечатать ленту комментариев к submission (если есть)."""
    try:
        from gostforge.db import get_connection, list_comments
    except ImportError:
        return
    try:
        with get_connection() as conn:
            comments = list_comments(conn, submission_id=submission_id)
    except Exception:
        return
    if not comments:
        return
    click.echo("\n  " + click.style("Комментарии:", bold=True))
    for c in comments:
        role_color = {
            "supervisor": "magenta",
            "student": "blue",
            "anonymous": "bright_black",
        }.get(c.role, "white")
        role_label = click.style(f"[{c.role}]", fg=role_color)
        status = (
            click.style(" ✓", fg="green") if c.resolved else click.style(" ●", fg="yellow")
        )
        author = c.author or "—"
        click.echo(
            f"    #{c.id}{status}  {role_label}  {author}  "
            + click.style(c.created_at, fg="bright_black")
        )
        for line in c.body.splitlines():
            click.echo(f"        {line}")


def _normalize_message(text: str) -> str:
    """Нормализовать текст сообщения для устойчивого сравнения нарушений.

    Сжимает пробелы, обрезает пробелы по краям и приводит к нижнему регистру.
    Это уменьшает ложные срабатывания «нарушение пропало / появилось» из-за
    малозначимых отличий в форматировании сообщений.
    """
    return " ".join(text.split()).strip().lower()


def _violation_fingerprint(v: Violation) -> tuple[str, str, str]:
    """Отпечаток нарушения для сравнения двух документов.

    Тройка `(check_code, location, normalize(message))` — компромисс между
    стабильностью (одна и та же ошибка в двух прогонах даёт один и тот же
    отпечаток) и уникальностью (две разные ошибки в одном месте отличаются
    нормализованным сообщением).
    """
    return (v.check_code, v.location, _normalize_message(v.message))


def _print_violations_brief(violations: list[Violation], indent: str = "  ") -> None:
    """Кратко вывести список violations с цветовой пометкой по серьёзности."""
    for v in violations:
        _, style, short = _SEVERITY_STYLE.get(v.severity, ("", {}, v.severity.upper()))
        tag = click.style(f"[{short}]", **style) if style else f"[{short}]"
        code = click.style(v.check_code, bold=True)
        click.echo(f"{indent}{tag} {code}  {v.message}")
        if v.location:
            click.echo(indent + "       " + click.style(v.location, fg="bright_black"))


@main.command()
@click.argument("file_a", type=click.Path(exists=True, path_type=Path))
@click.argument("file_b", type=click.Path(exists=True, path_type=Path))
@click.option("--profile", "-p", default="gost-7.32-2017", help="ID профиля для проверки")
@click.option("--quiet", "-q", is_flag=True, help="Не показывать детали по нарушениям")
def diff(file_a: Path, file_b: Path, profile: str, quiet: bool) -> None:
    """Сравнить два .docx по списку нарушений.

    Выводит:
    - какие нарушения появились в B (не было в A)
    - какие нарушения исчезли в A (нет в B)
    - сводку: было N нарушений → стало M

    Полезно для CI (стало ли нарушений меньше после правки), проверки
    эффекта `gostforge fix`, анализа версий «черновик → финал».

    Exit code: 0 если число error-нарушений в B не больше, чем в A;
    1 если в B появились новые error-нарушения (регрессия).
    """
    try:
        prof = load_profile(profile)
    except FileNotFoundError as e:
        click.echo(f"Ошибка: {e}", err=True)
        sys.exit(2)

    document_a = parse_docx(file_a)
    document_b = parse_docx(file_b)
    violations_a = validate(document_a, prof)
    violations_b = validate(document_b, prof)

    fingerprints_a = {_violation_fingerprint(v): v for v in violations_a}
    fingerprints_b = {_violation_fingerprint(v): v for v in violations_b}

    fixed_keys = set(fingerprints_a) - set(fingerprints_b)
    new_keys = set(fingerprints_b) - set(fingerprints_a)

    fixed = [fingerprints_a[k] for k in fixed_keys]
    introduced = [fingerprints_b[k] for k in new_keys]

    errors_a = sum(1 for v in violations_a if v.severity == "error")
    errors_b = sum(1 for v in violations_b if v.severity == "error")

    click.echo(
        click.style("Профиль: ", bold=True) + profile + f" (v{prof.version})"
    )
    click.echo(
        click.style("A: ", bold=True)
        + f"{file_a.name} — {len(violations_a)} нарушений ({errors_a} ошибок)"
    )
    click.echo(
        click.style("B: ", bold=True)
        + f"{file_b.name} — {len(violations_b)} нарушений ({errors_b} ошибок)"
    )

    if not fixed and not introduced:
        click.echo(click.style("\n[OK] Изменений в нарушениях нет.", fg="green", bold=True))
        sys.exit(0)

    if fixed:
        click.echo(
            "\n"
            + click.style(f"Исчезло нарушений: {len(fixed)}", fg="green", bold=True)
        )
        if not quiet:
            _print_violations_brief(fixed)

    if introduced:
        click.echo(
            "\n"
            + click.style(f"Появилось нарушений: {len(introduced)}", fg="red", bold=True)
        )
        if not quiet:
            _print_violations_brief(introduced)

    delta = errors_b - errors_a
    if delta > 0:
        click.echo(
            "\n"
            + click.style(
                f"Регрессия: число error-нарушений выросло ({errors_a} → {errors_b}, +{delta}).",
                fg="red",
                bold=True,
            )
        )
        sys.exit(1)
    elif delta < 0:
        click.echo(
            "\n"
            + click.style(
                f"Прогресс: число error-нарушений уменьшилось ({errors_a} → {errors_b}, {delta}).",
                fg="green",
                bold=True,
            )
        )
    else:
        click.echo(
            "\n"
            + click.style(
                f"Число error-нарушений не изменилось ({errors_a}).",
                fg="yellow",
            )
        )
    sys.exit(0)


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


@main.command("new-state")
@click.option(
    "--template",
    type=click.Choice(["coursework", "thesis", "research_report", "empty"]),
    default="empty",
    help="Тип шаблона (по умолчанию пустой каркас).",
)
@click.option(
    "--title", type=str, default="Новая работа", help="Название работы."
)
@click.option("--author", type=str, default="", help="Автор.")
@click.option(
    "--year",
    type=int,
    default=None,
    help="Год работы (по умолчанию текущий).",
)
@click.option(
    "--profile", "profile_id", type=str, default="gost-7.32-2017",
    help="Идентификатор профиля.",
)
@click.option(
    "-o",
    "--output",
    type=click.Path(path_type=Path),
    required=True,
    help="Куда сохранить JSON-state.",
)
def new_state_cmd(
    template: str,
    title: str,
    author: str,
    year: int | None,
    profile_id: str,
    output: Path,
) -> None:
    """Создать пустой JSON-state для конструктора по выбранному шаблону.

    Зеркало команды ``gostforge new`` (которая создаёт .docx), но
    результат — JSON для UI/CLI-цикла. Использует существующие
    шаблоны из ``gostforge.builder.templates``.

    Полный цикл: создать → отредактировать → собрать::

        gostforge new-state --template coursework --title "Анализ X" -o state.json
        gostforge ui    # правим в Streamlit
        gostforge generate state.json -o work.docx
    """
    from datetime import date  # noqa: PLC0415

    from gostforge.builder.templates import (  # noqa: PLC0415
        bachelor_thesis_template,
        coursework_template,
        research_report_template,
    )
    from gostforge.web.builder_editor import document_to_state  # noqa: PLC0415

    if year is None:
        year = date.today().year

    if template == "empty":
        # Минимальный каркас: один раздел «Введение» + список источников.
        state = {
            "title": title,
            "author": author,
            "year": year,
            "profile_id": profile_id,
            "sections": [
                {
                    "heading": "Введение",
                    "blocks": [
                        {"kind": "paragraph", "text": ""}
                    ],
                },
                {
                    "heading": "Список использованных источников",
                    "is_bibliography": True,
                    "references": [],
                },
            ],
        }
    else:
        # Используем существующий шаблон builder-а, собираем Document
        # и конвертируем обратно в state. Это даёт ровно то же
        # содержимое, что и `gostforge new --template=X`, но в формате
        # для конструктора.
        if template == "coursework":
            builder = coursework_template(
                title=title, author=author, year=year
            )
        elif template == "thesis":
            builder = bachelor_thesis_template(
                title=title, author=author, year=year
            )
        else:  # research_report
            builder = research_report_template(title=title, year=year)
        document = builder.build()
        document.profile_id = profile_id
        state = document_to_state(document)

    output.write_text(
        json.dumps(state, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    n = len(state.get("sections", []))
    click.echo(
        f"Создан {output} ({n} разделов, шаблон '{template}'). "
        f"Откройте в `gostforge ui` или редактируйте JSON напрямую."
    )


@main.command("generate")
@click.argument("state_path", type=click.Path(exists=True, path_type=Path))
@click.option(
    "-o",
    "--output",
    type=click.Path(path_type=Path),
    required=True,
    help="Куда сохранить .docx.",
)
@click.option(
    "--profile",
    "profile_override",
    type=str,
    default=None,
    help="Профиль для экспорта. По умолчанию — из state.json (profile_id).",
)
def generate_cmd(
    state_path: Path, output: Path, profile_override: str | None
) -> None:
    """Сгенерировать .docx из JSON-state конструктора.

    Это зеркало команды ``import-docx``: вместе они образуют полный
    CLI-цикл:

    \b
        gostforge import-docx work.docx -o state.json
        # ... редактируете state.json вручную или скриптом ...
        gostforge generate state.json -o new.docx

    Формат state.json — тот же, что в Streamlit-конструкторе
    (sidebar → «Загрузить сохранение»). Профиль берётся из
    ``state.profile_id``; ``--profile`` его переопределяет.
    """
    from gostforge.web.builder_editor import (  # noqa: PLC0415
        _build_document_from_state,
    )

    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        click.echo(f"Не удалось прочитать JSON: {exc}", err=True)
        sys.exit(2)
    if not isinstance(state, dict) or "sections" not in state:
        click.echo("В state.json должен быть ключ 'sections'.", err=True)
        sys.exit(2)
    if profile_override:
        state = dict(state)
        state["profile_id"] = profile_override

    try:
        data = _build_document_from_state(state)
    except FileNotFoundError as exc:
        click.echo(f"Профиль не найден: {exc}", err=True)
        sys.exit(2)
    except ValueError as exc:
        click.echo(f"Ошибка сборки: {exc}", err=True)
        sys.exit(3)

    output.write_bytes(data)
    click.echo(f"Сгенерирован файл: {output}")


@main.command("import-docx")
@click.argument("path", type=click.Path(exists=True, path_type=Path))
@click.option(
    "-o",
    "--output",
    type=click.Path(path_type=Path),
    required=True,
    help="Куда сохранить JSON-state для конструктора.",
)
def import_docx_cmd(path: Path, output: Path) -> None:
    """Разложить готовую работу .docx в JSON-state конструктора.

    Это обратная операция к ``gostforge new``: парсит .docx и кладёт
    результат в JSON-формат, который можно загрузить в Streamlit-
    конструктор (sidebar → «Загрузить сохранение (.json)») или
    использовать как промежуточный формат для скриптов.

    Структура JSON: title/author/year/profile_id и sections[] с
    блоками paragraph/table/figure/list/formula. Каждый раздел
    может иметь disabled_checks: list[str] — фича-конструктор
    «не проверять этот раздел нормоконтролем».

    Пример::

        gostforge import-docx work.docx -o draft.json
        gostforge ui
        # В UI: Загрузить сохранение (.json) → draft.json → редактируем

    Ограничения: нумерованные списки текущей реализацией экспорта
    пишутся как обычные параграфы с маркером — при импорте они
    останутся параграфами. Это не теряет содержимое, но требует
    собрать список заново в UI, если он нужен как list-блок.
    """
    from gostforge.web.builder_editor import document_to_state  # noqa: PLC0415

    document = parse_docx(path)
    state = document_to_state(document)
    output.write_text(
        json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    n_sec = len(state.get("sections", []))
    click.echo(
        f"Разложено {n_sec} разделов в {output}. "
        f"Загрузите его через `gostforge ui` → «Загрузить сохранение (.json)»."
    )


if __name__ == "__main__":
    main()
