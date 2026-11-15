"""A chat inside a collection, and its messages."""

from __future__ import annotations

import json
from typing import ClassVar

from ..database.repository import repo_query
from .base import ObjectModel


class ChatSession(ObjectModel):
    table_name: ClassVar[str] = "chats"
    missing_message: ClassVar[str] = "This chat no longer exists."

    collection_id: int
    title: str = "New chat"

    def public(self) -> dict:
        return {"id": self.id, "title": self.title, "created_at": self.created_at}

    @staticmethod
    def list_for_collection(collection_id: int) -> list[dict]:
        return repo_query(
            "SELECT id, title, created_at FROM chats WHERE collection_id = ? ORDER BY id DESC",
            (collection_id,),
        )

    @staticmethod
    def messages(chat_id: int) -> list[dict]:
        rows = repo_query(
            "SELECT id, role, content, citations FROM messages WHERE chat_id = ? ORDER BY id", (chat_id,)
        )
        for row in rows:
            row["citations"] = json.loads(row["citations"]) if row["citations"] else []
        return rows
