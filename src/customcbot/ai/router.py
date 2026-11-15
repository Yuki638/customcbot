"""Sends each request to the local model or the online service, as set in Settings."""

from __future__ import annotations

from collections.abc import Callable, Iterator

from .base import LLM
from .ollama import OllamaLLM
from .openai_compat import OpenAICompatLLM


class SwitchLLM(LLM):
    def __init__(self, local: OllamaLLM, online: OpenAICompatLLM, use_online: Callable[[], bool]) -> None:
        super().__init__()
        self.local = local
        self.online = online
        self._use_online = use_online

    @property
    def active(self) -> LLM:
        return self.online if self._use_online() else self.local

    def has_vision(self) -> bool:
        return self.active.has_vision()

    def _stream(self, messages, *, images, json_schema, temperature, max_tokens) -> Iterator[str]:
        yield from self.active._stream(
            messages,
            images=images,
            json_schema=json_schema,
            temperature=temperature,
            max_tokens=max_tokens,
        )
