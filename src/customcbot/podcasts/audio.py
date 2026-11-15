"""Joins spoken lines into one episode and saves it as an MP3 file."""

from __future__ import annotations

from pathlib import Path

import av
import numpy as np

from .speech import SAMPLE_RATE

PAUSE_BETWEEN_LINES = 0.35  # seconds
PAUSE_BETWEEN_PARTS = 0.8


def silence(seconds: float) -> np.ndarray:
    return np.zeros(int(seconds * SAMPLE_RATE), dtype=np.float32)


def join(parts: list[list[np.ndarray]]) -> np.ndarray:
    """One recording from the lines of each part, with short pauses in between."""
    pieces: list[np.ndarray] = []
    for part in parts:
        for line in part:
            pieces += [line, silence(PAUSE_BETWEEN_LINES)]
        if pieces:
            pieces[-1] = silence(PAUSE_BETWEEN_PARTS)
    if not pieces:
        return silence(0)
    audio = np.concatenate(pieces[:-1])
    peak = float(np.max(np.abs(audio))) if len(audio) else 0.0
    return audio * (0.9 / peak) if peak > 0.9 else audio  # never clip


def save_mp3(samples: np.ndarray, path: Path) -> float:
    """Write the samples as a mono MP3 and return the length in seconds."""
    path.parent.mkdir(parents=True, exist_ok=True)
    pcm = (np.clip(samples, -1.0, 1.0) * 32767).astype(np.int16)
    with av.open(str(path), "w", format="mp3") as container:
        stream = container.add_stream("libmp3lame", rate=SAMPLE_RATE)
        stream.bit_rate = 64000
        stream.layout = "mono"
        for start in range(0, len(pcm), SAMPLE_RATE):  # one second at a time
            frame = av.AudioFrame.from_ndarray(pcm[start : start + SAMPLE_RATE].reshape(1, -1), format="s16", layout="mono")
            frame.sample_rate = SAMPLE_RATE
            for packet in stream.encode(frame):
                container.mux(packet)
        for packet in stream.encode(None):
            container.mux(packet)
    return len(pcm) / SAMPLE_RATE
