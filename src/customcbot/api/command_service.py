"""Submitting background commands and reading how they are getting on."""

from __future__ import annotations

import json

from ..commands.registry import get_command
from ..commands.worker import Worker
from ..database.repository import repo_one, repo_query
from ..exceptions import InvalidInputError, NotFoundError

JOB_FIELDS = "id, kind, collection_id, params, status, stage, progress, error, result, created_at"


def _job(row: dict) -> dict:
    row["params"] = json.loads(row["params"] or "{}")
    row["result"] = json.loads(row["result"]) if row["result"] else None
    return row


def get_job(job_id: int) -> dict:
    row = repo_one(f"SELECT {JOB_FIELDS} FROM jobs WHERE id = ?", (job_id,))
    if row is None:
        raise NotFoundError("That task no longer exists.")
    return _job(row)


def active_jobs(collection_id: int) -> list[dict]:
    rows = repo_query(
        f"SELECT {JOB_FIELDS} FROM jobs WHERE collection_id = ? AND status IN ('queued', 'running') ORDER BY id",
        (collection_id,),
    )
    return [_job(r) for r in rows]


def submit_command_job(worker: Worker, name: str, collection_id: int | None, params: dict) -> dict:
    """Queue the command `name` and return its job, which starts as "queued"."""
    if get_command(name) is None:
        raise InvalidInputError(f"There is no background task called {name}.")
    return get_job(worker.submit_job(name, collection_id, params))
