"""A collection: one subject or project, holding sources, chats and study material.

It plays the part open-notebook calls a notebook.
"""

from __future__ import annotations

import shutil
from typing import ClassVar

from .. import config
from ..database import search
from ..database.repository import repo_execute, repo_query
from ..exceptions import InvalidInputError
from .base import ObjectModel

MAX_NAME_CHARS = 100


class Collection(ObjectModel):
    table_name: ClassVar[str] = "collections"
    missing_message: ClassVar[str] = "That collection no longer exists."

    name: str
    summary: str | None = None

    @staticmethod
    def clean_name(name: str) -> str:
        name = name.strip()
        if not name:
            raise InvalidInputError("Give the collection a name.")
        return name[:MAX_NAME_CHARS]

    @staticmethod
    def list_with_counts() -> list[dict]:
        return repo_query(
            "SELECT c.id, c.name, c.created_at, "
            "(SELECT COUNT(*) FROM sources s WHERE s.collection_id = c.id) AS source_count "
            "FROM collections c ORDER BY c.id DESC"
        )

    def delete(self) -> None:
        """Remove the collection with its files, passages and everything made from them."""
        for source in repo_query("SELECT id FROM sources WHERE collection_id = ?", (self.id,)):
            shutil.rmtree(config.files_dir() / str(source["id"]), ignore_errors=True)
        repo_execute("DELETE FROM chunks WHERE collection_id = ?", (self.id,))
        for episode in repo_query(
            "SELECT audio_path FROM podcast_episodes WHERE collection_id = ? AND audio_path IS NOT NULL",
            (self.id,),
        ):
            (config.podcasts_dir() / episode["audio_path"]).unlink(missing_ok=True)
        super().delete()
        search.invalidate(self.id)
