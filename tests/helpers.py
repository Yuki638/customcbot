"""Builders for small test files, and a reader for the chat event stream."""

from __future__ import annotations

import io
import json

from PIL import Image, ImageDraw


def text_pdf(pages: list[str]) -> bytes:
    """A minimal valid PDF with one line-wrapped block of text per page."""
    objects: list[bytes] = []

    def add(body: str | bytes) -> int:
        objects.append(body if isinstance(body, bytes) else body.encode("latin-1"))
        return len(objects)

    font = add("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    page_ids: list[int] = []
    pages_id = len(objects) + 2 * len(pages) + 1
    for text in pages:
        words, lines, line = text.split(), [], ""
        for word in words:
            if len(line) + len(word) > 80:
                lines.append(line)
                line = ""
            line = f"{line} {word}".strip()
        lines.append(line)
        ops = ["BT", "/F1 11 Tf", "50 780 Td", "14 TL"]
        for item in lines:
            escaped = item.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")
            ops.append(f"({escaped}) Tj T*")
        ops.append("ET")
        stream = "\n".join(ops).encode("latin-1")
        content = add(b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream")
        page_ids.append(
            add(
                f"<< /Type /Page /Parent {pages_id} 0 R /MediaBox [0 0 612 842] "
                f"/Contents {content} 0 R /Resources << /Font << /F1 {font} 0 R >> >> >>"
            )
        )
    kids = " ".join(f"{i} 0 R" for i in page_ids)
    assert add(f"<< /Type /Pages /Kids [{kids}] /Count {len(page_ids)} >>") == pages_id
    catalog = add(f"<< /Type /Catalog /Pages {pages_id} 0 R >>")

    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(out.tell())
        out.write(b"%d 0 obj\n" % number + body + b"\nendobj\n")
    xref = out.tell()
    out.write(b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1))
    for offset in offsets:
        out.write(b"%010d 00000 n \n" % offset)
    out.write(b"trailer\n<< /Size %d /Root %d 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, catalog, xref))
    return out.getvalue()


def text_image(text: str, size: tuple[int, int] = (900, 200)) -> Image.Image:
    image = Image.new("RGB", size, "white")
    draw = ImageDraw.Draw(image)
    try:
        from PIL import ImageFont

        font = ImageFont.load_default(size=48)
    except TypeError:  # very old Pillow
        font = None
    draw.text((30, 60), text, fill="black", font=font)
    return image


def png_bytes(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def scanned_pdf(text: str) -> bytes:
    """A PDF whose only page is a picture of text, like a scan."""
    buffer = io.BytesIO()
    text_image(text).save(buffer, format="PDF")
    return buffer.getvalue()


def docx_bytes(paragraphs: list[str]) -> bytes:
    from docx import Document

    document = Document()
    for paragraph in paragraphs:
        document.add_paragraph(paragraph)
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def pptx_bytes(slides: list[tuple[str, str]]) -> bytes:
    from pptx import Presentation

    presentation = Presentation()
    layout = presentation.slide_layouts[1]
    for title, body in slides:
        slide = presentation.slides.add_slide(layout)
        slide.shapes.title.text = title
        slide.placeholders[1].text = body
    buffer = io.BytesIO()
    presentation.save(buffer)
    return buffer.getvalue()


def read_events(response) -> list[tuple[str, dict]]:
    """Parse a server-sent event stream into (event, data) pairs."""
    events = []
    for block in response.text.split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.splitlines() if ": " in line)
        if "event" in lines:
            events.append((lines["event"], json.loads(lines["data"])))
    return events


def ask(client, collection_id: int, question: str, chat_id: int | None = None, **extra):
    if chat_id is None:
        chat_id = client.post(f"/api/collections/{collection_id}/chats").json()["id"]
    response = client.post(f"/api/chats/{chat_id}/messages", json={"content": question, **extra})
    assert response.status_code == 200
    events = read_events(response)
    text = "".join(data["text"] for event, data in events if event == "token")
    sources = next(data["citations"] for event, data in events if event == "sources")
    return chat_id, text, sources, events
