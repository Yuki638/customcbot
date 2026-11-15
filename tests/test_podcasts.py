"""Podcasts: profiles, the episode workflow, and the audio file."""

from __future__ import annotations

import json

import numpy as np

from customcbot import config
from customcbot.ai.fake import FakeLLM, default_responder
from customcbot.domain import PodcastEpisode
from customcbot.domain.podcast import Speaker
from customcbot.ingest.media import decode_audio
from customcbot.podcasts import audio, voices
from customcbot.podcasts.generate import Line, _assign, spoken
from customcbot.podcasts.speech import SAMPLE_RATE, FakeSpeech

from .conftest import wait
from .test_api import CELLS, ROME, run_job, sources, upload

SCRIPT = [
    {"speaker": "Maya", "text": "Welcome! Today: **mitochondria** [1]."},
    {"speaker": "Daniel", "text": "What do they make?"},
    {"speaker": "Somebody else", "text": "They make ATP."},
]


def scripted() -> FakeLLM:
    """A stand-in model that plans two parts and writes the same three lines for each."""

    def respond(messages, schema, images):
        fields = (schema or {}).get("properties", {})
        if "segments" in fields:
            parts = [{"title": f"Part {n}", "points": ["Mitochondria make ATP."]} for n in (1, 2, 3)]
            return json.dumps({"title": "Powerhouses of the cell", "segments": parts})
        if "lines" in fields:
            return json.dumps({"lines": SCRIPT})
        return default_responder(messages, schema, images)

    return FakeLLM(responder=respond)


def profile(client, name: str) -> dict:
    return next(p for p in client.get("/api/episode-profiles").json() if p["name"] == name)


# -- profiles ----------------------------------------------------------------


def test_ready_made_profiles_and_voices(client):
    assert [p["name"] for p in client.get("/api/episode-profiles").json()] == ["Study recap", "Quick overview", "Exam drill"]
    speakers = client.get("/api/speaker-profiles").json()
    assert [len(p["speakers"]) for p in speakers] == [2, 1, 2]
    offered = client.get("/api/podcast-voices").json()
    assert offered[0] == {"id": "af_heart", "label": "Heart (American English, female)", "language": "American English"}
    # Every ready-made speaker uses a voice that is on offer.
    assert {s["voice"] for p in speakers for s in p["speakers"]} <= {v["id"] for v in offered}
    assert voices.language_code("bm_george") == "en-gb" and voices.language_code("hf_alpha") == "hi"


def test_own_profiles_can_be_added_changed_and_removed(client):
    body = {"name": "Trio", "speakers": [
        {"name": "Ana", "voice": "ef_dora", "role": "explains"},
        {"name": "Luis", "voice": "em_alex", "role": "asks"},
        {"name": "Eva", "voice": "af_bella", "role": "sums up"},
    ]}  # fmt: skip
    trio = next(p for p in client.post("/api/speaker-profiles", json=body).json() if p["name"] == "Trio")
    assert [s["name"] for s in trio["speakers"]] == ["Ana", "Luis", "Eva"]
    kind = {"name": "Spanish chat", "speaker_profile_id": trio["id"], "briefing": "A relaxed chat.", "segments": 9}
    made = next(p for p in client.post("/api/episode-profiles", json=kind).json() if p["name"] == "Spanish chat")
    assert made["segments"] == 6  # held to a sensible length
    client.put(f"/api/episode-profiles/{made['id']}", json={**kind, "segments": 2})
    assert profile(client, "Spanish chat")["segments"] == 2
    client.delete(f"/api/speaker-profiles/{trio['id']}")
    assert profile(client, "Spanish chat")["speaker_profile_id"] is None  # the episode kind survives
    client.delete(f"/api/episode-profiles/{made['id']}")
    assert len(client.get("/api/episode-profiles").json()) == 3


def test_bad_profiles_are_refused(client):
    def refused(speakers, name="X"):
        reply = client.post("/api/speaker-profiles", json={"name": name, "speakers": speakers})
        assert reply.status_code == 400
        return reply.json()["detail"]

    assert refused([]) == "Use between one and 4 speakers."
    assert refused([{"name": "A", "voice": "no_such_voice"}]) == "Choose a voice for A."
    assert refused([{"name": "A", "voice": "af_heart"}, {"name": "a", "voice": "am_adam"}]) == "Give each speaker a different name."
    assert refused([{"name": "A", "voice": "af_heart"}], name=" ") == "Give this set of voices a name."
    blank = {"name": "K", "speaker_profile_id": 1, "briefing": " "}
    assert client.post("/api/episode-profiles", json=blank).json()["detail"] == "Describe what the episode should be like."


# -- making an episode -------------------------------------------------------


def test_an_episode_is_planned_written_recorded_and_saved(client, collection):
    upload(client, collection, "cells.txt", (CELLS * 3).encode())
    services = client.app.state.services
    services.llm = scripted()
    job = run_job(client, client.post(
        f"/api/collections/{collection}/podcasts",
        json={"episode_profile_id": profile(client, "Study recap")["id"], "briefing": "Keep it light."},
    ))
    assert job["kind"] == "generate_podcast"
    episode = client.get(f"/api/podcasts/{job['result']['episode_id']}").json()
    assert (episode["status"], episode["title"], episode["has_audio"]) == ("ready", "Powerhouses of the cell", True)
    assert "audio_path" not in episode and episode["briefing"].endswith("Keep it light.")

    # Three parts, three lines each; an unknown speaker name is given one of the profile's speakers.
    assert len(episode["transcript"]) == 9
    assert {line["speaker"] for line in episode["transcript"]} == {"Maya", "Daniel"}
    assert episode["transcript"][0]["text"] == "Welcome! Today: mitochondria ."  # nothing unspeakable left
    # Each speaker was recorded in their own voice.
    assert {voice for voice, _ in services.speech.said} == {"af_heart", "am_michael"}
    assert ("am_michael", "What do they make?") in services.speech.said

    # The script prompts carry the speakers, the part and its place in the episode.
    first_system = services.llm.calls[1]["messages"][0]["content"]
    last_system = services.llm.calls[3]["messages"][0]["content"]
    assert "- Maya, a friendly tutor who explains things clearly" in first_system
    assert "Begin by welcoming the listener" in first_system and "Do not say goodbye" in first_system
    assert "End with a short recap and a goodbye." in last_system and "Do not greet the listener again" in last_system
    assert 'The part before ended with: "They make ATP."' in services.llm.calls[2]["messages"][1]["content"]

    # The audio is a real MP3 of the right length.
    reply = client.get(f"/api/podcasts/{episode['id']}/audio")
    assert reply.status_code == 200 and reply.headers["content-type"] == "audio/mpeg"
    path = config.podcasts_dir() / f"{episode['id']}.mp3"
    assert path.read_bytes() == reply.content
    assert abs(len(decode_audio(path)) / 16000 - episode["duration_sec"]) < 0.5
    download = client.get(f"/api/podcasts/{episode['id']}/audio?download=true")
    saved_as = download.headers["content-disposition"]
    assert saved_as.startswith("attachment") and "Powerhouses%20of%20the%20cell.mp3" in saved_as
    assert [e["status"] for e in client.get(f"/api/collections/{collection}/podcasts").json()] == ["ready"]


def test_one_narrator_and_chosen_sources(client, collection):
    upload(client, collection, "cells.txt", (CELLS * 3).encode())
    upload(client, collection, "rome.txt", (ROME * 3).encode())
    rome = next(s for s in sources(client, collection) if s["title"] == "rome")
    services = client.app.state.services
    services.llm = scripted()
    job = run_job(client, client.post(
        f"/api/collections/{collection}/podcasts",
        json={"episode_profile_id": profile(client, "Quick overview")["id"], "source_ids": [rome["id"]]},
    ))
    episode = client.get(f"/api/podcasts/{job['result']['episode_id']}").json()
    assert {line["speaker"] for line in episode["transcript"]} == {"Maya"} and len(episode["transcript"]) == 6
    outline_prompt = services.llm.calls[0]["messages"][1]["content"]
    assert "Roman Republic" in outline_prompt and "Mitochondria" not in outline_prompt
    assert "It is spoken by one person: Maya" in services.llm.calls[1]["messages"][0]["content"]


def test_a_failed_episode_says_why_and_can_be_removed(client, collection):
    upload(client, collection, "cells.txt", (CELLS * 3).encode())

    class Broken(FakeSpeech):
        def say(self, text, voice):
            raise RuntimeError("The voices could not be set up. Check your internet connection and try again.")

    services = client.app.state.services
    services.llm, services.speech = scripted(), Broken()
    reply = client.post(f"/api/collections/{collection}/podcasts", json={"episode_profile_id": 1})
    wait(client)
    job = client.get(f"/api/jobs/{reply.json()['id']}").json()
    assert job["status"] == "error" and job["error"].startswith("The voices could not be set up.")
    listed = client.get(f"/api/collections/{collection}/podcasts").json()[0]
    assert listed["status"] == "error" and listed["error"] == job["error"]
    assert client.get(f"/api/podcasts/{listed['id']}/audio").status_code == 404
    client.delete(f"/api/podcasts/{listed['id']}")
    assert client.get(f"/api/collections/{collection}/podcasts").json() == []


def test_an_empty_collection_cannot_make_an_episode(client, collection):
    reply = client.post(f"/api/collections/{collection}/podcasts", json={"episode_profile_id": 1})
    wait(client)
    assert client.get(f"/api/jobs/{reply.json()['id']}").json()["error"] == "Add some material first."
    assert client.post(f"/api/collections/{collection}/podcasts", json={"episode_profile_id": 99}).status_code == 404


def test_removing_an_episode_or_its_collection_removes_the_audio(client, collection):
    upload(client, collection, "cells.txt", (CELLS * 3).encode())
    client.app.state.services.llm = scripted()
    ids = []
    for _ in range(2):
        job = run_job(client, client.post(f"/api/collections/{collection}/podcasts", json={"episode_profile_id": 2}))
        ids.append(job["result"]["episode_id"])
    files = [config.podcasts_dir() / f"{n}.mp3" for n in ids]
    assert all(f.is_file() for f in files)
    client.delete(f"/api/podcasts/{ids[0]}")
    assert not files[0].exists() and files[1].is_file()
    client.delete(f"/api/collections/{collection}")
    assert not files[1].exists() and PodcastEpisode.where() == []


# -- the pieces --------------------------------------------------------------


def test_text_is_made_speakable():
    assert spoken("ATP is made in the **mitochondria** [2, 3].") == "ATP is made in the mitochondria ."
    assert spoken("# Heading\n- a `list` item") == "Heading - a list item"


def test_lines_get_a_speaker_even_when_the_model_invents_names():
    speakers = [Speaker(name="Maya", voice="af_heart"), Speaker(name="Daniel", voice="am_michael")]
    lines = [Line(speaker="maya ", text="Hi."), Line(speaker="Host 2", text="Hello."), Line(speaker="Daniel", text="**")]
    assert _assign(lines, speakers) == [
        {"speaker": "Maya", "voice": "af_heart", "text": "Hi."},
        {"speaker": "Daniel", "voice": "am_michael", "text": "Hello."},
    ]


def test_a_stray_quote_mark_and_a_repeated_line_are_removed():
    assert spoken("So, oxygen is essential?\u201d") == "So, oxygen is essential?"
    assert spoken("She said \u201chello\u201d to me.") == "She said \u201chello\u201d to me."
    speakers = [Speaker(name="Maya", voice="af_heart")]
    lines = [Line(speaker="Maya", text="That is a huge difference."), Line(speaker="Maya", text="Next: glycolysis."),
             Line(speaker="Maya", text="Next: glycolysis.")]
    kept = _assign(lines, speakers, previous="That is a huge difference.")
    assert [line["text"] for line in kept] == ["Next: glycolysis."]


def test_lines_are_joined_with_pauses_and_never_clip(tmp_path):
    one = np.full(SAMPLE_RATE, 2.0, dtype=np.float32)  # one second, far too loud
    joined = audio.join([[one, one], [one]])
    expected = 3 + audio.PAUSE_BETWEEN_LINES + audio.PAUSE_BETWEEN_PARTS
    assert abs(len(joined) / SAMPLE_RATE - expected) < 0.01
    assert float(np.max(np.abs(joined))) <= 0.9 + 1e-6
    seconds = audio.save_mp3(joined, tmp_path / "out" / "episode.mp3")
    assert abs(seconds - expected) < 0.01 and (tmp_path / "out" / "episode.mp3").stat().st_size > 1000
    assert len(audio.join([])) == 0
