"""Podcast episodes: making one, listening to it, and removing it."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel

from ...domain import Collection, EpisodeProfile, PodcastEpisode
from ...exceptions import NotFoundError
from .. import command_service

router = APIRouter(prefix="/api")


class EpisodeBody(BaseModel):
    episode_profile_id: int
    briefing: str = ""  # extra wishes for this one episode
    source_ids: list[int] | None = None


@router.get("/collections/{collection_id}/podcasts")
def list_episodes(collection_id: int) -> list[dict]:
    return PodcastEpisode.list_for_collection(collection_id)


@router.post("/collections/{collection_id}/podcasts")
def make_episode(collection_id: int, body: EpisodeBody, request: Request) -> dict:
    """Start making an episode in the background. Returns its job."""
    Collection.get(collection_id)
    profile = EpisodeProfile.get(body.episode_profile_id)
    wishes = body.briefing.strip()[:500]
    episode = PodcastEpisode(
        collection_id=collection_id,
        episode_profile_id=profile.id,
        title=profile.name,
        briefing=f"{profile.briefing} {wishes}".strip(),
    ).save()
    job = command_service.submit_command_job(
        request.app.state.services.worker,
        "generate_podcast",
        collection_id,
        {"episode_id": episode.id, "source_ids": body.source_ids},
    )
    episode.update(job_id=job["id"])
    return job


@router.get("/podcasts/{episode_id}")
def get_episode(episode_id: int) -> dict:
    return PodcastEpisode.get(episode_id).public()


@router.get("/podcasts/{episode_id}/audio")
def episode_audio(episode_id: int, download: bool = False) -> FileResponse:
    episode = PodcastEpisode.get(episode_id)
    path = episode.audio_file()
    if path is None or not path.is_file():
        raise NotFoundError("This episode has no audio yet.")
    name = "".join(c if c.isalnum() or c in " -_" else "_" for c in episode.title).strip() or "episode"
    return FileResponse(
        path,
        media_type="audio/mpeg",
        filename=f"{name}.mp3",
        content_disposition_type="attachment" if download else "inline",
    )


@router.delete("/podcasts/{episode_id}")
def delete_episode(episode_id: int, request: Request) -> dict:
    episode = PodcastEpisode.get(episode_id)
    if episode.status in ("queued", "working") and episode.job_id:
        request.app.state.services.worker.cancel_job(episode.job_id)
    episode.delete()
    return {"ok": True}
