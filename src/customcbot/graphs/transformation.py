"""Carries out a transformation on a source and stores the result as an insight.

A source that fits in one prompt is given to the model whole. A longer one is
first reduced to notes, part by part, and the task is carried out on the notes.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from .. import config
from ..commands.worker import JobContext
from ..database.repository import repo_execute, repo_query
from ..domain import Source, SourceInsight, Transformation
from ..utils import indexing
from ..utils.prompter import render
from . import summary

if TYPE_CHECKING:
    from ..services import Services

STUDY_GUIDE = "study_guide"
# Small models like to announce what they are about to write ("Here's a list of the key
# points:"). Asking them not to does not stop it, so that first line is removed.
_ANNOUNCEMENT = re.compile(r"\A\s*(?:here(?:'|’)?s|here is|here are|sure|okay|certainly)\b[^\n]{0,160}[:!.]\s*\n+", re.I)


def tidy(content: str) -> str:
    return _ANNOUNCEMENT.sub("", content, count=1).strip()


def _carry_out(source: Source, transformation: Transformation, services: Services, context: JobContext) -> str:
    size = config.passage_budget()[0]
    texts = [
        r["text"] for r in repo_query("SELECT text FROM chunks WHERE source_id = ? ORDER BY ord", (source.id,))
    ]
    if not texts:
        raise ValueError(f'"{source.title}" has no text to work on yet.')
    windows = summary._windows(texts, size)
    if len(windows) == 1:
        template, material = "transformations/user", windows[0]
    else:
        parts = []
        for index, window in enumerate(windows):
            context.progress(
                f'Reading "{source.title}" (part {index + 1} of {len(windows)})', 0.7 * index / len(windows)
            )
            parts.append(summary._notes(window, services))
        material = summary._condense(parts, size, services, context, f'Combining notes on "{source.title}"')
        template = "transformations/user_notes"
    context.progress(f'Writing "{transformation.title}" for "{source.title}"', 0.9)
    return services.model("transformation").chat(
        [
            {"role": "system", "content": render("transformations/system", task=transformation.instruction())},
            {"role": "user", "content": render(template, title=source.title, material=material)},
        ],
        temperature=0.3,
        max_tokens=900,
        background=True,
    )


def run_transformation(
    source_id: int, transformation_id: int, services: Services, context: JobContext
) -> SourceInsight:
    source = Source.get(source_id)
    transformation = Transformation.get(transformation_id)
    if transformation.builtin == STUDY_GUIDE and not transformation.prompt:
        # The study guide keeps its own, well-tested way of being written.
        repo_execute("UPDATE sources SET summary = NULL WHERE id = ?", (source_id,))
        content = summary.summarize_source(source_id, services, context)
    else:
        content = tidy(_carry_out(source, transformation, services, context))
    if not content.strip():
        raise ValueError("The model wrote nothing. Try again, or choose another model in Settings.")
    return save_insight(source, transformation, content, services)


def save_insight(source: Source, transformation: Transformation, content: str, services: Services) -> SourceInsight:
    """Store a result, replacing an earlier one of the same kind for this source."""
    for old in SourceInsight.where("source_id = ? AND transformation_id = ?", (source.id, transformation.id)):
        old.delete()
    insight = SourceInsight(
        source_id=source.id,
        collection_id=source.collection_id,
        transformation_id=transformation.id,
        insight_type=transformation.title,
        content=content.strip(),
    ).save()
    indexing.index_insight(insight, services.embedder)
    return insight
