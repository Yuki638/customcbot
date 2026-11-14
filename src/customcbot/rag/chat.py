"""Answers a question from the user's material and streams the reply."""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from typing import TYPE_CHECKING

from .. import config, db
from ..ingest import youtube
from ..llm.base import LLMError
from . import citations as citation_check
from . import prompts, retrieve

if TYPE_CHECKING:
    from ..services import Services

HISTORY_MESSAGES = 4  # used to understand a follow-up question
PROMPT_HISTORY = 2  # the last exchange is repeated to the model when it answers
HISTORY_CHARS = 600
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
        "label": prompts.location_label(passage),
        "url": url,
        "text": passage["text"],
    }


def standalone_question(question: str, history: list[dict], services: Services) -> str:
    """Rewrite a follow-up ("and why is that?") so it can be searched on its own."""
    if not history:
        return question
    transcript = "\n".join(
        f"{'User' if m['role'] == 'user' else 'Tutor'}: {m['content'][:HISTORY_CHARS]}" for m in history
    )
    try:
        rewritten = services.llm.chat(
            [
                {"role": "system", "content": prompts.CONDENSE_SYSTEM},
                {"role": "user", "content": f"{transcript}\nUser: {question}\n\nRewritten question:"},
            ],
            temperature=0.0,
            max_tokens=80,
        )
    except LLMError:
        return question
    rewritten = rewritten.strip().strip('"').splitlines()[0] if rewritten.strip() else ""
    if not rewritten or len(rewritten) > 400:
        return question
    return rewritten


def answer(
    chat_id: int,
    question: str,
    services: Services,
    *,
    source_ids: list[int] | None = None,
    general: bool = False,
) -> Iterator[tuple[str, dict]]:
    """Yield (event, data) pairs: 'sources' once, 'token' many times, then 'done' or 'error'."""
    chat = db.one("SELECT * FROM chats WHERE id = ?", (chat_id,))
    if chat is None:
        yield "error", {"message": "This chat no longer exists."}
        return
    collection_id = chat["collection_id"]
    history = db.query(
        "SELECT role, content FROM messages WHERE chat_id = ? ORDER BY id DESC LIMIT ?",
        (chat_id, HISTORY_MESSAGES),
    )[::-1]

    db.execute("INSERT INTO messages (chat_id, role, content) VALUES (?, 'user', ?)", (chat_id, question))
    if not history:
        title = question.strip().splitlines()[0][:60]
        db.execute("UPDATE chats SET title = ? WHERE id = ?", (title, chat_id))

    has_material = db.one(
        "SELECT 1 AS x FROM chunks WHERE collection_id = ? LIMIT 1", (collection_id,)
    )
    if not has_material and not general:
        yield "sources", {"citations": []}
        yield "token", {"text": NOTHING_YET}
        _save(chat_id, NOTHING_YET, [])
        yield "done", {"content": NOTHING_YET, "citations": []}
        return

    passages: list[dict] = []
    if has_material:
        # A follow-up like "and the next stage?" is rewritten to stand on its own for
        # searching. The user's own words are searched too, so that a poor rewrite by
        # a small model cannot push the right passages out.
        passages = retrieve.search(
            collection_id,
            [question, standalone_question(question, history, services)],
            services.embedder,
            source_ids=source_ids,
            budget_chars=int(config.get("context_chars") or 5000),
            max_chunks=int(config.get("max_passages") or 6),
        )
    citations = [citation_for(n, p) for n, p in enumerate(passages, start=1)]
    yield "sources", {"citations": citations}

    if passages:
        system = prompts.GENERAL_SYSTEM if general else prompts.GROUNDED_SYSTEM
        user = f"Sources:\n\n{prompts.format_sources(passages)}\n\nQuestion: {question}"
    elif general:
        system, user = prompts.NO_SOURCES_SYSTEM, question
    else:
        system = prompts.GROUNDED_SYSTEM
        user = f"Sources:\n\n(no matching passages were found)\n\nQuestion: {question}"

    messages = [{"role": "system", "content": system}]
    messages += [
        {"role": m["role"], "content": m["content"][:HISTORY_CHARS]} for m in history[-PROMPT_HISTORY:]
    ]
    messages.append({"role": "user", "content": user})

    parts: list[str] = []
    try:
        for piece in services.llm.stream(messages, temperature=0.3, max_tokens=900):
            parts.append(piece)
            yield "token", {"text": piece}
    except LLMError as exc:
        if parts:
            _save(chat_id, "".join(parts), citations)
        yield "error", {"message": str(exc)}
        return
    text = "".join(parts).strip()
    if passages:
        try:
            text = citation_check.repair(text, passages, services.embedder)
        except Exception:  # checking citations must never lose the answer
            pass
    yield "done", {"content": text, "citations": _save(chat_id, text, citations)}


_CITE = re.compile(r"\[(?:source\s*)?(\d+(?:\s*,\s*\d+)*)\]", re.I)


def _save(chat_id: int, text: str, citations: list[dict]) -> list[dict]:
    """Store the reply with the passages it cited and return those passages.

    Small models sometimes forget to cite. The top passages are then kept and
    marked as uncited, so the user can still see what the answer drew on.
    """
    used = {int(n) for group in _CITE.findall(text) for n in re.findall(r"\d+", group)}
    kept = [c for c in citations if c["n"] in used]
    if not kept:
        kept = [{**c, "uncited": True} for c in citations[:3]]
    db.execute(
        "INSERT INTO messages (chat_id, role, content, citations) VALUES (?, 'assistant', ?, ?)",
        (chat_id, text.strip(), json.dumps(kept)),
    )
    return kept
