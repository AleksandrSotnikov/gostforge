"""Конвертация .docx → .pdf через LibreOffice headless.

Требует установленного LibreOffice (``libreoffice`` / ``soffice``).
Если LibreOffice не найден, поднимает :class:`LibreOfficeNotFoundError`
с подсказкой по установке.

Модуль изолирует вызов внешнего процесса: парсер/экспортёр/валидатор
gostforge не знают про PDF и про LibreOffice; CLI и web-UI идут сюда
точечно, когда пользователь явно запросил PDF-версию документа.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path


class LibreOfficeNotFoundError(FileNotFoundError):
    """LibreOffice не установлен или не найден в PATH."""


def _find_soffice() -> str:
    """Найти исполняемый файл LibreOffice.

    Пробуем ``soffice`` (универсальное имя на Linux/macOS), затем
    ``libreoffice`` (фоллбек). Возвращаем абсолютный путь до
    исполняемого файла или поднимаем :class:`LibreOfficeNotFoundError`.
    """
    for name in ("soffice", "libreoffice"):
        path = shutil.which(name)
        if path:
            return path
    raise LibreOfficeNotFoundError(
        "LibreOffice не найден. Установите libreoffice или soffice. "
        "На Ubuntu/Debian: sudo apt install libreoffice; "
        "на macOS: brew install --cask libreoffice"
    )


def convert_to_pdf(
    input_path: str | Path,
    output_path: str | Path,
    *,
    timeout: float = 60.0,
) -> Path:
    """Сконвертировать .docx в .pdf через LibreOffice headless.

    Параметры
    ---------
    input_path:
        Путь к исходному .docx-файлу.
    output_path:
        Куда сохранить результирующий .pdf. Если родительская папка
        не существует — будет создана.
    timeout:
        Таймаут на выполнение процесса LibreOffice в секундах.

    Возвращает путь к созданному PDF.

    Исключения
    ----------
    FileNotFoundError
        Входной файл не существует.
    LibreOfficeNotFoundError
        LibreOffice не установлен.
    subprocess.CalledProcessError
        LibreOffice вернул не-нулевой код.
    subprocess.TimeoutExpired
        Превышен таймаут.
    RuntimeError
        LibreOffice не создал ожидаемый PDF (формально успешный запуск,
        но файла нет — встречается при экзотических входных файлах).
    """
    input_path = Path(input_path).resolve()
    output_path = Path(output_path).resolve()
    if not input_path.is_file():
        raise FileNotFoundError(f"Файл не найден: {input_path}")
    soffice = _find_soffice()

    # LibreOffice складывает результат в outdir с именем <stem>.pdf.
    # Используем временную директорию, потом переносим в нужный output_path —
    # это позволяет независимо от расширения output_path задать целевое имя.
    with tempfile.TemporaryDirectory() as tmpdir:
        cmd = [
            soffice,
            "--headless",
            "--convert-to",
            "pdf",
            "--outdir",
            tmpdir,
            str(input_path),
        ]
        subprocess.run(cmd, check=True, timeout=timeout, capture_output=True)
        produced = Path(tmpdir) / (input_path.stem + ".pdf")
        if not produced.is_file():
            raise RuntimeError(f"LibreOffice не создал ожидаемый PDF: {produced}")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(produced), str(output_path))
    return output_path


def convert_document(
    input_path: str | Path,
    output_path: str | Path,
    *,
    target_format: str,
    timeout: float = 120.0,
) -> Path:
    """Сконвертировать документ в произвольный формат через LibreOffice.

    Обобщение :func:`convert_to_pdf` на любой целевой формат,
    поддерживаемый LibreOffice: ``docx``, ``doc``, ``odt``, ``rtf``,
    ``txt``, ``html``, ``pdf`` и др.

    Главный сценарий — конвертация старого формата ``.doc`` в ``.docx``,
    который понимает python-docx-парсер gostforge::

        convert_document("work.doc", "work.docx", target_format="docx")

    Параметры
    ---------
    input_path:
        Исходный файл (любой формат, который читает LibreOffice).
    output_path:
        Куда сохранить результат (расширение должно соответствовать
        target_format).
    target_format:
        Целевой формат LibreOffice (например, "docx", "pdf", "odt").
    timeout:
        Таймаут процесса в секундах.

    Возвращает путь к созданному файлу.

    Исключения — те же, что у :func:`convert_to_pdf`.
    """
    input_path = Path(input_path).resolve()
    output_path = Path(output_path).resolve()
    if not input_path.is_file():
        raise FileNotFoundError(f"Файл не найден: {input_path}")
    soffice = _find_soffice()
    # Расширение результата = последний токен формата (docx:..., html:...).
    ext = target_format.split(":", 1)[0]

    with tempfile.TemporaryDirectory() as tmpdir:
        cmd = [
            soffice,
            "--headless",
            "--convert-to",
            target_format,
            "--outdir",
            tmpdir,
            str(input_path),
        ]
        subprocess.run(cmd, check=True, timeout=timeout, capture_output=True)
        produced = Path(tmpdir) / (input_path.stem + "." + ext)
        if not produced.is_file():
            raise RuntimeError(f"LibreOffice не создал ожидаемый файл: {produced}")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(produced), str(output_path))
    return output_path
