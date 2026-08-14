"""
Structured Output Schemas
=========================

JSON Schemas for ``response_format: {"type": "json_schema"}``.

The turn contract used to live in prose inside the system prompt and was
recovered by scraping a fenced code block out of the reply. Moving it into a
schema removes several whole classes of failure at once:

  - No unparseable output, so no "raw JSON shown to the player as narration".
  - No zero-choice soft-lock, because minItems is enforced by the sampler.
  - No secret length rubric: the evaluator wanted 40-200 words and never told
    the model. minLength/maxLength say it out loud.
  - No hallucinated characters: npc_id is an enum built per turn from the NPCs
    actually present, so naming someone who is not in the room is unsampleable.

Fields the model used to be asked for and that were then thrown away
(stat_changes, items_gained, items_lost, skill_check) are gone. Removing them
removes the incentive to try.

THE MECHANIC LIVES IN THE CHOICE (v0.3.0)
-----------------------------------------
It used to be said here that "every mechanical effect goes through a tool
call". That was false in the only way that matters: this schema sets
``additionalProperties: False`` and declares no ``tool_calls`` property, so
with the grammar on a tool call could not be sampled at all. Travel, dice,
rest, food and trade were unreachable in real play, and a player who chose
"Follow the smoke toward Edgewood" was narrated into the village while the save
still read ``forest_clearing``.

A choice may now carry a structured ``intent``, and the same trick that makes
``npc_id`` safe makes it safe: the legal verbs and the legal targets for each
are built PER TURN from what the engine will actually accept
(``engine/game/intents.py``), so an unreachable destination is unsamplable
rather than merely wrong. The verbs branch rather than crossing one action enum
with one target enum, because a flat cross-product would make
``{"action": "travel", "target": "persuasion"}`` legal grammar.

``intent`` is omitted entirely when the engine can honour nothing in this state
-- a story with no travel graph, no dice and no economy gets the schema it
always had, byte for byte.

Version: v0.3.0 [2026-08-14]
"""

from __future__ import annotations

from typing import Any, Iterable

# The personas ask for 100-200 words; these are the GRAMMAR's bounds, not the
# target. The max leaves ~1.5x headroom over the guidance (1800 chars is ~300
# words at 5.5-6 chars/word) so the schema never cuts a sentence the model was
# finishing -- storyteller.py treats landing exactly on maxLength as a grammar
# cut. The min keeps a beat from collapsing to a single sentence.
# tests/test_prompt_schema_coherence.py asserts guidance and caps agree.
NARRATION_MIN_CHARS = 220
NARRATION_MAX_CHARS = 1800

CHOICE_HINTS = ["safe", "risky", "costly", "unknown"]
MOODS = ["calm", "uneasy", "tense", "dread", "warm", "wry"]


def intent_schema(intents: Iterable[Any]) -> dict[str, Any] | None:
    """
    The ``intent`` sub-schema for a choice, or None when there is nothing legal.

    One branch per verb, discriminated by a ``const`` action. Branching is what
    keeps the guarantee exact: with a single ``action`` enum beside a single
    ``target`` enum, every verb's targets would be legal for every other verb,
    and "unreachable destinations are unsamplable" would quietly become
    "unreachable destinations are caught later, if someone remembers".

    Args:
        intents: Verb objects from ``engine.game.intents.legal_intents``. Duck
            typed on ``.action``, ``.targets`` and ``.extra`` so this module
            keeps knowing nothing about the game.

    Returns:
        A JSON schema, or None if no verb is legal right now.
    """
    branches: list[dict[str, Any]] = []
    for verb in intents:
        action = str(getattr(verb, "action", "") or "")
        if not action:
            continue
        properties: dict[str, Any] = {"action": {"const": action}}
        required = ["action"]

        targets = [str(t) for t in getattr(verb, "targets", ()) if str(t)]
        if targets:
            properties["target"] = {"enum": targets}
            required.append("target")

        for name, values in (getattr(verb, "extra", None) or {}).items():
            allowed = [str(v) for v in values if str(v)]
            if allowed:
                properties[str(name)] = {"enum": allowed}

        branches.append(
            {
                "type": "object",
                "additionalProperties": False,
                "required": required,
                "properties": properties,
            }
        )

    if not branches:
        return None
    # A single legal verb needs no alternation. Emitting a one-element anyOf
    # would be correct but puts a pointless choice point in the grammar.
    return branches[0] if len(branches) == 1 else {"anyOf": branches}


def storyteller_turn_schema(
    *,
    npc_ids: Iterable[str] = (),
    intents: Iterable[Any] = (),
    min_narration: int = NARRATION_MIN_CHARS,
    max_narration: int = NARRATION_MAX_CHARS,
) -> dict[str, Any]:
    """
    Build the per-turn narration schema.

    Args:
        npc_ids: NPCs present. Constrains npc_voices so the model cannot voice
            someone who is not in the scene. Omitted entirely when empty --
            an empty enum is unsatisfiable and would make the whole object
            impossible to sample.
        intents: What the engine will accept from a choice this turn, from
            ``engine.game.intents.legal_intents``. Empty adds no property at
            all, which is how a story the engine can honour nothing for keeps
            the exact schema it had.
    """
    npc_voice_props: dict[str, Any] = {
        "line": {"type": "string", "maxLength": 220},
    }
    ids = [i for i in npc_ids if i]
    npc_voice_props["npc_id"] = {"enum": ids} if ids else {"type": "string"}

    choice_props: dict[str, Any] = {
        "id": {"enum": ["a", "b", "c", "d"]},
        "text": {"type": "string", "maxLength": 100},
        "hint": {"enum": CHOICE_HINTS},
    }
    intent = intent_schema(intents)
    if intent is not None:
        choice_props["intent"] = intent

    return {
        "name": "storyteller_turn",
        "strict": True,
        "schema": {
            "type": "object",
            "additionalProperties": False,
            # narration first: it streams before anything else is generated.
            "required": ["narration", "choices"],
            "properties": {
                "narration": {
                    "type": "string",
                    "minLength": min_narration,
                    "maxLength": max_narration,
                },
                "choices": {
                    "type": "array",
                    "minItems": 2,
                    "maxItems": 4,
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["id", "text"],
                        "properties": choice_props,
                    },
                },
                "npc_voices": {
                    "type": "array",
                    "maxItems": 3,
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["npc_id", "line"],
                        "properties": npc_voice_props,
                    },
                },
                "ledger_delta": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "facts": {
                            "type": "array",
                            "maxItems": 3,
                            "items": {
                                "type": "object",
                                "additionalProperties": False,
                                "required": ["text"],
                                "properties": {
                                    "text": {"type": "string", "maxLength": 140},
                                    "subject_id": {"type": "string"},
                                },
                            },
                        },
                        "names": {"type": "object"},
                        "npc_disposition": {"type": "object"},
                        "promises": {
                            "type": "array",
                            "maxItems": 1,
                            "items": {
                                "type": "object",
                                "additionalProperties": False,
                                "required": ["text"],
                                "properties": {
                                    "text": {"type": "string", "maxLength": 140},
                                    "from_id": {"type": "string"},
                                    "to_id": {"type": "string"},
                                    "due_day": {"type": "integer"},
                                },
                            },
                        },
                    },
                },
                "mood": {"enum": MOODS},
                "image_tag": {"type": "string", "maxLength": 64},
            },
        },
    }


ASSISTANT_TURN_SCHEMA: dict[str, Any] = {
    "name": "assistant_line",
    "strict": True,
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "required": ["text"],
        "properties": {
            # Hard cap enforces the "1-3 sentences" voice rule that prose alone
            # never reliably holds.
            "text": {"type": "string", "maxLength": 240},
            "voice_style": {"enum": ["whisper", "urgent", "flat", "amused"]},
        },
    },
}


def response_format(schema: dict[str, Any]) -> dict[str, Any]:
    """Wrap a schema in the OpenAI response_format envelope."""
    return {"type": "json_schema", "json_schema": schema}
