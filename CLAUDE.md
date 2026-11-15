# Notes for working on customcbot

A local "chat with your own material" app: FastAPI backend in `src/customcbot`, a no-build Preact interface in `src/customcbot/web`, one SQLite file for storage, Ollama for the model.

## Commands

- Install: `uv sync`
- Tests: `uv run pytest -q` (uses a stand-in model and embedder; no Ollama or network needed)
- Lint: `uv run ruff check .`
- Run with the stand-in model: `CUSTOMCBOT_FAKE=1 uv run customcbot --no-browser`
- Run for real: start Ollama, then `uv run customcbot --no-browser`
- Stand-in online service for trying the online option: `uv run python -m tests.standin 9911` (address `http://127.0.0.1:9911/v1`, key `test-key`)

## Layout

- `llm/`: model interface (`base.py`), Ollama client, client for online services (`openai_compat.py`), the switch between them (`router.py`), stand-in model, hardware detection, model sizes and online services (`catalog.py`).
- `ingest/`: one module per kind of source; `pipeline.py` ties them together; `chunking.py` splits text.
- `rag/`: embeddings, hybrid search (`retrieve.py`), prompts, chat, citation checking.
- `study/`: summaries, quizzes, flashcards. These run as jobs on the single background worker (`worker.py`).
- `api/`: HTTP routes. `app.py` builds the app; `cli.py` is the entry point.

## Conventions

- All text sent to the model lives in `rag/prompts.py`.
- Model names appear only in `llm/catalog.py`. Online services get no fixed model name: the app lists what the service offers and suggests one by pattern.
- The online key must never be returned by an API route. Use `config.public()` for anything sent to the browser.
- Background LLM calls pass `background=True` so chat stays responsive.
- Error messages reach end users as written; keep them plain and say what to do next.
- After changing prompts or retrieval, test against a real small model (`gemma3:1b`), not only the stand-in. Small models are where things break.
- Models differ in how they write citations (`[2]`, `【2】`, `【2†L4-L9】`). `rag/citations.py` normalises them; add new styles there.

## Live testing in a cloud session

Ollama is not in the base image. It can be installed with Nix:

```bash
nix-build --no-out-link -I nixpkgs=https://channels.nixos.org/nixpkgs-unstable/nixexprs.tar.xz '<nixpkgs>' -A ollama
```

Run `<store path>/bin/ollama serve`, pull `gemma3:1b`, and set `HF_HUB_DISABLE_XET=1` so the embedding model downloads through the allowed Hugging Face hosts. YouTube is not reachable from cloud IPs; YouTube code paths are covered by tests with recorded data only. The online path is tested against `tests/standin.py`. Real services are reachable only when a network secret for their host is saved on the environment (one exists for `api.groq.com`); the app then needs any placeholder as its key, because the proxy puts in the real one.
