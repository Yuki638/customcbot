"""Moves the one model choice saved by earlier versions into the new tables.

Written with plain SQL on purpose: a migration must keep working when the
domain models change later.
"""

from __future__ import annotations

import json
import sqlite3
from urllib.parse import urlparse

from customcbot.utils.encryption import encrypt

LABELS = {
    "groq": "Groq", "gemini": "Google Gemini", "openrouter": "OpenRouter",
    "cerebras": "Cerebras", "mistral": "Mistral", "freellmapi": "FreeLLMAPI",
}  # fmt: skip


def _label(service: str, address: str) -> str:
    return LABELS.get(service) or urlparse(address).netloc or "Online service"


def upgrade(conn: sqlite3.Connection) -> None:
    # Deleting a row normally leaves its bytes in the file. This makes SQLite
    # overwrite them, so the unencrypted key is really gone afterwards.
    conn.execute("PRAGMA secure_delete = ON")
    saved = {key: json.loads(value) for key, value in conn.execute("SELECT key, value FROM settings")}
    defaults: dict[str, int | None] = {}

    def add_model(credential_id: int, name: str, vision: bool) -> int:
        conn.execute(
            "INSERT OR IGNORE INTO models (credential_id, name, vision) VALUES (?, ?, ?)",
            (credential_id, name, int(vision)),
        )
        if vision:
            conn.execute(
                "UPDATE models SET vision = 1 WHERE credential_id = ? AND name = ?", (credential_id, name)
            )
        row = conn.execute(
            "SELECT id FROM models WHERE credential_id = ? AND name = ? AND type = 'language'",
            (credential_id, name),
        ).fetchone()
        return row[0]

    chat_model, vision_model = saved.get("chat_model"), saved.get("vision_model")
    if chat_model:
        local = conn.execute(
            "INSERT INTO credentials (provider, name) VALUES ('ollama', 'This computer (Ollama)')"
        ).lastrowid
        chat_id = add_model(local, chat_model, vision_model == chat_model)
        vision_id = add_model(local, vision_model, True) if vision_model else None
        if saved.get("provider", "local") != "online":
            defaults = {"chat": chat_id, "transformation": chat_id, "vision": vision_id}

    if saved.get("api_base_url") and saved.get("api_model"):
        key = saved.get("api_key")
        service = saved.get("online_service") or "custom"
        online = conn.execute(
            "INSERT INTO credentials (provider, name, base_url, api_key) VALUES (?, ?, ?, ?)",
            (service, _label(service, saved["api_base_url"]), saved["api_base_url"], encrypt(key) if key else None),
        ).lastrowid
        vision = bool(saved.get("api_vision"))
        model_id = add_model(online, saved["api_model"], vision)
        if saved.get("provider") == "online":
            defaults = {"chat": model_id, "transformation": model_id, "vision": model_id if vision else None}

    if defaults:
        conn.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES ('record:default_models', ?)",
            (json.dumps(defaults),),
        )
    # The key now lives, encrypted, with its service.
    conn.execute("DELETE FROM settings WHERE key = 'api_key'")
