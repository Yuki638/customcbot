"""Reads text out of images: handwriting, photos of notes, scanned pages."""

from __future__ import annotations

import io
import threading

from PIL import Image, ImageOps

from ..llm.base import LLM, LLMError

VISION_PROMPT = (
    "Transcribe all the text in this image exactly as written, including handwriting. "
    "Keep the line breaks and headings. Write maths in LaTeX between dollar signs. "
    "Briefly describe any diagram in square brackets. "
    "Reply with only the transcription, with no introduction or comments."
)

_ocr_engine = None
_ocr_lock = threading.Lock()


def load_image(data: bytes) -> Image.Image:
    image = Image.open(io.BytesIO(data))
    image = ImageOps.exif_transpose(image)  # phone photos are often stored rotated
    return image.convert("RGB")


def to_jpeg(image: Image.Image, max_side: int = 1568) -> bytes:
    image = image.copy()
    image.thumbnail((max_side, max_side))
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=88)
    return buffer.getvalue()


def transcribe_image(image: Image.Image, llm: LLM) -> tuple[str, str]:
    """Return (text, method). Uses the vision model when there is one, else basic OCR."""
    if llm.has_vision():
        try:
            text = llm.chat(
                [{"role": "user", "content": VISION_PROMPT}],
                images=[to_jpeg(image)],
                temperature=0.0,
                max_tokens=2000,
                background=True,
            )
            if text:
                return text, "vision"
        except LLMError:
            pass  # fall through to OCR rather than fail the whole source
    return basic_ocr(image), "ocr"


def basic_ocr(image: Image.Image) -> str:
    """Lightweight OCR for printed text. Not reliable on handwriting."""
    global _ocr_engine
    import numpy as np

    with _ocr_lock:
        if _ocr_engine is None:
            from rapidocr_onnxruntime import RapidOCR

            _ocr_engine = RapidOCR()
        result, _ = _ocr_engine(np.asarray(image))
    if not result:
        return ""
    return "\n".join(line[1] for line in result)
