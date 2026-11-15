"""Commands that read and index a source."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..ai import base as ai_base
from ..database.repository import repo_execute
from ..graphs.source import process_source
from .registry import command

if TYPE_CHECKING:
    from ..services import Services
    from .worker import JobContext


@command("process_source")
def process_source_command(job: dict, params: dict, services: Services, context: JobContext) -> dict:
    source_id = int(params["source_id"])
    # A source shows its own progress line, so a "waiting for the service" note goes there.
    ai_base.set_notice_hook(
        lambda text: repo_execute("UPDATE sources SET stage = ? WHERE id = ?", (text, source_id))
    )
    process_source(source_id, services)
    return {"source_id": source_id}
