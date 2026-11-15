"""The command that makes a podcast episode."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..domain.podcast import PodcastEpisode
from ..podcasts.generate import generate
from .registry import command
from .worker import Cancelled

if TYPE_CHECKING:
    from ..services import Services
    from .worker import JobContext


# One attempt only: an episode takes minutes, so trying again is the user's choice.
@command("generate_podcast", max_attempts=1)
def generate_podcast_command(job: dict, params: dict, services: Services, context: JobContext) -> dict:
    episode_id = int(params["episode_id"])
    try:
        episode = generate(episode_id, params.get("source_ids") or None, services, context)
    except Cancelled:
        found = PodcastEpisode.find(episode_id)
        if found is not None:
            found.delete()
        raise
    except Exception as exc:
        found = PodcastEpisode.find(episode_id)
        if found is not None:
            found.update(status="error", error=str(exc)[:400] or type(exc).__name__)
        raise
    return {"episode_id": episode.id, "seconds": episode.duration_sec}
