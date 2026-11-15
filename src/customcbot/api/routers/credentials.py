"""Saved AI services: adding one, checking it, and listing what it offers."""

from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel

from ...ai import catalog, models
from ...ai.base import LLMError
from ...ai.provider_registry import PROVIDERS, get_provider
from ...domain import Credential, Model
from ...exceptions import InvalidInputError

router = APIRouter(prefix="/api")


class CredentialBody(BaseModel):
    provider: str | None = None
    name: str | None = None
    base_url: str | None = None
    api_key: str | None = None  # empty: keep the saved key


def _provisioner(request: Request):
    services = request.app.state.services
    if services.llm is not None:
        raise InvalidInputError("AI services cannot be changed in demo mode.")
    return services.provisioner


def _address(provider_id: str, given: str | None) -> str:
    address = (given or "").strip() or get_provider(provider_id).base_url
    if not address:
        raise InvalidInputError("Enter the address of the service.")
    if not address.startswith(("http://", "https://")):
        address = "https://" + address
    return address.rstrip("/")


def _offered(provisioner, credential: Credential) -> list[str]:
    """The names of the models a service has right now."""
    if credential.is_local:
        return provisioner.ollama().installed_models()
    service = catalog.get_service(credential.provider)
    names = provisioner.online().list_models(credential.address(), credential.key())
    return catalog.usable_models(service, names) or list(service.prefer[:1])


def _shown(credential: Credential) -> dict:
    saved = Model.where("credential_id = ?", (credential.id,))
    return {**credential.public(), "models": [m.public() for m in saved]}


@router.get("/providers")
def list_providers() -> list[dict]:
    return [p.to_dict() for p in PROVIDERS.values()]


@router.get("/credentials")
def list_credentials() -> list[dict]:
    return [_shown(c) for c in Credential.where()]


@router.post("/credentials")
def add_credential(body: CredentialBody, request: Request) -> dict:
    """Save a service after checking that its address and key work."""
    provisioner = _provisioner(request)
    provider = get_provider(body.provider or "")
    if provider is None:
        raise InvalidInputError("Unknown service.")
    if provider.local:
        return _shown(models.local_credential())
    key = (body.api_key or "").strip() or None
    if provider.needs_key and not key:
        raise InvalidInputError("Paste your key first.")
    address = _address(provider.id, body.base_url)
    try:
        try:
            provisioner.online().list_models(address, key)
        except LLMError:
            if "/v1" in address:  # people often paste an address without its "/v1" ending
                raise
            provisioner.online().list_models(address + "/v1", key)
            address += "/v1"
    except LLMError as exc:
        raise InvalidInputError(str(exc)) from None
    credential = models.online_credential(provider.id, address) or Credential(
        provider=provider.id, name=models.service_name(provider.id, address), base_url=address
    )
    credential.name = (body.name or "").strip()[:60] or credential.name
    credential.set_key(key)
    return _shown(credential.save())


@router.put("/credentials/{credential_id}")
def change_credential(credential_id: int, body: CredentialBody, request: Request) -> dict:
    provisioner = _provisioner(request)
    credential = Credential.get(credential_id)
    if (body.name or "").strip():
        credential.name = body.name.strip()[:60]
    if not credential.is_local:
        if (body.base_url or "").strip():
            credential.base_url = _address(credential.provider, body.base_url)
        if (body.api_key or "").strip():
            credential.set_key(body.api_key)
        try:
            provisioner.online().list_models(credential.address(), credential.key())
        except LLMError as exc:
            raise InvalidInputError(str(exc)) from None
    credential.save()
    models.sync_settings()
    return _shown(credential)


@router.delete("/credentials/{credential_id}")
def delete_credential(credential_id: int, request: Request) -> dict:
    _provisioner(request)
    credential = Credential.get(credential_id)
    chat = models.resolve("chat")
    if chat and chat[1].id == credential.id:
        raise InvalidInputError(
            "This service answers your questions. Choose a model from another service for chat first."
        )
    credential.delete()
    models.forget_missing()
    return {"ok": True}


@router.get("/credentials/{credential_id}/discover")
def discover_models(credential_id: int, request: Request) -> dict:
    """What the service offers right now, with the ones already saved marked."""
    provisioner = _provisioner(request)
    credential = Credential.get(credential_id)
    try:
        names = _offered(provisioner, credential)
    except LLMError as exc:
        raise InvalidInputError(str(exc)) from None
    saved = {m.name for m in Model.where("credential_id = ?", (credential.id,))}
    return {
        "models": [{"name": name, "saved": name in saved} for name in names],
        "suggested": next((name for name in names if name not in saved), None),
    }
