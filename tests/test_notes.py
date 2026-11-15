"""Notes, transformations and insights."""

from __future__ import annotations

import sqlite3

from customcbot.database import migrate, search
from customcbot.database.repository import init_database, repo_one
from customcbot.domain import Note, SourceInsight, Transformation
from customcbot.utils import indexing

from .conftest import wait
from .helpers import ask
from .test_api import CELLS, ROME, run_job, sources, upload

# -- notes -------------------------------------------------------------------


def test_notes_are_written_listed_changed_and_removed(client, collection):
    made = client.post(
        f"/api/collections/{collection}/notes", json={"content": "# Mitosis\nThe cell divides in four phases."}
    ).json()
    assert made["title"] == "Mitosis" and made["note_type"] == "human"  # named after its first line
    client.post(f"/api/collections/{collection}/notes", json={"title": "Exam date", "content": "12 June"})
    listed = client.get(f"/api/collections/{collection}/notes").json()
    assert {n["title"] for n in listed} == {"Mitosis", "Exam date"}
    assert all("content" not in n and n["preview"] for n in listed)

    changed = client.put(f"/api/notes/{made['id']}", json={"title": "Mitosis", "content": "Five phases, not four."})
    assert changed.json()["content"] == "Five phases, not four."
    assert client.get(f"/api/notes/{made['id']}").json()["content"] == "Five phases, not four."
    assert client.delete(f"/api/notes/{made['id']}").json() == {"ok": True}
    assert client.get(f"/api/notes/{made['id']}").status_code == 404
    assert repo_one("SELECT COUNT(*) AS n FROM chunks WHERE note_id = ?", (made["id"],))["n"] == 0


def test_an_empty_note_is_refused(client, collection):
    reply = client.post(f"/api/collections/{collection}/notes", json={"title": " ", "content": "  "})
    assert reply.status_code == 400 and reply.json()["detail"] == "Write something in the note first."
    assert client.post("/api/collections/999/notes", json={"content": "x"}).status_code == 404


def test_chat_finds_a_note_and_cites_it_as_one(client, collection):
    upload(client, collection, "rome.txt", (ROME * 3).encode())
    client.post(
        f"/api/collections/{collection}/notes",
        json={"title": "Lab safety", "content": "Always wear goggles when heating copper sulphate crystals."},
    )
    _, _, cited, _ = ask(client, collection, "What should I wear when heating copper sulphate?")
    note = next(c for c in cited if c["kind"] == "note")
    assert note["label"] == "Your note: Lab safety" and note["source_id"] is None and note["note_id"]
    assert "goggles" in note["text"]
    # The model is told where the passage comes from.
    prompt = client.app.state.services.llm.calls[-1]["messages"][-1]["content"]
    assert "Your note: Lab safety" in prompt


def test_ticking_sources_leaves_notes_out(client, collection):
    upload(client, collection, "rome.txt", (ROME * 3).encode())
    rome = sources(client, collection)[0]
    client.post(
        f"/api/collections/{collection}/notes", json={"title": "Lab safety", "content": "Always wear goggles."}
    )
    _, _, cited, _ = ask(client, collection, "What about goggles?", source_ids=[rome["id"]])
    assert cited and all(c["kind"] != "note" for c in cited)


def test_a_changed_note_is_searched_by_its_new_text(client, collection):
    embedder = client.app.state.services.embedder
    made = client.post(
        f"/api/collections/{collection}/notes", json={"title": "Plants", "content": "Chlorophyll absorbs light."}
    ).json()
    assert search.search(collection, "chlorophyll", embedder)[0]["note_id"] == made["id"]
    client.put(f"/api/notes/{made['id']}", json={"title": "Plants", "content": "Stomata let gases in and out."})
    assert "Stomata" in search.search(collection, "stomata gases", embedder)[0]["text"]
    assert not any("Chlorophyll" in p["text"] for p in search.search(collection, "chlorophyll light", embedder))


# -- transformations ---------------------------------------------------------


def test_the_built_in_tasks_are_there(client):
    listed = client.get("/api/transformations").json()
    assert [t["title"] for t in listed] == [
        "Study guide", "Key points", "Glossary", "Revision questions", "Explain it simply",
    ]  # fmt: skip
    assert all(t["builtin"] and not t["changed"] and t["prompt"] for t in listed)
    assert not any(t["apply_default"] for t in listed)  # nothing runs by itself unless asked


def test_own_tasks_can_be_added_changed_and_removed(client):
    body = {"title": "Timeline", "prompt": "List every date in order with what happened."}
    listed = client.post("/api/transformations", json=body).json()
    own = next(t for t in listed if t["title"] == "Timeline")
    assert own["builtin"] is False
    client.put(f"/api/transformations/{own['id']}", json={**body, "title": "Dates", "apply_default": True})
    assert Transformation.get(own["id"]).title == "Dates" and Transformation.get(own["id"]).apply_default
    assert client.post("/api/transformations", json={"title": "Empty", "prompt": " "}).status_code == 400
    client.delete(f"/api/transformations/{own['id']}")
    assert Transformation.find(own["id"]) is None


def test_a_built_in_task_can_be_reworded_and_put_back(client):
    key_points = next(t for t in client.get("/api/transformations").json() if t["title"] == "Key points")
    original = key_points["prompt"]
    # Saving it unchanged keeps it tied to the built-in wording.
    client.put(f"/api/transformations/{key_points['id']}", json={"title": "Key points", "prompt": original})
    assert Transformation.get(key_points["id"]).prompt is None
    listed = client.put(
        f"/api/transformations/{key_points['id']}", json={"title": "Key points", "prompt": "Five bullets only."}
    ).json()
    assert next(t for t in listed if t["id"] == key_points["id"])["changed"] is True
    listed = client.post(f"/api/transformations/{key_points['id']}/reset").json()
    restored = next(t for t in listed if t["id"] == key_points["id"])
    assert restored["prompt"] == original and restored["changed"] is False
    refused = client.delete(f"/api/transformations/{key_points['id']}")
    assert refused.status_code == 400 and "cannot be removed" in refused.json()["detail"]


# -- insights ----------------------------------------------------------------


def task(client, title: str) -> int:
    return next(t["id"] for t in client.get("/api/transformations").json() if t["title"] == title)


def test_a_task_is_carried_out_on_a_source(client, collection):
    upload(client, collection, "cells.txt", (CELLS * 3).encode())
    cells = sources(client, collection)[0]
    llm = client.app.state.services.llm
    llm.calls.clear()
    job = run_job(client, client.post(f"/api/sources/{cells['id']}/insights", json={"transformation_id": task(client, "Glossary")}))
    assert job["kind"] == "run_transformation" and job["result"]["source_id"] == cells["id"]

    insights = client.get(f"/api/sources/{cells['id']}/insights").json()
    assert [i["insight_type"] for i in insights] == ["Glossary"] and insights[0]["content"]
    system, user = (m["content"] for m in llm.calls[-1]["messages"])
    assert "Task: List the important terms" in system and "using only what the material says" in system
    assert user.startswith('Material from "cells":') and "Mitochondria" in user

    # Doing it again replaces the earlier result instead of piling up.
    run_job(client, client.post(f"/api/sources/{cells['id']}/insights", json={"transformation_id": task(client, "Glossary")}))
    assert len(client.get(f"/api/sources/{cells['id']}/insights").json()) == 1
    assert len(client.get(f"/api/collections/{collection}/insights").json()) == 1


def test_a_long_source_is_reduced_to_notes_first(client, collection):
    upload(client, collection, "cells.txt", (CELLS * 60).encode())  # several prompts long
    cells = sources(client, collection)[0]
    llm = client.app.state.services.llm
    llm.calls.clear()
    run_job(client, client.post(f"/api/sources/{cells['id']}/insights", json={"transformation_id": task(client, "Key points")}))
    assert len(llm.calls) > 2  # one call per part, then the task itself
    assert llm.calls[-1]["messages"][-1]["content"].startswith('Notes taken from "cells"')


def test_an_opening_line_that_only_announces_the_result_is_removed():
    from customcbot.graphs.transformation import tidy

    assert tidy("Here’s a list of the most important points:\n\n* ATP stores energy.") == "* ATP stores energy."
    assert tidy("Sure! Here is the glossary.\n**ATP**: energy carrier.") == "**ATP**: energy carrier."
    assert tidy("Okay, here are eight questions:\n1. What is ATP?") == "1. What is ATP?"
    # Real content that happens to start with such a word is left alone.
    assert tidy("Here the cell divides into two.\nThen it rests.") == "Here the cell divides into two.\nThen it rests."
    assert tidy("## Overview\nHere is what matters: energy.") == "## Overview\nHere is what matters: energy."


def test_a_reworded_task_uses_the_new_wording(client, collection):
    upload(client, collection, "cells.txt", (CELLS * 3).encode())
    cells = sources(client, collection)[0]
    key_points = task(client, "Key points")
    client.put(f"/api/transformations/{key_points}", json={"title": "Key points", "prompt": "Write one haiku."})
    llm = client.app.state.services.llm
    run_job(client, client.post(f"/api/sources/{cells['id']}/insights", json={"transformation_id": key_points}))
    assert "Task: Write one haiku." in llm.calls[-1]["messages"][0]["content"]


def test_insights_are_searchable_but_chat_cites_the_source_itself(client, collection):
    upload(client, collection, "cells.txt", (CELLS * 3).encode())
    cells = sources(client, collection)[0]
    run_job(client, client.post(f"/api/sources/{cells['id']}/insights", json={"transformation_id": task(client, "Glossary")}))
    embedder = client.app.state.services.embedder
    everything = search.search(collection, "placeholder answer", embedder, kinds=(search.INSIGHT,))
    assert everything and everything[0]["kind"] == "insight" and everything[0]["source_id"] == cells["id"]
    _, _, cited, _ = ask(client, collection, "What do mitochondria produce?")
    assert cited and all(c["kind"] == "text" for c in cited)


def test_an_insight_can_be_saved_as_a_note_and_removed(client, collection):
    upload(client, collection, "cells.txt", (CELLS * 3).encode())
    cells = sources(client, collection)[0]
    run_job(client, client.post(f"/api/sources/{cells['id']}/insights", json={"transformation_id": task(client, "Glossary")}))
    insight = client.get(f"/api/sources/{cells['id']}/insights").json()[0]
    note = client.post(f"/api/insights/{insight['id']}/save-as-note").json()
    assert note["title"] == "Glossary: cells" and note["note_type"] == "ai" and note["content"] == insight["content"]
    assert client.delete(f"/api/insights/{insight['id']}").json() == {"ok": True}
    assert client.get(f"/api/sources/{cells['id']}/insights").json() == []
    assert Note.get(note["id"]).content  # the note stays


def test_a_task_marked_for_every_new_source_runs_by_itself(client, collection):
    glossary = task(client, "Glossary")
    client.put(
        f"/api/transformations/{glossary}",
        json={"title": "Glossary", "prompt": Transformation.get(glossary).instruction(), "apply_default": True},
    )
    upload(client, collection, "rome.txt", (ROME * 3).encode())
    wait(client)
    rome = sources(client, collection)[0]
    assert [i["insight_type"] for i in client.get(f"/api/sources/{rome['id']}/insights").json()] == ["Glossary"]


def test_a_study_guide_from_the_summary_tab_is_kept_as_an_insight(client, collection):
    upload(client, collection, "cells.txt", (CELLS * 3).encode())
    cells = sources(client, collection)[0]
    run_job(client, client.post(f"/api/collections/{collection}/summary", json={"source_id": cells["id"]}))
    guide = client.get(f"/api/sources/{cells['id']}/insights").json()
    summary = client.get(f"/api/collections/{collection}/summary").json()["sources"][0]["summary"]
    assert [i["insight_type"] for i in guide] == ["Study guide"] and guide[0]["content"] == summary


def test_removing_a_source_removes_its_insights(client, collection):
    upload(client, collection, "cells.txt", (CELLS * 3).encode())
    cells = sources(client, collection)[0]
    run_job(client, client.post(f"/api/sources/{cells['id']}/insights", json={"transformation_id": task(client, "Glossary")}))
    client.delete(f"/api/sources/{cells['id']}")
    assert SourceInsight.where() == []
    assert repo_one("SELECT COUNT(*) AS n FROM chunks")["n"] == 0


def test_a_source_that_is_not_ready_cannot_be_worked_on(client, collection):
    from customcbot.domain import Source

    waiting = Source(collection_id=collection, kind="text", title="Later", status="queued").save()
    reply = client.post(f"/api/sources/{waiting.id}/insights", json={"transformation_id": task(client, "Glossary")})
    assert reply.status_code == 400 and "not ready yet" in reply.json()["detail"]


# -- upgrading ---------------------------------------------------------------


def test_study_guides_from_an_earlier_version_become_searchable_insights(tmp_path, monkeypatch, services):
    monkeypatch.setenv("CUSTOMCBOT_DATA_DIR", str(tmp_path))
    path = tmp_path / "customcbot.db"
    old = sqlite3.connect(path)
    for name in ("001_initial.sql", "002_credentials_and_models.sql"):
        old.executescript((migrate.MIGRATIONS_DIR / name).read_text(encoding="utf-8"))
    old.execute("PRAGMA user_version = 3")
    old.execute("INSERT INTO collections (name) VALUES ('Biology')")
    old.execute(
        "INSERT INTO sources (collection_id, kind, title, status, summary) "
        "VALUES (1, 'text', 'Cells', 'ready', '## Overview\nMitochondria make ATP.')"
    )
    old.execute("INSERT INTO chunks (source_id, collection_id, ord, text) VALUES (1, 1, 0, 'Mitochondria make ATP.')")
    old.commit()
    old.close()

    init_database(path)
    insight = SourceInsight.where()[0]
    assert (insight.insight_type, insight.source_id) == ("Study guide", 1)
    # The passages kept their ids and are still found by their words.
    assert repo_one("SELECT id, source_id FROM chunks WHERE text LIKE 'Mitochondria%'") == {"id": 1, "source_id": 1}
    assert repo_one("SELECT COUNT(*) AS n FROM chunks_fts WHERE chunks_fts MATCH 'mitochondria'")["n"] == 1
    assert indexing.index_missing(services.embedder) == 1
    assert repo_one("SELECT COUNT(*) AS n FROM chunks WHERE insight_id = ?", (insight.id,))["n"] == 1
    assert indexing.index_missing(services.embedder) == 0
