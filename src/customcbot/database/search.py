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

# What a passage belongs to. Chat searches sources and the user's notes; insights are
# left out there, because they restate the sources and would be cited in their place.
SOURCE, NOTE, INSIGHT = "source", "note", "insight"
_KIND_CODES = {SOURCE: 0, NOTE: 1, INSIGHT: 2}
DEFAULT_KINDS = (SOURCE, NOTE)

_cache: dict[int, tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]] = {}
_cache_lock = threading.Lock()


def invalidate(collection_id: int) -> None:
    with _cache_lock:
        _cache.pop(collection_id, None)


def _index(collection_id: int) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """(chunk ids, source ids, kind codes, embedding matrix) for a collection, cached in memory.

    The source id of an insight's passage is the source the insight was made from;
    a note's passage has none (-1).
    """
    with _cache_lock:
        if collection_id in _cache:
            return _cache[collection_id]
    rows = repo_query(
        "SELECT c.id, COALESCE(c.source_id, i.source_id, -1) AS owner, "
        "CASE WHEN c.note_id IS NOT NULL THEN 1 WHEN c.insight_id IS NOT NULL THEN 2 ELSE 0 END AS kind, "
        "c.embedding FROM chunks c LEFT JOIN source_insights i ON i.id = c.insight_id "
        "WHERE c.collection_id = ? AND c.embedding IS NOT NULL",
        (collection_id,),
    )
    ids = np.array([r["id"] for r in rows], dtype=np.int64)
    source_ids = np.array([r["owner"] for r in rows], dtype=np.int64)
    kinds = np.array([r["kind"] for r in rows], dtype=np.int64)
    if rows:
        matrix = np.vstack([np.frombuffer(r["embedding"], dtype=np.float32) for r in rows])
    else:
        matrix = np.zeros((0, 1), dtype=np.float32)
    with _cache_lock:
        _cache[collection_id] = (ids, source_ids, kinds, matrix)
    return ids, source_ids, kinds, matrix


def _vector_ranking(collection_id, query, embedder, source_ids, limit, kinds=DEFAULT_KINDS) -> list[tuple[int, float]]:
    ids, chunk_sources, chunk_kinds, matrix = _index(collection_id)
    if len(ids) == 0:
        return []
    scores = matrix @ embedder.embed([query])[0]
    allowed = np.isin(chunk_kinds, [_KIND_CODES[k] for k in kinds])
    if source_ids:
        allowed &= np.isin(chunk_sources, list(source_ids))
    scores = np.where(allowed, scores, -np.inf)
    order = np.argsort(-scores)[:limit]
    return [(int(ids[i]), float(scores[i])) for i in order if np.isfinite(scores[i])]


def best_match(collection_id: int, query: str, embedder: Embedder, source_ids=None, kinds=DEFAULT_KINDS) -> float:
    """How closely the nearest passage matches a query by meaning (0 when there is none)."""
    ranking = _vector_ranking(collection_id, query, embedder, source_ids, 1, kinds)
    return ranking[0][1] if ranking else 0.0


_KIND_SQL = {
    SOURCE: "(c.note_id IS NULL AND c.insight_id IS NULL)",
    NOTE: "c.note_id IS NOT NULL",
    INSIGHT: "c.insight_id IS NOT NULL",
}
_OWNER_SQL = "COALESCE(c.source_id, (SELECT source_id FROM source_insights WHERE id = c.insight_id))"


def _keyword_ranking(collection_id, query, source_ids, limit, kinds=DEFAULT_KINDS) -> list[int]:
    words = [w for w in re.findall(r"\w+", query.lower()) if len(w) > 1 and w not in STOPWORDS]
    if not words:
        return []
    match = " OR ".join(f'"{w}"' for w in dict.fromkeys(words[:24]))
    sql = (
        "SELECT c.id FROM chunks_fts JOIN chunks c ON c.id = chunks_fts.rowid "
        "WHERE chunks_fts MATCH ? AND c.collection_id = ?"
    )
    params: list = [match, collection_id]
    sql += f" AND ({' OR '.join(_KIND_SQL[k] for k in kinds)})"
    if source_ids:
        sql += f" AND {_OWNER_SQL} IN ({','.join('?' * len(source_ids))})"
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
    kinds: tuple[str, ...] = DEFAULT_KINDS,
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
        by_meaning = _vector_ranking(collection_id, query, embedder, source_ids, 30, kinds)
        by_words = _keyword_ranking(collection_id, query, source_ids, 30, kinds)
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


# One row per passage, whatever it belongs to. For an insight, the title and
# source id are those of the source it was made from.
_SELECT = (
    "SELECT c.id, COALESCE(c.source_id, i.source_id) AS source_id, c.note_id, c.insight_id, "
    "c.ord, c.page, c.start_sec, c.text, COALESCE(n.title, s.title, si.title) AS title, "
    "CASE WHEN c.note_id IS NOT NULL THEN 'note' WHEN c.insight_id IS NOT NULL THEN 'insight' "
    "ELSE s.kind END AS kind, COALESCE(s.origin, si.origin) AS origin, i.insight_type "
    "FROM chunks c LEFT JOIN sources s ON s.id = c.source_id "
    "LEFT JOIN notes n ON n.id = c.note_id "
    "LEFT JOIN source_insights i ON i.id = c.insight_id "
    "LEFT JOIN sources si ON si.id = i.source_id "
)


def _load(chunk_ids: list[int]) -> list[dict]:
    marks = ",".join("?" * len(chunk_ids))
    return repo_query(_SELECT + f"WHERE c.id IN ({marks})", chunk_ids)


def _neighbour(row: dict) -> dict | None:
    """The passage that follows this one in the same source, note or insight."""
    for column in ("note_id", "insight_id"):
        if row[column] is not None:
            return repo_one(_SELECT + f"WHERE c.{column} = ? AND c.ord = ?", (row[column], row["ord"] + 1))
    return repo_one(_SELECT + "WHERE c.source_id = ? AND c.ord = ?", (row["source_id"], row["ord"] + 1))
