"""The Search page, Ask, and chats about one source."""

from __future__ import annotations

import json

from customcbot import config
from customcbot.ai import models
from customcbot.ai.base import LLMError
from customcbot.ai.fake import FakeLLM, default_responder
from customcbot.domain import ChatSession, Source

from .helpers import ask, read_events
from .test_api import CELLS, ROME, run_job, sources, upload

PLANTS = "Chlorophyll absorbs light in the chloroplast. Photosynthesis turns water and carbon dioxide into glucose. "


def find(client, collection, query, **extra):
    reply = client.post(f"/api/collections/{collection}/search", json={"query": query, **extra})
    assert reply.status_code == 200, reply.text
    return reply.json()["results"]


# -- search ------------------------------------------------------------------


def test_search_covers_sources_notes_and_insights(client, collection):
    upload(client, collection, "cells.txt", (CELLS * 3).encode())
    cells = sources(client, collection)[0]
    client.post(f"/api/collections/{collection}/notes", json={"title": "Reminder", "content": "Mitochondria appear in the exam."})
    glossary = next(t["id"] for t in client.get("/api/transformations").json() if t["title"] == "Glossary")
    client.app.state.services.llm = FakeLLM(responder=lambda m, s, i: "**Mitochondria**: where ATP is made.")
    run_job(client, client.post(f"/api/sources/{cells['id']}/insights", json={"transformation_id": glossary}))

    everything = find(client, collection, "mitochondria")
    assert {r["kind"] for r in everything} == {"text", "note", "insight"}
    assert {r["label"] for r in everything} >= {"cells", "Your note: Reminder", "Glossary of cells"}
    assert [r["kind"] for r in find(client, collection, "mitochondria", kinds=["note"])] == ["note"]
    assert all(r["kind"] == "text" for r in find(client, collection, "mitochondria", kinds=["source"]))


def test_search_by_words_or_by_meaning(client, collection):
    upload(client, collection, "cells.txt", (CELLS * 3).encode())
    upload(client, collection, "rome.txt", (ROME * 3).encode())
    by_words = find(client, collection, "Rubicon", mode="words")
    assert by_words and all("Rubicon" in r["text"] and r["matched_words"] for r in by_words)
    assert find(client, collection, "xylophone", mode="words") == []
    by_meaning = find(client, collection, "Julius Caesar civil war", mode="meaning")
    assert by_meaning[0]["title"] == "rome"


def test_an_empty_search_is_refused(client, collection):
    reply = client.post(f"/api/collections/{collection}/search", json={"query": "  "})
    assert reply.status_code == 400 and reply.json()["detail"] == "Type what you are looking for."
    assert client.post(f"/api/collections/{collection}/search", json={"query": "x", "mode": "magic"}).status_code == 400
    assert client.post("/api/collections/999/search", json={"query": "x"}).status_code == 404


# -- ask ---------------------------------------------------------------------


def planner(searches: list[dict]):
    """A stand-in model that plans the given searches and otherwise answers as usual."""

    def respond(messages, schema, images):
        if schema is not None and "searches" in schema.get("properties", {}):
            return json.dumps({"searches": searches})
        return default_responder(messages, schema, images)

    return FakeLLM(responder=respond)


def run_ask(client, collection, question, **extra):
    reply = client.post(f"/api/collections/{collection}/ask", json={"question": question, **extra})
    assert reply.status_code == 200, reply.text
    events = read_events(reply)
    return events, {name: data for name, data in events}


def test_ask_plans_searches_takes_notes_and_writes_one_answer(client, collection):
    upload(client, collection, "cells.txt", (CELLS * 3).encode())
    upload(client, collection, "plants.txt", (PLANTS * 3).encode())
    llm = planner([
        {"term": "mitochondria ATP", "instructions": "Find what mitochondria produce."},
        {"term": "chlorophyll photosynthesis", "instructions": "Find what chlorophyll does."},
    ])  # fmt: skip
    client.app.state.services.llm = llm
    events, last = run_ask(client, collection, "How do mitochondria and chlorophyll differ?")

    assert [name for name, _ in events if name != "token"] == ["strategy", "answer", "answer", "sources", "done"]
    assert [s["term"] for s in last["strategy"]["searches"]] == ["mitochondria ATP", "chlorophyll photosynthesis"]
    first, second = (data for name, data in events if name == "answer")
    assert first["text"] and second["text"]
    # Passages are numbered once across both searches.
    numbers = [c["n"] for c in first["citations"]] + [c["n"] for c in second["citations"]]
    assert numbers == sorted(set(numbers)) and numbers[0] == 1
    assert {c["title"] for c in first["citations"]} == {"cells"}
    assert {c["title"] for c in second["citations"]} == {"plants"}
    assert [c["n"] for c in last["sources"]["citations"]] == numbers

    plan_call, first_call, second_call, final_call = llm.calls
    assert plan_call["json_schema"] is not None
    assert f"[{second['citations'][0]['n']}] plants" in second_call["messages"][-1]["content"]
    assert "Find out: Find what chlorophyll does." in second_call["messages"][-1]["content"]
    final_prompt = final_call["messages"][-1]["content"]
    assert 'Notes on "mitochondria ATP":' in final_prompt and 'Notes on "chlorophyll photosynthesis":' in final_prompt
    assert last["done"]["content"] and all(c["n"] in numbers for c in last["done"]["citations"])


def test_ask_with_one_search_does_not_write_twice(client, collection):
    upload(client, collection, "cells.txt", (CELLS * 3).encode())
    llm = planner([{"term": "mitochondria", "instructions": "Find what they produce."}])
    client.app.state.services.llm = llm
    events, last = run_ask(client, collection, "What do mitochondria produce?")
    assert len(llm.calls) == 2  # the plan, and one set of notes that is also the answer
    assert last["done"]["content"] == last["answer"]["text"] and last["done"]["citations"]


def test_the_smallest_local_model_is_not_asked_to_plan(client, collection):
    upload(client, collection, "cells.txt", (CELLS * 3).encode())
    config.set_many({"tier": "lite"})
    llm = FakeLLM()
    client.app.state.services.llm = llm
    events, last = run_ask(client, collection, "What do mitochondria produce?")
    assert [s["term"] for s in last["strategy"]["searches"]] == ["What do mitochondria produce?"]
    assert len(llm.calls) == 1 and llm.calls[0]["json_schema"] is None


def test_an_online_model_may_plan_three_searches(online_client, service):
    from .conftest import connect

    connect(online_client, service)
    assert models.chat_is_online()
    from customcbot.graphs.ask import max_searches

    assert max_searches() == 3


def test_ask_still_answers_when_planning_fails(client, collection):
    upload(client, collection, "cells.txt", (CELLS * 3).encode())

    def respond(messages, schema, images):
        if schema is not None:
            raise LLMError("The model's reply was not in the form the app needs.")
        return default_responder(messages, schema, images)

    client.app.state.services.llm = FakeLLM(responder=respond)
    events, last = run_ask(client, collection, "What do mitochondria produce?")
    assert last["strategy"]["searches"][0]["term"] == "What do mitochondria produce?"
    assert last["done"]["content"]


def test_ask_says_so_when_the_material_has_nothing(client, collection):
    assert "nothing to search yet" in run_ask(client, collection, "Anything?")[1]["done"]["content"]
    upload(client, collection, "cells.txt", (CELLS * 3).encode())
    client.app.state.services.llm = FakeLLM(responder=lambda m, s, i: "Nothing found." if s is None else default_responder(m, s, i))
    events, last = run_ask(client, collection, "What is the capital of France?")
    assert last["done"] == {"content": "I could not find anything about that in your material.", "citations": []}


def test_a_failing_model_ends_ask_with_its_message(client, collection):
    upload(client, collection, "cells.txt", (CELLS * 3).encode())

    def respond(messages, schema, images):
        if schema is not None:
            return default_responder(messages, schema, images)
        raise LLMError("The free allowance at example.com is used up for now.")

    client.app.state.services.llm = FakeLLM(responder=respond)
    events, last = run_ask(client, collection, "What do mitochondria produce?")
    assert last["error"]["message"].startswith("The free allowance") and "done" not in last
    assert client.post(f"/api/collections/{collection}/ask", json={"question": " "}).status_code == 400


# -- a chat about one source -------------------------------------------------


def test_a_chat_about_one_source_looks_only_there(client, collection):
    upload(client, collection, "cells.txt", (CELLS * 2).encode())
    upload(client, collection, "rome.txt", (ROME * 2).encode())
    cells, rome = sources(client, collection)
    chat = client.post(f"/api/sources/{rome['id']}/chats").json()
    # Even a question about the other source only gets passages from this one.
    _, _, cited, _ = ask(client, collection, "What do mitochondria produce?", chat_id=chat["id"])
    assert cited and {c["source_id"] for c in cited} == {rome["id"]}
    # A short source is read whole and in order.
    assert [c["text"] for c in cited] == [c["text"] for c in sorted(cited, key=lambda c: c["chunk_id"])]

    assert [c["id"] for c in client.get(f"/api/sources/{rome['id']}/chats").json()] == [chat["id"]]
    assert client.get(f"/api/sources/{cells['id']}/chats").json() == []
    assert client.get(f"/api/collections/{collection}/chats").json() == []  # kept apart from the collection's chats


def test_a_long_source_is_searched_rather_than_read_whole(client, collection):
    upload(client, collection, "cells.txt", (CELLS * 80).encode())
    cells = sources(client, collection)[0]
    chat = client.post(f"/api/sources/{cells['id']}/chats").json()
    _, _, cited, _ = ask(client, collection, "What do mitochondria produce?", chat_id=chat["id"])
    assert 0 < sum(len(c["text"]) for c in cited) <= config.passage_budget()[0] + 1700


def test_source_chats_need_a_ready_source_and_go_when_it_goes(client, collection):
    waiting = Source(collection_id=collection, kind="text", title="Later", status="queued").save()
    refused = client.post(f"/api/sources/{waiting.id}/chats")
    assert refused.status_code == 400 and "not ready yet" in refused.json()["detail"]
    upload(client, collection, "rome.txt", (ROME * 2).encode())
    rome = next(s for s in sources(client, collection) if s["title"] == "rome")
    chat = client.post(f"/api/sources/{rome['id']}/chats").json()
    client.delete(f"/api/sources/{rome['id']}")
    assert ChatSession.find(chat["id"]) is None
