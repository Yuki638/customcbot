"""The layers under the routes: migrations, domain models, commands, prompt templates."""

from __future__ import annotations

import sqlite3

import pytest

from customcbot.commands import registry
from customcbot.commands.registry import command, command_names, get_command
from customcbot.database import migrate
from customcbot.database.repository import init_database, repo_execute, repo_one
from customcbot.domain import Collection, RecordModel, Source
from customcbot.exceptions import InvalidInputError, NotFoundError
from customcbot.utils.prompter import load_json, render

from .conftest import wait

# -- migrations ---------------------------------------------------------------


def test_a_new_database_is_brought_to_the_latest_version(tmp_path):
    init_database(tmp_path / "new.db")
    latest = max(number for number, _ in migrate.pending(0))
    assert repo_one("PRAGMA user_version")["user_version"] == latest
    assert repo_one("SELECT name FROM sqlite_master WHERE name = 'collections'")


def test_a_data_folder_from_before_migrations_keeps_its_data(tmp_path):
    # A database made by the first release: tables exist, version is still 0.
    path = tmp_path / "old.db"
    old = sqlite3.connect(path)
    old.executescript((migrate.MIGRATIONS_DIR / "001_initial.sql").read_text(encoding="utf-8"))
    old.execute("INSERT INTO collections (name) VALUES ('Biology 101')")
    old.execute(
        "INSERT INTO sources (collection_id, kind, title, status) VALUES (1, 'text', 'Notes', 'ready')"
    )
    old.commit()
    assert old.execute("PRAGMA user_version").fetchone()[0] == 0
    old.close()

    init_database(path)
    assert Collection.get(1).name == "Biology 101"
    assert Source.get(1).title == "Notes"
    assert repo_one("PRAGMA user_version")["user_version"] >= 1


def test_migrations_run_once_and_in_order(tmp_path, monkeypatch):
    folder = tmp_path / "migrations"
    folder.mkdir()
    (folder / "001_first.sql").write_text("CREATE TABLE a (n INTEGER); INSERT INTO a VALUES (1);")
    (folder / "002_second.sql").write_text("INSERT INTO a VALUES (2);")
    monkeypatch.setattr(migrate, "MIGRATIONS_DIR", folder)
    conn = sqlite3.connect(tmp_path / "m.db")
    assert migrate.run_migrations(conn) == 2
    assert migrate.run_migrations(conn) == 2  # nothing left to do
    assert [row[0] for row in conn.execute("SELECT n FROM a ORDER BY rowid")] == [1, 2]


# -- domain models ------------------------------------------------------------


def test_objects_save_update_and_delete(services, client):
    collection = Collection(name="History").save()
    assert collection.id and collection.created_at
    collection.update(name="Roman history")
    assert Collection.get(collection.id).name == "Roman history"
    assert [c.name for c in Collection.where("name LIKE ?", ("Roman%",))] == ["Roman history"]
    collection.delete()
    assert Collection.find(collection.id) is None
    with pytest.raises(NotFoundError, match="That collection no longer exists."):
        Collection.get(collection.id)


def test_update_writes_only_the_named_fields(services, client):
    collection = Collection(name="Physics").save()
    source = Source(collection_id=collection.id, kind="text", title="Waves").save()
    stale = Source.get(source.id)
    repo_execute("UPDATE sources SET stage = 'Reading page 3' WHERE id = ?", (source.id,))
    stale.update(title="Waves and optics")  # must not put the old stage back
    fresh = Source.get(source.id)
    assert (fresh.title, fresh.stage) == ("Waves and optics", "Reading page 3")


def test_a_blank_collection_name_is_refused(client):
    with pytest.raises(InvalidInputError):
        Collection.clean_name("   ")
    reply = client.post("/api/collections", json={"name": "  "})
    assert (reply.status_code, reply.json()["detail"]) == (400, "Give the collection a name.")


def test_a_settings_record_is_stored_once(services, client):
    class Preferences(RecordModel):
        record_id = "test:preferences"
        language: str = "en"

    assert Preferences.load().language == "en"
    Preferences(language="fr").save()
    Preferences(language="hi").save()
    assert Preferences.load().language == "hi"
    assert repo_one("SELECT COUNT(*) AS n FROM settings WHERE key = 'test:preferences'")["n"] == 1


# -- commands -----------------------------------------------------------------


def test_the_app_registers_its_commands():
    assert {"process_source", "quiz", "flashcards", "summary_source", "summary_collection"} <= set(
        command_names()
    )


def test_reading_a_source_is_a_command_with_a_job(client, collection):
    client.post(f"/api/collections/{collection}/sources/text", json={"title": "Cells", "text": "Cells divide."})
    wait(client)
    job = repo_one("SELECT * FROM jobs WHERE kind = 'process_source'")
    assert job["status"] == "done"
    assert client.get(f"/api/commands/jobs/{job['id']}").json()["result"] == {"source_id": 1}
    assert client.get(f"/api/jobs/{job['id']}").json()["status"] == "done"


@pytest.fixture
def scratch_commands(monkeypatch):
    monkeypatch.setattr(registry, "_commands", dict(registry._commands))


def test_a_command_is_retried_until_it_works(client, collection, scratch_commands):
    calls = []

    @command("test_flaky", max_attempts=3)
    def flaky(job, params, services, context):
        calls.append(1)
        if len(calls) < 3:
            raise RuntimeError("try again")
        return {"attempts": len(calls)}

    job_id = client.app.state.services.worker.submit_job("test_flaky", collection, {})
    wait(client)
    job = client.get(f"/api/jobs/{job_id}").json()
    assert (job["status"], job["result"]) == ("done", {"attempts": 3})


def test_a_command_stops_at_once_on_an_error_a_retry_cannot_fix(client, collection, scratch_commands):
    calls = []

    @command("test_hopeless", max_attempts=5, stop_on=(ValueError,))
    def hopeless(job, params, services, context):
        calls.append(1)
        raise ValueError("Add some material first.")

    job_id = client.app.state.services.worker.submit_job("test_hopeless", collection, {})
    wait(client)
    job = client.get(f"/api/jobs/{job_id}").json()
    assert (job["status"], job["error"], len(calls)) == ("error", "Add some material first.", 1)


def test_work_left_from_a_version_without_source_jobs_is_picked_up(services, client, collection):
    worker = services.worker
    worker.stop()
    source = Source(collection_id=collection, kind="text", title="Left over", status="queued").save()
    folder = source.folder()
    folder.mkdir(parents=True)
    (folder / "pasted.txt").write_text("Mitochondria make ATP.", encoding="utf-8")
    source.update(file_path=f"{source.id}/pasted.txt")
    assert repo_one("SELECT COUNT(*) AS n FROM jobs")["n"] == 0
    worker.start()
    worker.wait_idle()
    assert Source.get(source.id).status == "ready"


def test_an_unknown_command_is_refused(client, collection):
    from customcbot.api import command_service

    with pytest.raises(InvalidInputError):
        command_service.submit_command_job(client.app.state.services.worker, "no_such_thing", collection, {})
    assert get_command("no_such_thing") is None


# -- prompt templates ---------------------------------------------------------


def test_templates_render_and_fill_in_values():
    assert render("chat/grounded_system").startswith("You are a patient tutor.")
    assert render("common/json_instruction", schema='{"a": 1}').endswith('{"a": 1}')
    examples = load_json("chat/condense_examples")
    assert examples and {"conversation", "reply"} <= set(examples[0])


def test_a_template_with_a_missing_value_fails_loudly():
    from jinja2 import UndefinedError

    with pytest.raises(UndefinedError):
        render("common/json_instruction")
