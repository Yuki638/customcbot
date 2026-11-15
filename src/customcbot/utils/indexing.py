"""Makes notes and insights searchable, the same way a source's passages are."""

from __future__ import annotations

from ..ai.embeddings import Embedder
from ..database import search
from ..database.repository import repo_execute, repo_executemany, repo_query
from .chunking import Unit, make_chunks


def _store(column: str, owner_id: int, collection_id: int, text: str, embedder: Embedder) -> None:
    chunks = make_chunks([Unit(text)]) if text.strip() else []
    vectors = embedder.embed([c.text for c in chunks]) if chunks else []
    repo_execute(f"DELETE FROM chunks WHERE {column} = ?", (owner_id,))
    repo_executemany(
        f"INSERT INTO chunks ({column}, collection_id, ord, text, embedding) VALUES (?, ?, ?, ?, ?)",
        [(owner_id, collection_id, i, c.text, vectors[i].tobytes()) for i, c in enumerate(chunks)],
    )
    search.invalidate(collection_id)


def index_note(note, embedder: Embedder) -> None:
    _store("note_id", note.id, note.collection_id, note.text_to_index(), embedder)


def index_insight(insight, embedder: Embedder) -> None:
    _store("insight_id", insight.id, insight.collection_id, insight.text_to_index(), embedder)


def index_missing(embedder: Embedder) -> int:
    """Index notes and insights that have no passages yet (for example after an upgrade)."""
    from ..domain import Note, SourceInsight

    done = 0
    for row in repo_query(
        "SELECT id FROM notes WHERE content != '' AND id NOT IN (SELECT note_id FROM chunks WHERE note_id IS NOT NULL)"
    ):
        index_note(Note.get(row["id"]), embedder)
        done += 1
    for row in repo_query(
        "SELECT id FROM source_insights "
        "WHERE id NOT IN (SELECT insight_id FROM chunks WHERE insight_id IS NOT NULL)"
    ):
        index_insight(SourceInsight.get(row["id"]), embedder)
        done += 1
    return done
