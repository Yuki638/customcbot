"""Paths and user settings."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from platformdirs import user_data_dir

from . import db

DEFAULTS: dict[str, Any] = {
    "tier": None,  # "lite" | "standard" | "plus" | "custom"
    "chat_model": None,
    "vision_model": None,
    "whisper_model": "base",
    "num_ctx": 4096,
    "context_chars": 5000,
    "embedding_model": "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
    "ollama_url": None,
    "setup_done": False,
}


def data_dir() -> Path:
    """Where the database, uploaded files and downloaded models live."""
    path = Path(os.environ.get("CUSTOMCBOT_DATA_DIR") or user_data_dir("customcbot", appauthor=False))
    path.mkdir(parents=True, exist_ok=True)
    return path


def files_dir() -> Path:
    path = data_dir() / "files"
    path.mkdir(parents=True, exist_ok=True)
    return path


def models_dir() -> Path:
    path = data_dir() / "models"
    path.mkdir(parents=True, exist_ok=True)
    return path


def ollama_url() -> str:
    url = get("ollama_url") or os.environ.get("OLLAMA_HOST") or "http://127.0.0.1:11434"
    if not url.startswith("http"):
        url = "http://" + url
    return url.rstrip("/")


def get(key: str) -> Any:
    row = db.one("SELECT value FROM settings WHERE key = ?", (key,))
    if row is None:
        return DEFAULTS.get(key)
    return json.loads(row["value"])


def get_all() -> dict[str, Any]:
    values = dict(DEFAULTS)
    for row in db.query("SELECT key, value FROM settings"):
        values[row["key"]] = json.loads(row["value"])
    return values


def set_many(values: dict[str, Any]) -> None:
    for key, value in values.items():
        if key not in DEFAULTS:
            raise KeyError(f"Unknown setting: {key}")
        db.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, json.dumps(value)),
        )
