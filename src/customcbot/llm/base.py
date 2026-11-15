"""The small interface every model backend implements."""

from __future__ import annotations

import json
import re
import threading
import time
from abc import ABC, abstractmethod
from collections.abc import Iterator
from typing import TypeVar

from pydantic import BaseModel, ValidationError

Message = dict[str, str]
T = TypeVar("T", bound=BaseModel)


class LLMError(RuntimeError):
    """The model backend failed or returned something unusable."""


_notice = threading.local()


def set_notice_hook(hook) -> None:
    """Let the current thread hear short status notes from the backend (None to stop).

    The background worker uses this to show "waiting for the rate limit" on a job.
    """
    _notice.hook = hook


def notify(text: str) -> None:
    hook = getattr(_notice, "hook", None)
    if hook is not None:
        try:
            hook(text)
        except Exception:  # a status note must never break the request
            pass


class _Gate:
    """Lets interactive requests (chat) go ahead of background work.

    Local models answer one request at a time, so a long summary job would
    otherwise make the chat feel frozen. Background calls wait here until no
    interactive call is running.
    """

    def __init__(self) -> None:
        self._interactive = 0
        self._cond = threading.Condition()

    def enter(self, background: bool) -> None:
        with self._cond:
            if background:
                deadline = time.monotonic() + 600
                while self._interactive and time.monotonic() < deadline:
                    self._cond.wait(timeout=1)
            else:
                self._interactive += 1

    def leave(self, background: bool) -> None:
        if background:
            return
        with self._cond:
            self._interactive -= 1
            self._cond.notify_all()


class LLM(ABC):
    def __init__(self) -> None:
        self._gate = _Gate()

    @abstractmethod
    def _stream(
        self,
        messages: list[Message],
        *,
        images: list[bytes] | None,
        json_schema: dict | None,
        temperature: float,
        max_tokens: int,
    ) -> Iterator[str]:
        """Yield pieces of the reply as they are generated."""

    @abstractmethod
    def has_vision(self) -> bool:
        """Whether a model that can read images is configured and available."""

    def stream(
        self,
        messages: list[Message],
        *,
        images: list[bytes] | None = None,
        json_schema: dict | None = None,
        temperature: float = 0.2,
        max_tokens: int = 1024,
        background: bool = False,
    ) -> Iterator[str]:
        self._gate.enter(background)
        try:
            yield from self._stream(
                messages,
                images=images,
                json_schema=json_schema,
                temperature=temperature,
                max_tokens=max_tokens,
            )
        finally:
            self._gate.leave(background)

    def chat(self, messages: list[Message], **kwargs) -> str:
        return "".join(self.stream(messages, **kwargs)).strip()

    def chat_json(self, messages: list[Message], model: type[T], **kwargs) -> T:
        """Ask for a reply matching a pydantic model. Retries once on bad output."""
        from ..rag import prompts  # here, not at the top: rag imports this module

        schema = model.model_json_schema()
        messages = [dict(m) for m in messages]
        messages[-1]["content"] = f"{messages[-1]['content']}\n\n{prompts.JSON_QUOTES_NOTE}"
        last_error: Exception | None = None
        for _ in range(2):
            raw = self.chat(messages, json_schema=schema, **kwargs)
            try:
                return model.model_validate(extract_json(raw))
            except (ValueError, ValidationError) as exc:
                last_error = exc
        raise LLMError(f"The model did not return valid data: {last_error}")


def extract_json(raw: str) -> object:
    """Parse JSON from a model reply, tolerating code fences and surrounding prose."""
    text = raw.strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fenced:
        text = fenced.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    start = min((i for i in (text.find("{"), text.find("[")) if i != -1), default=-1)
    if start == -1:
        raise ValueError("no JSON found in model reply")
    decoder = json.JSONDecoder()
    try:
        value, _ = decoder.raw_decode(text[start:])
    except json.JSONDecodeError as exc:
        repaired = _repair(text[start:])
        if repaired is None:
            raise ValueError(f"invalid JSON in model reply: {exc}") from exc
        return repaired
    return value


def _repair(text: str) -> object | None:
    """Rescue a reply where the model closed a text with a curly quote.

    The reply then usually stops short as well, so the missing end is tried too.
    """
    fixed = re.sub(r"[\u201c\u201d](?=\s*(?:[,}\]]|$))", '"', text).rstrip()
    for ending in ("", "}", '"}', "]}", '"]}'):
        try:
            return json.loads(fixed + ending)
        except json.JSONDecodeError:
            continue
    return None
