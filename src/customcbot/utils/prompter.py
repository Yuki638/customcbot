"""Loads the wording sent to the model from the template files in `prompts/`.

A template is named by its path without the extension, for example
`render("chat/grounded_system")`. Values passed in fill the `{{ name }}` places.
"""

from __future__ import annotations

import json
from functools import cache
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined

PROMPTS_DIR = Path(__file__).parent.parent / "prompts"

_env = Environment(
    loader=FileSystemLoader(PROMPTS_DIR),
    undefined=StrictUndefined,  # a missing value is a bug, not an empty string
    autoescape=False,
    keep_trailing_newline=False,
)


def render(name: str, **data) -> str:
    return _env.get_template(f"{name}.jinja").render(**data)


@cache
def load_json(name: str):
    """Structured prompt material, such as worked examples."""
    return json.loads((PROMPTS_DIR / f"{name}.json").read_text(encoding="utf-8"))
