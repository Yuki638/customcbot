"""Talks to a local Ollama server over its HTTP API."""

from __future__ import annotations

import base64
import json
from collections.abc import Callable, Iterator
from urllib.parse import urlparse

import httpx

from .base import LLM, LLMError, Message

_LOOPBACK = {"127.0.0.1", "localhost", "::1", "0.0.0.0"}


class OllamaLLM(LLM):
    """Model names and the server URL are read through callables so that
    changing them in Settings takes effect without a restart."""

    def __init__(self, settings: Callable[[], dict], base_url: Callable[[], str]) -> None:
        super().__init__()
        self._settings = settings
        self._base_url = base_url
        self._caps: dict[str, set[str]] = {}

    # -- plumbing ---------------------------------------------------------

    def _client(self, read_timeout: float = 600) -> httpx.Client:
        url = self._base_url()
        # Ignore proxy environment variables for a server on this machine;
        # a corporate proxy setting would otherwise break the connection.
        local = (urlparse(url).hostname or "") in _LOOPBACK
        return httpx.Client(
            base_url=url,
            timeout=httpx.Timeout(read_timeout, connect=5),
            trust_env=not local,
        )

    # -- server state -----------------------------------------------------

    def version(self) -> str | None:
        """The server version, or None when Ollama is not running."""
        try:
            with self._client(read_timeout=5) as client:
                return client.get("/api/version").raise_for_status().json().get("version")
        except (httpx.HTTPError, ValueError):
            return None

    def installed_models(self) -> list[str]:
        try:
            with self._client(read_timeout=10) as client:
                data = client.get("/api/tags").raise_for_status().json()
        except (httpx.HTTPError, ValueError):
            return []
        return [m["name"] for m in data.get("models", [])]

    def is_installed(self, model: str | None) -> bool:
        if not model:
            return False
        names = self.installed_models()
        wanted = model if ":" in model else f"{model}:latest"
        return wanted in names

    def capabilities(self, model: str) -> set[str]:
        if model not in self._caps:
            try:
                with self._client(read_timeout=20) as client:
                    data = client.post("/api/show", json={"model": model}).raise_for_status().json()
            except (httpx.HTTPError, ValueError):
                return set()
            self._caps[model] = set(data.get("capabilities") or [])
        return self._caps[model]

    def pull(self, model: str) -> Iterator[dict]:
        """Download a model, yielding {status, total, completed} progress updates."""
        try:
            with self._client(read_timeout=None) as client:
                with client.stream("POST", "/api/pull", json={"model": model}) as response:
                    response.raise_for_status()
                    for line in response.iter_lines():
                        if not line:
                            continue
                        update = json.loads(line)
                        if update.get("error"):
                            raise LLMError(update["error"])
                        yield update
        except httpx.HTTPError as exc:
            raise LLMError(f"Could not download {model}: {exc}") from exc
        self._caps.pop(model, None)

    # -- LLM interface ----------------------------------------------------

    def has_vision(self) -> bool:
        model = self._settings().get("vision_model")
        return bool(model) and "vision" in self.capabilities(model)

    def _stream(self, messages, *, images, json_schema, temperature, max_tokens) -> Iterator[str]:
        settings = self._settings()
        model = settings.get("vision_model") if images else settings.get("chat_model")
        if not model:
            raise LLMError("No model is set up yet. Finish the setup first.")

        payload_messages: list[dict] = [dict(m) for m in messages]
        if images:
            encoded = [base64.b64encode(img).decode() for img in images]
            for message in reversed(payload_messages):
                if message["role"] == "user":
                    message["images"] = encoded
                    break

        payload: dict = {
            "model": model,
            "messages": payload_messages,
            "stream": True,
            "keep_alive": "30m",
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
                "num_ctx": int(settings.get("num_ctx") or 4096),
            },
        }
        if json_schema:
            payload["format"] = json_schema
        if "thinking" in self.capabilities(model):
            # Reasoning models think for a long time on a CPU; plain answers are faster.
            payload["think"] = False

        try:
            with self._client() as client:
                with client.stream("POST", "/api/chat", json=payload) as response:
                    if response.status_code >= 400:
                        detail = response.read().decode(errors="replace")
                        raise LLMError(_explain(detail, model))
                    for line in response.iter_lines():
                        if not line:
                            continue
                        update = json.loads(line)
                        if update.get("error"):
                            raise LLMError(_explain(update["error"], model))
                        piece = (update.get("message") or {}).get("content")
                        if piece:
                            yield piece
        except httpx.ConnectError as exc:
            raise LLMError("Ollama is not running. Start Ollama and try again.") from exc
        except httpx.HTTPError as exc:
            raise LLMError(f"Lost contact with Ollama: {exc}") from exc


def _explain(detail: str, model: str) -> str:
    try:
        detail = json.loads(detail).get("error", detail)
    except (ValueError, AttributeError):
        pass
    if "not found" in detail:
        return f"The model {model} is not downloaded. Open Settings to download it."
    if "memory" in detail:
        return f"Not enough free memory to run {model}. Close other apps or pick a smaller model in Settings."
    return f"Ollama error: {detail}"


def messages(system: str, user: str) -> list[Message]:
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]
