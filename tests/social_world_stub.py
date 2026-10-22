"""
A storyteller for READ RECEIPTS' world turn with no model (v0.23.0 T11, lesson 2).

``StubNarrator`` is an ``llm_fn``: for a Storyteller call it answers a turn that is valid under the
LIVE grammar (``storyteller_turn_schema`` over ``legal_intents`` of the active engine's state, checked
before it is returned), its narration naming the activity the turn's receipt carries, and its choices
the first three legal verbs, each with an intent on its first target. Any other agent's call gets a
short shapeless line. Built into the app from the start (``_live_session(llm_fn=StubNarrator())``,
pre-flight F2), so no world-turn test reaches a model.
"""

from __future__ import annotations

import json
from typing import Any

#: Pads the narration past the schema's minimum, in the story's plain register.
_FILLER = (
    "The flat is quiet around you: the boxes against the wall, the window going on with the street, "
    "the kettle cooling on the side. The phone lies face-down where you left it. "
    "Nothing in the room asks anything of you for a while."
)


class StubNarrator:
    """An ``llm_fn`` for the storyteller (see the module docstring). ``calls`` counts Storyteller calls.
    ``narration`` (v0.23.0 T15): the narration every call answers with, padded with the filler past the
    schema's minimum, in place of the activity line."""

    def __init__(self, narration: str = "") -> None:
        self.calls = 0
        self.prompts: list[str] = []
        self.narration = narration

    def __call__(self, messages: list[dict[str, Any]], **_: Any) -> str:
        from engine.agents.prompts import storyteller_persona

        persona = storyteller_persona().strip().splitlines()[0]          # the story's own first line
        if not any(persona in str(m.get("content", "")) for m in messages):
            return "Nothing is said, at length."
        self.calls += 1
        text = "\n".join(str(m.get("content", "")) for m in messages)
        self.prompts.append(text)
        return self.turn(text)

    @staticmethod
    def _activity(text: str) -> str:
        """The label of the activity the prompt's receipt names (its `activity` field), or ""."""
        import re

        from engine.social import world

        named = re.findall(r"activity\W+([a-z_]+)", text)
        rows = {str(r["id"]): r for r in world.activities()}
        for rid in reversed(named):
            if rid in rows:
                return str(rows[rid].get("label") or rid)
        return ""

    def turn(self, prompt: str) -> str:
        from engine.game.engine import get_active_engine
        from engine.game.intents import legal_intents
        from engine.llm.schemas import storyteller_turn_schema
        from schema_check import validate

        state = get_active_engine().state
        verbs = legal_intents(state)
        activity = self._activity(prompt)
        narration = (f"{activity}: you get on with it. " if activity else "") + _FILLER
        if self.narration:
            narration = f"{self.narration} {_FILLER}"
        choices: list[dict[str, Any]] = []
        for verb in verbs:
            if len(choices) == 3:
                break
            if verb.extra:
                continue
            row: dict[str, Any] = {"id": "abcd"[len(choices)], "text": f"{verb.action} {len(choices)}"[:100]}
            if verb.targets:
                row["text"] = verb.label_for(verb.targets[0])[:100]
                row["intent"] = {"action": verb.action, "target": verb.targets[0]}
            else:
                row["intent"] = {"action": verb.action}
            choices.append(row)
        while len(choices) < 2:
            choices.append({"id": "abcd"[len(choices)], "text": "Stay where you are"})
        payload = {"narration": narration, "choices": choices}
        schema = storyteller_turn_schema(intents=verbs)
        errors = validate(payload, schema["schema"])
        assert not errors, "StubNarrator's turn is not samplable from the live grammar: " + "; ".join(errors)
        return json.dumps(payload)
