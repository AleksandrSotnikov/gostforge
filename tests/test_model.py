"""Тесты модели документа."""

from gostforge.model import (
    Document,
    DocumentMetadata,
    PageSection,
    PageNumberingConfig,
    SCHEMA_VERSION,
)


def test_empty_document() -> None:
    doc = Document()
    assert doc.schema_version == SCHEMA_VERSION
    assert doc.profile_id == "gost-7.32-2017"
    assert doc.page_sections == []


def test_document_with_metadata() -> None:
    doc = Document(metadata=DocumentMetadata(title="Test", author="Иванов И.И."))
    assert doc.metadata.title == "Test"
    assert doc.metadata.author == "Иванов И.И."


def test_page_section_defaults() -> None:
    sect = PageSection(id="s1", name="Основная часть", type="main")
    assert sect.page.paper == "A4"
    assert sect.link_to_previous is False
    assert isinstance(sect.page_numbering, PageNumberingConfig)
