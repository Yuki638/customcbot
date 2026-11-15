from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from customcbot.ai import hardware
from customcbot.ai.embeddings import FakeEmbedder
from customcbot.ai.fake import FakeLLM
from customcbot.ai.provision import Provisioner
from customcbot.api.main import create_app
from customcbot.services import Services

from . import standin


@pytest.fixture
def services(tmp_path, monkeypatch) -> Services:
    monkeypatch.setenv("CUSTOMCBOT_DATA_DIR", str(tmp_path / "data"))
    hw = hardware.Hardware(ram_gb=8.0, cpu_cores=4, gpu=None, gpu_gb=0.0, system="Linux")
    return Services(llm=FakeLLM(), embedder=FakeEmbedder(), hardware=hw, fake=True)


@pytest.fixture
def client(services):
    with TestClient(create_app(services)) as test_client:
        yield test_client


@pytest.fixture
def collection(client) -> int:
    return client.post("/api/collections", json={"name": "Biology"}).json()["id"]


def wait(client) -> None:
    """Let the background worker finish what was queued."""
    client.app.state.services.worker.wait_idle()


# -- the online option, against stand-in services ---------------------------


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
    # Nothing listens on this port: the local side is "Ollama not installed".
    provisioner = Provisioner(ollama_url=lambda: "http://127.0.0.1:9", sleep=lambda seconds: None)
    return Services(embedder=FakeEmbedder(), hardware=hw, provisioner=provisioner)


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
