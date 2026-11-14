"""Summaries, quizzes, flashcards and the background jobs that create them."""

from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from .. import db
from ..llm.base import LLMError
from ..study import flashcards, quiz

router = APIRouter(prefix="/api")

JOB_FIELDS = "id, kind, collection_id, params, status, stage, progress, error, result, created_at"


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


def _job(row: dict) -> dict:
    row["params"] = json.loads(row["params"] or "{}")
    row["result"] = json.loads(row["result"]) if row["result"] else None
    return row


def _require_collection(collection_id: int) -> None:
    if db.one("SELECT id FROM collections WHERE id = ?", (collection_id,)) is None:
        raise HTTPException(404, "That collection no longer exists.")


# -- jobs -----------------------------------------------------------------


@router.get("/collections/{collection_id}/jobs")
def active_jobs(collection_id: int) -> list[dict]:
    rows = db.query(
        f"SELECT {JOB_FIELDS} FROM jobs WHERE collection_id = ? AND status IN ('queued', 'running') ORDER BY id",
        (collection_id,),
    )
    return [_job(r) for r in rows]


@router.get("/jobs/{job_id}")
def get_job(job_id: int) -> dict:
    row = db.one(f"SELECT {JOB_FIELDS} FROM jobs WHERE id = ?", (job_id,))
    if row is None:
        raise HTTPException(404, "That task no longer exists.")
    return _job(row)


@router.delete("/jobs/{job_id}")
def cancel_job(job_id: int, request: Request) -> dict:
    request.app.state.services.worker.cancel_job(job_id)
    return {"ok": True}


# -- summaries ------------------------------------------------------------


@router.get("/collections/{collection_id}/summary")
def get_summary(collection_id: int) -> dict:
    collection = db.one("SELECT summary FROM collections WHERE id = ?", (collection_id,))
    if collection is None:
        raise HTTPException(404, "That collection no longer exists.")
    sources = db.query(
        "SELECT id, title, kind, summary FROM sources WHERE collection_id = ? AND status = 'ready' ORDER BY id",
        (collection_id,),
    )
    return {"summary": collection["summary"], "sources": sources}


@router.post("/collections/{collection_id}/summary")
def make_summary(collection_id: int, body: SummaryBody, request: Request) -> dict:
    _require_collection(collection_id)
    worker = request.app.state.services.worker
    if body.source_id is not None:
        job_id = worker.submit_job("summary_source", collection_id, {"source_id": body.source_id})
    else:
        job_id = worker.submit_job("summary_collection", collection_id, {})
    return get_job(job_id)


# -- quizzes --------------------------------------------------------------


@router.get("/collections/{collection_id}/quizzes")
def list_quizzes(collection_id: int) -> list[dict]:
    rows = db.query(
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
        raise HTTPException(400, "Unknown question style.")
    job_id = request.app.state.services.worker.submit_job("quiz", collection_id, body.model_dump())
    return get_job(job_id)


@router.get("/quizzes/{quiz_id}")
def get_quiz(quiz_id: int) -> dict:
    row = db.one("SELECT * FROM quizzes WHERE id = ?", (quiz_id,))
    if row is None:
        raise HTTPException(404, "That quiz no longer exists.")
    row["questions"] = json.loads(row["questions"])
    return row


@router.delete("/quizzes/{quiz_id}")
def delete_quiz(quiz_id: int) -> dict:
    db.execute("DELETE FROM quizzes WHERE id = ?", (quiz_id,))
    return {"ok": True}


@router.post("/quizzes/{quiz_id}/grade")
def grade_answer(quiz_id: int, body: GradeBody, request: Request) -> dict:
    try:
        return quiz.grade(quiz_id, body.question_id, body.answer, request.app.state.services)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except LLMError as exc:
        raise HTTPException(503, str(exc)) from exc


@router.post("/quizzes/{quiz_id}/score")
def save_score(quiz_id: int, body: ScoreBody) -> dict:
    score = max(0.0, min(body.score, 1.0))
    db.execute(
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
    job_id = request.app.state.services.worker.submit_job("flashcards", collection_id, body.model_dump())
    return get_job(job_id)


@router.post("/flashcards/{card_id}/review")
def review_card(card_id: int, body: ReviewBody) -> dict:
    card = flashcards.review(card_id, body.known)
    if card is None:
        raise HTTPException(404, "That card no longer exists.")
    return card


@router.put("/flashcards/{card_id}")
def edit_card(card_id: int, body: CardBody) -> dict:
    if not body.front.strip() or not body.back.strip():
        raise HTTPException(400, "A card needs a front and a back.")
    db.execute(
        "UPDATE flashcards SET front = ?, back = ? WHERE id = ?", (body.front.strip(), body.back.strip(), card_id)
    )
    return {"ok": True}


@router.delete("/flashcards/{card_id}")
def delete_card(card_id: int) -> dict:
    db.execute("DELETE FROM flashcards WHERE id = ?", (card_id,))
    return {"ok": True}
