"""Commands behind the study tools: summaries, quizzes and flashcards."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..graphs import flashcards, quiz, summary
from .registry import command

if TYPE_CHECKING:
    from ..services import Services
    from .worker import JobContext


@command("summary_source")
def summarize_source_command(job: dict, params: dict, services: Services, context: JobContext) -> dict:
    return summary.job_summarize_source(job, params, services, context)


@command("summary_collection")
def summarize_collection_command(job: dict, params: dict, services: Services, context: JobContext) -> dict:
    return summary.job_summarize_collection(job, params, services, context)


@command("quiz")
def generate_quiz_command(job: dict, params: dict, services: Services, context: JobContext) -> dict:
    return quiz.job_generate(job, params, services, context)


@command("flashcards")
def generate_flashcards_command(job: dict, params: dict, services: Services, context: JobContext) -> dict:
    return flashcards.job_generate(job, params, services, context)
