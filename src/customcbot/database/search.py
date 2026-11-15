"""Finds the passages most relevant to a question.

Two searches run side by side: one by meaning (vectors) and one by exact
words (SQLite full-text search). Their rankings are merged, which is much
more reliable than either alone, especially with small embedding models.
"""

from __future__ import annotations

import re
import threading

import numpy as np

from ..ai.embeddings import Embedder
from .repository import repo_one, repo_query

STOPWORDS = frozenset(
    "a an and are as at be but by can do does for from how i in is it its me my of on or so "
    "that the their them then there these this to was what when where which who why will with "
    "you your about explain tell describe define give".split()
)
_RRF_K = 60
# A passage whose similarity is under this share of the best match's is left out,
# unless it is one of the top exact-word matches. Irrelevant passages slow a small
# model down and confuse it.
_RELATIVE_CUTOFF = 0.65
_KEYWORD_KEEP = 3

_cache: dict[int, tuple[np.ndarray, np.ndarray, np.ndarray]] = {}
_cache_lock = threading.Lock()


def invalidate(collection_id: int) -> None:
    with _cache_lock:
        _cache.pop(collection_id, None)


def _index(collection_id: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(chunk ids, source ids, embedding matrix) for a collection, cached in memory."""
    with _cache_lock:
        if collection_id in _cache:
            return _cache[collection_id]
    rows = repo_query(
        "SELECT id, source_id, embedding FROM chunks WHERE collection_id = ? AND embedding IS NOT NULL",
        (collection_id,),
    )
    ids = np.array([r["id"] for r in rows], dtype=np.int64)
    source_ids = np.array([r["source_id"] for r in rows], dtype=np.int64)
    if rows:
        matrix = np.vstack([np.frombuffer(r["embedding"], dtype=np.float32) for r in rows])
    else:
        matrix = np.zeros((0, 1), dtype=np.float32)
    with _cache_lock:
        _cache[collection_id] = (ids, source_ids, matrix)
    return ids, source_ids, matrix


def _vector_ranking(collection_id, query, embedder, source_ids, limit) -> list[tuple[int, float]]:
    ids, chunk_sources, matrix = _index(collection_id)
    if len(ids) == 0:
        return []
    scores = matrix @ embedder.embed([query])[0]
    if source_ids:
        scores = np.where(np.isin(chunk_sources, list(source_ids)), scores, -np.inf)
    order = np.argsort(-scores)[:limit]
    return [(int(ids[i]), float(scores[i])) for i in order if np.isfinite(scores[i])]


def best_match(collection_id: int, query: str, embedder: Embedder, source_ids=None) -> float:
    """How closely the nearest passage matches a query by meaning (0 when there is none)."""
    ranking = _vector_ranking(collection_id, query, embedder, source_ids, 1)
    return ranking[0][1] if ranking else 0.0


def _keyword_ranking(collection_id, query, source_ids, limit) -> list[int]:
    words = [w for w in re.findall(r"\w+", query.lower()) if len(w) > 1 and w not in STOPWORDS]
    if not words:
        return []
    match = " OR ".join(f'"{w}"' for w in dict.fromkeys(words[:24]))
    sql = (
        "SELECT c.id FROM chunks_fts JOIN chunks c ON c.id = chunks_fts.rowid "
        "WHERE chunks_fts MATCH ? AND c.collection_id = ?"
    )
    params: list = [match, collection_id]
    if source_ids:
        sql += f" AND c.source_id IN ({','.join('?' * len(source_ids))})"
        params += list(source_ids)
    sql += " ORDER BY bm25(chunks_fts) LIMIT ?"
    params.append(limit)
    return [r["id"] for r in repo_query(sql, params)]


def search(
    collection_id: int,
    queries: str | list[str],
    embedder: Embedder,
    *,
    source_ids: list[int] | None = None,
    budget_chars: int = 5000,
    max_chunks: int = 8,
) -> list[dict]:
    """Return the best passages, most relevant first, within a size budget.

    Several phrasings of the same question can be given (the user's words and a
    rewritten follow-up); a passage only needs to match one of them well.
    """
    if isinstance(queries, str):
        queries = [queries]
    fused: dict[int, float] = {}
    relevant: set[int] = set()
    for query in dict.fromkeys(q.strip() for q in queries if q.strip()):
        by_meaning = _vector_ranking(collection_id, query, embedder, source_ids, 30)
        by_words = _keyword_ranking(collection_id, query, source_ids, 30)
        for ranking in ([chunk_id for chunk_id, _ in by_meaning], by_words):
            for rank, chunk_id in enumerate(ranking):
                fused[chunk_id] = fused.get(chunk_id, 0.0) + 1.0 / (_RRF_K + rank + 1)
        best = by_meaning[0][1] if by_meaning else 0.0
        relevant.update(c for c, score in by_meaning if score >= best * _RELATIVE_CUTOFF)
        relevant.update(by_words[:_KEYWORD_KEEP])
    ordered = [c for c in sorted(fused, key=fused.get, reverse=True) if c in relevant][: max_chunks * 2]
    if not ordered:
        return []

    rows = {r["id"]: r for r in _load(ordered)}
    picked: list[dict] = []
    seen: set[int] = set()
    used = 0

    def add(row: dict | None) -> bool:
        nonlocal used
        if row is None or row["id"] in seen:
            return False
        if picked and used + len(row["text"]) > budget_chars:
            return False
        seen.add(row["id"])
        picked.append(row)
        used += len(row["text"])
        return True

    for position, chunk_id in enumerate(ordered):
        if len(picked) >= max_chunks:
            break
        row = rows.get(chunk_id)
        if add(row) and position < 2:
            # The answer often continues in the passage right after the best hits.
            add(_neighbour(row))
    return picked


_SELECT = (
    "SELECT c.id, c.source_id, c.ord, c.page, c.start_sec, c.text, "
    "s.title, s.kind, s.origin FROM chunks c JOIN sources s ON s.id = c.source_id "
)


def _load(chunk_ids: list[int]) -> list[dict]:
    marks = ",".join("?" * len(chunk_ids))
    return repo_query(_SELECT + f"WHERE c.id IN ({marks})", chunk_ids)


def _neighbour(row: dict) -> dict | None:
    return repo_one(_SELECT + "WHERE c.source_id = ? AND c.ord = ?", (row["source_id"], row["ord"] + 1))
