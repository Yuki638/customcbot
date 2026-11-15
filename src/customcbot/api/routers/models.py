"""Saved models, and which model does which job."""

from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel

from ...ai import models
from ...ai.base import LLMError
from ...domain import Credential, Model
from ...exceptions import InvalidInputError

router = APIRouter(prefix="/api")


class ModelBody(BaseModel):
    credential_id: int
    name: str
    vision: bool = False


class VisionBody(BaseModel):
    vision: bool


class DefaultsBody(BaseModel):
    chat: int | None = None
    transformation: int | None = None
    vision: int | None = None


def _provisioner(request: Request):
    services = request.app.state.services
    if services.llm is not None:
        raise InvalidInputError("Models cannot be changed in demo mode.")
    return services.provisioner


def _listing() -> dict:
    services = {c.id: c.public() for c in Credential.where()}
    saved = [{**m.public(), "service": services[m.credential_id]["name"]} for m in Model.where()]
    return {"models": saved, "defaults": models.describe()}


@router.get("/models")
def list_models() -> dict:
    return _listing()


@router.post("/models")
def add_model(body: ModelBody, request: Request) -> dict:
    """Save a model after one small request proves that it answers."""
    provisioner = _provisioner(request)
    credential = Credential.get(body.credential_id)
    name = body.name.strip()
    if not name:
        raise InvalidInputError("Choose a model.")
    if credential.is_local:
        if not provisioner.ollama().is_installed(name):
            raise InvalidInputError(
                f"{name} is not downloaded yet. Use Change in Settings to download a local model."
            )
    else:
        try:
            provisioner.online().check(credential.address(), credential.key(), name)
        except LLMError as exc:
            raise InvalidInputError(str(exc)) from None
    models.add_model(credential, name, vision=body.vision)
    return _listing()


@router.patch("/models/{model_id}")
def mark_vision(model_id: int, body: VisionBody, request: Request) -> dict:
    _provisioner(request)
    Model.get(model_id).update(vision=body.vision)
    models.forget_missing()
    return _listing()


@router.delete("/models/{model_id}")
def delete_model(model_id: int, request: Request) -> dict:
    _provisioner(request)
    model = Model.get(model_id)
    chat = models.resolve("chat")
    if chat and chat[0].id == model.id:
        raise InvalidInputError("This model answers your questions. Choose another model for chat first.")
    model.delete()
    models.forget_missing()
    return _listing()


@router.put("/models/defaults")
def set_defaults(body: DefaultsBody, request: Request) -> dict:
    """Choose the model for each job. A job left out keeps its model; null means "fall back"."""
    _provisioner(request)
    chosen = body.model_dump(exclude_unset=True)
    if "chat" in chosen and chosen["chat"] is None:
        raise InvalidInputError("Chat needs a model.")
    models.set_defaults(chosen)
    return _listing()
