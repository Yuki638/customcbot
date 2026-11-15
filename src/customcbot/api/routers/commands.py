"""Progress of background commands (reading a source, writing a quiz)."""

from __future__ import annotations

from fastapi import APIRouter, Request

from .. import command_service

router = APIRouter(prefix="/api")


@router.get("/collections/{collection_id}/jobs")
def active_jobs(collection_id: int) -> list[dict]:
    return command_service.active_jobs(collection_id)


@router.get("/jobs/{job_id}")
@router.get("/commands/jobs/{job_id}")
def get_job(job_id: int) -> dict:
    return command_service.get_job(job_id)


@router.delete("/jobs/{job_id}")
@router.delete("/commands/jobs/{job_id}")
def cancel_job(job_id: int, request: Request) -> dict:
    request.app.state.services.worker.cancel_job(job_id)
    return {"ok": True}
