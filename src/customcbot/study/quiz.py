"""Quiz generation and grading."""

from __future__ import annotations

import json
import random
from typing import TYPE_CHECKING

from pydantic import BaseModel

from .. import db
from ..llm.base import LLMError
from ..rag import prompts
from ..worker import JobContext

if TYPE_CHECKING:
    from ..services import Services

MIN_PASSAGE_CHARS = 250


class MultipleChoice(BaseModel):
    question: str
    options: list[str]
    correct_index: int
    explanation: str


class ShortAnswer(BaseModel):
    question: str
    answer: str


class Grade(BaseModel):
    correct: bool
    feedback: str


def sample_passages(collection_id: int, source_ids: list[int] | None, count: int) -> list[dict]:
    """Pick passages spread evenly through the material, so a quiz covers all of it."""
    sql = (
        "SELECT c.id, c.source_id, c.page, c.start_sec, c.text, s.title, s.kind, s.origin "
        "FROM chunks c JOIN sources s ON s.id = c.source_id "
        "WHERE c.collection_id = ? AND length(c.text) >= ?"
    )
    params: list = [collection_id, MIN_PASSAGE_CHARS]
    if source_ids:
        sql += f" AND c.source_id IN ({','.join('?' * len(source_ids))})"
        params += source_ids
    rows = db.query(sql + " ORDER BY c.source_id, c.ord", params)
    if not rows:
        # Very short material: fall back to whatever there is.
        params[1] = 1
        rows = db.query(sql + " ORDER BY c.source_id, c.ord", params)
    if len(rows) <= count:
        return rows
    step = len(rows) / count
    return [rows[min(int(i * step + random.random() * step), len(rows) - 1)] for i in range(count)]


def _multiple_choice(passage: dict, services: Services) -> dict | None:
    result = services.llm.chat_json(
        [
            {"role": "system", "content": prompts.QUIZ_MCQ_SYSTEM},
            {"role": "user", "content": f"Passage:\n\n{passage['text']}"},
        ],
        MultipleChoice,
        temperature=0.5,
        max_tokens=400,
        background=True,
    )
    options = [o.strip() for o in result.options if o.strip()]
    if len(options) < 2 or not 0 <= result.correct_index < len(options):
        return None
    if len({o.lower() for o in options}) != len(options) or not result.question.strip():
        return None
    # Models tend to put the right answer first; shuffle so position gives nothing away.
    correct = options[result.correct_index]
    random.shuffle(options)
    return {
        "type": "mcq",
        "question": result.question.strip(),
        "options": options,
        "answer_index": options.index(correct),
        "explanation": result.explanation.strip(),
    }


def _short_answer(passage: dict, services: Services) -> dict | None:
    result = services.llm.chat_json(
        [
            {"role": "system", "content": prompts.QUIZ_SHORT_SYSTEM},
            {"role": "user", "content": f"Passage:\n\n{passage['text']}"},
        ],
        ShortAnswer,
        temperature=0.5,
        max_tokens=300,
        background=True,
    )
    if not result.question.strip() or not result.answer.strip():
        return None
    return {"type": "short", "question": result.question.strip(), "answer": result.answer.strip()}


def job_generate(job: dict, params: dict, services: Services, context: JobContext) -> dict:
    collection_id = job["collection_id"]
    count = max(1, min(int(params.get("count", 5)), 20))
    style = params.get("style", "mcq")  # mcq | short | mixed
    passages = sample_passages(collection_id, params.get("source_ids") or None, count)
    if not passages:
        raise ValueError("Add some material first.")

    questions: list[dict] = []
    for index, passage in enumerate(passages):
        context.progress(f"Writing question {index + 1} of {len(passages)}", index / len(passages))
        short = style == "short" or (style == "mixed" and index % 3 == 2)
        try:
            question = (_short_answer if short else _multiple_choice)(passage, services)
        except LLMError:
            question = None  # one bad question should not sink the quiz
        if question is None:
            continue
        question.update(
            id=len(questions) + 1,
            chunk_id=passage["id"],
            source_id=passage["source_id"],
            where=prompts.location_label(passage),
        )
        questions.append(question)
    if not questions:
        raise ValueError("The model could not write questions from this material. Try again or use a larger model.")

    title = params.get("title") or f"Quiz, {len(questions)} questions"
    quiz_id = db.execute(
        "INSERT INTO quizzes (collection_id, title, questions) VALUES (?, ?, ?)",
        (collection_id, title, json.dumps(questions)),
    )
    return {"quiz_id": quiz_id}


def grade(quiz_id: int, question_id: int, answer: str, services: Services) -> dict:
    quiz = db.one("SELECT * FROM quizzes WHERE id = ?", (quiz_id,))
    if quiz is None:
        raise ValueError("That quiz no longer exists.")
    question = next((q for q in json.loads(quiz["questions"]) if q["id"] == question_id), None)
    if question is None or question["type"] != "short":
        raise ValueError("That question cannot be graded this way.")
    passage = db.one("SELECT text FROM chunks WHERE id = ?", (question["chunk_id"],))
    user = (
        f"Question: {question['question']}\n"
        f"Reference answer: {question['answer']}\n"
        f"Passage: {passage['text'] if passage else '(not available)'}\n\n"
        f"Student's answer: {answer}"
    )
    result = services.llm.chat_json(
        [{"role": "system", "content": prompts.GRADE_SYSTEM}, {"role": "user", "content": user}],
        Grade,
        temperature=0.0,
        max_tokens=200,
    )
    return {"correct": result.correct, "feedback": result.feedback.strip(), "answer": question["answer"]}
