"""Builds the text that puts retrieved passages in front of the model."""

from __future__ import annotations


def format_sources(passages: list[dict]) -> str:
    blocks = []
    for number, passage in enumerate(passages, start=1):
        blocks.append(f"[{number}] {location_label(passage)}\n{passage['text']}")
    return "\n\n".join(blocks)


def location_label(passage: dict) -> str:
    label = passage["title"]
    if passage.get("start_sec") is not None:
        label += f", at {format_time(passage['start_sec'])}"
    elif passage.get("page") is not None:
        label += f", {'slide' if passage['kind'] == 'pptx' else 'page'} {passage['page']}"
    return label


def format_time(seconds: float) -> str:
    seconds = int(seconds)
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"
