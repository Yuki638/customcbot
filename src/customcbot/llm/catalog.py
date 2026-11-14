"""Model presets.

Tags were checked against the Ollama registry in November 2026. To offer a
different model, change it here; nothing else in the code names a model.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

from .hardware import Hardware


@dataclass(frozen=True)
class Tier:
    id: str
    label: str
    chat_model: str
    vision_model: str | None  # reads handwriting and scanned pages; None = basic OCR only
    whisper_model: str  # speech-to-text size for videos without captions
    num_ctx: int  # how much text the model sees at once, in tokens
    context_chars: int  # how much retrieved material goes into each answer
    max_passages: int  # fewer passages keeps small models focused and fast
    download_gb: float
    min_ram_gb: int
    blurb: str

    def to_dict(self) -> dict:
        return asdict(self)


TIERS: list[Tier] = [
    Tier(
        id="lite",
        label="Lite",
        chat_model="gemma3:1b",
        vision_model=None,
        whisper_model="tiny",
        num_ctx=4096,
        context_chars=3600,
        max_passages=4,
        download_gb=0.8,
        min_ram_gb=4,
        blurb="For older or low-memory computers. Fast, simpler answers. "
        "Reads typed and printed text; handwriting is unreliable.",
    ),
    Tier(
        id="standard",
        label="Standard",
        chat_model="gemma3:4b",
        vision_model="gemma3:4b",
        whisper_model="base",
        num_ctx=8192,
        context_chars=9000,
        max_passages=6,
        download_gb=3.4,
        min_ram_gb=8,
        blurb="For most laptops with 8 GB of memory or more. "
        "Better explanations, and reads handwritten notes and scanned pages.",
    ),
    Tier(
        id="plus",
        label="Plus",
        chat_model="gemma3:12b",
        vision_model="gemma3:12b",
        whisper_model="small",
        num_ctx=8192,
        context_chars=12000,
        max_passages=8,
        download_gb=8.2,
        min_ram_gb=16,
        blurb="For computers with 16 GB of memory and a graphics card or Apple Silicon. "
        "Best answers; slow without a graphics card.",
    ),
]


def get_tier(tier_id: str) -> Tier:
    for tier in TIERS:
        if tier.id == tier_id:
            return tier
    raise KeyError(tier_id)


def recommend(hw: Hardware) -> str:
    if hw.ram_gb < 7:
        return "lite"
    if hw.ram_gb >= 15 and hw.gpu_gb >= 8:
        return "plus"
    return "standard"


def settings_for(tier: Tier, hw: Hardware) -> dict:
    """The settings a tier turns into on this machine."""
    num_ctx = tier.num_ctx
    context_chars = tier.context_chars
    if tier.id == "standard" and hw.ram_gb < 12 and hw.gpu_gb < 6:
        # A 4B model with a large context window does not fit comfortably in 8 GB.
        num_ctx, context_chars = 4096, 5000
    return {
        "tier": tier.id,
        "chat_model": tier.chat_model,
        "vision_model": tier.vision_model,
        "whisper_model": tier.whisper_model,
        "num_ctx": num_ctx,
        "context_chars": context_chars,
        "max_passages": tier.max_passages,
    }
