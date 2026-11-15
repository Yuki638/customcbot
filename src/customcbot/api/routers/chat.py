"""Chats: history and the streaming answer endpoint."""

from __future__ import annotations

import json

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ...domain import ChatSession, Collection
from ...exceptions import InvalidInputError
from ...graphs import chat as rag_chat

router = APIRouter(prefix="/api")


class MessageBody(BaseModel):
    content: str
    source_ids: list[int] | None = None
    general: bool = False


@router.get("/collections/{collection_id}/chats")
def list_chats(collection_id: int) -> list[dict]:
    return ChatSession.list_for_collection(collection_id)


@router.post("/collections/{collection_id}/chats")
def create_chat(collection_id: int) -> dict:
    Collection.get(collection_id)
    return ChatSession(collection_id=collection_id).save().public()


@router.delete("/chats/{chat_id}")
def delete_chat(chat_id: int) -> dict:
    chat = ChatSession.find(chat_id)
    if chat is not None:
        chat.delete()
    return {"ok": True}


@router.get("/chats/{chat_id}/messages")
def list_messages(chat_id: int) -> list[dict]:
    return ChatSession.messages(chat_id)


@router.post("/chats/{chat_id}/messages")
def send_message(chat_id: int, body: MessageBody, request: Request) -> StreamingResponse:
    question = body.content.strip()
    if not question:
        raise InvalidInputError("Type a question first.")
    services = request.app.state.services

    def events():
        try:
            for event, data in rag_chat.answer(
                chat_id, question, services, source_ids=body.source_ids or None, general=body.general
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
