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
(stat_changes, items_gained, items_lost, skill_check) are gone. Every
mechanical effect goes through a tool call. Removing them removes the
incentive to try.

Version: v0.2.0 [2026-08-07]
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


def storyteller_turn_schema(
    *,
    npc_ids: Iterable[str] = (),
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
    """
    npc_voice_props: dict[str, Any] = {
        "line": {"type": "string", "maxLength": 220},
    }
    ids = [i for i in npc_ids if i]
    npc_voice_props["npc_id"] = {"enum": ids} if ids else {"type": "string"}

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
                        "properties": {
                            "id": {"enum": ["a", "b", "c", "d"]},
                            "text": {"type": "string", "maxLength": 100},
                            "hint": {"enum": CHOICE_HINTS},
                        },
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
