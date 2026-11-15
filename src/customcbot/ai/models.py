"""Which saved model does which job.

There are three jobs: "chat" (answering questions), "transformation"
(summaries, quizzes, flashcards, insights) and "vision" (reading handwriting
and scanned pages). Each can be given its own model. A job without one falls
back: transformation uses the chat model, and vision uses the chat model if
that one can read images.
"""

from __future__ import annotations

from urllib.parse import urlparse

from .. import config
from ..domain.credential import Credential
from ..domain.model import LANGUAGE, DefaultModels, Model
from ..exceptions import InvalidInputError
from .provider_registry import OLLAMA, get_provider

TASKS = ("chat", "transformation", "vision")


def _pair(model_id: int | None) -> tuple[Model, Credential] | None:
    if model_id is None:
        return None
    model = Model.find(model_id)
    credential = Credential.find(model.credential_id) if model else None
    return (model, credential) if model and credential else None


def resolve(task: str) -> tuple[Model, Credential] | None:
    """The model and service for a job, after fallbacks. None if nothing is set up for it."""
    defaults = DefaultModels.load()
    chat = _pair(defaults.chat)
    if task == "chat":
        return chat
    if task == "transformation":
        return _pair(defaults.transformation) or chat
    if task == "vision":
        chosen = _pair(defaults.vision)
        if chosen:
            return chosen
        return chat if chat and chat[0].vision else None
    raise KeyError(task)


def chat_is_online() -> bool:
    chosen = resolve("chat")
    return bool(chosen and not chosen[1].is_local)


def describe() -> dict:
    """Each job with the model that will do it, for the Settings page."""
    defaults = DefaultModels.load()
    out = {}
    for task in TASKS:
        chosen = resolve(task)
        out[task] = {
            "model_id": getattr(defaults, task),  # what was picked; None means "fall back"
            "uses": {**chosen[0].public(), "service": chosen[1].public()["name"]} if chosen else None,
        }
    return out


def set_defaults(values: dict[str, int | None]) -> None:
    defaults = DefaultModels.load()
    for task, model_id in values.items():
        if task not in TASKS:
            raise InvalidInputError(f"There is no job called {task}.")
        if model_id is not None:
            model = Model.get(model_id)
            if model.type != LANGUAGE:
                raise InvalidInputError(f"{model.name} cannot be used for this.")
            if task == "vision" and not model.vision:
                raise InvalidInputError(f"{model.name} is not marked as able to read images.")
        setattr(defaults, task, model_id)
    defaults.save()
    sync_settings()


def forget_missing() -> None:
    """Clear any job whose model has been removed."""
    defaults = DefaultModels.load()
    changed = False
    for task in (*TASKS, "text_to_speech"):
        model_id = getattr(defaults, task)
        model = Model.find(model_id) if model_id is not None else None
        gone = model_id is not None and model is None
        cannot_see = task == "vision" and model is not None and not model.vision
        if gone or cannot_see:
            setattr(defaults, task, None)
            changed = True
    if changed:
        defaults.save()
    sync_settings()


def local_credential() -> Credential:
    found = Credential.where("provider = ?", (OLLAMA,))
    return found[0] if found else Credential(provider=OLLAMA, name=get_provider(OLLAMA).label).save()


def online_credential(provider_id: str, base_url: str | None = None) -> Credential | None:
    """The saved service of this kind (at this address, when one is given)."""
    for credential in Credential.where("provider = ?", (provider_id,), order_by="id DESC"):
        if base_url is None or credential.address() == base_url:
            return credential
    return None


def service_name(provider_id: str, address: str | None) -> str:
    """A label for a saved service. "Another service" says little, so its address is shown."""
    provider = get_provider(provider_id)
    if provider is None or provider.base_url is None:
        return urlparse(address or "").netloc or (provider.label if provider else provider_id)
    return provider.label


def add_model(credential: Credential, name: str, vision: bool = False, type: str = LANGUAGE) -> Model:
    """Save a model for a service, or return the one already saved."""
    found = Model.where("credential_id = ? AND name = ? AND type = ?", (credential.id, name, type))
    if found:
        model = found[0]
        if vision and not model.vision:
            model.update(vision=True)
        return model
    return Model(credential_id=credential.id, name=name, type=type, vision=vision).save()


def use_local(chat_model: str, vision_model: str | None) -> None:
    """Make local models do every job. Called by the setup page."""
    credential = local_credential()
    chat = add_model(credential, chat_model, vision=vision_model == chat_model)
    vision = add_model(credential, vision_model, vision=True) if vision_model else None
    DefaultModels(chat=chat.id, transformation=chat.id, vision=vision.id if vision else None).save()
    sync_settings()


def use_online(
    provider_id: str, base_url: str, key: str | None, model_name: str, vision: bool
) -> Credential:
    """Make one online model do every job. Called by the setup page."""
    credential = online_credential(provider_id, base_url)
    if credential is None:
        credential = Credential(provider=provider_id, name=service_name(provider_id, base_url), base_url=base_url)
    if key:
        credential.set_key(key)
    credential.save()
    model = add_model(credential, model_name, vision=vision)
    if model.vision != vision:
        model.update(vision=vision)
    DefaultModels(chat=model.id, transformation=model.id, vision=model.id if vision else None).save()
    sync_settings()
    return credential


def sync_settings() -> None:
    """Keep the older, simpler settings in step with the model chosen for chat.

    The setup page and the status reply still read these ("which mode is in
    use", "which model"), so they are rewritten whenever the choice changes.
    """
    chat = resolve("chat")
    if chat is None:
        return
    model, credential = chat
    vision = resolve("vision")
    if credential.is_local:
        local_vision = vision[0].name if vision and vision[1].is_local else None
        config.set_many({"provider": "local", "chat_model": model.name, "vision_model": local_vision})
    else:
        config.set_many(
            {
                "provider": "online",
                "online_service": credential.provider,
                "api_base_url": credential.address(),
                "api_model": model.name,
                "api_vision": bool(vision and vision[0].id == model.id),
            }
        )
