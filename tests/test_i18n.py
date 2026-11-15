"""The interface's language files."""

from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
LOCALES = ROOT / "src" / "customcbot" / "web" / "locales"
spec = importlib.util.spec_from_file_location("i18n_extract", ROOT / "tools" / "i18n_extract.py")
extract = importlib.util.module_from_spec(spec)
spec.loader.exec_module(extract)

PHRASES = extract.phrases()
LANGUAGES = ["es", "fr", "pt", "hi", "zh"]


def test_the_tool_finds_text_labels_and_phrases_chosen_in_code():
    assert len(PHRASES) > 300
    for phrase in (
        "+ New collection",  # text in a template
        "Paste YouTube links",  # a placeholder
        "Podcast",  # a tab name kept in a list
        "Saved to Notes",  # a label chosen in code
        "Settings saved.",  # a message shown with toast()
    ):
        assert phrase in PHRASES, phrase
    # Class names and other code strings are never offered for translation.
    assert not [p for p in PHRASES if re.fullmatch(r"[a-z]+( [a-z-]+)* (primary|small|ghost|stack|row|err)", p)]


@pytest.mark.parametrize("code", LANGUAGES)
def test_each_language_file_matches_the_interface(code):
    translations = json.loads((LOCALES / f"{code}.json").read_text(encoding="utf-8"))
    stale = [key for key in translations if key not in PHRASES]
    assert not stale, f"no longer in the interface: {stale[:5]}"
    covered = sum(1 for phrase in PHRASES if phrase in translations) / len(PHRASES)
    assert covered >= 0.95, f"only {covered:.0%} of the interface is translated"
    for english, translated in translations.items():
        assert isinstance(translated, str) and translated.strip(), english
        # Names in {curly braces} are filled in by the app and must survive translation.
        assert set(re.findall(r"\{\w+\}", english)) == set(re.findall(r"\{\w+\}", translated)), english
        assert "customcbot" not in english or "customcbot" in translated, english


def test_the_language_list_in_the_app_matches_the_files():
    source = (LOCALES.parent / "i18n.js").read_text(encoding="utf-8")
    offered = re.findall(r"\['(\w\w)', '", source)
    assert offered == ["en", *LANGUAGES]
    assert sorted(p.stem for p in LOCALES.glob("*.json")) == sorted(LANGUAGES)
