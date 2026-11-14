"""Chats: history and the streaming answer endpoint."""

from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from .. import db
from ..rag import chat as rag_chat

router = APIRouter(prefix="/api")


class MessageBody(BaseModel):
    content: str
    source_ids: list[int] | None = None
    general: bool = False


@router.get("/collections/{collection_id}/chats")
def list_chats(collection_id: int) -> list[dict]:
    return db.query(
        "SELECT id, title, created_at FROM chats WHERE collection_id = ? ORDER BY id DESC", (collection_id,)
    )


@router.post("/collections/{collection_id}/chats")
def create_chat(collection_id: int) -> dict:
    if db.one("SELECT id FROM collections WHERE id = ?", (collection_id,)) is None:
        raise HTTPException(404, "That collection no longer exists.")
    chat_id = db.execute("INSERT INTO chats (collection_id) VALUES (?)", (collection_id,))
    return db.one("SELECT id, title, created_at FROM chats WHERE id = ?", (chat_id,))


@router.delete("/chats/{chat_id}")
def delete_chat(chat_id: int) -> dict:
    db.execute("DELETE FROM chats WHERE id = ?", (chat_id,))
    return {"ok": True}


@router.get("/chats/{chat_id}/messages")
def list_messages(chat_id: int) -> list[dict]:
    rows = db.query(
        "SELECT id, role, content, citations FROM messages WHERE chat_id = ? ORDER BY id", (chat_id,)
    )
    for row in rows:
        row["citations"] = json.loads(row["citations"]) if row["citations"] else []
    return rows


@router.post("/chats/{chat_id}/messages")
def send_message(chat_id: int, body: MessageBody, request: Request) -> StreamingResponse:
    question = body.content.strip()
    if not question:
        raise HTTPException(400, "Type a question first.")
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
