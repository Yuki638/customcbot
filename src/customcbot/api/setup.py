"""First-run setup: check Ollama, recommend a model size, download it."""

from __future__ import annotations

import threading

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from .. import config
from ..llm import catalog
from ..llm.ollama import OllamaLLM

router = APIRouter(prefix="/api")

EDITABLE_SETTINGS = {"num_ctx", "context_chars", "whisper_model", "ollama_url", "chat_model", "vision_model"}


class InstallRequest(BaseModel):
    tier: str | None = None
    chat_model: str | None = None  # for a custom choice
    vision_model: str | None = None


class SettingsUpdate(BaseModel):
    values: dict


def _pull_state(request: Request) -> dict:
    if not hasattr(request.app.state, "pull"):
        request.app.state.pull = {"active": False, "done": False, "error": None}
    return request.app.state.pull


@router.get("/setup")
def status(request: Request) -> dict:
    services = request.app.state.services
    settings = config.get_all()
    llm = services.llm
    if isinstance(llm, OllamaLLM):
        version = llm.version()
        installed = llm.installed_models() if version else []
        chat_ok = llm.is_installed(settings["chat_model"])
        vision_ok = bool(settings["vision_model"]) and llm.is_installed(settings["vision_model"])
    else:
        version, installed, chat_ok, vision_ok = "built-in test model", [], True, llm.has_vision()
    return {
        "ready": services.fake or bool(settings["setup_done"] and version and chat_ok),
        "fake": services.fake,
        "ollama": {"running": version is not None, "version": version, "url": config.ollama_url()},
        "hardware": services.hardware.to_dict(),
        "tiers": [t.to_dict() for t in catalog.TIERS],
        "recommended": catalog.recommend(services.hardware),
        "settings": settings,
        "installed_models": installed,
        "chat_model_installed": chat_ok,
        "vision_available": vision_ok,
        "pull": _pull_state(request),
    }


@router.post("/setup/install")
def install(body: InstallRequest, request: Request) -> dict:
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
    config.set_many(values)

    models = list(dict.fromkeys(m for m in (values["chat_model"], values["vision_model"]) if m))
    state.clear()
    state.update(active=True, done=False, error=None, model=None, status="Starting", completed=0, total=0)
    threading.Thread(target=_install, args=(services, state, models), daemon=True).start()
    return state


def _install(services, state: dict, models: list[str]) -> None:
    try:
        llm = services.llm
        if isinstance(llm, OllamaLLM):
            for index, model in enumerate(models):
                if llm.is_installed(model):
                    continue
                state.update(model=model, step=index + 1, steps=len(models), completed=0, total=0)
                for update in llm.pull(model):
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
    return config.get_all()


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
    return config.get_all()
