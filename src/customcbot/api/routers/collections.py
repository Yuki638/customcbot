"""Collections: one per subject or project."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from ...domain import Collection

router = APIRouter(prefix="/api")


class CollectionBody(BaseModel):
    name: str


@router.get("/collections")
def list_collections() -> list[dict]:
    return Collection.list_with_counts()


@router.post("/collections")
def create_collection(body: CollectionBody) -> dict:
    return Collection(name=Collection.clean_name(body.name)).save().model_dump()


@router.patch("/collections/{collection_id}")
def rename_collection(collection_id: int, body: CollectionBody) -> dict:
    collection = Collection.get(collection_id)
    return collection.update(name=Collection.clean_name(body.name)).model_dump()


@router.delete("/collections/{collection_id}")
def delete_collection(collection_id: int) -> dict:
    Collection.get(collection_id).delete()
    return {"ok": True}
