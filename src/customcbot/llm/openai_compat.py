"""Talks to any hosted service that speaks the OpenAI chat API.

Groq, Google Gemini, OpenRouter, Cerebras, Mistral and self-hosted routers
such as FreeLLMAPI all accept the same requests, so one client covers them.
"""

from __future__ import annotations

import base64
import json
import time
from collections.abc import Callable, Iterator
from urllib.parse import urlparse

import httpx

from ..rag import prompts
from .base import LLM, LLMError, notify

_LOOPBACK = {"127.0.0.1", "localhost", "::1", "0.0.0.0"}
# Free services limit requests per minute. Short waits are sat out; a long one
# means the day's allowance is gone, and the user is told instead.
MAX_RATE_WAIT = 75
RATE_RETRIES = 4
# Limits written for a slow local model are too tight for hosted "thinking"
# models, which spend part of the allowance before the answer starts.
MIN_MAX_TOKENS = 2000

# How to ask for a JSON reply, from strictest to loosest. A service that
# rejects one way is asked the next way from then on.
_JSON_SCHEMA, _JSON_OBJECT, _JSON_PROMPT = 0, 1, 2


class OpenAICompatLLM(LLM):
    """The address, key and model are read through callables so that changing
    them in Settings takes effect without a restart."""

    def __init__(
        self,
        settings: Callable[[], dict],
        api_key: Callable[[], str | None],
        *,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        super().__init__()
        self._settings = settings
        self._api_key = api_key
        self._transport = transport
        self._sleep = sleep
        self._json_level: dict[tuple[str, str], int] = {}

    # -- plumbing ---------------------------------------------------------

    def _client(self, base_url: str, key: str | None, read_timeout: float = 300) -> httpx.Client:
        local = (urlparse(base_url).hostname or "") in _LOOPBACK
        headers = {"Authorization": f"Bearer {key}"} if key else {}
        return httpx.Client(
            base_url=base_url.rstrip("/") + "/",
            headers=headers,
            timeout=httpx.Timeout(read_timeout, connect=10),
            trust_env=not local,  # keep proxy settings for the internet, not for this machine
            transport=self._transport,
        )

    # -- used by the setup wizard -----------------------------------------

    def list_models(self, base_url: str, key: str | None) -> list[str]:
        """Model names the service offers. Raises LLMError with a plain message."""
        host = _host(base_url)
        try:
            with self._client(base_url, key, read_timeout=30) as client:
                response = client.get("models")
        except httpx.HTTPError as exc:
            raise LLMError(_unreachable(host)) from exc
        if response.status_code >= 400:
            raise LLMError(_explain(response.status_code, response.text, None, host))
        try:
            data = response.json()
        except ValueError as exc:
            raise LLMError(f"{host} did not answer like an AI service. Check the address.") from exc
        items = data.get("data") if isinstance(data, dict) else data
        names = []
        for item in items or []:
            name = item.get("id") if isinstance(item, dict) else item
            if isinstance(name, str) and name:
                names.append(name.removeprefix("models/"))
        return list(dict.fromkeys(names))

    def check(self, base_url: str, key: str | None, model: str) -> None:
        """Send one tiny request to prove the address, key and model work together."""
        reply = "".join(
            self._complete(
                base_url,
                key,
                model,
                [{"role": "user", "content": "Reply with the single word: ready"}],
                images=None,
                json_schema=None,
                temperature=0.0,
                max_tokens=20,
            )
        )
        if not reply.strip():
            raise LLMError(f"{model} gave an empty answer. Pick another model.")

    # -- LLM interface ----------------------------------------------------

    def has_vision(self) -> bool:
        settings = self._settings()
        return bool(settings.get("api_vision") and settings.get("api_model"))

    def _stream(self, messages, *, images, json_schema, temperature, max_tokens) -> Iterator[str]:
        settings = self._settings()
        base_url, model = settings.get("api_base_url"), settings.get("api_model")
        if not base_url or not model:
            raise LLMError("No online service is set up yet. Open Settings to choose one.")
        yield from self._complete(
            base_url,
            self._api_key(),
            model,
            messages,
            images=images,
            json_schema=json_schema,
            temperature=temperature,
            max_tokens=max_tokens,
        )

    def _complete(
        self, base_url, key, model, messages, *, images, json_schema, temperature, max_tokens
    ) -> Iterator[str]:
        host = _host(base_url)
        level_key = (base_url, model)
        waits = 0
        server_retries = 0
        while True:
            level = self._json_level.get(level_key, _JSON_SCHEMA)
            payload = _payload(model, messages, images, json_schema, level, temperature, max_tokens)
            try:
                with self._client(base_url, key) as client:
                    with client.stream("POST", "chat/completions", json=payload) as response:
                        status = response.status_code
                        if status == 429:
                            wait = _retry_after(response)
                            if waits >= RATE_RETRIES or wait > MAX_RATE_WAIT:
                                raise LLMError(
                                    f"The free allowance at {host} is used up for now. Wait a while, "
                                    "pick another model in Settings, or switch to a local model."
                                )
                            waits += 1
                            notify(f"Waiting {int(wait)} s for the service's rate limit")
                            self._sleep(wait)
                            continue
                        if status >= 500 and server_retries < 2:
                            server_retries += 1
                            self._sleep(2 * server_retries)
                            continue
                        if status >= 400:
                            detail = response.read().decode(errors="replace")
                            if json_schema and level < _JSON_PROMPT and status in (400, 404, 422):
                                # Probably the reply format: ask a looser way and remember it.
                                # If the cause was something else, the last attempt reports it.
                                self._json_level[level_key] = level + 1
                                continue
                            raise LLMError(_explain(status, detail, model, host))
                        got_text = False
                        for piece in _pieces(response):
                            got_text = got_text or bool(piece.strip())
                            yield piece
                        if not got_text:
                            raise LLMError(
                                f"{model} gave an empty answer. Try again, or pick another model in Settings."
                            )
                        return
            except httpx.HTTPError as exc:
                raise LLMError(_unreachable(host)) from exc


# -- request and response shapes ------------------------------------------


def _payload(model, messages, images, json_schema, level, temperature, max_tokens) -> dict:
    out: list[dict] = [dict(m) for m in messages]
    if json_schema and level >= _JSON_OBJECT:
        note = prompts.JSON_INSTRUCTION.format(schema=json.dumps(json_schema))
        for message in reversed(out):
            if message["role"] == "user":
                message["content"] = f"{message['content']}\n\n{note}"
                break
    if images:
        for message in reversed(out):
            if message["role"] == "user":
                parts: list[dict] = [{"type": "text", "text": message["content"]}]
                parts += [{"type": "image_url", "image_url": {"url": _data_url(img)}} for img in images]
                message["content"] = parts
                break
    payload: dict = {
        "model": model,
        "messages": out,
        "stream": True,
        "temperature": temperature,
        "max_tokens": max(max_tokens, MIN_MAX_TOKENS),
    }
    if json_schema and level == _JSON_SCHEMA:
        payload["response_format"] = {
            "type": "json_schema",
            "json_schema": {"name": "reply", "schema": json_schema},
        }
    elif json_schema and level == _JSON_OBJECT:
        payload["response_format"] = {"type": "json_object"}
    return payload


def _data_url(image: bytes) -> str:
    kind = "png" if image[:8] == b"\x89PNG\r\n\x1a\n" else "jpeg"
    return f"data:image/{kind};base64,{base64.b64encode(image).decode()}"


def _pieces(response: httpx.Response) -> Iterator[str]:
    """Yield the text of a reply, whether it is streamed or sent in one piece."""
    if "text/event-stream" not in response.headers.get("content-type", ""):
        try:
            data = json.loads(response.read())
        except ValueError:
            return
        _raise_if_error(data)
        choices = data.get("choices") if isinstance(data, dict) else None
        text = ((choices or [{}])[0].get("message") or {}).get("content")
        if isinstance(text, str) and text:
            yield text
        return
    for line in response.iter_lines():
        if not line.startswith("data:"):
            continue
        body = line[5:].strip()
        if body == "[DONE]":
            return
        try:
            update = json.loads(body)
        except ValueError:
            continue
        _raise_if_error(update)
        choices = update.get("choices") if isinstance(update, dict) else None
        if not choices:
            continue
        piece = (choices[0].get("delta") or {}).get("content")
        if isinstance(piece, str) and piece:
            yield piece


def _raise_if_error(data: object) -> None:
    if isinstance(data, dict) and data.get("error"):
        raise LLMError(f"The service reported a problem: {_message(data)}")


def _retry_after(response: httpx.Response) -> float:
    for header in ("retry-after", "x-ratelimit-reset-requests", "x-ratelimit-reset-tokens"):
        value = (response.headers.get(header) or "").strip().removesuffix("s")
        try:
            return max(1.0, float(value))
        except ValueError:
            continue
    return 10.0


def _host(base_url: str) -> str:
    return urlparse(base_url).hostname or base_url


def _unreachable(host: str) -> str:
    if host in _LOOPBACK:
        return f"Nothing is answering at {host}. Start that program, or check the address in Settings."
    return f"Could not reach {host}. Check your internet connection and the address in Settings."


def _message(data: object) -> str:
    """Dig the human-readable text out of the error shapes services use."""
    if isinstance(data, list) and data:
        data = data[0]
    if isinstance(data, dict):
        error = data.get("error", data)
        if isinstance(error, dict):
            return str(error.get("message") or error.get("code") or error)[:300]
        return str(error)[:300]
    return str(data)[:300]


def _explain(status: int, detail: str, model: str | None, host: str) -> str:
    try:
        text = _message(json.loads(detail))
    except ValueError:
        text = detail.strip()[:300]
    if status in (401, 403):
        return f"{host} did not accept the key. Check that it was copied completely, or create a new one."
    if model and (status == 404 or "model" in text.lower()):
        return f"{host} cannot use the model {model}: {text or 'not found'}. Pick another model in Settings."
    if status == 404:
        return f"{host} has no AI service at this address. Check the address."
    if status == 413 or "context" in text.lower() or "too large" in text.lower():
        return f"The request was too large for {model or 'this model'}. Pick a model that reads more text at once."
    return f"{host} reported a problem ({status}): {text or 'no details given'}"
