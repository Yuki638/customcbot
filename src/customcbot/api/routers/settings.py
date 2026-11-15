"""Settings the user can change after setup."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from ... import config
from ...ai import models
from ...exceptions import InvalidInputError

router = APIRouter(prefix="/api")

EDITABLE_SETTINGS = {"num_ctx", "context_chars", "whisper_model", "ollama_url", "chat_model", "vision_model", "language"}


class SettingsUpdate(BaseModel):
    values: dict


@router.get("/settings")
def get_settings() -> dict:
    return config.public()


@router.put("/settings")
def update_settings(body: SettingsUpdate) -> dict:
    unknown = set(body.values) - EDITABLE_SETTINGS
    if unknown:
        raise InvalidInputError(f"Cannot change: {', '.join(sorted(unknown))}")
    values = dict(body.values)
    for key in ("num_ctx", "context_chars"):
        if key in values:
            values[key] = max(1024, min(int(values[key]), 65536))
    for key in ("ollama_url", "vision_model"):
        if key in values:
            values[key] = (values[key] or "").strip() or None
    config.set_many(values)
    if not config.online() and ("chat_model" in values or "vision_model" in values):
        # A different local model was typed in: make it the one that is used.
        chat_model = config.get("chat_model")
        if chat_model:
            models.use_local(chat_model, config.get("vision_model"))
    return config.public()
