"""Speech-to-text for audio and video files, running on the CPU."""

from __future__ import annotations

import threading
from collections.abc import Callable
from pathlib import Path

from .chunking import Unit

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

    segments, info = model.transcribe(str(path), vad_filter=True)
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
