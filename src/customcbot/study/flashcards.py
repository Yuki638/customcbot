"""Flashcards with simple spaced repetition (the Leitner system).

A card you know moves up a box and comes back after a longer gap; a card you
miss goes back to box 1.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

from pydantic import BaseModel

from .. import db
from ..llm.base import LLMError
from ..rag import prompts
from ..worker import JobContext
from .quiz import sample_passages

if TYPE_CHECKING:
    from ..services import Services

# Days until a card in each box is shown again.
INTERVAL_DAYS = {1: 0, 2: 1, 3: 3, 4: 7, 5: 14}
MAX_BOX = 5


class Card(BaseModel):
    front: str
    back: str


class Cards(BaseModel):
    cards: list[Card]


def _timestamp(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def job_generate(job: dict, params: dict, services: Services, context: JobContext) -> dict:
    collection_id = job["collection_id"]
    count = max(1, min(int(params.get("count", 10)), 40))
    # A passage yields one or two cards, so sample enough passages for the worst case.
    passages = sample_passages(collection_id, params.get("source_ids") or None, count)
    if not passages:
        raise ValueError("Add some material first.")

    created = 0
    problem = ""  # why the model failed, if it did
    for index, passage in enumerate(passages):
        if created >= count:
            break
        context.progress(f"Writing cards ({created} of {count})", index / len(passages))
        try:
            result = services.llm.chat_json(
                [
                    {"role": "system", "content": prompts.FLASHCARD_SYSTEM},
                    {"role": "user", "content": f"Passage:\n\n{passage['text']}"},
                ],
                Cards,
                temperature=0.2,
                max_tokens=400,
                background=True,
            )
        except LLMError as exc:
            problem = str(exc)
            continue
        for card in result.cards[:2]:
            if created >= count or not card.front.strip() or not card.back.strip():
                continue
            db.execute(
                "INSERT INTO flashcards (collection_id, source_id, front, back) VALUES (?, ?, ?, ?)",
                (collection_id, passage["source_id"], card.front.strip(), card.back.strip()),
            )
            created += 1
    if not created:
        raise ValueError(problem or "The model could not write cards from this material. Try again or use a larger model.")
    return {"created": created}


def review(card_id: int, known: bool) -> dict | None:
    card = db.one("SELECT * FROM flashcards WHERE id = ?", (card_id,))
    if card is None:
        return None
    box = min(card["box"] + 1, MAX_BOX) if known else 1
    due = datetime.now(timezone.utc) + timedelta(days=INTERVAL_DAYS[box])
    db.execute("UPDATE flashcards SET box = ?, due_at = ? WHERE id = ?", (box, _timestamp(due), card_id))
    return db.one("SELECT * FROM flashcards WHERE id = ?", (card_id,))


def list_cards(collection_id: int, due_only: bool = False) -> list[dict]:
    sql = "SELECT * FROM flashcards WHERE collection_id = ?"
    params: list = [collection_id]
    if due_only:
        sql += " AND due_at <= ?"
        params.append(_timestamp(datetime.now(timezone.utc)))
    return db.query(sql + " ORDER BY box, due_at, id", params)
