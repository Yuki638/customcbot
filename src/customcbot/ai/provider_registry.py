"""Every kind of AI service the app can talk to.

`kind` says which client is used: "ollama" for a local Ollama, "openai" for
any service that speaks the OpenAI chat API. Online services are described in
`catalog.py`; this adds the local one and gives them all one shape.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

from . import catalog

OLLAMA = "ollama"


@dataclass(frozen=True)
class Provider:
    id: str
    label: str
    kind: str  # "ollama" | "openai"
    local: bool  # runs on this computer, so nothing leaves it
    base_url: str | None
    key_url: str | None
    needs_key: bool
    blurb: str

    def to_dict(self) -> dict:
        return asdict(self)


PROVIDERS: dict[str, Provider] = {
    OLLAMA: Provider(
        id=OLLAMA,
        label="This computer (Ollama)",
        kind="ollama",
        local=True,
        base_url=None,
        key_url=None,
        needs_key=False,
        blurb="A model that runs on your own computer through Ollama. Private, and works offline.",
    ),
    **{
        service.id: Provider(
            id=service.id,
            label=service.label,
            kind="openai",
            local=False,
            base_url=service.base_url,
            key_url=service.key_url,
            needs_key=service.needs_key,
            blurb=service.blurb,
        )
        for service in catalog.ONLINE_SERVICES
    },
}


def get_provider(provider_id: str) -> Provider | None:
    return PROVIDERS.get(provider_id)
