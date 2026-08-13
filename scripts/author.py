"""
LLM-Assisted Story Authoring
============================

Draft story content as VALID YAML, with the model on a leash:

    .\\.venv\\Scripts\\python.exe scripts\\author.py --game my-story --draft item --brief brief.txt
    .\\.venv\\Scripts\\python.exe scripts\\author.py --game my-story --draft location --brief - --count 2
    .\\.venv\\Scripts\\python.exe scripts\\author.py --game my-story --from-bible bible.md
    .\\.venv\\Scripts\\python.exe scripts\\author.py --game my-story --repair
    .\\.venv\\Scripts\\python.exe scripts\\author.py --game my-story --promote all

THE CONTRACT. Everything the model produces is (1) sampled under a JSON schema
derived from what the LOADERS accept, (2) converted to the loader's YAML shape
by this tool, never by the model, (3) validated by the SHARED backbone
(``engine/games/validation.py``) against the drafts and the live content
together, and (4) written only under ``games/<slug>/data/drafts/`` -- which
validation ignores (``DRAFTS_DIRNAME``) -- until ``--promote`` moves it into
the live tree, and ``--promote`` refuses while any error stands.

WHY THE SCHEMAS MIRROR THE LOADERS AND NOT THE DOCS. The loaders are forgiving
by design: a location without a ring is logged and dropped, an item without a
name is an error the player never sees explained. A drafting tool that leaned
on that forgiveness would produce files that load into silence. So each
per-kind schema requires exactly what the loader needs to NOT drop the entry
(``engine/game/locations.py``, ``engine/game/inventory.py``,
``engine/content/deck.py``, ``engine/game/quests.py``,
``engine/game/encounter.py``), and enum-constrains what the validator would
reject: skills and bands to the story's own vocabulary, quest arcs to
``arcs.yaml``, effect targets to the values ``state.yaml`` declares -- the
same trick ``engine/lmstudio/schemas.py`` plays with per-turn npc ids.

HOW VALIDATION SEES DRAFTS. ``validate_story`` takes a manifest, so the tool
builds a SYNTHETIC one: drafts are staged into a temp directory merged with
the live content (single-file kinds merge into a copy of the live file,
directory kinds sit beside copies of the live files), the synthetic manifest's
paths point at the staged tree, and the real story root supplies state.yaml,
agents.yaml and the canon dictionary. Nothing is activated; the live tree is
never touched.

THE REPAIR LOOP. Each error the backbone reports is attributed to the draft
that owns the offending id (or staged file), fed back to the model with the
draft's own YAML, and the corrected draft rewritten -- at most
``MAX_REPAIR_ATTEMPTS`` per file, then the tool reports what still fails
instead of arguing with the model forever.

LOCAL-FIRST, OFFLINE-TESTABLE. Inference goes through the engine's own
``engine/lmstudio/backend.py`` (structured output rides the OpenAI-compatible
transport; the profile supplies model, lane and temperature defaults; the
``small`` profile's utility lane for small kinds, ``big`` for the ones that
need room). The backend is INJECTED -- ``Author(slug, backend=...)`` -- and
every test supplies a fake, so a live LM Studio is a runtime nicety, never a
test dependency. The schema is always sent: an authoring tool without a
grammar is a tool that writes prose into YAML files, so this tool does not
consult ``lmstudio.structured_output`` mode the way a turn does.

THE TOOL NEVER TOUCHES ``engine/`` OR ANOTHER STORY'S TREE. It reads the
registry read-only (``registry.get``; never ``activate``), writes only under
``games/<slug>/data/drafts/`` -- and, on ``--promote``, into the target story's
own declared paths.

Version: v0.1.0 [2026-08-14]
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import logging
import pathlib
import re
import shutil
import sys
import tempfile
from dataclasses import dataclass, field
from typing import Any, Callable, Iterator, Optional

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import yaml  # noqa: E402

from engine.games import registry, validation  # noqa: E402
from engine.games.manifest import GameManifest, from_dict  # noqa: E402
from engine.games.validation import DRAFTS_DIRNAME, Issue  # noqa: E402

logger = logging.getLogger(__name__)

#: Where drafts live, relative to the story root. Validation skips any
#: ``drafts/`` directory (validation.DRAFTS_DIRNAME), so nothing here can leak
#: into a build until --promote moves it.
DRAFTS_REL = pathlib.Path("data") / DRAFTS_DIRNAME

#: The repair loop's per-file cap. Three is enough for "you misspelled the
#: item id"; a model still failing after three has misunderstood the shape,
#: and the author should read the report rather than pay for a fourth try.
MAX_REPAIR_ATTEMPTS = 3

#: Deterministic-ish by default. Authoring wants the same brief to land in
#: the same neighbourhood; raise it from the CLI when you want surprise.
DEFAULT_TEMPERATURE = 0.4

#: One reprompt when the content channel is not valid JSON. With the grammar
#: sent this should never fire; without grammar support on the server it is
#: the difference between a tool and a coin flip.
_JSON_RETRIES = 1

#: How many known ids of each family the prompt carries. Ids are context
#: discipline: enough for the model to reference real things, not the
#: flagship's entire registry pasted into every call.
_MAX_CONTEXT_IDS = 60


class AuthorError(RuntimeError):
    """The tool cannot proceed; the message says what to change."""


# ---------------------------------------------------------------------------
# Kinds
# ---------------------------------------------------------------------------

#: container values:
#:   dir         one draft file copied into the declared directory
#:   file        draft entries merged into the declared single file
#:   rules_file  spoilers.yaml, found by fixed name inside paths.rules
#:   deck_cards  cards appended into an existing deck file under paths.decks
@dataclass(frozen=True)
class KindSpec:
    kind: str
    path_key: str
    container: str
    profile: str = "big"
    max_tokens: int = 3000
    suffix: str = ".yaml"
    top_key: str = ""  # merge key for file containers


KINDS: dict[str, KindSpec] = {
    "location": KindSpec("location", "locations", "file", top_key="locations"),
    "npc": KindSpec("npc", "npc_schedules", "file", top_key="npcs"),
    "item": KindSpec("item", "items", "dir", profile="small", max_tokens=1400),
    "quest": KindSpec("quest", "quests", "dir"),
    "deck": KindSpec("deck", "decks", "dir", max_tokens=4000),
    "card": KindSpec("card", "decks", "deck_cards", max_tokens=2500),
    "encounter": KindSpec("encounter", "encounters", "dir", max_tokens=3500),
    "rumor": KindSpec("rumor", "world_rumors", "file", profile="small", max_tokens=1200, top_key="rumors"),
    "lore": KindSpec("lore", "lore", "dir", suffix=".md"),
    "prompt": KindSpec("prompt", "prompts", "dir", suffix=".md"),
    "spoilers": KindSpec("spoilers", "rules", "rules_file", profile="small", max_tokens=1000, top_key="spoilers"),
}


# ---------------------------------------------------------------------------
# Vocabulary -- the ids a draft may reference, live and already-drafted
# ---------------------------------------------------------------------------


@dataclass
class Vocabulary:
    """Ids only, never bodies -- this is what keeps the prompts lean."""

    locations: set[str] = field(default_factory=set)
    items: set[str] = field(default_factory=set)
    npcs: set[str] = field(default_factory=set)
    factions: set[str] = field(default_factory=set)
    values: set[str] = field(default_factory=set)
    clocks: set[str] = field(default_factory=set)
    arcs: set[str] = field(default_factory=set)
    decks: set[str] = field(default_factory=set)
    skills: frozenset[str] = frozenset()
    bands: frozenset[str] = frozenset()


def _load_yaml(path: pathlib.Path) -> Any:
    try:
        with path.open(encoding="utf-8") as handle:
            return yaml.safe_load(handle)
    except (OSError, yaml.YAMLError) as exc:
        logger.warning("[author] Unreadable YAML (operation=_load_yaml, path=%s): %s", path, exc)
        return None


def _declared(manifest: GameManifest, key: str) -> Optional[pathlib.Path]:
    rel = str(manifest.paths.get(key) or "").strip()
    return manifest.resolve(rel) if rel else None


# ---------------------------------------------------------------------------
# JSON schema builders -- one per kind, mirroring the loaders
# ---------------------------------------------------------------------------

_ID_PATTERN = "^[a-z][a-z0-9_]*$"


def _id_schema() -> dict[str, Any]:
    return {"type": "string", "minLength": 2, "maxLength": 48, "pattern": _ID_PATTERN}


def _enum_or_string(values: set[str] | frozenset[str]) -> dict[str, Any]:
    """An enum when the vocabulary exists, a plain string when it does not.

    The npc-ids trick from engine/lmstudio/schemas.py: an empty enum is
    unsatisfiable and would make the whole object impossible to sample."""
    ordered = sorted(v for v in values if v)
    return {"enum": ordered} if ordered else {"type": "string"}


def _obj(properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": required,
        "properties": properties,
    }


def _envelope(name: str, schema: dict[str, Any]) -> dict[str, Any]:
    return {"name": name, "strict": True, "schema": schema}


def _predicate_schema(vocab: Vocabulary) -> dict[str, Any]:
    """The engine-evaluable subset of the shared predicate grammar.

    engine/game/quests.py evaluates more, but a draft that sticks to a place
    stood in, an item held and a flag set is a draft the engine can always
    resolve -- 'a stage the model can argue its way through is not a stage'."""
    return _obj(
        {
            "at_location": _enum_or_string(vocab.locations),
            "has_item": _enum_or_string(vocab.items),
            "flag": {"type": "string"},
        },
        [],
    )


def _effect_schema(vocab: Vocabulary) -> dict[str, Any]:
    """Effects a deck/card beat may carry, shaped for effects.apply_effect."""
    return _obj(
        {
            "type": {"enum": ["value", "flag", "item"]},
            "name": _enum_or_string(vocab.values | vocab.clocks),
            "delta": {"type": "number"},
            "flag": {"type": "string"},
            "item_id": _enum_or_string(vocab.items),
            "qty": {"type": "integer", "minimum": 1, "maximum": 9},
        },
        ["type"],
    )


def _card_schema(vocab: Vocabulary) -> dict[str, Any]:
    """One deck card the way engine/content/deck.py binds it."""
    when = _obj(
        {
            "value": _obj(
                {"name": _enum_or_string(vocab.values | vocab.clocks), "min": {"type": "number"}, "max": {"type": "number"}},
                ["name"],
            ),
            "flag": {"type": "string"},
        },
        [],
    )
    gate = _obj(
        {
            "when": when,
            "check": _obj(
                {"stream": {"enum": ["beat"]}, "chance": {"type": "number", "minimum": 0, "maximum": 1}},
                ["stream", "chance"],
            ),
            "on_pass": _obj(
                {"text": {"type": "string", "maxLength": 400}, "effects": {"type": "array", "maxItems": 3, "items": _effect_schema(vocab)}},
                ["text"],
            ),
            "on_fail": _obj(
                {"text": {"type": "string", "maxLength": 400}, "effects": {"type": "array", "maxItems": 3, "items": _effect_schema(vocab)}},
                ["text"],
            ),
        },
        ["on_pass"],
    )
    band = _obj(
        {
            "value": _enum_or_string(vocab.values | vocab.clocks),
            "min": {"type": "number"},
            "max": {"type": "number"},
            "text": {"type": "string", "maxLength": 200},
        },
        ["value", "min", "max"],
    )
    beat = _obj(
        {
            "id": _id_schema(),
            "text": {"type": "string", "maxLength": 600},
            "gate": gate,
            "band": band,
        },
        ["id", "text"],
    )
    return _obj(
        {
            "id": _id_schema(),
            "title": {"type": "string", "maxLength": 120},
            "text": {"type": "string", "maxLength": 600},
            "required": {"type": "boolean"},
            "once": {"type": "boolean"},
            "weight": {"type": "number", "minimum": 0},
            "tags": {"type": "array", "maxItems": 4, "items": {"enum": ["sequence", "menu", "gm"]}},
            "when": when,
            "beats": {"type": "array", "minItems": 1, "maxItems": 6, "items": beat},
        },
        ["id", "title", "text", "tags", "beats"],
    )


def _schema_location(vocab: Vocabulary, count: int) -> dict[str, Any]:
    connection = _obj(
        {
            "to": {"type": "string"},
            "hours": {"type": "integer", "minimum": 0, "maximum": 48},
            "danger_dc": {"type": "integer", "minimum": 0, "maximum": 30},
            "awareness_delta": {"type": "integer", "minimum": -10, "maximum": 10},
        },
        ["to", "hours"],
    )
    location = _obj(
        {
            "id": _id_schema(),
            "name": {"type": "string", "minLength": 2, "maxLength": 80},
            "ring": {"type": "integer", "minimum": 0, "maximum": 4},
            "summary": {"type": "string", "minLength": 40, "maxLength": 500},
            "tags": {"type": "array", "minItems": 1, "maxItems": 6, "items": {"type": "string"}},
            "evil_multiplier": {"type": "number", "minimum": 0.1, "maximum": 3.0},
            "connections": {"type": "array", "minItems": 1, "maxItems": 6, "items": connection},
        },
        ["id", "name", "ring", "summary", "tags", "connections"],
    )
    return _envelope(
        "author_location",
        _obj({"locations": {"type": "array", "minItems": count, "maxItems": max(count, 4), "items": location}}, ["locations"]),
    )


def _schema_npc(vocab: Vocabulary, count: int) -> dict[str, Any]:
    slot = _obj(
        {
            "hours": {"type": "array", "minItems": 1, "maxItems": 24, "items": {"type": "integer", "minimum": 0, "maximum": 23}},
            "location": _enum_or_string(vocab.locations),
            "activity": {"type": "string", "minLength": 5, "maxLength": 160},
            "available": {"type": "boolean"},
        },
        ["hours", "location", "activity"],
    )
    npc = _obj(
        {
            "id": _id_schema(),
            "name": {"type": "string", "minLength": 2, "maxLength": 60},
            "role": {"type": "string", "maxLength": 40},
            "home": _enum_or_string(vocab.locations),
            "routine": {"type": "array", "minItems": 1, "maxItems": 8, "items": slot},
        },
        ["id", "name", "role", "home", "routine"],
    )
    return _envelope(
        "author_npc",
        _obj({"npcs": {"type": "array", "minItems": count, "maxItems": max(count, 4), "items": npc}}, ["npcs"]),
    )


def _schema_item(vocab: Vocabulary, count: int) -> dict[str, Any]:
    item = _obj(
        {
            "id": _id_schema(),
            "name": {"type": "string", "minLength": 2, "maxLength": 60},
            "description": {"type": "string", "minLength": 20, "maxLength": 400},
            "tags": {"type": "array", "minItems": 1, "maxItems": 5, "items": {"type": "string"}},
            "weight": {"type": "number", "minimum": 0, "maximum": 50},
            "value": {"type": "integer", "minimum": 0, "maximum": 500},
            "stack": {"type": "boolean"},
        },
        ["id", "name", "description", "tags", "weight", "value"],
    )
    return _envelope(
        "author_item",
        _obj({"items": {"type": "array", "minItems": count, "maxItems": max(count, 6), "items": item}}, ["items"]),
    )


def _schema_quest(vocab: Vocabulary, count: int) -> dict[str, Any]:
    stage = _obj(
        {
            "id": _id_schema(),
            "objective": {"type": "string", "minLength": 10, "maxLength": 200},
            "complete_when": _obj(
                {"all": {"type": "array", "minItems": 1, "maxItems": 3, "items": _predicate_schema(vocab)}},
                ["all"],
            ),
            "complete_text": {"type": "string", "maxLength": 400},
        },
        ["id", "objective", "complete_when"],
    )
    return _envelope(
        "author_quest",
        _obj(
            {
                "id": _id_schema(),
                "arc": _enum_or_string(vocab.arcs),
                "name": {"type": "string", "minLength": 2, "maxLength": 80},
                "summary": {"type": "string", "minLength": 30, "maxLength": 500},
                "start_text": {"type": "string", "minLength": 30, "maxLength": 600},
                "stages": {"type": "array", "minItems": 1, "maxItems": 6, "items": stage},
                "complete_text": {"type": "string", "maxLength": 600},
            },
            ["id", "arc", "name", "summary", "start_text", "stages"],
        ),
    )


def _schema_deck(vocab: Vocabulary, count: int) -> dict[str, Any]:
    return _envelope(
        "author_deck",
        _obj(
            {
                "id": _id_schema(),
                "draw": {"type": "integer", "minimum": 0, "maximum": 8},
                "cards": {"type": "array", "minItems": 1, "maxItems": 8, "items": _card_schema(vocab)},
            },
            ["id", "draw", "cards"],
        ),
    )


def _schema_card(vocab: Vocabulary, count: int) -> dict[str, Any]:
    return _envelope(
        "author_card",
        _obj(
            {
                "deck_id": _enum_or_string(vocab.decks),
                "cards": {"type": "array", "minItems": count, "maxItems": max(count, 4), "items": _card_schema(vocab)},
            },
            ["deck_id", "cards"],
        ),
    )


def _schema_encounter(vocab: Vocabulary, count: int) -> dict[str, Any]:
    outcome = _obj(
        {
            "text": {"type": "string", "minLength": 10, "maxLength": 500},
            "effects": {
                "type": "array",
                "maxItems": 3,
                "items": _obj(
                    {
                        "type": {"enum": ["item", "stamina", "stat", "flag"]},
                        "item_id": _enum_or_string(vocab.items),
                        "name": {"type": "string"},
                        "qty": {"type": "integer", "minimum": 1, "maximum": 9},
                        "delta": {"type": "number"},
                        "stat": {"type": "string"},
                        "flag": {"type": "string"},
                    },
                    ["type"],
                ),
            },
        },
        ["text"],
    )
    approach = _obj(
        {
            "key": _id_schema(),
            "skill": _enum_or_string(vocab.skills),
            "difficulty": _enum_or_string(vocab.bands),
            "text": {"type": "string", "minLength": 5, "maxLength": 160},
        },
        ["key", "skill", "difficulty", "text"],
    )
    row = _obj(
        {
            "id": _id_schema(),
            "tier": {"type": "integer", "minimum": 1, "maximum": 3},
            "weight": {"type": "integer", "minimum": 1, "maximum": 100},
            "triggers": _obj(
                {"edges": {"type": "array", "minItems": 1, "maxItems": 6, "items": {"type": "string", "pattern": "^[a-z0-9_]+>[a-z0-9_]+$"}}},
                ["edges"],
            ),
            "intro": {"type": "string", "minLength": 40, "maxLength": 700},
            "threat": _obj(
                {"name": {"type": "string", "maxLength": 80}, "resolve": {"type": "integer", "minimum": 1, "maximum": 6}},
                ["name", "resolve"],
            ),
            "approaches": {"type": "array", "minItems": 2, "maxItems": 4, "items": approach},
            "outcomes": _obj(
                {"crit_success": outcome, "success": outcome, "partial": outcome, "failure": outcome},
                ["crit_success", "success", "partial", "failure"],
            ),
        },
        ["id", "tier", "weight", "triggers", "intro", "threat", "approaches", "outcomes"],
    )
    return _envelope(
        "author_encounter",
        _obj(
            {
                "band": _id_schema(),
                "encounters": {"type": "array", "minItems": count, "maxItems": max(count, 4), "items": row},
            },
            ["band", "encounters"],
        ),
    )


def _schema_rumor(vocab: Vocabulary, count: int) -> dict[str, Any]:
    props: dict[str, Any] = {
        "id": _id_schema(),
        "text": {"type": "string", "minLength": 20, "maxLength": 300},
        "tier": {"type": "integer", "minimum": 1, "maximum": 3},
        "min_awareness": {"type": "integer", "minimum": 0, "maximum": 100},
    }
    # Only offered when the story has npcs at all: an unknown speaker is a
    # validation error, and a story with no cast has no speakers to name.
    if vocab.npcs:
        props["source_npc"] = _enum_or_string(vocab.npcs)
    rumor = _obj(props, ["id", "text", "tier", "min_awareness"])
    return _envelope(
        "author_rumor",
        _obj({"rumors": {"type": "array", "minItems": count, "maxItems": max(count, 6), "items": rumor}}, ["rumors"]),
    )


def _schema_lore(vocab: Vocabulary, count: int) -> dict[str, Any]:
    section = _obj(
        {
            "heading": {"type": "string", "minLength": 3, "maxLength": 100},
            # engine/lore/manager.py drops any section body under 40 chars at
            # ingest; the floor here keeps a draft from shipping stubs.
            "body": {"type": "string", "minLength": 80, "maxLength": 2000},
        },
        ["heading", "body"],
    )
    return _envelope(
        "author_lore",
        _obj(
            {
                "title": {"type": "string", "minLength": 3, "maxLength": 100},
                "sections": {"type": "array", "minItems": 1, "maxItems": 8, "items": section},
            },
            ["title", "sections"],
        ),
    )


def _schema_prompt(vocab: Vocabulary, count: int) -> dict[str, Any]:
    return _envelope(
        "author_prompt",
        _obj(
            {
                "name": _id_schema(),
                "persona": {"type": "string", "minLength": 200, "maxLength": 6000},
            },
            ["name", "persona"],
        ),
    )


def _schema_spoilers(vocab: Vocabulary, count: int) -> dict[str, Any]:
    row = _obj(
        {
            "term": {"type": "string", "minLength": 2, "maxLength": 60},
            "instead": {"type": "string", "minLength": 2, "maxLength": 120},
        },
        ["term", "instead"],
    )
    return _envelope(
        "author_spoilers",
        _obj({"spoilers": {"type": "array", "minItems": count, "maxItems": max(count, 8), "items": row}}, ["spoilers"]),
    )


SCHEMA_BUILDERS: dict[str, Callable[[Vocabulary, int], dict[str, Any]]] = {
    "location": _schema_location,
    "npc": _schema_npc,
    "item": _schema_item,
    "quest": _schema_quest,
    "deck": _schema_deck,
    "card": _schema_card,
    "encounter": _schema_encounter,
    "rumor": _schema_rumor,
    "lore": _schema_lore,
    "prompt": _schema_prompt,
    "spoilers": _schema_spoilers,
}


# ---------------------------------------------------------------------------
# JSON -> loader-shaped document. The model never writes YAML; this does.
# ---------------------------------------------------------------------------


def _to_doc(kind: str, payload: dict[str, Any]) -> tuple[Any, str]:
    """Convert a schema-shaped JSON payload to the loader's document shape.

    Returns:
        (document, primary_id). For markdown kinds the document is the text.

    Raises:
        AuthorError: The payload does not carry the ids the shape needs --
            which with the grammar on should be unreachable, and without it is
            exactly the failure to name.
    """
    if kind == "location":
        table: dict[str, Any] = {}
        for row in payload.get("locations") or []:
            if not isinstance(row, dict) or not row.get("id"):
                continue
            entry = {k: row[k] for k in ("name", "ring", "summary", "tags") if k in row}
            if "evil_multiplier" in row:
                entry["evil_multiplier"] = row["evil_multiplier"]
            entry["connections"] = {
                str(edge["to"]): {
                    "hours": int(edge.get("hours", 1)),
                    "danger_dc": int(edge.get("danger_dc", 0)),
                    "awareness_delta": int(edge.get("awareness_delta", 0)),
                }
                for edge in row.get("connections") or []
            }
            table[str(row["id"])] = entry
        if not table:
            raise AuthorError("model returned no locations")
        return {"locations": table}, next(iter(table))

    if kind == "npc":
        table = {}
        for row in payload.get("npcs") or []:
            if not isinstance(row, dict) or not row.get("id"):
                continue
            table[str(row["id"])] = {
                "name": row.get("name", ""),
                "role": row.get("role", ""),
                "home": row.get("home", ""),
                "routine": [
                    {
                        "hours": [int(h) for h in slot.get("hours") or []],
                        "location": slot.get("location", ""),
                        "activity": slot.get("activity", ""),
                        **({"available": bool(slot["available"])} if "available" in slot else {}),
                    }
                    for slot in row.get("routine") or []
                ],
            }
        if not table:
            raise AuthorError("model returned no npcs")
        return {"npcs": table}, next(iter(table))

    if kind == "item":
        rows = payload.get("items") or []
        if not rows:
            raise AuthorError("model returned no items")
        return {"items": rows}, str(rows[0]["id"])

    if kind == "quest":
        if not payload.get("id"):
            raise AuthorError("model returned a quest with no id")
        return dict(payload), str(payload["id"])

    if kind == "deck":
        if not payload.get("id"):
            raise AuthorError("model returned a deck with no id")
        return dict(payload), str(payload["id"])

    if kind == "card":
        deck_id = str(payload.get("deck_id") or "")
        if not deck_id or not payload.get("cards"):
            raise AuthorError("model returned no card, or no target deck")
        return {"deck_id": deck_id, "cards": payload["cards"]}, f"{deck_id}_cards"

    if kind == "encounter":
        rows = payload.get("encounters") or []
        if not rows:
            raise AuthorError("model returned no encounters")
        return {"band": payload.get("band") or "drafted", "encounters": rows}, str(rows[0]["id"])

    if kind == "rumor":
        rows = payload.get("rumors") or []
        if not rows:
            raise AuthorError("model returned no rumors")
        return {"rumors": rows}, str(rows[0]["id"])

    if kind == "lore":
        title = str(payload.get("title") or "").strip()
        sections = payload.get("sections") or []
        if not title or not sections:
            raise AuthorError("model returned no lore sections")
        parts = [f"# {title}", ""]
        for section in sections:
            parts += [f"## {section['heading']}", "", str(section["body"]).strip(), ""]
        return "\n".join(parts), _slugify(title)

    if kind == "prompt":
        name = str(payload.get("name") or "").strip()
        persona = str(payload.get("persona") or "").strip()
        if not name or not persona:
            raise AuthorError("model returned no persona")
        return persona + "\n", name

    if kind == "spoilers":
        rows = payload.get("spoilers") or []
        if not rows:
            raise AuthorError("model returned no spoiler rows")
        return {"spoilers": rows}, "spoilers"

    raise AuthorError(f"unknown kind {kind!r}")


def _slugify(text: str) -> str:
    cleaned = re.sub(r"[^a-z0-9_]+", "_", str(text).lower()).strip("_")
    return cleaned or "draft"


def _doc_ids(kind: str, doc: Any) -> set[str]:
    """The ids a draft DEFINES -- what error attribution keys on."""
    if kind == "location":
        return {str(k) for k in (doc.get("locations") or {})}
    if kind == "npc":
        return {str(k) for k in (doc.get("npcs") or {})}
    if kind == "item":
        return {str(r.get("id")) for r in (doc.get("items") or []) if isinstance(r, dict)}
    if kind in ("quest", "deck"):
        out = {str(doc.get("id") or "")}
        if kind == "deck":
            out |= {str(c.get("id")) for c in (doc.get("cards") or []) if isinstance(c, dict)}
        return {i for i in out if i}
    if kind == "card":
        return {str(c.get("id")) for c in (doc.get("cards") or []) if isinstance(c, dict)}
    if kind == "encounter":
        return {str(r.get("id")) for r in (doc.get("encounters") or []) if isinstance(r, dict)}
    if kind == "rumor":
        return {str(r.get("id")) for r in (doc.get("rumors") or []) if isinstance(r, dict)}
    if kind == "spoilers":
        return {str(r.get("term")) for r in (doc.get("spoilers") or []) if isinstance(r, dict)}
    return set()


# ---------------------------------------------------------------------------
# Draft bookkeeping
# ---------------------------------------------------------------------------


@dataclass
class Draft:
    """One file under data/drafts/<kind>/."""

    path: pathlib.Path
    kind: str
    doc: Any = None  # parsed body (yaml kinds); None for markdown
    ids: set[str] = field(default_factory=set)
    staged_sources: set[str] = field(default_factory=set)


@dataclass
class DraftReport:
    """One validation pass over drafts + live content, attributed."""

    issues: list[Issue] = field(default_factory=list)
    by_draft: dict[pathlib.Path, list[str]] = field(default_factory=dict)
    unattributed: list[str] = field(default_factory=list)

    @property
    def errors(self) -> list[Issue]:
        return validation.errors_only(self.issues)

    @property
    def clean(self) -> bool:
        return not self.errors and not self.by_draft


# ---------------------------------------------------------------------------
# The tool
# ---------------------------------------------------------------------------


class Author:
    """Draft, repair and promote content for ONE story.

    Args:
        slug: The story, resolved read-only through the registry -- never
            activated, so running this tool cannot repoint the engine.
        backend: Anything with the LMStudioBackend ``chat`` signature. None
            means the engine's real backend, constructed lazily so offline
            use of --repair/--promote never opens a connection.
        temperature: Sampling temperature for every call.
    """

    def __init__(
        self,
        slug: str,
        *,
        backend: Any = None,
        temperature: float = DEFAULT_TEMPERATURE,
    ) -> None:
        manifest = registry.get(slug)
        if manifest is None or manifest.root is None:
            raise AuthorError(f"no such game: games/{slug}/game.yaml not found or unreadable")
        self.manifest = manifest
        self.slug = slug
        self.temperature = float(temperature)
        self._backend = backend

    # -- plumbing ----------------------------------------------------------

    @property
    def backend(self) -> Any:
        if self._backend is None:
            from engine.lmstudio.backend import get_backend

            self._backend = get_backend()
        return self._backend

    @property
    def drafts_root(self) -> pathlib.Path:
        assert self.manifest.root is not None
        return self.manifest.root / DRAFTS_REL

    def _iter_drafts(self) -> Iterator[Draft]:
        for kind, spec in KINDS.items():
            directory = self.drafts_root / kind
            if not directory.is_dir():
                continue
            suffixes = {".md"} if spec.suffix == ".md" else {".yaml", ".yml"}
            for path in sorted(directory.iterdir()):
                if not path.is_file() or path.suffix.lower() not in suffixes:
                    continue
                doc = None
                ids: set[str] = {path.stem}
                if spec.suffix != ".md":
                    doc = _load_yaml(path)
                    if isinstance(doc, dict):
                        ids |= _doc_ids(kind, doc)
                yield Draft(path=path, kind=kind, doc=doc, ids=ids)

    # -- vocabulary --------------------------------------------------------

    def vocabulary(self) -> Vocabulary:
        """Live ids plus already-drafted ids, so siblings can cohere."""
        vocab = Vocabulary(
            skills=validation.story_skills(self.manifest),
            bands=validation.story_bands(self.manifest),
        )
        doc = validation.load_story_locations(self.manifest)
        vocab.locations |= {str(k) for k in (doc.get("locations") or {})}
        items, _ = validation.load_story_items(self.manifest)
        vocab.items |= set(items)

        npc_path = _declared(self.manifest, "npc_schedules")
        if npc_path is not None and npc_path.is_file():
            vocab.npcs |= {str(k) for k in ((_load_yaml(npc_path) or {}).get("npcs") or {})}
        factions_path = _declared(self.manifest, "factions")
        if factions_path is not None and factions_path.is_file():
            vocab.factions |= {str(k) for k in ((_load_yaml(factions_path) or {}).get("factions") or {})}

        schema_path = self.manifest.state_schema_path
        if schema_path is not None and schema_path.is_file():
            data = _load_yaml(schema_path) or {}
            vocab.values |= {str(k) for k in (data.get("meters") or {})}
            vocab.values |= {str(k) for k in (data.get("tracks") or {})}
            vocab.clocks |= {str(k) for k in (data.get("clocks") or {})}

        quests_dir = _declared(self.manifest, "quests")
        if quests_dir is not None and quests_dir.is_dir():
            arcs = _load_yaml(quests_dir / "arcs.yaml") or {}
            vocab.arcs |= {str(k) for k in (arcs.get("arcs") or {})}

        decks_dir = _declared(self.manifest, "decks")
        if decks_dir is not None and decks_dir.is_dir():
            vocab.decks |= {
                p.stem
                for p in decks_dir.glob("*.yaml")
                if DRAFTS_DIRNAME not in p.parts
            }

        for draft in self._iter_drafts():
            if draft.kind == "location":
                vocab.locations |= draft.ids
            elif draft.kind == "item":
                vocab.items |= draft.ids
            elif draft.kind == "npc":
                vocab.npcs |= draft.ids
            elif draft.kind == "deck" and isinstance(draft.doc, dict):
                vocab.decks.add(str(draft.doc.get("id") or draft.path.stem))
        return vocab

    # -- prompts -----------------------------------------------------------

    def _register_line(self) -> str:
        block = self.manifest.extras.get("safety")
        intensity = (block or {}).get("intensity") if isinstance(block, dict) else {}
        ceiling = str((intensity or {}).get("ceiling") or "suggestive").strip().lower()
        if ceiling in ("explicit", "extreme"):
            return (
                f"Register: this story declares a content ceiling of '{ceiling}'. "
                "Write to the register the story declares; never exceed the ceiling."
            )
        return (
            "Register: this story's content ceiling is 'suggestive'. "
            "Allusive at most; nothing explicit."
        )

    def _ids_line(self, label: str, ids: set[str] | frozenset[str]) -> str:
        ordered = sorted(ids)
        shown = ordered[:_MAX_CONTEXT_IDS]
        tail = f" (+{len(ordered) - len(shown)} more)" if len(ordered) > len(shown) else ""
        return f"{label}: {', '.join(shown) or '(none)'}{tail}"

    def system_prompt(self, kind: str) -> str:
        """Manifest summary + vocabulary + register + output rules. Lean."""
        vocab = self.vocabulary()
        manifest = self.manifest
        shape = ", ".join(sorted(manifest.paths)) or "(none)"
        lines = [
            f'You draft {kind} content for "{manifest.title}" ({manifest.slug}), '
            "a story running on the Clockwork engine. The engine resolves all "
            "mechanics; content declares data, never prose about mechanics.",
            f"Blurb: {manifest.blurb}" if manifest.blurb else "",
            f"Declared content sections: {shape}.",
            f"Entry location: {manifest.entry_location or '(none)'}.",
            self._ids_line("Known location ids", vocab.locations),
            self._ids_line("Known item ids", vocab.items),
            self._ids_line("Known npc ids", vocab.npcs),
            self._ids_line("Declared state values", vocab.values | vocab.clocks),
            self._ids_line("Skills", vocab.skills),
            self._ids_line("Difficulty bands", vocab.bands),
            self._ids_line("Quest arcs", vocab.arcs) if vocab.arcs else "",
            self._ids_line("Decks", vocab.decks) if vocab.decks else "",
            self._register_line(),
            "Rules: reply with ONE JSON object matching the response schema and "
            "nothing else. Ids are lowercase snake_case. Reference only ids "
            "listed above or ids this draft itself creates; an id that resolves "
            "to nothing is a validation error you will be asked to fix.",
        ]
        return "\n".join(line for line in lines if line)

    # -- inference ---------------------------------------------------------

    def _complete_json(
        self,
        task: str,
        messages: list[dict[str, str]],
        envelope: dict[str, Any],
        *,
        profile: str,
        max_tokens: int,
    ) -> dict[str, Any]:
        """One structured call through the engine's backend, JSON out.

        The schema is ALWAYS sent. If the server ignores grammars the JSON
        decode below catches it, reprompts once, then fails loudly -- an
        authoring tool must never quietly write prose into a YAML file.
        """
        response_format = {"type": "json_schema", "json_schema": envelope}
        attempt_messages = list(messages)
        last_error: Optional[Exception] = None
        for attempt in range(1 + _JSON_RETRIES):
            response = self.backend.chat(
                attempt_messages,
                profile=profile,
                response_format=response_format,
                temperature=self.temperature,
                max_tokens=max_tokens,
                label=f"author:{task}",
            )
            content = str(getattr(response, "content", "") or "")
            try:
                return json.loads(_extract_json(content))
            except (json.JSONDecodeError, ValueError) as exc:
                last_error = exc
                logger.warning(
                    "[author] Model reply was not valid JSON, reprompting "
                    "(operation=_complete_json, task=%s, attempt=%d)",
                    task,
                    attempt + 1,
                )
                attempt_messages = attempt_messages + [
                    {"role": "assistant", "content": content},
                    {
                        "role": "user",
                        "content": "That was not a valid JSON object. Reply again "
                        "with exactly one JSON object matching the schema.",
                    },
                ]
        raise AuthorError(f"model did not produce valid JSON for {task}: {last_error}")

    # -- draft -------------------------------------------------------------

    def draft(self, kind: str, brief: str, *, count: int = 1) -> pathlib.Path:
        """Draft one file of one kind from a freeform brief.

        Returns:
            The path written, always under ``games/<slug>/data/drafts/``.
        """
        spec = KINDS.get(kind)
        if spec is None:
            raise AuthorError(f"unknown kind {kind!r}; known: {', '.join(sorted(KINDS))}")
        count = max(1, int(count))
        envelope = SCHEMA_BUILDERS[kind](self.vocabulary(), count)
        messages = [
            {"role": "system", "content": self.system_prompt(kind)},
            {
                "role": "user",
                "content": f"Draft {count} {kind}{'s' if count > 1 else ''} for this "
                f"story.\n\nBRIEF:\n{brief.strip()}",
            },
        ]
        payload = self._complete_json(
            f"draft:{kind}", messages, envelope, profile=spec.profile, max_tokens=spec.max_tokens
        )
        doc, primary = _to_doc(kind, payload)
        return self._write_draft(spec, doc, primary, brief)

    def _write_draft(self, spec: KindSpec, doc: Any, primary: str, brief: str) -> pathlib.Path:
        directory = self.drafts_root / spec.kind
        directory.mkdir(parents=True, exist_ok=True)
        stem = _slugify(primary)
        path = directory / f"{stem}{spec.suffix}"
        counter = 2
        while path.exists():
            path = directory / f"{stem}-{counter}{spec.suffix}"
            counter += 1

        brief_line = " ".join(brief.split())[:100]
        stamp = _dt.date.today().isoformat()
        if spec.suffix == ".md":
            header = f"<!-- Drafted by scripts/author.py [{stamp}] -- brief: {brief_line} -->\n"
            path.write_text(header + str(doc), encoding="utf-8", newline="\n")
        else:
            header = (
                f"# Drafted by scripts/author.py [{stamp}] -- review before promoting.\n"
                f"# game: {self.slug}  kind: {spec.kind}\n"
                f"# brief: {brief_line}\n"
            )
            body = yaml.safe_dump(
                doc, sort_keys=False, allow_unicode=True, width=88, default_flow_style=False
            )
            path.write_text(header + body, encoding="utf-8", newline="\n")
        logger.info(
            "[author] Draft written (operation=draft, kind=%s, path=%s)", spec.kind, path
        )
        return path

    # -- staging + validation ---------------------------------------------

    def validate_drafts(self) -> DraftReport:
        """Stage drafts over the live content and run the shared validator.

        Merge collisions the validator cannot see (a draft redefining a live
        location, a card aimed at a deck that does not exist) are reported as
        attributed errors alongside the backbone's own findings.
        """
        drafts = list(self._iter_drafts())
        report = DraftReport()
        staging = pathlib.Path(tempfile.mkdtemp(prefix=f"author-{self.slug}-"))
        try:
            synthetic = self._stage(staging, drafts, report)
            report.issues = validation.validate_story(synthetic)
            self._attribute(report, drafts)
        finally:
            shutil.rmtree(staging, ignore_errors=True)
        return report

    def _stage(
        self,
        staging: pathlib.Path,
        drafts: list[Draft],
        report: DraftReport,
    ) -> GameManifest:
        """Build the synthetic manifest whose paths include the drafts."""
        manifest = self.manifest
        paths = dict(manifest.paths)
        by_kind: dict[str, list[Draft]] = {}
        for draft in drafts:
            by_kind.setdefault(draft.kind, []).append(draft)

        def collide(draft: Draft, message: str) -> None:
            report.by_draft.setdefault(draft.path, []).append(message)

        # -- single-file kinds: merge into a copy of the live document -----
        for kind in ("location", "npc", "rumor"):
            batch = by_kind.get(kind)
            if not batch:
                continue
            spec = KINDS[kind]
            live_path = _declared(manifest, spec.path_key)
            live_doc = _load_yaml(live_path) if live_path is not None and live_path.is_file() else None
            merged: dict[str, Any] = dict(live_doc) if isinstance(live_doc, dict) else {}
            if kind == "rumor":
                rows = list(merged.get("rumors") or [])
                for draft in batch:
                    rows.extend((draft.doc or {}).get("rumors") or [])
                merged["rumors"] = rows
            else:
                table = dict(merged.get(spec.top_key) or {})
                for draft in batch:
                    for entry_id, row in ((draft.doc or {}).get(spec.top_key) or {}).items():
                        if entry_id in table:
                            collide(
                                draft,
                                f"{kind} id {entry_id!r} already exists in the live "
                                f"{spec.top_key} table; rename the draft's id",
                            )
                            continue
                        table[entry_id] = row
                merged[spec.top_key] = table
            staged = staging / (live_path.name if live_path is not None else f"{spec.top_key}.yaml")
            _dump_yaml(staged, merged)
            paths[spec.path_key] = str(staged)
            for draft in batch:
                draft.staged_sources.add(str(staged))

        # -- spoilers: a copy of the whole rules dir, rows merged in --------
        if by_kind.get("spoilers"):
            rules_dir = _declared(manifest, "rules")
            staged_rules = staging / "rules"
            if rules_dir is not None and rules_dir.is_dir():
                shutil.copytree(rules_dir, staged_rules, ignore=_ignore_drafts)
            else:
                staged_rules.mkdir(parents=True)
            table_path = staged_rules / "spoilers.yaml"
            doc = _load_yaml(table_path) if table_path.is_file() else None
            merged = dict(doc) if isinstance(doc, dict) else {}
            rows = list(merged.get("spoilers") or [])
            for draft in by_kind["spoilers"]:
                rows.extend((draft.doc or {}).get("spoilers") or [])
                draft.staged_sources.add(str(table_path))
            merged["spoilers"] = rows
            _dump_yaml(table_path, merged)
            paths["rules"] = str(staged_rules)

        # -- directory kinds: live copies beside the draft files ------------
        for kind in ("item", "quest", "encounter", "lore"):
            batch = by_kind.get(kind)
            if not batch:
                continue
            spec = KINDS[kind]
            staged_dir = self._staged_dir(staging, spec)
            if kind == "quest":
                live_ids = self._live_quest_ids()
                for draft in batch:
                    quest_id = str((draft.doc or {}).get("id") or "")
                    if quest_id and quest_id in live_ids:
                        collide(draft, f"quest id {quest_id!r} already exists in the live tree")
            for draft in batch:
                target = staged_dir / draft.path.name
                counter = 2
                while target.exists():
                    target = staged_dir / f"{draft.path.stem}-{counter}{draft.path.suffix}"
                    counter += 1
                shutil.copy2(draft.path, target)
                draft.staged_sources.add(str(target))
            paths[spec.path_key] = str(staged_dir)

        # -- decks and cards -------------------------------------------------
        deck_batch = by_kind.get("deck") or []
        card_batch = by_kind.get("card") or []
        if deck_batch or card_batch:
            spec = KINDS["deck"]
            staged_dir = self._staged_dir(staging, spec)
            for draft in deck_batch:
                deck_id = str((draft.doc or {}).get("id") or draft.path.stem)
                target = staged_dir / f"{deck_id}.yaml"
                if target.exists():
                    report.by_draft.setdefault(draft.path, []).append(
                        f"deck id {deck_id!r} already exists in the live tree"
                    )
                    continue
                shutil.copy2(draft.path, target)
                draft.staged_sources.add(str(target))
            for draft in card_batch:
                deck_id = str((draft.doc or {}).get("deck_id") or "")
                target = staged_dir / f"{deck_id}.yaml"
                if not target.is_file():
                    report.by_draft.setdefault(draft.path, []).append(
                        f"card draft targets deck {deck_id!r}, which does not exist"
                    )
                    continue
                deck_doc = _load_yaml(target) or {}
                deck_doc["cards"] = list(deck_doc.get("cards") or []) + list(
                    (draft.doc or {}).get("cards") or []
                )
                _dump_yaml(target, deck_doc)
                draft.staged_sources.add(str(target))
            paths[spec.path_key] = str(staged_dir)

        # prompts: nothing in the backbone validates persona prose, so prompt
        # drafts are not staged; agents.yaml keeps pointing at the live files.

        data: dict[str, Any] = {
            "title": manifest.title,
            "paths": paths,
            "entry": dict(manifest.entry),
        }
        if "state" in manifest.extras:
            data["state"] = manifest.extras["state"]
        return from_dict(data, slug=self.slug, root=manifest.root)

    def _staged_dir(self, staging: pathlib.Path, spec: KindSpec) -> pathlib.Path:
        staged = staging / spec.path_key
        live_dir = _declared(self.manifest, spec.path_key)
        if live_dir is not None and live_dir.is_dir():
            shutil.copytree(live_dir, staged, ignore=_ignore_drafts)
        else:
            staged.mkdir(parents=True)
        return staged

    def _live_quest_ids(self) -> set[str]:
        quests_dir = _declared(self.manifest, "quests")
        out: set[str] = set()
        if quests_dir is None or not quests_dir.is_dir():
            return out
        for path in quests_dir.rglob("*.yaml"):
            if path.name == "arcs.yaml" or DRAFTS_DIRNAME in path.parts:
                continue
            doc = _load_yaml(path)
            if isinstance(doc, dict) and doc.get("id"):
                out.add(str(doc["id"]))
        return out

    def _attribute(self, report: DraftReport, drafts: list[Draft]) -> None:
        """Pin each backbone error on the draft that owns it, if any does."""
        for issue in report.errors:
            owner: Optional[Draft] = None
            for draft in drafts:
                if issue.source in draft.staged_sources:
                    owner = draft
                    break
                ref_parts = set(str(issue.ref_id).split(">"))
                if str(issue.ref_id) in draft.ids or (ref_parts & draft.ids):
                    owner = draft
                    break
            if owner is not None:
                report.by_draft.setdefault(owner.path, []).append(str(issue))
            else:
                report.unattributed.append(str(issue))

    # -- repair ------------------------------------------------------------

    def repair(self, *, max_attempts: int = MAX_REPAIR_ATTEMPTS) -> DraftReport:
        """Feed validator errors back to the model, at most ``max_attempts``
        per draft file, rewriting each corrected draft in place.

        Returns:
            The final report. ``by_draft`` still naming a file means the model
            never produced a clean version of it, and the report says so
            rather than the loop trying forever.
        """
        attempts: dict[pathlib.Path, int] = {}
        report = self.validate_drafts()
        while True:
            fixable = {
                path: errors
                for path, errors in report.by_draft.items()
                if attempts.get(path, 0) < max_attempts
            }
            if not fixable:
                break
            for path, errors in fixable.items():
                attempts[path] = attempts.get(path, 0) + 1
                try:
                    self._repair_one(path, errors)
                except AuthorError as exc:
                    logger.warning(
                        "[author] Repair attempt failed (operation=repair, path=%s): %s",
                        path,
                        exc,
                    )
            report = self.validate_drafts()
        return report

    def _repair_one(self, path: pathlib.Path, errors: list[str]) -> None:
        kind = path.parent.name
        spec = KINDS.get(kind)
        if spec is None or spec.suffix == ".md":
            raise AuthorError(f"cannot repair {path}; not a repairable kind")
        current = path.read_text(encoding="utf-8")
        envelope = SCHEMA_BUILDERS[kind](self.vocabulary(), 1)
        error_lines = "\n".join(f"- {e}" for e in errors)
        messages = [
            {"role": "system", "content": self.system_prompt(kind)},
            {
                "role": "user",
                "content": "This draft failed validation. Return the corrected "
                "content as one JSON object matching the schema. Keep everything "
                "that was not flagged; change only what the errors name.\n\n"
                f"DRAFT ({path.name}):\n{current}\n\nERRORS:\n{error_lines}",
            },
        ]
        payload = self._complete_json(
            f"repair:{kind}", messages, envelope, profile=spec.profile, max_tokens=spec.max_tokens
        )
        doc, _primary = _to_doc(kind, payload)
        header = "".join(
            line for line in current.splitlines(keepends=True) if line.startswith("#")
        )
        body = yaml.safe_dump(
            doc, sort_keys=False, allow_unicode=True, width=88, default_flow_style=False
        )
        path.write_text(header + body, encoding="utf-8", newline="\n")
        logger.info("[author] Draft repaired (operation=_repair_one, path=%s)", path)

    # -- promote -----------------------------------------------------------

    def promote(self, kind: str = "all") -> list[pathlib.Path]:
        """Move validated drafts into the live tree.

        Refuses outright while ANY error stands -- attributed, unattributed
        or collision -- because promoting around a broken combined tree just
        moves the breakage somewhere the validator will find it tomorrow.

        Single-file kinds are merged into the live file; the live file's
        LEADING comment banner survives, but comments between entries do not
        (yaml round-trips do not carry them). Directory kinds move the draft
        file in whole, header comment included.

        Returns:
            The live paths written.
        """
        if kind != "all" and kind not in KINDS:
            raise AuthorError(f"unknown kind {kind!r}; known: all, {', '.join(sorted(KINDS))}")

        report = self.validate_drafts()
        failures = list(report.unattributed)
        for path, errors in sorted(report.by_draft.items()):
            failures.extend(f"{path.name}: {e}" for e in errors)
        if failures:
            detail = "\n  ".join(failures)
            raise AuthorError(f"refusing to promote while errors exist:\n  {detail}")

        selected = [d for d in self._iter_drafts() if kind in ("all", d.kind)]
        if not selected:
            raise AuthorError(f"nothing to promote under {self.drafts_root}")

        written: list[pathlib.Path] = []
        for draft in selected:
            spec = KINDS[draft.kind]
            if spec.path_key not in self.manifest.paths:
                raise AuthorError(
                    f"cannot promote {draft.path.name}: the manifest declares no "
                    f"paths.{spec.path_key}; declare it in games/{self.slug}/game.yaml "
                    "(the file or directory must exist) and re-run"
                )
            if spec.container == "file":
                written.append(self._promote_into_file(draft, spec))
            elif spec.container == "rules_file":
                written.append(self._promote_spoilers(draft))
            elif spec.container == "deck_cards":
                written.append(self._promote_cards(draft))
            else:
                written.append(self._promote_into_dir(draft, spec))
            draft.path.unlink()
        self._prune_empty_kind_dirs()
        return written

    def _promote_into_file(self, draft: Draft, spec: KindSpec) -> pathlib.Path:
        live_path = _declared(self.manifest, spec.path_key)
        assert live_path is not None
        live_doc = _load_yaml(live_path) if live_path.is_file() else None
        merged: dict[str, Any] = dict(live_doc) if isinstance(live_doc, dict) else {}
        if spec.top_key == "rumors":
            merged["rumors"] = list(merged.get("rumors") or []) + list(
                (draft.doc or {}).get("rumors") or []
            )
        else:
            table = dict(merged.get(spec.top_key) or {})
            table.update((draft.doc or {}).get(spec.top_key) or {})
            merged[spec.top_key] = table
        self._rewrite_merged(live_path, merged)
        return live_path

    def _promote_spoilers(self, draft: Draft) -> pathlib.Path:
        rules_dir = _declared(self.manifest, "rules")
        assert rules_dir is not None
        live_path = rules_dir / "spoilers.yaml"
        live_doc = _load_yaml(live_path) if live_path.is_file() else None
        merged: dict[str, Any] = dict(live_doc) if isinstance(live_doc, dict) else {}
        merged["spoilers"] = list(merged.get("spoilers") or []) + list(
            (draft.doc or {}).get("spoilers") or []
        )
        self._rewrite_merged(live_path, merged)
        return live_path

    def _promote_cards(self, draft: Draft) -> pathlib.Path:
        decks_dir = _declared(self.manifest, "decks")
        assert decks_dir is not None
        deck_id = str((draft.doc or {}).get("deck_id") or "")
        live_path = decks_dir / f"{deck_id}.yaml"
        deck_doc = _load_yaml(live_path) or {}
        deck_doc["cards"] = list(deck_doc.get("cards") or []) + list(
            (draft.doc or {}).get("cards") or []
        )
        self._rewrite_merged(live_path, deck_doc)
        return live_path

    def _promote_into_dir(self, draft: Draft, spec: KindSpec) -> pathlib.Path:
        live_dir = _declared(self.manifest, spec.path_key)
        assert live_dir is not None
        live_dir.mkdir(parents=True, exist_ok=True)
        name = draft.path.name
        if spec.kind == "quest" and name == "arcs.yaml":
            name = "arcs_quest.yaml"  # never shadow the arc table
        if spec.kind == "deck" and isinstance(draft.doc, dict) and draft.doc.get("id"):
            name = f"{draft.doc['id']}.yaml"  # the filename IS the deck id
        target = live_dir / name
        counter = 2
        while target.exists():
            target = live_dir / f"{draft.path.stem}-{counter}{draft.path.suffix}"
            counter += 1
        shutil.copy2(draft.path, target)
        return target

    @staticmethod
    def _rewrite_merged(path: pathlib.Path, merged: dict[str, Any]) -> None:
        """Rewrite a merged single-file document, keeping the leading banner.

        A yaml round-trip drops comments; the leading block is preserved by
        hand because it is where these files keep their WHY. Interior
        comments are lost, and the promote report says so out loud.
        """
        banner = ""
        if path.is_file():
            lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
            kept: list[str] = []
            for line in lines:
                if line.startswith("#") or not line.strip():
                    kept.append(line)
                else:
                    break
            banner = "".join(kept)
        body = yaml.safe_dump(
            merged, sort_keys=False, allow_unicode=True, width=88, default_flow_style=False
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(banner + body, encoding="utf-8", newline="\n")

    def _prune_empty_kind_dirs(self) -> None:
        root = self.drafts_root
        if not root.is_dir():
            return
        for child in root.iterdir():
            if child.is_dir() and not any(child.iterdir()):
                child.rmdir()
        if not any(root.iterdir()):
            root.rmdir()

    # -- from-bible --------------------------------------------------------

    #: (kind, plural key in the plan payload). Dependency order: things that
    #: are referenced come before the things that reference them -- an npc
    #: lives at a drafted location, a quest watches a drafted item.
    _PLAN_ROWS: tuple[tuple[str, str], ...] = (
        ("location", "locations"),
        ("npc", "npcs"),
        ("item", "items"),
        ("quest", "quests"),
        ("deck", "decks"),
        ("encounter", "encounters"),
        ("rumor", "rumors"),
    )

    def plan_schema(self) -> dict[str, Any]:
        """The planning schema, shaped by what the manifest DECLARES.

        Graph-vs-deck is not guessed from prose: a story that declares
        ``paths.decks`` plans decks, one that declares ``paths.quests`` plans
        quests, and one that declares both plans both. A section the story
        does not declare is not offered, so the model cannot plan content the
        engine would never load.
        """
        entry = _obj(
            {"id": _id_schema(), "brief": {"type": "string", "minLength": 10, "maxLength": 300}},
            ["id", "brief"],
        )
        props: dict[str, Any] = {}
        required: list[str] = []
        for kind, plural in self._PLAN_ROWS:
            if KINDS[kind].path_key in self.manifest.paths:
                props[plural] = {"type": "array", "maxItems": 12, "items": entry}
                required.append(plural)
        if not props:
            raise AuthorError(
                "the manifest declares none of the content paths this tool can "
                "plan for; declare paths in game.yaml first"
            )
        return _envelope("author_plan", _obj(props, required))

    def from_bible(self, bible_path: str | pathlib.Path) -> list[pathlib.Path]:
        """Batch mode: plan the content set from a story bible, then draft
        each piece with the bible and the already-drafted siblings as context.

        Returns:
            Every draft path written, in the order drafted.
        """
        bible = pathlib.Path(bible_path).read_text(encoding="utf-8").strip()
        if not bible:
            raise AuthorError(f"story bible {bible_path} is empty")

        envelope = self.plan_schema()
        planned_sections = sorted(envelope["schema"]["properties"])
        messages = [
            {"role": "system", "content": self.system_prompt("plan")},
            {
                "role": "user",
                "content": "Plan the content set for this story from the bible "
                f"below. Sections to plan: {', '.join(planned_sections)}. Keep "
                "counts modest -- a handful per section that the bible actually "
                "supports; an empty list is the right answer for a section the "
                f"bible does not touch.\n\nSTORY BIBLE:\n{bible}",
            },
        ]
        plan = self._complete_json(
            "plan", messages, envelope, profile="big", max_tokens=3000
        )

        written: list[pathlib.Path] = []
        for kind, plural in self._PLAN_ROWS:
            for entry in plan.get(plural) or []:
                entry_id = str((entry or {}).get("id") or "").strip()
                entry_brief = str((entry or {}).get("brief") or "").strip()
                if not entry_id:
                    continue
                brief = (
                    f"Draft the {kind} '{entry_id}': {entry_brief}\n"
                    f"Use the id '{entry_id}'.\n\nSTORY BIBLE:\n{bible}"
                )
                written.append(self.draft(kind, brief))
        return written


def _ignore_drafts(directory: str, names: list[str]) -> set[str]:
    """copytree ignore callback: never carry a nested drafts/ along."""
    return {name for name in names if name == DRAFTS_DIRNAME}


def _dump_yaml(path: pathlib.Path, doc: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(doc, sort_keys=False, allow_unicode=True, width=88, default_flow_style=False),
        encoding="utf-8",
        newline="\n",
    )


def _extract_json(content: str) -> str:
    """The JSON object out of a reply, tolerating code fences and preamble."""
    text = content.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("no JSON object in reply")
    return text[start : end + 1]


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _read_brief(source: str) -> str:
    if source == "-":
        return sys.stdin.read()
    return pathlib.Path(source).read_text(encoding="utf-8")


def _print_report(report: DraftReport) -> None:
    for path, errors in sorted(report.by_draft.items()):
        for error in errors:
            print(f"[draft] {path.name}: {error}")
    for error in report.unattributed:
        print(f"[live] {error}")
    for warning in validation.warnings_only(report.issues):
        print(f"[advisory] {warning}")
    total = sum(len(v) for v in report.by_draft.values()) + len(report.unattributed)
    print(f"[author] {total} error(s) across drafts + live content")


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="LLM-assisted story content drafting, validated before it is written."
    )
    parser.add_argument("--game", required=True, help="story slug under games/")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--draft", choices=sorted(KINDS), help="draft one kind from --brief")
    mode.add_argument("--from-bible", metavar="FILE", help="plan and draft a content set from a story bible")
    mode.add_argument("--repair", action="store_true", help="feed validator errors back to the model")
    mode.add_argument(
        "--promote",
        nargs="?",
        const="all",
        metavar="KIND",
        help="move validated drafts into the live tree (default: all kinds)",
    )
    parser.add_argument("--brief", help="freeform brief: a file path, or '-' for stdin")
    parser.add_argument("--count", type=int, default=1, help="entries to draft (default 1)")
    parser.add_argument(
        "--temperature",
        type=float,
        default=DEFAULT_TEMPERATURE,
        help=f"sampling temperature (default {DEFAULT_TEMPERATURE})",
    )
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.WARNING, format="%(message)s")

    try:
        author = Author(args.game, temperature=args.temperature)

        if args.draft:
            if not args.brief:
                parser.error("--draft requires --brief <file|->")
            path = author.draft(args.draft, _read_brief(args.brief), count=args.count)
            print(f"[author] drafted {path}")
            _print_report(author.validate_drafts())
            return 0

        if args.from_bible:
            written = author.from_bible(args.from_bible)
            for path in written:
                print(f"[author] drafted {path}")
            report = author.validate_drafts()
            _print_report(report)
            if not report.clean:
                print("[author] run --repair to feed these errors back to the model")
            return 0

        if args.repair:
            report = author.repair()
            _print_report(report)
            return 0 if report.clean else 1

        if args.promote:
            written = author.promote(args.promote)
            for path in written:
                print(f"[author] promoted into {path}")
            print(
                "[author] note: merged single-file targets keep their leading "
                "banner but lose interior comments; review the diff"
            )
            return 0

    except AuthorError as exc:
        print(f"[author] {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
