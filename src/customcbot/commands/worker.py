"""One background thread that does the slow work, one task at a time.

A single worker is deliberate: local models and OCR are heavy, and running
two at once on a modest computer makes both slower.
"""

from __future__ import annotations

import json
import queue
import threading
import time
from typing import TYPE_CHECKING

from ..ai import base as llm_base
from ..database.repository import (
    repo_execute,
    repo_one,
    repo_query,
)
from ..utils import indexing
from .registry import get_command

if TYPE_CHECKING:
    from ..services import Services


class Cancelled(Exception):
    """Raised inside a job when the user cancels it."""


class JobContext:
    """What a running job uses to report progress and notice cancellation."""

    def __init__(self, job_id: int, worker: Worker) -> None:
        self.job_id = job_id
        self._worker = worker

    def progress(self, stage: str, fraction: float) -> None:
        if self.job_id in self._worker.cancelled:
            raise Cancelled()
        repo_execute(
            "UPDATE jobs SET stage = ?, progress = ? WHERE id = ?",
            (stage, max(0.0, min(fraction, 1.0)), self.job_id),
        )


class Worker:
    def __init__(self, services: Services) -> None:
        self.services = services
        self.cancelled: set[int] = set()
        self._queue: queue.Queue[int | None] = queue.Queue()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None:
            return
        # Pick up anything left unfinished when the app was last closed.
        waiting = repo_query("SELECT id, kind, params FROM jobs WHERE status IN ('queued', 'running') ORDER BY id")
        for row in waiting:
            self._queue.put(row["id"])
        # A source that is waiting without a job comes from a version that had no job for it.
        covered = {json.loads(r["params"]).get("source_id") for r in waiting if r["kind"] == "process_source"}
        for row in repo_query("SELECT id FROM sources WHERE status IN ('queued', 'processing') ORDER BY id"):
            if row["id"] not in covered:
                self.enqueue_source(row["id"])
        self._thread = threading.Thread(target=self._run, name="customcbot-worker", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._thread is not None:
            self._queue.put(None)
            self._thread.join(timeout=5)
            self._thread = None

    def wait_idle(self, timeout: float = 30) -> None:
        """Block until queued work is finished. Used by tests."""
        done = threading.Event()

        def waiter() -> None:
            self._queue.join()
            done.set()

        threading.Thread(target=waiter, daemon=True).start()
        if not done.wait(timeout):
            raise TimeoutError("worker did not finish in time")

    def enqueue_source(self, source_id: int) -> int | None:
        """Submit the command that reads and indexes a source."""
        source = repo_one("SELECT collection_id FROM sources WHERE id = ?", (source_id,))
        if source is None:
            return None
        return self.submit_job("process_source", source["collection_id"], {"source_id": source_id})

    def submit_job(self, kind: str, collection_id: int | None, params: dict) -> int:
        job_id = repo_execute(
            "INSERT INTO jobs (kind, collection_id, params) VALUES (?, ?, ?)",
            (kind, collection_id, json.dumps(params)),
        )
        self._queue.put(job_id)
        return job_id

    def cancel_job(self, job_id: int) -> None:
        self.cancelled.add(job_id)
        repo_execute(
            "UPDATE jobs SET status = 'error', error = 'Cancelled' WHERE id = ? AND status = 'queued'",
            (job_id,),
        )

    def _run(self) -> None:
        try:
            # Study guides carried over by an upgrade have no passages yet.
            indexing.index_missing(self.services.embedder)
        except Exception:  # the search model may not be downloaded yet; this runs again next start
            pass
        while True:
            job_id = self._queue.get()
            try:
                if job_id is None:
                    return
                self._run_job(job_id)
            except Exception:  # the worker thread must survive any single failure
                import traceback

                traceback.print_exc()
            finally:
                self._queue.task_done()

    def _run_job(self, job_id: int) -> None:
        job = repo_one("SELECT * FROM jobs WHERE id = ?", (job_id,))
        if job is None or job["status"] not in ("queued", "running"):
            return
        command = get_command(job["kind"])
        if command is None:
            repo_execute("UPDATE jobs SET status = 'error', error = 'Unknown job type' WHERE id = ?", (job_id,))
            return
        repo_execute("UPDATE jobs SET status = 'running', progress = 0 WHERE id = ?", (job_id,))
        context = JobContext(job_id, self)
        params = json.loads(job["params"])
        try:
            for attempt in range(1, command.max_attempts + 1):
                llm_base.set_notice_hook(
                    lambda text: repo_execute("UPDATE jobs SET stage = ? WHERE id = ?", (text, job_id))
                )
                try:
                    context.progress("Starting", 0.0)
                    result = command.run(job, params, self.services, context)
                    break
                except Cancelled:
                    raise
                except Exception as exc:
                    if attempt == command.max_attempts or isinstance(exc, command.stop_on):
                        raise
                    time.sleep(command.wait_seconds)
            repo_execute(
                "UPDATE jobs SET status = 'done', progress = 1, stage = NULL, result = ? WHERE id = ?",
                (json.dumps(result or {}), job_id),
            )
        except Cancelled:
            repo_execute("UPDATE jobs SET status = 'error', error = 'Cancelled' WHERE id = ?", (job_id,))
        except Exception as exc:
            repo_execute(
                "UPDATE jobs SET status = 'error', error = ? WHERE id = ?",
                (str(exc)[:400] or type(exc).__name__, job_id),
            )
        finally:
            llm_base.set_notice_hook(None)
            self.cancelled.discard(job_id)
