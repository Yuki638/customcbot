"""Sources: adding files, links and pasted text, and the text read from them."""

from __future__ import annotations

import re
import shutil
from pathlib import Path

from fastapi import APIRouter, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from ...database.repository import repo_execute, repo_one
from ...domain import Collection, Source
from ...exceptions import InvalidInputError, NotFoundError
from ...graphs import source as source_graph
from ...ingest import youtube

router = APIRouter(prefix="/api")

MAX_PASTED_CHARS = 2_000_000


class LinksBody(BaseModel):
    urls: list[str]


class TextBody(BaseModel):
    title: str = ""
    text: str


class UnitBody(BaseModel):
    text: str


def _safe_name(name: str) -> str:
    name = Path(name.replace("\\", "/")).name
    name = re.sub(r"[^\w.\- ]", "_", name).strip(" .")
    return name[-120:] or "file"


def _new_source(collection_id: int, kind: str, title: str, origin: str) -> Source:
    return Source(collection_id=collection_id, kind=kind, title=title, origin=origin, stage="Waiting").save()


@router.get("/collections/{collection_id}/sources")
def list_sources(collection_id: int) -> list[dict]:
    return Source.list_for_collection(collection_id)


@router.post("/collections/{collection_id}/sources/files")
def add_files(collection_id: int, files: list[UploadFile], request: Request) -> dict:
    Collection.get(collection_id)
    worker = request.app.state.services.worker
    added, rejected = [], []
    for upload in files:
        name = _safe_name(upload.filename or "file")
        kind = source_graph.kind_for(name)
        if kind is None:
            rejected.append({"name": name, "reason": "This file type is not supported."})
            continue
        source = _new_source(collection_id, kind, Path(name).stem or name, name)
        folder = source.folder()
        folder.mkdir(parents=True, exist_ok=True)
        with open(folder / name, "wb") as out:
            shutil.copyfileobj(upload.file, out, length=1024 * 1024)
        source.update(file_path=f"{source.id}/{name}")
        worker.enqueue_source(source.id)
        added.append(source.id)
    return {"added": added, "rejected": rejected}


@router.post("/collections/{collection_id}/sources/links")
def add_links(collection_id: int, body: LinksBody, request: Request) -> dict:
    Collection.get(collection_id)
    worker = request.app.state.services.worker
    videos: list[tuple[str, str]] = []
    rejected = []
    for url in (u.strip() for u in body.urls):
        if not url:
            continue
        try:
            if youtube.is_playlist(url):
                videos.extend(youtube.expand_playlist(url))
                continue
        except youtube.YouTubeError as exc:
            rejected.append({"name": url, "reason": str(exc)})
            continue
        vid = youtube.video_id(url)
        if vid is None:
            rejected.append({"name": url, "reason": "Only YouTube links are supported for now."})
        else:
            videos.append((vid, f"YouTube video {vid}"))

    added = []
    for vid, title in dict(videos).items():
        source = _new_source(collection_id, "youtube", title, youtube.watch_url(vid))
        worker.enqueue_source(source.id)
        added.append(source.id)
    return {"added": added, "rejected": rejected}


@router.post("/collections/{collection_id}/sources/text")
def add_text(collection_id: int, body: TextBody, request: Request) -> dict:
    Collection.get(collection_id)
    text = body.text.strip()
    if not text:
        raise InvalidInputError("Paste some text first.")
    if len(text) > MAX_PASTED_CHARS:
        raise InvalidInputError("That is too much text to paste at once. Save it as a file and upload it.")
    title = body.title.strip() or text.splitlines()[0][:60]
    source = _new_source(collection_id, "text", title, "Pasted text")
    folder = source.folder()
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "pasted.txt").write_text(text, encoding="utf-8")
    source.update(file_path=f"{source.id}/pasted.txt")
    request.app.state.services.worker.enqueue_source(source.id)
    return {"added": [source.id], "rejected": []}


@router.delete("/sources/{source_id}")
def delete_source(source_id: int) -> dict:
    Source.get(source_id).delete()
    return {"ok": True}


@router.post("/sources/{source_id}/retry")
def retry_source(source_id: int, request: Request) -> dict:
    Source.get(source_id).mark_queued()
    request.app.state.services.worker.enqueue_source(source_id)
    return {"ok": True}


@router.get("/sources/{source_id}/units")
def list_units(source_id: int) -> dict:
    source = Source.get(source_id)
    shown = source.model_dump(include={"id", "title", "kind", "origin", "note"})
    return {"source": shown, "units": source.units()}


@router.put("/units/{unit_id}")
def edit_unit(unit_id: int, body: UnitBody, request: Request) -> dict:
    """Let the user correct what was read (handwriting, speech), then re-index."""
    unit = repo_one("SELECT * FROM units WHERE id = ?", (unit_id,))
    if unit is None:
        raise NotFoundError("That text no longer exists.")
    repo_execute("UPDATE units SET text = ? WHERE id = ?", (body.text.strip(), unit_id))
    source_graph.rebuild_chunks(unit["source_id"], request.app.state.services)
    return {"ok": True}


@router.get("/sources/{source_id}/file")
def source_file(source_id: int) -> FileResponse:
    path = Source.get(source_id).stored_file()
    return FileResponse(path, filename=path.name, content_disposition_type="inline")
