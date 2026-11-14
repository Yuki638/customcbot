"""Summaries and study guides.

A whole document does not fit into a small model at once, so long sources are
summarised in parts (map) and the part-notes are then combined (reduce).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .. import config, db
from ..rag import prompts
from ..worker import JobContext

if TYPE_CHECKING:
    from ..services import Services


def _windows(texts: list[str], size: int) -> list[str]:
    windows: list[str] = []
    current: list[str] = []
    used = 0
    for text in texts:
        if used + len(text) > size and current:
            windows.append("\n\n".join(current))
            current, used = [], 0
        current.append(text)
        used += len(text)
    if current:
        windows.append("\n\n".join(current))
    return windows


def _notes(window: str, services: Services) -> str:
    return services.llm.chat(
        [
            {"role": "system", "content": prompts.SUMMARY_MAP_SYSTEM},
            {"role": "user", "content": f"Passage:\n\n{window}\n\nKey points:"},
        ],
        temperature=0.2,
        max_tokens=350,
        background=True,
    )


def _guide(notes: str, subject: str, services: Services) -> str:
    return services.llm.chat(
        [
            {"role": "system", "content": prompts.SUMMARY_REDUCE_SYSTEM},
            {"role": "user", "content": f'Notes on "{subject}":\n\n{notes}\n\nStudy guide:'},
        ],
        temperature=0.3,
        max_tokens=900,
        background=True,
    )


def _condense(notes: list[str], size: int, services: Services, context: JobContext, stage: str) -> str:
    """Shrink a list of notes until they fit in one prompt."""
    while len(notes) > 1 and sum(len(n) for n in notes) > size:
        groups = _windows(notes, size)
        if len(groups) >= len(notes):  # single notes larger than the window; cannot shrink further
            break
        merged = []
        for index, group in enumerate(groups):
            context.progress(stage, 0.7 + 0.2 * index / len(groups))
            merged.append(_notes(group, services))
        notes = merged
    return "\n\n".join(notes)[: size * 2]


def summarize_source(source_id: int, services: Services, context: JobContext, share: tuple[float, float] = (0.0, 1.0)) -> str:
    source = db.one("SELECT * FROM sources WHERE id = ?", (source_id,))
    if source is None:
        raise ValueError("That source no longer exists.")
    if source["summary"]:
        return source["summary"]
    start, span = share
    size = int(config.get("context_chars") or 5000)
    texts = [r["text"] for r in db.query("SELECT text FROM chunks WHERE source_id = ? ORDER BY ord", (source_id,))]
    if not texts:
        raise ValueError(f'"{source["title"]}" has no text to summarise yet.')
    windows = _windows(texts, size)
    title = source["title"]
    if len(windows) == 1:
        context.progress(f'Summarising "{title}"', start + span * 0.3)
        notes = windows[0]
    else:
        parts = []
        for index, window in enumerate(windows):
            context.progress(
                f'Reading "{title}" (part {index + 1} of {len(windows)})',
                start + span * 0.7 * index / len(windows),
            )
            parts.append(_notes(window, services))
        notes = _condense(parts, size, services, context, f'Combining notes on "{title}"')
    context.progress(f'Writing the study guide for "{title}"', start + span * 0.9)
    summary = _guide(notes, title, services)
    db.execute("UPDATE sources SET summary = ? WHERE id = ?", (summary, source_id))
    return summary


def job_summarize_source(job: dict, params: dict, services: Services, context: JobContext) -> dict:
    summarize_source(int(params["source_id"]), services, context)
    return {"source_id": params["source_id"]}


def job_summarize_collection(job: dict, params: dict, services: Services, context: JobContext) -> dict:
    collection_id = job["collection_id"]
    collection = db.one("SELECT * FROM collections WHERE id = ?", (collection_id,))
    sources = db.query(
        "SELECT id, title FROM sources WHERE collection_id = ? AND status = 'ready' ORDER BY id",
        (collection_id,),
    )
    if not sources:
        raise ValueError("Add some material first.")
    size = int(config.get("context_chars") or 5000)
    summaries = []
    for index, source in enumerate(sources):
        share = (0.8 * index / len(sources), 0.8 / len(sources))
        summary = summarize_source(source["id"], services, context, share)
        summaries.append(f'From "{source["title"]}":\n{summary}')
    if len(sources) == 1:
        overview = summaries[0].split("\n", 1)[1]
    else:
        notes = _condense(summaries, size, services, context, "Combining everything")
        context.progress("Writing the overview", 0.92)
        overview = _guide(notes, collection["name"], services)
    db.execute("UPDATE collections SET summary = ? WHERE id = ?", (overview, collection_id))
    return {"collection_id": collection_id}
