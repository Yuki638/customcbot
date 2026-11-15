"""Paths and user settings."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from platformdirs import user_data_dir

from .database.repository import repo_execute, repo_one, repo_query

DEFAULTS: dict[str, Any] = {
    "tier": None,  # "lite" | "standard" | "plus" | "custom"
    "chat_model": None,
    "vision_model": None,
    "whisper_model": "base",
    "num_ctx": 4096,
    "context_chars": 5000,
    "max_passages": 6,
    "embedding_model": "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
    "ollama_url": None,
    "setup_done": False,
    # Where answers come from: "local" (Ollama on this computer) or "online"
    # (a hosted service that speaks the OpenAI chat API).
    "provider": "local",
    "online_service": None,  # id of a preset in llm/catalog.py, or "custom"
    "api_base_url": None,
    "api_model": None,
    "api_vision": False,  # whether the online model can read images
}

# Hosted models read far more text at once than a small local model.
ONLINE_CONTEXT_CHARS = 12000
ONLINE_MAX_PASSAGES = 8


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


def online() -> bool:
    """Whether questions are answered by an online service rather than a local model."""
    return get("provider") == "online"


def passage_budget() -> tuple[int, int]:
    """(characters of material, number of passages) to send with each question."""
    if online():
        return ONLINE_CONTEXT_CHARS, ONLINE_MAX_PASSAGES
    return int(get("context_chars") or 5000), int(get("max_passages") or 6)


def public() -> dict[str, Any]:
    """All settings, safe to send to the browser: the key itself never leaves the server."""
    from .ai import models  # here, not at the top: the models are built on this module

    values = get_all()
    saved = models.online_credential(values["online_service"]) if values["online_service"] else None
    values["api_key_saved"] = bool(saved and saved.key())
    return values


def get(key: str) -> Any:
    row = repo_one("SELECT value FROM settings WHERE key = ?", (key,))
    if row is None:
        return DEFAULTS.get(key)
    return json.loads(row["value"])


def get_all() -> dict[str, Any]:
    values = dict(DEFAULTS)
    for row in repo_query("SELECT key, value FROM settings"):
        if row["key"] in DEFAULTS:  # other rows are settings records, stored by domain models
            values[row["key"]] = json.loads(row["value"])
    return values


def set_many(values: dict[str, Any]) -> None:
    for key, value in values.items():
        if key not in DEFAULTS:
            raise KeyError(f"Unknown setting: {key}")
        repo_execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, json.dumps(value)),
        )
