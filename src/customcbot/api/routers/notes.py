"""Notes inside a collection."""

from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel

from ...domain import Collection, Note
from ...domain.note import AI, HUMAN
from ...utils import indexing

router = APIRouter(prefix="/api")


class NoteBody(BaseModel):
    title: str = ""
    content: str = ""
    note_type: str = HUMAN


def _shown(note: Note) -> dict:
    return note.model_dump()


@router.get("/collections/{collection_id}/notes")
def list_notes(collection_id: int) -> list[dict]:
    return Note.list_for_collection(collection_id)


@router.post("/collections/{collection_id}/notes")
def add_note(collection_id: int, body: NoteBody, request: Request) -> dict:
    Collection.get(collection_id)
    title, content = Note.clean(body.title, body.content)
    note_type = AI if body.note_type == AI else HUMAN
    note = Note(collection_id=collection_id, title=title, content=content, note_type=note_type).save()
    indexing.index_note(note, request.app.state.services.embedder)
    return _shown(Note.get(note.id))


@router.get("/notes/{note_id}")
def get_note(note_id: int) -> dict:
    return _shown(Note.get(note_id))


@router.put("/notes/{note_id}")
def change_note(note_id: int, body: NoteBody, request: Request) -> dict:
    note = Note.get(note_id)
    title, content = Note.clean(body.title, body.content)
    note.update(title=title, content=content)
    note.touch()
    indexing.index_note(note, request.app.state.services.embedder)
    return _shown(Note.get(note_id))


@router.delete("/notes/{note_id}")
def delete_note(note_id: int) -> dict:
    from ...database import search

    note = Note.get(note_id)
    note.delete()
    search.invalidate(note.collection_id)
    return {"ok": True}
