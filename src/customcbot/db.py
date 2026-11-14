"""SQLite storage: one file holds everything.

Each thread gets its own connection. WAL mode lets the background worker write
while the web server reads.
"""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Iterable
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS collections (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL,
    summary     TEXT,
    created_at  TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS sources (
    id            INTEGER PRIMARY KEY,
    collection_id INTEGER NOT NULL REFERENCES collections(id) ON DELETE CASCADE,
    kind          TEXT NOT NULL,      -- pdf | image | youtube | media | docx | pptx | text
    title         TEXT NOT NULL,
    origin        TEXT,               -- original file name or URL
    file_path     TEXT,               -- stored copy, relative to the files dir
    status        TEXT NOT NULL DEFAULT 'queued',  -- queued | processing | ready | error
    stage         TEXT,
    progress      REAL NOT NULL DEFAULT 0,
    error         TEXT,
    note          TEXT,               -- non-fatal warning shown to the user
    summary       TEXT,
    created_at    TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- A unit is one extracted piece of a source: a PDF page, a slide, an image,
-- or a transcript segment. Users can correct unit text; chunks are rebuilt from units.
CREATE TABLE IF NOT EXISTS units (
    id         INTEGER PRIMARY KEY,
    source_id  INTEGER NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    ord        INTEGER NOT NULL,
    page       INTEGER,
    start_sec  REAL,
    method     TEXT NOT NULL,         -- text | vision | ocr | captions | whisper
    text       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS units_source ON units(source_id, ord);

CREATE TABLE IF NOT EXISTS chunks (
    id            INTEGER PRIMARY KEY,
    source_id     INTEGER NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    collection_id INTEGER NOT NULL,
    ord           INTEGER NOT NULL,
    page          INTEGER,
    start_sec     REAL,
    text          TEXT NOT NULL,
    embedding     BLOB
);
CREATE INDEX IF NOT EXISTS chunks_collection ON chunks(collection_id);
CREATE INDEX IF NOT EXISTS chunks_source ON chunks(source_id, ord);

CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
    text, content='chunks', content_rowid='id', tokenize='unicode61 remove_diacritics 2'
);
CREATE TRIGGER IF NOT EXISTS chunks_ai AFTER INSERT ON chunks BEGIN
    INSERT INTO chunks_fts(rowid, text) VALUES (new.id, new.text);
END;
CREATE TRIGGER IF NOT EXISTS chunks_ad AFTER DELETE ON chunks BEGIN
    INSERT INTO chunks_fts(chunks_fts, rowid, text) VALUES ('delete', old.id, old.text);
END;

CREATE TABLE IF NOT EXISTS chats (
    id            INTEGER PRIMARY KEY,
    collection_id INTEGER NOT NULL REFERENCES collections(id) ON DELETE CASCADE,
    title         TEXT NOT NULL DEFAULT 'New chat',
    created_at    TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS messages (
    id         INTEGER PRIMARY KEY,
    chat_id    INTEGER NOT NULL REFERENCES chats(id) ON DELETE CASCADE,
    role       TEXT NOT NULL,         -- user | assistant
    content    TEXT NOT NULL,
    citations  TEXT,                  -- JSON list
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS flashcards (
    id            INTEGER PRIMARY KEY,
    collection_id INTEGER NOT NULL REFERENCES collections(id) ON DELETE CASCADE,
    source_id     INTEGER REFERENCES sources(id) ON DELETE CASCADE,
    front         TEXT NOT NULL,
    back          TEXT NOT NULL,
    box           INTEGER NOT NULL DEFAULT 1,
    due_at        TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    created_at    TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS quizzes (
    id            INTEGER PRIMARY KEY,
    collection_id INTEGER NOT NULL REFERENCES collections(id) ON DELETE CASCADE,
    title         TEXT NOT NULL,
    questions     TEXT NOT NULL DEFAULT '[]',   -- JSON list
    best_score    REAL,
    created_at    TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Background work other than ingesting a source (summaries, quiz and card generation).
CREATE TABLE IF NOT EXISTS jobs (
    id            INTEGER PRIMARY KEY,
    kind          TEXT NOT NULL,
    collection_id INTEGER REFERENCES collections(id) ON DELETE CASCADE,
    params        TEXT NOT NULL DEFAULT '{}',
    status        TEXT NOT NULL DEFAULT 'queued',  -- queued | running | done | error
    stage         TEXT,
    progress      REAL NOT NULL DEFAULT 0,
    error         TEXT,
    result        TEXT,
    created_at    TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""

_path: Path | None = None
_generation = 0
_local = threading.local()


def init(path: Path) -> None:
    """Point the module at a database file and create tables if needed."""
    global _path, _generation
    _path = Path(path)
    _generation += 1
    conn = connect()
    conn.executescript(SCHEMA)
    conn.commit()


def connect() -> sqlite3.Connection:
    if _path is None:
        raise RuntimeError("db.init() has not been called")
    if getattr(_local, "generation", None) != _generation:
        conn = sqlite3.connect(_path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA synchronous = NORMAL")
        _local.conn = conn
        _local.generation = _generation
    return _local.conn


def query(sql: str, params: Iterable[Any] = ()) -> list[dict[str, Any]]:
    return [dict(row) for row in connect().execute(sql, tuple(params)).fetchall()]


def one(sql: str, params: Iterable[Any] = ()) -> dict[str, Any] | None:
    row = connect().execute(sql, tuple(params)).fetchone()
    return dict(row) if row is not None else None


def execute(sql: str, params: Iterable[Any] = ()) -> int:
    """Run a write statement and return the last inserted row id."""
    conn = connect()
    cur = conn.execute(sql, tuple(params))
    conn.commit()
    return cur.lastrowid or 0


def executemany(sql: str, rows: Iterable[Iterable[Any]]) -> None:
    conn = connect()
    conn.executemany(sql, [tuple(r) for r in rows])
    conn.commit()
