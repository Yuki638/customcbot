"""Lists every English phrase of the interface that can be translated.

    uv run python tools/i18n_extract.py            # print the phrases as JSON
    uv run python tools/i18n_extract.py --missing  # per language: phrases with no translation yet

It reads the JavaScript the same way `web/i18n.js` does at run time: text and
the placeholder/title/aria-label/alt attributes written directly in an
html`...` template, plus phrases passed to t('...').
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

WEB = Path(__file__).resolve().parent.parent / "src" / "customcbot" / "web"
ATTRIBUTES = re.compile(r'\b(?:placeholder|title|aria-label|alt)="([^"]+)"')
T_CALL = re.compile(r"""\b(?:t|toast)\(\s*(['"])((?:\\.|(?!\1).)+)\1""")
# A quoted phrase inside ${...}: it is translated when it lands in the page as a whole.
# Only phrases that start with a capital count: class names and other code never do,
# and i18n.js applies the same rule before translating a value.
QUOTED = re.compile(r"""(['"])((?:\\.|(?!\1).)+)\1""")


def _templates(source: str) -> list[list[str]]:
    """The fixed parts of every html`...` template, including templates nested in ${...}."""
    found: list[list[str]] = []
    chosen.clear()

    def template(index: int, collect: bool) -> int:
        parts, part = [], []
        while index < len(source):
            char = source[index]
            if char == "\\":
                part.append(source[index : index + 2])
                index += 2
            elif char == "`":
                parts.append("".join(part))
                if collect:
                    found.append(parts)
                return index + 1
            elif source.startswith("${", index):
                parts.append("".join(part))
                part = []
                index = expression(index + 2)
            else:
                part.append(char)
                index += 1
        return index

    def expression(index: int) -> int:
        depth = 0
        while index < len(source):
            char = source[index]
            if char in "'\"":
                start = index
                index += 1
                while index < len(source) and source[index] != char:
                    index += 2 if source[index] == "\\" else 1
                index += 1
                text = source[start + 1 : index - 1].replace("\\'", "'")
                if text[:1].isupper() and not text.startswith(("/", "#", ".")):
                    chosen.append(text)
            elif char == "`":
                index = template(index + 1, source[max(0, index - 4) : index] == "html")
            elif char == "{":
                depth += 1
                index += 1
            elif char == "}":
                if depth == 0:
                    return index + 1
                depth -= 1
                index += 1
            else:
                index += 1
        return index

    index = 0
    while True:
        start = source.find("html`", index)
        if start < 0:
            return found
        index = template(start + 5, True)


chosen: list[str] = []  # quoted phrases met inside ${...} by the last _templates() call


def _phrases(parts: list[str]) -> list[str]:
    out: list[str] = []
    in_tag, quote = False, ""
    run: list[str] = []

    def flush(tag: bool) -> None:
        text = "".join(run)
        run.clear()
        if tag:
            out.extend(ATTRIBUTES.findall(text))
        else:
            out.append(text)

    for part in parts:
        for char in part:
            if in_tag:
                run.append(char)
                if quote:
                    quote = "" if char == quote else quote
                elif char in "'\"":
                    quote = char
                elif char == ">":
                    flush(True)
                    in_tag = False
            elif char == "<":
                flush(False)
                in_tag = True
                run.append(char)
            else:
                run.append(char)
        flush(in_tag)
    return out


def phrases() -> list[str]:
    seen: dict[str, None] = {}
    for path in sorted(WEB.rglob("*.js")):
        if "vendor" in path.parts or path.name == "i18n.js":
            continue
        source = path.read_text(encoding="utf-8")
        candidates = [p for parts in _templates(source) for p in _phrases(parts)]
        candidates += chosen
        # Labels kept in lists outside any template (tab names, menu choices).
        for line in source.splitlines():
            if not line.lstrip().startswith(("import ", "//", "*")):
                candidates += [
                    m.group(2).replace("\\'", "'")
                    for m in QUOTED.finditer(line)
                    if m.group(2)[:1].isupper()
                    and not re.search(r"[/#${}=<>\\]|^\s|\s$|^[A-Z][a-z]+[A-Z]|^[A-Z_]+$", m.group(2))
                ]
        candidates += [m.group(2).replace("\\'", "'") for m in T_CALL.finditer(source)]
        for candidate in candidates:
            key = " ".join(candidate.split())
            if sum(c.isalpha() for c in key) >= 2 and key != "customcbot":
                seen.setdefault(key)
    return list(seen)


def main() -> None:
    keys = phrases()
    if "--missing" in sys.argv:
        for path in sorted((WEB / "locales").glob("*.json")):
            have = json.loads(path.read_text(encoding="utf-8"))
            missing = [k for k in keys if k not in have]
            print(f"{path.stem}: {len(keys) - len(missing)} of {len(keys)} translated; missing {len(missing)}")
        return
    print(json.dumps(keys, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
