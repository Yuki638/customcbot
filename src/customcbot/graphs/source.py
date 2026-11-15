"""Turns a source (file, link or pasted text) into searchable chunks."""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

from .. import config
from ..database import search as retrieve
from ..database.repository import (
    repo_execute,
    repo_executemany,
    repo_one,
    repo_query,
)
from ..ingest import media, ocr, office, pdf, youtube
from ..utils.chunking import Unit, make_chunks

if TYPE_CHECKING:
    from ..services import Services

KINDS_BY_EXTENSION = {
    ".pdf": "pdf",
    ".png": "image", ".jpg": "image", ".jpeg": "image", ".webp": "image", ".bmp": "image",
    ".gif": "image", ".tif": "image", ".tiff": "image",
    ".docx": "docx",
    ".pptx": "pptx",
    ".txt": "text", ".md": "text", ".markdown": "text", ".csv": "text", ".rst": "text",
    ".mp3": "media", ".wav": "media", ".m4a": "media", ".ogg": "media", ".flac": "media",
    ".aac": "media", ".opus": "media",
    ".mp4": "media", ".mkv": "media", ".webm": "media", ".mov": "media", ".avi": "media",
}  # fmt: skip


class IngestError(Exception):
    """A problem to show to the user as-is."""


def kind_for(filename: str) -> str | None:
    return KINDS_BY_EXTENSION.get(Path(filename).suffix.lower())


def set_progress(source_id: int, stage: str, fraction: float) -> None:
    repo_execute(
        "UPDATE sources SET stage = ?, progress = ? WHERE id = ?",
        (stage, max(0.0, min(fraction, 1.0)), source_id),
    )


def process_source(source_id: int, services: Services) -> None:
    """Extract, chunk and index one source. Records failure on the source row."""
    source = repo_one("SELECT * FROM sources WHERE id = ?", (source_id,))
    if source is None:
        return
    repo_execute(
        "UPDATE sources SET status = 'processing', error = NULL, note = NULL, progress = 0 WHERE id = ?",
        (source_id,),
    )
    try:
        units = _extract(source, services)
        if not any(u.text.strip() for u in units):
            raise IngestError(_empty_message(source["kind"]))
        note = _note_for(units)
        save_units(source_id, units)
        set_progress(source_id, "Indexing", 0.9)
        rebuild_chunks(source_id, services)
        repo_execute(
            "UPDATE sources SET status = 'ready', stage = NULL, progress = 1, note = ? WHERE id = ?",
            (note, source_id),
        )
    except (IngestError, youtube.YouTubeError, media.MediaError) as exc:
        _fail(source_id, str(exc))
    except Exception as exc:  # any reader can fail on a damaged file
        _fail(source_id, f"Could not read this source ({type(exc).__name__}: {exc})"[:400])


def _fail(source_id: int, message: str) -> None:
    repo_execute(
        "UPDATE sources SET status = 'error', stage = NULL, error = ? WHERE id = ?",
        (message, source_id),
    )


def _empty_message(kind: str) -> str:
    if kind in ("image", "pdf"):
        return "No readable text was found. If this is handwriting, a model that reads images is needed (Standard size or larger)."
    if kind in ("media", "youtube"):
        return "No speech was found in this recording."
    return "This source is empty."


def _note_for(units: list[Unit]) -> str | None:
    if any(u.method == "ocr" for u in units):
        return (
            "Read with basic text recognition, which is unreliable on handwriting. "
            "Check the text and fix any mistakes."
        )
    if any(u.method == "vision" for u in units):
        return "Read by the AI model from images. Check the text and fix any mistakes."
    return None


def _extract(source: dict, services: Services) -> list[Unit]:
    source_id = source["id"]
    kind = source["kind"]
    path = config.files_dir() / source["file_path"] if source["file_path"] else None

    def progress(stage: str, fraction: float) -> None:
        set_progress(source_id, stage, fraction * 0.85)

    def transcribe(image):
        return ocr.transcribe_image(image, services.model("vision"))

    if kind == "pdf":
        return pdf.extract(path, transcribe, progress)
    if kind == "image":
        progress("Reading the image", 0.1)
        text, method = transcribe(ocr.load_image(path.read_bytes()))
        return [Unit(text=text.strip(), page=1, method=method)] if text.strip() else []
    if kind == "docx":
        progress("Reading the document", 0.2)
        return office.extract_docx(path)
    if kind == "pptx":
        progress("Reading the slides", 0.2)
        return office.extract_pptx(path)
    if kind == "text":
        progress("Reading the text", 0.2)
        return office.extract_text_file(path)
    if kind == "media":
        whisper = config.get("whisper_model") or "base"
        return media.transcribe(path, whisper, config.models_dir() / "whisper", progress)
    if kind == "youtube":
        return _extract_youtube(source, progress)
    raise IngestError(f"Unsupported source type: {kind}")


def _extract_youtube(source: dict, progress) -> list[Unit]:
    vid = youtube.video_id(source["origin"] or "")
    if vid is None:
        raise IngestError("That does not look like a YouTube link.")
    progress("Getting the video details", 0.02)
    title = youtube.fetch_title(vid)
    if title:
        repo_execute("UPDATE sources SET title = ? WHERE id = ?", (title, source["id"]))
    progress("Getting the captions", 0.05)
    units = youtube.fetch_captions(vid)
    if units:
        return units
    # No captions: download the audio and transcribe it locally.
    progress("No captions found; downloading the audio", 0.08)
    folder = Path(tempfile.mkdtemp(prefix="customcbot-yt-"))
    try:
        audio = youtube.download_audio(vid, folder)
        whisper = config.get("whisper_model") or "base"
        return media.transcribe(audio, whisper, config.models_dir() / "whisper", progress)
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def save_units(source_id: int, units: list[Unit]) -> None:
    repo_execute("DELETE FROM units WHERE source_id = ?", (source_id,))
    repo_executemany(
        "INSERT INTO units (source_id, ord, page, start_sec, method, text) VALUES (?, ?, ?, ?, ?, ?)",
        [(source_id, i, u.page, u.start_sec, u.method, u.text) for i, u in enumerate(units) if u.text.strip()],
    )


def rebuild_chunks(source_id: int, services: Services) -> None:
    """Re-create chunks and embeddings from the stored units (also used after edits)."""
    source = repo_one("SELECT collection_id FROM sources WHERE id = ?", (source_id,))
    if source is None:
        return
    rows = repo_query("SELECT * FROM units WHERE source_id = ? ORDER BY ord", (source_id,))
    units = [Unit(r["text"], r["page"], r["start_sec"], r["method"]) for r in rows]
    chunks = make_chunks(units)
    vectors = services.embedder.embed([c.text for c in chunks]) if chunks else []
    repo_execute("DELETE FROM chunks WHERE source_id = ?", (source_id,))
    repo_executemany(
        "INSERT INTO chunks (source_id, collection_id, ord, page, start_sec, text, embedding) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        [
            (source_id, source["collection_id"], i, c.page, c.start_sec, c.text, vectors[i].tobytes())
            for i, c in enumerate(chunks)
        ],
    )
    # A changed source makes its cached summary stale.
    repo_execute("UPDATE sources SET summary = NULL WHERE id = ?", (source_id,))
    repo_execute("UPDATE collections SET summary = NULL WHERE id = ?", (source["collection_id"],))
    retrieve.invalidate(source["collection_id"])
