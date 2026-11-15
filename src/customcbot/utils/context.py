"""Builds the text that puts retrieved passages in front of the model."""

from __future__ import annotations


def format_sources(passages: list[dict], numbers: list[int] | None = None) -> str:
    """The passages as numbered sources. `numbers` overrides the default 1, 2, 3."""
    blocks = []
    for number, passage in zip(numbers or range(1, len(passages) + 1), passages, strict=True):
        blocks.append(f"[{number}] {location_label(passage)}\n{passage['text']}")
    return "\n\n".join(blocks)


def location_label(passage: dict) -> str:
    """Where a passage comes from, as shown to the model and in a citation."""
    if passage.get("kind") == "note":
        return f"Your note: {passage['title']}"
    if passage.get("kind") == "insight":
        return f"{passage.get('insight_type') or 'Insight'} of {passage['title']}"
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
