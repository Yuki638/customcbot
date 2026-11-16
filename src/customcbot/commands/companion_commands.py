"""Background work for the study companion."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..graphs import companion
from .registry import command

if TYPE_CHECKING:
    from ..services import Services
    from .worker import JobContext


@command("remember", max_attempts=1)
def remember_command(job: dict, params: dict, services: Services, context: JobContext) -> dict:
    return {"stored": companion.learn(params["message"], services)}
