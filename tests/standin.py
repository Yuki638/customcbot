"""A stand-in for a hosted AI service that speaks the OpenAI chat API.

Used by the tests, and runnable on its own to try the online option by hand:

    uv run python -m tests.standin 9911

then choose "Another service", address http://127.0.0.1:9911/v1, key test-key.

Model names switch on behaviours a real service can show:
  no-schema    rejects response_format "json_schema" (accepts "json_object")
  prompt-only  rejects any response_format
  busy         answers 429 with Retry-After before each success
  one-piece    ignores "stream" and replies in a single JSON body
  silent       replies with no text
"""

from __future__ import annotations

import json
import socket
import sys
import threading
import time

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

from customcbot.ai.fake import default_responder

KEY = "test-key"
MODELS = [
    "tiny-8b",
    "big-llama-3.3-70b",
    "vision-flash",
    "no-schema",
    "prompt-only",
    "busy",
    "one-piece",
    "silent",
    "text-embedding-3",
    "whisper-large",
]
SCHEMA_MARKER = "JSON schema:\n"


def make_app() -> FastAPI:
    app = FastAPI()
    app.state.requests = []  # every chat request body, for tests to inspect
    app.state.busy_left = 1

    def refused(request: Request) -> JSONResponse | None:
        if request.headers.get("authorization") != f"Bearer {KEY}":
            return JSONResponse({"error": {"message": "Invalid API Key", "code": "invalid_api_key"}}, 401)
        return None

    @app.get("/v1/models")
    def models(request: Request):
        return refused(request) or {"object": "list", "data": [{"id": name} for name in MODELS]}

    @app.post("/v1/chat/completions")
    async def chat(request: Request):
        denied = refused(request)
        if denied:
            return denied
        body = await request.json()
        app.state.requests.append(body)
        model = body.get("model")
        fmt = (body.get("response_format") or {}).get("type")
        if model not in MODELS:
            return JSONResponse({"error": {"message": f"The model `{model}` does not exist"}}, 404)
        if (model == "no-schema" and fmt == "json_schema") or (model == "prompt-only" and fmt):
            return JSONResponse({"error": {"message": "response_format is not supported"}}, 400)
        if model == "busy":
            if app.state.busy_left > 0:
                app.state.busy_left -= 1
                return JSONResponse({"error": {"message": "Rate limit reached"}}, 429, headers={"Retry-After": "1"})
            app.state.busy_left = 1

        messages, images = [], []
        for message in body["messages"]:
            content = message["content"]
            if isinstance(content, list):
                images += [p["image_url"]["url"] for p in content if p["type"] == "image_url"]
                content = "".join(p["text"] for p in content if p["type"] == "text")
            messages.append({"role": message["role"], "content": content})
        schema = None
        if fmt == "json_schema":
            schema = body["response_format"]["json_schema"]["schema"]
        elif SCHEMA_MARKER in messages[-1]["content"]:
            text, _, raw = messages[-1]["content"].partition(SCHEMA_MARKER)
            messages[-1]["content"] = text
            schema = json.loads(raw)
        reply = "" if model == "silent" else default_responder(messages, schema, images or None)
        if "single word: ready" in messages[-1]["content"] and model != "silent":
            reply = "ready"

        if not body.get("stream") or model == "one-piece":
            return {"choices": [{"index": 0, "message": {"role": "assistant", "content": reply}}]}

        def events():
            yield 'data: {"choices":[{"index":0,"delta":{"role":"assistant"}}]}\n\n'
            for word in reply.split(" "):
                chunk = {"choices": [{"index": 0, "delta": {"content": word + " "}}]}
                yield f"data: {json.dumps(chunk)}\n\n"
            yield 'data: {"choices":[{"index":0,"delta":{},"finish_reason":"stop"}]}\n\n'
            yield "data: [DONE]\n\n"

        return StreamingResponse(events(), media_type="text/event-stream")

    return app


class Running:
    """The stand-in served on a free local port, in a background thread."""

    def __init__(self, port: int = 0) -> None:
        self.app = make_app()
        sock = socket.socket()
        sock.bind(("127.0.0.1", port))
        self.port = sock.getsockname()[1]
        self.base_url = f"http://127.0.0.1:{self.port}/v1"
        config = uvicorn.Config(self.app, log_level="warning")
        self._server = uvicorn.Server(config)
        self._thread = threading.Thread(target=self._server.run, kwargs={"sockets": [sock]}, daemon=True)
        self._thread.start()
        deadline = time.time() + 10
        while not self._server.started and time.time() < deadline:
            time.sleep(0.02)

    @property
    def requests(self) -> list[dict]:
        return self.app.state.requests

    def stop(self) -> None:
        self._server.should_exit = True
        self._thread.join(timeout=5)


if __name__ == "__main__":
    running = Running(int(sys.argv[1]) if len(sys.argv) > 1 else 9911)
    print(f"Stand-in service at {running.base_url}  (key: {KEY})", flush=True)
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        running.stop()
