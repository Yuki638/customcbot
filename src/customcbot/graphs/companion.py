"""The study companion: a named character who answers, reacts and remembers.

Only the tone of an answer changes. What is searched, what is cited and how
citations are checked stay exactly as they are without the companion.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from pydantic import BaseModel

from .. import config
from ..ai.base import LLMError
from ..database import search as retrieve
from ..database.repository import repo_one
from ..domain.memory import MAX_CHARS, Memory
from ..utils.prompter import load_json, render

if TYPE_CHECKING:
    from ..services import Services

DEFAULT_NAME = "Mio"
PROMPT_MEMORIES = 12  # the newest facts are enough, and a small model has little room
SMALL_TALK_WORDS = 6
SMALL_TALK_MATCH = 0.3  # below this, a short message has nothing to do with the material
MIN_MESSAGE_CHARS = 12  # shorter than this, a message cannot say anything about the user
FACTS_PER_MESSAGE = 3
# A small model sometimes records what was asked instead of something about the user.
_ABOUT_THE_QUESTION = re.compile(r"\b(ask(s|ed|ing)?|question|wants? to know|inquir|request(s|ed)?)\b", re.I)


def active() -> bool:
    return bool(config.get("companion"))


def name() -> str:
    return (config.get("companion_name") or "").strip() or DEFAULT_NAME


def remembers() -> bool:
    return active() and bool(config.get("memory"))


def _memories() -> list[str]:
    return Memory.lines()[-PROMPT_MEMORIES:] if remembers() else []


def persona() -> str:
    """Text added to a system prompt so the answer comes from the companion. Empty when it is off."""
    if not active() or _smallest_model():
        return ""
    return render("companion/persona", who=name(), memories=_memories())


def _smallest_model() -> bool:
    """The smallest local model writes worse answers when asked for a tone as well (it starts
    saying "[1] tells us"), so there the companion greets and reacts but answers plainly."""
    return not config.online() and config.get("tier") == "lite"


def small_talk_prompt() -> str:
    return render("companion/small_talk_system", who=name(), memories=_memories())


def is_small_talk(question: str, collection_id: int, has_material: bool, services: Services, source_ids) -> bool:
    """Whether a message is a greeting or thanks rather than something to look up.

    Only a few words with no question mark can be, and only if they match nothing
    in the material: "photosynthesis" is short too, and must still be searched.
    """
    if not active() or "?" in question or len(question.split()) > SMALL_TALK_WORDS:
        return False
    if not has_material:
        return True
    # A word that appears in the material makes it a search, however short: "cristae surface area".
    for word in re.findall(r"\w{4,}", question.lower()):
        if word not in retrieve.STOPWORDS and repo_one(
            "SELECT 1 AS x FROM chunks WHERE collection_id = ? AND text LIKE ? LIMIT 1", (collection_id, f"%{word}%")
        ):
            return False
    return retrieve.best_match(collection_id, question, services.embedder, source_ids) < SMALL_TALK_MATCH


# A message says something about its writer only if it mentions them: "I", "my", "mon", "मेरा".
# This covers the languages the interface is offered in. It saves a model call on every plain
# question, and stops a small model from "remembering" the subject instead of the person.
_SELF = re.compile(
    r"(?<!\w)(i|i'm|i’m|im|i've|i’ve|my|me|mine|myself"  # English
    r"|yo|mi|mis|me|soy|estoy|tengo|llamo"  # Spanish
    r"|je|j'ai|j’ai|j'|j’|mon|ma|mes|moi|suis|m'appelle|m’appelle"  # French
    r"|eu|meu|minha|meus|minhas|sou|estou|tenho|chamo"  # Portuguese
    r"|main|mera|meri|mere|mujhe|mai)(?!\w)"  # Hindi in Latin letters
    r"|मैं|मेरा|मेरी|मेरे|मुझे|我",
    re.I,
)


class Facts(BaseModel):
    facts: list[str] = []


def learn(message: str, services: Services) -> list[str]:
    """Pick out lasting facts about the user from one of their messages and store them."""
    if not remembers() or len(message.strip()) < MIN_MESSAGE_CHARS or not _SELF.search(message):
        return []
    known = Memory.lines()
    messages = [{"role": "system", "content": render("companion/memory_system")}]
    for example in load_json("companion/memory_examples"):
        messages.append({"role": "user", "content": _memory_request([], example["message"])})
        messages.append({"role": "assistant", "content": Facts(**example["reply"]).model_dump_json()})
    messages.append({"role": "user", "content": _memory_request(known, message)})
    try:
        result = services.model("chat").chat_json(
            messages, Facts, temperature=0.0, max_tokens=160, background=True
        )
    except LLMError:
        return []
    stored = []
    for fact in result.facts[:FACTS_PER_MESSAGE]:
        fact = " ".join(str(fact).split())[:MAX_CHARS]
        if fact and _comes_from(fact, message) and Memory.remember(fact):
            stored.append(fact)
    return stored


def _memory_request(known: list[str], message: str) -> str:
    listed = "\n".join(f"- {line}" for line in known[-PROMPT_MEMORIES:]) or "(none)"
    return f"Facts already known:\n{listed}\n\nThe student's message:\n{message[:1500]}"


def _comes_from(fact: str, message: str) -> bool:
    """A fact must be about the user and use words they wrote, or it was made up."""
    if not fact.lower().startswith("the student") or _ABOUT_THE_QUESTION.search(fact):
        return False
    said = message.lower()
    words = [w for w in re.findall(r"\w{4,}", fact.lower()) if w not in ("student", "user")]
    return any(w in said for w in words)
