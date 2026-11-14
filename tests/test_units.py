"""Tests for the pieces that need no server."""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from customcbot.ingest import youtube
from customcbot.ingest.chunking import Unit, make_chunks, split_pieces
from customcbot.llm import catalog
from customcbot.llm.base import extract_json
from customcbot.llm.fake import FakeLLM, instance_from_schema
from customcbot.llm.hardware import Hardware
from customcbot.rag.prompts import format_time


def test_split_pieces_respects_limit():
    text = "First sentence here. " * 40 + "\n\n" + "word " * 300
    pieces = split_pieces(text, 200)
    assert pieces and all(len(p) <= 200 for p in pieces)


def test_chunks_keep_page_of_first_new_piece():
    units = [Unit(text=f"Page {n} content. " * 60, page=n) for n in (1, 2, 3)]
    chunks = make_chunks(units, max_chars=800, overlap=100)
    assert len(chunks) > 3
    assert chunks[0].page == 1
    assert {c.page for c in chunks} == {1, 2, 3}
    assert all(len(c.text) <= 800 + 100 + 50 for c in chunks)
    # Nothing is lost: every page's text appears somewhere.
    joined = " ".join(c.text for c in chunks)
    assert all(f"Page {n} content." in joined for n in (1, 2, 3))


def test_chunks_overlap_between_neighbours():
    units = [Unit(text=" ".join(f"Sentence number {i}." for i in range(200)))]
    chunks = make_chunks(units, max_chars=600, overlap=120)
    assert len(chunks) > 2
    for first, second in zip(chunks, chunks[1:], strict=False):
        tail = first.text.split("\n")[-1]
        assert tail in second.text


def test_caption_chunks_carry_timestamps():
    units = [Unit(text=f"caption line {i}", start_sec=i * 4.0, method="captions") for i in range(300)]
    chunks = make_chunks(units, max_chars=500, overlap=60)
    starts = [c.start_sec for c in chunks]
    assert starts[0] == 0.0
    assert starts == sorted(starts)
    assert "\n" not in chunks[0].text


def test_empty_units_make_no_chunks():
    assert make_chunks([]) == []
    assert make_chunks([Unit(text="   ")]) == []


@pytest.mark.parametrize(
    "url",
    [
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "https://youtu.be/dQw4w9WgXcQ?t=42",
        "youtube.com/watch?v=dQw4w9WgXcQ&list=PL123",
        "https://m.youtube.com/shorts/dQw4w9WgXcQ",
        "https://www.youtube.com/embed/dQw4w9WgXcQ",
        "https://www.youtube.com/live/dQw4w9WgXcQ?feature=share",
        "dQw4w9WgXcQ",
    ],
)
def test_video_id_from_common_links(url):
    assert youtube.video_id(url) == "dQw4w9WgXcQ"


@pytest.mark.parametrize("url", ["https://example.com/watch?v=dQw4w9WgXcQ", "not a link", "https://youtube.com/"])
def test_video_id_rejects_other_links(url):
    assert youtube.video_id(url) is None


def test_playlist_detection():
    assert youtube.is_playlist("https://www.youtube.com/playlist?list=PL123")
    assert not youtube.is_playlist("https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=PL123")
    assert not youtube.is_playlist("https://www.youtube.com/watch?v=dQw4w9WgXcQ")


def test_watch_url_with_timestamp():
    assert youtube.watch_url("abc", 75.9).endswith("v=abc&t=75s")
    assert youtube.watch_url("abc").endswith("v=abc")


def test_format_time():
    assert format_time(75) == "1:15"
    assert format_time(3725) == "1:02:05"


@pytest.mark.parametrize(
    "raw",
    ['{"a": 1}', '```json\n{"a": 1}\n```', 'Here you go: {"a": 1} hope that helps', '  {"a": 1}\n\nextra'],
)
def test_extract_json_tolerates_wrapping(raw):
    assert extract_json(raw) == {"a": 1}


def test_extract_json_rejects_prose():
    with pytest.raises(ValueError):
        extract_json("no data here")


def test_chat_json_retries_then_succeeds():
    class Answer(BaseModel):
        value: int

    replies = iter(["not json", '{"value": 7}'])
    llm = FakeLLM(responder=lambda messages, schema, images: next(replies))
    assert llm.chat_json([{"role": "user", "content": "x"}], Answer).value == 7
    assert len(llm.calls) == 2


def test_instance_from_schema_matches_model():
    class Inner(BaseModel):
        name: str
        score: float

    class Outer(BaseModel):
        items: list[Inner]
        ok: bool
        count: int

    Outer.model_validate(instance_from_schema(Outer.model_json_schema()))


def _hw(ram, gpu_gb=0.0):
    return Hardware(ram_gb=ram, cpu_cores=4, gpu="GPU" if gpu_gb else None, gpu_gb=gpu_gb, system="Linux")


def test_recommendation_follows_memory():
    assert catalog.recommend(_hw(4)) == "lite"
    assert catalog.recommend(_hw(7.7)) == "standard"
    assert catalog.recommend(_hw(32)) == "standard"  # no graphics card: the big model would crawl
    assert catalog.recommend(_hw(32, gpu_gb=12)) == "plus"


def test_standard_tier_uses_small_context_on_8gb():
    standard = catalog.get_tier("standard")
    assert catalog.settings_for(standard, _hw(7.7))["num_ctx"] == 4096
    assert catalog.settings_for(standard, _hw(16))["num_ctx"] == 8192
