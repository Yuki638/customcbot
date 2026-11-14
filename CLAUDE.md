# Notes for working on customcbot

A local "chat with your own material" app: FastAPI backend in `src/customcbot`, a no-build Preact interface in `src/customcbot/web`, one SQLite file for storage, Ollama for the model.

## Commands

- Install: `uv sync`
- Tests: `uv run pytest -q` (uses a stand-in model and embedder; no Ollama or network needed)
- Lint: `uv run ruff check .`
- Run with the stand-in model: `CUSTOMCBOT_FAKE=1 uv run customcbot --no-browser`
- Run for real: start Ollama, then `uv run customcbot --no-browser`

## Layout

- `llm/`: model interface (`base.py`), Ollama client, stand-in model, hardware detection, model sizes (`catalog.py`).
- `ingest/`: one module per kind of source; `pipeline.py` ties them together; `chunking.py` splits text.
- `rag/`: embeddings, hybrid search (`retrieve.py`), prompts, chat, citation checking.
- `study/`: summaries, quizzes, flashcards. These run as jobs on the single background worker (`worker.py`).
- `api/`: HTTP routes. `app.py` builds the app; `cli.py` is the entry point.

## Conventions

- All text sent to the model lives in `rag/prompts.py`.
- Model names appear only in `llm/catalog.py`.
- Background LLM calls pass `background=True` so chat stays responsive.
- Error messages reach end users as written; keep them plain and say what to do next.
- After changing prompts or retrieval, test against a real small model (`gemma3:1b`), not only the stand-in. Small models are where things break.

## Live testing in a cloud session

Ollama is not in the base image. It can be installed with Nix:

```bash
nix-build --no-out-link -I nixpkgs=https://channels.nixos.org/nixpkgs-unstable/nixexprs.tar.xz '<nixpkgs>' -A ollama
```

Run `<store path>/bin/ollama serve`, pull `gemma3:1b`, and set `HF_HUB_DISABLE_XET=1` so the embedding model downloads through the allowed Hugging Face hosts. YouTube is not reachable from cloud IPs; YouTube code paths are covered by tests with recorded data only.
