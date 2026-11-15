"""Several AI services at once, and a model per job."""

from __future__ import annotations

import json
import sqlite3

import pytest

from customcbot import config
from customcbot.ai import models
from customcbot.ai.base import LLMError
from customcbot.database import migrate
from customcbot.database.repository import init_database, repo_one
from customcbot.domain import Credential, DefaultModels, Model
from customcbot.utils import encryption

from . import standin
from .conftest import connect, wait
from .helpers import ask

CELLS = (
    "Mitochondria are the powerhouse of the cell. They produce ATP through cellular respiration. "
    "The inner membrane is folded into cristae, which increase the surface area for reactions. "
)


@pytest.fixture(scope="module")
def second_service():
    running = standin.Running()
    yield running
    running.stop()


def add_second(client, second_service, model="tiny-8b", **extra) -> tuple[int, int]:
    """Save a second service and one model from it. Returns (credential id, model id)."""
    saved = client.post(
        "/api/credentials",
        json={"provider": "custom", "base_url": second_service.base_url, "api_key": standin.KEY},
    )
    assert saved.status_code == 200, saved.text
    credential_id = saved.json()["id"]
    listing = client.post("/api/models", json={"credential_id": credential_id, "name": model, **extra})
    assert listing.status_code == 200, listing.text
    model_id = next(m["id"] for m in listing.json()["models"] if m["credential_id"] == credential_id)
    return credential_id, model_id


# -- two services, a model per job -------------------------------------------


def test_chat_and_study_tools_can_use_different_services(online_client, service, second_service):
    connect(online_client, service)
    _, study_model = add_second(online_client, second_service)
    chosen = online_client.put("/api/models/defaults", json={"transformation": study_model}).json()
    assert chosen["defaults"]["chat"]["uses"]["name"] == "big-llama-3.3-70b"
    assert chosen["defaults"]["transformation"]["uses"]["name"] == "tiny-8b"

    collection = online_client.post("/api/collections", json={"name": "Biology"}).json()["id"]
    online_client.post(f"/api/collections/{collection}/sources/text", json={"title": "Cells", "text": CELLS * 3})
    wait(online_client)
    service.requests.clear()
    second_service.requests.clear()

    _, text, _, _ = ask(online_client, collection, "What do mitochondria produce?")
    assert text
    assert {r["model"] for r in service.requests} == {"big-llama-3.3-70b"}
    assert second_service.requests == []  # chat did not touch the second service

    service.requests.clear()
    job = online_client.post(f"/api/collections/{collection}/flashcards", json={"count": 2}).json()
    wait(online_client)
    assert online_client.get(f"/api/jobs/{job['id']}").json()["status"] == "done"
    assert {r["model"] for r in second_service.requests} == {"tiny-8b"}
    assert service.requests == []  # the study tools did not touch the first


def test_a_job_without_its_own_model_uses_the_chat_model(online_client, service):
    connect(online_client, service)
    defaults = online_client.get("/api/models").json()["defaults"]
    assert defaults["transformation"]["uses"]["name"] == "big-llama-3.3-70b"
    assert defaults["vision"]["uses"] is None  # this model was not marked as reading images
    assert models.resolve("vision") is None


def test_reading_images_can_be_given_to_another_service(online_client, online_services, service, second_service):
    connect(online_client, service)  # the chat model cannot read images
    assert online_services.model("vision").has_vision() is False
    _, reader = add_second(online_client, second_service, model="vision-flash", vision=True)
    online_client.put("/api/models/defaults", json={"vision": reader})
    assert online_services.model("vision").has_vision() is True
    assert online_client.get("/api/setup").json()["vision_available"] is True
    # Unmarking the model takes the job away from it again.
    online_client.patch(f"/api/models/{reader}", json={"vision": False})
    assert DefaultModels.load().vision is None
    assert online_services.model("vision").has_vision() is False


def test_a_model_that_cannot_read_images_is_refused_for_that_job(online_client, service, second_service):
    connect(online_client, service)
    _, plain = add_second(online_client, second_service)
    reply = online_client.put("/api/models/defaults", json={"vision": plain})
    assert reply.status_code == 400 and "read images" in reply.json()["detail"]


def test_changing_the_chat_model_changes_the_mode_shown(online_client, service):
    connect(online_client, service)
    assert online_client.get("/api/setup").json()["mode"] == "online"
    models.use_local("gemma3:4b", "gemma3:4b")
    status = online_client.get("/api/setup").json()
    assert status["mode"] == "local" and status["settings"]["chat_model"] == "gemma3:4b"
    # Both stay saved, so going back needs no key.
    assert {c["provider"] for c in online_client.get("/api/credentials").json()} == {"custom", "ollama"}
    online_model = next(m for m in Model.where() if m.name == "big-llama-3.3-70b")
    online_client.put("/api/models/defaults", json={"chat": online_model.id})
    assert online_client.get("/api/setup").json()["mode"] == "online"


# -- removing things ---------------------------------------------------------


def test_the_model_that_answers_questions_cannot_be_removed(online_client, service):
    connect(online_client, service)
    credential = Credential.where()[0]
    model = Model.where()[0]
    assert online_client.delete(f"/api/models/{model.id}").status_code == 400
    refused = online_client.delete(f"/api/credentials/{credential.id}")
    assert refused.status_code == 400 and "answers your questions" in refused.json()["detail"]
    assert Model.find(model.id) is not None


def test_removing_a_service_puts_its_jobs_back_on_the_chat_model(online_client, service, second_service):
    connect(online_client, service)
    credential_id, study_model = add_second(online_client, second_service)
    online_client.put("/api/models/defaults", json={"transformation": study_model})
    assert online_client.delete(f"/api/credentials/{credential_id}").status_code == 200
    assert Model.find(study_model) is None  # its models go with it
    assert models.resolve("transformation")[0].name == "big-llama-3.3-70b"


# -- keys --------------------------------------------------------------------


def test_keys_are_encrypted_on_disk_and_never_sent_to_the_browser(online_client, service, second_service):
    connect(online_client, service)
    add_second(online_client, second_service)
    stored = [row.api_key for row in Credential.where()]
    assert all(value.startswith(encryption.PREFIX) and standin.KEY not in value for value in stored)
    assert all(c.key() == standin.KEY for c in Credential.where())
    raw = (config.data_dir() / "customcbot.db").read_bytes()
    assert standin.KEY.encode() not in raw
    for path in ("/api/credentials", "/api/models", "/api/setup", "/api/settings", "/api/providers"):
        text = online_client.get(path).text
        assert standin.KEY not in text and encryption.PREFIX not in text, path
    assert all(c["has_key"] for c in online_client.get("/api/credentials").json())


def test_a_wrong_key_is_refused_when_adding_a_service(online_client, service, second_service):
    connect(online_client, service)
    reply = online_client.post(
        "/api/credentials", json={"provider": "custom", "base_url": second_service.base_url, "api_key": "nope"}
    )
    assert reply.status_code == 400 and "did not accept the key" in reply.json()["detail"]
    assert len(Credential.where()) == 1


def test_a_model_is_tested_before_it_is_saved(online_client, service):
    connect(online_client, service)
    credential = Credential.where()[0]
    reply = online_client.post("/api/models", json={"credential_id": credential.id, "name": "silent"})
    assert reply.status_code == 400 and "empty answer" in reply.json()["detail"]
    offered = online_client.get(f"/api/credentials/{credential.id}/discover").json()
    assert {"name": "big-llama-3.3-70b", "saved": True} in offered["models"]
    assert offered["suggested"] != "big-llama-3.3-70b"


def test_encryption_round_trip_and_a_lost_key(tmp_path, monkeypatch):
    monkeypatch.setenv("CUSTOMCBOT_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.delenv("CUSTOMCBOT_ENCRYPTION_KEY", raising=False)
    locked = encryption.encrypt("gsk_secret")
    assert locked != "gsk_secret" and encryption.decrypt(locked) == "gsk_secret"
    assert encryption.decrypt("plain-old-key") == "plain-old-key"  # saved before keys were encrypted
    monkeypatch.setenv("CUSTOMCBOT_ENCRYPTION_KEY", "a different lock")
    assert encryption.decrypt(locked) is None  # cannot be opened: the user is asked for the key again


def test_nothing_set_up_is_explained(online_services, online_client):
    with pytest.raises(LLMError, match="No AI model is set up yet"):
        online_services.model("chat").chat([{"role": "user", "content": "Hello"}])


def test_models_cannot_be_changed_in_demo_mode(client):
    assert client.get("/api/credentials").json() == []
    reply = client.post("/api/credentials", json={"provider": "groq", "api_key": "x"})
    assert reply.status_code == 400 and "demo mode" in reply.json()["detail"]


# -- upgrading from the version with one saved service -----------------------


def _old_database(path, settings: dict) -> None:
    old = sqlite3.connect(path)
    old.executescript((migrate.MIGRATIONS_DIR / "001_initial.sql").read_text(encoding="utf-8"))
    old.executemany(
        "INSERT INTO settings (key, value) VALUES (?, ?)", [(k, json.dumps(v)) for k, v in settings.items()]
    )
    old.commit()
    old.close()


def test_a_saved_online_service_survives_the_upgrade(tmp_path, monkeypatch):
    monkeypatch.setenv("CUSTOMCBOT_DATA_DIR", str(tmp_path))
    path = tmp_path / "customcbot.db"
    _old_database(path, {
        "setup_done": True, "provider": "online", "online_service": "groq",
        "api_base_url": "https://api.groq.com/openai/v1", "api_key": "gsk_old_key",
        "api_model": "llama-3.3-70b-versatile", "api_vision": False,
        "tier": "lite", "chat_model": "gemma3:1b", "vision_model": None,
    })  # fmt: skip
    init_database(path)
    model, credential = models.resolve("chat")
    assert (credential.provider, model.name) == ("groq", "llama-3.3-70b-versatile")
    assert credential.key() == "gsk_old_key" and "gsk_old_key" not in credential.api_key
    assert repo_one("SELECT value FROM settings WHERE key = 'api_key'") is None
    assert b"gsk_old_key" not in path.read_bytes()
    assert models.chat_is_online() and config.public()["api_key_saved"] is True
    # The local model chosen earlier is kept too, ready to switch back to.
    assert [m.name for m in Model.where("credential_id = ?", (models.local_credential().id,))] == ["gemma3:1b"]


def test_a_saved_local_model_survives_the_upgrade(tmp_path, monkeypatch):
    monkeypatch.setenv("CUSTOMCBOT_DATA_DIR", str(tmp_path))
    path = tmp_path / "customcbot.db"
    _old_database(path, {
        "setup_done": True, "provider": "local", "tier": "standard",
        "chat_model": "gemma3:4b", "vision_model": "gemma3:4b",
    })  # fmt: skip
    init_database(path)
    assert models.resolve("chat")[0].name == "gemma3:4b"
    assert models.resolve("vision")[0].name == "gemma3:4b"
    assert not models.chat_is_online()


def test_a_fresh_install_starts_with_nothing_saved(tmp_path, monkeypatch):
    monkeypatch.setenv("CUSTOMCBOT_DATA_DIR", str(tmp_path))
    init_database(tmp_path / "customcbot.db")
    assert Credential.where() == [] and models.resolve("chat") is None
