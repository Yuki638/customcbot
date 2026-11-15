# Notes for working on customcbot

A "chat with your own material" app: FastAPI backend in `src/customcbot`, a no-build Preact interface in `src/customcbot/web`, one SQLite file for storage, and a local model through Ollama or a free online service.

## Commands

- Install: `uv sync`
- Tests: `uv run pytest -q` (uses a stand-in model and embedder; no Ollama or network needed)
- Lint: `uv run ruff check .`
- Run with the stand-in model: `CUSTOMCBOT_FAKE=1 uv run customcbot --no-browser`
- Run for real: start Ollama, then `uv run customcbot --no-browser`
- Start-file check, as a new user would run it (unpacks a fresh copy, runs `start.bat` or `start.sh`, uses the app, restarts it): `python tests/smoke_start.py --data-dir <empty folder>`. CI runs it on Windows, macOS and Linux with `--like-new-pc`.
- Stand-in online service for trying the online option: `uv run python -m tests.standin 9911` (address `http://127.0.0.1:9911/v1`, key `test-key`)

## Layout

The layers follow [open-notebook](https://github.com/lfnovo/open-notebook), on a lighter stack (SQLite, one process, no build step). All paths are under `src/customcbot/`.

- `api/`: `main.py` builds the app, `middleware.py` checks each request, `routers/` has one file per resource, `command_service.py` submits and reads background jobs.
- `domain/`: stored objects (`Collection`, `Source`, `Note`, `Transformation`, `SourceInsight`, `ChatSession`, `Credential`, `Model`) on `ObjectModel` in `base.py`; `RecordModel` is a one-off settings record such as `DefaultModels`.
- `database/`: `repository.py` (`repo_query`, `repo_one`, `repo_execute`), `migrate.py` and numbered files in `migrations/` (`.sql`, or `.py` with `upgrade(conn)` to move data), hybrid search in `search.py`.
- `ai/`: model interface (`base.py`), Ollama client, client for online services (`openai_compat.py`), the list of kinds of service (`provider_registry.py`), which saved model does which job (`models.py`), ready-made clients per job (`provision.py`), embeddings, stand-in model, hardware detection, model sizes and online services (`catalog.py`).
- `graphs/`: the multi-step workflows: `source.py` (read and index a source), `chat.py`, `ask.py` (plan searches, take notes from each, write one answer), `transformation.py` (carry out a task on a source and store the insight), `summary.py`, `quiz.py`, `flashcards.py`.
- `commands/`: background work. `registry.py` has the `@command` decorator, `worker.py` runs commands one at a time.
- `prompts/`: every instruction sent to the model, as Jinja templates; `utils/prompter.py` renders them.
- `podcasts/`: turning material into a spoken episode: `generate.py` (plan, script, record), `speech.py` (offline Kokoro voices; `FakeSpeech` for tests), `audio.py` (join lines, save MP3), `voices.py`.
- `ingest/`: one module per kind of source (PDF, Office, images, audio and video, YouTube).
- `utils/`: chunking, indexing notes and insights for search, citation checking, building the passage text for a prompt, key encryption.
- `web/`: the interface. `cli.py` is the entry point.

## Conventions

- Routes stay thin: they call domain models and graphs. Raise the typed errors in `exceptions.py` (`NotFoundError`, `InvalidInputError`, ...); `api/main.py` turns them into replies. Do not build error replies by hand.
- To change the tables, add a new numbered file to `database/migrations/`. Never edit one that has shipped: existing data folders have already run it.
- `ObjectModel.save()` writes every field. When the worker may be writing the same row (a source being read), use `update(field=...)`.
- Slow work is a command: decorate it with `@command("name")` in a module that `commands/__init__.py` imports, and submit it with `command_service.submit_command_job`.
- All text sent to the model lives in `prompts/`, named by path: `render("chat/grounded_system")`. A missing value raises; it is never left blank.
- Model names appear only in `ai/catalog.py`. Online services get no fixed model name: the app lists what the service offers and suggests one by pattern.
- Several services can be saved at once (`credentials`, `models` tables). Code that needs a model asks for it by job: `services.model("chat")`, `"transformation"` (summaries, quizzes, flashcards) or `"vision"`. Never build a client directly.
- Keys are stored encrypted (`utils/encryption.py`) and must never be returned by an API route. Send `Credential.public()` and `config.public()` to the browser, never `model_dump()` of a credential.
- A passage (`chunks` row) belongs to a source, a note or an insight. `search.search(..., kinds=...)` chooses which: chat uses sources and notes; insights are searchable but not cited, because they restate the sources.
- A transformation is a task carried out on one source; its result is an insight. Built-in ones take their wording from `prompts/transformations/<name>.jinja` until the user rewords them.
- Ask numbers passages once across all its searches, so `[3]` means the same passage in the notes and in the final answer. Keep that when changing `graphs/ask.py`.
- A chat with `source_id` set is about that one source: it looks nowhere else, and a source short enough is read whole.
- Background LLM calls pass `background=True` so chat stays responsive.
- Error messages reach end users as written; keep them plain and say what to do next.
- After changing prompts or retrieval, test against a real small model (`gemma3:1b`), not only the stand-in. Small models are where things break.
- Models differ in how they write citations (`[2]`, `【2】`, `【2†L4-L9】`). `utils/citations.py` normalises them; add new styles there.
- The code is synchronous on purpose (SQLite and the local model clients are). Routes are plain `def`, so FastAPI runs them on threads.

## Live testing in a cloud session

Ollama is not in the base image. It can be installed with Nix:

```bash
nix-build --no-out-link -I nixpkgs=https://channels.nixos.org/nixpkgs-unstable/nixexprs.tar.xz '<nixpkgs>' -A ollama
```

Run `<store path>/bin/ollama serve`, pull `gemma3:1b`, and set `HF_HUB_DISABLE_XET=1` so the embedding model downloads through the allowed Hugging Face hosts. YouTube is not reachable from cloud IPs; YouTube code paths are covered by tests with recorded data only. The online path is tested against `tests/standin.py`. Real services are reachable only when a network secret for their host is saved on the environment (one exists for `api.groq.com`); the app then needs any placeholder as its key, because the proxy puts in the real one.
