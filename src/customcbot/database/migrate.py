"""Brings the database up to date when the app starts.

Each file in `migrations/` is named `NNN_what_it_does.sql`. The database records
the number of the last one applied (SQLite's `user_version`), and only newer
files are run, in order. To change the tables, add a new file; never edit one
that has shipped.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def pending(version: int) -> list[tuple[int, Path]]:
    found = []
    for path in sorted(MIGRATIONS_DIR.glob("[0-9][0-9][0-9]_*.sql")):
        number = int(path.name[:3])
        if number > version:
            found.append((number, path))
    return found


def run_migrations(conn: sqlite3.Connection) -> int:
    """Apply every migration newer than the database. Returns the version reached."""
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    for number, path in pending(version):
        conn.executescript(path.read_text(encoding="utf-8"))
        conn.execute(f"PRAGMA user_version = {number}")
        conn.commit()
        version = number
    return version
