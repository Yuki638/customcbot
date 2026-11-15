"""Turns text into vectors so passages can be found by meaning."""

from __future__ import annotations

import hashlib
import re
import threading
from abc import ABC, abstractmethod

import numpy as np


class Embedder(ABC):
    @abstractmethod
    def embed(self, texts: list[str]) -> np.ndarray:
        """Return one unit-length float32 row per text."""

    def prepare(self) -> None:  # noqa: B027 - optional hook, not every embedder needs it
        """Download and load whatever the embedder needs. Safe to call twice."""


def _normalize(matrix: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    return (matrix / np.maximum(norms, 1e-12)).astype(np.float32)


class FastEmbedder(Embedder):
    """A small ONNX model that runs on the CPU, in this process.

    It never competes with the chat model for memory inside Ollama, which
    matters on low-memory machines.
    """

    def __init__(self, model_name: str, cache_dir: str) -> None:
        self.model_name = model_name
        self.cache_dir = cache_dir
        self._model = None
        self._lock = threading.Lock()

    def prepare(self) -> None:
        with self._lock:
            if self._model is None:
                from fastembed import TextEmbedding

                self._model = TextEmbedding(self.model_name, cache_dir=self.cache_dir)

    def embed(self, texts: list[str]) -> np.ndarray:
        self.prepare()
        with self._lock:
            vectors = list(self._model.embed(texts, batch_size=16))
        return _normalize(np.asarray(vectors, dtype=np.float32))


class FakeEmbedder(Embedder):
    """Word-hashing vectors for tests: texts sharing words score as similar."""

    dim = 256

    def embed(self, texts: list[str]) -> np.ndarray:
        matrix = np.zeros((len(texts), self.dim), dtype=np.float32)
        for row, text in enumerate(texts):
            for word in re.findall(r"\w+", text.lower()):
                digest = hashlib.md5(word.encode()).digest()
                matrix[row, int.from_bytes(digest[:4], "little") % self.dim] += 1.0
        return _normalize(matrix)
