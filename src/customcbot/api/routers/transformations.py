"""Transformations: the tasks that can be carried out on a source."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from ...domain import Transformation
from ...exceptions import InvalidInputError

router = APIRouter(prefix="/api")


class TransformationBody(BaseModel):
    title: str
    description: str = ""
    prompt: str = ""
    apply_default: bool = False


def _listing() -> list[dict]:
    return [t.public() for t in Transformation.where()]


@router.get("/transformations")
def list_transformations() -> list[dict]:
    return _listing()


@router.post("/transformations")
def add_transformation(body: TransformationBody) -> list[dict]:
    title, prompt = Transformation.clean(body.title, body.prompt)
    if not prompt:
        raise InvalidInputError("Write the instruction for this task.")
    Transformation(
        title=title, description=body.description.strip()[:200], prompt=prompt, apply_default=body.apply_default
    ).save()
    return _listing()


@router.put("/transformations/{transformation_id}")
def change_transformation(transformation_id: int, body: TransformationBody) -> list[dict]:
    transformation = Transformation.get(transformation_id)
    title, prompt = Transformation.clean(body.title, body.prompt)
    if not prompt and not transformation.builtin:
        raise InvalidInputError("Write the instruction for this task.")
    if transformation.builtin and prompt == Transformation(title=title, builtin=transformation.builtin).instruction():
        prompt = None  # unchanged built-in wording: keep following the template
    transformation.update(
        title=title,
        description=body.description.strip()[:200],
        prompt=prompt,
        apply_default=body.apply_default,
    )
    return _listing()


@router.post("/transformations/{transformation_id}/reset")
def reset_transformation(transformation_id: int) -> list[dict]:
    """Put a built-in task back to its original wording."""
    transformation = Transformation.get(transformation_id)
    if not transformation.builtin:
        raise InvalidInputError("Only the built-in tasks can be reset.")
    transformation.update(prompt=None)
    return _listing()


@router.delete("/transformations/{transformation_id}")
def delete_transformation(transformation_id: int) -> list[dict]:
    transformation = Transformation.get(transformation_id)
    if transformation.builtin:
        raise InvalidInputError("The built-in tasks cannot be removed. You can change their wording.")
    transformation.delete()
    return _listing()
