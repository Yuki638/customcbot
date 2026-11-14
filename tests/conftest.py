from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from customcbot.app import create_app
from customcbot.llm import hardware
from customcbot.llm.fake import FakeLLM
from customcbot.rag.embeddings import FakeEmbedder
from customcbot.services import Services


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
