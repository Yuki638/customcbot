"""Answers a question from the user's material and streams the reply."""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from typing import TYPE_CHECKING

from pydantic import BaseModel

from .. import config
from ..ai.base import LLMError
from ..database import search as retrieve
from ..database.repository import (
    repo_execute,
    repo_one,
    repo_query,
)
from ..ingest import youtube
from ..utils import citations as citation_check
from ..utils import context
from ..utils.prompter import load_json, render

if TYPE_CHECKING:
    from ..services import Services

HISTORY_MESSAGES = 4  # used to understand a follow-up question
PROMPT_HISTORY = 2  # the last exchange is repeated to the model when it answers
HISTORY_CHARS = 600
REWRITE_HISTORY_CHARS = 300
REWRITE_EXTRA_CHARS = 100
# See _resolve_follow_up.
SELF_CONTAINED = 0.45
REWRITE_MARGIN = 0.15
_CITE = re.compile(r"\[(?:source\s*)?(\d+(?:\s*,\s*\d+)*)\]", re.I)
NOTHING_YET = (
    "There is nothing to search yet. Add a PDF, a video link or some notes on the left, "
    'wait until it says "Ready", then ask again.'
)


def citation_for(number: int, passage: dict) -> dict:
    url = None
    if passage["kind"] == "youtube":
        vid = youtube.video_id(passage["origin"] or "")
        url = youtube.watch_url(vid, passage["start_sec"]) if vid else passage["origin"]
    return {
        "n": number,
        "chunk_id": passage["id"],
        "source_id": passage["source_id"],
        "title": passage["title"],
        "kind": passage["kind"],
        "page": passage["page"],
        "start_sec": passage["start_sec"],
        "label": context.location_label(passage),
        "url": url,
        "text": passage["text"],
    }


class Rewrite(BaseModel):
    # The topic comes first so the model works out what "it" refers to before rewriting.
    topic: str
    needs_topic: bool
    question: str


def standalone_question(question: str, history: list[dict], services: Services) -> str:
    """Rewrite a follow-up ("and why is that?") so it can be understood on its own."""
    if not history:
        return question
    transcript = "\n".join(
        f"{'User' if m['role'] == 'user' else 'Tutor'}: "
        f"{' '.join(_CITE.sub('', m['content']).split())[:REWRITE_HISTORY_CHARS]}"
        for m in history
    )
    messages = [{"role": "system", "content": render("chat/condense_system")}]
    for example in load_json("chat/condense_examples"):
        conversation, reply = example["conversation"], example["reply"]
        messages.append({"role": "user", "content": conversation})
        messages.append({"role": "assistant", "content": json.dumps(reply)})
    messages.append({"role": "user", "content": f"{transcript}\nLast message: {question}"})
    try:
        result = services.model("chat").chat_json(messages, Rewrite, temperature=0.0, max_tokens=120)
    except LLMError:
        return question
    rewritten = " ".join(result.question.split())
    # A rewrite much longer than the question has had the conversation stuffed into it.
    if not result.needs_topic or not rewritten or len(rewritten) > len(question) + REWRITE_EXTRA_CHARS:
        return question
    return rewritten if _keeps_the_words(question, rewritten) else question


def _keeps_the_words(question: str, rewritten: str) -> bool:
    """A rewrite should add what is missing, not replace what the user asked.

    Very small models sometimes return the previous question instead. At least
    half of the question's own content words must survive.
    """
    words = {w for w in re.findall(r"\w{4,}", question.lower()) if w not in retrieve.STOPWORDS}
    kept = sum(1 for w in words if w in rewritten.lower())
    return kept * 2 >= len(words)


def _resolve_follow_up(collection_id, question, history, services, source_ids) -> tuple[str, bool]:
    """Return (the question in full, whether to ask the model that form).

    A question that already matches the material well stands on its own and is left
    alone, which also saves a model call. Otherwise it is rewritten using the
    conversation. The rewrite is always searched alongside the user's own words; the
    model is asked it, in place of the user's words, only if it matches the material
    clearly better, because a small model can garble a rewrite. (Showing the model
    both forms makes small models repeat their previous answer.)
    """
    if not history:
        return question, False
    own = retrieve.best_match(collection_id, question, services.embedder, source_ids)
    if own >= SELF_CONTAINED:
        return question, False
    rewritten = standalone_question(question, history, services)
    if rewritten == question:
        return question, False
    full = retrieve.best_match(collection_id, rewritten, services.embedder, source_ids)
    return rewritten, full >= own + REWRITE_MARGIN


def answer(
    chat_id: int,
    question: str,
    services: Services,
    *,
    source_ids: list[int] | None = None,
    general: bool = False,
) -> Iterator[tuple[str, dict]]:
    """Yield (event, data) pairs: 'sources' once, 'token' many times, then 'done' or 'error'."""
    chat = repo_one("SELECT * FROM chats WHERE id = ?", (chat_id,))
    if chat is None:
        yield "error", {"message": "This chat no longer exists."}
        return
    collection_id = chat["collection_id"]
    history = repo_query(
        "SELECT role, content FROM messages WHERE chat_id = ? ORDER BY id DESC LIMIT ?",
        (chat_id, HISTORY_MESSAGES),
    )[::-1]

    repo_execute("INSERT INTO messages (chat_id, role, content) VALUES (?, 'user', ?)", (chat_id, question))
    if not history:
        title = question.strip().splitlines()[0][:60]
        repo_execute("UPDATE chats SET title = ? WHERE id = ?", (title, chat_id))

    has_material = repo_one(
        "SELECT 1 AS x FROM chunks WHERE collection_id = ? LIMIT 1", (collection_id,)
    )
    if not has_material and not general:
        yield "sources", {"citations": []}
        yield "token", {"text": NOTHING_YET}
        _save(chat_id, NOTHING_YET, [])
        yield "done", {"content": NOTHING_YET, "citations": []}
        return

    passages: list[dict] = []
    meant = question
    if has_material:
        # A follow-up like "and the next stage?" is rewritten to stand on its own for
        # searching. The user's own words are searched too, so that a poor rewrite by
        # a small model cannot push the right passages out.
        rewritten, show = _resolve_follow_up(collection_id, question, history, services, source_ids)
        if show:
            meant = rewritten
        budget_chars, max_chunks = config.passage_budget()
        passages = retrieve.search(
            collection_id,
            [question, rewritten],
            services.embedder,
            source_ids=source_ids,
            budget_chars=budget_chars,
            max_chunks=max_chunks,
        )
    citations = [citation_for(n, p) for n, p in enumerate(passages, start=1)]
    yield "sources", {"citations": citations}

    if passages:
        system = render("chat/general_system") if general else render("chat/grounded_system")
        user = f"Sources:\n\n{context.format_sources(passages)}\n\nQuestion: {meant}"
        if not general:
            reminder = render("chat/grounded_reminder_online") if config.online() else render("chat/grounded_reminder")
            user += f"\n\n{reminder}"
    elif general:
        system, user = render("chat/no_sources_system"), question
    else:
        system = render("chat/grounded_system")
        user = f"Sources:\n\n(no matching passages were found)\n\nQuestion: {question}"

    messages = [{"role": "system", "content": system}]
    if meant == question:
        # A rewritten question already carries what it needs from the conversation.
        # Repeating the earlier turns as well makes small models copy their last answer.
        messages += [
            {"role": m["role"], "content": m["content"][:HISTORY_CHARS]}
            for m in history[-PROMPT_HISTORY:]
        ]
    messages.append({"role": "user", "content": user})

    parts: list[str] = []
    try:
        for piece in services.model("chat").stream(messages, temperature=0.3, max_tokens=900):
            piece = citation_check.plain_brackets(piece)
            parts.append(piece)
            yield "token", {"text": piece}
    except LLMError as exc:
        if parts:
            _save(chat_id, "".join(parts), citations)
        yield "error", {"message": str(exc)}
        return
    text = citation_check.normalise("".join(parts).strip())
    if passages:
        try:
            text = citation_check.repair(text, passages, services.embedder)
        except Exception:  # checking citations must never lose the answer
            pass
    yield "done", {"content": text, "citations": _save(chat_id, text, citations)}


def _save(chat_id: int, text: str, citations: list[dict]) -> list[dict]:
    """Store the reply with the passages it cited and return those passages.

    Small models sometimes forget to cite. The top passages are then kept and
    marked as uncited, so the user can still see what the answer drew on.
    """
    used = {int(n) for group in _CITE.findall(text) for n in re.findall(r"\d+", group)}
    kept = [c for c in citations if c["n"] in used]
    if not kept:
        kept = [{**c, "uncited": True} for c in citations[:3]]
    repo_execute(
        "INSERT INTO messages (chat_id, role, content, citations) VALUES (?, 'assistant', ?, ?)",
        (chat_id, text.strip(), json.dumps(kept)),
    )
    return kept
