"""Brings the database up to date when the app starts.

Each file in `migrations/` is named `NNN_what_it_does.sql`, or `.py` with an
`upgrade(conn)` function when data has to be moved with code. The database
records the number of the last one applied (SQLite's `user_version`), and only
newer files are run, in order. To change the tables, add a new file; never edit
one that has shipped.
"""

from __future__ import annotations

import importlib.util
import sqlite3
from pathlib import Path

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def pending(version: int) -> list[tuple[int, Path]]:
    found = []
    for path in sorted(MIGRATIONS_DIR.glob("[0-9][0-9][0-9]_*")):
        number = int(path.name[:3])
        if path.suffix in (".sql", ".py") and number > version:
            found.append((number, path))
    return found


def _run_python(path: Path, conn: sqlite3.Connection) -> None:
    spec = importlib.util.spec_from_file_location(f"customcbot_migration_{path.stem}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.upgrade(conn)


def run_migrations(conn: sqlite3.Connection) -> int:
    """Apply every migration newer than the database. Returns the version reached."""
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    todo = pending(version)
    for number, path in todo:
        if path.suffix == ".py":
            _run_python(path, conn)
        else:
            conn.executescript(path.read_text(encoding="utf-8"))
        conn.execute(f"PRAGMA user_version = {number}")
        conn.commit()
        version = number
    if todo:
        # Fold the changes into the main file now, so nothing a migration removed lingers beside it.
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    return version
