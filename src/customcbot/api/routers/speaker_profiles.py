"""Speaker profiles: the voices that speak in a podcast."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from ...domain import SpeakerProfile
from ...exceptions import InvalidInputError
from ...podcasts import voices

router = APIRouter(prefix="/api")


class SpeakerProfileBody(BaseModel):
    name: str
    description: str = ""
    speakers: list[dict]


def _listing() -> list[dict]:
    return [p.model_dump() for p in SpeakerProfile.where()]


@router.get("/podcast-voices")
def list_voices() -> list[dict]:
    return voices.catalog()


@router.get("/speaker-profiles")
def list_speaker_profiles() -> list[dict]:
    return _listing()


@router.post("/speaker-profiles")
def add_speaker_profile(body: SpeakerProfileBody) -> list[dict]:
    name, speakers = SpeakerProfile.clean(body.name, body.speakers)
    SpeakerProfile(name=name, description=body.description.strip()[:200], speakers=speakers).save()
    return _listing()


@router.put("/speaker-profiles/{profile_id}")
def change_speaker_profile(profile_id: int, body: SpeakerProfileBody) -> list[dict]:
    profile = SpeakerProfile.get(profile_id)
    name, speakers = SpeakerProfile.clean(body.name, body.speakers)
    profile.name, profile.description, profile.speakers = name, body.description.strip()[:200], speakers
    profile.save()
    return _listing()


@router.delete("/speaker-profiles/{profile_id}")
def delete_speaker_profile(profile_id: int) -> list[dict]:
    profile = SpeakerProfile.get(profile_id)
    if len(SpeakerProfile.where()) == 1:
        raise InvalidInputError("Keep at least one set of voices.")
    profile.delete()
    return _listing()
