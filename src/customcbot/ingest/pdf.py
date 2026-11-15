"""PDF text extraction, with a fallback for scanned or handwritten pages."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pypdfium2 as pdfium
from PIL import Image

from ..utils.chunking import Unit

# A page with less text than this is treated as a scan and read as an image.
MIN_TEXT_CHARS = 40

Transcriber = Callable[[Image.Image], tuple[str, str]]
Progress = Callable[[str, float], None]


def extract(path: Path, transcribe: Transcriber, progress: Progress) -> list[Unit]:
    units: list[Unit] = []
    pdf = pdfium.PdfDocument(str(path))
    try:
        total = len(pdf)
        for index in range(total):
            page = pdf[index]
            try:
                textpage = page.get_textpage()
                try:
                    text = textpage.get_text_bounded().strip()
                finally:
                    textpage.close()
                method = "text"
                if len(text) < MIN_TEXT_CHARS:
                    progress(f"Reading scanned page {index + 1} of {total}", index / total)
                    bitmap = page.render(scale=2)
                    try:
                        scanned, scan_method = transcribe(bitmap.to_pil().convert("RGB"))
                    finally:
                        bitmap.close()
                    if len(scanned.strip()) > len(text):
                        text, method = scanned.strip(), scan_method
                else:
                    progress(f"Reading page {index + 1} of {total}", index / total)
            finally:
                page.close()
            if text:
                units.append(Unit(text=text, page=index + 1, method=method))
    finally:
        pdf.close()
    return units
