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

WITHOUT THE GRAMMAR (v0.19.0)
-----------------------------
Everything above holds while the schema is ON THE WIRE (rung 1 of the
structured-output ladder, ``backend.structured_output``). On a rung without it
the same schema does two other jobs: ``render_format_block`` puts it in the
prompt as text, and ``conform`` holds the parsed reply to it -- an undeclared
key dropped, a choice whose intent the engine did not offer dropped whole --
so "unsamplable" becomes "never offered", and nothing the model invents is run.

Version: v0.3.0 [2026-08-14]
"""

from __future__ import annotations

import json
import logging
from typing import Any, Iterable, Optional

logger = logging.getLogger(__name__)

# The personas ask for 100-200 words; these are the GRAMMAR's bounds, not the
# target. The max leaves ~1.5x headroom over the guidance (1800 chars is ~300
# words at 5.5-6 chars/word) so the schema never cuts a sentence the model was
# finishing -- storyteller.py treats landing exactly on maxLength as a grammar
# cut. The min keeps a beat from collapsing to a single sentence.
# tests/test_prompt_schema_coherence.py asserts guidance and caps agree.
NARRATION_MIN_CHARS = 220
NARRATION_MAX_CHARS = 1800

CHOICE_HINTS = ["safe", "risky", "costly", "unknown"]


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
    intents: Iterable[Any] = (),
    min_narration: int = NARRATION_MIN_CHARS,
    max_narration: int = NARRATION_MAX_CHARS,
) -> dict[str, Any]:
    """
    Build the per-turn narration schema.

    THREE FIELDS ARE GONE, as of v0.8.0: ``npc_voices``, ``mood`` and
    ``image_tag``. All three were sampled on every turn -- output tokens on a
    local model -- and read by nothing: the parser only ``setdefault``-ed
    them, no client code rendered them, and media takes its tags inline. The
    flagship's own few-shot showed why ``npc_voices`` was redundant rather than
    lost: its one line was a copy of dialogue already in the narration.

    Args:
        intents: What the engine will accept from a choice this turn, from
            ``engine.game.intents.legal_intents``. Empty adds no property at
            all, which is how a story the engine can honour nothing for keeps
            the exact schema it had.
    """
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


# -- without the grammar: the shape as text, and the reply held to it ----------


def _body(schema: dict[str, Any]) -> dict[str, Any]:
    """The JSON schema itself, from a bare schema or a ``{name, schema}`` envelope."""
    if isinstance(schema, dict) and "schema" in schema and "name" in schema:
        inner = schema.get("schema")
        return inner if isinstance(inner, dict) else {}
    return schema if isinstance(schema, dict) else {}


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _one_of(values: Iterable[Any]) -> str:
    return "one of " + ", ".join(_json(v) for v in values)


def _describe(prop: dict[str, Any]) -> str:
    """One property's constraint, in a few words."""
    if "const" in prop:
        return f"exactly {_json(prop['const'])}"
    if "enum" in prop:
        return _one_of(prop["enum"])
    kind = prop.get("type")
    if kind == "string":
        low, high = prop.get("minLength"), prop.get("maxLength")
        if low is not None and high is not None:
            return f"text, {low}-{high} characters"
        if high is not None:
            return f"text, at most {high} characters"
        if low is not None:
            return f"text, at least {low} characters"
        return "text"
    if kind in ("integer", "number"):
        noun = "a whole number" if kind == "integer" else "a number"
        low, high = prop.get("minimum"), prop.get("maximum")
        if low is not None and high is not None:
            return f"{noun} from {low} to {high}"
        return noun
    if kind == "boolean":
        return "true or false"
    if kind == "array":
        low, high = prop.get("minItems"), prop.get("maxItems")
        count = (
            f"{low}-{high} " if low is not None and high is not None
            else f"up to {high} " if high is not None
            else ""
        )
        items = prop.get("items") if isinstance(prop.get("items"), dict) else {}
        if items.get("type") == "object" or "properties" in items:
            noun = "object" if high == 1 else "objects"
            return f"a list of {count}{noun}, each:"
        return f"a list of {count}{_describe(items) if items else 'values'}"
    if "anyOf" in prop:
        return "one of these objects:"
    if _is_branch(prop):
        return "this object:"
    if kind == "object" or "properties" in prop:
        return "an object:" if prop.get("properties") else "an object"
    return "any value"


def _branch_line(branch: dict[str, Any]) -> str:
    """One ``anyOf`` object branch as a single line: ``{"action": "travel", ...}``."""
    parts = []
    for key, prop in (branch.get("properties") or {}).items():
        if "const" in prop:
            parts.append(f"{_json(key)}: {_json(prop['const'])}")
        elif "enum" in prop:
            parts.append(f"{_json(key)}: {' | '.join(_json(v) for v in prop['enum'])}")
        else:
            parts.append(f"{_json(key)}: <{_describe(prop)}>")
    return "{" + ", ".join(parts) + "}"


def _is_branch(prop: dict[str, Any]) -> bool:
    """A closed object discriminated by a ``const`` -- one intent verb's shape."""
    return any(
        isinstance(p, dict) and "const" in p for p in (prop.get("properties") or {}).values()
    )


def _render_object(schema: dict[str, Any], depth: int) -> list[str]:
    lines: list[str] = []
    pad = "  " * depth
    required = set(schema.get("required") or ())
    for key, prop in (schema.get("properties") or {}).items():
        if not isinstance(prop, dict):
            continue
        need = "required" if key in required else "optional"
        lines.append(f"{pad}- {_json(key)} ({need}): {_describe(prop)}")
        if "anyOf" in prop:
            lines += [f"{pad}  - {_branch_line(b)}" for b in prop["anyOf"] if isinstance(b, dict)]
        elif _is_branch(prop):
            lines.append(f"{pad}  - {_branch_line(prop)}")
        elif prop.get("properties"):
            lines += _render_object(prop, depth + 1)
        elif prop.get("type") == "array":
            items = prop.get("items") if isinstance(prop.get("items"), dict) else {}
            if items.get("properties"):
                lines += _render_object(items, depth + 1)
    if schema.get("additionalProperties") is False and lines:
        lines.append(f"{pad}(no other keys)")
    return lines


def render_format_block(schema: dict[str, Any]) -> str:
    """
    The schema as text, for a request whose grammar is not on the wire (§4.2).

    On rungs 2 and 3 the server enforces no shape, and the prompt side says
    "the JSON schema carries the contract" -- true only while the schema is on
    the wire. Without it the model writes prose, and the authored choices
    collapse to the generic fallback. So the contract travels as text: the
    envelope's keys, whether each is required, the choice ids, the hint
    values, and for each intent verb the targets that are legal THIS turn.

    Deterministic: the same schema renders the same block, byte for byte.
    """
    body = _body(schema)
    lines = [
        "OUTPUT FORMAT -- the server is not enforcing it, so follow it exactly.",
        "Reply with ONE JSON object and nothing else: no prose around it, no code fence.",
        "Its keys:",
    ]
    lines += _render_object(body, 0)
    return "\n".join(lines)


def _enum_ok(prop: dict[str, Any], value: Any) -> bool:
    if "const" in prop and value != prop["const"]:
        return False
    if "enum" in prop and value not in prop["enum"]:
        return False
    return True


def _branch_ok(branch: dict[str, Any], value: Any) -> bool:
    """Whether ``value`` satisfies one closed object branch of an intent schema."""
    if not isinstance(value, dict):
        return False
    props = branch.get("properties") or {}
    if branch.get("additionalProperties") is False and set(value) - set(props):
        return False
    if any(key not in value for key in branch.get("required") or ()):
        return False
    return all(_enum_ok(props[k], v) for k, v in value.items() if k in props)


def intent_legal(intent_prop: Optional[dict[str, Any]], intent: Any) -> bool:
    """Whether a choice's ``intent`` is one the turn's intent schema allows."""
    if not isinstance(intent_prop, dict):
        return False
    branches = intent_prop.get("anyOf") or [intent_prop]
    return any(_branch_ok(b, intent) for b in branches if isinstance(b, dict))


#: Where a narration turn keeps what ``conform`` took off it
#: (``storyteller.conform_turn``): the model's CLAIMS, which the turn must not
#: act on but the audits must still see.
CONFORMED_AWAY = "conformed_away"


def claimed(parsed: Any, key: str) -> Any:
    """
    What the model claimed under ``key``: the key itself, else what ``conform``
    took away from it.

    ``stat_changes`` and ``skill_check`` are not in the turn schema, so on a
    rung without the grammar ``conform`` drops them before anything reads the
    turn. They are exactly what governance R003 and the evaluator's
    "a check requested, no roll made" gate exist to catch, so those two read
    the claim through here: dropped from the turn, never from the audit.
    """
    if not isinstance(parsed, dict):
        return None
    value = parsed.get(key)
    if value in (None, {}, [], ""):
        away = parsed.get(CONFORMED_AWAY)
        if isinstance(away, dict) and key in away:
            return away[key]
    return value


def conform(
    parsed: dict[str, Any],
    schema: dict[str, Any],
    *,
    fallback: Iterable[dict[str, Any]] = (),
    keep: Iterable[str] = (),
) -> dict[str, Any]:
    """
    Hold a parsed reply to the schema that was built for it (§4.4).

    Without the grammar on the wire (rungs 2 and 3) the model can write what
    the schema forbids. This drops, each with a log line naming it:

    * any top-level key the schema does not declare (``keep`` excepted: the
      engine's own bookkeeping keys, which the model never wrote);
    * a declared top-level key whose value is outside its ``enum`` -- an
      ``npc_id`` naming someone who is not present, where one is declared;
    * any WHOLE choice whose ``intent`` has a verb or a target outside this
      turn's enums. Stripping only the intent would leave a choice whose text
      promises a walk no mechanic performs and nothing refuses -- itself a
      rule-1 breach -- so the choice goes, and is never offered;
    * a choice key the schema does not declare, and a ``hint`` outside its
      enum (the key, not the choice);
    * inside ``ledger_delta``, exactly what ``apply_ledger_delta`` would
      refuse, and nothing it would take (``_conform_ledger_delta``): the
      ledger, not the schema's stricter wording, is where that key lands, so
      a fact written as plain text or a promise due on day ``"3"`` is kept
      (coerced where the ledger coerces) rather than lost before the ledger
      could read it;
    * inside every other declared key, recursively: a value of the wrong
      type, an undeclared key of a closed object, an object missing a
      required key, and list items past ``maxItems`` (``_conform_value``).

    If fewer choices survive than the schema's ``minItems`` (two), the list is
    topped up from ``fallback`` -- rows that carry no intent -- and if more
    than its ``maxItems`` (four) survive, it is cut there; either way every
    choice is renumbered a, b, c.

    On rung 1 the grammar has already made all of this unsamplable, so the
    result equals the input. Never raises, and never mutates ``parsed``.
    """
    body = _body(schema)
    props = body.get("properties") or {}
    if not isinstance(parsed, dict) or not props:
        return parsed
    kept = set(keep)
    out: dict[str, Any] = {}
    for key, value in parsed.items():
        if key in kept:
            out[key] = value
            continue
        prop = props.get(key)
        if prop is None:
            if body.get("additionalProperties") is False:
                logger.warning(
                    "[schemas] Dropped a key the turn schema does not declare "
                    "(operation=conform, key=%s)",
                    key,
                )
                continue
            out[key] = value
            continue
        if isinstance(prop, dict) and not _enum_ok(prop, value):
            logger.warning(
                "[schemas] Dropped a value outside its enum (operation=conform, "
                "key=%s, value=%r)",
                key,
                value,
            )
            continue
        if key == "ledger_delta":
            value = _conform_ledger_delta(value)
            if value is _DROP:
                continue
        elif key != "choices" and isinstance(prop, dict):
            value = _conform_value(value, prop, key)
            if value is _DROP:
                continue
        out[key] = value

    choices_prop = props.get("choices")
    if isinstance(choices_prop, dict) and "choices" in out:
        out["choices"] = _conform_choices(out["choices"], choices_prop, list(fallback))
    return out


#: What ``_conform_value`` returns for a value that does not fit at all.
_DROP = object()

_TYPES: dict[str, tuple[type, ...]] = {
    "string": (str,),
    "integer": (int,),
    "number": (int, float),
    "boolean": (bool,),
    "object": (dict,),
    "array": (list,),
}


def _type_ok(value: Any, prop: dict[str, Any]) -> bool:
    kind = prop.get("type")
    if not isinstance(kind, str) or kind not in _TYPES:
        return True
    if isinstance(value, bool) and kind in ("integer", "number"):
        return False
    return isinstance(value, _TYPES[kind])


def _conform_value(value: Any, prop: dict[str, Any], path: str) -> Any:
    """
    ``value`` held to ``prop``, recursively: the nested half of ``conform``.

    A value of the wrong type (or outside its enum) is ``_DROP``. An object
    loses keys it does not declare when closed, and fails whole if a
    ``required`` key is gone; an array loses the items that do not fit and is
    cut to ``maxItems``. Each drop is logged with its path. A value that fits
    comes back equal to itself, so rung 1 is untouched.
    """
    if not _type_ok(value, prop) or not _enum_ok(prop, value):
        logger.warning(
            "[schemas] Dropped a value of the wrong shape (operation=conform, "
            "path=%s, value=%r)",
            path,
            value,
        )
        return _DROP
    if isinstance(value, dict) and isinstance(prop.get("properties"), dict):
        props = prop["properties"]
        closed = prop.get("additionalProperties") is False
        out: dict[str, Any] = {}
        for key, item in value.items():
            inner = props.get(key)
            if not isinstance(inner, dict):
                if closed:
                    logger.warning(
                        "[schemas] Dropped a key the schema does not declare "
                        "(operation=conform, path=%s.%s)",
                        path,
                        key,
                    )
                    continue
                out[key] = item
                continue
            kept = _conform_value(item, inner, f"{path}.{key}")
            if kept is not _DROP:
                out[key] = kept
        missing = [k for k in prop.get("required") or () if k not in out]
        if missing:
            logger.warning(
                "[schemas] Dropped an object missing a required key "
                "(operation=conform, path=%s, missing=%s)",
                path,
                missing,
            )
            return _DROP
        return out
    if isinstance(value, list) and isinstance(prop.get("items"), dict):
        items = []
        for index, item in enumerate(value):
            kept = _conform_value(item, prop["items"], f"{path}[{index}]")
            if kept is not _DROP:
                items.append(kept)
        maximum = prop.get("maxItems")
        if isinstance(maximum, int) and len(items) > maximum:
            logger.warning(
                "[schemas] Cut a list to its maxItems (operation=conform, path=%s, "
                "had=%s, max=%s)",
                path,
                len(items),
                maximum,
            )
            items = items[:maximum]
        return items
    return value


#: The keys ``apply_ledger_delta`` reads, and the container each must be.
_LEDGER_SHAPES: dict[str, type] = {
    "facts": list,
    "names": dict,
    "promises": list,
    "npc_disposition": dict,
}
#: ``apply_ledger_delta`` reads only the first promise (``[:1]``).
_LEDGER_PROMISES = 1


def _ledger_int(value: Any) -> Optional[int]:
    """``int(value)`` as the ledger takes it, or None where the ledger's raises."""
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return None


def _ledger_drop(path: str, value: Any) -> None:
    logger.warning(
        "[schemas] Dropped a ledger entry the ledger would refuse "
        "(operation=conform, path=%s, value=%r)",
        path,
        value,
    )


def _conform_ledger_delta(delta: Any) -> Any:
    """
    ``ledger_delta`` held to what ``engine.memory.ledger.apply_ledger_delta``
    accepts -- exactly: nothing it takes is dropped, and nothing it refuses
    survives. Where the ledger coerces (``str`` a fact's text, ``int`` a due
    day or a disposition) the value is coerced here, so what the turn carries
    is what the ledger will record. It mirrors the ledger's order too: the
    ledger reads the first three facts and the first promise, THEN skips the
    bad ones, so the list is cut before it is filtered.

    Kept in step with the ledger by ``tests/test_turn_conform.py``, which
    applies each shape both ways and compares the ledgers.
    """
    from engine.memory.ledger import MAX_FACTS_PER_TURN

    if not isinstance(delta, dict):
        _ledger_drop("ledger_delta", delta)
        return _DROP
    out: dict[str, Any] = {}
    for key, value in delta.items():
        kind = _LEDGER_SHAPES.get(key)
        if kind is None or (value is not None and not isinstance(value, kind)):
            _ledger_drop(f"ledger_delta.{key}", value)
            continue
        if value is None:
            continue  # the ledger reads it as empty
        if key == "facts":
            facts: list[Any] = []
            for index, raw in enumerate(value[:MAX_FACTS_PER_TURN]):
                if isinstance(raw, str):
                    text, row = raw, raw
                elif isinstance(raw, dict):
                    text = str(raw.get("text", ""))
                    row = {"text": text}
                    if "subject_id" in raw:
                        row["subject_id"] = str(raw["subject_id"])
                else:
                    text, row = "", None
                if row is None or not text.strip():
                    _ledger_drop(f"ledger_delta.facts[{index}]", raw)
                    continue
                facts.append(row)
            out[key] = facts
        elif key == "names":
            out[key] = {str(name): str(gloss) for name, gloss in value.items()}
        elif key == "npc_disposition":
            moves: dict[str, int] = {}
            for npc_id, raw in value.items():
                number = _ledger_int(raw)
                if number is None:
                    _ledger_drop(f"ledger_delta.npc_disposition.{npc_id}", raw)
                    continue
                moves[npc_id] = number
            out[key] = moves
        else:  # promises
            promises: list[dict[str, Any]] = []
            for index, raw in enumerate(value[:_LEDGER_PROMISES]):
                # `add_promise` refuses a promise with no text.
                if not isinstance(raw, dict) or not str(raw.get("text", "")).strip():
                    _ledger_drop(f"ledger_delta.promises[{index}]", raw)
                    continue
                row = {
                    name: str(raw[name])
                    for name in ("text", "from_id", "to_id")
                    if name in raw
                }
                due = raw.get("due_day")
                if due is not None:
                    # The ledger records a bool or an unreadable day as no day.
                    number = None if isinstance(due, bool) else _ledger_int(due)
                    if number is None:
                        _ledger_drop(f"ledger_delta.promises[{index}].due_day", due)
                    else:
                        row["due_day"] = number
                promises.append(row)
            out[key] = promises
    return out


def _conform_choices(
    choices: Any, choices_prop: dict[str, Any], fallback: list[dict[str, Any]]
) -> Any:
    items = choices_prop.get("items") if isinstance(choices_prop.get("items"), dict) else {}
    item_props = items.get("properties") or {}
    closed = items.get("additionalProperties") is False
    if not isinstance(choices, list):
        choices = []
    survivors: list[Any] = []
    changed = False
    for choice in choices:
        if not isinstance(choice, dict):
            survivors.append(choice)  # malformed rows are _positional_ids' to drop
            continue
        if "intent" in choice and choice["intent"] is not None and not intent_legal(
            item_props.get("intent"), choice["intent"]
        ):
            logger.warning(
                "[schemas] Dropped a whole choice: its intent is not one the "
                "engine offered this turn, so it is never shown and never run "
                "(operation=conform, intent=%s, text=%r)",
                _json(choice["intent"]),
                str(choice.get("text", ""))[:60],
            )
            changed = True
            continue
        row = dict(choice)
        for key in list(row):
            if closed and key not in item_props:
                logger.warning(
                    "[schemas] Dropped a choice key the schema does not declare "
                    "(operation=conform, key=%s)",
                    key,
                )
                del row[key]
                changed = True
            elif key == "hint" and key in item_props and not _enum_ok(item_props[key], row[key]):
                logger.warning(
                    "[schemas] Dropped a choice hint outside its enum "
                    "(operation=conform, hint=%r)",
                    row[key],
                )
                del row[key]
                changed = True
        survivors.append(row)

    minimum = int(choices_prop.get("minItems") or 0)
    usable = [c for c in survivors if isinstance(c, dict) and str(c.get("text") or "").strip()]
    if len(usable) < minimum:
        texts = {str(c.get("text", "")).strip().lower() for c in usable}
        for row in fallback:
            if len(usable) >= minimum:
                break
            if str(row.get("text", "")).strip().lower() in texts:
                continue
            usable.append(dict(row))
            texts.add(str(row.get("text", "")).strip().lower())
        logger.warning(
            "[schemas] Topped the choices up from the fallback rows "
            "(operation=conform, kept=%s, now=%s)",
            len(survivors),
            len(usable),
        )
        survivors = usable
        changed = True
    maximum = choices_prop.get("maxItems")
    usable = [c for c in survivors if isinstance(c, dict) and str(c.get("text") or "").strip()]
    if isinstance(maximum, int) and len(usable) > maximum:
        logger.warning(
            "[schemas] Cut the choices to the schema's maxItems; the client's "
            "shortcuts cover that many (operation=conform, had=%s, max=%s, cut=%r)",
            len(usable),
            maximum,
            [str(c.get("text", ""))[:40] for c in usable[maximum:]],
        )
        survivors = usable[:maximum]
        changed = True
    if not changed:
        return choices
    ids = [str(v) for v in (item_props.get("id") or {}).get("enum") or ()]
    renumbered = []
    for index, choice in enumerate(survivors):
        if isinstance(choice, dict):
            choice = dict(choice)
            choice["id"] = ids[index] if index < len(ids) else chr(ord("a") + index)
        renumbered.append(choice)
    return renumbered
