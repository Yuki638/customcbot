"""A note inside a collection: written by the user, or saved from an answer."""

from __future__ import annotations

from typing import ClassVar

from ..database.repository import repo_execute, repo_query
from ..exceptions import InvalidInputError
from .base import ObjectModel

HUMAN, AI = "human", "ai"
MAX_NOTE_CHARS = 200_000


class Note(ObjectModel):
    table_name: ClassVar[str] = "notes"
    missing_message: ClassVar[str] = "That note no longer exists."

    collection_id: int
    title: str
    content: str = ""
    note_type: str = HUMAN
    updated_at: str | None = None

    def _columns(self) -> dict:
        return self.model_dump(exclude={"id", "created_at", "updated_at"})

    @staticmethod
    def clean(title: str, content: str) -> tuple[str, str]:
        """A usable (title, content): a note without a title is named after its first line."""
        content = content.strip()
        if len(content) > MAX_NOTE_CHARS:
            raise InvalidInputError("That note is too long. Split it into several notes.")
        title = title.strip() or (content.splitlines()[0].lstrip("#*- ").strip() if content else "")
        if not title:
            raise InvalidInputError("Write something in the note first.")
        return title[:120], content

    @staticmethod
    def list_for_collection(collection_id: int) -> list[dict]:
        rows = repo_query(
            "SELECT id, title, note_type, created_at, updated_at, substr(content, 1, 240) AS preview "
            "FROM notes WHERE collection_id = ? ORDER BY updated_at DESC, id DESC",
            (collection_id,),
        )
        return rows

    def touch(self) -> None:
        repo_execute("UPDATE notes SET updated_at = CURRENT_TIMESTAMP WHERE id = ?", (self.id,))

    def text_to_index(self) -> str:
        return f"{self.title}\n\n{self.content}".strip()

    def delete(self) -> None:
        repo_execute("DELETE FROM chunks WHERE note_id = ?", (self.id,))
        super().delete()
