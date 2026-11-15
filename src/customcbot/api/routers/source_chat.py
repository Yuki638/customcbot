"""Chats about one source. Messages go through the same routes as any chat."""

from __future__ import annotations

from fastapi import APIRouter

from ...domain import ChatSession, Source
from ...exceptions import InvalidInputError

router = APIRouter(prefix="/api")


@router.get("/sources/{source_id}/chats")
def list_source_chats(source_id: int) -> list[dict]:
    Source.get(source_id)
    return ChatSession.list_for_source(source_id)


@router.post("/sources/{source_id}/chats")
def create_source_chat(source_id: int) -> dict:
    source = Source.get(source_id)
    if source.status != "ready":
        raise InvalidInputError(f'"{source.title}" is not ready yet. Wait until it has been read.')
    return ChatSession(collection_id=source.collection_id, source_id=source_id).save().public()
