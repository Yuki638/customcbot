"""Makes one episode: collect the material, plan it, write the script, record it.

The script is written part by part, so each request stays small enough for a
local model, and every line names its speaker so it can be given that voice.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from .. import config
from ..ai import base as ai_base
from ..commands.worker import JobContext
from ..database.repository import repo_query
from ..domain.podcast import EpisodeProfile, PodcastEpisode, Speaker, SpeakerProfile
from ..graphs import summary
from ..utils.prompter import render
from . import audio
from .voices import DEFAULT_VOICE

if TYPE_CHECKING:
    from ..services import Services

LINES_LOCAL, LINES_ONLINE = 6, 9  # spoken lines per part
_NOT_SPOKEN = re.compile(r"\[\d+(?:\s*,\s*\d+)*\]|[*_#`>|~]")


class Segment(BaseModel):
    title: str
    points: list[str] = Field(min_length=1)


class Outline(BaseModel):
    title: str
    segments: list[Segment] = Field(min_length=1)


class Line(BaseModel):
    speaker: str
    text: str


class Dialogue(BaseModel):
    lines: list[Line] = Field(min_length=1)


def _material(collection_id: int, source_ids: list[int] | None, services: Services, context: JobContext) -> str:
    """The text the episode is made from, reduced to notes if it is too long for one prompt."""
    sql = (
        "SELECT c.text FROM chunks c JOIN sources s ON s.id = c.source_id "
        "WHERE c.collection_id = ? AND s.status = 'ready'"
    )
    params: list = [collection_id]
    if source_ids:
        sql += f" AND c.source_id IN ({','.join('?' * len(source_ids))})"
        params += list(source_ids)
    texts = [r["text"] for r in repo_query(sql + " ORDER BY c.source_id, c.ord", params)]
    if not texts:
        raise ValueError("Add some material first.")
    size = config.passage_budget()[0]
    windows = summary._windows(texts, size)
    if len(windows) == 1:
        return windows[0]
    parts = []
    for index, window in enumerate(windows):
        context.progress(f"Reading your material (part {index + 1} of {len(windows)})", 0.25 * index / len(windows))
        parts.append(summary._notes(window, services))
    return summary._condense(parts, size, services, context, "Combining notes")


def spoken(text: str) -> str:
    """Remove what cannot be read aloud: citation numbers and formatting marks."""
    text = " ".join(_NOT_SPOKEN.sub("", text).split())
    # A small model sometimes leaves one quotation mark at the end of a line.
    for mark in ("\u201d", "\u201c", '"'):
        if text.count(mark) == 1 and text.count("\u201c") + text.count("\u201d") + text.count('"') == 1:
            text = text.replace(mark, "").strip()
    return text


def _assign(lines: list[Line], speakers: list[Speaker], previous: str = "") -> list[dict]:
    """Give every line one of the profile's speakers, whatever name the model wrote.

    A line that only repeats the one before it (a small model sometimes starts a
    part by saying the previous part's last line again) is left out.
    """
    by_name = {s.name.lower(): s for s in speakers}
    out = []
    last = previous.strip().lower()
    for index, line in enumerate(lines):
        text = spoken(line.text)
        if not text or (last and text.lower().startswith(last[:300])):
            continue
        last = text.lower()
        speaker = by_name.get(line.speaker.strip().lower()) or speakers[index % len(speakers)]
        out.append({"speaker": speaker.name, "voice": speaker.voice, "text": text})
    return out


def generate(episode_id: int, source_ids: list[int] | None, services: Services, context: JobContext) -> PodcastEpisode:
    episode = PodcastEpisode.get(episode_id)
    profile = EpisodeProfile.find(episode.episode_profile_id) if episode.episode_profile_id else None
    voices = SpeakerProfile.find(profile.speaker_profile_id) if profile and profile.speaker_profile_id else None
    speakers = voices.speakers if voices else [Speaker(name="Narrator", voice=DEFAULT_VOICE, role="a calm narrator")]
    briefing = episode.briefing or (profile.briefing if profile else "A clear overview of the material.")
    segments = profile.segments if profile else 2
    episode.update(status="working", error=None)

    context.progress("Reading your material", 0.02)
    material = _material(episode.collection_id, source_ids, services, context)
    model = services.model("transformation")

    context.progress("Planning the episode", 0.3)
    outline = model.chat_json(
        [
            {"role": "system", "content": render("podcast/outline_system", segments=segments)},
            {"role": "user", "content": render("podcast/outline_user", briefing=briefing, material=material)},
        ],
        Outline,
        temperature=0.3,
        max_tokens=600,
        background=True,
    )
    parts = outline.segments[:segments]
    episode.update(title=outline.title.strip()[:120] or episode.title, outline=outline.model_dump())

    lines_per_part = LINES_ONLINE if config.online() else LINES_LOCAL
    script: list[list[dict]] = []
    previous = ""
    for index, part in enumerate(parts):
        context.progress(f"Writing part {index + 1} of {len(parts)}", 0.35 + 0.25 * index / len(parts))
        system = render(
            "podcast/transcript_system",
            speakers=[s.model_dump() for s in speakers],
            names=", ".join(s.name for s in speakers),
            lines=lines_per_part,
            first=index == 0,
            last=index == len(parts) - 1,
        )
        user = render(
            "podcast/transcript_user",
            title=outline.title,
            briefing=briefing,
            segment_title=part.title,
            points=part.points,
            previous=previous,
            material=material,
        )
        dialogue = model.chat_json(
            [{"role": "system", "content": system}, {"role": "user", "content": user}],
            Dialogue,
            temperature=0.5,
            max_tokens=1100,
            background=True,
        )
        lines = _assign(dialogue.lines, speakers, previous)
        if lines:
            script.append(lines)
            previous = lines[-1]["text"][:300]
    if not script:
        raise ValueError("The model wrote no script. Try again, or choose another model in Settings.")
    transcript = [{"speaker": line["speaker"], "text": line["text"]} for part in script for line in part]
    episode.update(transcript=transcript)

    speech = services.speech
    speech.prepare(ai_base.notify)
    total = sum(len(part) for part in script)
    recorded: list[list] = []
    done = 0
    for part in script:
        takes = []
        for line in part:
            context.progress(f"Recording line {done + 1} of {total}", 0.6 + 0.38 * done / total)
            takes.append(speech.say(line["text"], line["voice"]))
            done += 1
        recorded.append(takes)

    context.progress("Saving the audio", 0.98)
    name = f"{episode.id}.mp3"
    seconds = audio.save_mp3(audio.join(recorded), config.podcasts_dir() / name)
    return episode.update(audio_path=name, duration_sec=round(seconds, 1), status="ready")
