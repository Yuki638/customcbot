"""SQLite storage: one file holds everything. All reads and writes go through here.

Each thread gets its own connection. WAL mode lets the background worker write
while the web server reads.
"""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Iterable
from pathlib import Path
from typing import Any

_path: Path | None = None
_generation = 0
_local = threading.local()


def init_database(path: Path) -> None:
    """Point the module at a database file and bring its tables up to date."""
    global _path, _generation
    from .migrate import run_migrations

    _path = Path(path)
    _generation += 1
    run_migrations(connect())


def connect() -> sqlite3.Connection:
    if _path is None:
        raise RuntimeError("init_database() has not been called")
    if getattr(_local, "generation", None) != _generation:
        conn = sqlite3.connect(_path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA synchronous = NORMAL")
        _local.conn = conn
        _local.generation = _generation
    return _local.conn


def repo_query(sql: str, params: Iterable[Any] = ()) -> list[dict[str, Any]]:
    return [dict(row) for row in connect().execute(sql, tuple(params)).fetchall()]


def repo_one(sql: str, params: Iterable[Any] = ()) -> dict[str, Any] | None:
    row = connect().execute(sql, tuple(params)).fetchone()
    return dict(row) if row is not None else None


def repo_execute(sql: str, params: Iterable[Any] = ()) -> int:
    """Run a write statement and return the last inserted row id."""
    conn = connect()
    cur = conn.execute(sql, tuple(params))
    conn.commit()
    return cur.lastrowid or 0


def repo_executemany(sql: str, rows: Iterable[Iterable[Any]]) -> None:
    conn = connect()
    conn.executemany(sql, [tuple(r) for r in rows])
    conn.commit()
