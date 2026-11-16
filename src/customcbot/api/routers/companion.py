"""The study companion: its name and faces, and what it remembers about the user."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse
from pydantic import BaseModel

from ... import config
from ...domain.memory import Memory
from ...exceptions import InvalidInputError, NotFoundError
from ...graphs import companion

router = APIRouter(prefix="/api")

MOODS = ("neutral", "happy", "thinking", "sad")
PICTURE_TYPES = (".png", ".webp", ".jpg", ".jpeg", ".gif", ".svg")
BUILT_IN = Path(__file__).parent.parent.parent / "web" / "companion"
MAX_NAME = 24


def own_pictures_dir() -> Path:
    """Pictures put here replace the built-in faces: neutral.png, happy.png, thinking.png, sad.png."""
    return config.data_dir() / "companion"


def _picture(mood: str) -> Path:
    folder = own_pictures_dir()
    if folder.is_dir():
        for wanted in (mood, "neutral"):  # one picture is enough: it is then used for every mood
            for ending in PICTURE_TYPES:
                if (folder / f"{wanted}{ending}").is_file():
                    return folder / f"{wanted}{ending}"
    return BUILT_IN / f"{mood}.svg"


def _state() -> dict:
    return {
        "enabled": companion.active(),
        "name": companion.name(),
        "memory": bool(config.get("memory")),
        "own_pictures": any(_picture(m).parent != BUILT_IN for m in MOODS),
        "pictures_folder": str(own_pictures_dir()),
    }


class CompanionUpdate(BaseModel):
    enabled: bool | None = None
    name: str | None = None
    memory: bool | None = None


class MemoryBody(BaseModel):
    content: str


@router.get("/companion")
def get_companion() -> dict:
    return _state()


@router.put("/companion")
def update_companion(body: CompanionUpdate) -> dict:
    values: dict = {}
    if body.enabled is not None:
        values["companion"] = body.enabled
    if body.memory is not None:
        values["memory"] = body.memory
    if body.name is not None:
        name = " ".join(body.name.split())
        if not name:
            raise InvalidInputError("Give your companion a name.")
        if len(name) > MAX_NAME:
            raise InvalidInputError(f"Keep the name under {MAX_NAME} characters.")
        values["companion_name"] = name
    config.set_many(values)
    return _state()


@router.get("/companion/face/{mood}")
def face(mood: str) -> FileResponse:
    if mood not in MOODS:
        raise NotFoundError("There is no such picture.")
    return FileResponse(_picture(mood), headers={"Cache-Control": "no-cache"})


@router.get("/memories")
def list_memories() -> list[dict]:
    return Memory.all()


@router.post("/memories")
def add_memory(body: MemoryBody) -> dict:
    memory = Memory.remember(body.content)
    if memory is None:
        raise InvalidInputError("That is already remembered.")
    return memory.model_dump()


@router.put("/memories/{memory_id}")
def edit_memory(memory_id: int, body: MemoryBody) -> dict:
    return Memory.get(memory_id).update(content=Memory.clean(body.content)).model_dump()


@router.delete("/memories/{memory_id}")
def forget_memory(memory_id: int) -> dict:
    memory = Memory.find(memory_id)
    if memory is not None:
        memory.delete()
    return {"ok": True}


@router.delete("/memories")
def forget_everything() -> dict:
    Memory.clear()
    return {"ok": True}
