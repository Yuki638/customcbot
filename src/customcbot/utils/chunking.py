"""Splits extracted text into passages small enough for a local model."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class Unit:
    """One extracted piece of a source: a page, a slide, an image or a caption line."""

    text: str
    page: int | None = None
    start_sec: float | None = None
    method: str = "text"  # text | vision | ocr | captions | whisper


@dataclass
class Chunk:
    text: str
    page: int | None = None
    start_sec: float | None = None


_SENTENCE_END = re.compile(r"(?<=[.!?。！？])\s+")


def split_pieces(text: str, max_chars: int) -> list[str]:
    """Break text at paragraph, then sentence, then word boundaries."""
    pieces: list[str] = []
    for paragraph in re.split(r"\n\s*\n", text):
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        if len(paragraph) <= max_chars:
            pieces.append(paragraph)
            continue
        for sentence in _SENTENCE_END.split(paragraph):
            sentence = sentence.strip()
            while len(sentence) > max_chars:
                cut = sentence.rfind(" ", 0, max_chars)
                cut = cut if cut > max_chars // 2 else max_chars
                pieces.append(sentence[:cut].strip())
                sentence = sentence[cut:].strip()
            if sentence:
                pieces.append(sentence)
    return pieces


def make_chunks(units: list[Unit], max_chars: int = 1600, overlap: int = 200) -> list[Chunk]:
    """Pack units into overlapping chunks.

    Each chunk keeps the page number or timestamp of its first new piece, so a
    citation points at where the passage starts.
    """
    pieces: list[tuple[str, int | None, float | None]] = []
    for unit in units:
        for piece in split_pieces(unit.text, max_chars // 2):
            pieces.append((piece, unit.page, unit.start_sec))

    # Caption lines are sentence fragments; join them with spaces, not line breaks.
    joiner = " " if any(u.start_sec is not None for u in units) else "\n"

    chunks: list[Chunk] = []
    current: list[tuple[str, int | None, float | None]] = []
    carried = 0  # how many leading pieces of `current` are overlap from the previous chunk
    size = 0

    def emit() -> None:
        nonlocal current, carried, size
        if len(current) <= carried:
            return
        label = current[carried]
        chunks.append(Chunk(joiner.join(p[0] for p in current), label[1], label[2]))
        tail: list[tuple[str, int | None, float | None]] = []
        tail_size = 0
        for piece in reversed(current):
            if tail_size + len(piece[0]) > overlap:
                break
            tail.insert(0, piece)
            tail_size += len(piece[0])
        current, carried, size = tail, len(tail), tail_size

    previous_page: int | None = None
    for piece in pieces:
        has_new = len(current) > carried
        # Start a new chunk at a page boundary so the cited page is the right one,
        # unless what we have so far is too short to stand alone (a title page, say).
        new_page = piece[1] is not None and piece[1] != previous_page and size >= max_chars // 4
        if has_new and (size + len(piece[0]) > max_chars or new_page):
            emit()
        previous_page = piece[1]
        current.append(piece)
        size += len(piece[0]) + 1
    emit()
    return chunks
