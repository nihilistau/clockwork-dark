"""
A scripted voice for the READ RECEIPTS tests (spec §19): a callable `LLMFn`
returning schema-valid replies by policy, so no test reaches a model
(`tests/conftest.py::_no_live_model_calls` stays default-deny).

Policies (each one bubble, nothing learned or shared, no proposal):

- ``warm``: regard warmth +3, trust +1, mood ``fond``;
- ``cold``: warmth -2, trust -1, mood ``annoyed``;
- ``zero``: 0, 0, ``neutral``;
- ``wordy``: different words, the same regard as ``zero``.

``script`` replies are returned first, in order, before the policy takes
over; ``fail`` makes the first N calls return text that does not parse;
``block`` makes every call wait on the event (a bounded ``wait(5)``, failing
the test if it times out). ``calls`` counts the calls; ``requests`` keeps
each call's (messages, response_format).
"""

from __future__ import annotations

import json
import threading
from typing import Any, Optional

import pytest

POLICIES: dict[str, tuple[str, dict[str, Any]]] = {
    "warm": ("that sounds lovely, tell me more", {"warmth": 3, "trust": 1, "mood": "fond"}),
    "cold": ("ok", {"warmth": -2, "trust": -1, "mood": "annoyed"}),
    "neutral": ("sure, sounds good", {"warmth": 1, "trust": 1, "mood": "neutral"}),
    "zero": ("sure", {"warmth": 0, "trust": 0, "mood": "neutral"}),
    "wordy": ("honestly that's such a good point, I keep thinking about it",
              {"warmth": 0, "trust": 0, "mood": "neutral"}),
}

#: What a `fail` call returns: no JSON object in it.
UNPARSEABLE = "sorry, I can't format that"

#: How long a blocked call waits on its event before it fails the test.
BLOCK_SECONDS = 5


class StubVoice:
    def __init__(self, policy: str = "warm", *, block: Optional[threading.Event] = None, fail: int = 0,
                 script: Optional[list[str]] = None) -> None:
        if policy not in POLICIES:
            raise ValueError(f"StubVoice: no policy {policy!r} ({', '.join(POLICIES)})")
        self.policy = policy
        self.block = block
        self.fail = int(fail)
        self.script = list(script or [])
        self.calls = 0
        self.requests: list[tuple[list[dict[str, Any]], dict[str, Any]]] = []
        self._lock = threading.Lock()

    def __call__(self, messages: list[dict[str, Any]], fmt: dict[str, Any]) -> str:
        with self._lock:
            self.calls += 1
            n = self.calls
            self.requests.append((list(messages), fmt))
            scripted = self.script.pop(0) if n > self.fail and self.script else None
        if self.block is not None and not self.block.wait(BLOCK_SECONDS):
            pytest.fail(f"StubVoice: call {n} was blocked for {BLOCK_SECONDS}s and never released")
        if n <= self.fail:
            return UNPARSEABLE
        if scripted is not None:
            return scripted
        return json.dumps(self.reply(fmt))

    def reply(self, fmt: dict[str, Any]) -> dict[str, Any]:
        """The policy's reply, valid against the call's schema (media and proposals only when declared)."""
        text, regard = POLICIES[self.policy]
        schema = ((fmt or {}).get("json_schema") or {}).get("schema") or {}
        props = schema.get("properties") or {}
        out: dict[str, Any] = {"bubbles": [{"text": text}], "regard": dict(regard), "learned": [], "shared": []}
        if "proposals" in props:
            out["proposals"] = []
        if "media" in props:
            out["media"] = {"caption": "this one's for you"}
        return out
