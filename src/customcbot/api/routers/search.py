"""Searching a collection, and Ask: a thorough answer built from several searches."""

from __future__ import annotations

import json

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ...database import search
from ...domain import Collection
from ...exceptions import InvalidInputError
from ...graphs import ask as ask_graph
from ...graphs.chat import citation_for

router = APIRouter(prefix="/api")

MODES = ("both", "words", "meaning")
KINDS = (search.SOURCE, search.NOTE, search.INSIGHT)


class SearchBody(BaseModel):
    query: str
    mode: str = "both"
    kinds: list[str] | None = None
    limit: int = 20


class AskBody(BaseModel):
    question: str
    source_ids: list[int] | None = None


@router.post("/collections/{collection_id}/search")
def search_collection(collection_id: int, body: SearchBody, request: Request) -> dict:
    Collection.get(collection_id)
    if not body.query.strip():
        raise InvalidInputError("Type what you are looking for.")
    if body.mode not in MODES:
        raise InvalidInputError("Unknown way of searching.")
    kinds = tuple(k for k in (body.kinds or KINDS) if k in KINDS)
    found = search.find(
        collection_id,
        body.query,
        request.app.state.services.embedder,
        mode=body.mode,
        kinds=kinds,
        limit=max(1, min(body.limit, 50)),
    )
    results = []
    for number, passage in enumerate(found, start=1):
        results.append({**citation_for(number, passage), "matched_words": passage["matched_words"]})
    return {"results": results}


@router.post("/collections/{collection_id}/ask")
def ask(collection_id: int, body: AskBody, request: Request) -> StreamingResponse:
    Collection.get(collection_id)
    question = body.question.strip()
    if not question:
        raise InvalidInputError("Type a question first.")
    services = request.app.state.services

    def events():
        try:
            for event, data in ask_graph.ask(
                collection_id, question, services, source_ids=body.source_ids or None
            ):
                yield f"event: {event}\ndata: {json.dumps(data)}\n\n"
        except Exception as exc:  # never leave the browser waiting on a broken stream
            message = json.dumps({"message": f"Something went wrong: {exc}"})
            yield f"event: error\ndata: {message}\n\n"

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
