"""Something the companion remembers about the user, such as their name or their exam date."""

from __future__ import annotations

import re
from typing import ClassVar

from ..database.repository import repo_execute, repo_query
from ..exceptions import InvalidInputError
from .base import ObjectModel

MAX_MEMORIES = 40
MAX_CHARS = 200


class Memory(ObjectModel):
    table_name: ClassVar[str] = "memories"
    missing_message: ClassVar[str] = "That memory no longer exists."

    content: str

    @staticmethod
    def clean(content: str) -> str:
        content = " ".join(content.split())
        if not content:
            raise InvalidInputError("Write what should be remembered first.")
        if len(content) > MAX_CHARS:
            raise InvalidInputError(f"Keep it under {MAX_CHARS} characters: one short fact at a time.")
        return content

    @staticmethod
    def all() -> list[dict]:
        return repo_query("SELECT id, content, created_at FROM memories ORDER BY id")

    @staticmethod
    def lines() -> list[str]:
        return [row["content"] for row in repo_query("SELECT content FROM memories ORDER BY id")]

    @staticmethod
    def clear() -> None:
        repo_execute("DELETE FROM memories")

    @classmethod
    def remember(cls, content: str) -> Memory | None:
        """Store a fact unless it is already known. The oldest go when there are too many."""
        content = cls.clean(content)
        known = {_key(line) for line in cls.lines()}
        if _key(content) in known:
            return None
        memory = cls(content=content).save()
        repo_execute(
            "DELETE FROM memories WHERE id NOT IN (SELECT id FROM memories ORDER BY id DESC LIMIT ?)",
            (MAX_MEMORIES,),
        )
        return memory


def _key(text: str) -> str:
    return re.sub(r"\W+", " ", text.lower()).strip()
