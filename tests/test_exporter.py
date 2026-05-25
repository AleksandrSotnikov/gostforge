"""Тесты экспортёра модели в .docx."""

from pathlib import Path

import docx as python_docx

from gostforge.exporter import export_docx
from gostforge.model import (
    Document,
    LogicalSection,
    PageGeometry,
    PageSection,
    Paragraph,
    TextRun,
)
from gostforge.profile import load_profile


def _minimal_doc() -> Document:
    """Документ с одним параграфом и одним заголовком."""
    doc = Document()
    intro = LogicalSection(
        id="intro",
        level=1,
        heading=[TextRun(text="Введение")],
        children=[
            Paragraph(
                id="p1",
                content=[TextRun(text="Это вводный абзац.")],
            )
        ],
    )
    doc.page_sections.append(
        PageSection(
            id="main",
            name="Основная часть",
            type="main",
            page=PageGeometry(),
            content=[intro],
        )
    )
    return doc


def test_export_creates_file(tmp_path: Path) -> None:
    profile = load_profile("gost-7.32-2017")
    out = tmp_path / "out.docx"
    export_docx(_minimal_doc(), profile, out)
    assert out.exists()
    assert out.stat().st_size > 0


def test_export_applies_page_margins(tmp_path: Path) -> None:
    profile = load_profile("gost-7.32-2017")
    out = tmp_path / "out.docx"
    export_docx(_minimal_doc(), profile, out)

    raw = python_docx.Document(str(out))
    section = raw.sections[0]
    # Margins возвращаются в EMU; .mm даёт float
    assert round(section.top_margin.mm) == int(profile.styles.page.margins_mm["top"])
    assert round(section.right_margin.mm) == int(profile.styles.page.margins_mm["right"])
    assert round(section.bottom_margin.mm) == int(profile.styles.page.margins_mm["bottom"])
    assert round(section.left_margin.mm) == int(profile.styles.page.margins_mm["left"])


def test_export_applies_normal_style(tmp_path: Path) -> None:
    profile = load_profile("gost-7.32-2017")
    out = tmp_path / "out.docx"
    export_docx(_minimal_doc(), profile, out)

    raw = python_docx.Document(str(out))
    normal = raw.styles["Normal"]
    assert normal.font.name == profile.styles.body.font
    assert normal.font.size.pt == profile.styles.body.size_pt


def test_export_writes_heading_and_paragraph(tmp_path: Path) -> None:
    profile = load_profile("gost-7.32-2017")
    out = tmp_path / "out.docx"
    export_docx(_minimal_doc(), profile, out)

    raw = python_docx.Document(str(out))
    texts = [p.text for p in raw.paragraphs]
    assert "Введение" in texts
    assert "Это вводный абзац." in texts


def test_export_preserves_bold_italic(tmp_path: Path) -> None:
    doc = Document()
    doc.page_sections.append(
        PageSection(
            id="main",
            name="m",
            type="main",
            content=[
                Paragraph(
                    id="p1",
                    content=[
                        TextRun(text="жирно", bold=True),
                        TextRun(text=" и "),
                        TextRun(text="курсивом", italic=True),
                    ],
                )
            ],
        )
    )
    profile = load_profile("gost-7.32-2017")
    out = tmp_path / "out.docx"
    export_docx(doc, profile, out)

    raw = python_docx.Document(str(out))
    runs = raw.paragraphs[0].runs
    assert runs[0].bold is True
    assert runs[2].italic is True
