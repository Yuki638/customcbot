"""Podcasts: who speaks (speaker profiles), what kind of episode (episode profiles), and episodes."""

from __future__ import annotations

import json
from typing import Any, ClassVar

from pydantic import BaseModel, field_validator

from .. import config
from ..database.repository import repo_query
from ..exceptions import InvalidInputError
from ..podcasts.voices import VOICE_IDS
from .base import ObjectModel

MAX_SPEAKERS = 4
MAX_SEGMENTS = 6


def _from_json(value: Any) -> Any:
    return json.loads(value) if isinstance(value, str) else value


class Speaker(BaseModel):
    name: str
    voice: str
    role: str = ""


class SpeakerProfile(ObjectModel):
    table_name: ClassVar[str] = "speaker_profiles"
    missing_message: ClassVar[str] = "That set of voices no longer exists."

    name: str
    description: str = ""
    speakers: list[Speaker]

    _parse = field_validator("speakers", mode="before")(_from_json)

    def _columns(self) -> dict:
        data = super()._columns()
        data["speakers"] = json.dumps(data["speakers"])
        return data

    @staticmethod
    def clean(name: str, speakers: list[dict]) -> tuple[str, list[Speaker]]:
        name = name.strip()
        if not name:
            raise InvalidInputError("Give this set of voices a name.")
        cleaned: list[Speaker] = []
        for item in speakers:
            speaker_name = str(item.get("name", "")).strip()[:30]
            if not speaker_name:
                raise InvalidInputError("Every speaker needs a name.")
            if item.get("voice") not in VOICE_IDS:
                raise InvalidInputError(f"Choose a voice for {speaker_name}.")
            role = str(item.get("role", "")).strip()[:200] or "who speaks clearly"
            cleaned.append(Speaker(name=speaker_name, voice=item["voice"], role=role))
        if not 1 <= len(cleaned) <= MAX_SPEAKERS:
            raise InvalidInputError(f"Use between one and {MAX_SPEAKERS} speakers.")
        if len({s.name.lower() for s in cleaned}) != len(cleaned):
            raise InvalidInputError("Give each speaker a different name.")
        return name[:60], cleaned


class EpisodeProfile(ObjectModel):
    table_name: ClassVar[str] = "episode_profiles"
    missing_message: ClassVar[str] = "That kind of episode no longer exists."

    name: str
    description: str = ""
    speaker_profile_id: int | None = None
    briefing: str
    segments: int = 3

    @staticmethod
    def clean(name: str, briefing: str, segments: int) -> tuple[str, str, int]:
        name, briefing = name.strip(), briefing.strip()
        if not name:
            raise InvalidInputError("Give this kind of episode a name.")
        if not briefing:
            raise InvalidInputError("Describe what the episode should be like.")
        return name[:60], briefing[:1000], max(1, min(int(segments), MAX_SEGMENTS))


class PodcastEpisode(ObjectModel):
    table_name: ClassVar[str] = "podcast_episodes"
    missing_message: ClassVar[str] = "That episode no longer exists."

    collection_id: int
    episode_profile_id: int | None = None
    title: str
    briefing: str = ""
    outline: dict | None = None
    transcript: list[dict] | None = None
    audio_path: str | None = None
    duration_sec: float | None = None
    status: str = "queued"  # queued | working | ready | error
    error: str | None = None
    job_id: int | None = None

    _parse = field_validator("outline", "transcript", mode="before")(_from_json)

    def _columns(self) -> dict:
        data = super()._columns()
        for key in ("outline", "transcript"):
            data[key] = json.dumps(data[key]) if data[key] is not None else None
        return data

    def update(self, **fields: Any):
        stored = {k: json.dumps(v) if k in ("outline", "transcript") and v is not None else v for k, v in fields.items()}
        super().update(**stored)
        for key, value in fields.items():  # keep the real values on the object, not their stored form
            setattr(self, key, value)
        return self

    @staticmethod
    def list_for_collection(collection_id: int) -> list[dict]:
        return repo_query(
            "SELECT id, title, status, error, duration_sec, job_id, created_at FROM podcast_episodes "
            "WHERE collection_id = ? ORDER BY id DESC",
            (collection_id,),
        )

    def audio_file(self):
        return config.podcasts_dir() / self.audio_path if self.audio_path else None

    def public(self) -> dict:
        return self.model_dump(exclude={"audio_path"}) | {"has_audio": bool(self.audio_path)}

    def delete(self) -> None:
        path = self.audio_file()
        if path is not None:
            path.unlink(missing_ok=True)
        super().delete()
