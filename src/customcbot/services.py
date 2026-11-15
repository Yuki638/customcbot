"""The shared objects the app runs on: models, embedder, worker, hardware."""

from __future__ import annotations

from dataclasses import dataclass, field

from .ai.base import LLM
from .ai.embeddings import Embedder
from .ai.hardware import Hardware
from .ai.provision import Provisioner
from .commands.worker import Worker
from .podcasts.speech import FakeSpeech, KokoroSpeech, Speech


@dataclass
class Services:
    embedder: Embedder
    hardware: Hardware
    # A fixed model used for every job. Set only by the tests and the demo mode;
    # normally each job gets the model chosen for it in Settings.
    llm: LLM | None = None
    fake: bool = False  # running with the built-in stand-in model
    provisioner: Provisioner = field(default_factory=Provisioner)
    speech: Speech | None = None  # text to speech, for podcasts
    worker: Worker = field(init=False)

    def __post_init__(self) -> None:
        if self.speech is None:
            # The stand-in model gets stand-in speech; otherwise the offline voices.
            self.speech = FakeSpeech() if (self.fake or self.llm is not None) else KokoroSpeech()
        self.worker = Worker(self)

    def model(self, task: str = "chat") -> LLM:
        """The model for a job: "chat", "transformation" or "vision"."""
        return self.llm if self.llm is not None else self.provisioner.model_for(task)
