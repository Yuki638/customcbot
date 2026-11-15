"""Model presets: local model sizes, and online services.

Local tags were checked against the Ollama registry in November 2026. To offer
a different model, change it here; nothing else in the code names a model.
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
    if hw.ram_gb < MIN_RAM_FOR_GOOD_LOCAL_GB:
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


# -- online services -------------------------------------------------------


@dataclass(frozen=True)
class OnlineService:
    """A hosted service that speaks the OpenAI chat API.

    Model names change often, so none is fixed here. The app asks the service
    for its current list and suggests the first one matching `prefer`.
    """

    id: str
    label: str
    base_url: str | None  # None: the user types the address
    key_url: str | None  # where to create a free key
    needs_key: bool
    prefer: tuple[str, ...]  # parts of model names, best first
    vision: bool  # whether the suggested models usually read images
    only_suffix: str | None  # list only models whose name ends like this
    blurb: str

    def to_dict(self) -> dict:
        return asdict(self)


ONLINE_SERVICES: list[OnlineService] = [
    OnlineService(
        id="groq",
        label="Groq",
        base_url="https://api.groq.com/openai/v1",
        key_url="https://console.groq.com/keys",
        needs_key=True,
        prefer=("llama-3.3-70b", "gpt-oss-120b", "70b", "llama"),
        vision=False,
        only_suffix=None,
        blurb="Very fast answers. Free account, no payment card needed.",
    ),
    OnlineService(
        id="gemini",
        label="Google Gemini",
        base_url="https://generativelanguage.googleapis.com/v1beta/openai",
        key_url="https://aistudio.google.com/apikey",
        needs_key=True,
        prefer=("flash-latest", "2.5-flash", "flash"),
        vision=True,
        only_suffix=None,
        blurb="Generous free allowance, and reads handwriting and scanned pages. "
        "Google may use free-tier requests to improve its products.",
    ),
    OnlineService(
        id="openrouter",
        label="OpenRouter",
        base_url="https://openrouter.ai/api/v1",
        key_url="https://openrouter.ai/keys",
        needs_key=True,
        prefer=("llama-3.3-70b", "gemma-3-27b", "70b", "gemma"),
        vision=False,
        only_suffix=":free",
        blurb="One key for many free models from different makers. Lower daily limits.",
    ),
    OnlineService(
        id="cerebras",
        label="Cerebras",
        base_url="https://api.cerebras.ai/v1",
        key_url="https://cloud.cerebras.ai",
        needs_key=True,
        prefer=("llama-3.3-70b", "gpt-oss-120b", "70b", "llama"),
        vision=False,
        only_suffix=None,
        blurb="Very fast answers. Free account with a daily allowance.",
    ),
    OnlineService(
        id="mistral",
        label="Mistral",
        base_url="https://api.mistral.ai/v1",
        key_url="https://console.mistral.ai/api-keys",
        needs_key=True,
        prefer=("mistral-small-latest", "mistral-small", "small"),
        vision=False,
        only_suffix=None,
        blurb="European service with a free plan. Free-plan requests may be used for training.",
    ),
    OnlineService(
        id="freellmapi",
        label="FreeLLMAPI on this computer",
        base_url="http://localhost:3001/v1",
        key_url="https://github.com/tashfeenahmed/freellmapi",
        needs_key=True,
        prefer=("auto",),
        vision=False,
        only_suffix=None,
        blurb="For people who run the FreeLLMAPI router, which spreads requests over many "
        "free services. Use the key shown in its dashboard.",
    ),
    OnlineService(
        id="custom",
        label="Another service",
        base_url=None,
        key_url=None,
        needs_key=False,
        prefer=(),
        vision=False,
        only_suffix=None,
        blurb="Any address that speaks the OpenAI chat API, including LM Studio or "
        "llama.cpp on your own network.",
    ),
]

# Below this much memory only the smallest local model fits, and its answers are
# poor. The setup wizard then suggests an online service first.
MIN_RAM_FOR_GOOD_LOCAL_GB = 7


def get_service(service_id: str) -> OnlineService:
    for service in ONLINE_SERVICES:
        if service.id == service_id:
            return service
    raise KeyError(service_id)


def recommend_mode(hw: Hardware) -> str:
    return "online" if hw.ram_gb < MIN_RAM_FOR_GOOD_LOCAL_GB else "local"


def usable_models(service: OnlineService, names: list[str]) -> list[str]:
    """The models worth offering: chat models only, best guess first."""
    # Speech, safety-filter, embedding and image models cannot hold a conversation.
    skip = (
        "embed", "whisper", "tts", "orpheus", "speech", "guard", "moderation",
        "rerank", "imagen", "veo", "image-generation",
    )  # fmt: skip
    kept = [n for n in names if not any(word in n.lower() for word in skip)]
    if service.only_suffix:
        kept = [n for n in kept if n.endswith(service.only_suffix)] or kept
    suggested = suggest_model(service, kept)
    return ([suggested] if suggested else []) + [n for n in kept if n != suggested]


def suggest_model(service: OnlineService, names: list[str]) -> str | None:
    for wanted in service.prefer:
        for name in names:
            if wanted in name.lower():
                return name
    return names[0] if names else None
