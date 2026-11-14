"""Word documents, PowerPoint slides and plain text."""

from __future__ import annotations

from pathlib import Path

from .chunking import Unit

SECTION_CHARS = 3000


def _sections(text: str) -> list[Unit]:
    """Split long text into editable sections at paragraph boundaries."""
    units: list[Unit] = []
    current: list[str] = []
    size = 0
    for paragraph in text.split("\n"):
        if size + len(paragraph) > SECTION_CHARS and current:
            units.append(Unit(text="\n".join(current).strip()))
            current, size = [], 0
        current.append(paragraph)
        size += len(paragraph) + 1
    if "".join(current).strip():
        units.append(Unit(text="\n".join(current).strip()))
    return [u for u in units if u.text]


def extract_text(text: str) -> list[Unit]:
    return _sections(text)


def extract_text_file(path: Path) -> list[Unit]:
    data = path.read_bytes()
    for encoding in ("utf-8-sig", "utf-16", "latin-1"):
        try:
            return _sections(data.decode(encoding))
        except UnicodeError:
            continue
    return []


def extract_docx(path: Path) -> list[Unit]:
    from docx import Document

    document = Document(str(path))
    lines = [p.text for p in document.paragraphs]
    for table in document.tables:
        for row in table.rows:
            cells = [cell.text.strip() for cell in row.cells]
            lines.append(" | ".join(c for c in cells if c))
    return _sections("\n".join(lines))


def extract_pptx(path: Path) -> list[Unit]:
    from pptx import Presentation

    units: list[Unit] = []
    for number, slide in enumerate(Presentation(str(path)).slides, start=1):
        lines: list[str] = []
        for shape in slide.shapes:
            if shape.has_text_frame:
                lines.extend(p.text for p in shape.text_frame.paragraphs if p.text.strip())
            if getattr(shape, "has_table", False) and shape.has_table:
                for row in shape.table.rows:
                    lines.append(" | ".join(cell.text.strip() for cell in row.cells))
        if slide.has_notes_slide:
            notes = slide.notes_slide.notes_text_frame.text.strip()
            if notes:
                lines.append(f"Speaker notes: {notes}")
        text = "\n".join(lines).strip()
        if text:
            units.append(Unit(text=text, page=number))
    return units
