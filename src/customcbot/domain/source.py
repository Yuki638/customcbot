"""A source: one file, link or pasted text inside a collection."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import ClassVar

from .. import config
from ..database import search
from ..database.repository import repo_execute, repo_query
from ..exceptions import NotFoundError
from .base import ObjectModel

# What the browser is sent for a source. The full text and summary are fetched separately.
PUBLIC_FIELDS = "id, collection_id, kind, title, origin, status, stage, progress, error, note, created_at"


class Source(ObjectModel):
    table_name: ClassVar[str] = "sources"
    missing_message: ClassVar[str] = "That source no longer exists."

    collection_id: int
    kind: str  # pdf | image | youtube | media | docx | pptx | text
    title: str
    origin: str | None = None  # original file name or URL
    file_path: str | None = None  # stored copy, relative to the files folder
    status: str = "queued"  # queued | processing | ready | error
    stage: str | None = None
    progress: float = 0
    error: str | None = None
    note: str | None = None  # a warning that is not a failure
    summary: str | None = None

    @staticmethod
    def list_for_collection(collection_id: int) -> list[dict]:
        return repo_query(
            f"SELECT {PUBLIC_FIELDS} FROM sources WHERE collection_id = ? ORDER BY id", (collection_id,)
        )

    def folder(self) -> Path:
        return config.files_dir() / str(self.id)

    def stored_file(self) -> Path:
        """The saved copy of the file, checked to be inside the files folder."""
        if not self.file_path:
            raise NotFoundError("This source has no file.")
        root = config.files_dir().resolve()
        path = (root / self.file_path).resolve()
        if root not in path.parents or not path.is_file():
            raise NotFoundError("The file is missing.")
        return path

    def units(self) -> list[dict]:
        """The text read from the source, piece by piece (a page, a slide, a stretch of speech)."""
        return repo_query(
            "SELECT id, ord, page, start_sec, method, text FROM units WHERE source_id = ? ORDER BY ord",
            (self.id,),
        )

    def mark_queued(self) -> None:
        self.update(status="queued", stage="Waiting", error=None, progress=0)

    def delete(self) -> None:
        repo_execute("DELETE FROM chunks WHERE source_id = ?", (self.id,))
        super().delete()
        # The collection's overview was written with this source in it.
        repo_execute("UPDATE collections SET summary = NULL WHERE id = ?", (self.collection_id,))
        shutil.rmtree(self.folder(), ignore_errors=True)
        search.invalidate(self.collection_id)
