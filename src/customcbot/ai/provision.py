"""Hands out a ready-to-use client for the model that does a given job.

Everything that calls a model goes through `Provisioner.model_for(task)`.
Clients are kept and reused, because each remembers things about its service
(for example how it accepts requests for structured replies).
"""

from __future__ import annotations

import time
from collections.abc import Callable

import httpx

from .. import config
from ..domain.credential import Credential
from ..domain.model import Model
from . import models
from .base import LLM, LLMError, _Gate
from .ollama import OllamaLLM
from .openai_compat import OpenAICompatLLM
from .provider_registry import get_provider

NOT_SET_UP = "No AI model is set up yet. Open Settings to choose one."


class Provisioner:
    def __init__(
        self,
        *,
        ollama_url: Callable[[], str] | None = None,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._ollama_url = ollama_url or config.ollama_url
        self._transport = transport
        self._sleep = sleep
        self._clients: dict[tuple, LLM] = {}
        # One queue per service, shared by all its models, so that chat goes
        # ahead of background work on the same service.
        self._gates: dict[int, _Gate] = {}
        self._ollama = OllamaLLM(config.get_all, self._ollama_url)
        self._online = OpenAICompatLLM(dict, lambda: None, transport=transport, sleep=sleep)

    # -- clients for setting things up ------------------------------------

    def ollama(self) -> OllamaLLM:
        """For asking Ollama what is installed and downloading models."""
        return self._ollama

    def online(self) -> OpenAICompatLLM:
        """For listing a service's models and testing an address and key."""
        return self._online

    # -- clients for doing a job ------------------------------------------

    def model_for(self, task: str) -> LLM:
        chosen = models.resolve(task)
        if chosen is None and task == "vision":
            # No model reads images: callers ask has_vision() and fall back to plain OCR.
            chosen = models.resolve("chat")
        if chosen is None:
            raise LLMError(NOT_SET_UP)
        return self.client(*chosen)

    def client(self, model: Model, credential: Credential) -> LLM:
        key = credential.key()
        address = credential.address()
        signature = (credential.id, model.id, model.name, model.vision, address, key)
        client = self._clients.get(signature)
        if client is None:
            client = self._build(model, credential, address, key)
            client._gate = self._gates.setdefault(credential.id, _Gate())
            self._clients[signature] = client
        return client

    def _build(self, model: Model, credential: Credential, address: str | None, key: str | None) -> LLM:
        provider = get_provider(credential.provider)
        if provider is not None and provider.kind == "ollama":
            name, vision = model.name, model.name if model.vision else None

            def settings() -> dict:  # read each time, so a changed memory setting applies at once
                return {**config.get_all(), "chat_model": name, "vision_model": vision}

            return OllamaLLM(settings, (lambda: address) if address else self._ollama_url)
        fixed = {"api_base_url": address, "api_model": model.name, "api_vision": model.vision}
        return OpenAICompatLLM(lambda: fixed, lambda: key, transport=self._transport, sleep=self._sleep)
