"""The online option, tested against a stand-in service that speaks the OpenAI chat API."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel

from customcbot import config
from customcbot.ai import catalog, hardware
from customcbot.ai.base import LLMError, set_notice_hook
from customcbot.ai.embeddings import FakeEmbedder
from customcbot.ai.ollama import OllamaLLM
from customcbot.ai.openai_compat import OpenAICompatLLM
from customcbot.ai.router import SwitchLLM
from customcbot.api.main import create_app
from customcbot.services import Services

from . import standin
from .conftest import wait
from .helpers import ask, png_bytes, text_image

CELLS = (
    "Mitochondria are the powerhouse of the cell. They produce ATP through cellular respiration. "
    "The inner membrane is folded into cristae, which increase the surface area for reactions. "
)


@pytest.fixture(scope="module")
def service():
    running = standin.Running()
    yield running
    running.stop()


@pytest.fixture
def online_services(tmp_path, monkeypatch, service) -> Services:
    monkeypatch.setenv("CUSTOMCBOT_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.delenv("CUSTOMCBOT_API_KEY", raising=False)
    service.requests.clear()
    hw = hardware.Hardware(ram_gb=4.0, cpu_cores=2, gpu=None, gpu_gb=0.0, system="Linux")
    llm = SwitchLLM(
        # Nothing listens on this port: the local side is "Ollama not installed".
        OllamaLLM(config.get_all, lambda: "http://127.0.0.1:9"),
        OpenAICompatLLM(config.get_all, config.api_key, sleep=lambda seconds: None),
        config.online,
    )
    return Services(llm=llm, embedder=FakeEmbedder(), hardware=hw)


@pytest.fixture
def online_client(online_services):
    with TestClient(create_app(online_services)) as test_client:
        yield test_client


def connect(client, service, model="big-llama-3.3-70b", **extra):
    body = {"service": "custom", "base_url": service.base_url, "api_key": standin.KEY, "model": model, **extra}
    response = client.post("/api/setup/online", json=body)
    if response.status_code == 200:
        for _ in range(200):
            state = client.get("/api/setup").json()
            if not state["pull"]["active"]:
                break
    return response


def test_wizard_recommends_online_on_a_weak_computer(online_client):
    status = online_client.get("/api/setup").json()
    assert status["ready"] is False and status["mode"] == "local"
    assert status["recommended_mode"] == "online"  # 4 GB of memory
    assert {s["id"] for s in status["online_services"]} >= {"groq", "gemini", "openrouter", "freellmapi", "custom"}
    assert catalog.recommend_mode(hardware.Hardware(16.0, 8, None, 0.0, "Linux")) == "local"


def test_models_are_listed_with_a_sensible_suggestion(online_client, service):
    body = {"service": "groq", "base_url": service.base_url, "api_key": standin.KEY}
    listed = online_client.post("/api/setup/online/models", json=body).json()
    assert listed["suggested"] == "big-llama-3.3-70b"
    assert "tiny-8b" in listed["models"]
    assert not {"text-embedding-3", "whisper-large"} & set(listed["models"])


def test_address_without_v1_is_corrected(online_client, service):
    body = {"service": "custom", "base_url": service.base_url.removesuffix("/v1"), "api_key": standin.KEY}
    listed = online_client.post("/api/setup/online/models", json=body).json()
    assert listed["base_url"] == service.base_url and listed["models"]


def test_wrong_key_and_wrong_address_are_explained(online_client, service):
    body = {"service": "custom", "base_url": service.base_url, "api_key": "wrong"}
    response = online_client.post("/api/setup/online/models", json=body)
    assert response.status_code == 400 and "did not accept the key" in response.json()["detail"]
    response = online_client.post("/api/setup/online", json={**body, "model": "tiny-8b"})
    assert response.status_code == 400 and "did not accept the key" in response.json()["detail"]
    assert online_client.get("/api/setup").json()["mode"] == "local"  # nothing was saved

    body = {"service": "custom", "base_url": "http://127.0.0.1:9/v1", "api_key": "x"}
    response = online_client.post("/api/setup/online/models", json=body)
    assert response.status_code == 400 and "Nothing is answering" in response.json()["detail"]

    response = online_client.post("/api/setup/online/models", json={"service": "groq"})
    assert response.status_code == 400 and "key" in response.json()["detail"]


def test_unknown_model_is_explained(online_client, service):
    response = connect(online_client, service, model="missing")
    assert response.status_code == 400
    assert "cannot use the model missing" in response.json()["detail"]


def test_connecting_then_chatting_with_citations(online_client, service):
    assert connect(online_client, service).status_code == 200
    status = online_client.get("/api/setup").json()
    assert status["ready"] and status["mode"] == "online"

    collection = online_client.post("/api/collections", json={"name": "Biology"}).json()["id"]
    files = [("files", ("cells.txt", (CELLS * 4).encode(), "text/plain"))]
    online_client.post(f"/api/collections/{collection}/sources/files", files=files)
    wait(online_client)
    service.requests.clear()
    _, text, cited, _ = ask(online_client, collection, "What do mitochondria produce?")
    assert "Mitochondria are the powerhouse" in text and cited[0]["title"] == "cells"
    sent = service.requests[-1]
    assert sent["model"] == "big-llama-3.3-70b" and sent["stream"] is True
    assert sent["max_tokens"] >= 2000  # room for models that think before answering
    assert "Sources:" in sent["messages"][-1]["content"]


def test_the_key_never_reaches_the_browser(online_client, service):
    connect(online_client, service)
    for path in ("/api/setup", "/api/settings"):
        body = online_client.get(path).text
        assert standin.KEY not in body
    settings = online_client.get("/api/settings").json()
    assert settings["api_key_saved"] is True and "api_key" not in settings
    response = online_client.put("/api/settings", json={"values": {"api_key": "x"}})
    assert response.status_code == 400

    # Changing the model later does not need the key again.
    response = online_client.post(
        "/api/setup/online", json={"service": "custom", "base_url": service.base_url, "model": "tiny-8b"}
    )
    assert response.status_code == 200
    assert online_client.get("/api/settings").json()["api_model"] == "tiny-8b"


def test_key_can_come_from_the_environment(online_services, service, monkeypatch):
    with TestClient(create_app(online_services)):
        config.set_many({"provider": "online", "api_base_url": service.base_url, "api_model": "tiny-8b"})
        with pytest.raises(LLMError, match="did not accept the key"):
            online_services.llm.chat([{"role": "user", "content": "Hello"}])
        monkeypatch.setenv("CUSTOMCBOT_API_KEY", standin.KEY)
        assert "placeholder answer" in online_services.llm.chat([{"role": "user", "content": "Hello"}])
        assert config.public()["api_key_saved"] is True


def test_switching_back_to_local_takes_effect_at_once(online_client, online_services, service):
    connect(online_client, service)
    assert online_services.llm.active is online_services.llm.online
    config.set_many({"provider": "local"})
    assert online_services.llm.active is online_services.llm.local
    with pytest.raises(LLMError):  # the test's local side has no model set up
        online_services.llm.chat([{"role": "user", "content": "Hello"}])
    status = online_client.get("/api/setup").json()
    assert status["mode"] == "local" and status["ready"] is False


class Card(BaseModel):
    front: str
    back: str


@pytest.mark.parametrize(
    ("model", "formats"),
    [
        ("tiny-8b", ["json_schema"]),
        ("no-schema", ["json_schema", "json_object"]),
        ("prompt-only", ["json_schema", "json_object", None]),
    ],
)
def test_structured_replies_fall_back_when_a_format_is_refused(online_client, online_services, service, model, formats):
    connect(online_client, service, model=model)
    service.requests.clear()
    card = online_services.llm.chat_json([{"role": "user", "content": "Make a card."}], Card)
    assert card.front and card.back
    assert [(r.get("response_format") or {}).get("type") for r in service.requests] == formats
    if formats[-1] != "json_schema":
        assert "JSON schema" in service.requests[-1]["messages"][-1]["content"]
    # The refusal is remembered: the next request goes straight to what worked.
    service.requests.clear()
    online_services.llm.chat_json([{"role": "user", "content": "Another."}], Card)
    assert len(service.requests) == 1


def test_rate_limit_is_waited_out_and_reported(online_client, online_services, service):
    connect(online_client, service, model="tiny-8b")
    config.set_many({"api_model": "busy"})
    service.app.state.busy_left = 1
    notes: list[str] = []
    set_notice_hook(notes.append)
    try:
        reply = online_services.llm.chat([{"role": "user", "content": "Hello"}])
    finally:
        set_notice_hook(None)
    assert "placeholder answer" in reply
    assert notes == ["Waiting 1 s for the service's rate limit"]


def test_used_up_allowance_is_explained(online_client, online_services, service):
    connect(online_client, service, model="tiny-8b")
    config.set_many({"api_model": "busy"})
    service.app.state.busy_left = 99
    try:
        with pytest.raises(LLMError, match="free allowance .* is used up"):
            online_services.llm.chat([{"role": "user", "content": "Hello"}])
    finally:
        service.app.state.busy_left = 1


def test_single_piece_and_empty_replies(online_client, online_services, service):
    connect(online_client, service, model="one-piece")
    assert "placeholder answer" in online_services.llm.chat([{"role": "user", "content": "Hello"}])
    config.set_many({"api_model": "silent"})
    with pytest.raises(LLMError, match="empty answer"):
        online_services.llm.chat([{"role": "user", "content": "Hello"}])


def test_images_are_read_by_an_online_model_that_can_see(online_client, service):
    connect(online_client, service, model="vision-flash", vision=True)
    assert online_client.get("/api/setup").json()["vision_available"] is True
    collection = online_client.post("/api/collections", json={"name": "Notes"}).json()["id"]
    image = png_bytes(text_image("some handwriting"))
    online_client.post(
        f"/api/collections/{collection}/sources/files", files=[("files", ("note.png", image, "image/png"))]
    )
    wait(online_client)
    (source,) = online_client.get(f"/api/collections/{collection}/sources").json()
    assert source["status"] == "ready"
    unit = online_client.get(f"/api/sources/{source['id']}/units").json()["units"][0]
    assert unit["method"] == "vision" and "powerhouse" in unit["text"]
    parts = service.requests[-1]["messages"][-1]["content"]
    assert parts[0]["type"] == "text"
    assert parts[1]["image_url"]["url"].startswith("data:image/jpeg;base64,")


def test_study_tools_work_online(online_client, service):
    connect(online_client, service)
    collection = online_client.post("/api/collections", json={"name": "Biology"}).json()["id"]
    files = [("files", ("cells.txt", (CELLS * 6).encode(), "text/plain"))]
    online_client.post(f"/api/collections/{collection}/sources/files", files=files)
    wait(online_client)
    job = online_client.post(f"/api/collections/{collection}/quizzes", json={"count": 2}).json()
    wait(online_client)
    done = online_client.get(f"/api/jobs/{job['id']}").json()
    assert done["status"] == "done", done
    quiz = online_client.get(f"/api/quizzes/{done['result']['quiz_id']}").json()
    assert quiz["questions"] and quiz["questions"][0]["options"]


def test_demo_mode_has_no_online_option(client):
    response = client.post("/api/setup/online/models", json={"service": "groq", "api_key": "x"})
    assert response.status_code == 400 and "demo mode" in response.json()["detail"]
