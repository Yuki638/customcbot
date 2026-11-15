"""Insights: what a transformation wrote about a source."""

from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel

from ...database import search
from ...domain import Note, Source, SourceInsight, Transformation
from ...domain.note import AI
from ...exceptions import InvalidInputError
from ...utils import indexing
from .. import command_service

router = APIRouter(prefix="/api")


class InsightBody(BaseModel):
    transformation_id: int


@router.get("/collections/{collection_id}/insights")
def list_collection_insights(collection_id: int) -> list[dict]:
    return SourceInsight.list_for_collection(collection_id)


@router.get("/sources/{source_id}/insights")
def list_insights(source_id: int) -> list[dict]:
    Source.get(source_id)
    return SourceInsight.list_for_source(source_id)


@router.post("/sources/{source_id}/insights")
def make_insight(source_id: int, body: InsightBody, request: Request) -> dict:
    """Carry out a transformation on a source, in the background."""
    source = Source.get(source_id)
    if source.status != "ready":
        raise InvalidInputError(f'"{source.title}" is not ready yet. Wait until it has been read.')
    Transformation.get(body.transformation_id)
    return command_service.submit_command_job(
        request.app.state.services.worker,
        "run_transformation",
        source.collection_id,
        {"source_id": source_id, "transformation_id": body.transformation_id},
    )


@router.delete("/insights/{insight_id}")
def delete_insight(insight_id: int) -> dict:
    insight = SourceInsight.get(insight_id)
    insight.delete()
    search.invalidate(insight.collection_id)
    return {"ok": True}


@router.post("/insights/{insight_id}/save-as-note")
def save_as_note(insight_id: int, request: Request) -> dict:
    """Copy an insight into the collection's notes, where it can be edited."""
    insight = SourceInsight.get(insight_id)
    source = Source.get(insight.source_id)
    note = Note(
        collection_id=insight.collection_id,
        title=f"{insight.insight_type}: {source.title}"[:120],
        content=insight.content,
        note_type=AI,
    ).save()
    indexing.index_note(note, request.app.state.services.embedder)
    return Note.get(note.id).model_dump()
