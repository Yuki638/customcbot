"""Commands that carry out transformations on sources."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..exceptions import CustomcbotError
from ..graphs.transformation import run_transformation
from .registry import command

if TYPE_CHECKING:
    from ..services import Services
    from .worker import JobContext


@command("run_transformation", stop_on=(CustomcbotError, ValueError))
def run_transformation_command(job: dict, params: dict, services: Services, context: JobContext) -> dict:
    insight = run_transformation(int(params["source_id"]), int(params["transformation_id"]), services, context)
    return {"insight_id": insight.id, "source_id": insight.source_id}
