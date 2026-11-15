"""A model to use from a saved service, and which model does which job."""

from __future__ import annotations

from typing import ClassVar

from .base import ObjectModel, RecordModel

LANGUAGE = "language"
TEXT_TO_SPEECH = "text_to_speech"


class Model(ObjectModel):
    table_name: ClassVar[str] = "models"
    missing_message: ClassVar[str] = "That model is no longer saved."

    credential_id: int
    name: str
    type: str = LANGUAGE
    vision: bool = False  # can read images

    def public(self) -> dict:
        return self.model_dump(include={"id", "credential_id", "name", "type", "vision"})


class DefaultModels(RecordModel):
    """The model used for each kind of work. A blank one falls back as `ai/models.py` describes."""

    record_id: ClassVar[str] = "record:default_models"

    chat: int | None = None  # answering questions
    transformation: int | None = None  # summaries, quizzes, flashcards, insights
    vision: int | None = None  # reading handwriting and scanned pages
    text_to_speech: int | None = None  # podcasts
