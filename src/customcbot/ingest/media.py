"""Speech-to-text for audio and video files, running on the CPU."""

from __future__ import annotations

import threading
from collections.abc import Callable
from pathlib import Path

import numpy as np

from ..utils.chunking import Unit

SAMPLE_RATE = 16000  # what the speech-to-text model expects


class MediaError(Exception):
    """A problem with an audio or video file, worded for the end user."""


def decode_audio(path: Path) -> np.ndarray:
    """Read the sound of any audio or video file as mono 16 kHz samples.

    This is done here rather than by faster-whisper, whose own reader passes an
    option that newer PyAV releases no longer accept.
    """
    import av

    resampler = av.AudioResampler(format="s16", layout="mono", rate=SAMPLE_RATE)
    pieces: list[np.ndarray] = []
    with av.open(str(path)) as container:
        stream = next((s for s in container.streams if s.type == "audio"), None)
        if stream is None:
            raise MediaError("This file has no sound to transcribe.")
        for frame in container.decode(stream):
            pieces.extend(out.to_ndarray().reshape(-1) for out in resampler.resample(frame))
        pieces.extend(out.to_ndarray().reshape(-1) for out in resampler.resample(None))
    if not pieces:
        raise MediaError("This file has no sound to transcribe.")
    return np.concatenate(pieces).astype(np.float32) / 32768.0

_models: dict[str, object] = {}
_lock = threading.Lock()


def transcribe(
    path: Path, model_size: str, cache_dir: Path, progress: Callable[[str, float], None]
) -> list[Unit]:
    from faster_whisper import WhisperModel

    with _lock:
        if model_size not in _models:
            progress("Getting the speech-to-text model ready", 0.0)
            # int8 on the CPU works everywhere and needs no GPU libraries.
            _models[model_size] = WhisperModel(
                model_size, device="cpu", compute_type="int8", download_root=str(cache_dir)
            )
        model = _models[model_size]

    progress("Reading the audio", 0.0)
    segments, info = model.transcribe(decode_audio(path), vad_filter=True)
    duration = info.duration or 0
    units: list[Unit] = []
    for segment in segments:
        text = segment.text.strip()
        if text:
            units.append(Unit(text=text, start_sec=float(segment.start), method="whisper"))
        if duration:
            minutes = int(segment.end // 60)
            progress(f"Listening to the audio ({minutes} of {int(duration // 60) + 1} min)", segment.end / duration)
    return units
