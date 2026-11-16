# How customcbot is built

The layers follow [open-notebook](https://github.com/lfnovo/open-notebook). The stack is lighter, so that the app starts with one double-click and runs on a modest computer.

| open-notebook | customcbot |
|---|---|
| Next.js frontend | `web/`: Preact with no build step, served by the same process |
| FastAPI app, one router per resource | the same: `api/main.py`, `api/routers/` |
| SurrealDB (documents, full-text and vector search) | one SQLite file: tables, FTS5 for words, stored vectors for meaning |
| Separate worker process with `@command` jobs | `commands/`: the same decorator and retry rules, run on one thread inside the app |
| LangGraph workflows | `graphs/`: the same workflows as plain Python steps |
| Esperanto for model providers | `ai/`: a client for Ollama and one for any OpenAI-compatible service |
| Jinja prompt templates | the same: `prompts/` |
| Docker Compose, supervisord | `start.bat` / `start.sh`; Docker is optional |

## One process

```
browser ── web/ (static files)
   │
   ▼
api/routers ──► domain models ──► database/repository ──► SQLite file
   │                 ▲
   │ slow work       │
   ▼                 │
commands (worker thread) ──► graphs ──► ai/provision ──► Ollama or an online service
                                  └──► ingest, podcasts (local OCR, speech to text, voices)
```

- **A request** reaches a router, which calls domain models and returns. Typed errors (`exceptions.py`) become replies in one place.
- **Slow work** (reading a source, a quiz, a task on a source, a podcast) is submitted as a command. The route returns the job at once and the browser asks for its progress. One command runs at a time, on purpose: two heavy jobs at once make a small computer slower at both.
- **Chat and Ask** run inside the request and stream their answer as events.

## Stored objects

A **collection** (open-notebook's notebook) holds **sources**, **notes**, chats, quizzes, flashcards and podcast episodes. A **transformation** is a task carried out on one source; what it writes is a **source insight**. Text is cut into **passages** (`chunks`), each belonging to a source, a note or an insight, and indexed twice: by words and by meaning.

Models are chosen through **credentials** (a saved service, key encrypted), **models** (a model of that service) and one record of **default models** saying which model does which job. Code asks for a model by job: `services.model("chat")`.

## Workflows (`graphs/`)

| Workflow | Steps |
|---|---|
| `source` | read the file or link, split into passages, embed, index |
| `chat` | resolve a follow-up, search, answer with numbered sources, check the citations |
| `ask` | plan a few searches, take notes from each, write one answer; passages are numbered once across all searches |
| `transformation` | read a source whole, or reduce a long one to notes first, then carry out the task |
| `summary`, `quiz`, `flashcards` | map over passages, then combine |
| `companion` | adds the companion's voice to the chat prompt; answers a greeting without a search; after a chat turn, a `remember` command picks out lasting facts about the user |
| `podcasts.generate` | collect material, outline, script part by part, record each line, join into an MP3 |

## Changing the tables

Add a numbered file to `database/migrations/`: `.sql`, or `.py` with an `upgrade(conn)` function when data has to be moved. Files run in order at start, once per data folder. Never edit one that has shipped.

## What is deliberately different

- The code is synchronous. SQLite and the local model clients are, and FastAPI runs plain functions on threads.
- Chat cites sources and notes, but not insights: an insight restates a source, and the page itself is the better citation.
- Podcast voices are local only. No online speech service is wired in.
