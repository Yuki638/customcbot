"""Transformations (tasks to carry out on a source) and the insights they produce."""

from __future__ import annotations

from typing import ClassVar

from ..database.repository import repo_execute, repo_query
from ..exceptions import InvalidInputError
from ..utils.prompter import render
from .base import ObjectModel

MAX_PROMPT_CHARS = 4000


class Transformation(ObjectModel):
    table_name: ClassVar[str] = "transformations"
    missing_message: ClassVar[str] = "That task no longer exists."

    title: str
    description: str = ""
    prompt: str | None = None  # None: a built-in with its original wording
    builtin: str | None = None  # template name under prompts/transformations/
    apply_default: bool = False  # run on every new source

    @staticmethod
    def clean(title: str, prompt: str | None) -> tuple[str, str | None]:
        title = title.strip()
        if not title:
            raise InvalidInputError("Give the task a name.")
        prompt = (prompt or "").strip() or None
        if prompt and len(prompt) > MAX_PROMPT_CHARS:
            raise InvalidInputError("That instruction is too long. Keep it to a few sentences.")
        return title[:60], prompt

    def instruction(self) -> str:
        """The wording sent to the model: the user's own, or the built-in template."""
        if self.prompt:
            return self.prompt
        if self.builtin:
            return render(f"transformations/{self.builtin}")
        raise InvalidInputError(f'"{self.title}" has no instruction yet. Edit it and write one.')

    def public(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "prompt": self.instruction() if (self.prompt or self.builtin) else "",
            "builtin": bool(self.builtin),
            "changed": bool(self.builtin and self.prompt),  # a built-in the user has reworded
            "apply_default": self.apply_default,
        }


class SourceInsight(ObjectModel):
    table_name: ClassVar[str] = "source_insights"
    missing_message: ClassVar[str] = "That result no longer exists."

    source_id: int
    collection_id: int
    transformation_id: int | None = None
    insight_type: str
    content: str

    @staticmethod
    def list_for_source(source_id: int) -> list[dict]:
        return repo_query(
            "SELECT id, source_id, transformation_id, insight_type, content, created_at "
            "FROM source_insights WHERE source_id = ? ORDER BY id",
            (source_id,),
        )

    @staticmethod
    def list_for_collection(collection_id: int) -> list[dict]:
        return repo_query(
            "SELECT i.id, i.source_id, i.transformation_id, i.insight_type, i.content, i.created_at, "
            "s.title AS source_title FROM source_insights i JOIN sources s ON s.id = i.source_id "
            "WHERE i.collection_id = ? ORDER BY s.id, i.id",
            (collection_id,),
        )

    def text_to_index(self) -> str:
        return self.content

    def delete(self) -> None:
        repo_execute("DELETE FROM chunks WHERE insight_id = ?", (self.id,))
        super().delete()
