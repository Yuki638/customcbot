"""A stand-in model for tests and for trying the interface without Ollama.

Start the app with CUSTOMCBOT_FAKE=1 to use it. Replies are canned: plain
requests get a short answer that cites the first source, and structured
requests get a minimal object that fits the requested schema.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterator

from .base import LLM, Message

Responder = Callable[[list[Message], dict | None, list[bytes] | None], str]


class FakeLLM(LLM):
    def __init__(self, responder: Responder | None = None, vision: bool = True) -> None:
        super().__init__()
        self.responder = responder or default_responder
        self.vision = vision
        self.calls: list[dict] = []

    def has_vision(self) -> bool:
        return self.vision

    def _stream(self, messages, *, images, json_schema, temperature, max_tokens) -> Iterator[str]:
        self.calls.append({"messages": messages, "images": images, "json_schema": json_schema})
        reply = self.responder(messages, json_schema, images)
        yield from re.findall(r"\S+\s*", reply)


def default_responder(messages: list[Message], schema: dict | None, images: list[bytes] | None) -> str:
    if schema is not None:
        return json.dumps(instance_from_schema(schema))
    if images:
        return "Handwritten note: the mitochondria is the powerhouse of the cell."
    prompt = messages[-1]["content"]
    first_source = re.search(r"\[1\][^\n]*\n(.+)", prompt)
    if first_source:
        return f"Based on your material: {first_source.group(1)[:200].strip()} [1]"
    return "This is a placeholder answer from the built-in test model."


def instance_from_schema(schema: dict, root: dict | None = None, name: str = "value") -> object:
    """Build the smallest value that satisfies a JSON schema."""
    root = root or schema
    if "$ref" in schema:
        target = root
        for part in schema["$ref"].lstrip("#/").split("/"):
            target = target[part]
        return instance_from_schema(target, root, name)
    if "anyOf" in schema:
        return instance_from_schema(schema["anyOf"][0], root, name)
    if "enum" in schema:
        return schema["enum"][0]
    kind = schema.get("type")
    if kind == "object":
        return {
            key: instance_from_schema(sub, root, key)
            for key, sub in schema.get("properties", {}).items()
        }
    if kind == "array":
        count = max(schema.get("minItems", 4), 1)
        return [instance_from_schema(schema.get("items", {}), root, f"{name} {i + 1}") for i in range(count)]
    if kind == "integer":
        return schema.get("minimum", 0)
    if kind == "number":
        return float(schema.get("minimum", 0))
    if kind == "boolean":
        return True
    return f"Sample {name.replace('_', ' ')}"
