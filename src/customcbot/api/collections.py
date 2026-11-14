"""Collections and the sources inside them."""

from __future__ import annotations

import re
import shutil
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from .. import config, db
from ..ingest import pipeline, youtube
from ..rag import retrieve

router = APIRouter(prefix="/api")

SOURCE_FIELDS = "id, collection_id, kind, title, origin, status, stage, progress, error, note, created_at"
MAX_PASTED_CHARS = 2_000_000


class CollectionBody(BaseModel):
    name: str


class LinksBody(BaseModel):
    urls: list[str]


class TextBody(BaseModel):
    title: str = ""
    text: str


class UnitBody(BaseModel):
    text: str


def _collection(collection_id: int) -> dict:
    row = db.one("SELECT * FROM collections WHERE id = ?", (collection_id,))
    if row is None:
        raise HTTPException(404, "That collection no longer exists.")
    return row


def _source(source_id: int) -> dict:
    row = db.one("SELECT * FROM sources WHERE id = ?", (source_id,))
    if row is None:
        raise HTTPException(404, "That source no longer exists.")
    return row


def _safe_name(name: str) -> str:
    name = Path(name.replace("\\", "/")).name
    name = re.sub(r"[^\w.\- ]", "_", name).strip(" .")
    return name[-120:] or "file"


# -- collections ----------------------------------------------------------


@router.get("/collections")
def list_collections() -> list[dict]:
    return db.query(
        "SELECT c.id, c.name, c.created_at, "
        "(SELECT COUNT(*) FROM sources s WHERE s.collection_id = c.id) AS source_count "
        "FROM collections c ORDER BY c.id DESC"
    )


@router.post("/collections")
def create_collection(body: CollectionBody) -> dict:
    name = body.name.strip()
    if not name:
        raise HTTPException(400, "Give the collection a name.")
    collection_id = db.execute("INSERT INTO collections (name) VALUES (?)", (name[:100],))
    return _collection(collection_id)


@router.patch("/collections/{collection_id}")
def rename_collection(collection_id: int, body: CollectionBody) -> dict:
    _collection(collection_id)
    name = body.name.strip()
    if not name:
        raise HTTPException(400, "Give the collection a name.")
    db.execute("UPDATE collections SET name = ? WHERE id = ?", (name[:100], collection_id))
    return _collection(collection_id)


@router.delete("/collections/{collection_id}")
def delete_collection(collection_id: int) -> dict:
    _collection(collection_id)
    for source in db.query("SELECT id FROM sources WHERE collection_id = ?", (collection_id,)):
        shutil.rmtree(config.files_dir() / str(source["id"]), ignore_errors=True)
    db.execute("DELETE FROM chunks WHERE collection_id = ?", (collection_id,))
    db.execute("DELETE FROM collections WHERE id = ?", (collection_id,))
    retrieve.invalidate(collection_id)
    return {"ok": True}


# -- sources --------------------------------------------------------------


@router.get("/collections/{collection_id}/sources")
def list_sources(collection_id: int) -> list[dict]:
    return db.query(
        f"SELECT {SOURCE_FIELDS} FROM sources WHERE collection_id = ? ORDER BY id", (collection_id,)
    )


@router.post("/collections/{collection_id}/sources/files")
def add_files(collection_id: int, files: list[UploadFile], request: Request) -> dict:
    _collection(collection_id)
    worker = request.app.state.services.worker
    added, rejected = [], []
    for upload in files:
        name = _safe_name(upload.filename or "file")
        kind = pipeline.kind_for(name)
        if kind is None:
            rejected.append({"name": name, "reason": "This file type is not supported."})
            continue
        source_id = db.execute(
            "INSERT INTO sources (collection_id, kind, title, origin, stage) VALUES (?, ?, ?, ?, 'Waiting')",
            (collection_id, kind, Path(name).stem or name, name),
        )
        folder = config.files_dir() / str(source_id)
        folder.mkdir(parents=True, exist_ok=True)
        with open(folder / name, "wb") as out:
            shutil.copyfileobj(upload.file, out, length=1024 * 1024)
        db.execute("UPDATE sources SET file_path = ? WHERE id = ?", (f"{source_id}/{name}", source_id))
        worker.enqueue_source(source_id)
        added.append(source_id)
    return {"added": added, "rejected": rejected}


@router.post("/collections/{collection_id}/sources/links")
def add_links(collection_id: int, body: LinksBody, request: Request) -> dict:
    _collection(collection_id)
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
        source_id = db.execute(
            "INSERT INTO sources (collection_id, kind, title, origin, stage) VALUES (?, 'youtube', ?, ?, 'Waiting')",
            (collection_id, title, youtube.watch_url(vid)),
        )
        worker.enqueue_source(source_id)
        added.append(source_id)
    return {"added": added, "rejected": rejected}


@router.post("/collections/{collection_id}/sources/text")
def add_text(collection_id: int, body: TextBody, request: Request) -> dict:
    _collection(collection_id)
    text = body.text.strip()
    if not text:
        raise HTTPException(400, "Paste some text first.")
    if len(text) > MAX_PASTED_CHARS:
        raise HTTPException(400, "That is too much text to paste at once. Save it as a file and upload it.")
    title = body.title.strip() or text.splitlines()[0][:60]
    source_id = db.execute(
        "INSERT INTO sources (collection_id, kind, title, origin, stage) VALUES (?, 'text', ?, 'Pasted text', 'Waiting')",
        (collection_id, title),
    )
    folder = config.files_dir() / str(source_id)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "pasted.txt").write_text(text, encoding="utf-8")
    db.execute("UPDATE sources SET file_path = ? WHERE id = ?", (f"{source_id}/pasted.txt", source_id))
    request.app.state.services.worker.enqueue_source(source_id)
    return {"added": [source_id], "rejected": []}


@router.delete("/sources/{source_id}")
def delete_source(source_id: int) -> dict:
    source = _source(source_id)
    db.execute("DELETE FROM chunks WHERE source_id = ?", (source_id,))
    db.execute("DELETE FROM sources WHERE id = ?", (source_id,))
    db.execute("UPDATE collections SET summary = NULL WHERE id = ?", (source["collection_id"],))
    shutil.rmtree(config.files_dir() / str(source_id), ignore_errors=True)
    retrieve.invalidate(source["collection_id"])
    return {"ok": True}


@router.post("/sources/{source_id}/retry")
def retry_source(source_id: int, request: Request) -> dict:
    _source(source_id)
    db.execute(
        "UPDATE sources SET status = 'queued', stage = 'Waiting', error = NULL, progress = 0 WHERE id = ?",
        (source_id,),
    )
    request.app.state.services.worker.enqueue_source(source_id)
    return {"ok": True}


@router.get("/sources/{source_id}/units")
def list_units(source_id: int) -> dict:
    source = _source(source_id)
    units = db.query(
        "SELECT id, ord, page, start_sec, method, text FROM units WHERE source_id = ? ORDER BY ord",
        (source_id,),
    )
    return {"source": {k: source[k] for k in ("id", "title", "kind", "origin", "note")}, "units": units}


@router.put("/units/{unit_id}")
def edit_unit(unit_id: int, body: UnitBody, request: Request) -> dict:
    """Let the user correct what was read (handwriting, speech), then re-index."""
    unit = db.one("SELECT * FROM units WHERE id = ?", (unit_id,))
    if unit is None:
        raise HTTPException(404, "That text no longer exists.")
    db.execute("UPDATE units SET text = ? WHERE id = ?", (body.text.strip(), unit_id))
    pipeline.rebuild_chunks(unit["source_id"], request.app.state.services)
    return {"ok": True}


@router.get("/sources/{source_id}/file")
def source_file(source_id: int) -> FileResponse:
    source = _source(source_id)
    if not source["file_path"]:
        raise HTTPException(404, "This source has no file.")
    root = config.files_dir().resolve()
    path = (root / source["file_path"]).resolve()
    if root not in path.parents or not path.is_file():
        raise HTTPException(404, "The file is missing.")
    return FileResponse(path, filename=path.name, content_disposition_type="inline")
