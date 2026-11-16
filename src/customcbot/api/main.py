"""Builds the web application."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from .. import __version__, config
from ..ai import hardware
from ..ai.embeddings import FakeEmbedder, FastEmbedder
from ..ai.fake import FakeLLM
from ..database.repository import (
    init_database,
)
from ..exceptions import CustomcbotError
from ..services import Services
from .middleware import password_required, same_origin_only
from .routers import (
    auth as auth_routes,
)
from .routers import (
    chat,
    collections,
    commands,
    companion,
    credentials,
    episode_profiles,
    insights,
    models,
    notes,
    podcasts,
    search,
    settings,
    setup,
    source_chat,
    sources,
    speaker_profiles,
    study,
    transformations,
)

ROUTERS = (
    auth_routes, setup, settings, credentials, models, collections, sources, notes, transformations, insights,
    chat, source_chat, companion, search, study, podcasts, speaker_profiles, episode_profiles, commands,
)  # fmt: skip

WEB_DIR = Path(__file__).parent.parent / "web"


def build_services() -> Services:
    hw = hardware.detect()
    if os.environ.get("CUSTOMCBOT_FAKE") == "1":
        return Services(llm=FakeLLM(), embedder=FakeEmbedder(), hardware=hw, fake=True)
    embedder = FastEmbedder(config.get("embedding_model"), str(config.models_dir() / "embeddings"))
    return Services(embedder=embedder, hardware=hw)


def create_app(services: Services | None = None) -> FastAPI:
    init_database(config.data_dir() / "customcbot.db")
    services = services or build_services()
    worker = services.worker

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        worker.start()
        yield
        worker.stop()

    app = FastAPI(title="customcbot", version=__version__, lifespan=lifespan, docs_url="/api/docs")
    app.state.services = services

    app.middleware("http")(password_required)
    app.middleware("http")(same_origin_only)

    @app.exception_handler(CustomcbotError)
    async def typed_error(request: Request, exc: CustomcbotError) -> JSONResponse:
        return JSONResponse({"detail": exc.message}, status_code=exc.status_code)

    for module in ROUTERS:
        app.include_router(module.router)
    app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
    return app
