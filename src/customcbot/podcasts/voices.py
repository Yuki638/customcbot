"""The voices offered for podcasts. They come with the offline speech model (Kokoro)."""

from __future__ import annotations

# The letter before the underscore in a voice id says which language it speaks.
LANGUAGES = {
    "a": ("en-us", "American English"),
    "b": ("en-gb", "British English"),
    "e": ("es", "Spanish"),
    "f": ("fr-fr", "French"),
    "h": ("hi", "Hindi"),
    "i": ("it", "Italian"),
    "p": ("pt-br", "Portuguese"),
}

# (id, name shown). English voices are the best tested; the others are included as they come.
_VOICES = [
    ("af_heart", "Heart"), ("af_bella", "Bella"), ("af_nicole", "Nicole"), ("af_sarah", "Sarah"),
    ("am_michael", "Michael"), ("am_fenrir", "Fenrir"), ("am_puck", "Puck"), ("am_adam", "Adam"),
    ("bf_emma", "Emma"), ("bf_isabella", "Isabella"), ("bm_george", "George"), ("bm_lewis", "Lewis"),
    ("ef_dora", "Dora"), ("em_alex", "Alex"),
    ("ff_siwis", "Siwis"),
    ("hf_alpha", "Alpha"), ("hm_omega", "Omega"),
    ("if_sara", "Sara"), ("im_nicola", "Nicola"),
    ("pf_dora", "Dora"), ("pm_alex", "Alex"),
]  # fmt: skip
VOICE_IDS = {voice_id for voice_id, _ in _VOICES}
DEFAULT_VOICE = "af_heart"


def language_code(voice_id: str) -> str:
    return LANGUAGES.get(voice_id[:1], LANGUAGES["a"])[0]


def catalog() -> list[dict]:
    out = []
    for voice_id, name in _VOICES:
        language = LANGUAGES[voice_id[0]][1]
        gender = "female" if voice_id[1] == "f" else "male"
        out.append({"id": voice_id, "label": f"{name} ({language}, {gender})", "language": language})
    return out
