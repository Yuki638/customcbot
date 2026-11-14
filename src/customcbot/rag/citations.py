"""Checks the source numbers a model put in its answer, and fixes wrong ones.

Small models often state the right fact but attach the wrong number. Each
cited sentence is compared with every passage that was given to the model,
by shared words and by meaning; when another passage is clearly the better
match, the number is corrected.
"""

from __future__ import annotations

import re

import numpy as np

from .embeddings import Embedder

MARKER = re.compile(r"[ \t]*\[(?:source\s*)?(\d+(?:\s*,\s*\d+)*)\]", re.I)
_WORD = re.compile(r"\w{4,}")
_BOUNDARY = re.compile(r"(?<=[.!?。！？])\s+|\n+")

# How much better another passage must score before a number is changed.
SWAP_MARGIN = 0.15
# Below this, a claim matches nothing well enough to be given a number.
MIN_SUPPORT = 0.35


def _claim_before(text: str, start: int, end: int) -> str:
    """The sentence that a citation marker at `end` refers to."""
    segment = text[start:end].strip()
    parts = [p for p in _BOUNDARY.split(segment) if p.strip()]
    return (parts[-1] if parts else segment).strip(" *-•\t")[-400:]


def _overlap(claim: str, passage: str) -> float:
    words = set(_WORD.findall(claim.lower()))
    if not words:
        return 0.0
    passage_words = set(_WORD.findall(passage.lower()))
    return len(words & passage_words) / len(words)


def repair(text: str, passages: list[dict], embedder: Embedder) -> str:
    """Return `text` with citation numbers corrected against `passages` (1-based order)."""
    matches = list(MARKER.finditer(text))
    if not matches or not passages:
        return text

    claims = []
    previous_end = 0
    for match in matches:
        claims.append(_claim_before(text, previous_end, match.start()))
        previous_end = match.end()

    vectors = embedder.embed(claims + [p["text"] for p in passages])
    similarity = vectors[: len(claims)] @ vectors[len(claims) :].T

    pieces: list[str] = []
    cursor = 0
    for index, match in enumerate(matches):
        pieces.append(text[cursor : match.start()])
        cursor = match.end()
        numbers = [int(n) for n in re.findall(r"\d+", match.group(1))]
        claim = claims[index]
        if len(claim) < 12:
            # Nothing to judge by (a bare marker); keep it only if the number exists.
            valid = [n for n in numbers if 1 <= n <= len(passages)]
            pieces.append("".join(f" [{n}]" for n in valid))
            continue
        scores = np.array(
            [
                0.5 * max(float(similarity[index, i]), 0.0) + 0.5 * _overlap(claim, passage["text"])
                for i, passage in enumerate(passages)
            ]
        )
        best = int(np.argmax(scores))
        valid = [n for n in numbers if 1 <= n <= len(passages)]
        cited_score = max((scores[n - 1] for n in valid), default=-1.0)
        if scores[best] - cited_score > SWAP_MARGIN:
            valid = [best + 1] if scores[best] >= MIN_SUPPORT else []
        pieces.append("".join(f" [{n}]" for n in valid))
    pieces.append(text[cursor:])
    return "".join(pieces)
