"""Builds the web application."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlparse

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from . import __version__, config, db
from .api import chat, collections, setup, study
from .llm import hardware
from .llm.fake import FakeLLM
from .llm.ollama import OllamaLLM
from .llm.openai_compat import OpenAICompatLLM
from .llm.router import SwitchLLM
from .rag.embeddings import FakeEmbedder, FastEmbedder
from .services import Services
from .study import flashcards, quiz, summary

WEB_DIR = Path(__file__).parent / "web"


def build_services() -> Services:
    hw = hardware.detect()
    if os.environ.get("CUSTOMCBOT_FAKE") == "1":
        return Services(llm=FakeLLM(), embedder=FakeEmbedder(), hardware=hw, fake=True)
    embedder = FastEmbedder(config.get("embedding_model"), str(config.models_dir() / "embeddings"))
    llm = SwitchLLM(
        OllamaLLM(config.get_all, config.ollama_url),
        OpenAICompatLLM(config.get_all, config.api_key),
        config.online,
    )
    return Services(llm=llm, embedder=embedder, hardware=hw)


def create_app(services: Services | None = None) -> FastAPI:
    db.init(config.data_dir() / "customcbot.db")
    services = services or build_services()
    worker = services.worker
    worker.register("summary_source", summary.job_summarize_source)
    worker.register("summary_collection", summary.job_summarize_collection)
    worker.register("quiz", quiz.job_generate)
    worker.register("flashcards", flashcards.job_generate)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        worker.start()
        yield
        worker.stop()

    app = FastAPI(title="customcbot", version=__version__, lifespan=lifespan, docs_url="/api/docs")
    app.state.services = services

    @app.middleware("http")
    async def same_origin_only(request: Request, call_next):
        # The app has no login, so refuse requests that another website makes
        # from the user's browser to this local server.
        origin = request.headers.get("origin")
        if origin and urlparse(origin).netloc != request.headers.get("host"):
            return JSONResponse({"detail": "Cross-site requests are not allowed."}, status_code=403)
        response = await call_next(request)
        if not request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-cache"
        return response

    for module in (setup, collections, chat, study):
        app.include_router(module.router)
    app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
    return app
