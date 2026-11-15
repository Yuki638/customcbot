"""A saved AI service: Ollama on this computer, or an online service with its key."""

from __future__ import annotations

import os
from typing import ClassVar

from ..ai.provider_registry import OLLAMA, get_provider
from ..utils.encryption import decrypt, encrypt
from .base import ObjectModel


class Credential(ObjectModel):
    table_name: ClassVar[str] = "credentials"
    missing_message: ClassVar[str] = "That service is no longer saved."

    provider: str
    name: str
    base_url: str | None = None
    api_key: str | None = None  # as stored: encrypted. Use key() to read it, set_key() to change it.

    @property
    def is_local(self) -> bool:
        return self.provider == OLLAMA

    def set_key(self, plain: str | None) -> None:
        self.api_key = encrypt(plain.strip()) if plain and plain.strip() else None

    def key(self) -> str | None:
        """The key to send: the saved one, or the one given through the environment."""
        if self.is_local:
            return None
        return decrypt(self.api_key) or os.environ.get("CUSTOMCBOT_API_KEY") or None

    def address(self) -> str | None:
        provider = get_provider(self.provider)
        return self.base_url or (provider.base_url if provider else None)

    def public(self) -> dict:
        """What the browser may see. The key itself never leaves the server."""
        provider = get_provider(self.provider)
        return {
            "id": self.id,
            "provider": self.provider,
            "provider_label": provider.label if provider else self.provider,
            "name": self.name,
            "base_url": self.address(),
            "local": self.is_local,
            "has_key": bool(self.key()),
        }
