"""The study companion: its voice in chat, small talk, memory and pictures."""

from __future__ import annotations

import json

from customcbot import config
from customcbot.ai.fake import FakeLLM
from customcbot.domain.memory import MAX_MEMORIES, Memory
from customcbot.graphs import companion

from .helpers import ask
from .test_api import CELLS, upload


def system_prompts(llm) -> list[str]:
    return [call["messages"][0]["content"] for call in llm.calls]


def test_answers_come_from_the_named_companion_and_keep_citations(client, collection):
    upload(client, collection, "cells.txt", (CELLS * 5).encode())
    llm = client.app.state.services.llm
    _, text, cited, _ = ask(client, collection, "What do mitochondria produce?")
    assert "[1]" in text and cited
    assert "You are Mio, the user's study companion" in system_prompts(llm)[-1]

    client.put("/api/companion", json={"name": "  Aiko  "})
    ask(client, collection, "What do mitochondria produce?")
    assert "You are Aiko" in system_prompts(llm)[-1]

    assert client.put("/api/companion", json={"enabled": False}).json()["enabled"] is False
    ask(client, collection, "What do mitochondria produce?")
    assert "study companion" not in system_prompts(llm)[-1]


def test_a_greeting_gets_a_greeting_not_a_search(client, collection):
    llm = client.app.state.services.llm
    _, text, cited, events = ask(client, collection, "hey")
    assert cited == [] and events[-1][0] == "done" and text
    assert "said hello or made small talk" in system_prompts(llm)[-1]

    upload(client, collection, "cells.txt", (CELLS * 5).encode())
    ask(client, collection, "thank you")
    assert "small talk" in system_prompts(llm)[-1]
    # Short, but its words are in the material: that is a search.
    _, _, cited, _ = ask(client, collection, "cristae surface area")
    assert cited and "small talk" not in system_prompts(llm)[-1]


def test_without_the_companion_a_greeting_is_treated_as_before(client, collection):
    client.put("/api/companion", json={"enabled": False})
    llm = client.app.state.services.llm
    _, text, _, _ = ask(client, collection, "hey")
    assert "nothing to search yet" in text and llm.calls == []


def test_memories_can_be_added_edited_and_cleared(client):
    first = client.post("/api/memories", json={"content": "  My name is   Arjun. "}).json()
    assert first["content"] == "My name is Arjun."
    assert client.post("/api/memories", json={"content": "my name is arjun"}).status_code == 400  # known already
    assert client.post("/api/memories", json={"content": " "}).status_code == 400
    assert client.post("/api/memories", json={"content": "x" * 300}).status_code == 400
    client.post("/api/memories", json={"content": "Exam on 12 June."})
    edited = client.put(f"/api/memories/{first['id']}", json={"content": "My name is Arjun Rao."}).json()
    assert edited["content"] == "My name is Arjun Rao."
    assert [m["content"] for m in client.get("/api/memories").json()] == ["My name is Arjun Rao.", "Exam on 12 June."]
    client.delete(f"/api/memories/{first['id']}")
    assert len(client.get("/api/memories").json()) == 1
    client.delete("/api/memories")
    assert client.get("/api/memories").json() == []


def test_what_is_remembered_reaches_the_prompt_only_while_memory_is_on(client, collection):
    upload(client, collection, "cells.txt", (CELLS * 5).encode())
    client.post("/api/memories", json={"content": "The student's name is Arjun."})
    llm = client.app.state.services.llm
    ask(client, collection, "What do mitochondria produce?")
    assert "The student's name is Arjun." in system_prompts(llm)[-1]
    client.put("/api/companion", json={"memory": False})
    ask(client, collection, "What do mitochondria produce?")
    assert "Arjun" not in system_prompts(llm)[-1]


def test_only_the_newest_memories_are_kept(client):
    for n in range(MAX_MEMORIES + 5):
        Memory.remember(f"Fact number {n}.")
    lines = Memory.lines()
    assert len(lines) == MAX_MEMORIES and lines[-1] == f"Fact number {MAX_MEMORIES + 4}."


def learn_with(client, reply: dict, message: str) -> list[str]:
    services = client.app.state.services
    services.llm = FakeLLM(lambda messages, schema, images: json.dumps(reply))
    return companion.learn(message, services)


def test_learning_keeps_facts_the_user_said_and_drops_the_rest(client):
    message = "hi, I'm Priya and my biology final is on 12 June"
    reply = {"facts": ["The student's name is Priya.", "The student has a biology final on 12 June."]}
    assert learn_with(client, reply, message) == reply["facts"]
    assert learn_with(client, reply, message) == []  # nothing is stored twice
    # What was asked is not a fact about the user.
    asked = {"facts": ["The student asked about mitosis."]}
    assert learn_with(client, asked, "What is mitosis and why does it matter?") == []
    # Nor is something the user never said.
    invented = {"facts": ["The student lives in Paris."]}
    assert learn_with(client, invented, "Please explain photosynthesis to me") == []
    assert learn_with(client, reply, "ok") == []  # too short to say anything
    assert len(Memory.lines()) == 2


def test_learning_stops_when_memory_is_off(client):
    config.set_many({"memory": False})
    reply = {"facts": ["The student's name is Priya."]}
    assert learn_with(client, reply, "hi, I'm Priya and I study biology") == []
    assert client.app.state.services.llm.calls == []


def test_pictures_built_in_and_replaced_by_the_users_own(client):
    state = client.get("/api/companion").json()
    assert state == {**state, "enabled": True, "name": "Mio", "memory": True, "own_pictures": False}
    for mood in ("neutral", "happy", "thinking", "sad"):
        response = client.get(f"/api/companion/face/{mood}")
        assert response.status_code == 200 and response.headers["content-type"].startswith("image/svg")
    assert client.get("/api/companion/face/angry").status_code == 404

    folder = config.data_dir() / "companion"
    folder.mkdir()
    (folder / "neutral.png").write_bytes(b"\x89PNG own picture")
    assert client.get("/api/companion").json()["own_pictures"] is True
    # One picture of the user's own is used for every mood.
    assert client.get("/api/companion/face/happy").content == b"\x89PNG own picture"


def test_the_name_must_be_usable(client):
    assert client.put("/api/companion", json={"name": "  "}).status_code == 400
    assert client.put("/api/companion", json={"name": "x" * 40}).status_code == 400


def test_the_smallest_local_model_answers_plainly_but_still_greets(client, collection):
    upload(client, collection, "cells.txt", (CELLS * 5).encode())
    config.set_many({"provider": "local", "tier": "lite"})
    llm = client.app.state.services.llm
    ask(client, collection, "What do mitochondria produce?")
    assert "study companion" not in system_prompts(llm)[-1]
    ask(client, collection, "hello")
    assert "small talk" in system_prompts(llm)[-1]


def test_a_message_that_does_not_mention_its_writer_is_not_read_for_facts(client):
    reply = {"facts": ["The student studies glycolysis."]}
    assert learn_with(client, reply, "Where does glycolysis happen and what does it make?") == []
    assert client.app.state.services.llm.calls == []  # the model was not even asked
    # A fact that is about the subject, not the student, is dropped.
    subject = {"facts": ["Glycolysis happens in the cytoplasm."]}
    assert learn_with(client, subject, "I think glycolysis happens in the cytoplasm") == []
    assert learn_with(client, {"facts": ["The student's name is Claire."]}, "Je m'appelle Claire") == [
        "The student's name is Claire."
    ]
