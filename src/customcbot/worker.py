"""One background thread that does the slow work, one task at a time.

A single worker is deliberate: local models and OCR are heavy, and running
two at once on a modest computer makes both slower.
"""

from __future__ import annotations

import json
import queue
import threading
from collections.abc import Callable
from typing import TYPE_CHECKING

from . import db

if TYPE_CHECKING:
    from .services import Services


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
        db.execute(
            "UPDATE jobs SET stage = ?, progress = ? WHERE id = ?",
            (stage, max(0.0, min(fraction, 1.0)), self.job_id),
        )


JobHandler = Callable[[dict, dict, "Services", JobContext], dict | None]


class Worker:
    def __init__(self, services: Services) -> None:
        self.services = services
        self.handlers: dict[str, JobHandler] = {}
        self.cancelled: set[int] = set()
        self._queue: queue.Queue[tuple[str, int] | None] = queue.Queue()
        self._thread: threading.Thread | None = None

    def register(self, kind: str, handler: JobHandler) -> None:
        self.handlers[kind] = handler

    def start(self) -> None:
        if self._thread is not None:
            return
        # Pick up anything left unfinished when the app was last closed.
        for row in db.query("SELECT id FROM sources WHERE status IN ('queued', 'processing') ORDER BY id"):
            self._queue.put(("source", row["id"]))
        for row in db.query("SELECT id FROM jobs WHERE status IN ('queued', 'running') ORDER BY id"):
            self._queue.put(("job", row["id"]))
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

    def enqueue_source(self, source_id: int) -> None:
        self._queue.put(("source", source_id))

    def submit_job(self, kind: str, collection_id: int | None, params: dict) -> int:
        job_id = db.execute(
            "INSERT INTO jobs (kind, collection_id, params) VALUES (?, ?, ?)",
            (kind, collection_id, json.dumps(params)),
        )
        self._queue.put(("job", job_id))
        return job_id

    def cancel_job(self, job_id: int) -> None:
        self.cancelled.add(job_id)
        db.execute(
            "UPDATE jobs SET status = 'error', error = 'Cancelled' WHERE id = ? AND status = 'queued'",
            (job_id,),
        )

    def _run(self) -> None:
        from .ingest.pipeline import process_source

        while True:
            task = self._queue.get()
            try:
                if task is None:
                    return
                kind, item_id = task
                if kind == "source":
                    process_source(item_id, self.services)
                else:
                    self._run_job(item_id)
            except Exception:  # the worker thread must survive any single failure
                import traceback

                traceback.print_exc()
            finally:
                self._queue.task_done()

    def _run_job(self, job_id: int) -> None:
        job = db.one("SELECT * FROM jobs WHERE id = ?", (job_id,))
        if job is None or job["status"] not in ("queued", "running"):
            return
        handler = self.handlers.get(job["kind"])
        if handler is None:
            db.execute("UPDATE jobs SET status = 'error', error = 'Unknown job type' WHERE id = ?", (job_id,))
            return
        db.execute("UPDATE jobs SET status = 'running', progress = 0 WHERE id = ?", (job_id,))
        context = JobContext(job_id, self)
        try:
            context.progress("Starting", 0.0)
            result = handler(job, json.loads(job["params"]), self.services, context)
            db.execute(
                "UPDATE jobs SET status = 'done', progress = 1, stage = NULL, result = ? WHERE id = ?",
                (json.dumps(result or {}), job_id),
            )
        except Cancelled:
            db.execute("UPDATE jobs SET status = 'error', error = 'Cancelled' WHERE id = ?", (job_id,))
        except Exception as exc:
            db.execute(
                "UPDATE jobs SET status = 'error', error = ? WHERE id = ?",
                (str(exc)[:400] or type(exc).__name__, job_id),
            )
        finally:
            self.cancelled.discard(job_id)
