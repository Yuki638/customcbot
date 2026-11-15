"""First-run setup: choose a local model or an online service, and get it ready."""

from __future__ import annotations

import threading

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from .. import config
from ..llm import catalog
from ..llm.base import LLMError
from ..llm.ollama import OllamaLLM
from ..llm.openai_compat import OpenAICompatLLM
from ..llm.router import SwitchLLM

router = APIRouter(prefix="/api")

EDITABLE_SETTINGS = {"num_ctx", "context_chars", "whisper_model", "ollama_url", "chat_model", "vision_model"}


class InstallRequest(BaseModel):
    tier: str | None = None
    chat_model: str | None = None  # for a custom choice
    vision_model: str | None = None


class OnlineRequest(BaseModel):
    service: str
    base_url: str | None = None  # needed for "custom"; optional override otherwise
    api_key: str | None = None  # empty: use the key that is already saved
    model: str | None = None
    vision: bool | None = None


class SettingsUpdate(BaseModel):
    values: dict


def _pull_state(request: Request) -> dict:
    if not hasattr(request.app.state, "pull"):
        request.app.state.pull = {"active": False, "done": False, "error": None}
    return request.app.state.pull


def _local(services) -> OllamaLLM | None:
    llm = services.llm
    if isinstance(llm, SwitchLLM):
        return llm.local
    return llm if isinstance(llm, OllamaLLM) else None


def _online(services) -> OpenAICompatLLM | None:
    llm = services.llm
    if isinstance(llm, SwitchLLM):
        return llm.online
    return llm if isinstance(llm, OpenAICompatLLM) else None


@router.get("/setup")
def status(request: Request) -> dict:
    services = request.app.state.services
    # Read the progress first: setup marks itself done in the settings before it
    # reports "done" here, so a reply that says done always has settings to match.
    pull = dict(_pull_state(request))
    settings = config.public()
    local = _local(services)
    online = settings["provider"] == "online" and _online(services) is not None
    if local is not None:
        version = local.version()
        # Ask Ollama nothing more when it is not running; each failed attempt
        # to reach it takes a couple of seconds on Windows.
        installed = local.installed_models() if version else []
        chat_ok = bool(version) and local.is_installed(settings["chat_model"])
        local_vision = bool(version and settings["vision_model"]) and local.is_installed(settings["vision_model"])
    else:
        version, installed, chat_ok, local_vision = "built-in test model", [], True, services.llm.has_vision()
    if online:
        usable = bool(settings["api_base_url"] and settings["api_model"])
        vision = bool(settings["api_vision"])
    else:
        usable = bool(version and chat_ok)
        vision = local_vision
    return {
        "ready": services.fake or bool(settings["setup_done"] and usable),
        "fake": services.fake,
        "mode": "online" if online else "local",
        "recommended_mode": catalog.recommend_mode(services.hardware),
        "online_services": [s.to_dict() for s in catalog.ONLINE_SERVICES],
        "ollama": {"running": version is not None, "version": version, "url": config.ollama_url()},
        "hardware": services.hardware.to_dict(),
        "tiers": [t.to_dict() for t in catalog.TIERS],
        "recommended": catalog.recommend(services.hardware),
        "settings": settings,
        "installed_models": installed,
        "chat_model_installed": chat_ok,
        "vision_available": vision,
        "pull": pull,
    }


@router.post("/setup/install")
def install(body: InstallRequest, request: Request) -> dict:
    """Use a local model: save the choice and download what is missing."""
    services = request.app.state.services
    state = _pull_state(request)
    if state["active"]:
        raise HTTPException(409, "A download is already running.")
    if body.tier and body.tier != "custom":
        try:
            tier = catalog.get_tier(body.tier)
        except KeyError:
            raise HTTPException(400, "Unknown model size.") from None
        values = catalog.settings_for(tier, services.hardware)
    elif body.chat_model:
        values = {
            "tier": "custom",
            "chat_model": body.chat_model.strip(),
            "vision_model": (body.vision_model or "").strip() or None,
        }
    else:
        raise HTTPException(400, "Choose a model size.")
    config.set_many({**values, "provider": "local"})

    models = list(dict.fromkeys(m for m in (values["chat_model"], values["vision_model"]) if m))
    _start_install(services, state, models)
    return state


def _resolve_online(body: OnlineRequest) -> tuple[catalog.OnlineService, str, str | None]:
    """(service, address, key) for a request from the wizard."""
    try:
        service = catalog.get_service(body.service)
    except KeyError:
        raise HTTPException(400, "Unknown service.") from None
    base_url = (body.base_url or "").strip() or service.base_url
    if not base_url:
        raise HTTPException(400, "Enter the address of the service.")
    if not base_url.startswith(("http://", "https://")):
        base_url = "https://" + base_url
    key = (body.api_key or "").strip()
    if not key and config.get("online_service") == service.id:
        key = config.api_key() or ""  # changing the model keeps the saved key
    if not key and service.needs_key:
        raise HTTPException(400, "Paste your key first.")
    return service, base_url.rstrip("/"), key or None


def _require_online(request: Request) -> OpenAICompatLLM:
    llm = _online(request.app.state.services)
    if llm is None:
        raise HTTPException(400, "Online services are not available in demo mode.")
    return llm


@router.post("/setup/online/models")
def online_models(body: OnlineRequest, request: Request) -> dict:
    """Check the address and key, and list the models the service offers."""
    llm = _require_online(request)
    service, base_url, key = _resolve_online(body)
    try:
        try:
            names = llm.list_models(base_url, key)
        except LLMError:
            # People often paste an address without its "/v1" ending.
            if "/v1" in base_url:
                raise
            names = llm.list_models(base_url + "/v1", key)
            base_url += "/v1"
    except LLMError as exc:
        raise HTTPException(400, str(exc)) from None
    models = catalog.usable_models(service, names)
    if not models and service.prefer:
        models = [service.prefer[0]]  # a router with no list still accepts its default name
    return {"base_url": base_url, "models": models, "suggested": models[0] if models else None}


@router.post("/setup/online")
def use_online(body: OnlineRequest, request: Request) -> dict:
    """Use an online service: test it with one small request, then save it."""
    services = request.app.state.services
    llm = _require_online(request)
    state = _pull_state(request)
    if state["active"]:
        raise HTTPException(409, "A download is already running.")
    service, base_url, key = _resolve_online(body)
    model = (body.model or "").strip()
    if not model:
        raise HTTPException(400, "Choose a model.")
    try:
        llm.check(base_url, key, model)
    except LLMError as exc:
        raise HTTPException(400, str(exc)) from None
    values = {
        "provider": "online",
        "online_service": service.id,
        "api_base_url": base_url,
        "api_model": model,
        "api_vision": service.vision if body.vision is None else bool(body.vision),
    }
    if (body.api_key or "").strip():
        values["api_key"] = body.api_key.strip()
    config.set_many(values)
    _start_install(services, state, [])
    return state


def _start_install(services, state: dict, models: list[str]) -> None:
    state.clear()
    state.update(active=True, done=False, error=None, model=None, status="Starting", completed=0, total=0)
    threading.Thread(target=_install, args=(services, state, models), daemon=True).start()


def _install(services, state: dict, models: list[str]) -> None:
    try:
        local = _local(services)
        if local is not None:
            for index, model in enumerate(models):
                if local.is_installed(model):
                    continue
                state.update(model=model, step=index + 1, steps=len(models), completed=0, total=0)
                for update in local.pull(model):
                    state.update(
                        status=update.get("status", ""),
                        completed=update.get("completed", 0),
                        total=update.get("total", 0),
                    )
        state.update(model=None, status="Getting the search index ready", completed=0, total=0)
        services.embedder.prepare()
        config.set_many({"setup_done": True})
        state.update(active=False, done=True, status="Done")
    except Exception as exc:  # shown to the user in the wizard
        state.update(active=False, error=str(exc) or type(exc).__name__)


@router.post("/setup/finish")
def finish(request: Request) -> dict:
    """The user has seen the "all set" screen; do not show it again."""
    _pull_state(request)["done"] = False
    return {"ok": True}


@router.get("/settings")
def get_settings() -> dict:
    return config.public()


@router.put("/settings")
def update_settings(body: SettingsUpdate) -> dict:
    unknown = set(body.values) - EDITABLE_SETTINGS
    if unknown:
        raise HTTPException(400, f"Cannot change: {', '.join(sorted(unknown))}")
    values = dict(body.values)
    for key in ("num_ctx", "context_chars"):
        if key in values:
            values[key] = max(1024, min(int(values[key]), 65536))
    for key in ("ollama_url", "vision_model"):
        if key in values:
            values[key] = (values[key] or "").strip() or None
    config.set_many(values)
    return config.public()
