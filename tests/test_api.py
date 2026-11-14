"""End-to-end tests through the HTTP API, using the built-in stand-in model."""

from __future__ import annotations

import json

from customcbot.ingest import youtube
from customcbot.ingest.chunking import Unit

from .conftest import wait
from .helpers import ask, docx_bytes, png_bytes, pptx_bytes, scanned_pdf, text_image, text_pdf

CELLS = (
    "Mitochondria are the powerhouse of the cell. They produce ATP through cellular respiration. "
    "The inner membrane is folded into cristae, which increase the surface area for reactions. "
)
ROME = (
    "The Roman Republic was founded in 509 BC after the last king was overthrown. "
    "Julius Caesar crossed the Rubicon in 49 BC, which started a civil war. "
)


def upload(client, collection_id, name, data, mime="application/octet-stream"):
    response = client.post(
        f"/api/collections/{collection_id}/sources/files", files=[("files", (name, data, mime))]
    )
    assert response.status_code == 200
    wait(client)
    return response.json()


def sources(client, collection_id):
    return client.get(f"/api/collections/{collection_id}/sources").json()


def test_setup_reports_ready_with_test_model(client):
    status = client.get("/api/setup").json()
    assert status["ready"] and status["fake"]
    assert [t["id"] for t in status["tiers"]] == ["lite", "standard", "plus"]
    assert status["recommended"] == "standard"


def test_text_file_is_indexed_and_answered_with_citation(client, collection):
    result = upload(client, collection, "cells.txt", (CELLS * 5).encode())
    assert len(result["added"]) == 1
    (source,) = sources(client, collection)
    assert source["status"] == "ready" and source["kind"] == "text" and source["title"] == "cells"

    chat_id, text, cited, events = ask(client, collection, "What do mitochondria produce?")
    assert cited and cited[0]["title"] == "cells"
    assert "[1]" in text
    assert events[-1][0] == "done"
    assert events[-1][1]["citations"][0]["n"] == 1
    assert events[-1][1]["content"] == text.strip()

    messages = client.get(f"/api/chats/{chat_id}/messages").json()
    assert [m["role"] for m in messages] == ["user", "assistant"]
    assert messages[1]["citations"][0]["chunk_id"] == cited[0]["chunk_id"]
    chats = client.get(f"/api/collections/{collection}/chats").json()
    assert chats[0]["title"].startswith("What do mitochondria")


def test_pdf_citations_carry_page_numbers(client, collection):
    pdf = text_pdf(["Introduction to botany. " * 30, ROME * 6, CELLS * 6])
    upload(client, collection, "lecture.pdf", pdf, "application/pdf")
    (source,) = sources(client, collection)
    assert source["status"] == "ready", source

    _, _, cited, _ = ask(client, collection, "When did Caesar cross the Rubicon?")
    assert cited[0]["page"] == 2
    assert cited[0]["label"] == "lecture, page 2"
    _, _, cited, _ = ask(client, collection, "What are cristae in mitochondria?")
    assert cited[0]["page"] == 3

    served = client.get(f"/api/sources/{source['id']}/file")
    assert served.status_code == 200 and served.content.startswith(b"%PDF")


def test_scanned_pdf_is_read_by_the_vision_model(client, collection):
    upload(client, collection, "scan.pdf", scanned_pdf("HELLO"), "application/pdf")
    (source,) = sources(client, collection)
    assert source["status"] == "ready", source
    assert "Check the text" in source["note"]
    units = client.get(f"/api/sources/{source['id']}/units").json()["units"]
    assert units[0]["method"] == "vision" and "mitochondria" in units[0]["text"]


def test_image_falls_back_to_basic_ocr_without_a_vision_model(client, collection):
    client.app.state.services.llm.vision = False
    upload(client, collection, "note.png", png_bytes(text_image("PHOTOSYNTHESIS")), "image/png")
    (source,) = sources(client, collection)
    assert source["status"] == "ready", source
    assert "unreliable on handwriting" in source["note"]
    units = client.get(f"/api/sources/{source['id']}/units").json()["units"]
    assert units[0]["method"] == "ocr"
    assert "PHOTOSYNTHESIS" in units[0]["text"].upper().replace(" ", "")


def test_blank_image_reports_a_clear_error(client, collection):
    client.app.state.services.llm.vision = False
    upload(client, collection, "blank.png", png_bytes(text_image("")), "image/png")
    (source,) = sources(client, collection)
    assert source["status"] == "error"
    assert "No readable text" in source["error"]


def test_word_and_powerpoint(client, collection):
    upload(client, collection, "essay.docx", docx_bytes([ROME * 3, "A second paragraph about the Senate."]))
    upload(client, collection, "slides.pptx", pptx_bytes([("Cells", CELLS), ("Rome", ROME)]))
    assert [s["status"] for s in sources(client, collection)] == ["ready", "ready"]

    _, _, cited, _ = ask(client, collection, "Tell me about the Senate paragraph")
    assert any(c["title"] == "essay" for c in cited)
    _, _, cited, _ = ask(client, collection, "cristae surface area")
    slide = next(c for c in cited if c["title"] == "slides")
    assert slide["page"] == 1 and slide["label"] == "slides, slide 1"


def test_unsupported_and_damaged_files(client, collection):
    result = upload(client, collection, "program.exe", b"MZ")
    assert result["added"] == [] and result["rejected"][0]["name"] == "program.exe"
    upload(client, collection, "broken.pdf", b"this is not a pdf", "application/pdf")
    (source,) = sources(client, collection)
    assert source["status"] == "error" and source["error"]

    assert client.post(f"/api/sources/{source['id']}/retry").status_code == 200
    wait(client)
    assert sources(client, collection)[0]["status"] == "error"


def test_youtube_captions_give_timestamped_citations(client, collection, monkeypatch):
    captions = [Unit(text=f"filler talk number {i}", start_sec=i * 5.0, method="captions") for i in range(120)]
    captions[80] = Unit(text="Photosynthesis happens in the chloroplast.", start_sec=400.0, method="captions")
    monkeypatch.setattr(youtube, "fetch_captions", lambda vid: captions)
    monkeypatch.setattr(youtube, "fetch_title", lambda vid: "Plant biology lecture")

    response = client.post(
        f"/api/collections/{collection}/sources/links",
        json={"urls": ["https://youtu.be/dQw4w9WgXcQ", "https://example.com/video", ""]},
    )
    body = response.json()
    assert len(body["added"]) == 1 and body["rejected"][0]["name"] == "https://example.com/video"
    wait(client)
    (source,) = sources(client, collection)
    assert source["status"] == "ready" and source["title"] == "Plant biology lecture"

    _, _, cited, _ = ask(client, collection, "Where does photosynthesis happen? chloroplast")
    top = cited[0]
    assert top["start_sec"] is not None and top["start_sec"] <= 400.0
    assert "Photosynthesis" in top["text"]
    assert top["url"].startswith("https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=")
    assert ", at " in top["label"]


def test_youtube_failure_is_explained(client, collection, monkeypatch):
    def blocked(vid):
        raise youtube.YouTubeError("YouTube refused the request from this network.")

    monkeypatch.setattr(youtube, "fetch_captions", blocked)
    monkeypatch.setattr(youtube, "fetch_title", lambda vid: None)
    client.post(f"/api/collections/{collection}/sources/links", json={"urls": ["https://youtu.be/dQw4w9WgXcQ"]})
    wait(client)
    (source,) = sources(client, collection)
    assert source["status"] == "error" and "refused" in source["error"]


def test_search_picks_the_right_source_and_respects_the_filter(client, collection):
    upload(client, collection, "cells.txt", (CELLS * 4).encode())
    upload(client, collection, "rome.txt", (ROME * 4).encode())
    cells, rome = sources(client, collection)

    _, _, cited, _ = ask(client, collection, "Who crossed the Rubicon?")
    assert cited[0]["source_id"] == rome["id"]
    _, _, cited, _ = ask(client, collection, "Who crossed the Rubicon?", source_ids=[cells["id"]])
    assert cited and all(c["source_id"] == cells["id"] for c in cited)


def test_follow_up_question_is_rewritten_before_searching(client, collection):
    upload(client, collection, "cells.txt", (CELLS * 4).encode())
    llm = client.app.state.services.llm
    chat_id, *_ = ask(client, collection, "What are mitochondria?")
    calls_after_first = len(llm.calls)
    ask(client, collection, "And why so?", chat_id=chat_id)
    assert len(llm.calls) - calls_after_first == 2  # one rewrite, one answer
    rewrite_prompt = llm.calls[calls_after_first]["messages"][0]["content"]
    assert "understandable on its own" in rewrite_prompt


def test_rewrite_is_used_only_when_it_keeps_the_question(services):
    from customcbot.llm.fake import FakeLLM
    from customcbot.rag import chat

    history = [
        {"role": "user", "content": "Where does glycolysis take place?"},
        {"role": "assistant", "content": "In the cytoplasm [1]."},
    ]

    def rewrite_with(reply: dict, question: str) -> str:
        services.llm = FakeLLM(responder=lambda messages, schema, images: json.dumps(reply))
        return chat.standalone_question(question, history, services)

    good = {"topic": "glycolysis", "needs_topic": True, "question": "What is the next stage after glycolysis?"}
    assert rewrite_with(good, "And the next stage?") == good["question"]
    # The model says the question stands alone: it is left as it was.
    assert rewrite_with({**good, "needs_topic": False}, "And the next stage?") == "And the next stage?"
    # The model returned the previous question instead of the new one.
    swapped = {**good, "question": "Where does glycolysis take place?"}
    assert rewrite_with(swapped, "What does pepsin do?") == "What does pepsin do?"
    # The conversation was stuffed into the question.
    stuffed = {**good, "question": "And the next stage, " + "considering what was said before " * 5 + "?"}
    assert rewrite_with(stuffed, "And the next stage?") == "And the next stage?"


def test_empty_collection_asks_for_material(client, collection):
    llm = client.app.state.services.llm
    _, text, cited, _ = ask(client, collection, "Anything?")
    assert "nothing to search yet" in text and cited == [] and llm.calls == []
    _, text, _, _ = ask(client, collection, "Anything?", general=True)
    assert llm.calls and "placeholder answer" in text


def test_editing_extracted_text_updates_the_index(client, collection):
    upload(client, collection, "notes.txt", b"The capital of Freedonia is Zubrowka city, famous for its lakes.")
    (source,) = sources(client, collection)
    unit = client.get(f"/api/sources/{source['id']}/units").json()["units"][0]
    response = client.put(f"/api/units/{unit['id']}", json={"text": "The capital of Freedonia is Marxville."})
    assert response.status_code == 200
    _, _, cited, _ = ask(client, collection, "capital of Freedonia")
    assert "Marxville" in cited[0]["text"] and "Zubrowka" not in cited[0]["text"]


def test_deleting_a_source_removes_it_from_answers(client, collection):
    upload(client, collection, "rome.txt", (ROME * 4).encode())
    (source,) = sources(client, collection)
    assert client.delete(f"/api/sources/{source['id']}").status_code == 200
    assert sources(client, collection) == []
    _, text, cited, _ = ask(client, collection, "Rubicon?")
    assert cited == [] and "nothing to search yet" in text


def test_pasted_text(client, collection):
    response = client.post(
        f"/api/collections/{collection}/sources/text", json={"title": "", "text": ROME * 3}
    )
    assert response.status_code == 200
    wait(client)
    (source,) = sources(client, collection)
    assert source["status"] == "ready" and source["title"].startswith("The Roman Republic")
    assert client.post(f"/api/collections/{collection}/sources/text", json={"text": "  "}).status_code == 400


def run_job(client, response):
    assert response.status_code == 200, response.text
    wait(client)
    job = client.get(f"/api/jobs/{response.json()['id']}").json()
    assert job["status"] == "done", job
    return job


def test_summaries_for_a_source_and_the_collection(client, collection):
    upload(client, collection, "cells.txt", (CELLS * 60).encode())  # long enough to need several parts
    upload(client, collection, "rome.txt", (ROME * 4).encode())
    cells, rome = sources(client, collection)

    run_job(client, client.post(f"/api/collections/{collection}/summary", json={"source_id": cells["id"]}))
    summary = client.get(f"/api/collections/{collection}/summary").json()
    assert summary["sources"][0]["summary"] and summary["sources"][1]["summary"] is None

    run_job(client, client.post(f"/api/collections/{collection}/summary", json={}))
    summary = client.get(f"/api/collections/{collection}/summary").json()
    assert summary["summary"] and all(s["summary"] for s in summary["sources"])

    # Adding material makes the overview stale.
    upload(client, collection, "more.txt", (ROME * 2).encode())
    assert client.get(f"/api/collections/{collection}/summary").json()["summary"] is None


def test_quiz_generation_and_grading(client, collection):
    upload(client, collection, "cells.txt", (CELLS * 30).encode())
    job = run_job(client, client.post(f"/api/collections/{collection}/quizzes", json={"count": 4, "style": "mixed"}))
    quiz = client.get(f"/api/quizzes/{job['result']['quiz_id']}").json()
    assert len(quiz["questions"]) == 4
    kinds = {q["type"] for q in quiz["questions"]}
    assert kinds == {"mcq", "short"}
    mcq = next(q for q in quiz["questions"] if q["type"] == "mcq")
    assert 0 <= mcq["answer_index"] < len(mcq["options"]) and mcq["where"] == "cells"

    short = next(q for q in quiz["questions"] if q["type"] == "short")
    graded = client.post(
        f"/api/quizzes/{quiz['id']}/grade", json={"question_id": short["id"], "answer": short["answer"]}
    ).json()
    assert graded["correct"] is True and graded["answer"] == short["answer"]
    partly = client.post(
        f"/api/quizzes/{quiz['id']}/grade", json={"question_id": short["id"], "answer": "Sample, roughly"}
    ).json()
    assert partly["correct"] is True and partly["feedback"] == "Sample feedback"  # decided by the model
    assert client.post(f"/api/quizzes/{quiz['id']}/grade", json={"question_id": mcq["id"], "answer": "x"}).status_code == 400
    assert len(mcq["options"]) == 4 and mcq["options"][mcq["answer_index"]] == "Sample correct answer"

    # An answer unrelated to the reference is marked wrong without consulting the model.
    calls = len(client.app.state.services.llm.calls)
    nonsense = client.post(
        f"/api/quizzes/{quiz['id']}/grade", json={"question_id": short["id"], "answer": "bananas"}
    ).json()
    assert nonsense["correct"] is False and len(client.app.state.services.llm.calls) == calls

    client.post(f"/api/quizzes/{quiz['id']}/score", json={"score": 0.75})
    client.post(f"/api/quizzes/{quiz['id']}/score", json={"score": 0.5})
    listed = client.get(f"/api/collections/{collection}/quizzes").json()
    assert listed[0]["best_score"] == 0.75 and listed[0]["question_count"] == 4


def test_quiz_needs_material(client, collection):
    response = client.post(f"/api/collections/{collection}/quizzes", json={"count": 3})
    wait(client)
    job = client.get(f"/api/jobs/{response.json()['id']}").json()
    assert job["status"] == "error" and "Add some material" in job["error"]


def test_flashcards_and_spaced_repetition(client, collection):
    upload(client, collection, "cells.txt", (CELLS * 30).encode())
    job = run_job(client, client.post(f"/api/collections/{collection}/flashcards", json={"count": 3}))
    assert job["result"]["created"] == 3
    cards = client.get(f"/api/collections/{collection}/flashcards", params={"due": True}).json()
    assert len(cards) == 3 and all(c["box"] == 1 for c in cards)

    known = client.post(f"/api/flashcards/{cards[0]['id']}/review", json={"known": True}).json()
    assert known["box"] == 2
    due = client.get(f"/api/collections/{collection}/flashcards", params={"due": True}).json()
    assert len(due) == 2  # the known card comes back tomorrow
    missed = client.post(f"/api/flashcards/{cards[0]['id']}/review", json={"known": False}).json()
    assert missed["box"] == 1
    assert len(client.get(f"/api/collections/{collection}/flashcards", params={"due": True}).json()) == 3

    assert client.put(f"/api/flashcards/{cards[1]['id']}", json={"front": "Q", "back": "A"}).status_code == 200
    assert client.put(f"/api/flashcards/{cards[1]['id']}", json={"front": " ", "back": "A"}).status_code == 400
    client.delete(f"/api/flashcards/{cards[2]['id']}")
    assert len(client.get(f"/api/collections/{collection}/flashcards").json()) == 2


def test_collections_can_be_renamed_and_deleted(client, collection):
    upload(client, collection, "rome.txt", (ROME * 4).encode())
    assert client.patch(f"/api/collections/{collection}", json={"name": "History"}).json()["name"] == "History"
    assert client.get("/api/collections").json()[0]["source_count"] == 1
    assert client.delete(f"/api/collections/{collection}").status_code == 200
    assert client.get("/api/collections").json() == []
    assert client.post("/api/collections", json={"name": "  "}).status_code == 400


def test_requests_from_other_websites_are_refused(client):
    response = client.post("/api/collections", json={"name": "x"}, headers={"Origin": "https://evil.example"})
    assert response.status_code == 403
    same = client.post("/api/collections", json={"name": "x"}, headers={"Origin": "http://testserver"})
    assert same.status_code == 200


def test_settings_can_be_changed_within_limits(client):
    updated = client.put("/api/settings", json={"values": {"num_ctx": 10, "vision_model": " "}}).json()
    assert updated["num_ctx"] == 1024 and updated["vision_model"] is None
    assert client.put("/api/settings", json={"values": {"setup_done": False}}).status_code == 400
