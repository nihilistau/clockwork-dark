"""
The Wicked Garden's authored content: ten day chapters, 23 endings, 47 cards.

WHAT THIS SUITE IS FOR. A beat that names a value, item, location or flag which
does not exist does not raise. ``effects.apply_effect`` returns an ``_unknown``
receipt, ``evaluate_condition`` logs an unknown predicate and returns False, and
the scene plays -- silently wrong, at the exact moment a player reaches it, on
one branch in fifty. That is the failure mode this file exists to make
impossible, and it is why "a beat naming something that does not exist is worse
than a missing beat".

So every assertion here is a resolution assertion. The day files are driven
through the REAL deck loader against the REAL schema, and every id they mention
is checked against the file that owns it:

    value / clock  ->  games/wicked-garden/state.yaml
    item           ->  games/wicked-garden/data/items/garden.yaml
    location       ->  games/wicked-garden/data/world/locations.yaml
    flag           ->  the design state dictionary, or something that reads it

The flag rule is bidirectional on purpose. A flag a scene WRITES must be either
canon or read by something; a flag a scene READS must be either canon or written
by something. A one-directional check would pass a typo on whichever side it did
not look at, and both sides are equally easy to mistype.

Version: v0.1.0 [2026-08-08]
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterator

import pytest
import yaml

from engine.config import set_overlay
from engine.content import deck as deck_module  # noqa: F401  -- also the fixture's loader

# The reference scanners live in the shared validator now, because they ARE the
# generalised check: engine/games/validation.py runs them over every story's
# structural files, and this suite runs them with the Garden's own bespoke
# framing. One set of scanners, or the two would drift about what counts as a
# reference.
from engine.games.validation import (
    canon_flags as _shared_canon_flags,
)
from engine.games.validation import (
    engine_owned_flag as _engine_owned,
)
from engine.games.validation import (
    flags_read as _flags_read,
)
from engine.games.validation import (
    flags_written as _flags_written,
)
from engine.games.validation import (
    item_refs as _item_refs,
)
from engine.games.validation import (
    location_refs as _location_refs,
)
from engine.games.validation import (
    value_refs as _value_refs,
)
from engine.games.validation import (
    walk as _walk,
)

# The state layer registers `value`, `clock` and `track`; threads and endings
# register theirs. Imported for the side effect, so a condition in a scene file
# is evaluated against the full grammar rather than a partial one.
from engine.game import clocks as _clocks  # noqa: F401
from engine.game import effects
from engine.game import endings as endings_module
from engine.game import epilogue as epilogue_module
from engine.game import threads as _threads  # noqa: F401
from engine.game.state import GameState
from engine.state import active as active_state
from engine.state.schema import load_schema

_ROOT = Path(__file__).resolve().parents[1]

GARDEN = _ROOT / "games" / "wicked-garden"
SCENES = GARDEN / "data" / "scenes"
RULES = GARDEN / "data" / "rules"
EPILOGUES = GARDEN / "data" / "epilogues"
#: The story's declared vocabulary, vendored into the game tree. It was read
#: from `Design_files/` until that directory became local-only, at which point
#: every scan below passed on one machine and errored on a fresh checkout.
CANON = GARDEN / "data" / "canon"

#: The material the Garden was AUTHORED from, which a public checkout does not
#: carry -- see the note in .gitignore. Only the transcription-provenance test
#: below reads it, and that test skips when it is absent rather than pretending
#: to have run.
DESIGN = _ROOT / "Design_files" / "Wicked-Garden" / "docs" / "design"
HAVE_DESIGN = DESIGN.is_dir()

#: The ten day chapters, in order. Named rather than globbed: a suite that
#: globs cannot fail when a day goes missing, and "Day 6 is not authored" is
#: precisely the kind of thing this has to be able to say.
DAY_FILES = [
    "day_00_prologue",
    "day_01_guest",
    "day_02_laws",
    "day_03_heat",
    "day_04_ashen",
    "day_05_labyrinth",
    "day_06_roots",
    "day_07_reckoning",
    "day_08_mirrors",
    "day_09_finale",
]



# ---------------------------------------------------------------------------
# Fixtures and loading
# ---------------------------------------------------------------------------


@pytest.fixture
def garden() -> Iterator[GameState]:
    """
    The real story, with `paths.decks` pointed at the day chapters.

    Same shape as tests/test_structural_systems.py's fixture, and deliberately
    so: this drives the shipped loaders over the shipped files. `data/scenes`
    is now what game.yaml itself declares -- it briefly was not, and these
    tests went on passing over content the running game could not see.
    """
    set_overlay(
        {
            "paths": {
                "clocks": "games/wicked-garden/data/rules/clocks.yaml",
                "threads": "games/wicked-garden/data/rules/threads.yaml",
                "endings": "games/wicked-garden/data/rules/endings.yaml",
                "decks": "games/wicked-garden/data/scenes",
                "epilogues": "games/wicked-garden/data/epilogues",
            }
        }
    )
    active_state._schema = load_schema(GARDEN / "state.yaml", slug="wicked-garden")
    state = GameState(rng_seed=42)
    try:
        yield state
    finally:
        active_state.reset_schema()
        set_overlay(None)


def _read(path: Path) -> Any:
    with path.open(encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def _scene_docs() -> dict[str, Any]:
    return {name: _read(SCENES / f"{name}.yaml") for name in DAY_FILES}


def _authored_docs() -> dict[str, Any]:
    """Everything this content owns: the ten days plus the ending modules."""
    docs = _scene_docs()
    docs["endings"] = _read(RULES / "endings.yaml")
    return docs


def _side_deck_paths() -> list[Path]:
    """
    Every deck in `paths.decks` that is not one of the ten days -- today, the
    labyrinth's chambers.

    Globbed rather than named because these are optional: a story may ship none.
    That is the opposite of DAY_FILES, where a missing file must be a failure.
    The two flag scans below read these for writes and reads, and a
    `Path.glob` over a directory that does not exist yields nothing without
    complaint -- so this is derived from the directory the loader actually uses
    rather than a second literal that can quietly go stale and take the scan
    with it.
    """
    days = {f"{name}.yaml" for name in DAY_FILES}
    return [path for path in sorted(SCENES.glob("*.yaml")) if path.name not in days]


# ---------------------------------------------------------------------------
# Declared vocabularies
# ---------------------------------------------------------------------------


def _declared_values() -> set[str]:
    """Every meter and clock `state.yaml` declares. Nothing else may be moved."""
    schema = _read(GARDEN / "state.yaml")
    return set(schema.get("meters") or {}) | set(schema.get("clocks") or {})


def _declared_items() -> set[str]:
    out: set[str] = set()
    for path in sorted((GARDEN / "data" / "items").glob("*.yaml")):
        for row in _read(path).get("items") or []:
            if isinstance(row, dict) and row.get("id"):
                out.add(str(row["id"]))
    return out


def _declared_locations() -> set[str]:
    return set(_read(GARDEN / "data" / "world" / "locations.yaml").get("locations") or {})


def _dictionary() -> dict[str, Any]:
    with (CANON / "state-dictionary.json").open(encoding="utf-8") as handle:
        return json.load(handle)


def _canon_flags() -> set[str]:
    """
    Flags the DESIGN declares, plus the ones the shipped rules declare.

    The expansion itself (booleans, enum spellings, clock ``set_flags``) is
    ``engine.games.validation.canon_flags`` -- the generalised check runs the
    same expansion for any story with a canon dictionary, and this suite must
    agree with it about what counts as declared.
    """
    return _shared_canon_flags(_dictionary(), _read(RULES / "clocks.yaml"))


# ---------------------------------------------------------------------------
# 1. The ten days exist and load through the real loader
# ---------------------------------------------------------------------------


def test_all_ten_day_chapters_exist() -> None:
    """Named, not globbed. A missing day has to be able to fail this."""
    missing = [name for name in DAY_FILES if not (SCENES / f"{name}.yaml").is_file()]
    assert missing == []


def test_every_day_loads_through_the_deck_loader(garden: GameState) -> None:
    """
    The shipped parser, not a private one.

    `deck_ids()` reading the scenes directory is also what proves the day files
    are in the one format the engine already has a loader for, rather than a
    second grammar that happens to look similar.
    """
    # The days plus the labyrinth's chamber deck, which moved in beside them:
    # `paths.decks` is one flat directory, and to this engine a day chapter and
    # a chamber deck are the same kind of thing. Asserted exactly rather than as
    # a superset so a stray file in here is a failure and not a shrug.
    assert deck_module.deck_ids() == sorted([*DAY_FILES, "thorn_labyrinth"])
    for name in DAY_FILES:
        loaded = deck_module.load_deck(name)
        assert loaded is not None, name
        assert loaded.id == name
        assert loaded.required, f"{name} has no spine"


def test_no_beat_survives_the_bounder_changed(garden: GameState) -> None:
    """
    Nothing authored is clamped, retargeted or dropped on load.

    `bound_beats` records every adjustment it makes. An authored beat that
    produces one is an authored beat whose numbers are not the numbers that will
    run -- a `track` effect silently removed, a band over the story's per-scene
    ceiling, a difficulty band that is not canon. All of those are content bugs
    and all of them are invisible at runtime.
    """
    offenders: list[str] = []
    for name in DAY_FILES:
        loaded = deck_module.load_deck(name)
        assert loaded is not None
        for card in loaded.cards:
            for beat in card.beats:
                if beat.get("adjustments"):
                    offenders.append(f"{name}/{card.id}/{beat['id']}: {beat['adjustments']}")
    assert offenders == []


def test_effects_survive_the_bounder_intact(garden: GameState) -> None:
    """
    Every authored effect is still there after loading.

    A dropped effect leaves no adjustment when the whole outcome block was
    within bounds but one row named a disallowed type, so this counts them
    rather than trusting the adjustment list alone.
    """
    losses: list[str] = []
    for name in DAY_FILES:
        raw = _read(SCENES / f"{name}.yaml")
        loaded = deck_module.load_deck(name)
        assert loaded is not None
        parsed = {card.id: card for card in loaded.cards}
        for raw_card in raw["cards"]:
            card = parsed[str(raw_card["id"])]
            raw_beats = raw_card.get("beats") or []
            assert len(card.beats) == len(raw_beats), f"{name}/{card.id}"
            for index, raw_beat in enumerate(raw_beats):
                for branch in ("on_pass", "on_fail"):
                    authored = (raw_beat.get("gate") or {}).get(branch) or {}
                    kept = (card.beats[index].get("gate") or {}).get(branch) or {}
                    if len(authored.get("effects") or []) != len(kept.get("effects") or []):
                        losses.append(f"{name}/{card.id}/{raw_beat['id']}/{branch}")
    assert losses == []


def test_every_card_declares_its_resolution_contract() -> None:
    """
    Exactly one of `menu` or `sequence`, on every card.

    The engine cannot tell a decision from a sequence of steps, and
    `resolve_card` runs every beat in order. On a menu card that would apply all
    four branches of a choice. The tag is the contract with whatever calls it
    and a card without one is a card that will eventually be resolved wrongly.
    """
    bad: list[str] = []
    for name, doc in _scene_docs().items():
        for card in doc["cards"]:
            tags = set(card.get("tags") or [])
            if len({"menu", "sequence"} & tags) != 1:
                bad.append(f"{name}/{card['id']}: {sorted(tags)}")
    assert bad == []


def test_no_beat_declares_both_a_gate_and_a_band() -> None:
    """
    One beat is one question.

    `deck.py` keeps the gate and drops the band with a warning, so this would
    never crash -- it would quietly discard an authored award.
    """
    bad: list[str] = []
    for name, doc in _authored_docs().items():
        for node in _walk(doc):
            if "gate" in node and "band" in node:
                bad.append(f"{name}/{node.get('id')}")
    assert bad == []


def test_every_day_charges_its_toll() -> None:
    """
    Ten mortal days, once per day, on every chapter.

    The toll is the thesis (00-WORLD-CONCEPT.md:48) and a day that forgets to
    charge it is a day the player got for free. Day 5 charges a second shard
    inside the Clearing of the Lost, which is why this asserts "at least one".
    """
    for name, doc in _scene_docs().items():
        tolls = [
            node
            for node in _walk(doc)
            if node.get("type") == "value"
            and node.get("name") == "time_debt_mortal_days"
            and float(node.get("delta", 0)) >= 10
        ]
        assert tolls, f"{name} never charges a full day toll"


# ---------------------------------------------------------------------------
# 2. Every id resolves
# ---------------------------------------------------------------------------


def test_every_value_named_by_a_scene_is_declared() -> None:
    """A meter the schema does not declare is a write the store refuses."""
    declared = _declared_values()
    unresolved: dict[str, set[str]] = {}
    for name, doc in _authored_docs().items():
        missing = _value_refs(doc) - declared
        if missing:
            unresolved[name] = missing
    assert unresolved == {}


def test_every_item_named_by_a_scene_exists() -> None:
    """
    Both directions: an `item` effect that grants it and a `has_item` that
    gates on it. A gate on an item id that does not exist is a gate that can
    never open, and it fails silently.
    """
    declared = _declared_items()
    unresolved: dict[str, set[str]] = {}
    for name, doc in _authored_docs().items():
        missing = _item_refs(doc) - declared
        if missing:
            unresolved[name] = missing
    assert unresolved == {}


def test_every_location_named_by_a_scene_exists() -> None:
    declared = _declared_locations()
    unresolved: dict[str, set[str]] = {}
    for name, doc in _authored_docs().items():
        missing = _location_refs(doc) - declared
        if missing:
            unresolved[name] = missing
    assert unresolved == {}


def test_every_flag_a_scene_reads_is_written_or_canon() -> None:
    """
    A gate on a flag nobody sets can never open.

    This is the read side. The write side is the next test and both are needed:
    a typo only ever appears on one of them.
    """
    canon = _canon_flags()
    docs = _authored_docs()
    written: set[str] = set()
    for doc in docs.values():
        written |= _flags_written(doc)
    for doc in (_read(RULES / "clocks.yaml"), _read(RULES / "threads.yaml")):
        written |= _flags_written(doc)
    for path in _side_deck_paths():
        written |= _flags_written(_read(path))

    unresolved: dict[str, set[str]] = {}
    for name, doc in docs.items():
        missing = {
            flag
            for flag in _flags_read(doc)
            if flag not in canon and flag not in written and not _engine_owned(flag)
        }
        if missing:
            unresolved[name] = missing
    assert unresolved == {}


def test_every_flag_a_scene_writes_is_canon_or_read() -> None:
    """
    A write-only flag outside the design's vocabulary is a typo or dead weight.

    Canon covers the design's own list and the enum spellings. Anything else has
    to be READ by something -- an ending gate, a clock, a thread cutter, a
    later day -- or it is a fact nobody will ever ask about.
    """
    canon = _canon_flags()
    docs = _authored_docs()
    read: set[str] = set()
    for doc in docs.values():
        read |= _flags_read(doc)
    for path in [RULES / "clocks.yaml", RULES / "threads.yaml", *_side_deck_paths()]:
        read |= _flags_read(_read(path))

    orphans: dict[str, set[str]] = {}
    for name, doc in docs.items():
        missing = {
            flag
            for flag in _flags_written(doc)
            if flag not in canon and flag not in read and not _engine_owned(flag)
        }
        if missing:
            orphans[name] = missing
    assert orphans == {}


def test_every_condition_in_every_scene_evaluates(garden: GameState) -> None:
    """
    No unknown predicates.

    `evaluate_condition` treats an unknown predicate as unmet and logs it, so a
    misspelled `has_iteem:` produces a gate that is shut forever and no error.
    Running every authored condition against a blank state proves only that the
    grammar recognises them -- which is the whole failure mode.
    """
    from engine.game import quests

    known = set(quests.predicate_names())
    groups = {"all", "any", "none"}
    annotations = {"id"}
    unknown: set[str] = set()

    def scan(node: Any) -> None:
        """
        Walk CLAUSES, not arguments.

        `{value: {name: favor, min: 70}}` is one clause whose predicate is
        `value`; `name` and `min` belong to that predicate's own vocabulary and
        are not predicate names. Recursing into them would report every
        argument key as unknown, which is how a check like this ends up being
        deleted for being noisy.
        """
        if isinstance(node, list):
            for entry in node:
                scan(entry)
            return
        if not isinstance(node, dict):
            return
        for key, value in node.items():
            if key in groups:
                scan(value)
            elif key not in annotations and key not in known:
                unknown.add(key)

    for doc in _authored_docs().values():
        for node in _walk(doc):
            if isinstance(node.get("when"), (dict, list)):
                scan(node["when"])
    assert unknown == set()


# ---------------------------------------------------------------------------
# 2b. Every pressure clock keeps its promise
# ---------------------------------------------------------------------------


def _pressure_clock_ids(schema_doc: Any, docs: list[Any]) -> set[str]:
    """
    Every id a story treats as a pressure clock, derived from its own files.

    Two sources, and the union is the point:

      1. the `clocks:` block of its state.yaml -- declaring a value there IS
         the claim that it forces a scene at its ceiling;
      2. every `{clock: {name: ...}}` predicate anywhere in its content -- a
         gate written in the clock grammar is content asserting the same claim.

    A helper over parsed documents rather than over this story's paths, so the
    check can be lifted verbatim when every story grows one.
    """
    out = set(schema_doc.get("clocks") or {})
    for doc in docs:
        for node in _walk(doc):
            clock = node.get("clock")
            if isinstance(clock, dict):
                name = clock.get("name") or clock.get("clock")
                if name:
                    out.add(str(name))
    return out


def _every_garden_doc() -> list[Any]:
    """The ten days, the rules, the roster, the tables, the side decks."""
    return [
        *_authored_docs().values(),
        _read(RULES / "clocks.yaml"),
        _read(RULES / "threads.yaml"),
        _read(GARDEN / "agents.yaml"),
        *(_read(path) for path in _side_deck_paths()),
        *(_read(path) for path in sorted((GARDEN / "data" / "tables").glob("*.yaml"))),
    ]


def test_every_pressure_clock_has_a_beat_table() -> None:
    """
    state.yaml's clocks block promises "At 5 the story stops asking and takes a
    scene -- see clocks.yaml". A clock declared or gated but absent from
    clocks.yaml keeps that promise nowhere: the store accepts every write, every
    `{clock: ...}` gate answers, and the ceiling is mute -- which is exactly how
    `sophia_break` shipped, wound in seven decks and never firing a scene.
    """
    used = _pressure_clock_ids(_read(GARDEN / "state.yaml"), _every_garden_doc())
    table = set(_read(RULES / "clocks.yaml").get("clocks") or {})
    assert used <= table, f"clocks with no beat table: {sorted(used - table)}"


def test_the_beat_table_only_names_declared_clocks() -> None:
    """
    The reverse direction. `clocks.value_of` reads an undeclared name as 0.0
    forever, so a beat table over one is a setpiece that can never fire, with
    no error anywhere -- the same silence, from the other side.
    """
    declared = set(_read(GARDEN / "state.yaml").get("clocks") or {})
    table = set(_read(RULES / "clocks.yaml").get("clocks") or {})
    assert table <= declared, f"beat tables over undeclared clocks: {sorted(table - declared)}"


def test_her_patience_filling_forces_the_unmasking(garden: GameState) -> None:
    """
    The `sophia_break` promise, kept through the real resolver: at its ceiling
    the clock owes `sophia_unmasked`, sets the durable flag, and the Day 8 card
    that answers the scene actually opens on it.
    """
    from engine.game import clocks

    effects.apply_effect(garden, {"type": "value", "name": "sophia_break", "set": 5})
    clocks.resolve(garden)

    assert "sophia_unmasked" in clocks.forced_scenes(garden)
    assert garden.flags.get("sophia_mask_slipped") is True

    card = next(
        c
        for c in deck_module.load_deck("day_08_mirrors").cards
        if c.id == "D8_06b_sophia_unmasked"
    )
    result = deck_module.resolve_beat(garden, card.beats[0], by="test")
    assert result.passed is True

    # Soothing her afterwards eases the clock but cannot un-force the scene:
    # the card gates on the flag, not the number, and that is deliberate.
    clocks.advance(garden, "sophia_break", -1, why="soothed")
    assert "sophia_unmasked" in clocks.forced_scenes(garden)


# ---------------------------------------------------------------------------
# 3. Ending modules
# ---------------------------------------------------------------------------


def test_the_table_declares_all_twenty_three_endings(garden: GameState) -> None:
    """08-ENDINGS-AND-PROGRESSION.md declares 23 variants across six classes."""
    declared = endings_module.declared()
    assert len(declared) == 23
    expected = {
        "E1a", "E1b", "E1c", "E1d",
        "E2a", "E2b", "E2c",
        "E3a", "E3b", "E3c",
        "E4a", "E4b", "E4c", "E4d", "E4e",
        "E5a", "E5b", "E5c",
        "E6a", "E6b", "E6c", "E6d", "E6e",
    }
    assert set(declared) == expected


def test_every_ending_has_speak_act_and_seal(garden: GameState) -> None:
    """
    DAY-09-FINALE.md:102 -- each module is three beats, in that order.

    Read from the raw table, because `declared()` builds its flattened view from
    a fixed key list and drops `beats:`. That is the NOT WIRED note at the top
    of endings.yaml, asserted rather than trusted.
    """
    rules = endings_module.load_rules()
    missing: list[str] = []
    for body in (rules.get("classes") or {}).values():
        for variant_id, variant in (body.get("variants") or {}).items():
            beats = variant.get("beats") or []
            if len(beats) != 3:
                missing.append(f"{variant_id}: {len(beats)} beats")
                continue
            suffixes = [str(b.get("id", "")).rsplit("_", 1)[-1] for b in beats]
            if suffixes != ["speak", "act", "seal"]:
                missing.append(f"{variant_id}: {suffixes}")
    assert missing == []


def test_every_ending_beat_resolves_through_the_deck_engine(garden: GameState) -> None:
    """
    The ending modules are ordinary beats in the shared grammar.

    Resolving all 69 of them against one state is not a playthrough -- it is a
    proof that none of them raises, and that every effect they carry is a kind
    the dispatcher implements against a value this story declares.
    """
    rules = endings_module.load_rules()
    for body in (rules.get("classes") or {}).values():
        for variant_id, variant in (body.get("variants") or {}).items():
            for beat in variant.get("beats") or []:
                result = deck_module.resolve_beat(garden, beat, by="test")
                assert result.beat_id, variant_id
                for receipt in result.effects:
                    assert not str(receipt.get("type", "")).startswith("unknown"), (
                        f"{variant_id}/{beat.get('id')}: {receipt}"
                    )


def test_the_existing_gates_still_answer_the_way_they_did(garden: GameState) -> None:
    """
    Adding beats and three E6 variants changed no gate.

    The blank-state answer is the one tests/test_structural_systems.py asserts,
    and it is the property most easily broken by adding an ending with a gate
    that accidentally passes on an empty save.
    """
    report = endings_module.eligible(garden)
    assert report.eligible == ["E4e"]
    assert report.forced is True
    assert len(report.scores) == 23


def test_the_new_e6_variants_are_reachable(garden: GameState) -> None:
    """
    An ending nothing can reach is worse than one that is not declared.

    E6b, E6d and E6e were added with this content; each is gated on a flag one
    of the day chapters actually writes.
    """
    from engine.game import effects

    for flags, ending_id in (
        ({"met_lior": True, "false_self_kissed": True}, "E6b"),
        ({"market_true_debt": True}, "E6d"),
        ({"mara_pact": True}, "E6e"),
    ):
        state = GameState(rng_seed=7)
        for flag, value in flags.items():
            effects.apply_effect(state, {"type": "flag", "flag": flag, "value": value})
        assert ending_id in endings_module.eligible(state).eligible


# ---------------------------------------------------------------------------
# 4. Epilogues
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not HAVE_DESIGN, reason="Design_files/ is local-only; see .gitignore")
def test_the_epilogue_index_matches_the_design_json() -> None:
    """
    The transcription lost nothing.

    Same ids in the same order, same titles, same gallery keys. The gallery key
    is checked specifically because it is not the ending id and the finale
    unlocks art by it -- DAY-09-FINALE.md:351.

    THE ONLY SKIPPABLE TEST IN THIS FILE, and it is skippable because it checks
    PROVENANCE rather than correctness: it compares the shipped YAML to the
    authored JSON it was transcribed from, and that JSON is deliberately not in
    the repository. On a checkout without it there is nothing to compare to, and
    a check with no second opinion is not a check.

    What it guards is covered without the source by tests that read only shipped
    files -- `test_every_declared_ending_has_an_epilogue` holds the index, the
    prose and `endings.declared()` to the same twenty-three ids, and
    `test_epilogue_echo_speakers_are_people_this_story_has` holds the speakers to
    the canon roster. What is lost here is only the ability to say the
    transcription is faithful to a document nobody else has.
    """
    index = _read(EPILOGUES / "epilogue_index.yaml")
    with (DESIGN / "epilogues" / "epilogue-index.json").open(encoding="utf-8") as handle:
        source = json.load(handle)

    mine = {row["id"]: row for row in index["endings"]}
    theirs = {row["id"]: row for row in source["endings"]}
    assert [r["id"] for r in index["endings"]] == [r["id"] for r in source["endings"]]
    for ending_id, row in theirs.items():
        assert mine[ending_id]["title"] == row["title"], ending_id
        assert mine[ending_id]["gallery_key"] == row["gallery_key"], ending_id
        assert mine[ending_id]["class"] == row["class"], ending_id


def test_forty_six_epilogue_cards_landed() -> None:
    """Twenty-three endings, a mortal card and a Garden card each."""
    cards = _read(EPILOGUES / "epilogue_cards.yaml")["cards"]
    assert len(cards) == 23
    mortal = [k for k, v in cards.items() if (v.get("card_m") or "").strip()]
    garden = [k for k, v in cards.items() if (v.get("card_g") or "").strip()]
    assert len(mortal) == 23
    assert len(garden) == 23
    assert len(mortal) + len(garden) == 46


def test_every_declared_ending_has_an_epilogue(garden: GameState) -> None:
    """
    The set the engine can resolve to and the set the renderer can render are
    the same set. An ending with no card is a finale that ends on a blank page.
    """
    cards = _read(EPILOGUES / "epilogue_cards.yaml")["cards"]
    index = {row["id"] for row in _read(EPILOGUES / "epilogue_index.yaml")["endings"]}
    declared = set(endings_module.declared())
    assert declared == set(cards)
    assert declared == index


def test_epilogue_echo_speakers_are_people_this_story_has() -> None:
    """
    An echo attributed to somebody who does not exist is a voice the agents
    cannot cast. The nine names are the state dictionary's relationship roster.
    """
    roster = set((_dictionary().get("relationships") or {}).get("npcs") or [])
    cards = _read(EPILOGUES / "epilogue_cards.yaml")["cards"]
    index = {row["id"]: row for row in _read(EPILOGUES / "epilogue_index.yaml")["endings"]}

    for ending_id, card in cards.items():
        speakers = [str(e["speaker"]) for e in (card.get("echoes") or [])]
        for speaker in speakers:
            assert speaker in roster, f"{ending_id}: {speaker}"
        # The index and the prose agree about who speaks, including the two
        # endings with two echoes and the one with none.
        assert speakers == [str(s) for s in index[ending_id]["echo_speaker"]], ending_id


# ---------------------------------------------------------------------------
# The epilogue loader
#
# The tests above read the files directly, which is right for asserting what was
# authored -- but for a year these files were authored and loaded by nothing.
# These drive engine/game/epilogue.py instead, so "23 cards exist" and "23 cards
# are reachable" stop being the same claim.
# ---------------------------------------------------------------------------


def test_the_loader_reaches_every_authored_card(garden: GameState) -> None:
    """Both files, joined, through `paths.epilogues`."""
    rows = epilogue_module.declared()
    assert set(rows) == set(endings_module.declared())
    for ending_id, row in rows.items():
        # Structure from the index, prose from the cards file -- the join is the
        # whole point of `declared()`, so assert both halves landed.
        assert row.get("gallery_key"), ending_id
        assert (row.get("card_m") or "").strip(), ending_id
        assert (row.get("card_g") or "").strip(), ending_id


def test_the_time_line_reports_the_debt_the_state_holds(garden: GameState) -> None:
    """
    Not `days * 10`.

    A run that lost the labyrinth owes extra shards, and recomputing the toll
    from the day index would quietly forgive them. The declared value is
    authoritative and the sentence has to say what it says.
    """
    effects.apply_effect(garden, {"type": "value", "name": "time_debt_mortal_days", "set": 137})
    assert "137" in epilogue_module.time_line(garden)


def test_the_hollow_clause_lands_on_a_winning_ending(garden: GameState) -> None:
    """
    E1a is the good ending. Past the threshold it still says what it cost.

    "Cost is the thesis" -- the clause is gated on the debt and NOT on the
    ending class, so the one place it would be tempting to suppress is exactly
    the place this asserts it appears.
    """
    index = _read(EPILOGUES / "epilogue_index.yaml")
    threshold = index["hollow_clause_if_time_debt_gte"]
    clause = index["hollow_clause_text"].strip()

    effects.apply_effect(
        garden, {"type": "value", "name": "time_debt_mortal_days", "set": threshold - 1}
    )
    assert clause not in epilogue_module.render(garden, "E1a").card_m

    effects.apply_effect(
        garden, {"type": "value", "name": "time_debt_mortal_days", "set": threshold}
    )
    assert clause in epilogue_module.render(garden, "E1a").card_m


def test_an_undeclared_ending_renders_nothing(garden: GameState) -> None:
    """None, not a blank card -- a caller has to be able to tell them apart."""
    assert epilogue_module.render(garden, "E9z") is None


def test_the_epilogue_waits_for_the_lock_and_then_for_the_module(
    garden: GameState,
) -> None:
    """
    Two gates, and both matter.

    NOT `resolve()`: it always answers, because it falls forward rather than
    softlock a finale, so a turn loop asking it "is there an ending yet?" is
    told yes on turn one.

    NOT the lock alone either: the lock is the DECISION and the module is the
    SCENE. Returning the cards on the locking turn swaps the screen out from
    under Speak, Act and Seal -- the last three beats of the story, and the ones
    that write the gallery key and the New Game+ seed.
    """
    ending_id = endings_module.fail_forward_id()

    assert endings_module.resolve(garden), "resolve always answers; that is why it is not a gate"
    assert epilogue_module.for_state(garden) is None

    endings_module.lock(garden, ending_id)
    assert epilogue_module.for_state(garden) is None, "shown before the module played"

    endings_module.run_module(garden)
    rendered = epilogue_module.for_state(garden)
    assert rendered is not None
    assert rendered.ending_id == ending_id
    assert rendered.card_m and rendered.card_g and rendered.time_line


def test_the_finales_own_beat_ends_the_run(garden: GameState) -> None:
    """
    The whole chain, driven from the authored file rather than from a call.

    F3_point_of_no_return declares `{type: ending_lock}` with no id; the effect
    dispatcher resolves what the run earned, `endings.lock` refuses anything
    that cannot complete, and `epilogue.for_state` turns the locked id into the
    two cards the turn payload carries. Every one of those existed and none of
    them were connected: the finale named `endings.lock` in prose and no Python
    anywhere called it, so the last screen of the story was unreachable by
    playing.
    """
    card = next(
        c
        for c in deck_module.load_deck("day_09_finale").cards
        if c.id == "F3_point_of_no_return"
    )
    assert epilogue_module.for_state(garden) is None

    deck_module.resolve_card(garden, card, chosen="confirm_the_ending")

    locked_id = endings_module.locked(garden)
    assert locked_id != endings_module.NONE_ID, "the finale's own beat did not lock"

    # NOT over yet. The lock is the decision; Speak/Act/Seal is the scene, and
    # showing the cards here would swap the screen out from under the last three
    # beats of the story.
    assert epilogue_module.for_state(garden) is None

    module = next(
        c
        for c in deck_module.load_deck("day_09_finale").cards
        if c.id == "F4_ending_module"
    )
    deck_module.resolve_card(garden, module, chosen="run_the_locked_module")

    rendered = epilogue_module.for_state(garden)
    assert rendered is not None, "the module played and the epilogue still did not arrive"
    assert rendered.ending_id == locked_id
    assert rendered.card_m and rendered.card_g

    # Both cards refuse a replay, so a reconnect or a re-resolved turn cannot
    # rewrite the ending or award Seal's flags twice.
    deck_module.resolve_card(garden, card, chosen="confirm_the_ending")
    deck_module.resolve_card(garden, module, chosen="run_the_locked_module")
    assert endings_module.locked(garden) == locked_id
    assert endings_module.module_ran(garden) == locked_id


def test_the_module_plays_the_endings_own_three_beats(garden: GameState) -> None:
    """
    Speak, then Act, then Seal -- the authored beats, in authored order.

    Sixty-nine beats across twenty-three endings were reachable and never run:
    `F4_ending_module` described the call in prose and no effect invoked it, so
    a finale went from the point of no return straight to the cards. Seal is
    where `ending_gallery_unlocked` and `ng_plus_seed_written` are set, so
    skipping it silently cost the gallery and the New Game+ seed too.
    """
    # The fail-forward, because it is the one ending eligible from a blank
    # state -- `lock` refuses anything that cannot complete, which is the point
    # of it, so naming a richer ending here would test the refusal instead.
    ending_id = endings_module.fail_forward_id()
    endings_module.lock(garden, ending_id)
    assert endings_module.module_ran(garden) == endings_module.NONE_ID

    receipt = endings_module.run_module(garden)
    assert receipt["ok"] is True
    assert receipt["beats"] == [f"{ending_id}_speak", f"{ending_id}_act", f"{ending_id}_seal"]
    # Seal's writes landed, which is the half a skipped module was costing.
    assert garden.flags.get("ending_gallery_unlocked") is True
    assert garden.flags.get("ng_plus_seed_written") is True

    replay = endings_module.run_module(garden)
    assert replay["ok"] is False


def test_the_module_refuses_to_run_before_an_ending_is_locked(garden: GameState) -> None:
    """
    Which three beats these are is decided by the lock.

    Running off `intent` would play a finale the player has not committed to,
    and Day 8 exists precisely so an intent can be sworn and then changed.
    """
    endings_module.set_intent(garden, endings_module.fail_forward_id())
    receipt = endings_module.run_module(garden)
    assert receipt["ok"] is False
    assert endings_module.module_ran(garden) == endings_module.NONE_ID


def test_every_ending_module_is_speak_act_seal(garden: GameState) -> None:
    """
    All twenty-three, through the bounder, with nothing dropped.

    Three beats each in that order is the design's own contract
    (`DAY-09-FINALE.md:102`), and a module that loses one is a finale missing
    its middle with no error anywhere.
    """
    wrong: list[str] = []
    for ending_id in endings_module.declared():
        beats = endings_module.module_beats(ending_id)
        suffixes = [str(b["id"]).rsplit("_", 1)[-1] for b in beats]
        if suffixes != ["speak", "act", "seal"]:
            wrong.append(f"{ending_id}: {suffixes}")
    assert wrong == []


def test_a_locked_ending_always_has_a_card_to_show(garden: GameState) -> None:
    """
    Every ending the engine can lock renders.

    The finale commits before this is asked, so an ending with no authored card
    is a run that reaches its last screen and is shown nothing. Checked over all
    twenty-three rather than the reachable ones, because "reachable" is the
    thing most likely to be wrong.
    """
    blank = [
        ending_id
        for ending_id in endings_module.declared()
        if epilogue_module.render(garden, ending_id) is None
    ]
    assert blank == []


def test_epilogues_are_inert_for_a_story_that_declares_none() -> None:
    """
    The Clockwork Dark ships no epilogues, and adding this module cost it
    nothing. Same contract as clocks, threads and decks.
    """
    assert epilogue_module.load_index() == {}
    assert epilogue_module.declared() == {}
    assert epilogue_module.render(GameState(), "E1a") is None
    # And the turn payload never grows an `ending` key for it, on any turn.
    assert epilogue_module.for_state(GameState()) is None
