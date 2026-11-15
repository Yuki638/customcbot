"""Text to speech.

`KokoroSpeech` runs a small open model on the CPU, in this process, so nothing
is sent anywhere. Its files (about 350 MB) are downloaded the first time a
podcast is made. `FakeSpeech` makes placeholder tones for tests and demo mode.
"""

from __future__ import annotations

import threading
from abc import ABC, abstractmethod
from collections.abc import Callable
from pathlib import Path

import numpy as np

from .. import config
from .voices import language_code

SAMPLE_RATE = 24000
MODEL_REPO = "fastrtc/kokoro-onnx"
MODEL_FILE, VOICES_FILE = "kokoro-v1.0.onnx", "voices-v1.0.bin"
DOWNLOAD_NOTE = "Getting the voices ready (about 350 MB, the first time only)"


class SpeechError(RuntimeError):
    """A problem to show to the user as-is."""


class Speech(ABC):
    @abstractmethod
    def say(self, text: str, voice: str) -> np.ndarray:
        """The text spoken in the given voice: mono float32 samples at SAMPLE_RATE."""

    def prepare(self, notify: Callable[[str], None] | None = None) -> None:  # noqa: B027
        """Download and load whatever is needed. Safe to call twice."""


class KokoroSpeech(Speech):
    def __init__(self, folder: Path | None = None) -> None:
        self._folder = folder
        self._model = None
        self._lock = threading.Lock()

    def prepare(self, notify: Callable[[str], None] | None = None) -> None:
        with self._lock:
            if self._model is not None:
                return
            folder = self._folder or (config.models_dir() / "speech")
            try:
                from huggingface_hub import hf_hub_download
                from kokoro_onnx import Kokoro

                if notify and not any(folder.rglob(MODEL_FILE)):
                    notify(DOWNLOAD_NOTE)
                model = hf_hub_download(MODEL_REPO, MODEL_FILE, cache_dir=str(folder))
                voices = hf_hub_download(MODEL_REPO, VOICES_FILE, cache_dir=str(folder))
                self._model = Kokoro(model, voices)
            except Exception as exc:
                raise SpeechError(
                    "The voices could not be set up. Check your internet connection and try again. "
                    f"({type(exc).__name__}: {str(exc)[:160]})"
                ) from exc

    def say(self, text: str, voice: str) -> np.ndarray:
        self.prepare()
        with self._lock:
            samples, rate = self._model.create(text, voice=voice, speed=1.0, lang=language_code(voice))
        samples = np.asarray(samples, dtype=np.float32)
        if rate != SAMPLE_RATE:  # the model speaks at 24 kHz; this guards against a future change
            positions = np.linspace(0, len(samples) - 1, int(len(samples) * SAMPLE_RATE / rate))
            samples = np.interp(positions, np.arange(len(samples)), samples).astype(np.float32)
        return samples


class FakeSpeech(Speech):
    """A soft tone per line, as long as the line would take to say. Each voice has its own pitch."""

    def __init__(self) -> None:
        self.said: list[tuple[str, str]] = []

    def say(self, text: str, voice: str) -> np.ndarray:
        self.said.append((voice, text))
        seconds = max(0.3, 0.06 * len(text.split()))
        pitch = 180 + (sum(voice.encode()) % 8) * 30
        moments = np.arange(int(seconds * SAMPLE_RATE)) / SAMPLE_RATE
        return (0.1 * np.sin(2 * np.pi * pitch * moments)).astype(np.float32)
