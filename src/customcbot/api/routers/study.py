"""Summaries, quizzes and flashcards."""

from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from ...ai.base import LLMError
from ...database.repository import (
    repo_execute,
    repo_one,
    repo_query,
)
from ...domain import Collection
from ...exceptions import InvalidInputError, NotFoundError
from ...graphs import flashcards, quiz
from .. import command_service

router = APIRouter(prefix="/api")



class SummaryBody(BaseModel):
    source_id: int | None = None


class QuizBody(BaseModel):
    count: int = 5
    style: str = "mcq"
    source_ids: list[int] | None = None


class CardsBody(BaseModel):
    count: int = 10
    source_ids: list[int] | None = None


class GradeBody(BaseModel):
    question_id: int
    answer: str


class ScoreBody(BaseModel):
    score: float


class ReviewBody(BaseModel):
    known: bool


class CardBody(BaseModel):
    front: str
    back: str


def _require_collection(collection_id: int) -> None:
    Collection.get(collection_id)


# -- summaries ------------------------------------------------------------


@router.get("/collections/{collection_id}/summary")
def get_summary(collection_id: int) -> dict:
    collection = repo_one("SELECT summary FROM collections WHERE id = ?", (collection_id,))
    if collection is None:
        raise NotFoundError("That collection no longer exists.")
    sources = repo_query(
        "SELECT id, title, kind, summary FROM sources WHERE collection_id = ? AND status = 'ready' ORDER BY id",
        (collection_id,),
    )
    return {"summary": collection["summary"], "sources": sources}


@router.post("/collections/{collection_id}/summary")
def make_summary(collection_id: int, body: SummaryBody, request: Request) -> dict:
    _require_collection(collection_id)
    worker = request.app.state.services.worker
    if body.source_id is not None:
        return command_service.submit_command_job(
            worker, "summary_source", collection_id, {"source_id": body.source_id}
        )
    return command_service.submit_command_job(worker, "summary_collection", collection_id, {})


# -- quizzes --------------------------------------------------------------


@router.get("/collections/{collection_id}/quizzes")
def list_quizzes(collection_id: int) -> list[dict]:
    rows = repo_query(
        "SELECT id, title, questions, best_score, created_at FROM quizzes WHERE collection_id = ? ORDER BY id DESC",
        (collection_id,),
    )
    for row in rows:
        row["question_count"] = len(json.loads(row.pop("questions")))
    return rows


@router.post("/collections/{collection_id}/quizzes")
def make_quiz(collection_id: int, body: QuizBody, request: Request) -> dict:
    _require_collection(collection_id)
    if body.style not in ("mcq", "short", "mixed"):
        raise InvalidInputError("Unknown question style.")
    worker = request.app.state.services.worker
    return command_service.submit_command_job(worker, "quiz", collection_id, body.model_dump())


@router.get("/quizzes/{quiz_id}")
def get_quiz(quiz_id: int) -> dict:
    row = repo_one("SELECT * FROM quizzes WHERE id = ?", (quiz_id,))
    if row is None:
        raise NotFoundError("That quiz no longer exists.")
    row["questions"] = json.loads(row["questions"])
    return row


@router.delete("/quizzes/{quiz_id}")
def delete_quiz(quiz_id: int) -> dict:
    repo_execute("DELETE FROM quizzes WHERE id = ?", (quiz_id,))
    return {"ok": True}


@router.post("/quizzes/{quiz_id}/grade")
def grade_answer(quiz_id: int, body: GradeBody, request: Request) -> dict:
    try:
        return quiz.grade(quiz_id, body.question_id, body.answer, request.app.state.services)
    except ValueError as exc:
        raise InvalidInputError(str(exc)) from exc
    except LLMError as exc:
        raise HTTPException(503, str(exc)) from exc


@router.post("/quizzes/{quiz_id}/score")
def save_score(quiz_id: int, body: ScoreBody) -> dict:
    score = max(0.0, min(body.score, 1.0))
    repo_execute(
        "UPDATE quizzes SET best_score = MAX(COALESCE(best_score, 0), ?) WHERE id = ?", (score, quiz_id)
    )
    return {"ok": True}


# -- flashcards -----------------------------------------------------------


@router.get("/collections/{collection_id}/flashcards")
def list_flashcards(collection_id: int, due: bool = False) -> list[dict]:
    return flashcards.list_cards(collection_id, due_only=due)


@router.post("/collections/{collection_id}/flashcards")
def make_flashcards(collection_id: int, body: CardsBody, request: Request) -> dict:
    _require_collection(collection_id)
    worker = request.app.state.services.worker
    return command_service.submit_command_job(worker, "flashcards", collection_id, body.model_dump())


@router.post("/flashcards/{card_id}/review")
def review_card(card_id: int, body: ReviewBody) -> dict:
    card = flashcards.review(card_id, body.known)
    if card is None:
        raise NotFoundError("That card no longer exists.")
    return card


@router.put("/flashcards/{card_id}")
def edit_card(card_id: int, body: CardBody) -> dict:
    if not body.front.strip() or not body.back.strip():
        raise InvalidInputError("A card needs a front and a back.")
    repo_execute(
        "UPDATE flashcards SET front = ?, back = ? WHERE id = ?", (body.front.strip(), body.back.strip(), card_id)
    )
    return {"ok": True}


@router.delete("/flashcards/{card_id}")
def delete_card(card_id: int) -> dict:
    repo_execute("DELETE FROM flashcards WHERE id = ?", (card_id,))
    return {"ok": True}
