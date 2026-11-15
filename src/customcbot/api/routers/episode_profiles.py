"""Episode profiles: the kinds of podcast episode that can be made."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from ...domain import EpisodeProfile, SpeakerProfile
from ...exceptions import InvalidInputError

router = APIRouter(prefix="/api")


class EpisodeProfileBody(BaseModel):
    name: str
    description: str = ""
    speaker_profile_id: int
    briefing: str
    segments: int = 3


def _listing() -> list[dict]:
    return [p.model_dump() for p in EpisodeProfile.where()]


@router.get("/episode-profiles")
def list_episode_profiles() -> list[dict]:
    return _listing()


@router.post("/episode-profiles")
def add_episode_profile(body: EpisodeProfileBody) -> list[dict]:
    name, briefing, segments = EpisodeProfile.clean(body.name, body.briefing, body.segments)
    SpeakerProfile.get(body.speaker_profile_id)
    EpisodeProfile(
        name=name,
        description=body.description.strip()[:200],
        speaker_profile_id=body.speaker_profile_id,
        briefing=briefing,
        segments=segments,
    ).save()
    return _listing()


@router.put("/episode-profiles/{profile_id}")
def change_episode_profile(profile_id: int, body: EpisodeProfileBody) -> list[dict]:
    profile = EpisodeProfile.get(profile_id)
    name, briefing, segments = EpisodeProfile.clean(body.name, body.briefing, body.segments)
    SpeakerProfile.get(body.speaker_profile_id)
    profile.update(
        name=name,
        description=body.description.strip()[:200],
        speaker_profile_id=body.speaker_profile_id,
        briefing=briefing,
        segments=segments,
    )
    return _listing()


@router.delete("/episode-profiles/{profile_id}")
def delete_episode_profile(profile_id: int) -> list[dict]:
    profile = EpisodeProfile.get(profile_id)
    if len(EpisodeProfile.where()) == 1:
        raise InvalidInputError("Keep at least one kind of episode.")
    profile.delete()
    return _listing()
