"""The shared objects the app runs on: model, embedder, worker, hardware."""

from __future__ import annotations

from dataclasses import dataclass, field

from .ai.base import LLM
from .ai.embeddings import Embedder
from .ai.hardware import Hardware
from .commands.worker import Worker


@dataclass
class Services:
    llm: LLM
    embedder: Embedder
    hardware: Hardware
    fake: bool = False  # running with the built-in stand-in model
    worker: Worker = field(init=False)

    def __post_init__(self) -> None:
        self.worker = Worker(self)
