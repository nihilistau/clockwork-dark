"""
Incremental JSON Narration Scanner
==================================

Streams the ``narration`` string out of a JSON object that is still arriving.

With ``response_format: json_schema`` the model emits one JSON object, so the
naive approach is to wait for it to close and then parse -- which means the
player stares at a frozen screen for the whole generation. ``narration`` is
first in the schema's property order, so it can be decoded and forwarded
character by character while the rest of the object is still being written.

Also provides a brace-counting object finder to replace the old fallback regex

    _JSON_LOOSE = r"(\\{[^{}]*\"narration\"[^{}]*\\})"

whose ``[^{}]*`` could never match the mandated payload, because that payload
always contains a nested ``{`` in ``choices``. That fallback has never once
fired; when the model omitted the code fence, raw JSON was shown to the player
as narration.

Version: v0.2.0 [2026-08-07]
"""

from __future__ import annotations

import json
from typing import Optional

_KEY = '"narration"'

# JSON's two-character escapes.
_ESCAPES = {
    '"': '"',
    "\\": "\\",
    "/": "/",
    "b": "\b",
    "f": "\f",
    "n": "\n",
    "r": "\r",
    "t": "\t",
}


class NarrationStreamer:
    """
    Feed raw model output; get decoded narration text back incrementally.

    States: looking for the key, then the opening quote, then decoding string
    contents until the closing unescaped quote.
    """

    def __init__(self) -> None:
        self._raw = ""
        self._cursor = 0
        self._state = "seek_key"
        self._escape = False
        self._hex = ""
        self.done = False
        self.text = ""

    def push(self, delta: str) -> str:
        """Feed a chunk. Returns newly decoded narration characters."""
        if self.done or not delta:
            return ""
        self._raw += delta
        return self._drain()

    def _drain(self) -> str:
        out: list[str] = []

        while self._cursor < len(self._raw) and not self.done:
            if self._state == "seek_key":
                index = self._raw.find(_KEY, self._cursor)
                if index == -1:
                    # Keep a tail long enough to hold a key split across chunks.
                    self._cursor = max(self._cursor, len(self._raw) - len(_KEY))
                    break
                self._cursor = index + len(_KEY)
                self._state = "seek_open"
                continue

            char = self._raw[self._cursor]
            self._cursor += 1

            if self._state == "seek_open":
                if char == '"':
                    self._state = "in_string"
                elif char not in ": \t\r\n":
                    # Not the shape we expected; resume hunting for the key.
                    self._state = "seek_key"

            elif self._state == "unicode":
                self._hex += char
                if len(self._hex) == 4:
                    try:
                        out.append(chr(int(self._hex, 16)))
                    except ValueError:
                        pass
                    self._hex = ""
                    self._state = "in_string"

            elif self._state == "in_string":
                if self._escape:
                    self._escape = False
                    if char == "u":
                        self._hex = ""
                        self._state = "unicode"
                    else:
                        out.append(_ESCAPES.get(char, char))
                elif char == "\\":
                    self._escape = True
                elif char == '"':
                    self.done = True
                    self._state = "finished"
                else:
                    out.append(char)

        chunk = "".join(out)
        self.text += chunk
        return chunk


def find_json_object(text: str, start: int = 0) -> Optional[str]:
    """
    Return the first balanced JSON object in text, or None.

    Brace counting, string- and escape-aware, so nested objects and braces
    inside string values are both handled. This is what the old regex could
    not do.
    """
    depth = 0
    in_string = False
    escape = False
    begin = -1

    for index in range(start, len(text)):
        char = text[index]

        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue

        if char == '"':
            in_string = True
        elif char == "{":
            if depth == 0:
                begin = index
            depth += 1
        elif char == "}":
            if depth > 0:
                depth -= 1
                if depth == 0 and begin != -1:
                    return text[begin : index + 1]

    return None


def extract_json(text: str) -> Optional[dict]:
    """
    Best-effort parse of a JSON object embedded in model output.

    Tries a fenced ```json block first, then any balanced object, then the
    whole string.
    """
    fence = text.find("```json")
    if fence != -1:
        candidate = find_json_object(text, fence)
        if candidate:
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                pass

    candidate = find_json_object(text)
    if candidate:
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            pass

    try:
        parsed = json.loads(text.strip())
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        return None
