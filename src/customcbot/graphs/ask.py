"""Ask: a more thorough way to answer one question than chat.

1. Plan: the model splits the question into a few searches.
2. For each search, the matching passages are read and notes are written.
3. One answer is written from all the notes.

Passages are numbered once across all searches, so a citation number means the
same passage in the notes and in the final answer. A very small local model
cannot plan reliably, so with the Lite size there is a single search.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from .. import config
from ..ai.base import LLMError
from ..database import search
from ..database.repository import repo_one
from ..utils import citations as citation_check
from ..utils import context
from ..utils.prompter import load_json, render
from .chat import _CITE, NOTHING_YET, citation_for

if TYPE_CHECKING:
    from ..services import Services

MAX_SEARCHES_ONLINE = 3
MAX_SEARCHES_LOCAL = 2
NOTHING_FOUND = "Nothing found."
NOT_IN_MATERIAL = "I could not find anything about that in your material."


class Search(BaseModel):
    term: str
    instructions: str = ""


class Strategy(BaseModel):
    searches: list[Search] = Field(min_length=1)


def max_searches() -> int:
    if config.online():
        return MAX_SEARCHES_ONLINE
    return 1 if config.get("tier") == "lite" else MAX_SEARCHES_LOCAL


def plan(question: str, services: Services) -> list[Search]:
    """The searches to run. Falls back to searching for the question itself."""
    whole = [Search(term=question, instructions="")]
    limit = max_searches()
    if limit == 1:
        return whole
    messages = [{"role": "system", "content": render("ask/strategy_system", max_searches=limit)}]
    for example in load_json("ask/strategy_examples"):
        reply = {"searches": example["reply"]["searches"][:limit]}
        messages.append({"role": "user", "content": example["question"]})
        messages.append({"role": "assistant", "content": json.dumps(reply)})
    messages.append({"role": "user", "content": question})
    try:
        strategy = services.model("chat").chat_json(messages, Strategy, temperature=0.0, max_tokens=300)
    except LLMError:
        return whole
    seen: set[str] = set()
    searches = []
    for item in strategy.searches:
        term = " ".join(item.term.split())[:120]
        if term and term.lower() not in seen:
            seen.add(term.lower())
            searches.append(Search(term=term, instructions=" ".join(item.instructions.split())[:200]))
    return searches[:limit] or whole


def ask(
    collection_id: int, question: str, services: Services, *, source_ids: list[int] | None = None
) -> Iterator[tuple[str, dict]]:
    """Yield (event, data): 'strategy', one 'answer' per search, 'sources', 'token's, then 'done' or 'error'."""
    if not repo_one("SELECT 1 AS x FROM chunks WHERE collection_id = ? LIMIT 1", (collection_id,)):
        yield "strategy", {"searches": []}
        yield "sources", {"citations": []}
        yield "token", {"text": NOTHING_YET}
        yield "done", {"content": NOTHING_YET, "citations": []}
        return

    try:
        searches = plan(question, services)
        yield "strategy", {"searches": [s.model_dump() for s in searches]}

        budget_chars, max_chunks = config.passage_budget()
        pool: list[dict] = []  # every passage read, in the order it was first found
        number_of: dict[int, int] = {}
        notes: list[dict] = []
        for index, item in enumerate(searches):
            found = search.search(
                collection_id,
                [item.term] if len(searches) > 1 else [question],
                services.embedder,
                source_ids=source_ids,
                budget_chars=budget_chars,
                max_chunks=max_chunks,
            )
            for passage in found:
                if passage["id"] not in number_of:
                    pool.append(passage)
                    number_of[passage["id"]] = len(pool)
            numbers = [number_of[p["id"]] for p in found]
            text = ""
            if found:
                task = item.instructions or f"what the sources say about {item.term}"
                text = services.model("chat").chat(
                    [
                        {"role": "system", "content": render("ask/query_system")},
                        {
                            "role": "user",
                            "content": render(
                                "ask/query_user",
                                sources=context.format_sources(found, numbers),
                                question=question,
                                task=task,
                            ),
                        },
                    ],
                    temperature=0.2,
                    max_tokens=500,
                )
                text = citation_check.normalise(text)
                if text.strip().rstrip(".").lower() == NOTHING_FOUND.rstrip(".").lower():
                    text = ""
            if text:
                notes.append({"term": item.term, "text": text})
            yield "answer", {
                "index": index,
                "term": item.term,
                "text": text,
                "citations": [citation_for(n, p) for n, p in zip(numbers, found, strict=True)],
            }

        citations = [citation_for(number, passage) for number, passage in enumerate(pool, start=1)]
        yield "sources", {"citations": citations}
        if not notes:
            yield "token", {"text": NOT_IN_MATERIAL}
            yield "done", {"content": NOT_IN_MATERIAL, "citations": []}
            return

        if len(notes) == 1:
            # One set of notes is already the answer; a second pass would only reword it.
            final = notes[0]["text"]
            yield "token", {"text": final}
        else:
            parts: list[str] = []
            messages = [
                {"role": "system", "content": render("ask/final_system")},
                {"role": "user", "content": render("ask/final_user", question=question, answers=notes)},
            ]
            for piece in services.model("chat").stream(messages, temperature=0.3, max_tokens=900):
                piece = citation_check.plain_brackets(piece)
                parts.append(piece)
                yield "token", {"text": piece}
            final = citation_check.normalise("".join(parts).strip())
        try:
            final = citation_check.repair(final, pool, services.embedder)
        except Exception:  # checking citations must never lose the answer
            pass
        used = {int(n) for group in _CITE.findall(final) for n in group.replace(" ", "").split(",")}
        yield "done", {"content": final, "citations": [c for c in citations if c["n"] in used]}
    except LLMError as exc:
        yield "error", {"message": str(exc)}
